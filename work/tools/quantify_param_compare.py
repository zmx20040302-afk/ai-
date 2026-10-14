"""量化参数对照的**可比对数**，避免把「表达式缺省」误当成「一致」。"""

from __future__ import annotations

import json
from pathlib import Path

WS = Path(r"C:\Users\zmx\Desktop\memsharness")
OLD = WS / "work" / "models" / "bGEtask2-20260911T064304Z" / "params.json"
NEW = WS / "work" / "reports" / "modelio" / "probe-probe-20260911T153110Z-75135037.json"

old_raw = json.loads(OLD.read_text(encoding="utf-8"))
container = old_raw.get("parameters", old_raw)
old = {}
for item in container if isinstance(container, list) else []:
    old[item["name"]] = item
if isinstance(container, dict):
    for name, value in container.items():
        old[name] = value if isinstance(value, dict) else {"expression": value}

new = {p["name"]: p for p in json.loads(NEW.read_text(encoding="utf-8"))["parameters"]}

both = same = diff = 0
skipped = []
for name in sorted(set(old) & set(new)):
    oe = str(old[name].get("expression") or old[name].get("m_expression") or "").strip()
    ne = str(new[name].get("expression") or "").strip()
    if oe and ne:
        both += 1
        if oe == ne:
            same += 1
        else:
            diff += 1
            print(f"  差异 {name}: 旧={oe!r} 新={ne!r}")
    else:
        skipped.append((name, oe or "(空)", ne or "(空)"))

print(f"公共参数 {len(set(old) & set(new))} 个：双方表达式非空可比 {both} 个（一致 {same}、不同 {diff}）")
print(f"表达式缺省/未取到而**不可比** {len(skipped)} 个：")
for name, oe, ne in skipped:
    print(f"  {name:12s} 旧={oe[:40]:42s} 新={ne[:40]}")
print("\n旧 params.json 可用字段样例：")
sample = next(iter(old.values()))
print(f"  {json.dumps(sample, ensure_ascii=False)[:300]}")
