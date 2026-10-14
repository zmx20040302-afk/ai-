"""回读校验已安装的 DSH「MEMS 模式」预设与 MCP 补丁条目（**只读**，不修改任何东西）。

用途：`scripts/install_mems_preset.py` 装完后跑一次，确认
① 预设目录存在且含 `agent.cordis.yml` + `preset.yml`；
② persona 用的是本机 schema 要求的 `prefix` 键（不是旧版的 `text`）；
③ 与本机 standard 预设的结构一致（含 `command-goal` 条目）；
④ 人格里的仓库路径已是本机路径、无旧机残留；
⑤ profile 补丁层里的 MCP 条目指向的解释器与 cwd 都真实存在。

用法：
    python scripts\\verify_mems_install.py                     # 校验已安装到 ~/.dsh 的预设
    python scripts\\verify_mems_install.py --dsh-home "D:\\some\\dsh"
    python scripts\\verify_mems_install.py --staged            # 装之前先验 install_mems_preset.py 的 dry-run 产物

⚠️ 为什么需要 ``--staged``（2026-09-22 实测教训）：persona 的渲染缺陷（`{{cwd}}` 被 str.format
折叠成字面量）**只会在产物里现形**，装完再验就得重装一遍才发现。先验产物可以fail-closed 在安装前。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_STAGING = _REPO_ROOT / "work" / "dsh-install" / "agent-presets-mems"


def _js_constructor(loader, node):
    import yaml

    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="校验 DSH MEMS 模式安装（只读）")
    ap.add_argument("--dsh-home", default=os.environ.get("DSH_HOME", str(Path.home() / ".dsh")))
    ap.add_argument("--preset-id", default="mems")
    ap.add_argument("--staged", nargs="?", const=str(_STAGING), default=None,
                    help="校验 install_mems_preset.py 的 dry-run 产物（默认 work/dsh-install/"
                         "agent-presets-mems），而不是 ~/.dsh 下的安装件；装之前先验，能挡住"
                         "只在产物里现形的 persona 渲染缺陷")
    args = ap.parse_args(argv)

    import yaml

    yaml.SafeLoader.add_constructor("tag:yaml.org,2002:js", _js_constructor)

    dsh = Path(args.dsh_home)
    staged = bool(args.staged)
    preset = Path(args.staged) if staged else dsh / ".agent-presets" / args.preset_id
    # --staged 只看预设产物本身：profile 补丁层还没写（merge_patch 在 dry-run 下只预算不落盘）
    patch = None if staged else dsh / "profiles" / "web" / "cordis.patch.yml"
    repo = str(_REPO_ROOT)
    ok = True

    print("== 预设" + ("产物（--staged，尚未安装）" if staged else "目录") + " ==")
    if not preset.is_dir():
        print(f"  [FAIL] 不存在：{preset}")
        return 1
    for f in sorted(preset.iterdir()):
        print(f"  {f.name:20s} {f.stat().st_size} B")

    meta = yaml.safe_load((preset / "preset.yml").read_text(encoding="utf-8"))
    print(f"\n== preset.yml ==\n  name={meta.get('name')!r}  order={meta.get('order')}")

    doc = yaml.safe_load((preset / "agent.cordis.yml").read_text(encoding="utf-8"))
    ids = [r.get("id") for r in doc if isinstance(r, dict)]
    persona = next(r for r in doc if isinstance(r, dict) and r.get("id") == "persona")
    cfg = persona["config"]
    print("\n== agent.cordis.yml ==")
    print(f"  条目数          : {len(doc)}")
    print(f"  persona 配置键  : {sorted(cfg)}")
    print(f"  含 command-goal : {'command-goal' in ids}")
    prefix = cfg.get("prefix", "")
    print(f"  prefix 含 {{model}}: {'{{model}}' in prefix}")
    print(f"  prefix 含 {{cwd}}  : {'{{cwd}}' in prefix}")
    print(f"  prefix 仓库路径 : {repo in prefix}")
    # 这里的针是 `D:\`（源码须写作 "D:\\"）。旧版写成 'D:\\\\'（值 = D: + 两个反斜杠）
    # ⇒ 永远匹配不到真实 Windows 路径，是条**死检查**（2026-09-22 修正）。
    residue = ("18161" in prefix) or ("D:\\" in prefix)
    missing_ph = [p for p in ("{{model}}", "{{cwd}}") if p not in prefix]
    literal_cwd = "{cwd}" in prefix.replace("{{cwd}}", "")
    print(f"  旧机路径残留    : {residue}（应为 False）")
    print(f"  未解析的 {{cwd}} : {literal_cwd}（应为 False）")
    # 关键陷阱（2026-09-22 实测）：渲染时若用 str.format，`{{cwd}}` 会被折叠成字面量
    # `{cwd}` —— DSH 不再注入工作区路径，而同一段文字里的 `{{model}}` 仍正常解析，
    # 于是装出来"看着没问题"。必须要求占位符原样存在，并把裸 `{cwd}` 判为失败。
    if missing_ph or literal_cwd:
        print(f"  [FAIL] persona 占位符不合格：缺 {missing_ph or '无'}；未解析 {literal_cwd}")
        print("         多半是渲染用了 str.format 折叠花括号 → install_mems_preset.render_persona()")
        ok = False
    if residue:
        print("  [FAIL] persona 含旧机路径残留（D:\\ 或 18161）")
        ok = False
    if "prefix" not in cfg or "text" in cfg or repo not in prefix:
        print("  [FAIL] persona schema 或路径不符")
        ok = False
    if "command-goal" not in ids:
        print("  [FAIL] 缺 command-goal（与本机 standard 预设不一致 → 可能来自旧版 DSH）")
        ok = False

    print("\n== cordis.patch.yml ==")
    if patch is None:
        print("  （--staged 模式：只看预设产物，跳过 profile 补丁层）")
        backups: list[Path] = []
    else:
        if not patch.is_file():
            print(f"  [FAIL] 不存在：{patch}")
            return 1
        entries = yaml.safe_load(patch.read_text(encoding="utf-8"))
        print(f"  顶层类型 : {type(entries).__name__}，条目数 {len(entries)}")
        found = False
        for row in entries:
            for child in row.get("insert", []) if isinstance(row, dict) else []:
                if child.get("id") != "mcp-mems-harness":
                    continue
                found = True
                c = child["config"]
                print(f"  insert {child['id']}  serverName={c['serverName']}  transport={c['transport']}")
                print(f"         command = {c['command']}（存在: {Path(c['command']).is_file()}）")
                print(f"         cwd     = {c['cwd']}（存在: {Path(c['cwd']).is_dir()}）")
                if not Path(c["command"]).is_file() or not Path(c["cwd"]).is_dir():
                    ok = False
        if not found:
            print("  [FAIL] 没有 mcp-mems-harness 条目")
            ok = False
        backups = sorted(dsh.glob("profiles/web/cordis.patch.yml.bak-*"))
        print(f"\n== 备份 ==\n  {[b.name for b in backups] or '无'}")

    if staged:
        print("\n结论：" + ("产物校验通过；下一步 python scripts\\install_mems_preset.py --install --force"
                          if ok else "产物存在失败项，**不要安装**，见上"))
        return 0 if ok else 1
    print("\n结论：" + ("全部校验通过；重启 DSH 并新建会话后生效" if ok else "存在失败项，见上"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
