"""已保存解算子导出的本地只读验收与研究数据适配；不求解、不补造物理条件。"""
from __future__ import annotations

import math
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

import numpy as np
from scipy.io import loadmat

from .pmut_f1_sparse_plan import branch_id, canonical_id
from .pmut_pressure_operator import (
    DATASET_SCHEMA, OperatorDataError, REQUIRED_PHYSICS, dataset_audit, load_dataset,
    read_json, require, sha256, validate_splits, write_new_json,
)

HASH = re.compile(r"[a-f0-9]{64}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
OBSERVATION = np.array([0., 0., -1e-5])
CASE_FIELDS = ("x_scale", "N_w_te1", "N_w_te2", "frequency_Hz", "source_table_row_1based")
SCOPE = "requested_parameters_frequency_and_point_pressure_not_physics_equivalence"


def scalar(value, label):
    while isinstance(value, np.ndarray):
        require(value.size == 1, "Expected scalar: " + label)
        value = value.reshape(-1)[0]
    return value.item() if isinstance(value, np.generic) else value


def number(value, label, *, positive_integer=False):
    value = scalar(value, label)
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), "Invalid number: " + label)
    if positive_integer:
        require(value >= 1 and value == int(value), "Expected positive integer: " + label)
    return float(value)


def text(value, label):
    value = scalar(value, label)
    require(isinstance(value, str) and bool(value), "Expected text: " + label)
    return value


def digest(value, label):
    value = text(value, label).lower()
    require(HASH.fullmatch(value), "Invalid SHA256: " + label)
    return value


def flag(value, expected, label):
    value = scalar(value, label)
    require(isinstance(value, (bool, int, float)) and value in (0, 1) and bool(value) is expected, "Incorrect flag: " + label)


def struct(value, label):
    value = scalar(value, label)
    if hasattr(value, "_fieldnames"):
        value = {key: getattr(value, key) for key in value._fieldnames}
    require(isinstance(value, dict), "Expected structure: " + label)
    return value


def vector(value, n, label, *, complex_allowed=False):
    array = np.asarray(value)
    require(array.dtype.kind in "biufc" and array.size == n and array.ndim <= 2
            and (array.ndim < 2 or 1 in array.shape), "Invalid vector: " + label)
    require(complex_allowed or not np.iscomplexobj(array), "Unexpected complex vector: " + label)
    return array.reshape(-1)


def indexed_cases(value, label):
    require(isinstance(value, list) and bool(value), "Expected nonempty cases: " + label)
    result, lower = {}, set()
    for case in value:
        require(isinstance(case, dict), "Non-object case: " + label)
        cid = case.get("case_id")
        require(isinstance(cid, str) and ID.fullmatch(cid), "Unsafe case ID")
        require(cid.lower() not in lower, "Duplicate case ID: " + label)
        result[cid], lower = case, lower | {cid.lower()}
    return result


def reported_basename(value, expected):
    value = text(value, "report path").replace("\\", "/")
    require("\x00" not in value and not value.endswith("/") and not any(part in (".", "..") for part in value.split("/")), "Unsafe report path")
    require(PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute() or "/" not in value, "Untrusted relative report subdirectory")
    require(value.rsplit("/", 1)[-1] == expected, "Report filename differs from expected artifact")
    return expected


def stamp(value):
    require(isinstance(value, dict) and set(value) == {"size_bytes", "mtime_millis"}, "Invalid source stamp")
    return tuple(number(value[k], k, positive_integer=True) for k in ("size_bytes", "mtime_millis"))


def check_case_values(actual, planned, label, *, include_indices=False):
    for key in CASE_FIELDS:
        a, b = number(actual[key], key), number(planned[key], key)
        tolerance = 1. if key == "frequency_Hz" else 5e-9 if key == "x_scale" else 0.
        require(abs(a - b) <= tolerance, label + " case value differs: " + key)
    require(digest(actual["source_table_sha256"], "source table") == digest(planned["source_table_sha256"], "plan source table"), label + " table hash mismatch")
    if include_indices:
        for key in ("outer_solnum", "inner_solnum"):
            require(number(actual[key], key, positive_integer=True) == number(planned[key], key, positive_integer=True), label + " solution index mismatch")


