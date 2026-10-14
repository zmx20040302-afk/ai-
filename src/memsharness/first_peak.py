# -*- coding: utf-8 -*-
"""一阶峰标签表的数据访问层（供网页 Pareto 图与参数敏感性热力图使用）。

数据来源：`work/runs/first-peak-20260929/multichannel_labels.csv`
（**超集表**：含"无局部极大"的组合并标 `first_peak_found=False`；A 223 + C 1782 = 2005 行）

硬约束（来自用户裁定，**不是可选项**）：
* **Pareto 前沿只允许放 `bandwidth_closed=true` 且 `ranking_eligible=true` 的组合**
  （裁定 §10：不得把没有闭合带宽的组合放入正式 Pareto 前沿）；
* Q 与 ζ **只作门槛**：`q_gate_pass` 已含在 `ranking_eligible` 里；ζ 仅报告，不与 Q 重复计权；
* 正式排名量只有三组：**绝对 −3 dB 带宽、振幅、单位电压灵敏度**；
* 跨批（A 0.1 步长 / C 0.01 步长，A 5–35 MHz / C 5–50 MHz）**必须按批次分层**，
  不得混在一张趋势图里 —— 本模块所有函数都要求显式给 `batch`。

⚠️ 本模块只读 CSV，不写任何文件。
"""
from __future__ import annotations

import csv
import math
import pathlib
from functools import lru_cache

REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_CSV = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"

#: 可供前端选择的指标（名称 → 中文标签 + 方向）
#: 方向 `max` = 越大越好；`none` = **只作门槛/报告，不参与排名**（用户裁定 §3.2/§10）
METRICS = {
    "bandwidth_Hz": ("绝对 −3 dB 带宽 (Hz)", "max"),
    "abs_w_m": ("中心位移幅值 |w| (m)", "max"),
    # 裁定 §3.1 把**结构速度幅值**与位移、声压、SPL 并列为振幅判据 ⇒ 必须可选
    "abs_vz_struct_m3s": ("结构速度幅值 |vz| (m³/s)", "max"),
    "abs_p_Pa": ("声压幅值 |p| (Pa)", "max"),
    "peak_SPL_dB": ("峰值 SPL (dB)", "max"),
    "abs_w_per_V_m": ("位移灵敏度 |w|/V (m/V)", "max"),
    # 裁定 §3.3 明确要求结构速度灵敏度（不只是位移/声压）
    "abs_vz_struct_per_V_m3s": ("结构速度灵敏度 |vz|/V (m³/s/V)", "max"),
    "abs_p_per_V_Pa": ("声压灵敏度 |p|/V (Pa/V)", "max"),
    "spl_per_V_dB": ("SPL 灵敏度 (dB re 20µPa/V)", "max"),
    # 裁定 §3.2 的左右 −3 dB 截止：**不排名**，但要能看、能画（且未闭合时为空）
    "f_lo_3dB_Hz": ("−3 dB 左截止频率 (Hz)", "none"),
    "f_hi_3dB_Hz": ("−3 dB 右截止频率 (Hz)", "none"),
    "Q_factor": ("Q 因子（**仅门槛/报告**）", "none"),
    "damping_ratio_report_only": ("阻尼比 ζ（**仅报告**）", "none"),
    "f_peak_Hz": ("首个可观测局部峰频率 (Hz)", "none"),
}
#: 正式排名的三组量（裁定）—— Pareto 默认用这三组
FORMAL_OBJECTIVES = ("bandwidth_Hz", "abs_w_m", "abs_p_per_V_Pa")
#: 裁定 §3 的四类判据 → 本模块可提供的指标（供 `ruling_coverage()` 自检，
#: 防止「表里有列、数据层却取不到」这种半截完备）
RULING_GROUPS = {
    "§3.1 振幅": ("abs_w_m", "abs_vz_struct_m3s", "abs_p_Pa", "peak_SPL_dB"),
    "§3.2 带宽": ("bandwidth_Hz", "f_lo_3dB_Hz", "f_hi_3dB_Hz", "Q_factor",
                   "damping_ratio_report_only", "f_peak_Hz"),
    "§3.3 灵敏度": ("abs_w_per_V_m", "abs_vz_struct_per_V_m3s", "abs_p_per_V_Pa",
                     "spl_per_V_dB"),
}
#: 裁定 §3.4：功率/应力/能量**只作约束，永不参与排名** ⇒ 不放进 METRICS（进不了 Pareto/热图），
#: 只在下游做约束筛选时按列名直接取用。
CONSTRAINT_ONLY = ("abs_pv_W", "abs_stress_zz_N", "sGp_du_W", "u_du_m4s2")

