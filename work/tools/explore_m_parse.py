"""查看 parse_matlab_export 对用户导出的 .m 的解析结构（只读探路，不落任何结论）。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
sys.path.insert(0, str(REPO / "src"))

from memsharness import modelio as mio  # noqa: E402

M = Path(r"C:\Users\zmx\Desktop\b_GE_task3_2new.m")
spec = mio.parse_matlab_export(M)

print(f"parsed={spec.get('parsed')} reason={spec.get('reason')}")
print(f"model_tag={spec.get('model_tag')} sha256={spec.get('sha256')}")
print(f"顶层键: {sorted(spec)}")
for key in ("parameters", "geometry", "materials", "physics", "selections", "study", "solvers"):
    value = spec.get(key)
    print(f"  {key}: {type(value).__name__} len={len(value) if hasattr(value, '__len__') else '?'}")

print("\n== study 结构 ==")
for s in spec.get("study") or []:
    print(f"  [{s.get('tag')}] {s.get('label')}")
    for step in s.get("steps") or []:
        print(f"    step {step.get('tag')} type={step.get('type')} keys={sorted(step)}")
        props = step.get("properties")
        if isinstance(props, dict):
            for name, value in list(props.items())[:12]:
                print(f"        {name} = {value}")
        elif isinstance(props, list):
            for item in props[:12]:
                print(f"        {json.dumps(item, ensure_ascii=False)[:140]}")

print("\n== selections（前 8 条）==")
for sel in (spec.get("selections") or [])[:8]:
    print(f"  {json.dumps(sel, ensure_ascii=False)[:160]}")

print("\n== physics（前 3 个接口）==")
for p in (spec.get("physics") or [])[:3]:
    print(f"  [{p.get('interface_tag')}] {p.get('interface_type')} features={len(p.get('features') or [])}")
    for f in (p.get("features") or [])[:4]:
        print(f"      {f.get('tag')} :: {f.get('type')} props={len(f.get('properties') or [])}")

print("\n== enum_validation ==")
ev = spec.get("enum_validation") or {}
print(f"  available={ev.get('available')} checked={ev.get('checked')} n_assignments={ev.get('n_assignments')}")
print(f"  keys={sorted(ev)}")
print(f"  violations/errors 字段: {json.dumps({k: v for k, v in ev.items() if k not in ('assignments','results')}, ensure_ascii=False)[:400]}")

print("\n== unknown_assignments ==")
ua = spec.get("unknown_assignments") or []
print(f"  数量={len(ua)}；前 3 条：{json.dumps(ua[:3], ensure_ascii=False)[:300]}")

print("\n== 参数在 .m 里的设置历史（自算，用于复刻旧机的 m_lines/m_occurrences）==")
text = M.read_text(encoding="utf-8", errors="replace")
pattern = re.compile(r"model\.param\.set\(\s*'([^']+)'\s*,\s*'([^']*)'")
hist: dict[str, list[tuple[int, str]]] = {}
for lineno, line in enumerate(text.splitlines(), 1):
    for name, expr in pattern.findall(line):
        hist.setdefault(name, []).append((lineno, expr))
print(f"  .m 里 param.set 次数={sum(len(v) for v in hist.values())}，涉及参数 {len(hist)} 个")
multi = {k: v for k, v in hist.items() if len(v) > 1}
print(f"  被设置多次的参数 {len(multi)} 个：")
for name, items in sorted(multi.items()):
    distinct = sorted({e for _, e in items})
    print(f"    {name:12s} {len(items)} 次，行号 {[ln for ln, _ in items]}，不同表达式 {distinct}")
