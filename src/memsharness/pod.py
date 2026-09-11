"""场级降阶骨架（POD）：公共点集 → 快照 → 掩膜 → POD 基 → 系数回归 → 场级留出误差。

对应 WORKING_PLAN §4.4B 的**降阶优先**路径。这是"免 COMSOL 出场解"的第一块实件。

为什么是 POD 而不是先上 FNO：用户条件是**固定拓扑 + 1–2 个参数**，场解落在低维流形上，
POD 用 30–60 个快照即可、训练在 CPU 上分钟级完成，且基函数物理可解释（便于论文与误差归因）。

三条来自实测的硬约束（P1 验证，见 work/reports/p1_field_grid.json）：
1. **公共点集必须固定**：几何变化会让网格变，只有插值到同一套点集上才能逐点比较；
2. **必须掩膜**：几何缩小后部分公共点落在域外 → NaN，POD 只在"所有快照都有限"的点上做；
3. **误差必须按场级相对 L2 报**，而不是只看标量指标。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from .ml.surrogate import SurrogateEnsemble


class LinearCoeffModel:
    """线性（岭回归）系数模型：小样本 POD-ROM 的默认选择。

    为什么默认线性而不是深度集成：快照数通常只有 30–60（本例更少），
    MLP 在这个量级上只能**逼近**线性映射（实测训练点重构误差 ~1e-4），
    而 POD 系数对参数的依赖常常本身就是近似线性的；线性模型能精确重构、
    外推行为可预期，且不确定度可以用残差标准差给出（保守、可解释）。
    系数确实非线性时，把 ``coeff_model="mlp"`` 换回深度集成即可。
    """

    def __init__(self, alpha: float = 1e-8):
        self.alpha = float(alpha)
        self.input_cols: list[str] = []
        self.output_cols: list[str] = []
        self._mean_x: np.ndarray | None = None
        self._std_x: np.ndarray | None = None
        self._coef: np.ndarray | None = None
        self._intercept: np.ndarray | None = None
        self._resid_std: np.ndarray | None = None

    def fit(self, frame: "Any", input_cols: Sequence[str], output_cols: Sequence[str]) -> "LinearCoeffModel":
        x = frame[list(input_cols)].to_numpy(dtype=float)
        y = frame[list(output_cols)].to_numpy(dtype=float)
        self.input_cols, self.output_cols = list(input_cols), list(output_cols)
        self._mean_x, self._std_x = x.mean(axis=0), np.where(x.std(axis=0) > 0, x.std(axis=0), 1.0)
        xs = (x - self._mean_x) / self._std_x
        design = np.column_stack([np.ones(xs.shape[0]), xs])
        gram = design.T @ design + self.alpha * np.eye(design.shape[1])
        weights = np.linalg.solve(gram, design.T @ y)
        self._intercept, self._coef = weights[0], weights[1:]
        resid = y - design @ weights
        self._resid_std = resid.std(axis=0, ddof=0)
        return self

    def predict(self, frame: "Any") -> tuple[np.ndarray, np.ndarray]:
        x = frame[self.input_cols].to_numpy(dtype=float)
        xs = (x - self._mean_x) / self._std_x
        mean = self._intercept + xs @ self._coef
        std = np.tile(self._resid_std, (mean.shape[0], 1))
        return mean, std


def conformal_quantile(scores: Sequence[float], alpha: float = 0.1) -> float:
    """保形预测的分位数：取第 ⌈(n+1)(1−α)⌉ 小的非一致性得分。

    **当样本不足时返回 inf**，这是数学上正确的答案而不是缺陷：
    n 个校准点最多只能保证 (n)/(n+1) 的覆盖率，例如 n=6 时 `k=7>6` → 无法给出 90% 的有限保证。
    这种情况下必须如实报告"样本不足以认证该置信水平"，绝不能用残差标准差硬凑一个窄区间
    （实测后果：90% 区间实际覆盖率塌到 3%）。
    """
    arr = np.sort(np.asarray([s for s in scores if np.isfinite(s)], dtype=float))
    n = arr.size
    if n == 0:
        return float("inf")
    k = int(np.ceil((n + 1) * (1.0 - alpha)))
    if k > n:
        return float("inf")
    return float(arr[k - 1])


@dataclass
class PodModel:
    """POD 降阶模型：场 ≈ 均值 + Σ aᵢ(θ)·φᵢ(x)，系数 aᵢ 由参数 θ 回归得到。"""

    param_names: list[str]
    mask: np.ndarray                 # (n_points,) 公共掩膜（True = 参与 POD）
    mean: np.ndarray                 # (n_points,)
    basis: np.ndarray                # (n_modes, n_points)
    singular_values: np.ndarray      # (n_modes,)
    energy_ratio: float              # 基保留的能量占比
    coeff_model: Any                 # 系数回归：LinearCoeffModel（默认）或 SurrogateEnsemble
    n_snapshots: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
    # 保形校准（S5）：区间 = ŷ ± q·σ；未校准时 q=None，此时区间**不可用于放行**
    conformal_q: float | None = None
    conformal_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_modes(self) -> int:
        return int(self.basis.shape[0])

    def predict(self, params: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
        """返回 (场均值, 场标准差)，长度 = 被掩膜选中的点数。

        若已做保形校准，返回的标准差已按 ``conformal_q`` 放大（可直接乘 1.6449 得 90% 区间）。
        """
        import pandas as pd

        row = pd.DataFrame([{f"in_{name}": float(params[name]) for name in self.param_names}])
        coeff_mean, coeff_std = self.coeff_model.predict(row)
        coeff_mean = np.asarray(coeff_mean, dtype=float).ravel()
        coeff_std = np.asarray(coeff_std, dtype=float).ravel()
        field_mean = self.mean + coeff_mean @ self.basis
        # 系数独立近似下，场标准差 = sqrt(Σ (σᵢ·φᵢ)²)
        field_std = np.sqrt(np.sum((coeff_std[:, None] * self.basis) ** 2, axis=0))
        if self.conformal_q is not None and np.isfinite(self.conformal_q):
            field_std = field_std * float(self.conformal_q)
        return field_mean, field_std

    def calibrate(
        self,
        params: Sequence[dict[str, float]],
        snapshots: Sequence[np.ndarray],
        *,
        alpha: float = 0.1,
        leave_one_out: bool = True,
    ) -> dict[str, Any]:
        """保形校准（S5）：用**非一致性得分**给出有覆盖率保证的区间放大系数 q。

        非一致性得分（每个快照一个标量）：该快照上逐点 |真值−预测| / σ 的最大值。
        ``leave_one_out=True`` 时对训练点做 LOO 重拟合取分——避免用训练偏差自证校准
        （直接拿拟合残差当得分正是"覆盖率塌到 3%"的根因）。
        """
        scores: list[float] = []
        if leave_one_out:
            for i in range(len(params)):
                rest_p = [p for j, p in enumerate(params) if j != i]
                rest_s = [s for j, s in enumerate(snapshots) if j != i]
                if len(rest_p) < 2:
                    continue
                try:
                    fold = fit(rest_p, rest_s, energy_ratio=self.energy_ratio,
                               param_names=self.param_names,
                               coeff_model=self.meta.get("coeff_model", "linear"))
                except Exception:
                    continue
                mean, std = fold.predict(params[i])
                truth = np.asarray(snapshots[i], dtype=float).ravel()[fold.mask]
                keep = np.isfinite(truth)
                if not keep.any():
                    continue
                scale = np.maximum(std[keep], 1e-30)
                scores.append(float(np.max(np.abs(truth[keep] - mean[keep]) / scale)))
        else:
            for point, snap in zip(params, snapshots):
                mean, std = self.predict(point)
                truth = np.asarray(snap, dtype=float).ravel()[self.mask]
                keep = np.isfinite(truth)
                if not keep.any():
                    continue
                scale = np.maximum(std[keep], 1e-30)
                scores.append(float(np.max(np.abs(truth[keep] - mean[keep]) / scale)))

        q = conformal_quantile(scores, alpha=alpha)
        self.conformal_q = q
        self.conformal_meta = {
            "alpha": alpha,
            "target_coverage": 1.0 - alpha,
            "n_calibration": len(scores),
            "leave_one_out": leave_one_out,
            "scores": scores,
            "q": None if not np.isfinite(q) else q,
            "guarantee": (
                f"可保证 ≥{(1 - alpha):.0%} 覆盖率"
                if np.isfinite(q)
                else f"校准点仅 {len(scores)} 个，**不足以认证 {1 - alpha:.0%} 覆盖率**"
                     f"（最多保证 {len(scores) / (len(scores) + 1):.0%}）——必须补样本"
            ),
            "certified": bool(np.isfinite(q)),
        }
        return self.conformal_meta

    def to_meta(self) -> dict[str, Any]:
        return {
            "param_names": self.param_names,
            "n_points": int(self.mask.size),
            "n_masked_points": int(self.mask.sum()),
            "n_modes": self.n_modes,
            "energy_ratio": self.energy_ratio,
            "singular_values": [float(v) for v in self.singular_values],
            "n_snapshots": self.n_snapshots,
            "conformal": self.conformal_meta,
            **self.meta,
        }


def common_mask(snapshots: Sequence[np.ndarray]) -> np.ndarray:
    """公共掩膜：只有**在所有快照中都有限**的点才参与 POD。

    这是 P1 实测的直接产物——几何变化会让部分公共点落到域外变成 NaN；
    把它们当 0 处理会污染基，直接报错又会让整个数据集不可用，掩膜是唯一正确做法。
    """
    if not snapshots:
        raise ValueError("没有快照")
    mask = np.ones(np.asarray(snapshots[0]).size, dtype=bool)
    for snap in snapshots:
        mask &= np.isfinite(np.asarray(snap, dtype=float))
    return mask


def fit_pod(
    snapshots: Sequence[np.ndarray],
    *,
    energy_ratio: float = 0.999,
    mask: np.ndarray | None = None,
    max_modes: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """对快照做 POD（SVD），返回 (mask, mean, basis, singular_values, meta)。

    ``energy_ratio`` 决定保留多少个模态：累计奇异值平方占比达到该比例即截断。
    """
    snaps = [np.asarray(s, dtype=float).ravel() for s in snapshots]
    if len(snaps) < 2:
        raise ValueError("至少需要 2 个快照")
    if mask is None:
        mask = common_mask(snaps)
    if int(mask.sum()) < 2:
        raise ValueError("公共掩膜后可用点不足 2 个，无法做 POD")

    matrix = np.stack([s[mask] for s in snaps], axis=0)      # (n_snapshots, n_points)
    mean = matrix.mean(axis=0)
    fluctuations = matrix - mean
    # 用 economy SVD：快照数通常远小于点数
    _u, sv, vt = np.linalg.svd(fluctuations, full_matrices=False)
    energy = sv**2
    total = float(energy.sum())
    if total <= 0:
        raise ValueError("快照之间没有任何变化（能量为 0），无法建立 POD 基")
    cumulative = np.cumsum(energy) / total
    n_modes = int(np.searchsorted(cumulative, energy_ratio) + 1)
    n_modes = max(1, min(n_modes, len(sv)))
    if max_modes is not None:
        n_modes = min(n_modes, max(1, int(max_modes)))
    basis = vt[:n_modes]
    meta = {
        "retained_modes": n_modes,
        "available_modes": int(len(sv)),
        "cumulative_energy_at_n": float(cumulative[n_modes - 1]),
        "requested_energy_ratio": energy_ratio,
    }
    return mask, mean, basis, sv[:n_modes], meta


def fit(
    params: Sequence[dict[str, float]],
    snapshots: Sequence[np.ndarray],
    *,
    energy_ratio: float = 0.999,
    param_names: Sequence[str] | None = None,
    coeff_model: str = "linear",
    n_members: int = 5,
    seed: int = 0,
    max_modes: int | None = None,
) -> PodModel:
    """从 (参数, 快照) 对拟合 POD 降阶模型（含系数回归）。

    ``coeff_model``：``"linear"``（默认，小样本更稳、可精确重构）或 ``"mlp"``（系数非线性时用）。
    """
    import pandas as pd

    if len(params) != len(snapshots):
        raise ValueError("参数与快照数量不一致")
    names = list(param_names) if param_names else sorted(params[0].keys())
    mask, mean, basis, sv, meta = fit_pod(
        snapshots, energy_ratio=energy_ratio, max_modes=max_modes
    )
    matrix = np.stack([np.asarray(s, dtype=float).ravel()[mask] for s in snapshots], axis=0)
    coeffs = (matrix - mean) @ basis.T                                  # (n_snapshots, n_modes)
    frame = pd.DataFrame([{f"in_{n}": float(p[n]) for n in names} for p in params])
    frame = frame.assign(**{f"out_c{i}": coeffs[:, i] for i in range(coeffs.shape[1])})
    out_cols = [c for c in frame.columns if c.startswith("out_")]
    if coeff_model == "linear":
        model: Any = LinearCoeffModel()
    elif coeff_model == "mlp":
        model = SurrogateEnsemble(n_members=n_members, seed=seed)
    else:
        raise ValueError(f"coeff_model 必须是 'linear' 或 'mlp'，收到 {coeff_model!r}")
    model.fit(frame, [f"in_{n}" for n in names], out_cols)
    meta["coeff_model"] = coeff_model
    return PodModel(
        param_names=names, mask=mask, mean=mean, basis=basis, singular_values=sv,
        energy_ratio=energy_ratio, coeff_model=model, n_snapshots=len(snapshots), meta=meta,
    )


def relative_l2_field(true: np.ndarray, pred: np.ndarray, mask: np.ndarray | None = None) -> float:
    """场级相对 L2 误差（S1 指标）：‖pred − true‖ / ‖true‖，只在掩膜点上计算。"""
    a = np.asarray(true, dtype=float).ravel()
    b = np.asarray(pred, dtype=float).ravel()
    if mask is not None:
        a, b = a[mask], b[mask]
    keep = np.isfinite(a) & np.isfinite(b)
    a, b = a[keep], b[keep]
    denom = float(np.sqrt(np.sum(a**2)))
    if denom <= 0:
        raise ValueError("真值范数为 0：相对 L2 无意义")
    return float(np.sqrt(np.sum((b - a) ** 2)) / denom)


def holdout_report(
    model: PodModel,
    params: Sequence[dict[str, float]],
    snapshots: Sequence[np.ndarray],
) -> dict[str, Any]:
    """在**留出快照**上评估场级误差（含逐点误差界覆盖率与 S5 认证状态）。"""
    errors: list[float] = []
    coverages: list[float] = []
    for point, snap in zip(params, snapshots):
        field_mean, field_std = model.predict(point)
        truth = np.asarray(snap, dtype=float).ravel()[model.mask]
        keep = np.isfinite(truth)
        if not keep.any():
            continue
        errors.append(relative_l2_field(truth[keep], field_mean[keep]))
        inside = np.abs(truth[keep] - field_mean[keep]) <= 1.6449 * np.maximum(field_std[keep], 1e-30)
        coverages.append(float(np.mean(inside)))
    if not errors:
        return {"n_holdout": 0, "note": "没有可评估的留出快照"}

    coverage = float(np.mean(coverages))
    certified = bool((model.conformal_meta or {}).get("certified"))
    # S5 只在**已认证**（保形校准给出有限保证）时才谈达标；否则如实标为未认证
    s5_passed = bool(certified and 0.85 <= coverage <= 0.95) if certified else None
    return {
        "n_holdout": len(errors),
        "field_rel_l2": errors,
        "field_rel_l2_mean": float(np.mean(errors)),
        "field_rel_l2_max": float(np.max(errors)),
        "interval_coverage_90": coverage,
        "s1_threshold": 0.05,
        "s1_passed": bool(max(errors) <= 0.05),
        "s5_certified": certified,
        "s5_passed": s5_passed,
        "conformal": model.conformal_meta or None,
        "note": "S1 判据：场级相对 L2 ≤ 5%；S5 判据：90% 区间覆盖率 85–95%，"
                "且必须已通过保形校准（未认证时 s5_passed=null，不得当通过）",
    }
