"""只用合成MAT验证取证适配；不冒充真实COMSOL结果、不启动训练。"""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

from memsharness.pmut_f1_operator_data import prepare_operator_data, validate_export_directory, validate_plan
from memsharness.pmut_pressure_operator import OperatorDataError, load_dataset, sha256

ROOT = Path(__file__).resolve().parents[1]


def save_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def bundle():
    temporary = ROOT / "work" / ".test-tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary, prefix="operator-intake-") as folder:
        base = Path(folder)
        export = base / "export"
        export.mkdir()
        cases = []
        for i, (x, n1, n2, split) in enumerate(((.3, 1, 5, "train"), (.4, 2, 5, "validation"), (.5, 3, 5, "test"), (.6, 1, 9, "train"))):
            cid = "x%03d_N1%d_N2%d" % (round(x * 100), n1, n2)
            bid = "N1%d_N2%d" % (n1, n2)
            legacy = "dev" if split == "validation" else split
            cases.append({"case_id": cid, "design_id": cid, "geometry_id": cid, "branch_id": bid,
                "x_scale": x, "N_w_te1": n1, "N_w_te2": n2, "frequency_Hz": 10e6 + i * 5e5,
                "source_table_sha256": "a" * 64, "source_table_row_1based": 20 + i,
                "p_point_real_Pa": 3., "p_point_imag_Pa": 4., "mode_identity": "unverified",
                "source_hash_verified": False, "outer_solnum": None, "inner_solnum": None,
                "training_eligibility": "lineage_quarantine" if n2 == 9 else "pending_physics_and_field",
                "selection": {"case_id": cid, "design_id": cid, "branch_id": bid,
                    "training_splits": {"branch_holdout": split, "design_holdout": split},
                    "splits": {"branch_holdout": legacy, "parameter_holdout": legacy},
                    "previously_exposed": False, "lineage_quarantine": n2 == 9}})
        plan = {"schema": "memsharness.pmut_f1_sparse_plan/v0", "dataset": "dset3", "field_expression": "acpr.p_t",
                "observation_xyz_m": [0, 0, -1e-5], "n_selected": len(cases), "cases": copy.deepcopy(cases)}
        plan_path = base / "plan.json"
        save_json(plan_path, plan)
        manifest = {"schema": "memsharness.pmut_f1_operator_export_manifest/v0", "dataset": "dset3", "field_expression": "acpr.p_t",
                    "observation_xyz_m": [0, 0, -1e-5], "resolve_solution_indices": True,
                    "expected_source_model_sha256": "b" * 64, "cases": copy.deepcopy(cases)}
        save_json(export / "manifest.json", manifest)
        manifest_hash = sha256(export / "manifest.json")
        savemat(export / "model_definition_context.mat", {"context": {"available": False, "outer_binding_verified": False}})
        context_hash = sha256(export / "model_definition_context.mat")
        savemat(export / "solution_map_raw.mat", {"schema": "memsharness.pmut_f1_solution_map_evidence/v0", "synthetic": True})
        raw_hash = sha256(export / "solution_map_raw.mat")
        resolved = {"schema": "memsharness.pmut_f1_resolved_indices/v0", "dataset": "dset3", "source_model": "/synthetic/model.mph",
            "source_model_sha256": "b" * 64, "source_hash_verified": True, "expected_source_hash_verified": True,
            "manifest_sha256": manifest_hash, "training_ready": False,
            "raw_solution_map": {"file": "/remote/out/solution_map_raw.mat", "sha256": raw_hash}, "cases": []}
        report = {"schema": "memsharness.pmut_f1_operator_export/v0", "status": "complete", "dataset": "dset3", "field_expression": "acpr.p_t",
            "requested": len(cases), "completed": len(cases), "source_model": "/synthetic/model.mph", "source_model_sha256": "b" * 64,
            "source_hash_verification": "computed_and_expected_hash_matched", "expected_source_model_sha256": "b" * 64, "expected_source_hash_verified": True,
            "manifest_sha256": manifest_hash, "source_unchanged": True,
            "source_before": {"size_bytes": 123, "mtime_millis": 456}, "source_after": {"size_bytes": 123, "mtime_millis": 456},
            "training_ready": False, "release_allowed": False, "mode_identity": "unverified", "point_reference_same_model_verified": False,
            "model_definition_context": {"file": "/remote/out/model_definition_context.mat", "sha256": context_hash, "outer_binding_verified": False}, "cases": []}
        samples = {}
        xyz = np.array([[0, 1e-6, 2e-6, 3e-6], [0, 0, 0, 0], [-2e-5, -2e-5, -2e-5, -2e-5]])
        for i, case in enumerate(cases):
            cid = case["case_id"]
            selected = {key: case[key] for key in ("case_id", "x_scale", "N_w_te1", "N_w_te2", "frequency_Hz", "source_table_sha256", "source_table_row_1based", "p_point_real_Pa", "p_point_imag_Pa")}
            selected.update(outer_solnum=i+1, inner_solnum=11, mode_identity="unverified")
            resolved["cases"].append({**selected, "parameter_frequency_readback_verified": True, "exact_point_pressure_verified": True})
            sample = {key: selected[key] for key in ("case_id", "x_scale", "N_w_te1", "N_w_te2", "frequency_Hz", "outer_solnum", "inner_solnum")}
            sample.update(schema="memsharness.pmut_f1_operator_field/v0", case_manifest=selected,
                xyz_m=xyz.copy(), x_m=xyz[0].copy(), y_m=xyz[1].copy(), z_m=xyz[2].copy(),
                p_total_Pa=np.array([100+200j, 2+1j, np.nan+0j, np.nan+0j]), p_finite_mask=np.array([1, 1, 0, 0], dtype=np.uint8),
                dom_available=True, dom=np.array([1, 1, 2, np.nan]), dom_alignment="same_eval_columns_not_nearest_neighbor",
                source_type="simulation", source_model=report["source_model"], source_model_sha256="b"*64,
                source_hash_verification="computed_and_expected_hash_matched", expected_source_hash_verified=True,
                source_dataset="dset3", canonical_expression="acpr.p_t", manifest_sha256=manifest_hash,
                definition_context_sha256=context_hash, definition_context_outer_binding_verified=False,
                solution_identity_verified=True, solution_identity_verification_scope="requested_parameters_frequency_and_point_pressure_not_physics_equivalence",
                training_ready=False, release_allowed=False, physics_inputs_complete=False, geometry_material_bc_exported=False, mode_identity="unverified",
                point_evaluation_method="stored_finite_element_solution_at_exact_coordinate_ext0", p_point_stored_solution_Pa=3+4j,
                point_reference_pressure_consistent=True, units={"coordinates": "m", "pressure": "Pa", "frequency": "Hz"},
                displacement={"values": np.array([999])},
                point_reference={"xyz_m": [0, 0, -1e-5], "p_real_Pa": 3., "p_imag_Pa": 4.,
                    "source_type": "scalar_table_reference_not_field_node", "source_table_sha256": "a"*64,
                    "source_table_row_1based": selected["source_table_row_1based"], "table_hash_verification": "manifest_declared_not_recomputed",
                    "pressure_consistent_with_stored_solution": True, "same_source_model_verified": False,
                    "comparison_rtol": 1e-6, "comparison_atol_Pa": 1e-9})
            samples[cid] = sample
            path = export / (cid + ".mat")
            savemat(path, sample, long_field_names=True)
            report["cases"].append({"case_id": cid, "file": "/remote/out/" + path.name, "sha256": sha256(path),
                "n_points": 4, "n_finite_pressure": 2, "point_reference_pressure_consistent": True, "dom_available": True,
                "physics_inputs_complete": False, "training_ready": False, "mode_identity": "unverified"})
        save_json(export / "resolved_index.json", resolved)
        report["resolved_index_sha256"] = sha256(export / "resolved_index.json")
        save_json(export / "export_report.json", report)
        yield {"base": base, "export": export, "plan": plan, "plan_path": plan_path, "manifest": manifest,
               "report": report, "resolved": resolved, "samples": samples}


