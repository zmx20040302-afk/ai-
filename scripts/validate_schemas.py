"""契约机器校验入口（校验对象 = 仓库根的 ``schemas/``）。

落点依据：``AGENTS.md`` §5「可执行脚本 → ``scripts\\``」。
本文件 2026-09-14 由 ``schemas/validate_examples.py`` **移动**至此（内容等价，仅改路径推导）；
``schemas/`` 下只保留 schema / 样例 / 人读层 README。

用法（在仓库根执行）::

    work\\.venv\\Scripts\\python.exe scripts\\validate_schemas.py
    work\\.venv\\Scripts\\python.exe scripts\\validate_schemas.py --verbose
    work\\.venv\\Scripts\\python.exe scripts\\validate_schemas.py --json

路径推导：``SCHEMAS = <repo_root>/schemas``，其中 ``<repo_root> = Path(__file__).parents[1]``
（本文件位于 ``<repo_root>/scripts/``）。**不要**改成 ``Path(__file__).parent``——
那会在移动/复制本文件后静默去 ``scripts/`` 下找 schema 并全部报「文件缺失」。

行为（fail-closed）:
1. ``schemas/examples/valid/*``  必须 **schema 通过且语义检查通过**；否则本脚本以退出码 2 失败。
2. ``schemas/examples/invalid/*`` 必须**被拒**，且拒绝理由要与 ``manifest.json`` 里声明的
   (stage, keyword, path_contains) 或 (stage, check) 一致；否则同样失败。
3. 任何期望不成立、样例缺失、schema 缺失 ⇒ 退出码 2（宁可报错，不做「静默跳过」）。

语义检查覆盖 JSON Schema 表达不了的部分：跨文件引用解析、族间泄漏（数组交集）、
单位换算自洽、进度/任务合同与 device_spec 的交叉核对等。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
EXAMPLES = SCHEMAS / "examples"


# --------------------------------------------------------------------------------------
# 加载
# --------------------------------------------------------------------------------------
def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_schemas() -> dict[str, dict]:
    return {p.name: load_json(p) for p in sorted(SCHEMAS.glob("*.schema.json"))}


def load_records() -> dict[str, dict[str, dict]]:
    """按 kind 建索引：{kind: {id: record}}，供跨文件语义检查解析引用。"""
    index: dict[str, dict[str, dict]] = {
        "sample": {}, "dataset": {}, "evidence": {}, "experiment": {},
        "feedback": {}, "run": {}, "device_spec": {}, "task_spec": {},
        # solver_spec 目前**不被别的样例交叉引用**（AI 求解器层与样本层靠 stamps 衔接，
        # 那条链路由 src/memsharness/solver.py 的用例守着）⇒ 这里留一个空桶即可
        "solver_spec": {},
    }
    key_of = {
        "sample": "sample_id", "dataset": "dataset_id", "evidence": "evidence_id",
        "experiment": "experiment_id", "feedback": "feedback_id", "run": "run_id",
        "device_spec": "spec_id", "task_spec": "task_id", "solver_spec": "solver_id",
    }
    for entry in load_json(EXAMPLES / "manifest.json")["valid"]:
        rec = load_json(EXAMPLES / entry["file"])
        key = key_of[entry["kind"]]
        if key in rec and isinstance(rec[key], str):
            index[entry["kind"]][rec[key]] = rec
    return index


# --------------------------------------------------------------------------------------
# 语义检查（schema 表达不了的规则）
# --------------------------------------------------------------------------------------
def _pending_blob(rec: dict) -> str:
    return " | ".join(str(x) for x in (rec.get("pending_human") or []))


def _placeholder_paths(rec: dict) -> list[str]:
    return [str(p.get("path", "")) for p in (rec.get("placeholders") or [])]


def _gap_blob(rec: dict) -> str:
    return " | ".join(str(x) for x in (rec.get("provenance_gaps") or []))


def s1_dataset_no_family_leak(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "dataset":
        return []
    split = rec.get("split") or {}
    train = set(split.get("train_families") or [])
    holdout = set(split.get("holdout_families") or [])
    overlap = sorted(train & holdout)
    problems = []
    if overlap:
        problems.append(f"训练集与留出集共享几何族 {overlap}：存在数据泄漏（R15）")
    if split.get("leak_overlap_families"):
        problems.append(f"leak_overlap_families 非空：{split['leak_overlap_families']}")
    if split.get("cross_family_holdout") and not holdout:
        problems.append("cross_family_holdout=true 但 holdout_families 为空：不能声称跨族泛化")
    return problems


def s2_literature_evidence_resolvable(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "sample" or rec.get("source_type") != "literature":
        return []
    ev = rec.get("evidence_id")
    known = ctx["records"]["evidence"]
    if not ev:
        return ["literature 样本缺 evidence_id"]
    if ev not in known:
        return [
            f"evidence_id={ev!r} 无法解析到任何**合法** evidence 记录"
            f"（当前样例集中合法 evidence 记录：{sorted(known) or '无'}）"
            "——红线 1：文献值必须回溯到带页码与原文摘录的证据"
        ]
    return []


def s3_sample_split_group_key(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "sample":
        return []
    split = rec.get("split") or {}
    family = (rec.get("design") or {}).get("geometry_family")
    key = split.get("group_key")
    if key and family and key != family:
        return [f"split.group_key={key!r} 与 design.geometry_family={family!r} 不一致：分组键错会让防泄漏失效"]
    return []


def s4_sample_units(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "sample":
        return []
    problems: list[str] = []
    params = (rec.get("design") or {}).get("parameters") or {}
    units = (rec.get("design") or {}).get("parameter_units") or {}
    missing = sorted(set(params) - set(units))
    if missing:
        problems.append(f"参数缺单位（必须逐参数给 SI 单位）：{missing}")
    extra = sorted(set(units) - set(params))
    if extra:
        problems.append(f"parameter_units 含未声明参数的条目：{extra}")
    for entry in (rec.get("units") or {}).get("original_values") or []:
        name = entry.get("name")
        raw, factor, si = entry.get("raw_value"), entry.get("factor"), entry.get("si_value")
        if None in (raw, factor, si):
            problems.append(f"换算记录 {name!r} 缺 raw_value/factor/si_value")
            continue
        expected = float(raw) * float(factor)
        tol = max(1e-12, abs(float(si)) * 1e-9)
        if abs(expected - float(si)) > tol:
            problems.append(
                f"换算记录 {name!r} 不自洽：raw_value×factor={expected!r} ≠ si_value={si!r}"
                f"（raw_unit={entry.get('raw_unit')!r} → si_unit={entry.get('si_unit')!r}）"
            )
        if entry.get("raw_unit") == entry.get("si_unit"):
            problems.append(f"换算记录 {name!r} 的 raw_unit 与 si_unit 相同，不构成换算记录")
    return problems


def s5_frequency_ascending(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "sample":
        return []
    values = ((rec.get("frequency_set") or {}).get("values")) or []
    if values != sorted(values) or len(set(values)) != len(values):
        return [f"frequency_set.values 必须严格升序且不重复，收到 {values}"]
    return []


def s6_uncertainty_present_or_explained(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "sample":
        return []
    if rec.get("uncertainty"):
        return []
    reason = (rec.get("quality") or {}).get("uncertainty_not_quantified_reason")
    if not (isinstance(reason, str) and reason.strip()):
        per_metric = [
            name for name, m in (rec.get("metrics") or {}).items()
            if isinstance(m, dict) and m.get("uncertainty")
        ]
        return [
            "样本级 uncertainty 为空，且 quality.uncertainty_not_quantified_reason 也缺失；"
            f"若分量已逐指标给出（本样本：{per_metric or '无'}）也必须写明这一事实，"
            "否则「不确定度未量化」这件事会被静默吞掉"
        ]
    return []


def s7_ai_solver_not_disguised(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "sample" or rec.get("source_type") != "ai_solver":
        return []
    problems = []
    if rec.get("run_id"):
        problems.append("ai_solver 样本携带 run_id：AI 解不得伪装成 COMSOL 解（红线 7/8）")
    blk = rec.get("ai_solver") or {}
    for field in ("validation_level", "field_error_bound", "applicability"):
        if not blk.get(field):
            problems.append(f"ai_solver 缺 {field}（红线 7：误差界 + S 级状态 + 适用范围命中三件套）")
    if (blk.get("applicability") or {}).get("in_scope") is not True:
        problems.append("ai_solver.applicability.in_scope 必须为 true：超范围外推应拒答，不得入库")
    return problems


def d1_device_spec_caliber(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "device_spec":
        return []
    if (rec.get("targets") or {}).get("caliber_id") is None:
        blob = _pending_blob(rec)
        if "口径" not in blob and "caliber" not in blob.lower():
            return ["targets.caliber_id 为 null（口径未钉死）但 pending_human 未声明该未确认项"]
    return []


def d2_device_spec_pending_range(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "device_spec":
        return []
    blob = _pending_blob(rec)
    problems = []
    for p in rec.get("parameters") or []:
        if p.get("auto_adjust_ok") and p.get("range") is None and p.get("values") is None:
            if str(p.get("name")) not in blob:
                problems.append(
                    f"参数 {p.get('name')!r} 可自动改参但既无 range 也无 values，"
                    "且未在 pending_human 中声明 ⇒ 会被误当成「可用但没范围」"
                )
        elif p.get("auto_adjust_ok") and p.get("range") is None and str(p.get("name")) not in blob:
            problems.append(
                f"参数 {p.get('name')!r} 只有离散档位、无确认的设计范围，未在 pending_human 中声明"
            )
    return problems


def d3_device_spec_source_hash(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "device_spec":
        return []
    if (rec.get("source_model") or {}).get("sha256") is None:
        if "sha256" not in _pending_blob(rec).lower() and "哈希" not in _pending_blob(rec):
            return ["source_model.sha256 为空但 pending_human 未声明（禁止用截断/推测哈希凑满）"]
    return []


def t1_task_params_exist(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "task_spec":
        return []
    spec = ctx["records"]["device_spec"].get(rec.get("device_spec_ref"))
    if spec is None:
        return [f"device_spec_ref={rec.get('device_spec_ref')!r} 无法解析到 device_spec（跨文件引用必须可解析）"]
    allowed = {p.get("name") for p in spec.get("parameters") or []}
    bad = sorted({p.get("name") for p in rec.get("parameters") or []} - allowed)
    if bad:
        return [f"task_spec 声明了 device_spec 未定义的参数 {bad}（只允许改已声明的参数；红线：防误改/器件无关）"]
    return []


def t2_task_goals_exist(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "task_spec":
        return []
    spec = ctx["records"]["device_spec"].get(rec.get("device_spec_ref"))
    if spec is None:
        return []
    goals = {g.get("name"): g for g in (spec.get("targets") or {}).get("scalar_goals") or []}
    problems = []
    for goal in (rec.get("objective") or {}).get("goals") or []:
        name = goal.get("name")
        if name not in goals:
            problems.append(f"目标 {name!r} 不在 device_spec.targets.scalar_goals 中（器件无关：目标必须声明式给出）")
            continue
        if goals[name].get("kind") == "measure_only":
            if not any(str(p).startswith("/objective") for p in _placeholder_paths(rec)):
                problems.append(
                    f"目标 {name!r} 在 device_spec 里是 measure_only（仅为观测量），"
                    "却被当作优化目标使用；若确为草稿必须在 placeholders 中声明 /objective 路径"
                )
    return problems


def t3_task_range_within_spec(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "task_spec":
        return []
    spec = ctx["records"]["device_spec"].get(rec.get("device_spec_ref")) or {}
    spec_params = {p.get("name"): p for p in spec.get("parameters") or []}
    problems = []
    for p in rec.get("parameters") or []:
        ref = spec_params.get(p.get("name")) or {}
        rng, ref_rng = p.get("range"), ref.get("range")
        if rng and ref_rng:
            if float(rng[0]) < float(ref_rng[0]) or float(rng[1]) > float(ref_rng[1]):
                problems.append(
                    f"参数 {p.get('name')!r} 的任务范围 {rng} 超出 device_spec 声明范围 {ref_rng}"
                )
    return problems


def t4_task_caliber_matches(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "task_spec":
        return []
    spec = ctx["records"]["device_spec"].get(rec.get("device_spec_ref")) or {}
    a = (rec.get("target_caliber") or {}).get("id")
    b = (spec.get("targets") or {}).get("caliber_id")
    if a and b and a != b:
        return [f"task_spec.target_caliber.id={a!r} 与 device_spec.targets.caliber_id={b!r} 不一致（口径漂移）"]
    return []


def r1_run_gaps_declared(rec: dict, kind: str, ctx: dict) -> list[str]:
    if kind != "run" or rec.get("status") != "succeeded":
        return []
    blob = _gap_blob(rec)
    problems = []
    for field in ("model_sha256", "wall_seconds", "finished_at"):
        if rec.get(field) in (None, ""):
            if field not in blob:
                problems.append(
                    f"succeeded 运行的 {field} 为空且未在 provenance_gaps 中声明（缺什么就要声明什么）"
                )
    return problems


CHECKS: dict[str, Callable[[dict, str, dict], list[str]]] = {
    "S1_dataset_no_family_leak": s1_dataset_no_family_leak,
    "S2_literature_evidence_resolvable": s2_literature_evidence_resolvable,
    "S3_sample_split_group_key_matches_family": s3_sample_split_group_key,
    "S4_sample_parameter_units_cover_parameters": s4_sample_units,
    "S5_frequency_values_ascending": s5_frequency_ascending,
    "S6_uncertainty_present_or_explained": s6_uncertainty_present_or_explained,
    "S7_ai_solver_not_disguised_as_simulation": s7_ai_solver_not_disguised,
    "D1_device_spec_caliber_or_pending": d1_device_spec_caliber,
    "D2_device_spec_range_null_or_confirmed": d2_device_spec_pending_range,
    "D3_device_spec_source_hash_or_pending": d3_device_spec_source_hash,
    "T1_task_params_exist_in_device_spec": t1_task_params_exist,
    "T2_task_goals_exist_in_device_spec": t2_task_goals_exist,
    "T3_task_param_range_within_device_spec": t3_task_range_within_spec,
    "T4_task_caliber_matches_device_spec": t4_task_caliber_matches,
    "R1_run_gaps_declared": r1_run_gaps_declared,
}


# --------------------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------------------
def schema_errors(schema: dict, instance: Any) -> list[dict]:
    """返回**扁平化**的 schema 错误列表。

    ``oneOf``/``anyOf``/``allOf`` 的失败本身信息量很低（如「oneOf 不成立」），
    真正的原因是它的子错误（「缺 zero_is_known」）。因此这里递归展开 ``err.context``，
    让校验输出直接指向具体字段与关键字，便于人工复核与「拒绝理由」比对。
    """
    validator = Draft202012Validator(schema)
    out: list[dict] = []

    def walk(err) -> None:
        path = "/".join(str(x) for x in err.absolute_path)
        out.append({
            "keyword": err.validator,
            "path": path,
            "message": err.message,
            "match_blob": f"{path} {err.message}",
        })
        for sub in err.context or []:
            walk(sub)

    for err in validator.iter_errors(instance):
        walk(err)
    # 去重（同一 (keyword, path, message) 可能经多条分支重复出现）
    seen = set()
    unique = []
    for item in out:
        key = (item["keyword"], item["path"], item["message"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def semantic_errors(instance: dict, kind: str, ctx: dict, only: str | None = None) -> list[dict]:
    out = []
    for name, fn in CHECKS.items():
        if only and name != only:
            continue
        for problem in fn(instance, kind, ctx):
            out.append({"check": name, "message": problem})
    return out


def run_validation(verbose: bool = False) -> int:
    schemas = load_schemas()
    manifest = load_json(EXAMPLES / "manifest.json")
    ctx = {"records": load_records()}
    rows: list[tuple[str, str, str, str]] = []  # (期望, 结果, 依据, 文件)
    failures: list[str] = []

    for entry in manifest["valid"]:
        rel = entry["file"]
        path = EXAMPLES / rel
        if not path.is_file():
            failures.append(f"缺少样例文件：{rel}")
            rows.append(("schema+语义通过", "失败", "文件不存在", rel))
            continue
        instance = load_json(path)
        s_errs = schema_errors(schemas[entry["schema"]], instance)
        m_errs = semantic_errors(instance, entry["kind"], ctx)
        if s_errs:
            evidence = "; ".join(f"{e['keyword']}@{e['path'] or '<root>'}: {e['message'][:120]}" for e in s_errs[:3])
            failures.append(f"[valid] {rel} 未通过 schema：{evidence}")
            rows.append(("schema+语义通过", "失败(schema)", evidence, rel))
            continue
        if m_errs:
            evidence = "; ".join(f"{e['check']}: {e['message'][:160]}" for e in m_errs[:3])
            failures.append(f"[valid] {rel} 未通过语义检查：{evidence}")
            rows.append(("schema+语义通过", "失败(语义)", evidence, rel))
            continue
        checks_n = len(CHECKS)
        rows.append(("schema+语义通过", "通过", f"0 error；语义检查 {checks_n} 项全过", rel))
        if verbose:
            print(f"  [ok] {rel}: schema 0 error, {checks_n} 项语义检查通过")

    for entry in manifest["invalid"]:
        rel = entry["file"]
        path = EXAMPLES / rel
        if not path.is_file():
            failures.append(f"缺少非法样例文件：{rel}")
            rows.append(("被拒", "失败", "文件不存在", rel))
            continue
        instance = load_json(path)
        s_errs = schema_errors(schemas[entry["schema"]], instance)
        m_errs = semantic_errors(instance, entry["kind"], ctx)
        if not s_errs and not m_errs:
            failures.append(f"[invalid] {rel} 竟然通过了校验（期望被拒：{entry.get('red_line')}）")
            rows.append(("被拒", "失败(未被拒)", f"期望 {entry['expect']}", rel))
            continue

        exp = entry["expect"]
        hit = None
        if exp["stage"] == "schema":
            needle = exp.get("path_contains", "")
            for e in s_errs:
                if e["keyword"] == exp["keyword"] and (needle == "" or needle in e["match_blob"]):
                    hit = f"{e['keyword']}@{e['path'] or '<root>'}"
                    break
            if hit is None and s_errs:
                hit = None
        else:
            for e in m_errs:
                if e["check"] == exp["check"]:
                    hit = e["check"]
                    break

        if hit is None:
            got_s = "; ".join(f"{e['keyword']}@{e['path'] or '<root>'}" for e in s_errs[:4]) or "无"
            got_m = "; ".join(e["check"] for e in m_errs[:4]) or "无"
            evidence = f"拒绝理由不符期望：期望 {exp}；实际 schema=[{got_s}] semantic=[{got_m}]"
            failures.append(f"[invalid] {rel} {evidence}")
            rows.append(("被拒", "失败(理由不符)", evidence, rel))
        else:
            rows.append(("被拒", "通过", f"{hit}｜{entry.get('red_line', '')}", rel))

    # ---- 输出 ----
    width_file = max((len(r[3]) for r in rows), default=10)
    print("=" * 118)
    print("MEMS Harness 契约校验（schemas/validate_examples.py）")
    print(f"schema 文件 {len(schemas)} 个；样例 {len(manifest['valid'])} 合法 / {len(manifest['invalid'])} 非法；语义检查 {len(CHECKS)} 项")
    print("=" * 118)
    print(f"{'期望':<16}{'结果':<18}{'文件':<{width_file}}  依据")
    print("-" * 118)
    for want, got, why, rel in rows:
        print(f"{want:<16}{got:<18}{rel:<{width_file}}  {why[:150]}")
    print("-" * 118)
    if failures:
        print(f"结论：失败（{len(failures)} 项期望未成立）")
        for f in failures:
            print(f"  ✗ {f}")
        return 2
    print(f"结论：全部通过 —— {len(manifest['valid'])} 个合法样例通过、{len(manifest['invalid'])} 个非法样例按声明理由被拒")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 schemas/ 下的契约样例（fail-closed）")
    parser.add_argument("--verbose", action="store_true", help="逐条打印通过项")
    parser.add_argument("--json", action="store_true", help="额外输出机器可读结论")
    args = parser.parse_args()
    code = run_validation(verbose=args.verbose)
    if args.json:
        print(json.dumps({"exit_code": code}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
