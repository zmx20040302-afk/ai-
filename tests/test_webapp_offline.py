# -*- coding: utf-8 -*-
"""网页控制台（`scripts/webapp_server.py`）的离线自测：**真的起 HTTP 服务再打它**。

覆盖（对应"控制台会不会被误用/骗人"的风险）：
* 首页与 `/api/jobs` 可访问，任务清单里**没有**任意执行类入口；
* **白名单**：未登记任务 → 400 + 不产生 job；
* **写任务需 confirm**：缺 confirm → 400；
* **只读任务**端到端：`freeze_gate` 提交 → 轮询到 done → 带 verdict/release_allowed；
* **路径守卫**：输出目录在 work/ 外 → 任务报错而不是写出去；
* **裁决不被前端改写**：返回体里的 `verdict` 与代码产出一致（`inconclusive` 不得变 passed）；
* 任务**串行执行**（全局锁）：两个写任务先后跑，产物不互相覆盖（顺序断言）。
"""
from __future__ import annotations

import importlib.util
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def load_srv():
    spec = importlib.util.spec_from_file_location("_web", REPO / "scripts/webapp_server.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def server():
    m = load_srv()
    from http.server import ThreadingHTTPServer
    port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), m.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    yield m, f"http://127.0.0.1:{port}"
    srv.shutdown()
    srv.server_close()


