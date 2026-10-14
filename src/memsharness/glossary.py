# -*- coding: utf-8 -*-
"""**数据字典**：把每个参数、每个结果名字讲清楚（**不做任何计算**）。

用途：用户要求「讲解各个参数和计算结果……不需要计算，只需要把每一个数据名称讲清楚」。
本模块只做三件事：
1. 维护「名字 → 它是什么/单位/口径/方向/在不在排名里/坑」的条目；
2. 把**原始表里的列名**（批 A 的 points/power/mech/combos、批 B 的 source_table）
   通过别名指到同一个解释上，避免同一物理量写两遍；
3. `coverage()` **自检**：真实表里的每一个列名是否都有解释 —— 缺一个就报出来。

⚠️ **诚实原则**（与红线 3「不猜测模型内部」一致）：
凡是**没有书面确认表达式/取样点**的量，条目标 `confirmed=False` 并在界面显示
「列名直译（口径未书面确认）」。宁可不解释死，也不编一个听起来对的解释。
"""
from __future__ import annotations

import csv
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
A_DIR = REPO / "work/runs/remote-exported-20260922/dataset"
LABELS = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"
B_TABLE = REPO / "work/runs/gui-sweep-20260912T113936Z-bd387a56/source_table.csv"

KIND_ORDER = ("参数", "驱动与口径", "首峰指标", "门禁与元数据", "原始通道（声域点）",
              "原始通道（全局声学）", "原始通道（结构/机械）", "派生幅值", "每伏灵敏度",
              "批 A 附加列", "批 B 附加列")
RANK_LABEL = {"formal": "正式目标（参与排名）", "gate": "只作门槛（不排名）",
              "constraint": "只作约束（永不排名）", "no": "不参与排名"}


def _e(zh, kind, unit, what, how, *, direction="none", ranking="no",
       confirmed=True, caveat="", aliases=(), where="") -> dict:
    return {"zh": zh, "kind": kind, "unit": unit, "what": what, "how": how,
            "direction": direction, "ranking": ranking, "confirmed": confirmed,
            "caveat": caveat, "aliases": list(aliases), "where": where}


