"""A6 测试：POD 场级降阶骨架（掩膜 / 基 / 系数回归 / 场级留出误差）。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from memsharness import pod  # noqa: E402


def _analytic_family(thetas, nx=12, ny=9, Lx=0.01, Ly=0.008):
    """解析场族：T(x,y) = 300 + θ·(Lx−x)/Lx（一维沿 x 导热）→ POD 理论上 1 个模态足够。"""
    xs = np.linspace(0, Lx, nx)
    ys = np.linspace(0, Ly, ny)
    X, Y = np.meshgrid(xs, ys)
    snaps = [300.0 + t * (Lx - X) / Lx for t in thetas]
    params = [{"q_over_k": float(t)} for t in thetas]
    return params, [s.ravel() for s in snaps], np.column_stack([X.ravel(), Y.ravel()])


# ---------------- 掩膜 ----------------

def test_common_mask_keeps_only_always_finite_points() -> None:
    a = np.array([1.0, 2.0, np.nan, 4.0])
    b = np.array([1.0, 2.0, 3.0, np.nan])
    mask = pod.common_mask([a, b])
    assert mask.tolist() == [True, True, False, False]


def test_common_mask_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        pod.common_mask([])


# ---------------- POD 基 ----------------

def test_pod_needs_two_snapshots() -> None:
    with pytest.raises(ValueError):
        pod.fit_pod([np.zeros(5)])


def test_pod_rejects_constant_snapshots() -> None:
    """所有快照相同 → 无能量 → 不能建立基（必须显式报错而不是给出假基）。"""
    with pytest.raises(ValueError, match="能量为 0"):
        pod.fit_pod([np.ones(5), np.ones(5)])


def test_one_dimensional_family_needs_single_mode() -> None:
    params, snaps, _ = _analytic_family([1.0, 2.0, 3.0, 4.0])
    mask, mean, basis, sv, meta = pod.fit_pod(snaps, energy_ratio=0.999999)
    assert mask.all()
    assert basis.shape[0] == 1, "线性族应恰好只需 1 个模态"
    assert meta["cumulative_energy_at_n"] > 0.999999


def test_two_dimensional_family_needs_two_modes() -> None:
    """含两个独立空间模态的场族应需要 2 个模态。"""
    import numpy as np

    xs = np.linspace(0, 1, 15)
    ys = np.linspace(0, 1, 11)
    X, Y = np.meshgrid(xs, ys)
    snaps = [a * np.sin(np.pi * X) + b * np.sin(2 * np.pi * Y) for a, b in [(1, 1), (2, 1), (1, 3), (3, 2)]]
    _, _, basis, _, _ = pod.fit_pod([s.ravel() for s in snaps], energy_ratio=0.999999)
    assert basis.shape[0] == 2


# ---------------- 端到端：拟合并预测 ----------------

def test_fit_and_predict_reproduces_linear_family() -> None:
    thetas = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    params, snaps, _ = _analytic_family(thetas)
    model = pod.fit(params, snaps, energy_ratio=0.999999, n_members=3)
    assert model.n_modes == 1
    # 训练点上应几乎精确
    for point, snap in zip(params, snaps):
        field_mean, field_std = model.predict(point)
        err = pod.relative_l2_field(np.asarray(snap)[model.mask], field_mean)
        assert err < 1e-6
        assert field_std.shape == field_mean.shape


def test_holdout_report_flags_accuracy_and_coverage() -> None:
    params, snaps, _ = _analytic_family([1.0, 2.0, 3.0, 4.0, 5.0])
    model = pod.fit(params[:4], snaps[:4], energy_ratio=0.999999, n_members=3)
    report = pod.holdout_report(model, params[4:], snaps[4:])
    assert report["n_holdout"] == 1
    assert report["field_rel_l2_max"] < 0.05
    assert report["s1_passed"] is True
    assert 0.0 <= report["interval_coverage_90"] <= 1.0


def test_extrapolation_is_detected_by_error_growth() -> None:
    """外推到训练范围之外时误差应显著上升——这是 OOD 拒答的数值依据。"""
    params, snaps, _ = _analytic_family([1.0, 2.0, 3.0])
    model = pod.fit(params, snaps, energy_ratio=0.999999, n_members=3)
    inside = pod.holdout_report(model, [{"q_over_k": 1.5}], _analytic_family([1.5])[1])
    outside = pod.holdout_report(model, [{"q_over_k": 12.0}], _analytic_family([12.0])[1])
    assert inside["field_rel_l2_max"] < outside["field_rel_l2_max"]


def test_relative_l2_requires_nonzero_reference() -> None:
    with pytest.raises(ValueError, match="范数为 0"):
        pod.relative_l2_field(np.zeros(4), np.ones(4))


def test_mask_is_applied_in_prediction_shape() -> None:
    """掩膜后的点数应小于公共点集总数，预测输出长度与掩膜一致。"""
    params, snaps, _ = _analytic_family([1.0, 2.0, 3.0])
    broken = [s.copy() for s in snaps]
    broken[1][:5] = np.nan  # 第 2 个快照前 5 点域外
    model = pod.fit(params, broken, energy_ratio=0.999999, n_members=2)
    assert model.mask.sum() == snaps[0].size - 5
    field_mean, _ = model.predict(params[0])
    assert field_mean.size == int(model.mask.sum())


# ---------------- 保形校准（S5） ----------------

def test_conformal_quantile_math() -> None:
    # n=9, alpha=0.1 → k=ceil(10*0.9)=9 → 取第 9 小（最大）
    assert pod.conformal_quantile(list(range(1, 10)), alpha=0.1) == 9.0
    # n=4, alpha=0.5 → k=ceil(5*0.5)=3 → 第 3 小
    assert pod.conformal_quantile([4.0, 1.0, 3.0, 2.0], alpha=0.5) == 3.0


def test_conformal_quantile_is_infinite_when_samples_insufficient() -> None:
    """n 个点最多保证 n/(n+1)：n=6 时无法认证 90%，必须返回 inf 而不是硬凑一个数。"""
    scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert pod.conformal_quantile(scores, alpha=0.1) == float("inf")
    assert pod.conformal_quantile(scores, alpha=0.15) == 6.0   # k=ceil(7*0.85)=6 ≤ 6


def test_calibrate_marks_uncertifiable_alpha() -> None:
    params, snaps, _ = _analytic_family([1.0, 2.0, 3.0, 4.0])
    model = pod.fit(params, snaps, energy_ratio=0.999999, coeff_model="linear")
    meta = model.calibrate(params, snaps, alpha=0.1)   # n=4 → k=5>4
    assert meta["certified"] is False
    assert "不足以认证" in meta["guarantee"]
    assert model.conformal_q == float("inf")


def test_calibrate_certifies_and_widens_intervals() -> None:
    """可认证时区间必须被放大：原残差标准差过窄正是覆盖率塌到 3% 的根因。"""
    params, snaps, _ = _analytic_family([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    model = pod.fit(params, snaps, energy_ratio=0.999999, coeff_model="linear")
    _, std_before = model.predict(params[0])
    meta = model.calibrate(params, snaps, alpha=0.25)   # n=8 → k=7 ≤ 8
    assert meta["certified"] is True and meta["q"] >= 0.0
    _, std_after = model.predict(params[0])
    assert np.all(std_after >= std_before - 1e-12)


def test_holdout_report_s5_is_null_when_not_certified() -> None:
    """未认证时 S5 必须是 null（不得当通过），S1 仍独立判定。"""
    params, snaps, _ = _analytic_family([1.0, 2.0, 3.0, 4.0])
    model = pod.fit(params[:3], snaps[:3], energy_ratio=0.999999, coeff_model="linear")
    report = pod.holdout_report(model, params[3:], snaps[3:])
    assert report["s5_certified"] is False
    assert report["s5_passed"] is None
