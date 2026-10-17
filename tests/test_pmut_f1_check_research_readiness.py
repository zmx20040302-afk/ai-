"""合成124例契约验证；固定生产SHA只在测试进程内替换，不产生训练或物理证据。"""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pytest

from memsharness.pmut_pressure_operator import DATASET_SCHEMA, sha256

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pmut_readiness_under_test", ROOT / "scripts/pmut_f1_check_research_readiness.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_production_hashes_are_fixed_not_cli_overridable():
    assert gate.EXPECTED_PLAN_SHA256 == "749efd9c394f59a90da304911dfbd0c80f09fe98dbda1ad7514e5ce67da7b2c3"
    assert gate.EXPECTED_PROTOCOL_SHA256 == "7ea7b9879588b4a9f320816a82359f97e29acae3ba13a8ebc23288fb071b7833"
    assert gate.EXPECTED_DESIGNS == 124
    assert gate.EXPECTED_EXPOSED == 21


@pytest.fixture
def bundle(monkeypatch):
    temporary = ROOT / "work" / ".test-tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary, prefix="readiness-") as folder:
        root = Path(folder)
        plan = {"schema": "memsharness.pmut_f1_sparse_plan/v0", "dataset": "dset3", "field_expression": "acpr.p_t",
                "observation_xyz_m": [0., 0., -1e-5], "cases": []}
        manifest = {"schema": DATASET_SCHEMA, "split_policy": "branch_holdout", "training_ready": False, "release_allowed": False,
            "condition_features": [{"name": n, "unit": "1" if n == "domain_id" else "m"} for n in ("x_m", "y_m", "z_m", "domain_id")],
            "context_features": [{"name": n, "unit": "Hz" if n == "frequency_Hz" else "1"} for n in ("x_scale", "N_w_te1", "N_w_te2", "frequency_Hz")], "cases": []}
        for n2 in range(5, 10):
            for n1 in range(1, n2):
                for i in range(7 if n2 == 8 else 5):
                    x = (30 + i) / 100
                    cid, bid = f"x{30+i:03d}_N1{n1}_N2{n2}", f"N1{n1}_N2{n2}"
                    exposed = n2 == 8 and i < 3
                    split = "validation" if n2 == 8 or n1 == 1 else "test" if n1 == 2 else "train"
                    design_split = "validation" if exposed else ("train", "validation", "test", "train", "train", "train", "train")[i]
                    aliases = lambda value: "dev" if value == "validation" else value
                    case = {"case_id": cid, "design_id": cid, "geometry_id": cid, "branch_id": bid,
                        "x_scale": x, "N_w_te1": n1, "N_w_te2": n2, "frequency_Hz": 1e7+i*5e5,
                        "p_point_real_Pa": 3., "p_point_imag_Pa": 4., "mode_identity": "unverified",
                        "training_eligibility": "lineage_quarantine" if n2 == 9 else "pending_physics_and_field",
                        "selection": {"case_id": cid, "design_id": cid, "branch_id": bid, "previously_exposed": exposed,
                            "lineage_quarantine": n2 == 9, "training_splits": {"branch_holdout": split, "design_holdout": design_split},
                            "splits": {"branch_holdout": aliases(split), "parameter_holdout": aliases(design_split)}}}
                    plan["cases"].append(case)
                    if n2 == 9:
                        continue
                    q = np.array([[0., 0., -2e-5], [1e-5, 0., -2e-5], [2e-5, 0., -2e-5]])
                    arrays = {"condition_points": np.column_stack((q, np.ones(3))),
                        "context": np.array([x, n1, n2, case["frequency_Hz"]]), "query_xyz_m": q,
                        "target_pressure_ri_Pa": np.array([[1., 2.], [2., 1.], [np.nan, np.nan]]),
                        "loss_mask": np.array([True, True, False]), "exact_query_xyz_m": np.array([[0., 0., -1e-5]]),
                        "exact_pressure_ri_Pa": np.array([[3., 4.]])}
                    path = root / (cid + ".npz")
                    np.savez(path, **arrays)
                    manifest["cases"].append({"case_id": cid, "design_id": cid, "branch_id": bid, "split": split,
                        "npz": path.name, "sha256": sha256(path), "source_type": "simulation", "source_model_sha256": "%064x" % n2,
                        "frequency_source": "stored_solution_oracle", "mode_identity": "unverified", "physics_evidence": {},
                        "input_provenance": "saved_solution_evaluation_geometry", "domain_semantics": "unverified"})
        plan["n_selected"] = len(plan["cases"])
        plan_path, protocol_path, dataset_path = root / "plan.json", root / "protocol.json", root / "dataset.json"
        save(plan_path, plan)
        protocol = {"schema": "memsharness.pmut_operator_research_protocol/v0", "frozen_plan_sha256": sha256(plan_path),
            "required_accepted_N_w_te2": [5, 6, 7, 8], "required_accepted_designs_for_cross_branch_experiment": 124,
            "training_ready": False, "release_allowed": False, "physics_inputs_complete": False,
            "training": {"research_only": True}, "split_policies": ["branch_holdout", "design_holdout"]}
        save(protocol_path, protocol)
        manifest["plan_sha256"] = sha256(plan_path)
        save(dataset_path, manifest)
        monkeypatch.setattr(gate, "EXPECTED_PLAN_SHA256", sha256(plan_path))
        monkeypatch.setattr(gate, "EXPECTED_PROTOCOL_SHA256", sha256(protocol_path))
        yield {"root": root, "plan": plan, "protocol": protocol, "manifest": manifest,
               "plan_path": plan_path, "protocol_path": protocol_path, "dataset_path": dataset_path}


