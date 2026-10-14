# -*- coding: utf-8 -*-
"""更正：按 **ulp 归一化**（`round(...,6)`）重算 v2 相对批次 C 的新增/重叠，并修正 N2=9 的可用数。

发现问题：`verify_two_batch_integrity.py` 报交集 **167**，而先前 `v2_coverage_check.py` 报
"新增 117（=250−133）"。差异来自 `x_scale` 的 **1 ulp 表示差**（C: `0.30000000000000004`，v2: `0.3`）：
不归一化 ⇒ 同一组合被判成不同 ⇒ **新增数被虚高**。这正是注入稿 R5 的教训在数据侧的重演。

本脚本输出**更正后的数字**（不改任何既有产物；更正通过追加记录完成）。
"""
from __future__ import annotations

import csv
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
V2 = sorted((REPO / "work/runs/remote-exported-v2-20260922").glob("v2_labels_frozen_*.csv"))[-1]
OLD = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"


def k(r: dict) -> tuple:
    return (round(float(r["x_scale"]), 6), int(float(r["N_w_te1"])), int(float(r["N_w_te2"])))


def main() -> int:
    old = {k(r) for r in csv.DictReader(OLD.open("r", encoding="utf-8", newline=""))}
    v2 = list(csv.DictReader(V2.open("r", encoding="utf-8", newline="")))
    print("C 组合（ulp 归一化）%d ｜ V2 组合 %d" % (len(old), len(v2)))
    shared = [r for r in v2 if k(r) in old]
    new = [r for r in v2 if k(r) not in old]
    print("\n== 更正后（ulp 归一化）==")
    print("  两批重叠 %d ｜ V2 新增 %d（先前误报 117，虚高 %d）"
          % (len(shared), len(new), len(new) - 117))
    print("\n  逐 cell：")
    for cell in sorted({r["cell"] for r in v2}):
        s = [r for r in v2 if r["cell"] == cell]
        sh = [r for r in s if k(r) in old]
        nw = [r for r in s if k(r) not in old]
        print("    %-7s 共 %2d ｜ 重叠 %2d ｜ 新增 %2d" % (cell, len(s), len(sh), len(nw)))
    n9 = [r for r in new if int(float(r["N_w_te2"])) == 9]
    usable = [r for r in n9 if str(r["peak_at_scan_endpoint"]).lower() != "true"
              and str(r["bw_upper_cutoff_at_endpoint"]).lower() != "true"]
    print("\n== N2=9（新增部分）==")
    print("  新增 %d ｜ 可用 %d" % (len(n9), len(usable)))
    print("  （先前报「79 新增 / 46 可用」——若与此不同，以本节为准）")
    allu = [r for r in v2 if str(r["peak_at_scan_endpoint"]).lower() != "true"
            and str(r["bw_upper_cutoff_at_endpoint"]).lower() != "true"]
    print("\n== 全批可用性（不受重叠影响）==")
    print("  250 组合 ｜ 可用 %d（%.1f%%）" % (len(allu), 100 * len(allu) / len(v2)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