def rewrite_sample(bundle, mutation):
    cid = bundle["plan"]["cases"][0]["case_id"]
    mutation(bundle["samples"][cid])
    path = bundle["export"] / (cid + ".mat")
    savemat(path, bundle["samples"][cid], long_field_names=True)
    bundle["report"]["cases"][0]["sha256"] = sha256(path)
    save_json(bundle["export"] / "export_report.json", bundle["report"])


def test_research_conversion_preserves_all_geometry_not_pressure_mask(bundle):
    output = bundle["base"] / "prepared"
    audit = prepare_operator_data(bundle["plan_path"], [bundle["export"]], output)
    assert audit["n_designs"] == 3 and audit["n_excluded"] == 1
    assert audit["designs_by_split"] == {"train": 1, "validation": 1, "test": 1}
    assert audit["exact_point_consistency_verified"] and not audit["physical_mapping_verified"]
    assert not audit["training_ready"] and not audit["release_allowed"]
    dataset = load_dataset(output / "dataset.json", research_only=True)
    case = dataset.cases[0]
    assert case.condition_points.shape == (3, 4)  # 第三个点的pressure为NaN，但几何/dom有效。
    assert case.condition_points[2, -1] == 2
    assert case.query_xyz_m.shape == (4, 3) and case.loss_mask.tolist() == [True, True, False, False]
    assert np.array_equal(case.exact_pressure_ri_Pa, [[3, 4]])
    assert case.metadata["input_provenance"] == "saved_solution_evaluation_geometry"
    assert case.metadata["domain_semantics"] == "unverified"
    assert not any(case.metadata["physics_evidence"].values())
    assert "missing_verified_physics_boundary" in audit["blockers"]
    assert "inference_geometry_pipeline_unverified" in audit["blockers"]
    with pytest.raises(OperatorDataError, match="Production training refused"):
        load_dataset(output / "dataset.json")
    with pytest.raises(OperatorDataError, match="append-only"):
        prepare_operator_data(bundle["plan_path"], [bundle["export"]], output)


