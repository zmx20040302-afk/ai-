# -*- coding: utf-8 -*-
"""**环境事实必须带观测时间**：瞬时观测不得当作长期事实。

## 事故背景（实测）

* 「SAC 拦 sklearn ⇒ 3 个测试文件无法收集」曾被当成一条**当前事实**上报，
  **后来不复现** —— 记录里没有观测时间，事后**无法判断**它到底是「当时为真、现在为假」
  还是「当时就测错了」（`INDEX §93.6` 那类同机并发失败的同一族问题）。
* 平台能力表 `module_capability` 的 `mphserver_listening` **实测曾报 `true`，
  而现场探端口 2036 是 CLOSED**（`AGENTS.md` 第 3 节明文：端口存活一律**现场探**，
  不得引用快照）。

⇒ 约定：**「本机/远端能力」类的每条记录必须带 `observed_at`（带时区的 ISO-8601 观测时间）
＋ `source`（谁在什么地方测的）**；缺任一 ⇒ **不合格**（`check_fact()` 报错，
`assert_fact()` 抛出）。要引用旧观测必须**显式**给出 `max_age_s` 并接受过期即废。

本模块只做**判定**（不落盘、不联网）：把「这条环境事实还能不能用」变成一个可测的函数。
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = [
    "MissingObservationTime", "StaleFactError", "REQUIRED_FACT_FIELDS",
    "LIVE_ONLY_CAPS", "now_stamp", "parse_stamp", "make_fact", "check_fact",
    "assert_fact", "check_facts", "fact_age_s",
]

#: 环境事实记录的必填字段（缺任一 ⇒ 不合格）
REQUIRED_FACT_FIELDS = ("capability", "value", "observed_at", "source")

#: **不得引用快照**的能力项：无论多新，都必须现场实测
#: （`AGENTS.md` 实测：`mphserver_listening` 快照曾报 true 而现场端口 CLOSED）
LIVE_ONLY_CAPS: tuple[str, ...] = ("mphserver_listening", "mphserver_port_open")

#: 允许的「未来」容差（时钟抖动/写入延迟），超过即视为时间戳不可信
_FUTURE_TOLERANCE_S = 60.0


class MissingObservationTime(ValueError):
    """缺观测时间（或时间戳不可信）⇒ 不合格。"""


class StaleFactError(ValueError):
    """观测时间超出允许的时效 ⇒ 必须重新实测。"""


def now_stamp(now: _dt.datetime | None = None) -> str:
    """当前（或给定）时刻的 ISO-8601 时间戳，**带 UTC 时区**（秒精度）。"""
    t = now or _dt.datetime.now(_dt.timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return t.astimezone(_dt.timezone.utc).replace(microsecond=0).isoformat()


def parse_stamp(value: Any) -> _dt.datetime:
    """解析观测时间；**必须带时区**（naive 时间戳无法判断新旧 ⇒ 拒收）。"""
    if isinstance(value, _dt.datetime):
        t = value
    elif isinstance(value, str) and value.strip():
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            t = _dt.datetime.fromisoformat(s)
        except ValueError as exc:
            raise MissingObservationTime("观测时间不是 ISO-8601：%r（%s）" % (value, exc)) from exc
    else:
        raise MissingObservationTime("观测时间缺失或类型不对：%r" % (value,))
    if t.tzinfo is None:
        raise MissingObservationTime(
            "观测时间 %r 没有时区 ⇒ 无法判断新旧（写成本地时间要带偏移，如 +08:00）" % (value,))
    return t


def fact_age_s(fact: Mapping, *, now: _dt.datetime | None = None) -> float:
    """这条事实的年龄（秒）。时间戳不合格 ⇒ 抛 `MissingObservationTime`。"""
    t = parse_stamp(fact.get("observed_at") if isinstance(fact, Mapping) else None)
    ref = now or _dt.datetime.now(_dt.timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=_dt.timezone.utc)
    return (ref - t).total_seconds()


def make_fact(capability: str, value: Any, *, source: str,
              now: _dt.datetime | None = None, detail: str = "",
              **extra: Any) -> dict:
    """造一条**合格**的环境事实（自动打上观测时间戳）。

    `source` 不可省：说不清「现场探的 / 抄文档的 / 从缓存读的」，这条事实就没法用。
    """
    fact = {"capability": capability, "value": value, "observed_at": now_stamp(now),
            "source": source}
    if detail:
        fact["detail"] = detail
    fact.update(extra)
    return fact


def check_fact(fact: Mapping, *, max_age_s: float | None = None,
               now: _dt.datetime | None = None) -> list[str]:
    """检查一条环境事实；返回中文问题清单（空 = 合格）。

    * 缺 `capability` / `value` / `observed_at` / `source` ⇒ 问题；
    * 时间戳不可解析、**无时区**、落在未来（容差 60 s）⇒ 问题；
    * `max_age_s` 给了且年龄超限 ⇒ 问题（**过期即废，必须现场重测**）；
    * `capability` 在 `LIVE_ONLY_CAPS` 里 ⇒ 没有 `max_age_s` 也要求「现场实测」标注
      （`live=True`），否则算不合格 —— 这类项**从来不允许引用快照**。
    """
    problems: list[str] = []
    if not isinstance(fact, Mapping):
        return ["环境事实不是字典：%r" % type(fact).__name__]
    for key in ("capability", "value", "source"):
        if key not in fact or fact[key] in (None, ""):
            problems.append("缺 %s（环境事实必须说清是什么、值多少、谁测的）" % key)
    if "observed_at" not in fact or fact["observed_at"] in (None, ""):
        problems.append(
            "缺观测时间 observed_at ⇒ **不合格**：没有观测时间的「能力/环境」记录"
            "无法区分「当时为真」与「当时测错」，不得当作长期事实引用")
        return problems                     # 没时间就无从判断时效，直接拒

    try:
        t = parse_stamp(fact["observed_at"])
    except MissingObservationTime as exc:
        problems.append(str(exc))
        return problems

    ref = now or _dt.datetime.now(_dt.timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=_dt.timezone.utc)
    age = (ref - t).total_seconds()
    if age < -_FUTURE_TOLERANCE_S:
        problems.append("观测时间落在未来（%.0f s 之后）⇒ 时间戳不可信" % (-age))

    cap = str(fact.get("capability") or "")
    if cap in LIVE_ONLY_CAPS and not fact.get("live"):
        problems.append(
            "「%s」属于**不得引用快照**的能力项（实测教训：快照报 true 而现场端口 CLOSED）"
            "⇒ 必须现场实测并标 `live=True`" % cap)

    if max_age_s is not None:
        if age > float(max_age_s):
            problems.append(
                "观测时间过旧：age=%.0f s > 允许 %.0f s ⇒ **必须现场重测**，"
                "不得引用这次快照（瞬时环境当长期事实就是本仓库踩过的坑）"
                % (age, float(max_age_s)))
    return problems


def assert_fact(fact: Mapping, *, max_age_s: float | None = None,
                now: _dt.datetime | None = None) -> dict:
    """`check_fact()` 的断言版；缺时间戳 ⇒ `MissingObservationTime`，过期 ⇒ `StaleFactError`。"""
    problems = check_fact(fact, max_age_s=max_age_s, now=now)
    if not problems:
        return dict(fact)
    joined = "\n  - ".join(problems)
    if any("缺观测时间" in p or "时区" in p or "不是 ISO-8601" in p for p in problems):
        raise MissingObservationTime("环境事实不合格：\n  - %s" % joined)
    if any("过旧" in p for p in problems):
        raise StaleFactError("环境事实不合格：\n  - %s" % joined)
    raise ValueError("环境事实不合格：\n  - %s" % joined)


def check_facts(facts: Iterable[Mapping], *, max_age_s: float | None = None,
                now: _dt.datetime | None = None) -> dict:
    """批量检查：返回 `{"ok","valid":[...],"invalid":[{fact,problems}],"stale":[...]}`。

    `stale` 单列（时间戳合格但过期）—— 那类记录**不是**伪造，只是**需要重测**，
    报报告时不应与「不合格」混为一谈。
    """
    valid: list[dict] = []
    invalid: list[dict] = []
    stale: list[dict] = []
    for i, f in enumerate(facts):
        probs = check_fact(f, max_age_s=max_age_s, now=now)
        if not probs:
            valid.append(dict(f) if isinstance(f, Mapping) else {"value": f})
            continue
        item = {"index": i, "fact": dict(f) if isinstance(f, Mapping) else {"value": f},
                "problems": probs}
        (stale if all("过旧" in p for p in probs) else invalid).append(item)
    return {"ok": not invalid, "n_total": len(valid) + len(invalid) + len(stale),
            "valid": valid, "invalid": invalid, "stale": stale}
