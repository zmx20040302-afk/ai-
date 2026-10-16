"""有界的单一复声压场 AI 求解器。

本模块只解决 ``p_total_Pa``。它把离散结构/频率当作**分支键**，仅在同一分支内沿
``x_scale`` 做经留出验证的插值；绝不跨 ``N_w_te1``、``N_w_te2`` 或频率插值。

运行时契约：

* 命中已注册分支和证据范围：返回 ``source_type=ai_solver`` 的复场、误差带和 S 级；
* 未命中：不返回场值，只返回串行 COMSOL 补点计划；
* 模型保持 ``draft``，只有人可以把它提升为 ``approved_for_use``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from scipy.interpolate import PchipInterpolator

SCHEMA = "memsharness.single_pressure_branch/v1"
REGISTRY_SCHEMA = "memsharness.single_pressure_registry/v1"
FIELD_NAME = "p_total_Pa"
TOL = 1e-9


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _complex_pchip(x: np.ndarray, y: np.ndarray, xq: float) -> np.ndarray:
    """沿最后一轴插值复数数组；显式拆实/虚，禁止外推。"""
    re = PchipInterpolator(x, y.real, axis=-1, extrapolate=False)(xq)
    im = PchipInterpolator(x, y.imag, axis=-1, extrapolate=False)(xq)
    return np.asarray(re) + 1j * np.asarray(im)


@dataclass(frozen=True)
class PressurePrediction:
    """一次 AI 场预测；``field`` 与冻结公共点一一对应。"""

    field: np.ndarray
    points_xyz_m: np.ndarray
    mask: np.ndarray
    report: dict[str, Any]


@dataclass
class AmpShapeBranch:
    """固定 ``(N1,N2,f)`` 分支内的幅值/形状分离 POD-PCHIP 模型。"""

    manifest: dict[str, Any]
    mask: np.ndarray
    points_xyz_m: np.ndarray
    x_train: np.ndarray
    log10_norm_train: np.ndarray
    shape_mean: np.ndarray
    shape_basis: np.ndarray
    coeff_train: np.ndarray

    @property
    def branch_key(self) -> tuple[int, int, float]:
        b = self.manifest["branch"]
        return int(b["N_w_te1"]), int(b["N_w_te2"]), float(b["freq_Hz"])

    @property
    def x_bounds(self) -> tuple[float, float]:
        lo, hi = self.manifest["applicability"]["x_scale"]
        return float(lo), float(hi)

    @classmethod
    def load(cls, manifest_path: str | pathlib.Path) -> "AmpShapeBranch":
        mp = pathlib.Path(manifest_path).resolve()
        meta = _json(mp)
        if meta.get("schema") != SCHEMA:
            raise ValueError("不支持的单场模型 schema: %r" % meta.get("schema"))
        ap = (mp.parent / meta["arrays_file"]).resolve()
        if _sha256(ap) != meta["arrays_sha256"]:
            raise ValueError("模型数组哈希不匹配：%s" % ap)
        z = np.load(ap, allow_pickle=False)
        required = {
            "mask", "points_xyz_m", "x_train", "log10_norm_train",
            "shape_mean", "shape_basis", "coeff_train",
        }
        missing = required.difference(z.files)
        if missing:
            raise ValueError("模型数组缺字段：%s" % sorted(missing))
        obj = cls(meta, *(np.asarray(z[name]) for name in (
            "mask", "points_xyz_m", "x_train", "log10_norm_train",
            "shape_mean", "shape_basis", "coeff_train")))
        obj._validate()
        return obj

    def _validate(self) -> None:
        if self.mask.dtype != np.bool_ or self.mask.ndim != 1:
            raise ValueError("mask 必须是一维 bool")
        if self.points_xyz_m.shape != (self.mask.size, 3):
            raise ValueError("点集尺寸与 mask 不一致")
        n = self.x_train.size
        if n < 3 or not np.all(np.diff(self.x_train) > 0):
            raise ValueError("x_train 必须至少 3 点且严格递增")
        if self.log10_norm_train.shape != (n,):
            raise ValueError("幅值训练数组尺寸错误")
        if self.coeff_train.ndim != 2 or self.coeff_train.shape[1] != n:
            raise ValueError("系数训练数组尺寸错误")
        if self.shape_basis.shape != (self.coeff_train.shape[0], int(self.mask.sum())):
            raise ValueError("POD 基尺寸错误")
        if self.shape_mean.shape != (int(self.mask.sum()),):
            raise ValueError("形状均值尺寸错误")

    def accepts(self, x_scale: float, n1: float, n2: float, freq_hz: float) -> bool:
        k1, k2, kf = self.branch_key
        lo, hi = self.x_bounds
        return (
            abs(n1 - k1) <= TOL
            and abs(n2 - k2) <= TOL
            and abs(freq_hz - kf) <= max(TOL, abs(kf) * 1e-12)
            and lo - TOL <= x_scale <= hi + TOL
        )

    def predict(self, x_scale: float) -> PressurePrediction:
        lo, hi = self.x_bounds
        if not (lo - TOL <= x_scale <= hi + TOL):
            raise ValueError("x_scale=%g 超出证据范围 [%g,%g]" % (x_scale, lo, hi))
        logn = float(PchipInterpolator(
            self.x_train, self.log10_norm_train, extrapolate=False)(x_scale))
        coeff = _complex_pchip(self.x_train, self.coeff_train, x_scale)
        shape = self.shape_mean + coeff @ self.shape_basis
        norm = float(np.linalg.norm(shape))
        if not np.isfinite(norm) or norm <= 0:
            raise RuntimeError("预测形状范数无效，拒绝输出")
        masked = (10.0 ** logn) * shape / norm
        if not np.isfinite(masked.real).all() or not np.isfinite(masked.imag).all():
            raise RuntimeError("预测场含非有限值，拒绝输出")
        field = np.full(self.mask.size, np.nan + 1j * np.nan, dtype=np.complex128)
        field[self.mask] = masked
        validation = self.manifest["validation"]
        report = {
            "refused": False,
            "field_name": FIELD_NAME,
            "units": "Pa",
            "complex": True,
            "source_type": "ai_solver",
            "model_id": self.manifest["model_id"],
            "model_state": self.manifest["model_state"],
            "human_approved": bool(self.manifest.get("human_approved", False)),
            "branch": dict(self.manifest["branch"]),
            "query": {"x_scale": float(x_scale)},
            "n_points": int(self.mask.size),
            "n_valid_points": int(self.mask.sum()),
            "max_abs_pressure_Pa": float(np.max(np.abs(masked))),
            "field_rel_l2_error_bound": float(validation["field_rel_l2_error_bound"]),
            "error_bound_kind": validation["error_bound_kind"],
            "s_levels": dict(validation["s_levels"]),
            "warning": validation["warning"],
            "provenance": dict(self.manifest["provenance"]),
            "interpolation": "仅同一离散分支内的 x_scale PCHIP；不跨 N1/N2/频率",
        }
        return PressurePrediction(field, self.points_xyz_m.copy(), self.mask.copy(), report)


class SinglePressureSolver:
    """多个离散分支组成的有界 ``p_total_Pa`` 求解器注册表。"""

    def __init__(self, branches: Sequence[AmpShapeBranch], registry: dict[str, Any]):
        self.branches = list(branches)
        self.registry = registry

    @classmethod
    def load(cls, registry_path: str | pathlib.Path) -> "SinglePressureSolver":
        rp = pathlib.Path(registry_path).resolve()
        meta = _json(rp)
        if meta.get("schema") != REGISTRY_SCHEMA:
            raise ValueError("不支持的注册表 schema: %r" % meta.get("schema"))
        branches = [AmpShapeBranch.load(rp.parent / item["manifest_file"])
                    for item in meta.get("branches", [])]
        if not branches:
            raise ValueError("注册表没有任何分支")
        return cls(branches, meta)

    def solve(self, *, x_scale: float, n1: float, n2: float, freq_hz: float) -> PressurePrediction | dict[str, Any]:
        if abs(n1 - round(n1)) > TOL:
            return self._refusal(x_scale, n1, n2, freq_hz,
                                 "N_w_te1 是离散电极对数，禁止小数 N1 插值")
        exact = [b for b in self.branches if (
            abs(n1 - b.branch_key[0]) <= TOL
            and abs(n2 - b.branch_key[1]) <= TOL
            and abs(freq_hz - b.branch_key[2]) <= max(TOL, abs(freq_hz) * 1e-12))]
        if not exact:
            return self._refusal(x_scale, n1, n2, freq_hz,
                                 "没有该离散 (N1,N2,频率) 分支；禁止跨模态/结构插值")
        branch = exact[0]
        if not branch.accepts(x_scale, n1, n2, freq_hz):
            lo, hi = branch.x_bounds
            return self._refusal(x_scale, n1, n2, freq_hz,
                                 "x_scale 超出该分支的留出证据范围 [%g,%g]" % (lo, hi))
        return branch.predict(float(x_scale))

    def _refusal(self, x: float, n1: float, n2: float, freq: float, reason: str) -> dict[str, Any]:
        return {
            "refused": True,
            "field_name": FIELD_NAME,
            "source_type": None,
            "query": {"x_scale": x, "N_w_te1": n1, "N_w_te2": n2, "freq_Hz": freq},
            "reason": reason,
            "fallback": "comsol_support_plan",
            "support_plan": plan_comsol_support(x, n1, n2, freq),
        }


def plan_comsol_support(x_scale: float, n1: float, n2: float, freq_hz: float,
                        *, delta: float = 0.02) -> dict[str, Any]:
    """为一个新离散分支给出最小五点试验计划（3 训练 + 2 真留出）。

    这只是数据获取计划，不代表五点后必然通过；只有 S1/S2/S5 重新评估通过且人工放行后，
    新分支才能注册。COMSOL 任务必须串行。
    """
    if abs(n1 - round(n1)) > TOL or n1 < 1 or n1 >= n2:
        return {
            "auto_submittable": False,
            "reason": "离散结构参数无效或为小数；需要先由人修正器件参数",
            "runs": [],
        }
    if not (0.2 <= x_scale <= 1.0):
        return {
            "auto_submittable": False,
            "reason": "x_scale 超出现有器件扫描边界 [0.2,1.0]；需先扩展 device_spec",
            "runs": [],
        }
    lo = max(0.2, x_scale - 2 * delta)
    hi = min(1.0, x_scale + 2 * delta)
    if hi - lo < 4 * delta:
        if lo <= 0.2 + TOL:
            hi = min(1.0, lo + 4 * delta)
        else:
            lo = max(0.2, hi - 4 * delta)
    xs = np.linspace(lo, hi, 5)
    roles = ("train", "holdout", "train", "holdout", "train")
    runs = [{
        "x_scale": float(v), "N_w_te1": int(round(n1)), "N_w_te2": int(round(n2)),
        "freq_Hz": float(freq_hz), "role": role, "field": FIELD_NAME,
    } for v, role in zip(xs, roles)]
    return {
        "auto_submittable": True,
        "execution": "serial_only",
        "n_runs": 5,
        "runs": runs,
        "promotion_gate": (
            "用 3 个训练点建局部幅值/形状模型；2 个留出点只做评估。"
            "必须重新通过 S1/S2，S5 样本不足时保持 inconclusive；人工放行前状态仍为 draft。"
        ),
    }


def build_branch(cache_path: str | pathlib.Path, points_path: str | pathlib.Path,
                 validation_report_path: str | pathlib.Path, out_dir: str | pathlib.Path,
                 *, n1: int, n2: int = 8, freq_hz: float = 20_000_000.0,
                 energy_ratio: float = 0.999) -> pathlib.Path:
    """从冻结缓存构建一个安全、无 pickle 的分支产物，返回 manifest 路径。"""
    cache = pathlib.Path(cache_path).resolve()
    points_file = pathlib.Path(points_path).resolve()
    report_file = pathlib.Path(validation_report_path).resolve()
    out = pathlib.Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    z = np.load(cache, allow_pickle=False)
    p = np.asarray(z["P"], dtype=np.complex128)
    mask = np.asarray(z["mask"], dtype=bool)
    xs = np.asarray(z["x_scale"], dtype=float)
    roles = np.asarray(z["role_x"]).astype(str)
    points = np.loadtxt(points_file, delimiter="\t", skiprows=1)
    if p.shape != (mask.size, xs.size) or points.shape != (mask.size, 3):
        raise ValueError("缓存、mask 与冻结点集尺寸不一致")
    train = np.where(roles == "train")[0]
    holdout = np.where(roles == "holdout")[0]
    if train.size < 3 or holdout.size < 1:
        raise ValueError("构建需要至少 3 个训练点和 1 个留出点")
    order = np.argsort(xs[train])
    train = train[order]
    x_train = xs[train]
    x = p[mask][:, train]
    norms = np.linalg.norm(x, axis=0)
    if np.any(norms <= 0) or not np.isfinite(norms).all():
        raise ValueError("训练快照范数无效")
    shape = x / norms[None, :]
    mean = shape.mean(axis=1, keepdims=True)
    u, s, _vh = np.linalg.svd(shape - mean, full_matrices=False)
    energy = np.cumsum(s ** 2) / np.sum(s ** 2)
    k = max(1, int(np.searchsorted(energy, energy_ratio) + 1))
    basis = u[:, :k].T
    coeff = basis.conj() @ (shape - mean)

    validation = _json(report_file)
    if validation.get("tag") != "n1_%d" % n1:
        raise ValueError("验证报告 tag 与 N1 不一致")
    s1 = validation["s1"]["B_amp_shape"]
    band = validation["s5"]["bands"]["0.1"]
    hold_x = sorted(float(xs[i]) for i in holdout)
    model_id = "pressure-amp-shape-n1-%d-n2-%d-f-%g-v1" % (n1, n2, freq_hz)
    arrays_name = "branch_n1_%d_arrays.npz" % n1
    arrays_path = out / arrays_name
    np.savez_compressed(
        arrays_path, mask=mask, points_xyz_m=points, x_train=x_train,
        log10_norm_train=np.log10(norms), shape_mean=mean[:, 0],
        shape_basis=basis, coeff_train=coeff,
    )
    manifest = {
        "schema": SCHEMA,
        "model_id": model_id,
        "model_state": "draft",
        "human_approved": False,
        "field": {"name": FIELD_NAME, "units": "Pa", "dtype": "complex128"},
        "method": "log10 norm PCHIP + unit-norm complex shape POD + coefficient PCHIP",
        "branch": {"N_w_te1": n1, "N_w_te2": n2, "freq_Hz": float(freq_hz)},
        "applicability": {
            "x_scale": [min(hold_x), max(hold_x)],
            "policy": "范围由冻结 x 留出点覆盖决定；禁止外推",
        },
        "training": {
            "n_train": int(train.size), "n_holdout": int(holdout.size),
            "n_modes": int(k), "energy_ratio": float(energy[k - 1]),
            "x_train_span": [float(x_train.min()), float(x_train.max())],
        },
        "validation": {
            "global_rel_l2_max": float(s1["global_max"]),
            "key_region_rel_l2_max": float(s1["key_max"]),
            "field_rel_l2_error_bound": float(band["band_rel_L2"]),
            "error_bound_kind": "90%-target conformal relative-L2 band (empirical)",
            "holdout_coverage": float(band["coverage_on_holdout"]),
            "n_holdout": int(band["n_holdout"]),
            "s_levels": dict(validation["gate_view"]),
            "warning": "S1/S2 passed；S5 因冻结留出集只有 5 点而 inconclusive，不能宣称全面认证",
        },
        "provenance": {
            "cache_sha256": _sha256(cache),
            "points_sha256": _sha256(points_file),
            "validation_report_sha256": _sha256(report_file),
            "raw_field": FIELD_NAME,
        },
        "arrays_file": arrays_name,
        "arrays_sha256": _sha256(arrays_path),
    }
    mp = out / ("branch_n1_%d.json" % n1)
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return mp


def write_registry(manifests: Sequence[str | pathlib.Path], out_path: str | pathlib.Path) -> pathlib.Path:
    out = pathlib.Path(out_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    items = []
    for p in manifests:
        mp = pathlib.Path(p).resolve()
        meta = _json(mp)
        items.append({"model_id": meta["model_id"], "branch": meta["branch"],
                      "manifest_file": pathlib.Path(mp).relative_to(out.parent).as_posix()})
    reg = {
        "schema": REGISTRY_SCHEMA,
        "field": FIELD_NAME,
        "source_type": "ai_solver",
        "model_state": "draft",
        "human_approved": False,
        "branches": items,
        "red_lines": [
            "不跨 N1/N2/频率插值",
            "超出 x 留出证据范围即拒答",
            "AI 解不冒充 COMSOL 解",
            "人工放行前保持 draft",
        ],
    }
    out.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="有界单一复声压场 AI 求解器")
    ap.add_argument("--registry", required=True)
    ap.add_argument("--x", type=float, required=True)
    ap.add_argument("--n1", type=float, required=True)
    ap.add_argument("--n2", type=float, default=8)
    ap.add_argument("--freq", type=float, default=20_000_000)
    ap.add_argument("--out", help="命中时把复场和点集写入 NPZ")
    args = ap.parse_args(argv)
    solver = SinglePressureSolver.load(args.registry)
    result = solver.solve(x_scale=args.x, n1=args.n1, n2=args.n2, freq_hz=args.freq)
    if isinstance(result, PressurePrediction):
        if not args.out:
            print(json.dumps({**result.report, "refused": True,
                              "reason": "需要 --out 才能安全写出大数组；未输出场值"},
                             ensure_ascii=False, indent=2))
            return 2
        target = pathlib.Path(args.out).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(target, p_total_Pa=result.field,
                            points_xyz_m=result.points_xyz_m, mask=result.mask)
        payload = dict(result.report)
        payload["output_file"] = str(target)
        payload["output_sha256"] = _sha256(target)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
