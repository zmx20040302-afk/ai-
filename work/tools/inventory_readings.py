"""盘点「第一次阅读」的成果：哪些 probe 读了哪个模型；旧案例与新目标器件的参数对照。"""

from __future__ import annotations

import json
from pathlib import Path

WS = Path(r"C:\Users\zmx\Desktop\memsharness")
PROBE_DIR = WS / "work" / "reports" / "modelio"
OLD = WS / "work" / "models" / "bGEtask2-20260911T064304Z"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


print("== 每个 probe JSON 读的是哪个模型 ==")
rows = []
for path in sorted(PROBE_DIR.glob("probe-*.json")):
    data = load(path)
    src = (data.get("source") or {}).get("path")
    rows.append((path.name, data.get("ok"), len(data.get("parameters") or []), src, data.get("comsol_version")))
for name, ok, nparam, src, ver in rows:
    print(f"  {name[:44]:46s} ok={str(ok):5s} nparam={nparam:3d} {src}")

by_model: dict[str, list] = {}
for name, ok, nparam, src, ver in rows:
    by_model.setdefault(str(src), []).append((name, ok, nparam))
print("\n== 按模型归并 ==")
for src, items in by_model.items():
    oks = sum(1 for _, ok, _ in items if ok)
    print(f"  {src}\n      probe {len(items)} 次（成功 {oks}），最新一次 nparam={items[-1][2]}")

print("\n== 旧案例产物结构 ==")
for fname in ("params.json", "probe_mph.json", "m_parsed.json"):
    path = OLD / fname
    if not path.is_file():
        continue
    data = load(path)
    if isinstance(data, dict):
        print(f"  {fname}: dict keys={list(data)[:10]}")
        for key, value in list(data.items())[:2]:
            extra = f"len={len(value)}" if isinstance(value, (list, dict)) else repr(value)[:60]
            print(f"      {key}: {type(value).__name__} {extra}")
    elif isinstance(data, list):
        print(f"  {fname}: list len={len(data)}")
        if data:
            print(f"      首元素: {json.dumps(data[0], ensure_ascii=False)[:220]}")

# ---- 参数对照：旧案例 vs 目标器件 ----
target = load(PROBE_DIR / "probe-probe-20260911T153110Z-75135037.json")
tparams = {p["name"]: p for p in target.get("parameters") or []}

old_params_raw = load(OLD / "params.json")
old: dict[str, dict] = {}
if isinstance(old_params_raw, dict):
    container = old_params_raw.get("parameters", old_params_raw)
elif isinstance(old_params_raw, list):
    container = old_params_raw
else:
    container = {}
if isinstance(container, dict):
    for name, value in container.items():
        old[name] = value if isinstance(value, dict) else {"expression": value}
elif isinstance(container, list):
    for item in container:
        if isinstance(item, dict) and "name" in item:
            old[item["name"]] = item

print(f"\n== 参数对照 ==\n  旧案例(bGEtask2) 参数 {len(old)} 个；目标器件(b_GE_task3_2-new) 参数 {len(tparams)} 个")
only_old = sorted(set(old) - set(tparams))
only_new = sorted(set(tparams) - set(old))
print(f"  仅旧案例有 ({len(only_old)}): {only_old}")
print(f"  仅目标器件有 ({len(only_new)}): {only_new}")

diff = []
for name in sorted(set(old) & set(tparams)):
    oe = str(old[name].get("expression") or old[name].get("value") or "")
    te = str(tparams[name].get("expression") or "")
    if oe.strip() and te.strip() and oe.strip() != te.strip():
        diff.append((name, oe.strip(), te.strip()))
print(f"  同名但表达式不同 ({len(diff)}):")
for name, oe, te in diff:
    print(f"      {name:12s} 旧: {oe:24s} 新: {te}")
