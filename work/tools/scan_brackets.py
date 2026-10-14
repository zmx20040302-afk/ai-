# -*- coding: utf-8 -*-
"""手写扫描器：忽略字符串/注释，报告每层括号的起止行，找出未闭合的那个。"""
from __future__ import annotations

import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(r"C:\Users\zmx\Desktop\memsharness\work\runs\eda64-20261010\make_item3_prereg_and_cost.py")
src = P.read_text(encoding="utf-8")

stack = []
i, line = 0, 1
in_str = None
pairs = {")": "(", "]": "[", "}": "{"}
while i < len(src):
    ch = src[i]
    if ch == "\n":
        line += 1
    if in_str:
        if ch == "\\":
            i += 2
            continue
        if src.startswith(in_str, i):
            i += len(in_str)
            in_str = None
            continue
        i += 1
        continue
    if src.startswith('"""', i) or src.startswith("'''", i):
        in_str = src[i:i + 3]
        i += 3
        continue
    if ch in "\"'":
        in_str = ch
        i += 1
        continue
    if ch == "#":
        while i < len(src) and src[i] != "\n":
            i += 1
        continue
    if ch in "([{":
        stack.append((ch, line))
    elif ch in pairs:
        if stack and stack[-1][0] == pairs[ch]:
            stack.pop()
        else:
            print("不匹配 %r 在第 %d 行（栈顶 %s）" % (ch, line, stack[-1] if stack else None))
    i += 1
print("未闭合 %d 个：" % len(stack))
for op, ln in stack:
    print("   %r 开于第 %d 行" % (op, ln))
