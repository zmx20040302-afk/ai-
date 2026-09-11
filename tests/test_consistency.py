"""A5 测试：S3 物理一致性检查器（纯数值，可离线验证）。

这些测试本身就是安全网的一部分——checker 出错（漏检/误判）比没有 checker 更危险，
因此每类检查都要有"通过"、"不通过"、"无法判定"三种用例。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from memsharness import consistency as cs  # noqa: E402


# ---------------- 守恒 ----------------

def test_conservation_pass_and_fail() -> None:
    ok = cs.conservation_residual(influx=10.0, outflux=10.0)
    assert ok.passed is True and ok.metric == pytest.approx(0.0)
    bad = cs.conservation_residual(influx=10.0, outflux=8.85, threshold=0.01)
    assert bad.passed is False and bad.metric == pytest.approx(0.115)


def test_conservation_zero_influx_is_inconclusive_not_pass() -> None:
    """入口为 0 时相对残差无意义——必须判为"无法判定"，不能算通过。"""
    result = cs.conservation_residual(influx=0.0, outflux=0.0)
    assert result.passed is None
    assert "无意义" in result.reason


def test_conservation_missing_value_is_inconclusive() -> None:
    assert cs.conservation_residual(influx=None, outflux=1.0).passed is None


# ---------------- 边界条件 ----------------

def test_boundary_condition_pass_and_fail() -> None:
    ok = cs.boundary_condition_residual(values=[300.0, 300.0, 300.0], prescribed=300.0, scale=10.0)
    assert ok.passed is True
    # 边界上出现 300.5 K（温升尺度 10 K）→ 相对偏差 5% > 1e-6，必须拦下
    bad = cs.boundary_condition_residual(values=[300.0, 300.5], prescribed=300.0, scale=10.0)
    assert bad.passed is False and bad.metric == pytest.approx(0.05)


def test_boundary_condition_zero_scale_needs_explicit_scale() -> None:
    """归一化尺度为 0 时必须要求显式 scale，否则判为无法判定。"""
    result = cs.boundary_condition_residual(values=[0.001, 0.002], prescribed=0.0)
    assert result.passed is None
    assert "scale" in result.reason
    fixed = cs.boundary_condition_residual(values=[0.05, 0.001], prescribed=0.0, scale=1.0, threshold=0.01)
    assert fixed.passed is False  # 0.05 > 1% of 1.0


# ---------------- 对称性 ----------------

def _grid(nx: int = 21, ny: int = 21):
    xs = [i / (nx - 1) for i in range(nx)]
    ys = [j / (ny - 1) for j in range(ny)]
    coords = [(x, y) for y in ys for x in xs]
    return coords


def test_symmetry_detects_symmetric_field() -> None:
    coords = _grid()
    # 场只依赖 x → 关于 y=0.5 完全对称
    values = [x for x, _ in coords]
    result = cs.mirror_symmetry_residual(coords=coords, values=values, axis=1, axis_value=0.5)
    assert result.passed is True, result.reason
    assert result.metric < 1e-9


def test_symmetry_flags_asymmetric_field() -> None:
    coords = _grid()
    values = [x + 0.5 * y for x, y in coords]  # 含 y 项 → 不再对称
    result = cs.mirror_symmetry_residual(coords=coords, values=values, axis=1, axis_value=0.5, threshold=0.01)
    assert result.passed is False


def test_symmetry_inconclusive_when_no_pairs() -> None:
    coords = [(float(i), 0.0) for i in range(20)]  # 一维线，关于 y 无法配对
    values = [float(i) for i in range(20)]
    result = cs.mirror_symmetry_residual(coords=coords, values=values, axis=1, axis_value=0.5)
    assert result.passed is None
    assert "配对点不足" in result.reason


# ---------------- 极限一致性 ----------------

def test_limit_consistency_pass() -> None:
    # q_in → 0 时 T_max → T0（单调）
    result = cs.limit_consistency(
        driver=[0.0, 500.0, 1000.0], response=[300.0, 305.0, 310.0], expected_limit=300.0, scale=10.0
    )
    assert result.passed is True


def test_limit_consistency_flags_wrong_limit() -> None:
    result = cs.limit_consistency(
        driver=[0.0, 500.0], response=[299.0, 305.0], expected_limit=300.0, scale=10.0, threshold=0.02
    )
    assert result.passed is False and result.metric == pytest.approx(0.1)


def test_limit_consistency_flags_non_monotonic_response() -> None:
    """极限值对但响应非单调 → 不能判通过（说明模型或数据有问题）。"""
    result = cs.limit_consistency(
        driver=[0.0, 500.0, 1000.0], response=[300.0, 310.0, 305.0], expected_limit=300.0, scale=10.0
    )
    assert result.passed is False
    assert "非单调" in result.reason


# ---------------- 汇总（硬门禁） ----------------

def test_evaluate_s3_any_failure_blocks_release() -> None:
    good = cs.conservation_residual(influx=10.0, outflux=10.0)
    bad = cs.boundary_condition_residual(values=[300.5], prescribed=300.0, scale=10.0)
    report = cs.evaluate_s3([good, bad])
    assert report["verdict"] == "failed"
    assert report["release_allowed"] is False


def test_evaluate_s3_inconclusive_is_not_release() -> None:
    """无法判定 ≠ 通过：不得据此放行。"""
    unknown = cs.conservation_residual(influx=0.0, outflux=0.0)
    report = cs.evaluate_s3([unknown])
    assert report["verdict"] == "inconclusive"
    assert report["release_allowed"] is False


def test_evaluate_s3_all_pass_allows_release() -> None:
    checks = [
        cs.conservation_residual(influx=10.0, outflux=10.0),
        cs.boundary_condition_residual(values=[300.0], prescribed=300.0, scale=10.0),
    ]
    report = cs.evaluate_s3(checks)
    assert report["verdict"] == "passed" and report["release_allowed"] is True
    assert report["n_checks"] == 2 and report["n_failed"] == 0


def test_evaluate_s3_empty_is_inconclusive() -> None:
    report = cs.evaluate_s3([])
    assert report["verdict"] == "inconclusive" and report["release_allowed"] is False


# ---------------- ΔT 对标口径（模板层） ----------------

def test_heat_slab_comparison_baseline_is_declared() -> None:
    """L0 判据必须作用在温升 ΔT 上，否则 3%×300K≈整个温升，容差形同虚设。"""
    from memsharness.comsol import java_model as jm

    template = jm.get_template("heat_slab_2d")
    assert template.baseline_params() == {"T_max_K": "T0", "T_min_K": "T0"}
    assert template.analytic_rtol <= 0.01


def test_heat_slab_flux_boundary_is_opposite_temperature_boundary() -> None:
    """热流边与温度边必须是**对边**（4 右 / 1 左），否则退化为二维、解析对标失效。"""
    from memsharness.comsol import java_model as jm

    template = jm.get_template("heat_slab_2d")
    assert template.boundary_numbers["temperature"] == 4
    assert template.boundary_numbers["heat_flux"] == 1
