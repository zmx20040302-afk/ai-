# -*- coding: utf-8 -*-
"""净价值核算：新导出（5–50 MHz，x 0.20→1.00 步长 0.01）相对 v2（5–35 MHz，x 0.10→1.00 步长 0.10）值多少。

判据（**先声明，后计算**）
----------------------
* v2 侧基线取**注册过的冻结标签 CSV**（默认 `v2_labels_frozen_20261008T143151.csv`，sha256 校验），
  而不是"我再解析一遍 v2"（`--v2-dir` 仅用于夹具自测）；
* **删失**：`peak_at_scan_endpoint = True`；**截断**：`bw_upper_cutoff_at_endpoint = True`；
  两者都算「非可用」；
* **救回**（头号判据）：v2 该格非可用 **且** 新导出该格 `usable = True`；
* **不在扫描范围的格子绝不计增益**：v2 有、而新导出网格里根本不存在的 x 列（本批即 **x = 0.10 的 8 格**）
  一律报为「不在扫描范围、未救回」，并**在结构上**排除在任何增益之外
  （`present_in_new = False` ⇒ `rescued` 恒为 False，且计入 `focus_absent_from_scan`）；
* **可判定分母**分开报：`Q` 为 `nan`/空的格子只进 `Q_decidable = False`，不进分母；
* 净可用增量同时给**两种口径**：主口径（与冻结标签同规则）与**峰值感知口径**
  （同峰值 SPL 键对应多条 −3 dB 带时，取「带内含该组合峰值频率」的那条；v2 实测该口径下少 3 格）。

⚠️ 不提升任何状态、不跑 COMSOL、只读既有产物；输出只落 `--out-dir`。

退出码：0 成功（新导出到位）｜2 用法错误｜3 **产物未到位**（此时仍写出 v2 侧普查，标 `pending_products`）｜4 新导出解析有结构性问题。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from parse_te29_v1 import (  # noqa: E402
    EXPECT_N1, EXPECT_N2, EXPECT_X, Q_PASS_HI, Q_PASS_LO, REPO, combo_key_str,
    find_cell_dir, parse_export,
)

V2_LABELS_DEFAULT = (REPO / "work/runs/remote-exported-v2-20260922"
                     / "v2_labels_frozen_20261008T143151.csv")
V2_LABELS_SHA256 = "cdf11ce2fe560fd9630463f5ad407d2da068051109c4b7a91f42c23e73fb4b31"
V2_CELL = "te2_9"
V2_REGISTERED = {"n_cells": 80, "n_peak_at_scan_endpoint": 28,
                 "n_bw_upper_cutoff_at_endpoint": 34, "n_usable": 46,
                 "n_Q_decidable": 32, "n_Q_pass_2p5_3p5": 11}
FOCUS_X_DEFAULT = (0.10, 0.20, 0.30)     # 任务书点名的「24 格」三列
DECLARED_X = frozenset(EXPECT_X)         # 本批声明的 x 扫描范围：0.20→1.00 步长 0.01
DEFAULT_OUT_DIR = REPO / "work/runs/te29-prep-20261009/netgain"


def _tru(v) -> bool:
    return str(v).strip().lower() == "true"


def _fnum(v):
    s = str(v).strip()
    if s.lower() in ("nan", "", "-nan"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return None if math.isnan(f) else f


def load_v2_baseline(path: pathlib.Path) -> tuple[dict, dict]:
    """冻结标签 → ({(x_norm, N1): cell}, meta)。meta 里含 sha256 与登记值对账。"""
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    cells = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("cell") != V2_CELL:
                continue
            x = round(float(r["x_scale"]), 6)
            n1 = int(float(r["N_w_te1"]))
            q = _fnum(r["Q"])
            peak_end = _tru(r["peak_at_scan_endpoint"])
            bw_end = _tru(r["bw_upper_cutoff_at_endpoint"])
            cells[(x, n1)] = {
                "x_scale": x, "N_w_te1": n1, "N_w_te2": int(float(r["N_w_te2"])),
                "combo_key": combo_key_str((x, n1, int(float(r["N_w_te2"])))),
                "n_freq": int(float(r["n_freq"])),
                "freq_hi_Hz": _fnum(r["freq_max_Hz"]),
                "peak_freq_Hz": _fnum(r["peak_freq_Hz"]), "peak_spl_dB": _fnum(r["peak_spl_dB"]),
                "peak_at_scan_endpoint": peak_end,
                "bw_upper_cutoff_at_endpoint": bw_end,
                "bandwidth_Hz": _fnum(r["bandwidth_Hz"]), "Q": q,
                "censored": peak_end, "truncated": bw_end,
                "non_usable": bool(peak_end or bw_end),
                "usable": bool((not peak_end) and (not bw_end)),
                "Q_decidable": q is not None,
                "Q_pass_2p5_3p5": bool(q is not None and Q_PASS_LO <= q <= Q_PASS_HI),
            }
    meta = {"path": str(path), "sha256": sha, "sha256_expected": V2_LABELS_SHA256,
            "sha256_ok": sha == V2_LABELS_SHA256, "n_cells": len(cells)}
    return cells, meta


def v2_census(v2: dict) -> dict:
    cells = list(v2.values())
    usable = [c for c in cells if c["usable"]]
    qdec = [c for c in cells if c["usable"] and c["Q_decidable"]]
    qpass = [c for c in usable if c["Q_pass_2p5_3p5"]]
    qnan = [c for c in cells if not c["Q_decidable"]]
    return {
        "n_cells": len(cells),
        "n_peak_at_scan_endpoint": sum(1 for c in cells if c["censored"]),
        "n_bw_upper_cutoff_at_endpoint": sum(1 for c in cells if c["truncated"]),
        "n_censored_and_truncated": sum(1 for c in cells if c["censored"] and c["truncated"]),
        "n_non_usable": sum(1 for c in cells if c["non_usable"]),
        "n_usable": len(usable),
        "n_Q_nan_rows": len(qnan),
        "n_Q_nan_but_usable": sum(1 for c in qnan if c["usable"]),
        "n_Q_decidable": len(qdec),
        "n_Q_decidable_denominator_note": "分母 = 可用且 Q 非 nan 的格子数",
        "n_Q_pass_2p5_3p5": len(qpass),
        "Q_pass_window": [Q_PASS_LO, Q_PASS_HI],
    }


def focus_census(v2: dict, new_by_x, n1s: tuple, focus_x: tuple,
                 products_present: bool = True) -> dict:
    """任务书点名的「24 格」：x ∈ focus_x × N1 ∈ 1..8 逐格交代。

    `products_present=False`（产物未到）时，`present_in_new` 退化为**声明扫描范围**的成员判定
    —— 关键区别是 x = 0.10 **本来就不在** 0.20→1.00 内，永远不得计增益；
    而 x = 0.20/0.30 只是「还没到」，不得误报成「不在扫描范围」。
    """
    cells = []
    for x in focus_x:
        xn = round(x, 6)
        in_declared = xn in DECLARED_X
        for n1 in n1s:
            c = v2.get((xn, n1))
            present = (xn in new_by_x) if products_present else in_declared
            if not in_declared:
                reason = "不在新扫描范围（x 0.20→1.00 步长 0.01），未救回"
            elif not present:
                reason = "在声明扫描范围内但新导出缺该格（待产物/异常）"
            else:
                reason = "待核"
            if c is None:
                cells.append({"x_scale": xn, "N_w_te1": n1, "in_v2": False,
                              "in_declared_scan": in_declared, "present_in_new": present,
                              "rescued": False, "reason": "v2 冻结标签里没有该格"})
                continue
            cells.append({
                "x_scale": xn, "N_w_te1": n1, "in_v2": True,
                "combo_key": c["combo_key"],
                "in_declared_scan": in_declared,
                "present_in_new": present,
                "v2_peak_at_scan_endpoint": c["censored"],
                "v2_bw_upper_cutoff_at_endpoint": c["truncated"],
                "v2_usable": c["usable"],
                "rescued": None,           # 由调用方在拿到新导出后填（present_in_new=False ⇒ 恒 False）
                "reason": reason,
            })
    return {
        "focus_x": [round(x, 6) for x in focus_x],
        "products_present": products_present,
        "present_in_new_is_declared_fallback": (not products_present),
        "n_focus_cells": len(cells),
        "n_focus_in_v2": sum(1 for c in cells if c["in_v2"]),
        "n_focus_non_usable_in_v2": sum(1 for c in cells if c["in_v2"] and not c["v2_usable"]),
        "n_focus_outside_declared_scan": sum(1 for c in cells if c["in_v2"] and not c["in_declared_scan"]),
        "n_focus_absent_from_new_scan": sum(1 for c in cells
                                            if c["in_v2"] and c["in_declared_scan"]
                                            and not c["present_in_new"]),
        "cells": cells,
    }


def write_md(rep: dict, out_dir: pathlib.Path) -> None:
    v2c = rep["v2_census"]
    new_c = rep.get("new_export")
    pending = rep.get("pending_products") or (new_c is None)
    parse_err = rep.get("parse_error")
    # 「新导出」列的口径标签由**实测状态**推出，不是字面量：
    new_label = ("解析失败" if parse_err else "待产物") if pending else None
    if parse_err:
        note = ("> ⚠️ **新导出解析失败（fail-closed）**：`%s`。以下只有 v2 侧普查"
                "（数字来自注册冻结标签 `%s`，sha 核对 %s）；新导出侧一律标「%s」，"
                "**增益字段全部 `null`** —— 不把「解析不出来」写成 0、更不写成任何数字。"
                % (parse_err, rep["v2_meta"]["path"], rep["v2_meta"].get("sha256_ok"), new_label))
    elif rep.get("pending_products"):
        note = ("> **产物未到位**：以下只列出 v2 侧普查（数字来自注册冻结标签 `%s`，sha 核对 %s）；"
                "新导出侧一律标「待产物」，**没有任何增益数字被编造**。"
                % (rep["v2_meta"]["path"], rep["v2_meta"].get("sha256_ok")))
    else:
        note = ("> 数字全部来自：v2 侧 = **注册冻结标签** `%s`（sha 核对 %s）；"
                "新导出侧 = 本机解析 `%s`。"
                % (rep["v2_meta"]["path"], rep["v2_meta"].get("sha256_ok"),
                   rep.get("new_cell_dir")))
    md = ["# te2_9 新导出净价值（旧 v2 → 新导出）", "", note, ""]
    if parse_err:
        md += ["> 解析失败原文：`%s`" % parse_err, ""]
    if pending:
        L = new_label
        md += ["| 指标 | v2（5–35 MHz） | 新导出（5–50 MHz） |", "|---|---|---|",
               "| 组合数 | %d | %s |" % (v2c["n_cells"], L),
               "| 峰值端点删失 | %d | %s |" % (v2c["n_peak_at_scan_endpoint"], L),
               "| 带宽上截止=端点（截断） | %d | %s |" % (v2c["n_bw_upper_cutoff_at_endpoint"], L),
               "| 可用 | %d | %s |" % (v2c["n_usable"], L),
               "| Q 可判定（分母） | %d / 可用 %d | %s |" % (v2c["n_Q_decidable"], v2c["n_usable"], L),
               "| Q 达标（%.1f–%.1f） | %d | %s |"
               % (Q_PASS_LO, Q_PASS_HI, v2c["n_Q_pass_2p5_3p5"], L),
               "| Q=nan 行 | %d（其中被 flag 判可用 %d） | %s |"
               % (v2c["n_Q_nan_rows"], v2c["n_Q_nan_but_usable"], L), "",
               ("> 「在新导出」列在产物未到时**按声明扫描范围推断**"
                "（`present_in_new_is_declared_fallback=True`）：x = 0.10 判定为「不在扫描范围」，"
                "x = 0.20/0.30 判定为「在范围内、待产物」。"
                if rep.get("pending_products") else
                "> 「在新导出」列标「%s」：本侧**没有**任何被采信的数值。" % L), ""]
    else:
        md += ["| 指标 | v2（5–35 MHz） | 新导出（5–50 MHz） |", "|---|---|---|",
               "| 组合数 | %d | %d |" % (v2c["n_cells"], new_c["n_combos"]),
               "| 峰值端点删失 | %d | %d |" % (v2c["n_peak_at_scan_endpoint"],
                                               new_c["n_peak_at_scan_endpoint"]),
               "| 带宽上截止=端点（截断） | %d | %d |" % (v2c["n_bw_upper_cutoff_at_endpoint"],
                                                         new_c["n_bw_upper_cutoff_at_endpoint"]),
               "| **可用** | **%d** | **%d**（峰值感知口径 %d） |"
               % (v2c["n_usable"], rep["net_gain"]["new_usable"],
                  rep["net_gain"]["new_usable_peakaware"]),
               "| Q 可判定（分母） | %d / 可用 %d | %d / 可用 %d |"
               % (v2c["n_Q_decidable"], v2c["n_usable"],
                  rep["net_gain"]["new_Q_decidable_among_usable"], rep["net_gain"]["new_usable"]),
               "| Q 达标（%.1f–%.1f） | %d | %d |"
               % (Q_PASS_LO, Q_PASS_HI, v2c["n_Q_pass_2p5_3p5"], rep["net_gain"]["new_Q_pass_2p5_3p5"]),
               "| Q=nan 行 | %d（其中被 flag 判可用 %d） | %d（其中被 flag 判可用 %d） |"
               % (v2c["n_Q_nan_rows"], v2c["n_Q_nan_but_usable"], new_c["n_Q_nan_rows"],
                  new_c["n_Q_nan_but_flagged_usable"]), ""]
        rg = rep["rescue"]
        md += ["## 救回", "",
               "* 全量救回（v2 非可用 → 新导出可用）：**%d** 格" % rg["n_rescued_total"],
               "* 「24 格」（x ∈ %s × N1 ∈ %s）中救回：**%d** 格"
               % (rep["focus"]["focus_x"], rep["n1_values"], rg["n_rescued_within_focus"]),
               "* 「24 格」中**不在新扫描范围、未救回**：**%d** 格（x = 0.10 的 8 格）"
               % rg["n_focus_outside_declared_scan"],
               "* 「24 格」中在声明扫描范围内但新导出缺格（异常，未计增益）：%d 格"
               % rg["n_focus_absent_from_new_scan"],               "* 「24 格」中 v2 非可用：%d 格" % rg["n_focus_not_usable_in_v2"], ""]
    md += ["| x_scale | N1 | 在 v2 | 在声明扫描内 | 在新导出 | v2 可用 | 新可用 | 救回 | 说明 |",
           "|---|---|---|---|---|---|---|---|---|"]
    for c in rep["focus"]["cells"]:
        md.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                  % (c["x_scale"], c["N_w_te1"], c["in_v2"], c["in_declared_scan"],
                     c["present_in_new"], c.get("v2_usable"), c.get("new_usable"),
                     c.get("rescued"), c.get("reason")))
    md.append("")
    (out_dir / "netgain_te29.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="te2_9 新导出净价值核算（救回/净可用/Q 达标）")
    ap.add_argument("--new-dir", default=None, help="新导出目录；缺省或不存在时按「产物未到位」处理")
    ap.add_argument("--v2-labels", default=str(V2_LABELS_DEFAULT))
    ap.add_argument("--v2-dir", default=None,
                    help="夹具自测用：直接用某个 v2 形状的目录替代冻结 CSV")
    ap.add_argument("--focus-x", default=",".join("%g" % x for x in FOCUS_X_DEFAULT))
    ap.add_argument("--n1-values", default=",".join(str(i) for i in EXPECT_N1))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    focus_x = tuple(float(t) for t in a.focus_x.split(",") if t.strip())
    n1s = tuple(int(t) for t in a.n1_values.split(",") if t.strip())
    out_dir = pathlib.Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rep: dict = {"run": "work/runs/te29-prep-20261009", "cell": V2_CELL,
                 "focus_x": focus_x, "n1_values": list(n1s),
                 "new_dir": a.new_dir, "v2_source": a.v2_dir or a.v2_labels}

    # ---- v2 基线 ----
    v2_meta = None
    if a.v2_dir:
        d = pathlib.Path(a.v2_dir)
        cell, cands = find_cell_dir(d)
        if cell is None:
            print("[用法] --v2-dir 下没找到 Table_9.txt：%s" % d)
            return 2
        try:
            parsed = parse_export(cell, strict_grid=False, expect_combos=None, expect_nfreq=None)
        except ValueError as e:
            print("[用法] --v2-dir 解析失败（表头/列定位，fail-closed）：%s" % e)
            return 2
        v2 = {}
        for c in parsed["cells"]:
            key = (c["x_scale"], int(c["N_w_te1"]))
            v2[key] = {**c, "censored": bool(c["peak_at_scan_endpoint"]),
                       "truncated": c["bw_upper_cutoff_at_endpoint"] is True,
                       "non_usable": bool(c["peak_at_scan_endpoint"]
                                          or c["bw_upper_cutoff_at_endpoint"] is True),
                       "Q_decidable": bool(c["Q_decidable"]),
                       "Q_pass_2p5_3p5": bool(c["Q_pass_2p5_3p5"])}
        v2_meta = {"path": str(cell), "kind": "parsed_dir", "n_cells": len(v2)}
    else:
        lp = pathlib.Path(a.v2_labels)
        if not lp.exists():
            print("[用法] 冻结标签 CSV 不存在：%s" % lp)
            return 2
        v2, v2_meta = load_v2_baseline(lp)
        if not v2_meta["sha256_ok"]:
            print("[基线拒绝] 冻结标签 CSV 的 sha256 与登记值不符：")
            print("   实得 %s" % v2_meta["sha256"])
            print("   登记 %s" % V2_LABELS_SHA256)
            return 2

    v2c = v2_census(v2)
    rep["v2_meta"] = v2_meta
    rep["v2_census"] = v2c
    rep["v2_census_vs_registered"] = {
        "registered": V2_REGISTERED,
        "matches": all(v2c[k] == v for k, v in V2_REGISTERED.items()),
    }
    v2_focus = focus_census(v2, set(), n1s, focus_x, products_present=False)
    rep["focus"] = v2_focus

    # ---- 新导出侧 ----
    new_ok, new_err, new_cells, new_census = False, None, [], None
    if a.new_dir:
        nd = pathlib.Path(a.new_dir)
        if not nd.exists():
            new_err = "新导出目录不存在：%s" % nd
        else:
            cell, cands = find_cell_dir(nd)
            if cell is None:
                new_err = "新导出目录下没找到 Table_9.txt（产物未到位）：%s" % nd
            else:
                try:
                    parsed = parse_export(cell, strict_grid=False, expect_combos=None,
                                          expect_nfreq=None)
                except ValueError as e:
                    rep["parse_error"] = str(e)
                    rep["new_cell_dir"] = str(cell)
                    rep["pending_products"] = False
                    rep["new_export"] = None
                    rep["error"] = "新导出解析失败（表头/列定位，fail-closed）：%s" % e
                    rep["net_gain"] = {"pending_products": False,
                                       "v2_usable_baseline": v2c["n_usable"],
                                       "new_usable": None, "usable_delta": None,
                                       "rescued_total": None}
                    for c in rep["focus"]["cells"]:
                        c["rescued"] = None
                        c["new_usable"] = None
                    (out_dir / "netgain_te29.json").write_text(
                        json.dumps(rep, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
                    write_md(rep, out_dir)
                    if not a.quiet:
                        print("[解析失败] %s" % rep["error"])
                        print("已写出 %s 与 netgain_te29.md（增益字段一律 null，不编造）"
                              % (out_dir / "netgain_te29.json"))
                    return 4
                new_cells = parsed["cells"]
                new_census = parsed["diag"]
                new_ok = True
                rep["new_cell_dir"] = str(cell)
    else:
        new_err = "未提供 --new-dir"

    if not new_ok:
        rep["pending_products"] = True
        rep["new_export"] = None
        rep["error"] = new_err
        for c in rep["focus"]["cells"]:
            c["rescued"] = False
            c["new_usable"] = None
        rep["focus"]["n_focus_rescued"] = 0
        rep["net_gain"] = {"pending_products": True,
                           "v2_usable_baseline": v2c["n_usable"],
                           "new_usable": None, "usable_delta": None,
                           "rescued_total": None}
        (out_dir / "netgain_te29.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        write_md(rep, out_dir)
        if not a.quiet:
            print("[待产物] %s" % new_err)
            print("v2 基线（冻结标签 %s，sha 核对=%s）：组合 %d ｜ 删失 %d ｜ 截断 %d ｜ 非可用 %d"
                  " ｜ 可用 %d ｜ Q 可判定 %d ｜ Q 达标 %d"
                  % (v2_meta["path"], v2_meta.get("sha256_ok"), v2c["n_cells"],
                     v2c["n_peak_at_scan_endpoint"], v2c["n_bw_upper_cutoff_at_endpoint"],
                     v2c["n_non_usable"], v2c["n_usable"], v2c["n_Q_decidable"],
                     v2c["n_Q_pass_2p5_3p5"]))
            print("        「24 格」普查：%d 格 ｜ 其中 v2 非可用 %d ｜ 不在声明扫描范围 %d"
                  "（x=0.10 的 8 格，已标「不在扫描范围、未救回」）｜ 在范围内但缺产物 %d"
                  % (rep["focus"]["n_focus_cells"], rep["focus"]["n_focus_non_usable_in_v2"],
                     rep["focus"]["n_focus_outside_declared_scan"],
                     rep["focus"]["n_focus_absent_from_new_scan"]))
            print("已写出 %s 与 netgain_te29.md" % (out_dir / "netgain_te29.json"))
        return 3

    # ---- 有产物：算救回与净增量 ----
    new_index = {(c["x_scale"], int(c["N_w_te1"])): c for c in new_cells}
    new_by_x = {k[0] for k in new_index}
    focus = focus_census(v2, new_by_x, n1s, focus_x, products_present=True)
    n_focus_rescued = 0
    for c in focus["cells"]:
        if not c["in_v2"]:
            c["rescued"] = False
            continue
        if not c["in_declared_scan"]:
            c["rescued"] = False
            c["reason"] = "不在新扫描范围（x 0.20→1.00 步长 0.01），未救回"
            continue
        if not c["present_in_new"]:
            c["rescued"] = False
            c["reason"] = "在声明扫描范围内但新导出缺该格（异常，未计增益）"
            continue
        nc = new_index[(c["x_scale"], c["N_w_te1"])]
        c["new_usable"] = bool(nc["usable"])
        c["new_peak_at_scan_endpoint"] = bool(nc["peak_at_scan_endpoint"])
        c["new_bw_upper_cutoff_at_endpoint"] = nc["bw_upper_cutoff_at_endpoint"]
        c["rescued"] = bool((not c["v2_usable"]) and nc["usable"])
        c["reason"] = ("v2 非可用 → 新导出可用（救回）" if c["rescued"] else
                       ("v2 非可用 → 新导出仍非可用" if not c["v2_usable"] else "v2 本就可"))
        n_focus_rescued += int(c["rescued"])
    focus["n_focus_rescued"] = n_focus_rescued
    rep["focus"] = focus

    rescued_all = []
    for key, c in sorted(v2.items()):
        if c["usable"]:
            continue
        if key not in new_index:
            continue
        nc = new_index[key]
        if nc["usable"]:
            rescued_all.append({"combo_key": c["combo_key"], "x_scale": key[0], "N_w_te1": key[1],
                                "v2_censored": c["censored"], "v2_truncated": c["truncated"]})
    rescued_by_x: dict = {}
    for r in rescued_all:
        rescued_by_x.setdefault("%.6f" % r["x_scale"], []).append(r["N_w_te1"])
    n_new_usable = sum(1 for c in new_cells if c["usable"])
    n_new_usable_alt = sum(1 for c in new_cells if c["usable_alt"])
    qdec = [c for c in new_cells if c["usable"] and c["Q_decidable"]]
    qpass = [c for c in new_cells if c["usable"] and c["Q_pass_2p5_3p5"]]
    rep["new_export"] = new_census
    rep["rescue"] = {
        "rule": "v2 非可用（删失或截断）且新导出 usable=True",
        "n_rescued_total": len(rescued_all),
        "rescued_by_x": {k: {"n": len(v), "N_w_te1": sorted(v)} for k, v in sorted(rescued_by_x.items())},
        "rescued_list": rescued_all,
        "focus_scope_note": "「24 格」= x ∈ %s × N1 ∈ %s（共 %d 格）"
                            % (list(focus_x), list(n1s), len(focus_x) * len(n1s)),
        "n_rescued_within_focus": n_focus_rescued,
        "n_focus_outside_declared_scan": focus["n_focus_outside_declared_scan"],
        "n_focus_absent_from_new_scan": focus["n_focus_absent_from_new_scan"],
        "n_focus_not_usable_in_v2": focus["n_focus_non_usable_in_v2"],
    }
    rep["net_gain"] = {
        "pending_products": False,
        "v2_usable_baseline": v2c["n_usable"],
        "v2_usable_baseline_peakaware": None,     # 冻结 CSV 只有主口径；峰值感知口径见 parse 侧 alt 列
        "new_cells": len(new_cells),
        "new_usable": n_new_usable,
        "usable_delta": n_new_usable - v2c["n_usable"],
        "new_usable_peakaware": n_new_usable_alt,
        "new_Q_decidable_among_usable": len(qdec),
        "new_Q_pass_2p5_3p5": len(qpass),
        "v2_Q_decidable": v2c["n_Q_decidable"],
        "v2_Q_pass_2p5_3p5": v2c["n_Q_pass_2p5_3p5"],
        "Q_pass_window": [Q_PASS_LO, Q_PASS_HI],
    }
    rep["pending_products"] = False

    (out_dir / "netgain_te29.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_md(rep, out_dir)
    if not a.quiet:
        print("新导出 = %s" % rep.get("new_cell_dir"))
        print("v2 基线 = %s（sha 核对 %s）" % (v2_meta["path"], v2_meta.get("sha256_ok")))
        print("可用：v2 %d → 新 %d（Δ %+d）｜ 峰值感知口径新 %d"
              % (v2c["n_usable"], n_new_usable, n_new_usable - v2c["n_usable"], n_new_usable_alt))
        print("Q 达标：v2 %d/%d → 新 %d/%d（分母 = 可用且 Q 非 nan）"
              % (v2c["n_Q_pass_2p5_3p5"], v2c["n_Q_decidable"], len(qpass), len(qdec)))
        print("救回：全量 %d 格 ｜「24 格」中 %d 格 ｜ 其中不在扫描范围未救回 %d 格"
              % (len(rescued_all), n_focus_rescued, focus["n_focus_absent_from_new_scan"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
