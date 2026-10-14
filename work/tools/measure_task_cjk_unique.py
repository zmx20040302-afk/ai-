# -*- coding: utf-8 -*-
"""去重量化：若要把任务产物里的中文自由文本改成英文，实际需要写多少条**互不相同**的字符串。"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
M4 = R / "work/runs/ai11-m4-20261013"
CJK = re.compile(r"[\u4e00-\u9fff]")
exp = json.loads((M4 / "EXPECTED_TASKS.json").read_text(encoding="utf-8"))

uniq: dict[str, set] = collections.defaultdict(set)
keyof: dict[str, set] = collections.defaultdict(set)


def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            walk(v, path + "." + k)
    elif isinstance(o, list):
        for v in o:
            walk(v, path + "[]")
    elif isinstance(o, str) and CJK.search(o):
        leaf = path.lstrip(".").split(".", 1)[-1]
        leaf = re.sub(r"\[\]", "[]", leaf)
        uniq[leaf].add(o)
        keyof[path.lstrip(".").split(".")[0]].add(o)


for task, items in exp["tasks"].items():
    for rel, obj in items.items():
        walk(obj, rel)

alluniq = set()
print("%-56s %8s %8s" % ("叶键（去掉外层输出件名）", "不同串", "总出现"))
for k in sorted(uniq, key=lambda x: -len(uniq[x])):
    alluniq |= uniq[k]
    print("%-56s %8d %8d" % (k[:56], len(uniq[k]), 1))
print("\n**去重后共需处理 %d 条不同字符串**" % len(alluniq))
print("\n字符数分布（去重后）：")
ln = sorted((len(s), s) for s in alluniq)
print("  最短 %d 字 / 中位 %d 字 / 最长 %d 字 / 合计 %d 字"
      % (ln[0][0], ln[len(ln) // 2][0], ln[-1][0], sum(x[0] for x in ln)))
print("\n最长的 6 条：")
for n, s in ln[-6:]:
    print("  [%3d 字] %s" % (n, s[:150]))
