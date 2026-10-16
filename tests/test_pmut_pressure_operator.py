from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from memsharness.pmut_pressure_operator import (
    DATASET_SCHEMA, OperatorDataError, TrainNormalization, _case_inputs, build_model,
    complex_metrics, dataset_audit, exact_point_metrics, load_dataset, sha256,
    train_operator, validate_splits, supervision_indices,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixture_dir():
    root = ROOT / "work" / ".test-tmp"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix="pressure-operator-") as folder:
        yield Path(folder)


def make_dataset(folder):
    features = [{"name": n, "unit": "m" if n.endswith("_m") else "1"} for n in ("x_m", "y_m", "z_m", "domain_id")]
    contexts = [{"name": "x_scale", "unit": "1"}, {"name": "frequency_Hz", "unit": "Hz"}]
    manifest = {"schema": DATASET_SCHEMA, "condition_features": features, "context_features": contexts,
                "split_policy": "branch_holdout", "cases": []}
    for i, split in enumerate(("train", "validation", "test")):
        q = np.array([[0, 0, -1e-5], [1e-5, 0, -1e-5], [0, 1e-5, -1e-5], [-1e-5, 0, -1e-5]])
        arrays = {
            "condition_points": np.column_stack([q[:i + 2], np.ones(i + 2)]),
            "context": np.array([.3 + .1 * i, 1e7 + i * 1e6]),
            "query_xyz_m": q,
            "target_pressure_ri_Pa": np.tile([1 + i, 2 + i], (4, 1)).astype(float),
            "loss_mask": np.array([True, True, True, False]),
            "exact_query_xyz_m": q[:1], "exact_pressure_ri_Pa": np.array([[1 + i, 2 + i]], dtype=float),
        }
        arrays["target_pressure_ri_Pa"][-1] = np.nan
        path = folder / f"case{i}.npz"
        np.savez(path, **arrays)
        manifest["cases"].append({"case_id": f"case{i}", "design_id": f"design{i}", "branch_id": f"branch{i}",
            "split": split, "npz": path.name, "sha256": sha256(path), "source_type": "synthetic_test",
            "source_model_sha256": "a" * 64, "frequency_source": "stored_solution_oracle", "mode_identity": "unverified",
            "physics_evidence": {}, "input_provenance": "saved_solution_evaluation_geometry",
            "domain_semantics": "geometric_domain_ids_verified"})
    path = folder / "dataset.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def save_manifest(path, manifest):
    path.write_text(json.dumps(manifest), encoding="utf-8")


def mutate_arrays(path, manifest, index, mutate):
    npz = path.parent / manifest["cases"][index]["npz"]
    with np.load(npz, allow_pickle=False) as stored:
        arrays = {key: stored[key].copy() for key in stored.files}
    mutate(arrays)
    np.savez(npz, **arrays)
    manifest["cases"][index]["sha256"] = sha256(npz)
    save_manifest(path, manifest)


def test_research_gate_does_not_promote_saved_geometry_or_oracle_frequency(fixture_dir):
    path, _ = make_dataset(fixture_dir)
    with pytest.raises(OperatorDataError, match="Production training refused"):
        load_dataset(path)
    dataset = load_dataset(path, research_only=True)
    audit = dataset_audit(dataset)
    assert audit["n_designs"] == 3
    assert not audit["training_ready"] and not audit["release_allowed"]
    assert "inference_geometry_pipeline_unverified" in audit["blockers"]
    assert "missing_verified_physics_material" in audit["blockers"]
    assert "oracle_frequency_not_end_to_end_frequency_prediction" in audit["blockers"]
    assert audit["mode_label"] == "first_observable_peak_research"


@pytest.mark.parametrize("name", ["p_total_Pa", "p_point_real_Pa", "displacement_m", "target_pressure", "pressure", "solution", "loss_mask"])
def test_solution_features_rejected_even_in_research(fixture_dir, name):
    path, manifest = make_dataset(fixture_dir)
    manifest["condition_features"][-1] = {"name": name, "unit": "1"}
    save_manifest(path, manifest)
    with pytest.raises(OperatorDataError, match="Unapproved or solution-derived"):
        load_dataset(path, research_only=True)


