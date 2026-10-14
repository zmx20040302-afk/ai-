# -*- coding: utf-8 -*-
"""量化 PREREG_T7.json 里需要英文化的字符串，并列出两处泄漏（work/runs、input.mph）。"""
from __future__ import annotations

import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
p = R / "work/runs/ai11-m4-20261013/tasks_dev/t7/tasks/PREREG_T7.json"
t = p.read_text(encoding="utf-8")
d = json.loads(t)
CJK = re.compile(r"[\u4e00-\u9fff]")

uniq, paths = {}, []
def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            walk(v, path + "." + k)
    elif isinstance(o, list):
        for v in o:
            walk(v, path + "[]")
    elif isinstance(o, str):
        if CJK.search(o):
            uniq.setdefault(o, []).append(path.lstrip("."))
        for pat in ("work/runs", "work\\runs", ".mph"):
            if pat in o:
                paths.append((path.lstrip("."), pat, o[:110]))
walk(d)

print("含中文的不同字符串：%d 条，总汉字 %d" % (len(uniq), sum(len(CJK.findall(s)) for s in uniq)))
for i, (s, ps) in enumerate(sorted(uniq.items(), key=lambda x: -len(x[0])), 1):
    print("  [%02d] %3d 字 @ %s" % (i, len(s), ", ".join(sorted(set(ps))[:2])[:70]))
    print("       %s" % s[:200])
print("\n泄漏串：%d 处" % len(paths))
for pa, pat, s in paths:
    print("  %-40s [%s] %s" % (pa[:40], pat, s))
