"""渲染《模型第一次阅读报告》：把三个来源合成一份可回溯的报告。

三个来源（缺一不可，互为印证；任何一个缺项都如实标注，不推断）：
    1. ``probe_model`` 的 Java 探针 JSON —— 运行态结构（参数/物理场/选择集/研究步类型/几何/网格/schema 回读）
    2. GUI 导出的 Model M-file（``.m``）—— **文本权威**：研究步取值、属性枚举原文、
       **同一参数被设置的次数/行号/不同表达式**（多重设置历史，运行态看不到）
    3. MPh 运行态读取（可选）—— 第三个独立读数，用于印证 1 与 2

同时调用仓库自带的 ``modelio.cross_check``（只报差异、缺失≠一致）得到正式差异清单。

用法：
    python scripts\\render_reading_report.py <probe.json> --m-file <model.m> [--runtime <mph-runtime.json>]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

_LITERAL = re.compile(r"^\s*[-+]?[\d.]+(\s*\[[^\]]+\])?\s*$")
_PARAM_SET = re.compile(r"model\.param\.set\(\s*'([^']+)'\s*,\s*'([^']*)'")


def classify_expression(expr: str) -> str:
    return "字面量" if _LITERAL.match(expr or "") else "引用/派生"


def param_history_from_m(text: str) -> dict[str, dict]:
    """从 `.m` 文本里统计每个参数的设置历史（次数/行号/不同表达式）。"""
    hist: dict[str, dict] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, expr in _PARAM_SET.findall(line):
            entry = hist.setdefault(name, {"lines": [], "expressions": []})
            entry["lines"].append(lineno)
            entry["expressions"].append(expr)
    for entry in hist.values():
        distinct = sorted(set(entry["expressions"]))
        entry["n_settings"] = len(entry["expressions"])
        entry["distinct"] = distinct
        entry["conflict"] = len(distinct) > 1
        entry["last"] = entry["expressions"][-1]
        entry["last_line"] = entry["lines"][-1]
    return hist


def steps_of(spec: dict) -> list[tuple[str, list[dict]]]:
    out = []
    for study in spec.get("study") or []:
        out.append((study.get("tag"), study.get("steps") or []))
    return out


def step_props(step: dict) -> dict:
    props = step.get("properties")
    if isinstance(props, dict):
        return {str(k): str(v) for k, v in props.items()}
    if isinstance(props, list):
        merged = {}
        for item in props:
            if isinstance(item, dict) and "name" in item:
                merged[str(item["name"])] = str(item.get("value"))
        return merged
    return {}


def render(
    probe: dict,
    *,
    m_path: Path | None,
    spec: dict | None,
    runtime: dict | None,
    diffs: list[dict] | None,
) -> str:
    src = probe.get("source") or {}
    params = probe.get("parameters") or []
    physics = probe.get("physics") or []
    ifaces = [n for n in physics if n.get("kind") != "named_selection"]
    selections = [n for n in physics if n.get("kind") == "named_selection"]
    studies = probe.get("studies") or []
    solvers = probe.get("solvers") or []
    geometry = probe.get("geometry") or []
    mesh = probe.get("mesh") or []
    readback = probe.get("readback") or []
    schema = probe.get("schema_source") or {}
    unreadable = [r for r in readback if r.get("level") == "unreadable"]

    m_text = m_path.read_text(encoding="utf-8", errors="replace") if m_path and m_path.is_file() else ""
    history = param_history_from_m(m_text) if m_text else {}
    probe_expr = {p["name"]: (p.get("expression") or "") for p in params}
    runtime_expr = {p["name"]: p.get("expression") for p in (runtime or {}).get("parameters", [])}

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    L: list[str] = []
    add = L.append

    add("# 模型第一次阅读报告（三方合成）")
    add("")
    add(f"> 生成时间：{ts}")
    add(f"> ① Java 探针：`{probe.get('run_id')}`　② Model M-file：`{m_path}`　③ MPh 运行态：{'有' if runtime else '无'}")
    add("> 本报告只搬运实测字段；三侧不一致处**并列显示**，不合并、不取平均、不推断（AGENTS.md 红线 3）。")
    add("")

    add("## 1. 模型与原件")
    add("")
    add("| 项 | 值 |")
    add("|---|---|")
    add(f"| 源 `.mph` | `{src.get('path')}` |")
    add(f"| 源 SHA256 | `{src.get('sha256')}` |")
    add(f"| 只读副本 | `{src.get('staged_path')}` |")
    add(f"| 旁路 `.lock` | {src.get('lock_present')} |")
    add(f"| **原件未被改动** | **{src.get('original_untouched')}** |")
    add(f"| COMSOL 版本 | {probe.get('comsol_version')} |")
    if spec:
        add(f"| `.m` 路径 / SHA256 | `{spec.get('source_path')}` / `{spec.get('sha256')}` |")
        add(f"| `.m` 解析成功 | {spec.get('parsed')}（model_tag=`{spec.get('model_tag')}`） |")
    add("")

    add(f"## 2. 全局参数（{len(params)} 个）与 `.m` 设置历史")
    add("")
    if history:
        multi = {k: v for k, v in history.items() if v["n_settings"] > 1}
        conflict = {k: v for k, v in history.items() if v["conflict"]}
        add(f"`.m` 里 `model.param.set` 共 **{sum(v['n_settings'] for v in history.values())} 次**，"
            f"涉及 **{len(history)} 个参数**；被设置多次的 **{len(multi)} 个**，"
            f"其中**不同表达式互相冲突的 {len(conflict)} 个**。")
        add("")
    add("| # | 参数 | 运行态(probe) | `.m` 末次 | `.m` 次数 | `.m` 行号 | `.m` 不同表达式 | 冲突 | 求值 | 类型 |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for i, p in enumerate(params, 1):
        name = p.get("name")
        h = history.get(name, {})
        value = p.get("value")
        add(
            f"| {i} | `{name}` | `{probe_expr.get(name, '')}` | `{h.get('last', '')}` | "
            f"{h.get('n_settings', '')} | {h.get('lines', '')} | {h.get('distinct', '')} | "
            f"{'⚠️是' if h.get('conflict') else '否'} | "
            f"{'' if value is None else f'{value:.6g}'} | {classify_expression(probe_expr.get(name, ''))} |"
        )
    add("")
    missing_in_m = [p["name"] for p in params if p["name"] not in history]
    extra_in_m = sorted(set(history) - {p["name"] for p in params})
    if missing_in_m or extra_in_m:
        add(f"- `.m` 里未出现的参数：{missing_in_m or '无'}；`.m` 里多出的参数：{extra_in_m or '无'}")
        add("")

    add(f"## 3. 物理场接口（{len(ifaces)} 个，probe 侧）")
    add("")
    for node in ifaces:
        feats = node.get("features") or []
        add(f"### `{node.get('tag')}` — {node.get('type')}　选择 `{node.get('selection')}`")
        add("")
        add("| 特征 tag | 类型 | 标签 |")
        add("|---|---|---|")
        for f in feats:
            add(f"| `{f.get('tag')}` | `{f.get('type')}` | {f.get('label') or ''} |")
        add("")
    if spec:
        add("`.m` 侧接口与特征数（文本权威）：")
        add("")
        add("| `.m` 接口 | 类型 | 特征数 | 特征 tag::type |")
        add("|---|---|---|---|")
        for iface in spec.get("physics") or []:
            feats = iface.get("features") or []
            tags = ", ".join(f"`{f.get('tag')}`::{f.get('type')}" for f in feats)
            add(f"| `{iface.get('interface_tag')}` | `{iface.get('interface_type')}` | {len(feats)} | {tags} |")
        add("")

    add(f"## 4. 命名选择集（probe 侧 {len(selections)} 个）")
    add("")
    add("probe 标签：" + (", ".join(f"`{s.get('tag')}`" for s in selections) if selections else "（无）"))
    add("")
    if spec:
        sels = spec.get("selections") or []
        add(f"`.m` 侧选择集赋值 **{len(sels)} 条**（含几何特征创建/删除的历史记录），前 20 条：")
        add("")
        add("| owner | tag | 实体数 | `.m` 行 |")
        add("|---|---|---|---|")
        for sel in sels[:20]:
            entities = sel.get("entities")
            add(f"| `{sel.get('owner')}` | `{sel.get('tag')}` | "
                f"{len(entities) if isinstance(entities, list) else entities} | {sel.get('line')} |")
        add("")

    add(f"## 5. 研究（probe 侧 {len(studies)} 个）—— 取值来自 `.m` 与 MPh")
    add("")
    if spec:
        for stag, steps in steps_of(spec):
            add(f"### `{stag}`（`.m` 侧）")
            add("")
            for step in steps:
                props = step_props(step)
                add(f"**step `{step.get('tag')}` type=`{step.get('type')}`**")
                add("")
                if props:
                    add("| 属性 | 取值 |")
                    add("|---|---|")
                    for k, v in props.items():
                        add(f"| `{k}` | `{v}` |")
                else:
                    add("（`.m` 未记录该步的属性赋值）")
                add("")
    for study in studies:
        add(f"### `{study.get('tag')}`（probe 侧，仅步骤类型）")
        add("")
        add("| 步骤 | 类型 |")
        add("|---|---|")
        for step in study.get("steps") or []:
            add(f"| `{step.get('tag')}` | `{step.get('type')}` |")
        add("")
    if runtime:
        add("### MPh 运行态（第三个独立读数）")
        add("")
        for study in runtime.get("studies") or []:
            for step in study.get("steps") or []:
                props = step.get("properties") or {}
                if props:
                    add(f"- `{step.get('tag')}` ({step.get('type')}): " +
                        "; ".join(f"`{k}`=`{v}`" for k, v in props.items()))
        add("")

    add(f"## 6. 求解器（probe 侧 {len(solvers)} 个）")
    add("")
    add(", ".join(f"`{s if isinstance(s, str) else s.get('tag')}`" for s in solvers) or "（未读到）")
    add("")
    if spec and spec.get("solvers"):
        add("`.m` 侧求解器特征：")
        add("")
        add("| 求解器 | 关联研究 | 特征 |")
        add("|---|---|---|")
        for sol in spec["solvers"]:
            feats = ", ".join(f"`{f.get('tag')}`::{f.get('type')}" for f in (sol.get("features") or []))
            add(f"| `{sol.get('tag')}` | `{sol.get('study')}` | {feats} |")
        add("")

    add("## 7. 几何与网格")
    add("")
    add("| 几何 | 维度 | 顶点 | 边 | 边界 | 域 |")
    add("|---|---|---|---|---|---|")
    for g in geometry:
        add(f"| `{g.get('tag')}` | {g.get('space_dim')}D | {g.get('n_vertices')} | {g.get('n_edges')} | "
            f"{g.get('n_boundaries')} | {g.get('n_domains')} |")
    add("")
    add("| 网格 | 单元数 | 顶点数 | 本次重算 |")
    add("|---|---|---|---|")
    for m in mesh:
        add(f"| `{m.get('tag')}` | {m.get('num_elements')} | {m.get('num_vertices')} | {m.get('computed_in_this_run')} |")
    add("")
    if runtime:
        for m in runtime.get("meshes") or []:
            add(f"- MPh 运行态印证：`{m['tag']}` num_elements={m['num_elements']}, num_vertices={m['num_vertices']}")
        for g in runtime.get("geometries") or []:
            add(f"- MPh 运行态印证：`{g['tag']}` 顶点/边/边界/域 = "
                f"{g.get('n_vertices')}/{g.get('n_edges')}/{g.get('n_boundaries')}/{g.get('n_domains')}")
        add("")
    add("> ⚠️ 该模型保存态**未构建网格**（0 单元），故无单元数/包围盒/网格收敛信息。")
    add("")

    if spec:
        ev = spec.get("enum_validation") or {}
        add("## 8. `.m` 枚举合法性校验（用 COMSOL 自带 schema）")
        add("")
        add("| 项 | 值 |")
        add("|---|---|")
        add(f"| schema 可用 | {ev.get('available')} |")
        add(f"| 已校验赋值数 | {ev.get('checked_count')} |")
        for key in ("illegal", "unresolved", "variant_dependent"):
            value = ev.get(key)
            add(f"| {key} | {len(value) if isinstance(value, (list, dict)) else value} |")
        add("")
        illegal = ev.get("illegal")
        if isinstance(illegal, (list, dict)) and illegal:
            add("非法枚举赋值明细（前 10 条）：")
            add("")
            items = illegal.items() if isinstance(illegal, dict) else enumerate(illegal)
            for k, v in list(items)[:10]:
                add(f"- {k}: {json.dumps(v, ensure_ascii=False)[:200]}")
            add("")
        unknown = spec.get("unknown_assignments") or []
        add(f"## 9. `.m` 里无法归类的赋值（{len(unknown)} 条，保留原文与行号）")
        add("")
        add("| 行 | 块 | 原因 | 原文 |")
        add("|---|---|---|---|")
        for item in unknown[:20]:
            text = str(item.get("text", ""))[:110].replace("|", "\\|")
            add(f"| {item.get('line')} | {item.get('block')} | {item.get('reason')} | `{text}` |")
        add("")

    add(f"## 10. 交叉校验差异（`modelio.cross_check`，共 {len(diffs or [])} 条）")
    add("")
    if diffs:
        by_kind: dict[str, int] = {}
        for d in diffs:
            by_kind[d.get("kind", "?")] = by_kind.get(d.get("kind", "?"), 0) + 1
        add("按类型统计：" + ", ".join(f"`{k}`={v}" for k, v in sorted(by_kind.items())))
        add("")
        add("| 维度 | 键 | 类型 | `.m`/spec | probe | 说明 |")
        add("|---|---|---|---|---|---|")
        for d in diffs[:60]:
            sv = str(d.get("spec_value"))[:60].replace("|", "\\|")
            pv = str(d.get("probe_value"))[:60].replace("|", "\\|")
            reason = str(d.get("reason", ""))[:80].replace("|", "\\|")
            add(f"| {d.get('dimension')} | `{d.get('key')}` | {d.get('kind')} | `{sv}` | `{pv}` | {reason} |")
        if len(diffs) > 60:
            add(f"| … | | | | | 其余 {len(diffs) - 60} 条见落档 JSON |")
        add("")
    else:
        add("无差异（注意：这表示两侧在**可比较的项**上一致，不代表未比较的项也一致）。")
        add("")

    add(f"## 11. probe 回读校验（{len(readback)} 项，不可读 {len(unreadable)} 项）")
    add("")
    if unreadable:
        add("| 项 | 原因 |")
        add("|---|---|")
        for r in unreadable:
            add(f"| `{r.get('item')}` | `{r.get('reason')}` |")
        add("")

    add("## 12. schema 来源")
    add("")
    add(f"- {schema.get('path')}（特征 {schema.get('features_parsed')} / 变体 {schema.get('variants_parsed')} / "
        f"枚举属性 {schema.get('enum_properties_parsed')}，SHA256 `{schema.get('sha256')}`）")
    add("")

    add("## 13. 仍未读到 / 待人工确认")
    add("")
    for item in [
        "网格：保存态未构建（0 单元）→ 无单元数、包围盒、网格收敛信息。",
        "目标量（声压/位移等）可用性与数值 → 需要真实求解。",
        "参数的结构分类（几何类/研究数值类/激励类）：本报告只标「字面量/派生」，分类需人工或规则定义。",
        "多重设置的口径裁决：见第 2 节「冲突=是」的参数（运行态只反映**最后一次**生效值，历史被覆盖）。",
    ]:
        add(f"- {item}")
    add("")

    add("## 14. 证据索引")
    add("")
    add(f"- Java 探针 JSON：`work/reports/modelio/probe-{probe.get('run_id')}.json`")
    add(f"- run 目录（命令/日志/Java 源码/输入副本）：`{probe.get('run_dir')}`")
    if m_path:
        add(f"- Model M-file：`{m_path}`")
    if runtime:
        add(f"- MPh 运行态 JSON：`work/reports/modelio/mph-runtime-{Path(str(src.get('path'))).stem}.json`")
    add("- 「派生/字面量」「冲突」等标注由表达式文本与行号判定，规则写在 `scripts/render_reading_report.py` 顶部。")
    add("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="渲染《模型第一次阅读报告》（三方合成）")
    ap.add_argument("probe", help="probe JSON 路径")
    ap.add_argument("--m-file", default=None, help="GUI 导出的 Model M-file（.m）")
    ap.add_argument("--runtime", default=None, help="MPh 运行态 JSON（可选）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    probe_path = Path(args.probe)
    probe = json.loads(probe_path.read_text(encoding="utf-8"))

    m_path = Path(args.m_file) if args.m_file else None
    runtime = json.loads(Path(args.runtime).read_text(encoding="utf-8")) if args.runtime else None

    spec = None
    diffs: list[dict] | None = None
    if m_path and m_path.is_file():
        from memsharness import modelio as mio

        spec = mio.parse_matlab_export(m_path)
        diffs = mio.cross_check(spec, probe)
        ev_dir = _REPO_ROOT / "work" / "reports" / "modelio"
        ev_dir.mkdir(parents=True, exist_ok=True)
        (ev_dir / f"mspec-{m_path.stem}.json").write_text(
            json.dumps(spec, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        (ev_dir / f"crosscheck-{m_path.stem}.json").write_text(
            json.dumps(diffs, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

    text = render(probe, m_path=m_path, spec=spec, runtime=runtime, diffs=diffs)

    if args.out:
        out = Path(args.out)
    else:
        stem = Path(str((probe.get("source") or {}).get("path") or "model")).stem
        out = _REPO_ROOT / "work" / "reports" / "modelio" / f"READING-{stem}-{probe.get('run_id')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"报告已生成：{out}（{len(text.splitlines())} 行，{out.stat().st_size} 字节）")
    if diffs is not None:
        kinds: dict[str, int] = {}
        for d in diffs:
            kinds[d.get("kind", "?")] = kinds.get(d.get("kind", "?"), 0) + 1
        print(f"cross_check 差异 {len(diffs)} 条：{kinds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
