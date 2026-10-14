# -*- coding: utf-8 -*-
"""**metric_protocol_v2** —— 评价协议修订版（外部审阅方裁定 2026-09-29，登记 `feedback`
`fb-20260929T035510Z-17e73f1a`）。

为什么要这一版（v1 的三个缺陷，均为实测）：
1. **`p_abs` 的相对误差不可用**：`|p|` 会过零 ⇒ `|Δ|/|p|` 在零点发散。
   四轮实测 max 从 116% 到 4940%（轮 1 的 S1 就 1156%）。它量的是"零点附近的数值噪声"。
2. **dB 上的"相对百分比误差"没有意义**：dB 是绝对量，`ΔdB/dB` 不是相对误差。
3. **用单个 `max` 判胜负会被极少数窄分支控制**，且实测**随网格间距 h 非单调**
   （h=0.08 的 max 19.15 dB > h=0.10 的 11.17 dB）。

v2 的规则（与 v1 **并存**，历史结果不重算、不覆盖）：

* **20 MHz 声压目标**：主 `|ΔSPL20|`（dB）、辅 `||Δ|p||`（Pa）、
  诊断 `|Δlog10 max(|p|, p_floor)|`；普通相对误差**只作诊断**，
  且 `|p_true| < p_floor` 时记 `not_applicable`。
  `p_floor = max(噪声下限, 训练集 |p| 的第 1 百分位)` —— **只能用训练集定，不能用测试集**。
* **dB 误差**：报 `median / p90 / p99 / max / >0.5 dB 比例 / >1 dB 比例`；
  `pass` = median ≤ 0.05 dB **且** p90 ≤ 0.20 dB **且** >0.5 dB 比例 ≤ 5%；
  `partial` = p90 ≤ 0.50 dB **且** >1 dB 比例 ≤ 5%；其余 `fail`。
  **`max` 不单独决定 pass/fail**，但 `max > 3 dB` 触发 `local_hotspot_unclosed` 旗标。
* **"打赢最近邻"改配对判据**（同一测试点配对）：`d_i = |err_model_i| − |err_base_i|`，
  五条同时满足才算胜出（见 `paired_verdict`）。
* **频谱**：主 = 逐频点 `|ΔSPL|` 的 median/p90/p99/max；辅 = `RMSE_dB`；
  再给线性幅值归一化 L2（可由 dB 反推，全局常数在归一化中约掉）。
  **不再用 dB 空间的相对 L2 作主指标**（dB 基准平移会改变分母）。

⚠️ 本模块**不读任何数据、不写任何文件**（纯函数），便于单测与复算。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

PROTOCOL = "metric_protocol_v2"
V1_PROTOCOL = "metric_protocol_v1"

#: v2 判定带（裁定 §1.2，写死）
BAND_DB = {
    "pass": {"median_max": 0.05, "p90_max": 0.20, "frac_gt_0p5_max": 0.05},
    "partial": {"p90_max": 0.50, "frac_gt_1_max": 0.05},
    "hotspot_max_db": 3.0,
}
#: 配对胜负门槛（裁定 §2，写死）
PAIRED = {"win_rate_min": 0.55, "min_p90_gain_db": 0.10, "max_worsen_db": 0.5,
          "boot_n": 10000, "boot_seed": 0}
PERCENTILES = (50.0, 90.0, 99.0)


# ---------------------------------------------------------------- p_floor
def training_p_floor(train_abs_p: Sequence[float] | np.ndarray,
                     noise_floor: float = 0.0, pct: float = 1.0) -> float:
    """`p_floor = max(噪声下限, 训练集 |p| 的第 pct 百分位)`。

    **只能用训练集**定（裁定 §1.1）——用测试集会污染判定。
    """
    a = np.asarray([v for v in np.asarray(train_abs_p, dtype=float) if np.isfinite(v)], dtype=float)
    if a.size == 0:
        raise ValueError("训练集 |p| 为空 ⇒ 无法定义 p_floor（不得用测试集代替）")
    return float(max(noise_floor, np.percentile(a, pct)))


# ---------------------------------------------------------------- 20 MHz 三级
def three_level_20MHz(spl_pred: float, spl_true: float,
                      p_pred: float, p_true: float, p_floor: float) -> dict[str, Any]:
    """裁定 §1.1 的三级结构。主/辅始终给；诊断的相对误差在 `|p_true| < p_floor` 时 N/A。"""
    out = {
        "main_abs_error_spl20_dB": abs(float(spl_pred) - float(spl_true)),
        "aux_abs_error_p20_Pa": abs(abs(float(p_pred)) - abs(float(p_true))),
        "p_floor_Pa": float(p_floor),
    }
    lo = max(abs(float(p_pred)), float(p_floor))
    lt = max(abs(float(p_true)), float(p_floor))
    out["diag_abs_log10_error"] = abs(np.log10(lo) - np.log10(lt))
    if abs(float(p_true)) < float(p_floor):
        out["diag_rel_error"] = None
        out["diag_rel_error_status"] = "not_applicable(|p_true| < p_floor)"
    else:
        out["diag_rel_error"] = abs(abs(float(p_pred)) - abs(float(p_true))) / abs(float(p_true))
        out["diag_rel_error_status"] = "ok"
    return out


# ---------------------------------------------------------------- dB 统计与判定
def db_error_stats(abs_err_db: Sequence[float] | np.ndarray) -> dict[str, Any]:
    """逐点**绝对** dB 误差的分位数与超阈值比例（裁定 §1.2 要求全部报出）。"""
    e = np.asarray(abs_err_db, dtype=float)
    e = e[np.isfinite(e)]
    if e.size == 0:
        return {"n": 0, "median": None, "p90": None, "p99": None, "max": None,
                "frac_gt_0p5": None, "frac_gt_1": None}
    p50, p90, p99 = (float(np.percentile(e, q)) for q in PERCENTILES)
    return {"n": int(e.size), "median": p50, "p90": p90, "p99": p99, "max": float(e.max()),
            "frac_gt_0p5": float((e > 0.5).mean()), "frac_gt_1": float((e > 1.0).mean())}


def verdict_db(stats: Mapping[str, Any]) -> dict[str, Any]:
    """裁定 §1.2 的判定带：`max` 不进 pass/fail，只触发热点旗标。"""
    if not stats or stats.get("n") in (None, 0):
        return {"verdict": "not_applicable", "reason": "无有效点", "local_hotspot_unclosed": None}
    m, p90 = stats["median"], stats["p90"]
    f05, f1 = stats["frac_gt_0p5"], stats["frac_gt_1"]
    hot = bool(stats["max"] is not None and stats["max"] > BAND_DB["hotspot_max_db"])
    if m <= BAND_DB["pass"]["median_max"] and p90 <= BAND_DB["pass"]["p90_max"] \
            and f05 <= BAND_DB["pass"]["frac_gt_0p5_max"]:
        v = "pass"
    elif p90 <= BAND_DB["partial"]["p90_max"] and f1 <= BAND_DB["partial"]["frac_gt_1_max"]:
        v = "partial"
    else:
        v = "fail"
    return {"verdict": v, "local_hotspot_unclosed": hot,
            "reason": ("max>3dB ⇒ 存在局部未闭合热点，禁止宣称全域光滑/全域收敛" if hot else None),
            "band_used": BAND_DB}


# ---------------------------------------------------------------- 配对胜负
def paired_verdict(err_model_db: Sequence[float] | np.ndarray,
                   err_base_db: Sequence[float] | np.ndarray, *,
                   boot_n: int = PAIRED["boot_n"], seed: int = PAIRED["boot_seed"]) -> dict[str, Any]:
    """裁定 §2 的配对判据（**同一测试点**配对）。`err_*` 为**有符号**误差，内部取绝对值。

    五条同时满足才 `model_wins=True`：
    ① `median(d) < 0`；② 胜率 `P(d<0) > 55%`；③ 配对 bootstrap 中位差 95% CI 上界 `< 0`
    **或** 单侧 Wilcoxon `p < 0.05`；④ `p90(|err|)` 至少改善 0.10 dB；
    ⑤ 模型的 `max` 不得比基线恶化超过 0.5 dB（否则标 `new_disaster_point`，不算完全胜出）。
    """
    a = np.abs(np.asarray(err_model_db, dtype=float))
    b = np.abs(np.asarray(err_base_db, dtype=float))
    if a.shape != b.shape:
        raise ValueError("配对判据要求逐点一一对应：%s vs %s" % (a.shape, b.shape))
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    n = a.size
    res: dict[str, Any] = {"protocol": PROTOCOL, "n_pairs": int(n),
                           "pearson_matched": True, "band_used": PAIRED}
    if n < 5:
        res.update({"model_wins": None, "reason": "配对数 %d <5，不出判定" % n})
        return res
    d = a - b
    res["median_d_dB"] = float(np.median(d))
    res["win_rate"] = float((d < 0).mean())
    # ①
    c1 = res["median_d_dB"] < 0
    # ②
    c2 = res["win_rate"] > PAIRED["win_rate_min"]
    # ③ 配对 bootstrap（固定种子；可复现）
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(boot_n, n))
    med_boot = np.median(d[idx], axis=1)
    lo, hi = float(np.percentile(med_boot, 2.5)), float(np.percentile(med_boot, 97.5))
    res["boot_median_d_ci95"] = [lo, hi]
    c3_boot = hi < 0
    c3_wil = None
    try:
        from scipy.stats import wilcoxon
        if np.any(d != 0):
            c3_wil = float(wilcoxon(d, alternative="less").pvalue)
    except Exception:
        c3_wil = None
    res["wilcoxon_p_onesided"] = c3_wil
    c3 = bool(c3_boot or (c3_wil is not None and c3_wil < 0.05))
    # ④ p90 改善
    gain = float(np.percentile(b, 90) - np.percentile(a, 90))
    res["p90_gain_dB"] = gain
    c4 = gain >= PAIRED["min_p90_gain_db"]
    # ⑤ max 恶化
    worsen = float(a.max() - b.max())
    res["max_worsen_dB"] = worsen
    c5 = worsen <= PAIRED["max_worsen_db"]
    res["conditions"] = {"c1_median_negative": bool(c1), "c2_win_rate": bool(c2),
                         "c3_significance": bool(c3), "c4_p90_gain": bool(c4),
                         "c5_max_not_worse": bool(c5)}
    res["model_wins"] = bool(c1 and c2 and c3 and c4 and c5)
    if res["model_wins"]:
        res["reason"] = None
    elif c1 and c2 and c3 and c4 and not c5:
        res["reason"] = ("主体更优但**产生新灾难点**（max 恶化 %.3f dB > %.2f）⇒ 不算完全胜出"
                         % (worsen, PAIRED["max_worsen_db"]))
    else:
        failed = [k for k, v in res["conditions"].items() if not v]
        res["reason"] = "未满足：" + ", ".join(failed)
    return res


# ---------------------------------------------------------------- 频谱
def spectrum_metrics(spl_pred: Sequence[float] | np.ndarray,
                     spl_true: Sequence[float] | np.ndarray) -> dict[str, Any]:
    """裁定 §2.1 的频谱指标顺序：①逐点 |ΔSPL| 分位数 ②RMSE_dB ③（无复声压时）线性幅值归一化 L2。

    线性幅值由 dB 反推：`a = 10**(SPL/20) ∝ |p|`（20µPa 与 √2 只是**全局常数**，
    在归一化 L2 里约掉）⇒ 这是"线性声压幅值归一化 L2"的可用近似，**不是**复声压 L2。
    **不再**输出 dB 空间的相对 L2 作主指标。
    """
    p = np.asarray(spl_pred, dtype=float)
    t = np.asarray(spl_true, dtype=float)
    if p.shape != t.shape:
        raise ValueError("频谱形状不一致：%s vs %s" % (p.shape, t.shape))
    ok = np.isfinite(p) & np.isfinite(t)
    p, t = p[ok], t[ok]
    if p.size == 0:
        return {"n_freq": 0, "abs_dB": None, "rmse_dB": None, "linear_amp_relL2": None}
    ad = np.abs(p - t)
    lp = 10.0 ** (p / 20.0)
    lt = 10.0 ** (t / 20.0)
    den = float(np.linalg.norm(lt))
    return {"n_freq": int(p.size), "abs_dB": db_error_stats(ad),
            "rmse_dB": float(np.sqrt(np.mean((p - t) ** 2))),
            "linear_amp_relL2": (float(np.linalg.norm(lp - lt) / den) if den > 0 else None),
            "note": ("linear_amp_relL2 由 dB 反推线性幅值（全局常数在归一化中约掉）；"
                     "有复声压时应改用复声压能量归一化 L2")}
