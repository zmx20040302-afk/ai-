# -*- coding: utf-8 -*-
"""定位 `make_item3_prereg_and_cost.py` 里未闭合的括号（按 tokenize，忽略字符串内括号）。"""
from __future__ import annotations

import io
import pathlib
import sys
import tokenize

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(r"C:\Users\zmx\Desktop\memsharness\work\runs\eda64-20261010\make_item3_prereg_and_cost.py")
src = P.read_text(encoding="utf-8")
stack = []
pairs = {")": "(", "]": "[", "}": "{"}
for tok in tokenize.generate_tokens(io.StringIO(src).readline):
    if tok.type == tokenize.OP:
        if tok.string in "([{":
            stack.append((tok.string, tok.start))
        elif tok.string in pairs:
            if not stack:
                print("多余的 %r 在 %s" % (tok.string, tok.start))
            else:
                op, pos = stack.pop()
                if op != pairs[tok.string]:
                    print("不匹配：%r@%s 对上了 %r@%s" % (op, pos, tok.string, tok.start))
print("未闭合（栈内剩余 %d 个）：" % len(stack))
for op, pos in stack[-12:]:
    print("   %r 开于第 %d 行第 %d 列" % (op, pos[0], pos[1]))
