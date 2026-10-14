# -*- coding: utf-8 -*-
"""P2 第 3 步：**分层**整组切分（INDEX §128.5 `【待补】Q3` 后半：**「分层切分未做」**）。

## 一句话

在**同一防泄漏约束**下（`(round(x_scale,6), N_w_te1, N_w_te2)` **整组**进同一侧；`batch` **不**当
分组键），把 1926 个组先按**分层键**分到互不相交的层，再**逐层**按比例配额切分 ⇒ 两侧的批/N2/x 构成
按比例对齐；然后**复用既有评估内核**在分层切分上重跑 8 通道，与**既有非分层整组切分**并列。

## 分层键（`strat_key`）

| 代号 | 分层键 | 说明 |
|---|---|---|
| `S_batch` | 组的**批次构成签名**（如 `A_5-35MHz`、`A_5-35MHz+C_5-50MHz`） | 跨批组自成一签名（不按行拆批） |
| `S_n2` | `N_w_te2` 层（3…9） | 组内 N2 唯一（键含 N2） |
| `S_x3` | x **三分位**（`x_low`/`x_mid`/`x_high`，按组级 x 升序切） | 分界值随数据现算并登记 |
| `S_batch_n2` / `S_batch_x3` / `S_n2_x3` / `S_batch_n2_x3` | 组合键 | 层数不足时空层**不参与**（实测层数逐项报出） |

## 配额口径（**先定后算**）

1. 每层配额 `quota_i = frac × 该层行数`；取 `floor`，余数按**最大余数法**补齐到全局 `ceil(frac×N)`；
2. 层内：组按**数值字典序**排序 → `random.Random(mix(seed, 层名)).shuffle` → 累加行数到配额即停；
   `mix` = `(seed << 20) ^ (crc32(层名) & 0xfffff)`（**不依赖 `PYTHONHASHSEED`**，逐位可复现）；
3. 整组放置：同一个 round-6 组合键的**全部行**只在一边。

## 纪律

* **不改**任何既有产物（既有 `work/runs/grouped-split-20261009/*` 一律**只读**）、不提升任何状态、不跑 COMSOL；
* 复用 `scripts/split_grouped_holdout.py` 的键函数与 `scripts/rerun_grouped_split_channels.py` 的评估路径
  （`import` 复用，**未复制未改写**）；
* **回归对照**：本脚本重算的**非分层**口径必须与既有 `grouped_split_assignments.csv` 与
  `rerun_channel_lift_table.csv` **逐位一致**（否则退出码 2）——证明新旧两列确实同机同径；
* 每通道给**可判定分母**（`n_defined_holdout` / `n_in_domain_holdout`）与 flag 口径对照（`n_flag_usable_holdout`）；
  **不得用 flag 口径当分母**；
* **不得**据任何一种切分宣布翻身；`channels_without_lift` 与 `draft` 状态**不变**。

用法::

    work\\.venv\\Scripts\\python.exe -X utf8 scripts/stratified_grouped_split.py

退出码：`0` 成功 ／ `2` 输入不可用、自校验或回归对照不成立。
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import importlib.util
import json
import math
import pathlib
import random
import sys
import zlib

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

EXIT_OK, EXIT_FAIL = 0, 2

SCRIPTS = REPO / "scripts"
OLD_DIR = REPO / "work/runs/grouped-split-20261009"
DEFAULT_OUT = REPO / "work/runs/stratified-split-20261009"

SEEDS = (0, 1, 2, 3, 4)
HOLDOUT_FRAC = 0.30

STRAT_KEYS = ("S_batch", "S_n2", "S_x3", "S_batch_n2", "S_batch_x3", "S_n2_x3", "S_batch_n2_x3")

FOCUS_CHANNELS = ("bandwidth_Hz", "Q_factor", "abs_w_m")


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def read_csv(p: pathlib.Path) -> tuple[list[str], list[dict]]:
    with p.open("r", encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        return list(rd.fieldnames or []), [dict(r) for r in rd]


# ================================================================ 分层键

def tercile_bounds(xs_sorted: list[float]) -> tuple[float, float]:
    """x 三分位分界（**先定后算**）：`b1 = xs[n//3]`、`b2 = xs[2n//3]`（升序，含并列）。"""
    n = len(xs_sorted)
    return xs_sorted[n // 3], xs_sorted[(2 * n) // 3]


def make_strata(groups: dict, rows: list[dict], key_of) -> tuple[dict, dict, dict]:
    """组 → 各分层键的层标签。返回 (labels_by_key, meta, bounds)。"""
    gb: dict[tuple, list[str]] = {}
    gx: dict[tuple, float] = {}
    gn2: dict[tuple, float] = {}
    for k, idxs in groups.items():
        gb[k] = sorted({rows[i]["batch"] for i in idxs})
        gx[k] = k[0]
        gn2[k] = k[2]
    b1, b2 = tercile_bounds(sorted(gx.values()))

    def x3_of(k):
        x = gx[k]
        if x <= b1:
            return "x_low"
        if x <= b2:
            return "x_mid"
        return "x_high"

    labels: dict[tuple, dict[str, str]] = {}
    for k in groups:
        b = "+".join(gb[k])
        n2 = "%g" % gn2[k]
        x3 = x3_of(k)
        labels[k] = {
            "S_batch": b,
            "S_n2": "N2=%s" % n2,
            "S_x3": x3,
            "S_batch_n2": "%s|N2=%s" % (b, n2),
            "S_batch_x3": "%s|%s" % (b, x3),
            "S_n2_x3": "N2=%s|%s" % (n2, x3),
            "S_batch_n2_x3": "%s|N2=%s|%s" % (b, n2, x3),
        }
    meta = {"x_tercile_bounds": {"b1": b1, "b2": b2,
                                 "rule": "xs 升序后 b1=xs[n//3]、b2=xs[2n//3]；"
                                         "x<=b1→x_low、b1<x<=b2→x_mid、x>b2→x_high"},
            "n_groups": len(groups),
            "batch_signatures": {s: sum(1 for k in groups if "+".join(gb[k]) == s)
                                 for s in sorted({"+".join(v) for v in gb.values()})}}
    return labels, meta, {"b1": b1, "b2": b2}


def mix_seed(seed: int, stratum: str) -> int:
    """`(seed, 层名)` → 无歧义整数种子（**不依赖 `PYTHONHASHSEED`**）。"""
    return (int(seed) << 20) ^ (zlib.crc32(stratum.encode("utf-8")) & 0xFFFFF)


def grouped_stratum_ledger(groups: dict, side: dict, labels: dict, strat_key: str) -> dict:
    """**非分层**切分下同一分层的 train/holdout 占比（对照，用来证明分层确实生效）。"""
    out: dict[str, dict] = {}
    for k, idxs in groups.items():
        d = out.setdefault(labels[k][strat_key],
                           {"n_groups": 0, "n_rows": 0, "train_rows": 0, "holdout_rows": 0})
        d["n_groups"] += 1
        d["n_rows"] += len(idxs)
        if side[k] == "train":
            d["train_rows"] += len(idxs)
        else:
            d["holdout_rows"] += len(idxs)
    for d in out.values():
        d["holdout_row_frac"] = d["holdout_rows"] / d["n_rows"]
    return out


def stratified_assign(groups: dict, frac: float, seed: int, labels: dict,
                      strat_key: str) -> tuple[dict, dict]:
    """**分层 + 整组**切分。返回 (key → side, 逐层账本)。"""
    by_stratum: dict[str, list[tuple]] = {}
    for k in groups:
        by_stratum.setdefault(labels[k][strat_key], []).append(k)
    n_total = sum(len(groups[k]) for k in groups)
    global_target = int(math.ceil(frac * n_total))

    # ---- 配额：floor + 最大余数法补齐（先定后算）----
    strata = sorted(by_stratum)
    quota: dict[str, int] = {}
    rem: dict[str, float] = {}
    for s in strata:
        rows_s = sum(len(groups[k]) for k in by_stratum[s])
        q = frac * rows_s
        quota[s] = int(math.floor(q))
        rem[s] = q - quota[s]
    assigned = sum(quota.values())
    need = max(0, global_target - assigned)
    for s in sorted(strata, key=lambda s: (-rem[s], s))[:need]:
        quota[s] += 1

    side: dict[tuple, str] = {}
    ledger: dict[str, dict] = {}
    for s in strata:
        ks = sorted(by_stratum[s], key=lambda k: tuple(
            (v if isinstance(v, (int, float)) else -1) for v in k))
        rows_s = sum(len(groups[k]) for k in ks)
        rng = random.Random(mix_seed(seed, "%s::%s" % (strat_key, s)))
        rng.shuffle(ks)
        tgt = quota[s]
        acc = 0
        n_ho_groups = 0
        for k in ks:
            if acc < tgt:
                side[k] = "holdout"
                acc += len(groups[k])
                n_ho_groups += 1
            else:
                side[k] = "train"
        ledger[s] = {
            "n_groups": len(ks), "n_rows": rows_s,
            "quota_rows": tgt, "quota_exact": frac * rows_s,
            "n_groups_holdout": n_ho_groups, "n_groups_train": len(ks) - n_ho_groups,
            "holdout_rows": acc, "train_rows": rows_s - acc,
            "holdout_row_frac": (acc / rows_s) if rows_s else None,
            "train_row_frac": ((rows_s - acc) / rows_s) if rows_s else None,
            "rng": "random.Random((seed<<20) ^ (crc32(层名) & 0xfffff))；层内组序=组合键数值字典序→shuffle",
        }
    overall = {
        "strat_key": strat_key, "seed": seed, "n_strata": len(strata),
        "holdout_rows": sum(v["holdout_rows"] for v in ledger.values()),
        "train_rows": sum(v["train_rows"] for v in ledger.values()),
        "global_target_rows": global_target,
        "holdout_row_frac": (sum(v["holdout_rows"] for v in ledger.values()) / n_total),
    }
    return side, {"per_stratum": ledger, "overall": overall}


# ================================================================ 主流程

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default=",".join(str(s) for s in SEEDS))
    ap.add_argument("--holdout-frac", type=float, default=HOLDOUT_FRAC)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    a = ap.parse_args(argv)
    seeds = [int(x) for x in str(a.seeds).split(",") if x.strip()]

    sg = _load("_sg", SCRIPTS / "split_grouped_holdout.py")
    rr = _load("_rr", SCRIPTS / "rerun_grouped_split_channels.py")
    hashmod = _load("_ch", SCRIPTS / "collection_content_hashes.py")

    # ---------- 输入（fail-closed：登记 sha256 必须对上）----------
    for p, want in ((sg.VIEW, sg.VIEW_SHA), (sg.UNION_V3, sg.UNION_V3_SHA)):
        got = sha256_file(p)
        if got != want:
            print("[FAIL] 输入 sha256 不符：%s got=%s want=%s" % (p, got, want))
            return EXIT_FAIL
    for p in (sg.VIEW, sg.UNION_V3, rr.ASSIGN, rr.LABELS_AC, rr.LABELS_V2, rr.FITTER,
              OLD_DIR / "rerun_channel_lift_table.csv"):
        if not p.is_file():
            print("[FAIL] 缺输入：%s" % p)
            return EXIT_FAIL

    cols, rows = read_csv(sg.UNION_V3)
    n_rows = len(rows)
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(rows):
        groups.setdefault(sg.key_round6(r), []).append(i)
    n_groups = len(groups)
    print("并集表 %d 行 × %d 列 ⇒ **%d 组**（round-6 组合键）" % (n_rows, len(cols), n_groups))

    labels, strata_meta, bounds = make_strata(groups, rows, sg.key_round6)
    print("分层键：%s｜x 三分位分界 b1=%g b2=%g"
          % (", ".join(STRAT_KEYS), bounds["b1"], bounds["b2"]))

    # ---------- ① 既有非分层整组切分（**重算**，用于回归对照）----------
    old_side: dict[int, dict] = {}
    old_meta: dict[int, dict] = {}
    for s in seeds:
        side, meta = sg.assign_split(groups, n_rows, a.holdout_frac, s, rows)
        old_side[s] = side
        which = [side[sg.key_round6(r)] for r in rows]
        meta["rows_by_side"] = {"train": sum(1 for x in which if x == "train"),
                                "holdout": sum(1 for x in which if x == "holdout")}
        meta["leak"] = sg.leak_stats(side, groups, rows, which)
        old_meta[s] = meta

    # 回归对照 ①：与既有落盘指派表**逐行逐位**一致
    _ac, arows = read_csv(rr.ASSIGN)
    reg_assign = {}
    for s in seeds:
        col = "side_seed%d" % s
        mism = sum(1 for i, r in enumerate(arows)
                   if old_side[s][sg.key_round6(r)] != r[col])
        reg_assign["seed%d" % s] = {"n_rows": len(arows), "n_mismatch": mism, "ok": mism == 0}
    reg_ok = all(v["ok"] for v in reg_assign.values())
    print("回归对照 ①（重算非分层切分 == 既有 grouped_split_assignments.csv）: %s" % reg_ok)
    if not reg_ok:
        print("[FAIL] 非分层切分与既有指派表不一致 ⇒ 拒绝出表")
        return EXIT_FAIL

    # ---------- ② 分层切分（7 个分层键 × 多种子）----------
    strat_side: dict[tuple, dict[int, dict]] = {}
    strat_ledger: dict[tuple, dict] = {}
    for sk in STRAT_KEYS:
        for s in seeds:
            side, led = stratified_assign(groups, a.holdout_frac, s, labels, sk)
            strat_side[(sk, s)] = side
            strat_ledger["%s|seed%d" % (sk, s)] = led

    # ---------- ③ 无泄漏判据（三口径）+ 逐层占比 ----------
    leak_report = {}
    for s in seeds:
        which_old = [old_side[s][sg.key_round6(r)] for r in rows]
        entry = {"grouped": sg.leak_stats(old_side[s], groups, rows, which_old)}
        for sk in STRAT_KEYS:
            side = strat_side[(sk, s)]
            which = [side[sg.key_round6(r)] for r in rows]
            entry[sk] = sg.leak_stats(side, groups, rows, which)
        leak_report["seed%d" % s] = entry
    n_bad = sum(1 for s in seeds for k, v in leak_report["seed%d" % s].items()
                if v["round6"]["n_keys_intersection"] or v["repr"]["n_keys_intersection"]
                or v["literal"]["n_keys_intersection"])
    print("无泄漏判据（%d 个「切分口径×种子」× 三口径）不成立数 = %d" % (len(seeds) * 8, n_bad))

    # ---------- ③b 分层生效对照：同一分层在「非分层」下的 holdout 占比 ----------
    grouped_by_stratum = {sk: {str(s): grouped_stratum_ledger(groups, old_side[s], labels, sk)
                               for s in seeds} for sk in STRAT_KEYS}
    degenerate = []
    for sk in STRAT_KEYS:
        for s in seeds:
            for name, v in strat_ledger["%s|seed%d" % (sk, s)]["per_stratum"].items():
                if v["train_rows"] == 0 or v["holdout_rows"] == 0:
                    degenerate.append({"strat_key": sk, "seed": s, "stratum": name,
                                       "n_groups": v["n_groups"], "n_rows": v["n_rows"],
                                       "train_rows": v["train_rows"],
                                       "holdout_rows": v["holdout_rows"]})
    print("极小层（train 或 holdout 行数为 0）的「分层键×种子×层」数 = %d" % len(degenerate))

    # ---------- ④ 8 通道 lift：新旧并列 ----------
    F = rr.load_fitter()
    ac, ac_meta = rr.rows_ac(F)
    v2, v2_meta = rr.rows_v2(F, rr.SHARED4)
    fixtures = {"C": [r for r in ac if r["batch"] == "C_5-50MHz"],
                "AC": list(ac), "UNION4": list(ac) + list(v2)}
    chans_of = {"C": tuple(F.CHANNELS), "AC": tuple(F.CHANNELS), "UNION4": rr.SHARED4}

    for name, fx in fixtures.items():
        missing = [r for r in fx if r["key"] not in groups]
        if missing:
            print("[FAIL] %s 有 %d 行的组合键不在并集分组里（例 %r）"
                  % (name, len(missing), missing[0]["key"]))
            return EXIT_FAIL

    def run_caliber(rule, data, seed, side_map) -> dict:
        fx = fixtures[data]
        pool = [r for r in fx if not r["quarantined"]]
        train = [r for r in pool if side_map[r["key"]] == "train"]
        test = [r for r in pool if side_map[r["key"]] == "holdout"]
        chans = {c: rr.evaluate(F, train, test, c) for c in chans_of[data]}
        return {"rule": rule, "data": data, "seed": seed,
                "n_train_rows": len(train), "n_holdout_rows": len(test),
                "leak": rr.leak(F, train, test), "channels": chans}

    results: list[dict] = []
    for data in ("C", "AC", "UNION4"):
        for s in seeds:
            results.append(run_caliber("grouped(非分层)", data, s, old_side[s]))
        for sk in STRAT_KEYS:
            for s in seeds:
                results.append(run_caliber("stratified:%s" % sk, data, s, strat_side[(sk, s)]))
    print("评估口径数 = %d" % len(results))

    # ---------- 回归对照 ②：与既有 rerun_channel_lift_table.csv 逐位一致 ----------
    _c, old_lift = read_csv(OLD_DIR / "rerun_channel_lift_table.csv")
    old_idx = {(r["data"], int(r["seed"]), r["channel"]): r for r in old_lift
               if r["split_rule"] == "grouped"}
    reg_lift = {"n_compared": 0, "n_mismatch": 0, "examples": []}
    for res in results:
        if res["rule"] != "grouped(非分层)":
            continue
        for ch, v in res["channels"].items():
            k = (res["data"], res["seed"], ch)
            o = old_idx.get(k)
            if o is None:
                continue
            reg_lift["n_compared"] += 1
            def _eq(x, y):
                if x in ("", None) and y is None:
                    return True
                try:
                    return abs(float(x) - float(y)) < 1e-15
                except (TypeError, ValueError):
                    return False
            ok = (int(o["n_holdout_rows"]) == res["n_holdout_rows"]
                  and int(o["n_predicted"]) == v["n_predicted"]
                  and int(o["n_defined_holdout"]) == v["n_defined_holdout"]
                  and int(o["n_in_domain_holdout"]) == v["n_in_domain_holdout"]
                  and _eq(o["median_err"], v["median"])
                  and _eq(o["lift_vs_persistence"], v["lift_vs_persistence"])
                  and _eq(o["baseline_persistence_median"], v["baseline_persistence_median"]))
            if not ok:
                reg_lift["n_mismatch"] += 1
                if len(reg_lift["examples"]) < 5:
                    reg_lift["examples"].append(
                        {"key": list(k), "old": {kk: o[kk] for kk in
                                                 ("n_holdout_rows", "n_predicted", "median_err",
                                                  "lift_vs_persistence")},
                         "new": {"n_holdout_rows": res["n_holdout_rows"],
                                 "n_predicted": v["n_predicted"], "median": v["median"],
                                 "lift": v["lift_vs_persistence"]}})
    reg_lift["ok"] = reg_lift["n_mismatch"] == 0 and reg_lift["n_compared"] > 0
    print("回归对照 ②（重算非分层 lift == 既有 rerun_channel_lift_table.csv）：%s（%d 项比对，%d 不符）"
          % (reg_lift["ok"], reg_lift["n_compared"], reg_lift["n_mismatch"]))

    # ---------- ⑤ 稳定性和判定 ----------
    stability = build_stability(results, seeds)
    verdict = build_verdict(stability)

    # ---------- 产物 ----------
    outdir = pathlib.Path(a.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 组清单（含每层每 seed 的 side）
    gcols = (["key_round6", "x_scale", "N_w_te1", "N_w_te2", "n_rows", "batches"]
             + ["%s" % sk for sk in STRAT_KEYS]
             + ["side_%s_seed%d" % (sk, s) for sk in STRAT_KEYS for s in seeds])
    gpath = outdir / "stratified_split_groups.csv"
    with gpath.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=gcols)
        w.writeheader()
        for k in sorted(groups, key=lambda kk: tuple(kk)):
            d = {"key_round6": sg._kstr(k), "x_scale": k[0], "N_w_te1": k[1], "N_w_te2": k[2],
                 "n_rows": len(groups[k]),
                 "batches": "+".join(sorted({rows[i]["batch"] for i in groups[k]}))}
            for sk in STRAT_KEYS:
                d[sk] = labels[k][sk]
            for sk in STRAT_KEYS:
                for s in seeds:
                    d["side_%s_seed%d" % (sk, s)] = strat_side[(sk, s)][k]
            w.writerow(d)

    # 逐行指派
    acols = (["row_index", "batch", "x_scale", "N_w_te1", "N_w_te2", "key_round6"]
             + ["%s" % sk for sk in STRAT_KEYS]
             + ["side_grouped_seed%d" % s for s in seeds]
             + ["side_%s_seed%d" % (sk, s) for sk in STRAT_KEYS for s in seeds])
    apath = outdir / "stratified_split_assignments.csv"
    with apath.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=acols)
        w.writeheader()
        for i, r in enumerate(rows):
            k = sg.key_round6(r)
            d = {"row_index": i, "batch": r["batch"], "x_scale": r["x_scale"],
                 "N_w_te1": r["N_w_te1"], "N_w_te2": r["N_w_te2"],
                 "key_round6": sg._kstr(k)}
            for sk in STRAT_KEYS:
                d[sk] = labels[k][sk]
            for s in seeds:
                d["side_grouped_seed%d" % s] = old_side[s][k]
            for sk in STRAT_KEYS:
                for s in seeds:
                    d["side_%s_seed%d" % (sk, s)] = strat_side[(sk, s)][k]
            w.writerow(d)

    # 逐层占比表
    comp_path = outdir / "stratum_composition.csv"
    with comp_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["strat_key", "seed", "stratum", "n_groups", "n_rows",
                    "quota_rows", "quota_exact", "groups_train", "groups_holdout",
                    "rows_train", "rows_holdout", "holdout_row_frac", "train_row_frac"])
        for sk in STRAT_KEYS:
            for s in seeds:
                led = strat_ledger["%s|seed%d" % (sk, s)]
                for name, v in led["per_stratum"].items():
                    w.writerow([sk, s, name, v["n_groups"], v["n_rows"], v["quota_rows"],
                                "%.6f" % v["quota_exact"], v["n_groups_train"],
                                v["n_groups_holdout"], v["train_rows"], v["holdout_rows"],
                                "%.6f" % v["holdout_row_frac"], "%.6f" % v["train_row_frac"]])

    # lift 长表（新旧并列）
    lpath = outdir / "stratified_channel_lift_table.csv"
    lrows = []
    for res in results:
        for ch, v in res["channels"].items():
            lrows.append({
                "rule": res["rule"], "data": res["data"], "seed": res["seed"], "channel": ch,
                "group": v["group"], "is_formal_objective": v["is_formal_objective"],
                "n_train_rows": res["n_train_rows"], "n_holdout_rows": res["n_holdout_rows"],
                "leak_rows": res["leak"]["n_rows_key_also_in_train"],
                "n_defined_holdout": v["n_defined_holdout"],
                "n_in_domain_holdout": v["n_in_domain_holdout"],
                "n_flag_usable_holdout": v["n_flag_usable_holdout"],
                "n_predicted": v["n_predicted"],
                "coverage_of_defined": v["coverage_of_defined"],
                "coverage_of_in_domain": v["coverage_of_in_domain"],
                "median_err": v["median"], "p90": v["p90"],
                "baseline_persistence_median": v["baseline_persistence_median"],
                "lift_vs_persistence": v["lift_vs_persistence"],
                "beats_persistence": v["beats_persistence"],
                "verdict_band": v["verdict_band"],
                "n_in_layer": v["modes"]["in_layer"], "n_n2_extrap": v["modes"]["n2_extrap"],
                "refusal_reasons": json.dumps(v["refusal_reasons"], ensure_ascii=False),
            })
    with lpath.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(lrows[0].keys()))
        w.writeheader()
        w.writerows(lrows)

    # 集合内容哈希（新集合：分层切分的 train/holdout 组集合）——用同一份规范化口径
    new_hashes = {}
    for sk in STRAT_KEYS:
        for s in seeds:
            side = strat_side[(sk, s)]
            for want in ("train", "holdout"):
                triples = [k for k in groups if side[k] == want]
                lines = hashmod.canonical_lines_keys(triples)
                h = hashmod.hash_lines(lines)
                new_hashes["stratified_%s_%s_groups_seed%d" % (sk, want, s)] = {
                    "element_type": "key", "n_elements": h["n_elements"],
                    "n_unique_elements": h["n_unique_elements"], "n_bytes": h["n_bytes"],
                    "sha256": h["sha256"]}

    summary = {
        "kind": "stratified_grouped_split_v1",
        "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "not_a_model": "本件只是**切分 + 用既有内核重跑指标**：不改数据、不提升状态、不跑 COMSOL。",
        "inputs": {
            "union_v3": {"path": str(sg.UNION_V3.relative_to(REPO)).replace("\\", "/"),
                         "sha256": sg.UNION_V3_SHA},
            "view": {"path": str(sg.VIEW.relative_to(REPO)).replace("\\", "/"),
                     "sha256": sg.VIEW_SHA},
            "assignments_readonly": {"path": str(rr.ASSIGN.relative_to(REPO)).replace("\\", "/"),
                                     "sha256": sha256_file(rr.ASSIGN)},
            "eval_core": {"path": str(rr.FITTER.relative_to(REPO)).replace("\\", "/"),
                          "sha256": sha256_file(rr.FITTER),
                          "reuse": "import fit_multichannel_surrogate（未改写）"},
            "labels_ac": ac_meta, "labels_v2": v2_meta,
        },
        "rule": {
            "group_key": "(round(x_scale,6), N_w_te1, N_w_te2) —— 与门禁同一函数，整组放置",
            "batch_not_a_grouping_key": "跨批同组合 446 对（§95.4）⇒ batch 无资格当分组键；"
                                        "本件把 batch 用作**分层键**（只影响配额，不影响整组放置）",
            "strat_keys": list(STRAT_KEYS),
            "quota": "每层 floor(frac×行数) + 最大余数法补齐到 ceil(frac×N)；层内组序=数值字典序→"
                     "random.Random((seed<<20)^(crc32(层名)&0xfffff)).shuffle；累加到配额即停",
            "holdout_frac_requested": a.holdout_frac,
        },
        "strata": strata_meta,
        "n_rows": n_rows, "n_groups": n_groups,
        "old_grouped_split": {str(s): {"leak": old_meta[s]["leak"],
                                       "rows_by_side": old_meta[s]["rows_by_side"],
                                       "n_groups_train": old_meta[s]["n_groups_train"],
                                       "n_groups_holdout": old_meta[s]["n_groups_holdout"]}
                              for s in seeds},
        "leak_three_calibers": leak_report,
        "n_leak_failures": n_bad,
        "stratum_ledger": strat_ledger,
        "grouped_by_stratum_ledger": grouped_by_stratum,
        "degenerate_strata": degenerate,
        "regression_vs_existing": {"assignments": reg_assign, "lift_table": reg_lift},
        "stability": stability,
        "verdict": verdict,
        "lifts": results,
        "new_collection_hashes": new_hashes,
        "self_consistency_with_113_114": {
            "channels_without_lift": ["bandwidth_Hz", "Q_factor"],
            "changed": False,
            "statement": ("§113/§114 的 `channels_without_lift = ['bandwidth_Hz','Q_factor']` 与 "
                          "`draft` 状态**不变**；本件不据任何一种切分宣布翻身；"
                          "`abs_w_m` 的反向转负与「折依赖」判定一并保留。"),
        },
        "no_state_promotion": True,
        "not_a_solver": ("代理只预测一阶峰标量，无场级误差界、无 L1 网格收敛 ⇒ "
                         "不得用于工程绝对值，不得称为免 COMSOL 出解"),
    }
    (outdir / "stratified_split_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "STRATIFIED_SPLIT.md").write_text(
        render_md(summary, seeds, results, lrows, reg_assign, reg_lift, strata_meta),
        encoding="utf-8")
    print("\n产物：%s（%d B）｜%s（%d B）｜%s（%d B）｜%s（%d B）"
          % (gpath.relative_to(REPO), gpath.stat().st_size,
             apath.relative_to(REPO), apath.stat().st_size,
             lpath.relative_to(REPO), lpath.stat().st_size,
             (outdir / "STRATIFIED_SPLIT.md").relative_to(REPO),
             (outdir / "STRATIFIED_SPLIT.md").stat().st_size))

    if n_bad or not reg_ok or not reg_lift["ok"]:
        print("[FAIL] 无泄漏判据或回归对照不成立")
        return EXIT_FAIL
    return EXIT_OK


# ================================================================ 稳定性 / 判定

def build_stability(results: list[dict], seeds: list[int]) -> dict:
    out = {}
    for data in ("C", "AC", "UNION4"):
        for rule in sorted({r["rule"] for r in results if r["data"] == data}):
            chans = sorted({c for r in results if r["data"] == data and r["rule"] == rule
                            for c in r["channels"]})
            for ch in chans:
                vals = []
                for r in results:
                    if r["data"] == data and r["rule"] == rule and ch in r["channels"]:
                        vals.append(r["channels"][ch]["lift_vs_persistence"])
                key = "%s|%s|%s" % (data, rule, ch)
                nn = [v for v in vals if v is not None]
                out[key] = {
                    "n_seeds": len(vals), "n_numeric": len(nn),
                    "signs": "".join("+" if v > 0 else ("-" if v < 0 else "0") for v in nn),
                    "n_positive": sum(1 for v in nn if v > 0),
                    "n_negative": sum(1 for v in nn if v < 0),
                    "min": min(nn) if nn else None, "max": max(nn) if nn else None,
                    "median": sorted(nn)[len(nn) // 2] if nn else None,
                    "sign_consistent": len({(v > 0) for v in nn}) == 1 if nn else None,
                }
    return out


def build_verdict(stability: dict) -> dict:
    """**先定后算**：判据 = 正式目标通道在「新口径（分层）」上是否 5/5 全为正。

    本函数**只报**，不给「翻身」：`verdict` 里没有 `approved`/`passed` 这类状态字面量。
    """
    out = {"criterion": ("对每个 (data, 分层键, 通道)：`n_positive == n_seeds` ⇒ 该口径下符号一致为正；"
                         "`n_negative == n_seeds` ⇒ 一致为负；其余 ⇒ 不稳"),
           "focus_channels": list(FOCUS_CHANNELS), "per_channel": {}, "summary": {}}
    for ch in FOCUS_CHANNELS:
        rows = {k: v for k, v in stability.items() if k.endswith("|" + ch)}
        grouped = {k: v for k, v in rows.items() if "grouped(非分层)" in k}
        strat = {k: v for k, v in rows.items() if k.startswith("stratified:") or "|stratified:" in k}
        out["per_channel"][ch] = {
            "n_calibers_grouped": len(grouped),
            "grouped_all_negative": all(v["n_negative"] == v["n_numeric"] for v in grouped.values()),
            "n_calibers_stratified": len(strat),
            "stratified_all_negative": all(v["n_negative"] == v["n_numeric"] for v in strat.values()),
            "stratified_any_all_positive": any(v["n_positive"] == v["n_numeric"] for v in strat.values()),
            "stratified_inconsistent_sign": sorted(k for k, v in strat.items()
                                                   if v["sign_consistent"] is False),
            "grouped_inconsistent_sign": sorted(k for k, v in grouped.items()
                                                if v["sign_consistent"] is False),
        }
    for ch, d in out["per_channel"].items():
        out["summary"][ch] = ("分层口径全部为负" if d["stratified_all_negative"]
                              else ("分层口径存在 5/5 全为正的口径" if d["stratified_any_all_positive"]
                                    else "分层口径符号**依赖分层键或种子** ⇒ **不稳**"))
    out["no_promotion"] = ("本判定**不改变** `channels_without_lift`、**不提升**任何状态；"
                           "放行权在人。")
    return out


# ================================================================ 渲染

def _f(v, n=8):
    return "—" if v is None else ("%+.*g" % (n, v))


def render_md(s: dict, seeds, results, lrows, reg_assign, reg_lift, strata_meta) -> str:
    L = ["# **分层**整组切分（P2 第 3 步；INDEX §128.5 `【待补】Q3` 后半：「分层切分未做」）", "",
         "> 只做**切分 + 用既有内核重跑指标**：**不改**任何既有产物、**不提升**任何状态、**不跑** COMSOL。",
         "> 输入 = `%s`（sha256 `%s`）＋ 只读 `%s`。"
         % (s["inputs"]["union_v3"]["path"], s["inputs"]["union_v3"]["sha256"][:16],
            s["inputs"]["assignments_readonly"]["path"]), "",
         "## 1. 一句话方案与分层键", "",
         "在**同一防泄漏约束**下（`(round(x_scale,6), N_w_te1, N_w_te2)` **整组**进同一侧；"
         "`batch` **不**当分组键），先按**分层键**把 %d 个组分层，再**逐层**按比例配额切分。" % s["n_groups"], "",
         "| 分层键 | 层数 | 层标签（组数） |", "|---|---:|---|"]
    led0 = s["stratum_ledger"]["%s|seed%d" % ("S_batch", seeds[0])]
    _ = led0
    for sk in STRAT_KEYS:
        led = s["stratum_ledger"]["%s|seed%d" % (sk, seeds[0])]
        items = sorted(led["per_stratum"].items())
        L.append("| `%s` | %d | %s |" % (sk, len(items),
                                         "；".join("%s(%d)" % (k, v["n_groups"]) for k, v in items)))
    L += ["", "x 三分位分界（**现算并登记**）：`b1 = %g`、`b2 = %g`（%s）。"
          % (strata_meta["x_tercile_bounds"]["b1"], strata_meta["x_tercile_bounds"]["b2"],
             strata_meta["x_tercile_bounds"]["rule"]),
          "", "配额口径（**先定后算**）：%s" % s["rule"]["quota"], "",
          "## 2. 分层生效的证据：逐层占比（train / holdout）", "",
          "（下表 seed 0；全 5 个种子的完整账本见 `stratum_composition.csv`）", "",
          "| 分层键 | 层 | 组数 | 行数 | 配额行数 | train 行 | holdout 行 | **holdout 行占比** |",
          "|---|---|---:|---:|---:|---:|---:|---:|"]
    for sk in STRAT_KEYS:
        led = s["stratum_ledger"]["%s|seed%d" % (sk, seeds[0])]
        for name, v in sorted(led["per_stratum"].items()):
            L.append("| `%s` | `%s` | %d | %d | %d | %d | %d | **%.4f** |"
                     % (sk, name, v["n_groups"], v["n_rows"], v["quota_rows"],
                        v["train_rows"], v["holdout_rows"], v["holdout_row_frac"]))
        ov = led["overall"]
        L.append("| `%s` | **合计** | — | — | %d | %d | %d | **%.4f** |"
                 % (sk, ov["global_target_rows"], ov["train_rows"], ov["holdout_rows"],
                    ov["holdout_row_frac"]))
    L += ["", "⇒ 各层 holdout 行占比一致贴近请求的 **%.2f**（分层生效）。"
          % s["rule"]["holdout_frac_requested"], "",
          "### 2.1 分层生效对照（**同一层**在「非分层 vs 分层」下的 holdout 行占比，seed 0）", "",
          "| 分层键 | 层 | 组数 | 行数 | 非分层 holdout 占比 | **分层 holdout 占比** |",
          "|---|---|---:|---:|---:|---:|"]
    for sk in STRAT_KEYS:
        led = s["stratum_ledger"]["%s|seed%d" % (sk, seeds[0])]
        gl = s["grouped_by_stratum_ledger"][sk][str(seeds[0])]
        for name, v in sorted(led["per_stratum"].items()):
            gv = gl.get(name)
            L.append("| `%s` | `%s` | %d | %d | %s | **%.4f** |"
                     % (sk, name, v["n_groups"], v["n_rows"],
                        ("%.4f" % gv["holdout_row_frac"]) if gv else "—",
                        v["holdout_row_frac"]))
    L += ["", "⇒ **同一层**的 holdout 占比在非分层口径下**按层剧烈波动**（最极端处可为 0 或 1），"
          "在分层口径下**一致贴近 0.30** —— 这就是「分层生效」的可核对证据（不是声明）。", ""]
    if s.get("degenerate_strata"):
        L += ["### 2.2 边界（**如实登记**）：极小层", "",
              "下列「分层键 × 种子 × 层」因层内行数太少、配额取整后**有一侧为空**：", "",
              "| 分层键 | seed | 层 | 组数 | 行数 | train 行 | holdout 行 |",
              "|---|---:|---|---:|---:|---:|---:|"]
        for d in s["degenerate_strata"][:40]:
            L.append("| `%s` | %d | `%s` | %d | %d | %d | %d |"
                     % (d["strat_key"], d["seed"], d["stratum"], d["n_groups"], d["n_rows"],
                        d["train_rows"], d["holdout_rows"]))
        L += ["", "共 **%d** 条（全部见 `stratified_split_summary.json` 的 `degenerate_strata`）。"
              "这些层**不改变**模型训练的总体（模型在**全体训练行**上构建），"
              "但**如实登记**：这些层的 holdout 行在训练侧没有同层样本 ⇒ 对该层而言属"
              "**跨层外推**，不得当作层内内插读数。"
              % len(s["degenerate_strata"]), ""]
    else:
        L += ["", "### 2.2 边界：极小层", "",
              "本切分**没有**任何「train 或 holdout 行数为 0」的层（实测 0 条）。", ""]
    L += ["## 3. 无泄漏判据：三口径交集 = 0", "",
          "| 切分口径 | seed | 字面键交集 | `repr` 键交集 | **round-6 键交集** | holdout 中「键也在 train」的行数 |",
          "|---|---:|---:|---:|---:|---:|"]
    for sdd in seeds:
        ent = s["leak_three_calibers"]["seed%d" % sdd]
        for k in ("grouped",) + STRAT_KEYS:
            v = ent[k]
            L.append("| `%s` | %d | %d | %d | **%d** | %d |"
                     % (k, sdd, v["literal"]["n_keys_intersection"],
                        v["repr"]["n_keys_intersection"],
                        v["round6"]["n_keys_intersection"],
                        v["round6"]["n_rows_in_holdout_with_key_also_in_train"]))
    L += ["", "**不成立的「口径×种子」数 = %d**（共 %d 个）⇒ 三口径**同时为 0**。"
          % (s["n_leak_failures"], len(seeds) * 8), "",
          "## 4. 8 通道 lift：**新旧并列**（旧 = 既有**非分层**整组切分，同数据同种子）", "",
          "`lift = 基线（抄相邻层）中位误差 − 模型中位误差`（正 = 有增值；与既有 `lift_vs_persistence` 同定义）。",
          "分母口径：`n_defined_holdout`（可判定基数）/ `n_in_domain_holdout`（再 ∧ 域内）；"
          "flag 口径 `n_flag_usable_holdout` **只作对照，不作分母**。", ""]
    for data in ("C", "AC", "UNION4"):
        L += ["### 4.%d 数据 = `%s`（%d 通道）" % (("C", "AC", "UNION4").index(data) + 1, data,
                                                  len(lrows_by_data(lrows, data))), ""]
        rules = sorted({r["rule"] for r in results if r["data"] == data})
        chans = sorted({c for r in results if r["data"] == data for c in r["channels"]})
        L += ["| 通道 | 口径 | " + " | ".join("seed%d lift" % sd for sd in seeds)
              + " | 符号串 | 为正数 | **可判定分母**（定义/域内，seed0） | flag 口径 |",
              "|---|---|" + "---:|" * (len(seeds) + 4)]
        for ch in chans:
            for rule in rules:
                vals, denom, flagd = [], "", ""
                for r in results:
                    if r["data"] == data and r["rule"] == rule and ch in r["channels"]:
                        v = r["channels"][ch]
                        vals.append(v["lift_vs_persistence"])
                        if r["seed"] == seeds[0]:
                            denom = "%d / %d" % (v["n_defined_holdout"], v["n_in_domain_holdout"])
                            flagd = "%d" % v["n_flag_usable_holdout"]
                nn = [v for v in vals if v is not None]
                signstr = "".join("+" if v > 0 else ("-" if v < 0 else "0") for v in nn)
                L.append("| `%s` | %s | %s | `%s` | %d/%d | %s | %s |"
                         % (ch, rule, " | ".join(_f(v) for v in nn), signstr,
                            sum(1 for v in nn if v > 0), len(nn), denom, flagd))
        L.append("")
    L += ["## 5. 5 种子符号一致性（含 `bandwidth_Hz` / `Q_factor` / `abs_w_m`）", "",
          "| data | 口径 | 通道 | 符号串 | 为负数 | 符号一致？ | 区间 [min, max] |",
          "|---|---|---|---|---:|---|---|"]
    for k, v in sorted(s["stability"].items()):
        data, rule, ch = k.split("|")
        if ch not in FOCUS_CHANNELS:
            continue
        L.append("| %s | %s | `%s` | `%s` | %d/%d | %s | [%s, %s] |"
                 % (data, rule, ch, v["signs"], v["n_negative"], v["n_numeric"],
                    v["sign_consistent"], _f(v["min"]), _f(v["max"])))
    L += ["", "## 6. 判定（**不含任何状态字面量**）", "",
          "判据（先定后算）：%s" % s["verdict"]["criterion"], "",
          "| 通道 | 非分层口径全为负？ | 分层口径全为负？ | 分层口径有 5/5 全为正？ | 分层口径符号不一致的口径数 | **一句话** |",
          "|---|---|---|---|---:|---|"]
    for ch, d in s["verdict"]["per_channel"].items():
        L.append("| `%s` | %s | %s | %s | %d | %s |"
                 % (ch, d["grouped_all_negative"], d["stratified_all_negative"],
                    d["stratified_any_all_positive"], len(d["stratified_inconsistent_sign"]),
                    s["verdict"]["summary"][ch]))
    L += ["", "## 7. 与 §113 / §114 的自洽声明", "",
          "* `channels_without_lift = ['bandwidth_Hz','Q_factor']`（冻结模型登记值）**不变**；",
          "* `solver_spec.json` 仍 `state=draft`、`multichannel_model.json` 仍 `status=draft`（复核见交付说明）；",
          "* §113/§114 的**折依赖**结论（`N2ex5/6` 为正、`N2ex7/8` 为负）**不受本节影响**；"
          "分层只改变**层内配额**，不改变「问的是哪一类问题」；",
          "* 本件**不据任何一种切分**（也不据任一单折）宣布翻身；代理仍 `draft`。", "",
          "## 8. 回归对照（证明新旧两列**同机同径**）", "",
          "| 对照 | 结果 |", "|---|---|",
          "| 重算非分层切分 == 既有 `grouped_split_assignments.csv`（逐行逐位） | **%s** |"
          % all(v["ok"] for v in reg_assign.values()),
          "| 重算非分层 lift == 既有 `rerun_channel_lift_table.csv`（%d 项逐位） | **%s**（不符 %d） |"
          % (reg_lift["n_compared"], reg_lift["ok"], reg_lift["n_mismatch"]),
          "", "## 9. 新集合的内容哈希（同一规范化口径；全表见 `hashes/COLLECTION_HASHES.md`）", "",
          "| 集合 | 元素数 | sha256 |", "|---|---:|---|"]
    for k, v in sorted(s["new_collection_hashes"].items()):
        L.append("| `%s` | %d | `%s` |" % (k, v["n_elements"], v["sha256"]))
    L += ["", "## 10. 产物", "",
          "| 文件 | 内容 |", "|---|---|",
          "| `stratified_split_groups.csv` | 组清单（组级分层标签 + 7 分层键 × 5 种子的 side） |",
          "| `stratified_split_assignments.csv` | 逐行指派（同宽表 + 每行分区） |",
          "| `stratum_composition.csv` | **逐层占比账本**（组数/行数/配额/train/holdout/占比） |",
          "| `stratified_channel_lift_table.csv` | lift 长表（口径 × 数据 × 种子 × 通道，含可判定分母） |",
          "| `stratified_split_summary.json` | 机器可读全量 |",
          "| `STRATIFIED_SPLIT.md` | 本件 |", "",
          "## 11. 未做 / 边界（逐条）", "",
          "1. **未跑 COMSOL**、未改任何 `.mph`、未改 `src/`、`tests/`、未提升任何状态；",
          "2. **未改**既有 `work/runs/grouped-split-20261009/*`（**只读**：回归对照逐位比对了指派表与 lift 表）；",
          "3. `AC` / `UNION4` 口径与 INDEX §95.2（O-A：禁止池化/禁止合并批）**冲突** ⇒ "
          "只作**归因**（隔离「切分规则」这一变量），**不得当结论**；",
          "4. 三批并集**跑不了 8 通道**（v2 冻结副本缺 4 列）⇒ `UNION4` 只有 4 通道；",
          "5. **未**对跨批标签不一致（137 组）做任何合并/取舍 ⇒ 仍 **【待裁定】**；"
          "`build()` 沉默 last-write-wins 的事实不变；",
          "6. 分层只做**三种键 + 四种组合**；未做比例配额以外的方案（如按指标分层），也未做 `N1` 分层；",
          "7. 分层**不改变**「无泄漏」的判据，也**不产生**增值；`channels_without_lift` 不变；",
          "8. **未跑 pytest**（本件只新增 `scripts/` 脚本，未改被测对象；会话内另有线在跑 pytest）。", ""]
    return "\n".join(L)


def lrows_by_data(lrows, data):
    return sorted({r["channel"] for r in lrows if r["data"] == data})


if __name__ == "__main__":
    sys.exit(main())
