# -*- coding: utf-8 -*-
"""**分母纪律**：任何「比例 / 通过率」类结果必须**同时**携带两个数。

## 事故背景（实测，`INDEX §98.4.1`）

V2 批的 `usable` 标志口径算出 **146** 行「可用」，于是 §92.2 把 Q 门禁的**适用基数**
写成「可用 146」。后来实测：那 146 行里 **39 行字面 `nan`**（其中 **38 行的两个端点标志
都是「未删失、未截断」 ⇒ flag 口径判它们「可用」**）⇒ **真正的 Q 可判定基数是 108**，
不是 146。数字 `40`（Q 达标数）不变，但**分母写错**会让「通过率」从 37.0% 变成 27.4%。

⇒ 纪律：**只要报一个比例，就必须同时说清「分母是什么口径」**。

## 本模块的口径

* `flag_basis_count`：**标志口径计数**（如 `usable == True` 的行数）；
* `denominator`：**可判定基数**（标志为可用 **且** 该指标的值**可判定**的行数）；
* `n_nondecidable`：两者之差（有 flag 却没有可判定值的行数，即「算不出来」的那些）。

**判定（fail-closed）**：缺 `denominator` 或 `flag_basis_count` 任一 ⇒ 拒绝；
`nan` / `None` / 空串 / 不可解析的值**一旦被算进分母** ⇒ 拒绝。`nan` 不是 0，
也不是「通过/不通过」，它只是**不可判定**。
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "DenominatorDisciplineError", "RATE_REQUIRED_FIELDS", "is_decidable_value",
    "decidable_base", "make_rate_record", "check_rate_record", "assert_rate_record",
    "ratio", "format_rate",
]

#: 比例/通过率类结果**必须**携带的字段（缺任一即拒绝）
RATE_REQUIRED_FIELDS = ("metric", "numerator", "denominator", "flag_basis_count")

_MISSING = object()


class DenominatorDisciplineError(ValueError):
    """比例类结果没有说清分母口径，或分母里混进了不可判定的行。"""


def is_decidable_value(v: Any) -> bool:
    """这个值**能不能参与判定**（`nan` / `None` / 空串 / 不可解析的字符串 ⇒ 不能）。"""
    if v is None:
        return False
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        return math.isfinite(float(v))
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return False
        try:
            return math.isfinite(float(s))
        except ValueError:
            return False
    return False


def _value_class(v: Any) -> str:
    if v is None:
        return "none"
    if isinstance(v, str):
        return "empty" if not v.strip() else "unparsable"
    if isinstance(v, float) and math.isnan(v):
        return "nan"
    if isinstance(v, (int, float)) and not math.isfinite(float(v)):
        return "inf"
    return "other"


def _is_flag_true(v: Any, true_values: Sequence[Any]) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {str(t).lower() for t in true_values}
    return any(v is t or v == t for t in true_values)


def decidable_base(rows: Sequence[Mapping], *, flag_key: str = "usable",
                   value_key: str = "Q", flag_true_values: Sequence[Any] = (True,),
                   label: str = "") -> dict:
    """从明细行算**两个口径**：标志口径计数 与 可判定基数（含差额分解）。

    返回：
    `{"label", "n_rows", "n_missing_flag", "flag_basis_count", "n_nondecidable",
      "denominator", "breakdown": {"nan": n, "none": n, "empty": n, "unparsable": n, "inf": n}}`

    * `flag_basis_count` = 标志为真的行数（**不看值**）；
    * `denominator` = 标志为真 **且** 值可判定的行数；
    * 两者之差 ⇒ `n_nondecidable`，并按**成因**分解（`nan` 最多，但 `None`/空串同样算）。
    """
    n_rows = len(rows)
    n_flag = 0
    n_missing_flag = 0
    breakdown: dict[str, int] = {}
    for r in rows:
        raw = r.get(flag_key, _MISSING) if isinstance(r, Mapping) else _MISSING
        if raw is _MISSING or raw is None:
            n_missing_flag += 1
            continue
        if not _is_flag_true(raw, flag_true_values):
            continue
        n_flag += 1
        v = r.get(value_key, None) if isinstance(r, Mapping) else None
        if is_decidable_value(v):
            continue
        key = _value_class(v)
        breakdown[key] = breakdown.get(key, 0) + 1
    n_nondecidable = sum(breakdown.values())
    return {"label": label or "%s（标志=%s）" % (value_key, flag_key),
            "n_rows": n_rows, "n_missing_flag": n_missing_flag,
            "flag_basis_count": n_flag, "n_nondecidable": n_nondecidable,
            "denominator": n_flag - n_nondecidable, "breakdown": breakdown,
            "flag_key": flag_key, "value_key": value_key}


def make_rate_record(metric: str, numerator: int, rows: Sequence[Mapping], *,
                     flag_key: str = "usable", value_key: str = "Q",
                     flag_true_values: Sequence[Any] = (True,), note: str = "") -> dict:
    """由明细行造一条**合规**的比例记录（直接把两个口径都带上）。"""
    base = decidable_base(rows, flag_key=flag_key, value_key=value_key,
                          flag_true_values=flag_true_values, label=metric)
    rec = {"metric": metric, "numerator": int(numerator),
           "denominator": base["denominator"],
           "flag_basis_count": base["flag_basis_count"],
           "n_nondecidable": base["n_nondecidable"],
           "nondecidable_breakdown": dict(base["breakdown"]),
           "flag_key": flag_key, "value_key": value_key, "n_rows": base["n_rows"]}
    if note:
        rec["note"] = note
    return rec


def _int_field(rec: Mapping, key: str) -> tuple[int | None, list[str]]:
    if key not in rec or rec[key] is None:
        return None, ["缺 %s（比例/通过率必须同时给出可判定基数与标志口径计数）" % key]
    v = rec[key]
    if isinstance(v, bool) or not isinstance(v, int):
        return None, ["%s 必须是整数，实得 %r（%s）—— 字符串/浮点分母一律拒绝"
                      % (key, v, type(v).__name__)]
    return v, []


def check_rate_record(rec: Mapping, *, rows: Sequence[Mapping] | None = None) -> list[str]:
    """检查一条比例/通过率记录的**分母纪律**；返回中文问题清单（空 = 合格）。

    `rows` 给了就**独立复算**一遍并逐项对照 —— 那样才能抓住「146 被当成 108」这类
    「口径写错但内部自洽」的形态。
    """
    problems: list[str] = []
    if not isinstance(rec, Mapping):
        return ["比例记录不是字典：%r" % type(rec).__name__]
    metric = rec.get("metric")
    if not isinstance(metric, str) or not metric.strip():
        problems.append("缺 metric（说不清这个比例是什么）")

    den, p = _int_field(rec, "denominator")
    problems += p
    flag, p = _int_field(rec, "flag_basis_count")
    problems += p
    num, p = _int_field(rec, "numerator")
    problems += p
    if den is None or flag is None or num is None:
        return problems                      # 缺数就没法再往下判，直接拒

    if den <= 0:
        problems.append("denominator=%d ≤ 0 ⇒ 分母非法（空集不得当分母）" % den)
    if num < 0:
        problems.append("numerator=%d < 0" % num)
    if flag < den:
        problems.append("flag_basis_count=%d < denominator=%d ⇒ 两个口径矛盾"
                        % (flag, den))
    if num > den:
        problems.append("numerator=%d > denominator=%d ⇒ 分子超出可判定基数"
                        % (num, den))

    if "n_nondecidable" in rec and rec["n_nondecidable"] is not None:
        nd, p = _int_field(rec, "n_nondecidable")
        problems += p
        if nd is not None:
            if nd < 0:
                problems.append("n_nondecidable=%d < 0" % nd)
            elif flag - nd != den:
                problems.append(
                    "分母口径不自洽：flag_basis_count(%d) − n_nondecidable(%d) = %d ≠ "
                    "denominator(%d)" % (flag, nd, flag - nd, den))
    else:
        # ⚠️ 这一条是**必需的**，不是形式主义：真实事故里正是「146 里有多少行不可判定」
        # 这个数没人写下来 ⇒ 分母 146 与 108 的差别**看不见**。哪怕差额是 0 也要显式写。
        problems.append(
            "缺 n_nondecidable（标志口径与可判定基数的**差额必须显式给出**，哪怕为 0）"
            "⇒ 无法看出「flag 口径 %d 行里有多少行不可判定」，也就无法复算分母" % flag)

    if rows is not None:
        base = decidable_base(rows, flag_key=str(rec.get("flag_key") or "usable"),
                              value_key=str(rec.get("value_key") or "Q"),
                              label=str(metric))
        if base["flag_basis_count"] != flag:
            problems.append("复算不符：flag_basis_count 记录 %d，逐行复算 %d"
                            % (flag, base["flag_basis_count"]))
        if base["denominator"] != den:
            problems.append(
                "复算不符：denominator 记录 %d，逐行复算（标志为真且值可判定）= %d"
                "（差 %+d 行不可判定：%s）⇒ **不可判定行被算进了分母**"
                % (den, base["denominator"], den - base["denominator"],
                   base["breakdown"] or "—"))
        if "n_nondecidable" in rec and rec["n_nondecidable"] is not None:
            if base["n_nondecidable"] != rec["n_nondecidable"]:
                problems.append("复算不符：n_nondecidable 记录 %s，逐行复算 %d"
                                % (rec["n_nondecidable"], base["n_nondecidable"]))
    return problems


def assert_rate_record(rec: Mapping, *, rows: Sequence[Mapping] | None = None) -> dict:
    """`check_rate_record()` 的断言版：不合格即抛 `DenominatorDisciplineError`。"""
    problems = check_rate_record(rec, rows=rows)
    if problems:
        raise DenominatorDisciplineError(
            "比例记录不合格：\n  - %s" % "\n  - ".join(problems))
    return dict(rec)


def ratio(rec: Mapping, *, rows: Sequence[Mapping] | None = None) -> tuple[int, int]:
    """取（分子, 可判定基数）。不合格 ⇒ 抛出，**绝不返回一个错分母的比例**。"""
    assert_rate_record(rec, rows=rows)
    return int(rec["numerator"]), int(rec["denominator"])


def format_rate(rec: Mapping, *, rows: Sequence[Mapping] | None = None,
                digits: int = 1) -> str:
    """渲染成**两个口径都在**的一行文本（报告里直接粘贴，想漏都漏不掉）。"""
    assert_rate_record(rec, rows=rows)
    num, den = int(rec["numerator"]), int(rec["denominator"])
    flag = int(rec["flag_basis_count"])
    nd = flag - den
    tail = "；标志口径可用 %d" % flag
    if nd:
        tail += "，其中 %d 行不可判定（已剔除，未计入分母）" % nd
    return "%s = %d/%d = %.*f%%%s" % (rec.get("metric", "比例"), num, den,
                                     digits, 100.0 * num / den, tail)
