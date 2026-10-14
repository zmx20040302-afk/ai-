# -*- coding: utf-8 -*-
"""A5「扫描分析与优化」的命令行入口（分指标排名 + Pareto + 下一批选点，**无总分**）。

用法（本机实测口径：PMUT `structure_summary.csv`）：

    python scripts/run_sweep_analysis.py ^
      --csv work/runs/scalar-channel-20260915/pmut_report/structure_summary.csv ^
      --preset pmut-structure-summary ^
      --metrics-json work/runs/a5a9-20260916/metrics.json ^
      --model-sha256 <模型哈希> --precheck <预检 json> ^
      --candidate-grid work/runs/a5a9-20260916/candidate_grid.json ^
      --out-dir work/runs/a5a9-20260916

产出（落 `--out-dir`）：
    scan_analysis.json / scan_analysis.md / next_batch.json / next_batch.md

退出码（给自动化用）：
    0 = verdict=ranked（该批排名可用于下游决策）
    2 = failed（口径冲突/跨族/空输入/含总分字段/质量门排除率过高）
    3 = inconclusive 或 provisional（**不得当作结论**）
    4 = 用法错误 / 文件缺失

注意：本脚本**只读数据**，不触发任何求解（选点建议交给 A3）。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.sweep_analysis import (  # noqa: E402
    MetricSpec, analyze, build_next_batch, render_md, render_next_batch_md,
    rows_from_records, sha256_file,
)


# ---------------------------------------------------------------------------
# 本机 PMUT 口径预设（列名 → 口径/质量标记）
# ---------------------------------------------------------------------------
def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("true", "1", "yes", "y", "t")


def _falsy(v) -> bool:
    return not _truthy(v)


#: PMUT 质量标记规则——**已接线**（每个都必须至少被一个指标 exclude/advisory 引用，
#: 否则 `assert_flag_rules_wired` 会以退出码 4 拦停；A8 红队实测过"声明了却从不排除"的死规则）。
PMUT_FLAG_RULES = {
    "sparse_frequency_grid":
        lambda r: (float(r.get("n_freq_points") or 0) < 9),
    "peak_is_lower_bound": lambda r: _truthy(r.get("peak_is_lower_bound")),
    "peak_at_range_edge": lambda r: _truthy(r.get("peak_at_range_edge")),
    "bandwidth_not_closed_3dB_Vave": lambda r: _falsy(r.get("bandwidth_closed_3dB_Vave")),
    "drive_not_verified": lambda r: _falsy(r.get("drive_verified")),
    "measurement_point_unverified": lambda r: _falsy(r.get("measurement_point_verified")),
    # 全局取消资格（几何/网格无效、退化几何、预检非 clean）在 sweep_analysis 里强制生效
    "geometry_invalid": lambda r: str(r.get("geometry_valid") or "").lower() == "invalid",
    "mesh_invalid": lambda r: str(r.get("mesh_valid") or "").lower() == "invalid",
    # 退化：零电极或 N_w_te1 ≥ N_w_te2（两电极边界重合）
    "degenerate_geometry": lambda r: (
        float(r.get("N_w_te1") or 0) <= 0
        or (r.get("N_w_te2_used") not in (None, "")
            and float(r.get("N_w_te1") or 0) >= float(r.get("N_w_te2_used")))),
    # 求解状态**只有明确失败**才算失败：`not_exported/unknown` 是"没记录"，不是"求解失败"
    "solver_not_succeeded": lambda r: str(r.get("solver_status") or "").strip().lower() in (
        "failed", "error", "not_converged", "diverged", "cancelled"),
    "solver_status_unrecorded": lambda r: str(r.get("solver_status") or "").strip().lower() in (
        "", "not_exported", "unknown"),
}

#: **已声明但本批没有对应指标**的规则（诚实单列：它们不参与任何筛选）。
#: 一旦把相应指标接进 `PMUT_METRICS`（例如压力带宽、6 dB 带宽、Ptot 带宽），就把规则移上去。
PMUT_FLAG_RULES_UNWIRED = {
    "bandwidth_not_closed_3dB_Ptot": lambda r: _falsy(r.get("bandwidth_closed_3dB_Ptot")),
    "bandwidth_not_closed_3dB_Vcenter_abs":
        lambda r: _falsy(r.get("bandwidth_closed_3dB_Vcenter_abs")),
    "bandwidth_not_closed_6dB_Vave": lambda r: _falsy(r.get("bandwidth_closed_6dB_Vave")),
    "pressure_bandwidth_unavailable": lambda r: _falsy(r.get("bandwidth_pressure_available")),
}

#: PMUT 指标口径（**幅值 20log10 / 功率 10log10 / 响应 20log10 / 绝对量**，不得混用）
PMUT_METRICS = [
    MetricSpec("Ptot_peak", "峰值总辐射声功率", "W", "max", "drive_dependent",
               exclude_flags=("sparse_frequency_grid", "peak_is_lower_bound",
                              "peak_at_range_edge", "solver_not_succeeded"),
               advisory_flags=("drive_not_verified", "solver_status_unrecorded")),
    MetricSpec("p_axis_100um_abs_Pa", "20 MHz 轴向 100 µm 声压", "Pa", "max", "absolute",
               advisory_flags=("drive_not_verified", "measurement_point_unverified",
                               "solver_status_unrecorded")),
    MetricSpec("displacement_center_peak_m", "中心位移峰值", "m", "max", "absolute",
               exclude_flags=("sparse_frequency_grid", "peak_is_lower_bound",
                              "solver_not_succeeded"),
               advisory_flags=("drive_not_verified", "solver_status_unrecorded")),
    MetricSpec("BW_3dB_Vave_MHz", "响应 -3 dB 带宽（代理：Vave，20log10）", "MHz", "max",
               "response_20log10",
               exclude_flags=("bandwidth_not_closed_3dB_Vave", "solver_not_succeeded"),
               advisory_flags=("drive_not_verified", "solver_status_unrecorded")),
    MetricSpec("FBW_3dB_Vave_pct", "响应 -3 dB 相对带宽（代理：Vave）", "%", "max",
               "response_20log10",
               exclude_flags=("bandwidth_not_closed_3dB_Vave", "solver_not_succeeded"),
               advisory_flags=("drive_not_verified", "solver_status_unrecorded")),
    MetricSpec("Zin_X_at_Ptot_peak", "输入阻抗虚部（峰值处）", "ohm", "max", "absolute",
               advisory_flags=("drive_not_verified", "solver_status_unrecorded")),
]
PMUT_DEFAULT_PARETO = ["Ptot_peak", "p_axis_100um_abs_Pa", "displacement_center_peak_m",
                       "BW_3dB_Vave_MHz"]

def _flag_col(name: str):
    """从 `flag_<name>` 布尔列读标记（远端导出族用；值形如 True/False）。"""
    return lambda r: str(r.get("flag_" + name) or "").strip().lower() in ("true", "1", "yes")


#: 远端导出族 `cell_te2_*` 的质量标记规则：**只有真的被指标引用的才声明**
#: （否则 `assert_flag_rules_wired` 会以退出码 4 拦停）。
#: 导出器告警与 `marker_table_not_attributable` 留在 CSV/清单里作证据，不进排名判据
#: ——它们要么是 run 级、要么与本组合的指标有效性无关。
CELL_TE2_FLAG_RULES = {
    "peak_at_range_edge": _flag_col("peak_at_range_edge"),
    "bandwidth_not_closed": _flag_col("bandwidth_not_closed"),
    "partial_x_scan": _flag_col("partial_x_scan"),
}

CELL_TE2_METRICS = [
    # 20 MHz 处的 SPL：**不含峰值假设**，最稳健
    MetricSpec("spl_20MHz_dB", "20 MHz 轴向 SPL（点 (0,0,−10 µm)）", "dB", "max",
               "amplitude_20log10", advisory_flags=("partial_x_scan",)),
    MetricSpec("p_abs_20MHz_Pa", "20 MHz 轴向声压幅值", "Pa", "max", "absolute",
               advisory_flags=("partial_x_scan",)),
    # 峰值类：峰落在扫描边界时，报出的只是**下界** ⇒ 排除出排名
    MetricSpec("spl_max_dB", "扫描段内 SPL 最大值", "dB", "max", "amplitude_20log10",
               exclude_flags=("peak_at_range_edge",), advisory_flags=("partial_x_scan",)),
    MetricSpec("disp_at_peak_m", "峰频处中心位移幅值", "m", "max", "absolute",
               exclude_flags=("peak_at_range_edge",), advisory_flags=("partial_x_scan",)),
    # 带宽/Q：−3 dB 交点没同时落在扫描范围内 ⇒ 排除（不编数）
    MetricSpec("bandwidth_3dB_MHz", "−3 dB 带宽（逐点扫频自算）", "MHz", "max", "absolute",
               exclude_flags=("bandwidth_not_closed",), advisory_flags=("partial_x_scan",)),
    MetricSpec("q_from_points", "Q（逐点扫频自算）", "1", "max", "absolute",
               exclude_flags=("bandwidth_not_closed",), advisory_flags=("partial_x_scan",)),
]
CELL_TE2_DEFAULT_PARETO = ["spl_20MHz_dB", "spl_max_dB", "bandwidth_3dB_MHz", "disp_at_peak_m"]

PRESETS = {
    "pmut-structure-summary": {
        "family_col": "source_family",
        "params": ["x_scale", "N_w_te1"],
        "metrics": PMUT_METRICS,
        "flag_rules": PMUT_FLAG_RULES,
        "pareto": PMUT_DEFAULT_PARETO,
        "primary_metric": "Ptot_peak",
        "note": "口径来自 work/runs/scalar-channel-20260915/pmut_report/（本会话 72 网格）",
    },
    "cell_te2-exported": {
        "family_col": "source_family",
        # ⚠️ `params` 必须包含**定义族的那个参数**（这里是 N_w_te2）：否则
        # `no_cross_family_duplicate_points` 会把"同一 (x,N1) 出现在不同 N2"误判成重复点
        # （实测踩过：223 组合被判 failed）。N2 在族内恒定 ⇒ 不影响格距计算。
        "params": ["x_scale", "N_w_te1", "N_w_te2"],
        "metrics": CELL_TE2_METRICS,
        "flag_rules": CELL_TE2_FLAG_RULES,
        "pareto": CELL_TE2_DEFAULT_PARETO,
        "primary_metric": "spl_max_dB",
        "note": ("远端导出族 cell_te2_*（取样点 (0,0,−1E-5) m = −10 µm；5–35 MHz / 61 点）；"
                 "族 = cell_te2_N2<k>；峰/带宽/Q 一律由逐点扫频自算，不用 Bandwidth.txt"),
    },
}


def load_metrics_json(path: Path) -> tuple[list[MetricSpec], dict]:
    """从 JSON 载入口径声明：`[{"name":..., "exclude_flags":[...], ...}]`。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data["metrics"] if isinstance(data, dict) else data
    specs = []
    for it in items:
        kw = {k: v for k, v in it.items() if k in MetricSpec.__dataclass_fields__}
        for k in ("exclude_flags", "advisory_flags"):
            if k in kw and isinstance(kw[k], list):
                kw[k] = tuple(kw[k])
        specs.append(MetricSpec(**kw))
    rules = (data.get("flag_rules") if isinstance(data, dict) else None) or {}
    return specs, rules