#: 每个指标的**基本单位**（只给单位名，**不给缩放因子**）。
#: 前端用工程记数法自适应换算（Hz→MHz、m→nm、Pa→kPa…），
#: 这样界面显示的是人读得懂的量级，又不会因为我写错 1e-6/1e-9 而算错数。
#: `—` 表示无量纲（Q、ζ）。
UNITS = {
    "bandwidth_Hz": "Hz", "abs_w_m": "m", "abs_vz_struct_m3s": "m³/s",
    "abs_p_Pa": "Pa", "peak_SPL_dB": "dB", "abs_w_per_V_m": "m/V",
    "abs_vz_struct_per_V_m3s": "m³/s/V", "abs_p_per_V_Pa": "Pa/V",
    "spl_per_V_dB": "dB/V", "f_lo_3dB_Hz": "Hz", "f_hi_3dB_Hz": "Hz",
    "Q_factor": "—", "damping_ratio_report_only": "—", "f_peak_Hz": "Hz",
}
#: 无量纲/对数量：**不做工程记数法换算**（否则 "3.5 k—" 这种荒谬输出）
NO_PREFIX_UNITS = ("—", "dB", "dB/V")


def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _bool(x) -> bool:
    return str(x).strip().lower() in ("true", "1", "yes")


@lru_cache(maxsize=4)
def load(path: str | None = None) -> tuple[dict, ...]:
    """读多通道标签表（超集）。返回 tuple of dict（可哈希缓存）。"""
    p = pathlib.Path(path) if path else DEFAULT_CSV
    if not p.is_file():
        raise FileNotFoundError("缺少一阶峰标签表：%s（先跑 build_multichannel_labels.py）" % p)
    rows = []
    with p.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            d = {
                "source_dataset": r["source_dataset"],
                "x_density_class": r.get("x_density_class", "?"),
                "x_scale": _num(r["x_scale"]), "N_w_te1": _num(r["N_w_te1"]),
                "N_w_te2": _num(r["N_w_te2"]),
                "freq_grid_MHz": r.get("freq_grid_MHz"),
                "first_peak_found": _bool(r["first_peak_found"]),
                "bandwidth_closed": _bool(r["bandwidth_closed"]),
                "ranking_eligible": _bool(r["ranking_eligible"]),
                "q_gate_pass": None if r.get("q_gate_pass") in ("", "None", None)
                else _bool(r["q_gate_pass"]),
                "quarantined": _bool(r.get("quarantined", "False")),
                "delta_V_V": _num(r.get("delta_V_V")),
                "v_inner_V": _num(r.get("v_inner_V")),
                "v_outer_V": _num(r.get("v_outer_V")),
            }
            for m in METRICS:
                d[m] = _num(r.get(m))
            rows.append(d)
    return tuple(rows)


