"""构建本机可用的「MEMS 模式」DSH 预设与 profile 补丁（只写工作区，不碰 ~/.dsh）。

为什么需要这个脚本而不是直接拷贝 ``dsh-config/agent-presets-mems/``：
    迁移包内那份预设出自**旧一代 DSH**：persona 用 ``text:`` 键，而本机
    ``@deepseek-ai/dsh-persona`` 的 schema 只要 ``prefix``（必填）/``suffix``/
    ``complete``/``includeRuntimeContext``，没有 ``text``；它还缺了本机 standard
    预设里的 ``command-goal`` 条目。直接拷贝会挂载失败（症状：选择器能选到，
    选完跳回原模式）。
    因此本脚本以**本机版本**的 ``presets/standard/agent.cordis.yml`` 为 donor，
    只替换 persona 的 config 块为 MEMS 人格，并修正写死的旧机路径。

产出（工作区暂存，供随后授权拷贝到 %USERPROFILE%\\.dsh）：
    work/dsh-install/agent-presets-mems/agent.cordis.yml
    work/dsh-install/agent-presets-mems/preset.yml
    work/dsh-install/cordis.patch.yml
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def _js_constructor(loader: yaml.Loader, node: yaml.Node):
    """让 PyYAML 认 DSH 的 ``!!js`` 标签（把表达式原样当字符串/结构读出来）。

    donor 预设里有 ``disabled: !!js process.platform === 'win32'`` 这类行，
    不注册构造器就无法 safe_load 校验。
    """
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


yaml.SafeLoader.add_constructor("tag:yaml.org,2002:js", _js_constructor)


DSH_PKG = Path(
    r"C:\Users\zmx\AppData\Local\npm-cache\_npx\1e7f6d9597241db0"
    r"\node_modules\@deepseek-ai\dsh-agent-presets"
)
DONOR = DSH_PKG / "presets" / "standard" / "agent.cordis.yml"
SHIPPED_PRESET_DIR = Path(
    r"C:\Users\zmx\Desktop\memsharness\dsh-config\agent-presets-mems"
)

REPO = r"C:\Users\zmx\Desktop\memsharness"
VENV_PY = rf"{REPO}\work\.venv\Scripts\python.exe"
OUT = Path(r"C:\Users\zmx\Desktop\memsharness\work\dsh-install")

PERSONA_LINES = [
    "You are the MEMS Harness platform engineer, powered by the {{model}} model.",
    f"Your workspace is {{{{cwd}}}}; the platform repo is {REPO}.",
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
]


def build_preset() -> str:
    lines = DONOR.read_text(encoding="utf-8").splitlines(keepends=True)

    start = next(i for i, ln in enumerate(lines) if ln.rstrip("\n") == "- id: persona")
    end = next(
        i for i, ln in enumerate(lines[start + 1 :], start + 1) if ln.startswith("- id: ")
    )
    cfg = next(
        i for i, ln in enumerate(lines[start:end], start) if ln.rstrip("\n") == "  config:"
    )

    block = ["  config:\n", "    # MEMS 人格：用本机 schema 要求的 prefix 键（无 text 键）\n",
             "    # 用 |- 而非 >-：保留红线清单的换行结构，>- 会把它折成一整段\n",
             "    prefix: |-\n"]
    block += [f"      {ln}\n" if ln else "\n" for ln in PERSONA_LINES]
    block.append("\n")

    out = "".join(lines[:cfg] + block + lines[end:])
    return out


def build_patch() -> str:
    head = (
        "# Your patch layer for this dsh profile, applied after every bundle layer:\n"
        "# a top-level YAML array of loader patch entries (id-targeted config\n"
        "# overrides, disables, and insert lists; `!!js` expressions allowed).\n"
        "\n"
        "# ---- MEMS Harness：把平台工具以 mcp__mems__* 暴露给智能体 ----\n"
        "# 新增条目必须包在 `insert:` 里（不带 id 的 insert = 插入到根条目列表；\n"
        "# 不带 insert 的条目会被当作对既有 id 的覆盖，找不到 id 就会报 patch 错误）。\n"
        "# 注意：MCP 的 serverName 不得与其它实例重复，否则后来的实例挂载失败。\n"
        "# 本条目按本机路径生成（旧机路径 D:\\桌面\\memsharness 在本机不存在）。\n"
        "# 未包含「局域网访问(0.0.0.0)」条目——按用户选择不加。\n"
    )
    entry = (
        "- insert:\n"
        "    - id: mcp-mems-harness\n"
        "      name: '@deepseek-ai/dsh-mcp-client'\n"
        "      config:\n"
        "        serverName: mems\n"
        "        transport: stdio\n"
        f"        command: '{VENV_PY}'\n"
        "        args: ['-m', 'memsharness.mcp_server']\n"
        f"        cwd: '{REPO}'\n"
        "        toolCallTimeoutMs: 60000\n"
        "        failOnStartupError: false\n"
        "        reconnect:\n"
        "          enabled: true\n"
    )
    return head + entry


def main() -> int:
    if not DONOR.is_file():
        print(f"donor 不存在：{DONOR}", file=sys.stderr)
        return 2

    preset_text = build_preset()
    patch_text = build_patch()

    preset_dir = OUT / "agent-presets-mems"
    preset_dir.mkdir(parents=True, exist_ok=True)
    (preset_dir / "agent.cordis.yml").write_text(preset_text, encoding="utf-8")
    (OUT / "cordis.patch.yml").write_text(patch_text, encoding="utf-8")

    # preset.yml 沿用迁移包的 name/description，只保证 order 存在
    shipped = yaml.safe_load((SHIPPED_PRESET_DIR / "preset.yml").read_text(encoding="utf-8"))
    meta = {
        "name": shipped.get("name", "MEMS 模式"),
        "description": shipped.get("description", ""),
        "order": shipped.get("order", 3),
    }
    (preset_dir / "preset.yml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    # ---- 校验 ----
    print("== 校验 ==")
    doc = yaml.safe_load(preset_text)
    persona = next(r for r in doc if isinstance(r, dict) and r.get("id") == "persona")
    cfg = persona["config"]
    print(f"  preset 条目数        : {len(doc)}")
    print(f"  persona 配置键       : {sorted(cfg)}")
    assert "prefix" in cfg, "persona 必须有 prefix"
    assert "text" not in cfg, "本机 schema 无 text 键"
    assert "{{model}}" in cfg["prefix"] and "{{cwd}}" in cfg["prefix"]
    assert REPO in cfg["prefix"], "人格里的仓库路径未更新为本机路径"
    ids = [r.get("id") for r in doc if isinstance(r, dict)]
    print(f"  含 command-goal     : {'command-goal' in ids}（应与本机 standard 一致）")
    print(f"  agent.cordis.yml    : {len(preset_text)} 字符 / {preset_text.count(chr(10))} 行")

    patch = yaml.safe_load(patch_text)
    assert isinstance(patch, list) and len(patch) == 1 and "insert" in patch[0]
    entry = patch[0]["insert"][0]
    print(f"  patch 条目          : {entry['id']} / serverName={entry['config']['serverName']}")
    print(f"  MCP command         : {entry['config']['command']}")
    print(f"  MCP cwd             : {entry['config']['cwd']}")
    assert Path(entry["config"]["command"]).is_file(), "MCP 解释器路径不存在"
    assert Path(entry["config"]["cwd"]).is_dir(), "MCP cwd 不存在"
    print(f"  MCP 解释器存在      : True")
    print("\n== 产出 ==")
    for p in sorted(OUT.rglob("*")):
        if p.is_file():
            print(f"  {p}  ({p.stat().st_size} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
