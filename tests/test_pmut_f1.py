from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from memsharness.pmut_f1 import (
    PmutF1ContractError,
    build_validation_handoff,
    coverage_summary,
    load_contract,
    validate_design_point,
)


def test_frozen_observation_and_full_grid_counts():
    contract = load_contract()
    status = coverage_summary(contract)
    assert status["observation"]["side"] == "below"
    assert status["observation"]["xyz_m"] == [0.0, 0.0, -1e-5]
    grid = status["validation_grid"]
    assert grid["n_x"] == 81
    assert grid["n_discrete_branches"] == 30
    assert grid["n_designs_total"] == 2430
    assert grid["n_scalar_spectrum_registered"] == 1782
    assert grid["n_scalar_spectrum_missing"] == 648
    assert status["first_peak"]["n_found"] == 1612
    assert status["first_peak"]["n_not_found_in_registered_window"] == 170
    policy = status["modeling_policy"]
    assert policy["primary_model_family"] == "geometry_conditioned_neural_operator"
    assert policy["interpolation_as_solver"] == "forbidden"
    assert policy["zero_shot_release"] == "forbidden_without_independent_validation"
    assert status["data_preparation_audit"]["n_raw_designs"] == 2430
    assert status["additional_raw_scalar_data"]["merge_with_legacy_C_allowed"] is False


def test_n2_9_raw_data_exists_but_is_not_merged_or_released():
    result = validate_design_point(0.6, 4, 9)
    assert result["in_domain"] is True
    assert result["scalar_spectrum_registered"] is False
    assert result["additional_raw_spectrum_registered"] is True
    assert result["raw_spectrum_registered"] is True
    assert result["lineage_alignment_pending"] is True
    assert result["first_mode_operator_dataset_ready"] is False
    assert result["release_allowed"] is False
    assert result["action"].startswith("verify_additional_raw_source")


def test_existing_scalar_branch_is_not_mislabeled_as_first_mode_field():
    result = validate_design_point(0.6, 4, 8)
    assert result["scalar_spectrum_registered"] is True
    assert result["fixed_20MHz_raw_field_branch_registered"] is True
    assert result["first_mode_operator_dataset_ready"] is False


def test_later_raw_intake_does_not_expand_released_draft_solver():
    result = validate_design_point(0.6, 2, 8)
    assert result["fixed_20MHz_raw_field_branch_registered"] is True
    assert result["fixed_20MHz_released_draft_branch_registered"] is False
    assert result["first_mode_operator_dataset_ready"] is False
    assert result["operator_prediction_available"] is False


def test_n2_9_unmeasured_continuous_point_does_not_inherit_raw_sample():
    result = validate_design_point(0.605, 4, 9)
    assert result["raw_spectrum_registered"] is False
    assert result["additional_raw_spectrum_registered"] is False
    assert result["operator_prediction_available"] is False


@pytest.mark.parametrize(
    "args",
    [
        (0.19, 1, 5),
        (1.01, 1, 5),
        (0.6, 5, 5),
        (0.6, 4.5, 8),
        (0.6, 1, 10),
        (0.6, float("inf"), 8),
        (0.6, 1, float("nan")),
        (0.6, True, 8),
    ],
)
def test_out_of_domain_designs_fail_closed(args):
    with pytest.raises(PmutF1ContractError):
        validate_design_point(*args)


def test_handoff_requires_copy_only_and_exact_point():
    handoff = build_validation_handoff(
        x_scale=0.6,
        n1=4,
        n2=9,
        source_model={"path": r"C:\models\pmut.mph", "sha256": "a" * 64},
        prediction={"model_id": "draft-model", "f1_Hz": None},
    )
    assert handoff["source_model"]["read_only"] is True
    assert handoff["model_write"] == "copy_only"
    assert handoff["observation"]["xyz_m"] == [0.0, 0.0, -1e-5]
    assert handoff["execution"] == "serial_only"
    assert handoff["human_release_required"] is True
    assert handoff["release_allowed"] is False
    assert "write_and_read_back_all_three_parameters" in handoff["required_steps"]


def test_continuous_unmeasured_point_is_not_registered_as_sampled():
    result = validate_design_point(0.605, 4, 8)
    assert result["in_domain"] is True
    assert result["scalar_spectrum_registered"] is False
    assert result["on_registered_x_grid"] is False
    assert result["operator_prediction_available"] is False
    assert result["action"].startswith("consider_sparse_sampling")


