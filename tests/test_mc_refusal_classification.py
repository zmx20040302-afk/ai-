# -*- coding: utf-8 -*-
"""§104 拒答归类回归：结构约束 vs N2 越域的**子串碰撞**。

背景（§101.5 / §102 实测登记，本轮修）：
`check_domain()` 的结构约束原文是 `该层不存在：要求 N_w_te1 < N_w_te2`，
**这句本身含子串 `N_w_te2`**；`_classify_refusal()` 按顺序匹配子串 ⇒
若 N2 分支排在结构约束之前，结构约束会被**误报成 N2 越域**。
E3 的 476 点网格上实测有 **102** 条被误标（真实触发是结构约束 `N1 ≥ N2`）。

本文件锁三件事（缺一不可）：
① 结构约束消息 ⇒ 判 `layer_does_not_exist`（**不是** `n2_out_of_domain`）；
② **真的** N2 越域 ⇒ 仍判 `n2_out_of_domain`（证明没把该分支废掉）；
③ **聚合回归**：E3 同一网格（17×7×4 = 476）上「接受 323 / 拒答 153 / 网格 476」
   三项不变，且逐点**接受/拒答判定**与冻结 CSV 一致 —— 只允许标签归属变。
"""
from __future__ import annotations

import collections
import csv
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
MODEL = REPO / "work/runs/multichannel-surrogate-20260929/multichannel_model.json"
FROZEN_CSV = REPO / "work/runs/paper-evidence-20261009/E3_refusal_grid_points.csv"

sys.path.insert(0, str(REPO / "src"))

from memsharness import multichannel_surrogate as MCS  # noqa: E402

needs_model = pytest.mark.skipif(
    not MODEL.is_file(),
    reason="缺多通道代理模型（work/ 不进版本库）⇒ 先跑 export_multichannel_model.py")


def _refusal_message(x, n1, n2) -> str:
    """取 `predict()` 真正抛出的拒答原文（不手写消息，避免与实现脱钩）。"""
    with pytest.raises(MCS.Refused) as ei:
        MCS.predict(x, n1, n2, channels=list(MCS.FORMAL_OBJECTIVES), alpha=0.05)
    return str(ei.value)


# ---------------------------------------------------------------- ① 结构约束
@pytest.mark.parametrize("n2", [5, 6, 7, 8])
def test_structural_layer_missing_is_not_misread_as_n2_out_of_domain(n2):
    """① 结构约束 `N1 ≥ N2`（层不存在）必须判 `layer_does_not_exist`。

    同时**显式断言碰撞前提成立**（消息里确实含 `N_w_te2` 子串）——
    否则本用例会因「消息措辞改了」而变成假通过。
    """
    msg = _refusal_message(0.50, n2, n2)          # N1 == N2 ⇒ 结构约束
    assert "该层不存在" in msg, msg
    assert "N_w_te2" in msg, "碰撞前提不成立（结构约束消息里已无 N_w_te2 子串）：%s" % msg
    assert MCS._classify_refusal(msg) == "layer_does_not_exist", msg
    assert MCS._classify_refusal(msg) != "n2_out_of_domain", msg

    # N1 > N2 同样成立（N2=5 时 N1 ∈ {5,6,7}）
    n1 = n2 + 1
    msg2 = _refusal_message(0.50, n1, n2)
    assert "该层不存在" in msg2, msg2
    assert MCS._classify_refusal(msg2) == "layer_does_not_exist", msg2


# ---------------------------------------------------------------- ② N2 越域
@pytest.mark.parametrize("n2", [4, 10, 11])
def test_genuine_n2_out_of_domain_still_classified_as_n2(n2):
    """② 真正的 N2 越域（N2 ∉ [5,9]，9 是 1 步外推上限、**属域内**）必须仍判 `n2_out_of_domain`。

    这条是「没把 N2 分支废掉」的反证：仅靠调顺序的修复不得让它变成
    `layer_does_not_exist` 或 `other`。
    """
    msg = _refusal_message(0.50, 1, n2)
    assert "N_w_te2 必须在 [5, 9]" in msg, msg
    assert "该层不存在" not in msg, "N2 越域的消息里不应出现结构约束措辞：%s" % msg
    assert MCS._classify_refusal(msg) == "n2_out_of_domain", msg

    # 且 N2 越域优先于结构约束报出时（N1 ≥ N2，例如 x 合法但 N2=4、N1=6），
    # 归类跟随**真实抛出**的消息，不臆断
    msg2 = _refusal_message(0.50, 6, 4)
    assert MCS._classify_refusal(msg2) == "n2_out_of_domain", msg2


