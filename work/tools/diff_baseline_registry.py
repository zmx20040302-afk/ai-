# -*- coding: utf-8 -*-
"""结构比对：注册的 baselines_by_seed.json vs 包内 bench.py 复跑的同一件。

关心两件事：
  ① 差异是否**只在溯源/路径元数据**；
  ② 所有**数值**（per_seed 的 median/p90/... 与 anchors）是否逐位相同。
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
SRC = json.loads((R / "work/runs/eda64-20261010/n2_baselines/baselines_by_seed.json").read_text(encoding="utf-8"))
PKG = json.loads((R / "work/runs/ai11-m4-20261013/smoke_results/baselines_by_seed.json").read_text(encoding="utf-8"))


def walk(a, b, path="$", diffs=None, nums=None):
    diffs = [] if diffs is None else diffs
    nums = [] if nums is None else nums
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                diffs.append((path + "." + k, "<仅复跑有>", repr(b[k])[:60]))
            elif k not in b:
                diffs.append((path + "." + k, repr(a[k])[:60], "<仅注册有>"))
            else:
                walk(a[k], b[k], path + "." + k, diffs, nums)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append((path + "[]", "len=%d" % len(a), "len=%d" % len(b)))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, path + "[%d]" % i, diffs, nums)
    else:
        if isinstance(a, (int, float)) and not isinstance(a, bool):
            if a != b:
                nums.append((path, a, b))
        elif a != b:
            diffs.append((path, repr(a)[:70], repr(b)[:70]))
    return diffs, nums


d, n = walk(SRC, PKG)
print("== 非数值差异（%d 处）==" % len(d))
for p, x, y in d[:40]:
    print("  %-52s\n      注册: %s\n      复跑: %s" % (p, x, y))
print("\n== 数值差异（%d 处）==" % len(n))
for p, x, y in n[:20]:
    print("  %-52s 注册=%r 复跑=%r" % (p, x, y))
if not n:
    print("  （无）⇒ 全部数值逐位相同")
print("\n== 顶层键 ==")
print("  注册:", list(SRC.keys()))
print("  复跑:", list(PKG.keys()))
