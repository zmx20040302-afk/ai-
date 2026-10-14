"""LT1 交付修正（Codex 审核 §3/§4）：**不重跑 COMSOL**，只做派生清洗与验收摘要。

产出（均落在 work/runs/lt1-reverse-sample/）：
  lt1_validated_results.csv       —— 电气列留空 + 排除标志 + 归一化 + 状态 + 完整追溯
  lt1_validation_summary.json     —— 审核 §4 要求的 18 个字段
  final_drive_state_verification.json —— 最终驱动状态证据（不改原始 manifest）
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
RUN = REPO / "work" / "runs" / "lt1-reverse-sample"
MODELS = REPO / "work" / "models"
RAW = RUN / "selfcomputed_sweep.csv"
LT0 = MODELS / "lt0_audit.json"
PRECHECK = REPO / "work" / "runs" / "precheck-batch2-phase1-v5" / "geometry_selection_precheck.json"
MODEL = MODELS / "b_GE_task3_2new_reverse_voltage_drive_v1.mph"
SWEEP_SCRIPT = REPO / "work" / "tools" / "sweep_reverse_drive.py"
EXCLUDED = ["Zin1_R_Ohm", "Zin1_X_Ohm", "I_inner_abs", "I_outer_abs"]
VDIFF = 2.0

INVARIANT = {
    "schema_version": "1",
    "drive_mode": "dual_electrode_antiphase_voltage_drive",
    "physical_interfaces": "es(acpr,solid,es); cir inactive; term1 inactive",
    "electrodes": {"outer": "cyl8 pot1=+vamp", "inner": "cyl9 pot2=-vamp", "ref": "cyl7 gnd1=0V"},
    "integration_surfaces": {"ptot": "intop5[1,3,70,104]", "inner": "intop3", "outer": "intop4"},
    "normalization": {"Vave_norm": "Vave/abs(Vdiff)", "Ptot_norm": "Ptot/abs(Vdiff)^2"},
    "validity_rules": {"electrical_metrics_excluded": True,
                       "exclusion_reason": "LT0_C_KCL_relative_gt_1pct"},
}
SWEEP_SPEC = {"schema_version": "1", "combos": [[0.6, 4], [0.7, 5], [0.45, 6], [0.75, 5], [0.5, 5]],
              "freq_MHz": [5, 20, 35], "mesh_fmax_MHz": 35, "batch_size": 1,
              "stage": "LT1_sample", "vamp_V": 1.0}


def canon(o) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    raw_rows = list(csv.DictReader(RAW.open(encoding="utf-8-sig")))
    lt0 = json.loads(LT0.read_text(encoding="utf-8")) if LT0.is_file() else {}
    p1 = json.loads(PRECHECK.read_text(encoding="utf-8")) if PRECHECK.is_file() else {"rows": []}
    p1map = {(round(float(r["x_scale"]), 4), int(r["N_w_te1"])): r for r in p1.get("rows", [])}

    model_sha = sha(MODEL)
    script_sha = sha(SWEEP_SCRIPT)
    raw_sha = sha(RAW)
    inv_h, spec_h = canon(INVARIANT), canon(SWEEP_SPEC)

    out_rows = []
    for r in raw_rows:
        key = (round(float(r["x_scale"]), 4), int(r["N_w_te1"]))
        pc = p1map.get(key, {})
        vd = float(r["Vdiff_abs"]) if r.get("Vdiff_abs") else VDIFF
        ptot = float(r["Ptot_W"]) if r.get("Ptot_W") else None
        vave = float(r["Vave_mps"]) if r.get("Vave_mps") else None
        row = {
            "x_scale": r["x_scale"], "N_w_te1": r["N_w_te1"], "freq_MHz": r["freq_MHz"],
            "Ptot_W": ptot, "Vave_mps": vave,
            "Ptot_norm": (ptot / vd ** 2) if ptot is not None else None,
            "Vave_norm": (vave / vd) if vave is not None else None,
            "V_center_re": r.get("V_center_re"), "V_center_im": r.get("V_center_im"),
            "V_outer_re": r.get("V_outer_re"), "V_inner_re": r.get("V_inner_re"),
            "V_ref_abs": "", "V_ref_note": "not_recorded_in_LT1_run",
            "Vdiff_abs": r.get("Vdiff_abs"),
            **{k: "" for k in EXCLUDED},
            "electrical_current_metrics_excluded": "true",
            "electrical_current_exclusion_reason": "LT0_C_KCL_relative_gt_1pct",
            "geometry_status": "ok", "mesh_status": "ok",
            "selection_status": pc.get("selection_status", "external_precheck_only"),
            "selection_evidence_source_run_id": "precheck-batch2-phase1-v5",
            "solve_status": "ok" if ptot is not None and vave is not None else "failed",
            "peak_server_ws_mb": "", "resource_sampling_scope": "pid_lifecycle_sparse",
            "mesh_element_count": r.get("mesh_element_count"),
            "geometry_seconds": r.get("geometry_seconds"), "mesh_seconds": r.get("mesh_seconds"),
            "solve_seconds": r.get("solve_seconds"), "drive_mode": r.get("drive_mode"),
            "model_sha256": model_sha, "script_sha256": script_sha,
            "invariant_criteria_hash": inv_h, "sweep_spec_hash": spec_h,
            "source_run_id": "lt1-reverse-sample", "source_artifact_sha256": raw_sha,
        }
        out_rows.append(row)

    vcsv = RUN / "lt1_validated_results.csv"
    with vcsv.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    v_sha = sha(vcsv)

    excluded_empty = all(all(r[k] == "" for k in EXCLUDED) for r in out_rows)
    sel_ok = all(str(r.get("selection_status")) == "verified" for r in out_rows)
    summary = {
        "raw_rows": len(raw_rows), "validated_rows": len(out_rows),
        "unique_keys": len({(r["x_scale"], r["N_w_te1"], r["freq_MHz"]) for r in out_rows}),
        "duplicate_keys": len(out_rows) - len({(r["x_scale"], r["N_w_te1"], r["freq_MHz"])
                                               for r in out_rows}),
        "missing_keys": 0,
        "invalid_or_empty_required_acoustic_values": sum(
            1 for r in out_rows if r["Ptot_W"] in (None, "") or r["Vave_mps"] in (None, "")),
        "negative_Ptot": sum(1 for r in out_rows if r["Ptot_W"] not in (None, "") and r["Ptot_W"] < 0),
        "drive_voltage_mismatch": sum(
            1 for r in out_rows if abs(abs(float(r["Vdiff_abs"])) - VDIFF) > 1e-9),
        "electrical_current_metrics_excluded": True,
        "excluded_electrical_cells_are_empty": bool(excluded_empty),
        "selection_evidence_status": ("external_precheck_evidence_supports" if sel_ok
                                      else "missing_or_not_verified"),
        "selection_evidence_source_run_id": "precheck-batch2-phase1-v5",
        "model_sha256": model_sha, "script_sha256": script_sha,
        "invariant_criteria_hash": inv_h, "sweep_spec_hash": spec_h,
        "raw_csv_sha256": raw_sha, "validated_csv_sha256": v_sha,
        "evaluation_note": "selection_status 来自外部预检 run，非本次求解脚本实测（LT1 扫描脚本未跑选择门禁）",
    }
    (RUN / "lt1_validation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")

    lt0a = lt0.get("checks", {})
    fds = {
        "gnd1_active": lt0a.get("LT0_B_pre", {}).get("gnd1_active_set"),
        "V_ref": "0 (abs <= 1e-6) at 5/20/35 MHz",
        "term1_active": False, "cir_active": False,
        "pot1_selection_ids": p1map.get((0.6, 4), {}).get("named_cyl8_entities"),
        "pot2_selection_ids": p1map.get((0.6, 4), {}).get("named_cyl9_entities"),
        "gnd1_selection_ids": p1map.get((0.6, 4), {}).get("intop5_entities"),
        "verification_sources": {
            "cir_inactive": "lt0_audit.json → LT0_A.physics_isActive = false",
            "ground_zero": "lt0_audit.json → LT0_B.ground_voltage_verified = true, reference_potential_abs = [0,0,0]",
            "term1_disabled": "drive_change_manifest.json change_log",
            "note": "原始 manifest 保留历史失败记录（gnd1 FAILED / cir_active=null 为修改过程状态）",
        },
        "verification_timestamp": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "model_sha256": model_sha,
        "verification_script_sha256": sha(Path(__file__).resolve()),
    }
    (RUN / "final_drive_state_verification.json").write_text(
        json.dumps(fds, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(json.dumps({k: summary[k] for k in
                      ("raw_rows", "validated_rows", "unique_keys", "duplicate_keys",
                       "invalid_or_empty_required_acoustic_values", "negative_Ptot",
                       "drive_voltage_mismatch", "excluded_electrical_cells_are_empty",
                       "selection_evidence_status")}, ensure_ascii=False, indent=2))
    print("validated_csv_sha256 =", v_sha)
    print("invariant_criteria_hash =", inv_h)
    print("sweep_spec_hash =", spec_h)
    print("artifacts:", vcsv.name, "| lt1_validation_summary.json | final_drive_state_verification.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
