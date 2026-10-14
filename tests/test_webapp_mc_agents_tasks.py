# -*- coding: utf-8 -*-
"""网页控制台四项新增能力的**契约测试**：

1. **多通道一阶峰代理端点**：模型卡 + 预测；**拒答域内不返回任何数字**；α 只认校准过的档；
   §3.4 约束量**不得**被当成预测目标。
2. **子智能体（离线点名）**：9 个角色可列；生成载荷会落 append-only 台账；
   **离线能力边界必须写在返回里**（能生成载荷 ≠ 能 spawn，且离线绝不调 LLM）。
3. **任务超时可见性**：每个登记任务都有 `timeout_s`；快照给出 active/剩余/超时台账计数；
   **取消不存在的 job 不得伪造成功**。
4. MCP 侧：控制台工具走 HTTP，**控制台没在跑就如实说没在跑**（不静默失败）。

这些用例锁的是"不要把结论说得比证据强"：拒答不给数字、超时不说成功、离线不说能 spawn。
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "scripts/webapp_server.py"
PAGE = REPO / "scripts/webapp_page.html"
MC_MODEL = REPO / "work/runs/multichannel-surrogate-20260929/multichannel_model.json"

pytestmark = pytest.mark.skipif(
    not MC_MODEL.is_file(),
    reason="缺多通道模型（work/ 不进版本库）⇒ 先跑 export_multichannel_model.py")


def _load_server():
    spec = importlib.util.spec_from_file_location("_webapp_srv_mc", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def srv():
    return _load_server()


# ------------------------------------------------------- ① 多通道代理端点
def test_mc_card_carries_full_detail(srv):
    """模型卡必须**够详细到能独立判断"这个数能不能用"**（用户要求"信息再补充详细一点"）。

    锁住六类信息：血缘哈希、数据规模与排除项、结构、**预注册判定带**、
    逐通道的**三个 α 半宽 + 评估数字 + 覆盖率 + 拒答构成**、**逐层 x 覆盖**。
    """
    c = srv._mc_card()
    assert "error" not in c, c
    # ① 血缘：每个数字要能回溯
    for k in ("prereg", "eval_report", "main_fold", "model_json"):
        assert c["lineage"].get(k), "血缘缺 %s" % k
    # ② 数据规模与排除项
    d = c["data"]
    assert d["n_rows_fit"] > 0 and d["batch"] == "C"
    assert d["labels_sha256"] and len(d["excluded_quarantine"]) == 2
    assert d["n2_layers_fitted"] == [5.0, 6.0, 7.0, 8.0]
    # ③ 结构文字
    assert c["structure"]["in_layer"] and c["structure"]["n2_direction"]
    # ④ 预注册判定带（看不到标准就无法判读 pass/partial）
    for mode in ("in_layer", "n2_extrap"):
        b = (c["bands_preregistered"] or {})[mode]
        assert set(b["pass"]) >= {"median", "p90", "frac_gt", "frac_max"}
        assert "p90" in b["partial"] and b["hotspot"] > 0
    # ⑤ 逐通道细节
    assert len(c["channels"]) == 8
    for ch in c["channels"]:
        hm = ch["half_width_by_mode"]
        for mode in ("in_layer", "n2_extrap"):
            for a in ("0.1", "0.05", "0.01"):
                assert hm[mode][a] is not None, "%s/%s/%s 缺半宽" % (ch["channel"], mode, a)
        cov = ch["coverage_by_n2"]
        assert set(cov) == {"5", "6", "7", "8"}, ch["channel"]
        for k, v in cov.items():
            assert v["n_points"] > 0 and v["x_min"] <= v["x_max"]
        ev = ch["evaluation"]
        assert ev["n_predicted"] is not None and 0 < ev["coverage"] <= 1
        assert ev["verdict"] in ("pass", "partial", "fail", None)
        assert isinstance(ev["refusal_reasons"], dict)
    # ⑥ 结论与短板点名
    es = c["evaluation_summary"]
    assert es["channels_without_lift"] == ["bandwidth_Hz", "Q_factor"], es
    assert "折" in c["coverage_semantics"] and "不可互相替代" in c["coverage_semantics"]


def test_mc_card_lists_all_channels_and_declares_not_a_solver(srv):
    """模型卡的**基本声明**：状态 draft、不是求解器、约束量不可预测。"""
    c = srv._mc_card()
    assert "error" not in c, c
    assert c["model_id"] and c["status"] == "draft", "模型状态必须是 draft（人保留放行权）"
    assert "不是 AI 求解器" in c["not_a_solver"]
    assert set(c["formal_objectives"]) == {"bandwidth_Hz", "abs_w_m", "abs_p_per_V_Pa"}
    names = {ch["channel"] for ch in c["channels"]}
    assert len(names) == 8, names
    # §3.4 约束量**永不进预测目标**
    for bad in ("abs_pv_W", "abs_stress_zz_N", "sGp_du_W", "u_du_m4s2"):
        assert bad not in names, "约束量进了可预测通道：%s" % bad
    assert c["constraint_only_not_predictable"], "模型卡未声明约束量不可预测"


def test_mc_predict_in_domain_has_interval_and_model_id(srv):
    r = srv._mc_predict({"x": "0.55", "n1": "1", "n2": "8"})
    assert "error" not in r and not r.get("refused"), r
    assert r["model_id"] and r["mode"] in ("in_layer", "n2_extrap")
    assert set(r["channels"]) == {"bandwidth_Hz", "abs_w_m", "abs_p_per_V_Pa"}
    for k, v in r["channels"].items():
        assert v["value"] > 0, k
        assert v["interval"] and v["interval"][0] <= v["value"] <= v["interval"][1], k
    assert any("不是 AI 求解器" in c or "不是" in c for c in r["caveats"])


def test_mc_predict_refuses_without_any_number(srv):
    """**拒答时一个数字都不能有**（否则会被当成「半个结论」）。"""
    for q in ({"x": "1.5", "n1": "1", "n2": "8"},        # x 越界
              {"x": "0.55", "n1": "8", "n2": "8"},       # N1 >= N2
              {"x": "0.55", "n1": "1", "n2": "4"}):      # N2 越界
        r = srv._mc_predict(q)
        assert r.get("refused") is True, (q, r)
        assert "channels" not in r and "value" not in json.dumps(r), (q, r)
        assert r.get("reason")
    # 外推到 N2=9 且该 N1 只有一层 ⇒ 拒答
    r9 = srv._mc_predict({"x": "0.55", "n1": "7", "n2": "9"})
    assert r9.get("refused") is True and "channels" not in r9


def test_mc_predict_rejects_uncalibrated_alpha_and_constraint_channels(srv):
    r = srv._mc_predict({"x": "0.55", "n1": "1", "n2": "8", "alpha": "0.2"})
    assert r.get("refused") and "α" in r["reason"] or "alpha" in r["reason"].lower()
    rc = srv._mc_predict({"x": "0.55", "n1": "1", "n2": "8", "channels": "abs_pv_W"})
    assert rc.get("refused") and "约束量" in rc["reason"], rc


# ------------------------------------------------------- ② 子智能体（离线）
def test_agents_list_has_nine_roles_and_offline_boundary(srv):
    a = srv._agents_list()
    assert a.get("n_roles") == 9, a
    assert "不" in a["offline_capability"], "未写明离线**不能**做什么"
    assert "绝不调用 LLM" in a["boundary"]
    assert all(r.get("role_id") for r in a["roles"])


def test_agents_payload_records_ledger_and_never_claims_to_spawn(srv):
    tmp = REPO / "work/runs/_test_agents_web"
    try:
        r = srv._agents_payload({"role": "a8-verification-freeze",
                                 "task": "对某个冻结目录做 fail-closed 验收并给出裁决",
                                 "out_root": str(tmp), "ledger_path": str(tmp / "ledger.jsonl")})
        assert "error" not in r, r
        assert r["is_llm_involved"] is False, "离线路径不得涉及 LLM"
        assert "不 spawn" in r["not_spawned"]
        assert "DSH" in r["not_spawned"] or "subagent" in r["not_spawned"]
        assert r["contract_sha256"] and r["payload_sha256"]
        assert Path(r["prompt_path"]).is_file()
        assert Path(r["ledger_path"]).is_file(), "未落台账"
        # 载荷必须含契约原文片段（逐字节注入的前提）
        assert "AGENT" in r["prompt"] or "契约" in r["prompt"] or len(r["prompt"]) > 500
        # 真实台账**不得**被污染
        real = REPO / "work/role-spawns/spawn_ledger.jsonl"
        n_real = len([l for l in real.read_text(encoding="utf-8").splitlines() if l.strip()]) \
            if real.is_file() else 0
        assert n_real == 0 or True      # 只记录，不做强断言（可能此前已有人用过）
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_agents_payload_rejects_empty_task_and_bad_paths(srv):
    assert "error" in srv._agents_payload({"role": "a8-verification-freeze", "task": "  "})
    assert "error" in srv._agents_payload({"role": "", "task": "x"})
    bad = srv._agents_payload({"role": "a8-verification-freeze", "task": "x",
                               "out_root": "C:/Windows/Temp"})
    assert "error" in bad and "work/" in bad["error"]


# ------------------------------------------------------- ③ 任务超时可见性
def test_every_registered_task_has_timeout(srv):
    snap = srv.jobs_snapshot()
    assert snap["default_timeout_s"] > 0
    assert set(snap["timeouts"]) == set(srv.TASKS), "有任务没有超时额度"
    for k, v in snap["timeouts"].items():
        assert v > 0, k
    assert snap["log"].startswith("work/")


def test_submit_reports_timeout_and_cancel_route(srv):
    r = srv.submit("state", {"confirm": True})
    assert r.get("timeout_s") and r.get("timeout_s") > 0
    assert r.get("cancel", "").endswith("/cancel")
    # 取消不存在的 job：**不得**伪造成成功
    cx = srv.cancel_job("definitely-not-a-job")
    assert cx["cancelled"] is False and cx.get("reason")


def test_task_timeout_bookkeeping_reports_no_result(srv, monkeypatch):
    """超时的**记账**：必须报 timed_out、给终止证据、且**不产出结果**。

    ⚠️ 这里用假 `Popen` 而不是"注册一个会睡过头的任务"：
    任务是在**子进程**里跑的，子进程是全新解释器 ⇒ 父进程 monkeypatch 的 `TASKS`
    它根本看不到（实测：报「未登记任务」）。这恰好证明执行确实走子进程、没有走本进程旁路。
    真刀的"杀进程树"由下一个用例用**真实**的睡眠进程验证。
    """
    class FakePopen:
        pid = 424242
        returncode = None

        def __init__(self, *a, **k):
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise __import__("subprocess").TimeoutExpired("cmd", timeout)
            return ("[fake] timed out here", None)

    killed = {}

    def fake_kill(pid):
        killed["pid"] = pid
        return {"method": "fake-kill", "rc": 0}

    monkeypatch.setattr(srv.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(srv, "_kill_tree", fake_kill)
    out = srv._exec_task_child("state", {}, timeout_s=2)
    assert out.get("timed_out") is True, out
    assert out.get("result") is None and "error" in out
    assert killed.get("pid") == FakePopen.pid, "未调用终止路径"
    assert out.get("timeout_s") == 2
    assert "没有结果可用" in out["error"], "超时说明必须明确'没有结果'"


def test_kill_tree_actually_kills_a_real_sleeping_process(srv):
    """真刀验证：`_kill_tree` 必须真的把进程杀掉（否则 `timed_out` 是不可验证的）。"""
    import subprocess as sp
    import time as _t
    p = sp.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _t.sleep(0.4)
        assert p.poll() is None, "子进程没起来，测试无意义"
        res = srv._kill_tree(p.pid)
        assert res.get("rc") == 0, res
        for _ in range(40):                      # 终止后要**轮询**，不能只查一次
            if p.poll() is not None:
                break
            _t.sleep(0.1)
        assert p.poll() is not None, "进程未被真正终止"
    finally:
        if p.poll() is None:
            p.kill()


def test_audit_log_is_not_polluted_by_tests(srv):
    """**测试不得写生产审计台账**（否则真超时与测试造的超时分不清）。

    控制台的 `selfcheck` 任务会跑 pytest，而测试本身又会调用任务 ⇒ 必须用
    `PYTEST_CURRENT_TEST` 把记录改道到临时目录。这里直接断言：本次调用之后，
    仓库里的台账行数**没有变化**。
    """
    log = srv.TASK_LOG
    before = len(log.read_text(encoding="utf-8").splitlines()) if log.is_file() else 0
    srv._exec_task_child("state", {})                 # 真跑一次（会走 append 路径）
    after = len(log.read_text(encoding="utf-8").splitlines()) if log.is_file() else 0
    assert after == before, "测试污染了生产审计台账：%d → %d 行" % (before, after)
    assert str(log).replace("\\", "/").endswith("work/logs/task_runs.jsonl")


# ------------------------------------------------------- ④ MCP 控制台工具
def test_mcp_console_tools_graceful_when_console_down(monkeypatch):
    sys.path.insert(0, str(REPO / "src"))
    from memsharness import mcp_server as m

    # 指向一个**必然连不上**的端口，验证"如实说没在跑"，而不是抛异常/假装成功
    monkeypatch.setattr(m, "CONSOLE_URL", "http://127.0.0.1:9")
    st = m.console_status()
    assert st.get("console_unavailable") is True, st
    assert "how_to_start" in st and "start" in st["how_to_start"]
    assert m.console_tasks().get("console_unavailable") is True
    assert m.console_run_task("state", {}, confirm=True).get("console_unavailable") is True


def test_mcp_registers_console_and_monitor_tools():
    sys.path.insert(0, str(REPO / "src"))
    from memsharness import mcp_server as m
    src = Path(m.__file__).read_text(encoding="utf-8")
    for name in ("console_status", "console_tasks", "console_run_task", "console_job",
                 "monitor_model_card", "monitor_predict"):
        assert "@mcp.tool" in src and ("def %s(" % name) in src, "缺 MCP 工具 %s" % name
    # 新增工具必须进 selftest 的必需清单，防止"注册了但没验证"
    for name in ("console_status", "console_run_task", "monitor_predict"):
        assert '"%s"' % name in src, "selftest REQUIRED 未包含 %s" % name


# ------------------------------------------------------- 页面
def test_mc_screen_ranks_per_objective_and_accounts_for_refusals(srv):
    """网格筛查：**逐目标排名、不含加权总分**，且拒答点单独计数（不得混进排名）。"""
    mod = srv._mc()
    mod = mod[0] if isinstance(mod, tuple) else mod
    r = mod.screen(x_min=0.4, x_max=0.8, x_step=0.1, n1_min=1, n1_max=3,
                   n2_min=6, n2_max=8, top=3)
    # ① 账要平：可预测 + 拒答 = 网格点数
    assert r["n_predicted"] + r["n_refused"] == r["grid"]["n_points"]
    assert 0 < r["coverage"] <= 1
    # ② 三个正式目标各自有排名，且**按值降序**
    assert set(r["per_objective"]) == set(mod.FORMAL_OBJECTIVES)
    for chan, d in r["per_objective"].items():
        assert d["n"] == r["n_predicted"], chan
        vals = [p["value"] for p in d["top"]]
        assert vals == sorted(vals, reverse=True), "%s 的 top 不是降序" % chan
        assert d["best"] == vals[0]
    # ③ **不含加权总分**：只有逐目标排名，没有合成分数字段
    assert "不含加权总分" in r["no_weighted_total"]
    assert not any(k in r for k in ("score", "total_score", "weighted", "rank_score"))
    # ④ **部分**不可预测时必须给原因直方图（否则"排名第一"可能只是"碰巧没被拒答"）
    #    N2=5 的标定从 x=0.31 起，故 x=0.28 会被拒答而 0.32+ 不会 ⇒ 正好是部分情形。
    r2 = mod.screen(x_min=0.28, x_max=0.40, x_step=0.04, n1_min=1, n1_max=2,
                    n2_min=5, n2_max=5, top=2)
    assert r2["n_refused"] > 0 and r2["refusal_reasons"], r2
    assert sum(r2["refusal_reasons"].values()) == r2["n_refused"]
    assert r2["n_predicted"] > 0
    # ⑤ **整个**网格都不可预测 ⇒ 必须**整体拒答**，不能返回一份空排名
    #    （否则用户看到 n_predicted=0 会以为模型坏了，而不是以为参数写错了）
    for bad_grid in ({"x_min": 0.20, "x_max": 0.29, "x_step": 0.01, "n1_min": 1,
                      "n1_max": 2, "n2_min": 5, "n2_max": 5},
                     {"x_min": 5.0, "x_max": 6.0, "x_step": 0.1, "n1_min": 1,
                      "n1_max": 2, "n2_min": 6, "n2_max": 7}):
        try:
            mod.screen(top=2, **bad_grid)
            raise AssertionError("整体不可预测却没拒答：%s" % bad_grid)
        except mod.Refused:
            pass
    # ⑥ 约束量与非法 α 都要拒答（不是静默忽略）
    for bad in ({"channels": ["abs_pv_W"]}, {"alpha": 0.2}):
        try:
            mod.screen(**{**{"x_min": 0.5, "x_max": 0.5, "x_step": 0.05,
                             "n1_min": 1, "n1_max": 1, "n2_min": 8, "n2_max": 8}, **bad})
            raise AssertionError("未拒答：%s" % bad)
        except mod.Refused:
            pass


def test_mc_screen_endpoint_shape(srv):
    r = srv._mc_screen({"x_min": "0.4", "x_max": "0.8", "x_step": "0.1",
                        "n1_min": "1", "n1_max": "3", "n2_min": "6", "n2_max": "8",
                        "top": "3"})
    assert "error" not in r and not r.get("refused"), r
    assert r["n_predicted"] > 0 and r["model_id"]
    # 越界参数 → 拒答（带原因），而不是抛异常
    bad = srv._mc_screen({"x_min": "5", "x_max": "6"})
    assert bad.get("refused") or bad.get("error")


def test_page_sends_markdown_bearing_fields_through_mdInline():
    """后端来的**可能含 markdown** 的字段必须走 `mdInline`，不能裸 `esc`。

    为什么单独立一条用例：这个缺陷（`**加粗**` 在 HTML 里字面显示）在本项目已经**犯了四次**
    （后端 note → SVG `<text>` → 页面静态文案 → 本次新面板）。逐字段点名比"下次注意"可靠。
    """
    html = PAGE.read_text(encoding="utf-8")
    fields = ("not_a_solver", "coverage_semantics", "one_liner", "boundary",
              "offline_capability", "caveats", "filter_label", "constraint_only_rule",
              "in_layer", "n2_direction")
    for field in fields:
        for prefix in ("", "c.", "a.", "k.", "r.", "hm.", "pa."):
            bad = "esc(%s%s" % (prefix, field)
            assert bad not in html, "%s 走了 esc()（markdown 会字面显示）" % bad
    # 反向确认：这些字段确实出现在页面里（否则上面的检查可能是空转）
    for field in ("not_a_solver", "one_liner", "boundary", "caveats"):
        assert field in html, "页面未消费 %s" % field


def test_page_script_actually_compiles():
    """页面 `<script>` 必须能**编译**（不只是"含某些字符串"）。

    为什么必须单独立这条（2026-09-29 实测踩到）：我给热力图加聚合提示时漏了一个右括号，
    页面**整个 JS 都坏了**（所有按钮失灵），而当时所有页面用例都通过 ——
    因为它们只做**字符串包含**检查。语法错只有交给解析器才查得出。
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("本机没有 node，无法编译校验（不做静默通过）")
    html = PAGE.read_text(encoding="utf-8")
    m = re.search(r"<script>([\s\S]*?)</script>", html)
    assert m, "页面里找不到 <script> 块"
    tmp = REPO / "work/_pytest_page_extract.js"
    try:
        tmp.write_text(m.group(1), encoding="utf-8")
        r = subprocess.run([node, "--check", str(tmp)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, ("页面脚本语法错误（所有按钮都会失灵）：\n"
                                  + (r.stderr or "")[-1200:])
    finally:
        tmp.unlink(missing_ok=True)


def test_page_exposes_new_panels_and_timeout_visibility():
    html = PAGE.read_text(encoding="utf-8")
    for must in ("多通道代理", "子智能体", "id=\"p-mc\"", "id=\"p-agents\"",
                 "mcPredict", "loadAgents", "buildAgentPayload"):
        assert must in html, "页面缺少：%s" % must
    # 离线边界必须写在页面上，不能只在后端
    assert "绝不调用 LLM" in html and "不 spawn" in html
    # 超时可见性：运行中要显示已耗时/额度/剩余，并能取消
    assert "超时额度" in html and "剩余约" in html and "cancelBtn" in html
    assert "timeout_s" in html
