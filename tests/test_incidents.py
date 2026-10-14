# -*- coding: utf-8 -*-
"""失败通道（`src/memsharness/incidents.py`）的契约测试。

锁住的是**承诺**，不是"能跑"：
* 未登记类别拒收；
* 台账 append-only、包文件不覆盖；
* **密钥一定被脱敏**（按参数名 + 按文本模式两条路，实测各漏过一次）；
* 长文本截断必须**显式留痕**，不静默丢内容；
* 复现命令**推不出来就留空**，绝不编造；
* 包里**只有事实**、带"不得改裁定"的声明；
* **结构上不外发**：模块不导入任何网络库（"不外发"是承诺，得能被机器检查）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

CANARY = "LEAK-CANARY-9999"


@pytest.fixture()
def inc(tmp_path, monkeypatch):
    """每条用例一个**独立**台账/包目录：否则计数与顺序都会被别的用例污染。"""
    monkeypatch.setenv("MEMS_INCIDENTS_LEDGER", str(tmp_path / "led.jsonl"))
    monkeypatch.setenv("MEMS_INCIDENTS_ROOT", str(tmp_path / "pkgs"))
    from memsharness import incidents
    return incidents


def _lines(inc) -> list[str]:
    p = inc.ledger_path()
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if p.is_file() else []


def test_unknown_kind_is_refused_and_nothing_is_written(inc):
    with pytest.raises(ValueError) as e:
        inc.record("no_such_kind", "x")
    assert "未登记的失败类别" in str(e.value)
    assert _lines(inc) == [], "被拒的记录不许留下任何痕迹"


def test_record_load_get_roundtrip(inc):
    r1 = inc.record("refusal", "域外，正确的 fail-closed", params={"x": 1.5})
    r2 = inc.record("task_failed", "任务报错", task="sweep_analysis")
    d = inc.load(limit=10)
    assert d["n_total"] == 2 and d["n_bad_lines"] == 0
    assert [i["incident_id"] for i in d["items"]] == [r2["incident_id"], r1["incident_id"]], \
        "最新的必须排在最前"
    assert inc.get(r1["incident_id"])["kind"] == "refusal"
    assert inc.get("inc-nope") is None
    assert inc.counts()["by_kind"] == {"refusal": 1, "task_failed": 1}


def test_ledger_is_append_only(inc):
    inc.record("manual", "第一条")
    first = _lines(inc)[0]
    inc.record("manual", "第二条")
    lines = _lines(inc)
    assert len(lines) == 2
    assert lines[0] == first, "追加不得改动已有行"


def test_package_files_refuse_overwrite(inc):
    r = inc.record("manual", "写包用")
    a = inc.write_package(r["incident_id"])
    assert "md_path" in a and Path(REPO / a["md_path"]).is_file() \
        or Path(a["md_path"]).is_file()
    b = inc.write_package(r["incident_id"])
    assert "拒绝覆盖" in b["error"], b
    assert b.get("existing")


def test_write_package_index_guard_rejects_outside_work(inc, tmp_path):
    """**人显式指定的**输出目录必须在 work/ 下（env 重定向的临时目录不在此列）。"""
    r = inc.record("manual", "路径守卫")
    bad = inc.write_package(r["incident_id"], out_root="C:/Windows/Temp/inc-guard")
    assert "必须在 work/ 下" in bad["error"], bad


@pytest.mark.parametrize("field,payload", [
    ("参数名 token", {"params": {"token": CANARY}}),
    ("参数名 api_key", {"params": {"api_key": CANARY}}),
    ("参数名 password", {"params": {"password": CANARY}}),
    ("嵌套参数里的 key", {"params": {"a": {"b": {"key": CANARY}}}}),
    ("error_text 里 sk- 开头", {"error_text": "sk-" + CANARY}),
    ("error_text 里 key=values", {"error_text": "key=" + CANARY}),
    ("error_text 里 Bearer", {"error_text": "Authorization: Bearer " + CANARY}),
    ("error_text 里 URL query", {"error_text": "GET /x?token=" + CANARY}),
    ("args 里 token", {"args": {"token": CANARY}}),
    ("repro 里 token", {"repro": "curl http://x/?token=" + CANARY}),
    ("command 里 token", {"command": "run --token=" + CANARY}),
])
def test_secrets_never_reach_the_ledger_or_the_package(inc, field, payload):
    """**逐条**验脱敏路径：初版只有「按文本模式」，参数里 `{"token": …}` 直接漏了。"""
    r = inc.record("manual", "脱敏用例：" + field, **payload)
    md = inc.render_md(r)
    blob = md + json.dumps(r, ensure_ascii=False)
    assert CANARY not in blob, "%s 没被脱敏" % field
    assert r["redacted_hits"] >= 1, "%s 应记录脱敏命中数" % field


def test_legitimate_values_survive_redaction(inc):
    """脱敏不能把有用的输入一起抹掉（否则包就没法分析了）。"""
    r = inc.record("manual", "正常参数要留着",
                   params={"x_scale": 0.55, "n1": 1, "n2": 8, "alpha": 0.1})
    md = inc.render_md(r)
    assert "0.55" in md and '"n2": 8' in md
    assert "x_scale" in md


def test_long_text_is_truncated_with_disclosure(inc):
    long = "A" * 30000
    r = inc.record("task_failed", "超长输出", error_text=long)
    assert "error_text" in r["truncated"] and r["truncated"]["error_text"] == 30000
    md = inc.render_md(r)
    assert "原长 30000 字符" in md, "截断必须显式留痕"
    assert "字段截断" in md


def test_repro_synthesis_branches(inc):
    t = inc.record("task_timeout", "任务超时", task="sweep_analysis", args={"preset": "x"})
    assert "--exec-task sweep_analysis" in t["repro"]
    g = inc.record("refusal", "拒答", endpoint="/api/mc/predict", method="GET",
                   params={"x": 1.5, "n1": 1})
    assert "curl.exe" in g["repro"] and "x=1.5" in g["repro"]
    p = inc.record("manual", "没有端点")
    assert p["repro"] == "", "推不出来必须留空，不许编造"
    assert "不编造" in inc.render_md(p)


def test_package_has_required_sections_and_no_analysis_claim(inc):
    r = inc.record("api_error", "接口炸了", endpoint="/api/x", method="POST",
                   error_text="boom", stack="Traceback (most recent call last): ...")
    md = inc.render_md(r)
    for must in ("## 1. 现象", "## 2. 原始错误全文（含堆栈）", "### 2.1 堆栈",
                 "## 3. 当时的输入与调用", "## 4. 本包**不含**什么"):
        assert must in md, "缺章节：%s" % must
    assert "不得" in md and "不含任何分析结论" in md
    assert "不外发" in md or "由人发给" in md or "不含日志尾部" in md


def test_package_json_shape_and_hash(inc):
    import hashlib
    r = inc.record("manual", "包结构")
    pk = inc.package(r["incident_id"])
    assert pk["json"]["_package"]["schema"] == inc.SCHEMA
    assert pk["json"]["_package"]["md_sha256"] == \
        hashlib.sha256(pk["md"].encode("utf-8")).hexdigest()
    assert pk["json"]["incident"]["incident_id"] == r["incident_id"]
    assert pk["md_bytes"] == len(pk["md"].encode("utf-8"))


def test_missing_incident_is_reported_not_invented(inc):
    r = inc.package("inc-nope")
    assert "没有这条记录" in r["error"]
    assert "md" not in r


def test_bad_lines_counted_not_fatal(inc):
    inc.record("manual", "好行")
    with inc.ledger_path().open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("{ not json\n")
    d = inc.load(limit=10)
    assert d["n_bad_lines"] == 1 and d["n_total"] == 1, "坏行只统计，不能把台账读崩"


def test_kinds_are_complete_for_the_agreed_scope(inc):
    """用户选的「全部失败面」必须都在：缺一个就说明有一面收不上来。"""
    for k in ("task_timeout", "task_failed", "task_cancelled", "refusal",
              "page_error", "api_error", "service_unavailable", "manual"):
        assert k in inc.KINDS and inc.KINDS[k], k


def test_module_never_sends_anything(inc):
    """**不外发**必须是结构事实：不许有网络调用，也不许出现外部地址。

    初版把 `http://` 整个禁掉 ⇒ 误报：模块要**生成给人看的复现命令**
    （`curl.exe … http://127.0.0.1:8877/…`），那是文本、不是请求。
    判据改成两条：① 不出现网络调用/客户端库；② 除回环地址外不出现任何主机名。
    """
    src = Path(inc.__file__).read_text(encoding="utf-8")
    for bad in ("import requests", "urllib.request", "http.client", "urlopen(",
                "import socket", "socket.socket", "requests."):
        assert bad not in src, "失败通道里出现了疑似外发的代码：%s" % bad
    external = re.findall(r"https?://(?!127\.0\.0\.1|localhost)[A-Za-z0-9.-]+", src)
    assert not external, "出现外部地址（可能外发）：%s" % external
    assert "127.0.0.1" in src, "复现命令需要本机回环地址"
