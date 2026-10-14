# -*- coding: utf-8 -*-
"""独立复核 A3 的 `te2_9` 画像数字（**不 import** 主脚本，另写一遍算法）。

用途（对应技能 `ai-solver-verification` §8 的精神：**复核必须自证独立**）：
把 `scripts/te2_9_value_profile.py` 产出的 `te2_9_profile.json` 里的关键数字，
用一份**独立实现**直接从冻结副本/v3 表/C 原表重算一遍并逐项对照。

本脚本**默认只读**：输出一份对照表（stdout），**不写任何文件**；只有显式给 `--out <路径>`
时才写出结果 JSON —— **默认路径下不写被校验目录**（R16：`--profile-dir` 既是读的根，
修复前又被同一作用域当写的根，见 INDEX 本轮 R1–R4 裁决与落地的末尾节）。
任一项对不上 ⇒ 退出码 **3**。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
V2 = REPO / "work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv"
V3 = REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv"
CRAW = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"


def rd(p):
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def K(x_raw, n1, n2):
    return (round(float(x_raw), 6), float(n1), float(n2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile-dir", required=True)
    ap.add_argument("--out", default=None,
                    help="显式给出才写结果 JSON；缺省只读、不写任何文件（R16）")
    a = ap.parse_args()
    pd = pathlib.Path(a.profile_dir)
    if not pd.is_absolute():
        pd = REPO / pd
    prof = json.loads((pd / "te2_9_profile.json").read_text(encoding="utf-8"))

    v2 = [r for r in rd(V2) if r["cell"] == "te2_9"]
    v3 = rd(V3)
    craw = rd(CRAW)

    got = {}
    got["n_rows"] = len(v2)
    got["n_unique_keys"] = len({K(r["x_scale"], r["N_w_te1"], r["N_w_te2"]) for r in v2})

    def usable_flag(r):
        return r["peak_at_scan_endpoint"] != "True" and r["bw_upper_cutoff_at_endpoint"] != "True"

    u = [r for r in v2 if usable_flag(r)]
    got["n_usable"] = len(u)
    got["n_peak_censored_any"] = sum(1 for r in v2 if r["peak_at_scan_endpoint"] == "True")
    got["n_bw_truncated_any"] = sum(1 for r in v2 if r["bw_upper_cutoff_at_endpoint"] == "True")
    got["n_both"] = sum(1 for r in v2 if r["peak_at_scan_endpoint"] == "True"
                        and r["bw_upper_cutoff_at_endpoint"] == "True")
    got["n_peak_only"] = sum(1 for r in v2 if r["peak_at_scan_endpoint"] == "True"
                             and r["bw_upper_cutoff_at_endpoint"] != "True")
    got["n_bw_only"] = sum(1 for r in v2 if r["bw_upper_cutoff_at_endpoint"] == "True"
                           and r["peak_at_scan_endpoint"] != "True")

    # 覆盖矩阵：另一条路径（按 (x,N1) 集合差集算，不逐格查表）
    cells = {}
    for r in v2:
        cells[(round(float(r["x_scale"]), 6), int(float(r["N_w_te1"])))] = (
            r["peak_at_scan_endpoint"] == "True", r["bw_upper_cutoff_at_endpoint"] == "True")
    usable_cells = sorted(k for k, (p, b) in cells.items() if not p and not b)
    got["n_usable_cells"] = len(usable_cells)
    got["usable_x"] = sorted({c[0] for c in usable_cells})
    got["usable_n1"] = sorted({c[1] for c in usable_cells})
    got["full_factorial_cells"] = len(cells)

    # 净价值
    def keyset(batch):
        return {K(r["x_scale"], r["N_w_te1"], r["N_w_te2"]) for r in v3 if r["batch"] == batch}

    A, C = keyset("A_5-35MHz"), keyset("C_5-50MHz")
    v9 = {K(r["x_scale"], r["N_w_te1"], r["N_w_te2"]) for r in v2}
    got["n_in_A"] = len(v9 & A)
    got["n_in_C"] = len(v9 & C)
    got["cat_only_v2"] = len(v9 - A - C)
    got["net_usable_increment"] = len({
        K(r["x_scale"], r["N_w_te1"], r["N_w_te2"]) for r in u} - A - C)
    got["C_has_N2_9_rows"] = sum(1 for r in v3 if r["batch"] == "C_5-50MHz"
                                 and float(r["N_w_te2"]) == 9.0)
    got["A_has_N2_9_rows"] = sum(1 for r in v3 if r["batch"] == "A_5-35MHz"
                                 and float(r["N_w_te2"]) == 9.0)
    got["C_N2_values"] = sorted({float(r["N_w_te2"]) for r in v3 if r["batch"] == "C_5-50MHz"})

    # Q 门禁（两条路径：直接读 v2 冻结副本 / 读 v3 的 V2 批）
    q_in = [r for r in u if r["Q"].strip().lower() != "nan" and 2.5 <= float(r["Q"]) <= 3.5]
    got["te2_9_Q_in_gate"] = len(q_in)
    got["te2_9_Q_numeric"] = sum(1 for r in u if r["Q"].strip().lower() != "nan")
    got["te2_9_Q_literal_nan"] = sum(1 for r in u if r["Q"].strip().lower() == "nan")
    got["only_v2_usable_Q_in_gate"] = len([r for r in q_in
                                           if K(r["x_scale"], r["N_w_te1"], r["N_w_te2"])
                                           not in (A | C)])
    v2_all = [r for r in v3 if r["batch"] == "V2_5-35MHz"]
    v2u = [r for r in v2_all if r.get("usable", "") == "True"]
    got["v2_batch_rows"] = len(v2_all)
    got["v2_batch_usable"] = len(v2u)
    got["v2_batch_Q_in_gate"] = len([r for r in v2u if r["Q"].strip().lower() != "nan"
                                     and 2.5 <= float(r["Q"]) <= 3.5])
    got["v2_batch_Q_numeric"] = len([r for r in v2u if r["Q"].strip().lower() != "nan"])
    got["v2_batch_Q_nan"] = len([r for r in v2_all if r["Q"].strip().lower() == "nan"])

    # 唯一重叠组合的 C 原表侧证据
    ov = [(r["x_scale"], r["N_w_te1"], r["N_w_te2"]) for r in craw
          if float(r["N_w_te2"]) == 9.0]
    got["craw_N2_9_rows"] = len(ov)
    got["craw_N2_9_first_peak_found"] = sorted({r["first_peak_found"] for r in craw
                                                if float(r["N_w_te2"]) == 9.0})

    # 与画像 JSON 对照
    exp = {
        "n_rows": prof["te2_9"]["n_rows"],
        "n_unique_keys": prof["te2_9"]["n_unique_keys"],
        "n_usable": prof["te2_9"]["n_usable"],
        "n_peak_censored_any": prof["te2_9"]["n_peak_censored_any"],
        "n_bw_truncated_any": prof["te2_9"]["n_bw_truncated_any"],
        "n_both": prof["te2_9"]["n_both"],
        "n_peak_only": prof["te2_9"]["n_peak_only"],
        "n_bw_only": prof["te2_9"]["n_bw_only"],
        "n_usable_cells": len(prof["coverage_matrix"]["usable_cells"]),
        "usable_x": prof["coverage_matrix"]["usable_x_values"],
        "usable_n1": prof["coverage_matrix"]["usable_N1_values"],
        "full_factorial_cells": len(prof["coverage_matrix"]["cells"]),
        "n_in_A": prof["net_value"]["n_in_A"],
        "n_in_C": prof["net_value"]["n_in_C"],
        "cat_only_v2": prof["net_value"]["cat_only_v2"],
        "net_usable_increment": prof["net_usable_increment"]["n"],
        "te2_9_Q_in_gate": prof["q_gate_reconciliation"]["te2_9_Q_in_gate_among_usable"],
        "te2_9_Q_numeric": prof["distributions_usable_only"]["Q_evaluable_base"],
        "te2_9_Q_literal_nan": prof["distributions_usable_only"]["Q_usable_null"],
        "only_v2_usable_Q_in_gate": prof["q_gate_reconciliation"]["te2_9_only_v2_usable_Q_in_gate"],
        "v2_batch_rows": prof["q_gate_reconciliation"]["v2_whole_batch_rows"],
        "v2_batch_usable": prof["q_gate_reconciliation"]["v2_whole_batch_usable"],
        "v2_batch_Q_in_gate": prof["q_gate_reconciliation"]["v2_whole_batch_Q_in_gate_among_usable"],
        "v2_batch_Q_numeric": prof["q_gate_reconciliation"]["v2_whole_batch_Q_evaluable_base"],
        "v2_batch_Q_nan": prof["q_gate_reconciliation"]["v2_whole_batch_Q_literal_nan"],
    }
    diff = {k: {"independent": got[k], "profile": exp[k]}
            for k in exp if got.get(k) != exp[k]}
    # 画像里没登记、但独立算出来的结构事实
    extra = {"C_has_N2_9_rows": got["C_has_N2_9_rows"],
             "A_has_N2_9_rows": got["A_has_N2_9_rows"],
             "C_N2_values": got["C_N2_values"],
             "craw_N2_9_rows": got["craw_N2_9_rows"],
             "craw_N2_9_first_peak_found": got["craw_N2_9_first_peak_found"]}

    res = {
        "profile_dir": str(pd.relative_to(REPO)).replace("\\", "/"),
        "inputs": {str(p.relative_to(REPO)).replace("\\", "/"):
                   hashlib.sha256(p.read_bytes()).hexdigest() for p in (V2, V3, CRAW)},
        "independent": got, "profile": exp, "diff": diff, "structural_facts": extra,
        "n_compared": len(exp), "n_diff": len(diff),
        "verdict": "passed" if not diff else "failed",
    }
    for k in sorted(exp):
        mark = "OK " if got.get(k) == exp[k] else "DIFF"
        print("  [%s] %-28s independent=%-8s profile=%s" % (mark, k, got.get(k), exp[k]))
    for k, v in extra.items():
        print("  [fact] %-28s %s" % (k, v))
    print("对照 %d 项，差异 %d 项 ⇒ %s" % (res["n_compared"], res["n_diff"], res["verdict"]))
    # ---- 输出：**默认只读**；只有显式 --out 才落盘（由调用方选在被校验树之外）（R16）
    out_path = pathlib.Path(a.out) if a.out else None
    if out_path is not None:
        if not out_path.is_absolute():
            out_path = REPO / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print("结果 JSON 已写出：%s" % out_path)
    else:
        print("未给 --out ⇒ **未写任何文件**（本脚本默认只读）")
    return 0 if not diff else 3


if __name__ == "__main__":
    sys.exit(main())