def test_recovered_export_qc_does_not_release_or_train_operator():
    summary = coverage_summary()
    submission = summary["stored_field_export_submission"]
    assert submission["n_cases"] == 21
    assert submission["status"] == "recovered_qc_passed"
    assert submission["status_basis"] == "audited_recovered_artifacts_not_live_remote_polling"
    assert submission["new_solve_requested"] is False
    assert submission["production_model_write_requested"] is False
    assert submission["recovered_export_qc_passed"] is True
    assert submission["recovered"] is True
    assert submission["n_recovered_cases"] == submission["n_exact_point_consistency_passed"] == 21
    assert submission["n_domain_labels_available"] == 0
    assert submission["domain_label_status"] == "unavailable_coordinate_mismatch"
    assert submission["recovered_file_count"] == 22
    assert submission["recovered_size_bytes"] == 49068920
    assert submission["qc_scope"] == "recovered_export_integrity_and_exact_point_consistency"
    assert submission["source_model_rehashed_locally"] is False
    assert submission["mode_identity"] == "unverified"
    assert submission["training_ready"] is False
    assert submission["release_allowed"] is False
    assert submission["submission_snapshot"] == {
        "status": "submitted_result_pending",
        "status_basis": "submission_record_not_live_remote_polling",
        "recovered_export_qc_passed": False,
    }
    # 先前盘点记录 append-only：不能将当时未导出的事实改写为成功。
    assert summary["data_preparation_audit"]["full_field_export_executed"] is False
    assert summary["data_preparation_audit"]["n_mode_identity_verified"] == 0
    assert summary["operator_training_status"] == "not_trained"
    assert summary["ready_for_full_loop"] is False
    checked = validate_design_point(0.6, 4, 8)
    assert checked["first_mode_operator_dataset_ready"] is False
    assert checked["operator_prediction_available"] is False
    assert checked["release_allowed"] is False


@pytest.mark.parametrize("export_status", ["submitted_result_pending", "recovered_qc_passed", "unknown_status"])
def test_export_status_alone_never_opens_operator_gate(export_status):
    contract = load_contract()
    contract["stored_field_export_submission"] = {"status": export_status}
    assert coverage_summary(contract)["ready_for_full_loop"] is False
    checked = validate_design_point(0.6, 4, 8, contract)
    assert checked["first_mode_operator_dataset_ready"] is False
    assert checked["operator_prediction_available"] is False
    assert checked["release_allowed"] is False


def test_local_recovered_evidence_matches_registered_hashes_when_present():
    """运行区不进 Git；有原件时验其哈希，缺失时明确跳过，不假称已验收。"""
    repo = Path(__file__).resolve().parents[1]
    submission = load_contract()["stored_field_export_submission"]
    qc_path = repo / submission["qc_report"]
    if not qc_path.is_file():
        pytest.skip("本部署未携带回收证据；合同仅为已审计快照登记")
    assert hashlib.sha256(qc_path.read_bytes()).hexdigest() == submission["qc_report_sha256"]
    qc = json.loads(qc_path.read_text(encoding="utf-8"))
    assert qc["passed"] is True and qc["n_cases"] == submission["n_recovered_cases"]
    assert qc["scope"] == submission["qc_scope"]
    assert qc["training_ready"] is False and qc["release_allowed"] is False
    for artifact, hash_key in (("manifest_path", "manifest_sha256"), ("export_report", "export_report_sha256")):
        assert hashlib.sha256((repo / submission[artifact]).read_bytes()).hexdigest() == submission[hash_key]
        assert qc[hash_key] == submission[hash_key]
    assert qc["source_model_sha256"] == submission["source_model_sha256"]
    recovered = repo / submission["recovered_directory"]
    report = json.loads((repo / submission["export_report"]).read_text(encoding="utf-8"))
    assert report["status"] == "complete" and report["source_unchanged"] is True
    assert report["requested"] == report["completed"] == submission["n_cases"]
    assert report["source_model_sha256"] == submission["source_model_sha256"]
    assert sum(case["dom_available"] is True for case in report["cases"]) == submission["n_domain_labels_available"]
    assert len(list(recovered.glob("*.mat"))) == submission["n_recovered_cases"]
    assert len(list(recovered.iterdir())) == submission["recovered_file_count"]
    assert sum(p.stat().st_size for p in recovered.iterdir()) == submission["recovered_size_bytes"]
    for case in qc["cases"]:
        assert hashlib.sha256((recovered / case["file"]).read_bytes()).hexdigest() == case["sha256"]
        assert case["exact_point_abs_error_Pa"] <= case["exact_point_tolerance_Pa"]
        assert case["mode_identity"] == "unverified" and case["training_ready"] is False


@pytest.mark.parametrize("field,value", [
    ("coordinate_system", "local"), ("side", "above"), ("xyz_m", [0, 0, 1e-5])
])
def test_observation_changes_require_a_new_contract(field, value):
    from memsharness.pmut_f1 import validate_contract
    contract = load_contract()
    contract["objective"]["observation"][field] = value
    with pytest.raises(PmutF1ContractError):
        validate_contract(contract)
