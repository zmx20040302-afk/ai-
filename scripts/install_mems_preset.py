"""安装/更新 DSH「MEMS 模式」工作模式（agent preset）与 MCP 工具条目。

**为什么必须动态生成，而不能直接拷贝 `dsh-config/agent-presets-mems/`**（实测 2026-09-11）：
    随包发布的那份预设出自**旧一代 DSH**——persona 用 ``text:`` 键，而本机
    ``@deepseek-ai/dsh-persona`` 的 schema 只接受 ``prefix``（必填）+ ``suffix`` /
    ``complete`` / ``includeRuntimeContext``；它还缺本机 standard 预设里的 ``command-goal`` 条目。
    直接拷贝会**挂载失败**，症状是「模式选择器里能选到，选完立刻跳回原模式」。
    因此本脚本以**本机版本**的 ``presets/standard/agent.cordis.yml`` 为基底做文本级改写。

做三件事：
    ① 以本机 standard 预设为基底，把 persona 换成 MEMS 人格（schema 对齐的 ``prefix`` 键）；
    ② 写 ``preset.yml`` 元数据；③ 把 MCP 条目并入 profile 补丁层（**不在 preset 里挂 MCP**，
       否则 ``@deepseek-ai/dsh-mcp-client`` 的 ``serverName`` 重复会让预设 recompose 失败）。

落盘位置（实测）：``$DSH_HOME/.agent-presets/<id>/``，必须同时含 ``agent.cordis.yml`` 与 ``preset.yml``。

用法：
    python scripts\\install_mems_preset.py                 # 默认 dry-run：只生成到 work/dsh-install 并校验
    python scripts\\install_mems_preset.py --install        # 真正写入 ~/.dsh（含 MCP 补丁，先备份）
    python scripts\\install_mems_preset.py --install --no-mcp
    python scripts\\install_mems_preset.py --donor <agent.cordis.yml 路径>
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
DSH_HOME = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
PRESET_ID = "mems"
PKG = "@deepseek-ai/dsh-agent-presets"
REL_DONOR = Path("presets") / "standard" / "agent.cordis.yml"
PATCH_REL = Path("profiles") / "web" / "cordis.patch.yml"

PERSONA_LINES = (
    "You are the MEMS Harness platform engineer, powered by the {{model}} model.",
    "Your workspace is {{cwd}}; the platform repo is {repo}.",
    "You drive COMSOL solving, the provenance database, the autonomous optimization",
    "loop, analytic data generation and POD field surrogates through mcp__mems__* tools.",
    "",
    "Non-negotiable rules (the platform's red lines):",
    "1. No number without evidence: every value must trace to a run_id, a literature",
    "   page with a verbatim quote, an experiment, or a human feedback record.",
    "2. Physics beats AI metrics: a solution that violates conservation, boundary",
    "   conditions or symmetry is void even if it fits the data well.",
    "3. Never guess a .mph model's internals; if it cannot be read, say so plainly.",
    "4. Never mix sources: simulation / analytic / literature / experiment /",
    "   human_feedback / ai_solver stay separate, each with its own weight.",
    "5. Long solves are submit-then-poll (sim_submit -> sim_status); never block a",
    "   single call on a multi-minute solve. Solving is single-instance serial.",
    "6. Out-of-scope means refuse and fall back to COMSOL; AI solutions must carry an",
    "   error bound and a scope verdict.",
    "Answer in Chinese unless asked otherwise, and state uncertainty explicitly.",
    "",
    "Deterministic layers — call these instead of improvising (all offline, no COMSOL):",
    "* A5 sweep analysis (per-metric rankings + Pareto, NO composite score):",
    "  mcp__mems__sweep_analysis, or `python scripts/run_sweep_analysis.py`.",
    "* A9 report gate (every number needs a trace id; no 'verified' wording unless a",
    "  gate that is BOUND to this report passed): mcp__mems__make_report,",
    "  or `python scripts/run_report_augment.py`.",
    "* A8 freeze gate (fail-closed byte/evidence verdict): mcp__mems__freeze_gate,",
    "  or `python scripts/verify_and_freeze.py`.",
    "* 9 role contracts live in agents/<id>-<slug>/AGENT.md. Point-name one with",
    "  mcp__mems__role_list / mcp__mems__role_payload, then inject the built payload",
    "  VERBATIM as the subagent prompt; the append-only spawn ledger is",
    "  work/role-spawns/spawn_ledger.jsonl. Do not hand-copy a contract from memory.",
    "Code verdicts outrank any prose: never restate inconclusive/None as passing,",
    "never raise a model's state, and never edit files under ~/.dsh or agents/ by hand.",
)

PRESET_DESCRIPTION = (
    "MEMS/PMUT 仿真自动化平台：COMSOL 求解、溯源数据、自主寻优、扫描分析与选点(A5)、"
    "可溯源报告门禁(A9)、冻结门禁(A8)、9 个子智能体角色点名（经 mcp__mems__* 工具）。"
)


def render_persona(repo: str) -> list[str]:
    """把 ``PERSONA_LINES`` 渲染成最终人格行：**只替换 ``{repo}``，绝不动 DSH 占位符**。

    必须用 ``str.replace`` 而**不是** ``str.format``：``format`` 按花括号转义语义会把
    ``{{cwd}}`` 折叠成字面量 ``{cwd}``，从而毁掉 DSH 的模板占位符。

    2026-09-22 实测踩坑：旧实现（L163 ``ln.format(repo=repo)``）只对**含 ``{repo}`` 的行**
    做 format，于是同一段人格里 ``{{model}}``（所在行不含 ``{repo}``，未 format）能正常解析成
    模型名，而 ``{{cwd}}``（与 ``{repo}`` 同行）被折叠成 ``{cwd}`` 后原样留在系统提示里 ——
    "同一句话里一个占位符活了、一个死了"正是该缺陷的判据。
    """
    return [ln.replace("{repo}", repo) for ln in PERSONA_LINES]


def _js_constructor(loader, node):  # pragma: no cover - 仅用于校验
    """让 PyYAML 认 ``!!js`` 标签（DSH 的 JS 表达式），只影响校验。"""
    import yaml

    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


def _yaml():
    import yaml

    yaml.SafeLoader.add_constructor("tag:yaml.org,2002:js", _js_constructor)
    return yaml


def find_donor(explicit: str | None = None) -> Path:
    """定位本机 DSH 自带的 standard 预设（版本对齐是关键）。"""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_pkg = os.environ.get("DSH_AGENT_PRESETS_PKG")
    if env_pkg:
        candidates.append(Path(env_pkg) / REL_DONOR)
    candidates += [
        DSH_HOME / "profiles" / "web" / "node_modules" / PKG / REL_DONOR,
        DSH_HOME / "profiles" / "node_modules" / PKG / REL_DONOR,
    ]
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        candidates += sorted(
            Path(local_appdata).glob(f"npm-cache/_npx/*/node_modules/{PKG}/{REL_DONOR}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidates.append(Path(appdata) / "npm" / "node_modules" / PKG / REL_DONOR)
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "找不到本机 DSH 自带的 standard 预设。请用 --donor 显式指定 "
        f"（形如 .../node_modules/{PKG}/{REL_DONOR}），或设置 DSH_AGENT_PRESETS_PKG。"
    )


def build_composition(donor: Path, repo: str) -> tuple[str, dict]:
    """以 donor 为基底改写 persona；返回 (内容, 校验信息)。"""
    lines = donor.read_text(encoding="utf-8").splitlines(keepends=True)
    try:
        start = next(i for i, ln in enumerate(lines) if ln.rstrip("\n") == "- id: persona")
    except StopIteration as exc:
        raise ValueError(f"基底文件里找不到 persona 条目，拒绝盲目改写：{donor}") from exc
    end = next(
        (i for i, ln in enumerate(lines[start + 1 :], start + 1) if ln.startswith("- id: ")),
        len(lines),
    )
    try:
        cfg = next(
            i for i, ln in enumerate(lines[start:end], start) if ln.rstrip("\n") == "  config:"
        )
    except StopIteration as exc:
        raise ValueError("persona 条目里找不到 config 块，拒绝盲目改写") from exc

    old_block = "".join(lines[cfg:end])
    if "prefix:" not in old_block:
        raise ValueError(
            "基底 persona 里没有 `prefix:` 键——说明 DSH 版本与预期不符"
            "（旧版本用 `text:`），请人工确认后再装。"
        )

    block = [
        "  config:\n",
        "    # MEMS 人格（由 scripts/install_mems_preset.py 生成）\n",
        "    # 用本机 schema 要求的 prefix 键；用 |- 保留红线清单的换行结构（>- 会折成一整段）\n",
        "    prefix: |-\n",
    ]
    # 注意：用 render_persona（str.replace）而不是 ln.format(repo=repo)：
    # format 会把 {{cwd}} 折叠成 {cwd}，毁掉 DSH 的占位符（见 render_persona 文档串）。
    block += [f"      {ln}\n" if ln else "\n" for ln in render_persona(repo)]
    block.append("\n")

    text = "".join(lines[:cfg] + block + lines[end:])
    info = {
        "n_entries": len(re.findall(r"^- id:", text, flags=re.MULTILINE)),
        "has_persona": "MEMS Harness platform engineer" in text,
        "has_command_goal": bool(re.search(r"^- id: command-goal$", text, flags=re.MULTILINE)),
        "has_old_machine_path": ("D:\\" in text) or ("18161" in text),
    }
    return text, info


def _plugin_roots(donor: Path) -> list[Path]:
    """收集可能存放 DSH 插件的 node_modules 根目录。

    注意：``~/.dsh/profiles/node_modules/@deepseek-ai/*`` 通常是指向 npx 缓存的 junction，
    所以只要路径存在即可（``Path.exists()`` 会跟随 junction）。
    """
    roots = [p for p in donor.parents if p.name == "node_modules"]
    roots += [
        DSH_HOME / "profiles" / "web" / "node_modules",
        DSH_HOME / "profiles" / "node_modules",
    ]
    return list(dict.fromkeys(roots))


def validate_composition(text: str, donor: Path) -> dict:
    yaml = _yaml()
    data = yaml.safe_load(text)
    assert isinstance(data, list), "组合文件顶层必须是数组"
    persona = next(r for r in data if isinstance(r, dict) and r.get("id") == "persona")
    cfg = persona["config"]
    assert "prefix" in cfg, "persona 必须有 prefix 键（本机 schema 要求）"
    assert "text" not in cfg, "本机 schema 没有 text 键"

    names = [r.get("name") for r in data if isinstance(r, dict) and r.get("name")]
    roots = _plugin_roots(donor)
    missing = []
    for name in names:
        if not isinstance(name, str) or not name.startswith("@deepseek-ai/"):
            continue
        pkg = name.split("/")[1]
        if not any((root / "@deepseek-ai" / pkg).exists() for root in roots):
            missing.append(name)
    return {
        "top_level_entries": len(data),
        "referenced_plugins": len(names),
        "missing_plugins": missing,
        "plugin_roots": [str(r) for r in roots],
    }


def mcp_block(python_exe: str, repo: str, docs_hint: str) -> str:
    return (
        "\n# ---- MEMS Harness：把平台工具以 mcp__mems__* 暴露给智能体 ----\n"
        "# 新增条目必须包在 `insert:` 里（不带 id 的 insert 插到根列表；\n"
        "# 不带 insert 的条目会被当成对既有 id 的覆盖，找不到 id 就报 patch 错误）。\n"
        "# 不要在两个实例里用同一个 serverName，否则后挂载的实例会失败。\n"
        f"# 说明见 {docs_hint}\n"
        "- insert:\n"
        "    - id: mcp-mems-harness\n"
        "      name: '@deepseek-ai/dsh-mcp-client'\n"
        "      config:\n"
        "        serverName: mems\n"
        "        transport: stdio\n"
        f"        command: '{python_exe}'\n"
        "        args: ['-m', 'memsharness.mcp_server']\n"
        f"        cwd: '{repo}'\n"
        "        toolCallTimeoutMs: 60000\n"
        "        failOnStartupError: false\n"
        "        reconnect:\n"
        "          enabled: true\n"
    )


def merge_patch(patch_path: Path, block: str, *, install: bool) -> dict:
    """把 MCP 条目并入 profile 补丁层（保留既有注释/条目，先备份）。"""
    existing = patch_path.read_text(encoding="utf-8") if patch_path.is_file() else ""
    if "mcp-mems-harness" in existing:
        return {"action": "already_present", "path": str(patch_path)}
    stripped = existing.rstrip()
    if stripped.endswith("[]"):
        merged = stripped[: -len("[]")] + block.lstrip("\n")
    else:
        merged = stripped + "\n" + block
    result = {"action": "append", "path": str(patch_path), "content": merged}
    if not install:
        return result
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    if patch_path.is_file():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = patch_path.with_name(patch_path.name + f".bak-{stamp}")
        shutil.copy2(patch_path, backup)
        result["backup"] = str(backup)
    patch_path.write_text(merged, encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="安装 DSH「MEMS 模式」agent preset（默认 dry-run）")
    ap.add_argument("--install", action="store_true", help="真正写入 ~/.dsh（默认只暂存到 work/dsh-install）")
    ap.add_argument("--dry-run", action="store_true", help="显式 dry-run（默认行为）")
    ap.add_argument("--no-mcp", action="store_true", help="只装预设，不动 profile 补丁层")
    ap.add_argument("--force", action="store_true", help="已存在时也重写")
    ap.add_argument("--donor", default=None, help="基底 standard 预设路径")
    ap.add_argument("--repo", default=str(_REPO_ROOT), help="写进人格与 MCP 的仓库路径")
    ap.add_argument("--python", dest="python_exe", default=None, help="MCP 使用的解释器路径")
    args = ap.parse_args(argv)

    install = args.install and not args.dry_run
    python_exe = args.python_exe or str(Path(args.repo) / "work" / ".venv" / "Scripts" / "python.exe")
    repo = args.repo

    donor = find_donor(args.donor)
    composition, info = build_composition(donor, repo)
    checks = validate_composition(composition, donor)

    preset_dir = DSH_HOME / ".agent-presets" / PRESET_ID
    staging = _REPO_ROOT / "work" / "dsh-install" / "agent-presets-mems"
    patch_plan = (
        {"action": "skipped(no-mcp)"}
        if args.no_mcp
        else merge_patch(DSH_HOME / PATCH_REL, mcp_block(python_exe, repo, "docs/dsh_mcp_registration.md"), install=install)
    )

    print("=" * 72)
    print(f"DSH MEMS 模式安装（{'写入 ~/.dsh' if install else 'dry-run：只暂存'}）")
    print("=" * 72)
    print(f"  DSH_HOME      : {DSH_HOME}")
    print(f"  基底 standard : {donor}")
    print(f"  顶层条目      : {info['n_entries']}（含 command-goal: {info['has_command_goal']}）")
    print(f"  persona 已换  : {info['has_persona']}｜旧机路径残留: {info['has_old_machine_path']}")
    print(f"  引用插件      : {checks['referenced_plugins']} 个｜本机缺失: {checks['missing_plugins'] or '无'}")
    print(f"  MCP 补丁      : {patch_plan['action']}")
    print(f"  MCP 解释器    : {python_exe}（存在: {Path(python_exe).is_file()}）")
    print(f"  MCP cwd       : {repo}（存在: {Path(repo).is_dir()}）")

    if checks["missing_plugins"]:
        print("有插件在本机不存在，挂载会失败——拒绝安装", file=sys.stderr)
        return 3
    if info["has_old_machine_path"]:
        print("生成内容里仍含旧机路径（D:\\ 或 18161），拒绝安装", file=sys.stderr)
        return 3

    preset_meta = f"name: MEMS 模式\ndescription: {PRESET_DESCRIPTION}\norder: 3\n"

    if not install:
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "agent.cordis.yml").write_text(composition, encoding="utf-8")
        (staging / "preset.yml").write_text(preset_meta, encoding="utf-8")
        if "content" in patch_plan:
            (_REPO_ROOT / "work" / "dsh-install" / "cordis.patch.yml").write_text(
                patch_plan["content"], encoding="utf-8"
            )
        print(f"\n[dry-run] 已暂存到 {staging.parent}；加 --install 才会写入 {preset_dir}")
        return 0

    if preset_dir.exists() and not args.force:
        if (preset_dir / "agent.cordis.yml").is_file():
            print(f"\n预设已存在：{preset_dir}；要覆盖请加 --force（不改动任何文件）", file=sys.stderr)
            return 2
    preset_dir.mkdir(parents=True, exist_ok=True)
    (preset_dir / "agent.cordis.yml").write_text(composition, encoding="utf-8")
    (preset_dir / "preset.yml").write_text(preset_meta, encoding="utf-8")
    print(f"\n✅ 已写入：{preset_dir / 'agent.cordis.yml'}")
    print(f"✅ 已写入：{preset_dir / 'preset.yml'}")
    if patch_plan.get("backup"):
        print(f"✅ 原补丁已备份：{patch_plan['backup']}")
    print("\n生效方式：**重启 DSH 并新建会话**（预设与 MCP 都在启动时装载，且 preset 在会话创建时锁定）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