def get(url: str):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def post(url: str, payload: dict):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def wait_job(base: str, jid: str, timeout: float = 300.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        _, j = get("%s/api/job/%s" % (base, jid))
        if j.get("status") != "running":
            return j
        time.sleep(0.3)
    raise AssertionError("任务超时未结束：%s" % jid)


def test_index_and_job_catalog(server):
    _, base = server
    with urllib.request.urlopen(base + "/", timeout=30) as r:
        html = r.read().decode("utf-8")
    assert r.status == 200 and "响应级代理" in html and "控制台" in html
    assert "/api/run" in html and "confirm" in html
    _, cat = get(base + "/api/jobs")
    tasks = cat["tasks"]
    assert {"state", "sweep_analysis", "report_gate", "freeze_gate",
            "a6_eval", "x_plan", "role_payload"} <= set(tasks)
    # 无任意执行入口；且 fn 不泄露到目录里
    assert not any(k in tasks for k in ("exec", "shell", "eval", "cmd", "python"))
    assert all("fn" not in v for v in tasks.values())
    # 每个任务都声明了 params 与 writes
    for k, v in tasks.items():
        assert "params" in v and "writes" in v, k


def test_whitelist_and_confirm(server):
    m, base = server
    n0 = len(m.JOBS)
    code, r = post(base + "/api/run", {"task": "rm -rf /", "args": {"confirm": True}})
    assert code == 400 and "allowed" in r and len(m.JOBS) == n0
    code, r = post(base + "/api/run", {"task": "sweep_analysis", "args": {}})
    assert code == 400 and r.get("writes") is True and len(m.JOBS) == n0


def test_readonly_task_end_to_end(server):
    m, base = server
    code, r = post(base + "/api/run", {"task": "freeze_gate", "args": {"confirm": True}})
    assert code == 200 and r.get("job_id")
    j = wait_job(base, r["job_id"])
    assert j["status"] == "done"
    res = j["result"]
    # 裁决字段与代码产出一致（不得被改写）
    sys.path.insert(0, str(REPO / "src"))
    from memsharness.freeze_gate import run_gate
    truth = run_gate(Path(res["target_dir"]))
    assert res["verdict"] == truth["verdict"]
    assert res["release_allowed"] == truth["release_allowed"]
    assert res["verdict"] in ("passed", "failed", "inconclusive")
    if res["verdict"] == "inconclusive":
        assert res["release_allowed"] is False, "inconclusive 绝不能 released"
    assert res["script"]["sha256"]


def test_path_guard_blocks_outside_work(server):
    m, base = server
    code, r = post(base + "/api/run", {"task": "sweep_analysis",
                                       "args": {"confirm": True, "out_dir": "C:/Windows/Temp/x"}})
    assert code == 200
    j = wait_job(base, r["job_id"])
    assert j["status"] == "error" and "work/" in j["error"]


def test_jobs_are_serialized(server):
    m, base = server
    # 两个写任务同时提交：都应成功，且执行段互不重叠（用 EXEC_LOCK 保证）
    ids = []
    for _ in range(2):
        code, r = post(base + "/api/run", {"task": "dashboard",
                                           "args": {"confirm": True,
                                                    "out_dir": "work/reports/webapp/dash-test",
                                                    "generated_at": "2026-09-23T00:00:00+00:00"}})
        assert code == 200
        ids.append(r["job_id"])
    outs = [wait_job(base, i) for i in ids]
    assert all(o["status"] == "done" for o in outs)
    assert all("index.html" in json.dumps(o["result"]) for o in outs)
    assert m.EXEC_LOCK.locked() is False


# ---------------------------------------------------------------- 对话式前端
# 打桩原则：**不真调 LLM**（离线、无 key、不花钱），只验证路由/权限/口径。

FAKE_KEY = "sk-UNIT-TEST-DO-NOT-LEAK-0123456789"


def _fake_llm(steps):
    """按顺序返回预设的 LLM 响应；`steps` 用完后重复最后一条。"""
    box = {"i": 0}
    def _call(messages, tools, *, timeout=90):
        i = min(box["i"], len(steps) - 1)
        box["i"] += 1
        return {"choices": [{"message": steps[i]}], "_used": {"model": "stub-llm",
                                                              "base": "https://stub.invalid"}}
    return _call


def _tool_call(name, args, cid="c1"):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": cid, "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_chat_mode_endpoint(server, monkeypatch):
    """新契约（2026-09-29）：**有 key 也不默认联网**；必须显式切到 DeepSeek。

    旧行为是"有 key 就自动走 LLM"，那等于**默认联网**；现在默认离线，
    `/api/chat/mode` 作为兼容别名也必须反映真实 STATE（不得只看有没有 key）。
    """
    m, base = server
    monkeypatch.setitem(m.STATE, "mode", "offline")
    monkeypatch.setattr(m, "load_api_key", lambda: (None, "none"))
    _, r = get(base + "/api/chat/mode")
    assert r["mode"] == "local" and r["state_mode"] == "offline"
    # 有 key 但仍是离线 ⇒ **不得**报 llm
    monkeypatch.setattr(m, "load_api_key", lambda: (FAKE_KEY, "unit-test"))
    _, r = get(base + "/api/chat/mode")
    assert r["mode"] == "local" and r["key_present"] is True
    _, mp = get(base + "/api/mode")
    assert mp["mode"] == "offline" and mp["network_allowed"] is False
    # 显式切换后才允许联网
    code, s = post(base + "/api/mode", {"mode": "deepseek"})
    assert code == 200 and s["mode"] == "deepseek" and s["network_allowed"] is True
    _, r = get(base + "/api/chat/mode")
    assert r["mode"] == "llm" and r["state_mode"] == "deepseek"
    post(base + "/api/mode", {"mode": "offline"})          # 复原


def test_chat_empty_message_rejected(server):
    _, base = server
    code, r = post(base + "/api/chat", {"message": "   "})
    assert code == 400 and "error" in r


def test_chat_local_mode_without_key(server, monkeypatch):
    """无 key → 本地路由**真的跑工具**，并把结果（含产物哈希）带回来。"""
    m, base = server
    monkeypatch.setattr(m, "load_api_key", lambda: (None, "none"))
    code, r = post(base + "/api/chat", {"message": "一阶谐振在多少 MHz？"})
    assert code == 200 and r["mode"] == "local"
    assert r["tool_trace"], "本地模式也必须真的跑工具，而不是回一句空话"
    assert "离线" in r["reply"] and "非 LLM 生成" in r["reply"]
    assert FAKE_KEY not in json.dumps(r, ensure_ascii=False)


def test_chat_llm_readonly_tool_runs_and_write_tool_only_proposed(server, monkeypatch):
    """读类工具自动执行；写类工具**只提议**，不落任何产物。"""
    m, base = server
    monkeypatch.setattr(m, "load_api_key", lambda: (FAKE_KEY, "unit-test"))
    monkeypatch.setitem(m.STATE, "mode", "deepseek")   # 新契约：有 key 也要**显式**切模式
    monkeypatch.setattr(m, "_llm_call", _fake_llm([
        _tool_call("freeze_gate", {}, "c1"),
        _tool_call("sweep_analysis", {"preset": "cell_te2-exported"}, "c2"),
        {"role": "assistant", "content": "只读项已跑完；写类项等你确认。"},
    ]))
    # 记下写任务的产物指纹，事后必须**逐字节不变**
    out = REPO / "work/runs/remote-exported-20260922/a5/scan_analysis.json"
    before = out.read_bytes() if out.exists() else None
    code, r = post(base + "/api/chat", {"message": "跑一下 A8 和 A5"})
    assert code == 200 and r["mode"] == "llm"
    assert [t["task"] for t in r["tool_trace"]] == ["freeze_gate"]
    assert r["tool_trace"][0]["result"]["verdict"] in ("passed", "failed", "inconclusive")
    assert len(r["pending"]) == 1 and r["pending"][0]["needs_confirmation"] is True
    assert r["pending"][0]["task"] == "sweep_analysis"
    after = out.read_bytes() if out.exists() else None
    assert after == before, "未确认的写任务绝不能落盘"
    assert FAKE_KEY not in json.dumps(r, ensure_ascii=False)


def test_chat_llm_unknown_tool_rejected(server, monkeypatch):
    """模型点名一个没登记的工具 → 拒绝，不执行、不提议。"""
    m, base = server
    monkeypatch.setattr(m, "load_api_key", lambda: (FAKE_KEY, "unit-test"))
    monkeypatch.setitem(m.STATE, "mode", "deepseek")   # 新契约：有 key 也要**显式**切模式
    monkeypatch.setattr(m, "_llm_call", _fake_llm([
        _tool_call("run_shell", {"cmd": "rm -rf /"}, "c1"),
        {"role": "assistant", "content": "该工具不存在。"},
    ]))
    n0 = len(m.JOBS)
    code, r = post(base + "/api/chat", {"message": "帮我删掉所有东西"})
    assert code == 200 and r["tool_trace"] == [] and r["pending"] == []
    assert len(m.JOBS) == n0


def test_chat_llm_failure_falls_back_to_local(server, monkeypatch):
    """LLM 抛错（网络/配额）→ 降级到本地路由，且**明确说明**降级原因。"""
    m, base = server
    monkeypatch.setattr(m, "load_api_key", lambda: (FAKE_KEY, "unit-test"))
    monkeypatch.setitem(m.STATE, "mode", "deepseek")   # 新契约：有 key 也要**显式**切模式
    def boom(messages, tools, *, timeout=90):
        raise RuntimeError("stub network down")
    monkeypatch.setattr(m, "_llm_call", boom)
    code, r = post(base + "/api/chat", {"message": "远端清单"})
    assert code == 200 and r["mode"] == "local" and "LLM 不可用" in r["reply"]
    assert r["tool_trace"], "降级后仍应真的跑本地工具"


def test_chat_frontend_is_conversational(server):
    """前端形态：主对话框 + 侧栏功能选择 + 待确认卡片 + 模式徽章 + 代理面板。"""
    _, base = server
    with urllib.request.urlopen(base + "/", timeout=30) as r:
        html = r.read().decode("utf-8")
    for needle in ('id="log"', 'id="inp"', 'id="tasks"', 'id="pMode"', 'id="nav"',
                   "/api/chat", "/api/mode", "/api/surrogate/predict",
                   "允许执行", "需要确认", "写产物（会确认）",
                   "不是 AI 求解器", "拒答"):
        assert needle in html, needle


def test_chat_preroute_write_gives_confirm_card_without_model_cooperation(server, monkeypatch):
    """**显式"跑 X" + 写类任务 → 服务端自己挂确认卡**，不依赖模型是否真的发起调用。

    实测踩到的坑：模型会在文字里列出参数并说"等你点『允许执行』"，却**一次工具调用都没发**，
    于是前端根本渲染不出卡片——文字与事实不一致。预路由把这件事从模型自觉改成代码事实。"""
    m, base = server
    monkeypatch.setattr(m, "load_api_key", lambda: (FAKE_KEY, "unit-test"))
    monkeypatch.setitem(m.STATE, "mode", "deepseek")   # 新契约：有 key 也要**显式**切模式
    # 模型只回一句空话、一个工具都不调，也必须出现确认卡
    monkeypatch.setattr(m, "_llm_call", _fake_llm([
        {"role": "assistant", "content": "好的，我列一下参数，等你确认。"}]))
    out = REPO / "work/runs/remote-exported-20260922/a5/scan_analysis.json"
    before = out.read_bytes() if out.exists() else None
    code, r = post(base + "/api/chat", {"message": "跑一下 A5 排名，给我分族榜首"})
    assert code == 200 and r["mode"] == "llm"
    assert [p["task"] for p in r["pending"]] == ["sweep_analysis"]
    assert r["pending"][0]["needs_confirmation"] is True
    assert m.TASKS["sweep_analysis"]["writes"] is True
    assert (out.read_bytes() if out.exists() else None) == before, "预路由也不许替用户确认写任务"
    # 模型重复调用同一个任务 → 不产生第二张卡
    monkeypatch.setattr(m, "_llm_call", _fake_llm([
        _tool_call("sweep_analysis", {}, "c1"), {"role": "assistant", "content": "已提议。"}]))
    _, r2 = post(base + "/api/chat", {"message": "执行 A5 排名"})
    assert [p["task"] for p in r2["pending"]] == ["sweep_analysis"], "同一任务不得重复挂卡"
    assert r2["tool_trace"] == []


def test_chat_preroute_readonly_runs_without_model(server, monkeypatch):
    """显式"跑 X" + 只读任务 → 直接跑出真结果（模型不必配合）。"""
    m, base = server
    monkeypatch.setattr(m, "load_api_key", lambda: (FAKE_KEY, "unit-test"))
    monkeypatch.setitem(m.STATE, "mode", "deepseek")   # 新契约：有 key 也要**显式**切模式
    monkeypatch.setattr(m, "_llm_call", _fake_llm([
        {"role": "assistant", "content": "已执行。"}]))
    code, r = post(base + "/api/chat", {"message": "执行 冻结门禁"})
    assert code == 200
    assert [t["task"] for t in r["tool_trace"]] == ["freeze_gate"]
    assert r["tool_trace"][0]["result"]["verdict"] in ("passed", "failed", "inconclusive")
    assert r["pending"] == []


def test_chat_falls_back_to_route_when_model_calls_no_tool(server, monkeypatch):
    """模型一次工具都没调 → 服务端按本地路由补跑，**回答不悬空**（红线：没有证据不出数字）。"""
    m, base = server
    monkeypatch.setattr(m, "load_api_key", lambda: (FAKE_KEY, "unit-test"))
    monkeypatch.setitem(m.STATE, "mode", "deepseek")   # 新契约：有 key 也要**显式**切模式
    monkeypatch.setattr(m, "_llm_call", _fake_llm([
        {"role": "assistant", "content": "镜像应该是好的。"}]))
    code, r = post(base + "/api/chat", {"message": "本地镜像和远端哈希对不对得上"})
    assert code == 200 and [t["task"] for t in r["tool_trace"]] == ["verify_mirror"]
    assert r["tool_trace"][0]["result"]["verdict"] in ("passed", "failed")
    assert "模型未调用工具" in r["reply"]
    # 与路由无关的闲聊不硬塞工具
    monkeypatch.setattr(m, "_llm_call", _fake_llm([
        {"role": "assistant", "content": "你好，有什么要查的？"}]))
    _, r2 = post(base + "/api/chat", {"message": "你好呀"})
    assert r2["tool_trace"] == [] and r2["pending"] == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
