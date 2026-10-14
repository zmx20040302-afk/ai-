# -*- coding: utf-8 -*-
"""把 v2（5–35 MHz，250 组合）作为**独立批次**接进标签层，与批次 C（2005 行）并列。

纪律：
* **只做并集，不做混算**：输出表带 `batch` 列；所有统计**按批次分别出**，不给合成数；
* **不做猜测式列映射**：批次 C 的列名先探测，命中就搬、命不中就**留空并报出来**（fail-closed），
  绝不用"看起来像"的列填；
* **不覆盖任何既有产物**：输出落到新目录，C 的原表与 v2 冻结副本只读；
* **保留原始标志列**（2026-10-08 第 3 项待办）：`peak_at_scan_endpoint` /
  `bw_upper_cutoff_at_endpoint` 由 v2 冻结副本原样搬入；**C 侧没有这两列 ⇒ 留空并写明**，
  **不得用派生值倒填**。派生列 `usable` 保留，但**不是**原始标志的替代。
* **不去重，只标记**：`dup_score` / `dup_of` / `dup_kind` 标注该组合在另一批（或同批另一来源）
  是否也出现、以及重复类型。**去重规则待用户拍板，本脚本不执行任何删除。**

## fail-closed 产出门禁（2026-10-08 第 5 项待办）

写表之后调用 `sweep_analysis.check_batch_isolation`（判定语义复用 `consistency.evaluate_s3`，
**不另造一套**），把判定写进 `VERSION_*.json` 的 `gate` 字段，并在**判定不是 passed 时以非零退出码结束**：

```text
0 = 全部检查通过；3 = 有 failed；4 = 无 failed 但有 inconclusive（**不等于通过**）；2 = 输入不可用
```

**产物在任何情况下都保留**（便于诊断），文件内 `release_allowed` 明确标注是否放行。

⚠️ 本批数据**必然**存在删失/截断组合与跨批重叠 ⇒ 门禁很可能判 `inconclusive`/`failed`。
**这是预期结果，不是 bug**：本脚本的任务是让判定被自动执行并落痕，**不是**把判定做好看。
**禁止**为通过而放松检查项或过滤掉不满足的组合。

门禁跑**两次**（同一套检查，只换"扫描口径列"）：

* `declared` —— `freq_range_MHz`（批次声明的口径，与上一版并集表一致）；
* `row_grid` —— `freq_grid_MHz`（**逐行**真实栅格）。

第二次是必要的：C 批 2005 行里 **223 行**的 `freq_grid_MHz` 实为 `5-35/61`（`source_dataset=A`），
而上一版把它们一律声明成 `5-50`。只跑第一次会让门禁在**事实上不成立的口径**上通过。
两次都跑、**以更严重者决定退出码**（只收紧、不放松），两套判定原样落进 `gate` 字段。
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.consistency import evaluate_s3                     # noqa: E402
from memsharness.sweep_analysis import (                            # noqa: E402
    IDENTITY_ROUND_DECIMALS,
    check_batch_isolation,
)

DEFAULT_V2 = REPO / "work/runs/remote-exported-v2-20260922"
OLD = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"
PREV_UNION = REPO / "work/runs/labels-two-batch/20261008T143641/labels_two_batch.csv"
Q_LO, Q_HI = 2.5, 3.5

EXIT_PASS, EXIT_INPUT, EXIT_FAIL, EXIT_INCONCLUSIVE = 0, 2, 3, 4
_SEVERITY = {"passed": 0, "inconclusive": 1, "failed": 2}

#: 上一版并集表的 15 列 —— **原样保留、顺序不变**（下游消费者不受影响），新列一律追加在后。
BASE_COLUMNS = ["batch", "source_file", "x_scale", "N_w_te1", "N_w_te2", "freq_range_MHz",
                "peak_freq_Hz", "bandwidth_Hz", "Q", "zeta", "spl_dB", "peak_closed",
                "ranking_eligible", "usable", "source_type"]

#: 本版新增列
ADDED_COLUMNS = ["source_pipeline", "source_dataset", "x_density_class", "freq_grid_MHz",
                 "n_freq", "source_model",
                 "peak_at_scan_endpoint", "bw_upper_cutoff_at_endpoint",
                 "dup_score", "dup_of", "dup_kind"]

#: 重复类型判定时视为「来源/批次标记」的列（其差异**不表示测量结果不同**）
MARKER_COLUMNS = ("batch", "source_file", "source_pipeline", "source_dataset",
                  "x_density_class", "freq_grid_MHz", "n_freq", "source_model",
                  "freq_range_MHz")

#: 「测量类」列（用于判定 measurement_differs）
MEASUREMENT_COLUMNS = ("peak_freq_Hz", "bandwidth_Hz", "Q", "zeta", "spl_dB")

#: 重复类型逐对比较时使用的列 = 除标记自身外的全部列（**必须排除 dup_***，否则自比较）
COMPARE_COLUMNS = tuple(c for c in BASE_COLUMNS + ADDED_COLUMNS
                        if c not in ("dup_score", "dup_of", "dup_kind"))

#: 规范列 → 候选列名（大小写不敏感，按顺序取第一个命中）
PATTERNS: dict[str, tuple[str, ...]] = {
    "peak_freq_Hz": ("peak_freq_hz", "f_peak_hz", "peak_frequency_hz", "first_peak_freq_hz",
                     "f0_hz", "peak_hz", "resonance_freq_hz"),
    "bandwidth_Hz": ("bandwidth_hz", "bw_hz", "bw_abs_hz", "absolute_bandwidth_hz"),
    "Q": ("q_factor", "q", "qfactor"),
    "zeta": ("zeta", "damping_ratio", "damping"),
    "peak_closed": ("peak_closed", "bandwidth_closed", "closed"),
    "ranking_eligible": ("ranking_eligible", "eligible"),
    "spl_dB": ("peak_spl_db", "spl_db", "peak_spl"),
}


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def pick(cols: list[str], key: str) -> str | None:
    low = {c.strip().lower(): c for c in cols}
    for cand in PATTERNS[key]:
        if cand in low:
            return low[cand]
    return None


def _rel(p: pathlib.Path) -> str:
    try:
        return str(pathlib.Path(p).relative_to(REPO))
    except ValueError:
        return str(p)


def _identity(row: dict, decimals: int = IDENTITY_ROUND_DECIMALS) -> tuple:
    """组合身份键：**先做 ulp 归一化**（R5；不做会把同一组合判成两个）。

    归一化口径与 `sweep_analysis.check_batch_isolation` 的 `_identity_key` 一致：
    **每个**浮点参数都 `round(v, decimals)`，保证本表的 `dup_*` 标记与门禁的重叠数同源。
    """
    out = []
    for k in ("x_scale", "N_w_te1", "N_w_te2"):
        try:
            out.append(round(float(str(row.get(k, "")).strip()), decimals))
        except (TypeError, ValueError):
            out.append(str(row.get(k, "")).strip())
    return tuple(out)


def _freeze_v2(v2dir: pathlib.Path, explicit: str | None) -> pathlib.Path:
    if explicit:
        return pathlib.Path(explicit)
    cands = sorted(pathlib.Path(v2dir).glob("v2_labels_frozen_*.csv"))
    if not cands:
        raise FileNotFoundError("未找到冻结的 v2 标签副本：%s/v2_labels_frozen_*.csv" % v2dir)
    return cands[-1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2-dir", default=str(DEFAULT_V2))
    ap.add_argument("--v2", default=None, help="显式指定 v2 冻结副本（缺省取 --v2-dir 下最新）")
    ap.add_argument("--old-c", default=str(OLD))
    ap.add_argument("--prev-union", default=str(PREV_UNION),
                    help="上一版并集表（用于差异说明；不存在则跳过）")
    ap.add_argument("--out-dir", default=None,
                    help="输出目录（缺省 work/runs/labels-two-batch/<ts>，保持既有语义）")
    ap.add_argument("--decimals", type=int, default=IDENTITY_ROUND_DECIMALS)
    a = ap.parse_args(argv)

    try:
        v2p = _freeze_v2(pathlib.Path(a.v2_dir), a.v2)
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

    v2 = list(csv.DictReader(v2p.open("r", encoding="utf-8", newline="")))
    old = list(csv.DictReader(oldp.open("r", encoding="utf-8", newline="")))
    if not old or not v2:
        print("[FAIL] 输入为空（C %d 行 / v2 %d 行）⇒ 空集判失败" % (len(old), len(v2)))
        return EXIT_INPUT
    ocols = list(old[0].keys())
    mapping = {k: pick(ocols, k) for k in PATTERNS}
    print("== 批次 C 列映射探测（%d 列）==" % len(ocols))
    for k, v in mapping.items():
        print("  %-18s → %s" % (k, v if v else "**未命中，留空**"))
    miss = {c for c in ocols if "freq" in c.lower() or "band" in c.lower() or "q" in c.lower()}
    print("  含 freq/band/q 的候选列：%s" % sorted(miss))

    def f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    out: list[dict] = []
    for r in old:
        out.append({
            # ---- 上一版的 15 列（原样）----
            "batch": "C_5-50MHz", "source_file": oldp.name,
            "x_scale": r.get("x_scale"), "N_w_te1": r.get("N_w_te1"),
            "N_w_te2": r.get("N_w_te2"), "freq_range_MHz": "5-50",
            "peak_freq_Hz": r.get(mapping["peak_freq_Hz"]) if mapping["peak_freq_Hz"] else "",
            "bandwidth_Hz": r.get(mapping["bandwidth_Hz"]) if mapping["bandwidth_Hz"] else "",
            "Q": r.get(mapping["Q"]) if mapping["Q"] else "",
            "zeta": r.get(mapping["zeta"]) if mapping["zeta"] else "",
            "spl_dB": r.get(mapping["spl_dB"]) if mapping["spl_dB"] else "",
            "peak_closed": r.get(mapping["peak_closed"]) if mapping["peak_closed"] else "",
            "ranking_eligible": (r.get(mapping["ranking_eligible"])
                                 if mapping["ranking_eligible"] else ""),
            "usable": "", "source_type": "simulation",
            # ---- 本版新增：原始来源/栅格列（原样搬，不改写）----
            "source_pipeline": "C_first_peak_20260929",
            "source_dataset": r.get("source_dataset", ""),
            "x_density_class": r.get("x_density_class", ""),
            "freq_grid_MHz": r.get("freq_grid_MHz", ""),
            "n_freq": r.get("n_freq", ""),
            "source_model": r.get("source_model", ""),
            # ---- C 侧**没有**原始删失/截断列 ⇒ 留空（**不倒填**）----
            "peak_at_scan_endpoint": "",
            "bw_upper_cutoff_at_endpoint": "",
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
            "batch": "V2_5-35MHz", "source_file": v2p.name,
            "x_scale": r["x_scale"], "N_w_te1": r["N_w_te1"], "N_w_te2": r["N_w_te2"],
            "freq_range_MHz": "5-35", "peak_freq_Hz": r["peak_freq_Hz"],
            "bandwidth_Hz": r["bandwidth_Hz"], "Q": r["Q"], "zeta": r["zeta"],
            "spl_dB": r["peak_spl_dB"],
            "peak_closed": "", "ranking_eligible": "",
            "usable": str((str(r["peak_at_scan_endpoint"]).lower() != "true") and
                          (str(r["bw_upper_cutoff_at_endpoint"]).lower() != "true")),
            "source_type": "simulation",
            "source_pipeline": "v2_comsol_native_markers",
            "source_dataset": "V2", "x_density_class": "",
            "freq_grid_MHz": grid, "n_freq": n_freq, "source_model": "",
            # ---- 原始标志：**原样**搬自冻结副本 ----
            "peak_at_scan_endpoint": r["peak_at_scan_endpoint"],
            "bw_upper_cutoff_at_endpoint": r["bw_upper_cutoff_at_endpoint"],
        })

    # ---------------- 重复标记（**只标记，不删除**）----------------
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(out):
        groups.setdefault(_identity(r, a.decimals), []).append(i)
    n_dup_groups = 0
    n_cross_batch_rows = 0
    for key, idxs in groups.items():
        if len(idxs) < 2:
            for i in idxs:
                out[i]["dup_score"] = "0"
                out[i]["dup_of"] = ""
                out[i]["dup_kind"] = ""
            continue
        n_dup_groups += 1
        for i in idxs:
            others = [j for j in idxs if j != i]
            kinds = set()
            descr = []
            cross = False
            for j in others:
                descr.append("%s/%s" % (out[j]["batch"], out[j]["source_dataset"] or "-"))
                if out[j]["batch"] != out[i]["batch"]:
                    cross = True
                a_, b_ = out[i], out[j]
                if all(str(a_.get(c, "")) == str(b_.get(c, "")) for c in COMPARE_COLUMNS):
                    kind = "exact_duplicate_row"
                else:
                    dcols = [c for c in COMPARE_COLUMNS
                             if str(a_.get(c, "")) != str(b_.get(c, ""))]
                    kind = ("marker_columns_only" if set(dcols) <= set(MARKER_COLUMNS)
                            else "measurement_differs")
                kinds.add("%s@%s" % (kind, out[j]["batch"]))
            out[i]["dup_score"] = str(len(others))
            out[i]["dup_of"] = ";".join(sorted(descr))
            out[i]["dup_kind"] = ";".join(sorted(kinds))
            if cross:
                n_cross_batch_rows += 1

    columns = BASE_COLUMNS + ADDED_COLUMNS
    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    outdir = (pathlib.Path(a.out_dir) if a.out_dir
              else REPO / "work/runs/labels-two-batch" / ts)
    if not outdir.is_absolute():
        outdir = REPO / outdir
    outdir.mkdir(parents=True, exist_ok=True)
    csvp = outdir / "labels_two_batch.csv"
    with csvp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(out)

    # ---------------- fail-closed 门禁（两次口径）----------------
    gates: dict[str, dict] = {}
    for tag, rkey in (("declared", "freq_range_MHz"), ("row_grid", "freq_grid_MHz")):
        checks = check_batch_isolation(out, range_key=rkey, decimals=a.decimals)
        gates[tag] = {"range_key": rkey, "verdict": evaluate_s3(checks)}
    worst = max(gates.values(), key=lambda g: _SEVERITY[g["verdict"]["verdict"]])
    release_allowed = all(g["verdict"]["verdict"] == "passed" for g in gates.values())
    if release_allowed:
        exit_code = EXIT_PASS
    elif any(g["verdict"]["n_failed"] for g in gates.values()):
        exit_code = EXIT_FAIL
    else:
        exit_code = EXIT_INCONCLUSIVE
    worst_verdict = worst["verdict"]["verdict"]

    # 原始标志列的**逐批**可得性（信息项；说明 batch_censored_not_eligible 覆盖到哪些行）
    flag_cov: dict[str, dict] = {}
    for b in sorted({r["batch"] for r in out}):
        sel = [r for r in out if r["batch"] == b]
        flag_cov[b] = {
            "n_rows": len(sel),
            "n_rows_with_peak_at_scan_endpoint": sum(
                1 for r in sel if str(r.get("peak_at_scan_endpoint", "")).strip() != ""),
            "n_rows_with_bw_upper_cutoff_at_endpoint": sum(
                1 for r in sel if str(r.get("bw_upper_cutoff_at_endpoint", "")).strip() != ""),
        }

    # ---------------- 与上一版并集表的差异说明 ----------------
    prevp = pathlib.Path(a.prev_union)
    prev_info: dict = {"path": _rel(prevp), "exists": prevp.exists()}
    if prevp.exists():
        prev = list(csv.DictReader(prevp.open("r", encoding="utf-8", newline="")))
        pcols = list(prev[0].keys())
        prev_info.update({
            "sha256": sha256_file(prevp), "n_rows": len(prev), "n_columns": len(pcols),
            "columns_only_in_prev": sorted(set(pcols) - set(columns)),
            "columns_only_in_new": sorted(set(columns) - set(pcols)),
            "rows_by_batch": {b: sum(1 for r in prev if r["batch"] == b)
                              for b in sorted({r["batch"] for r in prev})},
            "unique_combos_by_batch": {
                b: len({_identity(r, a.decimals) for r in prev if r["batch"] == b})
                for b in sorted({r["batch"] for r in prev})},
            "required_columns_present": {
                c: (c in pcols) for c in
                ("peak_at_scan_endpoint", "bw_upper_cutoff_at_endpoint",
                 "freq_range_MHz", "source_pipeline")},
        })

    stats: dict = {}
    for batch in ("C_5-50MHz", "V2_5-35MHz"):
        sel = [r for r in out if r["batch"] == batch]
        q = [r for r in sel if (f(r["Q"]) is not None) and Q_LO <= f(r["Q"]) <= Q_HI]
        u = [r for r in sel if r["usable"] == "True"]
        stats[batch] = {
            "n": len(sel),
            "n_unique_combos": len({_identity(r, a.decimals) for r in sel}),
            "n_Q_in_gate": len(q),
            "Q_gate_pct": 100 * len(q) / len(sel) if sel else 0.0,
            "n_usable": len(u) if batch.startswith("V2") else None,
            "Q_gate_pct_of_usable": (
                100 * len([r for r in u if f(r["Q"]) is not None and Q_LO <= f(r["Q"]) <= Q_HI])
                / len(u)) if u else None}

    version_id = "LTB2_v%s" % ts
    version = {
        "kind": "labels_union_version",
        "version_id": version_id,
        "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "frozen": False,
        "deduplicated": False,
        "dedup_note": "**本版未做去重，仅加标记**（dup_score / dup_of / dup_kind）；"
                      "去重规则待用户拍板，本脚本不执行任何删除。",
        "row_count": len(out),
        "column_count": len(columns),
        "columns": columns,
        "identity_key": {"param_keys": ["x_scale", "N_w_te1", "N_w_te2"],
                         "ulp_decimals": a.decimals,
                         "note": "组合身份键判等前**先做 ulp 归一化**（R5）；不做会把同一组合"
                                 "判成两个 ⇒ 新增数虚高（实测 83 误报成 117）"},
        "inputs": {
            "c_batch_source": {"path": _rel(oldp), "bytes": oldp.stat().st_size,
                               "sha256": sha256_file(oldp), "n_rows": len(old),
                               "n_columns": len(ocols)},
            "v2_frozen": {"path": _rel(v2p), "bytes": v2p.stat().st_size,
                          "sha256": sha256_file(v2p), "n_rows": len(v2)},
        },
        "outputs": {
            "labels_two_batch.csv": {"path": _rel(csvp), "bytes": csvp.stat().st_size,
                                     "sha256": sha256_file(csvp)},
        },
        "column_mapping": mapping,
        "unmapped_canonical": [k for k, v in mapping.items() if not v],
        "raw_flags": {
            "peak_at_scan_endpoint": "v2 侧原样搬自冻结副本；**C 侧该列不存在 ⇒ 留空**"
                                     "（不用派生值倒填，也不猜测）",
            "bw_upper_cutoff_at_endpoint": "同上",
            "usable": "派生列（v2 侧 = 峰值不在扫描端点 且 上截止点不在端点）；"
                      "**保留但不得作为原始标志的替代**——门禁缺原始列时判 inconclusive。",
            "per_batch_availability": flag_cov,
            "known_limitation": "C 批 2005 行的原始删失/截断标志在本表内**不可得**（原表无此列）"
                                "⇒ 门禁项 batch_censored_not_eligible 对 C 批**无法判定**；"
                                "该检查项因 v2 侧提供了列而整体可求值，其 passed 只覆盖 v2 行。"
                                "本版**未**修改门禁函数，也未另造一套判定；此处如实披露。",
        },
        "row_grid_disclosure": {
            "C_5-50MHz": {g: sum(1 for r in out if r["batch"] == "C_5-50MHz"
                                 and r["freq_grid_MHz"] == g)
                          for g in sorted({r["freq_grid_MHz"] for r in out
                                           if r["batch"] == "C_5-50MHz"})},
            "V2_5-35MHz": {g: sum(1 for r in out if r["batch"] == "V2_5-35MHz"
                                  and r["freq_grid_MHz"] == g)
                           for g in sorted({r["freq_grid_MHz"] for r in out
                                            if r["batch"] == "V2_5-35MHz"})},
            "note": "`freq_range_MHz` 是**批次声明口径**（与上一版并集表逐行一致）；"
                    "`freq_grid_MHz` 是**逐行真实栅格**。二者在 C 批的 223 行上不一致 —— "
                    "本版**不单方面改批次标签**，而是并置两套口径并让更严者决定退出码；"
                    "是否把 C 批的 A 子批重新登记为独立批次，**待用户拍板**。",
        },
        "dup_marking": {
            "n_rows": len(out),
            "n_dup_groups": n_dup_groups,
            "n_rows_in_dup_groups": sum(1 for r in out if r["dup_score"] != "0"),
            "definitions": {
                "dup_score": "本表内与它共享同一（ulp 归一化）组合键的**其他**行数",
                "dup_of": "这些其他行的 `<batch>/<source_dataset>` 列表（`;` 分隔）",
                "dup_kind": "逐对的重复类型：`exact_duplicate_row` / "
                            "`marker_columns_only`（差异仅在来源/栅格标记列） / "
                            "`measurement_differs`（测量列也不同），附对方批次",
            },
            "cross_batch_rows": n_cross_batch_rows,
            "cross_batch_definition": "本组内**至少有一个对应行的 `batch` 与本行不同**的行数",
        },
        "stats_by_batch": stats,
        "no_combined_number": True,
        "stats_note": "并集表带 batch 列；所有统计按批次分列，**禁止合成总分 / 合并池化**"
                      "（不同扫描范围不得混算）。",
        "previous_union": prev_info,
        "diff_vs_previous": [
            "行数与列名：上一版 15 列；本版保留这 15 列**原样且顺序不变**，并追加 "
            "%d 列（%s）。" % (len(ADDED_COLUMNS), "、".join(ADDED_COLUMNS)),
            "**修复**：上一版只保留派生 `usable`、丢掉原始标志 ⇒ 门禁 `batch_censored_not_eligible` "
            "报 `无法判定`。本版补入原始列 `peak_at_scan_endpoint` / "
            "`bw_upper_cutoff_at_endpoint`（v2 侧原样；C 侧留空）。",
            "**新增**：`source_pipeline` / `source_dataset` / `x_density_class` / "
            "`freq_grid_MHz` / `n_freq` / `source_model`（逐行来源与栅格，原样或由该行自身字段构造，"
            "不猜测）。",
            "**新增**：`dup_score` / `dup_of` / `dup_kind` 重复标记（**只标记，不去重**）。",
            "**未改**：行数、逐批组合数、`freq_range_MHz`、`usable`、数值列的取值与列名。",
        ],
        "gate": {
            "gate_function": "memsharness.sweep_analysis.check_batch_isolation",
            "verdict_function": "memsharness.consistency.evaluate_s3（未另造一套）",
            "runs": gates,
            "worst_verdict": worst_verdict,
            "release_allowed": release_allowed,
            "exit_code": exit_code,
            "exit_code_semantics": {"0": "passed", "2": "输入不可用",
                                    "3": "有 failed", "4": "无 failed 但有 inconclusive（不等于通过）"},
            "fail_closed": "判定不是 passed ⇒ 本脚本以非零退出码结束；**产物一律保留**，"
                           "并在本字段与 `release_allowed` 内明确标注不放行。",
            "raw_flag_coverage": flag_cov,
            "no_relaxation": "**未**为让判定通过而放松任何检查项、阈值或过滤任何不满足的组合；"
                             "删失/截断组合与跨批重叠**全部保留在表内**。",
        },
    }
    vpath = outdir / ("VERSION_%s.json" % version_id)
    vpath.write_text(json.dumps(version, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== 按批次分别统计（**不给合成数**）==")
    for batch, st in stats.items():
        print("  %-12s 组合 %4d（唯一 %4d）｜ Q∈[%.1f,%.1f] %4d（占全部 %5.1f%%）｜ 可用 %s"
              % (batch, st["n"], st["n_unique_combos"], Q_LO, Q_HI, st["n_Q_in_gate"],
                 st["Q_gate_pct"],
                 ("%d（其中 Q 达标 %5.1f%%）" % (st["n_usable"], st["Q_gate_pct_of_usable"]))
                 if st["n_usable"] is not None else "—（该批未做删失过滤）"))
    print("\n== 重复标记（**只标记，不去重**）==")
    print("  重复组 %d 个；涉及 %d 行；其中存在跨批对应行的 %d 行"
          % (n_dup_groups, version["dup_marking"]["n_rows_in_dup_groups"],
             version["dup_marking"]["cross_batch_rows"]))
    print("== 逐行真实栅格（freq_grid_MHz）==")
    print("  C_5-50MHz：%s" % json.dumps(version["row_grid_disclosure"]["C_5-50MHz"],
                                        ensure_ascii=False))
    print("  V2_5-35MHz：%s" % json.dumps(version["row_grid_disclosure"]["V2_5-35MHz"],
                                         ensure_ascii=False))
    print("\n== fail-closed 批次隔离门禁 ==")
    for tag, g in gates.items():
        v = g["verdict"]
        print("  [%s] range_key=%s ⇒ verdict=%s ｜ release_allowed=%s ｜ "
              "n_checks=%d n_failed=%d n_inconclusive=%d"
              % (tag, g["range_key"], v["verdict"], v["release_allowed"],
                 v["n_checks"], v["n_failed"], v["n_inconclusive"]))
        for cchk in v["checks"]:
            tagc = {True: "PASS", False: "FAIL", None: "????"}[cchk["passed"]]
            print("        [%s] %s%s" % (tagc, cchk["name"],
                                         ("  —— %s" % cchk["reason"]) if cchk["reason"] else ""))
    print("  ⇒ release_allowed=%s ｜ exit_code=%d" % (release_allowed, exit_code))
    if not release_allowed:
        print("  ⚠️ 不是通过：inconclusive 表示**判不了**（不等同通过）；"
              "产物已保留，供诊断。")
    print("\n并集表：%s（%d 行，%d 列）" % (_rel(csvp), len(out), len(columns)))
    print("版本清单：%s" % _rel(vpath))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