def validate_plan(path, split_policy):
    plan = read_json(path)
    require(plan.get("schema") == "memsharness.pmut_f1_sparse_plan/v0", "Unsupported sparse plan")
    require(split_policy in ("branch_holdout", "design_holdout"), "Invalid split policy")
    require(plan.get("dataset") == "dset3" and plan.get("field_expression") == "acpr.p_t"
            and plan.get("observation_xyz_m") == OBSERVATION.tolist(), "Plan physical target mismatch")
    cases = indexed_cases(plan.get("cases"), "plan")
    require(number(plan.get("n_selected"), "n_selected", positive_integer=True) == len(cases), "Plan case count mismatch")
    for cid, case in cases.items():
        require(cid == canonical_id(case) and case.get("design_id") == cid and case.get("geometry_id") == cid
                and case.get("branch_id") == branch_id(case), "Noncanonical complete design in frozen plan")
        selection = case.get("selection", {})
        require(selection.get("case_id") == cid and selection.get("design_id") == cid and selection.get("branch_id") == case["branch_id"], "Frozen split identity mismatch")
        split = selection.get("training_splits", {}).get(split_policy)
        legacy = selection.get("splits", {}).get("parameter_holdout" if split_policy == "design_holdout" else "branch_holdout")
        require(split in ("train", "validation", "test") and split == ("validation" if legacy == "dev" else legacy), "Frozen split mapping mismatch")
        require(not selection.get("previously_exposed") or split != "test", "Previously exposed design cannot become a test design")
        require(case.get("mode_identity") == "unverified", "Unexpected mode certification in plan")
    return plan, cases


