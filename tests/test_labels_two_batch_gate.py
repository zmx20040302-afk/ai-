# -*- coding: utf-8 -*-
"""并集表**产出路径**上的 fail-closed 门禁用例（`scripts/labels_two_batch.py`）。

守的是 2026-10-08 第 5 项待办与注入稿 R2 的同一纪律：**门禁判定必须被执行并落痕，
且不得被复述成通过**。三条最低覆盖：

1. 门禁**未通过** ⇒ 产出脚本**非零退出**，且产物内 `gate.release_allowed=false`
   （产物**仍然存在**，用于诊断；**不去重、不过滤**）；
2. 门禁**通过** ⇒ 退出码 0（⚠️ 2026-10-08 收紧后，本脚本产出的表**结构上到不了** `passed`：
   C 批原表没有原始删失/截断列 ⇒ 该批**整列为空** ⇒ 那一项判「无法判定」；收紧见 §96）；
3. `inconclusive` **不等于**通过 ⇒ 退出码同样非零。

外加：`freq_range_MHz`（批次声明）与 `freq_grid_MHz`（逐行真实栅格）**两个口径都要跑**，
**以更严重者决定退出码**（只收紧、不放松）。

夹具全部是合成数据，落在 `tmp_path`，**不触碰仓库里的真实产物**。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))

from _subproc import out_of, run_py  # noqa: E402

SCRIPT = REPO / "scripts" / "labels_two_batch.py"

C_FIELDS = ["x_scale", "N_w_te1", "N_w_te2", "f_peak_Hz", "bandwidth_Hz", "Q_factor",
            "damping_ratio", "peak_closed", "ranking_eligible", "peak_SPL_dB",
            "source_dataset", "x_density_class", "freq_grid_MHz", "n_freq", "source_model"]

V2_FIELDS = ["cell", "x_scale", "N_w_te1", "N_w_te2", "n_freq", "freq_min_Hz", "freq_max_Hz",
             "peak_freq_Hz", "peak_spl_dB", "peak_at_scan_endpoint", "bw_f_lo_Hz",
             "bw_f_hi_Hz", "bandwidth_Hz", "Q", "zeta", "bw_upper_cutoff_at_endpoint"]


def _write(path: Path, fields, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    return path


def c_row(x, n1, n2, grid="5-50/91", dataset="C", **kw) -> dict:
    d = {"x_scale": x, "N_w_te1": n1, "N_w_te2": n2, "f_peak_Hz": "20000000.0",
         "bandwidth_Hz": "5000000.0", "Q_factor": "3.0", "damping_ratio": "0.166",
         "peak_closed": "True", "ranking_eligible": "True", "peak_SPL_dB": "150.0",
         "source_dataset": dataset,
         "x_density_class": "coarse_0.1" if dataset == "A" else "fine_0.01",
         "freq_grid_MHz": grid,
         "n_freq": grid.split("/")[-1], "source_model": "model/%s" % dataset}
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


def _fixtures(tmp_path: Path, c_rows, v2_rows) -> tuple[Path, Path]:
    return (_write(tmp_path / "c.csv", C_FIELDS, c_rows),
            _write(tmp_path / "v2_frozen.csv", V2_FIELDS, v2_rows))


def _run(tmp_path: Path, c_rows, v2_rows, outdir: Path):
    cp, vp = _fixtures(tmp_path, c_rows, v2_rows)
    return run_py(SCRIPT, "--old-c", cp, "--v2", vp, "--out-dir", outdir,
                  "--prev-union", tmp_path / "no_such_prev_union.csv")


def _version(outdir: Path) -> dict:
    vs = sorted(outdir.glob("VERSION_*.json"))
    assert len(vs) == 1, "应恰好产出一个 VERSION_*.json，实得 %s" % vs
    return json.loads(vs[0].read_text(encoding="utf-8"))


# --------------------------------------------------------------- 无法判定（不放行）
def test_clean_two_batches_with_one_grid_each_is_not_passed_due_to_blank_flag_column(tmp_path):
    """两批各一个栅格、组合互不重叠 ⇒ **没有 failed 项**，但**仍不放行**：退出码 4。

    2026-10-08 收紧后：批次 C 原表**没有**原始删失/截断列（脚本按红线留空不倒填）⇒
    C 批那两列**整列为空** ⇒ `batch_censored_not_eligible` 判**无法判定**（空列 ≠ 通过）。
    ⇒ 本脚本产出的并集表**结构上不可能**再拿到 `passed`（这是收紧的正确后果，不是故障）。
    """
    out = tmp_path / "out"
    r = _run(tmp_path, [c_row("0.4", "1", "6"), c_row("0.5", "1", "6")],
             [v2_row("0.6", "1", "9"), v2_row("0.7", "1", "9")], out)
    assert r.returncode == 4, out_of(r)
    v = _version(out)
    assert v["gate"]["release_allowed"] is False
    assert v["gate"]["worst_verdict"] == "inconclusive"
    for tag in ("declared", "row_grid"):
        g = v["gate"]["runs"][tag]["verdict"]
        assert g["verdict"] == "inconclusive", (tag, g["reason"])
        assert g["n_failed"] == 0, (tag, g["reason"])
        # 唯一的不可判定项就是那一项，且 reason 指名了整列为空的批
        inc = [c["name"] for c in g["checks"] if c["passed"] is None]
        assert inc == ["batch_censored_not_eligible"], inc
        chk = [c for c in g["checks"] if c["name"] == "batch_censored_not_eligible"][0]
        assert chk["detail"]["blank_batches"] == ["c_5-50mhz"], chk["detail"]
        assert "整列为空" in chk["reason"] and "空列 ≠ 通过" in chk["reason"]


# --------------------------------------------------------------- 判失败
def test_failed_gate_exits_nonzero_and_marks_not_released(tmp_path):
    """C 批一行一个栅格 ⇒ `row_grid` 口径判 failed ⇒ **非零退出**且产物标注不放行。

    同时锁定：**产物仍然写出**（不去重、不过滤任何行），便于诊断。
    """
    out = tmp_path / "out"
    crows = [c_row("0.4", "1", "6", grid="5-50/91"),
             c_row("0.5", "1", "6", grid="5-35/61", dataset="A")]
    r = _run(tmp_path, crows, [v2_row("0.6", "1", "9")], out)
    assert r.returncode != 0, out_of(r)
    assert r.returncode == 3, out_of(r)
    v = _version(out)
    assert v["gate"]["release_allowed"] is False
    assert v["gate"]["runs"]["row_grid"]["verdict"]["verdict"] == "failed"
    # declared 口径（批次声明 5-50/5-35）**没有 failed 项**，但因 C 批原始标志列整列为空
    # ⇒ 该口径判 inconclusive（2026-10-08 收紧；**不是** passed）。两套判定都要原样落痕。
    declared = v["gate"]["runs"]["declared"]["verdict"]
    assert declared["verdict"] == "inconclusive", declared["reason"]
    assert declared["n_failed"] == 0, declared["reason"]
    assert [c["name"] for c in declared["checks"] if c["passed"] is None] == \
        ["batch_censored_not_eligible"]
    # 产物保留且**一行不少**
    csvp = out / "labels_two_batch.csv"
    assert csvp.exists()
    rows = list(csv.DictReader(csvp.open("r", encoding="utf-8", newline="")))
    assert len(rows) == len(crows) + 1
    assert v["deduplicated"] is False
    assert "未做去重" in v["dedup_note"]


def test_missing_censor_columns_would_be_inconclusive_but_table_provides_them(tmp_path):
    """产出脚本**必须**写出原始删失/截断列；C 侧即使有列也**整列为空** ⇒ 判不了（退出码 4）。

    2026-10-08 收紧前这里判 passed / 退出码 0（**假通过**）；现在 C 侧整列为空 ⇒
    `batch_censored_not_eligible` = inconclusive。本用例同时锁住「原始标志列必须保留」。
    """
    out = tmp_path / "out"
    r = _run(tmp_path, [c_row("0.4", "1", "6")], [v2_row("0.6", "1", "9")], out)
    assert r.returncode == 4, out_of(r)
    cols = _version(out)["columns"]
    for c in ("peak_at_scan_endpoint", "bw_upper_cutoff_at_endpoint"):
        assert c in cols, "原始标志列必须保留：%s" % c
    rows = list(csv.DictReader((out / "labels_two_batch.csv").open("r", encoding="utf-8",
                                                                  newline="")))
    cside = [x for x in rows if x["batch"] == "C_5-50MHz"]
    assert all(x["peak_at_scan_endpoint"] == "" for x in cside), \
        "C 侧没有原始列 ⇒ 必须留空，**不得用派生值倒填**"
    v2side = [x for x in rows if x["batch"] == "V2_5-35MHz"]
    assert v2side[0]["peak_at_scan_endpoint"] == "False"
    chk = [c for c in _version(out)["gate"]["runs"]["declared"]["verdict"]["checks"]
           if c["name"] == "batch_censored_not_eligible"][0]
    assert chk["passed"] is None, chk["reason"]
    assert chk["detail"]["blank_batches"] == ["c_5-50mhz"], chk["detail"]


# --------------------------------------------------------------- 无法判定
def test_inconclusive_gate_also_exits_nonzero(tmp_path):
    """跨批同组合 ⇒ `inconclusive`（判不了）⇒ **仍然非零退出**（inconclusive ≠ 通过）。"""
    out = tmp_path / "out"
    r = _run(tmp_path, [c_row("0.5", "1", "6")], [v2_row("0.5", "1", "6")], out)
    assert r.returncode == 4, out_of(r)
    v = _version(out)
    assert v["gate"]["release_allowed"] is False
    assert v["gate"]["worst_verdict"] == "inconclusive"
    assert "不是通过" in out_of(r) or "inconclusive" in out_of(r)


def test_missing_input_is_input_error_not_success(tmp_path):
    """输入不可用 ⇒ 退出码 2（**不得**当 0 处理）。"""
    out = tmp_path / "out"
    r = run_py(SCRIPT, "--old-c", tmp_path / "nope.csv",
               "--v2", tmp_path / "nope_v2.csv", "--out-dir", out)
    assert r.returncode == 2, out_of(r)
    assert not out.exists() or not list(out.glob("VERSION_*.json"))


# --------------------------------------------------------------- 产物自洽
def test_version_records_hashes_and_gate_verbatim(tmp_path):
    """VERSION 必须带逐文件 sha256，且 `gate` 字段是**原样**判定（不美化）。

    退出码 4（不是 0）：C 批原始标志列整列为空 ⇒ `batch_censored_not_eligible` 判不了
    （2026-10-08 收紧）。本用例只关心哈希落痕与 `gate` 的**原样**性。
    """
    import hashlib
    out = tmp_path / "out"
    r = _run(tmp_path, [c_row("0.4", "1", "6")], [v2_row("0.6", "1", "9")], out)
    assert r.returncode == 4, out_of(r)
    v = _version(out)
    csvp = out / "labels_two_batch.csv"
    assert v["outputs"]["labels_two_batch.csv"]["sha256"] == \
        hashlib.sha256(csvp.read_bytes()).hexdigest()
    for k in ("c_batch_source", "v2_frozen"):
        assert len(v["inputs"][k]["sha256"]) == 64
    assert v["gate"]["no_relaxation"]
    assert v["gate"]["release_allowed"] is (v["gate"]["runs"]["declared"]
                                            ["verdict"]["release_allowed"])
