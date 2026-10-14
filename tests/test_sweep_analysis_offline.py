# -*- coding: utf-8 -*-
"""A5 扫描分析层的**离线自测**（pytest 风格；同时保留直接运行入口）。

这些测试是安全网的一部分：排名层出错（跨族合并、把被排除点混进排名、合成总分）
比没有排名更危险，所以每类拦截都要有"通过 / 不通过 / 无法判定"三种用例。

对应关系：
* 干净批次 ⇒ `ranked` 且 `release_allowed=True`；
* 缺族标签 / 空输入 / 排除率过高 / 有效点不足 ⇒ `failed`（不出结论）；
* 口径未批准 ⇒ `inconclusive` 且 **不放行**；
* 同 quantity_group 混用 20log10 与 10log10 ⇒ `failed`；
* 指标名含 `total_score` / 输出含 `weighted_score` ⇒ 直接拦截（禁止合成总分）；
* 被质量门排除的点**逐条单列**、NaN **不填 0**；
* 缺模型哈希/缺预检 ⇒ `provisional`（不可与其它批合并）；
* 选点：只在已声明网格、必须有实测邻居；无邻居/已测/budget 超限 ⇒ 进 `rejected`；
* 上游 failed/inconclusive ⇒ `next_batch` 为 `blocked` 且 `selected` 为空。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.sweep_analysis import (  # noqa: E402
    MetricSpec, Row, analyze, build_next_batch, check_no_composite_score,
    check_cross_family_isolation, render_md, render_next_batch_md,
    rows_from_records,
)

P = "Ptot_peak"
B = "BW_MHz"


def metrics() -> list[MetricSpec]:
    return [
        MetricSpec(P, "峰值功率", "W", "max", "drive_dependent",
                   exclude_flags=("sparse_frequency_grid",),
                   advisory_flags=("drive_not_verified",)),
        MetricSpec(B, "带宽", "MHz", "max", "response_20log10",
                   exclude_flags=("bandwidth_not_closed_3dB_Vave",)),
    ]


#: 一个**可解析且非空**的预检（红队实测：空预检 `{}` 会让排名降级为临时；这里给"正常批"用）
GOOD_PRECHECK = {"classification": {"F1|0.4": "clean", "F2|0.4": "clean"}}
#: 故意留空的预检，只在"空预检不得放行"的负向用例里用
EMPTY_PRECHECK_UNDER_TEST: dict = {}

def grid_rows(family: str = "F1", xs=(0.4, 0.5, 0.6, 0.7, 0.8), n1s=(1, 2, 3)) -> list[Row]:
    rows = []
    for x in xs:
        for n in n1s:
            rows.append(Row(family, {"x_scale": x, "N_w_te1": n},
                            {P: x * n, B: 10.0 - x}, set()))
    return rows


def _get(doc: dict, name: str) -> dict:
    return next(c for c in doc["checks"] if c["name"] == name)


def _getf(doc: dict, name: str, family: str = "F1") -> dict:
    """取逐族检查项（`effective_points[F1]` 这类）。"""
    return _get(doc, "%s[%s]" % (name, family))


# ---------------------------------------------------------------------------
# 基础：干净批次
# ---------------------------------------------------------------------------
def test_clean_batch_is_ranked_and_releasable():
    doc = analyze(grid_rows(), metrics(), min_effective=3, model_sha256="a" * 64,
                  precheck=GOOD_PRECHECK)
    assert doc["verdict"] == "ranked" and doc["release_allowed"] is True
    assert doc["provisional"] is False
    assert doc["no_composite_score"] is True
    assert doc["not_checked"] and doc["semantics"]
    assert json.dumps(doc, ensure_ascii=False)  # 可序列化


def test_rankings_are_per_family_and_never_merged():
    rows = grid_rows("F1") + [Row("F2", {"x_scale": 0.4, "N_w_te1": 1}, {P: 999.0, B: 1.0}, set()),
                              Row("F2", {"x_scale": 0.5, "N_w_te1": 1}, {P: 5.0, B: 1.0}, set()),
                              Row("F2", {"x_scale": 0.6, "N_w_te1": 1}, {P: 4.0, B: 1.0}, set())]
    doc = analyze(rows, metrics(), min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    groups = {(r["family"], r["metric"]) for r in doc["rankings"]}
    assert groups == {("F1", P), ("F1", B), ("F2", P), ("F2", B)}
    f2p = next(r for r in doc["rankings"] if r["family"] == "F2" and r["metric"] == P)
    assert f2p["top"][0]["value"] == 999.0 and len(f2p["families"]) == 1
    # F1 的排名里绝不能出现 F2 的点
    f1p = next(r for r in doc["rankings"] if r["family"] == "F1" and r["metric"] == P)
    assert all(t["params"]["x_scale"] in (0.4, 0.5, 0.6, 0.7, 0.8) for t in f1p["top"])


def test_pareto_front_is_non_dominated():
    doc = analyze(grid_rows(), metrics(), min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    pf = doc["pareto"][0]
    assert pf["n_front"] >= 1 and pf["n_considered"] == 15
    # 前沿内部不得存在支配关系：通过"任一维更大另一维更小"的单调结构间接验证
    for m in pf["members"]:
        for o in pf["members"]:
            if m is o:
                continue
            assert not (m["values"][P] <= o["values"][P] and m["values"][B] <= o["values"][B]
                        and m["values"] != o["values"])


# ---------------------------------------------------------------------------
# 负向：不出结论 / 判失败
# ---------------------------------------------------------------------------
def test_empty_input_fails():
    doc = analyze([], metrics(), min_effective=3)
    assert doc["verdict"] == "failed" and doc["release_allowed"] is False
    assert _get(doc, "input_nonempty")["passed"] is False


def test_missing_family_label_fails():
    rows = grid_rows()
    rows[0].family = ""
    doc = analyze(rows, metrics(), min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    assert _get(doc, "family_label_present")["passed"] is False
    assert doc["verdict"] == "failed"


def test_caliber_not_approved_is_inconclusive_and_not_released():
    doc = analyze(grid_rows(), metrics(), min_effective=3, model_sha256="a" * 64,
                  precheck=GOOD_PRECHECK, caliber_approved=False)
    assert doc["verdict"] == "inconclusive" and doc["release_allowed"] is False
    assert any("口径未批准" in r for r in doc["stop_reasons"])


def test_mixing_20log10_and_10log10_in_same_quantity_group_fails():
    ms = [MetricSpec("A_dB", "幅值", "dB", "max", "amplitude_20log10", quantity_group="G"),
          MetricSpec("P_dB", "功率", "dB", "max", "power_10log10", quantity_group="G")]
    rows = [Row("F1", {"x_scale": 0.4, "N_w_te1": 1}, {"A_dB": 1.0, "P_dB": 1.0}, set())
            for _ in range(5)]
    doc = analyze(rows, ms, min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    assert _get(doc, "caliber_consistency")["passed"] is False
    assert doc["verdict"] == "failed"


def test_metric_named_like_a_composite_score_is_rejected_at_construction():
    with pytest.raises(ValueError):
        MetricSpec("total_score", "总分", "-", "max", "absolute")
    with pytest.raises(ValueError):
        MetricSpec("weighted_sum", "加权和", "-", "max", "absolute")


def test_composite_score_key_in_payload_is_caught():
    cr = check_no_composite_score({"rankings": [{"metric": P}],
                                   "summary": {"weighted_score": 1.0}}, metrics())
    assert cr.passed is False and cr.detail["hits"]


def test_cross_family_ranking_is_caught():
    cr = check_cross_family_isolation([{"family": "F1", "families": ["F1", "F2"], "metric": P}])
    assert cr.passed is False


def test_excluded_points_are_listed_not_dropped_and_nan_is_not_zero_filled():
    rows = grid_rows()
    rows[0].flags.add("sparse_frequency_grid")          # (0.4, 1) 的 P 被排除
    rows[1].values[P] = None                            # (0.4, 2) 的 P 缺失
    doc = analyze(rows, metrics(), min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    excl = [e for e in doc["quality"]["excluded"] if e["metric"] == P]
    reasons = {tuple(e["reasons"]) for e in excl}
    assert ("sparse_frequency_grid",) in reasons
    assert ("missing_value",) in reasons
    ranked_params = [t["params"] for r in doc["rankings"] if r["metric"] == P for t in r["top"]]
    assert {"x_scale": 0.4, "N_w_te1": 1} not in ranked_params
    m = next(x for x in doc["measured"] if x["params"] == {"x_scale": 0.4, "N_w_te1": 2})
    assert m["values"][P] is None and "missing_value" in m["flags"]


def test_flag_rules_are_declared_by_the_caller():
    recs = [{"source_family": "F1", "x_scale": 0.4, "N_w_te1": 1, P: 1.0, B: 2.0,
             "n_freq_points": "5"}]
    rows = rows_from_records(recs, metric_keys=[P, B],
                            flag_rules={"sparse_frequency_grid":
                                        lambda r: float(r["n_freq_points"]) < 9})
    assert rows[0].flags == {"sparse_frequency_grid"}
    with pytest.raises(ValueError):
        rows_from_records(recs, metric_keys=[P, B], flag_rules={"not_a_known_flag": lambda r: True})


def test_high_exclusion_rate_is_inconclusive_not_failed():
    rows = grid_rows()
    for r in rows:
        if r.params["x_scale"] != 0.4:                  # 只留一列干净，排除率 0.8
            r.flags.add("sparse_frequency_grid")
            r.flags.add("bandwidth_not_closed_3dB_Vave")
    doc = analyze(rows, metrics(), min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    assert _getf(doc, "exclusion_rate")["passed"] is None     # 数据不足 ⇒ 无法判定
    assert doc["verdict"] == "inconclusive" and doc["release_allowed"] is False
    assert doc["quality"]["flag_counts"]["sparse_frequency_grid"] == 12


def test_all_points_excluded_is_failed_by_empty_effective_set():
    rows = grid_rows()
    for r in rows:
        r.flags.add("sparse_frequency_grid")
        r.flags.add("bandwidth_not_closed_3dB_Vave")
    doc = analyze(rows, metrics(), min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    assert _getf(doc, "effective_points")["passed"] is False   # 该族一个有效点都没有 ⇒ 判失败
    assert doc["verdict"] == "failed"


def test_too_few_effective_points_is_inconclusive_not_failed():
    rows = grid_rows(xs=(0.4, 0.5), n1s=(1,))          # 只有 2 个点
    doc = analyze(rows, metrics(), min_effective=5, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    assert _getf(doc, "effective_points")["passed"] is None
    assert doc["verdict"] == "inconclusive" and doc["stop_reasons"]


def test_one_bad_family_does_not_hide_a_usable_family():
    rows = grid_rows("F1")
    for r in rows:
        r.flags.add("sparse_frequency_grid")
        r.flags.add("bandwidth_not_closed_3dB_Vave")
    rows += grid_rows("F2", xs=(0.45, 0.55, 0.65, 0.75, 0.85))   # 与 F1 无重复参数点
    doc = analyze(rows, metrics(), min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    by = doc["quality"]["exclusion_rate_by_family"]
    assert by["F1"] == 1.0 and by["F2"] == 0.0
    assert _getf(doc, "exclusion_rate", "F1")["passed"] is None
    assert _getf(doc, "exclusion_rate", "F2")["passed"] is True
    # 逐族判定：F2 可用，但**顶层**整体不放行（保守）⇒ 且 failed 批次不向任何族放行
    assert doc["verdict_by_family"] == {"F1": "failed", "F2": "ranked"}
    assert doc["released_families"] == []
    assert doc["verdict"] == "failed" and doc["release_allowed"] is False


def test_missing_model_hash_or_precheck_degrades_to_provisional():
    doc = analyze(grid_rows(), metrics(), min_effective=3)   # 既无哈希又无预检
    assert doc["verdict"] == "provisional" and doc["release_allowed"] is False
    assert len(doc["provisional_reasons"]) == 2
    assert any("禁止与其它批合并" in r for r in doc["provisional_reasons"])


# ---------------------------------------------------------------------------
# A8 红队实测漏洞的回归（每条都对应一个真实被利用过的绕过）
# ---------------------------------------------------------------------------
def test_bogus_model_hash_and_empty_precheck_do_not_release():
    """红队 B：`{}` 空预检 + 任意 sha 字符串曾能拿到 ranked + release_allowed=true。"""
    doc = analyze(grid_rows(), metrics(), min_effective=3,
                  model_sha256="不是哈希", precheck=EMPTY_PRECHECK_UNDER_TEST)
    assert doc["verdict"] == "provisional" and doc["release_allowed"] is False
    assert doc["precheck"]["used"] is False and doc["precheck"]["problem"]
    assert any("64 位十六进制" in r for r in doc["provisional_reasons"])
    assert any("预检**不可用**" in r for r in doc["provisional_reasons"])


def test_valid_hash_and_precheck_still_rank():
    doc = analyze(grid_rows(), metrics(), min_effective=3, model_sha256="a" * 64,
                  precheck={"classification": {"F1|0.4": "clean"}})
    assert doc["verdict"] == "ranked" and doc["release_allowed"] is True
    assert doc["precheck"]["used"] is True and doc["precheck"]["n_not_clean"] == 0


def test_global_disqualifying_flags_remove_points_everywhere():
    """红队 C：标了 geometry_invalid+mesh_invalid 的点仍能排 Ptot 第 1 并进 Pareto。"""
    rows = grid_rows()
    rows[-1].flags.add("geometry_invalid")     # (0.8, 3) 本是 Ptot 最大
    rows[-1].flags.add("mesh_invalid")
    doc = analyze(rows, metrics(), min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    assert rows[-1].values[P] == max(r.values[P] for r in rows)   # 它确实是最大值
    for rk in doc["rankings"]:
        assert all(t["params"] != {"x_scale": 0.8, "N_w_te1": 3} for t in rk["top"])
    for pf in doc["pareto"]:
        assert all(m["params"] != {"x_scale": 0.8, "N_w_te1": 3} for m in pf["members"])
    assert {"geometry_invalid", "mesh_invalid"} <= set(doc["quality"]["flag_counts"])


def test_precheck_not_clean_is_globally_disqualifying():
    rows = grid_rows()
    doc = analyze(rows, metrics(), min_effective=3, model_sha256="a" * 64,
                  precheck={"classification": {"F1|0.8": "bc_conflict"}})
    assert doc["precheck"]["n_not_clean"] == 3          # x=0.8 的 3 个 N1
    for rk in doc["rankings"]:
        assert all(t["params"]["x_scale"] != 0.8 for t in rk["top"])
    assert any("全局取消排名资格" in r for r in doc["provisional_reasons"])


def test_global_failure_downgrades_all_families_and_releases_none():
    """红队 C：口径混用让顶层 failed 时，逐族曾仍报 ranked 且 released_families 非空。"""
    ms = [MetricSpec("A_dB", "幅值", "dB", "max", "amplitude_20log10", quantity_group="G"),
          MetricSpec("P_dB", "功率", "dB", "max", "power_10log10", quantity_group="G")]
    rows = [Row(f, {"x_scale": x, "N_w_te1": 1}, {"A_dB": 1.0, "P_dB": 1.0}, set())
            for f in ("F1", "F2") for x in (0.4, 0.5, 0.6)]
    doc = analyze(rows, ms, min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    assert doc["verdict"] == "failed"
    assert set(doc["verdict_by_family"].values()) == {"failed"}
    assert doc["released_families"] == []


def test_next_batch_output_also_passes_composite_guard():
    nb = build_next_batch(_scan_ok(), candidate_grid=[{"family": "F1", "x_scale": 0.9,
                                                       "N_w_te1": 3}])
    assert nb["no_composite_score"] is True
    # 反例：把总分字段塞进去，守卫必须命中（这条防止"只扫 scan_analysis 不扫 next_batch"复发）
    bad = dict(nb, weighted_score=0.5)
    cr = check_no_composite_score(bad, metrics())
    assert cr.passed is False and any("weighted_score" in h for h in cr.detail["hits"])


def test_same_params_in_two_families_is_rejected():
    """红队漏检 #9：同一参数点在两族各排 #1 会被读成"两族独立复算一致"。"""
    rows = grid_rows("F1") + grid_rows("F2")
    doc = analyze(rows, metrics(), min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    assert _get(doc, "no_cross_family_duplicate_points")["passed"] is False
    assert doc["verdict"] == "failed" and doc["released_families"] == []

def test_pareto_participants_must_be_clean_on_every_declared_metric():
    """红队漏检 #10：只在 Pareto 子集上判可比，会让"在别的指标上被排除的点"照样进前沿。"""
    rows = grid_rows()
    # 让 (0.8,3) 在 B 上被排除（B 不在 Pareto 子集里）
    rows[-1].flags.add("bandwidth_not_closed_3dB_Vave")
    doc = analyze(rows, metrics(), min_effective=3, model_sha256="a" * 64,
                  precheck=GOOD_PRECHECK, pareto_metrics=[P])
    pf = doc["pareto"][0]
    assert pf["gate_metrics"] == [P, B]
    assert all(m["params"] != {"x_scale": 0.8, "N_w_te1": 3} for m in pf["members"])
    assert pf["n_considered"] == 14


def test_declared_flag_rules_must_be_wired():
    """红队 C 的根因：预设里声明了 `degenerate_geometry` 等规则却从不接线（死规则）。"""
    sys.path.insert(0, str(REPO / "scripts"))
    import run_sweep_analysis as cli
    unwired = cli.assert_flag_rules_wired(cli.PMUT_METRICS, cli.PMUT_FLAG_RULES)
    assert unwired == [], "预设里存在声明未接线的质量标记：%r" % unwired
    # 反例：删掉唯一引用某规则的指标后，该规则必须被报出来
    trimmed = [m for m in cli.PMUT_METRICS if m.name != "Ptot_peak"]
    unwired2 = cli.assert_flag_rules_wired(trimmed, cli.PMUT_FLAG_RULES)
    assert "peak_at_range_edge" in unwired2          # 只有 Ptot_peak 用它
    assert "sparse_frequency_grid" not in unwired2    # 还有别的指标在用


# ---------------------------------------------------------------------------
# 下一批选点
# ---------------------------------------------------------------------------
def _scan_ok() -> dict:
    return analyze(grid_rows(), metrics(), min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)


def test_next_batch_requires_measured_neighbour():
    nb = build_next_batch(_scan_ok(),
                          candidate_grid=[{"family": "F1", "x_scale": 0.9, "N_w_te1": 3},
                                          {"family": "F1", "x_scale": 0.3, "N_w_te1": 9}],
                          budget=4)
    reasons = {r["reason"] for r in nb["rejected"]}
    assert any(r.startswith("no_measured_neighbour") for r in reasons)
    got = {json.dumps(s["params"], sort_keys=True) for s in nb["selected"]}
    assert json.dumps({"x_scale": 0.9, "N_w_te1": 3}, sort_keys=True) in got


def test_candidate_beyond_range_without_measured_slope_is_rejected():
    """该族只有一个实测点时，向外扩一格没有任何实测差分作依据 ⇒ 属于外推，必须被拒。"""
    rows = [Row("F1", {"x_scale": 0.4, "N_w_te1": 1}, {P: 1.4, B: 2.0}, set())]
    scan = analyze(rows, metrics(), min_effective=1, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    nb = build_next_batch(scan, candidate_grid=[{"family": "F1", "x_scale": 0.5, "N_w_te1": 1}])
    assert nb["verdict"] == "blocked"
    assert any("would_extrapolate_without_measured_slope" in r["reason"]
               for r in nb["rejected"])


def test_next_batch_rejects_already_measured_and_respects_budget():
    nb = build_next_batch(_scan_ok(),
                          candidate_grid=[{"family": "F1", "x_scale": 0.5, "N_w_te1": 2},
                                          {"family": "F1", "x_scale": 0.9, "N_w_te1": 1},
                                          {"family": "F1", "x_scale": 0.9, "N_w_te1": 2},
                                          {"family": "F1", "x_scale": 0.9, "N_w_te1": 3}],
                          budget=1)
    assert any(r["reason"] == "already_measured" for r in nb["rejected"])
    assert any(r["reason"] == "budget_exhausted" for r in nb["rejected"])
    assert nb["budget"]["n_selected"] == 1 <= nb["budget"]["max_points"]


def test_distance_is_counted_in_grid_steps_not_in_differing_keys():
    """实测踩坑：把「有 1 个键不同」当相邻 ⇒ (0.45,N1=4) 被误判为 (0.80,N1=4) 的邻居。"""
    nb = build_next_batch(_scan_ok(),
                          candidate_grid=[{"family": "F1", "x_scale": 0.9, "N_w_te1": 3},
                                          {"family": "F1", "x_scale": 0.45, "N_w_te1": 2}],
                          budget=4)
    got = {json.dumps(s["params"], sort_keys=True) for s in nb["selected"]}
    # (0.45,2) 距离最优点 (0.80,3) 有 7+1 格 ⇒ 只能作对照或不做，绝不能算"相邻细化"
    assert all(json.loads(g) != {"x_scale": 0.45, "N_w_te1": 2} or
               next(s for s in nb["selected"]
                    if s["params"] == {"x_scale": 0.45, "N_w_te1": 2})["role"] == "contrast"
               for g in got)


def test_string_param_values_match_numeric_candidate_grid():
    """CSV 参数是字符串、候选网格是数字 ⇒ 必须能对上同一个点（否则质量修复永远匹配不上）。"""
    recs = [{"source_family": "F1", "x_scale": "0.40", "N_w_te1": "6", P: 1.0, B: 2.0}
            for _ in range(4)]
    rows = rows_from_records(recs, metric_keys=[P, B])
    assert rows[0].params == {"x_scale": 0.4, "N_w_te1": 6}
    for r in rows:
        r.flags.add("sparse_frequency_grid")           # 让 P 被排除 ⇒ 触发质量修复
    scan = analyze(rows, metrics(), min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    nb = build_next_batch(scan, candidate_grid=[{"family": "F1", "x_scale": 0.4, "N_w_te1": 6}])
    assert nb["verdict"] == "proposed"
    assert nb["selected"][0]["role"] == "quality_repair"
    assert nb["selected"][0]["params"] == {"x_scale": 0.4, "N_w_te1": 6}


def test_next_batch_suggestions_always_carry_basis_and_stop_condition():
    nb = build_next_batch(_scan_ok(),
                          candidate_grid=[{"family": "F1", "x_scale": 0.9, "N_w_te1": 3}])
    assert nb["verdict"] == "proposed" and nb["release_allowed"] is True
    s = nb["selected"][0]
    assert s["expected_gain"]["basis"] and s["stop_condition"] and s["cost"]["n_solves"] >= 1
    assert s["role"] in ("quality_repair", "baseline_refine", "contrast")


def test_next_batch_repairs_a_quality_excluded_best_point():
    rows = grid_rows()
    for r in rows:
        if r.params["x_scale"] == 0.8 and r.params["N_w_te1"] == 3:
            r.flags.add("sparse_frequency_grid")        # 本批"最好"的点被质量门排除
    scan = analyze(rows, metrics(), min_effective=3, model_sha256="a" * 64, precheck=GOOD_PRECHECK)
    nb = build_next_batch(scan, candidate_grid=[{"family": "F1", "x_scale": 0.8, "N_w_te1": 3}])
    assert nb["verdict"] == "proposed"
    assert nb["selected"][0]["role"] == "quality_repair"
    assert nb["selected"][0]["params"] == {"x_scale": 0.8, "N_w_te1": 3}


def test_next_batch_is_blocked_when_scan_did_not_pass():
    scan = analyze([], metrics(), min_effective=3)
    nb = build_next_batch(scan, candidate_grid=[{"family": "F1", "x_scale": 0.9, "N_w_te1": 3}])
    assert nb["verdict"] == "blocked" and nb["selected"] == []
    assert nb["release_allowed"] is False and nb["stop_conditions"]
    assert "空集不得被读成" in nb["semantics"]


def test_next_batch_from_provisional_scan_is_not_released():
    scan = analyze(grid_rows(), metrics(), min_effective=3)      # 缺哈希/预检 ⇒ provisional
    nb = build_next_batch(scan, candidate_grid=[{"family": "F1", "x_scale": 0.9, "N_w_te1": 3}])
    assert nb["provisional"] is True and nb["release_allowed"] is False
    assert nb["verdict"] == "proposed" and nb["selected"]      # 建议仍在，但不得直接执行
    assert any("临时" in s for s in nb["stop_conditions"])


def test_next_batch_empty_grid_is_blocked_not_silently_ok():
    nb = build_next_batch(_scan_ok(), candidate_grid=[])
    assert nb["verdict"] == "blocked" and nb["blocked"] is True
    assert nb["budget"]["n_selected"] == 0 and nb["release_allowed"] is False


# ---------------------------------------------------------------------------
# 人读层
# ---------------------------------------------------------------------------
def test_render_md_states_calibers_and_not_checked():
    doc = _scan_ok()
    md = render_md(doc)
    assert "逐指标排名" in md and "Pareto" in md
    assert "没有" in md and "判定语义" in md
    nb = build_next_batch(doc, candidate_grid=[{"family": "F1", "x_scale": 0.9, "N_w_te1": 3}])
    md2 = render_next_batch_md(nb)
    assert "下一批选点建议" in md2 and "停止条件" in md2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
