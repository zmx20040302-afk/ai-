# -*- coding: utf-8 -*-
"""**守卫 P1-③「分母纪律」**（`src\\memsharness\\guards_denominator.py`）的用例。

事故背景（`INDEX §98.4.1` 实测）：V2 批的 `usable`（flag 口径）算出 **146** 行「可用」，
于是 Q 门禁的适用基数被写成「可用 146」。实测那 146 行里 **39 行字面 `nan`**，
其中 **38 行的两个端点标志都是「未删失、未截断」⇒ flag 口径判它们「可用」**
⇒ **真实可判定基数是 108**。数字 `40` 不变，但分母 146 → 108 会让通过率从 27.4% 变成 37.0%。

本文件用**合成数据复现这个形状**，并锁住纪律：比例/通过率必须同时携带两个口径，
缺任一即拒；`nan`/`None`/空值一旦被算进分母即拒。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from memsharness import guards_denominator as g   # noqa: E402


def v2_like_rows(n_flag: int = 146, n_nan: int = 38, n_other: int = 2) -> list[dict]:
    """复现 V2 形状：`n_flag` 行标志为可用，其中 `n_nan` 行的 Q 是字面 `nan`。"""
    rows = [{"cell": "te2_%d" % (5 + i % 5), "N1": 1 + i % 7, "N2": 5 + i % 5,
             "usable": True, "Q": (float("nan") if i < n_nan else 2.0 + (i % 7) * 0.1)}
            for i in range(n_flag)]
    rows += [{"cell": "te2_x", "usable": False, "Q": 3.0}] * n_other   # 删失/截断：不可用
    return rows


# ============================================================ ① 146 vs 108（核心复现）
def test_decidable_base_reproduces_146_vs_108():
    base = g.decidable_base(v2_like_rows(), label="V2 Q 门禁")
    assert base["n_rows"] == 148
    assert base["flag_basis_count"] == 146, "flag 口径可用数"
    assert base["n_nondecidable"] == 38
    assert base["denominator"] == 108, "**可判定基数**（146 − 38）"
    assert base["breakdown"] == {"nan": 38}


def test_well_formed_rate_record_passes_and_shows_both_bases():
    rows = v2_like_rows()
    rec = g.make_rate_record("V2 Q 达标率", 40, rows)
    assert g.check_rate_record(rec, rows=rows) == []
    assert g.ratio(rec, rows=rows) == (40, 108)
    text = g.format_rate(rec, rows=rows)
    assert "/108" in text and "146" in text and "38 行不可判定" in text, text


def test_naive_record_that_uses_flag_count_as_denominator_is_refused():
    """**反侧（原事故形态）**：把 `usable=146` 直接当分母 ⇒ 必须拒绝，且点出 108。"""
    rows = v2_like_rows()
    good = g.make_rate_record("V2 Q 达标率", 40, rows)
    naive = {k: v for k, v in good.items() if k != "n_nondecidable"}
    naive["denominator"] = naive["flag_basis_count"]          # 146 ⇒ 错

    problems = g.check_rate_record(naive)
    assert problems, "口径不一致却未给 n_nondecidable ⇒ 必须拒绝"
    joined = " ".join(problems)
    assert "n_nondecidable" in joined and "146" in joined, problems

    problems2 = g.check_rate_record(naive, rows=rows)
    joined2 = " ".join(problems2)
    assert "不可判定行被算进了分母" in joined2 and "108" in joined2, problems2

    with pytest.raises(g.DenominatorDisciplineError):
        g.ratio(naive, rows=rows)            # **绝不返回一个错分母的比例**
    with pytest.raises(g.DenominatorDisciplineError):
        g.format_rate(naive)


def test_zero_denominator_is_refused():
    rows = [{"usable": True, "Q": float("nan")} for _ in range(5)]
    rec = g.make_rate_record("全 nan", 0, rows)
    assert rec["denominator"] == 0
    problems = g.check_rate_record(rec)
    assert any("≤ 0" in p for p in problems), problems


# ============================================================ ② 缺任一即拒
@pytest.mark.parametrize("drop", ["denominator", "flag_basis_count"])
def test_missing_either_base_is_refused(drop):
    rows = v2_like_rows()
    rec = g.make_rate_record("V2 Q 达标率", 40, rows)
    rec.pop(drop)
    problems = g.check_rate_record(rec)
    assert problems and any(drop in p and "必须同时给出" in p for p in problems), problems
    with pytest.raises(g.DenominatorDisciplineError):
        g.assert_rate_record(rec)


def test_record_with_only_a_number_is_refused():
    """只报一个百分比、连分子分母都不给 ⇒ 拒。"""
    problems = g.check_rate_record({"metric": "Q 达标率", "numerator": 40})
    assert len(problems) >= 2, problems
    assert sum("必须同时给出" in p for p in problems) == 2, problems


def test_internally_consistent_but_wrong_record_needs_rows_to_catch():
    """**如实声明能力边界**：不给明细时，`146/146/0` 这种「内部自洽」的错记录抓不到
    （`0` 是假的不可判定行数）；一旦给出明细，必须抓到。

    ⇒ 纪律：比例类结果**必须能从明细复算**，`check_rate_record(rec, rows=…)` 才是完整判定；
    这也是 `make_rate_record()` 只能由明细行构造的原因。
    """
    rows = v2_like_rows()
    forged = {"metric": "V2 Q 达标率", "numerator": 40, "denominator": 146,
              "flag_basis_count": 146, "n_nondecidable": 0}
    assert g.check_rate_record(forged) == [], "不给明细时它看起来是自洽的（已知边界）"
    problems = g.check_rate_record(forged, rows=rows)
    assert problems and "不可判定行被算进了分母" in " ".join(problems), problems


@pytest.mark.parametrize("value", ["108", 108.0, True, None])
def test_non_integer_denominator_is_refused(value):
    rows = v2_like_rows()
    rec = g.make_rate_record("V2 Q 达标率", 40, rows)
    rec["denominator"] = value
    problems = g.check_rate_record(rec)
    assert problems, value
    assert any("denominator" in p for p in problems), problems


# ============================================================ ③ 不可判定值不得进分母
@pytest.mark.parametrize("bad_value,key", [
    (float("nan"), "nan"),
    (None, "none"),
    ("", "empty"),
    ("   ", "empty"),
    ("abc", "unparsable"),
    (float("inf"), "inf"),
])
def test_nondecidable_values_are_excluded_and_counted(bad_value, key):
    rows = [{"usable": True, "Q": 2.5}, {"usable": True, "Q": bad_value}]
    base = g.decidable_base(rows)
    assert base["flag_basis_count"] == 2
    assert base["denominator"] == 1, base
    assert base["n_nondecidable"] == 1
    assert base["breakdown"] == {key: 1}, base


@pytest.mark.parametrize("ok_value", [0, 0.0, -1.0, "2.5", 2.5])
def test_zero_and_numeric_strings_are_decidable(ok_value):
    """`0` 不是 `nan`：0 值必须算进分母（否则是另一种分母错误）。"""
    base = g.decidable_base([{"usable": True, "Q": ok_value}, {"usable": True, "Q": 1.0}])
    assert base["denominator"] == 2 and base["n_nondecidable"] == 0


def test_flag_false_and_missing_flag_are_not_in_either_base():
    rows = [{"usable": True, "Q": 1.0},
            {"usable": False, "Q": None},        # 删失/截断：不可用
            {"Q": 2.0},                          # 标志缺失
            {"usable": None, "Q": 2.0}]          # 标志为空
    base = g.decidable_base(rows)
    assert base["flag_basis_count"] == 1
    assert base["denominator"] == 1
    assert base["n_missing_flag"] == 2, base


# ============================================================ ④ 其它自洽性
def test_numerator_greater_than_denominator_is_refused():
    rec = g.make_rate_record("V2 Q 达标率", 40, v2_like_rows())
    rec["numerator"] = 109
    assert any("超出可判定基数" in p for p in g.check_rate_record(rec))


def test_flag_basis_smaller_than_denominator_is_refused():
    rec = g.make_rate_record("V2 Q 达标率", 40, v2_like_rows())
    rec["flag_basis_count"] = rec["denominator"] - 1
    assert any("两个口径矛盾" in p for p in g.check_rate_record(rec))


def test_n_nondecidable_mismatch_is_refused():
    rec = g.make_rate_record("V2 Q 达标率", 40, v2_like_rows())
    rec["n_nondecidable"] = 5                       # 与 146−108=38 不符
    assert any("口径不自洽" in p for p in g.check_rate_record(rec))


def test_recompute_disagreement_is_refused_even_if_internally_consistent():
    """内部自洽但**与明细不符**的记录也必须被拒（这正是「口径写错」最难抓的形态）。"""
    rows = v2_like_rows()
    rec = g.make_rate_record("V2 Q 达标率", 40, rows)
    rec["denominator"] = 100
    rec["flag_basis_count"] = 100
    rec["n_nondecidable"] = 0
    problems = g.check_rate_record(rec, rows=rows)
    joined = " ".join(problems)
    assert "复算不符" in joined and "108" in joined, problems


def test_missing_metric_is_refused():
    rec = g.make_rate_record("V2 Q 达标率", 40, v2_like_rows())
    del rec["metric"]
    assert any("缺 metric" in p for p in g.check_rate_record(rec))


def test_non_mapping_record_is_refused():
    assert g.check_rate_record([1, 2, 3]) == ["比例记录不是字典：'list'"]
