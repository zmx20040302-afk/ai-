# -*- coding: utf-8 -*-
"""扫出「中文紧邻 ASCII 双引号」的可疑行（我反复踩的语法坑）。"""
import io
import re
import sys

p = r"C:\Users\zmx\Desktop\memsharness\scripts\build_dashboard.py"
pat = re.compile(r'[\u4e00-\u9fff]"|"[\u4e00-\u9fff]')
bad = 0
for i, ln in enumerate(io.open(p, encoding="utf-8").read().splitlines(), 1):
    if pat.search(ln):
        bad += 1
        print(i, ln.strip()[:160])
print("可疑行数:", bad)
sys.exit(0)
