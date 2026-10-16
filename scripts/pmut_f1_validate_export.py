"""只读核验取回的 21 个已存场快照；不验证场精度、第一模态或训练泛化。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

import numpy as np
from scipy.io import loadmat

EXPECTED_CASES = 21
OBSERVATION = np.array([0.0, 0.0, -1e-5])
CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
LIMITATIONS = [
    "Checks export integrity, selected-solution metadata and exact-point pressure consistency only.",
    "Does not establish a field-level error bound or first-mode identity.",
    "Does not certify physics equivalence, cross-model transfer or operator training readiness.",
    "Source-model hash is checked for consistency between artifacts; the remote MPH is not rehashed locally.",
    "Scalar-table hashes are compared with the manifest, not recomputed from unprovided tables.",
]


class ExportValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ExportValidationError(message)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scalar(value):
    while isinstance(value, np.ndarray):
        require(value.size == 1, "Expected a scalar MAT value")
        value = value.reshape(-1)[0]
    return value.item() if isinstance(value, np.generic) else value


def number(value, name, *, integer=False):
    value = scalar(value)
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value), "Invalid numeric field: " + name)
    if integer:
        require(value == int(value) and value > 0, "Expected positive integer: " + name)
    return float(value)


def flag(value, expected, name):
    value = scalar(value)
    require(isinstance(value, (bool, int, float)) and value in (0, 1)
            and bool(value) is expected, "Incorrect flag: " + name)


def text_value(value, name):
    value = scalar(value)
    require(isinstance(value, str) and bool(value), "Invalid text field: " + name)
    return value


def digest_value(value, name):
    value = text_value(value, name)
    require(HASH.fullmatch(value) is not None, "Invalid SHA256: " + name)
    return value.lower()


def struct_value(value, name):
    value = scalar(value)
    if hasattr(value, "_fieldnames"):
        value = {key: getattr(value, key) for key in value._fieldnames}
    require(isinstance(value, dict), "Invalid structure: " + name)
    return value


def vector(value, n, name, *, complex_ok=False):
    a = np.asarray(value)
    require(a.dtype.kind in "biufc" and a.size == n and a.ndim <= 2
            and (a.ndim < 2 or 1 in a.shape), "Invalid vector: " + name)
    require(complex_ok or not np.iscomplexobj(a), "Unexpected complex vector: " + name)
    return a.reshape(-1)


def safe_basename(remote_path, case_id):
    """远端路径仅作元数据，绝不在本地按该路径打开文件。"""
    require(isinstance(remote_path, str) and remote_path and "\x00" not in remote_path,
            "Invalid report file path")
    normalized = remote_path.replace("\\", "/")
    require(not normalized.endswith("/") and not any(p in (".", "..") for p in normalized.split("/")),
            "Unsafe report file path")
    # 允许 COMSOL 生成的 Linux/Windows 绝对路径或一个文件名，不接受任意相对子目录。
    require(PurePosixPath(normalized).is_absolute() or PureWindowsPath(remote_path).is_absolute()
            or "/" not in normalized, "Relative report subdirectory is not allowed")
    basename = normalized.rsplit("/", 1)[-1]
    require(basename == case_id + ".mat", "Report basename does not match case_id")
    return basename


def source_stamp(value):
    require(isinstance(value, dict) and set(value) == {"size_bytes", "mtime_millis"},
            "Missing or invalid source stamp")
    size = number(value["size_bytes"], "source size", integer=True)
    mtime = number(value["mtime_millis"], "source mtime", integer=True)
    return size, mtime


def read_json(path):
    def no_constant(value):
        raise ExportValidationError("Nonfinite JSON constant: " + value)
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle, parse_constant=no_constant)


def indexed_cases(value, label):
    require(isinstance(value, list) and len(value) == EXPECTED_CASES,
            label + " must contain exactly 21 cases")
    out = {}
    seen = set()
    for case in value:
        require(isinstance(case, dict), label + " contains a non-object case")
        case_id = case.get("case_id")
        require(isinstance(case_id, str) and CASE_ID.fullmatch(case_id) is not None,
                "Unsafe case_id")
        require(case_id.lower() not in seen, "Duplicate case_id")
        seen.add(case_id.lower())
        out[case_id] = case
    return out


def validate_sample(path, selected, reported, report, manifest_hash):
    case_id = selected["case_id"]
    require(selected.get("mode_identity") == "unverified", "Manifest claims verified first mode")
    expected_hash = digest_value(reported["sha256"], "snapshot sha256")
    require(file_sha256(path) == expected_hash, "Snapshot SHA256 mismatch: " + case_id)
    m = loadmat(path, struct_as_record=False, squeeze_me=False)
    for field, expected in {
        "schema": "memsharness.pmut_f1_stored_field/v0", "case_id": case_id,
        "source_type": "simulation", "source_dataset": "dset3", "canonical_expression": "acpr.p_t",
        "source_model": report["source_model"], "mode_identity": "unverified",
        "source_hash_verification": "computed_from_file_bytes",
        "point_evaluation_method": "stored_finite_element_solution_at_exact_coordinate_ext0",
        "solution_identity_verification_scope": "requested_parameters_frequency_and_point_pressure_not_physics_equivalence",
    }.items():
        require(text_value(m[field], field) == expected, "Snapshot metadata mismatch: " + field)
    require(digest_value(m["source_model_sha256"], "MAT source hash") == report["source_model_sha256"].lower(),
            "Snapshot source model hash mismatch")
    require(digest_value(m["manifest_sha256"], "MAT manifest hash") == manifest_hash,
            "Snapshot manifest hash mismatch")
    for field, expected in {"solution_identity_verified": True, "point_reference_pressure_consistent": True,
                            "training_ready": False, "geometry_material_bc_exported": False}.items():
        flag(m[field], expected, field)
    for field in ("x_scale", "N_w_te1", "N_w_te2", "frequency_Hz", "outer_solnum", "inner_solnum"):
        integer = field in ("N_w_te1", "N_w_te2", "outer_solnum", "inner_solnum")
        actual = number(m[field], field, integer=integer)
        expected = number(selected[field], "manifest " + field, integer=integer)
        tolerance = 0 if integer else (1.0 if field == "frequency_Hz" else 5e-9)
        require(abs(actual - expected) <= tolerance, "Snapshot parameter/index mismatch: " + field)
    xyz = np.asarray(m["xyz_m"])
    require(xyz.ndim == 2 and xyz.shape[0] == 3 and xyz.shape[1] > 0
            and xyz.dtype.kind in "iuf" and np.isfinite(xyz).all(), "Invalid 3xN coordinates")
    n = xyz.shape[1]
    require(number(reported["n_points"], "report n_points", integer=True) == n, "Point count mismatch")
    for axis, field in enumerate(("x_m", "y_m", "z_m")):
        require(np.array_equal(vector(m[field], n, field), xyz[axis]), "Coordinate aliases disagree")
    p = vector(m["p_total_Pa"], n, "p_total_Pa", complex_ok=True).astype(complex)
    mask_values = vector(m["p_finite_mask"], n, "p_finite_mask")
    require(np.isin(mask_values, (0, 1)).all(), "Mask contains nonboolean values")
    mask = mask_values.astype(bool)
    finite = np.isfinite(p.real) & np.isfinite(p.imag)
    require(np.array_equal(mask, finite) and bool(mask.any()), "Finite pressure mask mismatch")
    require(number(reported["n_finite_pressure"], "report n_finite_pressure", integer=True) == int(mask.sum()),
            "Finite pressure count mismatch")
    units = struct_value(m["units"], "units")
    for name, expected in {"coordinates": "m", "pressure": "Pa", "frequency": "Hz"}.items():
        require(text_value(units[name], name) == expected, "Incorrect units: " + name)
    ref = struct_value(m["point_reference"], "point_reference")
    require(np.array_equal(vector(ref["xyz_m"], 3, "point reference coordinate"), OBSERVATION),
            "Exact observation coordinate mismatch")
    require(text_value(ref["source_type"], "point source") == "scalar_table_reference_not_field_node",
            "Point reference provenance mismatch")
    require(text_value(ref["table_hash_verification"], "table hash verification") == "manifest_declared_not_recomputed",
            "Point reference verification scope mismatch")
    require(digest_value(ref["source_table_sha256"], "point source hash") ==
            digest_value(selected["source_table_sha256"], "manifest table hash"), "Scalar-table hash mismatch")
    require(number(ref["source_table_row_1based"], "point source row", integer=True) ==
            number(selected["source_table_row_1based"], "manifest source row", integer=True), "Scalar-table row mismatch")
    flag(ref["same_source_model_verified"], False, "point same model verified")
    flag(ref["pressure_consistent_with_stored_solution"], True, "point reference consistency")
    require(number(ref["comparison_rtol"], "comparison rtol") == 1e-6
            and number(ref["comparison_atol_Pa"], "comparison atol") == 1e-9, "Point comparison tolerance changed")
    expected = complex(number(selected["p_point_real_Pa"], "reference real"),
                       number(selected["p_point_imag_Pa"], "reference imag"))
    recorded = complex(number(ref["p_real_Pa"], "recorded reference real"),
                       number(ref["p_imag_Pa"], "recorded reference imag"))
    require(abs(recorded - expected) <= 1e-12 + 1e-12 * abs(expected), "Scalar point reference changed")
    point = scalar(m["p_point_stored_solution_Pa"])
    require(isinstance(point, (int, float, complex)) and np.isfinite(point), "Invalid exact-point complex pressure")
    error = abs(complex(point) - expected)
    tolerance = 1e-9 + 1e-6 * abs(expected)
    require(error <= tolerance, "Exact-point pressure differs from scalar table: " + case_id)
    flag(reported["point_reference_pressure_consistent"], True, "report point consistency")
    require(text_value(reported["mode_identity"], "report mode") == "unverified", "Report claims verified mode")
    dom_available = scalar(m["dom_available"])
    report_dom_available = scalar(reported["dom_available"])
    flag(report_dom_available, bool(report_dom_available), "report domain availability")
    flag(dom_available, bool(report_dom_available), "domain availability")
    if bool(dom_available):
        dom = vector(m["dom"], n, "domain ids")
        finite_dom = dom[np.isfinite(dom)]
        require(len(finite_dom) > 0 and np.all(finite_dom >= 1) and np.all(finite_dom == np.floor(finite_dom)),
                "Invalid optional domain IDs")
    require(file_sha256(path) == expected_hash, "Snapshot changed during validation")
    return {"case_id": case_id, "file": path.name, "sha256": expected_hash, "n_points": n,
            "n_finite_pressure": int(mask.sum()), "exact_point_abs_error_Pa": float(error),
            "exact_point_tolerance_Pa": float(tolerance), "mode_identity": "unverified", "training_ready": False}


def validate_export(manifest_path: Path, export_dir: Path) -> dict:
    manifest_path, export_dir = Path(manifest_path).resolve(), Path(export_dir).resolve()
    manifest_hash = file_sha256(manifest_path)
    manifest = read_json(manifest_path)
    report_path = export_dir / "export_report.json"
    require(report_path.is_file() and not report_path.is_symlink(), "Missing or linked export_report.json")
    report_hash = file_sha256(report_path)
    report = read_json(report_path)
    require(isinstance(manifest, dict) and isinstance(report, dict), "Manifest and report must be JSON objects")
    require(manifest.get("schema") == "memsharness.pmut_f1_export_manifest/v0", "Invalid manifest schema")
    require(report.get("schema") == "memsharness.pmut_f1_stored_export/v0", "Invalid report schema")
    require(report.get("status") == "complete", "Export report is incomplete or failed")
    for payload in (manifest, report):
        require(payload.get("dataset") == "dset3" and payload.get("field_expression") == "acpr.p_t",
                "Wrong dataset or pressure expression")
        flag(payload["training_ready"], False, "training_ready")
    require(np.array_equal(np.asarray(manifest["observation_xyz_m"]), OBSERVATION), "Wrong manifest observation point")
    expected, reported = indexed_cases(manifest["cases"], "Manifest"), indexed_cases(report["cases"], "Report")
    require(set(expected) == set(reported), "Report case set differs from manifest")
    require(number(report["requested"], "requested", integer=True) == EXPECTED_CASES
            and number(report["completed"], "completed", integer=True) == EXPECTED_CASES, "Incomplete case counts")
    flag(report["source_unchanged"], True, "source unchanged")
    require(source_stamp(report["source_before"]) == source_stamp(report["source_after"]), "Source stamps changed")
    require(report.get("mode_identity") == "unverified", "Report claims verified first mode")
    flag(report["point_reference_same_model_verified"], False, "same model verified")
    digest_value(report["source_model_sha256"], "report source hash")
    text_value(report["source_model"], "source model")
    require(digest_value(report["manifest_sha256"], "report manifest hash") == manifest_hash, "Manifest SHA256 mismatch")
    names = {safe_basename(reported[k]["file"], k) for k in expected}
    require(len(names) == EXPECTED_CASES, "Duplicate snapshot basenames")
    entries = list(export_dir.iterdir())
    require(all(p.is_file() and not p.is_symlink() for p in entries), "Export contains subdirectories or linked files")
    require({p.name for p in entries} == names | {"export_report.json"}, "Export file set is missing or contains extra files")
    cases = [validate_sample(export_dir / (key + ".mat"), expected[key], reported[key], report, manifest_hash)
             for key in sorted(expected)]
    require(file_sha256(manifest_path) == manifest_hash and file_sha256(report_path) == report_hash,
            "Manifest or report changed during validation")
    return {"schema": "memsharness.pmut_f1_export_qc/v0", "passed": True,
            "scope": "recovered_export_integrity_and_exact_point_consistency", "n_cases": len(cases),
            "manifest_path": str(manifest_path), "manifest_sha256": manifest_hash,
            "export_dir": str(export_dir), "export_report_sha256": report_hash,
            "source_model_sha256": report["source_model_sha256"].lower(),
            "source_unchanged_report_verified": True, "source_model_rehashed_locally": False,
            "mode_identity": "unverified", "training_ready": False, "release_allowed": False,
            "limitations": LIMITATIONS, "cases": cases}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="可选的新 QC JSON 文件；省略时只打印结果")
    args = parser.parse_args(argv)
    if args.output is not None and args.output.exists():
        raise FileExistsError("QC output already exists; history is append-only")
    if args.output is not None and args.output.resolve().is_relative_to(args.export_dir.resolve()):
        raise ValueError("QC output must be outside the read-only recovered export directory")
    try:
        qc = validate_export(args.manifest, args.export_dir)
    except (ExportValidationError, OSError, ValueError, KeyError, TypeError) as exc:
        qc = {"schema": "memsharness.pmut_f1_export_qc/v0", "passed": False,
              "error": type(exc).__name__ + ": " + str(exc), "training_ready": False,
              "release_allowed": False, "limitations": LIMITATIONS}
    if args.output is not None:
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(qc, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    print(json.dumps(qc, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if qc["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