@pytest.mark.parametrize("fault", ["hash", "path", "duplicate_design", "branch_leak", "no_test", "quarantine", "nonfinite_input", "integer_domain", "pressure_shape", "target_nan", "mask_type", "wrong_observation", "extra_label_input", "unit"])
def test_bad_inputs_fail_closed(fixture_dir, fault):
    path, manifest = make_dataset(fixture_dir)
    if fault == "hash":
        manifest["cases"][0]["sha256"] = "b" * 64
    elif fault == "path":
        manifest["cases"][0]["npz"] = "../escape.npz"
    elif fault == "duplicate_design":
        manifest["cases"][1]["design_id"] = manifest["cases"][0]["design_id"]
    elif fault == "branch_leak":
        manifest["cases"][1]["branch_id"] = manifest["cases"][0]["branch_id"]
    elif fault == "no_test":
        manifest["cases"][2]["split"] = "validation"
    elif fault == "quarantine":
        manifest["cases"][2]["training_eligibility"] = "lineage_quarantine"
    elif fault == "unit":
        manifest["condition_features"][0]["unit"] = "um"
    else:
        mutations = {
            "nonfinite_input": lambda a: a["condition_points"].__setitem__((0, 0), np.nan),
            "integer_domain": lambda a: a["condition_points"].__setitem__((0, -1), 1.5),
            "pressure_shape": lambda a: a.__setitem__("target_pressure_ri_Pa", np.zeros(4)),
            "target_nan": lambda a: a["target_pressure_ri_Pa"].__setitem__((0, 0), np.nan),
            "mask_type": lambda a: a.__setitem__("loss_mask", np.ones(4, dtype=float)),
            "wrong_observation": lambda a: a["exact_query_xyz_m"].__setitem__((0, 2), 1e-5),
            "extra_label_input": lambda a: a.__setitem__("p_point_as_input", np.array([123])),
        }
        mutate_arrays(path, manifest, 0, mutations[fault])
    save_manifest(path, manifest)
    with pytest.raises(OperatorDataError):
        load_dataset(path, research_only=True)


def test_design_holdout_does_not_pretend_discrete_branch_holdout(fixture_dir):
    path, manifest = make_dataset(fixture_dir)
    manifest["split_policy"] = "design_holdout"
    manifest["cases"][1]["branch_id"] = manifest["cases"][0]["branch_id"]
    save_manifest(path, manifest)
    dataset = load_dataset(path, research_only=True)
    assert dataset_audit(dataset)["split_policy"] == "design_holdout"


@pytest.mark.parametrize("same_path", [True, False])
def test_artifact_aliases_cannot_leak_same_npz_into_holdout(fixture_dir, same_path):
    path, manifest = make_dataset(fixture_dir)
    first, second = manifest["cases"][:2]
    if same_path:
        second["npz"] = first["npz"]
    else:
        (fixture_dir / second["npz"]).write_bytes((fixture_dir / first["npz"]).read_bytes())
    second["sha256"] = first["sha256"]
    save_manifest(path, manifest)
    with pytest.raises(OperatorDataError, match="reused across splits"):
        load_dataset(path, research_only=True)


def test_declared_physics_flags_and_hashes_never_unlock_production(fixture_dir):
    path, manifest = make_dataset(fixture_dir)
    for case in manifest["cases"]:
        case.update(source_type="simulation", frequency_source="prescribed", mode_identity="verified_first_mode",
                    input_provenance="pre_solve_geometry_and_conditions", domain_semantics="unverified")
        case["physics_evidence"] = {name: {"verified": True, "design_id": case["design_id"], "artifact_sha256": "b" * 64}
            for name in ("geometry", "material", "boundary", "excitation", "circuit", "damping", "selection")}
    save_manifest(path, manifest)
    with pytest.raises(OperatorDataError, match="Production training refused"):
        load_dataset(path)
    dataset = load_dataset(path, research_only=True)
    assert "production_physics_evidence_binding_not_implemented" in dataset.blockers
    assert "domain_to_physics_semantics_unverified" in dataset.blockers
    dataset.blockers.clear()  # 即使调用方手工清空列表，也不能走所谓生产训练。
    with pytest.raises(OperatorDataError, match="Production training refused"):
        train_operator(dataset, fixture_dir / "production", research_only=False)


def test_normalization_fits_only_train_and_not_exact_truth(fixture_dir):
    path, _ = make_dataset(fixture_dir)
    dataset = load_dataset(path, research_only=True)
    before = TrainNormalization.fit(dataset.cases)
    dataset.cases[1].condition_points[:] = 1e12
    dataset.cases[2].query_xyz_m[:] = 1e15
    dataset.cases[2].context[:] = 1e20
    dataset.cases[1].target_pressure_ri_Pa[:] = 1e25
    for case in dataset.cases:
        case.exact_pressure_ri_Pa[:] = 1e30
    after = TrainNormalization.fit(dataset.cases)
    assert before.to_dict() == after.to_dict()
    assert after.fitted_design_ids == ["design0"]
    assert after.pressure_scale_Pa == pytest.approx(np.sqrt(5))


