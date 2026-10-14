"""对照旧案例(bGEtask2)与本机目标器件(b_GE_task3_2-new)的物理场/选择集/研究设置。"""

from __future__ import annotations

import json
import re
from pathlib import Path

WS = Path(r"C:\Users\zmx\Desktop\memsharness")
OLD = WS / "work" / "models" / "bGEtask2-20260911T064304Z"
PROBE = WS / "work" / "reports" / "modelio" / "probe-probe-20260911T153110Z-75135037.json"

old_params = json.loads((OLD / "params.json").read_text(encoding="utf-8"))
old_probe = json.loads((OLD / "probe_mph.json").read_text(encoding="utf-8"))
new = json.loads(PROBE.read_text(encoding="utf-8"))

old_phys = old_params.get("physics")
print("== 旧案例 physics（params.json）==")
print(f"  类型={type(old_phys).__name__}")
if isinstance(old_phys, list):
    for item in old_phys[:12]:
        print(f"    {json.dumps(item, ensure_ascii=False)[:150]}")
elif isinstance(old_phys, dict):
    for key, value in list(old_phys.items())[:12]:
        print(f"    {key}: {json.dumps(value, ensure_ascii=False)[:120]}")

old_sel = old_params.get("named_selections_m_file")
print("\n== 旧案例命名选择集（来自 .m）==")
if isinstance(old_sel, list):
    print(f"  数量={len(old_sel)}: {old_sel}")
elif isinstance(old_sel, dict):
    print(f"  keys={list(old_sel)[:20]}")

new_phys = [n for n in (new.get("physics") or []) if n.get("kind") != "named_selection"]
new_sel = [n.get("tag") for n in (new.get("physics") or []) if n.get("kind") == "named_selection"]
print("\n== 目标器件（本机 probe）==")
print(f"  物理场接口: {[n.get('tag') for n in new_phys]}")
print(f"  命名选择集 {len(new_sel)} 个: {new_sel}")
print(f"  研究: {[(s.get('tag'), [x.get('type') for x in s.get('steps') or []]) for s in new.get('studies') or []]}")
print(f"  几何: {new.get('geometry')}")
print(f"  网格: {new.get('mesh')}")

print("\n== 旧案例 probe_mph.json 里的对应项 ==")
print(f"  components: {json.dumps(old_probe.get('components'), ensure_ascii=False)[:200]}")
print(f"  geometry: {json.dumps(old_probe.get('geometry'), ensure_ascii=False)[:200]}")
print(f"  parameter_names 数量: {len(old_probe.get('parameter_names') or [])}")
print(f"  readback: {json.dumps(old_probe.get('readback'), ensure_ascii=False)[:160]}")

report = (OLD / "REPORT.md").read_text(encoding="utf-8", errors="replace")
print("\n== 旧 REPORT.md 里关于研究/频点/DOF 的行 ==")
for line in report.splitlines():
    if re.search(r"研究|频点|freq|DOF|自由度|网格|单元", line) and len(line.strip()) > 8:
        print(f"    {line.strip()[:160]}")
