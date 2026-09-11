"""物理一致性检查（WORKING_PLAN 6.1.1 的 **S3** 等级）——免求解器的安全网。

设计要点（对应红线 2/7）：
- **任一检查不通过 → 该解作废**，不允许"降权保留"或"综合打分掩盖"；
- 检查是**独立于误差指标**的：一个解可以与数据吻合得很好却违反守恒，这种解必须被拦下；
- 所有阈值必须显式传入并随报告返回，禁止把阈值藏在代码里（否则"通过"无法复核）；
- 函数全部是纯数值计算，不依赖 COMSOL，**可单测**（checker 本身出错比漏检更危险）。

本模块只做 S3 原语；与 COMSOL 解对接的取值逻辑在调用方（脚本/MCP 工具）里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


@dataclass
class CheckResult:
    """单项检查结果。``passed=None`` 表示**无法判定**（数据不足），不等同于通过。"""

    name: str
    passed: bool | None
    metric: float | None
    threshold: float | None
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "metric": self.metric,
            "threshold": self.threshold,
            "reason": self.reason,
            "detail": self.detail,
        }


def conservation_residual(
    *, influx: float, outflux: float, threshold: float = 0.01, name: str = "conservation"
) -> CheckResult:
    """全局守恒残差：|入口量 − 出口量| / |入口量| ≤ 阈值。

    例：稳态传热下「热流入口总功率」应等于「低温边界流出的总功率」。
    """
    if influx is None or outflux is None:
        return CheckResult(name, None, None, threshold, "入口/出口量缺失，无法判定守恒")
    if abs(influx) <= 1e-30:
        return CheckResult(name, None, None, threshold, "入口量为 0：相对残差无意义（判据不适用）")
    residual = abs(float(influx) - float(outflux)) / abs(float(influx))
    return CheckResult(
        name,
        residual <= threshold,
        residual,
        threshold,
        "" if residual <= threshold else f"守恒残差 {residual:.3e} 超阈值 {threshold:.3e}",
        {"influx": float(influx), "outflux": float(outflux)},
    )


def boundary_condition_residual(
    *,
    values: Sequence[float],
    prescribed: float,
    threshold: float = 1e-6,
    scale: float | None = None,
    name: str = "boundary_condition",
) -> CheckResult:
    """边界条件满足度：指定边界上的值应等于给定值（最大相对偏差）。

    ``scale`` 用于把绝对偏差归一化（例如用温升 ΔT 作尺度）；缺省用 ``|prescribed|``，
    若 prescribed≈0 则必须显式给 scale，否则相对偏差无意义（此时返回"无法判定"）。
    """
    finite = [float(v) for v in values if v is not None and v == v]
    if not finite:
        return CheckResult(name, None, None, threshold, "边界上没有有限值，无法判定")
    denom = abs(float(scale)) if scale else abs(float(prescribed))
    if denom <= 1e-30:
        return CheckResult(
            name, None, None, threshold,
            "归一化尺度为 0：请显式传入 scale，否则相对偏差无意义",
        )
    worst = max(abs(v - float(prescribed)) for v in finite) / denom
    return CheckResult(
        name,
        worst <= threshold,
        worst,
        threshold,
        "" if worst <= threshold else f"边界最大偏差 {worst:.3e} 超阈值 {threshold:.3e}",
        {"n_points": len(finite), "prescribed": float(prescribed), "scale": denom,
         "max_abs_deviation": max(abs(v - float(prescribed)) for v in finite)},
    )


def mirror_symmetry_residual(
    *,
    coords: Sequence[Sequence[float]],
    values: Sequence[float],
    axis: int,
    axis_value: float,
    threshold: float = 0.02,
    scale: float | None = None,
    name: str = "symmetry",
) -> CheckResult:
    """镜像对称性：关于 ``coord[axis] == axis_value`` 的镜像点，场值应相等。

    做法：对每个点求镜像坐标，用最近邻找到配对点；只统计配对距离足够小的点对。
    配对不足（例如几何本身不对称）时返回"无法判定"，**不返回通过**。
    """
    import numpy as np
    from scipy.spatial import cKDTree

    pts = np.asarray(coords, dtype=float)
    vals = np.asarray(values, dtype=float)
    if pts.ndim != 2 or vals.ndim != 1 or pts.shape[0] != vals.size or pts.shape[0] < 10:
        return CheckResult(name, None, None, threshold, "坐标/值数组不匹配或点数过少，无法判定")

    mirrored = pts.copy()
    mirrored[:, axis] = 2.0 * float(axis_value) - pts[:, axis]
    tree = cKDTree(pts)
    dist, idx = tree.query(mirrored, k=1)
    # 只取"镜像点确实存在"的配对（容差取相邻点距的量级）
    spacing = float(np.median(tree.query(pts, k=2)[0][:, 1])) if pts.shape[0] > 1 else 0.0
    pair_tol = max(spacing * 0.5, 1e-12)
    paired = dist <= pair_tol
    if paired.sum() < 10:
        return CheckResult(
            name, None, None, threshold,
            f"镜像配对点不足（{int(paired.sum())} 个，容差 {pair_tol:.3g}）：该几何/网格不适合本项检查",
        )

    denom = abs(float(scale)) if scale else max(float(np.nanmax(np.abs(vals))), 1e-30)
    diff = np.abs(vals[paired] - vals[idx[paired]]) / denom
    worst = float(diff.max())
    return CheckResult(
        name,
        worst <= threshold,
        worst,
        threshold,
        "" if worst <= threshold else f"镜像最大相对差 {worst:.3e} 超阈值 {threshold:.3e}",
        {"paired_points": int(paired.sum()), "scale": denom, "pair_tolerance": pair_tol},
    )


def limit_consistency(
    *,
    driver: Sequence[float],
    response: Sequence[float],
    expected_limit: float,
    threshold: float = 0.02,
    scale: float | None = None,
    name: str = "limit",
) -> CheckResult:
    """极限一致性：当驱动量 → 0 时，响应量应收敛到 ``expected_limit``。

    例：入射热流 q_in → 0 时，T_max 应 → T0。用**最小驱动量**那一点判定，
    并要求响应随驱动量单调（非单调说明模型或数据有问题）。
    """
    if len(driver) != len(response) or len(driver) < 2:
        return CheckResult(name, None, None, threshold, "驱动量/响应量长度不足，无法判定")
    pairs = sorted(zip((float(d) for d in driver), (float(r) for r in response)))
    _, y0 = pairs[0]
    denom = abs(float(scale)) if scale else max(abs(float(expected_limit)), 1e-30)
    error = abs(y0 - float(expected_limit)) / denom
    monotonic = all(b[1] >= a[1] - 1e-12 for a, b in zip(pairs, pairs[1:]))
    ok = error <= threshold and monotonic
    reason = ""
    if error > threshold:
        reason = f"极限偏差 {error:.3e} 超阈值 {threshold:.3e}（最小值 {y0:.6g} vs 期望 {expected_limit:.6g}）"
    elif not monotonic:
        reason = "响应随驱动量非单调：可能存在模型或数据问题，不能仅凭极限值判定通过"
    return CheckResult(
        name, ok, error, threshold, reason,
        {"smallest_driver": pairs[0][0], "response_at_smallest": y0,
         "expected_limit": float(expected_limit), "monotonic": monotonic},
    )


def evaluate_s3(checks: Iterable[CheckResult]) -> dict[str, Any]:
    """汇总 S3 判定：**任一不通过即整体不通过**（硬门禁，不允许降权保留）。

    ``passed=None``（无法判定）的处理：**不视为通过**。整体结论会标为
    ``inconclusive``，调用方必须补数据或补检查，不得据此放行。
    """
    items = [c for c in checks]
    results = [c.to_dict() for c in items]
    if not items:
        return {
            "verdict": "inconclusive",
            "reason": "没有任何检查项",
            "checks": results,
            "release_allowed": False,
        }

    failed = [c for c in items if c.passed is False]
    unknown = [c for c in items if c.passed is None]
    if failed:
        verdict = "failed"
        reason = "存在未通过项：" + "; ".join(f"{c.name}({c.reason})" for c in failed)
    elif unknown:
        verdict = "inconclusive"
        reason = "存在无法判定项（不等同于通过）：" + "; ".join(f"{c.name}({c.reason})" for c in unknown)
    else:
        verdict = "passed"
        reason = "全部检查通过"

    return {
        "verdict": verdict,
        "reason": reason,
        "n_checks": len(items),
        "n_failed": len(failed),
        "n_inconclusive": len(unknown),
        "checks": results,
        # 硬门禁语义：只有 verdict == "passed" 才允许放行/入库
        "release_allowed": verdict == "passed",
    }
