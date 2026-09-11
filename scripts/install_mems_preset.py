"""安装/更新 DSH「MEMS 模式」工作模式（agent preset）。

做法：以随包发布的 **standard** 模式为基底（文本级改写，保留其全部结构与注释），
① 替换 persona 为 MEMS 平台人格与红线；② 注入 MEMS MCP 工具条目；③ 写 preset.yml 元数据。

落盘位置（实测）：``$DSH_HOME/.agent-presets/<id>/``，必须同时含 ``agent.cordis.yml`` 与 ``preset.yml``。

用法：
    C:\\Users\\18161\\memsharness_work\\repo\\work\\.venv\\Scripts\\python.exe scripts\\install_mems_preset.py
    ... --dry-run       # 只打印将要写入的内容
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
DSH_HOME = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
SHIPPED_STANDARD = (
    Path(r"C:\Users\18161\Documents\ChatGPT\deepseek")
    / "node_modules" / "@deepseek-ai" / "dsh" / "config" / "agent-presets" / "standard" / "agent.cordis.yml"
)
PRESET_ID = "mems"

# MCP 服务器启动命令：MCP 服务器本身是纯 Python（不启 JVM），故无需 ASCII 交汇点
PYTHON = r"D:\桌面\memsharness\work\.venv\Scripts\python.exe"
REPO = r"D:\桌面\memsharness"

PERSONA_ANCHOR = "You are a coding agent powered by the {{model}} model."

MEMS_PERSONA = """      You are the MEMS Harness platform engineer, powered by the {{model}} model.
      Your workspace is {{cwd}}; the platform repo is D:\\桌面\\memsharness.
      You drive COMSOL solving, the provenance database, the autonomous optimization
      loop, analytic data generation and POD field surrogates through mcp__mems__* tools.

      Non-negotiable rules (the platform's red lines):
      1. No number without evidence: every value must trace to a run_id, a literature
         page with a verbatim quote, an experiment, or a human feedback record.
      2. Physics beats AI metrics: a solution that violates conservation, boundary
         conditions or symmetry is void even if it fits the data well.
      3. Never guess a .mph model's internals; if it cannot be read, say so plainly.
      4. Never mix sources: simulation / analytic / literature / experiment /
         human_feedback / ai_solver stay separate, each with its own weight.
      5. Long solves are submit-then-poll (sim_submit -> sim_status); never block a
         single call on a multi-minute solve. Solving is single-instance serial.
      6. Out-of-scope means refuse and fall back to COMSOL; AI solutions must carry an
         error bound and a scope verdict.
      Answer in Chinese unless asked otherwise, and state uncertainty explicitly."""

# 注入位置：标准模式的 agent-instructions 条目之后
MCP_BLOCK = """
# ── MEMS 平台工具（本模式的核心）──────────────────────────────────────────────
# 平台能力全部经 MCP 暴露为 mcp__mems__*：环境/设备/队列/数据/寻优/场级降阶。
# 求解类工具只入队（submit 立即返回 run_id），执行由单实例 worker 串行完成。
- id: mcp-mems-harness
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: mems
    transport: stdio
    command: '{python}'
    args: ['-m', 'memsharness.mcp_server']
    cwd: '{repo}'
    toolCallTimeoutMs: 60000
    failOnStartupError: false
    reconnect:
      enabled: true
"""

PRESET_META = """name: MEMS 模式
description: MEMS/PMUT 仿真自动化平台：COMSOL 求解、溯源数据、自主寻优、解析数据工厂与场级降阶模型（经 mcp__mems__* 工具）。
order: 3
"""


def build_composition() -> tuple[str, dict]:
    """返回 (组合文件内容, 校验信息)。文本级改写，保留基底结构与注释。"""
    if not SHIPPED_STANDARD.is_file():
        raise FileNotFoundError(f"找不到基底模式文件：{SHIPPED_STANDARD}")
    text = SHIPPED_STANDARD.read_text(encoding="utf-8")

    if PERSONA_ANCHOR not in text:
        raise ValueError("基底文件里找不到 persona 锚点，拒绝盲目改写（请检查 DSH 版本）")
    # 把 persona 的一行文本替换成 MEMS 人格（保留 `text: >-` 折叠块缩进：6 空格）
    # 用 lambda 作替换：MEMS_PERSONA 里含 Windows 路径（\桌 等），直接当替换串会被 re 当转义解析而报错
    text = re.sub(
        r"^      You are a coding agent powered by the \{\{model\}\} model.*$",
        lambda _match: MEMS_PERSONA,
        text,
        count=1,
        flags=re.MULTILINE,
    )

    marker = "    maxBytes: 65536\n"
    if marker not in text:
        raise ValueError("基底文件里找不到 agent-instructions 锚点，拒绝盲目插入")
    text = text.replace(marker, marker + MCP_BLOCK.format(python=PYTHON, repo=REPO), 1)

    info = {
        "has_persona": "MEMS Harness platform engineer" in text,
        "has_mcp": "mcp-mems-harness" in text,
        "n_entries": len(re.findall(r"^- id:", text, flags=re.MULTILINE)),
        "n_nested_ids": len(re.findall(r"^    - id:", text, flags=re.MULTILINE)),
    }
    return text, info


def validate_yaml(text: str) -> dict:
    """解析 YAML 并检查引用的插件是否在本机存在（挂载失败是可预防的）。

    注意：组合文件里用了 DSH 的自定义标签 ``!!js``（如 ``disabled: !!js process.platform === 'win32'``），
    pyyaml 不认识它。校验时把它剥掉当普通标量解析——**只影响校验，不改变写盘内容**。
    """
    import yaml

    probe = re.sub(r"!!js\s+", "", text)
    data = yaml.safe_load(probe)
    assert isinstance(data, list), "组合文件顶层必须是数组"
    names = [row.get("name") for row in data if isinstance(row, dict) and row.get("name")]
    nested = [
        child.get("name")
        for row in data
        if isinstance(row, dict) and isinstance(row.get("config"), list)
        for child in row["config"]
        if isinstance(child, dict) and child.get("name")
    ]
    node_modules = DSH_HOME / "profiles" / "node_modules" / "@deepseek-ai"
    missing = []
    for name in names + nested:
        if not isinstance(name, str) or not name.startswith("@deepseek-ai/"):
            continue
        # 形如 `@deepseek-ai/<pkg>` 或 `@deepseek-ai/<pkg>/<entry>`（同包子路径导出）：
        # 一律只按包名判存在性，否则会把子路径条目误判成"缺失插件"。
        parts = name.split("/")
        pkg = parts[1] if len(parts) >= 2 else ""
        if pkg and not (node_modules / pkg).exists():
            missing.append(name)
    return {
        "parsed": True,
        "top_level_entries": len(data),
        "referenced_plugins": len(names) + len(nested),
        "missing_plugins": missing,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="安装 DSH「MEMS 模式」agent preset")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    composition, info = build_composition()
    checks = validate_yaml(composition)
    target_dir = DSH_HOME / ".agent-presets" / PRESET_ID

    print("=" * 70)
    print("安装 DSH「MEMS 模式」")
    print("=" * 70)
    print(f"  落盘目录：{target_dir}")
    print(f"  组合文件：{target_dir / 'agent.cordis.yml'}（基底 = standard 模式，文本级改写）")
    print(f"  顶层条目 {info['n_entries']} 个（含分组内 {info['n_nested_ids']} 个）")
    print(f"  persona 已替换：{info['has_persona']}｜已注入 MCP：{info['has_mcp']}")
    print(f"  YAML 解析：{checks['parsed']}｜引用插件 {checks['referenced_plugins']} 个"
          f"｜本机缺失：{checks['missing_plugins'] or '无'}")

    if checks["missing_plugins"]:
        print("有插件在本机不存在，挂载会失败——拒绝安装", file=sys.stderr)
        return 3
    if args.dry_run:
        print("\n[dry-run] 未写入任何文件。前 40 行预览：")
        print("\n".join(composition.splitlines()[:40]))
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "agent.cordis.yml").write_text(composition, encoding="utf-8")
    (target_dir / "preset.yml").write_text(PRESET_META, encoding="utf-8")
    print(f"\n✅ 已写入：{target_dir / 'agent.cordis.yml'}")
    print(f"✅ 已写入：{target_dir / 'preset.yml'}")
    print("生效方式：**重启 DSH**（与 MCP 补丁同理，HMR 不新增条目），"
          "然后在界面模式选择器里选「MEMS 模式」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
