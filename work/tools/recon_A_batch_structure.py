# -*- coding: utf-8 -*-
"""查 A 批为何随机臂的 x 邻接也是 0：A 批的 (cell, x) 结构到底是什么（只读）。"""
from __future__ import annotations

import collections
import csv
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(r"C:\Users\zmx\Desktop\memsharness")
A = REPO / "work/runs/grouped-split-20261009/grouped_split_assignments.csv"
with A.open(encoding="utf-8-sig", newline="") as fh:
    rows = list(csv.DictReader(fh))

for b in ("A_5-35MHz", "V2_5-35MHz", "C_5-50MHz"):
    rs = [r for r in rows if r["batch"] == b]
    cells = collections.defaultdict(list)
    for r in rs:
        cells[(r["N_w_te1"], r["N_w_te2"])].append(float(r["x_scale"]))
    print("==", b, "行数", len(rs), "；单元 (N1,N2) 数 =", len(cells))
    for k, xs in sorted(cells.items())[:6]:
        c = collections.Counter(xs)
        rep = sum(1 for v in c.values() if v > 1)
        print("   cell %-12s 行 %3d ｜唯一 x %3d ｜出现>1次的 x %3d ｜x 范围 %.2f–%.2f"
              % (str(k), len(xs), len(c), rep, min(xs), max(xs)))
    # seed0 的 holdout/train x 是否相交（按 cell）
    cell_ho = collections.defaultdict(set)
    cell_tr = collections.defaultdict(set)
    for r in rs:
        (cell_ho if r["side_seed0"] == "holdout" else cell_tr)[(r["N_w_te1"], r["N_w_te2"])].add(float(r["x_scale"]))
    inter = sum(len(cell_ho[k] & cell_tr[k]) for k in cell_ho)
    print("   seed0：按 cell 的 x 交集大小合计 =", inter)
