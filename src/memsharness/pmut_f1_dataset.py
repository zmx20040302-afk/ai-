"""从真实 Table_9 生成首个可观测声压峰清单；不插值、不求解、不确认模态。"""
from __future__ import annotations

import csv
import ast
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
from scipy.io import loadmat

OBSERVATION = (0.0, 0.0, -1e-5)
FREQUENCIES = np.arange(5e6, 50e6 + 1, 0.5e6)


class DatasetError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def design_key(x, n1, n2) -> tuple[float, int, int]:
    values = tuple(float(v) for v in (x, n1, n2))
    if not all(math.isfinite(v) for v in values):
        raise DatasetError("Nonfinite design parameter")
    x, n1, n2 = values
    if n1 != int(n1) or n2 != int(n2) or not (5 <= n2 <= 9 and 1 <= n1 < n2):
        raise DatasetError("Invalid discrete design branch")
    if not 0.2 - 1e-12 <= x <= 1.0 + 1e-12:
        raise DatasetError("x outside frozen design domain")
    if abs(x * 100 - round(x * 100)) > 1e-8:
        raise DatasetError("Table is not on the registered 0.01 grid")
    return round(x, 2), int(n1), int(n2)


def first_local_peak(values) -> int | None:
    """复现历史 R1：最低频内点，左严格大、右大于等于；不细化峰频。"""
    a = np.asarray(values, dtype=float)
    if a.ndim != 1 or not np.isfinite(a).all():
        raise DatasetError("Peak search requires a complete finite spectrum")
    return next((i for i in range(1, len(a) - 1)
                 if a[i] > a[i - 1] and a[i] >= a[i + 1]), None)


def _column(headers: list[str], base: str, *, point: bool) -> int:
    matches = []
    for i, header in enumerate(headers):
        parts = header.split(", Point:", 1)
        if parts[0].strip() != base:
            continue
        if point:
            if len(parts) != 2:
                continue
            match = re.fullmatch(r"\s*\(([^()]+)\)\s*", parts[1])
            try:
                xyz = tuple(float(v.strip()) for v in match.group(1).split(",")) if match else ()
            except ValueError:
                xyz = ()
            if xyz != OBSERVATION:
                raise DatasetError("Wrong observation coordinates for " + base)
        elif len(parts) != 1:
            continue
        matches.append(i)
    if len(matches) != 1:
        raise DatasetError("Missing or ambiguous column: " + base)
    return matches[0]


