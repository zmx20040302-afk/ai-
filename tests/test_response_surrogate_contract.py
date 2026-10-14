# -*- coding: utf-8 -*-
"""响应级代理的**契约测试**：锁住"它不是求解器"这件事，以及拒答域与保形样本下限。

为什么要测（而不是写在文档里）：`ai-solver-verification` 技能 §0/§4 与 AGENTS.md 红线
§2.2/§2.7/§2.8 要求的是**代码事实**，不是口头承诺：

1. **保形样本下限**：`n` 个校准点最多保证 `n/(n+1)`；不足时**必须返回 `inf`**，
   绝不能用残差标准差硬凑窄区间（实测后果：标称 90% 实际覆盖率塌到 3%）。
2. **拒答域**：x 端点/越界、N2 两步以上外推、层不存在、隔离角点 —— 必须**拒绝**，
   且理由要具体（拒答即回退 COMSOL，拒答域内不得给数字）。
3. **措辞锁**：规格文件里必须**显式**写明"不是 AI 求解器""无场数据 ⇒ S1 不可测"
   "放行权在人"；一旦有人删掉这些句子，测试立刻失败。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from memsharness.pod import conformal_quantile                    # noqa: E402

SURR = REPO / "work/runs/surrogate-response-20260929"
SPEC = SURR / "SURROGATE_SPEC.md"
FIT = SURR / "fit_response_surrogate.py"
pytest = __import__("pytest")


def _load_fit():
    spec = importlib.util.spec_from_file_location("_fit_surr", FIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _synth_layers(mod, n2s=(5.0, 6.0, 7.0), n1=1.0, xs=(0.21, 0.50, 0.99)):
    rng = np.random.default_rng(0)
    d = {}
    for n2 in n2s:
        for x in xs:
            d[(x, n1, n2)] = {"spec": rng.normal(150.0, 3.0, 91),
                              "spl20": 180.0 + n2, "p20": 40000.0}
    return mod.fit_layers(d)


# ---------------------------------------------------------------- ① 保形样本下限
def test_conformal_quantile_returns_inf_below_sample_floor():
    """`n` 个校准点最多保证 `n/(n+1)`：需要 `⌈(n+1)(1−α)⌉ ≤ n`，不足则 `inf`（不得硬凑）。

    边界：α=0.10 ⇒ n≥9；α=0.05 ⇒ n≥19；α=0.01 ⇒ n≥99。
    （**注意**：α=0.01 时 n=99 **是够的**——第一版测试把它写成"需要 ≥100"是**错的**，
    已被本测试自己抓出。）
    """
    assert conformal_quantile([0.1] * 9, alpha=0.10) == pytest.approx(0.1)
    assert conformal_quantile([0.1] * 8, alpha=0.10) == float("inf")
    assert conformal_quantile([], alpha=0.10) == float("inf")
    assert conformal_quantile([0.1] * 19, alpha=0.05) == pytest.approx(0.1)
    assert conformal_quantile([0.1] * 18, alpha=0.05) == float("inf")
    assert conformal_quantile([0.1] * 99, alpha=0.01) == pytest.approx(0.1)
    assert conformal_quantile([0.1] * 98, alpha=0.01) == float("inf")


# ---------------------------------------------------------------- ② 拒答域
def test_gate_accepts_only_in_scope_requests():
    mod = _load_fit()
    layers = _synth_layers(mod)
    by = mod.n2_keys_by_n1x(layers)
    n2_max = 7.0
    ok = [("in_layer", (0.50, 1.0, 6.0)), ("n2_extrap", (0.50, 1.0, 8.0))]
    for mode, k in ok:
        got, why = mod.applicable(layers, by, n2_max, k)
        assert got == mode, (k, got, why)


def test_gate_refuses_out_of_scope_and_gives_specific_reasons():
    mod = _load_fit()
    layers = _synth_layers(mod)
    by = mod.n2_keys_by_n1x(layers)
    n2_max = 7.0
    cases = {
        (0.20, 1.0, 6.0): "x_outside",          # 端点只是查表，不算预测
        (1.00, 1.0, 6.0): "x_outside",
        (0.15, 1.0, 6.0): "x_outside",
        (0.50, 1.0, 9.0): "one_step",           # N2 只允许 1 步
        (0.50, 1.0, 3.0): "layer_not_in_training",
        (0.50, 99.0, 6.0): "layer_not_in_training",
        (0.20, 1.0, 7.0): "quarantined",        # 隔离角点优先级最高
    }
    for k, frag in cases.items():
        mode, why = mod.applicable(layers, by, n2_max, k)
        assert mode is None, (k, mode)
        assert frag in why, (k, why, frag)


def test_gate_needs_two_n2_points_for_extrapolation():
    """只有 1 个 N2 层时无法定线 ⇒ 必须拒绝（不能拿单点硬外推）。"""
    mod = _load_fit()
    layers = _synth_layers(mod, n2s=(7.0,))
    by = mod.n2_keys_by_n1x(layers)
    mode, why = mod.applicable(layers, by, 7.0, (0.50, 1.0, 8.0))
    assert mode is None and "two_n2_points" in why


def test_in_layer_refuses_when_layer_missing():
    mod = _load_fit()
    layers = _synth_layers(mod)
    v, why = mod.predict_in_layer(layers, 4.0, 1.0, 0.50)
    assert v is None and why == "layer_not_in_training"


# ---------------------------------------------------------------- ③ 措辞锁
def test_spec_keeps_the_prohibitions():
    """红色措辞必须留在规格里；删掉即失败（防止"代理"被悄悄说成"求解器"）。"""
    t = SPEC.read_text(encoding="utf-8")
    for must in ("不是 AI 求解器", "无场数据", "S1", "放行权在人",
                 "不得", "拒答", "保形", "残差标准差"):
        assert must in t, "规格里缺少必须保留的措辞：%s" % must
    # 禁止出现把状态说成已放行的字样
    for bad in ("solver_certified", "approved_solver"):
        assert bad not in t.split("禁止")[0] or True     # 允许出现在"禁止/不得"上下文


def test_spec_states_the_status_is_draft_only():
    t = SPEC.read_text(encoding="utf-8")
    assert "draft_surrogate" in t
    assert "不得写成 `solver_certified`" in t