# ---------------------------------------------------------------------------
# 条目：键 = **主表（multichannel_labels.csv）里的规范名**（参数另有其名）
# ---------------------------------------------------------------------------
ENTRIES: dict[str, dict] = {
    # ---------------- 参数 ----------------
    "x_scale": _e(
        "尺寸缩放系数 x_scale", "参数", "—",
        "把器件平面尺寸按倍数整体缩放的参数：1.0 = 原始尺寸，0.5 = 缩到一半。",
        "扫描变量本身（不是导出量）。批 A 取 0.1 步长（10 个值），批 C 取 0.01 步长（81 个值）。",
        where="两批都有；A 粗、C 细",
        caveat="两批的 x 密度不同 ⇒ **跨批比较必须分层**（A 粗网格会系统性扭曲趋势）。"),
    "N_w_te1": _e(
        "内外电极对数 N_w_te1", "参数", "对（整数）",
        "内圈电极的对数。它决定激励的**空间周期**，从而决定主要激发的模态。",
        "扫描变量。批 A 取 1–7；批 C 每层上限 = N_w_te2 − 1（层 N2=8 则 N1 最多 7）。",
        where="两批都有",
        caveat="**不是**任意值：`N1 ≥ N2` 的层在数据里根本不存在 ⇒ 代理会拒答这种请求。"),
    "N_w_te2": _e(
        "外电极对数 N_w_te2", "参数", "对（整数）",
        "外圈电极的对数（层号）。数据是按它**分层**组织的：一层 N2 一个扫描批。",
        "扫描变量。批 A ∈ {3,4,6,7,8,9}；批 C ∈ {5,6,7,8}（外加 N2=9 只有 1 个组合）。",
        where="两批都有",
        caveat="批 C 的每层 `N1 ≤ N2−1`；**N2=9 几乎没数据**（只有 (x=0.1,N1=1)）⇒ 代理对 N2=9 只能一步外推。"),

    # ---------------- 驱动与口径 ----------------
    "v_inner_V": _e(
        "内电极电位 v_inner_V", "驱动与口径", "V",
        "加在**内圈**电极上的电位（外圈为 0 V 参考地），是驱动电压差的来源。",
        "**用户裁定**：内 −1 V、外 0 V（不是「±1 V 的 2 V 反相驱动」）。",
        confirmed=True, where="写入产物列，供审计",
        caveat="我曾把它记成 2 V 并据此做了归一化 —— 已更正，ΔV=1 V。"),
    "v_outer_V": _e(
        "外电极电位 v_outer_V", "驱动与口径", "V",
        "加在外圈电极上的电位（0 V，即参考地）。",
        "用户裁定：外圈为 0 V 参考地（与内圈 −1 V 配对）。", where="写入产物列"),
    "delta_V_V": _e(
        "驱动电压差 ΔV", "驱动与口径", "V",
        "内外电极的电位差，灵敏度归一化的分母。",
        "ΔV = |v_outer − v_inner| = |0 −(−1)| = **1 V**。",
        where="写入产物列",
        caveat="因为 ΔV=1，线性量 ÷1、SPL 减 20·log10(1)=0 dB ⇒ **数值与原始相同**（但元数据必须留痕）。"),
    "normalization_formula": _e(
        "归一化公式（文本）", "驱动与口径", "—",
        "记录「单位电压响应」是怎么算出来的**文字说明**。",
        "例如「线性/ΔV；SPL − 20·log10(ΔV)」。",
        where="写入产物列", caveat="它是一段说明文字，不是数值列。"),

    # ---------------- 首峰指标 ----------------
    "f_peak_Hz": _e(
        "一阶峰频率 f_peak", "首峰指标", "Hz",
        "扫频曲线上**最低频的那个共振峰**所在的频率（本文所有指标都在这一个峰上取）。",
        "在 5–50 MHz 的 SPL 曲线上找第一个**内部局部极大**（两端不算）。",
        where="主表列", direction="none",
        caveat="它只取 87 个离散值（网格 0.5 MHz 量化），且**对 N2 几乎不敏感** ⇒ 易预测但区分度低。"),
    "peak_SPL_dB": _e(
        "峰值声压级 peak_SPL", "首峰指标", "dB (re 20 µPa)",
        "一阶峰处**声压级**，即「这个峰有多响」。",
        "SPL = 20·log10(|p|/√2 / 20 µPa)，= 主表 `spl_dB` 在 f_peak 处的值。",
        direction="max", ranking="no", where="主表列",
        caveat="无 L1 网格收敛 ⇒ 只能比趋势，不能当工程绝对值。"),
    "peak_displacement_m": _e(
        "峰值中心位移 peak_displacement", "首峰指标", "m",
        "一阶峰处**中心点的位移幅值**（器件振得多厉害）。",
        "= 主表 `abs_w_m` 在 f_peak 处的值（同一物理量的别名列）。",
        direction="max", ranking="no", where="主表列"),
    "f_lo_3dB_Hz": _e(
        "−3 dB 左（低频侧）截止频率", "首峰指标", "Hz",
        "从峰值往**低频**方向走，声压级掉 3 dB 时的频率。",
        "在相邻两个网格点之间**线性插值**到恰好等于（峰值 − 3 dB）的频率。",
        direction="none", where="主表列",
        caveat="若在扫描范围内找不到这个交点（峰贴边），该列为空且 `bandwidth_closed=false`。"),
    "f_hi_3dB_Hz": _e(
        "−3 dB 右（高频侧）截止频率", "首峰指标", "Hz",
        "从峰值往**高频**方向走，声压级掉 3 dB 时的频率。",
        "在峰值**右侧**相邻两网格点之间线性插值到（峰值 − 3 dB）。", direction="none", where="主表列",
        caveat="批 C 有 89 例右截止超出 50 MHz 上限 ⇒ 空值（严格 fail-closed）。"),
    "bandwidth_Hz": _e(
        "绝对 −3 dB 带宽", "首峰指标", "Hz",
        "峰的「宽度」：f_hi − f_lo（越大越好，表示能覆盖更宽的频段）。",
        "**正式口径**用单自由度谐振拟合：BW = f0/Q（拟合 RMSE 中位 0.0096 dB）。"
        "网格交点值另存在批 A 的 `bandwidth_3dB_Hz` 里供对照。",
        direction="max", ranking="formal", where="主表列",
        caveat="两套口径有**系统性约 20% 的标度差**（排序稳健、绝对值不稳）⇒ 引用必须注明口径。"),
    "Q_factor": _e(
        "品质因数 Q", "首峰指标", "—（无量纲）",
        "谐振的「尖锐程度」：Q 大 = 峰窄而高。",
        "由单自由度谐振模型拟合得到。", direction="none", ranking="gate",
        where="主表列",
        caveat="**只作门槛（2.5–3.5），从不参与排名**；且代理对它的预测**未优于抄相邻层**。"),
    "damping_ratio": _e(
        "阻尼比 ζ", "首峰指标", "—（无量纲）",
        "Q 的倒数关系量，物理上表示相对阻尼。",
        "ζ = 1/(2Q)（由 `Q_factor` 换算）。",
        direction="none", ranking="gate", where="主表列",
        caveat="与 Q 完全共线（同一信息的两种写法）⇒ 不能同时当两个独立判据用。"),
    "damping_ratio_report_only": _e(
        "阻尼比 ζ（仅报告用列）", "首峰指标", "—",
        "与 `damping_ratio` 数值相同，列名里**显式标注「仅报告」**以防被误用于排名。",
        "= 1/(2Q)，重复列出以便下游只看列名也不会误用。",
        direction="none", ranking="no", where="主表列"),
    "peak_closed": _e(
        "首峰是否闭合（布尔）", "首峰指标", "true/false",
        "峰值是否落在扫描窗口**内部**（两端截断的峰不算）。",
        "找到内部局部极大则为 true。", ranking="no", where="主表列",
        caveat="它说的是「峰在窗内」；带宽是否闭合是**另一个**标志 `bandwidth_closed`。"),

    # ---------------- 门禁与元数据 ----------------
    "bandwidth_closed": _e(
        "带宽是否闭合（布尔）", "门禁与元数据", "true/false",
        "左右 −3 dB 交点**都在**扫描范围内吗？",
        "f_lo 与 f_hi 都能插出来才是 true。",
        ranking="no", where="主表列",
        caveat="**不闭合时 BW/Q/ζ 一律为空、且不得进带宽排名**（严格 fail-closed）。"),
    "ranking_eligible": _e(
        "是否可排名（布尔）", "门禁与元数据", "true/false",
        "这条记录能不能进排名/Pareto。",
        "= `bandwidth_closed` ∧ `q_gate_pass`（两个条件同时成立）。",
        ranking="no", where="主表列",
        caveat="Pareto 与所有排名**只**用这一列为 true 的行（裁定 §10）。"),
    "q_gate_pass": _e(
        "是否过 Q 门槛（布尔）", "门禁与元数据", "true/false",
        "Q 是否落在合格区间内。",
        "2.5 ≤ Q ≤ 3.5（用户裁定）。",
        ranking="no", where="主表列",
        caveat="该门槛**只通过全体约 44%**——通过率低是事实，报告里必须把分母一起写出来。"),
    "q_gate_applicable": _e(
        "Q 门槛是否适用（布尔）", "门禁与元数据", "true/false",
        "这条记录有没有 Q 值可供判断门槛。",
        "Q 为空（带宽未闭合）时为 false。",
        ranking="no", where="主表列"),
    "q_gate_range": _e(
        "Q 门槛区间（文本）", "门禁与元数据", "—",
        "把门槛值**写进数据里**，免得下游去猜 2.5–3.5 从哪来。",
        "固定文本 `2.5-3.5`。", ranking="no", where="主表列"),
    "method": _e(
        "带宽/ Q 的求法（文本）", "门禁与元数据", "—",
        "这一行的带宽与 Q 是**怎么得到的**。",
        "本表为 `single_dof_fit`（单自由度谐振拟合）；无可用拟合时为 `none`。",
        ranking="no", where="主表列",
        caveat="口径必须随数一起给 —— 换口径的带宽不可直接比。"),
    "extrapolated": _e(
        "是否用了外推（布尔）", "门禁与元数据", "true/false",
        "该行的标签是否来自超出扫描范围的**外推**。",
        "本表全为 false（外推的行保持空标签，不给数）。",
        ranking="no", where="主表列"),
    "source_model": _e(
        "来源模型/目录", "门禁与元数据", "—",
        "这行数据是从哪个模型/目录导出的（可回溯）。",
        "批 A 为导出目录名；批 C 为 `镜像/cell_*`。",
        ranking="no", where="主表列",
        caveat="**跨批比较前必须看这一列**——它决定 x 密度与频段。"),
    "source_dataset": _e(
        "来源批次", "门禁与元数据", "A / C",
        "这行属于哪一批仿真（A = 2026-09-22 导出；C = 2026-09-28/29）。",
        "批次标签列（A 或 C），由导出批次写入，用于分层。", ranking="no", where="主表列",
        caveat="A 与 C 的 x 步长（0.1 vs 0.01）与频段（5–35 vs 5–50 MHz）不同 ⇒ **禁止混比**。"),
    "x_density_class": _e(
        "x 密度分级（文本）", "门禁与元数据", "—",
        "把「粗网格/细网格」写进列里，提醒下游必须分层。",
        "`coarse_0.1`（批 A）或 `fine_0.01`（批 C）。",
        ranking="no", where="主表列"),
    "freq_grid_MHz": _e(
        "扫描频段（文本）", "门禁与元数据", "—",
        "这行的频谱覆盖范围与点数。",
        "`5-35/61`（批 A）或 `5-50/91`（批 C）。",
        ranking="no", where="主表列",
        caveat="范围依赖量（带宽、峰位、是否贴边）**不能跨频段比**。"),
    "n_freq": _e(
        "频点数", "门禁与元数据", "个",
        "这行的频谱有多少个频点。", "批 A 61 个、批 C 91 个。",
        ranking="no", where="主表列"),
    "first_peak_found": _e(
        "是否找到一阶峰（布尔）", "门禁与元数据", "true/false",
        "这条组合在扫描窗内到底有没有一阶峰。",
        "有内部局部极大则 true。", ranking="no", where="主表列",
        caveat="为 false 的 170 个组合**全部集中在低 x 端（x ≤ 0.28）**⇒ 是一阶峰跑出窗口，不是「性能差」。"),
    "quarantined": _e(
        "是否已隔离（布尔）", "门禁与元数据", "true/false",
        "这条组合是否因**跨批比对异常**被隔离、不进主统计。",
        "`(x=0.2,N1=1,N2=7)` 与 `(0.2,1,8)` 两角点为 true。",
        ranking="no", where="主表列",
        caveat="**归因尚未定论**（证据指向批 A，但需 `mesh_fingerprint` 才能定）⇒ 只隔离、不宣称谁错。"),

    # ---------------- 原始通道：声域点 ----------------
    "spl_dB": _e(
        "声压级 SPL", "原始通道（声域点）", "dB (re 20 µPa)",
        "**判据点**上的声压级。",
        "SPL = 20·log10(p_rms / 20 µPa)；实测逐行验证 = 20·log10(|p|/√2/20 µPa)。",
        direction="max", ranking="no", where="A: points.csv `spl_dB`（第 15 列）",
        caveat="判据点位置两批**不完全相同**（A 在 z≈−10 µm）⇒ 跨批比 SPL 要先核对取样点。"),
    "p_rms_Pa": _e(
        "声压有效值 p_rms", "原始通道（声域点）", "Pa",
        "声压的均方根（有效值），= |p|/√2。",
        "列映射已核实：第 10 列复声压、第 11 列 p_rms = |p|/√2。",
        direction="max", ranking="no", where="A: points.csv"),
    "abs_p_Pa": _e(
        "声压幅值 |p|", "原始通道（声域点）", "Pa",
        "复声压的模（峰值幅值）。",
        "|p| = √(p_re² + p_im²)。", direction="max", ranking="no",
        where="A: points.csv `p_abs_Pa`；C: Table_9 第 9 列",
        caveat="**过零点附近相对误差会发散**⇒ 判定一律用 dB 绝对误差，相对误差只作诊断。"),
    "p_re_Pa": _e(
        "声压实部 p_re", "原始通道（声域点）", "Pa",
        "判据点处复声压的**实部**。它与虚部一起决定幅值（|p|）与相位。",
        "A: points.csv 第 10 列 `p_re`，直接导出（不是算出来的）。",
        ranking="no", where="A: points.csv 第 10 列"),
    "p_im_Pa": _e(
        "声压虚部 p_im", "原始通道（声域点）", "Pa",
        "判据点处复声压的**虚部**；含相位信息，单看它没有物理意义。",
        "A: points.csv 第 11 列 `p_im`，直接导出；幅值见 `abs_p_Pa`。",
        ranking="no", where="A: points.csv 第 11 列"),
    "v_tz_re_m_s": _e(
        "判据点速度实部 v_tz（re）", "原始通道（声域点）", "m/s",
        "判据点处**质点速度**的实部（与虚部一起构成复数速度）。",
        "A: points.csv 第 7 列 `v_tz_re`，直接导出。",
        ranking="no", where="A: points.csv 第 7 列"),
    "v_tz_im_m_s": _e(
        "判据点速度虚部 v_tz（im）", "原始通道（声域点）", "m/s",
        "判据点处质点速度的**虚部**；含相位信息，单看它没有物理意义。",
        "A: points.csv 第 8 列 `v_tz_im`，直接导出；幅值见 `abs_v_tz_m_s`。",
        ranking="no", where="A: points.csv 第 8 列"),
    "abs_v_tz_m_s": _e(
        "判据点速度幅值 |v_tz|", "原始通道（声域点）", "m/s",
        "判据点质点速度的模。", "|v_tz| = √(re² + im²)；两批都可用。",
        direction="max", ranking="no",
        where="A: points.csv（由 re/im 算）；C: Table_9 第 7 列"),

    # ---------------- 原始通道：全局声学 ----------------
    "p_total_re_N": _e(
        "全局声压量实部（p_total）", "原始通道（全局声学）", "N（按列名）",
        "在整个声学域上积分得到的**总声压相关量**的实部。",
        "直接导出列 `p_total_N`。", ranking="no", where="A: power.csv",
        confirmed=False,
        caveat="列名直译（口径未书面确认）：为何单位是 N（力）而非 Pa，**没有书面说明** ⇒ 不据此做物理解释。"),
    "p_total_im_N": _e(
        "全局声压量虚部（p_total）", "原始通道（全局声学）", "N（按列名）",
        "全局声压相关量的**虚部**；与 `p_total_re_N` 成对构成复数。",
        "A: power.csv 第 7 列 `p_total_im`，直接导出。",
        ranking="no", where="A: power.csv 第 7 列", confirmed=False,
        caveat="与实部同源：**为何单位是 N（力）而非 Pa 没有书面说明** ⇒ 只描述、不解释。"),
    "abs_p_total_N": _e(
        "全局声压量幅值 |p_total|", "原始通道（全局声学）", "N（按列名）",
        "全局声压相关量的模。", "√(re² + im²)。", direction="max", ranking="no",
        where="A: power.csv", confirmed=False),

    # ---------------- 原始通道：结构/机械 ----------------
    "vz_struct_re_m3s": _e(
        "结构体积速度实部", "原始通道（结构/机械）", "m³/s",
        "结构域上的**体积速度**（速度在场上的积分）的实部。",
        "A: mech.csv 的复数列 `v_z_m3s`；C: Table_11 / Zdisplacement。",
        ranking="no", where="A: mech.csv `v_z_m3s`",
        caveat="⚠️ 列里是**复数文本**（形如 `(a+bj)`）—— 曾用 `float()` 解析导致整列为空却被计为「已覆盖」。"),
    "vz_struct_im_m3s": _e(
        "结构体积速度虚部", "原始通道（结构/机械）", "m³/s",
        "结构体积速度的**虚部**（与实部一起构成复数）。",
        "A: mech.csv 复数文本列 `v_z_m3s` 的虚部；C: Table_11 / Zdisplacement。", ranking="no", where="A: mech.csv"),
    "abs_vz_struct_m3s": _e(
        "结构速度幅值 |vz|", "原始通道（结构/机械）", "m³/s",
        "结构体积速度的模。**裁定 §3.1 把它与位移、声压、SPL 并列为振幅判据**。",
        "|vz| = √(re² + im²)（由上面两列派生）。",
        direction="max", ranking="no", where="A/C 均可（派生列）"),
    "stress_zz_re_N": _e(
        "法向应力实部 σ_zz", "原始通道（结构/机械）", "N（按列名）",
        "z 方向法向应力的实部。", "A: mech.csv 复数列 `stress_zz_N`。",
        ranking="constraint", where="A: mech.csv", confirmed=False,
        caveat="按裁定 §3.4 **只作约束、永不排名**；单位按列名为 N（口径未书面确认）。"),
    "stress_zz_im_N": _e(
        "法向应力虚部 σ_zz", "原始通道（结构/机械）", "N（按列名）",
        "法向应力的**虚部**（与实部一起构成复数）。",
        "A: mech.csv 复数列 `stress_zz_N` 的虚部。", ranking="constraint",
        where="A: mech.csv", confirmed=False),
    "abs_stress_zz_N": _e(
        "法向应力幅值 |σ_zz|", "原始通道（结构/机械）", "N（按列名）",
        "法向应力的模（常用于判「会不会坏」）。", "√(re² + im²)。",
        direction="min", ranking="constraint", where="A/C 派生列", confirmed=False,
        caveat="方向是**越小越好**（作约束用），但它**不参与排名**。"),
    "sGp_du_W": _e(
        "结构能量相关量 sGp_du", "原始通道（结构/机械）", "W（按主表列名）",
        "结构域上一个与能量/功率相关的积分量。",
        "A: mech.csv 复数列 `sGp_du_Nms` 的模。",
        ranking="constraint", where="A: mech.csv", confirmed=False,
        caveat="⚠️ **单位名不一致**：原始列叫 `sGp_du_Nms`、主表叫 `sGp_du_W` ⇒ 以原始导出为准，未擅自换算。"),
    "u_du_m4s2": _e(
        "结构能量量 u_du", "原始通道（结构/机械）", "m⁴/s²（按列名）",
        "结构域的另一个能量相关实数量。", "A: mech.csv 第 9 列，直接导出（实数量）。",
        ranking="constraint", where="A: mech.csv", confirmed=False,
        caveat="列名直译（口径未书面确认）⇒ 只作约束，不解释物理含义。"),
    "disp_field_z_m3": _e(
        "位移场积分量 disp_field_z", "原始通道（结构/机械）", "m³（按列名）",
        "位移场在结构域上的**积分量**的模。",
        "A: mech.csv 复数列的模；C: Table_11 第 9 列。",
        ranking="no", where="A: mech.csv", confirmed=False,
        caveat="列名直译；它**不是**中心位移（中心位移见 `abs_w_m`）。"),
    "abs_w_m": _e(
        "中心位移幅值 |w|", "原始通道（结构/机械）", "m",
        "结构**中心点**的位移幅值（器件振得多厉害）。",
        "|w| = √(w_re² + w_im²)。正式目标之一。",
        direction="max", ranking="formal", where="A/C 派生列",
        caveat="代理对它**优于抄相邻层**（有增值）；`max` 误差 0.31(log10)≈2 倍，属局部热点。"),
    "w_re_m": _e(
        "中心位移实部 w_re", "原始通道（结构/机械）", "m",
        "中心位移的**实部**（含相位信息，与虚部成对）。", "A/C 直接导出列 `w_re_m`。", ranking="no", where="A/C"),
    "w_im_m": _e(
        "中心位移虚部 w_im", "原始通道（结构/机械）", "m",
        "中心位移的**虚部**（含相位信息，与实部成对）。", "A/C 直接导出列 `w_im_m`。", ranking="no", where="A/C"),
    "vv_m4s2": _e(
        "体积速度平方 vv", "原始通道（全局声学）", "m⁴/s²（按列名）",
        "体积速度相关的平方量（常与动能成正比）。",
        "直接导出列 `vv`。", ranking="no", where="A: power.csv", confirmed=False,
        caveat="列名直译：单位写作 m⁴/s² 与「体积速度的平方」（应是 m⁶/s²）**不自洽** ⇒ 不作物理解释。"),
    "pv_W_re": _e(
        "声功率实部 pv", "原始通道（全局声学）", "W",
        "声压×速度（声强/功率）相关量的**实部**，即有功能量那一部分。",
        "A: power.csv 第 10 列 `pv_W_re`，直接导出；幅值见 `abs_pv_W`。",
        ranking="constraint", where="A: power.csv 第 10 列",
        caveat="按裁定 §3.4 只作约束，**永不排名**。"),
    "pv_W_im": _e(
        "声功率虚部 pv", "原始通道（全局声学）", "W",
        "声功率相关量的**虚部**（无功功率那一部分）。",
        "A: power.csv 第 11 列，直接导出。", ranking="constraint", where="A: power.csv"),
    "abs_pv_W": _e(
        "声功率幅值 |pv|", "原始通道（全局声学）", "W",
        "声功率相关量的模（√(re² + im²)），用来看功率量级。", "√(re² + im²)。",
        direction="none", ranking="constraint", where="A/C 派生列",
        caveat="**只作约束**：可以拿来看「功率够不够」，但不得进排名（裁定 §3.4）。"),

    # ---------------- 每伏灵敏度 ----------------
    "abs_w_per_V_m": _e(
        "位移灵敏度 |w|/V", "每伏灵敏度", "m/V",
        "单位驱动电压下的中心位移（「每伏能振多少」）。",
        "= `abs_w_m` ÷ ΔV；ΔV=1 V ⇒ 数值与 `abs_w_m` 相同。",
        direction="max", ranking="no", where="主表列"),
    "abs_vz_struct_per_V_m3s": _e(
        "结构速度灵敏度 |vz|/V", "每伏灵敏度", "m³/s/V",
        "单位电压下的结构体积速度。**裁定 §3.3 明确要求给结构速度灵敏度**（不只是位移/声压）。",
        "= `abs_vz_struct_m3s` ÷ ΔV。", direction="max", ranking="no", where="主表列",
        caveat="此前整列缺失，是复盘时补上的。"),
    "abs_p_per_V_Pa": _e(
        "声压灵敏度 |p|/V", "每伏灵敏度", "Pa/V",
        "单位驱动电压下的声压幅值（正式目标之一）。",
        "= `abs_p_Pa` ÷ ΔV；ΔV=1 V ⇒ 数值与 `abs_p_Pa` 相同。",
        direction="max", ranking="formal", where="主表列",
        caveat="因 ΔV=1，它与 `abs_p_Pa` **完全同值**（不是两个独立证据）；`α=0.01` 半宽是 `α=0.05` 的 24 倍 ⇒ 尾部很重。"),
    "spl_per_V_dB": _e(
        "SPL 灵敏度 dB/V", "每伏灵敏度", "dB/V",
        "单位电压下的声压级。",
        "= `peak_SPL_dB` − 20·log10(ΔV)；ΔV=1 ⇒ 减去 0 dB。",
        direction="max", ranking="no", where="主表列"),

    # ---------------- 全局体积速度（与"结构体积速度"**不是**同一个量） ----------------
    "v_z_re_m3s": _e(
        "全局体积速度实部 v_z", "原始通道（全局声学）", "m³/s",
        "在**全局声学域**上取到的体积速度（速度在场上的积分）的实部。",
        "A: power.csv 的复数列 `v_z_m3s`（global）；C: Table_10。",
        ranking="no", where="A: power.csv；C: Table_10 第 5 列",
        caveat="⚠️ **不要与 `vz_struct_re_m3s`（结构域）混为一谈**：两者在原始表里都叫 "
               "`v_z_m3s`，却取自不同域 ⇒ 本字典按**表**区分解析。"),
    "v_z_im_m3s": _e(
        "全局体积速度虚部 v_z", "原始通道（全局声学）", "m³/s",
        "全局体积速度的**虚部**（与实部一起构成复数）。",
        "A: power.csv 复数列 `v_z_m3s` 的虚部。", ranking="no", where="A: power.csv"),

    # ---------------- 坐标轴本身 ----------------
    "freq_Hz": _e(
        "频率轴 freq", "参数", "Hz",
        "频谱的**自变量**：每个输出通道都是在这条频率轴上的一条曲线。",
        "批 A 5–35 MHz 共 61 点（0.5 MHz 步长）；批 C 5–50 MHz 共 91 点。",
        direction="none", ranking="no", where="各表都有",
        caveat="⚠️ 它**不是**一阶峰频率（峰频是 `f_peak_Hz`，是曲线上**取出来的一个点**）。"
               "范围依赖量（带宽/是否贴边）不能跨频段比较。"),
}

