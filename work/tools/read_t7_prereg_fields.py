# -*- coding: utf-8 -*-
"""取 T7 冻结预注册里脚本真正要内联的**真实值**。"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
p = R / "work/runs/ai11-m4-20261013/tasks_dev/t7/tasks/PREREG_T7.json"
d = json.loads(p.read_text(encoding="utf-8"))
print("PREREG_SHA256   =", repr(hashlib.sha256(p.read_bytes()).hexdigest()))
print("PREREG_KIND     =", repr(d["kind"]))
print("PREREG_STATUS   =", repr(d["status"]))
print("pool            =", json.dumps(d["candidate_pool"], ensure_ascii=False)[:300])
print("pool size       =", repr((d["candidate_pool"] or {}).get("size")))
print("pool sha256     =", repr((d["candidate_pool"] or {}).get("sha256")))
print("design.budget   =", json.dumps((d.get("design") or {}).get("budget"), ensure_ascii=False))
# 也看扩展块里的真实调用数（用于核对 165 次的来源）
ext = d.get("extension_20261013")
print("extension block =", json.dumps(ext, ensure_ascii=False)[:400] if ext else None)