def check(b):
    return gate.check_readiness(b["plan_path"], b["protocol_path"], b["dataset_path"])


def mutate_npz(b, mutation, index=0):
    case = b["manifest"]["cases"][index]
    path = b["root"] / case["npz"]
    with np.load(path, allow_pickle=False) as original:
        arrays = {key: original[key].copy() for key in original.files}
    mutation(arrays)
    np.savez(path, **arrays)
    case["sha256"] = sha256(path)
    save(b["dataset_path"], b["manifest"])


def test_all_124_ids_and_npz_pass_only_research_completeness(bundle):
    result = check(bundle)
    assert result["research_dataset_complete"]
    assert not result["cross_branch_research_training_blocked"]
    assert result["received_eligible_designs"] == 124
    assert result["missing_eligible_case_ids"] == []
    assert len(result["planned_quarantine_case_ids"]) == 40
    assert result["dataset_file_validation_passed"] and result["frozen_case_binding_passed"]
    for field in ("training_ready", "release_allowed", "physics_inputs_complete", "physical_mapping_verified",
                  "training_executed", "first_mode_identified", "field_error_bound_verified"):
        assert result[field] is False


def test_n2_5_complete_batch_is_not_124_complete(bundle):
    manifest = bundle["manifest"]
    manifest["cases"] = [case for case in manifest["cases"] if case["case_id"].endswith("_N25")]
    manifest.update(intake_passed=True, status="complete", n_designs=124, missing_selected_case_ids=[])
    save(bundle["dataset_path"], manifest)
    result = check(bundle)
    assert not result["research_dataset_complete"] and result["cross_branch_research_training_blocked"]
    assert result["dataset_file_validation_passed"]
    assert result["received_eligible_designs"] == 20
    assert result["missing_eligible_designs"] == len(result["missing_eligible_case_ids"]) == 104
    assert all(not cid.endswith("_N29") for cid in result["missing_eligible_case_ids"])


@pytest.mark.parametrize("which", ["plan_path", "protocol_path"])
def test_exact_frozen_bytes_are_required(bundle, which):
    with bundle[which].open("a", encoding="utf-8") as handle:
        handle.write(" ")
    result = check(bundle)
    assert not result["research_dataset_complete"] and not result["frozen_inputs_valid"]
    assert any("SHA256" in message for message in result["validation_errors"])


def test_124_rows_with_duplicate_and_missing_design_fails(bundle):
    bundle["manifest"]["cases"][1] = copy.deepcopy(bundle["manifest"]["cases"][0])
    save(bundle["dataset_path"], bundle["manifest"])
    result = check(bundle)
    assert result["received_case_rows"] == 124 and result["received_unique_designs"] == 123
    assert len(result["duplicate_case_ids"]) == len(result["missing_eligible_case_ids"]) == 1
    assert not result["research_dataset_complete"]


def test_n2_9_replacement_cannot_complete_population(bundle):
    case = bundle["manifest"]["cases"][-1]
    target = next(c for c in bundle["plan"]["cases"] if c["N_w_te2"] == 9)
    case.update(case_id=target["case_id"], design_id=target["design_id"], branch_id=target["branch_id"], split="validation")
    save(bundle["dataset_path"], bundle["manifest"])
    result = check(bundle)
    assert result["quarantined_included_case_ids"] == [target["case_id"]]
    assert len(result["missing_eligible_case_ids"]) == 1
    assert not result["research_dataset_complete"]


