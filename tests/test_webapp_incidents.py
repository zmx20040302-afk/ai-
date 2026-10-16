# -*- coding: utf-8 -*-
"""失败通道在**控制台侧**的契约：自动采集各失败面 + 端点行为 + 不外发。

为什么必须有这一层：`tests/test_incidents.py` 只证明"包能生成"；
真正决定这个功能有没有用的是**采集点**——拒答、任务失败、取消、接口异常、
页面异常到底有没有被收上来。少一个采集点，用户就会说"我遇到的那件事没进去"。
"""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "scripts" / "webapp_server.py"

#: 后台替身进程的**命令行标识**（本文件里唯一会用到的替身名）。
_DUMMY_TAG = "slow_dsh.py"
_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _pid_alive(pid: int) -> bool:
    """PID 是否**仍在运行**。

    ⚠️ 本仓教训（AGENTS.md §3，2026-09-14 实测）：**不能用「`OpenProcess` 是否成功」判存活** ——
    目标被终止后，只要父进程仍持有句柄，`OpenProcess` 依然成功 ⇒ 会把「已成功终止」误判成
    「还在跑」。正确判据 = `GetExitCodeProcess(h) == STILL_ACTIVE(259)`。
    """
    if pid is None or int(pid) <= 0:
        return False
    pid = int(pid)
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    h = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False                      # 打不开 ⇒ 进程不存在
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def _powershell() -> str | None:
    """PowerShell 可执行文件（绝对路径优先，找不到就返回 None ⇒ 命令行复检**如实降级**）。"""
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    cand = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(cand) if cand.is_file() else None


def _pids_matching(needle: str = _DUMMY_TAG) -> list[int] | None:
    """命令行里含 `needle` 的 python 进程 PID（`None` = 本机查不了，不假装查过）。

    为什么必须查命令行：`work\\.venv\\Scripts\\python.exe` 是**启动器**，一次 `Popen` 会再 exec 出
    真正的解释器 ⇒ 同一份替身对应 **2 个 OS 进程**，只盯 Popen 的 PID 会漏掉子进程。
    """
    ps = _powershell()
    if ps is None:
        return None
    script = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -like '*%s*' } | "
              "ForEach-Object { [string]$_.ProcessId }" % needle)
    try:
        r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return [int(x) for x in (r.stdout or "").split() if x.strip().isdigit()]


def _report_record(mod, report_id: str) -> dict:
    """从**台账**取这次上报的记录（PID 从台账拿 ⇒ 不依赖 `_PROCS` 还在不在）。"""
    hits = [r for r in mod.load_reports(limit=200)["items"]
            if r.get("report_id") == report_id]
    assert hits, "台账里找不到这次上报：%s" % report_id
    return hits[0]


def _wait_ledger_terminal(mod, report_id: str, *, timeout_s: float = 15.0):
    """等台账从 `running` 落成终态（等待有上限；超时就返回当时的记录，由调用方断言）。"""
    t0 = time.time()
    rec = _report_record(mod, report_id)
    while rec.get("status") == "running" and time.time() - t0 < timeout_s:
        time.sleep(0.2)
        rec = _report_record(mod, report_id)
    return rec, round(time.time() - t0, 2)


