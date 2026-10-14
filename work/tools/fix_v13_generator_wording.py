# -*- coding: utf-8 -*-
"""把 v13 生成器里残留的「7 处」字样改成「9 处」（纯文案一致性，不改逻辑）。"""
from __future__ import annotations

import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
p = pathlib.Path(r"C:\Users\zmx\Desktop\memsharness\work\tools\make_dac2027_en_v13.py")
t = p.read_text(encoding="utf-8")
pairs = [
    ("7 处替换，每处**恰好命中 1 次**", "9 处替换，每处**恰好命中 1 次**"),
    ("经 **7 处**单命中字面替换生成（每处恰好 1 次）", "经 **9 处**单命中字面替换生成（每处恰好 1 次）"),
    ("7 处替换各命中 1 次", "9 处替换各命中 1 次"),
    ("除上述 7 处外**一字未动**", "除上述 9 处外**一字未动**"),
]
for a, b in pairs:
    if a not in t:
        print("未找到（跳过）：%s" % a)
    t = t.replace(a, b)
p.write_bytes(t.encode("utf-8"))
left = t.count("7 处")
print("剩余「7 处」出现次数 =", left)
print("校验：\"9 处替换各命中 1 次\" 在文件中 =", "9 处替换各命中 1 次" in t)
