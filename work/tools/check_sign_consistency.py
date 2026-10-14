# -*- coding: utf-8 -*-
"""同一数值在正文/旧补充材料/新补充材料里是否用了**同一个负号**。"""
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
files = ["docs/PAPER_DAC2027_EN_v17_20261013.md", "docs/PAPER_DAC2027_EN_v18_20261013.md",
         "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013d.md", "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013e.md"]
needle = "2.094393557e"
for f in files:
    t = (R / f).read_text(encoding="utf-8")
    for m in re.finditer(re.escape(needle) + r"(.{0,2})", t):
        code = " ".join("U+%04X" % ord(c) for c in m.group(1)[:1])
        print("%-52s %s  → 负号码位 %s" % (f.split("/")[-1][:52], m.group(0), code))
