# -*- coding: utf-8 -*-
"""把 ref_ledger.json 里唯一一条中文 note 改成英文（JSON 感知改写，不碰其它字段）。"""
from __future__ import annotations

import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
p = R / "work/runs/ai11-m4-20261013/tasks_dev/t7/tasks/ref_ledger.json"
d = json.loads(p.read_text(encoding="utf-8"))
print("旧 note:", d["note"])
old = d["note"]
d["note"] = ("(arm,seed,k) -> design projection; used only to check each replayed **proposal** call by "
             "call; contains no y values (truth can come only from the oracle cache)")
b = (json.dumps(d, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
if b"\r\n" in b:
    raise SystemExit("[FAIL] 不应含 CRLF")
CJK = re.compile(r"[\u4e00-\u9fff]")
if CJK.search(b.decode("utf-8")):
    raise SystemExit("[FAIL] 仍有中文")
p.write_bytes(b)
print("新 note:", d["note"])
print("写出 %d B；records=%d；n_records=%d" % (len(b), len(d.get("records") or []), d.get("n_records")))