@pytest.mark.parametrize("fault", ["incomplete", "count", "source_changed", "source_flag", "manifest_sha", "resolved_sha", "context_sha", "raw_sha", "expected_source", "duplicate_report", "unsafe_path", "extra_mat", "missing_manifest"])
def test_report_and_byte_integrity_refusal(bundle, fault):
    r, root = bundle["report"], bundle["export"]
    if fault == "incomplete": r["status"] = "running"
    elif fault == "count": r["completed"] -= 1
    elif fault == "source_changed": r["source_after"]["mtime_millis"] += 1
    elif fault == "source_flag": r["source_unchanged"] = False
    elif fault == "manifest_sha": r["manifest_sha256"] = "c" * 64
    elif fault == "resolved_sha": r["resolved_index_sha256"] = "c" * 64
    elif fault == "context_sha": r["model_definition_context"]["sha256"] = "c" * 64
    elif fault == "raw_sha": (root / "solution_map_raw.mat").write_bytes(b"tampered")
    elif fault == "expected_source": r["expected_source_model_sha256"] = "c" * 64
    elif fault == "duplicate_report": r["cases"][1] = copy.deepcopy(r["cases"][0])
    elif fault == "unsafe_path": r["cases"][0]["file"] = "/remote/../" + r["cases"][0]["case_id"] + ".mat"
    elif fault == "extra_mat": (root / "stale.mat").write_bytes(b"stale")
    elif fault == "missing_manifest": (root / "manifest.json").unlink()
    save_json(root / "export_report.json", r)
    with pytest.raises(OperatorDataError):
        prepare_operator_data(bundle["plan_path"], [root], bundle["base"] / "rejected")
    assert not (bundle["base"] / "rejected").exists()


