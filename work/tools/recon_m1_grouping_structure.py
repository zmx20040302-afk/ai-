# -*- coding: utf-8 -*-
"""M1 的自查：注册 grouped split 到底"分组"在什么上？与随机臂在**几何**上差多少？（只读）"""
from __future__ import annotations

import collections
import csv
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(r"C:\Users\zmx\Desktop\memsharness")
A = REPO / "work/runs/grouped-split-20261009/grouped_split_assignments.csv"

with A.open(encoding="utf-8-sig", newline="") as fh:
    rows = list(csv.DictReader(fh))

print("dup_score 分布 =", dict(collections.Counter(r["dup_score"] for r in rows)))
print("dup_kind_refined 分布 =", dict(collections.Counter(r["dup_kind_refined"] for r in rows)))
print("source_pipeline =", dict(collections.Counter(r["source_pipeline"] for r in rows)))

# 每个种子每批：holdout 中有多少行的 (n1,n2) 里存在 |Δx| <= 0.0101 的 train 行
for s in (0, 1):
    print()
    for b in ("A_5-35MHz", "C_5-50MHz", "V2_5-35MHz"):
        rs = [r for r in rows if r["batch"] == b]
        tr = [r for r in rs if r["side_seed%d" % s] == "train"]
        ho = [r for r in rs if r["side_seed%d" % s] == "holdout"]
        cell_tr = collections.defaultdict(list)
        for r in tr:
            cell_tr[(r["N_w_te1"], r["N_w_te2"])].append(float(r["x_scale"]))
        adj = 0
        for r in ho:
            xs = cell_tr.get((r["N_w_te1"], r["N_w_te2"]))
            if xs and any(abs(float(r["x_scale"]) - v) <= 0.0101 for v in xs):
                adj += 1
        xs_ho = sorted({float(r["x_scale"]) for r in ho})
        xs_tr = sorted({float(r["x_scale"]) for r in tr})
        print("seed %d  %-11s  holdout %4d  x邻接(<=0.0101) %4d（%.1f%%）｜holdout 唯一 x 数 %3d ｜train 唯一 x 数 %3d"
              % (s, b, len(ho), adj, 100.0 * adj / max(1, len(ho)), len(xs_ho), len(xs_tr)))
        if b == "C_5-50MHz":
            print("      C 批 holdout x 头 12 个：", [round(v, 3) for v in xs_ho[:12]])
            print("      C 批 train   x 头 12 个：", [round(v, 3) for v in xs_tr[:12]])