def validate_sample(path, planned, requested, resolved, reported, report, context_hash):
    m = loadmat(path, struct_as_record=False, squeeze_me=False)
    require(sha256(path) == digest(reported["sha256"], "snapshot hash"), "Snapshot changed while reading")
    for key, expected in {
        "schema": "memsharness.pmut_f1_operator_field/v0", "case_id": planned["case_id"],
        "source_type": "simulation", "source_model": report["source_model"], "source_dataset": "dset3",
        "canonical_expression": "acpr.p_t", "source_hash_verification": report["source_hash_verification"],
        "mode_identity": "unverified", "dom_alignment": "same_eval_columns_not_nearest_neighbor",
        "solution_identity_verification_scope": SCOPE,
        "point_evaluation_method": "stored_finite_element_solution_at_exact_coordinate_ext0",
    }.items():
        require(text(m[key], key) == expected, "MAT metadata mismatch: " + key)
    for key, expected in {"source_model_sha256": report["source_model_sha256"], "manifest_sha256": report["manifest_sha256"],
                          "definition_context_sha256": context_hash}.items():
        require(digest(m[key], key) == expected.lower(), "MAT evidence hash mismatch: " + key)
    for key in ("training_ready", "release_allowed", "physics_inputs_complete", "geometry_material_bc_exported", "definition_context_outer_binding_verified"):
        flag(m[key], False, key)
    for key in ("solution_identity_verified", "point_reference_pressure_consistent", "dom_available"):
        flag(m[key], True, key)
    flag(m["expected_source_hash_verified"], report["expected_source_hash_verified"], "sample expected source hash")
    internal = struct(m["case_manifest"], "case_manifest")
    require(text(internal["case_id"], "case_manifest.case_id") == planned["case_id"], "Embedded manifest case differs")
    check_case_values(internal, planned, "Embedded")
    for key in ("x_scale", "N_w_te1", "N_w_te2", "frequency_Hz"):
        require(number(m[key], key) == number(internal[key], key), "MAT scalar differs from embedded manifest")
    for key in ("outer_solnum", "inner_solnum"):
        actual = number(m[key], key, positive_integer=True)
        require(actual == number(internal[key], key, positive_integer=True) == number(resolved[key], key, positive_integer=True), "Resolved solution index mismatch")
        if requested.get(key) is not None:
            require(actual == number(requested[key], key, positive_integer=True), "Requested solution index mismatch")
    xyz = np.asarray(m["xyz_m"])
    require(xyz.dtype.kind in "iuf" and xyz.ndim == 2 and xyz.shape[0] == 3 and xyz.shape[1] > 0 and np.isfinite(xyz).all(), "Invalid 3xN coordinates")
    n = xyz.shape[1]
    require(number(reported["n_points"], "point count", positive_integer=True) == n, "Reported point count mismatch")
    for axis, name in enumerate(("x_m", "y_m", "z_m")):
        require(np.array_equal(vector(m[name], n, name), xyz[axis]), "Coordinate aliases disagree")
    pressure = vector(m["p_total_Pa"], n, "pressure", complex_allowed=True).astype(complex)
    mask = vector(m["p_finite_mask"], n, "finite mask")
    require(np.isin(mask, [0, 1]).all(), "Nonboolean field mask")
    mask = mask.astype(bool)
    require(np.array_equal(mask, np.isfinite(pressure.real) & np.isfinite(pressure.imag)) and mask.any(), "Pressure finite mask mismatch")
    require(number(reported["n_finite_pressure"], "finite count", positive_integer=True) == int(mask.sum()), "Finite count mismatch")
    dom = vector(m["dom"], n, "dom").astype(float)
    geometric = np.isfinite(dom)  # 绝不使用压力mask决定条件几何点。
    require(geometric.any() and ((dom[geometric] >= 1) & (dom[geometric] == np.floor(dom[geometric]))).all(), "Domain IDs must be positive integers where finite")
    require(geometric[mask].all(), "Valid pressure row lacks aligned domain ID")
    units = struct(m["units"], "units")
    require(all(text(units[k], k) == v for k, v in {"coordinates": "m", "pressure": "Pa", "frequency": "Hz"}.items()), "Incorrect physical units")
    point = scalar(m["p_point_stored_solution_Pa"], "exact point pressure")
    require(isinstance(point, (float, int, complex)) and np.isfinite(point), "Nonfinite exact-point solution")
    reference = struct(m["point_reference"], "point_reference")
    require(np.array_equal(vector(reference["xyz_m"], 3, "observation"), OBSERVATION), "Exact observation coordinate mismatch")
    for key, expected in {"source_type": "scalar_table_reference_not_field_node", "table_hash_verification": "manifest_declared_not_recomputed"}.items():
        require(text(reference[key], key) == expected, "Point source metadata mismatch")
    flag(reference["pressure_consistent_with_stored_solution"], True, "point consistency")
    flag(reference["same_source_model_verified"], False, "point source identity")
    require(number(reference["comparison_rtol"], "rtol") == 1e-6 and number(reference["comparison_atol_Pa"], "atol") == 1e-9, "Unexpected point tolerance")
    require(digest(reference["source_table_sha256"], "point source table") == planned["source_table_sha256"], "Point reference source hash mismatch")
    require(number(reference["source_table_row_1based"], "point row", positive_integer=True) == planned["source_table_row_1based"], "Point reference row mismatch")
    real, imag = number(reference["p_real_Pa"], "point real"), number(reference["p_imag_Pa"], "point imag")
    require(real == planned["p_point_real_Pa"] and imag == planned["p_point_imag_Pa"], "Point reference differs from frozen plan")
    delta = abs(point - complex(real, imag))
    require(delta <= 1e-9 + 1e-6 * abs(complex(real, imag)), "Exact-point complex pressure mismatch")
    arrays = {
        "condition_points": np.column_stack((xyz[:, geometric].T, dom[geometric])),
        "context": np.array([planned[k] for k in ("x_scale", "N_w_te1", "N_w_te2", "frequency_Hz")], dtype=float),
        "query_xyz_m": xyz.T, "target_pressure_ri_Pa": np.column_stack((pressure.real, pressure.imag)),
        "loss_mask": mask, "exact_query_xyz_m": OBSERVATION[None, :],
        "exact_pressure_ri_Pa": np.array([[complex(point).real, complex(point).imag]]),
    }
    details = {"n_query_points": n, "n_condition_points": int(geometric.sum()), "n_finite_pressure": int(mask.sum()),
               "n_condition_points_without_finite_pressure": int(np.sum(geometric & ~mask)), "exact_point_absolute_difference_Pa": float(delta),
               "condition_selection": "finite_xyz_and_positive_integer_dom_independent_of_pressure_mask"}
    return arrays, details


