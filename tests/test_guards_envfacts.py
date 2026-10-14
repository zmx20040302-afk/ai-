# -*- coding: utf-8 -*-
"""**守卫 P1-④「环境事实时间戳」**（`src\\memsharness\\guards_envfacts.py`）的用例。

事故背景：① 「SAC 拦 sklearn ⇒ 3 个文件无法收集」曾被当成**当前事实**上报，
**后来不复现**，而记录里没有观测时间 ⇒ 事后**无法分辨**「当时为真、现在为假」与「当时测错」；
② 平台能力表 `module_capability` 的 `mphserver_listening` 曾报 `true`，而现场探端口是 CLOSED
（`AGENTS.md` 第 3 节：端口存活一律现场探）。

判据：**「本机/远端能力」类记录必须带 `observed_at`（带时区）＋ `source`；缺任一 ⇒ 不合格。**
"""
from __future__ import annotations

import datetime as _dt
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from memsharness import guards_envfacts as g   # noqa: E402

NOW = _dt.datetime(2026, 10, 9, 12, 0, 0, tzinfo=_dt.timezone.utc)


def good_fact(**over):
    fact = g.make_fact("sac_blocks_sklearn", False,
                       source="现场跑全量 pytest（2026-10-09 12:00 UTC）", now=NOW)
    fact.update(over)
    return fact


# ============================================================ ① 正侧
def test_stamped_fact_is_valid():
    fact = good_fact()
    assert g.check_fact(fact, now=NOW) == []
    assert g.assert_fact(fact, now=NOW)["capability"] == "sac_blocks_sklearn"
    assert g.parse_stamp(fact["observed_at"]).tzinfo is not None
    assert g.fact_age_s(fact, now=NOW) == 0.0


def test_now_stamp_roundtrips_and_is_utc():
    s = g.now_stamp(NOW)
    assert s.endswith("+00:00") and "Z" not in s
    assert g.parse_stamp(s) == NOW
    assert g.parse_stamp(s.replace("+00:00", "Z")) == NOW


# ============================================================ ② 反侧：缺观测时间 ⇒ 不合格
def test_record_without_timestamp_is_invalid():
    """**核心判据**：缺 `observed_at` 的记录判定为不合格。"""
    fact = {"capability": "sac_blocks_sklearn", "value": False, "source": "当时听说"}
    problems = g.check_fact(fact, now=NOW)
    assert problems and "缺观测时间" in problems[0], problems
    assert "不合格" in problems[0]
    with pytest.raises(g.MissingObservationTime):
        g.assert_fact(fact, now=NOW)


@pytest.mark.parametrize("bad", [None, "", "  ", 0, [], {}])
def test_empty_or_wrong_typed_timestamp_is_invalid(bad):
    problems = g.check_fact(good_fact(observed_at=bad), now=NOW)
    assert problems, bad


def test_naive_timestamp_is_invalid():
    """不带时区的时间戳无法判断新旧 ⇒ 拒收。"""
    problems = g.check_fact(good_fact(observed_at="2026-10-09T12:00:00"), now=NOW)
    assert problems and "没有时区" in problems[0], problems


def test_unparsable_timestamp_is_invalid():
    problems = g.check_fact(good_fact(observed_at="2026/10/09 12:00"), now=NOW)
    assert problems and "不是 ISO-8601" in problems[0], problems


def test_future_timestamp_is_invalid():
    problems = g.check_fact(good_fact(observed_at=g.now_stamp(NOW + _dt.timedelta(hours=2))),
                            now=NOW)
    assert problems and "落在未来" in problems[0], problems


def test_missing_capability_or_value_or_source_is_invalid():
    for drop in ("capability", "value", "source"):
        fact = good_fact()
        fact.pop(drop)
        problems = g.check_fact(fact, now=NOW)
        assert any(drop in p for p in problems), (drop, problems)


# ============================================================ ③ 瞬时环境不得当长期事实
def test_stale_observation_is_flagged_and_raises():
    """3 小时前的观测，要求 10 分钟内有效 ⇒ 必须**判过期并要求现场重测**。"""
    old = good_fact(observed_at=g.now_stamp(NOW - _dt.timedelta(hours=3)))
    assert g.check_fact(old, now=NOW) == [], "不设时效时，时间戳本身是合格的"
    problems = g.check_fact(old, max_age_s=600, now=NOW)
    assert problems and "过旧" in problems[0] and "现场重测" in problems[0], problems
    with pytest.raises(g.StaleFactError):
        g.assert_fact(old, max_age_s=600, now=NOW)


def test_check_facts_separates_stale_from_invalid():
    old = good_fact(observed_at=g.now_stamp(NOW - _dt.timedelta(hours=3)))
    no_ts = {"capability": "sac_blocks_sklearn", "value": False, "source": "当年听说"}
    r = g.check_facts([good_fact(), no_ts, old], max_age_s=600, now=NOW)
    assert r["n_total"] == 3 and r["ok"] is False
    assert len(r["valid"]) == 1 and len(r["invalid"]) == 1 and len(r["stale"]) == 1
    assert r["invalid"][0]["problems"][0].startswith("缺观测时间")
    assert "过旧" in r["stale"][0]["problems"][0]


def test_fresh_within_window_is_valid():
    recent = good_fact(observed_at=g.now_stamp(NOW - _dt.timedelta(seconds=59)))
    assert g.check_fact(recent, max_age_s=60, now=NOW) == []
    just_over = good_fact(observed_at=g.now_stamp(NOW - _dt.timedelta(seconds=61)))
    assert g.check_fact(just_over, max_age_s=60, now=NOW), "61 s > 60 s 必须判过期"


# ============================================================ ④ 不得引用快照的能力项
def test_live_only_capabilities_require_live_observation():
    snap = g.make_fact("mphserver_listening", True, source="读能力表快照", now=NOW)
    problems = g.check_fact(snap, now=NOW)
    assert any("不得引用快照" in p for p in problems), problems
    live = g.make_fact("mphserver_listening", True, source="现场探 127.0.0.1:2036",
                       now=NOW, live=True)
    assert g.check_fact(live, now=NOW) == []


def test_live_only_list_is_documented_with_a_source_of_truth():
    """这条「不得引用快照」的清单必须有出处（AGENTS.md 的实测教训），不是随手写的。"""
    assert "mphserver_listening" in g.LIVE_ONLY_CAPS
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert "mphserver_listening" in agents and "CLOSED" in agents
