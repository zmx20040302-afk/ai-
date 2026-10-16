from __future__ import annotations

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


def test_remote_submission_is_not_completed_operator_evidence():
    summary = coverage_summary()
    submission = summary["stored_field_export_submission"]
    assert submission["n_cases"] == 21
    assert submission["status"] == "submitted_result_pending"
    assert submission["status_basis"] == "submission_record_not_live_remote_polling"
    assert submission["new_solve_requested"] is False
    assert submission["production_model_write_requested"] is False
    assert submission["recovered_export_qc_passed"] is False
    assert submission["training_ready"] is False
    assert summary["ready_for_full_loop"] is False


@pytest.mark.parametrize("field,value", [
    ("coordinate_system", "local"), ("side", "above"), ("xyz_m", [0, 0, 1e-5])
])
def test_observation_changes_require_a_new_contract(field, value):
    from memsharness.pmut_f1 import validate_contract
    contract = load_contract()
    contract["objective"]["observation"][field] = value
    with pytest.raises(PmutF1ContractError):
        validate_contract(contract)
