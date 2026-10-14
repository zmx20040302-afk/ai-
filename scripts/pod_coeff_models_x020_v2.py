# -*- coding: utf-8 -*-
"""x=0.20 七快照：训练折内选模、范数/形状分解、端点门禁和 persistence 基线。

本脚本只读取本地冻结点集与插值缓存，不联网、不调用 COMSOL。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone
from typing import Any

import numpy as np
from scipy.interpolate import PchipInterpolator, RBFInterpolator


REPO = pathlib.Path(__file__).resolve().parents[1]
RUN = REPO / "work/runs/te2_8_pod_fields_20261005/pod_pipeline_x020_v2"
POINTS = RUN / "common_points_xyz_m.tsv"
CACHE = RUN / "interp_cache.npz"
OUT = RUN / "coeff_models_v2/coeff_models_x020_normalized_report.json"
EXPECTED_POINTS_SHA256 = "9067cbdc3e43ced9c270de79e6add0672afaefb7d6dc08cddd9b57bcc487f0e7"
N1 = np.arange(1, 8, dtype=float)
METHODS = ("linear", "pchip", "rbf_tps", "poly1_ridge", "poly2_ridge")


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_or_none(value: float | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def n_modes_999(singular_values: np.ndarray) -> int:
    energy = singular_values.astype(float) ** 2
    total = float(energy.sum())
    if total <= 0:
        return 0
    return int(np.searchsorted(np.cumsum(energy / total), 0.999) + 1)


def linear_extrapolate(xs: np.ndarray, values: np.ndarray, xq: float) -> np.ndarray:
    """沿 axis=0 线性插值；区间外用最近两训练点线性外推。"""
    if xq < xs[0]:
        return values[0] + (values[1] - values[0]) * (xq - xs[0]) / (xs[1] - xs[0])
    if xq > xs[-1]:
        return values[-1] + (values[-1] - values[-2]) * (xq - xs[-1]) / (xs[-1] - xs[-2])
    right = int(np.searchsorted(xs, xq, side="right"))
    left = max(0, right - 1)
    right = min(len(xs) - 1, right)
    if left == right:
        return values[left]
    weight = (xq - xs[left]) / (xs[right] - xs[left])
    return values[left] * (1 - weight) + values[right] * weight


def predict_real(method: str, xs: np.ndarray, values: np.ndarray, xq: float) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    if method == "linear":
        return np.asarray(linear_extrapolate(xs, values, xq)).ravel()
    if method == "pchip":
        if xs[0] <= xq <= xs[-1]:
            return np.asarray(PchipInterpolator(xs, values, axis=0)(xq)).ravel()
        return np.asarray(linear_extrapolate(xs, values, xq)).ravel()
    if method == "rbf_tps":
        model = RBFInterpolator(
            xs[:, None], values, kernel="thin_plate_spline", degree=1, smoothing=0.0
        )
        return np.asarray(model([[xq]])[0]).ravel()
    if method in ("poly1_ridge", "poly2_ridge"):
        degree = 1 if method == "poly1_ridge" else 2
        center = float(xs.mean())
        scale = max(float(xs.std()), 1e-12)
        normalized = (xs - center) / scale
        design = np.vander(normalized, degree + 1, increasing=True)
        ridge = 1e-8 * np.eye(degree + 1)
        coefficients = np.linalg.solve(design.T @ design + ridge, design.T @ values)
        query = np.vander([(xq - center) / scale], degree + 1, increasing=True)
        return np.asarray(query @ coefficients).ravel()
    raise ValueError(f"未知方法：{method}")


def predict_complex(method: str, xs: np.ndarray, values: np.ndarray, xq: float) -> np.ndarray:
    values = np.asarray(values, dtype=np.complex128)
    real = predict_real(method, xs, values.real, xq)
    imag = predict_real(method, xs, values.imag, xq)
    return real + 1j * imag


def fit_fold_pod(train_fields: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    mean = train_fields.mean(axis=1, keepdims=True)
    centered = train_fields - mean
    basis, singular_values, _ = np.linalg.svd(centered, full_matrices=False)
    k = n_modes_999(singular_values)
    if k < 1:
        raise ValueError("训练折没有可建模的场变化")
    basis = basis[:, :k]
    coefficients = (basis.conj().T @ centered).T
    return mean, basis, coefficients, k


def raw_pod_prediction(
    method: str, train_x: np.ndarray, train_fields: np.ndarray, query_x: float
) -> tuple[np.ndarray, int]:
    mean, basis, coefficients, k = fit_fold_pod(train_fields)
    predicted_coefficients = predict_complex(method, train_x, coefficients, query_x)
    return mean[:, 0] + basis @ predicted_coefficients, k


def norm_shape_prediction(
    method: str, train_x: np.ndarray, train_fields: np.ndarray, query_x: float
) -> tuple[np.ndarray, int, float]:
    norms = np.linalg.norm(train_fields, axis=0)
    if np.any(norms <= 0):
        raise ValueError("训练折包含零范数场，无法做范数/形状分解")
    shapes = train_fields / norms[None, :]
    mean, basis, coefficients, k = fit_fold_pod(shapes)
    predicted_coefficients = predict_complex(method, train_x, coefficients, query_x)
    predicted_shape = mean[:, 0] + basis @ predicted_coefficients
    shape_norm = float(np.linalg.norm(predicted_shape))
    if shape_norm <= 0:
        raise ValueError("预测单位形状范数为零")
    predicted_shape = predicted_shape / shape_norm
    predicted_log10_norm = float(predict_real(method, train_x, np.log10(norms), query_x)[0])
    predicted_norm = float(10.0**predicted_log10_norm)
    return predicted_shape * predicted_norm, k, predicted_norm


def summarize(rows: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["rel_L2"]) for row in rows]
    interior = [float(row["rel_L2"]) for row in rows if row["fold_type"] == "interior"]
    endpoint = [float(row["rel_L2"]) for row in rows if row["fold_type"] == "endpoint_extrapolation"]
    baseline_by_n1 = {row["held_out_n1"]: float(row["rel_L2"]) for row in baseline}
    for row in rows:
        base = baseline_by_n1[row["held_out_n1"]]
        row["rel_L2_over_raw_persistence"] = finite_or_none(float(row["rel_L2"]) / base if base else None)
    return {
        "per_fold": rows,
        "max_all": max(values),
        "median_all": float(np.median(values)),
        "max_interior": max(interior) if interior else None,
        "max_endpoint": max(endpoint) if endpoint else None,
        "max_all_over_raw_persistence_max": max(values) / max(baseline_by_n1.values()),
        "beats_raw_persistence_on_max": max(values) < max(baseline_by_n1.values()),
        "n_folds_better_than_raw_persistence": sum(
            float(row["rel_L2"]) < baseline_by_n1[row["held_out_n1"]] for row in rows
        ),
    }


def main() -> int:
    points_hash = sha256_file(POINTS)
    if points_hash != EXPECTED_POINTS_SHA256:
        raise RuntimeError(f"冻结点集哈希不符：{points_hash}")
    cache_hash = sha256_file(CACHE)
    loaded = np.load(CACHE)
    pressure = np.asarray(loaded["P"], dtype=np.complex128)
    mask = np.asarray(loaded["mask"], dtype=bool)
    if pressure.shape[1] != 7 or pressure.shape[0] != len(mask):
        raise ValueError(f"缓存形状异常：P={pressure.shape}, mask={mask.shape}")
    fields = pressure[mask]

    report: dict[str, Any] = {
        "kind": "pod_coeff_models_x020_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "points_file": str(POINTS.relative_to(REPO)),
            "sha256_points_file": points_hash,
            "interp_cache": str(CACHE.relative_to(REPO)),
            "sha256_interp_cache": cache_hash,
            "n1": N1.astype(int).tolist(),
            "n_common_points": int(mask.sum()),
        },
        "methodology": {
            "fold_local_mode_selection": True,
            "mode_energy_threshold": 0.999,
            "endpoint_definition": "held-out N1 lies outside [min(train N1), max(train N1)]",
            "normalization": (
                "factor field into scalar L2 norm and unit-norm complex shape; model log10(norm) "
                "and complex POD shape separately; no phase alignment"
            ),
            "raw_persistence": "nearest training snapshot in N1, without POD truncation",
            "segmentation": None,
        },
        "field_norm_by_n1": {
            str(int(n1)): float(norm)
            for n1, norm in zip(N1, np.linalg.norm(fields, axis=0))
        },
        "raw_persistence": {},
        "models": {},
        "gate": {},
        "errors": [],
    }

    baseline_rows: list[dict[str, Any]] = []
    for held_out in range(7):
        train = [index for index in range(7) if index != held_out]
        train_x = N1[train]
        nearest_local = int(np.argmin(np.abs(train_x - N1[held_out])))
        predicted = fields[:, train[nearest_local]]
        truth = fields[:, held_out]
        rel = float(np.linalg.norm(predicted - truth) / np.linalg.norm(truth))
        fold_type = (
            "interior"
            if train_x.min() < N1[held_out] < train_x.max()
            else "endpoint_extrapolation"
        )
        baseline_rows.append(
            {
                "held_out_n1": int(N1[held_out]),
                "nearest_training_n1": int(train_x[nearest_local]),
                "fold_type": fold_type,
                "rel_L2": rel,
            }
        )
    report["raw_persistence"] = summarize(baseline_rows, baseline_rows)

    for representation in ("raw", "norm_shape"):
        for method in METHODS:
            name = f"{representation}_{method}"
            rows: list[dict[str, Any]] = []
            for held_out in range(7):
                train = [index for index in range(7) if index != held_out]
                train_x = N1[train]
                train_fields = fields[:, train]
                if representation == "raw":
                    predicted, k = raw_pod_prediction(
                        method, train_x, train_fields, float(N1[held_out])
                    )
                    predicted_norm = float(np.linalg.norm(predicted))
                else:
                    predicted, k, predicted_norm = norm_shape_prediction(
                        method, train_x, train_fields, float(N1[held_out])
                    )
                truth = fields[:, held_out]
                truth_norm = float(np.linalg.norm(truth))
                rel = float(np.linalg.norm(predicted - truth) / truth_norm)
                fold_type = (
                    "interior"
                    if train_x.min() < N1[held_out] < train_x.max()
                    else "endpoint_extrapolation"
                )
                rows.append(
                    {
                        "held_out_n1": int(N1[held_out]),
                        "fold_type": fold_type,
                        "k_modes_selected_from_training_fold": int(k),
                        "rel_L2": rel,
                        "true_field_norm": truth_norm,
                        "predicted_field_norm": predicted_norm,
                        "relative_norm_error": abs(predicted_norm - truth_norm) / truth_norm,
                    }
                )
            report["models"][name] = summarize(rows, baseline_rows)

    baseline_max = float(report["raw_persistence"]["max_all"])
    ranked = sorted(
        report["models"].items(), key=lambda item: float(item[1]["max_all"])
    )
    best_name, best_result = ranked[0]
    report["gate"] = {
        "user_rel_L2_threshold": None,
        "baseline_name": "raw_persistence",
        "baseline_max_all": baseline_max,
        "best_model_by_max_all": best_name,
        "best_model_max_all": float(best_result["max_all"]),
        "best_model_max_over_baseline": float(best_result["max_all"]) / baseline_max,
        "best_model_beats_baseline_on_max": bool(best_result["max_all"] < baseline_max),
        "expansion_to_405_allowed": False,
        "reasons": [
            "用户尚未给出场级 rel_L2 放行阈值",
            "本阶段仅有 x_scale=0.20 的 7 个快照",
            "端点外推必须保留在全体 max 中单列报告",
        ],
    }
    report["decision"] = (
        "normalization_experiment_complete_but_not_approved_for_engineering_use"
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    OUT.write_text(payload, encoding="utf-8", newline="\n")
    # 严格回读，防止非法 JSON 或缺字段。
    check = json.loads(OUT.read_text(encoding="utf-8"))
    required = (
        "inputs",
        "methodology",
        "raw_persistence",
        "models",
        "gate",
        "decision",
        "errors",
    )
    missing = [key for key in required if key not in check]
    if missing:
        raise RuntimeError(f"报告缺少字段：{missing}")

    print(json.dumps({
        "report": str(OUT),
        "baseline_max_all": baseline_max,
        "best_model": best_name,
        "best_model_max_all": best_result["max_all"],
        "best_model_max_interior": best_result["max_interior"],
        "best_model_max_endpoint": best_result["max_endpoint"],
        "expansion_to_405_allowed": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