def ruling_coverage() -> dict:
    """裁定 §3 各类判据在**数据层**是否可取（防止「表里有列、代码取不到」的半截完备）。

    ⚠️ **分母必须是「该量有定义」的行**，不能拿全表当分母（2026-09-29 实测）：
    * 振幅/灵敏度只在**找到首峰**的组合上有定义（无峰 ⇒ 本就该为空）；
    * 带宽/Q/左右截止只在**带宽闭合**的组合上有定义（未闭合 ⇒ 本就该为空）。
    第一版拿全表当分母 ⇒ 把这些**预期的空**报成 3 项缺口，是永久性假警报。
    """
    _guard = load()          # 表不存在时在此 fail-closed（而不是静默给出 0 缺口）
    cols: set[str] = set()
    if DEFAULT_CSV.is_file():
        with DEFAULT_CSV.open(encoding="utf-8", newline="") as fh:
            rd = csv.DictReader(fh)
            cols = set(rd.fieldnames or [])
            data = list(rd)
    else:
        data = []
    peaked = [r for r in data if str(r.get("first_peak_found")).lower() == "true"]
    closed = [r for r in data if str(r.get("bandwidth_closed")).lower() == "true"]
    #: 每个指标「有定义」的行的集合
    pop = {"abs_w_m": peaked, "abs_vz_struct_m3s": peaked, "abs_p_Pa": peaked,
           "peak_SPL_dB": peaked, "abs_w_per_V_m": peaked,
           "abs_vz_struct_per_V_m3s": peaked, "abs_p_per_V_Pa": peaked,
           "spl_per_V_dB": peaked, "f_peak_Hz": peaked,
           "bandwidth_Hz": closed, "f_lo_3dB_Hz": closed, "f_hi_3dB_Hz": closed,
           "Q_factor": closed, "damping_ratio_report_only": closed}
    groups, gaps = {}, []
    for name, keys in RULING_GROUPS.items():
        miss_code = [k for k in keys if k not in METRICS]
        miss_col = [k for k in keys if k not in cols]
        rates = {}
        for k in keys:
            if k not in cols:
                continue
            denom = pop.get(k, data)
            if not denom:
                rates[k] = 0.0
                gaps.append("%s 的 %s 无任何有定义的行（分母 0）" % (name, k))
                continue
            filled = sum(1 for r in denom
                         if str(r.get(k, "")).strip() not in ("", "None"))
            rate = filled / len(denom)
            rates[k] = round(rate, 4)
            if rate < 0.99:
                gaps.append("%s 的 %s 在「有定义」的行上仍有 %.1f%% 为空"
                            % (name, k, 100 * (1 - rate)))
        groups[name] = {"metrics": list(keys), "未进METRICS": miss_code,
                        "表中缺列": miss_col,
                        "有定义行上的填充率": rates,
                        "分母定义": "找到首峰的行" if name.startswith("§3.1")
                        or name.startswith("§3.3") else "带宽闭合的行（f_peak_Hz 用首峰行）"}
        if miss_code:
            gaps.append("%s 未进 METRICS：%s" % (name, miss_code))
        if miss_col:
            gaps.append("%s 表中缺列：%s" % (name, miss_col))
    cc = {k: (k in cols) for k in CONSTRAINT_ONLY}
    if not all(cc.values()):
        gaps.append("§3.4 约束列缺失：%s" % [k for k, v in cc.items() if not v])
    return {
        "n_rows": len(data), "n_rows_first_peak": len(peaked),
        "n_rows_bandwidth_closed": len(closed),
        "groups": groups,
        "constraint_only_present": cc,
        "constraint_only_rule": ("§3.4 的功率/应力/能量**只作约束、永不排名** ⇒ "
                                 "刻意不进 METRICS（不会被 Pareto/热图选中）"),
        "gaps": gaps,
        "verdict": ("**裁定 §3 四类判据在数据层全部可取**（空值只出现在「无首峰/带宽未闭合」这些"
                    "本就该为空的行上）" if not gaps else "**存在 %d 项缺口**" % len(gaps)),
    }


