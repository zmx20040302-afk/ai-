# -*- coding: utf-8 -*-
"""盘点「可作独立留出集」的候选（只读，不求解）：把仓库里**真实存在**的留出划分全部列出。"""
from __future__ import annotations

import collections
import csv
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]   # work/tools/*.py ⇒ parents[2] = 仓库根
R = REPO / "work/runs"

print("=" * 90)
print("A. 导出方快照索引（权威划分来源）:", "snapshot_index.tsv")
tsv = R / "te2_8_pod_fields_20261005/snapshot_index.tsv"
with tsv.open(encoding="utf-8-sig", newline="") as fh:
    rows = list(csv.DictReader(fh, delimiter="\t"))
print("   总行数", len(rows), "列:", list(rows[0].keys()))
fam = collections.defaultdict(lambda: {"n": 0, "x": set(), "role": collections.Counter()})
for r in rows:
    k = (float(r["N_w_te1"]), float(r["N_w_te2"]), float(r["freq_Hz"]) / 1e6)
    fam[k]["n"] += 1
    fam[k]["x"].add(round(float(r["x_scale"]), 2))
    fam[k]["role"][r["x_holdout_role"]] += 1
for k in sorted(fam):
    v = fam[k]
    xs = sorted(v["x"])
    print("   (N1=%.0f, N2=%.0f, f=%g MHz): n=%d  x∈[%.2f,%.2f] 共 %d 值  role=%s"
          % (k[0], k[1], k[2], v["n"], xs[0], xs[-1], len(xs), dict(v["role"])))
holdout_x = sorted({round(float(r["x_scale"]), 2) for r in rows if r["x_holdout_role"] == "holdout"})
na_x = sorted({round(float(r["x_scale"]), 2) for r in rows if r["x_holdout_role"] == "na"})
print("   留出 x（role=holdout）:", holdout_x)
print("   role=na 的 x:", na_x)

print("=" * 90)
print("B. 标签语料的防泄漏整组切分（CV 用，不是独立留出）")
asg = R / "grouped-split-20261009/grouped_split_assignments.csv"
with asg.open(encoding="utf-8-sig", newline="") as fh:
    a = list(csv.DictReader(fh))
print("   行数", len(a), "批次:", dict(collections.Counter(r["batch"] for r in a)))
for c in [c for c in a[0] if c.startswith("side_seed")]:
    cnt = collections.Counter(r[c] for r in a)
    print("   %s: %s" % (c, dict(cnt)))

print("=" * 90)
print("C. 其它候选留出集（按来源）")
cands = [
    ("H1 导出方 x-holdout 5", "work/runs/te2_8_pod_fields_20261005/snapshot_index.tsv",
     "x_holdout_role=holdout；N1∈{4,7}×N2=8，20 MHz，1369 点场云；S1/S2 已用它"),
    ("H2 v2 冻结批（异管线）", "work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv",
     "250 行；标志是代理量（peak_at_scan_endpoint 等）⇒ 只能作**异管线/分布偏移**对照，不是干净留出"),
    ("H3 te2_9 重导出（异源模型）", "work/runs/…（648 组合 × 91 频点 = 58,968 点）",
     "与 v2 的重叠回归靶未过（最大 |Δ| 0.08849 dB）⇒ 只能作分布偏移测试集"),
    ("H4 分组 CV（5 种子）", "work/runs/grouped-split-20261009/grouped_split_assignments.csv",
     "同语料内的防泄漏整组切分 ⇒ 是**交叉验证**，不是独立留出"),
]
for name, path, note in cands:
    print("   - %s\n      路径: %s\n      性质: %s" % (name, path, note))

print("=" * 90)
print("D. 8 折覆盖率协议的两族（S5 补充件）")
for f in ("n1_4", "n1_7"):
    p = R / ("te2_8_pod_fields_20261005/x_family/%s/s5_8fold_%s.json" % (f, f))
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        keep = {k: v for k, v in d.items()
                if isinstance(v, (int, float, str, bool, type(None)))}
        print("   %s: %s" % (f, json.dumps(keep, ensure_ascii=False)[:300]))
    else:
        print("   %s: 缺 %s" % (f, p))
