from __future__ import annotations

import csv
import json

import numpy as np
import pytest

from memsharness.pmut_f1_dataset import (
    DatasetError, FREQUENCIES, audit_labels, build_manifest, design_key,
    first_local_peak, load_solution_index, parse_table_arrays, write_new_json,
)


def table(peak=True):
    point = ", Point: (0, 0, -1E-5)"
    headers = ["x_scale", "N_w_te1", "N_w_te2", "freq (Hz)",
               "real(acpr.p_t) (Pa)" + point, "imag(acpr.p_t) (Pa)" + point,
               "Total acoustic pressure (Pa)" + point, "Total sound pressure level (dB)" + point,
               "x_scale" + point, "N_w_te1" + point, "N_w_te2" + point]
    real, imag = np.zeros((91, 11)), np.zeros((91, 11))
    real[:, [0, 8]], real[:, [1, 9]], real[:, [2, 10]] = .6, 4, 8
    real[:, 3] = FREQUENCIES
    amplitude = np.concatenate((np.arange(1, 22), np.linspace(20, 1, 70))) if peak else np.arange(1, 92)
    pressure = amplitude * (1 + 2j)
    real[:, 4], real[:, 5] = pressure.real, pressure.imag
    real[:, 6], imag[:, 6] = pressure.real, pressure.imag
    real[:, 7] = 20 * np.log10(np.abs(pressure) / (np.sqrt(2) * 20e-6))
    return headers, real, imag


def test_complex_truth_exact_point_and_solved_frequency_not_interpolation():
    record, = parse_table_arrays(*table())
    assert record["frequency_Hz"] == 15e6
    assert record["frequency_grid_index_1based"] == 21
    assert record["source_table_row_1based"] == 21
    assert record["p_point_real_Pa"] == 21
    assert record["p_point_imag_Pa"] == 42
    assert record["mode_identity"] == "unverified"
    assert record["training_ready"] is False


def test_no_local_peak_does_not_get_endpoint_or_zero_pressure():
    record, = parse_table_arrays(*table(False))
    assert not record["first_observable_peak_found"]
    assert record["frequency_Hz"] is None
    assert record["p_point_real_Pa"] is None


def test_sort_by_frequency_preserves_original_source_row():
    h, r, i = table()
    record, = parse_table_arrays(h, r[::-1], i[::-1])
    assert record["frequency_Hz"] == 15e6
    assert record["source_table_row_1based"] == 71


@pytest.mark.parametrize("fault", ["wrong_point", "wrong_complex", "wrong_duplicate_param", "duplicate_freq", "nan", "wrong_spl", "scalar_imag"])
def test_corrupt_raw_data_fails_closed(fault):
    h, r, i = table()
    if fault == "wrong_point":
        h[4] = h[4].replace("-1E-5", "1E-5")
    elif fault == "wrong_complex":
        i[0, 6] += 1
    elif fault == "wrong_duplicate_param":
        r[0, 8] += .01
    elif fault == "duplicate_freq":
        r[0, 3] = r[1, 3]
    elif fault == "nan":
        r[0, 4] = float("nan")
    elif fault == "wrong_spl":
        r[0, 7] += .1
    else:
        i[0, 4] = 1
    with pytest.raises(DatasetError):
        parse_table_arrays(h, r, i)


def test_columns_can_be_reordered_without_changing_physics():
    h, r, i = table()
    order = list(reversed(range(len(h))))
    assert parse_table_arrays([h[k] for k in order], r[:, order], i[:, order]) == parse_table_arrays(h, r, i)


def test_chunked_n2_9_singleton_wrapped_headers():
    h, r, i = table()
    assert parse_table_arrays([repr([v]) for v in h], r, i) == parse_table_arrays(h, r, i)


def test_first_peak_not_global_max_and_plateau_policy():
    assert first_local_peak([1, 3, 2, 10, 1]) == 1
    assert first_local_peak([1, 3, 3, 1]) == 1
    assert first_local_peak([3, 2, 1]) is None


@pytest.mark.parametrize("args", [(0.605, 4, 8), (.6, 4.5, 8), (.6, 8, 8), (float("nan"), 4, 8)])
def test_bad_designs_rejected(args):
    with pytest.raises(DatasetError):
        design_key(*args)


def test_actual_index_mapping_is_used_not_old_stride_eight(tmp_path):
    path = tmp_path / "index.tsv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["kind", "x_scale", "N_w_te1", "N_w_te2", "freq_Hz", "inner_solnum", "outer_solnum", "x_holdout_role", "n_holdout_role"], delimiter="\t")
        writer.writeheader()
        for xi in range(81):
            for n1 in range(1, 8):
                writer.writerow(dict(kind="pod20", x_scale=.2+.01*xi, N_w_te1=n1, N_w_te2=8,
                                     freq_Hz=20e6, inner_solnum=31, outer_solnum=xi*7+n1,
                                     x_holdout_role="train", n_holdout_role="train"))
    mapping, source = load_solution_index(path)
    assert mapping[(.21, 1, 8)]["outer_solnum"] == 8
    assert mapping[(.95, 6, 8)]["outer_solnum"] == 531
    assert source["n_mappings"] == 567


def test_manifest_does_not_admit_quarantine_or_other_lineage():
    record, = parse_table_arrays(*table())
    record.update(quarantined=False, lineage_alignment_pending=False)
    mapping = {(.6, 4, 8): {"outer_solnum": 284}}
    manifest = build_manifest([record], mapping, {}, pilot=True)
    assert len(manifest["cases"]) == 1
    assert manifest["cases"][0]["inner_solnum"] == 21
    assert manifest["training_ready"] is False
    for changes in [dict(quarantined=True), dict(quarantined=None), dict(lineage_alignment_pending=True)]:
        assert not build_manifest([{**record, **changes}], mapping, {}, pilot=True)["cases"]


def test_duplicate_legacy_labels_fail(tmp_path):
    path = tmp_path / "labels.csv"
    path.write_text("source_dataset,x_scale,N_w_te1,N_w_te2\nC,0.6,4,8\nC,0.6,4,8\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="Duplicate"):
        audit_labels([], path)


def test_evidence_is_append_only(tmp_path):
    path = tmp_path / "evidence.json"
    write_new_json(path, {"ok": True})
    with pytest.raises(FileExistsError):
        write_new_json(path, {"ok": False})
    assert json.loads(path.read_text())["ok"] is True