def summary(rows=None) -> dict:
    rows = list(rows if rows is not None else load())
    by = {}
    for b in sorted({r["source_dataset"] for r in rows}):
        s = [r for r in rows if r["source_dataset"] == b]
        by[b] = {
            "n_rows": len(s),
            "x_density_class": sorted({r["x_density_class"] for r in s}),
            "freq_grid": sorted({str(r["freq_grid_MHz"]) for r in s}),
            "n_first_peak": sum(1 for r in s if r["first_peak_found"]),
            "n_no_peak": sum(1 for r in s if not r["first_peak_found"]),
            "n_bandwidth_closed": sum(1 for r in s if r["bandwidth_closed"]),
            "n_q_gate_pass": sum(1 for r in s if r["q_gate_pass"]),
            "n_ranking_eligible": sum(1 for r in s if r["ranking_eligible"]),
            "n_quarantined": sum(1 for r in s if r["quarantined"]),
        }
    layers = {}
    for r in rows:
        layers.setdefault("%g" % r["N_w_te2"], {}).setdefault(r["source_dataset"], 0)
        layers["%g" % r["N_w_te2"]][r["source_dataset"]] += 1
    return {
        "n_rows": len(rows), "by_batch": by, "layers": layers,
        "metrics": {k: v[0] for k, v in METRICS.items()},
        "formal_objectives": list(FORMAL_OBJECTIVES),
        "metric_directions": {k: v[1] for k, v in METRICS.items()},
        "metric_units": dict(UNITS),
        "no_prefix_units": list(NO_PREFIX_UNITS),
        "ruling_coverage": ruling_coverage(),
        "constraint_only": list(CONSTRAINT_ONLY),
        "pareto_rule": ("**只放 `bandwidth_closed=true` 且 `ranking_eligible=true` 的组合**"
                        "（用户裁定 §10）；Q/ζ 只作门槛，不参与排名"),
        "cross_batch_rule": ("A 与 C 的 x 密度与频段不同 ⇒ **必须按批次分层**；"
                             "本页所有图表的 `batch` 参数为必填"),
    }


def _dominates(a: dict, b: dict, objectives) -> bool:
    ge = all((a[o] is not None and b[o] is not None and a[o] >= b[o]) for o in objectives)
    gt = any((a[o] is not None and b[o] is not None and a[o] > b[o]) for o in objectives)
    return ge and gt


#: 允许的筛选键（**未知键必须报错**，不得静默忽略——静默忽略会让人以为"筛过了"）
FILTER_KEYS = ("x_min", "x_max", "n1_min", "n1_max", "n2")


def parse_filter(q: dict) -> tuple[dict, str | None]:
    """把查询参数解析成筛选条件。返回 (flt, 错误信息)。

    只认 `FILTER_KEYS`；出现未知键一律报错（**fail-closed**）。
    原因：`heatmap?n1=3` 曾经被**静默忽略**并照常返回全部数据 ⇒ 用户以为筛过了。
    """
    unknown = sorted(set(q) - set(FILTER_KEYS))
    if unknown:
        return {}, ("不支持的参数 %s；可用参数：%s" % (unknown, list(FILTER_KEYS)))
    flt: dict = {}
    for k, cast in (("x_min", float), ("x_max", float),
                    ("n1_min", float), ("n1_max", float), ("n2", float)):
        v = q.get(k)
        if v in (None, ""):
            continue
        try:
            flt[k] = cast(v)
        except (TypeError, ValueError):
            return {}, "参数 %s 不是数字：%r" % (k, v)
    for a, b in (("x_min", "x_max"), ("n1_min", "n1_max")):
        if a in flt and b in flt and flt[a] > flt[b]:
            return {}, "%s(%s) 大于 %s(%s)" % (a, flt[a], b, flt[b])
    return flt, None


def _apply_filter(rows: list, flt: dict | None) -> list:
    """按条件过滤行。`flt` 为空 ⇒ 原样返回（**无筛选**）。"""
    if not flt:
        return list(rows)
    out = list(rows)
    if "x_min" in flt:
        out = [r for r in out if r.get("x_scale") is not None and r["x_scale"] >= flt["x_min"]]
    if "x_max" in flt:
        out = [r for r in out if r.get("x_scale") is not None and r["x_scale"] <= flt["x_max"]]
    if "n1_min" in flt:
        out = [r for r in out if r.get("N_w_te1") is not None and r["N_w_te1"] >= flt["n1_min"]]
    if "n1_max" in flt:
        out = [r for r in out if r.get("N_w_te1") is not None and r["N_w_te1"] <= flt["n1_max"]]
    if "n2" in flt:
        out = [r for r in out if r.get("N_w_te2") == flt["n2"]]
    return out


