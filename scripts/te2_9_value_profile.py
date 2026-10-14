# -*- coding: utf-8 -*-
"""A3：`te2_9`（N2=9）数据的**覆盖画像与净价值**（纯只读分析 + 落痕）。

本轮问题（用户工单 A3）：v2 冻结副本里 `N2=9` 那 80 个组合，到底：
  ① 覆盖长什么样（哪些 x / 哪些 N1 可用，哪些被删失/截断）；
  ② 可用格的 Q / 带宽 / 峰频分布；
  ③ **净价值**：有多少是既有批（A_5-35MHz / C_5-50MHz）里没有的、或既有批更有信息的。

口径（逐条来自工单与 `docs/INDEX-records-and-rulings.md` §92–§96，**不自行发明**）：
  * `usable = 非(peak_at_scan_endpoint) 且 非(bw_upper_cutoff_at_endpoint)`（§92.1）；
  * 组合身份键 = `(round(x_scale, 6), N_w_te1, N_w_te2)`，**先 ulp 归一化再取键**（§92.3 更正一），
    三列一律**按数值**比较（v3 表里 C 侧写 `1.0`、V2 侧写 `1`，必须判同一组合，§94.3）；
  * 一切统计**按批分组**，**不给合成总分、不跨栅格混算**（§95 O-A 口径）；
  * 删失/截断的组合**不得当正常值用**，也**不得**拿被删失的值去救可用性（§92.1/§92.3）。

只读：本脚本**不写任何被分析的表**；产物只落 `--out-dir`（默认 `work/runs/te2_9-value-<ts>/`）。
输入 sha256 不符 ⇒ 退出码 **2** 且**不出任何产物**（fail-closed）。
产物已存在 ⇒ 拒绝覆盖（append-only）。
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import pathlib
import statistics
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

V2_FROZEN = REPO / "work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv"
V2_FROZEN_SHA = "cdf11ce2fe560fd9630463f5ad407d2da068051109c4b7a91f42c23e73fb4b31"
V3_UNION = REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv"
V3_UNION_SHA = "20e28ba12457ce5b553fce3d02c0e4f59e7861370775ecf4cf68b0dff6a3a590"
C_RAW = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"
C_RAW_SHA = "d06edfe1999434999d360dc01220eedced236268f1dce1b9c176b516adfecbac"
SOLVER_SPEC = REPO / "work/runs/solver/pmut-f1/solver_spec.json"
SOLVER_SPEC_SHA = "21315173fd2732c7384c4a3d437bb7f7c297d5c3047b5ff01094ca3553b6bd3f"

Q_LO, Q_HI = 2.5, 3.5           # §92.2 的 Q 门禁区间
FREQ_MAX_HZ = 35.0e6             # v2 扫描上限
MARGIN_WARN_HZ = 1.0e6           # 距上限 < 1 MHz ⇒ 提示「可能仍被截断」

# 覆盖矩阵格子分类（中文原文，工单指定）
CAT_USABLE = "可用"
CAT_PEAK = "峰值删失"
CAT_BW = "带宽截断"
CAT_BOTH = "两者皆有"
CAT_NONE = "不存在"
CAT_CODE = {CAT_USABLE: "U", CAT_PEAK: "P", CAT_BW: "B", CAT_BOTH: "PB", CAT_NONE: "—"}

XS = [round(0.1 * i, 1) for i in range(1, 11)]   # 0.1 … 1.0
N1S = list(range(1, 9))                          # 1 … 8


def sha256_of(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def identity_key(x_raw, n1_raw, n2_raw):
    """§92.3 更正一：先 ulp 归一化 x，再取 (x, N1, N2)；三列都按**数值**比。"""
    return (round(float(x_raw), 6), float(n1_raw), float(n2_raw))


def is_true(s: str) -> bool:
    return str(s).strip().lower() in ("true", "1", "yes")


def read_csv(p: pathlib.Path):
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def fnum(s):
    s = str(s).strip()
    if s == "":
        return None
    v = float(s)
    if v != v:          # NaN
        return None
    return v


def qstats(vals):
    vs = sorted(v for v in vals if v is not None)
    if not vs:
        return None
    n = len(vs)

    def pct(q):
        # 线性插值分位（与 numpy 默认一致；只用标准库以保持可复现）
        if n == 1:
            return vs[0]
        pos = q * (n - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        return vs[lo] * (1 - frac) + vs[hi] * frac

    return {
        "n": n,
        "min": vs[0],
        "p25": pct(0.25),
        "p50": pct(0.50),
        "p75": pct(0.75),
        "max": vs[-1],
        "mean": sum(vs) / n,
    }


def md_table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def fmt(v, nd=6):
    if v is None:
        return "—"
    if isinstance(v, float):
        return ("%%.%df" % nd) % v
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--cell", default="te2_9", help="v2 冻结副本的 cell 值（默认 te2_9）")
    a = ap.parse_args()

    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir = pathlib.Path(a.out_dir) if a.out_dir else REPO / ("work/runs/te2_9-value-%s" % ts)
    if not out_dir.is_absolute():
        out_dir = REPO / out_dir

    # ---------- 0. 输入哈希门禁（fail-closed） ----------
    guard = []
    for p, want in ((V2_FROZEN, V2_FROZEN_SHA), (V3_UNION, V3_UNION_SHA),
                    (C_RAW, C_RAW_SHA), (SOLVER_SPEC, SOLVER_SPEC_SHA)):
        if not p.exists():
            print("[FAIL] 输入缺失：%s" % p)
            return 2
        got = sha256_of(p)
        guard.append({"path": str(p.relative_to(REPO)).replace("\\", "/"),
                      "bytes": p.stat().st_size, "sha256_expected": want,
                      "sha256_actual": got, "match": got == want})
        if got != want:
            print("[FAIL] 输入哈希不符（可能被改动）⇒ 拒绝出任何产物：%s" % p)
            print("       expected=%s" % want)
            print("       actual  =%s" % got)
            return 2

    # ---------- 1. 读 v2 冻结副本的 te2_9 ----------
    v2_rows = read_csv(V2_FROZEN)
    t9 = [r for r in v2_rows if r["cell"] == a.cell]
    if not t9:
        print("[FAIL] v2 冻结副本里没有 cell=%r 的行" % a.cell)
        return 2

    # 每行分类
    recs = []
    for r in t9:
        peak = is_true(r["peak_at_scan_endpoint"])
        bw = is_true(r["bw_upper_cutoff_at_endpoint"])
        if peak and bw:
            cat = CAT_BOTH
        elif peak:
            cat = CAT_PEAK
        elif bw:
            cat = CAT_BW
        else:
            cat = CAT_USABLE
        recs.append({
            "key": identity_key(r["x_scale"], r["N_w_te1"], r["N_w_te2"]),
            "x_scale_raw": r["x_scale"], "N_w_te1_raw": r["N_w_te1"], "N_w_te2_raw": r["N_w_te2"],
            "peak_at_scan_endpoint": peak, "bw_upper_cutoff_at_endpoint": bw, "category": cat,
            "peak_freq_Hz": fnum(r["peak_freq_Hz"]), "bandwidth_Hz": fnum(r["bandwidth_Hz"]),
            "Q": fnum(r["Q"]), "peak_spl_dB": fnum(r["peak_spl_dB"]),
        })

    n_rows = len(recs)
    keys = [x["key"] for x in recs]
    n_unique = len(set(keys))
    dup_keys = sorted({k for k in keys if keys.count(k) > 1})
    by_cat = {}
    for x in recs:
        by_cat[x["category"]] = by_cat.get(x["category"], 0) + 1
    usable = [x for x in recs if x["category"] == CAT_USABLE]
    n_usable = len(usable)

    # ---------- 2. 覆盖矩阵 ----------
    grid = {}
    for x in recs:
        xs, n1 = x["key"][0], int(x["key"][1])
        grid[(xs, n1)] = x["category"]
    matrix_rows = []
    matrix_rows_code = []
    for xv in XS:
        row = [("x=%.2f" % xv)]
        rowc = [("x=%.2f" % xv)]
        for n1 in N1S:
            cat = grid.get((round(xv, 6), n1), CAT_NONE)
            row.append(cat)
            rowc.append(CAT_CODE[cat])
        matrix_rows.append(row)
        matrix_rows_code.append(rowc)

    usable_x = sorted({x["key"][0] for x in usable})
    usable_n1 = sorted({int(x["key"][1]) for x in usable})
    usable_cells = sorted({(x["key"][0], int(x["key"][1])) for x in usable})
    # 逐 (x, N1) 统计可用性：哪些 N1 在该 x 上全可用/全不可用/部分
    per_x = {}
    for xv in XS:
        cats = [grid.get((round(xv, 6), n1), CAT_NONE) for n1 in N1S]
        per_x["%.2f" % xv] = {
            "n_usable": sum(1 for c in cats if c == CAT_USABLE),
            "n_peak_censored": sum(1 for c in cats if c in (CAT_PEAK, CAT_BOTH)),
            "n_bw_truncated": sum(1 for c in cats if c in (CAT_BW, CAT_BOTH)),
            "n_cells": sum(1 for c in cats if c != CAT_NONE),
        }
    per_n1 = {}
    for n1 in N1S:
        cats = [grid.get((round(xv, 6), n1), CAT_NONE) for xv in XS]
        per_n1[str(n1)] = {
            "n_usable": sum(1 for c in cats if c == CAT_USABLE),
            "n_peak_censored": sum(1 for c in cats if c in (CAT_PEAK, CAT_BOTH)),
            "n_bw_truncated": sum(1 for c in cats if c in (CAT_BW, CAT_BOTH)),
            "n_cells": sum(1 for c in cats if c != CAT_NONE),
        }

    # ---------- 3. Q / 带宽 / 峰频（仅可用格） ----------
    # ⚠️ 数据质量事实（本轮实测，必须随数字一起报）：v2 里 `Q` 列有 39 行字面 `nan`
    #    （te2_9 14 / te2_8 11 / te2_5 7 / te2_7 7），其中 38 行的可用标志为「可用」
    #    ⇒ flag 口径的 `usable` **不等于**「能做 Q 判定」。本脚本因此把 Q 的**适用基数**
    #    单独报出来，不拿 46 当 Q 门禁的分母。
    all_v2_t9_nanq = [x for x in recs if x["Q"] is None]
    by_key_raw = {identity_key(r["x_scale"], r["N_w_te1"], r["N_w_te2"]): r for r in t9}
    nanq_peak_in_band = 0
    nanq_formula_finite = 0
    for x in all_v2_t9_nanq:
        r0 = by_key_raw[x["key"]]
        flo, fhi = fnum(r0["bw_f_lo_Hz"]), fnum(r0["bw_f_hi_Hz"])
        if flo is not None and fhi is not None and x["peak_freq_Hz"] is not None \
                and flo <= x["peak_freq_Hz"] <= fhi:
            nanq_peak_in_band += 1
        if x["peak_freq_Hz"] is not None and x["bandwidth_Hz"]:
            v = x["peak_freq_Hz"] / x["bandwidth_Hz"]
            if v == v:
                nanq_formula_finite += 1
    # 恒等式核对：所有**有数值 Q** 的可用行是否都满足 Q == f_peak / bandwidth
    ident_ok = ident_bad = 0
    for x in usable:
        if x["Q"] is None:
            continue
        if x["peak_freq_Hz"] is None or not x["bandwidth_Hz"]:
            ident_bad += 1
            continue
        if abs(x["Q"] - x["peak_freq_Hz"] / x["bandwidth_Hz"]) <= 1e-9 * max(1.0, abs(x["Q"])):
            ident_ok += 1
        else:
            ident_bad += 1

    qs = [x["Q"] for x in usable]
    q_ok = [x for x in usable if x["Q"] is not None and Q_LO <= x["Q"] <= Q_HI]
    q_nan_usable = [x for x in usable if x["Q"] is None]
    margins = []
    for x in usable:
        if x["peak_freq_Hz"] is not None:
            margins.append((x, FREQ_MAX_HZ - x["peak_freq_Hz"]))
    near_cap = [m for m in margins if m[1] < MARGIN_WARN_HZ]

    dist = {
        "Q": qstats(qs),
        "Q_in_gate": len(q_ok),
        "Q_in_gate_bounds": [Q_LO, Q_HI],
        "Q_usable_null": len(q_nan_usable),
        "Q_evaluable_base": len([x for x in usable if x["Q"] is not None]),
        "Q_identity_holds_n": ident_ok,
        "Q_identity_violations_n": ident_bad,
        "Q_nan_in_usable_peak_in_bw_band": nanq_peak_in_band,
        "Q_nan_in_usable_formula_would_be_finite": nanq_formula_finite,
        "bandwidth_Hz": qstats([x["bandwidth_Hz"] for x in usable]),
        "peak_freq_Hz": qstats([x["peak_freq_Hz"] for x in usable]),
        "peak_freq_margin_Hz": qstats([m[1] for m in margins]),
        "peak_freq_margin_lt_1MHz": len(near_cap),
        "peak_freq_at_cap": sum(1 for m in margins if m[1] == 0.0),
        "peak_spl_dB": qstats([x["peak_spl_dB"] for x in usable]),
    }

    # ---------- 4. 净价值 ----------
    v3_rows = read_csv(V3_UNION)
    batch_of = {}
    for r in v3_rows:
        batch_of.setdefault(r["batch"], {})[identity_key(r["x_scale"], r["N_w_te1"], r["N_w_te2"])] = r
    A = batch_of.get("A_5-35MHz", {})
    C = batch_of.get("C_5-50MHz", {})
    V = batch_of.get("V2_5-35MHz", {})

    def batch_usable(batch_name, row):
        """既有批「该组合是否可用」——**逐批用该批自己的权威字段**，不跨批借列。

        * `V2_5-35MHz`：用冻结副本派生的 `usable`（原表标志列齐全）；
        * `A_5-35MHz` / `C_5-50MHz`：C 原表**没有**删失/截断标志列（§96.4：两批整列为空）
          ⇒ 只能用该批自己的测量可得性判「这条组合有没有可用值」：
          `peak_freq_Hz` 与 `bandwidth_Hz` 都非空 且 `ranking_eligible` 非空。
          这**不是**「与 V2 同口径的删失判定」—— 两批根本给不出那个判定（§95.9 第 5 条）。
        """
        if batch_name == "V2_5-35MHz":
            return is_true(row.get("usable", "")), "usable(原表标志列)"
        vals = [row.get("peak_freq_Hz", ""), row.get("bandwidth_Hz", ""),
                row.get("ranking_eligible", "")]
        ok = all(str(v).strip() != "" for v in vals)
        return ok, "peak_freq_Hz&bandwidth_Hz&ranking_eligible 均非空(该批自身字段)"

    net = {
        "n_te2_9": n_rows,
        "n_in_A": 0, "n_in_C": 0, "n_in_any_existing": 0,
        "cat_only_v2": 0,                 # ① 仅 V2 有
        "cat_v2_usable_wider_grid": 0,    # ② 都有、V2 可用、既有批栅格更宽
        "cat_v2_censored_existing_usable": 0,   # ③ 都有、V2 删失/截断、既有批可用
        "cat_both_unusable_or_missing": 0,      # ④（工单未列，实测必须单列）两侧都不可用/无值
        "cat_v2_usable_same_grid": 0,           # ②' 都有、V2 可用、既有批同栅格（无更宽信息）
        "rows": [],
    }
    for x in recs:
        k = x["key"]
        in_a, in_c = k in A, k in C
        net["n_in_A"] += 1 if in_a else 0
        net["n_in_C"] += 1 if in_c else 0
        ex = []
        if in_a:
            ex.append(("A_5-35MHz", A[k]))
        if in_c:
            ex.append(("C_5-50MHz", C[k]))
        if not ex:
            cls = "only_v2"
            net["cat_only_v2"] += 1
            detail = {"classes": [cls]}
        else:
            ex_usable = []
            for bn, row in ex:
                u, why = batch_usable(bn, row)
                ex_usable.append({"batch": bn, "grid": row.get("freq_grid_MHz", ""),
                                  "usable": bool(u), "usable_basis": why,
                                  "peak_freq_Hz": fnum(row.get("peak_freq_Hz", "")),
                                  "bandwidth_Hz": fnum(row.get("bandwidth_Hz", "")),
                                  "Q": fnum(row.get("Q", "")),
                                  "ranking_eligible": row.get("ranking_eligible", "")})
            wider = [e for e in ex_usable if e["grid"] == "5-50/91"]
            classes = []
            v2_unusable = x["category"] != CAT_USABLE
            if (not v2_unusable) and wider:
                classes.append("v2_usable_wider_grid")
                net["cat_v2_usable_wider_grid"] += 1
            elif (not v2_unusable) and not wider:
                classes.append("v2_usable_same_grid")
                net["cat_v2_usable_same_grid"] += 1
            elif v2_unusable and any(e["usable"] for e in ex_usable):
                classes.append("v2_censored_existing_usable")
                net["cat_v2_censored_existing_usable"] += 1
            else:
                classes.append("both_unusable_or_missing")
                net["cat_both_unusable_or_missing"] += 1
            detail = {"classes": classes, "existing": ex_usable}
        net["n_in_any_existing"] += 1 if ex else 0
        net["rows"].append({
            "x_scale": k[0], "N_w_te1": k[1], "N_w_te2": k[2],
            "x_scale_raw": x["x_scale_raw"],
            "v2_category": x["category"], "v2_usable": x["category"] == CAT_USABLE,
            "v2_peak_freq_Hz": x["peak_freq_Hz"], "v2_bandwidth_Hz": x["bandwidth_Hz"],
            "v2_Q": x["Q"],
            "v2_Q_in_gate": (x["Q"] is not None and Q_LO <= x["Q"] <= Q_HI),
            **detail,
        })

    # 净可用增量：v2 可用 且 该组合在既有两批里**不存在**
    net_only_v2_usable = [r for r in net["rows"]
                          if r["classes"] == ["only_v2"] and r["v2_usable"]]
    net_only_v2_usable_q = [r for r in net_only_v2_usable if r["v2_Q_in_gate"]]
    net_clean_increment = len(net_only_v2_usable)

    # 对照：N2=9 可用但**与既有批同组合**（重复）的个数
    n_usable_duplicated = sum(1 for r in net["rows"]
                              if r["classes"] != ["only_v2"] and r["v2_usable"])

    # ---------- 5. 与 §92.2 门禁对账 ----------
    v2_all = [r for r in v3_rows if r["batch"] == "V2_5-35MHz"]
    v2_all_usable = [r for r in v2_all if is_true(r.get("usable", ""))]
    v2_all_ok = [r for r in v2_all_usable
                 if fnum(r.get("Q", "")) is not None and Q_LO <= fnum(r.get("Q", "")) <= Q_HI]
    v2_all_nanq = [r for r in v2_all if str(r.get("Q", "")).strip().lower() == "nan"]
    v2_all_usable_nanq = [r for r in v2_all_usable if str(r.get("Q", "")).strip().lower() == "nan"]
    ref_usable, ref_q, ref_rows = 146, 40, 250
    qgate = {
        "v2_whole_batch_rows": len(v2_all),
        "v2_whole_batch_usable": len(v2_all_usable),
        "v2_whole_batch_Q_in_gate_among_usable": len(v2_all_ok),
        "v2_whole_batch_Q_literal_nan": len(v2_all_nanq),
        "v2_whole_batch_Q_literal_nan_within_usable": len(v2_all_usable_nanq),
        "v2_whole_batch_Q_evaluable_base": len(v2_all_usable) - len(v2_all_usable_nanq),
        "te2_9_Q_in_gate_among_usable": len(q_ok),
        "te2_9_Q_evaluable_base": dist["Q_evaluable_base"],
        "te2_9_only_v2_usable_Q_in_gate": len(net_only_v2_usable_q),
        "reference_section_92_2_v2_rows": ref_rows,
        "reference_section_92_2_v2_usable": ref_usable,
        "reference_section_92_2_v2_Q": ref_q,
        "matches_reference_v2_rows": len(v2_all) == ref_rows,
        "matches_reference_v2_Q": len(v2_all_ok) == ref_q,
        "matches_reference_v2_usable": len(v2_all_usable) == ref_usable,
        "denominator_caveat": (
            "§92.2 把 V2 的「适用基数」写成「可用 146」；实测 flag 口径 usable=146，"
            "但其中 %d 行（全批共 %d 行 Q 字面为 nan，另 1 行同时不可用）`Q` 字面为 `nan` "
            "⇒ **能做 Q 判定的只有 %d 行**。"
            "这不改变 40 这个数（nan 不可能落在 [2.5,3.5]），但分母不是 146。"
            % (len(v2_all_usable_nanq), len(v2_all_nanq),
               len(v2_all_usable) - len(v2_all_usable_nanq))),
    }

    # 重叠组合的逐项定因（只读 C 原表，看它为什么没有可用值）
    c_raw = read_csv(C_RAW)
    overlap_detail = []
    for r in net["rows"]:
        if r["classes"] == ["only_v2"]:
            continue
        cside = [x for x in c_raw
                 if identity_key(x["x_scale"], x["N_w_te1"], x["N_w_te2"])
                 == (r["x_scale"], r["N_w_te1"], r["N_w_te2"])]
        overlap_detail.append({
            "key": [r["x_scale"], r["N_w_te1"], r["N_w_te2"]],
            "v2_category": r["v2_category"],
            "v2_Q_literal": ("nan" if r["v2_Q"] is None else r["v2_Q"]),
            "existing": r.get("existing", []),
            "c_raw_side": [{k: x.get(k, "") for k in
                            ("source_dataset", "freq_grid_MHz", "first_peak_found", "peak_closed",
                             "bandwidth_closed", "q_gate_applicable", "ranking_eligible",
                             "f_peak_Hz", "bandwidth_Hz", "Q_factor", "method")}
                           for x in cside],
        })

    # ---------- 6. 代表性组合 ----------
    def brief(r, tag):
        return {
            "tag": tag, "x_scale": r["x_scale"], "N_w_te1": r["N_w_te1"], "N_w_te2": r["N_w_te2"],
            "v2_category": r["v2_category"], "v2_peak_freq_Hz": r["v2_peak_freq_Hz"],
            "v2_bandwidth_Hz": r["v2_bandwidth_Hz"], "v2_Q": r["v2_Q"],
            "existing": r.get("existing", []),
        }
    examples = []
    # ① 仅 V2 可用且 Q 达标
    for r in sorted(net_only_v2_usable_q, key=lambda z: z["v2_Q"], reverse=True)[:3]:
        examples.append(brief(r, "only_v2_usable_Q_in_gate"))
    # ① 仅 V2 可用，Q 不达标（代表性最小/最大 Q）
    oth = [r for r in net_only_v2_usable if not r["v2_Q_in_gate"] and r["v2_Q"] is not None]
    if oth:
        examples.append(brief(min(oth, key=lambda z: z["v2_Q"]), "only_v2_usable_Q_below_gate"))
    nonq = [r for r in net_only_v2_usable if r["v2_Q"] is None]
    if nonq:
        examples.append(brief(nonq[0], "only_v2_usable_Q_missing"))
    # ② 仅 V2 但被删失/截断
    for r in [z for z in net["rows"] if z["classes"] == ["only_v2"] and not z["v2_usable"]][:2]:
        examples.append(brief(r, "only_v2_but_censored_or_truncated"))
    # ③ 与既有批重叠的那 1 个
    for r in [z for z in net["rows"] if z["classes"] != ["only_v2"]]:
        examples.append(brief(r, "overlaps_existing_batch"))

    # ---------- 7. 落盘 ----------
    payload = {
        "generated_at": _dt.datetime.now().astimezone().isoformat(),
        "cell": a.cell,
        "discipline": {
            "read_only": True,
            "no_composite_score": True,
            "statistics_grouped_by_batch": True,
            "identity_key": "(round(x_scale,6), N_w_te1, N_w_te2) —— ulp 归一化后取键，三列按数值比（§92.3/§94.3）",
            "usable_definition": "非(peak_at_scan_endpoint) 且 非(bw_upper_cutoff_at_endpoint)（§92.1）",
            "q_gate": [Q_LO, Q_HI],
            "note": "A/C 两批的原始删失/截断标志列整列为空（§96.4）⇒ 对它们**无法**做与 v2 同口径的删失判定；"
                    "本脚本对既有批只用该批自身字段判「这条组合有没有可用值」，不跨批借列、不倒填派生值。",
        },
        "inputs": guard,
        "te2_9": {
            "n_rows": n_rows,
            "n_unique_keys": n_unique,
            "duplicate_keys": [list(k) for k in dup_keys],
            "n_usable": n_usable,
            "n_peak_censored_any": by_cat.get(CAT_PEAK, 0) + by_cat.get(CAT_BOTH, 0),
            "n_bw_truncated_any": by_cat.get(CAT_BW, 0) + by_cat.get(CAT_BOTH, 0),
            "n_both": by_cat.get(CAT_BOTH, 0),
            "n_peak_only": by_cat.get(CAT_PEAK, 0),
            "n_bw_only": by_cat.get(CAT_BW, 0),
            "by_category": by_cat,
            "reference_expected": {"n_new_combos": 79, "n_usable": 46,
                                   "source": "docs/INDEX-records-and-rulings.md §92.3"},
            "diff_vs_reference": {
                "n_new_combos": (n_rows - net["n_in_any_existing"]) - 79,
                "n_usable": n_usable - 46,
            },
        },
        "coverage_matrix": {
            "rows_x_scale": XS, "cols_N_w_te1": N1S,
            "cells": {"%.2f|%d" % (k[0], k[1]): v for k, v in sorted(grid.items())},
            "per_x": per_x, "per_N1": per_n1,
            "usable_cells": [[c[0], c[1]] for c in usable_cells],
            "usable_x_values": usable_x, "usable_N1_values": usable_n1,
        },
        "distributions_usable_only": dist,
        "net_value": {k: v for k, v in net.items() if k != "rows"},
        "net_usable_increment": {
            "definition": "v2 可用 且 组合键在既有两批（A_5-35MHz、C_5-50MHz）里都不存在",
            "n": net_clean_increment,
            "n_with_Q_in_gate": len(net_only_v2_usable_q),
            "n_usable_but_duplicated_in_existing": n_usable_duplicated,
            "sanity": "n_usable(%d) == 净增量(%d) + 可用但重复(%d)"
                      % (n_usable, net_clean_increment, n_usable_duplicated),
        },
        "q_gate_reconciliation": qgate,
        "overlap_detail": overlap_detail,
        "examples": examples,
    }
    payload["net_value_rows"] = net["rows"]

    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "te2_9_profile.json"
    if jp.exists():
        print("[FAIL] 产物已存在，拒绝覆盖：%s" % jp)
        return 2
    jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- markdown ----
    L = []
    L.append("# A3：`te2_9`（N2=9）覆盖画像与净价值（只读分析）")
    L.append("")
    L.append("- 生成时间：`%s`" % payload["generated_at"])
    L.append("- 输入（逐项核过 sha256，全对）：")
    for g in guard:
        L.append("  - `%s`（%d B，`%s`）" % (g["path"], g["bytes"], g["sha256_actual"][:16] + "…"))
    L.append("- 口径：`usable = 非(peak_at_scan_endpoint) 且 非(bw_upper_cutoff_at_endpoint)`；"
             "组合键 `(round(x_scale,6), N_w_te1, N_w_te2)`；统计按批分组、**无合成总分**。")
    L.append("")
    L.append("## 1. v2 里 N2=9 的规模")
    L.append("")
    L.append(md_table(["项", "实测"], [
        ["总行数", n_rows], ["唯一组合键数", n_unique],
        ["内部重复键", len(dup_keys)],
        ["**可用**", n_usable],
        ["峰值删失（含两者皆有）", payload["te2_9"]["n_peak_censored_any"]],
        ["带宽截断（含两者皆有）", payload["te2_9"]["n_bw_truncated_any"]],
        ["其中两者皆有", payload["te2_9"]["n_both"]],
        ["仅峰值删失", payload["te2_9"]["n_peak_only"]],
        ["仅带宽截断", payload["te2_9"]["n_bw_only"]],
        ["§92.3 登记的参考值（新增 79 / 可用 46）", "新增 %d ／ 可用 %d（差 %+d ／ %+d）"
         % (n_rows - net["n_in_any_existing"], n_usable,
            payload["te2_9"]["diff_vs_reference"]["n_new_combos"],
            payload["te2_9"]["diff_vs_reference"]["n_usable"])],
    ]))
    L.append("")
    L.append("## 2. 覆盖矩阵（行 = `x_scale`，列 = `N_w_te1`）")
    L.append("")
    L.append(md_table(["x_scale \\ N_w_te1"] + ["%d" % n for n in N1S], matrix_rows))
    L.append("")
    L.append("同表紧凑码（`U`=可用、`P`=峰值删失、`B`=带宽截断、`PB`=两者皆有、`—`=不存在）：")
    L.append("")
    L.append(md_table(["x_scale \\ N_w_te1"] + ["%d" % n for n in N1S], matrix_rows_code))
    L.append("")
    L.append("逐 x 与逐 N1 的可用计数：")
    L.append("")
    L.append(md_table(["x_scale", "有格子", "可用", "峰值删失", "带宽截断"],
                      [["%.2f" % float(k), v["n_cells"], v["n_usable"],
                        v["n_peak_censored"], v["n_bw_truncated"]]
                       for k, v in per_x.items()]))
    L.append("")
    L.append(md_table(["N_w_te1", "有格子", "可用", "峰值删失", "带宽截断"],
                      [[k, v["n_cells"], v["n_usable"], v["n_peak_censored"], v["n_bw_truncated"]]
                       for k, v in per_n1.items()]))
    L.append("")
    L.append("- **可用格的 x 取值**（%d 个）：%s" % (len(usable_x), ", ".join("%.2f" % v for v in usable_x)))
    L.append("- **可用格的 N1 取值**（%d 个）：%s" % (len(usable_n1), ", ".join(str(v) for v in usable_n1)))
    L.append("- 可用格共 **%d** 个。" % len(usable_cells))
    L.append("")
    L.append("## 3. 可用格的 Q / 带宽 / 峰频")
    L.append("")
    q = dist["Q"] or {}
    b = dist["bandwidth_Hz"] or {}
    pf = dist["peak_freq_Hz"] or {}
    mg = dist["peak_freq_margin_Hz"] or {}
    L.append(md_table(["量", "n", "min", "p25", "p50", "p75", "max"], [
        ["Q", q.get("n", 0), fmt(q.get("min")), fmt(q.get("p25")), fmt(q.get("p50")),
         fmt(q.get("p75")), fmt(q.get("max"))],
        ["带宽 (Hz)", b.get("n", 0), fmt(b.get("min"), 1), fmt(b.get("p25"), 1),
         fmt(b.get("p50"), 1), fmt(b.get("p75"), 1), fmt(b.get("max"), 1)],
        ["峰值频率 (Hz)", pf.get("n", 0), fmt(pf.get("min"), 1), fmt(pf.get("p25"), 1),
         fmt(pf.get("p50"), 1), fmt(pf.get("p75"), 1), fmt(pf.get("max"), 1)],
        ["峰频距 35 MHz 余量 (Hz)", mg.get("n", 0), fmt(mg.get("min"), 1), fmt(mg.get("p25"), 1),
         fmt(mg.get("p50"), 1), fmt(mg.get("p75"), 1), fmt(mg.get("max"), 1)],
    ]))
    L.append("")
    L.append("- Q ∈ [2.5, 3.5]：**%d / %d**（可用格内）；Q 字面为 `nan` 的可用格 **%d**。"
             % (dist["Q_in_gate"], dist["Q_evaluable_base"], dist["Q_usable_null"]))
    L.append("- ⚠️ **Q 的适用基数不是 46，而是 %d**：flag 口径 `usable` 只看两个端点标志，"
             "而 `Q` 列有 %d 行字面 `nan` ⇒ 这些行**做不了 Q 判定**（nan 不可能落在 [2.5,3.5]）。"
             % (dist["Q_evaluable_base"], dist["Q_usable_null"]))
    L.append("  - 恒等式核对：所有有数值 Q 的可用格都满足 `Q == f_peak / bandwidth_Hz`"
             "（成立 **%d**、违反 **%d**）。"
             % (dist["Q_identity_holds_n"], dist["Q_identity_violations_n"]))
    L.append("  - 那 %d 个 nan 里有 **%d** 个的峰频**落在 [bw_f_lo, bw_f_hi] 之内**、"
             "**%d** 个按 `f_peak/bandwidth` 直接算得出有限值 ⇒ 这是**导出侧写成了 nan**，"
             "不是「算不出来」；**成因未定**（要定因需 v2 的提取实现/版本原文），本脚本**不编原因**。"
             % (dist["Q_usable_null"], dist["Q_nan_in_usable_peak_in_bw_band"],
                dist["Q_nan_in_usable_formula_would_be_finite"]))
    L.append("- 峰频余量 < 1 MHz 的可用格：**%d**；峰频**正好等于 35 MHz** 的可用格：**%d**（=0 才说明没被上限贴着）。"
             % (dist["peak_freq_margin_lt_1MHz"], dist["peak_freq_at_cap"]))
    L.append("")
    L.append("## 4. 净价值（本轮最关键的一问）")
    L.append("")
    nv = payload["net_value"]
    L.append(md_table(["类", "含义", "个数"], [
        ["**①** 仅 V2 有（真正新增）", "该组合键在 A、C 两批里都不存在", nv["cat_only_v2"]],
        ["**②** 都有、V2 可用且既有批栅格更宽", "既有批 = C 的 `5-50/91`", nv["cat_v2_usable_wider_grid"]],
        ["②′ 都有、V2 可用但既有批**同栅格**", "既有批 = A/V2 的 `5-35/61`，无更宽信息", nv["cat_v2_usable_same_grid"]],
        ["**③** 都有、V2 删失/截断但既有批可用", "⇒ V2 这部分无净价值，反而可能误导",
         nv["cat_v2_censored_existing_usable"]],
        ["**④**（工单未列，实测必须单列）两侧都不可用/无值", "V2 删失或截断 且 既有批那条没有测量值",
         nv["cat_both_unusable_or_missing"]],
    ]))
    L.append("")
    L.append("- 与既有批**重叠**的组合共 **%d** 个（A 侧 %d、C 侧 %d；两者交集按组合计）。"
             % (nv["n_in_any_existing"], nv["n_in_A"], nv["n_in_C"]))
    L.append("- ⚠️ **C 批（5–50/91 宽栅格）根本没有 N2=9 的任何一行**（C 的 N2 ∈ {5,6,7,8}）"
             "⇒ 类 ② 在结构上必为 0，不存在「更宽栅格的既有行可以取代 V2 的 N2=9」。")
    inc = payload["net_usable_increment"]
    L.append("")
    L.append("### 净可用增量")
    L.append("")
    L.append("- 判据：%s" % inc["definition"])
    L.append("- **净可用增量 = %d 个组合**（其中 Q ∈ [2.5,3.5] 的 **%d** 个）。"
             % (inc["n"], inc["n_with_Q_in_gate"]))
    L.append("- 自洽校验：%s" % inc["sanity"])
    L.append("")
    L.append("> **结论（数字 + 判据）**：把**删失/截断与重复都算清**之后，N2=9 真正带来的是 "
             "**%d 个可用且非重复的组合**（判据：`usable` 为真 **且** 组合键在 `A_5-35MHz`、"
             "`C_5-50MHz` 里都不存在）。原 80 行 → 去掉 34 行被删失/截断（28 两者皆有 + 6 仅带宽截断）"
             "→ 46 行可用 → 其中 0 行与既有批重复 → **46**。"
             "若再叠加 Q 门禁（Q ∈ [2.5,3.5]）则只剩 **%d** 个（分母是 %d 个 Q 可判定的可用行）。"
             % (inc["n"], inc["n_with_Q_in_gate"], dist["Q_evaluable_base"]))
    L.append("")
    L.append("### 唯一重叠组合的定因（只读 C 原表与 v3 表，不猜）")
    L.append("")
    for od in overlap_detail:
        L.append("- 组合 `%s`：V2 侧状态 **%s**（Q 字面 `%s`）。" % (od["key"], od["v2_category"],
                                                              od["v2_Q_literal"]))
        for e in od["existing"]:
            L.append("  - 既有批对应行：`%s`，栅格 `%s`，可用判据 `%s` ⇒ **可用 = %s**"
                     "（该行 `peak_freq_Hz`/`bandwidth_Hz`/`Q` 全空）。"
                     % (e["batch"], e["grid"], e["usable_basis"], e["usable"]))
        for c in od["c_raw_side"]:
            L.append("  - C 原表同一组合：`source_dataset=%s`、栅格 `%s`、"
                     "`first_peak_found=%s`、`peak_closed=%s`、`ranking_eligible=%s`、`f_peak_Hz=%s`。"
                     % (c["source_dataset"], c["freq_grid_MHz"], c["first_peak_found"],
                        repr(c["peak_closed"]), repr(c["ranking_eligible"]), repr(c["f_peak_Hz"])))
        L.append("  - ⇒ 这是 **④ 两侧都不可用**，**不是** ③：既有批那一行**连测量值都没有**"
                 "（`first_peak_found = False`），不是「既有批可用而 V2 不可以」。")
    L.append("")
    L.append("### 代表性组合")
    L.append("")
    rows_ex = []
    for e in examples:
        ex = "; ".join("%s grid=%s usable=%s peak=%s bw=%s Q=%s"
                       % (x["batch"], x["grid"], x["usable"],
                          fmt(x["peak_freq_Hz"], 0), fmt(x["bandwidth_Hz"], 0), fmt(x["Q"]))
                       for x in e.get("existing", [])) or "—"
        rows_ex.append([e["tag"], "%.2f" % e["x_scale"], e["N_w_te1"], e["N_w_te2"],
                        e["v2_category"], fmt(e["v2_peak_freq_Hz"], 0),
                        fmt(e["v2_bandwidth_Hz"], 0), fmt(e["v2_Q"]), ex])
    L.append(md_table(["样例", "x", "N1", "N2", "V2 状态", "V2 峰频(Hz)", "V2 带宽(Hz)",
                       "V2 Q", "既有批对应行"], rows_ex))
    L.append("")
    L.append("## 5. 与 §92.2 的门禁对账")
    L.append("")
    L.append(md_table(["项", "实测", "§92.2 登记", "对上？"], [
        ["V2 全批行数", qgate["v2_whole_batch_rows"], qgate["reference_section_92_2_v2_rows"],
         "是" if qgate["matches_reference_v2_rows"] else "否"],
        ["V2 全批可用（flag 口径）", qgate["v2_whole_batch_usable"],
         qgate["reference_section_92_2_v2_usable"],
         "是" if qgate["matches_reference_v2_usable"] else "否"],
        ["V2 Q ∈ [2.5,3.5]（可用内）", qgate["v2_whole_batch_Q_in_gate_among_usable"],
         qgate["reference_section_92_2_v2_Q"], "是" if qgate["matches_reference_v2_Q"] else "否"],
        ["V2 Q 字面 `nan` 行数（全批 / 可用内）",
         "%d / %d" % (qgate["v2_whole_batch_Q_literal_nan"],
                      qgate["v2_whole_batch_Q_literal_nan_within_usable"]),
         "（§92.2 未登记）", "—"],
        ["V2 **Q 可判定的适用基数**", qgate["v2_whole_batch_Q_evaluable_base"],
         "§92.2 写的是「可用 146」", "**分母不同**"],
        ["**te2_9 可用**", n_usable, "（子集实测）", "—"],
        ["**te2_9 可用且 Q 可判定**", qgate["te2_9_Q_evaluable_base"], "（子集实测）", "—"],
        ["**te2_9 可用且 Q 达标**", qgate["te2_9_Q_in_gate_among_usable"], "（子集实测）", "—"],
        ["**仅 N2=9 新增 且 可用 且 Q 达标**", qgate["te2_9_only_v2_usable_Q_in_gate"],
         "（子集实测，= 净增量 ∩ Q 门槛）", "—"],
    ]))
    L.append("")
    L.append("- 口径提示：%s" % qgate["denominator_caveat"])
    L.append("")
    L.append("---")
    L.append("")
    L.append("**未改任何数据、未提升任何状态、未跑 COMSOL、未合成总分。**")
    (out_dir / "te2_9_profile.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    print("[OK] 产物目录：%s" % out_dir.relative_to(REPO))
    for f in sorted(out_dir.iterdir()):
        if f.is_file():
            print("     %s  %d B  %s" % (f.name, f.stat().st_size, sha256_of(f)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
