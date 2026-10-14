# -*- coding: utf-8 -*-
"""回归靶：新导出（te2_9 v1，5–50 MHz）vs v2 参照（5–35 MHz）在**重叠频点**上逐组合逐频点比 SPL。

判据（fail-closed）
------------------
* 阈值 **1e-3 dB**（`--tol-db`）。任一点 `|Δ| > 阈值` ⇒ **非零退出（5）**，绝不"报告一下就算了"；
* **重叠组合数 / 重叠频点数 / 重叠点数**三项都如实报出，并可用
  `--expect-overlap-combos 72 --expect-overlap-freqs 61 --expect-overlap-points 4392` 把它钉死；
* 重叠点**缺一个**（某组合在某重叠频点上没有数据）⇒ 结构性问题，非零退出（4）——
  缺的点不会被悄悄跳过;
* v2 侧解析结果与**冻结标签 CSV**（`v2_labels_frozen_20261008T143151.csv`）逐行对账
  （峰值频率/峰值 SPL/两个原始标志/Q/带宽），对不上 ⇒ 非零退出（4）：
  回归靶必须比的是**注册过的** v2 数值，不是"我再算一遍"的 v2。

退出码：0 通过｜2 用法错误｜3 产物未到位｜4 结构性失败（无重叠/缺点/v2 对不上账）｜5 超阈值｜6 与声明的期望不符。

只读：v2 目录与冻结 CSV 一律只读引用；输出只落 `--out-dir`。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from parse_te29_v1 import (  # noqa: E402
    REPO, combo_key_str, find_cell_dir, parse_export,
)

V2_DIR_DEFAULT = (REPO / "work/runs/remote-exported-v2-20260922/exported_results_v2"
                  / "cell_te2_9_test_v2_20260922_195327416_001")
V2_LABELS_DEFAULT = (REPO / "work/runs/remote-exported-v2-20260922"
                     / "v2_labels_frozen_20261008T143151.csv")
V2_LABELS_SHA256 = "cdf11ce2fe560fd9630463f5ad407d2da068051109c4b7a91f42c23e73fb4b31"
V2_CELL = "te2_9"

# v2 侧期望的重叠口径（本机实测：x=0.2..1.0 步长 0.1 的 9 值 × N1 1..8；5–35 MHz 步长 0.5 的 61 点）
EXPECT_OVERLAP_COMBOS = 72
EXPECT_OVERLAP_FREQS = 61
DEFAULT_OUT_DIR = REPO / "work/runs/te29-prep-20261009/regress"


def _tru(v) -> bool:
    return str(v).strip().lower() == "true"


def load_frozen_v2_labels(csv_path: pathlib.Path) -> dict:
    """冻结标签 CSV → {(x_norm, N1): row}（只取 te2_9 行；x 做同样的 ulp 归一化）。"""
    out = {}
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("cell") != V2_CELL:
                continue
            key = (round(float(r["x_scale"]), 6), int(float(r["N_w_te1"])))
            out[key] = r
    return out


def v2_label_selfcheck(v2_res: dict, labels: dict, tol: float = 1e-9) -> dict:
    """把解析出的 v2 与冻结标签逐行对账。返回差异清单（空 = 完全一致）。"""
    diffs = []
    keys = set()
    for c in v2_res["cells"]:
        key = (c["x_scale"], int(c["N_w_te1"]))
        keys.add(key)
        lab = labels.get(key)
        if lab is None:
            diffs.append({"key": "%s/N1=%s" % key, "field": "<row>", "parsed": "present",
                          "frozen": "MISSING"})
            continue
        def cmp_num(field, parsed, frozen, ftol=tol):
            if frozen.strip().lower() in ("nan", ""):
                if parsed is not None:
                    diffs.append({"key": "%s/N1=%s" % key, "field": field,
                                  "parsed": parsed, "frozen": frozen})
                return
            f = float(frozen)
            if parsed is None or abs(float(parsed) - f) > ftol:
                diffs.append({"key": "%s/N1=%s" % key, "field": field,
                              "parsed": parsed, "frozen": f})
        cmp_num("peak_freq_Hz", c["peak_freq_Hz"], lab["peak_freq_Hz"])
        cmp_num("peak_spl_dB", c["peak_spl_dB"], lab["peak_spl_dB"])
        cmp_num("bandwidth_Hz", c["bandwidth_Hz"], lab["bandwidth_Hz"])
        cmp_num("Q", c["Q"], lab["Q"])
        cmp_num("zeta", c["zeta"], lab["zeta"])
        for field, col in (("peak_at_scan_endpoint", "peak_at_scan_endpoint"),
                           ("bw_upper_cutoff_at_endpoint", "bw_upper_cutoff_at_endpoint")):
            p = c[field]
            f = _tru(lab[col])
            if (p is None) or (bool(p) != f):
                diffs.append({"key": "%s/N1=%s" % key, "field": field, "parsed": p, "frozen": f})
    for key in sorted(set(labels) - keys):
        diffs.append({"key": "%s/N1=%s" % key, "field": "<row>", "parsed": "MISSING",
                      "frozen": "present"})
    return {"n_parsed_cells": len(v2_res["cells"]), "n_frozen_rows": len(labels),
            "n_diffs": len(diffs), "diffs_sample": diffs[:30], "identical": not diffs}


def point_map(res: dict) -> dict:
    """长表 → {(x_norm, N1, freq_Hz): spl_dB}。"""
    return {(p["x_scale"], int(p["N_w_te1"]), p["freq_Hz"]): p["spl_dB"] for p in res["points"]}


def run(new_dir: pathlib.Path, v2_dir: pathlib.Path, labels_path: pathlib.Path,
        tol_db: float, exp_combos, exp_freqs, exp_points, do_selfcheck: bool,
        selfcheck_only: bool = False) -> tuple[int, dict]:
    rep: dict = {"new_dir": str(new_dir), "v2_dir": str(v2_dir),
                 "v2_labels": str(labels_path), "tol_dB": tol_db,
                 "selfcheck_only": selfcheck_only}
    # ---- v2 侧 ----
    if not v2_dir.exists():
        return 3, {**rep, "error": "v2 参照目录不存在：%s" % v2_dir}
    if not labels_path.exists():
        return 3, {**rep, "error": "冻结标签 CSV 不存在：%s" % labels_path}
    got_sha = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    rep["v2_labels_sha256"] = got_sha
    rep["v2_labels_sha256_expected"] = V2_LABELS_SHA256
    rep["v2_labels_sha256_ok"] = (got_sha == V2_LABELS_SHA256)
    if not rep["v2_labels_sha256_ok"]:
        return 4, {**rep, "error": "冻结标签 CSV 的 sha256 与登记值不符 —— 回归靶拒绝在非注册基线上比对"}

    # ---- v2 侧解析与对账（--selfcheck-only 时到此为止） ----
    try:
        v2r = parse_export(v2_dir, strict_grid=False, expect_combos=None, expect_nfreq=None)
    except ValueError as e:
        return 4, {**rep, "error": "v2 参照解析失败（表头/列定位，fail-closed）：%s" % e}
    labels = load_frozen_v2_labels(labels_path)
    rep["v2_census"] = {k: v2r["diag"][k] for k in
                        ("n_combos", "n_peak_at_scan_endpoint", "n_bw_upper_cutoff_at_endpoint",
                         "n_usable", "n_usable_alt_peakaware", "n_Q_decidable",
                         "n_Q_decidable_among_usable", "n_Q_pass_2p5_3p5",
                         "n_Q_nan_rows", "n_Q_nan_but_flagged_usable",
                         "n_ambiguous_bridge_cells", "n_ambiguous_primary_disagrees_alt")}
    rep["v2_census_registered"] = {"n_combos": 80, "n_peak_at_scan_endpoint": 28,
                                  "n_bw_upper_cutoff_at_endpoint": 34, "n_usable": 46,
                                  "n_Q_decidable_among_usable": 32, "n_Q_pass_2p5_3p5": 11}
    rep["v2_census_matches_registered"] = all(
        rep["v2_census"].get(k) == v for k, v in rep["v2_census_registered"].items())
    if do_selfcheck or selfcheck_only:
        rep["v2_label_selfcheck"] = v2_label_selfcheck(v2r, labels)
        if not rep["v2_label_selfcheck"]["identical"]:
            return 4, {**rep, "error": "v2 侧解析与冻结标签不一致（%d 处）—— 回归靶基线不可信"
                                        % rep["v2_label_selfcheck"]["n_diffs"]}
        if not rep["v2_census_matches_registered"]:
            return 4, {**rep, "error": "v2 侧计数与登记剖面不符 —— 回归靶基线不可信"}
    else:
        rep["v2_label_selfcheck"] = None
    if selfcheck_only:
        return 0, rep

    # ---- 新导出侧 ----
    if not new_dir.exists():
        return 3, {**rep, "error": "新导出目录不存在：%s" % new_dir}
    cell, cands = find_cell_dir(new_dir)
    if cell is None:
        return 3, {**rep, "error": "新导出目录下没找到 Table_9.txt（产物未到位）",
                   "candidates": [str(c) for c in cands]}
    rep["new_cell_dir"] = str(cell)
    if cell.resolve() == v2_dir.resolve():
        return 4, {**rep, "error": "新导出目录 == v2 参照目录 —— 拒绝自己跟自己比"}

    try:
        newr = parse_export(cell, strict_grid=False, expect_combos=None, expect_nfreq=None)
    except ValueError as e:
        return 4, {**rep, "error": "新导出解析失败（表头/列定位，fail-closed）：%s" % e}
    rep["new_diag"] = {k: v for k, v in newr["diag"].items()
                       if k not in ("missing_expected_combos_sample", "unexpected_combos_sample")}
    rep["v2_diag"] = {k: v for k, v in v2r["diag"].items()
                      if k not in ("missing_expected_combos_sample", "unexpected_combos_sample")}

    # ---- 重叠口径 ----
    a, b = point_map(v2r), point_map(newr)
    v2_combos = {(k[0], k[1]) for k in a}
    new_combos = {(k[0], k[1]) for k in b}
    ov_combos = sorted(v2_combos & new_combos)
    v2_freqs = sorted({k[2] for k in a})
    new_freqs = sorted({k[2] for k in b})
    ov_freqs = sorted(set(v2_freqs) & set(new_freqs))
    rep["v2"] = {"n_combos": len(v2_combos), "n_freqs": len(v2_freqs),
                 "freq_lo_Hz": v2_freqs[0] if v2_freqs else None,
                 "freq_hi_Hz": v2_freqs[-1] if v2_freqs else None, "n_points": len(a)}
    rep["new"] = {"n_combos": len(new_combos), "n_freqs": len(new_freqs),
                  "freq_lo_Hz": new_freqs[0] if new_freqs else None,
                  "freq_hi_Hz": new_freqs[-1] if new_freqs else None, "n_points": len(b)}
    rep["overlap"] = {"n_combos": len(ov_combos), "n_freqs": len(ov_freqs),
                      "freq_lo_Hz": ov_freqs[0] if ov_freqs else None,
                      "freq_hi_Hz": ov_freqs[-1] if ov_freqs else None,
                      "freqs_all": ov_freqs}
    if not ov_combos or not ov_freqs:
        return 4, {**rep, "error": "重叠组合或重叠频点为空 —— 无法回归"}

    common = sorted(set(a) & set(b))
    # 结构性完备性：重叠组合 × 重叠频点的**全积**必须都能比
    expected_triples = {(x, n1, f) for (x, n1) in ov_combos for f in ov_freqs}
    missing = sorted(expected_triples - set(common))
    extra = sorted(set(common) - expected_triples)
    rep["overlap"]["n_points_compared"] = len(common)
    rep["overlap"]["n_points_expected_full_product"] = len(expected_triples)
    rep["overlap"]["n_missing_points"] = len(missing)
    rep["overlap"]["missing_points_sample"] = ["x%.6f/N1=%d/f=%.3fMHz" % (x, n1, f / 1e6)
                                               for (x, n1, f) in missing[:20]]
    rep["overlap"]["n_extra_points"] = len(extra)

    deltas = [(abs(a[k] - b[k]), k, a[k], b[k]) for k in common]
    maxd, maxk, va, vb = max(deltas) if deltas else (float("nan"), None, None, None)
    rep["regression"] = {
        "n_points": len(deltas),
        "max_abs_delta_dB": maxd,
        "max_abs_delta_at": (None if maxk is None else
                             {"combo": combo_key_str((maxk[0], maxk[1], 9)),
                              "freq_Hz": maxk[2], "v2_dB": va, "new_dB": vb}),
        "n_exceeding_tol": sum(1 for d, *_ in deltas if d > tol_db),
        "tol_dB": tol_db,
        "passed": bool(deltas) and maxd <= tol_db,
    }
    per_combo = {}
    for d, k, va0, vb0 in deltas:
        pc = per_combo.setdefault(combo_key_str((k[0], k[1], 9)), {"n": 0, "max": 0.0})
        pc["n"] += 1
        pc["max"] = max(pc["max"], d)
    rep["per_combo_max_abs_delta_dB"] = dict(sorted(per_combo.items()))
    rep["violations_sample"] = [
        {"combo": combo_key_str((k[0], k[1], 9)), "freq_Hz": k[2],
         "v2_dB": va0, "new_dB": vb0, "abs_delta_dB": d}
        for d, k, va0, vb0 in sorted(deltas, reverse=True) if d > tol_db][:25]

    exp = {"overlap_combos": exp_combos, "overlap_freqs": exp_freqs,
           "overlap_points": exp_points}
    rep["expectations"] = exp
    exp_bad = []
    if exp_combos is not None and len(ov_combos) != exp_combos:
        exp_bad.append("重叠组合数 %d ≠ 期望 %d" % (len(ov_combos), exp_combos))
    if exp_freqs is not None and len(ov_freqs) != exp_freqs:
        exp_bad.append("重叠频点数 %d ≠ 期望 %d" % (len(ov_freqs), exp_freqs))
    if exp_points is not None and len(common) != exp_points:
        exp_bad.append("重叠点数 %d ≠ 期望 %d" % (len(common), exp_points))

    if missing:
        return 4, {**rep, "error": "重叠区缺点 %d 个（比较不完整，拒绝出结论）" % len(missing)}
    if not deltas:
        return 4, {**rep, "error": "没有任何可比点"}
    if exp_bad:
        return 6, {**rep, "error": "；".join(exp_bad)}
    if maxd > tol_db:
        return 5, {**rep, "error": "最大 |Δ| = %.6g dB > 阈值 %g dB（超阈 %d 点）"
                                   % (maxd, tol_db, rep["regression"]["n_exceeding_tol"])}
    return 0, rep


def write_report(rep: dict, out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "regress_te29_vs_v2.json").write_text(
        json.dumps({**rep, "verdict": "pass" if rep.get("passed") else "fail"},
                   ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    ov, rg = rep.get("overlap", {}), rep.get("regression", {})
    verdict = ("**仅 v2 对账**（未比对新导出）" if rep.get("selfcheck_only") else
               ("**通过**" if (rg.get("passed") and not rep.get("error")) else
                "**失败/未完成**：%s" % rep.get("error", "")))
    md = ["# te2_9 新导出 vs v2 参照：重叠频点 SPL 回归", "",
          "| 项 | 值 |", "|---|---|",
          "| 新导出目录 | `%s` |" % rep.get("new_cell_dir", rep.get("new_dir")),
          "| v2 参照目录 | `%s` |" % rep.get("v2_dir"),
          "| 冻结标签 sha256 核对 | %s |" % rep.get("v2_labels_sha256_ok"),
          "| v2 侧与冻结标签逐行对账 | %s |"
          % (rep.get("v2_label_selfcheck") or {}).get("identical"),
          "| v2 侧计数 == 登记剖面 | %s |" % rep.get("v2_census_matches_registered"),
          "| 阈值 | %s dB |" % rep.get("tol_db"),
          "| 重叠组合数 | %s |" % ov.get("n_combos"),
          "| 重叠频点数 | %s（%s–%s Hz）" % (ov.get("n_freqs"), ov.get("freq_lo_Hz"),
                                            ov.get("freq_hi_Hz")),
          "| 已比点数 | %s（全积 %s，缺点 %s）"
          % (ov.get("n_points_compared"), ov.get("n_points_expected_full_product"),
             ov.get("n_missing_points")),
          "| 最大 \\|Δ\\| | %s dB |" % rg.get("max_abs_delta_dB"),
          "| 超阈点数 | %s |" % rg.get("n_exceeding_tol"),
          "| 结论 | %s |" % verdict, ""]
    if rep.get("violations_sample"):
        md += ["## 超阈点（最多 25 个）", "",
               "| 组合 | 频率 (Hz) | v2 (dB) | new (dB) | \\|Δ\\| (dB) |", "|---|---|---|---|---|"]
        for v in rep["violations_sample"]:
            md.append("| %s | %s | %s | %s | %s |"
                      % (v["combo"], v["freq_Hz"], v["v2_dB"], v["new_dB"], v["abs_delta_dB"]))
        md.append("")
    (out_dir / "regress_te29_vs_v2.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="te2_9 新导出 vs v2 参照：重叠频点 SPL 回归靶（fail-closed）")
    ap.add_argument("--new-dir", default=None, help="新导出目录（或其上层目录）")
    ap.add_argument("--v2-dir", default=str(V2_DIR_DEFAULT))
    ap.add_argument("--v2-labels", default=str(V2_LABELS_DEFAULT))
    ap.add_argument("--tol-db", type=float, default=1e-3)
    ap.add_argument("--expect-overlap-combos", type=int, default=EXPECT_OVERLAP_COMBOS)
    ap.add_argument("--expect-overlap-freqs", type=int, default=EXPECT_OVERLAP_FREQS)
    ap.add_argument("--expect-overlap-points", type=int, default=None,
                    help="缺省不启用；真实数据建议 4392 = 72 × 61")
    ap.add_argument("--no-v2-selfcheck", action="store_true")
    ap.add_argument("--selfcheck-only", action="store_true",
                    help="只做 v2 侧对账（v2 解析 vs 冻结标签 vs 登记剖面），不需要 --new-dir")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if not a.selfcheck_only and not a.new_dir:
        print("[用法] 需要 --new-dir（或改用 --selfcheck-only）")
        return 2

    code, rep = run(pathlib.Path(a.new_dir or "."), pathlib.Path(a.v2_dir),
                    pathlib.Path(a.v2_labels), a.tol_db, a.expect_overlap_combos,
                    a.expect_overlap_freqs, a.expect_overlap_points,
                    (not a.no_v2_selfcheck), a.selfcheck_only)
    rep["passed"] = (code == 0)
    write_report(rep, pathlib.Path(a.out_dir))
    if not a.quiet:
        print("回归靶：新导出 = %s" % rep.get("new_cell_dir", rep.get("new_dir")))
        print("        v2 参照 = %s" % rep.get("v2_dir"))
        print("        冻结标签 sha256 核对 = %s ｜ v2 逐行对账 = %s ｜ v2 计数==登记剖面 = %s"
              % (rep.get("v2_labels_sha256_ok"),
                 (rep.get("v2_label_selfcheck") or {}).get("identical"),
                 rep.get("v2_census_matches_registered")))
        if rep.get("v2_census"):
            c = rep["v2_census"]
            print("        v2 剖面：组合 %s ｜ 峰值删失 %s ｜ 带宽截断 %s ｜ 可用 %s（峰值感知 %s）"
                  " ｜ Q 可判定 %s/可用 ｜ Q 达标 %s ｜ 桥接歧义 %s（主规则与峰值带不一致 %s）"
                  % (c.get("n_combos"), c.get("n_peak_at_scan_endpoint"),
                     c.get("n_bw_upper_cutoff_at_endpoint"), c.get("n_usable"),
                     c.get("n_usable_alt_peakaware"), c.get("n_Q_decidable_among_usable"),
                     c.get("n_Q_pass_2p5_3p5"), c.get("n_ambiguous_bridge_cells"),
                     c.get("n_ambiguous_primary_disagrees_alt")))
        ov, rg = rep.get("overlap", {}), rep.get("regression", {})
        if ov:
            print("        重叠：组合 %s ｜ 频点 %s ｜ 已比点 %s（缺点 %s）"
                  % (ov.get("n_combos"), ov.get("n_freqs"), ov.get("n_points_compared"),
                     ov.get("n_missing_points")))
            print("        最大 |Δ| = %s dB（阈值 %s）｜ 超阈 %s 点"
                  % (rg.get("max_abs_delta_dB"), rep.get("tol_db"), rg.get("n_exceeding_tol")))
        print("        结论 = %s%s" % ("通过" if code == 0 else "失败",
                                      "" if code == 0 else "：%s" % rep.get("error", "")))
    return code


if __name__ == "__main__":
    sys.exit(main())