def test_labels_masks_and_exact_point_do_not_change_encoded_inputs(fixture_dir):
    path, _ = make_dataset(fixture_dir)
    dataset = load_dataset(path, research_only=True)
    norm = TrainNormalization.fit(dataset.cases)
    case = dataset.cases[0]
    before = _case_inputs(case, norm)
    case.target_pressure_ri_Pa[:] = 12345
    case.exact_pressure_ri_Pa[:] = -6789
    case.loss_mask[:] = False
    after = _case_inputs(case, norm)
    assert all(np.array_equal(a, b) for a, b in zip(before, after))


def test_exact_observation_is_excluded_even_if_field_grid_contains_it(fixture_dir):
    path, _ = make_dataset(fixture_dir)
    dataset = load_dataset(path, research_only=True)
    assert supervision_indices(dataset.cases[0]).tolist() == [1, 2]
    before = TrainNormalization.fit(dataset.cases)
    dataset.cases[0].target_pressure_ri_Pa[0] = 1e30
    after = TrainNormalization.fit(dataset.cases)
    assert before.pressure_scale_Pa == after.pressure_scale_Pa


def test_complex_error_detects_phase_even_with_identical_magnitudes():
    truth = np.array([[1, 0], [0, 1]])
    predicted = -truth
    metrics = complex_metrics(predicted, truth)
    assert metrics["relative_complex_l2"] == pytest.approx(2)
    assert metrics["norm_definition"] == "pointwise_relative_complex_l2"
    point = exact_point_metrics(predicted[:1], truth[:1])
    assert point["amplitude_relative_error"] == 0
    assert point["phase_absolute_error_rad"] == pytest.approx(np.pi)


def test_zero_pressure_norm_is_undefined_not_silently_zero_error():
    metrics = complex_metrics(np.array([[1., 0.]]), np.zeros((1, 2)))
    assert metrics["relative_complex_l2"] is None and metrics["zero_truth_norm"]
    assert metrics["complex_rmse_Pa"] == 1


def test_mask_only_excludes_invalid_labels_and_weights_are_explicit():
    truth = np.array([[1., 0], [2, 0], [np.nan, np.nan]])
    predicted = np.array([[1., 0], [4, 0], [np.nan, np.nan]])
    metric = complex_metrics(predicted, truth, [True, True, False], [1, 3, 0])
    assert metric["relative_complex_l2"] == pytest.approx(np.sqrt(12 / 13))
    assert metric["norm_definition"] == "physical_quadrature_relative_complex_l2"


@pytest.mark.skipif(importlib.util.find_spec("torch") is None, reason="Optional torch not installed; not evidence of model execution")
def test_network_accepts_variable_geometry_and_is_permutation_invariant():
    import torch
    torch.manual_seed(12)
    model = build_model(4, 2, width=8, latent=4).eval()
    geometry, context, query = torch.randn(11, 4), torch.randn(2), torch.randn(7, 3)
    with torch.no_grad():
        a = model(geometry, context, query)
        b = model(geometry.flip(0), context, query)
        c = model(geometry[:3], context, query)
    assert a.shape == c.shape == (7, 2)
    assert torch.allclose(a, b, atol=1e-6)


@pytest.mark.skipif(importlib.util.find_spec("torch") is None, reason="Optional torch not installed; not evidence of training")
def test_tiny_synthetic_training_runs_without_claiming_physical_validation(fixture_dir):
    path, _ = make_dataset(fixture_dir)
    dataset = load_dataset(path, research_only=True)
    output = fixture_dir / "experiment"
    report = train_operator(dataset, output, research_only=True, epochs=2, width=8, latent=4,
                            query_points_per_design=4, max_condition_points=4, seed=7, max_seconds=30)
    assert report["epochs_completed"] == 2
    assert not report["release_allowed"] and not report["training_ready"]
    assert report["exact_point_used_for_training"] is False
    assert report["checkpoint_selected_on"] == "validation_only"
    assert report["metrics_by_split"]["test"]["n_designs"] == 1
    assert report["prediction_source_type"] == "ai_solver"
    assert (output / "research_checkpoint.pt").is_file()
    with pytest.raises(OperatorDataError, match="append-only"):
        train_operator(dataset, output, research_only=True, epochs=1)
