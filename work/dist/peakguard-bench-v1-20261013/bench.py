# -*- coding: utf-8 -*-
"""N2-1 强基线（≥5 种子）+ N2-2 消融（6 项）——**本地、非求解**。

纪律
----
* 切分**只用** `data/splits_grouped_five_seeds.csv`
  的 `side_seed0..4`（整组同一侧，禁止自己乱切）。
* 标签主表 = `data/labels_two_batch_v3.csv`（2255×30）。
  该表**只有 4 个通道列**（`bandwidth_Hz`/`Q`/`peak_freq_Hz`/`spl_dB`）；另外 4 个
  （`abs_w_m`/`abs_p_Pa`/`abs_p_per_V_Pa`/`abs_vz_struct_m3s`）按 (batch, round6 组合键)
  从 A/C 侧 `first-peak-20260929/multichannel_labels.csv`（64 列）与 V2 侧
  `remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv` 补齐。
  V2 侧**没有**这 4 列 ⇒ 该 4 通道在 V2 批上**无数据**（如实报 0，不编造）。
* 指标：逐通道、**按批分列**、**不池化**、**无任何加权总分**。
  相对误差 = |pred − truth| / truth，分母 = 该通道真值且 > 0（分母行数逐格给出）。
* 不跑 COMSOL、不装包、不改任何既有文件、不提升任何状态。

产物：`baselines_by_seed.json`、`baseline_table.md`、`ablations.json`、`ablations.md`
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as _dt
import hashlib
import importlib.util
import json
import math
import pathlib
import sys
import time

import numpy as np

PKG = pathlib.Path(__file__).resolve().parent
# --- 以下两个小助手从既有实现**逐字内联**（使本包自包含）---
from collections.abc import Mapping, Sequence  # noqa: E402
from typing import Any  # noqa: E402


def _num(v: Any) -> Any:
    """把"看起来是数"的参数值统一成 int/float。

    实测必要性：CSV 里 `x_scale=0.40`、`N_w_te1=6.0` 都是**字符串**，而候选网格 JSON 里是
    数字；不做归一化会导致"同一个点"被当成两个点（质量修复目标永远匹配不上、选点重复）。
    """
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if not s:
        return v
    try:
        f = float(s)
    except ValueError:
        return v
    return int(f) if f.is_integer() else f


def _identity_key(rec: Mapping[str, Any], param_keys: Sequence[str],
                  decimals: int | None) -> tuple:
    """组合身份键。``decimals=None`` ⇒ 原样（用 `repr` 保留 1 ulp 差）。"""
    out: list[Any] = []
    for k in param_keys:
        v = _num(rec.get(k))
        if decimals is not None and isinstance(v, float):
            v = round(v, decimals)
        out.append(repr(v) if decimals is None else v)
    return tuple(out)


# ----------------------------------------------------------------- 输入（只读）
V3 = PKG / "data" / "labels_two_batch_v3.csv"
AC = PKG / "data" / "channels_multichannel.csv"
V2L = PKG / "data" / "labels_v2_frozen.csv"
ASSIGN = PKG / "data" / "splits_grouped_five_seeds.csv"
FITTER = PKG / "pchip_fitter.py"
QUARANTINE = PKG / "data" / "excluded_quarantine.json"
THRESHOLDS = PKG / "config" / "thresholds.json"
OUT = PKG / "results"

SEEDS = (0, 1, 2, 3, 4)
BATCHES = ("A_5-35MHz", "C_5-50MHz", "V2_5-35MHz")

CH8 = ("bandwidth_Hz", "Q_factor", "f_peak_Hz", "peak_SPL_dB",
       "abs_w_m", "abs_p_Pa", "abs_p_per_V_Pa", "abs_vz_struct_m3s")
#: v3 并集表的 4 个通道列名
V3_MAP = {"bandwidth_Hz": "bandwidth_Hz", "Q_factor": "Q",
          "f_peak_Hz": "peak_freq_Hz", "peak_SPL_dB": "spl_dB"}
#: V2 冻结副本的 4 个通道列名
V2_MAP = {"bandwidth_Hz": "bandwidth_Hz", "Q_factor": "Q",
          "f_peak_Hz": "peak_freq_Hz", "peak_SPL_dB": "peak_spl_dB"}
#: V2 侧缺这 4 列 ⇒ 该批无数据
V2_MISSING = ("abs_w_m", "abs_p_Pa", "abs_p_per_V_Pa", "abs_vz_struct_m3s")

#: 通道口径（沿用既有 `fit_multichannel_surrogate.CHANNELS`：空间 + 有定义所需条件）
SPACE = {"bandwidth_Hz": "log10", "abs_w_m": "log10", "abs_p_per_V_Pa": "log10",
         "f_peak_Hz": "log10", "abs_p_Pa": "log10", "abs_vz_struct_m3s": "log10",
         "peak_SPL_dB": "identity", "Q_factor": "log10"}
COND = {"bandwidth_Hz": "closed", "Q_factor": "closed", "f_peak_Hz": "peak",
        "peak_SPL_dB": "peak", "abs_w_m": "peak", "abs_p_Pa": "peak",
        "abs_p_per_V_Pa": "peak", "abs_vz_struct_m3s": "peak"}
GROUP = {"bandwidth_Hz": "§3.2 带宽", "abs_w_m": "§3.1 振幅",
         "abs_p_per_V_Pa": "§3.3 灵敏度", "f_peak_Hz": "描述",
         "abs_p_Pa": "§3.1 振幅", "abs_vz_struct_m3s": "§3.1 振幅",
         "peak_SPL_dB": "§3.1 振幅", "Q_factor": "门槛(报告)"}
IS_FORMAL = {"bandwidth_Hz": True, "abs_w_m": True, "abs_p_per_V_Pa": True,
             "f_peak_Hz": False, "abs_p_Pa": False, "abs_vz_struct_m3s": False,
             "peak_SPL_dB": False, "Q_factor": False}

FIT6 = ("linear", "rbf", "poly2_ridge", "GP", "boosted_trees", "MLP")
ALL_METHODS = ("persistence", "pchip") + FIT6
TOL = (0.03, 0.10, 0.25)          # false-accept 容差；0.03 = solver_spec S2 参考线
GP_MAX_TRAIN = 500
GP_MAX_TRAIN_SMALL = 200          # 该批训练行更少时不再降采样
ABL_TREES_ITER = 150


# ----------------------------------------------------------------- 基础工具
def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def fnum(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def truthy(v) -> bool:
    return str(v).strip().lower() == "true"


def r6key(batch, x, n1, n2):
    return (batch,) + _identity_key({"x_scale": x, "N_w_te1": n1, "N_w_te2": n2},
                                    ("x_scale", "N_w_te1", "N_w_te2"), 6)


def load_fitter():
    spec = importlib.util.spec_from_file_location("_mc_fit_n2", FITTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def q(a, p):
    return float(np.percentile(np.asarray(a, float), p))


def stats(rel, extra_abs=None):
    if len(rel) == 0:
        return {"n": 0, "median": None, "p90": None, "max": None, "mean": None}
    a = np.asarray(rel, float)
    out = {"n": int(a.size), "median": float(np.median(a)), "p90": q(a, 90),
           "max": float(a.max()), "mean": float(a.mean())}
    if extra_abs is not None and len(extra_abs):
        b = np.asarray(extra_abs, float)
        out["abs_median"] = float(np.median(b))
        out["abs_p90"] = q(b, 90)
    return out


def rel_err(pred, truth):
    return abs(pred - truth) / truth


def to_space(ch, y):
    return math.log10(y) if SPACE[ch] == "log10" else y


def from_space(ch, z):
    return 10.0 ** z if SPACE[ch] == "log10" else z


def from_space_sp(sp, z):
    """按**实际使用的目标空间**还原（消融 ④ 会改空间，不能再用通道默认空间）。"""
    if sp == "log10":
        return 10.0 ** z if z < 300 else float("inf")
    return z


# ----------------------------------------------------------------- 数据装载
class Row(dict):
    pass


def load_all():
    """装配行记录。返回 (rows, meta)。"""
    meta = {"inputs": {}}
    for p in (V3, AC, V2L, ASSIGN, FITTER, QUARANTINE, THRESHOLDS):
        meta["inputs"][str(p.relative_to(PKG)).replace("\\", "/")] = {
            "bytes": p.stat().st_size, "sha256": sha256_file(p)}

    with V3.open(encoding="utf-8-sig", newline="") as fh:
        v3 = list(csv.DictReader(fh))
    with ASSIGN.open(encoding="utf-8-sig", newline="") as fh:
        asg = list(csv.DictReader(fh))
    if len(v3) != len(asg):
        raise SystemExit("[FAIL] v3 行数 %d ≠ 指派表行数 %d" % (len(v3), len(asg)))

    # --- 指派表：row_index → side_seed* ---
    side: dict[int, dict] = {}
    for r in asg:
        side[int(r["row_index"])] = {s: r["side_seed%d" % s] for s in SEEDS}

    # --- A/C 侧 8 通道 + 原生状态标志 ---
    ac_by_key: dict[tuple, dict] = {}
    with AC.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            ds = str(r.get("source_dataset", "")).strip()
            if ds not in ("A", "C"):
                continue
            x, n1, n2 = fnum(r["x_scale"]), fnum(r["N_w_te1"]), fnum(r["N_w_te2"])
            if None in (x, n1, n2):
                continue
            b = "A_5-35MHz" if ds == "A" else "C_5-50MHz"
            k = r6key(b, x, n1, n2)
            d = {"ch": {c: fnum(r.get(c)) for c in CH8},
                 "peaked": truthy(r.get("first_peak_found")),
                 "closed": truthy(r.get("bandwidth_closed")),
                 "quarantined": truthy(r.get("quarantined")),
                 "flag_usable": truthy(r.get("ranking_eligible")),
                 "flag_note": "native"}
            if k in ac_by_key:
                raise SystemExit("[FAIL] A/C 侧组合键重复：%r" % (k,))
            ac_by_key[k] = d

    # --- V2 侧 4 通道 + 代理状态标志 ---
    v2_by_key: dict[tuple, dict] = {}
    with V2L.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            x, n1, n2 = fnum(r["x_scale"]), fnum(r["N_w_te1"]), fnum(r["N_w_te2"])
            if None in (x, n1, n2):
                continue
            k = r6key("V2_5-35MHz", x, n1, n2)
            peak_end = truthy(r.get("peak_at_scan_endpoint"))
            bw_end = truthy(r.get("bw_upper_cutoff_at_endpoint"))
            d = {"ch": {c: None for c in CH8},
                 "peaked": not peak_end,
                 "closed": (not peak_end) and (not bw_end),
                 "quarantined": False,
                 "flag_usable": (not peak_end) and (not bw_end),
                 "flag_note": "proxy"}
            for c, col in V2_MAP.items():
                d[c] = fnum(r.get(col))
                d["ch"][c] = fnum(r.get(col))
            if k in v2_by_key:
                raise SystemExit("[FAIL] V2 侧组合键重复：%r" % (k,))
            v2_by_key[k] = d

    rows: list[Row] = []
    audit = {"v3_vs_source_channel_mismatch": 0, "v3_missing_source": 0,
             "mismatch_examples": []}
    for i, r in enumerate(v3):
        x, n1, n2 = fnum(r["x_scale"]), fnum(r["N_w_te1"]), fnum(r["N_w_te2"])
        b = r["batch"]
        if b not in BATCHES:
            raise SystemExit("[FAIL] 未知批：%r" % b)
        k = r6key(b, x, n1, n2)
        src = ac_by_key.get(k) if b != "V2_5-35MHz" else v2_by_key.get(k)
        if src is None:
            audit["v3_missing_source"] += 1
            continue
        d = Row(batch=b, x=x, n1=n1, n2=n2, key=k, row_index=i,
                peaked=src["peaked"], closed=src["closed"],
                quarantined=src["quarantined"], flag_usable=src["flag_usable"],
                flag_note=src["flag_note"],
                ch=dict(src["ch"]),
                side={s: side[i][s] for s in SEEDS},
                v3_values={c: fnum(r.get(col)) for c, col in V3_MAP.items()})
        # 既有评估内核（fit_multichannel_surrogate）按 row[channel] 取值 ⇒ 顶层也放一份
        for c in CH8:
            d[c] = src["ch"].get(c)
        # 交叉核对：v3 主表的 4 列 vs 源表
        for c, col in V3_MAP.items():
            a, bb = d["v3_values"][c], d["ch"][c]
            if (a is None) != (bb is None) or (a is not None and abs(a - bb) > 1e-9):
                audit["v3_vs_source_channel_mismatch"] += 1
                if len(audit["mismatch_examples"]) < 5:
                    audit["mismatch_examples"].append(
                        {"batch": b, "x": x, "n1": n1, "n2": n2, "channel": c,
                         "v3": a, "source": bb})
        rows.append(d)
    meta["row_audit"] = audit
    meta["n_rows"] = len(rows)
    meta["batch_counts"] = dict(collections.Counter(r["batch"] for r in rows))
    meta["side_counts"] = {str(s): dict(collections.Counter(r["side"][s] for r in rows))
                           for s in SEEDS}
    meta["channel_column_available"] = {
        b: [c for c in CH8 if any(r["batch"] == b and r["ch"].get(c) is not None
                                  for r in rows)] for b in BATCHES}
    meta["flag_note_by_batch"] = {b: sorted({r["flag_note"] for r in rows
                                             if r["batch"] == b}) for b in BATCHES}
    return rows, meta


# ----------------------------------------------------------------- 判定与口径
def defined(row, ch, state_filter=True) -> bool:
    """该行在该通道是否有定义（+真值 > 0）。`state_filter=False` ⇒ 只看数值列。"""
    v = row["ch"].get(ch)
    if v is None or not (v > 0):
        return False
    if not state_filter:
        return True
    cond = COND[ch]
    if cond == "closed" and not row["closed"]:
        return False
    if cond == "peak" and not row["peaked"]:
        return False
    return True


def in_domain_train(train, ch, x, n1, n2, state_filter=True) -> bool:
    """代理适用域（层存在 ∧ x 落在该层训练 x 范围内）。"""
    if not (5 <= n2 <= 9) or n1 >= n2:
        return False
    xs = [r["x"] for r in train
          if r["n2"] == n2 and r["n1"] == n1 and defined(r, ch, state_filter)]
    if not xs:
        return False
    return min(xs) - 1e-9 <= x <= max(xs) + 1e-9


# ----------------------------------------------------------------- 基线（非拟合）
def persistence_pred(train, ch, row, state_filter=True):
    """同 (N1) 层最近邻：与既有 `baseline_persistence` 同口径（逐行版）。"""
    xr = round(row["x"], 6)
    cand = []
    for r in train:
        if r["n1"] != row["n1"]:
            continue
        if round(r["x"], 6) != xr:
            continue
        if not defined(r, ch, state_filter):
            continue
        cand.append((r["n2"], r["ch"][ch]))
    if not cand:
        return None
    near = min(cand, key=lambda t: abs(t[0] - row["n2"]))
    return near[1]


def nearest_fill(train, ch, row, state_filter=True):
    """兜底：训练集里 (x,N1,N2) 标准化欧氏距离最近的有定义行。"""
    best, bd = None, None
    for r in train:
        if not defined(r, ch, state_filter):
            continue
        d = ((r["x"] - row["x"]) / 0.45) ** 2 + (r["n1"] - row["n1"]) ** 2 \
            + (r["n2"] - row["n2"]) ** 2
        if bd is None or d < bd:
            best, bd = r["ch"][ch], d
    return best


def pchip_model(F, train, ch, state_filter=True):
    """既有口径层内 PCHIP + N2 一步线性外推（**直接 import 既有实现**）。"""
    if state_filter:
        return F.build(train, ch)
    # 关掉状态过滤时复用同一实现，但把过滤条件替换为「只看数值列」
    layers = {}
    for r in train:
        if not defined(r, ch, False):
            continue
        layers.setdefault((r["n2"], r["n1"]), {})[round(r["x"], 6)] = to_space(ch, r["ch"][ch])
    fits = {k: F.LayerFit(sorted(v), [v[x] for x in sorted(v)]) for k, v in layers.items()}
    return {"layers": layers, "fits": fits}


def pchip_pred(F, model, ch, row):
    p, mode = F.predict_one(model, ch, row["x"], row["n1"], row["n2"])
    return p, mode


# ----------------------------------------------------------------- 拟合族
def _xy(rows, ch, state_filter=True, log_on=None):
    X, y = [], []
    sp = SPACE[ch] if log_on is None else ("log10" if log_on else "identity")
    for r in rows:
        if not defined(r, ch, state_filter):
            continue
        v = r["ch"][ch]
        if sp == "log10" and not (v > 0):
            continue
        X.append([r["x"], r["n1"], r["n2"]])
        y.append(math.log10(v) if sp == "log10" else v)
    return np.asarray(X, float).reshape(-1, 3), np.asarray(y, float), sp


class Fitted:
    """统一包装：fit → predict(rows) → 值域还原。"""

    def __init__(self, name, seed):
        self.name = name
        self.seed = seed
        self.sp = None
        self.ok = False
        self.err = None
        self.note = ""

    def fit(self, rows, ch, state_filter=True, log_on=None):
        from sklearn.preprocessing import StandardScaler
        X, y, sp = _xy(rows, ch, state_filter, log_on)
        self.sp = sp
        n = len(y)
        if n < 8:
            self.err = "训练行不足（%d < 8）" % n
            return self
        try:
            if self.name in ("linear", "rbf", "poly2_ridge", "GP", "MLP"):
                self.sx = StandardScaler().fit(X)
                self.sy = StandardScaler().fit(y.reshape(-1, 1))
                Xs = self.sx.transform(X)
                ys = self.sy.transform(y.reshape(-1, 1)).ravel()
            else:
                Xs, ys = X, y
            if self.name == "linear":
                from sklearn.linear_model import LinearRegression
                self.m = LinearRegression().fit(Xs, ys)
            elif self.name == "rbf":
                from sklearn.kernel_ridge import KernelRidge
                self.m = KernelRidge(kernel="rbf", alpha=1e-2,
                                     gamma=1.0 / Xs.shape[1]).fit(Xs, ys)
            elif self.name == "poly2_ridge":
                from sklearn.linear_model import RidgeCV
                from sklearn.pipeline import make_pipeline
                from sklearn.preprocessing import PolynomialFeatures
                self.m = make_pipeline(
                    PolynomialFeatures(2, include_bias=False),
                    RidgeCV(alphas=np.logspace(-4, 3, 20))).fit(Xs, ys)
            elif self.name == "GP":
                from sklearn.gaussian_process import GaussianProcessRegressor
                from sklearn.gaussian_process.kernels import (ConstantKernel, Matern,
                                                              WhiteKernel)
                rng = np.random.default_rng(1000 + self.seed)
                cap = GP_MAX_TRAIN if n > GP_MAX_TRAIN_SMALL else n
                if n > cap:
                    idx = np.sort(rng.choice(n, cap, replace=False))
                    Xg, yg = Xs[idx], ys[idx]
                    self.note = "训练点由 %d 降采样到 %d（GP O(n³) 限速，已如实登记）" % (n, cap)
                else:
                    Xg, yg = Xs, ys
                k = (ConstantKernel(1.0, (1e-2, 1e2))
                     * Matern(length_scale=np.ones(Xs.shape[1]), nu=2.5,
                              length_scale_bounds=(1e-2, 1e2))
                     + WhiteKernel(1e-3, (1e-8, 1e0)))
                self.m = GaussianProcessRegressor(
                    kernel=k, normalize_y=False, n_restarts_optimizer=1,
                    random_state=self.seed, alpha=1e-10).fit(Xg, yg)
            elif self.name == "boosted_trees":
                from sklearn.ensemble import HistGradientBoostingRegressor
                self.m = HistGradientBoostingRegressor(
                    max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                    min_samples_leaf=20, l2_regularization=1e-3,
                    random_state=self.seed, early_stopping=False).fit(Xs, ys)
            elif self.name == "MLP":
                from sklearn.neural_network import MLPRegressor
                self.m = MLPRegressor(hidden_layer_sizes=(64, 32), activation="relu",
                                      solver="adam", alpha=1e-4, learning_rate_init=1e-3,
                                      max_iter=400, early_stopping=True,
                                      validation_fraction=0.15, n_iter_no_change=20,
                                      random_state=self.seed).fit(Xs, ys)
            else:
                raise ValueError(self.name)
            self.ok = True
        except Exception as exc:                                  # noqa: BLE001
            self.err = "%s: %r" % (type(exc).__name__, exc)
        return self

    def predict(self, rows, ch, state_filter=True):
        X = np.asarray([[r["x"], r["n1"], r["n2"]] for r in rows], float).reshape(-1, 3)
        if self.name in ("linear", "rbf", "poly2_ridge", "GP", "MLP"):
            z = self.m.predict(self.sx.transform(X)).reshape(-1, 1)
            z = self.sy.inverse_transform(z).ravel()
        else:
            z = self.m.predict(X)
        return np.asarray([from_space(ch, float(v)) for v in z], float)


# ----------------------------------------------------------------- 评估内核
def eval_cell(F, train, holdout, ch, seed, state_filter=True):
    """一个 (批 × 种子 × 通道) 的完整评估。"""
    defined_rows = [r for r in holdout if defined(r, ch, state_filter)]
    ndef = len(defined_rows)
    truth = np.asarray([r["ch"][ch] for r in defined_rows], float)
    per_method = {}

    # --- persistence ---
    pv = [persistence_pred(train, ch, r, state_filter) for r in defined_rows]
    preds = {"persistence": pv}
    # --- pchip（既有口径）---
    model = pchip_model(F, train, ch, state_filter)
    ph, modes = [], []
    for r in defined_rows:
        p, m = pchip_pred(F, model, ch, r)
        ph.append(p)
        modes.append(m)
    preds["pchip"] = ph
    # --- 6 个拟合族 ---
    fitted = {}
    for name in FIT6:
        m = Fitted(name, seed).fit(train, ch, state_filter)
        fitted[name] = m
        preds[name] = list(m.predict(defined_rows, ch, state_filter)) if m.ok else [None] * ndef

    for name in ALL_METHODS:
        p = preds[name]
        idx = [i for i in range(ndef) if p[i] is not None and math.isfinite(p[i]) and p[i] > 0]
        rel = [rel_err(p[i], truth[i]) for i in idx]
        ab = [abs(p[i] - truth[i]) for i in idx] if ch == "peak_SPL_dB" else None
        st = stats(rel, ab)
        # 与 persistence 配对（同一次要子集）
        pidx = [i for i in idx if pv[i] is not None]
        pr = [rel_err(p[i], truth[i]) for i in pidx]
        br = [rel_err(pv[i], truth[i]) for i in pidx]
        lift_paired = (float(np.median(br) - np.median(pr))) if pr else None
        own_base = stats([rel_err(pv[i], truth[i]) for i in idx if pv[i] is not None])
        lift_own = (None if (st["median"] is None or own_base["median"] is None)
                    else own_base["median"] - st["median"])
        per_method[name] = {
            "n_predicted": len(idx), "coverage_of_defined": (len(idx) / ndef) if ndef else None,
            "median": st["median"], "p90": st["p90"], "max": st["max"],
            "abs_median_dB": st.get("abs_median"), "abs_p90_dB": st.get("abs_p90"),
            "n_paired_with_persistence": len(pidx),
            "lift_vs_persistence_paired": lift_paired,
            "lift_vs_persistence_own": lift_own,
            "beats_persistence_paired": (None if lift_paired is None else bool(lift_paired >= 0)),
            "fit_ok": True if name not in FIT6 else bool(fitted[name].ok),
            "fit_note": (fitted[name].note or fitted[name].err or "") if name in FIT6 else "",
            "false_accept": {
                "%g" % t: (float(np.mean([1.0 if e > t else 0.0 for e in rel]))
                           if rel else None) for t in TOL},
        }
        if name == "pchip":
            per_method[name]["modes"] = dict(collections.Counter(
                m for m, i in zip(modes, range(ndef)) if preds[name][i] is not None
                and i in set(idx)))
            per_method[name]["refusals"] = dict(collections.Counter(
                m for m, i in zip(modes, range(ndef)) if preds[name][i] is None))

    # --- 全方法公共掩膜 + 7 方法公共掩膜（含/不含 pchip；pchip 有结构性拒答）---
    def _mask(names):
        return [i for i in range(ndef)
                if all(preds[n][i] is not None and math.isfinite(preds[n][i])
                       and preds[n][i] > 0 for n in names)]

    def _core_of(names):
        common = _mask(names)
        c = {"n": len(common), "member_methods": list(names)}
        if common:
            c["persistence_median"] = float(np.median(
                [rel_err(pv[i], truth[i]) for i in common]))
            c["methods"] = {}
            for n in names:
                e = [rel_err(preds[n][i], truth[i]) for i in common]
                c["methods"][n] = {
                    "median": float(np.median(e)), "p90": q(e, 90), "max": float(max(e)),
                    "lift_vs_persistence_paired": c["persistence_median"] - float(np.median(e))}
        else:
            c["methods"] = {}
        return c

    core = _core_of(ALL_METHODS)
    core7 = _core_of(tuple(n for n in ALL_METHODS if n != "pchip"))
    return {"n_defined_pos": ndef, "common_mask_n": core["n"], "core": core,
            "core7": core7, "methods": per_method}


# ----------------------------------------------------------------- N2-1 主流程
def run_baselines(F, rows, meta, n_seeds):
    store = {"per_seed": {}, "agg": {}}
    for b in BATCHES:
        store["per_seed"][b] = {}
        for s in SEEDS[:n_seeds]:
            tr = [r for r in rows if r["batch"] == b and r["side"][s] == "train"
                  and not r["quarantined"]]
            ho = [r for r in rows if r["batch"] == b and r["side"][s] == "holdout"
                  and not r["quarantined"]]
            trk = {r["key"] for r in tr}
            leak = sum(1 for r in ho if r["key"] in trk)
            cell = {"n_train_rows": len(tr), "n_holdout_rows": len(ho), "leak_rows": leak,
                    "channels": {}}
            for ch in CH8:
                if not any(r["ch"].get(ch) is not None for r in rows if r["batch"] == b):
                    cell["channels"][ch] = {"n_defined_pos": 0, "no_column": True,
                                            "methods": {}, "core": {"n": 0, "methods": {}}}
                    continue
                t0 = time.time()
                cell["channels"][ch] = eval_cell(F, tr, ho, ch, s)
                cell["channels"][ch]["seconds"] = round(time.time() - t0, 2)
            store["per_seed"][b][str(s)] = cell
            print("   [N2-1] %-11s seed %d  train %4d / holdout %4d  leak %d"
                  % (b, s, len(tr), len(ho), leak), flush=True)

    # --- 种子间波动汇总 ---
    for b in BATCHES:
        agg = {}
        for ch in CH8:
            per = {}
            for name in ALL_METHODS:
                lf, md, cov, mx, p9 = [], [], [], [], []
                for s in SEEDS[:n_seeds]:
                    c = store["per_seed"][b][str(s)]["channels"][ch]
                    m = c["methods"].get(name)
                    if not m or m["median"] is None:
                        continue
                    md.append(m["median"])
                    cov.append(m["coverage_of_defined"])
                    if m["lift_vs_persistence_paired"] is not None:
                        lf.append(m["lift_vs_persistence_paired"])
                    if m["max"] is not None:
                        mx.append(m["max"])
                    if m["p90"] is not None:
                        p9.append(m["p90"])
                if not md and not lf:
                    continue
                per[name] = {
                    "n_seeds_with_numbers": len(md),
                    "median_err_min": min(md) if md else None,
                    "median_err_max": max(md) if md else None,
                    "median_err_std": float(np.std(md)) if md else None,
                    "median_err_by_seed": md,
                    "p90_median": float(np.median(p9)) if p9 else None,
                    "p90_min": min(p9) if p9 else None,
                    "p90_max": max(p9) if p9 else None,
                    "max_err_min": min(mx) if mx else None,
                    "max_err_max": max(mx) if mx else None,
                    "coverage_min": min(cov) if cov else None,
                    "coverage_max": max(cov) if cov else None,
                    "lift_paired_min": min(lf) if lf else None,
                    "lift_paired_max": max(lf) if lf else None,
                    "lift_paired_std": float(np.std(lf)) if lf else None,
                    "lift_paired_by_seed": lf,
                    "n_seeds_lift_positive": sum(1 for x in lf if x >= 0),
                    "n_seeds_lift_negative": sum(1 for x in lf if x < 0),
                }
            # 公共掩膜上的最好方法（按 median，逐种子投票）；用 core7（不含 pchip）
            votes = collections.Counter()
            for s in SEEDS[:n_seeds]:
                c = store["per_seed"][b][str(s)]["channels"][ch].get("core7") or {}
                ms = c.get("methods") or {}
                if not ms or c.get("n", 0) < 30:
                    continue
                votes[min(ms, key=lambda n: ms[n]["median"])] += 1
            agg[ch] = {"per_method": per,
                       "best_method_votes_on_core7": dict(votes),
                       "core7_n_by_seed": [(store["per_seed"][b][str(s)]["channels"][ch]
                                            .get("core7") or {}).get("n")
                                           for s in SEEDS[:n_seeds]],
                       "core_all8_n_by_seed": [store["per_seed"][b][str(s)]["channels"][ch]
                                               ["core"]["n"] for s in SEEDS[:n_seeds]]}
        store["agg"][b] = agg
    return store


# ----------------------------------------------------------------- N2-2 消融
def _trees(seed, iters=ABL_TREES_ITER):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(max_iter=iters, learning_rate=0.08,
                                         max_leaf_nodes=31, min_samples_leaf=20,
                                         l2_regularization=1e-3, random_state=seed,
                                         early_stopping=False)


def _fit_predict_trees(tr, ho, ch, seed, state_filter=True, log_on=None):
    X, y, sp = _xy(tr, ch, state_filter, log_on)
    if len(y) < 8:
        return [None] * len(ho), sp
    m = _trees(seed).fit(X, y)
    Xh = np.asarray([[r["x"], r["n1"], r["n2"]] for r in ho], float).reshape(-1, 3)
    z = m.predict(Xh)
    return [from_space_sp(sp, float(v)) for v in z], sp


def _cell_stats(ho, ch, preds, state_filter=True):
    """返回 (n_defined_pos, stats over predicted defined rows, rel list, idx)。"""
    idx = [i for i, r in enumerate(ho)
           if defined(r, ch, state_filter) and preds[i] is not None
           and math.isfinite(preds[i]) and preds[i] > 0]
    rel = [rel_err(preds[i], ho[i]["ch"][ch]) for i in idx]
    return len([1 for r in ho if defined(r, ch, state_filter)]), stats(rel), rel, idx


def run_ablations(F, rows, meta, n_seeds):
    """6 项消融；每项**只改一个变量**，其余（数据/切分/特征/超参）不变。"""
    qlist = json.loads(QUARANTINE.read_text(encoding="utf-8")).get("excluded_quarantine") or []
    QUAR = {tuple(round(float(v), 6) for v in t) for t in qlist}
    spec = {"thresholds": json.loads(THRESHOLDS.read_text(encoding="utf-8")).get("thresholds") or {}}
    out = {"method_for_ablations": "boosted_trees(HistGradientBoostingRegressor, "
                                  "max_iter=%d, learning_rate=0.08)" % ABL_TREES_ITER,
           "seeds": list(SEEDS[:n_seeds]),
           "quarantine_source": {"file": "data/excluded_quarantine.json",
                                 "excluded_quarantine": qlist,
                                 "labels_two_batch_has_field": False,
                                 "note": "labels_two_batch.csv（30 列）**没有** excluded_quarantine 字段；"
                                         "本项用冻结模型的 excluded_quarantine 列表，"
                                         "并用 A/C 表原生 quarantined 标志作为最接近的可用口径另行计数。"},
           "solver_spec_thresholds_reference": spec.get("thresholds"),
           "items": {}}
    out["comparison_semantics"] = {
        "A1_peak_semantics": "改的是**行成员口径**（训练与留出同时改用同一过滤规则）："
                             "「当作普通值」= 只看数值列（不查 peaked/closed），"
                             "「按状态过滤」= 还要满足该通道的状态条件。",
        "A2_refusal": "「有拒答」= 既有 pchip 口径（结构性拒答，误差只在被接受子集上算）；"
                      "「无拒答」= pchip 给不出数时用 persistence→最近邻兜底填充，覆盖率=1。"
                      "两臂**不是同一行集**，故 Δmedian 只作副作用参考，主看覆盖率与 false-accept。",
        "A3_quarantine": "改的是**行成员**：两臂都**不做** `quarantined` 预过滤；"
                         "「启用(排除)」剔除原生 `quarantined=True` 或落在 "
                         "`excluded_quarantine` 列表里的行；「禁用(保留)」全部保留。"
                         "Δ = 禁用(保留) − 启用(排除)。",
        "A4_log_transform": "改的是**目标空间**：臂 1 强制 log10(y)；臂 2 用原空间 y。"
                            "特征与超参不变。Δ = 原空间(关) − log10(开)。"
                            "⚠️ `peak_SPL_dB` 的声明空间本就是 identity（dB 非比例尺度）⇒ "
                            "该通道的臂 1 是**超口径的敏感性**，只作参考。",
        "A5_extrapolation_limit": "改的是**是否接受域外预测**："
                                  "「不限制」接受全部；「限制」只接受层存在且 x 在训练层范围内的行；"
                                  "「被限制挡下的行(诊断)」= 这些被挡行的误差（看拒答是否合理）。",
        "A6_active_sampling": "改的是**是否给模型补 10% 额外带标签点**（最远点贪心，只用特征）；"
                              "两臂都在去掉补点后的剩余 holdout 上评估（同分母）。"
                              "补点用了 holdout 标签 = oracle 预算，已如实披露。",
    }

    def base_tr_ho(b, s, drop_quar=False, prefilter_quar=True):
        """`prefilter_quar=True` ⇒ 沿用既有口径先把 quarantined 行剔掉（N2-1 用）。

        消融 ③ 需要 `prefilter_quar=False`（否则「禁用隔离」臂会因预过滤而变成空操作）。
        """
        tr = [r for r in rows if r["batch"] == b and r["side"][s] == "train"
              and ((not prefilter_quar) or (not r["quarantined"]))]
        ho = [r for r in rows if r["batch"] == b and r["side"][s] == "holdout"
              and ((not prefilter_quar) or (not r["quarantined"]))]
        if drop_quar:
            tr = [r for r in tr if (round(r["x"], 6), r["n1"], r["n2"]) not in QUAR]
            ho = [r for r in ho if (round(r["x"], 6), r["n1"], r["n2"]) not in QUAR]
        return tr, ho

    def record(item, b, ch, s, arm, value):
        out["items"].setdefault(item, {}).setdefault(b, {}).setdefault(ch, {}) \
            .setdefault(arm, {})[str(s)] = value

    # 原生 quarantined 标志计数（最接近的可用口径）
    quar_counts = {}
    for b in BATCHES:
        quar_counts[b] = {
            "n_rows_native_quarantined_flag_true": sum(
                1 for r in rows if r["batch"] == b and r["quarantined"]),
            "n_rows_in_excluded_quarantine_list": sum(
                1 for r in rows if r["batch"] == b
                and (round(r["x"], 6), r["n1"], r["n2"]) in QUAR),
            "flag_note": sorted({r["flag_note"] for r in rows if r["batch"] == b}),
        }
    out["quarantine_flag_counts"] = quar_counts

    # ① 峰语义的**可区分性审计**：若「状态为假」的行其数值列本来就是空，
    #    那么「当普通值 vs 按状态过滤」两臂必然完全相同（该消融在该批上无区分力）。
    sem_audit = {}
    for b in BATCHES:
        per = {}
        for ch in CH8:
            if not any(r["ch"].get(ch) is not None for r in rows if r["batch"] == b):
                continue
            n_val_flag_false = 0
            n_flag_true_val_missing = 0
            for r in rows:
                if r["batch"] != b:
                    continue
                v = r["ch"].get(ch)
                has_val = v is not None and v > 0
                st = r["closed"] if COND[ch] == "closed" else r["peaked"]
                if has_val and not st:
                    n_val_flag_false += 1
                if st and not has_val:
                    n_flag_true_val_missing += 1
            per[ch] = {"n_rows_value_present_but_state_false": n_val_flag_false,
                       "n_rows_state_true_but_value_missing": n_flag_true_val_missing}
        sem_audit[b] = per
    out["peak_semantics_audit"] = sem_audit

    for b in BATCHES:
        chans = [c for c in CH8
                 if any(r["ch"].get(c) is not None for r in rows if r["batch"] == b)]
        for ch in chans:
            for s in SEEDS[:n_seeds]:
                tr, ho = base_tr_ho(b, s)

                # ① 峰语义：状态过滤 vs 当作普通值
                for arm, sf in (("按状态过滤", True), ("当作普通值", False)):
                    trx = [r for r in tr if defined(r, ch, sf)]
                    p, _ = _fit_predict_trees(trx, ho, ch, s, state_filter=sf)
                    n_def, st, _, _ = _cell_stats(ho, ch, p, sf)
                    record("A1_peak_semantics", b, ch, s, arm,
                           {"n_train_used": len(trx), "n_defined_pos_holdout": n_def,
                            "median": st["median"], "p90": st["p90"], "max": st["max"]})

                # ② 拒答：有（既有 pchip 口径）vs 无（pchip + 兜底填充）
                dm = pchip_model(F, tr, ch, True)
                pchip_p, fill_p = [], []
                for r in ho:
                    p, _ = pchip_pred(F, dm, ch, r)
                    pchip_p.append(p)
                    if p is None:
                        fb = persistence_pred(tr, ch, r, True)
                        if fb is None:
                            fb = nearest_fill(tr, ch, r, True)
                        fill_p.append(fb)
                    else:
                        fill_p.append(p)
                for arm, p in (("有拒答", pchip_p), ("无拒答", fill_p)):
                    n_def, st, rel, idx = _cell_stats(ho, ch, p, True)
                    n_accept = len(idx)
                    record("A2_refusal", b, ch, s, arm,
                           {"n_defined_pos": n_def, "n_accepted": n_accept,
                            "coverage": (n_accept / n_def) if n_def else None,
                            "median": st["median"], "p90": st["p90"], "max": st["max"],
                            "false_accept_rate": {("%g" % t): (
                                float(np.mean([1.0 if e > t else 0.0 for e in rel]))
                                if rel else None) for t in TOL},
                            "false_accept_per_defined": {("%g" % t): (
                                (sum(1 for e in rel if e > t) / n_def) if n_def else None)
                                for t in TOL}})
                # 无拒答臂中「靠兜底填充」的那部分单独看
                filled_idx = [i for i, (a, bb) in enumerate(zip(pchip_p, fill_p))
                              if a is None and bb is not None and defined(ho[i], ch, True)
                              and bb > 0]
                record("A2_refusal", b, ch, s, "无拒答-仅兜底子集",
                       {"n_filled": len(filled_idx),
                        "median": (float(np.median(
                            [rel_err(fill_p[i], ho[i]["ch"][ch]) for i in filled_idx]))
                            if filled_idx else None)})

                # ③ 异常隔离：启用 vs 禁用（**不做预过滤**，否则「禁用」臂成空操作）
                for arm, dropq in (("启用(排除)", True), ("禁用(保留)", False)):
                    trq, hoq = base_tr_ho(b, s, drop_quar=dropq, prefilter_quar=False)
                    p, _ = _fit_predict_trees(trq, hoq, ch, s)
                    px = [persistence_pred(trq, ch, r, True) for r in hoq]
                    n_def, st, rel, idx = _cell_stats(hoq, ch, p, True)
                    pidx = [i for i in idx if px[i] is not None and px[i] > 0]
                    lift = (float(np.median([rel_err(px[i], hoq[i]["ch"][ch]) for i in pidx])
                                  - np.median([rel_err(p[i], hoq[i]["ch"][ch]) for i in pidx]))
                            if pidx else None)
                    record("A3_quarantine", b, ch, s, arm,
                           {"n_train_used": len(trq), "n_holdout": len(hoq),
                            "n_defined_pos": n_def, "median": st["median"],
                            "lift_vs_persistence_paired": lift,
                            "n_quarantined_removed_from_train":
                                len([r for r in rows if r["batch"] == b
                                     and r["side"][s] == "train" and r["quarantined"]]),
                            "n_excluded_list_removed_from_train":
                                len([r for r in rows if r["batch"] == b
                                     and r["side"][s] == "train"
                                     and (round(r["x"], 6), r["n1"], r["n2"]) in QUAR])})

                # ④ log 变换：开 vs 关（臂 1 **强制** log10；对声明 space=identity 的通道
                #    即是一次超口径的敏感性，已在报告里标注）
                for arm, lo in (("log10(开)", True), ("原空间(关)", False)):
                    trx = [r for r in tr if defined(r, ch, True)]
                    p, sp = _fit_predict_trees(trx, ho, ch, s, True, lo)
                    n_def, st, _, _ = _cell_stats(ho, ch, p, True)
                    record("A4_log_transform", b, ch, s, arm,
                           {"target_space_used": sp, "declared_space": SPACE[ch],
                            "n_defined_pos": n_def,
                            "median": st["median"], "p90": st["p90"], "max": st["max"]})

                # ⑤ 外推限制：限制在训练域内 vs 不限制
                trx = [r for r in tr if defined(r, ch, True)]
                p, _ = _fit_predict_trees(trx, ho, ch, s)
                guard = [in_domain_train(trx, ch, r["x"], r["n1"], r["n2"], True) for r in ho]
                n_def, st_all, rel_all, idx_all = _cell_stats(ho, ch, p, True)
                idx_in = [i for i in idx_all if guard[i]]
                idx_out = [i for i in idx_all if not guard[i]]
                rel_in = [rel_err(p[i], ho[i]["ch"][ch]) for i in idx_in]
                rel_out = [rel_err(p[i], ho[i]["ch"][ch]) for i in idx_out]
                record("A5_extrapolation_limit", b, ch, s, "不限制(全部接受)",
                       {"n_accepted": len(idx_all), "n_defined_pos": n_def,
                        "coverage": (len(idx_all) / n_def) if n_def else None,
                        "median": st_all["median"], "p90": st_all["p90"],
                        "max": st_all["max"]})
                record("A5_extrapolation_limit", b, ch, s, "限制在训练域内",
                       {"n_accepted": len(idx_in), "n_defined_pos": n_def,
                        "coverage": (len(idx_in) / n_def) if n_def else None,
                        "median": (float(np.median(rel_in)) if rel_in else None),
                        "p90": (q(rel_in, 90) if rel_in else None),
                        "max": (max(rel_in) if rel_in else None)})
                record("A5_extrapolation_limit", b, ch, s, "被限制挡下的行(诊断)",
                       {"n": len(idx_out),
                        "median": (float(np.median(rel_out)) if rel_out else None)})

                # ⑥ 主动补点：无 vs 有（预算 = holdout 行数 10%，最远点贪心，无标签信息）
                rng = np.random.default_rng(2000 + s)
                order = list(range(len(ho)))
                rng.shuffle(order)
                budget = max(1, int(round(0.10 * len(order))))
                added_idx = order[:budget]
                remain = [ho[i] for i in order[budget:]]
                if remain:
                    Fx = np.asarray([[r["x"] / 0.45, r["n1"], r["n2"]] for r in tr], float)
                    # 最远点贪心（只用特征，不用标签）
                    pool = np.asarray([[ho[i]["x"] / 0.45, ho[i]["n1"], ho[i]["n2"]]
                                       for i in added_idx], float)
                    allcand = np.asarray([[r["x"] / 0.45, r["n1"], r["n2"]] for r in ho], float)
                    chosen, dists = [], np.full(len(allcand), np.inf)
                    centers = Fx.copy()
                    for _ in range(budget):
                        d = np.min(np.linalg.norm(
                            allcand[:, None, :] - centers[None, :, :], axis=2), axis=1)
                        k = int(np.argmax(d))
                        chosen.append(k)
                        centers = np.vstack([centers, allcand[k:k + 1]])
                    added_rows = [ho[i] for i in sorted(set(chosen))]
                    p_no, _ = _fit_predict_trees(
                        [r for r in tr if defined(r, ch, True)], remain, ch, s)
                    p_yes, _ = _fit_predict_trees(
                        [r for r in tr if defined(r, ch, True)] + added_rows, remain, ch, s)
                    n_def, st_no, _, _ = _cell_stats(remain, ch, p_no, True)
                    _, st_yes, _, _ = _cell_stats(remain, ch, p_yes, True)
                    record("A6_active_sampling", b, ch, s, "无补点",
                           {"budget_added": len(added_rows),
                            "n_eval_rows_defined": n_def,
                            "median": st_no["median"], "p90": st_no["p90"],
                            "max": st_no["max"]})
                    record("A6_active_sampling", b, ch, s, "有补点(最远点贪心)",
                           {"budget_added": len(added_rows),
                            "n_eval_rows_defined": n_def,
                            "median": st_yes["median"], "p90": st_yes["p90"],
                            "max": st_yes["max"],
                            "label_use_note": "补点用了 holdout 行的标签（oracle 预算），"
                                              "两臂都在**去掉补点后的剩余 holdout**上评估"})
        print("   [N2-2] %s 完成" % b, flush=True)

    # --- 逐项汇总（跨种子）---
    summary = {}
    for item, per_b in out["items"].items():
        summary[item] = {}
        for b, per_ch in per_b.items():
            summary[item][b] = {}
            for ch, per_arm in per_ch.items():
                cells = {}
                for arm, per_seed in per_arm.items():
                    med = [v["median"] for v in per_seed.values() if v.get("median") is not None]
                    cells[arm] = {
                        "n_seeds": len(per_seed),
                        "median_err_median_over_seeds": float(np.median(med)) if med else None,
                        "median_err_min": min(med) if med else None,
                        "median_err_max": max(med) if med else None,
                        "extra": {k: sorted({json.dumps(v.get(k), ensure_ascii=False)
                                             for v in per_seed.values()})
                                  for k in ("n_accepted", "coverage", "n_defined_pos",
                                            "n_defined_pos_holdout", "n_train_used",
                                            "budget_added", "n_eval_rows_defined", "n_filled",
                                            "target_space_used", "n_holdout")
                                  if any(k in v for v in per_seed.values())},
                    }
                # 两臂差（只对恰好 2 个臂的项）
                arms = [a for a in cells if not a.endswith("子集") and "诊断" not in a]
                if len(arms) == 2 and all(cells[a]["median_err_median_over_seeds"] is not None
                                          for a in arms):
                    a0, a1 = arms
                    cells["_delta"] = {
                        "arms": [a0, a1],
                        "delta_median_err": (cells[a1]["median_err_median_over_seeds"]
                                             - cells[a0]["median_err_median_over_seeds"]),
                        "reading": "正 = 后者误差更大（更差）"}
                cells["_per_seed"] = per_arm
                for a in per_arm:
                    if a.endswith("子集") or "诊断" in a:
                        med_d = [v["median"] for v in per_arm[a].values()
                                 if v.get("median") is not None]
                        cells["_diag"] = {"arm": a,
                                          "median_err_median_over_seeds":
                                              float(np.median(med_d)) if med_d else None}
                summary[item][b][ch] = cells
    out["summary"] = summary
    return out


# ----------------------------------------------------------------- 渲染
def _f(v, n=6):
    if v is None:
        return "—"
    if isinstance(v, float):
        return ("%.*g" % (n, v)) if abs(v) < 1e6 else "%.3g" % v
    return str(v)


def _fs(v, n=6):
    """带符号（只用于 lift / Δ）。"""
    if v is None:
        return "—"
    return ("%+.*g" % (n, v)) if abs(v) < 1e6 else "%+.3g" % v


def render_baseline_md(store, meta, n_seeds):
    L = ["# N2-1 强基线：8 通道 × 8 方法 × 5 种子（防泄漏整组切分）", "",
         "> 切分：`data/splits_grouped_five_seeds.csv` 的 "
         "`side_seed0..4`（**整组同一侧**）。标签主表：`labels_two_batch.csv`（2255×30）。",
         "> 指标：**相对误差** = |pred − truth| / truth，分母 = 该通道真值且 > 0（逐格给分母行数）。",
         "> `lift_paired` = 同一次要子集上「persistence 中位误差 − 模型中位误差」，**正 = 有增值**。",
         "> ⚠️ **本代理不是 AI 求解器**：无场级误差界、无 L1 ⇒ 不得用于工程绝对值。不得据此提升任何状态。",
         "", "## 0. 边界（先读）", "",
         "1. `labels_two_batch.csv` **只有 4 个通道列**（`bandwidth_Hz`/`Q`/`peak_freq_Hz`/`spl_dB`）；"
         "另 4 个通道按 (batch, round6 键) 从 A/C 64 列表与 V2 冻结表补齐。",
         "2. V2 冻结表**没有** `abs_w_m`/`abs_p_Pa`/`abs_p_per_V_Pa`/`abs_vz_struct_m3s` 四列 ⇒ "
         "这 4 个通道在 `V2_5-35MHz` 批上**无数据**（表里记 0 行，不编造）。",
         "3. V2 的「找到峰/闭合」标志是**代理**（`peak_at_scan_endpoint` / "
         "`bw_upper_cutoff_at_endpoint`），不是原生标志 ⇒ V2 行的状态过滤口径**待裁定**。",
         "4. 每批**各自训练**（不跨批池化）；**无任何加权总分**；`core` 掩膜 = 8 个方法在该"
         "(批,种子,通道) 上**都有预测**的公共行集，排名只在 `core` 上做。",
         "", "## 1. 数据与切分事实", ""]
    for b in BATCHES:
        L.append("* `%s`：%d 行；8 通道列可用 = %s；标志口径 = %s"
                 % (b, meta["batch_counts"].get(b, 0),
                    ", ".join("`%s`" % c for c in meta["channel_column_available"][b]),
                    ", ".join(meta["flag_note_by_batch"][b])))
    L += ["", "逐种子 train/holdout 行数：", "",
          "| 批 | 种子 | train 行 | holdout 行 | 泄漏行（键同侧违约） |", "|---|---|---|---|---|"]
    for b in BATCHES:
        for s in SEEDS[:n_seeds]:
            c = store["per_seed"][b][str(s)]
            L.append("| `%s` | %d | %d | %d | %d |"
                     % (b, s, c["n_train_rows"], c["n_holdout_rows"], c["leak_rows"]))
    L += ["", "> 泄漏行 = 留出行的组合键也出现在训练集的行数（整组切分 ⇒ 应为 0；不为 0 即切分被破坏）。", ""]

    for b in BATCHES:
        L += ["## 2. 批 `%s` 逐通道（跨 5 种子的中位与波动）" % b, ""]
        for ch in CH8:
            agg = store["agg"][b][ch]
            n_defs = [store["per_seed"][b][str(s)]["channels"][ch]["n_defined_pos"]
                      for s in SEEDS[:n_seeds]]
            core7_ns = agg["core7_n_by_seed"]
            core8_ns = agg["core_all8_n_by_seed"]
            if not agg["per_method"]:
                L += ["### `%s`（%s）" % (ch, GROUP[ch]), "",
                      "**无数据**：该批标签表没有此通道列（V2 缺 4 列）⇒ 本格 0 行，未做。", ""]
                continue
            L += ["### `%s`（%s，正式目标=%s）" % (ch, GROUP[ch], "是" if IS_FORMAL[ch] else "否"),
                  "",
                  "可判定基数（有定义且真值>0）逐种子：%s；`core7`（不含 pchip）公共掩膜行数逐种子：%s；"
                  "`core_all8` 逐种子：%s" % (n_defs, core7_ns, core8_ns), "",
                  "| 方法 | 覆盖 min~max | median 误差 中位[min,max] | median std | p90 中位 | max 误差 中位 | "
                  "lift_paired 中位[min,max] | 正/负种子数 | 判定 |",
                  "|---|---|---|---|---|---|---|---|---|"]
            votes = agg["best_method_votes_on_core7"]
            for name in ALL_METHODS:
                v = agg["per_method"].get(name)
                if not v:
                    L.append("| `%s` | — | — | — | — | — | — | — | 未做/无数字 |" % name)
                    continue
                if name == "persistence":
                    judg = "基线自身（对照）"
                else:
                    judg = ("**有增值**" if v["n_seeds_lift_negative"] == 0
                            and v["n_seeds_lift_positive"] == v["n_seeds_with_numbers"]
                            else ("无增值" if v["n_seeds_lift_positive"] == 0
                                  else "**符号不稳**"))
                md_by_seed = sorted(x for x in v["median_err_by_seed"] if x is not None)
                lf_by_seed = sorted(x for x in v["lift_paired_by_seed"] if x is not None)
                L.append("| `%s` | %s~%s | %s [%s, %s] | %s | %s | %s | %s [%s, %s] | %d / %d | %s |"
                         % (name,
                            _f(v["coverage_min"], 3), _f(v["coverage_max"], 3),
                            _f(float(np.median(md_by_seed)) if md_by_seed else None),
                            _f(v["median_err_min"]), _f(v["median_err_max"]),
                            _f(v["median_err_std"], 3),
                            _f(v["p90_median"]),
                            _f(v["max_err_min"]),
                            _fs(float(np.median(lf_by_seed)) if lf_by_seed else None),
                            _fs(v["lift_paired_min"]), _fs(v["lift_paired_max"]),
                            v["n_seeds_lift_positive"], v["n_seeds_with_numbers"], judg))
            L += ["", "> `core7` 掩膜上 median 误差最小的**种子投票**：%s"
                  % (json.dumps(votes, ensure_ascii=False) if votes else "无（core7 行数 < 30）"), ""]
    return "\n".join(L) + "\n"


def render_ablation_md(abl):
    L = ["# N2-2 消融（6 项，逐项数值与结论）", "",
         "消融方法固定为 `%s`（除 A2 用既有 pchip 口径）。**每项只改一个变量**，"
         "数据/切分/特征/超参其余不变。" % abl["method_for_ablations"],
         "", "> 参考线（**只读引用** `solver_spec.json` 的 thresholds）：S2 工程相对误差上限 "
         "`%s`、S5 覆盖率带 `[%s, %s]`。仅作参考线，**不构成任何放行**。"
         % (abl["solver_spec_thresholds_reference"].get("S2_engineering_rel_err_max"),
            abl["solver_spec_thresholds_reference"].get("S5_coverage_min"),
            abl["solver_spec_thresholds_reference"].get("S5_coverage_max")),
         "", "## 0. 异常隔离字段的来源", "",
         "`labels_two_batch.csv`（30 列）**没有** `excluded_quarantine` 字段（如实说明）⇒ "
         "本项改用**最接近的可用口径**：冻结模型 `multichannel_model.json` 的 "
         "`excluded_quarantine = %s`，并另行计数 A/C 表的原生 `quarantined` 标志。"
         % json.dumps(abl["quarantine_source"]["excluded_quarantine"], ensure_ascii=False),
         "", "| 批 | 原生 `quarantined`=True 行数 | 落在 excluded_quarantine 列表的行数 | 标志口径 |",
         "|---|---|---|---|"]
    for b, v in abl["quarantine_flag_counts"].items():
        L.append("| `%s` | %d | %d | %s |" % (b, v["n_rows_native_quarantined_flag_true"],
                                              v["n_rows_in_excluded_quarantine_list"],
                                              ", ".join(v["flag_note"])))
    titles = {
        "A1_peak_semantics": "① 峰语义：把删失/截断行当普通值 vs 按状态过滤",
        "A2_refusal": "② 拒答：有 vs 无（看 false-accept 类指标）",
        "A3_quarantine": "③ 异常隔离：启用 vs 禁用 `excluded_quarantine`",
        "A4_log_transform": "④ log 变换：对正定通道开 vs 关",
        "A5_extrapolation_limit": "⑤ 外推限制：限制在训练域内 vs 不限制",
        "A6_active_sampling": "⑥ 主动补点：无 vs 有（最远点贪心，预算 = holdout 的 10%）",
    }
    L += ["", "## 0.1 ①「峰语义」的可区分性审计（解释为什么有些格子 Δ = 0）", "",
          "| 批 | 通道 | 「状态为假但数值存在」的行数 | 「状态为真但数值缺失」的行数 |", "|---|---|---|---|"]
    for b, per in abl["peak_semantics_audit"].items():
        for ch, v in per.items():
            L.append("| `%s` | `%s` | %d | %d |"
                     % (b, ch, v["n_rows_value_present_but_state_false"],
                        v["n_rows_state_true_but_value_missing"]))
    L += ["", "> 读法：若第一列 = 0，则该 (批,通道) 上「当作普通值」与「按状态过滤」"
          "**必然给出同一行集**（数值列与状态标志同步缺失）⇒ 该消融在此格**无区分力**，"
          "Δ = 0 是数据结构造成的，不是「两种口径一样好」。", ""]
    for item in ("A1_peak_semantics", "A2_refusal", "A3_quarantine", "A4_log_transform",
                 "A5_extrapolation_limit", "A6_active_sampling"):
        s = abl["summary"][item]
        L += ["", "## %s" % titles[item], "",
              "**只改了什么**：%s" % abl["comparison_semantics"][item], ""]
        for b, per_ch in s.items():
            rows = []
            for ch, cells in per_ch.items():
                arms = sorted(a for a in cells
                              if not a.startswith("_") and "子集" not in a and "诊断" not in a)
                vals = []
                for a in arms:
                    c = cells[a]
                    vals.append("%s=%s" % (a, _f(c["median_err_median_over_seeds"])))
                diag = cells.get("_diag")
                extra = []
                for a in arms:
                    e = cells[a].get("extra") or {}
                    if e:
                        extra.append("%s:%s" % (a, json.dumps(e, ensure_ascii=False)))
                d = cells.get("_delta")
                rows.append("| `%s` | %s | %s | %s | %s |"
                            % (ch, "；".join(vals),
                               ("%s − %s = %s" % (d["arms"][1], d["arms"][0],
                                                  _fs(d["delta_median_err"]))) if d else "—",
                               ("%s=%s" % (diag["arm"],
                                           _f(diag["median_err_median_over_seeds"])))
                               if diag and diag["median_err_median_over_seeds"] is not None
                               else "—",
                               "；".join(extra)[:340]))
            if rows:
                L += ["**批 `%s`**（数值 = 跨种子的「中位误差的中位」；Δ = 臂序第 2 个 − 第 1 个）"
                      % b, "",
                      "| 通道 | 各臂 median 相对误差 | Δ | 诊断臂 median | 基数/覆盖（逐臂） |",
                      "|---|---|---|---|---|"]
                L += rows
                L.append("")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--skip-ablations", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    outdir = pathlib.Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    F = load_fitter()
    rows, meta = load_all()
    print("装载 %d 行；批计数 %s" % (meta["n_rows"], meta["batch_counts"]))
    print("v3↔源表 4 通道不一致行数 = %d；v3 找不到源 = %d"
          % (meta["row_audit"]["v3_vs_source_channel_mismatch"],
             meta["row_audit"]["v3_missing_source"]))
    if meta["row_audit"]["v3_missing_source"]:
        raise SystemExit("[FAIL] v3 有行在源表里找不到")
    if meta["row_audit"]["v3_vs_source_channel_mismatch"]:
        raise SystemExit("[FAIL] v3 主表 4 通道与源表不一致 ⇒ 拒绝出数")

    print("== N2-1 基线 ==")
    store = run_baselines(F, rows, meta, a.seeds)
    doc = {
        "kind": "n2_1_baselines_by_seed_v1",
        "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "seeds": list(SEEDS[:a.seeds]),
        "channels": list(CH8),
        "methods": list(ALL_METHODS),
        "metric": "relative_error = |pred-truth|/truth; denominator = truth>0 (逐格给 n)",
        "no_pooling": True, "no_weighted_total": True, "state_promoted": False,
        "not_a_solver": "一阶峰标量代理，无场级误差界、无 L1 ⇒ 不得用于工程绝对值",
        "inputs": meta["inputs"], "data_facts": meta,
        "notes": {
            "pchip": "既有口径：**直接 import** 本包内置的 `pchip_fitter.py`（"
                     "fit_multichannel_surrogate.py 的 build/predict_one（未改写）",
            "persistence": "同 (N1) 层最近邻，逐行版，与既有 baseline_persistence 同口径",
            "boosted_trees": "sklearn HistGradientBoostingRegressor；"
                             "**本机没有 xgboost / lightgbm**（已实测 ModuleNotFoundError）⇒ "
                             "boosted_trees 一律指 sklearn 的 HistGradientBoosting",
            "GP": "sklearn GaussianProcessRegressor，核 = ConstantKernel×Matern(ν=2.5)+White；"
                  "特征标准化；训练点 > %d 时**确定性降采样**至 %d（O(n³) 限速）"
                  % (GP_MAX_TRAIN, GP_MAX_TRAIN),
            "MLP": "sklearn MLPRegressor((64,32))，特征与目标都标准化，固定 random_state",
            "rbf": "实现为 sklearn KernelRidge(kernel='rbf')（**核岭回归，非精确 RBF 插值**）",
            "core_mask": "8 个方法都有预测的公共行集；排名只在此掩膜上做",
        },
        "per_seed": store["per_seed"],
        "by_seed_aggregate": store["agg"],
    }
    (outdir / "baselines_by_seed.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    (outdir / "baseline_table.md").write_text(
        render_baseline_md(store, meta, a.seeds), encoding="utf-8")
    print("已写 baselines_by_seed.json / baseline_table.md  (%.1f s)" % (time.time() - t0))

    if not a.skip_ablations:
        print("== N2-2 消融 ==")
        abl = run_ablations(F, rows, meta, a.seeds)
        abl["kind"] = "n2_2_ablations_v1"
        abl["created_utc"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
        (outdir / "ablations.json").write_text(
            json.dumps(abl, ensure_ascii=False, indent=1), encoding="utf-8")
        (outdir / "ablations.md").write_text(render_ablation_md(abl), encoding="utf-8")
        print("已写 ablations.json / ablations.md")
    print("总耗时 %.1f s" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
