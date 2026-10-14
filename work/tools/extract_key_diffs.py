"""提取 cross_check 的关键差异明细（非法枚举 / 值不一致 / 缺失），用于人工裁决。"""

from __future__ import annotations

import json
from pathlib import Path

D = Path(r"C:\Users\zmx\Desktop\memsharness\work\reports\modelio")
diffs = json.loads((D / "crosscheck-b_GE_task3_2new.json").read_text(encoding="utf-8"))

for kind in ("illegal_enum_value", "value_mismatch", "unreadable_in_probe"):
    items = [d for d in diffs if d.get("kind") == kind]
    print(f"\n{'=' * 20} {kind}（{len(items)} 条）{'=' * 20}")
    for d in items:
        print(f"  [{d.get('dimension')}] {d.get('key')}")
        print(f"      spec : {json.dumps(d.get('spec_value'), ensure_ascii=False)[:200]}")
        print(f"      probe: {json.dumps(d.get('probe_value'), ensure_ascii=False)[:200]}")
        print(f"      原因 : {str(d.get('reason'))[:160]}")
        ev = str(d.get("evidence") or "")[:160]
        if ev:
            print(f"      证据 : {ev}")

missing = [d for d in diffs if d.get("kind") == "missing_in_spec"]
print(f"\n{'=' * 20} missing_in_spec（{len(missing)} 条，前 12）{'=' * 20}")
for d in missing[:12]:
    print(f"  [{d.get('dimension')}] {d.get('key')} :: {str(d.get('reason'))[:110]}")

print("\n维度分布：")
by: dict[str, int] = {}
for d in diffs:
    by[str(d.get("dimension"))] = by.get(str(d.get("dimension")), 0) + 1
for k, v in sorted(by.items(), key=lambda x: -x[1]):
    print(f"  {k:22s} {v}")
