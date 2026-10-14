# -*- coding: utf-8 -*-
"""为「选哪个 DAC 方向」的评估做事实核对（只读）。"""
from __future__ import annotations

import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(r"C:\Users\zmx\Desktop\memsharness\work\runs\eda64-20261010")


def show(path: pathlib.Path, title: str) -> dict:
    print("=" * 100)
    print(title, "|", path.relative_to(R.parent.parent))
    if not path.is_file():
        print("  缺件")
        return {}
    d = json.loads(path.read_bytes().decode("utf-8"))
    return d


# ---- 1. 表示层实验：各变体离 2% 多远
d = show(R / "n5_stage3/REPR2_RESULT.json", "REPR2（表示层实验）")
print("  verdict =", d.get("verdict"))
print("  passing variants per family =", json.dumps(d.get("per_variant_families_passing"), ensure_ascii=False))
fams = d.get("families")
if isinstance(fams, dict):
    for fam, body in fams.items():
        print("  family:", fam)
        variants = body.get("variants") if isinstance(body, dict) else None
        if isinstance(variants, dict):
            for name, v in variants.items():
                if isinstance(v, dict):
                    keep = {k: v[k] for k in v if "max" in k or "key" in k or "pass" in k}
                    print("     %-30s %s" % (name, json.dumps(keep, ensure_ascii=False)[:200]))
        else:
            print("     ", json.dumps(body, ensure_ascii=False)[:400])

# ---- 2. 闭环（N3）
for cand in ("n3_dse/N3_DSE_REPORT.md", "n3_dse/N3_DSE_RESULT.json", "n3_dse/N3_RESULT.json"):
    p = R / cand
    if p.is_file():
        print("=" * 100)
        print("N3 闭环件：", cand, p.stat().st_size, "B")
        if p.suffix == ".md":
            print(p.read_text(encoding="utf-8")[:2600])
        else:
            j = json.loads(p.read_bytes().decode("utf-8"))
            print(json.dumps(j, ensure_ascii=False, indent=1)[:2600])
        break

# ---- 3. 既有消融/种子证据
print("=" * 100)
print("N2/N3 目录下的件（找种子与消融）")
for p in sorted(R.rglob("*")):
    if p.is_file() and p.suffix in (".json", ".md"):
        n = p.name.lower()
        if any(k in n for k in ("ablation", "seed", "coverage", "risk", "split", "manifest")):
            print("   %-72s %9d" % (str(p.relative_to(R)), p.stat().st_size))
