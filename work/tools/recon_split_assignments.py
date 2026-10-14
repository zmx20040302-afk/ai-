# -*- coding: utf-8 -*-
"""侦察冻结 grouped split 指派表（只读）：列、分组变量、逐种子每批 holdout 规模。"""
from __future__ import annotations

import collections
import csv
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(r"C:\Users\zmx\Desktop\memsharness")
A = REPO / "work/runs/grouped-split-20261009/grouped_split_assignments.csv"
V3 = REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv"

with A.open(encoding="utf-8-sig", newline="") as fh:
    rd = csv.DictReader(fh)
    cols = rd.fieldnames
    rows = list(rd)
print("指派表列 =", cols)
print("行数 =", len(rows))
print("首行 =", {k: rows[0][k] for k in cols})

for s in range(5):
    c = collections.Counter(r["side_seed%d" % s] for r in rows)
    print("seed %d 侧分布 = %s" % (s, dict(c)))

# 分组变量：找出哪些列在 holdout 上取值集中
for cand in cols:
    if cand.startswith("side_seed") or cand == "row_index":
        continue
    vals_ho = {r[cand] for r in rows if r["side_seed0"] == "holdout"}
    vals_tr = {r[cand] for r in rows if r["side_seed0"] == "train"}
    if len(vals_ho) <= 8 and len(vals_tr) <= 8:
        print("候选分组列 %-16s holdout=%s train=%s" % (cand, sorted(vals_ho)[:8], sorted(vals_tr)[:8]))

with V3.open(encoding="utf-8-sig", newline="") as fh:
    rd = csv.DictReader(fh)
    v3cols = rd.fieldnames
    v3 = list(rd)
print()
print("v3 表列 =", v3cols)
print("v3 行数 =", len(v3))
print("v3 批分布 =", dict(collections.Counter(r.get("batch") or r.get("source_dataset") or "?" for r in v3)))
