"""模型层：代理模型训练、不确定度、防泄漏切分与模型注册。

对应 WORKING_PLAN.md 第 4.4 / 6.2 / 6.3 节。P0/P1 阶段的定位是**管线正确**
而非精度：先把「数据→切分→训练→评分卡→模型卡→注册（draft）」跑通并留下证据。

红线（AGENTS.md）：
- 新模型一律以 ``draft`` 状态注册，**绝不自动晋升**（晋升需人工门禁）。
- 数据集划分按几何族分组，禁止同一几何族的点跨训练/测试集。
- 评分卡按输出分量分别报告，不做平均掩盖。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from ..paths import ensure_work_tree, work_root

# 评分卡里「样本量不足」的提示阈值（不阻止训练，但必须显式标注）
MIN_ROWS_FOR_RELIABLE = 100
MIN_ROWS_FOR_TRAINING = 8


@dataclass
class ScoreCard:
    """按输出分量分别给出的误差与不确定度评分卡。"""

    n_train: int
    n_test: int
    outputs: dict[str, dict[str, float | None]]
    interval_coverage_90: float | None
    interval_width_mean: dict[str, float]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_samples(conn: Any, fidelity: Sequence[str] | None = None) -> pd.DataFrame:
    """从元数据库读取样本并展开 JSON 列。

    ``geometry_family`` 取自 ``design`` 表（样本表不重复存储该字段），
    它是防泄漏切分的分组键。

    返回列：sample_id, run_id, design_id, fidelity, source_type, geometry_family
    以及每个输入/输出对应的 ``in_<name>`` / ``out_<name>`` 列。
    """
    sql = (
        "SELECT s.*, d.geometry_family AS geometry_family "
        "FROM sample s LEFT JOIN design d ON s.design_id = d.design_id"
    )
    params: list[Any] = []
    if fidelity:
        placeholders = ", ".join("?" for _ in fidelity)
        sql += f" WHERE s.fidelity IN ({placeholders})"
        params.extend(fidelity)
    rows = conn.execute(sql, params).fetchdf()
    if rows.empty:
        return rows

    records: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        item: dict[str, Any] = {
            "sample_id": row["sample_id"],
            "run_id": row.get("run_id"),
            "design_id": row.get("design_id"),
            "fidelity": row.get("fidelity"),
            "source_type": row.get("source_type"),
            "geometry_family": row.get("geometry_family"),
        }
        for key, prefix in (("inputs", "in_"), ("outputs", "out_")):
            raw = row.get(key)
            payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
            item.update({f"{prefix}{k}": v for k, v in payload.items()})
        records.append(item)
    return pd.DataFrame.from_records(records)


def grouped_split(
    frame: pd.DataFrame,
    group_col: str = "geometry_family",
    test_frac: float = 0.25,
    seed: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """按分组键切分，防止同族几何泄漏到测试集。

    当 ``group_col`` 不存在时退化为随机切分，并在报告里显式记录这一退化
    （不能静默当作分组切分）。
    """
    if frame.empty:
        return frame, frame, {"strategy": "empty", "groups": []}

    rng = np.random.default_rng(seed)
    if group_col in frame.columns and frame[group_col].nunique() > 1:
        groups = sorted(map(str, frame[group_col].dropna().unique()))
        shuffled = list(groups)
        rng.shuffle(shuffled)
        n_test = max(1, int(round(len(shuffled) * test_frac)))
        test_groups = set(shuffled[:n_test])
        mask = frame[group_col].astype(str).isin(test_groups)
        report = {
            "strategy": "grouped",
            "group_column": group_col,
            "n_groups": len(groups),
            "test_groups": sorted(test_groups),
        }
        return frame[~mask].copy(), frame[mask].copy(), report

    shuffled_idx = rng.permutation(len(frame))
    n_test = max(1, int(round(len(frame) * test_frac)))
    test_idx = set(shuffled_idx[:n_test].tolist())
    mask = frame.index.isin(test_idx)
    # 说清到底是哪一种退化：缺列 vs 只有一族。两者风险不同，不能混为一句话。
    if group_col not in frame.columns:
        reason = f"缺少分组列 {group_col!r}"
    else:
        distinct = frame[group_col].dropna().nunique()
        reason = (
            f"{group_col!r} 只有 {distinct} 个取值：本批数据全部同族，"
            f"无法用族间切分来检验跨族泛化"
        )
    report = {
        "strategy": "random_degraded",
        "warning": f"{reason}，已退化为随机切分（同族样本会同时出现在训练与测试集，指标偏乐观）",
    }
    return frame[~mask].copy(), frame[mask].copy(), report


class SurrogateEnsemble:
    """标准化 + MLP 深度集成：均值作预测，集成分歧作不确定度。

    6 GB 显存约束下刻意使用 CPU 与较小网络；这是 P0/P1 的基线模型，
    回归质量取决于数据量，管线正确性优先。
    """

    def __init__(self, n_members: int = 5, hidden: tuple[int, ...] = (64, 64), seed: int = 0):
        self.n_members = n_members
        self.hidden = hidden
        self.seed = seed
        self.x_scaler = StandardScaler()
        self.y_scaler = StandardScaler()
        self.members: list[MLPRegressor] = []
        self.input_cols: list[str] = []
        self.output_cols: list[str] = []
        self._x_mean: np.ndarray | None = None
        self._x_cov_inv: np.ndarray | None = None

    # ---- 训练与预测 ----
    def fit(self, frame: pd.DataFrame, input_cols: Sequence[str], output_cols: Sequence[str]) -> "SurrogateEnsemble":
        self.input_cols = list(input_cols)
        self.output_cols = list(output_cols)
        x = frame[self.input_cols].to_numpy(dtype=float)
        y = frame[self.output_cols].to_numpy(dtype=float)
        x_scaled = self.x_scaler.fit_transform(x)
        y_scaled = self.y_scaler.fit_transform(y)

        # OOD 检测用的输入分布统计
        self._x_mean = x_scaled.mean(axis=0)
        cov = np.cov(x_scaled, rowvar=False)
        cov = np.atleast_2d(cov) + np.eye(cov.shape[0] if cov.ndim == 2 else 1) * 1e-6
        self._x_cov_inv = np.linalg.pinv(cov)

        self.members = []
        # 单输出时 sklearn 期望 1D 目标，统一在这里拉平，避免列向量警告与后续维度错位
        y_fit = y_scaled.ravel() if y_scaled.ndim == 2 and y_scaled.shape[1] == 1 else y_scaled
        for i in range(self.n_members):
            model = MLPRegressor(
                hidden_layer_sizes=self.hidden,
                max_iter=2000,
                early_stopping=len(frame) >= 50,
                n_iter_no_change=25,
                random_state=self.seed + i,
            )
            model.fit(x_scaled, y_fit)
            self.members.append(model)
        return self

    def predict(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """返回 (均值, 标准差)，形状均为 (n_samples, n_outputs)。"""
        if not self.members:
            raise RuntimeError("模型尚未训练")
        x = frame[self.input_cols].to_numpy(dtype=float)
        x_scaled = self.x_scaler.transform(x)
        stacked: list[np.ndarray] = []
        for member in self.members:
            raw = np.asarray(member.predict(x_scaled), dtype=float)
            if raw.ndim == 1:  # 单输出模型返回 1D
                raw = raw.reshape(-1, 1)
            stacked.append(self.y_scaler.inverse_transform(raw))
        stack = np.stack(stacked, axis=0)
        return stack.mean(axis=0), stack.std(axis=0, ddof=0)

    def ood_score(self, frame: pd.DataFrame) -> np.ndarray:
        """输入的马氏距离（越大越可能超出适用范围）。"""
        if self._x_mean is None or self._x_cov_inv is None:
            raise RuntimeError("模型尚未训练")
        x = self.x_scaler.transform(frame[self.input_cols].to_numpy(dtype=float))
        delta = x - self._x_mean
        return np.sqrt(np.einsum("ij,jk,ik->i", delta, self._x_cov_inv, delta))


def display_name(column: str) -> str:
    """去掉 ``in_`` / ``out_`` 前缀，得到面向人的物理量名。"""
    for prefix in ("in_", "out_"):
        if column.startswith(prefix):
            return column[len(prefix):]
    return column


def score(
    model: SurrogateEnsemble,
    train: pd.DataFrame,
    test: pd.DataFrame,
) -> ScoreCard:
    """在测试集上给出分输出量的评分卡（含 90% 区间覆盖率）。"""
    warnings: list[str] = []
    if len(train) < MIN_ROWS_FOR_TRAINING:
        warnings.append(f"训练样本仅 {len(train)} 条，低于最小可用量 {MIN_ROWS_FOR_TRAINING}")
    elif len(train) < MIN_ROWS_FOR_RELIABLE:
        warnings.append(
            f"训练样本 {len(train)} 条，低于可靠阈值 {MIN_ROWS_FOR_RELIABLE}；指标仅供管线验证，不可用于工程判断"
        )
    if test.empty:
        warnings.append("测试集为空，无法给出泛化指标")

    out: dict[str, dict[str, float | None]] = {}
    widths: dict[str, float] = {}
    covered: list[np.ndarray] = []

    if not test.empty:
        mean, std = model.predict(test)
        truth = test[model.output_cols].to_numpy(dtype=float)
        for idx, name in enumerate(model.output_cols):
            y_true = truth[:, idx]
            y_pred = mean[:, idx]
            scale = float(np.mean(np.abs(y_true)))
            rel_rmse = (
                float(root_mean_squared_error(y_true, y_pred) / scale) if scale > 0 else None
            )
            zero_var = bool(np.allclose(y_true, y_true[0]))
            label = display_name(name)
            out[label] = {
                "rmse": float(root_mean_squared_error(y_true, y_pred)),
                "mae": float(mean_absolute_error(y_true, y_pred)),
                "r2": float(r2_score(y_true, y_pred)) if len(y_true) > 1 and not zero_var else None,
                "relative_rmse": rel_rmse,
            }
            if zero_var:
                warnings.append(f"输出 {label} 在测试集上方差为零，R² 与相对误差无意义")
            width = 1.6449 * std[:, idx] * 2  # 约 90% 区间宽度
            widths[label] = float(np.mean(width))
            covered.append(np.abs(truth[:, idx] - mean[:, idx]) <= 1.6449 * std[:, idx])

    coverage = float(np.mean(np.concatenate(covered))) if covered else None
    if coverage is not None and not 0.85 <= coverage <= 0.95:
        warnings.append(
            f"90% 区间实际覆盖率 {coverage:.3f} 偏离目标 [0.85, 0.95]，不确定度尚未校准"
        )

    return ScoreCard(
        n_train=len(train),
        n_test=len(test),
        outputs=out,
        interval_coverage_90=coverage,
        interval_width_mean=widths,
        warnings=warnings,
    )


def save_model(model: SurrogateEnsemble, model_id: str) -> Path:
    """把模型与元信息写入 ``work/models/<model_id>/``。"""
    ensure_work_tree()
    target = work_root() / "models" / model_id
    target.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, target / "model.joblib")
    (target / "meta.json").write_text(
        json.dumps(
            {
                "model_id": model_id,
                "input_cols": model.input_cols,
                "output_cols": model.output_cols,
                "n_members": model.n_members,
                "hidden": list(model.hidden),
                "seed": model.seed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return target


def write_model_card(
    model_id: str,
    card: ScoreCard,
    split_report: dict[str, Any],
    extras: dict[str, Any] | None = None,
) -> Path:
    """写模型卡（人类可读 JSON），含状态、适用范围与警告。"""
    ensure_work_tree()
    cards_dir = work_root() / "models" / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_id": model_id,
        "state": "draft",  # 红线：绝不自动晋升
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scorecard": card.to_dict(),
        "split": split_report,
        "extras": extras or {},
        "disclaimer": "draft 状态模型不得用于工程判断；晋升需人工门禁（见 WORKING_PLAN.md 6.3）",
    }
    path = cards_dir / f"{model_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def register_model(
    conn: Any,
    model_id: str,
    card: ScoreCard,
    card_path: Path,
    algorithm: str,
    uq_method: str,
    dataset_id: str | None = None,
    hyperparams: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
) -> str:
    """把模型登记进 ``model`` 表，状态固定为 ``draft``。"""
    version = datetime.now(timezone.utc).strftime("%Y%m%d.%H%M%S")
    conn.execute(
        """
        INSERT INTO model (model_id, version, dataset_id, algorithm, hyperparams,
                           metrics, uq_method, scope, state, card_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            model_id,
            version,
            dataset_id,
            algorithm,
            json.dumps(hyperparams or {}, ensure_ascii=False),
            json.dumps(card.to_dict(), ensure_ascii=False),
            uq_method,
            json.dumps(scope or {}, ensure_ascii=False),
            "draft",
            str(card_path),
            datetime.now(timezone.utc).replace(tzinfo=None),
        ],
    )
    return model_id


