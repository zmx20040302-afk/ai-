"""回读校验已安装的 MEMS 预设与 profile 补丁（只读，不修改任何东西）。"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def _js_constructor(loader: yaml.Loader, node: yaml.Node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


yaml.SafeLoader.add_constructor("tag:yaml.org,2002:js", _js_constructor)

DSH = Path(r"C:\Users\zmx\.dsh")
PRESET = DSH / ".agent-presets" / "mems"
PATCH = DSH / "profiles" / "web" / "cordis.patch.yml"

ok = True

print("== 预设目录 ==")
for f in sorted(PRESET.iterdir()):
    print(f"  {f.name:20s} {f.stat().st_size} B")

meta = yaml.safe_load((PRESET / "preset.yml").read_text(encoding="utf-8"))
print(f"\n== preset.yml ==\n  name={meta.get('name')!r}  order={meta.get('order')}")

doc = yaml.safe_load((PRESET / "agent.cordis.yml").read_text(encoding="utf-8"))
ids = [r.get("id") for r in doc if isinstance(r, dict)]
persona = next(r for r in doc if isinstance(r, dict) and r.get("id") == "persona")
cfg = persona["config"]
print("\n== agent.cordis.yml ==")
print(f"  条目数            : {len(doc)}")
print(f"  persona 配置键    : {sorted(cfg)}")
print(f"  含 command-goal   : {'command-goal' in ids}")
print(f"  prefix 含 {{model}}: {'{{model}}' in cfg.get('prefix', '')}")
print(f"  prefix 含 {{cwd}}  : {'{{cwd}}' in cfg.get('prefix', '')}")
print(f"  prefix 仓库路径   : {r'C:\Users\zmx\Desktop\memsharness' in cfg.get('prefix', '')}")
print(f"  旧机路径残留      : {(chr(68) + ':') in cfg.get('prefix', '') or '18161' in cfg.get('prefix', '')}（应为 False）")
if "prefix" not in cfg or "text" in cfg:
    print("  [FAIL] persona schema 不符")
    ok = False
if "command-goal" not in ids:
    print("  [FAIL] 缺 command-goal（与标准预设不一致）")
    ok = False

patch = yaml.safe_load(PATCH.read_text(encoding="utf-8"))
print("\n== cordis.patch.yml ==")
print(f"  顶层类型          : {type(patch).__name__}，条目数 {len(patch)}")
for entry in patch:
    if "insert" in entry:
        for row in entry["insert"]:
            c = row["config"]
            print(f"  insert {row['id']}  serverName={c['serverName']}  transport={c['transport']}")
            print(f"         command = {c['command']}")
            print(f"         cwd     = {c['cwd']}")
            print(f"         解释器存在 = {Path(c['command']).is_file()}  cwd 存在 = {Path(c['cwd']).is_dir()}")
            if not Path(c["command"]).is_file():
                ok = False
    else:
        print(f"  [警告] 存在非 insert 条目：{entry.get('id')}")

bak = sorted(DSH.glob("profiles/web/cordis.patch.yml.bak-*"))
print(f"\n== 备份 ==\n  {[b.name for b in bak]}")

print("\n结论：" + ("全部校验通过" if ok else "存在失败项，见上"))
sys.exit(0 if ok else 1)