def test_other_branches_unchanged_by_the_reorder():
    """顺序修复**不得**动到其它分支：全部实有拒答原文字典逐个钉住。"""
    cases = {
        "x_scale 必须在 [0.20, 1.00]（批 C 的标定范围）": "x_out_of_domain",
        "N_w_te1 必须是 ≥1 的整数（收到 0.0）": "other",
        "α 只认 [0.1, 0.05, 0.01]（其它取值没有校准记录）": "other",
        '该组合在所有请求通道上都无法预测：{"bandwidth_Hz": "x 超出该层标定的 x 范围（不外推）"}':
            "x_outside_layer_range",
        '该组合在所有请求通道上都无法预测：{"bandwidth_Hz": "训练层里没有该 N1 ⇒ 无法预测"}':
            "no_layer_for_n1",
        '该组合在所有请求通道上都无法预测：{"bandwidth_Hz": "N2 外推超过 1 步 ⇒ 拒答"}':
            "n2_extrap_too_far",
        '该组合在所有请求通道上都无法预测：{"bandwidth_Hz": "该 N1 在训练层里只有一层，单点无法线性外推"}':
            "need_two_layers",
        '该组合在所有请求通道上都无法预测：{"bandwidth_Hz": "外推所需的两层在同一个 x 上没有标定值"}':
            "x_missing",
    }
    got = {m: MCS._classify_refusal(m) for m in cases}
    assert got == cases, "调顺序改变了其它分支的归类：%s" % {
        m: (cases[m], got[m]) for m in cases if got[m] != cases[m]}


# ---------------------------------------------------------------- ③ 聚合回归
@needs_model
def test_e3_476_grid_totals_invariant_under_classification_fix():
    """③ E3 同一网格：接受/拒答/网格三项**与修复前逐项相同**，只允许标签归属变。

    修复前（冻结产物）：`n2_out_of_domain` 102 + `x_outside_layer_range` 51 = 153 拒答。
    子串碰撞修复后：`layer_does_not_exist` 102 + `x_outside_layer_range` 51 = 153。

    **2026-10-11 追加（门禁 #10）**：`predict()` 开始读模型的 `excluded_quarantine`
    ⇒ `(x=0.2, N1=1, N2=7)` 与 `(x=0.2, N1=1, N2=8)` 两个**隔离点**由
    `x_outside_layer_range` **改归** `quarantined_pending_rerun`（这两点本就不在层标定范围内，
    故**总账不变**：仍 323 接受 / 153 拒答 / 476 网格，`in_layer` 仍 323）。
    这只是把「原因归属」说得更准：隔离点的正确处置是**重跑标签**，不是「x 不在标定范围」。
    """
    names = list(MCS.FORMAL_OBJECTIVES)
    xs = [round(min(1.00, 0.20 + i * 0.05), 6)
          for i in range(int(round((1.00 - 0.20) / 0.05)) + 1)]
    reasons, modes, decisions = collections.Counter(), collections.Counter(), []
    by_pair = collections.defaultdict(collections.Counter)
    quarantine_pts = set()
    for x in xs:
        for n1 in range(1, 8):
            for n2 in range(5, 9):
                try:
                    r = MCS.predict(x, n1, n2, channels=names, alpha=0.05)
                except MCS.Refused as exc:
                    k = MCS._classify_refusal(str(exc))
                    reasons[k] += 1
                    by_pair[(n1, n2)][k] += 1
                    if k == "quarantined_pending_rerun":
                        quarantine_pts.add((x, n1, n2))
                    decisions.append((x, n1, n2, "refused"))
                    continue
                modes[r["mode"]] += 1
                decisions.append((x, n1, n2, "accepted"))

    n_grid = len(xs) * 7 * 4
    assert n_grid == 476, n_grid
    # ① 三项账不变
    assert len(decisions) == 476
    assert sum(modes.values()) == 323, modes
    assert sum(reasons.values()) == 153, reasons
    assert modes == {"in_layer": 323}, modes
    # ② 标签归属：结构约束 102 + x 超标定 49 + 隔离点 2 = 153
    assert dict(reasons) == {"layer_does_not_exist": 102, "x_outside_layer_range": 49,
                             "quarantined_pending_rerun": 2}, dict(reasons)
    assert reasons["n2_out_of_domain"] == 0, "网格内 N2∈[5,8]⊂[5,9] ⇒ 真 N2 越域必须为 0"
    # ②b 被归为隔离的，必须**恰是**模型声明的隔离点（不是别的点被顺手划进来）
    m = MCS.load()
    declared = {(float(q[0]), float(q[1]), float(q[2])) for q in (m.get("excluded_quarantine") or [])}
    assert quarantine_pts == {q for q in declared
                              if q[0] in xs and 1 <= q[1] <= 7 and 5 <= q[2] <= 8}, \
        "隔离桶里的点与模型声明不一致：%s" % sorted(quarantine_pts)
    # ③ 结构约束 = 6 组 (N1,N2) × 17 个 x = 102
    struct_pairs = {k: v["layer_does_not_exist"] for k, v in by_pair.items()
                    if v.get("layer_does_not_exist")}
    assert struct_pairs == {(5, 5): 17, (6, 5): 17, (6, 6): 17,
                            (7, 5): 17, (7, 6): 17, (7, 7): 17}, struct_pairs

    # ④ 逐点**接受/拒答判定**必须与冻结 CSV 一致（只允许 mode_or_reason 列变）
    if FROZEN_CSV.is_file():
        with FROZEN_CSV.open(encoding="utf-8", newline="") as fh:
            frozen = [(float(r["x_scale"]), int(r["N_w_te1"]), int(r["N_w_te2"]), r["decision"])
                      for r in csv.DictReader(fh)]
        assert frozen == decisions, "接受/拒答判定被改动（本轮只允许改标签归属）"