def parse_table_arrays(headers, real, imag) -> list[dict]:
    """按列语义读取，复数列与独立 Re/Im 列交叉核对，保留原行号。"""
    headers = [str(h).strip() for h in np.asarray(headers).reshape(-1)]
    # N2=9 分块合并件把单元素字符串数组写成了字面量字符串；只解包这一明确形式。
    for i, header in enumerate(headers):
        if header.startswith("["):
            try:
                wrapped = ast.literal_eval(header)
            except (ValueError, SyntaxError) as exc:
                raise DatasetError("Invalid wrapped header") from exc
            if not isinstance(wrapped, list) or len(wrapped) != 1 or not isinstance(wrapped[0], str):
                raise DatasetError("Ambiguous wrapped header")
            headers[i] = wrapped[0]
    real, imag = np.asarray(real, float), np.asarray(imag, float)
    if real.ndim != 2 or real.shape != imag.shape or real.shape[1] != len(headers) or not len(real):
        raise DatasetError("Invalid table shape")
    params = [_column(headers, name, point=False) for name in ("x_scale", "N_w_te1", "N_w_te2")]
    duplicate_params = [_column(headers, name, point=True) for name in ("x_scale", "N_w_te1", "N_w_te2")]
    frequency = _column(headers, "freq (Hz)", point=False)
    re_col = _column(headers, "real(acpr.p_t) (Pa)", point=True)
    im_col = _column(headers, "imag(acpr.p_t) (Pa)", point=True)
    total_names = ["Total acoustic pressure (Pa)", "总声压 (Pa)"]
    present = [name for name in total_names if any(h.split(", Point:")[0].strip() == name for h in headers)]
    if len(present) != 1:
        raise DatasetError("Missing or ambiguous total pressure column")
    total = _column(headers, present[0], point=True)
    spl_names = ["Total sound pressure level (dB)", "总声压级 (dB)"]
    present = [name for name in spl_names if any(h.split(", Point:")[0].strip() == name for h in headers)]
    if len(present) != 1:
        raise DatasetError("Missing or ambiguous SPL column")
    spl = _column(headers, present[0], point=True)
    scalar_cols = params + duplicate_params + [frequency, re_col, im_col, spl]
    if not np.isfinite(real[:, scalar_cols]).all() or not np.isfinite(imag).all():
        raise DatasetError("Nonfinite raw observation; refusing partial peak selection")
    if not np.allclose(imag[:, scalar_cols], 0, rtol=0, atol=1e-12):
        raise DatasetError("Scalar expressions unexpectedly complex")
    if not np.allclose(real[:, params], real[:, duplicate_params], rtol=0, atol=1e-10):
        raise DatasetError("Repeated parameter columns disagree")
    pressure = real[:, re_col] + 1j * real[:, im_col]
    if not np.allclose(pressure, real[:, total] + 1j * imag[:, total], rtol=1e-12, atol=1e-12):
        raise DatasetError("Independent real/imag expressions disagree with complex pressure")
    # COMSOL 的 SPL 使用 RMS；此检查约束量纲、列布局和数据身份，不拟合/重标定真值。
    expected_spl = 20 * np.log10(np.maximum(np.abs(pressure), np.finfo(float).tiny) / (math.sqrt(2) * 20e-6))
    if not np.allclose(real[:, spl], expected_spl, rtol=0, atol=1e-6):
        raise DatasetError("SPL and complex pressure inconsistent")
    groups: dict[tuple, list[int]] = {}
    for i, row in enumerate(real):
        groups.setdefault(design_key(*row[params]), []).append(i)
    records = []
    for key, indices in sorted(groups.items()):
        order = sorted(indices, key=lambda i: real[i, frequency])
        freqs = real[order, frequency]
        if len(freqs) != 91 or not np.allclose(freqs, FREQUENCIES, rtol=0, atol=1e-6):
            raise DatasetError("Incomplete/duplicate/wrong frequency grid for %s" % (key,))
        peak = first_local_peak(real[order, spl])
        row = order[peak] if peak is not None else None
        p = pressure[row] if row is not None else None
        records.append({
            "case_id": "x%03d_N1%d_N2%d" % (round(key[0] * 100), key[1], key[2]),
            "x_scale": key[0], "N_w_te1": key[1], "N_w_te2": key[2],
            "source_type": "simulation", "observation_xyz_m": list(OBSERVATION),
            "field_expression": "acpr.p_t", "n_frequency_samples": 91,
            "first_observable_peak_found": peak is not None,
            "frequency_Hz": float(freqs[peak]) if peak is not None else None,
            "frequency_grid_index_1based": peak + 1 if peak is not None else None,
            "source_table_row_1based": row + 1 if row is not None else None,
            "p_point_real_Pa": float(p.real) if p is not None else None,
            "p_point_imag_Pa": float(p.imag) if p is not None else None,
            "p_point_abs_Pa": float(abs(p)) if p is not None else None,
            "mode_identity": "unverified", "training_ready": False,
            "frequency_semantics": "first_observable_pressure_peak_on_solved_grid_not_verified_f1",
        })
    return records


def read_table(path: Path) -> tuple[list[dict], dict]:
    before = sha256(path)
    mat = loadmat(path, simplify_cells=True)
    records = parse_table_arrays(mat["headers"], mat["realData"], mat["imagData"])
    if sha256(path) != before:
        raise DatasetError("Table changed during parsing")
    n2_values = sorted({row["N_w_te2"] for row in records})
    if len(n2_values) != 1:
        raise DatasetError("Expected one N2 layer per source table")
    n2 = n2_values[0]
    expected = {(round(.2 + .01 * i, 2), n1, n2) for i in range(81) for n1 in range(1, n2)}
    if {design_key(r["x_scale"], r["N_w_te1"], r["N_w_te2"]) for r in records} != expected:
        raise DatasetError("Incomplete design layer")
    source = {"path": str(path.resolve()), "sha256": before, "N_w_te2": n2,
              "n_rows": int(mat["realData"].shape[0]), "n_designs": len(records),
              "n_first_observable_peaks": sum(r["first_observable_peak_found"] for r in records),
              "source_model_sha256": None, "source_model_identity_verified": False,
              "lineage_alignment_pending": n2 == 9}
    for record in records:
        record.update(source_table_sha256=before, source_table_path=str(path.resolve()),
                      lineage_group="raw_table_" + before[:16], lineage_alignment_pending=n2 == 9)
    return records, source


def audit_labels(records: list[dict], path: Path) -> dict:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        labels = {}
        for row in csv.DictReader(handle):
            if row["source_dataset"] != "C":
                continue
            key = design_key(row["x_scale"], row["N_w_te1"], row["N_w_te2"])
            if key in labels:
                raise DatasetError("Duplicate historical label key")
            labels[key] = row
    seen, unmatched, mismatches = set(), 0, []
    for record in records:
        key = design_key(record["x_scale"], record["N_w_te1"], record["N_w_te2"])
        label = labels.get(key)
        record["historical_label_matched"] = label is not None
        record["quarantined"] = None if label is None else label["quarantined"].lower() == "true"
        record["reference_excitation"] = None if label is None else {
            "v_inner_V": float(label["v_inner_V"]), "v_outer_V": float(label["v_outer_V"]),
            "delta_V_V": float(label["delta_V_V"]), "source": "historical_label_metadata",
            "verified_against_stored_solution": False, "phase_verified": False,
        }
        if label is None:
            unmatched += 1
            continue
        seen.add(key)
        found = label["first_peak_found"].lower() == "true"
        if found != record["first_observable_peak_found"]:
            mismatches.append(record["case_id"] + ":peak_presence")
        elif found:
            for target, old in (("frequency_Hz", "f_peak_Hz"), ("p_point_real_Pa", "p_re_Pa"),
                                ("p_point_imag_Pa", "p_im_Pa"), ("p_point_abs_Pa", "abs_p_Pa")):
                if not math.isclose(record[target], float(label[old]), rel_tol=1e-12, abs_tol=1e-12):
                    mismatches.append(record["case_id"] + ":" + target)
    if mismatches or len(seen) != len(labels):
        raise DatasetError("Historical label audit failed: %s; unpaired=%d" % (mismatches[:5], len(labels) - len(seen)))
    return {"path": str(path.resolve()), "sha256": sha256(path), "n_matched": len(seen),
            "n_without_legacy_label": unmatched, "n_mismatches": len(mismatches)}