def _stop_and_wait_dummy(mod, report_id: str, *, timeout_s: float = 30.0) -> dict:
    """**杀掉替身并等它真的消失**（带超时轮询；不是「发一次信号就断言」）。

    * 存活判据优先用 `Popen.poll()`（同一个句柄 ⇒ 不受 PID 复用影响）；句柄已不在手上时
      退回 `_pid_alive(pid)`（`GetExitCodeProcess == STILL_ACTIVE`）；
    * 除 `taskkill /T /F` 之外，再用**命令行匹配**兜底杀一次（启动器 ＋ 它 exec 出的子进程）；
    * 返回原始测量（`waited_s` / `alive_after` / `leftover_pids` / `kill`），**不吞**。
    """
    rec = _report_record(mod, report_id)
    pid = int(rec["pid"])
    held = mod._PROCS.get(report_id)
    proc = held.get("proc") if isinstance(held, dict) else None   # ⚠️ `_PROCS[rid]` 是 dict，不是 Popen
    kill = [dict(mod._kill_tree(pid))]
    for extra in (_pids_matching() or []):
        if int(extra) != pid:
            kill.append(dict(mod._kill_tree(int(extra))))
    t0 = time.time()
    alive, leftover = True, None
    while True:
        alive = (proc.poll() is None) if proc is not None else _pid_alive(pid)
        leftover = _pids_matching()
        if not alive and leftover in (None, []):
            break
        if time.time() - t0 >= timeout_s:
            break
        time.sleep(0.4)
    waited = round(time.time() - t0, 2)
    alive = (proc.poll() is None) if proc is not None else _pid_alive(pid)
    return {"pid": pid, "kill": kill, "waited_s": waited,
            "alive_after": bool(alive), "leftover_pids": leftover,
            "timed_out": bool(alive) or leftover not in (None, [])}


def _run_dedup_flow(srv, tmp_path, monkeypatch, tag: str = "用例：去重"):
    """跑完整「去重」流程：起替身 → 再来一次必须被去重 → **收尾杀掉并等它消失**。

    收尾放在 `finally` 里 ⇒ 即使中间断言失败，也不会把睡眠进程留给下一个用例。
    返回 `(第二次调用的结果, 第一次调用的结果, 收尾测量)`。**去重语义一字未改**。
    """
    slow = tmp_path / _DUMMY_TAG
    slow.write_text("import time\ntime.sleep(3600)\n", encoding="utf-8", newline="\n")
    monkeypatch.setenv("DSH_BIN", str(slow))
    iid = srv._inc_record({"kind": "manual", "symptom": tag})["incident_id"]
    srv.STATE["mode"] = "deepseek"
    c = srv._dsh_start({"incident_id": iid, "confirm": True})
    assert c.get("report_id"), c
    mod, _ = srv._dsh()
    d = None
    try:
        assert _pid_alive(int(c["pid"])) is True, "替身必须真的起来了（否则本用例什么都没证明）"
        d = srv._dsh_start({"incident_id": iid, "confirm": True})
    finally:
        cleanup = _stop_and_wait_dummy(mod, c["report_id"])
        mod.finish_report(c["report_id"], timeout_s=5)
    return d, c, cleanup


