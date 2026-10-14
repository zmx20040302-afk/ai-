# -*- coding: utf-8 -*-
"""`metric_protocol_v2` 的离线自测（`src/memsharness/metrics_v2.py`）。

锁住裁定（`feedback` `fb-20260929T035510Z-17e73f1a`）里**写死**的东西：
* `p_floor` **只能用训练集**定；训练集为空 ⇒ 抛错（不许拿测试集代）；
* `|p_true| < p_floor` ⇒ 相对误差必须记 `not_applicable`（不是 0、不是省略）；
* dB 误差的判定带：`max` **不参与** pass/fail，但 `max>3 dB` 必须触发热点旗标；
* 配对胜负必须**五条同时满足**；"主体更优但 max 恶化"要单独成一种结论；
* 频谱**不再**输出 dB 空间相对 L2（那条已从主指标撤下）；
* 配对 bootstrap 用**固定种子**（可复现）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness import metrics_v2 as m  # noqa: E402


def test_protocol_name_and_bands_are_frozen():
    assert m.PROTOCOL == "metric_protocol_v2"
    assert m.BAND_DB["pass"] == {"median_max": 0.05, "p90_max": 0.20, "frac_gt_0p5_max": 0.05}
    assert m.BAND_DB["partial"] == {"p90_max": 0.50, "frac_gt_1_max": 0.05}
    assert m.BAND_DB["hotspot_max_db"] == 3.0
    assert m.PAIRED["win_rate_min"] == 0.55
    assert m.PAIRED["min_p90_gain_db"] == 0.10
    assert m.PAIRED["max_worsen_db"] == 0.5


def test_p_floor_uses_train_only_and_rejects_empty():
    assert m.training_p_floor([0.1, 1.0, 10.0, 100.0]) == pytest.approx(
        float(np.percentile([0.1, 1.0, 10.0, 100.0], 1)))
    # 噪声下限可以抬高它（注意：两点样本的第 1 百分位是 1.01，仍在 0.5 之上，
    # 所以这里必须用**百分位低于噪声下限**的数据才测得到 max() 的作用）
    assert m.training_p_floor([0.01, 0.02], noise_floor=0.5) == pytest.approx(0.5)
    assert m.training_p_floor([1.0, 2.0], noise_floor=0.5) == pytest.approx(1.01)
    with pytest.raises(ValueError):
        m.training_p_floor([])


def test_three_level_and_rel_error_not_applicable_below_floor():
    r = m.three_level_20MHz(spl_pred=100.0, spl_true=98.0, p_pred=0.01, p_true=0.02, p_floor=1.0)
    assert r["main_abs_error_spl20_dB"] == pytest.approx(2.0)
    assert r["aux_abs_error_p20_Pa"] == pytest.approx(0.01)
    assert r["diag_rel_error"] is None
    assert "not_applicable" in r["diag_rel_error_status"]
    # 高于下限 ⇒ 正常给相对误差
    r2 = m.three_level_20MHz(100.0, 98.0, 11.0, 10.0, p_floor=1.0)
    assert r2["diag_rel_error"] == pytest.approx(0.1)
    assert r2["diag_rel_error_status"] == "ok"


def test_db_stats_reports_all_required_numbers():
    s = m.db_error_stats([0.01, 0.02, 0.3, 0.6, 1.5, 4.0])
    for k in ("n", "median", "p90", "p99", "max", "frac_gt_0p5", "frac_gt_1"):
        assert k in s, k
    assert s["n"] == 6 and s["max"] == pytest.approx(4.0)
    # >0.5 的有 0.6 / 1.5 / 4.0 共 3 个；>1.0 的有 1.5 / 4.0 共 2 个
    assert s["frac_gt_0p5"] == pytest.approx(3 / 6)
    assert s["frac_gt_1"] == pytest.approx(2 / 6)


def test_verdict_max_does_not_decide_but_flags_hotspot():
    """主体很好但有一个 4 dB 热点 ⇒ 判定仍是 pass，但必须带热点旗标。"""
    good = m.db_error_stats([0.01] * 39 + [4.0])
    v = m.verdict_db(good)
    assert v["verdict"] == "pass", "max 不得单独把 pass 拉成 fail"
    assert v["local_hotspot_unclosed"] is True
    assert "局部未闭合热点" in v["reason"]
    # 没有热点时不应置旗标
    v2 = m.verdict_db(m.db_error_stats([0.01, 0.02, 0.03]))
    assert v2["verdict"] == "pass" and v2["local_hotspot_unclosed"] is False
    # 中位/ p90 不合格 ⇒ fail / partial
    assert m.verdict_db(m.db_error_stats([0.3] * 10))["verdict"] == "partial"
    assert m.verdict_db(m.db_error_stats([1.0] * 10))["verdict"] == "fail"
    assert m.verdict_db({"n": 0})["verdict"] == "not_applicable"


def test_paired_verdict_requires_all_five_conditions():
    rng = np.random.default_rng(0)
    base = rng.uniform(0.2, 1.0, 200)
    # 模型一致更好（p90 改善明显、max 不恶化）
    better = base * 0.5
    r = m.paired_verdict(better, base)
    assert r["model_wins"] is True and r["reason"] is None
    assert r["conditions"]["c1_median_negative"] and r["conditions"]["c4_p90_gain"]
    # 完全一样 ⇒ 不满足
    r2 = m.paired_verdict(base.copy(), base)
    assert r2["model_wins"] is False and "c1_median_negative" in r2["reason"]
    # 主体更优但 max 恶化 1 dB ⇒ 单独一种结论，不算胜出
    worse_max = base * 0.5
    worse_max[0] = base[0] + 1.0
    r3 = m.paired_verdict(worse_max, base)
    assert r3["conditions"]["c1_median_negative"] and not r3["conditions"]["c5_max_not_worse"]
    assert r3["model_wins"] is False and "新灾难点" in r3["reason"]


def test_paired_bootstrap_is_reproducible():
    rng = np.random.default_rng(1)
    a = rng.uniform(0.1, 0.5, 120)
    b = a + 0.05
    r1 = m.paired_verdict(a, b)
    r2 = m.paired_verdict(a, b)
    assert r1["boot_median_d_ci95"] == r2["boot_median_d_ci95"]


def test_paired_requires_matched_lengths():
    with pytest.raises(ValueError):
        m.paired_verdict([0.1, 0.2, 0.3], [0.1, 0.2])


def test_spectrum_metrics_drops_db_space_relative_l2():
    t = np.linspace(80.0, 120.0, 21)
    p = t + 0.1
    s = m.spectrum_metrics(p, t)
    assert "abs_dB" in s and "rmse_dB" in s and "linear_amp_relL2" in s
    assert s["rmse_dB"] == pytest.approx(0.1, abs=1e-9)
    assert "rel_l2" not in s and "spectrum_relL2" not in s, "dB 空间相对 L2 已从主指标撤下"
    # 全带平移（基准平移）不会像相对 L2 那样被分母放大
    shifted = m.spectrum_metrics(t + 0.1, t)
    assert shifted["rmse_dB"] == pytest.approx(0.1, abs=1e-9)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
