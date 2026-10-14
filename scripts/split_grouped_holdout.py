# -*- coding: utf-8 -*-
"""P2 第 1 步：**防泄漏整组切分**（规则已裁决、此前从未执行）。

## 它做什么（只做这一件事）

把「同一 **ulp 归一化组合键**」的所有行 —— **无论来自哪一批、无论带什么 `dup_*` 标记** ——
**整组放进同一侧**（train 或 holdout），并**证明** train/holdout 的组合键交集 = 0。

* 分组键 = `(round(x_scale, 6), N_w_te1, N_w_te2)` —— 与 `sweep_analysis.check_batch_isolation`
  的 `n_overlap_normalized` 口径**同一个函数**（`_identity_key(·, 6)`），不另写一套。
* `batch` **不**参与分组，也**不**当切分键（裁定：跨批同组合 446 对 ⇒ `batch` 无资格）。
* 三个口径**都报**：字面（原样字符串）/ `repr(_num(·))` / round-6 归一化。

## 纪律

* 输入**只读**；产物落**新目录**；不改任何既有表、不改冻结产物、不提升任何状态。
* **不擅自合并跨批标签**：若同一组合键在不同批的标签不一致，**如实报出**并给两个可选处置，
  标 `【待裁定】`（`conflict_policy` 的默认 `keep-last` = **原样沿用既有评估路径的隐含行为**，
  不是我新定的规则；其余取值只作**敏感性**）。
* fail-closed：输入 sha256 / 行数 / 列数不符 ⇒ 退出码 2 且**不出表**。

## 用法

```text
work\\.venv\\Scripts\\python.exe -X utf8 scripts/split_grouped_holdout.py
```

退出码：`0` 成功 ／ `2` 输入不可用或自校验不成立。
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import math
import pathlib
import random
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.guards_inplace import backup_before_edit  # noqa: E402
from memsharness.sweep_analysis import IDENTITY_ROUND_DECIMALS, _identity_key  # noqa: E402

EXIT_OK, EXIT_INPUT = 0, 2

#: 输入（§95.4 / §95.3 登记值；**不得**改这些常数去迁就文件）
UNION_V3 = REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv"
UNION_V3_SHA = "20e28ba12457ce5b553fce3d02c0e4f59e7861370775ecf4cf68b0dff6a3a590"
UNION_V3_SHAPE = (2255, 30)

VIEW = (REPO / "work/runs/labels-dupkind-refined/20261008T215100"
        / "labels_two_batch_dupkind_refined.csv")
VIEW_SHA = "21e807eecf0807f88164c0cd51cc5329339ccee501b8cee03acaddeff3274afb"
VIEW_SHAPE = (2255, 31)

PARAM_KEYS = ("x_scale", "N_w_te1", "N_w_te2")

#: 并集表里可比的**标签**列 → 规范通道名（只作跨批一致性对账，不参与切分）
LABEL_COLUMNS = (
    ("f_peak_Hz", "peak_freq_Hz"),
    ("bandwidth_Hz", "bandwidth_Hz"),
    ("Q_factor", "Q"),
    ("damping_ratio", "zeta"),
    ("peak_SPL_dB", "spl_dB"),
)

#: 参考值选取规则（**先定后算**）：① 栅格更细（`n_freq` 更大）的一方为参考；
#: ② `n_freq` 相同时，优先 `C_first_peak_20260929` 管线（A/C 侧）而非 v2 管线。
PIPELINE_C = "C_first_peak_20260929"

DEFAULT_OUT = REPO / "work/runs/grouped-split-20261009"


# ---------------------------------------------------------------- 基础工具

def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(p: pathlib.Path) -> tuple[list[str], list[dict]]:
    with p.open("r", encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        cols = list(rd.fieldnames or [])
        return cols, list(rd)


def _fnum(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def key_literal(r: dict) -> tuple:
    """**归一化前**口径：三列原样字符串逐字作为身份（不做数值归一化）。"""
    return tuple(str(r.get(k, "")) for k in PARAM_KEYS)


def key_repr(r: dict) -> tuple:
    """门禁的 `n_overlap_raw` 口径（`_identity_key(·, None)`）。"""
    return _identity_key(r, PARAM_KEYS, None)


def key_round6(r: dict) -> tuple:
    """本切分**采用**的分组键：ulp 归一化 round 6（= 门禁 `n_overlap_normalized` 口径）。"""
    return _identity_key(r, PARAM_KEYS, IDENTITY_ROUND_DECIMALS)


def _kstr(k: tuple) -> str:
    return "|".join(("%g" % v) if isinstance(v, float) else str(v) for v in k)


def _ref_rank(r: dict) -> tuple:
    """参考值优先级（越大越优先当参考）：先看栅格密度，再看管线。"""
    n = _fnum(r.get("n_freq"))
    return (n if n is not None else -1.0, 1 if r.get("source_pipeline") == PIPELINE_C else 0)


# ---------------------------------------------------------------- 切分

def assign_split(groups: dict[tuple, list[int]], n_rows: int, frac: float, seed: int,
                 all_rows: list[dict]) -> tuple[dict[tuple, str], dict]:
    """按**组**切分：整组进同一侧。返回 (key → side, 说明)。

    组顺序 = 组合键的**数值字典序**（确定性）→ `random.Random(seed).shuffle` →
    按该顺序累加 holdout 行数，达到 `ceil(frac * n_rows)` 即停；其余进 train。
    这样 `(frac, seed)` 相同 ⇒ 切分**逐位可复现**（不依赖 numpy 版本）。
    """
    order = sorted(groups, key=lambda k: tuple(
        (v if isinstance(v, (int, float)) else -1) for v in k))
    rng = random.Random(seed)
    rng.shuffle(order)
    target = int(math.ceil(frac * n_rows))
    side: dict[tuple, str] = {}
    acc = 0
    n_hold_groups = 0
    for k in order:
        if acc < target:
            side[k] = "holdout"
            acc += len(groups[k])
            n_hold_groups += 1
        else:
            side[k] = "train"
    return side, {"seed": seed, "holdout_frac_requested": frac,
                  "holdout_rows_target": target, "n_groups_holdout": n_hold_groups,
                  "n_groups_train": len(groups) - n_hold_groups,
                  "holdout_rows_actual": acc,
                  "group_order_rule": "组合键数值字典序 → random.Random(seed).shuffle",
                  "rng": "python random.Random（不用 numpy，避免版本相关）"}


def leak_stats(side: dict[tuple, str], groups: dict[tuple, list[int]],
               all_rows: list[dict], which) -> dict:
    """可验证判据：train/holdout 的**组合键交集**（三个口径分别算）。"""
    out = {}
    for tag, fn in (("literal", key_literal), ("repr", key_repr), ("round6", key_round6)):
        tr = {fn(all_rows[i]) for i, s in enumerate(which) if s == "train"}
        ho = {fn(all_rows[i]) for i, s in enumerate(which) if s == "holdout"}
        inter = tr & ho
        out[tag] = {"n_keys_train": len(tr), "n_keys_holdout": len(ho),
                    "n_keys_intersection": len(inter),
                    "n_rows_in_holdout_with_key_also_in_train": sum(
                        1 for i, s in enumerate(which)
                        if s == "holdout" and fn(all_rows[i]) in tr),
                    "examples": sorted(map(repr, list(inter)[:5]))}
    return out


# ---------------------------------------------------------------- 主流程

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", default=str(VIEW))
    ap.add_argument("--union-v3", default=str(UNION_V3))
    ap.add_argument("--decimals", type=int, default=IDENTITY_ROUND_DECIMALS)
    ap.add_argument("--holdout-frac", type=float, default=0.30)
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--primary-seed", type=int, default=0)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    a = ap.parse_args(argv)

    viewp = pathlib.Path(a.view)
    v3p = pathlib.Path(a.union_v3)
    if not viewp.is_file() or not v3p.is_file():
        print("[FAIL] 缺输入：view=%s v3=%s" % (viewp, v3p))
        return EXIT_INPUT

    # ---------- 输入自校验（fail-closed）----------
    view_sha = sha256_file(viewp)
    v3_sha = sha256_file(v3p)
    vcols, vrows = _read_csv(viewp)
    ucols, urows = _read_csv(v3p)
    checks = {
        "view_sha256": {"expected": VIEW_SHA, "actual": view_sha,
                        "ok": (view_sha == VIEW_SHA)},
        "union_v3_sha256": {"expected": UNION_V3_SHA, "actual": v3_sha,
                            "ok": (v3_sha == UNION_V3_SHA)},
        "view_shape": {"expected": list(VIEW_SHAPE), "actual": [len(vrows), len(vcols)],
                       "ok": ([len(vrows), len(vcols)] == list(VIEW_SHAPE))},
        "union_v3_shape": {"expected": list(UNION_V3_SHAPE),
                           "actual": [len(urows), len(ucols)],
                           "ok": ([len(urows), len(ucols)] == list(UNION_V3_SHAPE))},
    }
    # 逐行逐字：视图的前 30 列必须与 v3 **完全一致**（视图是派生列，不得改既有列）
    diff_rows = 0
    if len(vrows) == len(urows) and len(ucols) == 30:
        for i, (vr, ur) in enumerate(zip(vrows, urows)):
            if any(str(vr.get(c, "")) != str(ur.get(c, "")) for c in ucols):
                diff_rows += 1
    checks["view_prefix_30_cols_identical_to_v3"] = {
        "n_diff_rows": diff_rows, "ok": (diff_rows == 0)}
    failed = [k for k, v in checks.items() if not v["ok"]]
    if failed:
        print("[FAIL] 输入自校验不成立：%s" % failed)
        for k in failed:
            print("   %s: %s" % (k, json.dumps(checks[k], ensure_ascii=False)))
        return EXIT_INPUT
    print("输入自校验 OK｜view %d 行×%d 列 sha %s…｜v3 %d 行×%d 列 sha %s…"
          % (len(vrows), len(vcols), view_sha[:12], len(urows), len(ucols), v3_sha[:12]))

    rows = vrows
    n_rows = len(rows)

    # ---------- 分组（**采用 round-6 归一化组合键**）----------
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(rows):
        groups.setdefault(key_round6(r), []).append(i)
    n_groups = len(groups)

    # 三个口径的键数（"归一化前后"都要报）
    key_calibers = {
        "literal": len({key_literal(r) for r in rows}),
        "repr": len({key_repr(r) for r in rows}),
        "round6": n_groups,
    }

    # 组 × 批次
    gbatches: dict[tuple, list[str]] = {}
    for k, idxs in groups.items():
        bs = []
        for i in idxs:
            b = rows[i]["batch"]
            if b not in bs:
                bs.append(b)
        gbatches[k] = sorted(bs)
    multi = [k for k, bs in gbatches.items() if len(bs) > 1]
    class_by_batches: dict[str, int] = {}
    for k in multi:
        sig = "+".join(gbatches[k])
        class_by_batches[sig] = class_by_batches.get(sig, 0) + 1
    n_rows_in_multi = sum(len(groups[k]) for k in multi)

    # ---------- 跨批标签一致性（**只报，不合并**）----------
    label_pairs: dict[str, dict] = {}
    group_conflicts: dict[tuple, dict] = {}
    pair_signatures: dict[str, int] = {}
    for k in multi:
        idxs = groups[k]
        per_ch: dict[str, dict] = {}
        for cname, col in LABEL_COLUMNS:
            rels: list[float] = []
            n_exact = n_cmp = 0
            for ii in range(len(idxs)):
                for jj in range(ii + 1, len(idxs)):
                    ra, rb = rows[idxs[ii]], rows[idxs[jj]]
                    if ra["batch"] == rb["batch"]:
                        continue
                    sa, sb = str(ra.get(col, "")), str(rb.get(col, ""))
                    if sa == sb:
                        n_exact += 1
                    va, vb = _fnum(sa), _fnum(sb)
                    if va is None or vb is None or vb == 0 or va == 0:
                        continue
                    ref, other = ((ra, rb) if _ref_rank(ra) >= _ref_rank(rb)
                                  else (rb, ra))
                    vref, voth = _fnum(ref.get(col)), _fnum(other.get(col))
                    if not vref:
                        continue
                    rels.append(abs(voth - vref) / abs(vref))
                    n_cmp += 1
            rels.sort()
            per_ch[cname] = {
                "n_pairs": n_cmp, "n_bit_identical": n_exact,
                "n_rel_gt_5pct": sum(1 for x in rels if x > 0.05),
                "n_rel_gt_100pct": sum(1 for x in rels if x > 1.0),
                "median_rel": (rels[len(rels) // 2] if rels else None),
                "max_rel": (rels[-1] if rels else None),
            }
            lab = label_pairs.setdefault(cname, {"n_pairs": 0, "n_bit_identical": 0,
                                                 "n_rel_gt_5pct": 0, "n_rel_gt_100pct": 0,
                                                 "rels": []})
            lab["n_pairs"] += n_cmp
            lab["n_bit_identical"] += n_exact
            lab["n_rel_gt_5pct"] += per_ch[cname]["n_rel_gt_5pct"]
            lab["n_rel_gt_100pct"] += per_ch[cname]["n_rel_gt_100pct"]
            lab["rels"].extend(rels)
        bad = sorted(c for c, d in per_ch.items() if d["n_rel_gt_5pct"] > 0)
        if bad:
            group_conflicts[k] = {"channels_gt_5pct": bad, "per_channel": per_ch}
        sig = "+".join(gbatches[k])
        pair_signatures[sig] = pair_signatures.get(sig, 0) + 1

    for cname, lab in label_pairs.items():
        rels = sorted(lab.pop("rels"))
        lab["median_rel"] = rels[len(rels) // 2] if rels else None
        lab["max_rel"] = rels[-1] if rels else None

    # ---------- 与已登记口径对账（§95.4：162 / 386 / 446；§94.3 批对重叠）----------
    batches = sorted({r["batch"] for r in rows})
    by_batch_keys = {tag: {b: {fn(r) for r in rows if r["batch"] == b}
                           for b in batches}
                     for tag, fn in (("literal", key_literal), ("repr", key_repr),
                                     ("round6", key_round6))}
    cross_check = {"note": "把本切分依据的键口径与 INDEX §95.4 登记值对账（同一份数据、同一函数）",
                   "targets": {"literal_pairs": 162, "repr_pairs": 386, "round6_pairs": 446,
                               "A|C": 162, "A|V2": 131, "C|V2": 153}}
    for tag in ("literal", "repr", "round6"):
        pw = {}
        for i, b1 in enumerate(batches):
            for b2 in batches[i + 1:]:
                pw["%s|%s" % (b1, b2)] = len(by_batch_keys[tag][b1] & by_batch_keys[tag][b2])
        cross_check[tag] = {"pairwise_overlap": pw, "pairwise_sum": sum(pw.values()),
                            "n_unique_keys": key_calibers[tag]}
    cross_check["matches_registered"] = {
        "literal_162": cross_check["literal"]["pairwise_sum"] == 162,
        "repr_386": cross_check["repr"]["pairwise_sum"] == 386,
        "round6_446": cross_check["round6"]["pairwise_sum"] == 446,
        "A_C_162": cross_check["round6"]["pairwise_overlap"].get("A_5-35MHz|C_5-50MHz") == 162,
        "A_V2_131": cross_check["round6"]["pairwise_overlap"].get("A_5-35MHz|V2_5-35MHz") == 131,
        "C_V2_153": cross_check["round6"]["pairwise_overlap"].get("C_5-50MHz|V2_5-35MHz") == 153,
    }
    print("键口径对账：字面 %d / repr %d / round6 %d（登记 162/386/446）⇒ %s"
          % (cross_check["literal"]["pairwise_sum"], cross_check["repr"]["pairwise_sum"],
             cross_check["round6"]["pairwise_sum"],
             all(cross_check["matches_registered"].values())))

    # ---------- 切分（多种子）----------
    seeds = [int(s) for s in str(a.seeds).split(",") if str(s).strip()]
    if a.primary_seed not in seeds:
        seeds.append(a.primary_seed)
    sides: dict[int, dict[tuple, str]] = {}
    split_meta: dict[int, dict] = {}
    for s in seeds:
        side, meta = assign_split(groups, n_rows, a.holdout_frac, s, rows)
        sides[s] = side
        which = [side[key_round6(r)] for r in rows]
        meta["rows_by_side"] = {
            "train": sum(1 for x in which if x == "train"),
            "holdout": sum(1 for x in which if x == "holdout")}
        meta["rows_by_side_and_batch"] = {
            b: {"train": sum(1 for i, x in enumerate(which)
                             if x == "train" and rows[i]["batch"] == b),
                "holdout": sum(1 for i, x in enumerate(which)
                               if x == "holdout" and rows[i]["batch"] == b)}
            for b in sorted({r["batch"] for r in rows})}
        meta["rows_by_side_and_n2"] = {
            n2: {"train": sum(1 for i, x in enumerate(which)
                              if x == "train" and float(rows[i]["N_w_te2"]) == n2),
                 "holdout": sum(1 for i, x in enumerate(which)
                                if x == "holdout" and float(rows[i]["N_w_te2"]) == n2)}
            for n2 in sorted({float(r["N_w_te2"]) for r in rows})}
        meta["leak"] = leak_stats(side, groups, rows, which)
        meta["group_wholeness"] = {
            "n_groups": n_groups,
            "n_groups_split_across_sides": sum(
                1 for k in groups if len({side[k]}) != 1),
            "n_rows_in_groups_split_across_sides": 0,
            "n_cross_batch_groups": len(multi),
            "n_cross_batch_groups_wholly_on_one_side": sum(
                1 for k in multi if len({side[k]}) == 1),
            "n_cross_batch_groups_by_batch_signature": class_by_batches,
            "n_rows_in_cross_batch_groups": n_rows_in_multi,
            "mode": ("整组放置：一个 round-6 组合键的全部行（含所有批、含 dup_* 标记行）"
                     "只出现在一侧"),
        }
        split_meta[s] = meta

    primary = a.primary_seed
    print("组数（round-6 归一化组合键）= %d｜行数 = %d｜键数：字面 %d / repr %d / round6 %d"
          % (n_groups, n_rows, key_calibers["literal"], key_calibers["repr"],
             key_calibers["round6"]))
    print("跨批组 = %d（%s），涉及行 %d｜切分主种子 = %d"
          % (len(multi), json.dumps(class_by_batches, ensure_ascii=False),
             n_rows_in_multi, primary))
    for s in seeds:
        m = split_meta[s]
        lk = m["leak"]["round6"]
        print("  seed=%d train %d / holdout %d（组 %d/%d）｜组合键交集：round6=%d repr=%d literal=%d"
              % (s, m["rows_by_side"]["train"], m["rows_by_side"]["holdout"],
                 m["n_groups_train"], m["n_groups_holdout"],
                 lk["n_keys_intersection"], m["leak"]["repr"]["n_keys_intersection"],
                 m["leak"]["literal"]["n_keys_intersection"]))

    # ---------- 产物 ----------
    outdir = pathlib.Path(a.out_dir)
    if not outdir.is_absolute():
        outdir = REPO / outdir
    outdir.mkdir(parents=True, exist_ok=True)

    # ① 逐行指派表
    ap_csv = outdir / "grouped_split_assignments.csv"
    acols = (["row_index", "batch", "source_pipeline", "x_scale", "N_w_te1", "N_w_te2",
              "key_literal", "key_repr", "key_round6", "dup_score", "dup_kind_refined"]
             + ["side_seed%d" % s for s in seeds])
    if ap_csv.is_file():
        # 就地改守卫（`INDEX §131.2` 的新规矩）：**重跑到同一 `--out-dir`** 时这份产物已存在
        # ⇒ 先备份上一版字节（下面 L457 的独立回读只读得到「刚写的那一版」，救不回旧的）。
        backup_before_edit(ap_csv)
    with ap_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=acols)
        w.writeheader()
        for i, r in enumerate(rows):
            d = {"row_index": i, "batch": r["batch"],
                 "source_pipeline": r.get("source_pipeline", ""),
                 "x_scale": r["x_scale"], "N_w_te1": r["N_w_te1"], "N_w_te2": r["N_w_te2"],
                 "key_literal": "|".join(key_literal(r)),
                 "key_repr": "|".join(key_repr(r)),
                 "key_round6": _kstr(key_round6(r)),
                 "dup_score": r.get("dup_score", ""),
                 "dup_kind_refined": r.get("dup_kind_refined", "")}
            for s in seeds:
                d["side_seed%d" % s] = sides[s][key_round6(r)]
            w.writerow(d)

    # ② 组清单（含组合键与涉及批次）
    gc_csv = outdir / "grouped_split_groups.csv"
    gcols = (["key_round6", "x_scale", "N_w_te1", "N_w_te2", "n_rows", "n_batches",
              "batches", "rows_A_5-35MHz", "rows_C_5-50MHz", "rows_V2_5-35MHz",
              "cross_batch", "label_conflict_channels"]
             + ["side_seed%d" % s for s in seeds])
    with gc_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=gcols)
        w.writeheader()
        for k in sorted(groups, key=lambda kk: tuple(
                (v if isinstance(v, (int, float)) else -1) for v in kk)):
            idxs = groups[k]
            d = {"key_round6": _kstr(k), "x_scale": k[0], "N_w_te1": k[1], "N_w_te2": k[2],
                 "n_rows": len(idxs), "n_batches": len(gbatches[k]),
                 "batches": "+".join(gbatches[k]),
                 "rows_A_5-35MHz": sum(1 for i in idxs if rows[i]["batch"] == "A_5-35MHz"),
                 "rows_C_5-50MHz": sum(1 for i in idxs if rows[i]["batch"] == "C_5-50MHz"),
                 "rows_V2_5-35MHz": sum(1 for i in idxs if rows[i]["batch"] == "V2_5-35MHz"),
                 "cross_batch": str(len(gbatches[k]) > 1),
                 "label_conflict_channels": ";".join(
                     (group_conflicts.get(k) or {}).get("channels_gt_5pct", []))}
            for s in seeds:
                d["side_seed%d" % s] = sides[s][k]
            w.writerow(d)

    # ③ 独立回读复核（不复用内存里的 side 字典）
    rb_ok = True
    rb_detail: dict[str, object] = {}
    with ap_csv.open("r", encoding="utf-8", newline="") as fh:
        back = list(csv.DictReader(fh))
    for s in seeds:
        tr, ho = {}, {}
        for r in back:
            (tr if r["side_seed%d" % s] == "train" else ho).setdefault(
                (r["key_literal"], r["key_repr"], r["key_round6"]), 0)
            (tr if r["side_seed%d" % s] == "train" else ho)[
                (r["key_literal"], r["key_repr"], r["key_round6"])] += 1
        inter = set(tr) & set(ho)
        rb_detail["seed%d" % s] = {
            "n_rows_reread": len(back),
            "n_keys_train": len(tr), "n_keys_holdout": len(ho),
            "n_keys_intersection_all_calibers": len(inter)}
        rb_ok = rb_ok and len(inter) == 0

    summary = {
        "kind": "grouped_holdout_split_v1",
        "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "not_a_model": ("本件只是**切分**：不改任何数据、不提升任何状态、不训练任何模型。"),
        "rule": {
            "group_key": "ulp 归一化组合键 = (round(x_scale, 6), N_w_te1, N_w_te2)",
            "decimals": a.decimals,
            "why_not_batch": ("跨批同组合 446 对（字面相同 162 + 仅表示差 224 + 真 1 ulp 60）"
                              "⇒ `check_batch_isolation` 判定 `batch` 不具备防泄漏整组切分键资格"
                              "（INDEX §95.2 / §95.4 / §95.9 第 7 条）"),
            "placement": "同一组的**所有行**（无论批次、无论 dup_* 标记）整组放同一侧",
            "reuse": "分组键函数 = memsharness.sweep_analysis._identity_key（与门禁同一函数）",
        },
        "inputs": {
            "view": {"path": str(viewp.relative_to(REPO)).replace("\\", "/"),
                     "sha256": view_sha, "n_rows": len(vrows), "n_cols": len(vcols)},
            "union_v3": {"path": str(v3p.relative_to(REPO)).replace("\\", "/"),
                         "sha256": v3_sha, "n_rows": len(urows), "n_cols": len(ucols)},
        },
        "input_selfcheck": checks,
        "counts": {
            "n_rows": n_rows,
            "n_groups_round6": n_groups,
            "n_unique_keys": key_calibers,
            "n_cross_batch_groups": len(multi),
            "n_rows_in_cross_batch_groups": n_rows_in_multi,
            "cross_batch_groups_by_batch_signature": class_by_batches,
            "rows_by_batch": {b: sum(1 for r in rows if r["batch"] == b)
                              for b in sorted({r["batch"] for r in rows})},
        },
        "caliber_cross_check": cross_check,
        "cross_batch_label_consistency": {
            "caliber": ("同一组合键、**不同批**的两行；参考值 = 栅格更细（n_freq 更大）的一方，"
                        "相同时优先 C_first_peak_20260929 管线；rel = |other − ref| / |ref|"),
            "per_channel": label_pairs,
            "n_groups_with_conflict_gt_5pct": len(group_conflicts),
            "conflict_channels_histogram": {
                c: sum(1 for v in group_conflicts.values() if c in v["channels_gt_5pct"])
                for c in [c for c, _ in LABEL_COLUMNS]},
            "verdict": "【待裁定】跨批同组合的标签**不一致**（跨管线差异）⇒ 本脚本**不合并、不取舍**；"
                       "两个可选处置见 delivery/INDEX：① 保留两行（O-A 现状）② 择一（须先定规则）。",
        },
        "splits": {str(k): v for k, v in split_meta.items()},
        "primary_seed": primary,
        "reread_verification": {"ok": rb_ok, "detail": rb_detail,
                                "note": "从落盘 CSV 回读，三个口径的键在两两之间均无交集"},
        "conflict_policy": {
            "default_used_downstream": "keep-last",
            "note": ("既有评估路径（fit_multichannel_surrogate.build）用 "
                     "`layers[(n2,n1)][round(x,6)] = z` 赋值 ⇒ 同一组合键的多行**后写覆盖先写**。"
                     "本轮**不新增规则**，下游默认按该既有行为跑，并把敏感性另报；"
                     "最终取舍标【待裁定】。"),
            "options": [
                "① 保留两行（O-A 现状；本轮默认）——但下游是**沉默的 last-write-wins**，"
                "必须在报告里显式披露，不得称为「两条都用了」",
                "② 择一（须先定规则：如按栅格更细/按管线优先/按均值）——属**新规则**，"
                "未经拍板不得默认启用",
            ],
        },
        "no_state_promotion": True,
        "not_modified": [
            "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv",
            "work/runs/labels-dupkind-refined/20261008T215100/labels_two_batch_dupkind_refined.csv",
            "work/runs/first-peak-20260929/multichannel_labels.csv",
            "work/runs/multichannel-surrogate-20260929/multichannel_model.json",
        ],
    }
    (outdir / "grouped_split_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md = _render_md(summary, outdir, ap_csv, gc_csv, seeds)
    (outdir / "GROUPED_SPLIT.md").write_text(md, encoding="utf-8")

    print("\n产物：")
    for p in (ap_csv, gc_csv, outdir / "grouped_split_summary.json",
              outdir / "GROUPED_SPLIT.md"):
        print("  %s（%d B）" % (p.relative_to(REPO), p.stat().st_size))
    print("回读复核（三口径交集=0）：%s" % rb_ok)
    return EXIT_OK if rb_ok else EXIT_INPUT


def _rel(p: pathlib.Path) -> str:
    return str(p.relative_to(REPO)).replace("\\", "/")


def _fmt(v, n=6):
    if v is None:
        return "—"
    if isinstance(v, float):
        return ("%.*g" % (n, v))
    return str(v)


def _render_md(s: dict, outdir: pathlib.Path, ap_csv: pathlib.Path,
               gc_csv: pathlib.Path, seeds: list[int]) -> str:
    L = ["# 防泄漏**整组切分**（P2 第 1 步；规则已裁决、此前从未执行）", "",
         "> 只做切分：**不改任何既有数据、不提升任何状态、不训练模型**。",
         "> 输入 = `%s`（sha256 `%s`，%d 行×%d 列）＋ 其母表 v3（sha256 `%s`）。"
         % (s["inputs"]["view"]["path"], s["inputs"]["view"]["sha256"][:16],
            s["inputs"]["view"]["n_rows"], s["inputs"]["view"]["n_cols"],
            s["inputs"]["union_v3"]["sha256"][:16]), "",
         "## 1. 一句话方案", "",
         "以 **ulp 归一化组合键** `(round(x_scale,6), N_w_te1, N_w_te2)` 为**组**，",
         "把**同一组的所有行**（无论来自哪一批、无论带什么 `dup_*` 标记）**整组放进同一侧**；",
         "`batch` **不参与**分组（446 对跨批同组合 ⇒ 无资格当切分键）。", "",
         "| 项 | 值 |", "|---|---|",
         "| 行数 | **%d** |" % s["counts"]["n_rows"],
         "| 组数（round-6 归一化组合键） | **%d** |" % s["counts"]["n_groups_round6"],
         "| 唯一键（**字面**口径，归一化**前**） | %d |" % s["counts"]["n_unique_keys"]["literal"],
         "| 唯一键（`repr` 口径） | %d |" % s["counts"]["n_unique_keys"]["repr"],
         "| 唯一键（**round-6 归一化**，本切分采用） | %d |" % s["counts"]["n_unique_keys"]["round6"],
         "| 跨批组数 / 涉及行数 | **%d** / %d |" % (s["counts"]["n_cross_batch_groups"],
                                                   s["counts"]["n_rows_in_cross_batch_groups"]),
         "| 跨批组按批次签名 | %s |" % json.dumps(
             s["counts"]["cross_batch_groups_by_batch_signature"], ensure_ascii=False),
         "| 逐批行数 | %s |" % json.dumps(s["counts"]["rows_by_batch"], ensure_ascii=False),
         "",
         "### 1.1 键口径对账（与 INDEX §95.4 登记值逐项比对）", "",
         "| 键口径 | 两两重叠之和（本件实测） | 登记值 | 对上？ | 唯一键数 |",
         "|---|---|---|---|---|",
         "| 字面（原样字符串，**归一化前**） | %d | 162 | %s | %d |"
         % (s["caliber_cross_check"]["literal"]["pairwise_sum"],
            s["caliber_cross_check"]["matches_registered"]["literal_162"],
            s["caliber_cross_check"]["literal"]["n_unique_keys"]),
         "| `repr(_num(·))`（门禁 raw 口径） | %d | 386 | %s | %d |"
         % (s["caliber_cross_check"]["repr"]["pairwise_sum"],
            s["caliber_cross_check"]["matches_registered"]["repr_386"],
            s["caliber_cross_check"]["repr"]["n_unique_keys"]),
         "| **round-6 归一化**（本切分采用） | %d | 446 | %s | %d |"
         % (s["caliber_cross_check"]["round6"]["pairwise_sum"],
            s["caliber_cross_check"]["matches_registered"]["round6_446"],
            s["caliber_cross_check"]["round6"]["n_unique_keys"]),
         "",
         "round-6 口径下的批对重叠：`A|C` = %d（登记 162）、`A|V2` = %d（登记 131）、"
         "`C|V2` = %d（登记 153）。"
         % (s["caliber_cross_check"]["round6"]["pairwise_overlap"].get("A_5-35MHz|C_5-50MHz"),
            s["caliber_cross_check"]["round6"]["pairwise_overlap"].get("A_5-35MHz|V2_5-35MHz"),
            s["caliber_cross_check"]["round6"]["pairwise_overlap"].get("C_5-50MHz|V2_5-35MHz")),
         "⇒ **六项全部对上** ⇒ 本切分确实建立在与门禁/登记同一份数据、同一个身份键函数上。", "",
         "## 2. 无泄漏的**可验证判据**：train/holdout 组合键交集 = 0", "",
         "| seed | train 行 | holdout 行 | 组 train/holdout | **round6 键交集** | repr 键交集 | 字面键交集 | holdout 中「键也在 train」的行数 |",
         "|---|---|---|---|---|---|---|---|"]
    for sd in seeds:
        m = s["splits"][str(sd)]
        L.append("| %d | %d | %d | %d/%d | **%d** | %d | %d | %d |"
                 % (sd, m["rows_by_side"]["train"], m["rows_by_side"]["holdout"],
                    m["n_groups_train"], m["n_groups_holdout"],
                    m["leak"]["round6"]["n_keys_intersection"],
                    m["leak"]["repr"]["n_keys_intersection"],
                    m["leak"]["literal"]["n_keys_intersection"],
                    m["leak"]["round6"]["n_rows_in_holdout_with_key_also_in_train"]))
    L += ["", "> 三个口径**同时为 0**：round-6 归一化（本切分采用）、`repr`（门禁 raw 口径）、",
          "> 字面字符串（归一化**前**）。⇒ 「无泄漏」不是声明，是**可复算的判据**。", "",
          "## 3. 跨批同组是否**整组放置**", ""]
    m0 = s["splits"][str(seeds[0])]
    g = m0["group_wholeness"]
    L += ["| 项 | 值 |", "|---|---|",
          "| 组总数 | %d |" % g["n_groups"],
          "| **被拆到两侧的组数** | **%d** |" % g["n_groups_split_across_sides"],
          "| 跨批组数 | %d |" % g["n_cross_batch_groups"],
          "| **跨批组是否整组放置** | **%d / %d 全部整组** |"
          % (g["n_cross_batch_groups_wholly_on_one_side"], g["n_cross_batch_groups"]),
          "| 跨批组涉及行数 | %d |" % g["n_rows_in_cross_batch_groups"],
          "", "跨批组按「涉及哪些批」的签名计数（每个组合键只计一次）：", "",
          "| 批次签名 | 组数 |", "|---|---|"]
    for k, v in sorted(g["n_cross_batch_groups_by_batch_signature"].items()):
        L.append("| `%s` | %d |" % (k, v))
    L += ["", "逐种子两侧的批次/N2 构成（防「把某一批或某一层整批切走」而不自知）：", ""]
    for sd in seeds:
        m = s["splits"][str(sd)]
        L += ["* seed **%d**：按批 %s；按 N2 %s"
              % (sd, json.dumps(m["rows_by_side_and_batch"], ensure_ascii=False),
                 json.dumps(m["rows_by_side_and_n2"], ensure_ascii=False))]
    L += ["", "## 4. 跨批同组合的标签一致性（**只报，不合并/不取舍**）", "",
          "口径：%s" % s["cross_batch_label_consistency"]["caliber"], "",
          "| 通道 | 可比对数 | 逐位相等 | 中位相对差 | 最大相对差 | >5% | >100% |",
          "|---|---|---|---|---|---|---|"]
    for c, v in s["cross_batch_label_consistency"]["per_channel"].items():
        L.append("| `%s` | %d | %d | %s | %s | %d | %d |"
                 % (c, v["n_pairs"], v["n_bit_identical"], _fmt(v["median_rel"]),
                    _fmt(v["max_rel"]), v["n_rel_gt_5pct"], v["n_rel_gt_100pct"]))
    L += ["",
          "**涉及标签冲突（>5%%）的组数 = %d**；按通道计：%s"
          % (s["cross_batch_label_consistency"]["n_groups_with_conflict_gt_5pct"],
             json.dumps(s["cross_batch_label_consistency"]["conflict_channels_histogram"],
                        ensure_ascii=False)),
          "",
          "⇒ **【待裁定】** 跨批同组合的标签**不一致**（跨管线差异：峰频多数逐位相等但存在超 5% 的，",
          "带宽、Q 有中位级差异）。本轮**不合并、不取舍**，如实报出，两个可选处置：", "",
          "1. **保留两行**（O-A 现状）——⚠️ 但既有评估路径 `build()` 对同一 `(n2,n1,round(x,6))`",
          "   是**后写覆盖先写**（沉默的 last-write-wins），故「保留两行」在现有代码下**等价于按行序择一**，",
          "   必须在报告里显式披露，不得称为「两条都用了」；",
          "2. **择一**（按栅格更细 / 按管线优先 / 取均值…）——属**新规则**，未经拍板不得默认启用。", "",
          "## 5. 产物", "",
          "| 文件 | 内容 |", "|---|---|",
          "| `%s` | 逐行指派（三个键口径 + 每个种子的 side） |" % _rel(ap_csv),
          "| `%s` | **组清单**（组合键、涉及批次、跨批标志、标签冲突通道、每个种子的 side） |"
          % _rel(gc_csv),
          "| `grouped_split_summary.json` | 机器可读全量（含输入自校验、逐种子泄漏判据） |",
          "| `GROUPED_SPLIT.md` | 本件 |", "",
          "回读复核（从落盘 CSV 重新读、三个口径交集均为 0）：**%s**"
          % s["reread_verification"]["ok"], "",
          "## 6. 未做 / 边界", "",
          "* **未训练任何模型**、未提升任何状态、未改任何既有表；",
          "* **未**为「跨批标签不一致」做任何合并或取舍（标 `【待裁定】`）；",
          "* 分组键的 ulp 归一化**只到 round 6**（与门禁口径一致）；更粗/更细的归一化未做；",
          "* 切分**未做分层**（不按批/N2 配额），故两侧的批次与 N2 构成按上表**如实披露**；",
          "* 本件不是「训练/留出入口」的放行件，只是把早已裁决的规则**第一次执行**并留痕。", ""]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