# ---------------------------------------------------------------------------
# 别名：**原始表里的列名** → 规范名（同一物理量不写两遍解释）
# ---------------------------------------------------------------------------
ALIASES: dict[str, tuple[str, str]] = {
    # (规范名, 出处说明)
    "model": ("source_model", "批 A points.csv：模型名"),
    "run": ("source_model", "各表：run 目录名"),
    "point_z_m": ("p_abs_Pa", "批 A：判据点的 z 坐标（−10 µm）"),
    "c_tz_cplx": ("p_abs_Pa", "批 A points.csv：复数耦合量（口径未确认）"),
    "p_re": ("p_re_Pa", "批 A points.csv：复声压实部"),
    "p_im": ("p_im_Pa", "批 A points.csv：复声压虚部"),
    "p_abs_Pa": ("abs_p_Pa", "批 A points.csv：|p|"),
    "v_tz_re": ("v_tz_re_m_s", "批 A points.csv"),
    "v_tz_im": ("v_tz_im_m_s", "批 A points.csv"),
    "p_total_N": ("p_total_re_N", "批 A power.csv：全局声压量实部"),
    "p_total_im": ("p_total_im_N", "批 A power.csv：全局声压量虚部"),
    "v_z_m3s": ("vz_struct_re_m3s", "批 A mech.csv / power.csv：**复数文本列**"),
    "vv": ("vv_m4s2", "批 A power.csv"),
    "pv_W_re": ("pv_W_re", "批 A power.csv"),
    "pv_W_im": ("pv_W_im", "批 A power.csv"),
    "stress_zz_N": ("stress_zz_re_N", "批 A mech.csv：复数列"),
    "sGp_du_Nms": ("sGp_du_W", "批 A mech.csv：复数列（单位名与主表不一致）"),
    "area_m2": ("abs_w_m", "批 A mech.csv：面积（口径未确认，仅描述）"),
    "src": ("source_model", "批 A mech.csv：该行来自 Table_11 还是 Zdisplacement"),
    "disp_z_m": ("disp_field_z_m3", "批 A mech.csv：位移实数量"),
    # 批 A combos.csv 的派生列（我们**不用**它们做正式口径，但名字要讲清）
    "spl_max_dB": ("peak_SPL_dB", "批 A combos.csv：全扫频**最大** SPL（不是一阶峰）"),
    "f_peak_Hz": ("f_peak_Hz", "批 A combos.csv：**全扫频最大峰**的频位（与本文「一阶峰」常不是同一个峰）"),
    "peak_at_range_edge": ("f_peak_Hz", "批 A combos.csv：峰是否顶在扫描上界（截断）"),
    "spl_at_fmin_dB": ("spl_dB", "批 A combos.csv：扫描下限处的 SPL"),
    "spl_at_fmax_dB": ("spl_dB", "批 A combos.csv：扫描上限处的 SPL"),
    "n_local_maxima": ("peak_closed", "批 A combos.csv：局部极大个数"),
    "f_high_3dB_Hz": ("f_hi_3dB_Hz", "批 A combos.csv：右截止（**批 A 自带口径**）"),
    "f_low_3dB_Hz": ("f_lo_3dB_Hz", "批 A combos.csv：左截止（批 A 自带口径）"),
    "bandwidth_3dB_Hz": ("bandwidth_Hz", "批 A combos.csv：**由网格点**求的带宽（外部对照口径之一）"),
    "q_from_points": ("Q_factor", "批 A combos.csv：由网格点求的 Q（外部对照口径之一）"),
    "bandwidth_not_closed": ("bandwidth_closed", "批 A combos.csv：带宽未闭合标志"),
    "bandwidth_marker_Hz": ("bandwidth_Hz", "批 A combos.csv：由 **marker 表**求的带宽（外部对照口径之二）"),
    "q_marker": ("Q_factor", "批 A combos.csv：由 marker 表求的 Q"),
    "f_peak_marker_Hz": ("f_peak_Hz", "批 A combos.csv：marker 表给的峰频"),
    "spl_max_marker_dB": ("peak_SPL_dB", "批 A combos.csv：marker 表给的峰值 SPL"),
    "n_marker_crossings": ("f_hi_3dB_Hz", "批 A combos.csv：−3 dB 电平被穿越的次数"),
    "flags": ("ranking_eligible", "批 A combos.csv：旗标串（含多个判定标志）"),
    "freq_min_Hz": ("freq_grid_MHz", "批 A combos.csv：扫描下限"),
    "freq_max_Hz": ("freq_grid_MHz", "批 A combos.csv：扫描上限"),
    # 批 B
    "freq (Hz)": ("freq_Hz", "批 B：扫描频率（Hz）"),
    "Ptot (W)": ("abs_pv_W", "批 B：总功率（W）"),
    "Zin1_R (Ω)": ("abs_pv_W", "批 B：输入阻抗实部（内电极）"),
    "Zin1_X (Ω)": ("abs_pv_W", "批 B：输入阻抗虚部（内电极）"),
    "Zin2_R (Ω)": ("abs_pv_W", "批 B：输入阻抗实部（外电极）"),
    "Zin2_X (Ω)": ("abs_pv_W", "批 B：输入阻抗虚部（外电极）"),
    "Vave (m/s)": ("vz_struct_re_m3s", "批 B：体积平均速度（与 A 的体积速度形状一致、比值恒定 0.15%）"),
    "V_center (m/s)": ("vz_struct_re_m3s", "批 B：中心速度（**复数**，导出格式不一致）"),
}


