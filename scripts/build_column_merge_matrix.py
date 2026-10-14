# -*- coding: utf-8 -*-
"""生成**列级可合并矩阵** `column_merge_matrix.json`（fail-closed）。

背景：用户 2026-09-23 裁定"同一模型、结构相同、只是改参数扫描"
（`feedback` `fb-20260923T110333Z-e0a59352`）。该裁定解决的是**结构同源**，
**不等于**"输出列可以互相拼接"——两批导出的列集不同，且共有列的定义未统一
（实测 `V_center` 差 16.36 倍、`Vave` 差 5.5%，各为近似常数）。

本脚本把"哪一列可以跨批比"写成机器可读文件，并**强制**：
* 出现在任一批次表头里的列，**必须**被显式分类；否则**退出码 2**（fail-closed）；
* 只有 `poolable is True` 的列允许进入跨批统计/训练；
* 未确认定义的列一律 `unknown`，**不得**由下游默认当作可并。

用法：
    python -B scripts/build_column_merge_matrix.py            # 写文件
    python -B scripts/build_column_merge_matrix.py --check     # 只校验，不写
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUN = REPO / "work/runs/remote-exported-20260922"
DATASET = RUN / "dataset"
GUI = REPO / "work/runs/gui-sweep-20260912T113936Z-bd387a56/source_table.csv"
OUT = RUN / "column_merge_matrix.json"

# 列 → 分类。`poolable=True` 只有在**两批定义已确认一致**时才允许。
RULES: dict[str, dict] = {
    # ---- 输入轴：可统一 ----
    "x_scale": {"axis": "input", "poolable": True, "unit": "1",
                "why": "两批同名同义；用户裁定结构同源 + 逐频点形状检验一致（散布 2.8%/0.2%）"},
    "N_w_te1": {"axis": "input", "poolable": True, "unit": "1",
                "why": "两批同名同义；数据 B 缺 N1=7（记为缺失，不插值）"},
    "N_w_te2": {"axis": "input", "poolable": True, "unit": "1",
                "why": "数据 A 为扫描列；数据 B 不在表内（模型常量 9）⇒ B 侧填常量，待数据侧确认真值"},
    "freq_Hz": {"axis": "input", "poolable": True, "unit": "Hz",
                "why": "同一物理量。但**分析视图按分辨率分流**：B 只有 7 点/5 MHz，撑不起带宽/Q 与一阶峰"},
    # ---- 输出轴：只有明确确认的才 poolable ----
    "spl_dB": {"axis": "output", "poolable": False, "unit": "dB",
               "why": "只有数据 A 有（B 无声压）⇒ 跨批表中 B 侧必须留空"},
    "p_abs_Pa": {"axis": "output", "poolable": False, "unit": "Pa",
                 "why": "只有数据 A 有"},
    "p_re": {"axis": "output", "poolable": False, "unit": "Pa", "why": "只有数据 A 有"},
    "p_im": {"axis": "output", "poolable": False, "unit": "Pa", "why": "只有数据 A 有"},
    "p_rms_Pa": {"axis": "output", "poolable": False, "unit": "Pa", "why": "只有数据 A 有"},
    "v_tz_re": {"axis": "output", "poolable": False, "unit": "m/s", "why": "只有数据 A 有（判据点声速）"},
    "v_tz_im": {"axis": "output", "poolable": False, "unit": "m/s", "why": "同上"},
    "c_tz_cplx": {"axis": "output", "poolable": False, "unit": "m/s", "why": "同上（复数文本）"},
    "Vcenter_20MHz_mps": {"axis": "output", "poolable": False, "unit": "m/s",
                          "why": "两批都有同名概念但**定义未统一**：实测比值 16.36（散布 2.8%）⇒ 待 B 提供测点定义"},
    "Vave_mps": {"axis": "output", "poolable": False, "unit": "m/s",
                 "why": "两批都有且**最接近可并**：比值 0.9447（散布 0.2%）⇒ 待确认 B 的取样面后可升级为 true"},
    "Ptot_W": {"axis": "output", "poolable": False, "unit": "W",
               "why": "定义不同：A 为复、有符号、实部可为负（p·conj(v) 面积分）；B 为实、正 ⇒ **不可并**"},
    "Zin1_R": {"axis": "output", "poolable": False, "unit": "Ohm", "why": "只有数据 B 有（数据 A 未导出阻抗）"},
    "Zin1_X": {"axis": "output", "poolable": False, "unit": "Ohm", "why": "同上"},
    "Zin2_R": {"axis": "output", "poolable": False, "unit": "Ohm", "why": "同上"},
    "Zin2_X": {"axis": "output", "poolable": False, "unit": "Ohm", "why": "同上"},
    "disp_z_m": {"axis": "output", "poolable": False, "unit": "m", "why": "只有数据 A 有"},
    "disp_at_peak_m": {"axis": "output", "poolable": False, "unit": "m", "why": "只有数据 A 有（派生）"},
    "bandwidth_3dB_MHz": {"axis": "output", "poolable": False, "unit": "MHz",
                          "why": "只有数据 A 有（B 只有 7 点，无法算带宽）"},
    "q_from_points": {"axis": "output", "poolable": False, "unit": "1", "why": "同上"},
    "spl_max_dB": {"axis": "output", "poolable": False, "unit": "dB", "why": "只有数据 A 有"},
    "f_peak_MHz": {"axis": "output", "poolable": False, "unit": "MHz", "why": "只有数据 A 有"},
    "spl_20MHz_dB": {"axis": "output", "poolable": False, "unit": "dB", "why": "只有数据 A 有（B 无声压）"},
    "p_20MHz_Pa": {"axis": "output", "poolable": False, "unit": "Pa", "why": "只有数据 A 有"},
    # ---- 溯源/质量：可统一（不是"值"）----
    "run": {"axis": "provenance", "poolable": True, "unit": None, "why": "溯源列，可统一"},
    "model": {"axis": "provenance", "poolable": True, "unit": None, "why": "溯源列（.mph 文件名）"},
    "src": {"axis": "provenance", "poolable": True, "unit": None, "why": "溯源列（来自哪张导出表）"},
    "point_z_m": {"axis": "provenance", "poolable": True, "unit": "m",
                  "why": "取样点 z 坐标（元数据，不是值）"},
    "flags": {"axis": "quality", "poolable": True, "unit": None, "why": "质量旗标，可统一"},
}

BATCH_A_FILES = ["points.csv", "power.csv", "mech.csv", "combos.csv",
                 "a5/metric_table.csv", "a6/first_mode_metrics.csv", "a6/target_20MHz_metrics.csv"]
BATCH_B_HEADER = ["% x_scale", "N_w_te1", "freq (Hz)", "Ptot (W)", "Zin1_R (Ω)", "Zin1_X (Ω)",
                  "Zin2_R (Ω)", "Zin2_X (Ω)", "Vave (m/s)", "V_center (m/s)"]

# 批量规则：命名清晰的成组列按**显式**模式归类，避免 68 条手工重复；
# 但每条模式都在产物里留痕（matched_rule），且**未命中任何规则仍 fail-closed**。
import re as _re

BULK_RULES: list[tuple[str, dict]] = [
    # 质量/元数据旗标：不是"测量值"，可随统一骨架携带（另一批侧为 NULL）
    (r"^flag_|^bandwidth_not_closed$|^peak_at_range_edge$|^family$|^source_family$",
     {"axis": "quality", "poolable": True, "unit": None,
      "why": "质量旗标/族标签（元数据，非测量值）；只有数据 A 有 ⇒ B 侧 NULL"}),
    (r"^q_marker$|^f_peak_marker_Hz$|^spl_max_marker_dB$|^bandwidth_marker_Hz$|^n_marker_crossings$",
     {"axis": "quality", "poolable": True, "unit": None,
      "why": "导出器标记表的交叉验证元数据（实测与逐点 argmax 223/223 一致）；只有 A 有 ⇒ B 侧 NULL"}),
    (r"^V[1-5]_|^none_|^first_mode_confidence$|^n_mech_local_max$|^n_spl_local_max$|^n_z_pt_|"
     r"^z_pt_im_has_sign_change$",
     {"axis": "output", "poolable": False, "unit": None,
      "why": "一阶峰识别的派生量，**只在数据 A 上算过**（B 的 7 点分辨率不支持）"}),
    (r"^at20_|^Vave_20MHz_mps$|^z_pt_20MHz_abs$|^phase_p_20MHz_deg$|^sensitivity_",
     {"axis": "output", "poolable": False, "unit": None,
      "why": "20 MHz 派生量，当前只在数据 A 上产出（B 侧缺声压/缺 N2）"}),
    (r"^f_peak_Hz$|^bandwidth_3dB_Hz$|^f_low_3dB_Hz$|^f_high_3dB_Hz$|^spl_max_dB$|^spl_at_f|"
     r"^q_from_points$|^n_local_maxima$|^n_freq$|^freq_min_Hz$|^freq_max_Hz$",
     {"axis": "output", "poolable": False, "unit": None,
      "why": "围绕扫频的派生指标，**只有数据 A 有**（B 7 点/5 MHz 无法算）"}),
    (r"^p_total_|^pv_W_|^v_z_m3s$|^vv$|^w_im_m$|^w_re_m$|^p_abs_20MHz_Pa$",
     {"axis": "output", "poolable": False, "unit": None,
      "why": "Table_10/Table_11 原始或派生量，**只有数据 A 有**；且功率类与 B 的 Ptot 定义不同"}),
    # Table_11 的量（2026-09-28 修好 ingest 的 Table_11 守卫后才出现在 mech.csv 里）
    (r"^stress_zz_N$|^sGp_du_Nms$|^u_du_m4s2$|^area_m2$|^disp_field_z_m3$",
     {"axis": "output", "poolable": False, "unit": None,
      "why": "Table_11 面积分/应力/能量/体位移；A↔C 列序一致（10 列），逐列复现性见 column_repeatability.json"}),
]


def classify(col: str) -> tuple[dict, str]:
    """返回 (分类, 命中规则名)。未命中 ⇒ 抛 KeyError（调用方 fail-closed）。"""
    if col in RULES:
        return RULES[col], "explicit"
    for pat, rule in BULK_RULES:
        if _re.search(pat, col):
            return rule, "bulk:%s" % pat
    raise KeyError(col)


def header(p: Path) -> list[str]:
    with p.open(encoding="utf-8", newline="") as f:
        return next(csv.reader(f))


# ---------------------------------------------------------------------------
# 批次 C（2026-09-28 新批：x 加密 + 频段 5–50 MHz）——**按位置对齐到规范名**
# ---------------------------------------------------------------------------
# 实测（2026-09-28）：C 的 6 张表数据列数与 A **逐一相同**：
#   Table_9=15, Table_10=8, Table_11=10, Zdisplacement=11, Peak_frequency=2, Bandwidth=5
# 表头由中文变英文（`点:` → `Point:`），属**名义差异**；列数与顺序一致。
C_MIRROR = REPO / "work/runs/x-densify-20260928/mirror"
C_RUNS = [
    "cell_te2_5_test_scal_0.2-1_0.01_freq5-50_v1_20260928_071108962_001",
    "cell_te2_6_test_scal_0.2-1_0.01_freq5-50_v1_20260928_074201239_001",
    "cell_te2_7_test_scal_0.2-1_0.01_freq5-50_v1_20260928_085936317_001",
]
C_BY_POSITION = {
    "Table_9.txt": ["x_scale", "N_w_te1", "N_w_te2", "freq_Hz", "v_tz_re", "v_tz_im",
                    "c_tz_cplx", "p_re", "p_im", "p_abs_Pa", "p_rms_Pa", None, None, None,
                    "spl_dB"],
    "Table_10.txt": ["x_scale", "N_w_te1", "N_w_te2", "freq_Hz", "p_total_N", "v_z_m3s",
                     "vv", "pv_W_re"],
    "Table_11.txt": ["x_scale", "N_w_te1", "N_w_te2", "freq_Hz", "v_z_m3s",
                     "stress_zz_N", "sGp_du_Nms", "u_du_m4s2", "area_m2",
                     "disp_field_z_m3"],
    "Zdisplacement.txt": ["x_scale", "N_w_te1", "N_w_te2", "freq_Hz", "disp_z_m", None, None,
                          None, "v_z_m3s", "w_re_m", "w_im_m"],
}

#: 判定依赖**扫描频率范围**的列（A 的上界 35 MHz vs C 的 50 MHz）
#: ⇒ 数值层面两批可互认（§57.4 已实测 6039 点复现），但**这些列的取值随范围而变**，
#:   跨批比较会得出错误结论（例：`peak_at_range_edge` 在 A 里指"顶在 35"，在 C 里指"顶在 50"）。
RANGE_DEPENDENT = {
    "peak_at_range_edge", "bandwidth_not_closed",
    "flag_peak_at_range_edge", "flag_bandwidth_not_closed",
    "spl_max_dB", "f_peak_MHz", "f_peak_Hz", "disp_at_peak_m",
    "bandwidth_3dB_MHz", "bandwidth_3dB_Hz", "q_from_points",
    "f_low_3dB_Hz", "f_high_3dB_Hz", "spl_at_fmin_dB", "spl_at_fmax_dB", "n_local_maxima",
    "bandwidth_marker_Hz", "q_marker", "f_peak_marker_Hz", "spl_max_marker_dB",
    "none_class", "none_lowest_mech_f_MHz", "none_has_mech_peak",
    "V1_f1_MHz", "V2_f1_MHz", "V1_BW1_MHz", "V2_BW1_MHz", "V1_Q1", "V2_Q1",
    "V1_missing_dir", "V2_missing_dir",
}

#: A↔C 的**逐列重复性证据**（`work/runs/x-densify-20260928/column_repeatability.json`）：
#: 6039 个共享点（99 组合 × 61 频点）上 18 个原始列全部 `reproduced`（中位相对差 ~1e-12）。
REPEATABILITY = "work/runs/x-densify-20260928/column_repeatability.json"
REPEAT_EVIDENCE = ("A↔C 6039 点逐列复现（2026-09-28 实测）：中位相对差 ~1e-12，"
                   "详见 column_repeatability.json")

#: 已实测复现的列 → 批次集合 {A, C}
A_C_REPRODUCED = {
    "x_scale", "N_w_te1", "N_w_te2", "freq_Hz",
    "v_tz_re", "v_tz_im", "c_tz_cplx", "p_re", "p_im", "p_abs_Pa", "p_rms_Pa", "spl_dB",
    "p_total_N", "p_total_im", "v_z_m3s", "vv", "pv_W_re", "pv_W_im",
    "disp_z_m", "w_re_m", "w_im_m", "area_m2",
    # Table_11 的其余列（2026-09-28 加入逐列复现检查后确认）
    "stress_zz_N", "sGp_du_Nms", "u_du_m4s2", "disp_field_z_m3",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成列级可合并矩阵（fail-closed）")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args(argv)

    a_cols: set[str] = set()
    for rel in BATCH_A_FILES:
        p = DATASET / rel if "/" not in rel else RUN / rel
        if p.is_file():
            a_cols |= set(header(p))
    b_cols = {c.lstrip("% ").strip() for c in BATCH_B_HEADER}

    # 数据 B 的列名 → 矩阵里的规范名
    alias = {"x_scale": "x_scale", "N_w_te1": "N_w_te1", "freq (Hz)": "freq_Hz",
             "Ptot (W)": "Ptot_W", "Zin1_R (Ω)": "Zin1_R", "Zin1_X (Ω)": "Zin1_X",
             "Zin2_R (Ω)": "Zin2_R", "Zin2_X (Ω)": "Zin2_X",
             "Vave (m/s)": "Vave_mps", "V_center (m/s)": "Vcenter_20MHz_mps"}
    b_norm = {alias.get(c, c) for c in b_cols}

    # ---- 批次 C：校验数据列数与位置映射一致，再取规范名 ----
    c_note: dict[str, object] = {"runs": C_RUNS, "columns_by_position": C_BY_POSITION}
    c_cols: set[str] = set()
    for tbl, names in C_BY_POSITION.items():
        got = None
        probe = C_MIRROR / C_RUNS[0] / tbl
        if probe.is_file():
            data_rows = [ln for ln in probe.read_text(encoding="utf-8", errors="replace").splitlines()
                         if ln.strip() and not ln.strip().startswith("%")]
            got = len(data_rows[0].split()) if data_rows else 0
        c_note.setdefault("observed_cols", {})[tbl] = got
        if got is not None and got != len(names):
            print("[FAIL] 批次 C 的 %s 数据列数 %s != 位置映射 %d ⇒ 位置对齐不成立，拒绝生成"
                  % (tbl, got, len(names)), file=sys.stderr)
            return 2
        c_cols |= {n for n in names if n}
        if tbl == "Table_10.txt":
            c_cols |= {"p_total_im", "pv_W_im"}      # 复数列的虚部
        if tbl == "Zdisplacement.txt":
            c_cols |= {"v_z_m3s"}
        if tbl == "Table_11.txt":
            c_cols |= {"v_z_m3s"}

    columns: dict[str, dict] = {}
    unclassified: list[str] = []
    for c in sorted(a_cols | b_norm | c_cols):
        try:
            rule, matched = classify(c)
        except KeyError:
            unclassified.append(c)
            continue
        columns[c] = {**rule, "matched_rule": matched,
                      "in_batch": (["A"] if c in a_cols else []) + (["B"] if c in b_norm else [])
                                  + (["C"] if c in c_cols else [])}
    if unclassified:
        print("[FAIL] 以下列未被分类，拒绝生成矩阵（fail-closed）：", file=sys.stderr)
        for c in unclassified:
            print("   - %s" % c, file=sys.stderr)
        print("请在 RULES 或 BULK_RULES 里显式分类（未确认定义的列写 poolable=False + why）",
              file=sys.stderr)
        return 2

    # ---- 逐列定 `poolable_batches` 与 `poolable` ----
    # 规则：**只有该列在 ≥2 个批次里都成立**才可并。
    #  * 起点 = in_batch（该列实际出现在哪些批次）；
    #  * **依赖扫描范围的列一律清空**（A 上界 35 vs C 上界 50 ⇒ 跨批比较无意义）；
    #  * A↔C 的原始量有**逐列复现证据**（6039 点，中位相对差 ~1e-12）⇒ 保留 {A, C}。
    for c, v in columns.items():
        inb = list(v["in_batch"])
        if c in RANGE_DEPENDENT:
            v["depends_on"] = "freq_range"
            v["range_note"] = ("取值依赖扫描频率**范围**（A: 5–35 MHz；C: 5–50 MHz）⇒ "
                               "不得跨批比较/统计；**必须在各自批次内重算**")
            pb, v["poolable"] = [], False
        elif c in A_C_REPRODUCED and {"A", "C"} <= set(inb):
            # **有逐列复现证据** ⇒ 证据优先于规则里的旧值（那些值是"C 出现之前"写的）
            pb = ["A", "C"]
            v["evidence"] = REPEAT_EVIDENCE
            v["evidence_path"] = REPEATABILITY
            v["poolable"] = True
        else:
            pb = inb
            v["poolable"] = bool(v.get("poolable")) and len(pb) >= 2
        v["poolable_batches"] = pb

    n_true = sum(1 for v in columns.values() if v["poolable"])
    matrix = {
        "kind": "column_merge_matrix",
        "created_utc": "2026-09-28",
        "ruling": {"feedback_id": "fb-20260923T110333Z-e0a59352", "verdict": "correct",
                   "content": "我做的是同一个模型，只是修改了参数扫描，名称不一样但是结构是一样的",
                   "settles": "结构/几何同源（据此类键改为 (base_model_id, configuration_id)）",
                   "does_not_settle": "输出列定义是否同一 ⇒ 值仍须逐列确认"},
        "semantics": {
            "poolable_true": ("该列在 `poolable_batches` 列出的批次之间**定义一致且有证据** "
                              "⇒ 允许合并比较"),
            "poolable_false": ("定义未确认、只有一批有、或**依赖扫描范围** ⇒ 统一表中该列在其它批次侧"
                              "**必须留空**；**禁止**跨批比较、统计与训练"),
            "poolable_batches": "该列可并的批次集合；长度 <2 ⇒ 不可并（单批列没有'合并'可言）",
            "depends_on=freq_range": ("该列的**定义**依赖扫描频率范围。数值层面 A↔C 可互认，"
                                      "但这些列本身随范围而变 ⇒ 必须按批重算，不得跨批比"),
            "rule": ("下游不得把 poolable=False 的列默认当作可并；缺失一律 NULL，"
                     "不插值、不用其他列伪造"),
        },
        "batches": {
            "A": {"name": "cell_te2_* 远端导出扫描（2026-09-22）", "n_combos": 223,
                  "freq_points": 61, "freq_range_MHz": [5, 35], "header_language": "zh",
                  "x_scale_values": 10, "x_step": 0.1, "N2": [3, 4, 6, 7, 8, 9]},
            "B": {"name": "b_GE_task3_2-newyizu GUI 扫描", "n_combos": 70, "freq_points": 7,
                  "freq_range_MHz": [5, 35], "header_language": "zh",
                  "note": "无声压；N_w_te2 不在表内（模型常量）"},
            "C": {"name": "cell_te2_* x 加密 + 频段 5–50 MHz（2026-09-28）", "n_combos": 1215,
                  "freq_points": 91, "freq_range_MHz": [5, 50], "header_language": "en",
                  "x_scale_values": 81, "x_step": 0.01, "N2": [5, 6, 7],
                  "artifact_sha256": {
                      "cell_te2_5_test_scal_0.2-1_0.01_freq5-50_v1.mph":
                          "6a930354002260a187b36b121ea96c2f561f41fa86aa47ffd988768edd79f1fd",
                      "cell_te2_6_test_scal_0.2-1_0.01_freq5-50_v1.mph":
                          "39cab857b8fbcd023d87dceb60b436ba5563583cad683105631be739f60442ee",
                      "cell_te2_7_test_scal_0.2-1_0.01_freq5-50_v1.mph":
                          "7d51febc4c05656b5e3966ef6b7a39ad863b2f609e568ce2bc2a05773c2b876f"},
                  "base_model_id": None, "base_model_id_status": "pending_sha256"},
        },
        "caliber_by_batch": {
            "criterion_point_m": [0.0, 0.0, -1e-05], "displacement_point_m": [0.0, 0.0, 1e-08],
            "spl_basis": "SPL[dB]=20log10(|p|/√2/20µPa)",
            "A_vs_C": ("判据点、SPL 基准、6 张表的数据列数（15/8/10/11/2/5）与列序**全部一致**；"
                       "差别只有①表头语言（zh→en，名义）②频率上界（35→50 MHz，**实质**）"),
        },
        "range_dependent_columns": sorted(RANGE_DEPENDENT),
        "range_dependent_reason": ("A 的扫描上界是 35 MHz、C 是 50 MHz。极值/端点/带宽/Q 这类量"
                                   "**由范围定义**：A 里 `peak_at_range_edge` 指'顶在 35'，"
                                   "C 里指'顶在 50'。实测 C 仍有 468/1215（38.5%）顶在 50 MHz 上界，"
                                   "A 有 80/223（35.9%）顶在 35 ⇒ 直接跨批比会得出错误结论。"),
        "anomalies": [{
            "kind": "single_combo_batch_disagreement",
            "combo": {"x_scale": 0.2, "N_w_te1": 1, "N_w_te2": 7},
            "observed": ("A↔C 6039 点中唯一实质不一致：SPL 在 5.0 MHz 处差 **6.51 dB**"
                         "（A 102.18021 / C 95.67125），差值随频率平滑衰减到 ~25 MHz；"
                         "26.5–35 MHz 处 C 比 A 高约 1.0–1.13 dB"),
            "neighbours_reproduce": ("同层邻点 (0.2,2,7)/(0.3,1,7) 与邻族 (0.2,1,6) 全部复现到 "
                                     "1e-11…1e-10 dB ⇒ **是单点异常，不是批间系统偏差**"),
            "action": "**查清前该组合不得参与任何合并统计**（未做原因推测）",
            "evidence": "work/runs/x-densify-20260928/anomaly_combo_0.2_1_7.json",
        }],
        "batch_C_positional_map": c_note,
        "one_to_one_evidence": {
            "overlap": {"x_scale": 0.1, "N_w_te1": 1, "N_w_te2": 9},
            "Vcenter_mps_ratio_A_over_B": {"mean": 16.3595, "min": 16.1784, "max": 16.6365,
                                           "spread_pct": 2.8,
                                           "reading": "近常数 ⇒ 测点/归一化差异，非结构差异；单调微漂移待解释"},
            "Vave_mps_ratio_A_over_B": {"mean": 0.9447, "min": 0.9438, "max": 0.9459,
                                        "spread_pct": 0.2,
                                        "reading": "近常数且散布极小 ⇒ 定义最可能相同，待确认取样面"},
            "A_overlap_with_C": {"n_common_combos": 99, "n_common_points": 6039,
                                 "columns_reproduced": len(A_C_REPRODUCED),
                                 "median_rel_diff": 1e-12,
                                 "path": REPEATABILITY,
                                 "reading": ("网格与求解设置未变（若随 fmax 改了，所有点都会漂，"
                                             "中位不可能在 1e-12）⇒ A↔C 的原始量可互认")},
        },
        "columns": columns,
        "summary": {
            "n_columns": len(columns),
            "n_poolable_true": n_true,
            "n_poolable_false": len(columns) - n_true,
            "input_poolable": sorted(k for k, v in columns.items()
                                     if v["axis"] == "input" and v["poolable"]),
            "output_poolable": sorted(k for k, v in columns.items()
                                      if v["axis"] == "output" and v["poolable"]),
            "quality_poolable": sorted(k for k, v in columns.items()
                                       if v["axis"] == "quality" and v["poolable"]),
            "output_poolable_by_batch": {k: columns[k]["poolable_batches"]
                                         for k in sorted(columns)
                                         if columns[k]["axis"] == "output" and columns[k]["poolable"]},
            "range_dependent_not_poolable": sorted(
                k for k, v in columns.items() if v.get("depends_on") == "freq_range"),
        },
    }
    if args.check:
        print("校验通过：%d 列全部分类；可并 %d / 不可并 %d"
              % (len(columns), n_true, len(columns) - n_true))
        return 0
    OUT.write_text(json.dumps(matrix, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote %s (%d B)" % (OUT.relative_to(REPO), OUT.stat().st_size))
    print("可并列（输入轴）:", matrix["summary"]["input_poolable"])
    print("可并列（输出轴）%d 个:" % len(matrix["summary"]["output_poolable"]),
          matrix["summary"]["output_poolable"] or "（无）")
    print("范围依赖而**不可并**的列 %d 个:" % len(matrix["summary"]["range_dependent_not_poolable"]))
    print("   ", ", ".join(matrix["summary"]["range_dependent_not_poolable"]))
    print("可并列（元数据）%d 个；不可并列合计 %d 个"
          % (len(matrix["summary"]["quality_poolable"]), matrix["summary"]["n_poolable_false"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
