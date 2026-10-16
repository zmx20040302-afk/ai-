from __future__ import annotations

import json

import numpy as np

from memsharness.single_pressure_solver import (
    AmpShapeBranch,
    PressurePrediction,
    SinglePressureSolver,
    build_branch,
    plan_comsol_support,
    write_registry,
)


def _fixture(tmp_path):
    xs = np.linspace(0.2, 1.0, 9)
    points = np.column_stack([np.arange(6), np.zeros(6), np.zeros(6)]) * 1e-6
    a = np.linspace(1.0, 2.0, 6) + 1j * np.linspace(-0.2, 0.3, 6)
    b = np.linspace(-0.1, 0.4, 6) + 1j * np.linspace(0.5, 0.1, 6)
    fields = np.column_stack([(1 + x) * (a + x * b) for x in xs])
    mask = np.ones(6, dtype=bool)
    roles = np.array(["train", "train", "holdout", "train", "holdout",
                      "train", "train", "train", "train"])
    cache = tmp_path / "cache.npz"
    np.savez_compressed(cache, P=fields, mask=mask, x_scale=xs,
                        role_x=roles, role_n=np.array(["train"] * 9),
                        names=np.array(["s%d.mat" % i for i in range(9)]))
    pts = tmp_path / "points.tsv"
    np.savetxt(pts, points, delimiter="\t", header="x\ty\tz", comments="")
    report = {
        "tag": "n1_4",
        "s1": {"B_amp_shape": {"global_max": 0.012, "key_max": 0.009}},
        "s5": {"bands": {"0.1": {"band_rel_L2": 0.02,
                                      "coverage_on_holdout": 1.0,
                                      "n_holdout": 2}}},
        "gate_view": {"S0": "inconclusive", "S1": "passed", "S2": "passed",
                      "S3": "inconclusive", "S4": "inconclusive", "S5": "inconclusive"},
    }
    rp = tmp_path / "report.json"
    rp.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "dist"
    mp = build_branch(cache, pts, rp, out, n1=4)
    reg = write_registry([mp], out / "registry.json")
    return mp, reg


def test_branch_roundtrip_and_complex_prediction(tmp_path):
    mp, _reg = _fixture(tmp_path)
    branch = AmpShapeBranch.load(mp)
    result = branch.predict(0.5)
    assert isinstance(result, PressurePrediction)
    assert np.iscomplexobj(result.field)
    assert np.isfinite(result.field[result.mask]).all()
    assert result.report["source_type"] == "ai_solver"
    assert result.report["model_state"] == "draft"
    assert result.report["s_levels"]["S1"] == "passed"
    assert result.report["s_levels"]["S5"] == "inconclusive"
    assert result.report["field_rel_l2_error_bound"] == 0.02


def test_registry_refuses_cross_branch_and_out_of_evidence(tmp_path):
    _mp, reg = _fixture(tmp_path)
    solver = SinglePressureSolver.load(reg)
    ok = solver.solve(x_scale=0.5, n1=4, n2=8, freq_hz=20_000_000)
    assert isinstance(ok, PressurePrediction)
    wrong_n1 = solver.solve(x_scale=0.5, n1=5, n2=8, freq_hz=20_000_000)
    assert wrong_n1["refused"] is True
    assert "禁止跨" in wrong_n1["reason"]
    outside = solver.solve(x_scale=0.95, n1=4, n2=8, freq_hz=20_000_000)
    assert outside["refused"] is True
    assert "证据范围" in outside["reason"]
    fractional = solver.solve(x_scale=0.5, n1=4.5, n2=8, freq_hz=20_000_000)
    assert fractional["refused"] is True
    assert fractional["support_plan"]["auto_submittable"] is False


def test_support_plan_is_five_serial_runs_with_true_holdouts():
    plan = plan_comsol_support(0.5, 5, 8, 25_000_000)
    assert plan["auto_submittable"] is True
    assert plan["execution"] == "serial_only"
    assert plan["n_runs"] == 5
    assert [r["role"] for r in plan["runs"]].count("holdout") == 2
    assert all(r["N_w_te1"] == 5 for r in plan["runs"])