def load_srv():
    spec = importlib.util.spec_from_file_location("_web_inc", SERVER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    """每条用例独立台账/包目录（否则本文件内的用例会互相污染计数）。"""
    monkeypatch.setenv("MEMS_INCIDENTS_LEDGER", str(tmp_path / "led.jsonl"))
    monkeypatch.setenv("MEMS_INCIDENTS_ROOT", str(tmp_path / "pkgs"))
    monkeypatch.setenv("MEMS_DSH_REPORT_LOG", str(tmp_path / "reports.jsonl"))
    m = load_srv()
    m._INC_MOD = None          # 强制重新解析（模块级缓存）
    m._DSH_MOD = None
    return m


def _kinds(m) -> list[str]:
    inc, err = m._inc()
    assert inc is not None, err
    return [i.get("kind") for i in inc.load(limit=50)["items"]]


def test_multi_channel_refusal_is_captured(srv):
    r = srv._mc_predict({"x": "1.5", "n1": "1", "n2": "8"})
    assert r.get("refused"), r
    assert "channels" not in r, "拒答不许带数字"
    assert "refusal" in _kinds(srv)


def test_response_surrogate_refusal_is_captured(srv):
    """响应代理是**返回值**里带 refused（不抛异常）⇒ 必须在出口兜住。"""
    r = srv._predict({"x": 1.5, "N1": 1, "N2": 8})
    assert r.get("refused"), r
    assert "refusal" in _kinds(srv)


def test_unknown_kind_via_endpoint_is_rejected(srv):
    r = srv._inc_record({"kind": "made_up", "symptom": "x"})
    assert "error" in r and "valid_kinds" in r
    assert _kinds(srv) == [], "被拒的上报不许留痕"


def test_manual_record_and_package_endpoints(srv):
    r = srv._inc_record({"kind": "manual", "symptom": "用例：人工上报",
                         "endpoint": "/api/x", "method": "GET", "params": {"a": 1}})
    assert r.get("recorded") and r["incident_id"]
    one = srv._inc_one({"incident_id": r["incident_id"]})
    assert one["record"]["symptom"].startswith("用例")
    assert "## 1. 现象" in one["md"]
    pk = srv._inc_package({"incident_id": r["incident_id"], "write": True})
    assert pk.get("md_path") and Path(pk["md_path"]).is_file()
    again = srv._inc_package({"incident_id": r["incident_id"], "write": True})
    assert "拒绝覆盖" in again["error"]
    lst = srv._inc_list({"limit": "10"})
    assert lst["n_total"] == 1
    # 「不外发」这句话在加入 DSH 上报后**不再准确**（控制台能把它交给 DSH），
    # 所以断言改成新的、更精确的承诺：包只落本机 / 由人按按钮决定 / 离线禁用。
    assert "只落本机" in lst["no_send"] and "按按钮" in lst["no_send"]
    assert "离线" in lst["no_send"]


def test_gpt_incident_analysis_requires_explicit_mode_and_is_append_only(srv, monkeypatch):
    """GPT 只在人确认并切换模式后收到脱敏包；分析落新文件，不改事件与裁决。"""
    iid = srv._inc_record({"kind": "manual", "symptom": "按钮失败",
                           "error_text": "Authorization: Bearer SECRET-CANARY-123456"})["incident_id"]
    blocked = srv._incident_analyze({"incident_id": iid, "provider": "openai", "confirm": True})
    assert blocked.get("blocked_by") == "mode_not_selected"
    monkeypatch.setitem(srv.STATE, "mode", "openai")
    monkeypatch.setattr(srv, "_provider_key", lambda p: ("sk-test", "unit-test"))
    seen = {}
    def fake(messages, tools, *, timeout=90, provider="deepseek"):
        seen["blob"] = json.dumps(messages, ensure_ascii=False)
        return {"choices": [{"message": {"content": "根因未知；先核验端点。"}}],
                "_used": {"provider": provider, "model": "gpt-test"}}
    monkeypatch.setattr(srv, "_llm_call", fake)
    r1 = srv._incident_analyze({"incident_id": iid, "provider": "openai", "confirm": True})
    r2 = srv._incident_analyze({"incident_id": iid, "provider": "openai", "confirm": True})
    assert r1["status"] == "done" and r1["readonly"] is True
    assert Path(r1["analysis_path"]).is_file() and Path(r2["analysis_path"]).is_file()
    assert r1["analysis_path"] != r2["analysis_path"], "分析产物只追加、不覆盖"
    assert "SECRET-CANARY" not in seen["blob"] and "<REDACTED>" in seen["blob"]
    assert "不得改变裁定" in r1["boundary"]


def test_inc_list_survives_bad_limit(srv):
    srv._inc_record({"kind": "manual", "symptom": "x"})
    lst = srv._inc_list({"limit": "not-a-number"})
    assert "error" not in lst and lst["n_total"] == 1


def test_task_failure_is_captured_but_success_is_not(srv):
    """**只收失败**：成功也登记的话，这个通道很快就没人看了。"""
    srv._capture_task_incident("sweep_analysis", {"a": 1},
                               {"task": "sweep_analysis", "duration_s": 1.0}, 300)
    assert _kinds(srv) == [], "成功不得登记"
    srv._capture_task_incident(
        "sweep_analysis", {"a": 1},
        {"task": "sweep_analysis", "error": "boom", "stdout": "raw output"}, 300)
    assert _kinds(srv) == ["task_failed"]
    inc, _ = srv._inc()
    rec = inc.load()["items"][0]
    assert "boom" in rec["error_text"] and "raw output" in rec["error_text"], \
        "原始错误全文（含子进程输出）必须进包"
    srv._capture_task_incident("x", {}, {"timed_out": True, "timeout_s": 300}, 300)
    assert "task_timeout" in _kinds(srv)


def test_cancel_of_dead_job_is_not_recorded(srv):
    """取消一个已结束的 job 是**正常回应**，不该进失败通道（否则会误导）。"""
    cx = srv.cancel_job("no-such-job")
    assert cx["cancelled"] is False
    assert _kinds(srv) == []


def test_api_error_records_full_stack(srv):
    mod, _ = srv._inc()
    try:
        raise RuntimeError("故意炸一次")
    except RuntimeError as exc:
        srv._record_api_error(exc, "GET", "/api/boom", "FAKE-TRACEBACK")
    rec = mod.load()["items"][0]
    assert rec["kind"] == "api_error" and rec["endpoint"] == "/api/boom"
    assert rec["stack"] == "FAKE-TRACEBACK" and "RuntimeError" in rec["error_text"]


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_unhandled_route_exception_returns_500_and_is_recorded(tmp_path, monkeypatch):
    """真打 HTTP：路由内部抛异常 ⇒ 500 + 记进台账（前端才拿得到 incident_id 线索）。"""
    monkeypatch.setenv("MEMS_INCIDENTS_LEDGER", str(tmp_path / "led.jsonl"))
    monkeypatch.setenv("MEMS_INCIDENTS_ROOT", str(tmp_path / "pkgs"))
    m = load_srv()
    m._INC_MOD = None
    from http.server import ThreadingHTTPServer

    def boom():
        raise RuntimeError("路由炸了")

    monkeypatch.setattr(m, "_glossary", boom)
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), m.Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    try:
        url = "http://127.0.0.1:%d/api/glossary" % port
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url, timeout=30)
        assert e.value.code == 500
        body = json.loads(e.value.read().decode("utf-8"))
        assert "失败通道" in body["error"] and body["path"] == "/api/glossary"
    finally:
        server.shutdown()
        server.server_close()
    inc, _ = m._inc()
    rec = inc.load()["items"][0]
    assert rec["kind"] == "api_error" and "RuntimeError" in rec["error_text"]
    assert "boo" in rec["stack"] or "RuntimeError" in rec["stack"]


