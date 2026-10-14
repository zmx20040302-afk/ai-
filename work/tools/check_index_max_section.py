# -*- coding: utf-8 -*-
"""只读检查 `docs/INDEX-records-and-rulings.md` 的当前最大节号与哈希。

用途：A3 轮追加索引前**先读**，用于确定 `max+1` 的节号并躲开并发会话的编号冲突
（工单要求：另一个会话可能正在写 §97；追加器本身有重复拒收守卫，但节号要自己算）。
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

p = pathlib.Path(__file__).resolve().parents[2] / "docs/INDEX-records-and-rulings.md"
t = p.read_text(encoding="utf-8")
secs = [int(m.group(1)) for m in re.finditer(r"(?m)^## (\d+)\.", t)]
print("path      = %s" % p)
print("chars     = %d" % len(t))
print("lines     = %d" % (t.count("\n") + 1))
print("sections  = %s ... %s" % (secs[:3], secs[-5:]))
print("max_section = %d" % (max(secs) if secs else 0))
print("next_free   = %d" % ((max(secs) + 1) if secs else 1))
print("sha256    = %s" % hashlib.sha256(p.read_bytes()).hexdigest())
sys.exit(0)
