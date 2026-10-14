# -*- coding: utf-8 -*-
"""跨批次纪律守卫的用例（`memsharness.sweep_analysis.check_batch_isolation`）。

这些用例守的是 `AGENTS.md` 红线 4/6 与注入稿 §8 的两条：

* **不同扫描范围（5–35 vs 5–50 MHz）不得混算、不得合成总分**；
* **删失（峰值卡在扫描端点）/ 截断（上截止点 = 端点）的组合不得进入排名**。

外加一条 2026-10-08 数据侧实测的坑：`x_scale` 的 **1 ulp 表示差**会让同一组合被判成两个组合，
使「新增数」**虚高**（实测把 83 误报成 117）。

判定语义与 S3/A5 一致：`passed=False` ⇒ failed；`passed=None` ⇒ inconclusive 且**不放行**。
**本文件不测"有没有放宽"以外的东西** —— 每个拦截都要有"通过 / 不通过 / 无法判定"三种用例。

2026-10-08 **收紧一处**（`batch_censored_not_eligible`）：某批的标志列**整列为空** ⇒ 该批
**无法复验** ⇒ 本项 inconclusive（`None`），**不得**因为「空列里没有违规」就判 PASS ——
**空列 ≠ 通过**。判定次序固定为「先已发现的违规（failed）→ 再整列为空的批（None）→ 否则通过」，
故相对收紧前**只可能把 True 变成 None**，不会把 False 变成 None。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.consistency import evaluate_s3  # noqa: E402
from memsharness.sweep_analysis import check_batch_isolation  # noqa: E402


def rec(batch: str, x, n1: int, n2: int, rng: str = "5-35", **kw) -> dict:
    d = {"batch": batch, "x_scale": x, "N_w_te1": n1, "N_w_te2": n2,
         "freq_range_MHz": rng}
    d.update(kw)
    return d


def censored(**kw) -> dict:
    """默认"未删失、未截断、可排名"的一组标记列。"""
    d = {"peak_at_scan_endpoint": "False", "bw_upper_cutoff_at_endpoint": "False",
         "ranking_eligible": "True", "usable": "True"}
    d.update(kw)
    return d


def by_name(checks) -> dict:
    return {c.name: c for c in checks}


def gate(records) -> dict:
    """走与 CLI 相同的判定路径（不另造一套 verdict 逻辑）。"""
    return evaluate_s3(check_batch_isolation(records))


# ----------------------------- 通过 -----------------------------
def test_two_clean_batches_with_distinct_ranges_pass():
    rows = [rec("C_5-50MHz", 0.4, 1, 6, rng="5-50", **censored()),
            rec("C_5-50MHz", 0.5, 1, 6, rng="5-50", **censored()),
            rec("V2_5-35MHz", 0.6, 1, 9, rng="5-35", **censored()),
            rec("V2_5-35MHz", 0.7, 1, 9, rng="5-35", **censored())]
    v = gate(rows)
    assert v["verdict"] == "passed", v["reason"]
    assert v["release_allowed"] is True
    assert v["n_failed"] == 0 and v["n_inconclusive"] == 0


# ----------------------------- 判失败 -----------------------------
def test_rows_without_batch_label_fail():
    rows = [rec("C_5-50MHz", 0.4, 1, 6, **censored()),
            rec("", 0.5, 1, 6, **censored())]
    c = by_name(check_batch_isolation(rows))["batch_label_present"]
    assert c.passed is False
    assert "缺批次标签" in c.reason


def test_empty_input_fails_not_passes():
    c = by_name(check_batch_isolation([]))["batch_label_present"]
    assert c.passed is False, "空集绝不能算通过"
    assert "空集判失败" in c.reason


@pytest.mark.parametrize("label", ["all", "ALL", "combined", "merged", "综合", "合并", "全部"])
def test_aggregate_batch_label_fails(label):
    """聚合标签 = 有人把多批合成了一批 ⇒ 必须判失败（红线：不得混算/不得合成总分）。"""
    rows = [rec("C_5-50MHz", 0.4, 1, 6, **censored()),
            rec(label, 0.5, 1, 6, **censored())]
    c = by_name(check_batch_isolation(rows))["batch_no_merge_label"]
    assert c.passed is False
    assert "聚合标签" in c.reason


def test_two_scan_ranges_inside_one_batch_fail():
    """同一批次标签下混了两个扫描口径 ⇒ 判失败（同名两口径）。"""
    rows = [rec("V2_5-35MHz", 0.4, 1, 6, rng="5-35", **censored()),
            rec("V2_5-35MHz", 0.5, 1, 6, rng="5-50", **censored())]
    c = by_name(check_batch_isolation(rows))["batch_single_range[v2_5-35mhz]"]
    assert c.passed is False
    assert "同名两口径" in c.reason


@pytest.mark.parametrize("flag", ["peak_at_scan_endpoint", "bw_upper_cutoff_at_endpoint"])
def test_censored_or_truncated_row_marked_eligible_fails(flag):
    """删失/截断的组合**不得**被标为可排名/可用（红线 §8.5）。"""
    rows = [rec("V2_5-35MHz", 0.4, 1, 6, **censored(**{flag: "True"})),
            rec("V2_5-35MHz", 0.5, 1, 6, **censored())]
    c = by_name(check_batch_isolation(rows))["batch_censored_not_eligible"]
    assert c.passed is False
    assert flag in c.detail["examples"][0]["censored_by"]
    assert "不得把删失/截断组合当正常测量值" in c.reason


def test_censored_row_marked_eligible_only_via_usable_also_fails():
    """`usable`（v2 批的可用列）与 `ranking_eligible`（C 批）**都**要守。"""
    rows = [rec("V2_5-35MHz", 0.4, 1, 6,
                peak_at_scan_endpoint="True", bw_upper_cutoff_at_endpoint="False",
                ranking_eligible="", usable="True")]
    c = by_name(check_batch_isolation(rows))["batch_censored_not_eligible"]
    assert c.passed is False
    assert c.detail["examples"][0]["marked_eligible_by"] == ["usable"]


def test_empty_string_is_not_truthy():
    """空字符串**不是真**：缺列 / 未填不得被当作"没问题"。"""
    rows = [rec("V2_5-35MHz", 0.4, 1, 6,
                peak_at_scan_endpoint="True", bw_upper_cutoff_at_endpoint="False",
                ranking_eligible="", usable="")]
    c = by_name(check_batch_isolation(rows))["batch_censored_not_eligible"]
    assert c.passed is True, "删失行没有被标为可用 ⇒ 本项不应报违规"


# ----------------------------- 无法判定（不放行）-----------------------------
def test_undeclared_scan_range_is_inconclusive_not_passed():
    rows = [rec("C_5-50MHz", 0.4, 1, 6, rng="", **censored()),
            rec("V2_5-35MHz", 0.5, 1, 6, rng="", **censored())]
    v = gate(rows)
    assert v["verdict"] == "inconclusive"
    assert v["release_allowed"] is False
    assert any(c.passed is None for c in check_batch_isolation(rows))


def test_missing_censor_columns_is_inconclusive_not_passed():
    """表里根本没有删失/截断列 ⇒ 判不了（**不等同通过**）。"""
    rows = [rec("C_5-50MHz", 0.4, 1, 6, rng="5-50"),
            rec("V2_5-35MHz", 0.5, 1, 6, rng="5-35")]
    c = by_name(check_batch_isolation(rows))["batch_censored_not_eligible"]
    assert c.passed is None
    assert "无法判定" in c.reason


def test_single_batch_is_inconclusive():
    """只有一个批次：没有混算风险，也不产生跨批证据 ⇒ 无法判定。"""
    rows = [rec("V2_5-35MHz", 0.4, 1, 6, **censored())]
    c = by_name(check_batch_isolation(rows))["batch_no_cross_batch_combo"]
    assert c.passed is None


@pytest.mark.parametrize("decimals", [6, 9])
def test_cross_batch_overlap_is_inconclusive_not_failed(decimals):
    """组合同时出现在两批 ⇒ 判"无法判定"，并报出重叠数。

    为什么不判 failed：重叠本身不是产物违规，但它让 batch **失去防泄漏整组切分键的资格**，
    结论因此不可放行。把它记成 failed 会让失败分类失去意义（与 A5 §check_effective_points 同一条纪律）。
    """
    rows = [rec("C_5-50MHz", 0.5, 1, 6, rng="5-50", **censored()),
            rec("V2_5-35MHz", 0.5, 1, 6, rng="5-35", **censored())]
    c = by_name(check_batch_isolation(rows, decimals=decimals))["batch_no_cross_batch_combo"]
    assert c.passed is None
    assert c.detail["n_overlap_normalized"] == 1
    assert c.detail["n_overlap_raw"] == 1
    assert c.detail["ulp_only_overlap"] == 0
    assert "防泄漏整组切分键" in c.reason
    assert gate(rows)["release_allowed"] is False


def test_one_ulp_representation_difference_is_detected_and_reported():
    """2026-10-08 数据侧实测：C 批 `0.30000000000000004` vs v2 批 `0.3`。

    不做 ulp 归一化 ⇒ 同一组合被判成两个 ⇒ **新增数虚高**（实测 83 被误报成 117）。
    守卫必须把「原样口径重叠 0、归一化口径重叠 1」这组数字并列报出。
    """
    rows = [rec("C_5-50MHz", 0.30000000000000004, 1, 7, rng="5-50", **censored()),
            rec("V2_5-35MHz", 0.3, 1, 7, rng="5-35", **censored())]
    c = by_name(check_batch_isolation(rows))["batch_no_cross_batch_combo"]
    assert c.passed is None
    assert c.detail["n_overlap_normalized"] == 1, "归一化后必须认出这是同一个组合"
    assert c.detail["n_overlap_raw"] == 0, "原样口径认不出（这正是虚高的来源）"
    assert c.detail["ulp_only_overlap"] == 1
    assert "虚高" in c.reason

    # 不归一化（decimals 大到位数内）时重叠数为 0 ⇒ 守卫会放过去 —— 说明默认必须归一化
    rows2 = [rec("C_5-50MHz", 0.30000000000000004, 1, 7, rng="5-50", **censored()),
             rec("V2_5-35MHz", 0.30000000001, 1, 7, rng="5-35", **censored())]
    c2 = by_name(check_batch_isolation(rows2, decimals=6))["batch_no_cross_batch_combo"]
    assert c2.passed is None and c2.detail["n_overlap_normalized"] == 1


# ----------------------------- verdict 语义 -----------------------------
def test_gate_releases_only_when_every_check_passes():
    ok = [rec("C_5-50MHz", 0.4, 1, 6, rng="5-50", **censored()),
          rec("V2_5-35MHz", 0.6, 1, 9, rng="5-35", **censored())]
    assert gate(ok)["release_allowed"] is True

    bad = [rec("C_5-50MHz", 0.4, 1, 6, rng="5-50", **censored()),
           rec("V2_5-35MHz", 0.6, 1, 9, rng="5-35",
               **censored(peak_at_scan_endpoint="True"))]
    v = gate(bad)
    assert v["verdict"] == "failed"
    assert v["release_allowed"] is False


# --------------- 派生列不能替代原始标志（2026-10-08 第 3 项待办的守卫）---------------
def test_usable_cannot_substitute_raw_censor_flags():
    """**派生 `usable` 不是原始标志的替代品**：只有 `usable`、没有原始列 ⇒ 判不了。

    2026-10-08 第 3 项待办的实测教训：并集表只保留了派生 `usable`、丢掉了
    `peak_at_scan_endpoint` / `bw_upper_cutoff_at_endpoint` ⇒ 门禁在这一项上
    **无法独立复验**（只能 inconclusive）。本用例把「不许用派生值顶替原始列」钉死。
    """
    rows = [rec("C_5-50MHz", 0.4, 1, 6, rng="5-50", usable="True"),
            rec("V2_5-35MHz", 0.6, 1, 9, rng="5-35", usable="True")]
    c = by_name(check_batch_isolation(rows))["batch_censored_not_eligible"]
    assert c.passed is None, "只有派生 usable ⇒ 必须判「无法判定」，不得算通过"
    assert "无法判定" in c.reason
    assert gate(rows)["release_allowed"] is False


def test_all_rows_marked_usable_still_inconclusive_without_raw_flags():
    """**每一行**都写了 `usable=True` 也一样判不了 —— 派生值再齐全也替代不了原始列。"""
    rows = [rec("C_5-50MHz", round(0.1 * i, 2), 1, 6, rng="5-50", usable="True",
                ranking_eligible="True") for i in range(1, 6)]
    rows.append(rec("V2_5-35MHz", 0.6, 1, 9, rng="5-35", usable="True"))
    c = by_name(check_batch_isolation(rows))["batch_censored_not_eligible"]
    assert c.passed is None
    assert gate(rows)["verdict"] == "inconclusive"


def test_raw_flags_blank_for_a_whole_batch_is_inconclusive_not_passed():
    """**① 某批标志列整列为空 ⇒ 本项判「无法判定」，不是 PASS**（2026-10-08 收紧）。

    收紧前的行为是**假通过**：C 批那两列全空（原表就没有），V2 批有值 ⇒ 整体求值 ⇒
    因为「空列里扫不出违规」而判 PASS。空列意味着**该批无法复验** ——
    「没看到违规」≠「没有违规」。实测：v3 并集表里 `C_5-50MHz` 1782 行与 `A_5-35MHz` 223 行
    该两列全空，只有 `V2_5-35MHz` 250 行有值。
    """
    rows = [rec("C_5-50MHz", 0.4, 1, 6, rng="5-50", usable="",
                peak_at_scan_endpoint="", bw_upper_cutoff_at_endpoint="",
                ranking_eligible="True"),
            rec("V2_5-35MHz", 0.6, 1, 9, rng="5-35",
                peak_at_scan_endpoint="False", bw_upper_cutoff_at_endpoint="False",
                usable="True")]
    c = by_name(check_batch_isolation(rows))["batch_censored_not_eligible"]
    assert c.passed is None, "整列为空 ⇒ 无法复验 ⇒ 必须是 None（不是 True、也不是 False）"
    assert c.detail["blank_batches"] == ["c_5-50mhz"], c.detail["blank_batches"]
    assert c.detail["per_batch_flag_coverage"]["c_5-50mhz"] == {
        "n_rows": 1,
        "n_flag_nonempty": {"peak_at_scan_endpoint": 0, "bw_upper_cutoff_at_endpoint": 0}}
    assert c.detail["per_batch_flag_coverage"]["v2_5-35mhz"]["n_flag_nonempty"] == {
        "peak_at_scan_endpoint": 1, "bw_upper_cutoff_at_endpoint": 1}
    # reason 必须**指名**整列为空的批，且写明「空列 ≠ 通过」
    assert "c_5-50mhz" in c.reason and "整列为空" in c.reason
    assert "空列 ≠ 通过" in c.reason
    assert "无法复验" in c.reason
    assert gate(rows)["verdict"] == "inconclusive"
    assert gate(rows)["release_allowed"] is False


def test_all_batches_with_raw_flag_values_and_no_violation_still_pass():
    """**② 所有批的标志列都有值、且无违规 ⇒ 仍然 PASS**（证明没变成「一律 inconclusive」）。"""
    rows = [rec("C_5-50MHz", 0.4, 1, 6, rng="5-50",
                peak_at_scan_endpoint="False", bw_upper_cutoff_at_endpoint="False",
                ranking_eligible="True"),
            rec("V2_5-35MHz", 0.6, 1, 9, rng="5-35",
                peak_at_scan_endpoint="False", bw_upper_cutoff_at_endpoint="False",
                usable="True")]
    c = by_name(check_batch_isolation(rows))["batch_censored_not_eligible"]
    assert c.passed is True, c.reason
    assert c.detail["blank_batches"] == []
    assert c.detail["n_violations"] == 0
    assert gate(rows)["verdict"] == "passed"


def test_raw_flag_values_with_violation_still_fail():
    """**③ 有值且存在违规 ⇒ 仍然 failed**（证明没放松）。"""
    rows = [rec("C_5-50MHz", 0.4, 1, 6, rng="5-50",
                peak_at_scan_endpoint="False", bw_upper_cutoff_at_endpoint="False",
                ranking_eligible="True"),
            rec("V2_5-35MHz", 0.6, 1, 9, rng="5-35",
                peak_at_scan_endpoint="True", bw_upper_cutoff_at_endpoint="False",
                usable="True")]
    c = by_name(check_batch_isolation(rows))["batch_censored_not_eligible"]
    assert c.passed is False
    assert c.detail["blank_batches"] == []
    assert c.detail["n_violations"] == 1
    assert gate(rows)["verdict"] == "failed"


def test_censor_columns_absent_entirely_is_inconclusive_and_names_the_reason():
    """**④ 缺列（列不存在）⇒ inconclusive**，且 detail 里逐批报 `n_rows`。"""
    rows = [rec("C_5-50MHz", 0.4, 1, 6, rng="5-50", usable="True"),
            rec("V2_5-35MHz", 0.6, 1, 9, rng="5-35", usable="True")]
    c = by_name(check_batch_isolation(rows))["batch_censored_not_eligible"]
    assert c.passed is None
    assert "未提供任何删失/截断标记列" in c.reason
    assert gate(rows)["verdict"] == "inconclusive"


def test_blank_batch_plus_violation_elsewhere_is_still_failed_not_downgraded():
    """**⑤ 空列 + 别处有违规 ⇒ 仍 failed**（证明收紧**没有**把 False 降级成 None）。

    判定次序是「先看已发现的违规，再看整列为空的批」；若反过来，就会用「有批判不了」
    去掩盖一条**已经查到**的违规 —— 那是放宽，不是收紧。
    """
    rows = [rec("C_5-50MHz", 0.4, 1, 6, rng="5-50", usable="",
                peak_at_scan_endpoint="", bw_upper_cutoff_at_endpoint="",
                ranking_eligible="True"),
            rec("V2_5-35MHz", 0.6, 1, 9, rng="5-35",
                peak_at_scan_endpoint="True", bw_upper_cutoff_at_endpoint="False",
                usable="True")]
    c = by_name(check_batch_isolation(rows))["batch_censored_not_eligible"]
    assert c.passed is False, "已发现的违规不得因别的批整列为空而降级"
    assert c.detail["n_violations"] == 1
    assert c.detail["blank_batches"] == ["c_5-50mhz"]
    assert "空列 ≠ 通过" in c.reason          # 空列事实仍如实附在 reason 里
    assert gate(rows)["verdict"] == "failed"

