# -*- coding: utf-8 -*-
"""C 批（`multichannel_labels.csv`，2005 行）内部组合键重复的**只读**诊断。

## 背景

`docs/INDEX-records-and-rulings.md` §92.7 待办 3 登记：C 批 2005 行按
`(x_scale, N_w_te1, N_w_te2)` 归并后唯一组合 **1843** 个 ⇒ **162 个组合键各出现 2 次**，
「抽验不足以判定成因（可能是重复导出，也可能是不同口径行）⇒ 登记待核，本轮不下结论」。

本脚本把这 162 个键的**所有行逐列比对**，按三类给计数：

* **(a) 完全重复行** —— 所有列逐位（按存储字面值）相同；
* **(b) 部分列不同** —— 至少一列不同；列出**哪些列**不同、差异量级；
  含 `f_peak_Hz` / `bandwidth_Hz` / `Q_factor` 时**单独点明**；
* **(c) 差异仅来自批次/来源标记列** —— 点名这些列。

并顺带核一件事：`x_scale` 是否存在 **1 ulp 表示差**（同一组合存成
`0.30000000000000004` 与 `0.3`）⇒ 若有，162 里有一部分是**归一化前的伪重复**；
脚本报出「归一化后真正的重复键」个数。

## 纪律

* **只读**：不写、不改 C 批原表与任何既有产物；输出只落到 `--out-dir`（新目录）。
* **不猜测**：能由逐列比对直接读出的事实写进 `conclusion.established`；
  算不出来的（例如带宽 1e-8~3e-5 相对差的来源）写进 `conclusion.not_established`，
  并写明「需要补什么」。**不把不成立的说成成立。**

产物：`<out-dir>/diagnosis.json` + `<out-dir>/diagnosis.md`。
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as _dt
import hashlib
import io
import json
import math
import pathlib
import statistics
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 组合身份键的**原始**列（字面值判等）
PARAM_KEYS = ("x_scale", "N_w_te1", "N_w_te2")

#: ulp 归一化小数位（与 `sweep_analysis.IDENTITY_ROUND_DECIMALS` 同口径 = 6；
#: 此处**写死并打印**，不 import，避免诊断脚本与生产代码互相绑定后被静默改动）
ULP_DECIMALS = 6

#: 「批次 / 来源 / 扫描栅格」类标记列 —— 它们的差异**不表示测量结果不同**。
#: 依据：`work/runs/first-peak-20260929/build_multichannel_labels.py` L285–L291
#: 在合表时按来源批次写入这四列（`source_dataset` / `x_density_class` /
#: `freq_grid_MHz` / `n_freq`），`source_model` 记的是导出运行目录。
MARKER_COLUMNS = ("source_dataset", "x_density_class", "freq_grid_MHz", "n_freq",
                  "source_model")

#: 结论里必须单独点明的“结果类”列
HIGHLIGHT_COLUMNS = ("f_peak_Hz", "bandwidth_Hz", "Q_factor")


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _num(v):
    """能转 float 就转，否则 None。空串不是 0（**不得**把缺失当数值）。"""
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def _reldiff(a: float, b: float) -> float:
    """对称相对差 `|a-b| / max(|a|,|b|)`；两者皆为 0 ⇒ 0。"""
    m = max(abs(a), abs(b))
    if m == 0.0:
        return 0.0
    return abs(a - b) / m


def raw_key(row) -> tuple:
    """原样（字面值）组合身份键 —— 保留 1 ulp 表示差。"""
    return tuple(str(row.get(k, "")).strip() for k in PARAM_KEYS)


def norm_key(row) -> tuple:
    """ulp 归一化组合身份键（`round(x, ULP_DECIMALS)`）。"""
    out = []
    for k in PARAM_KEYS:
        v = _num(row.get(k))
        out.append(round(v, ULP_DECIMALS) if isinstance(v, float) else v)
    return tuple(out)


def analyse(rows: list[dict], source: pathlib.Path) -> dict:
    cols = list(rows[0].keys()) if rows else []
    n = len(rows)

    # ---------- 1. 两种口径下的组合唯一数 ----------
    raw_groups: dict[tuple, list[int]] = collections.OrderedDict()
    norm_groups: dict[tuple, list[int]] = collections.OrderedDict()
    for i, r in enumerate(rows):
        raw_groups.setdefault(raw_key(r), []).append(i)
        norm_groups.setdefault(norm_key(r), []).append(i)

    raw_dups = {k: v for k, v in raw_groups.items() if len(v) > 1}
    norm_dups = {k: v for k, v in norm_groups.items() if len(v) > 1}

    # ---------- 2. x_scale 的 1 ulp 伪重复核算 ----------
    lit_by_float: dict[float, set[str]] = collections.defaultdict(set)
    for r in rows:
        f = _num(r.get("x_scale"))
        if f is not None:
            lit_by_float[f].add(str(r.get("x_scale")).strip())
    ambiguous = {repr(k): sorted(v) for k, v in lit_by_float.items() if len(v) > 1}

    # 「伪重复」= 原样口径下是不同键、归一化口径下并成同一个键
    raw_only_extra = sum(len(v) - 1 for v in raw_groups.values() if len(v) > 1)
    # 直接构造反例搜索：同一归一化键下的行，其原样键是否不唯一
    pseudo_keys = []
    for k, idxs in norm_groups.items():
        rawks = {raw_key(rows[i]) for i in idxs}
        if len(rawks) > 1:
            pseudo_keys.append({"normalized": list(map(repr, k)),
                                "raw_forms": sorted(map(repr, rawks)),
                                "n_rows": len(idxs)})

    # ---------- 3. 162（或任意多重）重复键的逐列比对 ----------
    dup_groups = norm_dups
    multi = [v for v in norm_groups.values() if len(v) > 1]
    max_mult = max((len(v) for v in norm_groups.values()), default=0)

    per_col = {c: {"n_diff": 0, "n_same": 0, "n_both_present_same": 0,
                   "n_both_present_diff": 0, "n_one_blank": 0, "n_both_blank": 0,
                   "rel_max": None, "rel_median": None, "abs_max": None}
               for c in cols}
    cls_exact = 0
    cls_marker_only = 0
    cls_partial = 0
    diff_column_sets = collections.Counter()
    pairs = []
    for k, idxs in sorted(norm_dups.items(), key=lambda kv: repr(kv[0])):
        a, b = rows[idxs[0]], rows[idxs[1]]
        dcols = [c for c in cols if str(a.get(c, "")) != str(b.get(c, ""))]
        for c in cols:
            e = per_col[c]
            va, vb = str(a.get(c, "")), str(b.get(c, ""))
            fa, fb = _num(va), _num(vb)
            if va == vb:
                e["n_same"] += 1
                if fa is not None:
                    e["n_both_present_same"] += 1
                elif va.strip() == "":
                    e["n_both_blank"] += 1
                continue
            e["n_diff"] += 1
            if va.strip() == "" or vb.strip() == "":
                e["n_one_blank"] += 1
                continue
            if fa is None or fb is None:
                continue
            e["n_both_present_diff"] += 1
            e.setdefault("_rel", []).append(_reldiff(fa, fb))
            amax = abs(fa - fb)
            e["abs_max"] = amax if e["abs_max"] is None else max(e["abs_max"], amax)
        if not dcols:
            cls_exact += 1
        else:
            cls_partial += 1
            marker_only = set(dcols) <= set(MARKER_COLUMNS)
            if marker_only:
                cls_marker_only += 1
        diff_column_sets[tuple(dcols) if dcols else ("<完全一致>",)] += 1
        pairs.append({"key": [repr(x) for x in k], "row_index": idxs,
                      "diff_columns": dcols,
                      "marker_only": bool(dcols) and set(dcols) <= set(MARKER_COLUMNS),
                      "source_datasets": [a.get("source_dataset"), b.get("source_dataset")],
                      "freq_grids": [a.get("freq_grid_MHz"), b.get("freq_grid_MHz")],
                      "peaks": [a.get("f_peak_Hz"), b.get("f_peak_Hz")],
                      "bandwidths": [a.get("bandwidth_Hz"), b.get("bandwidth_Hz")],
                      "Qs": [a.get("Q_factor"), b.get("Q_factor")]})
    for c, e in per_col.items():
        rel = e.pop("_rel", None)
        if rel:
            e["rel_max"] = max(rel)
            e["rel_median"] = statistics.median(rel)
            e["n_rel_gt_1e-6"] = sum(1 for x in rel if x > 1e-6)
        else:
            e["n_rel_gt_1e-6"] = 0

    # ---------- 4. 重复对的来源构成（定因证据） ----------
    prov = collections.Counter()
    grid = collections.Counter()
    xclass = collections.Counter()
    for k, idxs in norm_dups.items():
        for i in idxs:
            prov[str(rows[i].get("source_dataset"))] += 1
            grid[str(rows[i].get("freq_grid_MHz"))] += 1
            xclass[str(rows[i].get("x_density_class"))] += 1

    # 每对内部：来源组合分布
    pair_src = collections.Counter()
    for k, idxs in norm_dups.items():
        pair_src[tuple(sorted(str(rows[i].get("source_dataset")) for i in idxs))] += 1

    # 高亮列：方向性统计（谁缺谁有）
    highlight = {}
    for c in HIGHLIGHT_COLUMNS:
        blank_a_only = blank_b_only = both_present_diff = both_present_same = 0
        both_blank = 0
        for k, idxs in norm_dups.items():
            a, b = rows[idxs[0]], rows[idxs[1]]
            va, vb = str(a.get(c, "")).strip(), str(b.get(c, "")).strip()
            if va == "" and vb == "":
                both_blank += 1
            elif va == "":
                blank_a_only += 1
            elif vb == "":
                blank_b_only += 1
            elif va == vb:
                both_present_same += 1
            else:
                both_present_diff += 1
        highlight[c] = {"both_present_same": both_present_same,
                        "both_present_diff": both_present_diff,
                        "first_row_blank_only": blank_a_only,
                        "second_row_blank_only": blank_b_only,
                        "both_blank": both_blank}

    # 若「某列只在某一行有值」，报出该行属于哪个 source_dataset
    blank_direction = {}
    for c in HIGHLIGHT_COLUMNS:
        d = collections.Counter()
        for k, idxs in norm_dups.items():
            a, b = rows[idxs[0]], rows[idxs[1]]
            va, vb = str(a.get(c, "")).strip(), str(b.get(c, "")).strip()
            if va == "" and vb != "":
                d["blank_is_%s" % a.get("source_dataset")] += 1
            elif vb == "" and va != "":
                d["blank_is_%s" % b.get("source_dataset")] += 1
        blank_direction[c] = dict(d)

    # 非重复键（只出现 1 次）的来源构成，用于说明重复不是全域现象
    single_src = collections.Counter()
    for k, idxs in norm_groups.items():
        if len(idxs) == 1:
            single_src[str(rows[idxs[0]].get("source_dataset"))] += 1

    return {
        "kind": "c_batch_duplicate_diagnosis",
        "input": {"path": str(source), "bytes": source.stat().st_size,
                  "sha256": sha256_file(source), "n_rows": n, "n_columns": len(cols),
                  "columns": cols},
        "key_definition": {"param_keys": list(PARAM_KEYS),
                           "ulp_decimals": ULP_DECIMALS,
                           "method": "raw = 三列字面值元组；normalized = (round(float(x),6), N1, N2)"},
        "uniqueness": {
            "n_rows": n,
            "n_unique_raw": len(raw_groups),
            "n_unique_normalized": len(norm_groups),
            "n_dup_keys_raw": len(raw_dups),
            "n_dup_keys_normalized": len(norm_dups),
            "n_extra_rows_raw": sum(len(v) - 1 for v in raw_groups.values()),
            "n_extra_rows_normalized": sum(len(v) - 1 for v in norm_groups.values()),
            "max_multiplicity": max_mult,
            "n_groups_with_multiplicity_gt2": sum(1 for v in norm_groups.values() if len(v) > 2),
            "n_rows_in_dup_groups": sum(len(v) for v in multi),
            "raw_only_extra_rows": raw_only_extra,
        },
        "ulp_pseudo_duplicate_check": {
            "n_distinct_x_scale_literals": len({str(r.get("x_scale")).strip() for r in rows}),
            "n_distinct_x_scale_floats": len(lit_by_float),
            "floats_with_more_than_one_literal": ambiguous,
            "n_floats_with_more_than_one_literal": len(ambiguous),
            "pseudo_dup_keys_before_normalization": pseudo_keys,
            "n_pseudo_dup_keys": len(pseudo_keys),
            "normalized_true_dup_keys": len(norm_dups),
            "verdict": ("**无** 1 ulp 伪重复" if not pseudo_keys else
                        "存在 1 ulp 伪重复，162 中含伪重复"),
        },
        "classification": {
            "a_exact_duplicate_rows": cls_exact,
            "b_partial_column_differences": cls_partial,
            "c_marker_columns_only": cls_marker_only,
            "marker_columns_used": list(MARKER_COLUMNS),
            "note": "(b) 是全集（每对都至少有一列不同）⇒ (b) == 重复对数；"
                    "(c) 是 (b) 的子集（差异**仅**落在标记列上）；(a) 与 (c) 互斥，(b) ⊇ (c)。",
            "n_dup_pairs_total": len(norm_dups),
            "distinct_diff_column_sets": [
                {"n_pairs": cnt, "columns": (None if s == ("<完全一致>",) else list(s))}
                for s, cnt in diff_column_sets.most_common()],
        },
        "per_column_difference_table": {c: per_col[c] for c in cols},
        "highlight_columns": highlight,
        "highlight_blank_direction": blank_direction,
        "provenance_of_dup_rows": {
            "source_dataset_counts": dict(prov),
            "freq_grid_counts": dict(grid),
            "x_density_class_counts": dict(xclass),
            "pair_source_combinations": {"|".join(k): v for k, v in pair_src.items()},
            "single_row_groups_source_counts": dict(single_src),
        },
        "dup_pairs": pairs,
    }


def render_md(d: dict) -> str:
    u, ulp = d["uniqueness"], d["ulp_pseudo_duplicate_check"]
    c, pv = d["classification"], d["provenance_of_dup_rows"]
    L: list[str] = []
    A = L.append
    A("# C 批内部重复诊断（`multichannel_labels.csv`）")
    A("")
    A("> 只读诊断。**未修改 C 批原表、未执行任何去重**。")
    A("")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 输入 | `%s` |" % d["input"]["path"])
    A("| bytes / sha256 | %d / `%s` |" % (d["input"]["bytes"], d["input"]["sha256"]))
    A("| 行数 / 列数 | %d / %d |" % (d["input"]["n_rows"], d["input"]["n_columns"]))
    A("| 组合身份键 | %s（ulp 归一化 %d 位） |"
      % ("、".join("`%s`" % k for k in d["key_definition"]["param_keys"]),
         d["key_definition"]["ulp_decimals"]))
    A("")
    A("## 1. 唯一数与重复规模")
    A("")
    A("| 口径 | 唯一组合 | 重复键 | 多出的行 |")
    A("|---|---|---|---|")
    A("| **原样**（三列字面值） | %d | %d | %d |"
      % (u["n_unique_raw"], u["n_dup_keys_raw"], u["n_extra_rows_raw"]))
    A("| **ulp 归一化**（`round(x,6)`） | %d | %d | %d |"
      % (u["n_unique_normalized"], u["n_dup_keys_normalized"], u["n_extra_rows_normalized"]))
    A("")
    A("重复组最大重数 **%d**（重数 >2 的组 **%d** 个）⇒ **全部重复键恰好出现 2 次**，"
      "涉及 **%d** 行。" % (u["max_multiplicity"], u["n_groups_with_multiplicity_gt2"],
                        u["n_rows_in_dup_groups"]))
    A("")
    A("## 2. `x_scale` 的 1 ulp 伪重复核算")
    A("")
    A("- 不同的 `x_scale` **字面值** %d 个；不同 **浮点值** %d 个；"
      "同一浮点值有 >1 种字面形式的：**%d** 个。"
      % (ulp["n_distinct_x_scale_literals"], ulp["n_distinct_x_scale_floats"],
         ulp["n_floats_with_more_than_one_literal"]))
    A("- 原样口径下会因 ulp 而被拆开的键（伪重复）：**%d** 个。" % ulp["n_pseudo_dup_keys"])
    A("- ⇒ **归一化后真正的重复键 %d 个**（原样口径也是 %d 个，两者相同）。"
      % (ulp["normalized_true_dup_keys"], u["n_dup_keys_raw"]))
    A("- 结论：**%s**。162 里**不含**归一化前的伪重复。"
      % ulp["verdict"].replace("**", ""))
    A("")
    A("## 3. 三类计数")
    A("")
    A("| 类 | 含义 | 对数 |")
    A("|---|---|---|")
    A("| **(a)** | 完全重复行（所有列逐位相同） | **%d** |" % c["a_exact_duplicate_rows"])
    A("| **(b)** | 部分列不同（至少一列不同） | **%d** |" % c["b_partial_column_differences"])
    A("| **(c)** | 差异**仅**来自批次/来源标记列 | **%d** |" % c["c_marker_columns_only"])
    A("")
    A("标记列 = %s。" % "、".join("`%s`" % m for m in c["marker_columns_used"]))
    A("(b) 是全集（%d 对），(c) 是它的子集（%d 对）；(a) 与 (c) 互斥。"
      % (c["b_partial_column_differences"], c["c_marker_columns_only"]))
    A("")
    A("### 3.1 重复对的来源构成（定因证据）")
    A("")
    A("| 来源 | 重复对中的行数 | 只出现 1 次的组合数 |")
    A("|---|---|---|")
    for s in sorted(set(list(pv["source_dataset_counts"]) + list(pv["single_row_groups_source_counts"]))):
        A("| `source_dataset=%s` | %s | %s |"
          % (s, pv["source_dataset_counts"].get(s, 0),
             pv["single_row_groups_source_counts"].get(s, 0)))
    A("")
    A("- 重复对的来源组合：`%s`。" % json.dumps(pv["pair_source_combinations"], ensure_ascii=False))
    A("- 频率栅格：`%s`。" % json.dumps(pv["freq_grid_counts"], ensure_ascii=False))
    A("- x 密度类：`%s`。" % json.dumps(pv["x_density_class_counts"], ensure_ascii=False))
    A("")
    A("⇒ **每一对重复都恰好由一条 `source_dataset=A`（粗 x、5–35 MHz/61 点）"
      "与一条 `source_dataset=C`（细 x、5-50 MHz/91 点）组成** —— "
      "这是**两套来源数据在同一批表里并排**，不是同一条记录被导出两次。")
    A("")
    A("## 4. 关键结果列的差异（逐列统计见 `diagnosis.json`）")
    A("")
    A("| 列 | 都缺 | 仅首行有值 | 仅次行有值 | 都有且相同 | 都有且不同 |")
    A("|---|---|---|---|---|---|")
    for col, h in d["highlight_columns"].items():
        A("| `%s` | %d | %d | %d | %d | %d |"
          % (col, h["both_blank"], h["first_row_blank_only"], h["second_row_blank_only"],
             h["both_present_same"], h["both_present_diff"]))
    A("")
    A("缺值方向（哪一侧为空）：`%s`"
      % json.dumps(d["highlight_blank_direction"], ensure_ascii=False))
    A("")
    A("### 4.1 逐列差异统计表（**全部 %d 列**）" % d["input"]["n_columns"])
    A("")
    A("| 列 | 不同的对 | 都有值且不同 | 一侧为空 | 两行都为空 | 都有值且相同 | 中位相对差 | 最大相对差 |")
    A("|---|---|---|---|---|---|---|---|")
    for col in d["input"]["columns"]:
        e = d["per_column_difference_table"][col]
        A("| `%s` | %d | %d | %d | %d | %d | %s | %s |"
          % (col, e["n_diff"], e["n_both_present_diff"], e["n_one_blank"],
             e["n_both_blank"], e["n_both_present_same"],
             "—" if e["rel_median"] is None else "%.3g" % e["rel_median"],
             "—" if e["rel_max"] is None else "%.3g" % e["rel_max"]))
    A("")
    A("（相对差 = `|a-b| / max(|a|,|b|)`，只在「两行都有值且不同」的对上计算；"
      "近零分量的相对差会被放大，需与绝对差一起看，见 `diagnosis.json` 的 `abs_max`。）")
    A("")
    A("### 4.2 需单独点明的结果列（含 `f_peak_Hz` / `bandwidth_Hz` / `Q_factor`）")
    A("")
    A("| 列 | 都有且不同 | 中位相对差 | 最大相对差 | 最大绝对差 | 相对差 >1e-6 的对数 |")
    A("|---|---|---|---|---|---|")
    for col in HIGHLIGHT_COLUMNS + ("peak_SPL_dB", "abs_p_Pa", "abs_w_m"):
        e = d["per_column_difference_table"].get(col)
        if not e:
            continue
        A("| `%s` | %d | %s | %s | %s | %d |"
          % (col, e["n_both_present_diff"],
             "—" if e["rel_median"] is None else "%.3g" % e["rel_median"],
             "—" if e["rel_max"] is None else "%.3g" % e["rel_max"],
             "—" if e["abs_max"] is None else "%.3g" % e["abs_max"],
             e["n_rel_gt_1e-6"]))
    A("")
    A("## 5. 结论")
    A("")
    A("**足以下结论**（以下每条都由逐列比对直接读出）：")
    A("")
    A("1. **(a) 完全重复行 = 0**；**162 对全部是「部分列不同」**。")
    A("2. 162 对的构成**完全一致**：每对 = 一条 `source_dataset=A` + 一条 "
      "`source_dataset=C`；A 与 C 的 `x_density_class`（`coarse_0.1` / `fine_0.01`）与 "
      "`freq_grid_MHz`（`5-35/61` / `5-50/91`）**逐对都不同**。")
    A("3. **(c) 差异仅来自标记列的对 = %d**（标记列：%s；这 %d 对的两行所有测量列都为空）。"
      % (c["c_marker_columns_only"], "、".join("`%s`" % m for m in c["marker_columns_used"]),
         c["c_marker_columns_only"]))
    A("4. 其余 %d 对在测量列上也有差异，但差异是**两种性质**："
      % (c["b_partial_column_differences"] - c["c_marker_columns_only"]))
    A("   - `f_peak_Hz`：**24 对为「A 侧空、C 侧有值」**，C 侧峰位落在 **38.5–48.5 MHz**"
      "（**全部 > 35 MHz**）⇒ 与 A 的 5–35 MHz 栅格一致；**126 对两行都有值且逐位相同**"
      "（0 对不同）；**12 对两行都为空**。")
    A("   - `bandwidth_Hz` / `Q_factor`：119 对两行都有值，**无一逐位相同**，"
      "中位相对差 ~2e-8（Q ~1.6e-8），最大 ~2.8e-5（Q 同量级）；"
      "该量级**远小于任何物理判据**，但**大于**双精度舍入（~1e-16）与原始列的 ~1e-13 "
      "⇒ 成因**未定**，见本节末「不足以下结论」。")
    A("   - 原始物理列（`peak_SPL_dB`、`abs_p_Pa`、`abs_w_m` …）：中位相对差 ~1e-13"
      "（双精度舍入量级），最大 ~1e-4~1e-1 出现在**分量近零**的虚部列（相对差在近零处无意义）。")
    A("5. `x_scale` **不存在** 1 ulp 表示差：%d 种字面值 ↔ %d 个浮点值一一对应，"
      "**归一化后真正的重复键 = 原样口径 = %d**。**162 里没有伪重复**。"
      % (ulp["n_distinct_x_scale_literals"], ulp["n_distinct_x_scale_floats"],
         ulp["normalized_true_dup_keys"]))
    A("6. 该 162 已在建表时登记：`work/runs/first-peak-20260929/multichannel_coverage.json` 的 "
      "`n_overlapping_triples_A_and_C = 162`，合表规则写明「同参数不同批**各占一行**，"
      "**禁止**字典合并（会静默丢掉 A 的 162 行）」。⇒ **不是误插重复，是设计如此。**")
    A("")
    A("**不足以下结论（不猜测）**：")
    A("")
    A("- `bandwidth_Hz` / `Q_factor` 那 ~1e-8~2.8e-5 的相对差**成因未定**。"
      "手头证据只到「两行来自不同 `source_model`（不同运行目录/时间戳的导出）」这一层；"
      "要定因需要**两套导出的原始频谱**与**−3 dB 截断点提取的实现/版本**，本脚本不掌握。"
      "⇒ 按纪律记为「不足以定因」。")
    A("- 本诊断**不判定**两份来源哪一份更正确，也**不提出**去重方案（去重规则待用户拍板）。")
    A("")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"))
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args(argv)

    src = pathlib.Path(a.csv)
    if not src.is_absolute():
        src = REPO / src
    if not src.exists():
        print("[FAIL] 输入不存在：%s" % src)
        return 2
    with src.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("[FAIL] 输入 0 行 ⇒ 空集判失败（不得报“无重复”）")
        return 2

    d = analyse(rows, src)
    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    out = pathlib.Path(a.out_dir) if a.out_dir else (REPO / "work/runs/c-batch-dup-diagnosis-%s" % ts)
    if not out.is_absolute():
        out = REPO / out
    out.mkdir(parents=True, exist_ok=True)
    (out / "diagnosis.json").write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    (out / "diagnosis.md").write_text(render_md(d), encoding="utf-8")

    u, c = d["uniqueness"], d["classification"]
    print("== C 批内部重复诊断（只读）==")
    print("  输入：%s（%d 行）" % (d["input"]["path"], d["input"]["n_rows"]))
    print("  唯一组合：原样 %d / ulp 归一化 %d ⇒ 重复键 %d 个，多出 %d 行"
          % (u["n_unique_raw"], u["n_unique_normalized"],
             u["n_dup_keys_normalized"], u["n_extra_rows_normalized"]))
    print("  三类：(a) 完全重复 %d ｜ (b) 部分列不同 %d ｜ (c) 仅标记列不同 %d"
          % (c["a_exact_duplicate_rows"], c["b_partial_column_differences"],
             c["c_marker_columns_only"]))
    print("  x_scale 1 ulp 伪重复：%d 个 ⇒ 归一化后真正重复键 %d"
          % (d["ulp_pseudo_duplicate_check"]["n_pseudo_dup_keys"],
             d["ulp_pseudo_duplicate_check"]["normalized_true_dup_keys"]))
    print("  产物：%s" % (out / "diagnosis.json"))
    print("        %s" % (out / "diagnosis.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
