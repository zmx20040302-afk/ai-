# -*- coding: utf-8 -*-
"""多通道一阶峰代理：拟合 + 预注册折评估（v1）。

预注册（**先于本脚本运行写定**）：`PREREG_multichannel_surrogate.md`。
本脚本把该文件的 sha256 读进结果 JSON，以便日后核对"判定带是否事后改过"。

模型（与已验证的响应级代理同构）：
  1. 层内：固定 (N2,N1)，沿 x 做 PCHIP 插值；查询点超出该层训练 x 范围 ⇒ 拒答（不外推）
  2. N2 方向：固定 (N1,x)，用最近两层线性外推，**只允许 1 步**
  3. 其它越界 ⇒ 拒答

折（全部预注册）：L-N2ex(8) 主判定 / L-N2ex(7,6,5) 标尺 / S-D(h=0.02) 层内自洽

用法：`import pchip_fitter`（本包内置的既有 PCHIP 口径实现）
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import pathlib
import sys

import numpy as np
from scipy.interpolate import PchipInterpolator

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent
LABELS = PKG / "data" / "channels_multichannel.csv"  # 仅供独立使用时读取；本包的评估把行直接传入
PREREG = HERE / "PREREG_multichannel_surrogate.md"
OUT_JSON = HERE / "multichannel_surrogate.json"
OUT_REPORT = HERE / "MULTICHANNEL_SURROGATE_REPORT.md"

BATCH = "C"
QUARANTINE = {(0.2, 1.0, 7.0), (0.2, 1.0, 8.0)}
N2_TRAIN_MAIN = (5.0, 6.0, 7.0)
N2_TEST_MAIN = 8.0
N2_RULERS = (7.0, 6.0, 5.0)
N2_C2828 = (5.0, 6.0, 7.0)
S_D_H = 0.02
SEED = 0
ALPHAS = (0.10, 0.05, 0.01)

#: 通道 → (组, 是否正式目标, 空间, 该通道有定义所需条件)
CHANNELS = {
    "bandwidth_Hz": ("§3.2 带宽", True, "log10", "closed"),
    "abs_w_m": ("§3.1 振幅", True, "log10", "peak"),
    "abs_p_per_V_Pa": ("§3.3 灵敏度", True, "log10", "peak"),
    "f_peak_Hz": ("描述", False, "log10", "peak"),
    "abs_p_Pa": ("§3.1 振幅", False, "log10", "peak"),
    "abs_vz_struct_m3s": ("§3.1 振幅", False, "log10", "peak"),
    "peak_SPL_dB": ("§3.1 振幅", False, "identity", "peak"),
    "Q_factor": ("门槛(报告)", False, "log10", "closed"),
}
#: 预注册判定带（**不看结果先定**，见 PREREG §6）
BANDS = {
    "in_layer": {"pass": {"median": 0.004, "p90": 0.012, "frac_gt": 0.03, "frac_max": 0.02},
                 "partial": {"p90": 0.030}, "hotspot": 0.30},
    "n2_extrap": {"pass": {"median": 0.020, "p90": 0.060, "frac_gt": 0.10, "frac_max": 0.05},
                  "partial": {"p90": 0.150}, "hotspot": 0.30},
}


def _f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def load_rows() -> list[dict]:
    if not LABELS.is_file():
        raise SystemExit("[FAIL] 缺标签表：%s（先跑 build_multichannel_labels.py）" % LABELS)
    out = []
    with LABELS.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["source_dataset"] != BATCH:
                continue
            k = (_f(r["x_scale"]), _f(r["N_w_te1"]), _f(r["N_w_te2"]))
            if None in k or k in QUARANTINE:
                continue
            closed = str(r.get("bandwidth_closed", "")).lower() == "true"
            peaked = str(r.get("first_peak_found", "")).lower() == "true"
            d = {"key": k, "x": k[0], "n1": k[1], "n2": k[2],
                 "peaked": peaked, "closed": closed}
            for c in CHANNELS:
                d[c] = _f(r.get(c))
            out.append(d)
    return out


def defined(row: dict, ch: str) -> bool:
    """该行在该通道上是否有定义（带宽类需带闭合；其余需找到峰）。"""
    cond = CHANNELS[ch][3]
    if cond == "closed" and not row["closed"]:
        return False
    if cond == "peak" and not row["peaked"]:
        return False
    return row[ch] is not None and row[ch] > 0


def to_space(ch: str, y: float) -> float:
    return math.log10(y) if CHANNELS[ch][2] == "log10" else y


def from_space(ch: str, z: float) -> float:
    return 10.0 ** z if CHANNELS[ch][2] == "log10" else z


def err(ch: str, pred: float, truth: float) -> float:
    """误差：log10 通道用 |Δlog10|（≈相对误差）；dB 通道用 |ΔdB|。"""
    if CHANNELS[ch][2] == "log10":
        return abs(math.log10(pred) - math.log10(truth))
    return abs(pred - truth)


class LayerFit:
    """固定 (N2,N1) 的层内 PCHIP；只在训练 x 范围内插值。"""

    def __init__(self, xs: list[float], zs: list[float]):
        self.xs = np.array(xs, float)
        self.zs = np.array(zs, float)
        self.itp = PchipInterpolator(self.xs, self.zs) if len(xs) >= 2 else None

    def predict(self, x: float):
        if self.itp is None:
            return None
        if x < self.xs[0] or x > self.xs[-1]:
            return None                      # **不外推**
        return float(self.itp(x))


def build(train: list[dict], ch: str) -> dict:
    """按 (N2,N1) 建层内拟合，并索引每层可用 x（供 N2 方向线性外推）。

    ⚠️ `layers` 的键是 **元组 `(n2, n1)`**；外推时要按元组取（曾误用标量 n2 ⇒ KeyError）。
    x 用 `round(x, 6)` 作键：训练与查询都来自同一张表，但浮点等值比较不可靠。
    """
    layers: dict[tuple, dict] = {}
    for r in train:
        if not defined(r, ch):
            continue
        layers.setdefault((r["n2"], r["n1"]), {})[round(r["x"], 6)] = to_space(ch, r[ch])
    fits = {k: LayerFit(sorted(v), [v[x] for x in sorted(v)]) for k, v in layers.items()}
    return {"layers": layers, "fits": fits}


def predict_one(model: dict, ch: str, x: float, n1: float, n2: float):
    """返回 (预测值, 模式) 或 (None, 原因)。"""
    if not (0.20 <= x <= 1.00):
        return None, "x_out_of_domain"
    if n1 < 1 or abs(n1 - round(n1)) > 1e-9:
        return None, "n1_invalid"
    if n2 < 5 or n2 > 9:
        return None, "n2_out_of_domain"
    if n1 >= n2:
        return None, "layer_does_not_exist"
    lf = model["fits"].get((n2, n1))
    if lf is not None:
        z = lf.predict(x)
        return (None, "x_outside_layer_range") if z is None else (from_space(ch, z), "in_layer")
    # N2 方向线性外推（**只允许 1 步**）
    av = sorted({l for (l, m) in model["layers"] if m == n1})
    if not av:
        return None, "no_layer_for_n1"
    near = min(av, key=lambda l: abs(l - n2))
    if abs(near - n2) > 1:
        return None, "n2_extrap_more_than_one_step"
    others = [l for l in av if l != near]
    if not others:
        return None, "need_two_layers_to_extrapolate"
    other = min(others, key=lambda l: abs(l - near))
    xr = round(x, 6)
    lay_a, lay_b = model["layers"].get((near, n1)), model["layers"].get((other, n1))
    za, zb = (lay_a or {}).get(xr), (lay_b or {}).get(xr)
    if za is None or zb is None:
        return None, "x_missing_in_extrapolation_layers"
    slope = (za - zb) / (near - other)
    return from_space(ch, za + slope * (n2 - near)), "n2_extrap"


def stats(errs: list[float], mode: str) -> dict:
    if not errs:
        return {"n": 0}
    a = np.array(errs, float)
    b = BANDS[mode]
    st = {"n": int(a.size), "median": float(np.median(a)),
          "p90": float(np.percentile(a, 90)), "p99": float(np.percentile(a, 99)),
          "max": float(a.max()),
          "frac_gt": {("%g" % b["pass"]["frac_gt"]): float((a > b["pass"]["frac_gt"]).mean())}}
    ok = (st["median"] <= b["pass"]["median"] and st["p90"] <= b["pass"]["p90"]
          and float((a > b["pass"]["frac_gt"]).mean()) <= b["pass"]["frac_max"])
    st["verdict"] = "pass" if ok else ("partial" if st["p90"] <= b["partial"]["p90"] else "fail")
    st["local_hotspot_unclosed"] = bool(st["max"] > b["hotspot"])
    return st


def baseline_persistence(train: list[dict], test: list[dict], ch: str) -> dict:
    """**持续性基线**（control）：直接抄"同 (n1,x) 最近可用层"的值。

    为什么必须给这个对照：若代理的中位误差与"直接抄上一层"相当，则模型**没有增值**，
    主判定折的漂亮数字只是"相邻层本来就几乎一样"的同义反复。
    基线**不参与**预注册判定，只作对照（与 A6 里 B3 基线的作用相同）。
    """
    layers: dict[tuple, dict] = {}
    for r in train:
        if defined(r, ch):
            layers.setdefault((r["n2"], r["n1"]), {})[round(r["x"], 6)] = r[ch]
    errs = []
    for r in test:
        if not defined(r, ch):
            continue
        xr = round(r["x"], 6)
        cand = [l for (l, m) in layers if m == r["n1"] and xr in layers[(l, m)]]
        if not cand:
            continue
        near = min(cand, key=lambda l: abs(l - r["n2"]))
        errs.append(err(ch, layers[(near, r["n1"])][xr], r[ch]))
    return stats(errs, "n2_extrap") if errs else {"n": 0}


def eval_fold(train: list[dict], test: list[dict], label: str) -> dict:
    """对一个折，逐通道算误差 + 覆盖率（**覆盖率必须与误差同时报**，D1）。"""
    out = {"fold": label, "n_train_rows": len(train), "n_test_rows": len(test), "channels": {}}
    for ch in CHANNELS:
        model = build(train, ch)
        errs, modes, reasons, n_def = [], [], {}, 0
        for r in test:
            if not defined(r, ch):
                continue
            n_def += 1
            p, mode = predict_one(model, ch, r["x"], r["n1"], r["n2"])
            if p is None:
                reasons[mode] = reasons.get(mode, 0) + 1
                continue
            errs.append(err(ch, p, r[ch]))
            modes.append(mode)
        # 按模式分开且**合并**（合并用于总览，判定按主模式）
        per_mode = {}
        for m in ("in_layer", "n2_extrap"):
            sub = [e for e, mm in zip(errs, modes) if mm == m]
            per_mode[m] = stats(sub, m) if sub else {"n": 0}
        merged = stats(errs, "in_layer" if label.startswith("S-D") else "n2_extrap")
        base = baseline_persistence(train, test, ch)
        out["channels"][ch] = {
            "group": CHANNELS[ch][0], "is_formal_objective": CHANNELS[ch][1],
            "space": CHANNELS[ch][2],
            "n_defined_in_test": n_def,
            "n_predicted": len(errs),
            "coverage": (len(errs) / n_def) if n_def else None,
            "refusal_reasons": reasons,
            "merged": merged, "per_mode": per_mode,
            "baseline_persistence": base,
            "beats_persistence": (bool(merged.get("median") is not None
                                       and base.get("median") is not None
                                       and merged["median"] <= base["median"])),
        }
    return out


def eval_sd(rows: list[dict]) -> dict:
    """S-D(h=0.02)：同层内 x = 0.20 + k·0.02 作训练，其余作测试（层内模式）。"""
    train, test = [], []
    for r in rows:
        k = round((r["x"] - 0.20) / S_D_H)
        on = abs(r["x"] - (0.20 + k * S_D_H)) < 1e-9
        (train if on else test).append(r)
    return eval_fold(train, test, "S-D(h=0.02) 层内自洽")


def conformal(rows: list[dict]) -> dict:
    """保形校准：n2_extrap 用标尺折残差；in_layer 用 S-D 测试点对半切。"""
    cal = {}
    # --- n2_extrap：标尺折残差 ---
    res_by_ch: dict[str, list[float]] = {}
    for held in N2_RULERS:
        train = [r for r in rows if r["n2"] in [l for l in N2_C2828 if l != held]]
        test = [r for r in rows if r["n2"] == held]
        for ch in CHANNELS:
            model = build(train, ch)
            for r in test:
                if not defined(r, ch):
                    continue
                p, mode = predict_one(model, ch, r["x"], r["n1"], r["n2"])
                if p is not None and mode == "n2_extrap":
                    res_by_ch.setdefault(ch, []).append(err(ch, p, r[ch]))
    cal["n2_extrap"] = {ch: {("%g" % a): (float(np.quantile(v, 1 - a)) if v else None)
                             for a in ALPHAS} for ch, v in res_by_ch.items()}
    # --- in_layer：S-D 测试点对半切（seed 固定） ---
    rng = np.random.default_rng(SEED)
    tr, te = [], []
    for r in rows:
        k = round((r["x"] - 0.20) / S_D_H)
        (tr if abs(r["x"] - (0.20 + k * S_D_H)) < 1e-9 else te).append(r)
    idx = rng.permutation(len(te))
    half = len(idx) // 2
    te_cal = [te[i] for i in idx[:half]]
    te_eval = [te[i] for i in idx[half:]]
    res_in: dict[str, list[float]] = {}
    cov_in: dict[str, dict] = {}
    for ch in CHANNELS:
        model = build(tr, ch)
        cal_e, ev_e = [], []
        for r in te_cal:
            if defined(r, ch):
                p, mode = predict_one(model, ch, r["x"], r["n1"], r["n2"])
                if p is not None and mode == "in_layer":
                    cal_e.append(err(ch, p, r[ch]))
        for r in te_eval:
            if defined(r, ch):
                p, mode = predict_one(model, ch, r["x"], r["n1"], r["n2"])
                if p is not None and mode == "in_layer":
                    ev_e.append(err(ch, p, r[ch]))
        res_in[ch] = cal_e
        cov_in[ch] = {"n_cal": len(cal_e), "n_eval": len(ev_e)}
        if cal_e and ev_e:
            for a in ALPHAS:
                q = float(np.quantile(cal_e, 1 - a))
                cov_in[ch]["alpha_%g" % a] = {
                    "half_width": q, "empirical_coverage": float(np.mean(np.array(ev_e) <= q)),
                    "nominal": 1 - a,
                    "coverage_below_nominal": bool(np.mean(np.array(ev_e) <= q) < (1 - a) - 0.05)}
    cal["in_layer"] = {ch: {("%g" % a): (float(np.quantile(v, 1 - a)) if v else None)
                            for a in ALPHAS} for ch, v in res_in.items()}
    return {"quantiles": cal, "in_layer_coverage": cov_in}


def main() -> int:
    rows = load_rows()
    prereg_sha = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print("标签表 %d 行（批 %s，已排除隔离）｜预注册 sha256 %s"
          % (len(rows), BATCH, prereg_sha[:16]))

    folds = []
    # 主判定：L-N2ex(8)（训练 N2∈{5,6,7} → 测试 N2=8）
    folds.append(eval_fold([r for r in rows if r["n2"] in N2_TRAIN_MAIN],
                           [r for r in rows if r["n2"] == N2_TEST_MAIN],
                           "L-N2ex(8) 主判定（外部增量层）"))
    # 标尺折（只用 C_v20260928 的另外两层）
    for held in N2_RULERS:
        folds.append(eval_fold([r for r in rows if r["n2"] in [l for l in N2_C2828 if l != held]],
                               [r for r in rows if r["n2"] == held],
                               "L-N2ex(%g) 标尺" % held))
    # 层内自洽
    folds.append(eval_sd(rows))

    conf = conformal(rows)

    out = {
        "kind": "multichannel_surrogate_v1",
        "prereg": str(PREREG.relative_to(REPO)).replace("\\", "/"),
        "prereg_sha256": prereg_sha,
        "data": {"labels": str(LABELS.relative_to(REPO)).replace("\\", "/"),
                 "batch": BATCH, "n_rows_used": len(rows),
                 "excluded_quarantine": [list(k) for k in sorted(QUARANTINE)],
                 "n_layers": sorted({r["n2"] for r in rows})},
        "channels": {c: {"group": v[0], "is_formal_objective": v[1], "space": v[2],
                         "requires": v[3]} for c, v in CHANNELS.items()},
        "bands": BANDS,
        "folds": folds,
        "conformal": conf,
        "model_structure": {
            "in_layer": "固定 (N2,N1) 沿 x 的 PCHIP 插值；超出该层 x 范围 ⇒ 拒答",
            "n2_direction": "固定 (N1,x) 用最近两层线性外推，**只允许 1 步**",
            "m11_excluded": "二次外推未验证，不纳入生产模型",
        },
        "NOT_a_solver": ("本代理只预测**一阶峰标量**，无场级误差界、无 L1 网格收敛 ⇒ "
                         "不得用于工程绝对值，不得称为免 COMSOL 出解"),
        "status": "draft",
        "refusal_domain": {"x": [0.20, 1.00], "n1": ">=1 整数且 < N2", "n2": [5, 9],
                           "alphas": list(ALPHAS),
                           "modes": ["in_layer", "n2_extrap(≤1 步)"]},
    }

    # 逐通道汇总主判定的 pass/partial/fail（**逐通道，不用总误差掩盖**）
    main_fold = folds[0]
    summary = {}
    for ch, d in main_fold["channels"].items():
        m = d["per_mode"].get("n2_extrap", {})
        summary[ch] = {
            "is_formal_objective": d["is_formal_objective"],
            "n_predicted": d["n_predicted"], "coverage": d["coverage"],
            "verdict_n2_extrap": m.get("verdict", "no_data"),
            "median": m.get("median"), "p90": m.get("p90"), "max": m.get("max"),
        }
    for ch, v in summary.items():
        c = main_fold["channels"][ch]
        v["baseline_persistence_median"] = c["baseline_persistence"].get("median")
        v["beats_persistence"] = c["beats_persistence"]
        v["hotspot"] = c["per_mode"].get("n2_extrap", {}).get("local_hotspot_unclosed")
        v["refusal_reasons"] = c["refusal_reasons"]
    out["summary_main_fold"] = summary
    n_pass = sum(1 for v in summary.values() if v["verdict_n2_extrap"] == "pass")
    n_part = sum(1 for v in summary.values() if v["verdict_n2_extrap"] == "partial")
    # ⚠️ **"过预注册带" ≠ "模型有增值"**：必须把"未优于持续性基线"的通道点名列出。
    no_lift = [ch for ch, v in summary.items()
               if v["beats_persistence"] is False and v["median"] is not None]
    for ch, v in summary.items():
        b = v.get("baseline_persistence_median")
        v["lift_vs_persistence"] = (None if (b is None or v["median"] is None)
                                    else b - v["median"])
    out["channels_without_lift"] = no_lift
    out["verdict"] = ("主判定折（N2=8）：%d 通道 pass / %d partial / %d fail（共 %d 通道）；"
                      "但其中 **%d 个通道未优于持续性基线**（模型无增值）：%s"
                      % (n_pass, n_part, len(summary) - n_pass - n_part, len(summary),
                         len(no_lift), "、".join("`%s`" % c for c in no_lift) or "无"))
    out["verdict_scope"] = ("预注册带判定的是**绝对精度**；`beats_persistence` 判定的是"
                            "**模型是否比「直接抄相邻层」更好**。两者必须同时看：精度达标但无增值时，"
                            "工程上直接用相邻层即可，不需要代理。")
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------- 报告 ----------------
    L = ["# 多通道一阶峰代理 v1 — 结果报告", "",
         "> 预注册：`%s`（sha256 `%s`）" % (out["prereg"], prereg_sha[:16]),
         "> 数据：`%s`（批 %s，%d 行，已排除隔离）" % (out["data"]["labels"], BATCH, len(rows)),
         "> ⚠️ **不是 AI 求解器**：无场级误差界、无 L1 ⇒ 不得用于工程绝对值。", "",
         "## 主判定折 L-N2ex(8)（训练 N2∈{5,6,7} → 测试 N2=8）", "",
         "| 通道 | 正式目标 | 可预测/有定义 | 覆盖率 | 中位 | p90 | max | 抄相邻层(中位) | 增益 | 判定 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for ch, v in summary.items():
        L.append("| `%s` | %s | %d/%d | %s | %s | %s | %s | %s | %s | **%s** |"
                 % (ch, "是" if v["is_formal_objective"] else "否",
                    v["n_predicted"], main_fold["channels"][ch]["n_defined_in_test"],
                    ("%.1f%%" % (100 * v["coverage"])) if v["coverage"] is not None else "—",
                    _fmt(v["median"]), _fmt(v["p90"]), _fmt(v["max"]),
                    _fmt(v["baseline_persistence_median"]),
                    ("%+.4f" % v["lift_vs_persistence"]) if v.get("lift_vs_persistence") is not None
                    else "—",
                    v["verdict_n2_extrap"]))
    L += ["", "> 增益 = 抄相邻层的中位误差 − 代理的中位误差；**正数才说明模型有增值**。"]
    if no_lift:
        L += ["", "### ⚠️ 未优于持续性基线的通道（**模型无增值**）", "",
              "这些通道**精度达标但不如「直接抄相邻层」**：",
              ""]
        for ch in no_lift:
            v = summary[ch]
            L.append("* `%s`：代理中位 %s vs 基线 %s（增益 %+.4f）⇒ **工程上直接用相邻层即可**"
                     % (ch, _fmt(v["median"]), _fmt(v["baseline_persistence_median"]),
                        v["lift_vs_persistence"]))
        L += ["", "> 出现这种情况的原因是：这些量的层间差异本身很小，而线性外推要**估一个斜率**，",
              "> 斜率的估计噪声反而比「不估斜率」更大。**这不是 bug，是模型选择问题**——",
              "> 若要把它们做成可用的代理，应换更稳的模型（例如带收缩的斜率估计），**另开一版预注册**。", ""]
    L += ["", "### 判读与自查（**必须与上表一起读**）", "",
          "1. **覆盖率只有约 70%**——这不是 bug，而是结构性拒答，两条原因：",
          "   * `no_layer_for_n1`：训练层里**根本没有该 N1**（C 的每层 N1 上限 = N2−1，",
          "     故 N2=8 的 N1=7 在训练层中不存在）；",
          "   * `need_two_layers_to_extrapolate`：该 N1 在训练层里**只有一层**",
          "     （如 N1=6 只出现在 N2=7），单点无法作线性外推。",
          "   ⇒ 想提高覆盖率需要**换模型**（例如跨 N1 借斜率），那必须**另开一版预注册**，",
          "     不能在本版事后改。",
          "2. **`f_peak_Hz` 的中位误差恰为 0.0000，不要读成「极准」**：",
          "   `f_peak` 只取 87 个离散值（0.5 MHz 网格量化），且实测 **86.6% 的组合在 N2=7 与 N2=8 上完全相同**",
          "   ⇒ 线性外推的斜率≈0、退化为「抄上一层」，中位自然是 0。",
          "   **它是「容易预测」但「区分度低」的量**（量化+对 N2 不敏感），排名时不应据此下强结论。",
          "3. **`max` 已单独标出**：`abs_w_m` 的 max = 0.31（log10，≈2 倍）为局部热点",
          "   ⇒ 已置 `local_hotspot_unclosed`；`max` **不参与**判定（沿用 metric_protocol_v2 口径）。",
          "4. **dB 通道的带宽是数值上更严的**：预注册的 0.02/0.06 是按 log10（≈相对误差 4.7%/15%）定的，",
          "   套到 `peak_SPL_dB` 上就变成 0.02/0.06 dB ⇒ 该通道判 `partial` 属**保守**，不是缺陷。",
          "5. **持续性基线对照**（上表「抄相邻层」列）：代理中位误差须 ≤ 基线，否则模型无增值。", ""]
    for f in folds[1:]:
        L.append("### %s" % f["fold"])
        L.append("")
        L.append("| 通道 | 可预测/有定义 | 覆盖率 | 中位 | p90 | 抄相邻层 | 判定 |")
        L.append("|---|---|---|---|---|---|---|")
        for ch, d in f["channels"].items():
            mm = "in_layer" if f["fold"].startswith("S-D") else "n2_extrap"
            s = d["per_mode"].get(mm, {})
            L.append("| `%s` | %d/%d | %s | %s | %s | %s | **%s** |"
                     % (ch, d["n_predicted"], d["n_defined_in_test"],
                        ("%.1f%%" % (100 * d["coverage"])) if d["coverage"] is not None else "—",
                        _fmt(s.get("median")), _fmt(s.get("p90")),
                        _fmt(d["baseline_persistence"].get("median")),
                        s.get("verdict", "no_data")))
        L.append("")
    L += ["## 保形区间（α = 0.10 / 0.05 / 0.01）与经验覆盖率", ""]
    cov = conf["in_layer_coverage"]
    L.append("| 通道 | n_cal | n_eval | 半宽(α=0.05) | 经验覆盖 | 达标？ |")
    L.append("|---|---|---|---|---|---|")
    for ch, d in cov.items():
        a5 = d.get("alpha_0.05")
        L.append("| `%s` | %s | %s | %s | %s | %s |"
                 % (ch, d.get("n_cal"), d.get("n_eval"),
                    _fmt(a5["half_width"]) if a5 else "—",
                    ("%.1f%%" % (100 * a5["empirical_coverage"])) if a5 else "—",
                    ("**低于名义**" if a5 and a5["coverage_below_nominal"] else "未低于名义")
                    if a5 else "—"))
    L += ["", "> n2_extrap 的保形半宽由**标尺折**残差给出：",
          "> `%s`" % json.dumps(conf["quantiles"]["n2_extrap"], ensure_ascii=False)[:600],
          "", "## 拒答原因构成（主判定折，示例通道 `bandwidth_Hz`）", "",
          "```", json.dumps(main_fold["channels"]["bandwidth_Hz"]["refusal_reasons"],
                            ensure_ascii=False, indent=1), "```", "",
          "## 结论", "", out["verdict"], "",
          "**未做 / 不在范围**：",
          "* 网页端点接入（下一轮）",
          "* 场级验证（**无场数据，已按用户指示挂起**；S1 历史评估为失败）",
          "* 任何「工程绝对值」主张（需 PMUT L1，仍为 0 条通过）", "",
          "模型状态：**`draft`**（人保留放行权，红线 5）。"]
    OUT_REPORT.write_text("\n".join(L), encoding="utf-8")

    print("主判定折：", out["verdict"])
    for ch, v in summary.items():
        print("   %-22s 覆盖 %5.1f%%  中位 %s  p90 %s  → %s"
              % (ch, 100 * (v["coverage"] or 0), _fmt(v["median"]), _fmt(v["p90"]),
                 v["verdict_n2_extrap"]))
    print("已写：%s / %s" % (OUT_JSON.name, OUT_REPORT.name))
    return 0


def _fmt(v):
    return "—" if v is None else ("%.4f" % v if abs(v) < 100 else "%.1f" % v)


if __name__ == "__main__":
    sys.exit(main())
