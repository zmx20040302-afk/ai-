# -*- coding: utf-8 -*-
"""打印 t1_t2 两个产物里未映射中文串的**全文**（用于补片段表）。"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
H = R / "work/runs/ai11-m4-20261013/tasks_dev/_harness"
spec = importlib.util.spec_from_file_location("t", H / "tasks/_text.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)

for f in ("T1_T2_RESULT.json", "T1_T2_SPACING_RESULT.json"):
    d = json.loads((H / "results" / f).read_text(encoding="utf-8"))
    for p, s in T.unmapped_cjk(T.to_en(d)):
        print("=== %s" % f)
        print("path: %s" % p)
        print("full: %r" % s)
        print()
