"""用**正确字段名**重做参数对照（旧 params.json 用 probe_expression / m_last_expression）。

教训：第一次对照取了 `expression` 字段，旧文件里不存在 → 可比对数为 0，
却打印出「0 处不同」，属于**空比较得出的假结论**。本脚本先报可比对数，再报差异。
"""

from __future__ import annotations

import json
from pathlib import Path

WS = Path(r"C:\Users\zmx\Desktop\memsharness")
OLD_RAW = json.loads(
    (WS / "work" / "models" / "bGEtask2-20260911T064304Z" / "params.json").read_text(encoding="utf-8")
)
NEW_RAW = json.loads(
    (WS / "work" / "reports" / "modelio" / "probe-probe-20260911T153110Z-75135037.json").read_text(encoding="utf-8")
)

old = {p["name"]: p for p in OLD_RAW["parameters"]}
new = {p["name"]: p for p in NEW_RAW["parameters"]}

common = sorted(set(old) & set(new))
print(f"旧 {len(old)} 个参数，新 {len(new)} 个参数，公共 {len(common)} 个")
print(f"仅旧有: {sorted(set(old) - set(new))}")
print(f"仅新有: {sorted(set(new) - set(old))}\n")

print("== 运行态表达式对照：旧 probe_expression（MPh 读回） vs 新 expression（COM SOL 存储）==")
both = same = 0
diffs = []
incomparable = []
for name in common:
    oe = str(old[name].get("probe_expression") or "").strip()
    ne = str(new[name].get("expression") or "").strip()
    if oe and ne:
        both += 1
        if oe == ne:
            same += 1
        else:
            diffs.append((name, oe, ne))
    else:
        incomparable.append((name, oe or "(空)", ne or "(空)"))
print(f"可比 {both} / {len(common)}；一致 {same}；不同 {len(diffs)}；不可比 {len(incomparable)}")
for name, oe, ne in diffs:
    print(f"  差异 {name:12s} 旧={oe!r:22s} 新={ne!r}")
if incomparable:
    print("  不可比明细（一侧为空）：")
    for name, oe, ne in incomparable:
        print(f"    {name:12s} 旧={oe[:26]:28s} 新={ne[:26]}")

print("\n== .m 侧最终表达式 vs 新运行态表达式 ==")
both2 = same2 = 0
diffs2 = []
for name in common:
    oe = str(old[name].get("m_last_expression") or "").strip()
    ne = str(new[name].get("expression") or "").strip()
    if oe and ne:
        both2 += 1
        if oe == ne:
            same2 += 1
        else:
            diffs2.append((name, oe, ne))
print(f"可比 {both2} / {len(common)}；一致 {same2}；不同 {len(diffs2)}")
for name, oe, ne in diffs2:
    print(f"  差异 {name:12s} .m={oe!r:22s} 新运行态={ne!r}")

print("\n== 旧案例自带的交叉校验差异（.m ↔ 运行态）=")
for item in OLD_RAW.get("cross_check_differences") or []:
    print(f"  {json.dumps(item, ensure_ascii=False)[:200]}")
