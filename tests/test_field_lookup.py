# -*- coding: utf-8 -*-
"""场级离散查表的契约测试：**只有实测点给场，插值一律拒答**。

锁住的是口径（不是"能跑"）：
* 小数 N1 ⇒ 必须拒答、且**不返回任何数字**；
* 不存在的层（N1 ≥ N2、N1 < 1）⇒ 拒答；
* 未测量过的 (x,N1,N2,f) ⇒ 拒答，并给出**覆盖范围**让人知道该查什么；
* 命中实测点 ⇒ 返回快照元数据（含导出方的 train/holdout 标注与是否需要下载）；
* 本模块**不得**出现任何插值/外推调用（结构检查）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

pytestmark = pytest.mark.skipif(
    not (REPO / "work/runs/te2_8_pod_fields_20261005/snapshot_index.tsv").is_file(),
    reason="缺导出清单（work/ 不进版本库）⇒ 查表无法核对")


@pytest.fixture()
def fl():
    from memsharness import field_lookup
    return field_lookup


def test_measured_integer_point_is_a_hit(fl):
    r = fl.lookup(0.20, 1, 8, 20000000.0)
    assert r["refused"] is False
    assert r["file"] == "x0.20_N01_f20MHz.mat"
    assert r["n_points"] and r["n_points"] > 0
    assert r["split"]["x_holdout_role"] in ("train", "holdout", "na")
    assert r["mode"] == "discrete_lookup" and r["interpolation"] == "forbidden"


def test_fractional_n1_is_refused_without_numbers(fl):
    r = fl.lookup(0.20, 4.5, 8, 20000000.0)
    assert r["refused"] is True
    assert "电极对数" in r["reason"] and "0.207" in r["reason"]
    assert r["fallback"] == "comsol"
    # 拒答不许夹带任何结果型数字
    for k in ("file", "n_points", "field", "rel_L2"):
        assert k not in r, "拒答里不该有 %s" % k


@pytest.mark.parametrize("n1,n2,frag", [(8, 8, "该层不存在"), (0, 8, "该层不存在"),
                                        (9, 8, "该层不存在")])
def test_impossible_layer_is_refused(fl, n1, n2, frag):
    r = fl.lookup(0.20, n1, n2, 20000000.0)
    assert r["refused"] is True and frag in r["reason"]


def test_unmeasured_x_is_refused_and_explains_coverage(fl):
    # ⚠️ 注意：清单的 x 覆盖 0.20–1.00 **步长 0.01** ⇒ 0.33 是**测过的**（我第一版用例就栽在这），
    #    真正未测的是步长之间的值，例如 0.205。
    r = fl.lookup(0.205, 1, 8, 20000000.0)
    assert r["refused"] is True
    cov = r["index_coverage"]
    assert cov["n_rows"] > 500
    assert 0.20 in cov["x_scale"] and 0.33 in cov["x_scale"]
    assert 0.205 not in cov["x_scale"]
    assert "拒答" in cov["note"]


def test_coverage_lists_only_measured_values(fl):
    cov = fl.coverage()
    assert cov["N_w_te2"] == [8.0], "本数据集只有 N2=8"
    assert cov["N_w_te1"] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    assert 20000000.0 in cov["freq_Hz"], "必须有 20 MHz"


def test_module_never_interpolates(fl):
    """结构检查：这个模块只允许查表，出现插值/拟合调用就是口径被破坏。"""
    src = Path(fl.__file__).read_text(encoding="utf-8")
    for bad in ("griddata", "RBFInterpolator", "PchipInterpolator", "np.interp",
                "interp1d", "polyfit", "lstsq"):
        assert bad not in src, "离散查表模块里出现了插值/拟合：%s" % bad