def validate_export_directory(directory, planned):
    directory = Path(directory).resolve()
    paths = {name: directory / name for name in ("export_report.json", "manifest.json", "resolved_index.json", "model_definition_context.mat")}
    require(all(p.is_file() for p in paths.values()), "Recovered export needs report, original manifest.json, resolved_index and model_definition_context")
    hashes = {name: sha256(path) for name, path in paths.items()}
    report, manifest, resolved = (read_json(paths[name]) for name in ("export_report.json", "manifest.json", "resolved_index.json"))
    require(report.get("schema") == "memsharness.pmut_f1_operator_export/v0" and report.get("status") == "complete", "Operator export is not complete")
    require(report.get("dataset") == "dset3" and report.get("field_expression") == "acpr.p_t", "Export target mismatch")
    flag(report.get("source_unchanged"), True, "source_unchanged")
    require(stamp(report.get("source_before")) == stamp(report.get("source_after")), "Source stamp changed")
    for key in ("training_ready", "release_allowed", "point_reference_same_model_verified"):
        flag(report.get(key), False, key)
    require(report.get("mode_identity") == "unverified", "Unexpected export mode certification")
    source_hash = digest(report["source_model_sha256"], "source model")
    require(digest(report["manifest_sha256"], "manifest") == hashes["manifest.json"], "Original manifest byte hash mismatch")
    require(digest(report["resolved_index_sha256"], "resolved index") == hashes["resolved_index.json"], "Resolved index hash mismatch")
    context = report.get("model_definition_context", {})
    reported_basename(context.get("file"), "model_definition_context.mat")
    require(digest(context["sha256"], "definition context") == hashes["model_definition_context.mat"], "Definition context hash mismatch")
    flag(context.get("outer_binding_verified"), False, "definition context outer binding")
    require(manifest.get("schema") in ("memsharness.pmut_f1_operator_export_manifest/v0", "memsharness.pmut_f1_export_manifest/v0")
            and manifest.get("dataset") == "dset3" and manifest.get("field_expression") == "acpr.p_t"
            and manifest.get("observation_xyz_m") == OBSERVATION.tolist(), "Original export manifest mismatch")
    expected_source = manifest.get("expected_source_model_sha256")
    if expected_source is not None:
        require(digest(expected_source, "manifest expected source") == source_hash == digest(report["expected_source_model_sha256"], "report expected source"), "Expected source hash mismatch")
        flag(report.get("expected_source_hash_verified"), True, "expected source hash")
        require(report.get("source_hash_verification") == "computed_and_expected_hash_matched", "Expected source hash not verified")
    else:
        flag(report.get("expected_source_hash_verified"), False, "unexpected expected source hash")
        require(report.get("source_hash_verification") == "computed_from_file_bytes", "Source hash was not computed from bytes")
    require(resolved.get("schema") == "memsharness.pmut_f1_resolved_indices/v0" and resolved.get("dataset") == "dset3", "Resolved index schema mismatch")
    flag(resolved.get("source_hash_verified"), True, "resolved source hash")
    flag(resolved.get("training_ready"), False, "resolved training_ready")
    flag(resolved.get("expected_source_hash_verified"), expected_source is not None, "resolved expected source hash")
    require(resolved.get("source_model") == report.get("source_model") and digest(resolved["source_model_sha256"], "resolved source") == source_hash
            and digest(resolved["manifest_sha256"], "resolved manifest") == hashes["manifest.json"], "Resolved index provenance mismatch")
    requested, actual, indices = (indexed_cases(value, label) for value, label in ((manifest.get("cases"), "manifest"), (report.get("cases"), "report"), (resolved.get("cases"), "resolved")))
    require(set(requested) == set(actual) == set(indices), "Export/manifest/index case sets differ")
    require(set(requested) <= set(planned), "Export contains designs outside frozen plan")
    require(number(report.get("requested"), "requested", positive_integer=True) == number(report.get("completed"), "completed", positive_integer=True) == len(actual), "Export completion count mismatch")
    extra_mat = {"model_definition_context.mat"}
    if manifest.get("resolve_solution_indices") is True:
        raw = resolved.get("raw_solution_map", {})
        reported_basename(raw.get("file"), "solution_map_raw.mat")
        paths["solution_map_raw.mat"] = directory / "solution_map_raw.mat"
        require(paths["solution_map_raw.mat"].is_file(), "Missing raw solution map evidence")
        hashes["solution_map_raw.mat"] = sha256(paths["solution_map_raw.mat"])
        require(digest(raw["sha256"], "raw solution map") == hashes["solution_map_raw.mat"], "Raw solution map hash mismatch")
        extra_mat.add("solution_map_raw.mat")
    require({p.name for p in directory.glob("*.mat")} == {cid + ".mat" for cid in actual} | extra_mat, "Unexpected/missing MAT artifact set")
    result = []
    for cid in sorted(requested):
        case, req, idx, rep = planned[cid], requested[cid], indices[cid], actual[cid]
        check_case_values(req, case, "Requested")
        # resolved_index保存参数/频率和表哈希，原表行号仍由manifest/point_reference核验。
        for key in ("x_scale", "N_w_te1", "N_w_te2", "frequency_Hz"):
            require(number(idx[key], key) == number(req[key], key), "Resolved parameter/frequency mismatch")
        require(digest(idx["source_table_sha256"], "resolved table") == case["source_table_sha256"], "Resolved source table mismatch")
        for key in ("parameter_frequency_readback_verified", "exact_point_pressure_verified"):
            flag(idx.get(key), True, key)
        for key in ("point_reference_pressure_consistent", "dom_available"):
            flag(rep.get(key), True, key)
        for key in ("physics_inputs_complete", "training_ready"):
            flag(rep.get(key), False, key)
        require(rep.get("mode_identity") == "unverified", "Reported mode identity mismatch")
        filename = reported_basename(rep.get("file"), cid + ".mat")
        path = directory / filename
        require(sha256(path) == digest(rep["sha256"], "snapshot"), "Snapshot SHA256 mismatch")
        if case.get("source_hash_verified") is True:
            require(case.get("source_model_sha256") == source_hash, "Verified frozen source hash changed")
        arrays, details = validate_sample(path, case, req, idx, rep, report, hashes["model_definition_context.mat"])
        details.update(case_id=cid, source_model_sha256=source_hash, export_directory=str(directory),
                       source_mat_sha256=rep["sha256"], export_manifest_sha256=hashes["manifest.json"],
                       export_report_sha256=hashes["export_report.json"], original_source_rehashed_locally=False)
        result.append((case, arrays, details))
    require(all(sha256(paths[name]) == expected for name, expected in hashes.items()), "Export metadata changed during intake")
    return result, {"directory": str(directory), "files": hashes, "source_model_sha256": source_hash,
                    "n_cases": len(result), "source_model_rehashed_locally": False}