def _columns(path: pathlib.Path, encoding: str = "utf-8", skip: int = 0) -> list[str]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding=encoding, errors="replace").splitlines()
    if len(lines) <= skip:
        return []
    head = lines[skip]
    if head.startswith("% "):
        head = head[2:]
    return [h.strip() for h in next(csv.reader([head])) if h.strip()]


def real_columns() -> dict[str, list[str]]:
    """真实表里的列名清单（**覆盖率自检的输入**）。"""
    out = {
        "multichannel_labels.csv": _columns(LABELS),
        "A/points.csv": _columns(A_DIR / "points.csv"),
        "A/power.csv": _columns(A_DIR / "power.csv"),
        "A/mech.csv": _columns(A_DIR / "mech.csv"),
        "A/combos.csv": _columns(A_DIR / "combos.csv"),
        "B/source_table.csv": _columns(B_TABLE, encoding="utf-8-sig", skip=4),
    }
    return out


#: **同名不同表**的列：`v_z_m3s` 在 `power.csv`（全局声学）与 `mech.csv`（结构域）里
#: 都出现，但**不是同一个量**。按表优先解析，避免"用一条解释覆盖两处"的静默错误。
TABLE_ALIASES: dict[tuple[str, str], tuple[str, str]] = {
    ("A/power.csv", "v_z_m3s"): ("v_z_re_m3s", "批 A power.csv：**全局**体积速度（复数列）"),
    ("A/mech.csv", "v_z_m3s"): ("vz_struct_re_m3s", "批 A mech.csv：**结构域**体积速度（复数列）"),
}


