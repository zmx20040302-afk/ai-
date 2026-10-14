# -*- coding: utf-8 -*-
"""并集表 **v3**（批次标签改一批一栅格）与去重选项评估的用例。

守的是本轮工单的三条纪律：

1. **标签错 ≠ 门禁松**：同一份夹具，v2 脚本（旧标签：两套栅格同批）判 `row_grid=failed`，
   v3 脚本（新标签：一批一栅格）**该项不再 failed** —— **两脚本调用的是同一个门禁函数**
   （`memsharness.sweep_analysis.check_batch_isolation`），所以差别只可能来自标签；
   同时 v3 仍**不放行**：跨批重叠时 `inconclusive`，而 2026-10-08 收紧后
   **C/A 侧原始标志列整列为空**这一条也判「无法判定」（空列 ≠ 通过，见 §96）。
2. **不改历史**：v3 表保留 v2 的 26 列（名称 + 顺序）并把上一版 `batch` / `freq_range_MHz`
   逐行留在 `batch_v2_original` / `freq_range_v2_original`；C/A 侧原始删失/截断列**留空不倒填**。
3. **不猜、不去重**：子批两字段判据冲突 ⇒ 退出码 2 且不出表；去重选项脚本
   **不改输入表一字节**、`executed=false`。

夹具全部是合成数据，落在 `tmp_path`，不触碰仓库真实产物。
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))

from _subproc import out_of, run_py  # noqa: E402

V3 = REPO / "scripts" / "labels_two_batch_v3.py"
V2 = REPO / "scripts" / "labels_two_batch.py"
DUPOPT = REPO / "scripts" / "labels_dup_options.py"

C_FIELDS = ["x_scale", "N_w_te1", "N_w_te2", "f_peak_Hz", "bandwidth_Hz", "Q_factor",
            "damping_ratio", "peak_closed", "ranking_eligible", "peak_SPL_dB",
            "source_dataset", "x_density_class", "freq_grid_MHz", "n_freq", "source_model"]

V2_FIELDS = ["cell", "x_scale", "N_w_te1", "N_w_te2", "n_freq", "freq_min_Hz", "freq_max_Hz",
             "peak_freq_Hz", "peak_spl_dB", "peak_at_scan_endpoint", "bw_f_lo_Hz",
             "bw_f_hi_Hz", "bandwidth_Hz", "Q", "zeta", "bw_upper_cutoff_at_endpoint"]

#: v2 并集表的 26 列（顺序即契约）
V2_UNION_COLUMNS = [
    "batch", "source_file", "x_scale", "N_w_te1", "N_w_te2", "freq_range_MHz",
    "peak_freq_Hz", "bandwidth_Hz", "Q", "zeta", "spl_dB", "peak_closed",
    "ranking_eligible", "usable", "source_type", "source_pipeline", "source_dataset",
    "x_density_class", "freq_grid_MHz", "n_freq", "source_model",
    "peak_at_scan_endpoint", "bw_upper_cutoff_at_endpoint", "dup_score", "dup_of",
    "dup_kind",
]
V3_EXTRA_COLUMNS = ["batch_v2_original", "freq_range_v2_original", "batch_basis",
                    "freq_range_source"]


def _write(path: Path, fields, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    return path


def c_row(x, n1, n2, grid=None, dataset="C", **kw) -> dict:
    if grid is None:                       # 缺省与 dataset 自洽（A ⇒ 5-35/61）
        grid = "5-35/61" if dataset == "A" else "5-50/91"
    d = {"x_scale": x, "N_w_te1": n1, "N_w_te2": n2, "f_peak_Hz": "20000000.0",
         "bandwidth_Hz": "5000000.0", "Q_factor": "3.0", "damping_ratio": "0.166",
         "peak_closed": "True", "ranking_eligible": "True", "peak_SPL_dB": "150.0",
         "source_dataset": dataset,
         "x_density_class": "coarse_0.1" if dataset == "A" else "fine_0.01",
         "freq_grid_MHz": grid, "n_freq": grid.split("/")[-1],
         "source_model": "model/%s" % dataset}
    d.update(kw)
    return d


def v2_row(x, n1, n2, *, peak_endpoint="False", bw_endpoint="False", **kw) -> dict:
    d = {"cell": "te2_9", "x_scale": x, "N_w_te1": n1, "N_w_te2": n2, "n_freq": "61",
         "freq_min_Hz": "5000000.0", "freq_max_Hz": "35000000.0",
         "peak_freq_Hz": "22000000.0", "peak_spl_dB": "160.0",
         "peak_at_scan_endpoint": peak_endpoint, "bw_f_lo_Hz": "15000000.0",
         "bw_f_hi_Hz": "30000000.0", "bandwidth_Hz": "15000000.0", "Q": "1.47",
         "zeta": "0.34", "bw_upper_cutoff_at_endpoint": bw_endpoint}
    d.update(kw)
    return d


def _fixtures(tmp_path: Path, c_rows, v2_rows):
    return (_write(tmp_path / "c.csv", C_FIELDS, c_rows),
            _write(tmp_path / "v2_frozen.csv", V2_FIELDS, v2_rows))


def _run_v3(tmp_path, c_rows, v2_rows, outdir, *extra):
    cp, vp = _fixtures(tmp_path, c_rows, v2_rows)
    return run_py(V3, "--old-c", cp, "--v2", vp, "--out-dir", outdir,
                  "--prev-union", tmp_path / "no_such_prev.csv",
                  "--prev-version", tmp_path / "no_such_version.json", *extra)


def _version(outdir: Path) -> dict:
    vs = sorted(outdir.glob("VERSION_*.json"))
    assert len(vs) == 1, "应恰好产出一个 VERSION_*.json，实得 %s" % vs
    return json.loads(vs[0].read_text(encoding="utf-8"))


def _rows(outdir: Path) -> list:
    return list(csv.DictReader((outdir / "labels_two_batch.csv").open(
        "r", encoding="utf-8", newline="")))


# ------------------------------------------------------- 标签修正的实质效果
def test_same_fixture_v2_fails_but_v3_is_not_failed_because_labels_were_wrong(tmp_path):
    """同一夹具：v2 旧标签判 `row_grid=failed`；v3 新标签**该项不再 failed**。

    这条用例是「**这不是门禁放宽**」的机器证据：两个脚本调用**同一个**
    `check_batch_isolation`，夹具逐字节相同，唯一差别是批次标签。

    ⚠️ 2026-10-08 收紧后：v3 的 `row_grid` 判 `inconclusive`（**不是** `passed`）——
    因为 C/A 侧原表没有原始删失/截断列 ⇒ 该两批**整列为空** ⇒
    `batch_censored_not_eligible` 判「无法判定」（空列 ≠ 通过）。变的是那一项的**假通过**，
    不是标签的作用：`batch_single_range` 那一项由 v2 的 failed 变为 v3 的 passed 依旧成立。
    """
    crows = [c_row("0.4", "1", "6", grid="5-50/91", dataset="C"),
             c_row("0.5", "1", "6", grid="5-35/61", dataset="A")]
    vrows = [v2_row("0.6", "1", "9")]

    out2 = tmp_path / "out_v2"
    cp, vp = _fixtures(tmp_path, crows, vrows)
    r2 = run_py(V2, "--old-c", cp, "--v2", vp, "--out-dir", out2,
                "--prev-union", tmp_path / "no_such_prev.csv")
    assert r2.returncode == 3, out_of(r2)
    v2v = _version(out2)
    assert v2v["gate"]["runs"]["row_grid"]["verdict"]["verdict"] == "failed"

    out3 = tmp_path / "out_v3"
    r3 = _run_v3(tmp_path, crows, vrows, out3)
    assert r3.returncode == 4, out_of(r3)
    v3v = _version(out3)
    for tag in ("declared", "row_grid"):
        g = v3v["gate"]["runs"][tag]["verdict"]
        assert g["verdict"] == "inconclusive", (tag, g["reason"])
        assert g["n_failed"] == 0, (tag, g["reason"])
    assert v3v["gate"]["release_allowed"] is False
    # 标签的作用仍在：`batch_single_range` 类检查项在 v3 全 PASS（v2 的 row_grid 是 failed）
    row_grid = v3v["gate"]["runs"]["row_grid"]["verdict"]["checks"]
    assert all(c["passed"] is True for c in row_grid
               if c["name"].startswith("batch_single_range")), row_grid
    # 唯一判不了的是「整列为空」那一项，且 reason 指名批
    inc = [c["name"] for c in row_grid if c["passed"] is None]
    assert inc == ["batch_censored_not_eligible"], inc
    blank = [c for c in row_grid if c["name"] == "batch_censored_not_eligible"][0]
    assert sorted(blank["detail"]["blank_batches"]) == ["a_5-35mhz", "c_5-50mhz"]
    assert "空列 ≠ 通过" in blank["reason"]
    # 门禁函数未改：判定口径仍复用 evaluate_s3，且 sha256 落痕
    assert v3v["gate"]["verdict_function"].endswith("evaluate_s3（未另造一套）")
    assert len(v3v["gate"]["gate_function_sha256"]) == 64
    # v2 表仍是 C_5-50MHz 混两栅格；v3 表已一批一栅格（逐行自证）
    assert v3v["verification"]["one_grid_per_batch"] == {
        "A_5-35MHz": True, "C_5-50MHz": True, "V2_5-35MHz": True}



def test_cross_batch_overlap_still_not_released(tmp_path):
    """有跨批同组合 ⇒ 仍 `inconclusive`、`release_allowed=False`、退出码 4（不等于通过）。"""
    out = tmp_path / "out"
    r = _run_v3(tmp_path, [c_row("0.5", "1", "6", dataset="C")],
                [v2_row("0.5", "1", "6")], out)
    assert r.returncode == 4, out_of(r)
    v = _version(out)
    assert v["gate"]["release_allowed"] is False
    assert v["gate"]["worst_verdict"] == "inconclusive"
    assert "不是通过" in out_of(r)


# ------------------------------------------------------- 列契约与「不改历史」
def test_columns_v2_prefix_kept_and_old_labels_traced(tmp_path):
    """v2 的 26 列名称与顺序原样保留、新列追加在后；旧标签逐行留痕。

    退出码 4（2026-10-08 收紧后）：A 批原始标志列整列为空 ⇒
    `batch_censored_not_eligible` 判不了；本用例只关心列契约与留痕。
    """
    out = tmp_path / "out"
    r = _run_v3(tmp_path, [c_row("0.5", "1", "6", dataset="A")],
                [v2_row("0.6", "1", "9")], out)
    assert r.returncode == 4, out_of(r)
    v = _version(out)
    assert v["columns"][:26] == V2_UNION_COLUMNS
    assert v["columns"][26:] == V3_EXTRA_COLUMNS
    rows = _rows(out)
    a = [x for x in rows if x["batch"] == "A_5-35MHz"]
    assert len(a) == 1
    assert a[0]["batch_v2_original"] == "C_5-50MHz"      # 上一版标签留痕
    assert a[0]["freq_range_v2_original"] == "5-50"      # 上一版声明留痕
    assert a[0]["freq_range_MHz"] == "5-35"              # 本版逐行真实值
    assert a[0]["freq_grid_MHz"] == "5-35/61"
    assert a[0]["freq_range_source"] == "freq_grid_MHz"
    assert a[0]["batch_basis"] == "source_dataset=A"
    # C/A 侧没有原始删失/截断列 ⇒ 必须留空（不得倒填派生 usable）
    for x in rows:
        if x["batch"] in ("A_5-35MHz", "C_5-50MHz"):
            assert x["peak_at_scan_endpoint"] == ""
            assert x["bw_upper_cutoff_at_endpoint"] == ""
    for col in ("peak_at_scan_endpoint", "bw_upper_cutoff_at_endpoint",
                "freq_range_MHz", "source_pipeline"):
        assert v["verification"]["required_columns_present"][col] is True


def test_numeric_identity_merges_1_and_1_0(tmp_path):
    """跨批重叠必须按**数值**判等：C 侧字面 `1.0` 与 v2 侧字面 `1` 是同一组合。"""
    out = tmp_path / "out"
    r = _run_v3(tmp_path, [c_row("0.5", "1.0", "6.0", dataset="C")],
                [v2_row("0.5", "1", "6")], out)
    assert r.returncode == 4, out_of(r)
    v = _version(out)
    chk = [c for c in v["gate"]["runs"]["declared"]["verdict"]["checks"]
           if c["name"] == "batch_no_cross_batch_combo"][0]
    assert chk["detail"]["n_overlap_normalized"] == 1, chk["detail"]


# ------------------------------------------------------- 不猜 / fail-closed
def test_conflicting_sub_batch_evidence_is_input_error(tmp_path):
    """`source_dataset=A` 与 `freq_grid_MHz=5-50/91` 冲突 ⇒ **不猜**，退出码 2，不出表。"""
    out = tmp_path / "out"
    r = _run_v3(tmp_path, [c_row("0.5", "1", "6", grid="5-50/91", dataset="A")],
                [v2_row("0.6", "1", "9")], out)
    assert r.returncode == 2, out_of(r)
    assert not (out / "labels_two_batch.csv").exists()
    assert "不猜" in out_of(r) or "冲突" in out_of(r)


def test_row_count_expectation_mismatch_is_input_error(tmp_path):
    """自校验（期望行数）不成立 ⇒ 退出码 2，但**产物保留**并如实标注。"""
    out = tmp_path / "out"
    r = _run_v3(tmp_path, [c_row("0.5", "1", "6", dataset="A")],
                [v2_row("0.6", "1", "9")], out,
                "--expect-rows", "9999", "--expect-a-rows", "1")
    assert r.returncode == 2, out_of(r)
    v = _version(out)
    assert v["verification"]["passed"] is False
    assert v["exit_code"] == 2
    assert (out / "labels_two_batch.csv").exists()


def test_overlap_composition_written_and_consistent(tmp_path):
    """重叠构成报告必须落盘，且 `A∩C` 与「旧 C 标签的 162」同源可核。"""
    out = tmp_path / "out"
    r = _run_v3(tmp_path, [c_row("0.4", "1", "6", dataset="C"),
                           c_row("0.4", "1", "6", dataset="A",
                                 grid="5-35/61")],
                [v2_row("0.4", "1", "6")], out)
    assert r.returncode == 4, out_of(r)
    comp = json.loads((out / "overlap_composition.json").read_text(encoding="utf-8"))
    assert comp["pairwise_overlap"]["A_5-35MHz|C_5-50MHz"] == 1
    assert comp["classes_by_batches_involved"] == {
        "A_5-35MHz+C_5-50MHz+V2_5-35MHz": 1}
    assert comp["n_combos_in_two_or_more_batches"] == 1
    assert comp["old_167_attribution"]["sum_check"] == 1
    assert (out / "overlap_composition.md").exists()


# ------------------------------------------------------- 去重选项：只出选项
def test_dedup_options_does_not_touch_the_table(tmp_path):
    """选项评估脚本**不得改动输入表**（逐字节哈希不变），且自称 `executed=false`。"""
    out = tmp_path / "out"
    r = _run_v3(tmp_path, [c_row("0.4", "1", "6", dataset="C"),
                           c_row("0.4", "1", "6", dataset="A", grid="5-35/61")],
                [v2_row("0.4", "1", "6")], out)
    assert r.returncode == 4, out_of(r)
    table = out / "labels_two_batch.csv"
    before = hashlib.sha256(table.read_bytes()).hexdigest()
    r2 = run_py(DUPOPT, "--table", table, "--out-dir", out)
    assert r2.returncode == 0, out_of(r2)
    assert hashlib.sha256(table.read_bytes()).hexdigest() == before
    payload = json.loads((out / "dedup_options.json").read_text(encoding="utf-8"))
    assert payload["executed"] is False
    assert payload["options"] and all(o["n_dropped_rows"] >= 0 for o in payload["options"])
    # 每组合留一行的两条规则必须真的把「重复余量」减到 0
    for o in payload["options"]:
        if o["rule_id"] in ("O-B", "O-C"):
            assert o["n_kept_rows"] == o["n_unique_combos"]
    assert "不执行" in (out / "dedup_options.md").read_text(encoding="utf-8")
