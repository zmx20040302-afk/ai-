# -*- coding: utf-8 -*-
"""量化：包内**任务期望值**里有多少中文（CJK）自由文本，分别落在哪些键上。

用途：判断「逐字保留上游内部语言」与「英文投稿件的观感/匿名信号」之间的取舍。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
M4 = R / "work/runs/ai11-m4-20261013"
CJK = re.compile(r"[\u4e00-\u9fff]")

exp = json.loads((M4 / "EXPECTED_TASKS.json").read_text(encoding="utf-8"))

hits: dict[str, list[tuple[str, int]]] = {}


def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            walk(v, path + "." + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, path + "[]")
    elif isinstance(o, str) and CJK.search(o):
        n = len(CJK.findall(o))
        top = ".".join(path.lstrip(".").split(".")[:2])
        hits.setdefault(top, []).append((path, n))


for task, items in exp["tasks"].items():
    for rel, obj in items.items():
        walk(obj, rel)

total_strings = 0
total_cjk = 0
print("%-58s %6s %6s" % ("键前缀（前两层）", "串数", "中文字数"))
for k in sorted(hits, key=lambda x: -sum(n for _, n in hits[x])):
    lst = hits[k]
    total_strings += len(lst)
    total_cjk += sum(n for _, n in lst)
    print("%-58s %6d %6d" % (k, len(lst), sum(n for _, n in lst)))
print("\n合计：%d 个含中文字符串，%d 个中文字符" % (total_strings, total_cjk))

print("\n=== 示例（每类前 2 条）===")
for k in sorted(hits, key=lambda x: -sum(n for _, n in hits[x]))[:8]:
    for path, n in hits[k][:2]:
        print("  %-52s (%d 字)" % (path[:52], n))
