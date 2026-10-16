from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from memsharness.pmut_f1_dataset import sha256
from memsharness.pmut_f1_sparse_plan import (
    build_sparse_plan, read_historical_hints, resolve_indices, write_plan_run,
)


@pytest.fixture
def inventory():
    records, sources = [], []
    for n2 in range(5, 10):
        digest = str(n2) * 64
        sources.append({"N_w_te2": n2, "sha256": digest, "path": "synthetic-N2%d.mat" % n2,
                        "lineage_alignment_pending": n2 == 9})
        for ix in range(20, 101):
            for n1 in range(1, n2):
                records.append({"case_id": "x%03d_N1%d_N2%d" % (ix, n1, n2),
                    "x_scale": ix / 100, "N_w_te1": n1, "N_w_te2": n2,
                    "source_type": "simulation", "observation_xyz_m": [0, 0, -1e-5],
                    "field_expression": "acpr.p_t", "mode_identity": "unverified", "training_ready": False,
                    "source_table_sha256": digest, "source_table_row_1based": len(records) + 1,
                    "first_observable_peak_found": True, "frequency_Hz": 10e6,
                    "frequency_grid_index_1based": 11, "p_point_real_Pa": 3., "p_point_imag_Pa": 4.,
                    "frequency_semantics": "first_observable_pressure_peak_on_solved_grid_not_verified_f1",
                    "lineage_alignment_pending": n2 == 9, "quarantined": False})
    return {"schema": "memsharness.pmut_f1_scalar_inventory/v0", "n_designs": len(records),
            "sources": sources, "records": records}


@pytest.fixture
def exposed():
    return {"x%03d_N1%d_N28" % (x, n1) for x in (30, 60, 90) for n1 in range(1, 8)}


def test_full_geometry_grouping_two_policies_and_existing_pilot(inventory, exposed):
    plan, frozen, pending = build_sparse_plan(inventory, exposed)
    assert plan["n_selected"] == 164
    assert plan["split_counts"]["parameter_holdout"] == {"train": 90, "test": 30, "dev": 44}
    assert plan["n_discrete_branches"] == 30 and not plan["shortages"]
    assert len(frozen["assignments"]) == 2430
    assert len({c["design_id"] for c in plan["cases"]}) == 164
    for cid in exposed:
        row = next(c for c in plan["cases"] if c["case_id"] == cid)
        assert row["selection"]["splits"] == {"parameter_holdout": "dev", "branch_holdout": "dev"}
        assert row["selection"]["training_splits"]["design_holdout"] == "validation"
    branch_labels = {}
    for row in frozen["assignments"]:
        branch_labels.setdefault(row["branch_id"], set()).add(row["splits"]["branch_holdout"])
    assert all(len(labels) == 1 for labels in branch_labels.values())
    assert len(pending["pending_case_ids"]) == 164 and plan["n_export_ready"] == 0


def test_deterministic_order_independent_and_pressure_not_ranked(inventory, exposed):
    original = build_sparse_plan(inventory, exposed)
    changed = copy.deepcopy(inventory)
    changed["records"].reverse()
    for i, row in enumerate(changed["records"]):
        row["p_point_real_Pa"], row["p_point_imag_Pa"] = i * 123., -i * 456.
    repeated = build_sparse_plan(changed, exposed)
    assert [c["case_id"] for c in original[0]["cases"]] == [c["case_id"] for c in repeated[0]["cases"]]
    assert original[1] == repeated[1]
    assert original == build_sparse_plan(inventory, exposed)


def test_lineage_quarantine_is_retained_not_pooled(inventory, exposed):
    plan, _, pending = build_sparse_plan(inventory, exposed)
    n9 = [c for c in plan["cases"] if c["N_w_te2"] == 9]
    assert len(n9) == 40
    assert all(c["training_eligibility"] == "lineage_quarantine" for c in n9)
    assert set(pending["lineage_quarantine_case_ids"]) == {c["case_id"] for c in n9}
    assert plan["training_ready"] is False and plan["release_allowed"] is False


def test_existing_indices_are_not_trusted_or_recomputed(inventory, exposed):
    for row in inventory["records"]:
        row.update(outer_solnum=123, inner_solnum=11)
    plan, _, _ = build_sparse_plan(inventory, exposed)
    assert all(c["outer_solnum"] is None and c["inner_solnum"] is None for c in plan["cases"])
    assert all(c["resolve_solution_indices"] and not c["export_ready"] for c in plan["cases"])


def test_no_peak_is_not_substituted_with_endpoint_and_split_is_unchanged(inventory, exposed):
    baseline, frozen, _ = build_sparse_plan(inventory, exposed)
    for row in inventory["records"]:
        if row["N_w_te2"] == 5:
            row["first_observable_peak_found"] = False
            row["frequency_Hz"] = row["p_point_real_Pa"] = row["p_point_imag_Pa"] = None
    plan, new_frozen, _ = build_sparse_plan(inventory, exposed)
    assert not any(c["N_w_te2"] == 5 for c in plan["cases"])
    assert len(plan["shortages"]) == 12
    assert frozen == new_frozen


