# -*- coding: utf-8 -*-
"""网页控制台的契约测试：**双模式开关 + 代理端点 + 页面措辞锁**。

锁住的裁定/红线：
* **默认离线**（绝不默认联网）；无凭据时**拒绝**切到 DeepSeek（不能"切了其实没凭据"）；
* **离线模式下绝不调用 LLM**（这条必须是真的：把 `_llm_call` 换成会抛异常的替身，仍须正常回答）；
* 代理端点在**拒答域内不返回任何数字**；正常预测必须带 `model_id` + `certified` + 区间；
* 页面源码里**必须**有「不是 AI 求解器」等声明，且**不得**出现「免 COMSOL 出解」等反措辞；
* 非回环绑定必须带令牌（fail-closed），回环不需要。
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "scripts/webapp_server.py"
PAGE = REPO / "scripts/webapp_page.html"
SURR_DIR = REPO / "work/runs/surrogate-response-20260929"


def _load_server():
    spec = importlib.util.spec_from_file_location("_webapp_srv_test", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def srv():
    return _load_server()


@pytest.fixture(scope="module")
def http(srv):
    """真起一个回环 HTTP 服务（端口 0 自动分配），用完关掉。"""
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    yield base
    server.shutdown()
    server.server_close()


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(base: str, path: str, body: dict):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


# ---------------------------------------------------------------- 模式
def test_default_mode_is_offline(srv):
    srv.STATE["mode"] = "offline"
    p = srv.mode_payload()
    assert p["mode"] == "offline" and p["network_allowed"] is False


def test_reject_unknown_mode(srv):
    assert "error" in srv.set_mode("turbo")


def test_set_mode_deepseek_refused_without_key(srv, monkeypatch):
    monkeypatch.setattr(srv, "load_api_key", lambda: (None, "none"))
    r = srv.set_mode("deepseek")
    assert "error" in r and "未检测到 API key" in r["error"]
    assert srv.STATE["mode"] == "offline"          # 拒绝后**不得**改状态


def test_set_mode_deepseek_ok_with_key(srv, monkeypatch):
    monkeypatch.setattr(srv, "load_api_key", lambda: ("sk-test", "env:TEST"))
    r = srv.set_mode("deepseek")
    assert r["mode"] == "deepseek" and r["network_allowed"] is True
    srv.STATE["mode"] = "offline"                   # 复原


# ---------------------------------------------------------------- 离线绝不联网
def test_offline_chat_never_calls_llm(srv, monkeypatch):
    """把 `_llm_call` 换成**会抛异常**的替身；离线模式下仍必须正常回答。"""
    monkeypatch.setattr(srv, "load_api_key", lambda: ("sk-test", "env:TEST"))
    srv.STATE["mode"] = "offline"

    def boom(*a, **k):
        raise AssertionError("离线模式下不得调用 LLM！")

    monkeypatch.setattr(srv, "_llm_call", boom)
    res = srv.do_chat({"message": "校验镜像", "history": []})
    assert "error" not in res
    assert res["mode"] == "local"
    assert "离线" in res["reply"] and "非 LLM 生成" in res["reply"]


def test_deepseek_mode_requires_key_at_call_time(srv, monkeypatch):
    """切到 DeepSeek 后凭据又消失 ⇒ 必须**显式报错**，不得静默降级。"""
    srv.STATE["mode"] = "deepseek"
    monkeypatch.setattr(srv, "load_api_key", lambda: (None, "none"))
    res = srv.do_chat({"message": "你好", "history": []})
    assert "error" in res and "取不到 API key" in res["error"]
    srv.STATE["mode"] = "offline"


# ---------------------------------------------------------------- 绑定守卫
def test_bind_guard(srv):
    assert srv.check_bind("127.0.0.1", None) is None
    assert srv.check_bind("localhost", None) is None
    assert srv.check_bind("0.0.0.0", None) is not None
    assert srv.check_bind("0.0.0.0", "short") is not None
    assert srv.check_bind("0.0.0.0", "x" * 24) is None


# ---------------------------------------------------------------- 页面措辞锁
def test_page_has_required_and_no_forbidden_wording():
    t = PAGE.read_text(encoding="utf-8")
    for must in ("响应级代理", "不是 AI 求解器", "拒答", "model_id", "离线",
                 "放行权在人", "无场级误差界", "不给工程绝对值"):
        assert must in t, "页面缺少必备声明：%s" % must
    for bad in ("免 COMSOL 出解", "已验证等价", "可以替代 COMSOL", "solver_certified"):
        assert bad not in t, "页面出现禁止措辞：%s" % bad


def test_server_refuses_page_without_disclaimer(tmp_path, monkeypatch):
    """页面被改掉必备声明 ⇒ 服务端必须拒绝启动。"""
    srv = _load_server()
    bad = tmp_path / "webapp_page.html"
    bad.write_text("<html><body>什么都没有</body></html>", encoding="utf-8")
    monkeypatch.setattr(srv, "PAGE_FILE", bad)
    with pytest.raises(SystemExit):
        srv._load_page()


# ---------------------------------------------------------------- 代理端点
def test_http_mode_and_model_card(http):
    m = _get(http, "/api/mode")
    assert m["mode"] in ("offline", "deepseek") and "key_source" in m
    c = _get(http, "/api/surrogate/model")
    assert c["status"] == "draft_surrogate"
    assert len(c["model_id"]) == 64
    assert "不是 AI 求解器" in c["not_a_solver"]
    assert c["red_lines"] and c["quarantined"]
    assert c["conformal_table"], "模型卡必须含保形校准表"


def test_http_predict_accepted_and_refused(http):
    st, ok = _post(http, "/api/surrogate/predict", {"x": 0.55, "N1": 1, "N2": 6})
    assert st == 200 and ok["accepted"] and not ok["refused"]
    for k in ("model_id", "certified", "band_simultaneous_dB", "spl20_dB",
              "band_per_dim_dB", "freqs_MHz", "calibration", "usage_rule"):
        assert k in ok, "预测缺少必需字段：%s" % k
    assert len(ok["spl_dB"]) == 91 and len(ok["band_per_dim_dB"]) == 91
    # 角点必须被拒，且**不含任何数字**
    st2, bad = _post(http, "/api/surrogate/predict", {"x": 0.20, "N1": 1, "N2": 8})
    assert bad["refused"] is True
    for k in ("spl_dB", "spl20_dB", "band_simultaneous_dB", "p20_Pa"):
        assert k not in bad, "拒答时不得返回 %s" % k
    # 未校准的 α 必须被拒
    st3, a = _post(http, "/api/surrogate/predict", {"x": 0.55, "N1": 1, "N2": 6, "alpha": 0.20})
    assert a["refused"] is True and "alpha" in a["reason"]


def test_http_coverage_and_compare_and_sentinel(http):
    c = _get(http, "/api/surrogate/coverage")
    assert c["n_accepted"] > 2000 and sum(c["by_reason"].values()) > 900
    assert c["by_reason"].get("quarantined_pending_rerun") == 2
    assert c["by_reason"].get("fewer_than_two_n2_points_at_this_n1x") == 162

    st, cmp_ = _post(http, "/api/surrogate/compare",
                     {"a": {"x": 0.55, "N1": 1, "N2": 6}, "b": {"x": 0.56, "N1": 1, "N2": 6}})
    assert st == 200 and "discriminative" in cmp_ and "reason" in cmp_

    st2, sen = _post(http, "/api/surrogate/sentinel",
                     {"x": 0.55, "N1": 1, "N2": 6, "spl20": 1e6})
    assert sen["out_of_band"] is True and "不得" in sen["disclaimer"]


def test_http_data_browse(http):
    v = _get(http, "/api/data/versions")
    labels = [x["label"] for x in v["versions"]]
    assert "C_v20260928" in labels and "C_v20260929" in labels
    q = _get(http, "/api/data/quarantine")
    assert len(q["records"]) == 3
    assert [r["action"] for r in q["records"]].count("reinterpret_attribution") == 2
    assert len(q["corner"]["dip_rows"]) == 3
    d = _get(http, "/api/data/dataset")
    assert d["n_combos"] == 1780 and d["n_layers"] == 22


def test_http_rejects_unknown_post_path(http):
    st, r = _post(http, "/api/nope", {})
    assert st == 404 and "error" in r


# ---------------------------------------------------------------- 产物完整性
def test_surrogate_load_rejects_tampered_artifact(tmp_path):
    """篡改产物字节 ⇒ 必须拒绝加载（fail-closed），而不是拿错模型出数。"""
    import sys
    sys.path.insert(0, str(REPO / "src"))
    from memsharness.surrogate import ResponseSurrogate, SurrogateUnavailable
    for name in ("response_surrogate.json", "surrogate_model.npz"):
        shutil.copy(SURR_DIR / name, tmp_path / name)
    p = tmp_path / "surrogate_model.npz"
    b = bytearray(p.read_bytes())
    b[len(b) // 2] ^= 0xFF                      # 翻一个字节
    p.write_bytes(bytes(b))
    with pytest.raises(SurrogateUnavailable):
        ResponseSurrogate.load(tmp_path)
    # 原目录必须仍然可加载
    assert ResponseSurrogate.load(SURR_DIR).status == "draft_surrogate"


# ---------------------------------------------------------------- 页面结构（防"点了没反应"复发）
def test_page_binds_handlers_before_any_await():
    """**绑定必须先于任何 await**（2026-09-29 实测的真实 bug：原 `boot()` 先 await
    `/api/mode`、`/api/jobs`，再绑定按钮；那一环抛错 ⇒ 按钮**从未绑定** ⇒
    "点预测完全没反应"，而侧栏因为先执行所以正常）。
    """
    t = PAGE.read_text(encoding="utf-8")
    body = t.split("async function boot(){", 1)[1]
    head = body.split("\n}", 1)[0]
    i_bind, i_await = head.find("bindAll()"), head.find("await ")
    assert i_bind != -1, "boot() 里找不到 bindAll()"
    assert i_await != -1
    assert i_bind < i_await, "bindAll() 必须在第一个 await 之前"
    # 每个 await 都必须被 try/catch 包住（否则一次失败就静默中断后续初始化）
    assert "catch(e){ showError(" in head


def test_page_has_visible_error_reporting_and_autorun():
    """错误必须**可见**（横幅 + 面板），且 `autorun` 要走**真实 click** 通道。"""
    t = PAGE.read_text(encoding="utf-8")
    for must in ('id="errBanner"', "function showError(", "unhandledrejection",
                 "function wrap(", "b.textContent='运行中…'", "function autorun(",
                 "btn.click()"):
        assert must in t, "页面缺少：%s" % must
    # 不得再把 handler 直接等于函数（那样异常会静默）
    assert "$('#bPred').onclick=wrap(" in t


def test_page_is_never_cached(http):
    """HTML 响应必须 no-store：否则浏览器启发式缓存会让人拿到旧页面（"按钮不存在"）。"""
    with urllib.request.urlopen(http + "/", timeout=30) as r:
        cc = r.headers.get("Cache-Control") or ""
        assert "no-store" in cc, "HTML 必须禁用缓存，实得：%r" % cc


def test_autorun_url_params_reach_the_endpoint(http):
    """`?run=…&x=…` 的可分享链接：至少保证页面会把参数填进输入框（结构检查）。"""
    t = PAGE.read_text(encoding="utf-8")
    assert "RUN_TO_BTN" in t and "location.search" in t
    q = _get(http, "/api/mode")          # 顺带确认别名端点仍与真实 STATE 一致
    assert q["mode"] in ("offline", "deepseek")


# ------------------------------------------------- 跨来源打开（用户实际遇到的故障）
def test_cors_only_for_loopback_origins(http):
    """页面可能被**别的本地端口/界面内嵌**打开，那时需要绝对 URL 回落 ⇒ 要 CORS；
    但**只对回环来源**放行 —— 本服务能在本机跑写产物任务，不能让任意网页跨源调用。"""
    def hdr(origin):
        req = urllib.request.Request(http + "/api/mode", headers={"Origin": origin})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.headers.get("Access-Control-Allow-Origin")

    assert hdr("http://127.0.0.1:8898") == "http://127.0.0.1:8898"
    assert hdr("http://localhost:3080") == "http://localhost:3080"
    for bad in ("http://evil.example", "https://127.0.0.1:8898", "null"):
        assert hdr(bad) is None, "不得对非回环来源回 CORS 头：%s" % bad
    # 预检
    req = urllib.request.Request(http + "/api/mode", method="OPTIONS",
                                 headers={"Origin": "http://127.0.0.1:8898"})
    with urllib.request.urlopen(req, timeout=30) as r:
        assert r.status == 204
        assert r.headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:8898"


def test_page_can_fall_back_to_absolute_api_base():
    """页面必须能在"非 8877 来源"下自愈：探测多个候选基址并回落到 8877。"""
    t = PAGE.read_text(encoding="utf-8")
    for must in ("detectApiBase", "API_CANDIDATES", "http://127.0.0.1:8877",
                 "API_BASE", "showConnBanner", "diagText", "复制诊断信息", "重试连接"):
        assert must in t, "页面缺少回落到绝对基址所需的：%s" % must


def test_mode_buttons_are_never_both_disabled():
    """用户报"离线模式和 DeepSeek 连接都无法点击"——根因是两个按钮被**同时** disable。
    新实现必须显式把两个都置为可用，用高亮表示当前模式。"""
    t = PAGE.read_text(encoding="utf-8")
    assert "off.disabled=false; onb.disabled=false;" in t
    assert "setModeButtons" in t
    # 旧的"双双可能禁用"的写法必须已删除
    assert "$('#bOff').disabled=!on" not in t
    assert "$('#bOn').disabled=on||!m.key_present" not in t


def test_api_errors_carry_the_url_for_diagnosis():
    """错误里必须带**试过的 URL**，否则用户只能看到"发生了错误"而无法定位。"""
    t = PAGE.read_text(encoding="utf-8")
    assert "_url:url" in t and "非 JSON 响应（HTTP " in t


# ------------------------------------------------- 多参数（用户："我研究的不是单个参数"）
def test_grid_endpoint_covers_multiple_parameters(http):
    """网格端点必须一次覆盖 **N2 × N1 × x** 三个参数轴，并导出 CSV。"""
    st, g = _post(http, "/api/surrogate/grid",
                  {"n2_list": [7, 8], "n1_max": 4, "x_lo": 0.21, "x_hi": 0.29,
                   "x_step": 0.01, "alpha": 0.10})
    assert st == 200 and "error" not in g, g
    assert g["n2_list"] == ["7", "8"] and g["n1_max"] == 4
    # 三个轴都真的被覆盖了
    assert {r["N_w_te2"] for r in g["rows"]} == {7.0, 8.0}
    assert {r["N_w_te1"] for r in g["rows"]} == {1.0, 2.0, 3.0, 4.0}
    assert min(r["x_scale"] for r in g["rows"]) >= 0.21
    assert g["n_accepted"] + g["n_refused"] == g["n_points"]
    assert all(k in g["csv"] for k in ("x_scale,N_w_te1,N_w_te2", "band_simultaneous_dB"))
    assert len(g["csv"].strip().splitlines()) == g["n_accepted"] + 1
    # 每个点都必须带区间（不得只给点估计）
    assert all(r["band_simultaneous_dB"] is not None for r in g["rows"])
    assert g["by_n2"] and set(g["by_n2"]) == {"7", "8"}


def test_model_card_declares_parameter_dimension_and_axis_semantics(http):
    """模型卡必须写明：**参数是三维的**、坐标轴含义、以及"数据只扫了这三个参数"。"""
    c = _get(http, "/api/surrogate/model")
    t = c.get("model_card") or c
    assert t["target"]["x_axis"].startswith("频率")
    assert "SPL" in t["target"]["y_axis"]
    p = t["parameters"]
    assert p["design_space"] == ["x_scale", "N_w_te1", "N_w_te2"]
    assert "只有这三个" in p["note"]
    assert len(p["ranges"]["N_w_te2"]) >= 5     # 5,6,7,8 + 9


# ------------------------------------------------- 一阶峰：Pareto 与热力图（裁定 §10）
def test_peaks_summary_covers_both_batches(http):
    s = _get(http, "/api/peaks/summary")
    assert s["n_rows"] == 2005                      # A 223 + C 1782，**不互相覆盖**
    assert set(s["by_batch"]) == {"A", "C"}
    assert s["by_batch"]["A"]["n_rows"] == 223
    assert s["by_batch"]["C"]["n_rows"] == 1782
    # 跨批必须分层：密度类别不同
    assert s["by_batch"]["A"]["x_density_class"] == ["coarse_0.1"]
    assert s["by_batch"]["C"]["x_density_class"] == ["fine_0.01"]
    assert s["by_batch"]["C"]["n_ranking_eligible"] == 673
    assert s["by_batch"]["A"]["n_ranking_eligible"] == 55


def test_pareto_front_only_contains_eligible_closed_bandwidth(http):
    """裁定 §10：**不得**把没有闭合带宽（或未过 Q 门槛）的组合放进 Pareto 前沿。"""
    p = _get(http, "/api/peaks/pareto?batch=C")
    assert p["n_pool"] == 673 and p["n_front"] == 45
    assert p["n_front"] < p["n_pool"]
    for r in p["front"] + p["all"]:
        assert r["q_gate_pass"] is True, "Pareto 里出现未过 Q 门槛的组合：%s" % r
        for o in p["objectives"]:
            assert r[o] is not None, "Pareto 里出现目标值缺失：%s" % r
    # 前沿必须真的非支配：没有任何池内点支配前沿点
    objs = p["objectives"]
    for f in p["front"]:
        for a in p["all"]:
            if a is f:
                continue
            ge = all(a[o] >= f[o] for o in objs)
            gt = any(a[o] > f[o] for o in objs)
            assert not (ge and gt), "前沿点被支配：%s 被 %s" % (f, a)
    # A 批也能算（分层）
    assert _get(http, "/api/peaks/pareto?batch=A")["n_pool"] == 55


def test_heatmap_is_per_batch_and_unitless_cells_stay_empty(http):
    h = _get(http, "/api/peaks/heatmap?batch=C&metric=bandwidth_Hz&n2=8")
    assert h["metric_label"].startswith("绝对 −3 dB 带宽")
    assert len(h["xs"]) == 77 and len(h["n1s"]) == 7
    assert h["n_points"] == 478
    assert h["value_range"][0] > 0 and h["value_range"][1] > h["value_range"][0]
    # 空单元格必须是 None（不填 0）
    flat = [v for row in h["grid"] for v in row]
    assert any(v is None for v in flat) and any(v is not None for v in flat)
    assert 0.0 not in flat
    # 按批次分层：同一 (x,N1) 在两个批次里是**分开**的请求
    ha = _get(http, "/api/peaks/heatmap?batch=A&metric=bandwidth_Hz")
    assert ha["batch"] == "A"
    # A 共 10 个 x 取值，但只有**能找到首个峰**的那些才有带宽 ⇒ 列数 ≤ 10；
    # **缺的列不是丢数据，而是"该 x 无可用值"**（热力图不填 0、也不补空列）。
    assert 0 < len(ha["xs"]) <= 10
    assert set(ha["xs"]).issubset({round(0.1 * i, 2) for i in range(1, 11)})
    # 不给 n2 ⇒ 多层聚到同一格，**行数可以超过格数**（这不是错）；给 n2 时每个非空格恰好一行。
    h8 = _get(http, "/api/peaks/heatmap?batch=A&metric=bandwidth_Hz&n2=8")
    non_empty = sum(1 for row in h8["grid"] for v in row if v is not None)
    assert h8["n_points"] == non_empty, "指定 n2 时每格应恰好一行：%s vs %s" % (h8["n_points"],
                                                                          non_empty)