def filter_label(flt: dict | None) -> str:
    """给筛选条件一句人话描述；**没有筛选时必须明说"无筛选=全局"**。

    这句必须出现在图/表旁边：筛选后 Pareto 池会变小、前沿更容易"全占优"，
    不写明条件就会被误读成全局最优。
    """
    if not flt:
        return "无筛选（全部 x、N1、N2）⇒ 这是**全局**口径"
    bits = []
    if "x_min" in flt or "x_max" in flt:
        bits.append("x ∈ [%s, %s]" % (flt.get("x_min", "—"), flt.get("x_max", "—")))
    if "n1_min" in flt or "n1_max" in flt:
        bits.append("N1 ∈ [%s, %s]" % (flt.get("n1_min", "—"), flt.get("n1_max", "—")))
    if "n2" in flt:
        bits.append("N2 = %g" % flt["n2"])
    return "筛选：" + "，".join(bits)


def pareto(batch: str, objectives=None, rows=None, flt: dict | None = None) -> dict:
    """Pareto 前沿（**最大化**所有目标）。只纳入可排名的组合。

    ⚠️ 传入 `flt`（筛选）时，得到的是**条件前沿**（筛选后池内的非支配集），
    不等于全局前沿；返回里带 `is_conditional` 与 `filter_label` 供界面显式标注。
    """
    objs = tuple(objectives or FORMAL_OBJECTIVES)
    for o in objs:
        if o not in METRICS:
            return {"error": "未知指标：%s（可选 %s）" % (o, sorted(METRICS))}
    rows = list(rows if rows is not None else load())
    batch_rows = [r for r in rows if r["source_dataset"] == batch]
    # 漏斗：在**筛选后**的批内数据上算，保证各步之和 = 批内总数（可自检）
    rows_f = _apply_filter(batch_rows, flt)
    pool = [r for r in rows_f if r["ranking_eligible"]
            and all(r.get(o) is not None for o in objs)]
    excluded = {
        "batch_total": len(batch_rows),
        "after_filter": len(rows_f),
        "filtered_out": len(batch_rows) - len(rows_f),
        "not_first_peak": sum(1 for r in rows_f if not r["first_peak_found"]),
        "bandwidth_not_closed": sum(1 for r in rows_f if r["first_peak_found"]
                                    and not r["bandwidth_closed"]),
        "q_gate_failed": sum(1 for r in rows_f if r["bandwidth_closed"]
                             and r["q_gate_pass"] is False),
        "missing_objective_value": sum(1 for r in rows_f if r["ranking_eligible"]
                                       and any(r.get(o) is None for o in objs)),
    }
    front = []
    for a in pool:
        if not any(_dominates(b, a, objs) for b in pool if b is not a):
            front.append(a)
    keep = ("x_scale", "N_w_te1", "N_w_te2", "f_peak_Hz", "Q_factor", "q_gate_pass") + objs
    is_cond = bool(flt)
    return {
        "batch": batch, "objectives": list(objs),
        "objective_labels": [METRICS[o][0] for o in objs],
        "n_pool": len(pool), "n_front": len(front), "excluded": excluded,
        "filter": dict(flt or {}), "filter_label": filter_label(flt),
        "is_conditional": is_cond,
        "front_scope": ("**条件前沿**：仅在上述筛选条件下、池内非支配；"
                        "**不等于全局前沿**，不可当作全局最优" if is_cond
                        else "**全局前沿**：对全部 x/N1/N2 组合计算"),
        "front": [{k: r.get(k) for k in keep} for r in front],
        "all": [{k: r.get(k) for k in keep} for r in pool],
        "rule": "Pareto 前沿：任一目标都不差、且至少一个更好者才被支配；只纳入 ranking_eligible",
    }