@pytest.mark.parametrize("fault", ["duplicate", "case_id", "point", "pressure_nan", "mode", "exposure_missing", "source_layer", "missing_design"])
def test_invalid_inventory_fails_closed(inventory, exposed, fault):
    row = inventory["records"][0]
    if fault == "duplicate":
        inventory["records"].append(copy.deepcopy(row)); inventory["n_designs"] += 1
    elif fault == "case_id": row["case_id"] = "../unsafe"
    elif fault == "point": row["observation_xyz_m"] = [0, 0, 1e-5]
    elif fault == "pressure_nan": row["p_point_real_Pa"] = float("nan")
    elif fault == "mode": row["mode_identity"] = "verified"
    elif fault == "exposure_missing": exposed.add("x999_N11_N25")
    elif fault == "source_layer": row["source_table_sha256"] = "a" * 64
    else:
        inventory["records"].pop(); inventory["n_designs"] -= 1
    with pytest.raises(ValueError):
        build_sparse_plan(inventory, exposed)


@pytest.fixture
def verified_index(inventory, tmp_path):
    row = inventory["records"][0]
    evidence = tmp_path / "synthetic-readback.json"
    source = {"source_id": "synthetic-only", "source_table_sha256": row["source_table_sha256"],
              "source_model": "/synthetic/model.mph", "source_model_sha256": "a" * 64,
              "source_hash_verified": True, "dataset": "dset3", "evidence_path": str(evidence),
              "cases": [{**{k: row[k] for k in
                  ("case_id", "x_scale", "N_w_te1", "N_w_te2", "frequency_Hz")},
                  "outer_solnum": 77, "inner_solnum": 19, "parameter_frequency_readback_verified": True}]}
    evidence.write_text(json.dumps(source), encoding="utf-8")
    source["evidence_sha256"] = sha256(evidence)
    return row, source


def test_verified_index_is_used_without_frequency_grid_index_guessing(verified_index):
    row, source = verified_index
    result = resolve_indices(row, {row["source_table_sha256"]: source})
    assert result["export_ready"] and result["outer_solnum"] == 77 and result["inner_solnum"] == 19
    assert result["exact_point_consistency_still_required_at_export"]


@pytest.mark.parametrize("fault", ["historical", "hash", "missing_file", "wrong_param", "duplicate", "flag", "zero", "bool_index", "missing_field", "evidence_content"])
def test_unverified_index_never_becomes_executable(verified_index, fault):
    row, source = verified_index
    if fault == "historical": source["source_hash_verified"] = False
    elif fault == "hash": source["evidence_sha256"] = "b" * 64
    elif fault == "missing_file": source["evidence_path"] += ".missing"
    elif fault == "wrong_param": source["cases"][0]["N_w_te1"] += 1
    elif fault == "duplicate": source["cases"].append(copy.deepcopy(source["cases"][0]))
    elif fault == "flag": source["cases"][0]["parameter_frequency_readback_verified"] = False
    elif fault == "zero": source["cases"][0]["outer_solnum"] = 0
    elif fault == "bool_index": source["cases"][0]["inner_solnum"] = True
    elif fault == "missing_field": source.pop("source_model_sha256")
    else:
        path = Path(source["evidence_path"])
        path.write_text(json.dumps({"not_readback_evidence": True}), encoding="utf-8")
        source["evidence_sha256"] = sha256(path)
    result = resolve_indices(row, {row["source_table_sha256"]: source})
    assert result["export_ready"] is False and result["outer_solnum"] is None and result["inner_solnum"] is None


def test_historical_hash_stays_unverified_and_new_outputs_are_append_only(inventory, exposed, tmp_path):
    metadata = tmp_path / "models.tsv"
    metadata.write_text("sha256\tsize_bytes\tmodel_path\n" + "a" * 64 + "\t100\t/remote/cell_te2_5_saved.mph\n", encoding="utf-8")
    hints = read_historical_hints(metadata, ["9=/remote/cell_te2_9_saved.mph"])
    plan, frozen, pending = build_sparse_plan(inventory, exposed, source_hints=hints)
    source = pending["sources"][0]
    assert source["historical_source_model_sha256"] == "a" * 64 and not source["source_hash_verified"]
    output = tmp_path / "new-run"
    hashes = write_plan_run(output, plan, frozen, pending)
    assert len(hashes) == 3 and len(list(output.iterdir())) == 4
    with pytest.raises(ValueError, match="new run"):
        write_plan_run(output, plan, frozen, pending)


def test_cli_creates_new_run_and_records_input_hashes(inventory, exposed, tmp_path):
    spec = importlib.util.spec_from_file_location("pmut_sparse_cli_test", Path(__file__).parents[1] / "scripts/pmut_f1_plan_sparse.py")
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    inv, seen = tmp_path / "inventory.json", tmp_path / "seen.json"
    inv.write_text(json.dumps(inventory), encoding="utf-8")
    seen.write_text(json.dumps({"cases": [{"case_id": cid} for cid in sorted(exposed)]}), encoding="utf-8")
    args = ["--inventory", str(inv), "--exposed-manifest", str(seen), "--output-dir", str(tmp_path / "run")]
    assert cli.main(args) == 0
    plan = json.loads((tmp_path / "run/plan.json").read_text(encoding="utf-8"))
    assert plan["inputs"][0]["sha256"] == sha256(inv) and plan["n_export_ready"] == 0
    with pytest.raises(FileExistsError):
        cli.main(args)
