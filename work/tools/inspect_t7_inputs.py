# -*- coding: utf-8 -*-
"""读 T7 预注册件需要内联的字段 + ref_ledger.json 里的中文。"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
T7 = R / "work/runs/ai11-m4-20261013/tasks_dev/t7/tasks"
p = T7 / "PREREG_T7.json"
d = json.loads(p.read_text(encoding="utf-8"))
print("PREREG_T7.json")
print("  sha256 :", hashlib.sha256(p.read_bytes()).hexdigest())
print("  bytes  :", p.stat().st_size)
print("  top    :", list(d.keys()))
print("  kind   :", repr(d.get("kind")))
print("  status :", repr(d.get("status")))
print("  pool   :", json.dumps(d.get("candidate_pool"), ensure_ascii=False)[:220])
print("  budget :", (d.get("design") or {}).get("budget"))
print("  含 work/runs 的键:", [k for k in d if isinstance(d[k], str) and "work/runs" in d[k]])

q = T7 / "ref_ledger.json"
t = q.read_text(encoding="utf-8")
print("\nref_ledger.json")
print("  bytes  :", q.stat().st_size)
print("  顶层键 :", list(json.loads(t).keys()))
CJK = re.compile(r"[\u4e00-\u9fff]")
for m in re.finditer(r'"[^"]*"', t):
    if CJK.search(m.group(0)):
        print("  中文串 :", m.group(0)[:140])
