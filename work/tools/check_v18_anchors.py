# -*- coding: utf-8 -*-
"""复核 v18 生成器的四处锚点（文件式，避免 PS 引号/反引号被吃）。"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
d = (R / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013d.md").read_text(encoding="utf-8")

for ln, line in enumerate(d.split("\n"), 1):
    if line.startswith("| T3 |") or line.startswith("| T5 |"):
        print("L%d  %r" % (ln, line))
        print()
i = d.find("A single model file can therefore contain solutions")
print("S9 句定位：", i)
print(repr(d[i - 120:i + 200]))
