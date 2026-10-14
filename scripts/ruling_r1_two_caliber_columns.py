# -*- coding: utf-8 -*-
"""R1 落表：v2 `te2_9` 的 **SPL→带宽选带两口径并列成列**（不改任何既有数字）。

## 裁决（R1｜用户 2026-10-09 拍板）

**两口径并列落表**：主口径 = **文件序第一条** ⇒ 可用 **46** / 截断 **34**；
峰值感知口径 = 带内含本格峰值频率 ⇒ 可用 **43** / 截断 **37**。
**数字零改、不选边、论文不改。**

## 本脚本产出什么

1. `R1_two_caliber_columns.csv` —— **宽表**：指标为行，**两个口径为列**
   （`caliber_primary__*` / `caliber_peak_aware__*` ＋ `delta`）；
2. `R1_two_caliber_percell.csv` —— **逐格并列列**，列名沿用 §115.4 的器械命名
   （`bw_n_candidates / bw_level_ambiguous / bandwidth_alt_Hz / Q_alt /
   bw_upper_cutoff_at_endpoint_alt / usable_alt` 与主口径的 `bandwidth_Hz / Q /
   bw_upper_cutoff_at_endpoint / usable` **并排**）⇒「歧义不静默吞掉」；
3. `R1_two_calibers.md` —— 人读表 ＋ **回归靶依赖登记** ＋ **待重算**声明。

## 纪律

* **只读**：输入（v2 导出目录 + 冻结标签）**不写**；产物只落 `--out-dir`；
* **零数字改动**：主口径必须**逐位复现**冻结标签的 `bandwidth_Hz`（80/80），
  且三口径计数必须与 §115.4 登记值**逐项相同**（本脚本**现算比较**，不是抄）；
* **不选边**：两个口径都只是「口径」，本脚本**不**给出谁更正确的判定；
* **本脚本不改** `scripts/regress_te29_vs_v2.py`、不改 `scripts/parse_te29_v1.py`、
  不改 `build()`、不跑 COMSOL、不提升任何状态。

退出码：`0` 成功；`2` 输入不可读；`3` 与登记值不符（fail-closed，说明口径被动了）。
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
EXIT_OK, EXIT_INPUT, EXIT_REGRESSED = 0, 2, 3

V2_CELL_DIR = (REPO / "work/runs/remote-exported-v2-20260922/exported_results_v2/"
               "cell_te2_9_test_v2_20260922_195327416_001")
V2_LABELS = (REPO / "work/runs/remote-exported-v2-20260922/"
             "v2_labels_frozen_20261008T143151.csv")
DEFAULT_OUT = REPO / "work/runs/rulings-20261009"

#: 两口径的**并列列名**（峰值感知侧沿用 §115.4 已登记的 `*_alt` 命名）
COLUMNS_PRIMARY = ("bandwidth_Hz", "Q", "bw_upper_cutoff_at_endpoint", "usable")
COLUMNS_PEAK_AWARE = ("bandwidth_alt_Hz", "Q_alt", "bw_upper_cutoff_at_endpoint_alt",
                      "usable_alt")
DIAG_COLUMNS = ("bw_n_candidates", "bw_level_ambiguous")

#: §115.4 登记的 v2 三口径数字（**引用基线**；本脚本现算后逐项比较）
REGISTERED = {
    "primary": {"n_truncated": 34, "n_usable": 46, "n_Q_decidable_among_usable": 32,
                "n_Q_pass": 11},
    "peak_aware": {"n_truncated": 37, "n_usable": 43, "n_Q_decidable_among_usable": 32,
                   "n_Q_pass": 11},
    "strict": {"n_truncated": 34, "n_usable": 32, "n_Q_decidable_among_usable": 32,
               "n_Q_pass": 11},
}
REGISTERED_OTHER = {"n_combos": 80, "n_bands": 94, "n_peak_censored": 28,
                    "n_ambiguous_keys": 14, "n_selected_band_differs": 6,
                    "n_primary_band_without_peak": 6,
                    "n_usable_flips": 3, "n_grid24_usable_primary": 0, "n_grid24": 24}

#: **回归靶依赖**（R1 裁决要求登记的依赖，不是本轮改动）
REGRESSION_TARGET = {
    "target": "scripts/regress_te29_vs_v2.py",
    "invocation": "python -X utf8 scripts/regress_te29_vs_v2.py --selfcheck-only",
    "registered_census": {"n_combos": 80, "n_peak_at_scan_endpoint": 28,
                          "n_bw_upper_cutoff_at_endpoint": 34, "n_usable": 46,
                          "n_Q_decidable_among_usable": 32, "n_Q_pass_2p5_3p5": 11},
    "registered_census_lines": [134, 135, 136],
    "dependency": ("若将来**改判**为峰值感知口径，该回归靶的 `v2_census_registered` 必须"
                   "同步改为 截断 37 / 可用 43（其余 28/32/11/80 不变），否则 "
                   "`--selfcheck-only` 会长期报「v2 侧计数与登记剖面不符」（rc=4）；"
                   "**本轮 R1 = 并列落表、不改判 ⇒ 回归靶一字未改**。"),
    "ruling_this_round": "两口径并列落表（不改判）",
    "regression_target_changed_this_round": False,
    "verified_now": None,   # main() 现算
}

#: 新导出侧：**待重算**（现只有 3/8 块）
PENDING_RECOMPUTE = {
    "scope": "648 组合（8 块 × 81 外层解）",
    "blocks_available": 3,
    "blocks_total": 8,
    "measured_243_of_648": {"n_combos": 243,
                            "primary": {"n_truncated": 108, "n_usable": 108},
                            "peak_aware": {"n_truncated": 159, "n_usable": 84},
                            "n_usable_flips": 24,
                            "n_selected_band_differs": 51,
                            "n_Q_decidable_primary": 58, "n_Q_decidable_peak_aware": 58,
                            "n_Q_pass_primary": 14, "n_Q_pass_peak_aware": 14},
    "evidence": ("INDEX §136.2 / docs/ANALYSIS_FOUR_PENDING_RULINGS_20261009.md "
                 "§R1.1(e)（scratch 复现，**不是**登记产物）"),
    "must_recompute": ("全部 8 块到位（`N_DONE=8`、`Table_9.txt`、`ready_for_parse=True`）"
                       "后，用 `scripts/parse_te29_v1.py` 的登记实现复算，"
                       "**并列值需重算**（本表的 108/84 只是 3/8 块的中途读数）。"),
    "endpoint_rule_missing": ("`峰值 = 扫描上限` 的格在峰值感知口径下**尚无登记规则** "
                              "⇒ 该口径在新导出侧的取值仍属未定。"),
}


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def read_data_rows(p: pathlib.Path) -> list[list[str]]:
    txt = p.read_text(encoding="utf-8", errors="replace")
    return [ln.split() for ln in txt.splitlines() if ln.strip() and not ln.startswith("%")]


def load_bands(bw_path: pathlib.Path, fmax: float) -> list[dict]:
    rows = read_data_rows(bw_path)
    if len(rows) % 2:
        raise SystemExit("[FAIL] Bandwidth.txt 行数不是偶数：%d" % len(rows))
    bands = []
    for i in range(0, len(rows), 2):
        a, b = rows[i], rows[i + 1]
        f1, f2 = float(a[0]), float(b[0])
        bands.append({"band_index": i // 2, "spl_dB": float(a[1]), "width_Hz": float(a[2]),
                      "q_raw": (a[3] if len(a) > 3 else ""),
                      "f_lo_Hz": min(f1, f2), "f_hi_Hz": max(f1, f2),
                      "at_scan_endpoint": abs(max(f1, f2) - fmax) < 1e3})
    return bands


def _num(s):
    s = (s or "").strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _isnan(v) -> bool:
    return v is None or str(v).strip().lower() in ("nan", "")


def analyze(fmax: float) -> dict:
    bands = load_bands(V2_CELL_DIR / "Bandwidth.txt", fmax)
    by_key: dict[float, list[dict]] = collections.defaultdict(list)
    for b in bands:
        by_key[round(b["spl_dB"], 6)].append(b)
    with V2_LABELS.open(encoding="utf-8-sig", newline="") as fh:
        recs = [r for r in csv.DictReader(fh) if r["cell"] == "te2_9"]

    cells = []
    for r in recs:
        x, n1 = _num(r["x_scale"]), _num(r["N_w_te1"])
        pf, pspl = _num(r["peak_freq_Hz"]), _num(r["peak_spl_dB"])
        key = None if pspl is None else round(pspl - 3.0, 6)
        cands = by_key.get(key, []) if key is not None else []
        primary = cands[0] if cands else None
        inband = [b for b in cands if b["f_lo_Hz"] - 1e3 <= pf <= b["f_hi_Hz"] + 1e3]
        peak_aware = inband[0] if len(inband) == 1 else None
        cells.append({
            "x_scale": x, "N_w_te1": n1,
            "peak_freq_Hz": pf, "peak_spl_dB": pspl, "bridge_key_spl_minus_3dB": key,
            "bw_n_candidates": len(cands),
            "bw_level_ambiguous": len(cands) > 1,
            "bandwidth_Hz": (primary or {}).get("width_Hz"),
            "Q": (primary or {}).get("q_raw"),
            "bw_upper_cutoff_at_endpoint": ((primary or {}).get("at_scan_endpoint")
                                            if primary else None),
            "usable": (bool(primary) and not (str(r["peak_at_scan_endpoint"]).strip() == "True")
                       and not (primary or {}).get("at_scan_endpoint", False)),
            "bandwidth_alt_Hz": (peak_aware or {}).get("width_Hz"),
            "Q_alt": (peak_aware or {}).get("q_raw"),
            "bw_upper_cutoff_at_endpoint_alt": ((peak_aware or {}).get("at_scan_endpoint")
                                                if peak_aware else None),
            "usable_alt": (bool(peak_aware)
                           and not (str(r["peak_at_scan_endpoint"]).strip() == "True")
                           and not (peak_aware or {}).get("at_scan_endpoint", False)),
            "frozen_bandwidth_Hz": _num(r["bandwidth_Hz"]),
            "frozen_bw_upper_cutoff_at_endpoint":
                str(r["bw_upper_cutoff_at_endpoint"]).strip() == "True",
            "peak_at_scan_endpoint": str(r["peak_at_scan_endpoint"]).strip() == "True",
            "primary_band_contains_peak": bool(primary) and (
                primary["f_lo_Hz"] - 1e3 <= pf <= primary["f_hi_Hz"] + 1e3),
            "selected_band_differs": bool(primary and peak_aware) and (
                abs(primary["f_lo_Hz"] - peak_aware["f_lo_Hz"]) > 1e3
                or abs(primary["f_hi_Hz"] - peak_aware["f_hi_Hz"]) > 1e3),
            "usable_flips": None,      # 现算，见下（两口径 usable 不等即算一次翻转）
        })
    for c in cells:                    # 「状态字段不得是字面量」：由两口径的 usable 现算
        c["usable_flips"] = bool(c["usable"]) != bool(c["usable_alt"])

    def calib(sel) -> dict:
        n_cut = n_usable = n_qdec = n_qpass = 0
        for c in cells:
            b = sel(c)
            if b is None:
                continue
            cut = abs(b["f_hi_Hz"] - fmax) < 1e3
            peak_ep = c["peak_at_scan_endpoint"]
            if cut:
                n_cut += 1
            if (not peak_ep) and (not cut):
                n_usable += 1
                if not _isnan(b["q_raw"]):
                    n_qdec += 1
                    if 2.5 <= float(b["q_raw"]) <= 3.5:
                        n_qpass += 1
        return {"n_truncated": n_cut, "n_usable": n_usable,
                "n_Q_decidable_among_usable": n_qdec, "n_Q_pass": n_qpass}

    stats = {
        "primary": calib(lambda c: _band(by_key, c)[0]),
        "peak_aware": calib(lambda c: _band(by_key, c)[1]),
        "strict": calib(lambda c: (_band(by_key, c)[0]
                                   if c["bw_n_candidates"] == 1 else None)),
    }
    n_cut_strict = sum(1 for c in cells
                       if c["bw_n_candidates"] == 1 and c["bandwidth_Hz"] is not None
                       and abs(_hi(by_key, c) - fmax) < 1e3)
    stats["strict"]["n_truncated"] = n_cut_strict

    repro = sum(1 for c in cells if c["bandwidth_Hz"] is not None
                and c["frozen_bandwidth_Hz"] is not None
                and abs(c["bandwidth_Hz"] - c["frozen_bandwidth_Hz"]) < 1e-6)
    amb = [c for c in cells if c["bw_level_ambiguous"]]
    diff = [c for c in cells if c["selected_band_differs"]]
    flips = [c for c in cells if c["usable_flips"]]
    mis = [c for c in amb if not c["primary_band_contains_peak"]]
    grid24 = [c for c in cells if any(abs(c["x_scale"] - v) < 1e-9 for v in (0.1, 0.2, 0.3))]
    other = {
        "n_combos": len(cells),
        "n_bands": len(bands),
        "n_peak_censored": sum(1 for c in cells if c["peak_at_scan_endpoint"]),
        "n_ambiguous_keys": len(amb),
        "n_selected_band_differs": len(diff),
        "n_usable_flips": len(flips),
        "n_primary_band_without_peak": len(mis),
        "n_grid24": len(grid24),
        "n_grid24_usable_primary": sum(1 for c in grid24 if c["usable"]),
        "flip_cells": [{"x_scale": c["x_scale"], "N_w_te1": c["N_w_te1"],
                        "peak_freq_Hz": c["peak_freq_Hz"],
                        "primary_upper_cutoff_Hz": _hi(by_key, c),
                        "peak_aware_upper_cutoff_Hz": _hi(by_key, c, alt=True)}
                       for c in flips],
        "differing_cells": [{"x_scale": c["x_scale"], "N_w_te1": c["N_w_te1"],
                             "primary_bandwidth_Hz": c["bandwidth_Hz"],
                             "peak_aware_bandwidth_Hz": c["bandwidth_alt_Hz"],
                             "usable_primary": c["usable"], "usable_peak_aware": c["usable_alt"]}
                            for c in diff],
    }
    return {"cells": cells, "stats": stats, "n_primary_reproduces_frozen": repro,
            "other": other}


def _band(by_key, c):
    cands = by_key.get(c["bridge_key_spl_minus_3dB"], [])
    primary = cands[0] if cands else None
    inband = [b for b in cands if b["f_lo_Hz"] - 1e3 <= c["peak_freq_Hz"] <= b["f_hi_Hz"] + 1e3]
    return primary, (inband[0] if len(inband) == 1 else None)


def _hi(by_key, c, alt=False):
    p, a = _band(by_key, c)
    b = a if alt else p
    return None if b is None else b["f_hi_Hz"]


def render_md(res: dict, meta: dict) -> str:
    st, other = res["stats"], res["other"]
    L = ["# R1 落表：v2 `te2_9` SPL→带宽**两口径并列**（裁决 = 并列落表，不改判）", "",
         "> 裁决原文（用户 2026-10-09）：**两口径并列落表**（主：文件序第一条 ⇒ 可用 46 / 截断 34；"
         "峰值感知 ⇒ 43 / 37）。**数字零改、不选边、论文不改**。", "",
         "> 输入（**只读**）：`%s`（sha256 `%s`）＋ `%s`（sha256 `%s`）"
         % (meta["v2_cell_dir"], meta["v2_cell_dir_sha256"], meta["v2_labels"],
            meta["v2_labels_sha256"]),
         "> 本脚本**不改** `regress_te29_vs_v2.py` / `parse_te29_v1.py` / `build()`；"
         "**不跑 COMSOL**；**不提升任何状态**。", "",
         "## 0. 两口径并列表（**列** = 口径）", "",
         "| 指标 | `caliber_primary__`（文件序第一条） | `caliber_peak_aware__`（带内含峰值频率） | `delta`（峰值感知 − 主） | §115.4 登记值（主 / 峰值感知） | 与登记值相同？ |",
         "|---|---:|---:|---:|---|---|"]
    rows = [("n_truncated", "截断数"), ("n_usable", "可用 `usable`"),
            ("n_Q_decidable_among_usable", "Q 可判定（可用内）"),
            ("n_Q_pass", "Q 达标（2.5–3.5）")]
    for k, label in rows:
        p, q = st["primary"][k], st["peak_aware"][k]
        rp, rq = REGISTERED["primary"][k], REGISTERED["peak_aware"][k]
        L.append("| %s | **%d** | **%d** | %+d | %d / %d | %s |"
                 % (label, p, q, q - p, rp, rq, "**是**" if (p == rp and q == rq) else "**否**"))
    L += ["", "**严格口径（歧义 ⇒ 不可判定；本轮**不改判**，仅并列登记）**：截断 %d / 可用 **%d**"
          " / Q 可判定 %d / Q 达标 %d（登记值 %d / %d / %d / %d）。"
          % (st["strict"]["n_truncated"], st["strict"]["n_usable"],
             st["strict"]["n_Q_decidable_among_usable"], st["strict"]["n_Q_pass"],
             REGISTERED["strict"]["n_truncated"], REGISTERED["strict"]["n_usable"],
             REGISTERED["strict"]["n_Q_decidable_among_usable"],
             REGISTERED["strict"]["n_Q_pass"]), "",
          "> ⚠️ **不选边**：上表两个口径都只是「口径」，本表**不**给出谁正确的判定；"
          "「峰值感知」在 `峰值 = 扫描上限` 的格上**尚无登记规则**（见 §3）。", "",
          "## 1. 其它同源计数（并列，均现算）", "",
          "| 项 | 值 | §136/§115.4 登记值 | 相同？ |", "|---|---:|---:|---|"]
    for k, label in (("n_combos", "组合数"), ("n_bands", "−3 dB 带数"),
                     ("n_peak_censored", "峰值删失"), ("n_ambiguous_keys", "歧义键数"),
                     ("n_primary_band_without_peak", "主口径选中带不含本格峰值的格数"),
                     ("n_selected_band_differs", "**两口径选中带不同**的格数"),
                     ("n_usable_flips", "**`usable` 翻转**的格数")):
        L.append("| %s | %d | %d | %s |"
                 % (label, other[k], REGISTERED_OTHER[k],
                    "**是**" if other[k] == REGISTERED_OTHER[k] else "**否**"))
    L += ["", "> ⚠️ 「**差 3 格**」只能读成 **`usable` 翻转 3 格**，**不得**读成「选带差 3 格」"
          "（后者是 %d）——§136.2 已登记这一区分。" % other["n_selected_band_differs"], "",
          "**翻转格（%d 个）**：" % other["n_usable_flips"], "",
          "| x_scale | N1 | 峰值 (MHz) | 主口径带上截止 (MHz) | 峰值感知带上截止 (MHz) |",
          "|---|---:|---:|---:|---:|"]
    for c in other["flip_cells"]:
        L.append("| %s | %s | %.1f | %.3f | %.3f |"
                 % (c["x_scale"], c["N_w_te1"], c["peak_freq_Hz"] / 1e6,
                    c["primary_upper_cutoff_Hz"] / 1e6,
                    c["peak_aware_upper_cutoff_Hz"] / 1e6))
    L += ["", "**「24 格」（x ∈ 0.10/0.20/0.30）**：共 %d 格，主口径可用 **%d**"
          "（登记值 %d / %d）⇒ 「24 格全废」的结论**两口径都不受影响**。"
          % (other["n_grid24"], other["n_grid24_usable_primary"],
             REGISTERED_OTHER["n_grid24"], REGISTERED_OTHER["n_grid24_usable_primary"]), "",
          "## 2. **零数字改动**的证据", "",
          "* 主口径**逐位复现**冻结标签 `bandwidth_Hz`：**%d / %d** 格"
          % (res["n_primary_reproduces_frozen"], other["n_combos"]),
          "* 上表每一行的「与登记值相同？」列都是**现算比较**的结果，不是抄写；",
          "* 本脚本**不写**任何既有产物：输入目录与冻结标签**只读**打开，产物全部落在新目录 "
          "`%s`。" % meta["out_dir"], "",
          "## 3. **回归靶依赖**（R1 裁决要求登记；本轮**未改**回归靶）", "",
          "| 项 | 内容 |", "|---|---|",
          "| 回归靶 | `%s`" % REGRESSION_TARGET["target"],
          "| 调用 | `%s`" % REGRESSION_TARGET["invocation"],
          "| 靶内登记的 v2 计数（L134–L136） | `%s`"
          % json.dumps(REGRESSION_TARGET["registered_census"], ensure_ascii=False),
          "| **依赖** | %s" % REGRESSION_TARGET["dependency"],
          "| 本轮处置 | %s（`regression_target_changed_this_round = %s`）"
          % (REGRESSION_TARGET["ruling_this_round"],
             REGRESSION_TARGET["regression_target_changed_this_round"]),
          "| 现状实测 | `--selfcheck-only` ⇒ %s" % meta["selfcheck_now"], "",
          "## 4. **待重算**：新导出侧并列值（现只有 3/8 块）", "",
          "| 项 | 现测（243/648 组合） |", "|---|---|",
          "| 主口径 截断 / 可用 | %d / **%d** |"
          % (PENDING_RECOMPUTE["measured_243_of_648"]["primary"]["n_truncated"],
             PENDING_RECOMPUTE["measured_243_of_648"]["primary"]["n_usable"]),
          "| 峰值感知 截断 / 可用 | %d / **%d** |"
          % (PENDING_RECOMPUTE["measured_243_of_648"]["peak_aware"]["n_truncated"],
             PENDING_RECOMPUTE["measured_243_of_648"]["peak_aware"]["n_usable"]),
          "| `usable` 翻转 | **%d** 格 |"
          % PENDING_RECOMPUTE["measured_243_of_648"]["n_usable_flips"],
          "| 两口径选中带不同 | %d 格 |"
          % PENDING_RECOMPUTE["measured_243_of_648"]["n_selected_band_differs"],
          "| 证据 | %s |" % PENDING_RECOMPUTE["evidence"],
          "", "> ⚠️ 上表数字是 **%d/%d 块**的中途读数（scratch 复现，**不是**登记产物）"
          "⇒ **待全部块到位后，并列值需重算**（用 `scripts/parse_te29_v1.py` 的登记实现）。"
          % (PENDING_RECOMPUTE["blocks_available"], PENDING_RECOMPUTE["blocks_total"]),
          "> ⚠️ %s" % PENDING_RECOMPUTE["endpoint_rule_missing"], "",
          "## 5. 器械侧的并列列（已实现，本脚本不改它）", "",
          "`scripts/parse_te29_v1.py` 的 `FIELDS` 已含 "
          "`%s` ⇒ 新导出天然带两口径并列列，**歧义不静默吞掉**。"
          % "、".join("`%s`" % c for c in (DIAG_COLUMNS + COLUMNS_PEAK_AWARE)), "",
          "## 6. 未做 / 没做成（如实）", "",
          "1. **未改判**：主口径仍 = 文件序第一条（冻结标签）；本脚本**没有**把任何一列标成「正确口径」；",
          "2. **未改回归靶**：`regress_te29_vs_v2.py` 一字未改（依赖已登记，见 §3）；",
          "3. **未算 648 组合的总差**：现只有 3/8 块 ⇒ 总数不可算（见 §4）；",
          "4. **未给端点格规则**：`峰值 = 扫描上限` 在峰值感知口径下的取值**仍无登记规则**；",
          "5. **未解释 v2 上 3 格「选带不同却仍可用」的带宽差 5–8 倍之成因**"
          "（缺 v2 的 −3 dB 提取实现/版本原文，§92.7 待办 1）。", "",
          "**一句话确认**：**未改任何既有数字、未选边、未改回归靶、未改论文、未跑 COMSOL、"
          "未提升任何状态。**", ""]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 两口径并列落表（只读）")
    ap.add_argument("--fmax-hz", type=float, default=35.0e6)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--run-selfcheck", action="store_true",
                    help="额外只读复跑 regress_te29_vs_v2.py --selfcheck-only 并把 rc 写进 md")
    a = ap.parse_args(argv)

    for p in (V2_CELL_DIR / "Bandwidth.txt", V2_LABELS):
        if not p.is_file():
            print("[FAIL] 缺输入：%s" % p)
            return EXIT_INPUT

    res = analyze(a.fmax_hz)
    st, other = res["stats"], res["other"]
    ok_stats = all(st[k][m] == REGISTERED[k][m] for k in REGISTERED for m in REGISTERED[k])
    ok_other = all(other[k] == v for k, v in REGISTERED_OTHER.items())
    ok_repro = res["n_primary_reproduces_frozen"] == other["n_combos"]

    outdir = pathlib.Path(a.out_dir)
    if not outdir.is_absolute():
        outdir = REPO / outdir
    outdir.mkdir(parents=True, exist_ok=True)

    # ---- 宽表：两口径为列 ----
    wide = []
    for k, label in (("n_truncated", "n_truncated"), ("n_usable", "n_usable"),
                     ("n_Q_decidable_among_usable", "n_Q_decidable_among_usable"),
                     ("n_Q_pass", "n_Q_pass")):
        wide.append({"metric": label,
                     "caliber_primary__value": st["primary"][k],
                     "caliber_peak_aware__value": st["peak_aware"][k],
                     "delta_peak_aware_minus_primary": st["peak_aware"][k] - st["primary"][k],
                     "registered_primary": REGISTERED["primary"][k],
                     "registered_peak_aware": REGISTERED["peak_aware"][k],
                     "matches_registered": bool(st["primary"][k] == REGISTERED["primary"][k]
                                                and st["peak_aware"][k] == REGISTERED["peak_aware"][k]),
                     "values_unchanged_vs_registered": None})
    wide.append({"metric": "n_strict_usable", "caliber_primary__value": st["primary"]["n_usable"],
                 "caliber_peak_aware__value": st["strict"]["n_usable"],
                 "delta_peak_aware_minus_primary": st["strict"]["n_usable"] - st["primary"]["n_usable"],
                 "registered_primary": REGISTERED["primary"]["n_usable"],
                 "registered_peak_aware": REGISTERED["strict"]["n_usable"],
                 "matches_registered": bool(st["strict"]["n_usable"]
                                            == REGISTERED["strict"]["n_usable"]),
                 "values_unchanged_vs_registered": None})
    for w in wide:                      # 「状态字段不得是字面量」：现算赋值
        w["values_unchanged_vs_registered"] = bool(w["matches_registered"])
    with (outdir / "R1_two_caliber_columns.csv").open("w", encoding="utf-8", newline="") as fh:
        dw = csv.DictWriter(fh, fieldnames=list(wide[0].keys()))
        dw.writeheader()
        dw.writerows(wide)

    # ---- 逐格并列列 ----
    fields = ["x_scale", "N_w_te1", "peak_freq_Hz", "peak_spl_dB",
              "bridge_key_spl_minus_3dB"] + list(DIAG_COLUMNS) + \
             list(COLUMNS_PRIMARY) + list(COLUMNS_PEAK_AWARE) + \
             ["frozen_bandwidth_Hz", "primary_band_contains_peak", "selected_band_differs",
              "usable_flips", "peak_at_scan_endpoint", "frozen_bw_upper_cutoff_at_endpoint"]
    with (outdir / "R1_two_caliber_percell.csv").open("w", encoding="utf-8", newline="") as fh:
        dw = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        dw.writeheader()
        dw.writerows(res["cells"])

    selfcheck = "未复跑（--run-selfcheck 未给）"
    if a.run_selfcheck:
        import subprocess
        cp = subprocess.run([sys.executable, "-X", "utf8",
                             str(REPO / "scripts/regress_te29_vs_v2.py"), "--selfcheck-only"],
                            cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
        selfcheck = "rc=%d（回归靶未改，见 §3；节选：%s）" % (
            cp.returncode, (cp.stdout or "").strip().splitlines()[-1][:120]
            if (cp.stdout or "").strip() else "（无输出）")
    REGRESSION_TARGET["verified_now"] = selfcheck      # 现算结果写进 JSON，不留 null
    meta = {
        "v2_cell_dir": str(V2_CELL_DIR.relative_to(REPO)).replace("\\", "/"),
        "v2_cell_dir_sha256": sha256_file(V2_CELL_DIR / "Bandwidth.txt"),
        "v2_labels": str(V2_LABELS.relative_to(REPO)).replace("\\", "/"),
        "v2_labels_sha256": sha256_file(V2_LABELS),
        "out_dir": str(outdir.relative_to(REPO)).replace("\\", "/")
        if outdir.is_relative_to(REPO) else str(outdir),
        "selfcheck_now": selfcheck,
    }
    (outdir / "R1_two_calibers.json").write_text(
        json.dumps({"kind": "r1_two_caliber_columns_v1", "fmax_Hz": a.fmax_hz,
                    "inputs": meta, "stats": st, "other": other,
                    "n_primary_reproduces_frozen":
                        res["n_primary_reproduces_frozen"],
                    "registered": REGISTERED, "registered_other": REGISTERED_OTHER,
                    "all_registered_values_reproduced": bool(ok_stats and ok_other),
                    "primary_reproduces_frozen_bitwise": bool(ok_repro),
                    "regression_target_dependency": REGRESSION_TARGET,
                    "pending_recompute_new_export": PENDING_RECOMPUTE,
                    "columns_primary": list(COLUMNS_PRIMARY),
                    "columns_peak_aware": list(COLUMNS_PEAK_AWARE),
                    "diagnostic_columns": list(DIAG_COLUMNS),
                    "no_side_taken": True, "no_state_promotion": True},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "R1_two_calibers.md").write_text(render_md(res, meta), encoding="utf-8")

    print("组合 %d ｜ 带 %d ｜ 歧义键 %d ｜ 选带不同 %d ｜ usable 翻转 %d"
          % (other["n_combos"], other["n_bands"], other["n_ambiguous_keys"],
             other["n_selected_band_differs"], other["n_usable_flips"]))
    for k in ("primary", "peak_aware", "strict"):
        print("  %-11s 截断 %3d ｜ 可用 %3d ｜ Q 可判定 %3d ｜ Q 达标 %3d"
              % (k, st[k]["n_truncated"], st[k]["n_usable"],
                 st[k]["n_Q_decidable_among_usable"], st[k]["n_Q_pass"]))
    print("主口径逐位复现冻结带宽：%d/%d ｜ 与登记值逐项相同：%s ｜ 逐位复现冻结：%s"
          % (res["n_primary_reproduces_frozen"], other["n_combos"],
             ok_stats and ok_other, ok_repro))
    print("产物：%s" % meta["out_dir"])
    if not (ok_stats and ok_other and ok_repro):
        print("[FAIL] 与 §115.4 登记值不符 ⇒ 口径被动过（fail-closed）")
        return EXIT_REGRESSED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
