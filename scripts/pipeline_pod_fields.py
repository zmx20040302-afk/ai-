# -*- coding: utf-8 -*-
"""PMUT 复声压场：显式公共点集 → 插值/掩膜 → POD → 真正留一预测。

远端只通过 scp 读取；所有解析、插值和报告均在本地完成。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any


DEFAULT_HOST = "ubuntu-10-180-7-46"
DEFAULT_REMOTE = "/home/lab/projAI4US/autodesign/exported_results/te2_8_pod_fields_20MHz_v1"


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def parse_grid(value: str) -> tuple[int, int, int]:
    parts = value.lower().replace("x", ",").split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("--grid 必须是 nx,ny,nz，例如 17,17,9")
    grid = tuple(int(part.strip()) for part in parts)
    if any(n < 2 for n in grid):
        raise argparse.ArgumentTypeError("每个网格轴至少需要 2 个点")
    return grid  # type: ignore[return-value]


def run_scp(host: str, remote_path: str, local_path: pathlib.Path) -> dict[str, Any]:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    proc = subprocess.run(
        [
            "scp",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=20",
            f"{host}:{remote_path}",
            str(local_path),
        ],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    result: dict[str, Any] = {
        "rc": proc.returncode,
        "seconds": round(time.perf_counter() - started, 3),
    }
    if proc.returncode:
        result["stderr"] = (proc.stderr or "")[-1000:]
    return result


def fetch_index(host: str, remote_dir: str, local_dir: pathlib.Path) -> pathlib.Path:
    target = local_dir / "snapshot_index.tsv"
    if not target.is_file():
        result = run_scp(host, f"{remote_dir}/snapshot_index.tsv", target)
        if result["rc"] != 0:
            raise RuntimeError(f"snapshot_index.tsv 下载失败：{result.get('stderr', '')}")
    return target


def load_index(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def choose_rows(
    rows: list[dict[str, str]], which: str, split_protocol: str
) -> list[dict[str, str]]:
    pod = [row for row in rows if row.get("kind") == "pod20"]
    if which == "x020":
        return [row for row in pod if abs(float(row["x_scale"]) - 0.20) < 5e-10]
    if which == "all":
        return pod
    if which == "train":
        if split_protocol == "n":
            return [row for row in pod if row.get("n_holdout_role") == "train"]
        if split_protocol == "x":
            return [row for row in pod if row.get("x_holdout_role") == "train"]
        return [
            row
            for row in pod
            if row.get("n_holdout_role") == "train"
            and row.get("x_holdout_role") == "train"
        ]

    spec = pathlib.Path(which)
    if spec.is_file():
        requested = {
            line.strip()
            for line in spec.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    else:
        requested = {item.strip() for item in which.split(",") if item.strip()}
    selected = [row for row in pod if pathlib.PurePosixPath(row["file"]).name in requested]
    missing = requested - {pathlib.PurePosixPath(row["file"]).name for row in selected}
    if missing:
        raise ValueError(f"显式文件列表中有 {len(missing)} 个文件不在权威清单：{sorted(missing)[:5]}")
    return selected


def fetch_snapshot(
    host: str, row: dict[str, str], local_data_dir: pathlib.Path
) -> tuple[pathlib.Path, dict[str, Any]]:
    remote_path = row["file"]
    name = pathlib.PurePosixPath(remote_path).name
    target = local_data_dir / name
    transfer: dict[str, Any] | None = None
    if not target.is_file():
        transfer = run_scp(host, remote_path, target)
        if transfer["rc"] != 0:
            raise RuntimeError(f"{name} 下载失败：{transfer.get('stderr', '')}")
    info: dict[str, Any] = {
        "name": name,
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "n1": int(round(float(row["N_w_te1"]))),
        "x_scale": float(row["x_scale"]),
        "freq_Hz": float(row["freq_Hz"]),
        "split_x": row.get("x_holdout_role"),
        "split_n": row.get("n_holdout_role"),
        "n_points": int(row["n_points"]),
        "remote_file": remote_path,
    }
    if transfer is not None:
        info["transfer"] = transfer
    return target, info


def load_snapshot(path: pathlib.Path, info: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    from scipy.io import loadmat

    mat = loadmat(
        path,
        variable_names=[
            "x_m",
            "y_m",
            "z_m",
            "p_total_Pa",
            "p_finite_mask",
            "freq_Hz",
            "x_scale",
            "N_w_te1",
            "N_w_te2",
        ],
    )
    xyz = np.column_stack(
        [mat["x_m"].ravel(), mat["y_m"].ravel(), mat["z_m"].ravel()]
    ).astype(np.float64, copy=False)
    pressure = np.asarray(mat["p_total_Pa"]).ravel().astype(np.complex128, copy=False)
    declared = np.asarray(mat["p_finite_mask"]).ravel().astype(bool, copy=False)
    if len(xyz) != len(pressure) or len(pressure) != len(declared):
        raise ValueError(f"{path.name} 坐标、场和掩膜长度不一致")
    finite_xyz = np.all(np.isfinite(xyz), axis=1)
    finite_p = np.isfinite(pressure.real) & np.isfinite(pressure.imag)
    valid = finite_xyz & finite_p & declared
    if valid.sum() < 5:
        raise ValueError(f"{path.name} 有效声压点不足：{int(valid.sum())}")
    info["n_points_loaded"] = int(len(xyz))
    info["n_source_valid"] = int(valid.sum())
    return {
        "path": path,
        "info": info,
        "xyz": xyz,
        "pressure": pressure,
        "declared_mask": declared,
        "valid": valid,
    }


def make_common_points(
    snapshots: list[dict[str, Any]],
    grid: tuple[int, int, int],
    tol: float,
    domain_shape: str,
) -> tuple[Any, dict[str, Any]]:
    import numpy as np

    valid_mins = np.vstack([snap["xyz"][snap["valid"]].min(axis=0) for snap in snapshots])
    valid_maxs = np.vstack([snap["xyz"][snap["valid"]].max(axis=0) for snap in snapshots])
    lower = valid_mins.max(axis=0)
    upper = valid_maxs.min(axis=0)
    if np.any(upper - lower <= 2 * tol):
        raise ValueError(f"有效场包围盒没有三维交集：lower={lower}, upper={upper}")

    # 用单元中心而非边界点，降低凸包边界的数值不稳定性。
    axes = []
    for lo, hi, n in zip(lower, upper, grid):
        lo2, hi2 = float(lo + tol), float(hi - tol)
        step = (hi2 - lo2) / n
        axes.append(lo2 + (np.arange(n) + 0.5) * step)
    mesh = np.meshgrid(*axes, indexing="ij")
    candidates = np.column_stack([axis.ravel() for axis in mesh])

    # 这些 PMUT 快照的有限声压域是以 (0,0,0) 为球心的下半球声学域。
    # 半球若用外接长方体作点集，理论占比仅 pi/6≈52.36%，会人为触发
    # 80% 掩膜门禁。用每个快照有限声压点的最大半径取保守交集半径，
    # 再从规则笛卡尔候选点中过滤出公共半球内部点。这里仅使用坐标和
    # 有限性掩膜，不读取压力数值，因而不会把留出场值泄漏进模型。
    if domain_shape == "bbox":
        spec = {
            "coordinate_system": "cartesian",
            "units": "m",
            "placement": "cell_centers_inside_intersection_bbox",
            "axes": {
                name: {
                    "intersection_start": float(lower[i]),
                    "intersection_stop": float(upper[i]),
                    "n": int(grid[i]),
                    "first_center": float(axes[i][0]),
                    "last_center": float(axes[i][-1]),
                }
                for i, name in enumerate(("x", "y", "z"))
            },
            "tol_m": tol,
            "domain_filter": {"shape": "bbox", "uses_field_values": False},
        }
        return candidates, spec

    centers = np.zeros((len(snapshots), 3), dtype=float)
    radii = []
    hemisphere_fit = []
    for i, snap in enumerate(snapshots):
        valid_xyz = snap["xyz"][snap["valid"]]
        radius = float(np.max(np.linalg.norm(valid_xyz - centers[i], axis=1)))
        radii.append(radius)
        radial = np.linalg.norm(valid_xyz - centers[i], axis=1)
        hemisphere_fit.append(
            {
                "name": snap["path"].name,
                "radius_m": radius,
                "frac_valid_points_within_radius_plus_tol": float(
                    np.mean(radial <= radius + tol)
                ),
                "frac_valid_points_at_z_le_zero_plus_tol": float(
                    np.mean(valid_xyz[:, 2] <= tol)
                ),
            }
        )
    common_radius = float(min(radii) - tol)
    radial_candidates = np.linalg.norm(candidates, axis=1)
    inside = (radial_candidates <= common_radius) & (candidates[:, 2] <= tol)
    points = candidates[inside]
    if len(points) < 10:
        raise ValueError("公共半球点集不足 10 点")
    spec = {
        "coordinate_system": "cartesian",
        "units": "m",
        "placement": "cell_centers_inside_intersection_bbox",
        "axes": {
            name: {
                "intersection_start": float(lower[i]),
                "intersection_stop": float(upper[i]),
                "n": int(grid[i]),
                "first_center": float(axes[i][0]),
                "last_center": float(axes[i][-1]),
            }
            for i, name in enumerate(("x", "y", "z"))
        },
        "tol_m": tol,
        "domain_filter": {
            "shape": "lower_hemisphere",
            "center_m": [0.0, 0.0, 0.0],
            "common_radius_m": common_radius,
            "candidate_points_before_filter": int(len(candidates)),
            "points_after_filter": int(len(points)),
            "fit_diagnostics": hemisphere_fit,
            "uses_field_values": False,
        },
    }
    return points, spec


def save_points(path: pathlib.Path, points: Any) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    np.savetxt(tmp, points, delimiter="\t", header="x_m\ty_m\tz_m", comments="")
    os.replace(tmp, path)


def sampled_rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except Exception:
        return None


def interpolate_snapshot(snapshot: dict[str, Any], points: Any) -> tuple[Any, dict[str, Any]]:
    import numpy as np
    from scipy.interpolate import griddata

    xyz = snapshot["xyz"]
    pressure = snapshot["pressure"]
    valid = snapshot["valid"]
    started = time.perf_counter()

    # 复数拆为两列实数，一次构造 Delaunay，输出后再合成复数。
    pair = np.column_stack([pressure[valid].real, pressure[valid].imag])
    linear_pair = griddata(
        xyz[valid], pair, points, method="linear", fill_value=np.nan, rescale=False
    )
    linear = linear_pair[:, 0] + 1j * linear_pair[:, 1]

    nearest_pair = griddata(xyz[valid], pair, points, method="nearest", rescale=False)
    nearest = nearest_pair[:, 0] + 1j * nearest_pair[:, 1]
    mask_nearest = griddata(
        xyz[np.all(np.isfinite(xyz), axis=1)],
        snapshot["declared_mask"][np.all(np.isfinite(xyz), axis=1)].astype(float),
        points,
        method="nearest",
        rescale=False,
    )
    finite = np.isfinite(linear.real) & np.isfinite(linear.imag) & (mask_nearest >= 0.5)
    diagnostics: dict[str, Any] = {
        "name": snapshot["path"].name,
        "seconds": round(time.perf_counter() - started, 3),
        "n_finite_after": int(finite.sum()),
        "frac_finite_after": float(finite.mean()),
        "n_mask_nearest_true": int((mask_nearest >= 0.5).sum()),
        "rss_after_bytes": sampled_rss_bytes(),
    }
    if finite.any():
        denom = float(np.linalg.norm(linear[finite]))
        diagnostics["nearest_vs_linear_rel_L2"] = (
            float(np.linalg.norm(nearest[finite] - linear[finite]) / denom)
            if denom > 0
            else None
        )
    else:
        diagnostics["nearest_vs_linear_rel_L2"] = None
    return linear, diagnostics


def modes_for_energy(singular_values: Any, target: float = 0.999) -> tuple[int, Any]:
    import numpy as np

    power = np.asarray(singular_values, dtype=float) ** 2
    total = float(power.sum())
    if total <= 0:
        return 0, np.zeros_like(power)
    cumulative = np.cumsum(power / total)
    return int(np.searchsorted(cumulative, target) + 1), cumulative


def fit_rbf_coefficients(train_params: Any, train_coefficients: Any, query: Any) -> Any:
    import numpy as np
    from scipy.interpolate import RBFInterpolator

    x = np.asarray(train_params, dtype=float).reshape(-1, 1)
    q = np.asarray(query, dtype=float).reshape(-1, 1)
    coeff = np.asarray(train_coefficients)
    real_model = RBFInterpolator(
        x, coeff.real, kernel="thin_plate_spline", smoothing=0.0, degree=1
    )
    imag_model = RBFInterpolator(
        x, coeff.imag, kernel="thin_plate_spline", smoothing=0.0, degree=1
    )
    return real_model(q) + 1j * imag_model(q)


def compute_pod_and_loo(matrix: Any, snapshots: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import numpy as np

    mean = matrix.mean(axis=1, keepdims=True)
    centered = matrix - mean
    _, singular_values, _ = np.linalg.svd(centered, full_matrices=False)
    n999, cumulative = modes_for_energy(singular_values)
    energy = (
        singular_values**2 / float(np.sum(singular_values**2))
        if np.sum(singular_values**2) > 0
        else np.zeros_like(singular_values)
    )
    pod = {
        "n_modes_999": n999,
        "energy_first5": [float(x) for x in energy[:5]],
        "energy_cumulative_first5": [float(x) for x in cumulative[:5]],
        "singular_values_head": [float(x) for x in singular_values[:10]],
        "centered": True,
        "complex_field_preserved": True,
    }

    params = np.array([snap["info"]["n1"] for snap in snapshots], dtype=float)
    loo: list[dict[str, Any]] = []
    for held_out in range(matrix.shape[1]):
        train_idx = [i for i in range(matrix.shape[1]) if i != held_out]
        train = matrix[:, train_idx]
        train_mean = train.mean(axis=1, keepdims=True)
        train_centered = train - train_mean
        basis, train_singular, _ = np.linalg.svd(train_centered, full_matrices=False)
        k_modes, _ = modes_for_energy(train_singular)
        if k_modes < 1:
            raise ValueError("训练快照没有可用于预测的场变化")
        basis = basis[:, :k_modes]
        train_coeff = (basis.conj().T @ train_centered).T
        pred_coeff = fit_rbf_coefficients(
            params[train_idx], train_coeff, [params[held_out]]
        )[0]
        predicted = train_mean[:, 0] + basis @ pred_coeff
        truth = matrix[:, held_out]
        denominator = float(np.linalg.norm(truth))
        rel_l2 = (
            float(np.linalg.norm(predicted - truth) / denominator)
            if denominator > 0
            else None
        )
        loo.append(
            {
                "held_out": snapshots[held_out]["path"].name,
                "held_out_n1": int(params[held_out]),
                "k_modes": int(k_modes),
                "coefficient_model": "RBFInterpolator(thin_plate_spline, degree=1, smoothing=0)",
                "rel_L2": rel_l2,
            }
        )
    return pod, loo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote-host", default=DEFAULT_HOST)
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE)
    parser.add_argument("--local-dir", type=pathlib.Path, required=True)
    parser.add_argument(
        "--which",
        default="x020",
        help="x020、train、all、逗号分隔文件名，或每行一个文件名的文本文件",
    )
    parser.add_argument(
        "--split-protocol",
        choices=("n", "x", "both"),
        default="n",
        help="--which train 时采用的数据提供方切分；n 对应 405 个快照",
    )
    parser.add_argument("--grid", type=parse_grid, default=(17, 17, 9))
    parser.add_argument("--tol", type=float, default=1e-12)
    parser.add_argument(
        "--domain-shape",
        choices=("lower-hemisphere", "bbox"),
        default="lower-hemisphere",
        help="公共点域；本 PMUT 声学域使用 lower-hemisphere，bbox 用于诊断",
    )
    parser.add_argument("--out", type=pathlib.Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    import numpy as np

    args = build_parser().parse_args(argv)
    report: dict[str, Any] = {
        "kind": "pod_field_pipeline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "remote_dir": args.remote_dir,
        "local_dir": str(args.local_dir.resolve()),
        "selection": {
            "which": args.which,
            "split_protocol": args.split_protocol,
            "role_columns_preserved": True,
        },
        "files": [],
        "point_set": None,
        "interpolation": {
            "method": "linear",
            "nearest_diagnostic": True,
            "complex_strategy": "real_imag_columns_then_recombine",
            "mask_strategy": "nearest_interpolation_of_declared_binary_mask",
            "n_interp": 0,
            "per_snapshot": [],
        },
        "common_mask": None,
        "pod": None,
        "loo": [],
        "loo_max_rel_L2": None,
        "loo_median_rel_L2": None,
        "predictive_assessment": None,
        "verdict": "inconclusive",
        "caveats": [
            "该管线只做降阶与内部留一自检，不等价于 COMSOL 验证。",
            "小规模 x020 运行固定 x_scale=0.20，只检验沿 N_w_te1 的变化。",
            "RBF 系数映射是本次明确采用的建模选择，不是 COMSOL 模型的一部分。",
        ],
        "errors": [],
    }
    args.local_dir.mkdir(parents=True, exist_ok=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        index_path = fetch_index(args.remote_host, args.remote_dir, args.local_dir)
        rows = choose_rows(load_index(index_path), args.which, args.split_protocol)
        rows.sort(key=lambda row: (float(row["x_scale"]), float(row["N_w_te1"])))
        if len(rows) < 4:
            raise ValueError(f"至少需要 4 个快照，当前选择到 {len(rows)} 个")

        local_data_dir = args.local_dir / "snapshots"
        # 兼容已有小规模下载目录 x020，避免重复传输。
        legacy_x020 = args.local_dir / "x020"
        local_data_dir.mkdir(parents=True, exist_ok=True)
        snapshots: list[dict[str, Any]] = []
        for row in rows:
            name = pathlib.PurePosixPath(row["file"]).name
            target = local_data_dir / name
            legacy = legacy_x020 / name
            if not target.exists() and legacy.is_file():
                target = legacy
                info = {
                    "name": name,
                    "bytes": target.stat().st_size,
                    "sha256": sha256_file(target),
                    "n1": int(round(float(row["N_w_te1"]))),
                    "x_scale": float(row["x_scale"]),
                    "freq_Hz": float(row["freq_Hz"]),
                    "split_x": row.get("x_holdout_role"),
                    "split_n": row.get("n_holdout_role"),
                    "n_points": int(row["n_points"]),
                    "remote_file": row["file"],
                    "reused_existing_local_file": True,
                }
            else:
                target, info = fetch_snapshot(args.remote_host, row, local_data_dir)
            report["files"].append(info)
            snapshots.append(load_snapshot(target, info))

        points, point_spec = make_common_points(
            snapshots, args.grid, args.tol, args.domain_shape
        )
        points_path = args.out.parent / "common_points_xyz_m.tsv"
        save_points(points_path, points)
        report["point_set"] = {
            "spec": point_spec,
            "points_file": os.path.relpath(points_path, args.out.parent),
            "sha256_points_file": sha256_file(points_path),
            "n_points": int(len(points)),
            "origin": (
                "Cartesian cell centers inside the conservative common lower-hemisphere "
                "domain inferred from coordinates and finite masks only"
            ),
            "frozen_for_run": True,
        }

        interpolated = []
        for snapshot in snapshots:
            values, diagnostics = interpolate_snapshot(snapshot, points)
            interpolated.append(values)
            report["interpolation"]["per_snapshot"].append(diagnostics)
        report["interpolation"]["n_interp"] = len(interpolated)

        finite_each = [np.isfinite(v.real) & np.isfinite(v.imag) for v in interpolated]
        common = np.logical_and.reduce(finite_each)
        common_fraction = float(common.mean())
        report["common_mask"] = {
            "n_points": int(common.sum()),
            "frac_of_point_set": common_fraction,
            "n_snapshots": len(snapshots),
            "threshold_required": 0.80,
        }
        if common_fraction < 0.80:
            report["verdict"] = "alignment_failed"
            report["errors"].append(
                f"公共掩膜率 {common_fraction:.6f} < 0.80；按门禁停止，不计算 POD/LOO。"
            )
        else:
            matrix = np.column_stack([values[common] for values in interpolated])
            pod, loo = compute_pod_and_loo(matrix, snapshots)
            report["pod"] = pod
            report["loo"] = loo
            rel_values = [item["rel_L2"] for item in loo if item["rel_L2"] is not None]
            report["loo_max_rel_L2"] = float(max(rel_values)) if rel_values else None
            report["loo_median_rel_L2"] = (
                float(np.median(rel_values)) if rel_values else None
            )
            max_rel = report["loo_max_rel_L2"]
            median_rel = report["loo_median_rel_L2"]
            worst = max(loo, key=lambda item: item["rel_L2"])
            report["predictive_assessment"] = {
                "usable_as_trusted_predictor": bool(max_rel is not None and max_rel < 1.0),
                "reason": (
                    "LOO max rel_L2 >= 1; worst-case prediction error exceeds field norm"
                    if max_rel is not None and max_rel >= 1.0
                    else "No project accuracy threshold was supplied; review LOO distribution"
                ),
                "worst_held_out": worst["held_out"],
                "worst_rel_L2": worst["rel_L2"],
                "median_rel_L2": median_rel,
            }
            if rel_values and max(rel_values) > 2 * max(float(np.median(rel_values)), 1e-15):
                report["caveats"].append(
                    "LOO 最大误差超过中位数的 2 倍，存在明显最差点，不能只报告中位数。"
                )
            if max_rel is not None and max_rel >= 1.0:
                report["caveats"].append(
                    "当前 7 点 RBF 系数映射未通过可信预测检查；POD 能量集中不代表参数外推可靠。"
                )
            report["verdict"] = "pipeline_ok"
    except Exception as exc:
        report["verdict"] = "inconclusive"
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        report["errors"].append(traceback.format_exc())
    finally:
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_text(args.out, json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print(json.dumps({
        "verdict": report["verdict"],
        "common_mask": report["common_mask"],
        "loo_max_rel_L2": report["loo_max_rel_L2"],
        "loo_median_rel_L2": report["loo_median_rel_L2"],
        "errors": report["errors"][:2],
        "report": str(args.out),
    }, ensure_ascii=False, indent=2))
    return 0 if report["verdict"] == "pipeline_ok" else 2


if __name__ == "__main__":
    sys.exit(main())