def heatmap(batch: str, metric: str, n2: float | None = None, rows=None,
            flt: dict | None = None) -> dict:
    """参数敏感性热力图：`(x_scale × N_w_te1)` 网格上的某个指标（**按批次**）。

    网格的两个轴就是 x 与 N1，所以筛选 x/N1 会**裁掉网格的行列**（轴相应变短）；
    筛选 N2 则是取其中一层。`n2` 参数与 `flt['n2']` 等价（前者为兼容旧调用保留）。
    """
    if metric not in METRICS:
        return {"error": "未知指标：%s" % metric}
    merged = dict(flt or {})
    if n2 is not None:
        merged["n2"] = n2
    rows = list(rows if rows is not None else load())
    batch_rows = [r for r in rows if r["source_dataset"] == batch]
    rows_f = _apply_filter(batch_rows, merged)
    sel = [r for r in rows_f if r["first_peak_found"] and r.get(metric) is not None]
    if not sel:
        return {"error": "该筛选/批次下没有可用数据（batch=%s，metric=%s，%s）"
                         "——放宽筛选范围、换个指标，或换批次/清空筛选即可恢复出图"
                         % (batch, metric, filter_label(merged))}
    xs = sorted({r["x_scale"] for r in sel})
    n1s = sorted({r["N_w_te1"] for r in sel})
    ix = {v: i for i, v in enumerate(xs)}
    iy = {v: i for i, v in enumerate(n1s)}
    # ⚠️ **不许"最后一层覆盖"**（2026-09-29 改）：不给 n2 时同一 (x,N1) 可能有多层，
    #    原来的 `z[i][j] = r[metric]` 会让**层序隐式决定**格值，且丢信息
    #    （实测 N2=8 那批：有效行 1523 而格数只有 539）。现在改为**取均值**，
    #    并同时给出每格的**层数**与**层间跨度**，让"这一格是多层平均"这件事可见。
    cells: list[list[list[float]]] = [[[] for _ in n1s] for _ in xs]
    for r in sel:
        cells[ix[r["x_scale"]]][iy[r["N_w_te1"]]].append(r[metric])
    # 本模块**不依赖 numpy**（纯标准库）⇒ 用 sum/len，不要引 np.mean
    z = [[(sum(c) / len(c) if c else None) for c in row] for row in cells]
    grid_n = [[len(c) for c in row] for row in cells]
    grid_spread = [[(float(max(c) - min(c)) if len(c) > 1 else 0.0) if c else None
                    for c in row] for row in cells]
    cnt = sum(len(c) for row in cells for c in row)
    vals = [v for row in z for v in row if v is not None]
    layers = sorted({r["N_w_te2"] for r in sel})
    multi = max((n for row in grid_n for n in row), default=0) > 1
    return {
        "batch": batch, "metric": metric, "metric_label": METRICS[metric][0],
        "n2_filter": merged.get("n2"), "n2_layers_in_data": layers,
        "filter": dict(merged), "filter_label": filter_label(merged),
        "n_rows_after_filter": len(rows_f), "n_rows_batch": len(batch_rows),
        "xs": xs, "n1s": n1s, "grid": z, "n_points": cnt,
        "aggregation": "mean_of_layers" if multi else "single_value",
        "grid_n_layers": grid_n, "grid_layer_spread": grid_spread,
        "max_layers_per_cell": max((n for row in grid_n for n in row), default=0),
        "value_range": [min(vals), max(vals)] if vals else None,
        "note": ("单元格为空 = 该 (x,N1) 在选中范围内没有「找到首个峰的可用值」；"
                 "**不填 0**；按批次分层（A/C 的 x 密度与频段不同）。"
                 + ("**本图未限定 N2 ⇒ 每格是各 N2 层的均值**"
                    "（悬停可看层数与层间跨度；要看单层请填 N2）" if multi
                    else "每个格子只对应一个值。")),
    }
