# -*- coding: utf-8 -*-
"""导出**来自注册件**的中文串（去重），供人工翻译成英文；我自建的 4 条不进表（直接改写）。"""
from __future__ import annotations

import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
M4 = R / "work/runs/ai11-m4-20261013"
CJK = re.compile(r"[\u4e00-\u9fff]")
exp = json.loads((M4 / "EXPECTED_TASKS.json").read_text(encoding="utf-8"))

pairs: dict[str, list[str]] = {}


def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            walk(v, path + "." + k)
    elif isinstance(o, list):
        for v in o:
            walk(v, path + "[]")
    elif isinstance(o, str) and CJK.search(o):
        pairs.setdefault(o, []).append(path.lstrip("."))


for task, items in exp["tasks"].items():
    for rel, obj in items.items():
        if rel.endswith("label_validity.json"):
            continue          # 我自己写的：直接改写成英文，不进映射表
        walk(obj, rel)

out = []
for i, (s, paths) in enumerate(sorted(pairs.items(), key=lambda x: -len(x[0])), 1):
    out.append({"n": i, "chars": len(s), "zh": s, "paths": sorted(set(paths))[:4],
                "count": len(paths)})
dst = M4 / "CJK_STRINGS_TO_TRANSLATE.json"
dst.write_bytes((json.dumps(out, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
print("导出 %d 条不同中文串（来自注册件）→ %s" % (len(out), dst.relative_to(R)))
for o in out:
    print("\n[%02d] %d 字 × %d 处" % (o["n"], o["chars"], o["count"]))
    print("    %s" % o["zh"][:300])