def test_split_changes_cannot_override_frozen_plan(bundle):
    for case in bundle["manifest"]["cases"]:
        if case["branch_id"] == "N13_N25":
            case["split"] = "validation"
    save(bundle["dataset_path"], bundle["manifest"])
    result = check(bundle)
    assert result["dataset_file_validation_passed"]
    assert len(result["split_mismatches"]) == 5
    assert not result["research_dataset_complete"]


def test_old_21_designs_never_enter_test(bundle):
    for case in bundle["manifest"]["cases"]:
        if case["case_id"].endswith("_N28"):
            case["split"] = "test"
    save(bundle["dataset_path"], bundle["manifest"])
    result = check(bundle)
    assert len(result["previously_exposed_in_test"]) == 21
    assert not result["research_dataset_complete"]


@pytest.mark.parametrize("fault", ["context_n2", "context_x", "frequency", "point_phase", "hidden_mask", "nonfinite_label"])
def test_npz_identity_and_masks_bound_to_frozen_case(bundle, fault):
    mutations = {
        "context_n2": lambda a: a["context"].__setitem__(2, 9),
        "context_x": lambda a: a["context"].__setitem__(0, .77),
        "frequency": lambda a: a["context"].__setitem__(3, 88e6),
        "point_phase": lambda a: a["exact_pressure_ri_Pa"].__setitem__(slice(None), [[-3, -4]]),
        "hidden_mask": lambda a: a["loss_mask"].__setitem__(0, False),
        "nonfinite_label": lambda a: a["target_pressure_ri_Pa"].__setitem__((0, 0), np.nan),
    }
    mutate_npz(bundle, mutations[fault])
    result = check(bundle)
    assert not result["research_dataset_complete"]
    assert result["case_binding_errors"] or result["validation_errors"]


def test_npz_tamper_fails_existing_loader_hash_validation(bundle):
    path = bundle["root"] / bundle["manifest"]["cases"][0]["npz"]
    with path.open("ab") as handle:
        handle.write(b"tampered")
    result = check(bundle)
    assert not result["dataset_file_validation_passed"] and not result["research_dataset_complete"]
    assert any("SHA256 mismatch" in message for message in result["validation_errors"])


def test_npz_crc_damage_is_recorded_as_failed_validation(bundle):
    case = bundle["manifest"]["cases"][0]
    path = bundle["root"] / case["npz"]
    with zipfile.ZipFile(path) as archive:
        member = archive.getinfo("condition_points.npy")
    raw = bytearray(path.read_bytes())
    offset = member.header_offset
    filename_length = int.from_bytes(raw[offset + 26:offset + 28], "little")
    extra_length = int.from_bytes(raw[offset + 28:offset + 30], "little")
    data_offset = offset + 30 + filename_length + extra_length
    raw[data_offset + member.compress_size - 1] ^= 1
    path.write_bytes(raw)
    case["sha256"] = sha256(path)
    save(bundle["dataset_path"], bundle["manifest"])
    result = check(bundle)
    assert not result["dataset_file_validation_passed"] and not result["research_dataset_complete"]
    assert any("BadZipFile" in message for message in result["validation_errors"])


def test_development_design_holdout_can_pass_its_own_frozen_policy(bundle):
    plan = {case["case_id"]: case for case in bundle["plan"]["cases"]}
    bundle["manifest"]["split_policy"] = "design_holdout"
    for case in bundle["manifest"]["cases"]:
        case["split"] = plan[case["case_id"]]["selection"]["training_splits"]["design_holdout"]
    save(bundle["dataset_path"], bundle["manifest"])
    assert check(bundle)["research_dataset_complete"]


def test_cli_is_append_only_and_nonzero_for_incomplete_dataset(bundle):
    bundle["manifest"]["cases"] = [case for case in bundle["manifest"]["cases"] if case["case_id"].endswith("_N25")]
    save(bundle["dataset_path"], bundle["manifest"])
    output = bundle["root"] / "readiness.json"
    args = ["--plan", str(bundle["plan_path"]), "--research-protocol", str(bundle["protocol_path"]),
            "--dataset", str(bundle["dataset_path"]), "--output", str(output)]
    assert gate.main(args) == 2
    original = output.read_bytes()
    assert json.loads(original)["missing_eligible_designs"] == 104
    with pytest.raises(FileExistsError, match="new path"):
        gate.main(args)
    assert output.read_bytes() == original


def test_duplicate_manifest_json_keys_are_not_accepted(bundle):
    bundle["dataset_path"].write_text('{"cases": [], "cases": []}', encoding="utf-8")
    result = check(bundle)
    assert not result["research_dataset_complete"]
    assert any("Duplicate JSON key" in value for value in result["validation_errors"])
