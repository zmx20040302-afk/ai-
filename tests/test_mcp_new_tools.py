# -*- coding: utf-8 -*-
"""新增 MCP 工具（A5/A8/A9 + 角色点名）的离线自测。

测的是**MCP 工具面本身**（经 fastmcp 的 in-process Client 调用），不是内部函数：
这样"工具是否真的注册、参数是否真的能过、返回体是否带裁决"都被覆盖。

覆盖：
* 16 个工具全部注册（含新增 5 个）；
* `freeze_gate`：真实冻结件 ⇒ passed；被篡改的冻结件 ⇒ failed（在 `work/` 下现造）；
* `sweep_analysis`：真实 72 网格 ⇒ provisional + 产物落盘；未知 preset / 越界路径 ⇒ 结构化错误；
* `make_report`：真实 bundle ⇒ passed；含无来源数字的 bundle ⇒ failed；
* `role_list` / `role_payload`：9 角色；载荷落盘且契约逐字节一致；账本写到指定路径（不污染真实账本）。
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

import pytest
from fastmcp import Client

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness import mcp_server  # noqa: E402

R = REPO / "work" / "runs" / "a5a9-20260916"
CSV = REPO / "work/runs/scalar-channel-20260915/pmut_report/structure_summary.csv"
FREEZE06 = (REPO / "work/runs/phase0-field-holdout-20260915/freezes"
            / "freeze_phase1-executor-20260915-06")


def call(name: str, args: dict) -> dict:
    async def _run():
        async with Client(mcp_server.mcp) as client:
            res = await client.call_tool(name, args)
            return res.data
    return asyncio.run(_run())


#: 期望**恰好**注册的工具集。用集合相等而不是 `len == N`：
#: 数量断言只能抓"多了/少了"，集合断言还能抓"改名了/被替换了"，
#: 而且新增工具时**必须显式改这里**（有意的改动，不会被无意绕过）。
EXPECTED_TOOLS = {
    # 基础/环境
    "ping", "env_report", "module_capability", "data_stats", "records", "run_trace",
    # 求解队列
    "sim_templates", "sim_submit", "sim_status", "sim_logs", "sim_cancel",
    # 冻结/分析/报告
    "freeze_gate", "sweep_analysis", "make_report",
    # 子智能体角色
    "role_list", "role_payload",
    # 网页控制台（MCP 只做客户端，不绕过控制台的串行化）
    "console_status", "console_tasks", "console_run_task", "console_job",
    # 多通道一阶峰代理（进程内只读）
    "monitor_model_card", "monitor_predict",
}


def test_new_tools_are_registered():
    async def _run():
        async with Client(mcp_server.mcp) as client:
            return sorted(t.name for t in await client.list_tools())
    names = set(asyncio.run(_run()))
    for t in ("freeze_gate", "sweep_analysis", "make_report", "role_list", "role_payload"):
        assert t in names, t
    assert names == EXPECTED_TOOLS, (
        "MCP 工具集与预期不符；多出 %s，缺少 %s"
        % (sorted(names - EXPECTED_TOOLS), sorted(EXPECTED_TOOLS - names)))


def test_freeze_gate_on_real_and_tampered_freeze(tmp_path: Path):
    ok = call("freeze_gate", {"target_dir": str(FREEZE06)})
    assert ok["verdict"] == "passed" and ok["release_allowed"] is True

    # 越界路径 ⇒ 结构化错误（不读仓库外的东西）
    outside = call("freeze_gate", {"target_dir": str(tmp_path)})
    assert "error" in outside and "仓库内" in outside["error"]

    # 现造一个被篡改的冻结件（放 work/ 下，测完删除）
    fake = REPO / "work/runs/_mcp_test_freeze"
    if fake.exists():
        shutil.rmtree(fake)
    try:
        (fake / "snapshot").mkdir(parents=True)
        (fake / "snapshot" / "a.bin").write_bytes(b"payload")
        (fake / "freeze_manifest.json").write_text(json.dumps({
            "freeze_id": "fake-1",
            "source_inventory": [{"path": str(fake / "snapshot" / "a.bin"),
                                  "sha256": "0" * 64}],
            "snapshot_inventory": [{"path": str(fake / "snapshot" / "a.bin"),
                                    "sha256": "0" * 64}],
            "three_way_readback": True, "three_way_match": True,
        }), encoding="utf-8")
        (fake / "manifest.sha256").write_text("0" * 64 + "  freeze_manifest.json\n",
                                              encoding="utf-8")
        bad = call("freeze_gate", {"target_dir": str(fake)})
        assert bad["verdict"] == "failed" and bad["release_allowed"] is False
        assert bad["failed_or_unknown"]
    finally:
        shutil.rmtree(fake, ignore_errors=True)


def test_sweep_analysis_tool_end_to_end():
    out = "work/runs/_mcp_test_sweep"
    res = call("sweep_analysis", {
        "csv": str(CSV), "out_dir": out, "preset": "pmut-structure-summary",
        "candidate_grid": str(R / "candidate_grid.json"), "budget": 6, "min_effective": 5})
    try:
        assert res["verdict"] == "provisional" and res["release_allowed"] is False
        assert res["no_composite_score"] is True
        assert res["precheck"]["used"] is False          # 未提供预检 ⇒ 如实降级
        assert set(res["verdict_by_family"]) == {"A_scan_xrange040508", "D_0.5MHz_dense"}
        assert res["released_families"] == []            # 临时批次不放行
        assert res["next_batch"]["verdict"] in ("proposed", "blocked")
        for rel in ("scan_analysis_json", "scan_analysis_md", "next_batch_json"):
            assert Path(res["artifacts"][rel]).is_file(), rel
        scan = json.loads(Path(res["artifacts"]["scan_analysis_json"]).read_text(encoding="utf-8"))
        assert scan["kind"] == "scan_analysis" and scan["checks"]
        # 未知 preset / 越界输出目录 ⇒ 结构化错误
        assert "error" in call("sweep_analysis", {"csv": str(CSV), "preset": "nope"})
        assert "error" in call("sweep_analysis", {"csv": str(CSV), "out_dir": "C:/Windows/Temp/x"})
        assert "error" in call("sweep_analysis", {"csv": "C:/Windows/notepad.exe"})
    finally:
        shutil.rmtree(REPO / out, ignore_errors=True)


def test_make_report_tool_passes_and_blocks(tmp_path: Path):
    res = call("make_report", {"bundle": str(R / "bundle_platform.json"),
                               "known_ids": str(R / "known_ids.json"),
                               "out_dir": "work/runs/_mcp_test_report"})
    try:
        assert res["verdict"] == "passed" and res["publish_allowed"] is True
        assert res["gate_binding"]["mode"] == "not_applicable"
        assert Path(res["artifacts"]["analysis_report_md"]).is_file()

        # 反向：把无来源数字塞进结果段落 ⇒ 必须 failed
        spec = json.loads((R / "bundle_platform.json").read_text(encoding="utf-8"))
        spec["sections"]["error_bounds"] = "误差 918.43%（无来源）"
        bad_bundle = REPO / "work/runs/_mcp_test_bad_bundle.json"
        bad_bundle.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        bad = call("make_report", {"bundle": str(bad_bundle),
                                   "known_ids": str(R / "known_ids.json"),
                                   "out_dir": "work/runs/_mcp_test_report_bad"})
        assert bad["verdict"] == "failed"
        assert any(c["name"] == "section_numbers_traced" for c in bad["blocking"])
    finally:
        (REPO / "work/runs/_mcp_test_bad_bundle.json").unlink(missing_ok=True)
        shutil.rmtree(REPO / "work/runs/_mcp_test_report", ignore_errors=True)
        shutil.rmtree(REPO / "work/runs/_mcp_test_report_bad", ignore_errors=True)


def test_role_list_and_payload_do_not_touch_the_real_ledger():
    real = REPO / "work/role-spawns/spawn_ledger.jsonl"
    n_real_before = len([x for x in real.read_text(encoding="utf-8").splitlines() if x.strip()]) \
        if real.is_file() else 0
    rl = call("role_list", {})
    assert rl["n_roles"] == 9
    assert {"A5", "A8", "A9"} <= {r["role_id"] for r in rl["roles"]}

    res = call("role_payload", {
        "role": "a8-verification-freeze", "task": "复核本次 A5/A9 修补是否闭合红队发现。",
        "out_root": "work/runs/_mcp_test_roles",
        "ledger_path": "work/runs/_mcp_test_roles/ledger.jsonl"})
    try:
        assert res["role_id"] == "A8" and res["ledger"]["status"] == "appended"
        payload = Path(res["payload_path"])
        assert payload.is_file()
        contract = (REPO / "agents/a8-verification-freeze/AGENT.md").read_text(encoding="utf-8")
        assert contract.strip("\n") in payload.read_text(encoding="utf-8")
        # 账本落到指定位置，真实账本行数**不因本次测试增加**
        assert Path("work/runs/_mcp_test_roles/ledger.jsonl").is_file()
        real = REPO / "work/role-spawns/spawn_ledger.jsonl"
        n_after = len([x for x in real.read_text(encoding="utf-8").splitlines() if x.strip()]) \
            if real.is_file() else 0
        # ⚠️ 断言必须**相对**而不是"恰好 1 行"：控制台里真人点一次「生成载荷」就会合法地
        #    往真实账本追加一行，绝对计数会把这种正常使用误判成"测试污染"（实测撞到过）。
        assert n_after == n_real_before, \
            "MCP 测试污染了真实 spawn 账本：%d → %d 行" % (n_real_before, n_after)
        assert "error" in call("role_payload", {"role": "a99-nope", "task": "t"})
        assert "error" in call("role_payload", {"role": "A8", "task": "t",
                                                "out_root": "C:/Windows/Temp/x"})
    finally:
        shutil.rmtree(REPO / "work/runs/_mcp_test_roles", ignore_errors=True)


def test_mems_preset_persona_advertises_the_new_capabilities():
    """部署面回归守卫：新能力必须出现在 MEMS 模式的 persona 里（否则会话不知道它们存在）。

    同时（若本机已安装 preset）校验**已安装文件**里确实含有该能力块 —— 这是一条
    "你改了生成器但忘了重新安装"的探测器。
    """
    import importlib.util

    p = REPO / "scripts" / "install_mems_preset.py"
    spec = importlib.util.spec_from_file_location("_mems_installer", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    persona = "\n".join(mod.PERSONA_LINES)
    for token in ("mcp__mems__sweep_analysis", "mcp__mems__make_report",
                  "mcp__mems__freeze_gate", "mcp__mems__role_list",
                  "mcp__mems__role_payload", "agents/<id>-<slug>/AGENT.md",
                  "spawn_ledger.jsonl"):
        assert token in persona, "persona 未提到 %s" % token
    assert "A5" in mod.PRESET_DESCRIPTION and "A9" in mod.PRESET_DESCRIPTION

    # 渲染面回归（2026-09-22）：DSH 的 `{{model}}` / `{{cwd}}` 占位符必须**原样**活到成品里。
    # 旧实现用 str.format(repo=...) 渲染，把 `{{cwd}}` 折叠成字面量 `{cwd}` ⇒ 人格里留下
    # 未解析符号、DSH 不再注入工作区路径（实测本会话系统提示就是 "Your workspace is {cwd}"）。
    rendered = "\n".join(mod.render_persona("<REPO>"))
    assert "{{model}}" in rendered, "render_persona 折叠了 {{model}} 占位符"
    assert "{{cwd}}" in rendered, "render_persona 折叠了 {{cwd}} 占位符（多半是又改回 str.format）"
    assert "{cwd}" not in rendered.replace("{{cwd}}", ""), "render_persona 产出裸 {cwd}"
    assert "<REPO>" in rendered, "render_persona 没有替换 {repo}"

    installed = Path.home() / ".dsh" / ".agent-presets" / "mems" / "agent.cordis.yml"
    if not installed.is_file():
        pytest.skip("本机未安装 MEMS preset（跳过已安装文件的比对）")
    text = installed.read_text(encoding="utf-8")
    assert "mcp__mems__sweep_analysis" in text, "已安装的 preset 未包含新能力块：请重跑 install_mems_preset.py --install --force"
    assert "mcp__mems__role_payload" in text

    # 只看 persona 的**实际 prefix**：整文件搜 `{{cwd}}` 会被 donor 自带的注释行
    # （"`{{model}}` and `{{cwd}}` resolve from the agent's own route..."）命中
    # ⇒ 那是条**假绿断言**（2026-09-22 实测：测试全绿而装出来的 persona 实际是 `{cwd}`）。
    import yaml

    class _Loader(yaml.SafeLoader):
        """容忍 DSH 的 ``!!js`` 标签（本机 standard 预设里有）。"""

    _Loader.add_constructor("tag:yaml.org,2002:js", lambda loader, node: None)
    doc = yaml.load(text, Loader=_Loader)
    _persona = next(r for r in doc if isinstance(r, dict) and r.get("id") == "persona")
    prefix = _persona["config"]["prefix"]
    assert "{{cwd}}" in prefix, (
        "已安装 preset 的 persona **prefix** 里 {{cwd}} 未原样保留 ⇒ DSH 不会注入工作区路径，"
        "人格里会残留字面量 {cwd}。请重跑："
        "python scripts\\install_mems_preset.py --install --force（然后重启 DSH 并新建会话）")
    assert "{cwd}" not in prefix.replace("{{cwd}}", ""), "已安装 persona 里出现裸 {cwd}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
