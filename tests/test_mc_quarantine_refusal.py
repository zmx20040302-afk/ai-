# -*- coding: utf-8 -*-
"""门禁 #10：**隔离名单必须真的挡住运行时查询**（不是只写在模型文件里）。

背景（`EDA65_RELEASE_GATE.json` 第 10 项）：拒答路径存在且被测过，但
**`predict()` 不读 `excluded_quarantine`** ⇒ 被隔离的组合仍可能通过邻层插值**拿到数字**，
把"标签待重跑"的未决数据伪装成已决结论。本文件把这条**锁成用例**：

1. **模型声明的每个隔离组合，`predict()` 必须拒答**，且原因代号 = `quarantined_pending_rerun`
   （遍历模型里的名单，不硬编码 —— 名单变了用例依然有效）；
2. 拒答**不返回任何数字**（抛异常，而不是返回 `None` 或部分值）；
3. **x 容差**：与隔离点相隔 1e-9 仍判隔离；相隔 1e-3 则走正常路径（不许把邻域整片封死）；
4. **邻近未隔离点不受影响**（证明不是"整层禁掉"）；
5. `screen()` 的拒答直方图里必须有该桶且计数正确（筛查排名不得混入隔离点）；
6. 隔离名单在 **model_card** 里可见（运行时拒答与声明台账一致）。

缺模型文件时**跳过而非静默通过**。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from memsharness import multichannel_surrogate as MCS  # noqa: E402

pytestmark = pytest.mark.skipif(
    not MCS.MODEL_PATH.is_file(),
    reason="缺多通道模型（work/ 不进版本库）⇒ 先跑 fit_multichannel_surrogate.py")


@pytest.fixture(scope="module")
def model():
    return MCS.load()


@pytest.fixture(scope="module")
def quarantines(model):
    qs = [(float(q[0]), float(q[1]), float(q[2])) for q in (model.get("excluded_quarantine") or [])]
    assert qs, "本模型没有隔离名单 ⇒ 本用例失去意义（应显式跳过或换模型），不得静默通过"
    return qs


def test_every_declared_quarantine_combo_is_refused(model, quarantines):
    """① 模型声明的**每一个**隔离组合都必须拒答，且原因代号正确。"""
    for (x, n1, n2) in quarantines:
        with pytest.raises(MCS.Refused) as ei:
            MCS.predict(x, n1, n2)
        code = MCS._classify_refusal(str(ei.value))
        assert code == "quarantined_pending_rerun", (
            "隔离组合 (x=%g, N1=%g, N2=%g) 的拒答原因被标成 %s —— "
            "隔离必须是一个**独立、可点名的**拒答类别，不得混进「x 超层标定」"
            % (x, n1, n2, code))
        assert MCS.QUARANTINE_CODE in str(ei.value)


def test_refusal_returns_no_numbers(model, quarantines):
    """② 拒答 = 抛异常；**调用方拿不到任何数值**（这是"fail-closed"的定义）。"""
    x, n1, n2 = quarantines[0]
    got = None
    try:
        got = MCS.predict(x, n1, n2)
    except MCS.Refused:
        pass
    assert got is None, "隔离组合竟然返回了结果：%r" % (got,)


def test_quarantine_match_is_tight_not_blanket(model, quarantines):
    """③ x 容差：1e-9 仍隔离；1e-3 不因隔离被拒（只可能因别的正当理由被拒）。"""
    x, n1, n2 = quarantines[0]
    with pytest.raises(MCS.Refused) as ei:
        MCS.predict(x + 1e-9, n1, n2)
    assert MCS._classify_refusal(str(ei.value)) == "quarantined_pending_rerun"
    try:
        MCS.predict(x + 1e-3, n1, n2)
    except MCS.Refused as exc:
        assert MCS._classify_refusal(str(exc)) != "quarantined_pending_rerun", (
            "容差过宽：x=%.6f 明明不是隔离点却被判隔离" % (x + 1e-3))


def test_neighbouring_point_still_predicts(model, quarantines):
    """④ 邻近未隔离点照常出数（隔离只针对点，不针对层）。"""
    x, n1, n2 = quarantines[0]
    r = MCS.predict(0.50, n1, n2)
    assert r["mode"] == "in_layer"
    for c in MCS.FORMAL_OBJECTIVES:
        assert r["channels"][c]["value"] is not None, "%s 未给值" % c


def test_screen_histogram_has_quarantine_bucket(model, quarantines):
    """⑤ 筛查：隔离点必须进 `refusal_reasons` 的独立桶，且**不混进排名**。"""
    rep = MCS.screen(x_min=0.20, x_max=0.60, x_step=0.05, n1_min=1, n1_max=2,
                     n2_min=7, n2_max=8, alpha=0.05)
    got = rep["refusal_reasons"].get("quarantined_pending_rerun", 0)
    # 该网格含 x=0.20 的 n1=1 两个隔离点
    expect = sum(1 for (qx, qn1, qn2) in quarantines
                 if qx == 0.20 and 1 <= qn1 <= 2 and 7 <= qn2 <= 8)
    assert got == expect, "隔离桶计数 %d ≠ 网格内隔离点 %d" % (got, expect)
    assert rep["n_predicted"] + rep["n_refused"] == rep["grid"]["n_points"]
    for c, obj in rep["per_objective"].items():
        for top in obj["top"]:
            assert (top["x_scale"], top["N_w_te1"], top["N_w_te2"]) not in [
                (qx, qn1, qn2) for (qx, qn1, qn2) in quarantines
                if qx == 0.20], "隔离点出现在 %s 的排名里" % c


def test_model_card_exposes_quarantine_list(model, quarantines):
    """⑥ 运行时拒答依据必须与声明台账一致（可审计）。"""
    card = MCS.model_card()
    listed = card["data"]["excluded_quarantine"]
    assert [(float(q[0]), float(q[1]), float(q[2])) for q in listed] == quarantines
