# -*- coding: utf-8 -*-
"""跨管线一致性交叉检验：v2（5–35 MHz，COMSOL 自带峰值/截断点）vs C 批（5–50 MHz）。

做法：按 **ulp 归一化**的组合键 `(round(x_scale,6), N1, N2)` 连接两批，比较
`f_peak_Hz / bandwidth_Hz / Q` 的相对差。**只比较 v2 峰值未落在扫描端点**（未删失）的组合，
因为删失时 v2 的峰值只是下界，比它就是比错对象。

判读纪律：
* 阈值**不预设**通过线（两批扫描范围不同，预期本就有系统差）；先**描述分布**（中位/最大相对差、
  超 1% 的个数），把差异摆出来由人判读，**不合成总分、不下放行结论**；
* 任何"一致"只说明两条管线在共同组合上互相佐证，**不构成**对任一管线的合格判定。
"""
from __future__ import annotations

import csv
import pathlib
import statistics as st
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
V2 = sorted((REPO / "work/runs/remote-exported-v2-20260922").glob("v2_labels_frozen_*.csv"))[-1]
OLD = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"


def key(x, n1, n2):
    return (round(float(x), 6), int(float(n1)), int(float(n2)))


def fnum(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def main() -> int:
    old = {key(r["x_scale"], r["N_w_te1"], r["N_w_te2"]): r
           for r in csv.DictReader(OLD.open("r", encoding="utf-8", newline=""))}
    v2 = list(csv.DictReader(V2.open("r", encoding="utf-8", newline="")))
    print("C 组合 %d ｜ V2 组合 %d" % (len(old), len(v2)))

    pairs = [(r, old[key(r["x_scale"], r["N_w_te1"], r["N_w_te2"])])
             for r in v2 if key(r["x_scale"], r["N_w_te1"], r["N_w_te2"]) in old]
    print("重叠 %d 个" % len(pairs))
    for label, ccol, vcol in (("峰频 Hz", "f_peak_Hz", "peak_freq_Hz"),
                              ("带宽 Hz", "bandwidth_Hz", "bandwidth_Hz"),
                              ("Q", "Q_factor", "Q")):
        avail = [(a, b) for a, b in pairs if ccol in b]
        if not avail:
            print("\n[%s] C 批无列 %r ⇒ 跳过" % (label, ccol))
            continue
        usable = [(a, b) for a, b in avail
                  if str(a["peak_at_scan_endpoint"]).lower() != "true"
                  and str(a["bw_upper_cutoff_at_endpoint"]).lower() != "true"]
        rel = []
        for a, b in usable:
            va, vb = fnum(a[vcol]), fnum(b[ccol])
            if va is None or vb is None or vb == 0:
                continue
            rel.append(abs(va - vb) / abs(vb))
        print("\n[%s] 两批都有、且 v2 未删失/未截断 %d 组" % (label, len(rel)))
        if not rel:
            print("   无可比项")
            continue
        rel.sort()
        print("   相对差：中位 %.3e ｜ p90 %.3e ｜ 最大 %.3e（最大出现在组合 %s）"
              % (st.median(rel), rel[int(0.9 * len(rel)) - 1], rel[-1],
                 key(*[usable[rel.index(rel[-1])][0][c] for c in
                       ("x_scale", "N_w_te1", "N_w_te2")])))
        for thr in (1e-6, 1e-3, 1e-2, 5e-2):
            print("   超 %.0e 的个数 %d / %d（%.1f%%）"
                  % (thr, sum(1 for x in rel if x > thr), len(rel),
                     100 * sum(1 for x in rel if x > thr) / len(rel)))
    print("\n注：本检验只做描述性对账，不设通过线、不合成总分、不构成放行依据。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