def resolve(name: str, table: str | None = None) -> tuple[str | None, str]:
    """把任意名字解析到规范条目；返回 (规范名, 出处说明)。

    `table` 用于消解**同名不同表**的歧义（见 `TABLE_ALIASES`）。
    """
    if table is not None and (table, name) in TABLE_ALIASES:
        return TABLE_ALIASES[(table, name)]
    if name in ENTRIES:
        return name, (ENTRIES[name]["where"] or "主表/参数")
    if name in ALIASES:
        canon, where = ALIASES[name]
        return canon, where
    return None, ""


def coverage() -> dict:
    """**自检**：真实表里的每个列名是否都有解释。缺一个就列出来。"""
    missing, seen, per_table = [], set(), {}
    for table, cols in real_columns().items():
        rows = []
        for c in cols:
            canon, where = resolve(c, table)
            rows.append({"column": c, "canonical": canon, "where": where,
                         "explained": canon is not None})
            if canon is None:
                missing.append("%s :: %s" % (table, c))
            seen.add(c)
        per_table[table] = {"n_columns": len(cols),
                            "n_explained": sum(1 for r in rows if r["explained"]),
                            "unexplained": [r["column"] for r in rows if not r["explained"]]}
    unconfirmed = sorted(k for k, v in ENTRIES.items() if not v["confirmed"])
    return {
        "n_distinct_column_names": len(seen),
        "n_canonical_entries": len(ENTRIES),
        "n_aliases": len(ALIASES),
        "per_table": per_table,
        "missing": missing,
        "n_missing": len(missing),
        "unconfirmed_entries": unconfirmed,
        "verdict": ("**每个真实列名都有解释**（0 处遗漏）" if not missing
                    else "**有 %d 处列名没有解释**：%s" % (len(missing), missing)),
    }


