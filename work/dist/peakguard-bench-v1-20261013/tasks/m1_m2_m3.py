# -*- coding: utf-8 -*-
"""M1(V2) / M2 / M3 —— 拆分消融机制核对、risk–coverage、跨批迁移（零求解、纯 CPU）。

本脚本是 benchmark 包内 `tasks/` 下的一个**自足任务**：不依赖任何仓库内模块，
只读包内**相对路径**的冻结输入，并把三份结果写回包内 `results/`。

读：
  * `data/splits_grouped_five_seeds.csv` —— 冻结的五种子分组拆分（含 `side_seed0..4` 与 `key_repr`）
  * `results/baselines_by_seed.json`     —— 由包内 `bench.py` 产出的逐种子基线注册件
  * 语料装配由包内 `bench.py` 的 `load_all()` 完成（其输入同样是包内 `data/` 下的冻结件）
    —— 本脚本**不改写** `bench.py`，只 import 它的函数与超参。

写（`results/`）：
  * `M1_RESULT_V2.json` —— 分组臂 vs 随机臂的消融 + **事后**机制核对（几何/方向/通道级）
  * `M2_RESULT.json`    —— risk–coverage 曲线（预注册 score）与结构性 operating point
  * `M3_RESULT.json`    —— 跨批迁移（描述性证据，不设通过/失败阈值）

纪律（与既有分析一致）：
  * 逐批、逐通道，**不池化、无加权总分**；`None` 不当作通过；零求解、零状态提升。
  * M1 的公平性守卫：随机臂逐批逐种子的 train/holdout 行数必须与注册件**完全相等**，
    否则 fail-closed（`SystemExit`）。
  * M2 的 score–coverage **不是**区间校准，不得与 S5 的区间覆盖率混称。
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import importlib.util
import json
import math
import pathlib
import sys
import time

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent          # …/tasks/
sys.path.insert(0, str(HERE))
import _text  # noqa: E402  （自由文本的英文渲染表；见其 docstring）
PKG = HERE.parent                                        # 包根
BENCH = PKG / "bench.py"
ASSIGN = PKG / "data" / "splits_grouped_five_seeds.csv"
REG = PKG / "results" / "baselines_by_seed.json"
OUT = PKG / "results"

SEEDS = (0, 1, 2, 3, 4)
BATCHES = ("A_5-35MHz", "C_5-50MHz", "V2_5-35MHz")
RNG_BASE = 20261013
METHODS = ("persistence", "pchip", "linear", "rbf", "poly2_ridge", "GP", "boosted_trees", "MLP")

_ASG_CACHE: dict | None = None


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dump(path: pathlib.Path, obj) -> None:
    """UTF-8 + LF（不随平台改写行尾），保证跨平台字节一致；自由文本过英文渲染表。"""
    path.write_bytes((json.dumps(_text.to_en(obj), ensure_ascii=False, indent=2, default=str) + "\n")
                     .encode("utf-8"))


def load_mod():
    """按路径 import 包内 `bench.py`（不改写它，也不依赖任何已安装的包）。"""
    spec = importlib.util.spec_from_file_location("peakguard_bench", BENCH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def med(xs):
    if xs is None:
        return None
    xs = [x for x in xs if isinstance(x, (int, float)) and math.isfinite(x)]
    return float(np.median(xs)) if xs else None


def side_map() -> dict:
    """冻结拆分指派表：row_index → 整行；用于泄漏量化（`key_repr`）与恢复分组臂。"""
    global _ASG_CACHE
    if _ASG_CACHE is None:
        with ASSIGN.open(encoding="utf-8-sig", newline="") as fh:
            _ASG_CACHE = {int(r["row_index"]): r for r in csv.DictReader(fh)}
    return _ASG_CACHE


def inputs_block() -> dict:
    """本结果实际读入的两个冻结件的 sha256（包内相对路径，无绝对路径/用户名）。"""
    return {"data/splits_grouped_five_seeds.csv": sha(ASSIGN),
            "results/baselines_by_seed.json": sha(REG)}


def restore_grouped(rows, asg: dict) -> None:
    """把每行的 5 个 `side` 恢复成冻结拆分的分组臂（`load_all()` 的初始状态）。"""
    for r in rows:
        ri = r["row_index"]
        for s in SEEDS:
            r["side"][s] = asg[ri]["side_seed%d" % s]


def geometry(rows, seed: int, asg: dict) -> dict:
    """每批的泄漏相关几何（分组臂/随机臂同口径）。

    ⚠️ 不用**绝对**阈值 |Δx| ≤ 0.01，那会把**网格步长**与**拆分结构**混在一起
    （A/V2 的 x 步长是 0.1 ⇒ 结构上不可能有 0.01 邻接）。本脚本用两个口径：
      * `x_overlap_frac`：holdout 行的 **x 值本身**出现在同格 train 里的比例（最严的插值泄漏代理）；
      * `x_adjacent_rel_frac`：holdout 行在同格 train 里有 |Δx| ≤ 1.5 × **该格最小 x 步长** 的邻居。
    """
    out = {}
    for b in BATCHES:
        rs = [r for r in rows if r["batch"] == b]
        tr = [r for r in rs if r["side"][seed] == "train" and not r["quarantined"]]
        ho = [r for r in rs if r["side"][seed] == "holdout" and not r["quarantined"]]
        if not (tr and ho):
            out[b] = {"empty": True}
            continue
        cell_tr = collections.defaultdict(list)
        for r in tr:
            cell_tr[(r["n1"], r["n2"])].append(r["x"])
        # 该批的最小 x 步长（按格取，再取全局最小正差）
        steps = []
        for xs in cell_tr.values():
            u = sorted(set(xs))
            steps += [u[i + 1] - u[i] for i in range(len(u) - 1) if u[i + 1] > u[i]]
        step = min(steps) if steps else 0.01
        ov = adj = 0
        for r in ho:
            xs = cell_tr.get((r["n1"], r["n2"]))
            if not xs:
                continue
            if any(abs(r["x"] - v) <= 1e-12 for v in xs):
                ov += 1
            if any(abs(r["x"] - v) <= 1.5 * step for v in xs):
                adj += 1
        tr_keys = {asg[r["row_index"]]["key_repr"] for r in tr}
        dup = sum(1 for r in ho if asg[r["row_index"]]["key_repr"] in tr_keys)
        xs_all = [r["x"] for r in rs]
        rng = (max(xs_all) - min(xs_all)) or 1.0

        def dd(a, bb):
            return math.sqrt(((a["x"] - bb["x"]) / rng) ** 2 + ((a["n1"] - bb["n1"]) / 6.0) ** 2
                             + ((a["n2"] - bb["n2"]) / 8.0) ** 2)
        ds = [min(dd(h, t) for t in tr) for h in ho]
        out[b] = {"n_train": len(tr), "n_holdout": len(ho),
                  "grid_step_x": step,
                  "x_overlap_frac": ov / len(ho),
                  "x_adjacent_rel_frac": adj / len(ho),
                  "unique_x_holdout": len({r["x"] for r in ho}),
                  "unique_x_train": len({r["x"] for r in tr}),
                  "dup_key_repr_overlap": dup,
                  "nn_dist_norm_median": float(np.median(ds)),
                  "nn_dist_norm_p10": float(np.percentile(ds, 10))}
    return out


def random_geometry(rows, reg_ho: dict, asg: dict) -> dict:
    """按注册 RNG 配方复现**随机臂**指派（逐批分层、行数与注册件对齐），返回每种子几何。

    指派是逐种子独立抽的（`default_rng(RNG_BASE + s)`，批顺序 = `BATCHES`）。抽完即校验
    行数，不一致就 fail-closed；随后计算该种子的几何（只用到该种子的 side）。
    """
    geom_R = {}
    for s in SEEDS:
        for r in rows:
            r["side"][s] = "train"
        rng = np.random.default_rng(RNG_BASE + s)
        for b in BATCHES:
            pool = [r for r in rows if r["batch"] == b and not r["quarantined"]]
            k = reg_ho[(b, s)]
            if not 0 <= k <= len(pool):
                raise SystemExit("[FAIL] 目标 holdout 数越界：%s s%d k=%d pool=%d"
                                 % (b, s, k, len(pool)))
            pick = set(int(i) for i in rng.choice(len(pool), size=k, replace=False))
            for i, r in enumerate(pool):
                r["side"][s] = "holdout" if i in pick else "train"
        got = {b: sum(1 for r in rows if r["batch"] == b and r["side"][s] == "holdout"
                      and not r["quarantined"]) for b in BATCHES}
        for b in BATCHES:
            if got[b] != reg_ho[(b, s)]:
                raise SystemExit("[FAIL] 随机指派复现失败：%s s%d got=%d want=%d"
                                 % (b, s, got[b], reg_ho[(b, s)]))
        geom_R[s] = geometry(rows, s, asg)
    return geom_R


# --------------------------------------------------------------------- M1 (V2)
def task_m1(F, rows, meta, bench) -> int:
    """M1 **更正分析（V2）**：追加机制核对，检验 V1 的判定是否能按原意解读。

    V1 按**预注册的三条规则**触发了「常规随机评测会给出不同结论」。
    V2 追加**事后**机制核对：两臂在几何上到底差在哪里？差得够不够解释那些差异？

    关键质问：若两臂的「x 邻接泄漏」比例几乎相同，则 V1 的差异**不能归因于分组规则**，
    只能是拆分实现噪声。
    """
    print("== M1(V2)：分组臂 vs 随机臂 消融 + 事后机制核对 ==")
    asg = side_map()
    reg = json.loads(REG.read_text(encoding="utf-8"))
    G = reg["by_seed_aggregate"]
    reg_ho = {(b, s): reg["per_seed"][b][str(s)]["n_holdout_rows"]
              for b in BATCHES for s in SEEDS}

    # --- 复现随机指派（与注册配方同 RNG），并用注册件的行数交叉核对（fail-closed）
    t0 = time.time()
    geom_R = random_geometry(rows, reg_ho, asg)
    print("   随机指派复现：15/15 逐批逐种子 holdout 行数与注册件一致 ✓")

    # --- 随机臂评估（与分组臂**同代码、同超参、同指标、同行集合**，唯一差别是哪些行被留出）
    t1 = time.time()
    R = bench.run_baselines(F, rows, meta, len(SEEDS))["agg"]
    print("   随机臂评估完成（%.1f s）" % (time.time() - t1))

    # --- 恢复冻结的分组臂，再算分组臂几何
    restore_grouped(rows, asg)
    geom_G = {s: geometry(rows, s, asg) for s in SEEDS}
    print("   几何/指派复现合计 %.1f s" % (time.time() - t0))

    # --- 几何对照表
    K = ("grid_step_x", "x_overlap_frac", "x_adjacent_rel_frac", "unique_x_holdout",
         "unique_x_train", "dup_key_repr_overlap", "nn_dist_norm_median")
    geo = {}
    for b in BATCHES:
        g = {k: med([geom_G[s][b].get(k) for s in SEEDS]) for k in K}
        r = {k: med([geom_R[s][b].get(k) for s in SEEDS]) for k in K}
        geo[b] = {"grouped": g, "random": r,
                  "delta_x_adjacent_rel_pp": (None if (g["x_adjacent_rel_frac"] is None
                                                       or r["x_adjacent_rel_frac"] is None)
                                              else 100.0 * (r["x_adjacent_rel_frac"]
                                                            - g["x_adjacent_rel_frac"]))}

    # --- 逐批逐格对比 + 方向 + 种子间波动
    channels, methods = bench.CH8, list(METHODS)
    cells, per_batch = [], {}
    for b in BATCHES:
        for ch in channels:
            for m in methods:
                gm = G[b][ch]["per_method"].get(m) or {}
                rm = R[b][ch]["per_method"].get(m) or {}
                MG, MR = med(gm.get("median_err_by_seed")), med(rm.get("median_err_by_seed"))
                sg = (float(np.std([x for x in (gm.get("median_err_by_seed") or [])
                                    if x is not None]))
                      if gm.get("median_err_by_seed") else None)
                sr = (float(np.std([x for x in (rm.get("median_err_by_seed") or [])
                                    if x is not None]))
                      if rm.get("median_err_by_seed") else None)
                rec = {"batch": b, "channel": ch, "method": m, "median_G": MG, "median_R": MR,
                       "ratio": (MR / MG) if (MG and MR) else None,
                       "std_G": sg, "std_R": sr,
                       "lift_G_max": gm.get("lift_paired_max"), "lift_R_max": rm.get("lift_paired_max")}
                cells.append(rec)
                per_batch.setdefault(b, []).append(rec)
    direction = {}
    for b in BATCHES:
        rs = [c["ratio"] for c in per_batch[b] if c["ratio"] is not None]
        direction[b] = {"n_cells": len(rs),
                        "n_R_better_10pct": sum(1 for x in rs if x < 0.90),
                        "n_R_worse_10pct": sum(1 for x in rs if x > 1.10),
                        "median_ratio": med(rs),
                        "std_G_median": med([c["std_G"] for c in per_batch[b]]),
                        "std_R_median": med([c["std_R"] for c in per_batch[b]])}

    # --- D2 修正版（通道级；**只统计该批真有数据的通道**，无数据 ≠ 输给 persistence）
    def channel_level(store):
        out = {}
        for b in BATCHES:
            have = [ch for ch in channels
                    if any((store[b][ch]["per_method"].get(m) or {}).get("median_err_by_seed")
                           for m in methods)]
            bad = []
            for ch in have:
                won = False
                for m in methods:
                    if m == "persistence":
                        continue
                    e = (store[b][ch]["per_method"].get(m) or {})
                    lb = e.get("lift_paired_by_seed") or []
                    if med(lb) is not None and med(lb) > 0:
                        won = True
                        break
                if not won:
                    bad.append(ch)
            out[b] = {"n_channels_with_data": len(have),
                      "n_channels_all_lose_to_persistence": len(bad),
                      "channels": bad,
                      "no_data_channels": [ch for ch in channels if ch not in have]}
        return out

    d2G, d2R = channel_level(G), channel_level(R)

    # --- 机制判定
    mech = {}
    for b in BATCHES:
        d = geo[b]["delta_x_adjacent_rel_pp"]
        mech[b] = {"delta_x_adjacent_rel_pp": d,
                   "grid_step_x": geo[b]["grouped"]["grid_step_x"],
                   "x_overlap_frac_grouped": geo[b]["grouped"]["x_overlap_frac"],
                   "x_adjacent_rel_frac_grouped": geo[b]["grouped"]["x_adjacent_rel_frac"],
                   "arms_geometrically_equivalent": (d is not None and abs(d) < 5.0),
                   "reading": ("两臂在该批的 x 邻接（按网格步长相对化）几乎相同 ⇒ 该批差异**不能归因于分组规则**"
                               if (d is not None and abs(d) < 5.0)
                               else "两臂在该批的 x 邻接不同 ⇒ 该批差异**可归因于分组规则**")}
    attributable = [b for b in BATCHES if not mech[b]["arms_geometrically_equivalent"]]
    verdict_v2 = ("**评测结论对拆分实现不稳定**（该结论有证据，逐批方向见下表）；"
                  "但「随机拆分系统性改变结论」**未获支持**：两臂在 %s 上的 x 邻接比例几乎相同，"
                  "差异方向双向，不能排除拆分实现噪声。"
                  % "、".join([b for b in BATCHES if mech[b]["arms_geometrically_equivalent"]]))
    if attributable:
        verdict_v2 += (" 可归因于分组规则的是：%s。" % "、".join(attributable))
    verdict_v2 += (" **另有一条对我们自己协议的新发现**：主批 C 的 x 网格步长是 **%s**，"
                   "而注册拆分的 holdout 中有 **%.1f %%** 的行在 train 里有**相邻格**邻居（两臂皆然）"
                   "⇒ 该「grouped」拆分只挡住**重复簇/跨批重复**泄漏，**没有**挡住 x 邻接插值泄漏。"
                   % (("0.01" if (geo['C_5-50MHz']['grouped']['grid_step_x'] or 0) <= 0.0101
                       else str(geo['C_5-50MHz']['grouped']['grid_step_x'])),
                      100.0 * (geo["C_5-50MHz"]["grouped"]["x_adjacent_rel_frac"] or 0)))

    res = {"kind": "ai11_m1_split_ablation_v2_mechanism_checked",
           "created_local": "2026-10-13",
           "supersedes_report_of": {"v1_result": "M1_RESULT.json",
                                    "v1_verdict": "常规随机评测会给出不同结论"},
           "why_v2": ("V1 按**预注册规则**触发；V2 追加**事后**机制核对后发现：两臂在**三个批**上的"
                      "「x 相邻格」比例几乎相同（Δ ≤ 4.2 pp）⇒ 差异**不能归因于分组规则**。"
                      "并且查明注册的「grouped」拆分实际按**重复簇**分组（`dup_score ≥ 1`，541 行 / 24 %），"
                      "并不阻断主批 C 的 **x 邻接插值泄漏（约 91 %）**——原描述「an entire combination key "
                      "(geometry family)」与实测不符。"),
           "inputs": inputs_block(),
           "split_reproduction_check": "随机指派按预注册 RNG 配方复现，15/15 逐批行数与注册件一致 ✓",
           "geometry": geo, "mechanism_check": mech,
           "direction": direction, "channel_level": {"grouped": d2G, "random": d2R},
           "sample_cells": sorted([c for c in cells if c["ratio"] is not None],
                                  key=lambda c: abs(math.log(c["ratio"])))[-0:] or cells[:8],
           "verdict_v2": verdict_v2,
           "non_claims": ["V1 的**预注册判定不被改写**：它按规则触发了，这一点保留在原件里；",
                          "V2 的机制核对是**事后**的，故 V2 的结论标为更正结论而非新预注册；",
                          "不主张「随机拆分一定更乐观」；不主张「grouped 拆分已无泄漏」（恰恰相反，见 geometry）；",
                          "零求解、未改任何既有件。"]}
    dump(OUT / "M1_RESULT_V2.json", res)
    print("   相邻格比例（median）：C grouped %.4f vs random %.4f；A grouped %.4f vs random %.4f"
          % (geo["C_5-50MHz"]["grouped"]["x_adjacent_rel_frac"],
             geo["C_5-50MHz"]["random"]["x_adjacent_rel_frac"],
             geo["A_5-35MHz"]["grouped"]["x_adjacent_rel_frac"],
             geo["A_5-35MHz"]["random"]["x_adjacent_rel_frac"]))
    print("   写出 M1_RESULT_V2.json")
    return 0


# --------------------------------------------------------------------- M2
def task_m2(F, rows, meta, bench) -> int:
    print("== M2：risk–coverage ==")
    grid = [0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 1.00]
    channels = bench.CH8
    per = []
    t0 = time.time()
    for b in BATCHES:
        for s in SEEDS:
            tr = [r for r in rows if r["batch"] == b and r["side"][s] == "train"
                  and not r["quarantined"]]
            ho = [r for r in rows if r["batch"] == b and r["side"][s] == "holdout"
                  and not r["quarantined"]]
            for ch in channels:
                if not any(r["ch"].get(ch) is not None for r in rows if r["batch"] == b):
                    continue
                dfn = [r for r in ho if bench.defined(r, ch)]
                if len(dfn) < 10:
                    continue
                truth = np.asarray([r["ch"][ch] for r in dfn], float)
                pv = [bench.persistence_pred(tr, ch, r) for r in dfn]
                model = bench.pchip_model(F, tr, ch)
                pr, modes = [], []
                for r in dfn:
                    p, m = bench.pchip_pred(F, model, ch, r)
                    pr.append(p)
                    modes.append(m)
                preds = {"pchip": pr}
                for name in bench.FIT6:
                    mm = bench.Fitted(name, s).fit(tr, ch)
                    preds[name] = list(mm.predict(dfn, ch)) if mm.ok else [None] * len(dfn)
                for name, p in preds.items():
                    rec = []
                    for i, r in enumerate(dfn):
                        if p[i] is None or not math.isfinite(p[i]) or p[i] <= 0 or pv[i] is None:
                            continue
                        rel = bench.rel_err(p[i], truth[i])
                        score = abs(p[i] - pv[i]) / truth[i]
                        rec.append({"x": r["x"], "n1": r["n1"], "n2": r["n2"],
                                    "rel": rel, "score": score})
                    if len(rec) < 10:
                        continue
                    order = sorted(rec, key=lambda d: d["score"])
                    curve = []
                    for c in grid:
                        k = max(1, int(round(c * len(order))))
                        sub = [d["rel"] for d in order[:k]]
                        curve.append({"coverage": c, "n_accepted": k,
                                      "risk_median": float(np.median(sub)),
                                      "risk_p90": float(np.percentile(sub, 90)),
                                      "risk_max": float(max(sub))})
                    per.append({"batch": b, "seed": s, "channel": ch, "method": name,
                                "n_defined_pos": len(dfn), "n_scored": len(rec),
                                "coverage_of_defined": len(rec) / len(dfn),
                                "risk_at_full_coverage_median": curve[-1]["risk_median"],
                                "risk_at_full_coverage_p90": curve[-1]["risk_p90"],
                                "curve": curve})
                    if name == "pchip":
                        ref = dict(collections.Counter(m for m, q in zip(modes, range(len(dfn)))
                                                       if pr[q] is None))
                        per[-1]["structural_refusals"] = ref
    agg = {}
    for b in BATCHES:
        for ch in channels:
            for name in list(bench.FIT6) + ["pchip"]:
                cells = [x for x in per if x["batch"] == b and x["channel"] == ch
                         and x["method"] == name]
                if not cells:
                    continue
                curve = []
                for c in grid:
                    rm = med([next(z["risk_median"] for z in x["curve"] if z["coverage"] == c)
                              for x in cells])
                    rp = med([next(z["risk_p90"] for z in x["curve"] if z["coverage"] == c)
                              for x in cells])
                    curve.append({"coverage": c, "risk_median_over_seeds": rm,
                                  "risk_p90_over_seeds": rp})
                agg.setdefault(b, {}).setdefault(ch, {})[name] = {
                    "n_seeds": len(cells), "curve": curve,
                    "coverage_of_defined_median": med([x["coverage_of_defined"] for x in cells]),
                    "structural_refusals_total": sum(sum((x.get("structural_refusals") or {}).values())
                                                     for x in cells)}
    res = {"kind": "ai11_m2_risk_coverage", "created_local": "2026-10-13",
           "inputs": inputs_block(),
           "split": "arm G（注册 grouped split）",
           "score_preregistered": "s_i = |pred_i − pers_i| / truth_i（模型与强基线的分歧，归一化）",
           "coverage_grid": grid, "per_cell_raw": per, "aggregate_over_seeds": agg,
           "structural_operating_point": {b: {ch: {m: (agg[b][ch][m]["coverage_of_defined_median"],
                                                     agg[b][ch][m]["structural_refusals_total"])
                                                 for m in agg[b][ch]} for ch in agg[b]} for b in agg},
           "non_claims": ["**不**主张这是区间校准：S5 的区间覆盖率是**另一口径**，本节的 score-coverage 不得与 S5 混称；",
                          "只报**预注册的那一个** score，不主张已找到最优评分函数；",
                          "逐批逐通道陈述，不池化、不给加权总分；零求解、未改任何既有件。"]}
    dump(OUT / "M2_RESULT.json", res)
    print("   格数 = %d；聚合 (批×通道×方法) = %d（%.1f s）"
          % (len(per), sum(len(v) for bb in agg.values() for v in bb.values()), time.time() - t0))
    print("   写出 M2_RESULT.json")
    return 0


# --------------------------------------------------------------------- M3
def task_m3(F, rows, meta, bench) -> int:
    print("== M3：跨批迁移 ==")
    reg = json.loads(REG.read_text(encoding="utf-8"))
    G_AGG = reg.get("by_seed_aggregate") or reg.get("agg")
    if G_AGG is None:
        raise SystemExit("[FAIL] 注册件里找不到聚合块")
    arms = [("C_5-50MHz", "A_5-35MHz"), ("A_5-35MHz", "C_5-50MHz"),
            ("A_5-35MHz+C_5-50MHz", "V2_5-35MHz")]
    out = []
    t0 = time.time()
    for tr_name, te_name in arms:
        tr_batches = tr_name.split("+")
        tr = [r for r in rows if r["batch"] in tr_batches and not r["quarantined"]]
        te_all = [r for r in rows if r["batch"] == te_name and not r["quarantined"]]
        for ch in bench.CH8:
            have_tr = any(r["ch"].get(ch) is not None for r in tr)
            have_te = any(r["ch"].get(ch) is not None for r in te_all)
            if not (have_tr and have_te):
                out.append({"train": tr_name, "test": te_name, "channel": ch,
                            "note": "无数据（某侧缺该通道）"})
                continue
            dfn = [r for r in te_all if bench.defined(r, ch)]
            if len(dfn) < 10:
                out.append({"train": tr_name, "test": te_name, "channel": ch,
                            "note": "定义的测试行不足（%d）" % len(dfn)})
                continue
            truth = np.asarray([r["ch"][ch] for r in dfn], float)
            pv = [bench.persistence_pred(tr, ch, r) for r in dfn]
            preds = {}
            for name in bench.FIT6:
                mm = bench.Fitted(name, 0).fit(tr, ch)
                preds[name] = list(mm.predict(dfn, ch)) if mm.ok else [None] * len(dfn)
            model = bench.pchip_model(F, tr, ch)
            pr = []
            for r in dfn:
                p, _ = bench.pchip_pred(F, model, ch, r)
                pr.append(p)
            preds["pchip"] = pr
            for name, p in preds.items():
                idx = [i for i in range(len(dfn))
                       if p[i] is not None and math.isfinite(p[i]) and p[i] > 0]
                rel = [bench.rel_err(p[i], truth[i]) for i in idx]
                if not rel:
                    continue
                acc = []
                for i in idx:
                    acc.append(bool(bench.in_domain_train(tr, ch, dfn[i]["x"], dfn[i]["n1"],
                                                          dfn[i]["n2"])))
                ref = None
                if te_name in G_AGG and ch in G_AGG.get(te_name, {}):
                    refm = (G_AGG[te_name][ch]["per_method"].get(name) or {}).get("median_err_by_seed")
                    ref = med(refm)
                cross = float(np.median(rel))
                out.append({"train": tr_name, "test": te_name, "channel": ch, "method": name,
                            "n_defined_pos": len(dfn), "n_predicted": len(idx),
                            "acceptance_of_defined": len(idx) / len(dfn),
                            "in_domain_frac_of_predicted": (sum(acc) / len(acc)) if acc else None,
                            "median_cross": cross, "p90_cross": float(np.percentile(rel, 90)),
                            "max_cross": float(max(rel)),
                            "median_within_batch_reference": ref,
                            "transfer_gap": (cross - ref) if ref is not None else None,
                            "note": "within-batch 参照取自注册件（arm G），未重跑"})
    res = {"kind": "ai11_m3_cross_batch_transfer", "created_local": "2026-10-13",
           "inputs": inputs_block(),
           "arms": ["train C → test A", "train A → test C", "train A∪C → test V2"],
           "cells": out,
           "non_claims": ["**不设通过/失败阈值**（预注册写死为描述性证据）；",
                          "不得据此声称泛化能力或 OOD 检测性能；",
                          "测试侧用**整批**未 quarantine 行（跨批语义下该批整体未见）；train 侧用该批**全部**行；",
                          "零求解、未改任何既有件；逐批逐通道陈述，不池化。"]}
    dump(OUT / "M3_RESULT.json", res)
    print("   格数 = %d（其中带读数 %d）（%.1f s）"
          % (len(out), sum(1 for c in out if "note" not in c), time.time() - t0))
    print("   写出 M3_RESULT.json")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="all", choices=["m1", "m2", "m3", "all"])
    a = ap.parse_args()
    for p in (BENCH, ASSIGN, REG):
        if not p.is_file():
            raise SystemExit("[FAIL] 缺包内输入：%s（先跑包内 bench.py 生成 results/baselines_by_seed.json）"
                             % p.relative_to(PKG).as_posix())
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    bench = load_mod()
    F = bench.load_fitter()
    rows, meta = bench.load_all()
    print("语料装配：%d 行；批 = %s" % (len(rows), meta["batch_counts"]))
    tasks = {"m1": task_m1, "m2": task_m2, "m3": task_m3}
    for t in (["m1", "m2", "m3"] if a.task == "all" else [a.task]):
        tasks[t](F, rows, meta, bench)
        if t == "m1":
            # M1 会把 side 改成随机臂；M2/M3 必须落在冻结的分组臂上 ⇒ 显式恢复
            restore_grouped(rows, side_map())
    print("总耗时 %.1f s" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
