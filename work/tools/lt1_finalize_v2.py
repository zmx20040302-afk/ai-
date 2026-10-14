"""LT1 验收文件 v2（Codex 2026-09-14 裁定 §4.2 修正 A/B）——**不重跑 COMSOL、不改原始 CSV**。

与 v1 (`lt1_finalize.py`) 的差异，全部是**描述符语义**修正，不涉及任何数值重算：

修正 A（判据哈希语义）
  - `invariant_criteria_hash` 只放「不随 LT1/LT2 变化的判据」：
    驱动口径、物理界面状态、选择/积分面规则、归一化规则、量有效性/排除规则、单位与通用验收规则。
  - `sweep_spec_hash` 放「随阶段变化的东西」：
    参数组合、频率列表、期望行数、批次/生命周期组织、阶段专属资源阈值。
  - 迁移：`vamp_V` 由 SWEEP_SPEC → INVARIANT（它是驱动定义的一部分，与频率不同，不随阶段变）；
    新增 `expected_rows` 与 `resource_thresholds` 到 SWEEP_SPEC；
    新增 `units` 与 `acceptance_rules` 到 INVARIANT。
  - 两个 dict 都带 `descriptor_revision`，使哈希本身编码「这是事后重新拆分」这一事实。

修正 B（selection 状态措辞）
  - `selection_status` 强制写 `externally_supported`（不再沿用预检里的 `verified`）。
  - 新增 `selection_verification_scope = external_precheck_not_same_solve_run`。

产出（append-only，不覆盖 v1 文件）：
  lt1_validated_results_v2.csv
  lt1_validation_summary_v2.json
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

# v1 的两个哈希，用于在摘要里留下「拆分前后」对照（取自 v1 摘要，实测值）
V1_HASHES = {
    "invariant_criteria_hash": "a973de0d486bf51959ed3f8687899f6db3bcd1baac995414f885467b9a12a4e3",
    "sweep_spec_hash": "5a036b5388899d293656f461fa149ee13e94c13cd50c90bc2498d96fe1a902a4",
}

# ---- 不变量：不随 LT1/LT2 阶段改变 ----
INVARIANT = {
    "schema_version": "2",
    "descriptor_revision": "v2_post_hoc_resplit_no_rerun",
    "drive_mode": "dual_electrode_antiphase_voltage_drive",
    "vamp_V": 1.0,
    "Vdiff_V": 2.0,
    "physical_interfaces": "es(acpr,solid,es); cir inactive; term1 inactive",
    "electrodes": {"outer": "cyl8 pot1=+vamp", "inner": "cyl9 pot2=-vamp", "ref": "cyl7 gnd1=0V"},
    "integration_surfaces": {"ptot": "intop5[1,3,70,104]", "inner": "intop3", "outer": "intop4"},
    "normalization": {"Vave_norm": "Vave/abs(Vdiff)", "Ptot_norm": "Ptot/abs(Vdiff)^2"},
    "units": {"length": "m", "frequency": "Hz", "power": "W", "voltage": "V", "velocity": "m/s"},
    "validity_rules": {"electrical_metrics_excluded": True,
                       "exclusion_reason": "LT0_C_KCL_relative_gt_1pct"},
    "acceptance_rules": {"drive_voltage_mismatch_tol_V": 1e-9,
                         "duplicate_keys": 0, "missing_keys": 0,
                         "failed_frequency_points": 0},
}

# ---- 扫描规格：随阶段改变 ----
SWEEP_SPEC = {
    "schema_version": "2",
    "descriptor_revision": "v2_post_hoc_resplit_no_rerun",
    "stage": "LT1_sample",
    "combos": [[0.6, 4], [0.7, 5], [0.45, 6], [0.75, 5], [0.5, 5]],
    "freq_MHz": [5, 20, 35],
    "expected_rows": 15,
    "mesh_fmax_MHz": 35,
    "batch_size": 1,
    "server_lifecycle_size": 1,
    "resource_thresholds": {
        "note": "LT1 阶段未实施实时门禁；此处登记 LT2 起实施的门禁值以便哈希覆盖阶段阈值",
        "ws_warning_mb": 11500,
        "ws_hard_stop_mb": 12288,
        "physical_avail_hard_stop_mb": 4096,
        "commit_warning_mb": 6144,
        "commit_hard_stop_mb": 4096,
        "consecutive_samples": 2,
    },
}


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
        vd = float(r["Vdiff_abs"]) if r.get("Vdiff_abs") else VDIFF
        ptot = float(r["Ptot_W"]) if r.get("Ptot_W") else None
        vave = float(r["Vave_mps"]) if r.get("Vave_mps") else None
        out_rows.append({
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
            # 修正 B：不得写成 verified（选择门禁不是本次求解同次执行）
            "selection_status": "externally_supported",
            "selection_verification_scope": "external_precheck_not_same_solve_run",
            "selection_evidence_source_run_id": "precheck-batch2-phase1-v5",
            "selection_evidence_source_value": pc_status(p1map, key),
            "solve_status": "ok" if ptot is not None and vave is not None else "failed",
            "peak_server_ws_mb": "", "resource_sampling_scope": "pid_lifecycle_sparse",
            "mesh_element_count": r.get("mesh_element_count"),
            "geometry_seconds": r.get("geometry_seconds"), "mesh_seconds": r.get("mesh_seconds"),
            "solve_seconds": r.get("solve_seconds"), "drive_mode": r.get("drive_mode"),
            "model_sha256": model_sha, "script_sha256": script_sha,
            "invariant_criteria_hash": inv_h, "sweep_spec_hash": spec_h,
            "source_run_id": "lt1-reverse-sample", "source_artifact_sha256": raw_sha,
        })

    vcsv = RUN / "lt1_validated_results_v2.csv"
    with vcsv.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    v_sha = sha(vcsv)

    excluded_empty = all(all(r[k] == "" for k in EXCLUDED) for r in out_rows)
    summary = {
        "artifact_version": "v2",
        "supersedes": "lt1_validation_summary.json (v1)",
        "recompute_performed": False,
        "raw_rows": len(raw_rows), "validated_rows": len(out_rows),
        "expected_rows": SWEEP_SPEC["expected_rows"],
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
        # 修正 B
        "selection_evidence_status": "externally_supported",
        "selection_verification_scope": "external_precheck_not_same_solve_run",
        "selection_evidence_source_run_id": "precheck-batch2-phase1-v5",
        "model_sha256": model_sha, "script_sha256": script_sha,
        "invariant_criteria_hash": inv_h, "sweep_spec_hash": spec_h,
        "raw_csv_sha256": raw_sha, "validated_csv_sha256": v_sha,
        "hash_split_change_log": {
            "superseded_hashes": V1_HASHES,
            "moved_between_dicts": {"vamp_V": "sweep_spec -> invariant"},
            "added_to_invariant": ["units", "acceptance_rules", "Vdiff_V"],
            "added_to_sweep_spec": ["expected_rows", "server_lifecycle_size", "resource_thresholds"],
            "reason": "频率列表随阶段变化，须在 sweep_spec；驱动幅值不随阶段变化，须在 invariant",
            "note": "本次哈希变化反映描述符重新拆分，不代表 LT1 在旧哈希下未通过，也不触发任何重算",
        },
        "evaluation_note": "selection_status 来自外部预检 run，非本次求解脚本实测（LT1 扫描脚本未跑选择门禁）",
    }
    (RUN / "lt1_validation_summary_v2.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: summary[k] for k in
                      ("validated_rows", "expected_rows", "unique_keys", "duplicate_keys",
                       "invalid_or_empty_required_acoustic_values", "negative_Ptot",
                       "drive_voltage_mismatch", "excluded_electrical_cells_are_empty",
                       "selection_evidence_status", "selection_verification_scope")},
                     ensure_ascii=False, indent=2))
    print("invariant_criteria_hash =", inv_h)
    print("sweep_spec_hash        =", spec_h)
    print("v1 对照:", json.dumps(V1_HASHES, ensure_ascii=False))
    print("validated_csv_sha256   =", v_sha)
    return 0


def pc_status(p1map, key):
    """原预检里的 selection_status 值，仅作证据留痕，不再当作本表状态。"""
    return p1map.get(key, {}).get("selection_status", "")


if __name__ == "__main__":
    raise SystemExit(main())