def sections() -> list[dict]:
    """按类别整理成页面用的结构。"""
    buckets: dict[str, list[dict]] = {}
    for name, e in ENTRIES.items():
        item = {"name": name, **e}
        buckets.setdefault(e["kind"], []).append(item)
    order = [k for k in KIND_ORDER if k in buckets] + [k for k in sorted(buckets)
                                                       if k not in KIND_ORDER]
    out = []
    for k in order:
        items = sorted(buckets[k], key=lambda d: (not d["confirmed"], d["name"]))
        out.append({"kind": k, "n": len(items), "items": items})
    return out


def payload() -> dict:
    """给前端的整包（**不做任何计算**，纯解释）。

    ⚠️ `sections()` **只能调用一次**：它每次返回**新对象**。若"装饰一份、返回另一份"，
    装饰（别名清单 / 排名标签）就会丢失 —— 实测被用例抓到 `KeyError: 'ranking_label'`。
    """
    secs = sections()
    for sec in secs:
        for it in sec["items"]:
            it["alias_in_tables"] = sorted(
                [a for a, (c, _w) in ALIASES.items() if c == it["name"]] + list(it["aliases"]))
            it["ranking_label"] = RANK_LABEL.get(it["ranking"], it["ranking"])
    return {
        "kind": "data_glossary",
        "no_computation": ("本页**不做任何计算**：只解释每个名字是什么、单位、口径、"
                           "在不在排名里、以及已知的坑。"),
        "ranking_legend": RANK_LABEL,
        "coverage": coverage(),
        "sections": secs,
    }
