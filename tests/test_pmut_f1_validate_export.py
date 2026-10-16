"""只使用合成小 MAT，验证回收QC；不冒充真实COMSOL导出验收。"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

SPEC = importlib.util.spec_from_file_location("pmut_f1_validate_export_test", Path(__file__).parents[1] / "scripts/pmut_f1_validate_export.py")
qc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qc)


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "export"
    root.mkdir()
    manifest_path = tmp_path / "manifest.json"
    cases = []
    for i in range(21):
        cases.append({"case_id": "synthetic_%02d" % i, "x_scale": .3 + .01*i,
                      "N_w_te1": 1, "N_w_te2": 8, "frequency_Hz": 10e6,
                      "outer_solnum": i+1, "inner_solnum": 11, "p_point_real_Pa": 3.,
                      "p_point_imag_Pa": 4., "source_table_sha256": "a"*64,
                      "source_table_row_1based": 10+i, "mode_identity": "unverified"})
    manifest = {"schema": "memsharness.pmut_f1_export_manifest/v0", "dataset": "dset3",
                "field_expression": "acpr.p_t", "observation_xyz_m": [0,0,-1e-5],
                "training_ready": False, "cases": cases}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_hash = qc.file_sha256(manifest_path)
    report = {"schema": "memsharness.pmut_f1_stored_export/v0", "status": "complete",
              "dataset": "dset3", "field_expression": "acpr.p_t", "requested": 21, "completed": 21,
              "source_model": "/remote/synthetic.mph", "source_model_sha256": "b"*64,
              "manifest_sha256": manifest_hash, "source_unchanged": True,
              "source_before": {"size_bytes": 123, "mtime_millis": 456},
              "source_after": {"size_bytes": 123, "mtime_millis": 456},
              "mode_identity": "unverified", "training_ready": False,
              "point_reference_same_model_verified": False, "cases": []}
    samples = {}
    # 坐标中故意没有精确目标点；独立求值字段才可用于目标点对账。
    xyz = np.array([[0,1e-6,2e-6], [0,0,0], [-2e-5,-2e-5,-2e-5]])
    for case in cases:
        cid = case["case_id"]
        sample = {k: case[k] for k in ("case_id","x_scale","N_w_te1","N_w_te2","frequency_Hz","outer_solnum","inner_solnum")}
        sample.update(schema="memsharness.pmut_f1_stored_field/v0", xyz_m=xyz,
                      x_m=xyz[0], y_m=xyz[1], z_m=xyz[2], p_total_Pa=np.array([100+200j,2+1j,np.nan+0j]),
                      p_finite_mask=np.array([1,1,0], dtype=np.uint8), source_type="simulation",
                      source_dataset="dset3", canonical_expression="acpr.p_t", source_model=report["source_model"],
                      source_model_sha256="b"*64, manifest_sha256=manifest_hash,
                      source_hash_verification="computed_from_file_bytes", mode_identity="unverified",
                      training_ready=False, geometry_material_bc_exported=False, solution_identity_verified=True,
                      solution_identity_verification_scope="requested_parameters_frequency_and_point_pressure_not_physics_equivalence",
                      point_evaluation_method="stored_finite_element_solution_at_exact_coordinate_ext0",
                      p_point_stored_solution_Pa=3+4j, point_reference_pressure_consistent=True,
                      dom_available=True, dom=np.array([1,1,np.nan]),
                      units={"coordinates":"m","pressure":"Pa","frequency":"Hz"},
                      point_reference={"xyz_m": [0,0,-1e-5], "p_real_Pa":3.,"p_imag_Pa":4.,
                          "source_type":"scalar_table_reference_not_field_node", "source_table_sha256":"a"*64,
                          "source_table_row_1based":case["source_table_row_1based"],
                          "table_hash_verification":"manifest_declared_not_recomputed",
                          "pressure_consistent_with_stored_solution":True,"same_source_model_verified":False,
                          "comparison_rtol":1e-6,"comparison_atol_Pa":1e-9})
        samples[cid] = sample
        path = root / (cid+".mat")
        savemat(path, sample, long_field_names=True)
        report["cases"].append({"case_id":cid, "file":"/remote/export/"+path.name,
                                "sha256":qc.file_sha256(path),"n_points":3,"n_finite_pressure":2,
                                "point_reference_pressure_consistent":True,"dom_available":True,"mode_identity":"unverified"})
    report_path = root / "export_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return {"root":root,"manifest_path":manifest_path,"manifest":manifest,"report":report,
            "report_path":report_path,"samples":samples,"tmp":tmp_path}


def update_report(b):
    b["report_path"].write_text(json.dumps(b["report"]), encoding="utf-8")


def update_sample(b, change):
    cid = b["manifest"]["cases"][0]["case_id"]
    sample = b["samples"][cid]
    change(sample)
    path = b["root"] / (cid+".mat")
    savemat(path, sample, long_field_names=True)
    b["report"]["cases"][0]["sha256"] = qc.file_sha256(path)
    update_report(b)


def test_complete_synthetic_bundle_accepts_separate_exact_point(bundle):
    result = qc.validate_export(bundle["manifest_path"], bundle["root"])
    assert result["passed"] and result["n_cases"] == 21
    assert result["cases"][0]["exact_point_abs_error_Pa"] == 0
    assert result["training_ready"] is False
    assert result["source_model_rehashed_locally"] is False


@pytest.mark.parametrize("fault", ["incomplete","wrong_count","manifest_hash","source_changed","source_flag","duplicate_case","unsafe_file","wrong_basename","training_ready","dom_flag"])
def test_bad_report_fails(bundle, fault):
    r = bundle["report"]
    if fault == "incomplete": r["status"] = "running"
    elif fault == "wrong_count": r["completed"] = 20
    elif fault == "manifest_hash": r["manifest_sha256"] = "c"*64
    elif fault == "source_changed": r["source_after"]["mtime_millis"] += 1
    elif fault == "source_flag": r["source_unchanged"] = False
    elif fault == "duplicate_case": r["cases"][1] = copy.deepcopy(r["cases"][0])
    elif fault == "unsafe_file": r["cases"][0]["file"] = "/remote/../synthetic_00.mat"
    elif fault == "wrong_basename": r["cases"][0]["file"] = "/remote/another.mat"
    elif fault == "training_ready": r["training_ready"] = True
    else: r["cases"][0]["dom_available"] = "true"
    update_report(bundle)
    with pytest.raises(qc.ExportValidationError):
        qc.validate_export(bundle["manifest_path"], bundle["root"])


@pytest.mark.parametrize("fault", ["missing_file","extra_file","nested_dir","hash_mismatch"])
def test_file_set_and_hash_are_checked(bundle, fault):
    if fault == "missing_file": (bundle["root"] / "synthetic_00.mat").unlink()
    elif fault == "extra_file": (bundle["root"] / "stale.mat").write_bytes(b"stale")
    elif fault == "nested_dir": (bundle["root"] / "nested").mkdir()
    else:
        with (bundle["root"] / "synthetic_00.mat").open("ab") as f: f.write(b"tampered")
    with pytest.raises(qc.ExportValidationError):
        qc.validate_export(bundle["manifest_path"], bundle["root"])


@pytest.mark.parametrize("fault", ["xyz_transpose","coords_nan","mask","all_missing","wrong_param","wrong_index","wrong_freq","source_hash","manifest_hash","point_missing","nearest_node","point_coords","point_ref","point_hash","point_row","point_method","point_tolerance","fake_mode","bad_units"])
def test_mat_faults_fail_even_with_updated_file_hash(bundle, fault):
    def change(s):
        if fault == "xyz_transpose": s["xyz_m"] = np.ones((2,3))
        elif fault == "coords_nan": s["xyz_m"][0,0] = np.nan
        elif fault == "mask": s["p_finite_mask"][2] = 1
        elif fault == "all_missing":
            s["p_total_Pa"][:] = np.nan; s["p_finite_mask"][:] = 0
        elif fault == "wrong_param": s["N_w_te1"] = 2
        elif fault == "wrong_index": s["outer_solnum"] += 1
        elif fault == "wrong_freq": s["frequency_Hz"] += 5e5
        elif fault == "source_hash": s["source_model_sha256"] = "c"*64
        elif fault == "manifest_hash": s["manifest_sha256"] = "c"*64
        elif fault == "point_missing": s.pop("p_point_stored_solution_Pa")
        elif fault == "nearest_node": s["p_point_stored_solution_Pa"] = s["p_total_Pa"][0]
        elif fault == "point_coords": s["point_reference"]["xyz_m"] = [0,0,1e-5]
        elif fault == "point_ref": s["point_reference"]["p_real_Pa"] += 1
        elif fault == "point_hash": s["point_reference"]["source_table_sha256"] = "c"*64
        elif fault == "point_row": s["point_reference"]["source_table_row_1based"] += 1
        elif fault == "point_method": s["point_evaluation_method"] = "nearest_node"
        elif fault == "point_tolerance": s["point_reference"]["comparison_rtol"] = 1
        elif fault == "fake_mode": s["mode_identity"] = "verified"
        else: s["units"]["pressure"] = "MPa"
    update_sample(bundle, change)
    with pytest.raises((qc.ExportValidationError, KeyError)):
        qc.validate_export(bundle["manifest_path"], bundle["root"])


def test_complex_point_tolerance_checks_phase_not_only_magnitude(bundle):
    update_sample(bundle, lambda s: s.update(p_point_stored_solution_Pa=-3-4j))
    with pytest.raises(qc.ExportValidationError, match="Exact-point pressure"):
        qc.validate_export(bundle["manifest_path"], bundle["root"])


def test_exact_point_tolerance_accepts_small_complex_error(bundle):
    update_sample(bundle, lambda s: s.update(p_point_stored_solution_Pa=3+4j+1e-7j))
    result = qc.validate_export(bundle["manifest_path"], bundle["root"])
    assert 0 < result["cases"][0]["exact_point_abs_error_Pa"] < 1e-6


def test_cli_no_write_by_default_and_append_only_output(bundle, capsys):
    args = ["--manifest",str(bundle["manifest_path"]),"--export-dir",str(bundle["root"])]
    before = set(bundle["tmp"].iterdir())
    assert qc.main(args) == 0
    assert set(bundle["tmp"].iterdir()) == before
    output = bundle["tmp"] / "qc.json"
    assert qc.main(args+["--output",str(output)]) == 0
    assert json.loads(output.read_text())["training_ready"] is False
    with pytest.raises(FileExistsError):
        qc.main(args+["--output",str(output)])
    with pytest.raises(ValueError, match="read-only"):
        qc.main(args+["--output",str(bundle["root"] / "qc.json")])
    capsys.readouterr()


def test_cli_writes_honest_failure_qc(bundle, capsys):
    bundle["report"]["status"] = "failed"
    update_report(bundle)
    output = bundle["tmp"] / "failed-qc.json"
    assert qc.main(["--manifest",str(bundle["manifest_path"]),"--export-dir",str(bundle["root"]),"--output",str(output)]) == 1
    result = json.loads(output.read_text())
    assert result["passed"] is False and result["release_allowed"] is False
    capsys.readouterr()


def test_cli_rejects_nonobject_json_as_honest_failure(bundle, capsys):
    bundle["report_path"].write_text("[]", encoding="utf-8")
    assert qc.main(["--manifest", str(bundle["manifest_path"]), "--export-dir", str(bundle["root"])]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] is False