def new_model_id(prefix: str = "mdl") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"


def discover_columns(frame: pd.DataFrame) -> tuple[list[str], list[str]]:
    """从展开后的样本表推断输入/输出列。"""
    inputs = sorted(c for c in frame.columns if c.startswith("in_"))
    outputs = sorted(c for c in frame.columns if c.startswith("out_"))
    return inputs, outputs


def drop_constant_columns(
    frame: pd.DataFrame, columns: Sequence[str], tolerance: float = 0.0
) -> tuple[list[str], list[str]]:
    """剔除在数据集内**恒定**的列，返回 (保留, 剔除)。

    为什么必须剔除：任务合同里固定不扫的参数（Lx、T0、网格设置等）在本批数据里方差为零，
    标准化会除以零并产出 NaN/Inf —— 模型表面训得出来、实际不可用。
    剔除是物理上正确的处理（它们不是这批数据的自变量），但**必须如实记录剔除了哪些列**，
    否则模型卡会让人误以为模型"考虑了"这些参数。
    """
    import numpy as np

    kept: list[str] = []
    dropped: list[str] = []
    for name in columns:
        values = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        if finite.size == 0 or float(finite.max() - finite.min()) <= tolerance:
            dropped.append(name)
        else:
            kept.append(name)
    return kept, dropped
