# -*- coding: utf-8 -*-
"""「上报给 DSH」的契约测试。

三条口径是**用户当场选的**，因此每条都必须有可执行的守卫，而不是界面提示：
1. **只读分析**（不改文件）—— 约束要逐条写进 prompt，且被断言；
2. **只在人点按钮时**上报 —— 不得有任何自动触发路径；
3. **离线模式禁止** —— 门禁在控制台侧（模式是它的状态）。

安全：**测试绝不许启动真实 dsh**。全部用例都用 `DSH_BIN` 指向一个替身脚本；
另有一条用例专门验证「不给 `confirm_spawn` 就拒绝」和「测试期没有替身就拒绝」。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

FAKE_OK = ("import sys, pathlib\n"
           "p = pathlib.Path(sys.argv[-1])\n"
           "print('FAKE-DSH-OK: 读到任务文本 %d 字' % len(sys.argv[-1]))\n"
           "print('我的只读分析结论：根因 = 演示')\n")
FAKE_SLOW = ("import time\n"
             "time.sleep(3600)\n")


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMS_DSH_REPORT_LOG", str(tmp_path / "reports.jsonl"))
    monkeypatch.setenv("MEMS_INCIDENTS_ROOT", str(tmp_path / "packages"))
    from memsharness import dsh_report
    dsh_report._PROCS.clear()
    return dsh_report


def _fake(tmp_path: Path, body: str, name: str = "fake_dsh.py") -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8", newline="\n")
    return p


def test_refuses_without_explicit_confirm(tmp_path, mod, monkeypatch):
    """**核心安全**：不显式说"我就是要起真家伙"就拒绝（实测被这条救过）。"""
    monkeypatch.setenv("DSH_BIN", str(_fake(tmp_path, FAKE_OK)))
    r = mod.start_report("inc-1", "# 包", out_root=str(tmp_path / "pkgs"))
    assert "confirm_spawn" in str(r.get("blocked_by"))
    assert "拒绝启动" in r["error"]
    assert mod.load_reports()["n_total"] == 0, "被拒的上报不许留任何痕迹"
    assert not (tmp_path / "pkgs").exists(), "被拒时不得创建目录"


def test_refuses_real_dsh_under_pytest(tmp_path, mod, monkeypatch):
    """测试期没给替身 ⇒ 拒绝（而不是"顺手真跑一次"）。"""
    monkeypatch.delenv("DSH_BIN", raising=False)
    r = mod.start_report("inc-1", "# 包", out_root=str(tmp_path / "pkgs"), confirm_spawn=True)
    assert r.get("blocked_by") == "pytest_requires_fake_dsh"


def test_prompt_contains_readonly_rules_and_package(tmp_path, mod, monkeypatch):
    """只读口径必须**逐条**在 prompt 里（这是用户选的第一条）。"""
    mod_dsh = mod
    mod_dsh._PROCS.clear()
    f = _fake(tmp_path, FAKE_OK)
    monkeypatch.setenv("DSH_BIN", str(f))
    r = mod_dsh.start_report("inc-2", "# 失败分析包 inc-2\n\n## 1. 现象\n炸了",
                             out_root=str(tmp_path / "pkgs"), confirm_spawn=True)
    prompt = (REPO / r["prompt_path"]).read_text(encoding="utf-8") \
        if not Path(r["prompt_path"]).is_absolute() else Path(r["prompt_path"]).read_text(
            encoding="utf-8")
    for rule in mod_dsh.READONLY_RULES:
        assert rule in prompt, "prompt 缺约束：%s" % rule[:40]
    assert "不得修改、创建、删除仓库里的任何文件" in prompt
    assert "不得改变任何裁定、模型状态或放行结论" in prompt
    assert "不许猜" in prompt
    assert "## 1. 现象" in prompt, "包全文必须在 prompt 里"
    assert "输出格式" in prompt and "最可能的根因" in prompt
    mod_dsh.finish_report(r["report_id"], timeout_s=60)


def test_run_completes_and_is_logged(tmp_path, mod, monkeypatch):
    monkeypatch.setenv("DSH_BIN", str(_fake(tmp_path, FAKE_OK)))
    r = mod.start_report("inc-3", "# 包", out_root=str(tmp_path / "pkgs"), confirm_spawn=True)
    upd = mod.finish_report(r["report_id"], timeout_s=60)
    assert upd["status"] == "done" and upd["exit_code"] == 0
    rec = mod.load_reports(incident_id="inc-3")["items"][0]
    assert rec["status"] == "done" and rec["report_id"] == r["report_id"]
    assert "FAKE-DSH-OK" in (rec.get("tail") or ""), "结论/输出必须留痕"
    assert rec["mode"] == "readonly"
    # 启动 + 结束两条记录被归并成一条
    assert mod.load_reports()["n_total"] == 1


def test_timeout_kills_and_is_reported_honestly(tmp_path, mod, monkeypatch):
    monkeypatch.setenv("DSH_BIN", str(_fake(tmp_path, FAKE_SLOW)))
    r = mod.start_report("inc-4", "# 包", out_root=str(tmp_path / "pkgs"),
                         timeout_s=2, confirm_spawn=True)
    t0 = time.time()
    upd = mod.finish_report(r["report_id"], timeout_s=2)
    assert upd["status"] == "timeout" and time.time() - t0 < 90, "超时必须真杀掉"
    rec = mod.load_reports(incident_id="inc-4")["items"][0]
    assert rec["status"] == "timeout"


def test_running_dedup_helper(tmp_path, mod, monkeypatch):
    monkeypatch.setenv("DSH_BIN", str(_fake(tmp_path, FAKE_SLOW)))
    r = mod.start_report("inc-5", "# 包", out_root=str(tmp_path / "pkgs"),
                         timeout_s=2, confirm_spawn=True)
    assert mod.running("inc-5"), "在跑的上报要能被查出来（控制台据此去重）"
    assert mod.running("inc-other") is None
    mod.finish_report(r["report_id"], timeout_s=2)
    assert mod.running("inc-5") is None


def test_finish_without_handle_is_unknown_not_success(mod):
    """控制台重启后进程句柄没了 ⇒ 必须如实说"终态未知"，不许猜成功或失败。"""
    upd = mod.finish_report("dshr-nope", timeout_s=1)
    assert upd["status"] == "unknown" and "不猜" in upd["error"]


def test_find_dsh_is_honest_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_BIN", str(tmp_path / "not-here"))
    from memsharness import dsh_report
    pre, how = dsh_report.find_dsh()
    assert pre is None and "不存在" in how
    monkeypatch.delenv("DSH_BIN", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty"))
    pre2, how2 = dsh_report.find_dsh()
    assert pre2 is None, "找不到就必须报找不到，不许猜路径"
    assert "DSH_BIN" in how2, "要告诉用户怎么指定"


def test_report_log_is_append_only_and_survives_bad_lines(tmp_path, mod, monkeypatch):
    monkeypatch.setenv("DSH_BIN", str(_fake(tmp_path, FAKE_OK)))
    r = mod.start_report("inc-6", "# 包", out_root=str(tmp_path / "pkgs"), confirm_spawn=True)
    mod.finish_report(r["report_id"], timeout_s=60)
    p = mod.report_log()
    first = p.read_text(encoding="utf-8")
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("{ bad json\n")
    r2 = mod.start_report("inc-7", "# 包", out_root=str(tmp_path / "pkgs"), confirm_spawn=True)
    mod.finish_report(r2["report_id"], timeout_s=60)
    assert p.read_text(encoding="utf-8").startswith(first), "追加不得改动已有行"
    d = mod.load_reports()
    assert d["n_bad_lines"] == 1 and d["n_total"] == 2
