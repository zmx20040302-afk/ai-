"""数据集构建与**强制泄漏检查**（WORKING_PLAN 4.2 / 6.1，风险 R6/R15）。

为什么单独成模块：训练管线的 `grouped_split` 只能在"已经拿到样本表"之后做切分，
而**是否允许用这批数据训练**必须在构建数据集时就判定并把结论写进 `dataset.report`。
本模块负责后者——它是"防泄漏"这条红线的执行点，不是一个可选的便利函数。

核心规则：
1. **按几何族整族切分**：同一几何族的样本不得同时出现在训练集与留出集；
2. **留出集必须含未见族**才算真正检验了跨族泛化；否则必须如实标为
   `cross_family_holdout: false` 并给出降级原因（**不得静默当成有效留出集**）；
3. 缺 `geometry_family` 的样本一律**不得**进入数据集（无法判定归属 = 无法防泄漏）；
4. 数据集冻结后不原地修改，修正通过新版本实现（append-only）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from .store import SOURCE_TYPES, query

# 允许进入数据集的保真度等级
FIDELITIES = ("F0", "F1", "F2", "F3")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def load_groupable_samples(
    conn: Any,
    *,
    fidelity: Sequence[str] | None = None,
    source_types: Sequence[str] | None = None,
    only_succeeded: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """读出可用于数据集的样本，返回 (可用, 被排除并附原因)。

    排除原因 = 无法防泄漏或无法追溯的样本，必须显式列出而不是悄悄丢掉：
    - 缺 `geometry_family`（无法分组）
    - 缺 `source_type` / 非法来源
    - simulation 样本对应的 run 未成功（失败点不得当有效输出）
    """
    sql = [
        "SELECT s.sample_id, s.source_type, s.fidelity, s.run_id, s.design_id, s.inputs, s.outputs,",
        "       d.geometry_family AS geometry_family, r.status AS run_status",
        "FROM sample s",
        "LEFT JOIN design d ON s.design_id = d.design_id",
        "LEFT JOIN run r ON s.run_id = r.run_id",
    ]
    where: list[str] = []
    params: list[Any] = []
    if fidelity:
        where.append(f"s.fidelity IN ({', '.join('?' for _ in fidelity)})")
        params.extend(fidelity)
    if source_types:
        where.append(f"s.source_type IN ({', '.join('?' for _ in source_types)})")
        params.extend(source_types)
    if where:
        sql.append("WHERE " + " AND ".join(where))
    rows = query(conn, " ".join(sql), params, limit=100000)

    usable: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in rows:
        reasons: list[str] = []
        if not row.get("geometry_family"):
            reasons.append("缺 geometry_family：无法做族间切分，无法防泄漏")
        if row.get("source_type") not in SOURCE_TYPES:
            reasons.append(f"来源非法或缺失：{row.get('source_type')!r}")
        if only_succeeded and row.get("source_type") == "simulation" and row.get("run_status") != "succeeded":
            reasons.append(f"simulation 样本的 run 状态为 {row.get('run_status')!r}（失败点不得当有效输出）")
        if reasons:
            excluded.append({"sample_id": row["sample_id"], "reasons": reasons})
        else:
            usable.append(row)
    return usable, excluded


def split_by_family(
    samples: Sequence[dict[str, Any]], *, holdout_frac: float = 0.25, seed: int = 0
) -> dict[str, Any]:
    """按几何族整族切分，并返回**可判定**的泄漏检查报告。

    族数不足以切分时**不假装成功**：返回 `cross_family_holdout: False` 并说明原因，
    调用方据此决定是否仍然训练（训练可以，但不得声称验证了跨族泛化）。
    """
    import random

    by_family: dict[str, list[dict[str, Any]]] = {}
    for row in samples:
        by_family.setdefault(str(row["geometry_family"]), []).append(row)

    families = sorted(by_family)
    rng = random.Random(seed)
    shuffled = list(families)
    rng.shuffle(shuffled)

    report: dict[str, Any] = {
        "n_samples": len(samples),
        "n_families": len(families),
        "families": families,
        "strategy": "grouped_by_family",
        "holdout_frac": holdout_frac,
        "seed": seed,
    }

    if len(families) < 2:
        report.update({
            "cross_family_holdout": False,
            "train_families": families,
            "holdout_families": [],
            "degraded_reason": (
                f"只有 {len(families)} 个几何族，无法把整族分到不同侧："
                f"本数据集**无法检验跨族泛化**，任何指标都只反映族内插值"
            ),
        })
        report["train_sample_ids"] = [r["sample_id"] for r in samples]
        report["holdout_sample_ids"] = []
        report["leak_check_passed"] = True  # 训练/留出交集为空（留出为空集，平凡成立）
        return report

    n_holdout = max(1, int(round(len(families) * holdout_frac)))
    holdout_families = shuffled[:n_holdout]
    train_families = shuffled[n_holdout:]
    if not train_families:  # 极端情况：全部族被划入留出
        train_families, holdout_families = holdout_families[:-1], holdout_families[-1:]

    train_ids = [r["sample_id"] for f in train_families for r in by_family[f]]
    holdout_ids = [r["sample_id"] for f in holdout_families for r in by_family[f]]

    overlap = set(train_families) & set(holdout_families)
    report.update({
        "train_families": sorted(train_families),
        "holdout_families": sorted(holdout_families),
        "train_sample_ids": train_ids,
        "holdout_sample_ids": holdout_ids,
        "leak_check_passed": not overlap,
        "leak_overlap_families": sorted(overlap),
        "cross_family_holdout": True,
        "holdout_is_unseen_family": True,
    })
    if overlap:
        report["degraded_reason"] = f"训练集与留出集共享几何族 {sorted(overlap)}：存在数据泄漏"
    return report


def build_dataset(
    conn: Any,
    *,
    purpose: str = "train",
    fidelity: Sequence[str] | None = None,
    source_types: Sequence[str] | None = None,
    holdout_frac: float = 0.25,
    seed: int = 0,
    note: str | None = None,
    created_by: str | None = None,
    require_cross_family: bool = False,
) -> dict[str, Any]:
    """构建数据集并写入 `dataset` 表，返回数据集卡（含泄漏检查结论）。

    ``require_cross_family=True`` 时，若族数不足以做跨族留出则**直接拒绝**构建——
    用于"必须验证跨族泛化"的场合（如场级求解器放行）。
    """
    if purpose not in ("train", "holdout", "calibration"):
        raise ValueError(f"purpose 必须是 train|holdout|calibration，收到 {purpose!r}")

    usable, excluded = load_groupable_samples(conn, fidelity=fidelity, source_types=source_types)
    if not usable:
        return {
            "dataset_id": None,
            "created": False,
            "reason": "没有可用于数据集构建的样本",
            "excluded": excluded,
        }

    split = split_by_family(usable, holdout_frac=holdout_frac, seed=seed)
    if require_cross_family and not split.get("cross_family_holdout"):
        return {
            "dataset_id": None,
            "created": False,
            "reason": f"要求跨族留出但无法满足：{split.get('degraded_reason')}",
            "split": split,
            "excluded": excluded,
        }

    # 来源构成必须写进报告（红线 4：混用来源必须显式声明）
    source_counts: dict[str, int] = {}
    fidelity_counts: dict[str, int] = {}
    for row in usable:
        source_counts[str(row["source_type"])] = source_counts.get(str(row["source_type"]), 0) + 1
        fidelity_counts[str(row["fidelity"])] = fidelity_counts.get(str(row["fidelity"]), 0) + 1

    dataset_id = f"ds-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    version = datetime.now(timezone.utc).strftime("%Y.%m.%d.%H%M%S")
    report = {
        "dataset_id": dataset_id,
        "version": version,
        "purpose": purpose,
        "split": split,
        "source_counts": source_counts,
        "fidelity_counts": fidelity_counts,
        "excluded_samples": excluded,
        "note": note or "冻结后不原地修改；修正需新建版本（append-only）",
        "created_by": created_by,
        "created_at": _now().isoformat(),
        "warning": (
            "本数据集不含跨族留出：指标只反映族内插值，不得用于声称跨族泛化能力"
            if not split.get("cross_family_holdout") else None
        ),
    }
    filters = {
        "fidelity": list(fidelity) if fidelity else None,
        "source_types": list(source_types) if source_types else None,
        "holdout_frac": holdout_frac,
        "seed": seed,
    }
    conn.execute(
        "INSERT INTO dataset (dataset_id, version, purpose, sample_ids, filters, report, created_by, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            dataset_id,
            version,
            purpose,
            json.dumps(split["train_sample_ids"] + split["holdout_sample_ids"], ensure_ascii=False),
            json.dumps(filters, ensure_ascii=False),
            json.dumps(report, ensure_ascii=False),
            created_by,
            _now(),
        ],
    )
    return {
        "dataset_id": dataset_id,
        "created": True,
        "version": version,
        "report": report,
        "leak_check_passed": split.get("leak_check_passed"),
        "cross_family_holdout": split.get("cross_family_holdout"),
    }