def test_diagnostic_requests_can_opt_out_of_incident_capture(tmp_path, monkeypatch):
    """例行复检/探针会**故意**制造拒答 ⇒ 必须能声明「别登记」。

    实测动机：一次两轮复检就往生产台账塞了 2 条 refusal，把通道稀释成机器噪音。
    这里同时验**反向**：不带标记时必须登记（否则"opt-out"会把功能一起关掉）。
    """
    monkeypatch.setenv("MEMS_INCIDENTS_LEDGER", str(tmp_path / "led.jsonl"))
    monkeypatch.setenv("MEMS_INCIDENTS_ROOT", str(tmp_path / "pkgs"))
    m = load_srv()
    m._INC_MOD = None
    from http.server import ThreadingHTTPServer

    inc, _ = m._inc()
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), m.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.3)
    base = "http://127.0.0.1:%d/api/mc/predict?x=1.5&n1=1&n2=8" % port
    try:
        with urllib.request.urlopen(base, timeout=30) as r:
            assert json.loads(r.read().decode("utf-8")).get("refused")
        assert inc.load()["n_total"] == 1, "不带标记的拒答**必须**登记"

        req = urllib.request.Request(base, headers={"X-MEMS-No-Incident": "1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            assert json.loads(r.read().decode("utf-8")).get("refused"), "仍要照常拒答"
        assert inc.load()["n_total"] == 1, "带头部标记的不得登记"

        with urllib.request.urlopen(base + "&no_incident=1", timeout=30) as r:
            assert json.loads(r.read().decode("utf-8")).get("refused")
        assert inc.load()["n_total"] == 1, "带查询参数的不得登记"
    finally:
        server.shutdown()
        server.server_close()


def test_dsh_report_endpoint_gates_and_happy_path(srv, tmp_path, monkeypatch):
    """三条口径都要是**代码门禁**：离线禁、需确认、只读。

    全程用 `DSH_BIN` 指向替身 ⇒ 测试绝不启动真实 headless DSH（会花 token）。
    """
    fake = tmp_path / "fake_dsh.py"
    fake.write_text("import sys\nprint('FAKE-ANALYSIS 根因=演示')\n", encoding="utf-8",
                    newline="\n")
    monkeypatch.setenv("DSH_BIN", str(fake))
    r = srv._inc_record({"kind": "manual", "symptom": "用例：要上报给 DSH"})
    iid = r["incident_id"]

    # ① 离线模式禁止（用户选的第三条）
    srv.STATE["mode"] = "offline"
    a = srv._dsh_start({"incident_id": iid, "confirm": True})
    assert a.get("blocked_by") == "offline_mode", a
    assert "离线" in a["error"]
    # ② DeepSeek 模式但没确认 ⇒ 要确认（花 token 的动作）
    srv.STATE["mode"] = "deepseek"
    b = srv._dsh_start({"incident_id": iid})
    assert b.get("needs_confirmation") is True, b
    # ③ 确认后启动；报告可查且**声明只读**
    c = srv._dsh_start({"incident_id": iid, "confirm": True})
    assert c.get("report_id") and c.get("readonly") is True, c
    assert c.get("job_id")
    rep = srv._dsh_reports({"incident_id": iid})
    assert rep["allowed"] is True and rep["readonly"] is True
    assert rep["dsh_available"] is True, rep.get("dsh_how")
    assert any("不得修改" in x for x in rep["rules"]), "边界必须写清只读"
    assert rep["n_total"] >= 1
    # ④ 不存在的条目要如实报错
    assert "error" in srv._dsh_start({"incident_id": "inc-nope", "confirm": True})


def test_dsh_report_endpoint_dedups_a_running_report(srv, tmp_path, monkeypatch):
    """同一条失败**不许并行重复跑**（去重语义本用例被测对象，**未削弱**）。

    收尾必须**杀掉替身并等它消失**（带超时轮询复核）—— 缺陷背景：旧收尾写的是
    `for rid, proc in mod._PROCS.items(): mod._kill_tree(proc.pid)`，而
    `_PROCS[rid]` 是 **dict**（`{"proc": Popen, "log": …}`）不是 Popen ⇒ 一旦该条目还在就
    `AttributeError`，而更常见的是后台 `_dsh_wait` 线程早已把它 `pop` 走 ⇒ 循环体**一次都没执行**，
    于是每次全量 pytest 都漏下 `slow_dsh.py` 睡眠进程（`§140.5` 登记）。
    """
    d, c, cleanup = _run_dedup_flow(srv, tmp_path, monkeypatch)
    assert "已有一个上报在跑" in d["error"], d
    assert c.get("report_id")
    assert cleanup["timed_out"] is False, cleanup
    assert cleanup["alive_after"] is False, cleanup
    assert cleanup["leftover_pids"] in (None, []), cleanup
    print("去重用例收尾实测：pid=%s waited_s=%.2f kill=%r leftover=%r"
          % (cleanup["pid"], cleanup["waited_s"], cleanup["kill"], cleanup["leftover_pids"]))


def test_dsh_dedup_case_leaves_no_live_dummy_process(srv, tmp_path, monkeypatch):
    """**跑完去重流程后，必须一个替身进程都不剩**（PID 复检 ＋ 命令行匹配，双重）。

    * PID 复检用 `GetExitCodeProcess(h) == STILL_ACTIVE(259)`——**不用 `OpenProcess` 能否成功**
      （本仓教训，AGENTS.md §3：目标被终止后只要父进程还持句柄，`OpenProcess` 依然成功）；
    * 命令行匹配是**必要**补充：`work\\.venv\\Scripts\\python.exe` 是一次 spawn 会再 exec 出
      真正解释器的**启动器** ⇒ 同一份替身有 **2 个 OS 进程**（实测 PID 114736 → 121816），
      只盯 Popen 拿到的那个 PID 会漏掉子进程；
    * 台账里也不许还挂着 `status == "running"`（终态必须回填）。
    """
    d, c, cleanup = _run_dedup_flow(srv, tmp_path, monkeypatch)
    assert "已有一个上报在跑" in d["error"], d
    assert cleanup["alive_after"] is False, cleanup
    assert cleanup["leftover_pids"] in (None, []), cleanup
    mod, _ = srv._dsh()
    rec, waited = _wait_ledger_terminal(mod, c["report_id"], timeout_s=15)
    assert rec.get("status") != "running", (rec, waited)
    still = [r for r in mod.load_reports(limit=200)["items"] if r.get("status") == "running"]
    assert still == [], still
    print("无遗留实测：pid=%s waited_s=%.2f kill=%r leftover=%r 台账终态=%s（等了 %.2fs）"
          % (cleanup["pid"], cleanup["waited_s"], cleanup["kill"], cleanup["leftover_pids"],
             rec.get("status"), waited))


def test_failure_pops_up_a_report_button_and_has_no_dedicated_panel():
    """用户口径（2026-09-30）：**失败时弹上报按钮、不要单独分区、报不报由人点**。

    这条把三件事都变成机器可检的：
    ① 侧栏里**没有**失败通道分区，页面里**没有** `p-inc` 面板；
    ② 失败会**自动弹窗**（`#popups` + `popFailure`），并且服务端侧失败靠轮询捞回来；
    ③ 弹窗里**不会自动上报** —— `incDsh(` 只出现在点击处理器里。
    """
    html = (REPO / "scripts" / "webapp_page.html").read_text(encoding="utf-8")
    # ① 不再有单独分区
    assert 'id="p-inc"' not in html, "失败通道分区应当已移除"
    assert "['inc','失败通道']" not in html, "侧栏不应再有失败通道入口"
    # ② 弹出式入口 + 轮询
    for must in ('id="popups"', 'id="incDlg"', 'id="bIncOpen"', 'id="errBadge"',
                 'id="bIncClose"', "popFailure", "pollIncidents", "startIncPoll",
                 "incUploadLocal"):
        assert must in html, "页面缺少：%s" % must
    # 顶栏入口必须**始终可见**（不再依赖分区），对话框默认隐藏
    assert 'id="bIncOpen"' in html and 'id="incDlg" class="dlg"' in html \
        or 'class="dlg" id="incDlg"' in html
    # ③ 不自动上报：弹窗只在点击处理器里调上报
    body = html[html.index("function popFailure("):html.index("async function pollIncidents(")]
    assert "incDsh(" in body, "弹窗要有上报按钮"
    assert body.index("onclick=") < body.index("incDsh("), \
        "incDsh 必须在点击处理器里（不许自动上报）"
    assert "不会自动上报" in body
    # 「异常 → 弹窗」这条**接线**也要静态锁住：窗口 error / unhandledrejection 都走 showError，
    # 而 showError 调 incReportPage，incReportPage 成功后调 popFailure。
    err_body = html[html.index("function incReportPage("):html.index("async function loadInc(")]
    assert "popFailure(" in err_body, "页面异常必须走到弹窗（否则失败时不会提示上报）"
    assert "window.addEventListener('error'" in html \
        and "window.addEventListener('unhandledrejection'" in html, "两类页面异常都要接住"
    # 承诺仍要当场看得见
    for must in ("包只落本机", "不含任何分析结论", "不得改变裁定",
                 "不改仓库里任何文件", "离线模式下这个按钮被禁用"):
        assert must in html, "页面缺少承诺：%s" % must
    assert "esc(it.symptom" not in html, "it.symptom 走了 esc()"
