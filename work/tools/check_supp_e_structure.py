# -*- coding: utf-8 -*-
"""核对 v18 补充材料：章节编号、§S12 表格列数、§S13 结构。"""
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
p = R / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013e.md"
t = p.read_text(encoding="utf-8")

print("== 章节 ==")
for ln, line in enumerate(t.split("\n"), 1):
    if re.match(r"^#{2,3} ", line):
        print("  L%-5d %s" % (ln, line))

print("\n== §S12 表格逐行列数 ==")
in_tab = False
for ln, line in enumerate(t.split("\n"), 1):
    if line.startswith("## S12."):
        in_tab = True
    elif in_tab and re.match(r"^## ", line):
        break
    if in_tab and line.startswith("|"):
        cols = [c for c in line.split("|")[1:-1]]
        flag = "" if len(cols) == 6 else "  <== 列数 %d ≠ 6" % len(cols)
        print("  L%-5d %d 列%s  %s" % (ln, len(cols), flag, line[:58]))

print("\n== §S13 ==")
i = t.find("## S13.")
print("  位置:", i, "｜到文件尾:", len(t) - i, "字符")
seg = t[i:]
for must in ("6.667", "2.094393557e-12", "geometric invariant", "**Not claimed.**",
             "no solve", "re-solved", "identical geometry"):
    print("  含 %-22s %s" % (must, must in seg))
print("  §S13 内表格行数:", sum(1 for l in seg.split("\n") if l.startswith("|")))
bad = [l for l in seg.split("\n") if l.startswith("|") and len(l.split("|")[1:-1]) != 5]
print("  §S13 非 5 列表格行:", bad)
print("\n尾部 60 字符:", repr(t[-60:]))