def load_solution_index(path: Path) -> tuple[dict, dict]:
    """以实际导出索引绑定 outer，不根据目录名或参数个数猜测。"""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    result, outer_to_key = {}, {}
    for row in rows:
        if row["kind"] != "pod20":
            continue
        key = design_key(row["x_scale"], row["N_w_te1"], row["N_w_te2"])
        if key[2] != 8 or float(row["freq_Hz"]) != 20e6 or int(row["inner_solnum"]) != 31:
            raise DatasetError("Unexpected stored-solution index semantics")
        outer = int(row["outer_solnum"])
        if outer <= 0 or key in result or outer in outer_to_key:
            raise DatasetError("Duplicate or invalid solution mapping")
        outer_to_key[outer] = key
        result[key] = {"outer_solnum": outer, "legacy_x_role": row["x_holdout_role"],
                       "legacy_n_role": row["n_holdout_role"]}
    if len(result) != 567 or set(outer_to_key) != set(range(1, 568)):
        raise DatasetError("Incomplete N2=8 solution index")
    return result, {"path": str(path.resolve()), "sha256": sha256(path), "n_mappings": len(result)}


def build_manifest(records: list[dict], mapping: dict, index_source: dict, *, pilot: bool) -> dict:
    cases = []
    for record in records:
        key = design_key(record["x_scale"], record["N_w_te1"], record["N_w_te2"])
        if key not in mapping or not record["first_observable_peak_found"]:
            continue
        if record.get("quarantined") is not False or record["lineage_alignment_pending"]:
            continue
        if pilot and key[0] not in (0.3, 0.6, 0.9):
            continue
        cases.append({**record, **mapping[key], "inner_solnum": record["frequency_grid_index_1based"],
                      "solution_identity": "candidate_requires_parameter_frequency_and_exact_point_pressure_readback",
                      "selection_role": "development_pilot_not_blind_test" if pilot else "candidate_only_not_run_list"})
    return {"schema": "memsharness.pmut_f1_export_manifest/v0", "dataset": "dset3",
            "field_expression": "acpr.p_t", "observation_xyz_m": list(OBSERVATION),
            "selection": "fixed_x_0.30_0.60_0.90_all_N1" if pilot else "all_eligible_N2_8_candidates",
            "index_source": index_source, "source_model_hash_verified": False,
            "exact_point_consistency_required": True,
            "point_comparison_rtol": 1e-6, "point_comparison_atol_Pa": 1e-9,
            "interpolation_used": False, "comsol_solve_requested": False,
            "training_ready": False, "cases": cases}


def build_inventory(tables: list[Path], labels: Path, solution_index: Path) -> tuple[dict, dict, dict]:
    all_records, sources, n2_seen = [], [], set()
    for table in tables:
        records, source = read_table(table)
        if source["N_w_te2"] in n2_seen:
            raise DatasetError("Multiple tables for the same layer; do not merge model lineages implicitly")
        n2_seen.add(source["N_w_te2"])
        all_records.extend(records)
        sources.append(source)
    label_audit = audit_labels(all_records, labels)
    mapping, index_source = load_solution_index(solution_index)
    summary = {"schema": "memsharness.pmut_f1_scalar_inventory/v0", "source_type": "simulation",
               "coverage_basis": "raw_files_parsed_and_hashed_not_solver_certification",
               "n_designs": len(all_records), "n_frequency_rows": sum(s["n_rows"] for s in sources),
               "n_first_observable_peaks": sum(r["first_observable_peak_found"] for r in all_records),
               "n_mode_identity_verified": 0, "sources": sources, "historical_label_audit": label_audit,
               "operator_training_status": "not_trained", "release_allowed": False,
               "records": all_records}
    return summary, build_manifest(all_records, mapping, index_source, pilot=False), build_manifest(all_records, mapping, index_source, pilot=True)


def write_new_json(path: Path, value: dict) -> None:
    """只建新证据文件，拒绝覆盖历史。"""
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