@pytest.mark.parametrize("fault", ["field_source", "freq", "index", "identity", "domain_alignment", "noninteger_domain", "domain_missing", "mask", "coords", "point_phase", "point_coord", "point_source", "point_tolerance", "units", "mode", "fake_physics"])
def test_sample_refusals_even_when_file_hash_updated(bundle, fault):
    def change(m):
        if fault == "field_source": m["source_model_sha256"] = "c" * 64
        elif fault == "freq": m["frequency_Hz"] += 1e6
        elif fault == "index": m["inner_solnum"] += 1
        elif fault == "identity": m["solution_identity_verified"] = False
        elif fault == "domain_alignment": m["dom_alignment"] = "nearest_neighbor"
        elif fault == "noninteger_domain": m["dom"][2] = 2.5  # 非声压有效点同样不能造几何ID。
        elif fault == "domain_missing": m["dom"][0] = np.nan
        elif fault == "mask": m["p_finite_mask"][2] = 1
        elif fault == "coords": m["x_m"][0] = 1e-3
        elif fault == "point_phase": m["p_point_stored_solution_Pa"] = -3-4j
        elif fault == "point_coord": m["point_reference"]["xyz_m"] = [0, 0, 1e-5]
        elif fault == "point_source": m["point_reference"]["source_table_sha256"] = "c" * 64
        elif fault == "point_tolerance": m["point_reference"]["comparison_rtol"] = 1.
        elif fault == "units": m["units"]["coordinates"] = "um"
        elif fault == "mode": m["mode_identity"] = "verified_first_mode"
        else: m["physics_inputs_complete"] = True
    rewrite_sample(bundle, change)
    with pytest.raises(OperatorDataError):
        prepare_operator_data(bundle["plan_path"], [bundle["export"]], bundle["base"] / "rejected")


def test_plan_splits_are_frozen_not_reassigned(bundle):
    bundle["plan"]["cases"][0]["selection"]["training_splits"]["branch_holdout"] = "test"
    save_json(bundle["plan_path"], bundle["plan"])
    with pytest.raises(OperatorDataError, match="Frozen split mapping"):
        prepare_operator_data(bundle["plan_path"], [bundle["export"]], bundle["base"] / "rejected")


def test_exposed_data_cannot_enter_test(bundle):
    bundle["plan"]["cases"][2]["selection"]["previously_exposed"] = True
    save_json(bundle["plan_path"], bundle["plan"])
    with pytest.raises(OperatorDataError, match="Previously exposed"):
        prepare_operator_data(bundle["plan_path"], [bundle["export"]], bundle["base"] / "rejected")


def test_duplicate_exports_not_silently_deduplicated(bundle):
    with pytest.raises(OperatorDataError, match="Duplicate case across"):
        prepare_operator_data(bundle["plan_path"], [bundle["export"], bundle["export"]], bundle["base"] / "rejected")


def test_resolved_readback_identity_must_be_true(bundle):
    bundle["resolved"]["cases"][0]["parameter_frequency_readback_verified"] = False
    path = bundle["export"] / "resolved_index.json"
    save_json(path, bundle["resolved"])
    bundle["report"]["resolved_index_sha256"] = sha256(path)
    save_json(bundle["export"] / "export_report.json", bundle["report"])
    with pytest.raises(OperatorDataError, match="parameter_frequency_readback"):
        prepare_operator_data(bundle["plan_path"], [bundle["export"]], bundle["base"] / "rejected")


def test_design_holdout_uses_plan_design_labels(bundle):
    audit = prepare_operator_data(bundle["plan_path"], [bundle["export"]], bundle["base"] / "design", split_policy="design_holdout")
    assert audit["split_policy"] == "design_holdout"
    assert audit["cross_model_transfer_verified"] is False