def prepare_operator_data(plan_path, export_dirs, output_dir, *, split_policy="branch_holdout"):
    """只转换通过完整性验收的真值；不写源文件，所有新输出排他创建。"""
    plan_path, output_dir = Path(plan_path).resolve(), Path(output_dir).resolve()
    require(not output_dir.exists(), "Output directory must be new (append-only)")
    plan_hash = sha256(plan_path)
    plan, planned = validate_plan(plan_path, split_policy)
    require(bool(export_dirs), "At least one complete export directory required")
    seen, converted, evidence, excluded = set(), [], [], []
    for directory in export_dirs:
        validated, source = validate_export_directory(directory, planned)
        evidence.append(source)
        for case, arrays, details in validated:
            cid = case["case_id"]
            require(cid not in seen, "Duplicate case across export directories")
            seen.add(cid)
            if case["N_w_te2"] == 9 or case.get("training_eligibility") == "lineage_quarantine" or case.get("lineage_alignment_pending") is True or case["selection"].get("lineage_quarantine"):
                excluded.append({"case_id": cid, "reason": "lineage_quarantine_not_cleared_by_adapter"})
                continue
            converted.append((case, arrays, details))
    require(bool(converted), "No non-quarantined cases available")
    pending = [cid for cid in sorted(planned) if cid not in seen]
    manifest = {"schema": DATASET_SCHEMA, "split_policy": split_policy,
        "condition_features": [{"name": name, "unit": "m" if name != "domain_id" else "1"} for name in ("x_m", "y_m", "z_m", "domain_id")],
        "context_features": [{"name": name, "unit": "Hz" if name == "frequency_Hz" else "1"} for name in ("x_scale", "N_w_te1", "N_w_te2", "frequency_Hz")],
        "cases": [], "plan_sha256": plan_hash, "source_exports": evidence, "excluded_case_ids": [c["case_id"] for c in excluded],
        "missing_selected_case_ids": pending, "training_ready": False, "release_allowed": False,
        "holdout_caveat": plan.get("holdout_caveat", "reserved_field_holdout_not_blind_scalar_or_cross_model_validation")}
    for case, arrays, details in converted:
        manifest["cases"].append({"case_id": case["case_id"], "design_id": case["design_id"], "branch_id": case["branch_id"],
            "split": case["selection"]["training_splits"][split_policy], "npz": case["case_id"] + ".npz",
            "source_type": "simulation", "source_model_sha256": details["source_model_sha256"], "frequency_source": "stored_solution_oracle",
            "mode_identity": "unverified", "physics_evidence": {kind: False for kind in REQUIRED_PHYSICS},
            "input_provenance": "saved_solution_evaluation_geometry", "domain_semantics": "unverified",
            "training_eligibility": "research_only_missing_physics", "previously_exposed": case["selection"].get("previously_exposed", False),
            "source_evidence": details})
    validate_splits(manifest["cases"], split_policy)
    require(sha256(plan_path) == plan_hash, "Frozen plan changed during intake")
    output_dir.mkdir(parents=True, exist_ok=False)
    for entry, (_, arrays, _) in zip(manifest["cases"], converted):
        path = output_dir / entry["npz"]
        with path.open("xb") as handle:
            np.savez_compressed(handle, **arrays)
        entry["sha256"] = sha256(path)
    write_new_json(output_dir / "dataset.json", manifest)
    audit = dataset_audit(load_dataset(output_dir / "dataset.json", research_only=True))
    audit.update(intake_passed=True, export_integrity_verified=True, exact_point_consistency_verified=True,
                 n_excluded=len(excluded), excluded=excluded, n_missing_selected=len(pending),
                 physical_mapping_verified=False, domain_ids_verified_as_geometric_integers_only=True,
                 source_model_rehashed_locally=False, source_table_rehashed_locally=False,
                 no_interpolation=True, no_comsol_solve=True, plan_sha256=plan_hash)
    write_new_json(output_dir / "intake_audit.json", audit)
    hashes = {path.name: sha256(path) for path in output_dir.iterdir() if path.is_file()}
    write_new_json(output_dir / "file_hashes.json", hashes)
    return audit
