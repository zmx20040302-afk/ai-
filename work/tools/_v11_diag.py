# -*- coding: utf-8 -*-
"""诊断 v11 反向还原为何找不到 §6.9 块。"""
import importlib.util
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gen", HERE / "make_dac2027_v11_facts.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

block = gen.build_69()
print("block 行数 =", block.count("\n") + 1)
blines = block.split("\n")
print("首行:", repr(blines[0][:60]))
print("末行:", repr(blines[-1][:60]))
print("含 \\r ?", "\r" in block)

b10 = gen.V10.read_bytes()
txt = b10.decode("utf-8")
for old, new, tag in gen.EDITS:
    txt = txt.replace(old, new, 1)
lines = txt.split("\n")
note_i = next(i for i, l in enumerate(lines) if l.startswith("> **v10 修订（本轮；"))
lines.insert(note_i + 1, gen.NOTE_V11.rstrip("\n") + "\r")
sec_i = next(i for i, l in enumerate(lines) if l.rstrip("\r") == "## 7. 讨论")
add = [ln + "\r" for ln in blines] + [""]
lines[sec_i:sec_i] = add
txt11 = "\n".join(lines)
blk_crlf = "".join(ln + "\r\n" for ln in blines) + "\r\n"
print("blk_crlf in txt11 ?", blk_crlf in txt11)
i = txt11.find(blines[0])
print("首行出现位置:", i)
print("该处上下文:", repr(txt11[i - 20:i + 120]))
print("块区域:", repr(txt11[i:i + len(blk_crlf) + 40]))
print("相等？", txt11[i:i + len(blk_crlf)] == blk_crlf)
# 逐行比对
seg = txt11[i:i + len(blk_crlf)]
for n, (a, b) in enumerate(zip(seg.split("\r\n"), blk_crlf.split("\r\n"))):
    if a != b:
        print("首个不同行", n, repr(a[:80]), "|", repr(b[:80]))
        break
