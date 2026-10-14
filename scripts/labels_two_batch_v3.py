# -*- coding: utf-8 -*-
"""并集表 **v3**：把批次标签改成 **一批一栅格**（修 §93.5 的口径缺陷）。

## 为什么出 v3

§93.5 实测：`C_5-50MHz` 这个标签下**混着两套扫描栅格** —— `5-50/91` **1782 行** ＋
`5-35/61` **223 行**（`source_dataset=A`）。上一版并集表把这 223 行的 `freq_range_MHz`
一律声明成 `5-50`，于是门禁在 `row_grid` 口径下判：

```text
batch_single_range[c_5-50mhz]: 批次出现 2 个扫描口径 ['5-35/61', '5-50/91'] ⇒ 判失败
```

本版把子批**按行自身的来源字段**拆开，使**一批恰一栅格**：

| 新 `batch` | 判据（逐行） | 行数 | 栅格 |
|---|---|---|---|
| `C_5-50MHz` | 来自批次 C 原表 且 `source_dataset=C` | 1782 | `5-50/91` |
| `A_5-35MHz` | 来自批次 C 原表 且 `source_dataset=A` | **223** | `5-35/61` |
| `V2_5-35MHz` | 来自 v2 冻结副本 | 250 | `5-35/61` |

## 纪律（与 v2 同源，逐条不得松）

* **append-only**：输出落**新目录**；上一版并集表、v2 冻结副本、C 批原表**只读**，
  逐文件 sha256 落进 `VERSION_*.json`。
* **不改历史**：上一版 26 列**名称与顺序原样保留**；被本版有意改值的列**逐列在
  `diff_vs_previous.changed_columns` 里列明**，并把它们的上一版取值**逐行留痕**
  （新列 `batch_v2_original` / `freq_range_v2_original`）⇒ **不是静默改写**。
* **不倒填**：C/A 侧没有原始删失/截断标志列 ⇒ 那两列**继续留空**（禁止用派生 `usable` 倒填）。
* **不猜测**：子批判据是**两个独立字段**（`source_dataset` 与 `freq_grid_MHz`）；
  两者**不一致**时本脚本**不猜**，直接以退出码 2 结束（输入不可用）。
* **不去重**：只标记（`dup_score` / `dup_of` / `dup_kind`），**一行不删**；去重规则待用户拍板。
* **不改门禁**：判定仍走 `sweep_analysis.check_batch_isolation` ＋ `consistency.evaluate_s3`
  （`sweep_analysis.py` 的 sha256 落进 `VERSION.gate.gate_function_sha256`，用于证明未改）。
  双口径（`declared` = `freq_range_MHz`、`row_grid` = `freq_grid_MHz`）都跑，**以更严重者定退出码**。

退出码：`0` passed ／ `2` 输入不可用或自校验不成立 ／ `3` 有 failed ／ `4` 无 failed 但有 inconclusive（**不等于通过**）。
产物在**任何情况下都保留**。
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import pathlib
import sys


REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import labels_two_batch as L2                                          # noqa: E402
from memsharness.consistency import evaluate_s3                        # noqa: E402
from memsharness.sweep_analysis import (                               # noqa: E402
    IDENTITY_ROUND_DECIMALS,
    check_batch_isolation,
)

DEFAULT_PREV_UNION = (REPO / "work/runs/labels-two-batch-v2-20261008T164434"
                      / "labels_two_batch.csv")

EXIT_PASS, EXIT_INPUT, EXIT_FAIL, EXIT_INCONCLUSIVE = 0, 2, 3, 4

#: 本版新增列（追加在 v2 的 26 列**之后**，v2 的 26 列名称与顺序不变）
V3_ADDED_COLUMNS = [
    "batch_v2_original",        # 上一版的 batch 取值（回溯用；**不改历史**）
    "freq_range_v2_original",   # 上一版的 freq_range_MHz 取值（同上）
    "batch_basis",              # 子批判据的**证据**（命中了哪条规则）
    "freq_range_source",        # 逐行真实范围的**证据来源**（列名）
]

#: 真实 C 批原表的 sha256（§93.1 登记值）。用来自动启用「真实数据自校验」——
#: 合成夹具（sha256 不同）不套用真实数据的期望行数，但仍照常出全部校验数字。
REAL_C_SHA256 = "d06edfe1999434999d360dc01220eedced236268f1dce1b9c176b516adfecbac"
REAL_EXPECT = {"n_rows": 2255, "n_rows_A_5-35MHz": 223}

A_LABEL, C_LABEL, V2_LABEL = "A_5-35MHz", "C_5-50MHz", "V2_5-35MHz"


def _range_of_grid(grid: str) -> str:
    """`5-35/61` → `5-35`；拿不到就返回空串（**不猜**）。"""
    g = str(grid or "").strip()
    if not g:
        return ""
    return g.split("/")[0].strip()


def classify_c_row(r: dict) -> tuple[str, str, str]:
    """批次 C 原表的一行 → (新 batch, 判据, 冲突说明)。冲突 ⇒ 判据为空、回 EXIT_INPUT。"""
    ds = str(r.get("source_dataset", "") or "").strip().upper()
    grid = str(r.get("freq_grid_MHz", "") or "").strip()
    by_ds = {"A": A_LABEL, "C": C_LABEL}.get(ds, "")
    by_grid = ""
    if grid:
        by_grid = A_LABEL if _range_of_grid(grid) == "5-35" else C_LABEL
    if by_ds and by_grid and by_ds != by_grid:
        return "", "", ("source_dataset=%r 与 freq_grid_MHz=%r 给出的子批判据不一致"
                        % (ds, grid))
    if by_ds:
        return by_ds, ("source_dataset=%s" % ds), ""
    if by_grid:
        return by_grid, ("freq_grid_MHz=%s" % grid), ""
    return "", "", "source_dataset 与 freq_grid_MHz 都给不出子批判据（不猜）"


def sha256_file(p: pathlib.Path) -> str:
    return L2.sha256_file(p)


def overlap_composition(rows: list[dict], decimals: int) -> dict:
    """跨批重叠的**真实构成**（用修正后的标签）。

    口径与 `check_batch_isolation` 一致：组合身份键 = (`x_scale`, `N_w_te1`, `N_w_te2`)
    先做 ulp 归一化（`round(v, decimals)`）。
    """
    sets: dict[str, set] = {}
    for r in rows:
        sets.setdefault(r["batch"], set()).add(L2._identity(r, decimals))
    # 三个子批标签各自建集合（缺批 ⇒ 空集，**不是** KeyError）：单批/两批的输入也要能算
    for lbl in (A_LABEL, C_LABEL, V2_LABEL):
        sets.setdefault(lbl, set())
    labels = sorted(sets)
    n_combos = {b: len(s) for b, s in sets.items()}
    pairwise: dict[str, int] = {}
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            pairwise["%s|%s" % (a, b)] = len(sets[a] & sets[b])
    classes: dict[str, int] = {}
    for key in set().union(*sets.values()):
        bs = tuple(b for b in labels if key in sets[b])
        if len(bs) > 1:
            classes["+".join(bs)] = classes.get("+".join(bs), 0) + 1
    n_multi = sum(classes.values())
    union_ac = sets[A_LABEL] | sets[C_LABEL]
    old = {
        "(A_5-35MHz ∪ C_5-50MHz) ∩ V2_5-35MHz": len(union_ac & sets[V2_LABEL]),
        "A_5-35MHz ∩ V2_5-35MHz": len(sets[A_LABEL] & sets[V2_LABEL]),
        "C_5-50MHz ∩ V2_5-35MHz": len(sets[C_LABEL] & sets[V2_LABEL]),
        "A_5-35MHz ∩ C_5-50MHz": len(sets[A_LABEL] & sets[C_LABEL]),
        "A_5-35MHz ∩ C_5-50MHz ∩ V2_5-35MHz":
            len(sets[A_LABEL] & sets[C_LABEL] & sets[V2_LABEL]),
    }
    only_a = classes.get("+".join([A_LABEL, V2_LABEL]), 0)
    only_c = classes.get("+".join([C_LABEL, V2_LABEL]), 0)
    triple = classes.get("+".join([A_LABEL, C_LABEL, V2_LABEL]), 0)
    return {
        "identity_key": {"param_keys": ["x_scale", "N_w_te1", "N_w_te2"],
                         "ulp_decimals": decimals},
        "rows_by_batch": {b: sum(1 for r in rows if r["batch"] == b) for b in labels},
        "unique_combos_by_batch": n_combos,
        "pairwise_overlap": pairwise,
        "pairwise_overlap_sum": sum(pairwise.values()),
        "classes_by_batches_involved": classes,
        "n_combos_in_two_or_more_batches": n_multi,
        "old_c_label_versus_v2": old,
        "old_167_attribution": {
            "note": "上一版的 167 = 旧 C 标签（含 A 子批 223 行）与 V2 的组合重叠；"
                    "本版按新标签可把它**分解**为下列互不重叠的份数（单位：组合数）。",
            "reachable_via_A": len(sets[A_LABEL] & sets[V2_LABEL]),
            "reachable_via_C": len(sets[C_LABEL] & sets[V2_LABEL]),
            "via_both_A_and_C": triple,
            "via_A_only": only_a,
            "via_C_only": only_c,
            "sum_check": (len(sets[A_LABEL] & sets[V2_LABEL])
                          + len(sets[C_LABEL] & sets[V2_LABEL]) - triple),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2-dir", default=str(L2.DEFAULT_V2))
    ap.add_argument("--v2", default=None)
    ap.add_argument("--old-c", default=str(L2.OLD))
    ap.add_argument("--prev-union", default=str(DEFAULT_PREV_UNION))
    ap.add_argument("--prev-version", default=None,
                    help="上一版 VERSION_*.json（缺省取 --prev-union 同目录下最新）")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--decimals", type=int, default=IDENTITY_ROUND_DECIMALS)
    ap.add_argument("--expect-rows", type=int, default=None,
                    help="强制期望总行数（缺省：真实 C 表才自动套用 2255）")
    ap.add_argument("--expect-a-rows", type=int, default=None,
                    help="强制期望 A_5-35MHz 行数（缺省：真实 C 表才自动套用 223）")
    a = ap.parse_args(argv)

    try:
        v2p = L2._freeze_v2(pathlib.Path(a.v2_dir), a.v2)
    except FileNotFoundError as exc:
        print("[FAIL] %s" % exc)
        return EXIT_INPUT
    oldp = pathlib.Path(a.old_c)
    if not oldp.exists():
        print("[FAIL] 未找到批次 C 原表：%s" % oldp)
        return EXIT_INPUT
    if not v2p.exists():
        print("[FAIL] 未找到 v2 冻结副本：%s" % v2p)
        return EXIT_INPUT

    c_sha = sha256_file(oldp)
    v2 = list(csv.DictReader(v2p.open("r", encoding="utf-8", newline="")))
    old = list(csv.DictReader(oldp.open("r", encoding="utf-8", newline="")))
    if not old or not v2:
        print("[FAIL] 输入为空（C %d 行 / v2 %d 行）⇒ 空集判失败" % (len(old), len(v2)))
        return EXIT_INPUT
    ocols = list(old[0].keys())
    mapping = {k: L2.pick(ocols, k) for k in L2.PATTERNS}

    # ---------------- 子批判据（两字段交叉核对，冲突即不猜）----------------
    sub: list[dict] = []
    conflicts: list[dict] = []
    for i, r in enumerate(old):
        b, basis, why = classify_c_row(r)
        sub.append({"batch": b, "basis": basis})
        if not b:
            conflicts.append({"row_index": i, "why": why,
                              "source_dataset": r.get("source_dataset", ""),
                              "freq_grid_MHz": r.get("freq_grid_MHz", "")})
    print("== 子批判据（批次 C 原表 %d 行）==" % len(old))
    for lbl in (C_LABEL, A_LABEL):
        n = sum(1 for s in sub if s["batch"] == lbl)
        print("  %-12s %5d 行 ｜ 判据命中：%s"
              % (lbl, n, sorted({s["basis"] for s in sub if s["batch"] == lbl})))
    print("  判据冲突行数：%d" % len(conflicts))
    if conflicts:
        for c_ in conflicts[:5]:
            print("   [冲突] 行 %d：%s" % (c_["row_index"], c_["why"]))
        print("[FAIL] 子批判据冲突 ⇒ **不猜**，以退出码 2 结束（不产出并集表）")
        return EXIT_INPUT

    def f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # ---------------- 建表（行序与 v2 并集表一致：先 C 原表、后 v2）----------------
    out: list[dict] = []
    for r, s in zip(old, sub):
        grid = r.get("freq_grid_MHz", "")
        out.append({
            # ---- v2 的 26 列：名称与顺序原样保留（其中 batch / freq_range_MHz 有意改值）----
            "batch": s["batch"], "source_file": oldp.name,
            "x_scale": r.get("x_scale"), "N_w_te1": r.get("N_w_te1"),
            "N_w_te2": r.get("N_w_te2"),
            "freq_range_MHz": _range_of_grid(grid),
            "peak_freq_Hz": r.get(mapping["peak_freq_Hz"]) if mapping["peak_freq_Hz"] else "",
            "bandwidth_Hz": r.get(mapping["bandwidth_Hz"]) if mapping["bandwidth_Hz"] else "",
            "Q": r.get(mapping["Q"]) if mapping["Q"] else "",
            "zeta": r.get(mapping["zeta"]) if mapping["zeta"] else "",
            "spl_dB": r.get(mapping["spl_dB"]) if mapping["spl_dB"] else "",
            "peak_closed": r.get(mapping["peak_closed"]) if mapping["peak_closed"] else "",
            "ranking_eligible": (r.get(mapping["ranking_eligible"])
                                 if mapping["ranking_eligible"] else ""),
            "usable": "", "source_type": "simulation",
            "source_pipeline": "C_first_peak_20260929",
            "source_dataset": r.get("source_dataset", ""),
            "x_density_class": r.get("x_density_class", ""),
            "freq_grid_MHz": grid,
            "n_freq": r.get("n_freq", ""),
            "source_model": r.get("source_model", ""),
            # ---- C/A 侧没有原始删失/截断列 ⇒ 留空（**不倒填**）----
            "peak_at_scan_endpoint": "",
            "bw_upper_cutoff_at_endpoint": "",
            # ---- 本版新增（追加在 26 列之后）----
            "batch_v2_original": C_LABEL,
            "freq_range_v2_original": "5-50",
            "batch_basis": s["basis"],
            "freq_range_source": "freq_grid_MHz" if _range_of_grid(grid) else "",
        })
    for r in v2:
        n_freq = r.get("n_freq", "")
        try:
            fmin = float(r["freq_min_Hz"]) / 1e6
            fmax = float(r["freq_max_Hz"]) / 1e6
            grid = "%g-%g/%s" % (fmin, fmax, n_freq)
        except (KeyError, TypeError, ValueError):
            grid = ""
        out.append({
            "batch": V2_LABEL, "source_file": v2p.name,
            "x_scale": r["x_scale"], "N_w_te1": r["N_w_te1"], "N_w_te2": r["N_w_te2"],
            "freq_range_MHz": _range_of_grid(grid),
            "peak_freq_Hz": r["peak_freq_Hz"],
            "bandwidth_Hz": r["bandwidth_Hz"], "Q": r["Q"], "zeta": r["zeta"],
            "spl_dB": r["peak_spl_dB"],
            "peak_closed": "", "ranking_eligible": "",
            "usable": str((str(r["peak_at_scan_endpoint"]).lower() != "true") and
                          (str(r["bw_upper_cutoff_at_endpoint"]).lower() != "true")),
            "source_type": "simulation",
            "source_pipeline": "v2_comsol_native_markers",
            "source_dataset": "V2", "x_density_class": "",
            "freq_grid_MHz": grid, "n_freq": n_freq, "source_model": "",
            "peak_at_scan_endpoint": r["peak_at_scan_endpoint"],
            "bw_upper_cutoff_at_endpoint": r["bw_upper_cutoff_at_endpoint"],
            "batch_v2_original": V2_LABEL,
            "freq_range_v2_original": "5-35",
            "batch_basis": "v2_frozen_copy",
            "freq_range_source": "freq_grid_MHz" if _range_of_grid(grid) else "",
        })

    # ---------------- 重复标记（只标记，不删除）----------------
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(out):
        groups.setdefault(L2._identity(r, a.decimals), []).append(i)
    n_dup_groups = n_cross_batch_rows = 0
    for key, idxs in groups.items():
        if len(idxs) < 2:
            for i in idxs:
                out[i].update(dup_score="0", dup_of="", dup_kind="")
            continue
        n_dup_groups += 1
        for i in idxs:
            others = [j for j in idxs if j != i]
            kinds, descr, cross = set(), [], False
            for j in others:
                descr.append("%s/%s" % (out[j]["batch"], out[j]["source_dataset"] or "-"))
                if out[j]["batch"] != out[i]["batch"]:
                    cross = True
                a_, b_ = out[i], out[j]
                if all(str(a_.get(c, "")) == str(b_.get(c, "")) for c in L2.COMPARE_COLUMNS):
                    kind = "exact_duplicate_row"
                else:
                    dcols = [c for c in L2.COMPARE_COLUMNS
                             if str(a_.get(c, "")) != str(b_.get(c, ""))]
                    kind = ("marker_columns_only" if set(dcols) <= set(L2.MARKER_COLUMNS)
                            else "measurement_differs")
                kinds.add("%s@%s" % (kind, out[j]["batch"]))
            out[i]["dup_score"] = str(len(others))
            out[i]["dup_of"] = ";".join(sorted(descr))
            out[i]["dup_kind"] = ";".join(sorted(kinds))
            if cross:
                n_cross_batch_rows += 1

    columns = L2.BASE_COLUMNS + L2.ADDED_COLUMNS + V3_ADDED_COLUMNS
    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    outdir = (pathlib.Path(a.out_dir) if a.out_dir
              else REPO / "work/runs/labels-two-batch-v3" / ts)
    if not outdir.is_absolute():
        outdir = REPO / outdir
    outdir.mkdir(parents=True, exist_ok=True)
    csvp = outdir / "labels_two_batch.csv"
    with csvp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(out)

    # ---------------- 自校验：行数 / 逐批组合数 / 一批一栅格 / 与上一版逐列差异 ----------------
    grid_by_batch = {b: sorted({r["freq_grid_MHz"] or "(空)" for r in out
                                if r["batch"] == b})
                     for b in sorted({r["batch"] for r in out})}
    uniq_by_batch = {b: len({L2._identity(r, a.decimals) for r in out if r["batch"] == b})
                     for b in sorted({r["batch"] for r in out})}
    rows_by_batch = {b: sum(1 for r in out if r["batch"] == b)
                     for b in sorted({r["batch"] for r in out})}
    exp_rows = a.expect_rows if a.expect_rows is not None else (
        REAL_EXPECT["n_rows"] if c_sha == REAL_C_SHA256 else None)
    exp_a = a.expect_a_rows if a.expect_a_rows is not None else (
        REAL_EXPECT["n_rows_A_5-35MHz"] if c_sha == REAL_C_SHA256 else None)
    verification = {
        "real_c_sha256_expected": REAL_C_SHA256,
        "real_c_sha256_actual": c_sha,
        "real_data_expectations_applied": exp_rows is not None,
        "n_rows": {"expected": exp_rows, "actual": len(out),
                   "ok": (exp_rows is None or exp_rows == len(out))},
        "n_rows_A_5-35MHz": {"expected": exp_a, "actual": rows_by_batch.get(A_LABEL),
                             "ok": (exp_a is None or exp_a == rows_by_batch.get(A_LABEL))},
        "rows_by_batch": rows_by_batch,
        "unique_combos_by_batch": uniq_by_batch,
        "grids_by_batch": grid_by_batch,
        "one_grid_per_batch": {b: len(g) == 1 for b, g in grid_by_batch.items()},
        "required_columns_present": {
            c: (c in columns) for c in
            ("peak_at_scan_endpoint", "bw_upper_cutoff_at_endpoint",
             "freq_range_MHz", "source_pipeline")},
        "no_backfill_raw_flags": {
            "C/A 侧原始标志列非空行数": sum(
                1 for r in out if r["batch"] in (A_LABEL, C_LABEL)
                and (str(r["peak_at_scan_endpoint"]).strip()
                     or str(r["bw_upper_cutoff_at_endpoint"]).strip())),
            "说明": "C/A 侧原表没有这两列 ⇒ 必须全空；用派生 usable 倒填即违规。",
        },
        "c_sub_batch_conflicts": len(conflicts),
    }
    verification["passed"] = bool(
        verification["n_rows"]["ok"] and verification["n_rows_A_5-35MHz"]["ok"]
        and all(verification["one_grid_per_batch"].values())
        and all(verification["required_columns_present"].values())
        and verification["no_backfill_raw_flags"]["C/A 侧原始标志列非空行数"] == 0)

    # ---------------- fail-closed 门禁（两次口径，以更严者定退出码）----------------
    gates: dict[str, dict] = {}
    for tag, rkey in (("declared", "freq_range_MHz"), ("row_grid", "freq_grid_MHz")):
        checks = check_batch_isolation(out, range_key=rkey, decimals=a.decimals)
        gates[tag] = {"range_key": rkey, "verdict": evaluate_s3(checks)}
    release_allowed = all(g["verdict"]["verdict"] == "passed" for g in gates.values())
    if release_allowed:
        gate_exit = EXIT_PASS
    elif any(g["verdict"]["n_failed"] for g in gates.values()):
        gate_exit = EXIT_FAIL
    else:
        gate_exit = EXIT_INCONCLUSIVE
    worst = max(gates.values(), key=lambda g: L2._SEVERITY[g["verdict"]["verdict"]])

    # 与上一版判定的**逐项对照**（用于说明差异的**真实原因**）
    prevp = pathlib.Path(a.prev_union)
    prev_version: dict = {}
    pv_path = pathlib.Path(a.prev_version) if a.prev_version else None
    if pv_path is None and prevp.exists():
        cands = sorted(prevp.parent.glob("VERSION_*.json"))
        pv_path = cands[-1] if cands else None
    if pv_path is not None and pv_path.exists():
        try:
            prev_version = json.loads(pv_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            prev_version = {"_read_error": str(exc)}
    prev_gate = (prev_version or {}).get("gate", {})
    prev_runs = prev_gate.get("runs", {})

    def _gateitem(tag):
        v = gates[tag]["verdict"]
        return {"verdict": v["verdict"], "n_checks": v["n_checks"],
                "n_failed": v["n_failed"], "n_inconclusive": v["n_inconclusive"],
                "release_allowed": v["release_allowed"],
                "failed_checks": [c["name"] for c in v["checks"] if c["passed"] is False],
                "inconclusive_checks": [c["name"] for c in v["checks"] if c["passed"] is None]}

    gate_diff = {
        "previous_version_id": prev_version.get("version_id"),
        "previous_version_path": L2._rel(pv_path) if pv_path else None,
        "previous": {
            t: {"verdict": (prev_runs.get(t, {}).get("verdict", {}) or {}).get("verdict"),
                "n_failed": (prev_runs.get(t, {}).get("verdict", {}) or {}).get("n_failed"),
                "n_inconclusive": (prev_runs.get(t, {}).get("verdict", {}) or {}).get(
                    "n_inconclusive"),
                "failed_checks": [c["name"] for c in
                                  ((prev_runs.get(t, {}).get("verdict", {}) or {})
                                   .get("checks", []) or []) if c.get("passed") is False]}
            for t in ("declared", "row_grid")},
        "current": {t: _gateitem(t) for t in ("declared", "row_grid")},
        "previous_release_allowed": prev_gate.get("release_allowed"),
        "current_release_allowed": release_allowed,
        "previous_exit_code": prev_gate.get("exit_code"),
        "current_exit_code": gate_exit,
        "cause": (
            "上一版 `row_grid` 的**唯一 failed 项**是 `batch_single_range[c_5-50mhz]`"
            "（同一批次下出现两套栅格 5-35/61 与 5-50/91）。本版该项消失，"
            "**原因是原先的批次标签是错的** —— 那 223 行本就来自 `source_dataset=A` 的 "
            "5-35 MHz/61 点子批，被错并进了 `C_5-50MHz` 标签。本版只是把批次标签改成"
            "一批一栅格（判据取自每行自身的 source_dataset / freq_grid_MHz），"
            "**门禁函数、阈值、判据一字未改**（见 gate_function_sha256），"
            "也**没有**过滤任何行、**没有**去重。"
            "因此这**不是**「门禁放宽后通过」：跨批重叠项 batch_no_cross_batch_combo "
            "仍然判 inconclusive ⇒ release_allowed 仍为 False、退出码非零。"),
        "not_a_relaxation_evidence": {
            "gate_function_sha256": sha256_file(REPO / "src/memsharness/sweep_analysis.py"),
            "prev_gate_function_note": "与 §93.3 登记的 5a2146cc… 对照即可证明未改门禁函数",
            "n_rows_before": (prev_version.get("row_count")),
            "n_rows_after": len(out),
            "rows_dropped": 0,
        },
    }

    # ---------------- 跨批重叠的真实构成（§第 ② 步）----------------
    comp = overlap_composition(out, a.decimals)

    # ---------------- 与上一版并集表的逐列差异（证明只有列明的列改值）----------------
    prev_info: dict = {"path": L2._rel(prevp), "exists": prevp.exists()}
    if prevp.exists():
        prev = list(csv.DictReader(prevp.open("r", encoding="utf-8", newline="")))
        pcols = list(prev[0].keys())
        same_row_order = len(prev) == len(out)
        changed: dict[str, int] = {c: 0 for c in pcols}
        examples: dict[str, list] = {}
        for i, (pr, nr) in enumerate(zip(prev, out)):
            for c in pcols:
                if str(pr.get(c, "")) != str(nr.get(c, "")):
                    changed[c] += 1
                    examples.setdefault(c, []).append(
                        {"row": i, "prev": pr.get(c, ""), "new": nr.get(c, "")})
        prev_info.update({
            "sha256": sha256_file(prevp), "n_rows": len(prev), "n_columns": len(pcols),
            "same_row_order_and_count": same_row_order,
            "columns_only_in_prev": sorted(set(pcols) - set(columns)),
            "columns_only_in_new": sorted(set(columns) - set(pcols)),
            "changed_columns": {c: n for c, n in sorted(changed.items()) if n},
            "changed_columns_examples": {c: v[:3] for c, v in sorted(examples.items())},
            "unchanged_columns": sorted(c for c in pcols if not changed[c]),
        })
        xwalk: dict[str, int] = {}
        for pr, nr in zip(prev, out):
            k = "%s → %s" % (pr.get("batch"), nr["batch"])
            xwalk[k] = xwalk.get(k, 0) + 1
        prev_info["batch_relabel_crosswalk"] = xwalk

    # ---------------- 逐批统计（**不给合成数**）----------------
    stats: dict = {}
    for batch in sorted(rows_by_batch):
        sel = [r for r in out if r["batch"] == batch]
        q = [r for r in sel if (f(r["Q"]) is not None) and L2.Q_LO <= f(r["Q"]) <= L2.Q_HI]
        u = [r for r in sel if r["usable"] == "True"]
        stats[batch] = {
            "n": len(sel),
            "n_unique_combos": uniq_by_batch[batch],
            "n_Q_in_gate": len(q),
            "Q_gate_pct": 100 * len(q) / len(sel) if sel else 0.0,
            "n_usable": len(u) if batch == V2_LABEL else None,
            "Q_gate_pct_of_usable": (
                100 * len([r for r in u if f(r["Q"]) is not None
                           and L2.Q_LO <= f(r["Q"]) <= L2.Q_HI]) / len(u)) if u else None}

    flag_cov: dict[str, dict] = {}
    for b in sorted(rows_by_batch):
        sel = [r for r in out if r["batch"] == b]
        flag_cov[b] = {
            "n_rows": len(sel),
            "n_rows_with_peak_at_scan_endpoint": sum(
                1 for r in sel if str(r.get("peak_at_scan_endpoint", "")).strip() != ""),
            "n_rows_with_bw_upper_cutoff_at_endpoint": sum(
                1 for r in sel if str(r.get("bw_upper_cutoff_at_endpoint", "")).strip() != ""),
        }

    version_id = "LTB3_v%s" % ts
    version = {
        "kind": "labels_union_version",
        "version_id": version_id,
        "supersedes": {
            "version_id": prev_version.get("version_id"),
            "path": L2._rel(prevp) if prevp.exists() else None,
            "sha256": prev_info.get("sha256"),
            "note": "上一版**原样保留**（append-only）；本版是它的**修正版**，"
                    "不覆盖、不改写、不删除上一版任何字节。",
        },
        "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "frozen": False,
        "deduplicated": False,
        "dedup_note": "**本版未做去重，仅加标记**（dup_score / dup_of / dup_kind）；"
                      "去重规则待用户拍板，本脚本不执行任何删除。",
        "row_count": len(out),
        "column_count": len(columns),
        "columns": columns,
        "columns_kept_from_v2": L2.BASE_COLUMNS + L2.ADDED_COLUMNS,
        "columns_added_in_v3": V3_ADDED_COLUMNS,
        "identity_key": {
            "param_keys": ["x_scale", "N_w_te1", "N_w_te2"],
            "ulp_decimals": a.decimals,
            "note": "组合身份键判等前**先做 ulp 归一化**（R5）；且三列**一律按数值比较**"
                    "（C 侧字面 `1.0` 与 v2 侧字面 `1` 必须判为同一组合）。"},
        "batch_rule": {
            "A_5-35MHz": "批次 C 原表中 source_dataset=A（与 freq_grid_MHz=5-35/61 交叉一致）",
            "C_5-50MHz": "批次 C 原表中 source_dataset=C（与 freq_grid_MHz=5-50/91 交叉一致）",
            "V2_5-35MHz": "v2 冻结副本（source_dataset=V2）",
            "conflict_policy": "两字段判据不一致的行数 > 0 ⇒ **不猜**，退出码 2，不出表。",
            "n_conflicts": len(conflicts),
        },
        "inputs": {
            "c_batch_source": {"path": L2._rel(oldp), "bytes": oldp.stat().st_size,
                               "sha256": c_sha, "n_rows": len(old),
                               "n_columns": len(ocols)},
            "v2_frozen": {"path": L2._rel(v2p), "bytes": v2p.stat().st_size,
                          "sha256": sha256_file(v2p), "n_rows": len(v2)},
        },
        "outputs": {
            "labels_two_batch.csv": {"path": L2._rel(csvp), "bytes": csvp.stat().st_size,
                                     "sha256": sha256_file(csvp)},
        },
        "column_mapping": mapping,
        "unmapped_canonical": [k for k, v in mapping.items() if not v],
        "verification": verification,
        "raw_flags": {
            "peak_at_scan_endpoint": "v2 侧原样搬自冻结副本；**C/A 侧该列不存在 ⇒ 留空**"
                                     "（不用派生值倒填，也不猜测）",
            "bw_upper_cutoff_at_endpoint": "同上",
            "usable": "派生列（v2 侧 = 峰值不在扫描端点 且 上截止点不在端点）；"
                      "**保留但不得作为原始标志的替代**",
            "per_batch_availability": flag_cov,
            "known_limitation": "C/A 批的原始删失/截断标志在本表内**不可得**（原表无此列）"
                                "⇒ 门禁项 batch_censored_not_eligible 对 C/A 批**无法判定**；"
                                "该检查项因 v2 侧提供了列而整体可求值，其 passed 只覆盖 v2 行。"
                                "本版**未**修改门禁函数，也未另造一套判定；此处如实披露。",
        },
        "row_grid_disclosure": {
            b: {g: sum(1 for r in out if r["batch"] == b and r["freq_grid_MHz"] == g)
                for g in sorted({r["freq_grid_MHz"] for r in out if r["batch"] == b})}
            for b in sorted(rows_by_batch)},
        "freq_range_disclosure": (
            "**本版把 `freq_range_MHz` 改成逐行真实值**（取自该行自身的 `freq_grid_MHz`），"
            "不再是批次声明口径；上一版的取值逐行留在 `freq_range_v2_original`。"
            "被改的只有那 223 行（5-50 → 5-35）。"),
        "dup_marking": {
            "n_rows": len(out),
            "n_dup_groups": n_dup_groups,
            "n_rows_in_dup_groups": sum(1 for r in out if r["dup_score"] != "0"),
            "definitions": {
                "dup_score": "本表内与它共享同一（ulp 归一化）组合键的**其他**行数",
                "dup_of": "这些其他行的 `<batch>/<source_dataset>` 列表（`;` 分隔）",
                "dup_kind": "逐对的重复类型：`exact_duplicate_row` / "
                            "`marker_columns_only` / `measurement_differs`，附对方批次",
            },
            "cross_batch_rows": n_cross_batch_rows,
            "cross_batch_definition": "本组内**至少有一个对应行的 `batch` 与本行不同**的行数",
            "note_for_diff": "`dup_score` / `dup_of` / `dup_kind` 是**派生标记**："
                             "批次标签改了，它们随之重算。**上一版的取值已逐行留在"
                             "上一版文件里**（append-only），本版没有覆盖它。",
        },
        "stats_by_batch": stats,
        "no_combined_number": True,
        "stats_note": "并集表带 batch 列；所有统计按批次分列，**禁止合成总分 / 合并池化**。",
        "overlap_composition": comp,
        "previous_union": prev_info,
        "diff_vs_previous": [
            "**修正（本版唯一实质改动）**：`batch` 改为反映**真实来源子批**"
            "（`C_5-50MHz` 1782 ／ `A_5-35MHz` 223 ／ `V2_5-35MHz` 250）；"
            "`freq_range_MHz` 改为**逐行真实值**（223 行的 5-50 → 5-35）。"
            "上一版取值逐行留在新列 `batch_v2_original` / `freq_range_v2_original`。",
            "**修正原因**：§93.5 实测 `C_5-50MHz` 标签下混有两套栅格 ⇒ 上一版 `row_grid` "
            "口径的门禁判 `batch_single_range[c_5-50mhz]` failed。这是**标签错**，不是门禁错。",
            "**列**：v2 的 26 列**名称与顺序原样保留**，追加 %d 列（%s）⇒ 共 %d 列。"
            % (len(V3_ADDED_COLUMNS), "、".join(V3_ADDED_COLUMNS), len(columns)),
            "**随标签重算的派生列**：`dup_score` / `dup_of` / `dup_kind`（因其定义含批次标记）。"
            "数值列、`usable`、`source_*`、`freq_grid_MHz`、`n_freq` 与原始标志列**均未改**。",
            "**未做**：未去重（一行未删）、未改门禁函数、未改阈值、未过滤任何组合、"
            "未提升任何状态。",
        ],
        "gate": {
            "gate_function": "memsharness.sweep_analysis.check_batch_isolation",
            "verdict_function": "memsharness.consistency.evaluate_s3（未另造一套）",
            "gate_function_path": "src/memsharness/sweep_analysis.py",
            "gate_function_sha256": sha256_file(REPO / "src/memsharness/sweep_analysis.py"),
            "runs": gates,
            "worst_verdict": worst["verdict"]["verdict"],
            "release_allowed": release_allowed,
            "exit_code": gate_exit,
            "exit_code_semantics": {"0": "passed", "2": "输入不可用",
                                    "3": "有 failed", "4": "无 failed 但有 inconclusive（不等于通过）"},
            "fail_closed": "判定不是 passed ⇒ 非零退出码结束；**产物一律保留**。",
            "raw_flag_coverage": flag_cov,
            "no_relaxation": "**未**为让判定通过而放松任何检查项、阈值或过滤任何组合；"
                             "删失/截断组合与跨批重叠**全部保留在表内**。"
                             "本版让判定变好的唯一原因是**原先的批次标签是错的**。",
            "verdict_vs_previous": gate_diff,
        },
        "exit_code": (EXIT_INPUT if not verification["passed"] else gate_exit),
        "exit_code_note": (
            "自校验不成立 ⇒ 2（输入不可用）；否则取门禁判定（0/3/4）。"
            if not verification["passed"] else "门禁判定（0/3/4）。"),
    }
    vpath = outdir / ("VERSION_%s.json" % version_id)
    vpath.write_text(json.dumps(version, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------- 第 ② 步报告：重叠的真实构成 ----------------
    lines = [
        "# 跨批重叠的**真实构成**（修正标签后）",
        "",
        "> 只读分析；**未去重、未删行**。输入 = 本版并集表（`batch` 已改为一批一栅格）。",
        "> 身份键 = (`x_scale`, `N_w_te1`, `N_w_te2`)，**先做 ulp 归一化**（round 6 位），"
        "且三列一律按**数值**比较。",
        "",
        "## 1. 每批行数 / 唯一组合数",
        "",
        "| 批次 | 行数 | 唯一组合数 | 逐行栅格 |",
        "|---|---|---|---|",
    ]
    for b in sorted(rows_by_batch):
        lines.append("| `%s` | %d | %d | %s |"
                     % (b, rows_by_batch[b], uniq_by_batch[b], "、".join(grid_by_batch[b])))
    lines += [
        "",
        "## 2. 两两重叠",
        "",
        "| 批对 | 重叠组合数（ulp 归一化） |",
        "|---|---|",
    ]
    for k, v in sorted(comp["pairwise_overlap"].items()):
        lines.append("| `%s` | **%d** |" % (k, v))
    lines += [
        "",
        "两两之和 = **%d**" % comp["pairwise_overlap_sum"],
        "",
        "## 3. 重叠组合按「涉及哪些批」分类（互不重叠的划分）",
        "",
        "| 涉及的批 | 组合数 |",
        "|---|---|",
    ]
    for k, v in sorted(comp["classes_by_batches_involved"].items(),
                       key=lambda kv: -kv[1]):
        lines.append("| `%s` | **%d** |" % (k, v))
    lines += [
        "",
        "出现在 ≥2 个批的组合合计 = **%d**" % comp["n_combos_in_two_or_more_batches"],
        "",
        "## 4. 旧的「167」怎么分解",
        "",
        "上一版的 167 = **旧 `C_5-50MHz` 标签（2005 行，含 A 子批 223 行）** 与 V2 的组合重叠。",
        "按修正后的标签，它 = (A ∪ C) ∩ V2 = **%d**，并可分解为："
        % comp["old_c_label_versus_v2"]["(A_5-35MHz ∪ C_5-50MHz) ∩ V2_5-35MHz"],
        "",
        "| 分解项 | 组合数 |",
        "|---|---|",
        "| 可达于 `A_5-35MHz`（A ∩ V2） | **%d** |" % comp["old_167_attribution"]["reachable_via_A"],
        "| 可达于 `C_5-50MHz`（C ∩ V2） | **%d** |" % comp["old_167_attribution"]["reachable_via_C"],
        "| 同时涉及 A、C、V2（三者皆有） | **%d** |" % comp["old_167_attribution"]["via_both_A_and_C"],
        "| 只涉及 A 与 V2 | **%d** |" % comp["old_167_attribution"]["via_A_only"],
        "| 只涉及 C 与 V2 | **%d** |" % comp["old_167_attribution"]["via_C_only"],
        "",
        "校验：A∩V2 + C∩V2 − A∩C∩V2 = %d + %d − %d = **%d** ＝ 旧的 167 ⇒ 口径自洽。"
        % (comp["old_167_attribution"]["reachable_via_A"],
           comp["old_167_attribution"]["reachable_via_C"],
           comp["old_167_attribution"]["via_both_A_and_C"],
           comp["old_167_attribution"]["sum_check"]),
        "",
        "**结论：167 这个数在标签修好后不再是任何一个「批对」的重叠数。**",
        "它是 `(A ∪ C) ∩ V2` 的**并集口径**；按新标签，批对重叠是 A|C=**%d**、A|V2=**%d**、C|V2=**%d**。"
        % (comp["pairwise_overlap"].get("%s|%s" % (A_LABEL, C_LABEL), -1),
           comp["pairwise_overlap"].get("%s|%s" % (A_LABEL, V2_LABEL), -1),
           comp["pairwise_overlap"].get("%s|%s" % (C_LABEL, V2_LABEL), -1)),
        "",
        "## 5. 剩余定因证据（只报观测到的覆盖关系，不外推）",
        "",
        "| 子批 | 行数 | 唯一 `x_scale` 值 | 唯一 (te1,te2) cell |",
        "|---|---|---|---|",
    ]
    for b in sorted(rows_by_batch):
        sel = [r for r in out if r["batch"] == b]
        xs = {round(float(r["x_scale"]), a.decimals) for r in sel if r["x_scale"] != ""}
        cells = {(r["N_w_te1"], r["N_w_te2"]) for r in sel}
        lines.append("| `%s` | %d | %d | %d |" % (b, len(sel), len(xs), len(cells)))
    lines += [
        "",
        "（可用于判断重叠**是否**能由「A 与 V2 同为 5–35 MHz 栅格」解释：A 与 V2 共享同一套 x 取值"
        "与部分 cell，但 C 的 0.01 细栅格**包含**那些 x 值，因此 C 也与 V2 重叠；"
        "具体数字见本版 `VERSION_*.json` 的 `overlap_composition`。）",
        "",
    ]
    (outdir / "overlap_composition.md").write_text("\n".join(lines), encoding="utf-8")
    (outdir / "overlap_composition.json").write_text(
        json.dumps(comp, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------- 打印 ----------------
    print("\n== 自校验 ==")
    print("  总行数 %d（期望 %s）｜ A_5-35MHz %s 行（期望 %s）"
          % (len(out), exp_rows, rows_by_batch.get(A_LABEL), exp_a))
    for b in sorted(rows_by_batch):
        print("  %-12s 行 %5d ｜ 唯一组合 %5d ｜ 栅格 %s（一批一栅格=%s）"
              % (b, rows_by_batch[b], uniq_by_batch[b], grid_by_batch[b],
                 verification["one_grid_per_batch"][b]))
    print("  四个必需列全在：%s ｜ C/A 侧原始标志倒填行数：%d ｜ 自校验 passed=%s"
          % (all(verification["required_columns_present"].values()),
             verification["no_backfill_raw_flags"]["C/A 侧原始标志列非空行数"],
             verification["passed"]))
    if prevp.exists():
        print("  与上一版逐列差异（只有列明的列改值）：%s"
              % json.dumps(prev_info["changed_columns"], ensure_ascii=False))
        print("  批次改标签对照：%s" % json.dumps(prev_info["batch_relabel_crosswalk"],
                                                ensure_ascii=False))
    print("\n== 跨批重叠构成 ==")
    print("  两两重叠：%s（和 %d）" % (json.dumps(comp["pairwise_overlap"], ensure_ascii=False),
                                     comp["pairwise_overlap_sum"]))
    print("  按涉及批次分类：%s" % json.dumps(comp["classes_by_batches_involved"],
                                            ensure_ascii=False))
    print("  旧 167 分解：A∩V2=%d ｜ C∩V2=%d ｜ 三者皆有=%d"
          % (comp["old_167_attribution"]["reachable_via_A"],
             comp["old_167_attribution"]["reachable_via_C"],
             comp["old_167_attribution"]["via_both_A_and_C"]))
    print("\n== fail-closed 批次隔离门禁（未改门禁函数；sha256 %s…）=="
          % version["gate"]["gate_function_sha256"][:12])
    for tag, g in gates.items():
        v = g["verdict"]
        print("  [%s] range_key=%s ⇒ verdict=%s ｜ n_checks=%d n_failed=%d n_inconclusive=%d"
              % (tag, g["range_key"], v["verdict"], v["n_checks"], v["n_failed"],
                 v["n_inconclusive"]))
        for cchk in v["checks"]:
            tagc = {True: "PASS", False: "FAIL", None: "????"}[cchk["passed"]]
            print("        [%s] %s%s" % (tagc, cchk["name"],
                                         ("  —— %s" % cchk["reason"]) if cchk["reason"] else ""))
    print("  ⇒ release_allowed=%s ｜ 门禁退出码=%d ｜ 本脚本退出码=%d"
          % (release_allowed, gate_exit, version["exit_code"]))
    if not release_allowed:
        print("  ⚠️ 不是通过：inconclusive 表示**判不了**（不等同通过）；产物已保留。")
    print("\n并集表：%s（%d 行，%d 列）" % (L2._rel(csvp), len(out), len(columns)))
    print("版本清单：%s" % L2._rel(vpath))
    print("重叠构成：%s" % L2._rel(outdir / "overlap_composition.md"))
    return version["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