def read_csv_rows(path: Path, encoding: str = "utf-8-sig") -> list[dict]:
    with open(path, "r", encoding=encoding, newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def assert_flag_rules_wired(metrics: list, rules: dict) -> list[str]:
    """**接线自检**：声明了质量标记规则，就必须有指标真的用它。

    A8 红队实测：预设里 `degenerate_geometry`/`geometry_invalid`/`mesh_invalid` 等规则
    被声明却**从未排除任何点**（既不在任何指标的 exclude_flags，也不在全局取消资格集），
    导致"文档说它们是质量门排除项、代码里却是死规则"。这里把这种漂移变成硬失败。
    """
    from memsharness.sweep_analysis import GLOBAL_EXCLUDE_FLAGS
    used: set[str] = set(GLOBAL_EXCLUDE_FLAGS)
    for m in metrics:
        used |= set(m.exclude_flags) | set(m.advisory_flags)
    return sorted(set(rules) - used)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A5 扫描分析（分指标排名 + Pareto + 选点建议）")
    ap.add_argument("--csv", required=True, help="宽表 CSV（每行一个参数组合）")
    ap.add_argument("--encoding", default="utf-8-sig")
    ap.add_argument("--preset", choices=sorted(PRESETS), default=None)
    ap.add_argument("--metrics-json", default=None, help="口径声明 JSON（覆盖 preset 的指标）")
    ap.add_argument("--family-col", default=None)
    ap.add_argument("--param", action="append", default=[], help="参数列名（可重复）")
    ap.add_argument("--pareto-metric", action="append", default=[])
    ap.add_argument("--primary-metric", default=None, help="选点建议的主指标")
    ap.add_argument("--model-sha256", default=None)
    ap.add_argument("--precheck", default=None, help="几何/选择集预检 JSON（缺省 ⇒ 排名降级为临时）")
    ap.add_argument("--no-caliber-approval", action="store_true", help="A1 未批准口径 ⇒ 不出结论")
    ap.add_argument("--min-effective", type=int, default=5)
    ap.add_argument("--max-exclusion-rate", type=float, default=0.5)
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--candidate-grid", default=None, help="候选网格 JSON（选点只在其上进行）")
    ap.add_argument("--budget", type=int, default=6)
    ap.add_argument("--per-point-cost-s", type=float, default=None)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print("找不到 CSV：%s" % csv_path, file=sys.stderr)
        return 4
    preset = PRESETS.get(args.preset) if args.preset else None
    if preset is None and not args.metrics_json:
        print("必须给 --preset 或 --metrics-json（口径必须显式声明）", file=sys.stderr)
        return 4

    metrics = list(preset["metrics"]) if preset else []
    flag_rules = dict(preset["flag_rules"]) if preset else {}
    if args.metrics_json:
        m2, r2 = load_metrics_json(Path(args.metrics_json))
        metrics = m2
        flag_rules.update(r2)
    fam_col = args.family_col or (preset or {}).get("family_col") or "source_family"
    params = args.param or (preset or {}).get("params") or ["x_scale", "N_w_te1"]
    pareto = args.pareto_metric or (preset or {}).get("pareto") or []
    primary = args.primary_metric or (preset or {}).get("primary_metric")

    records = read_csv_rows(csv_path, args.encoding)
    rows = rows_from_records(records, family_key=fam_col, param_keys=params,
                            metric_keys=[m.name for m in metrics], flag_rules=flag_rules)
    unwired = assert_flag_rules_wired(list(metrics), flag_rules)
    if unwired:
        print("质量标记规则声明了却没有接线（任何指标都不用、也不在全局取消资格集里）：%r" % unwired,
              file=sys.stderr)
        print("⇒ 说明书会把这些写成『质量门排除项』而代码里是死规则。请接上或删掉声明。",
              file=sys.stderr)
        return 4
    precheck = None
    if args.precheck:
        precheck = json.loads(Path(args.precheck).read_text(encoding="utf-8"))

    scan = analyze(
        rows, metrics, top_n=args.top_n, min_effective=args.min_effective,
        max_exclusion_rate=args.max_exclusion_rate, model_sha256=args.model_sha256,
        precheck=precheck, caliber_approved=not args.no_caliber_approval,
        rows_path=str(csv_path), rows_sha256=sha256_file(csv_path),
        pareto_metrics=pareto or None,
        script_sha256=sha256_file(Path(__file__)),
    )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scan_analysis.json").write_text(
        json.dumps(scan, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "scan_analysis.md").write_text(render_md(scan), encoding="utf-8")

    print("verdict=%s release_allowed=%s provisional=%s"
          % (scan["verdict"], scan["release_allowed"], scan["provisional"]))
    print("rows=%d families=%d 排除率=%.1f%%"
          % (scan["input"]["n_rows"], scan["input"]["n_families"],
             100 * (scan["quality"]["exclusion_rate"] or 0.0)))
    for rk in scan["rankings"]:
        top = rk["top"][0] if rk["top"] else None
        print("  [%s] %-26s 有效 %3d 排除 %3d 榜首 %s"
              % (rk["family"], rk["metric"], rk["n_available"], rk["n_excluded"],
                 (json.dumps(top["params"], ensure_ascii=False) if top else "—")))

    nb = None
    if args.candidate_grid:
        grid = json.loads(Path(args.candidate_grid).read_text(encoding="utf-8"))
        nb = build_next_batch(scan, candidate_grid=grid, budget=args.budget,
                              param_keys=params, per_point_cost_s=args.per_point_cost_s,
                              primary_metric=primary)
        (out / "next_batch.json").write_text(
            json.dumps(nb, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        (out / "next_batch.md").write_text(render_next_batch_md(nb), encoding="utf-8")
        print("next_batch: %s 建议 %d 点（被拒 %d）"
              % (nb["verdict"], nb["budget"]["n_selected"], nb["budget"]["n_rejected"]))

    print("json:", out / "scan_analysis.json")
    if scan["verdict"] == "failed":
        return 2
    if scan["verdict"] != "ranked" or not scan["release_allowed"]:
        return 3
    if nb is not None and nb["verdict"] == "blocked":
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
