# -*- coding: utf-8 -*-
"""多通道一阶峰代理的**诚实性回归门禁**。

这个代理最容易出的问题不是算错数，而是**把结论说得比证据强**。所以本文件锁的是：
1. **预注册不可事后改**：结果 JSON 里的 `prereg_sha256` 必须等于预注册文件当前哈希
   ⇒ 任何人改了判定带，这个用例立刻失败（"事后调参"被机械挡住）。
2. **覆盖率必须与精度同时出现**（D1）：每个通道的误差旁必须有 `coverage` 与分母。
3. **必须有点名机制**：未优于持续性基线的通道要被 `channels_without_lift` 点名，
   且报告正文必须出现对应段落 —— 不允许"精度达标"掩盖"模型无增值"。
4. **不得越过红线措辞**：`NOT_a_solver` 必在，且报告不得出现"免 COMSOL 出解/等价于 COMSOL"等宣称
   （否定语境除外）。
5. 结构自洽：判定值只能取 pass/partial/fail；`Q_factor` 必须标为非正式目标（只作门槛）。

表/结果缺失时**跳过而非静默通过**（work/ 不进版本库）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
HERE = REPO / "work/runs/multichannel-surrogate-20260929"
PREREG = HERE / "PREREG_multichannel_surrogate.md"
RESULT = HERE / "multichannel_surrogate.json"
REPORT = HERE / "MULTICHANNEL_SURROGATE_REPORT.md"

pytestmark = pytest.mark.skipif(
    not (RESULT.is_file() and PREREG.is_file()),
    reason="缺多通道代理产物（work/ 不进版本库）⇒ 先跑 fit_multichannel_surrogate.py")

sys.path.insert(0, str(REPO / "src"))

VERDICTS = {"pass", "partial", "fail", "no_data"}
FORBIDDEN_CLAIMS = ("免 COMSOL 出解", "等价于 COMSOL", "AI 求解器可用", "已验证等价")
NEGATION = ("不得", "禁止", "不是", "非", "不许", "不可", "避免", "未", "无")


@pytest.fixture(scope="module")
def res():
    return json.loads(RESULT.read_text(encoding="utf-8"))


def test_prereg_hash_is_locked(res):
    """**预注册不得事后修改**：结果里记的哈希必须等于文件当前哈希。"""
    import hashlib
    now = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    assert res["prereg_sha256"] == now, (
        "预注册文件已被改动（当前 %s ≠ 结果记录的 %s）⇒ 判定带可能被事后调整。"
        "若确需改口径，必须**另开一版**并重跑，而不是改这一版的预注册。" % (now[:16],
                                                                  res["prereg_sha256"][:16]))


def test_every_channel_reports_coverage_alongside_accuracy(res):
    """D1：每个精度数字旁必须有覆盖率与分母（'只报中位不报覆盖率'会误导）。"""
    main = res["folds"][0]
    assert main["channels"], "主判定折没有任何通道"
    for ch, d in main["channels"].items():
        assert "coverage" in d and d["coverage"] is not None, "%s 缺覆盖率" % ch
        assert d["n_defined_in_test"] > 0, "%s 分母为 0（覆盖率无意义）" % ch
        assert 0.0 <= d["coverage"] <= 1.0
        assert d["n_predicted"] <= d["n_defined_in_test"]
        assert d["refusal_reasons"] is not None, "%s 未记录拒答原因" % ch


def test_verdicts_and_refusal_reasons_are_wellformed(res):
    for f in res["folds"]:
        for ch, d in f["channels"].items():
            for mode, s in d["per_mode"].items():
                if s.get("n"):
                    assert s["verdict"] in VERDICTS, "%s/%s 判定值非法：%s" % (ch, mode, s["verdict"])
                    assert s["median"] is not None and s["p90"] is not None
            assert set(d["refusal_reasons"]).issubset({
                "x_out_of_domain", "n1_invalid", "n2_out_of_domain", "layer_does_not_exist",
                "x_outside_layer_range", "no_layer_for_n1", "n2_extrap_more_than_one_step",
                "need_two_layers_to_extrapolate", "x_missing_in_extrapolation_layers"}), \
                "%s 出现未声明的拒答原因：%s" % (ch, d["refusal_reasons"])


def test_persistence_baseline_present_and_lift_named(res):
    """**必须在场**：持续性基线对照 + 无增值通道被点名（否则'pass'会被误读成模型有用）。"""
    main = res["folds"][0]
    for ch, d in main["channels"].items():
        assert "baseline_persistence" in d, "%s 缺持续性基线对照" % ch
        assert "beats_persistence" in d, "%s 未判定是否优于基线" % ch
    no_lift = res["channels_without_lift"]
    assert isinstance(no_lift, list)
    # 点名必须与逐通道判定一致（不能只在汇总里写、逐通道里矛盾）
    for ch in no_lift:
        assert main["channels"][ch]["beats_persistence"] is False
    for ch, d in main["channels"].items():
        if d["beats_persistence"] is False and d["baseline_persistence"].get("median") is not None:
            assert ch in no_lift, "%s 未优于基线却没被点名" % ch
    # 汇总口径与逐通道一致
    for ch, v in res["summary_main_fold"].items():
        assert v["beats_persistence"] == main["channels"][ch]["beats_persistence"]


def test_formal_objectives_and_gate_only_channel(res):
    """三个正式目标必须在；`Q_factor` 必须是**非**正式目标（裁定：Q 只作门槛）。"""
    ch = res["channels"]
    for o in ("bandwidth_Hz", "abs_w_m", "abs_p_per_V_Pa"):
        assert ch[o]["is_formal_objective"] is True, "%s 应为正式目标" % o
    assert ch["Q_factor"]["is_formal_objective"] is False, "Q_factor 不得被当作正式目标"
    # §3.4 约束量绝不进目标集
    for c in ("abs_pv_W", "abs_stress_zz_N", "sGp_du_W", "u_du_m4s2"):
        assert c not in ch, "约束量进了代理目标（违反 §3.4）：%s" % c


def test_batches_never_mixed(res):
    """跨批分层：本代理只标定批 C，不得混入批 A。"""
    assert res["data"]["batch"] == "C"
    assert res["data"]["n_rows_used"] > 0
    assert len(res["data"]["excluded_quarantine"]) == 2


def test_no_solver_claim_and_forbidden_wording(res):
    """红线：不得声称求解器能力；且必须显式声明「不是求解器」。"""
    assert res["status"] == "draft", "模型状态必须是 draft（人保留放行权）"
    assert "NOT_a_solver" in res and res["NOT_a_solver"]
    text = REPORT.read_text(encoding="utf-8")
    assert "不是 AI 求解器" in text, "报告未显式声明不是求解器"
    for bad in FORBIDDEN_CLAIMS:
        for m in re.finditer(re.escape(bad), text):
            ctx = text[max(0, m.start() - 12):m.start()]
            assert any(n in ctx for n in NEGATION), \
                "报告出现未加否定的禁用宣称：%s（上下文：…%s）" % (bad, ctx)


def test_report_contains_required_sections(res):
    """报告必须包含：判读自查、无增值通道段落、覆盖率说明。"""
    text = REPORT.read_text(encoding="utf-8")
    for must in ("判读与自查", "结构性拒答", "覆盖率", "持续性基线", "draft"):
        assert must in text, "报告缺必需内容：%s" % must
    if res["channels_without_lift"]:
        assert "未优于持续性基线" in text, "有点名通道但报告没有对应段落"
