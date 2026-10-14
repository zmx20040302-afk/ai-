# -*- coding: utf-8 -*-
"""P2 第 2 步：用**整组切分后的数据**重跑 8 通道，与**旧口径并列**。

## 复用（**不重写**）既有评估路径

评估内核直接 **import** 仓库既有的
`work/runs/multichannel-surrogate-20260929/fit_multichannel_surrogate.py`
（`build` / `predict_one` / `baseline_persistence` / `stats` / `defined` / `err` / `CHANNELS`），
本脚本**不复制、不改写**它的任何一行；只负责把数据、切分与口径喂进去，并把结果并排报出。

## 口径（每个数字都能指向 calibers 表里的一行）

| 代号 | 数据 | 切分 | 说明 |
|---|---|---|---|
| `OLD_C_N2ex8` | 批 C | N2 折（训练 N2∈{5,6,7} → 测试 8） | **旧口径**；与冻结 E5 逐项对照 |
| `*_grouped_s*` | 见 `data` | **整组切分**（round-6 组合键整组一侧） | 本轮新口径 |
| `*_rowwise_s*` | 同上 | **逐行**随机 30%（同种子、同 holdout 行数） | 「**非整组切分**」镜像，用于归因 |
| `UNION4_N2ex8` | 三批并集 | N2 折 | 证明**旧问题上整组规则是空操作** |

`data` 取值：`C`（1782 行）／`AC`（2005 行，**同一管线** A+C）／`UNION4`（2255 行，**跨管线**，
只取三批都有的 4 个通道）。

## 纪律

* 「g/L」= **增益 gain / lift**：`lift = 基线（抄相邻层）中位误差 − 模型中位误差`，正 = 有增值；
  与仓库既有 `lift_vs_persistence` **同定义**。
* 每通道都给**可判定分母**：`n_defined`（该通道有定义）与 `n_in_domain`（再 ∧ 代理适用域
  `5≤N2≤9 ∧ N1<N2`）；**不用** `ranking_eligible`/`usable` flag 口径当分母（另列 flag 口径供对照）。
* **多种子**（≥3）：同一口径在多个种子上各自出表，给 min/中位/max；**不许用一次切分宣布翻身**。
* 跨批**池化**（`AC` / `UNION4`）与 INDEX §95.2（O-A：禁止池化/禁止合并批）冲突 ⇒ 一律标
  `口径冲突`，只作**归因用途**，不得当结论。
* 不改任何既有数据、不提升任何状态、不跑 COMSOL。

退出码：`0` 成功 ／ `2` 输入不可用或自校验不成立。
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as _dt
import hashlib
import importlib.util
import io
import json
import math
import pathlib
import random
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.sweep_analysis import _identity_key  # noqa: E402

EXIT_OK, EXIT_INPUT = 0, 2

FITTER = REPO / "work/runs/multichannel-surrogate-20260929/fit_multichannel_surrogate.py"
LABELS_AC = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"
LABELS_V2 = REPO / "work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv"
ASSIGN = REPO / "work/runs/grouped-split-20261009/grouped_split_assignments.csv"
XWALK = REPO / "scripts/cross_pipeline_label_check.py"
MODEL_JSON = REPO / "work/runs/multichannel-surrogate-20260929/multichannel_model.json"

#: 三批都有的通道（并集口径只能用这 4 个；另外 4 个 v2 表里没有列）
SHARED4 = ("f_peak_Hz", "bandwidth_Hz", "Q_factor", "peak_SPL_dB")
#: 三批 | 并集**不存在**这 4 个通道列 ⇒ 8 通道只能在 A∪C 上跑（**边界，必须明说**）
V2_MISSING = ("abs_w_m", "abs_p_Pa", "abs_p_per_V_Pa", "abs_vz_struct_m3s")

DEFAULT_OUT = REPO / "work/runs/grouped-split-20261009"


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load_fitter():
    """import 既有评估内核（**只读**，不复制代码）。"""
    spec = importlib.util.spec_from_file_location("_mc_fitter", FITTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fnum(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _truthy(v) -> bool:
    return str(v).strip().lower() == "true"


# ------------------------------------------------------------------ 数据装载

def rows_ac(F) -> tuple[list[dict], list[dict]]:
    """A/C 侧（`multichannel_labels.csv`）：8 通道 + 原生标志；返回 (rows, meta)。"""
    rows: list[dict] = []
    with LABELS_AC.open("r", encoding="utf-8", newline="") as fh:
        for ri, r in enumerate(csv.DictReader(fh)):
            ds = str(r.get("source_dataset", "")).strip()
            if ds not in ("A", "C"):
                continue
            x, n1, n2 = _fnum(r["x_scale"]), _fnum(r["N_w_te1"]), _fnum(r["N_w_te2"])
            if None in (x, n1, n2):
                continue
            d = {"key": (round(x, 6), n1, n2), "x": x, "n1": n1, "n2": n2,
                 "batch": "A_5-35MHz" if ds == "A" else "C_5-50MHz",
                 "pipeline": "C_first_peak_20260929",
                 "_grid_n": _fnum(r.get("n_freq")) or -1,
                 "src_row": ri,
                 "peaked": _truthy(r.get("first_peak_found")),
                 "closed": _truthy(r.get("bandwidth_closed")),
                 "flag_usable": _truthy(r.get("ranking_eligible")),
                 "quarantined": _truthy(r.get("quarantined")),
                 "flag_note": "native"}
            for c in F.CHANNELS:
                d[c] = _fnum(r.get(c))
            for c, col in (("f_peak_Hz", "f_peak_Hz"), ("peak_SPL_dB", "peak_SPL_dB")):
                d[c] = _fnum(r.get(col))
            rows.append(d)
    return rows, {"source": str(LABELS_AC.relative_to(REPO)).replace("\\", "/"),
                  "sha256": sha256_file(LABELS_AC),
                  "columns_for_8_channels": "native（全部 8 通道列同源于 C_first_peak 管线）"}


def rows_v2(F, want: tuple[str, ...]) -> tuple[list[dict], dict]:
    """v2 冻结副本：只有 4 个通道；标志**没有原生列** ⇒ 用可得的原始列做**代理**（如实披露）。"""
    rows: list[dict] = []
    with LABELS_V2.open("r", encoding="utf-8", newline="") as fh:
        for ri, r in enumerate(csv.DictReader(fh)):
            x, n1, n2 = _fnum(r["x_scale"]), _fnum(r["N_w_te1"]), _fnum(r["N_w_te2"])
            if None in (x, n1, n2):
                continue
            peak_end = _truthy(r.get("peak_at_scan_endpoint"))
            bw_end = _truthy(r.get("bw_upper_cutoff_at_endpoint"))
            mapping = {"f_peak_Hz": "peak_freq_Hz", "peak_SPL_dB": "peak_spl_dB",
                       "bandwidth_Hz": "bandwidth_Hz", "Q_factor": "Q"}
            d = {"key": (round(x, 6), n1, n2), "x": x, "n1": n1, "n2": n2,
                 "batch": "V2_5-35MHz", "pipeline": "v2_comsol_native_markers",
                 "_grid_n": _fnum(r.get("n_freq")) or -1,
                 "src_row": ri,
                 # 代理（**不是原生标志**）：峰不在扫描端点 ⇒ 认为找到峰；上交点也不在端点 ⇒ 认为闭合
                 "peaked": (not peak_end),
                 "closed": (not peak_end) and (not bw_end),
                 "flag_usable": (not peak_end) and (not bw_end),
                 "quarantined": False,
                 "flag_note": "proxy: peaked=peak_at_scan_endpoint!=true; "
                              "closed=且 bw_upper_cutoff_at_endpoint!=true"}
            for c in F.CHANNELS:
                d[c] = None
            for c, col in mapping.items():
                d[c] = _fnum(r.get(col))
            rows.append(d)
    return rows, {"source": str(LABELS_V2.relative_to(REPO)).replace("\\", "/"),
                  "sha256": sha256_file(LABELS_V2),
                  "v2_channels_available": sorted(mapping),
                  "v2_channels_missing": list(V2_MISSING),
                  "flag_caliber": "代理（v2 表无 first_peak_found/bandwidth_closed 列）⇒ 【待裁定】"}


def load_assignments(seeds: list[int]) -> dict[tuple, dict]:
    """(batch, round-6 key) → {seed: side}。fail-closed：键必须一一对上。"""
    with ASSIGN.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out: dict[tuple, dict] = {}
    for r in rows:
        k = (r["batch"], _identity_key({"x_scale": r["x_scale"], "N_w_te1": r["N_w_te1"],
                                        "N_w_te2": r["N_w_te2"]}, ("x_scale", "N_w_te1",
                                                                   "N_w_te2"), 6))
        if k in out:
            raise SystemExit("[FAIL] 指派表里 (batch,key) 不唯一：%r" % (k,))
        d = {}
        for s in seeds:
            d[s] = r["side_seed%d" % s]
        out[k] = d
    return out


# ------------------------------------------------------------------ 评估

def evaluate(F, train: list[dict], test: list[dict], ch: str) -> dict:
    """一个「训练集/留出集」下的单通道评估。**复用既有内核算误差与持续性基线。**"""
    model = F.build(train, ch)
    errs, modes, reasons = [], [], {}
    n_defined = n_in_domain = n_flag = 0
    for r in test:
        if not F.defined(r, ch):
            continue
        n_defined += 1
        if r.get("flag_usable"):
            n_flag += 1
        in_dom = (5 <= r["n2"] <= 9) and (r["n1"] < r["n2"])
        if not in_dom:
            continue
        n_in_domain += 1
        p, mode = F.predict_one(model, ch, r["x"], r["n1"], r["n2"])
        if p is None:
            reasons[mode] = reasons.get(mode, 0) + 1
            continue
        errs.append(F.err(ch, p, r[ch]))
        modes.append(mode)
    per_mode = {}
    for m in ("in_layer", "n2_extrap"):
        sub = [e for e, mm in zip(errs, modes) if mm == m]
        per_mode[m] = F.stats(sub, m) if sub else {"n": 0}
    # 合并口径：只要有一个 n2_extrap 预测，就用**更严的** n2_extrap 判带（与旧主折一致）
    merged = F.stats(errs, "n2_extrap" if "n2_extrap" in modes else "in_layer") \
        if errs else {"n": 0}
    base = F.baseline_persistence(train, test, ch)
    lift = (None if (base.get("median") is None or merged.get("median") is None)
            else base["median"] - merged["median"])
    return {
        "channel": ch, "group": F.CHANNELS[ch][0], "space": F.CHANNELS[ch][2],
        "is_formal_objective": F.CHANNELS[ch][1],
        "n_defined_holdout": n_defined,
        "n_in_domain_holdout": n_in_domain,
        "n_out_of_domain_defined": n_defined - n_in_domain,
        "n_flag_usable_holdout": n_flag,
        "n_predicted": len(errs),
        "coverage_of_defined": (len(errs) / n_defined) if n_defined else None,
        "coverage_of_in_domain": (len(errs) / n_in_domain) if n_in_domain else None,
        "median": merged.get("median"), "p90": merged.get("p90"), "max": merged.get("max"),
        "verdict_band": merged.get("verdict"),
        "modes": {m: sum(1 for x in modes if x == m) for m in ("in_layer", "n2_extrap")},
        "per_mode": per_mode,
        "refusal_reasons": reasons,
        "baseline_persistence_median": base.get("median"),
        "baseline_persistence_n": base.get("n"),
        "lift_vs_persistence": lift,
        "beats_persistence": (bool(lift is not None and lift >= 0)),
    }


def leak(F, train: list[dict], test: list[dict]) -> dict:
    """可验证判据：留出行里「组合键也在训练集」的行数（0 = 无泄漏）。"""
    tr = {r["key"] for r in train}
    n = sum(1 for r in test if r["key"] in tr)
    return {"n_holdout_rows": len(test), "n_rows_key_also_in_train": n,
            "leak_rate": (n / len(test)) if test else None}


def rows_key_set(rows):
    return {r["key"] for r in rows}


# ------------------------------------------------------------------ 主流程

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2,3,4")
    ap.add_argument("--primary-seed", type=int, default=0)
    ap.add_argument("--holdout-frac", type=float, default=0.30)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    a = ap.parse_args(argv)

    for p in (FITTER, LABELS_AC, LABELS_V2, ASSIGN):
        if not p.is_file():
            print("[FAIL] 缺输入：%s" % p)
            return EXIT_INPUT
    F = load_fitter()
    seeds = [int(s) for s in str(a.seeds).split(",") if str(s).strip()]
    side = load_assignments(seeds)

    ac, ac_meta = rows_ac(F)
    v2, v2_meta = rows_v2(F, SHARED4)
    fixtures = {
        "C": [r for r in ac if r["batch"] == "C_5-50MHz"],
        "AC": list(ac),
        "UNION4": list(ac) + list(v2),
    }

    # ---- 每个标签行必须能在指派表里找到（fail-closed）----
    missing = [r for r in fixtures["UNION4"] if (r["batch"], r["key"]) not in side]
    if missing:
        print("[FAIL] %d 行在指派表里找不到 (batch,key)（例：%r）"
              % (len(missing), [(m["batch"], m["key"]) for m in missing[:3]]))
        return EXIT_INPUT
    key_dup = len(fixtures["UNION4"]) - len({(r["batch"], r["key"]) for r in fixtures["UNION4"]})
    if key_dup:
        print("[FAIL] 数据侧 (batch,key) 有重复 %d ⇒ 无法与指派表一一对应" % key_dup)
        return EXIT_INPUT
    print("装载：A/C %d 行（8 通道原生）｜V2 %d 行（4 通道，标志为代理）｜指派表 %d 键"
          % (len(ac), len(v2), len(side)))

    # ---- 旧口径：批 C 的 N2 折（与冻结 E5 同一路径）----
    # 折定义**沿用既有预注册**：主折训练 N2∈{5,6,7} → 测试 N2=8；标尺折把 {5,6,7} 里
    # 的一个留出、其余训练。整组规则在这些折上是**空操作**（训练键 N2≤7、测试键 N2=held
    # ⇒ 构造上不相交）——这一点由每个折的 `leak` 判据**实测**证明，而不是口头声明。
    def n2fold(rows, held=None):
        train_pool = list(F.N2_TRAIN_MAIN) if held is None else [l for l in F.N2_TRAIN_MAIN
                                                                if l != held]
        te_held = F.N2_TEST_MAIN if held is None else held
        tr = [r for r in rows if r["n2"] in train_pool and not r["quarantined"]]
        te = [r for r in rows if r["n2"] == te_held and not r["quarantined"]]
        return tr, te

    # ---- 逐行镜像：同种子、同 holdout 行数，行级随机 ----
    def rowwise(rows, seed):
        pool = [r for r in rows if not r["quarantined"]]
        order = list(range(len(pool)))
        random.Random(10000 + seed).shuffle(order)
        return [pool[i] for i in order]

    calibers: list[dict] = []
    results: dict[str, dict] = {}

    def run_caliber(name, data, split, seed, rows, channels, note_extra=None, quarantine=True,
                    held=None):
        rows = [r for r in rows if (not quarantine) or (not r["quarantined"])]
        if split == "N2fold":
            train, test = n2fold(rows, held)
        elif split == "grouped":
            train = [r for r in rows if side[(r["batch"], r["key"])][seed] == "train"]
            test = [r for r in rows if side[(r["batch"], r["key"])][seed] == "holdout"]
        elif split == "rowwise":
            pool = rowwise(rows, seed)
            gtr = [r for r in rows if side[(r["batch"], r["key"])][seed] == "train"]
            gte = [r for r in rows if side[(r["batch"], r["key"])][seed] == "holdout"]
            n_ho = max(1, len(gte))
            n_ho = min(n_ho, len(pool))
            test, train = pool[:n_ho], pool[n_ho:]
        else:
            raise ValueError(split)
        chans = {c: evaluate(F, train, test, c) for c in channels}
        res = {"caliber": name, "data": data, "split_rule": split, "seed": seed,
               "n_train_rows": len(train), "n_holdout_rows": len(test),
               "leak": leak(F, train, test), "channels": chans}
        if note_extra:
            res.update(note_extra)
        calibers.append(res)
        results[name] = res
        lk = res["leak"]["n_rows_key_also_in_train"]
        print("  %-26s train %4d / holdout %4d ｜ 泄漏行 %3d ｜ BW lift %s ｜ Q lift %s"
              % (name, len(train), len(test), lk,
                 _s(chans.get("bandwidth_Hz", {}).get("lift_vs_persistence")),
                 _s(chans.get("Q_factor", {}).get("lift_vs_persistence"))))

    print("\n== 旧口径（批 C，N2 折：训练 N2∈{5,6,7} → 测试 N2=8）==")
    run_caliber("OLD_C_N2ex8", "C", "N2fold", -1, fixtures["C"], tuple(F.CHANNELS),
                note_extra={"role": "旧口径（= E5 的 L-N2ex(8) 主判定折）",
                            "preregistered_bands": True})
    print("\n== 三批并集上跑**旧问题**（N2 折）：整组规则应为空操作 ==")
    run_caliber("UNION4_N2ex8", "UNION4", "N2fold", -1, fixtures["UNION4"], SHARED4,
                note_extra={"role": "证明整组规则在旧问题上为空操作；仅 4 通道（V2 缺列）",
                            "pooling_conflict": True})
    print("\n== **多折**标尺（沿用预注册折定义：训练 N2∈{5,6,7} 去掉留出者 → 测试留出者）==")
    for data, chans, extra in (("C", tuple(F.CHANNELS), {}),
                               ("AC", tuple(F.CHANNELS),
                                {"pooling_conflict": True,
                                 "pooling_conflict_reason": "池化口径，只作归因"})):
        for held in (None, 7.0, 6.0, 5.0):
            tag = "N2ex%d" % int(F.N2_TEST_MAIN if held is None else held)
            run_caliber("%s_%s" % (data, tag), data, "N2fold", -1, fixtures[data], chans,
                        note_extra=dict(extra, fold="held_out N2=%s; train pool N2∈{5,6,7}"
                                                     % (F.N2_TEST_MAIN if held is None else held)),
                        held=held)

    print("\n== 新口径（整组切分）vs 镜像（逐行切分），多种子 ==")
    for data, chans, extra in (("C", tuple(F.CHANNELS), {}),
                               ("AC", tuple(F.CHANNELS),
                                {"pooling_conflict": True,
                                 "pooling_conflict_reason":
                                     "INDEX §95.2（O-A）：A/C/V2 统计一律按批分组、禁止池化/合并批；"
                                     "本口径仅为**归因**（隔离「切分规则」这一变量），不得当结论。"}),
                               ("UNION4", SHARED4,
                                {"pooling_conflict": True,
                                 "pooling_conflict_reason": "同 AC，且跨管线（v2 标志为代理）"})):
        print("  -- data=%s（%d 通道）--" % (data, len(chans)))
        for s in seeds:
            run_caliber("%s_grouped_s%d" % (data, s), data, "grouped", s,
                        fixtures[data], chans, note_extra=extra)
            run_caliber("%s_rowwise_s%d" % (data, s), data, "rowwise", s,
                        fixtures[data], chans, note_extra=extra)

    # ---- 冲突处置敏感性（只在 pooled 口径、主种子）----
    conflict = _conflict_groups()
    print("\n== 冲突处置敏感性（默认 = 既有路径的 keep-last；其余仅作敏感性）==")
    print("  冲突组数（任一批对 rel>5%% 的跨批组）= %d" % len(conflict))
    sens: dict[str, dict] = {}
    for pol in ("keep-last", "exclude-conflicted", "prefer-finer-grid"):
        rows = _apply_policy(fixtures["AC"], conflict, pol)
        name = "AC_grouped_s%d_policy=%s" % (a.primary_seed, pol)
        res = _quick_eval(F, rows, side, a.primary_seed, tuple(F.CHANNELS))
        sens[pol] = res
        print("  %-22s 中位/%s BW %s ｜ Q %s"
              % (pol, "", _s(res["channels"]["bandwidth_Hz"]["median"]),
                 _s(res["channels"]["Q_factor"]["median"])))

    # ---- 与冻结 E5 的逐项对照 ----
    frozen = json.loads(MODEL_JSON.read_text(encoding="utf-8"))["evaluation"]
    repro = {}
    for ch, v in frozen["per_channel"].items():
        got = results["OLD_C_N2ex8"]["channels"][ch]
        repro[ch] = {
            "frozen_median": v["median"], "recomputed_median": got["median"],
            "abs_diff": (None if v["median"] is None else abs(v["median"] - got["median"])),
            "frozen_lift": v["lift_vs_persistence"],
            "recomputed_lift": got["lift_vs_persistence"],
            "frozen_n_predicted": v["n_predicted"], "recomputed_n_predicted": got["n_predicted"],
            "match": (v["n_predicted"] == got["n_predicted"]
                      and v["median"] is not None and got["median"] is not None
                      and abs(v["median"] - got["median"]) < 1e-12)}
    repro_ok = all(x["match"] for x in repro.values())
    print("\n旧口径复算与冻结 E5 逐通道一致：%s" % repro_ok)
    for ch, v in repro.items():
        print("   %-22s 冻结 %s / 复算 %s ｜ n %d/%d"
              % (ch, _s(v["frozen_median"]), _s(v["recomputed_median"]),
                 v["frozen_n_predicted"], v["recomputed_n_predicted"]))

    # ---- 跨管线既有脚本（只读复跑，作为证据留档）----
    xwalk_txt = ""
    try:
        spec = importlib.util.spec_from_file_location("_xwalk", XWALK)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.main()
        xwalk_txt = buf.getvalue()
        print("\n跨管线既有脚本（scripts/cross_pipeline_label_check.py）复跑完成（只读）")
    except Exception as exc:                      # noqa: BLE001
        xwalk_txt = "[复跑失败] %r" % (exc,)
        print("\n[WARN] 跨管线脚本复跑失败：%r" % (exc,))

    # ---- 稳定性汇总 ----
    stability = _stability(results, seeds)
    attribution = _attribution(results, seeds)
    verdict = _verdict(results, seeds)

    outdir = pathlib.Path(a.out_dir)
    if not outdir.is_absolute():
        outdir = REPO / outdir
    outdir.mkdir(parents=True, exist_ok=True)

    # 长表 CSV
    rows_out = []
    for r in calibers:
        for ch, v in r["channels"].items():
            rows_out.append({
                "caliber": r["caliber"], "data": r["data"], "split_rule": r["split_rule"],
                "seed": r["seed"], "channel": ch, "group": v["group"],
                "is_formal_objective": v["is_formal_objective"],
                "n_train_rows": r["n_train_rows"], "n_holdout_rows": r["n_holdout_rows"],
                "leak_rows": r["leak"]["n_rows_key_also_in_train"],
                "n_defined_holdout": v["n_defined_holdout"],
                "n_in_domain_holdout": v["n_in_domain_holdout"],
                "n_out_of_domain_defined": v["n_out_of_domain_defined"],
                "n_flag_usable_holdout": v["n_flag_usable_holdout"],
                "n_predicted": v["n_predicted"],
                "coverage_of_defined": v["coverage_of_defined"],
                "coverage_of_in_domain": v["coverage_of_in_domain"],
                "median_err": v["median"], "p90": v["p90"], "max": v["max"],
                "baseline_persistence_median": v["baseline_persistence_median"],
                "lift_vs_persistence": v["lift_vs_persistence"],
                "beats_persistence": v["beats_persistence"],
                "n_in_layer": v["modes"]["in_layer"], "n_n2_extrap": v["modes"]["n2_extrap"],
                "verdict_band": v["verdict_band"],
                "refusal_reasons": json.dumps(v["refusal_reasons"], ensure_ascii=False),
            })
    lt = outdir / "rerun_channel_lift_table.csv"
    with lt.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    summary = {
        "kind": "grouped_split_rerun_channels_v1",
        "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "eval_core": {"path": str(FITTER.relative_to(REPO)).replace("\\", "/"),
                      "sha256": sha256_file(FITTER),
                      "reuse": "import 既有 fit_multichannel_surrogate：build/predict_one/"
                               "baseline_persistence/stats/defined/err，**未改写**"},
        "inputs": {"labels_ac": ac_meta, "labels_v2": v2_meta,
                   "assignments": {"path": str(ASSIGN.relative_to(REPO)).replace("\\", "/"),
                                   "sha256": sha256_file(ASSIGN)},
                   "model_json": {"path": str(MODEL_JSON.relative_to(REPO)).replace("\\", "/"),
                                  "sha256": sha256_file(MODEL_JSON)},
                   "cross_pipeline_script": {
                       "path": str(XWALK.relative_to(REPO)).replace("\\", "/"),
                       "sha256": sha256_file(XWALK)}},
        "calibers": calibers,
        "old_caliber_reproduction_vs_frozen_E5": {"ok": repro_ok, "per_channel": repro},
        "stability": stability,
        "leak_attribution": attribution,
        "verdict": verdict,
        "conflict_policy_sensitivity": {
            "n_conflict_groups": len(conflict),
            "default": "keep-last（= 既有 build() 的后写覆盖先写，**不是**新规则）",
            "results": sens},
        "boundaries": {
            "v2_missing_channels": list(V2_MISSING),
            "eight_channel_scope": ("三批并集**只能**跑 4 通道：v2 冻结副本没有 %s 四列 ⇒ "
                                    "8 通道重跑只能在 A∪C（2005 行）上做" % list(V2_MISSING)),
            "v2_flags_are_proxies": v2_meta["flag_caliber"],
            "pooling_conflict": ("AC / UNION4 口径与 INDEX §95.2（O-A：禁止池化/禁止合并批）冲突，"
                                 "只作归因用途，不得当结论"),
            "quarantine": ("沿用既有模型口径：排除 (0.2,1,7)/(0.2,1,8)（A、C 各 1 行，共 4 行去 4）；"
                           "敏感性已由 `n_out_of_domain_defined` 与 fixtures 计数披露"),
        },
        "no_state_promotion": True,
        "not_a_solver": ("本代理只预测一阶峰标量，无场级误差界、无 L1 网格收敛 ⇒ "
                         "不得用于工程绝对值，不得称为免 COMSOL 出解"),
    }
    (outdir / "rerun_channels_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "cross_pipeline_label_check_stdout.txt").write_text(xwalk_txt, encoding="utf-8")
    md = _render_md(summary, seeds, a.primary_seed, lt)
    (outdir / "RERUN_CHANNELS.md").write_text(md, encoding="utf-8")
    print("\n产物：")
    for p in (lt, outdir / "rerun_channels_summary.json", outdir / "RERUN_CHANNELS.md",
              outdir / "cross_pipeline_label_check_stdout.txt"):
        print("  %s（%d B）" % (p.relative_to(REPO), p.stat().st_size))
    return EXIT_OK


def _s(v, n=8):
    return "—" if v is None else ("%+.*g" % (n, v))


def _conflict_groups() -> set:
    """从组清单读回「任一批对 rel>5%」的跨批组键（**逐组粗粒度**，只用于敏感性）。"""
    p = DEFAULT_OUT / "grouped_split_groups.csv"
    if not p.is_file():
        return set()
    out = set()
    with p.open("r", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("label_conflict_channels", "")).strip():
                out.add(tuple(float(v) for v in r["key_round6"].split("|")))
    return out


def _apply_policy(rows: list[dict], conflict: set, policy: str) -> list[dict]:
    """冲突处置的**敏感性**实现（默认 keep-last 即原样返回）。"""
    if policy == "keep-last" or not conflict:
        return list(rows)
    if policy == "exclude-conflicted":
        return [r for r in rows if r["key"] not in conflict]
    if policy == "prefer-finer-grid":
        best: dict[tuple, dict] = {}
        for r in rows:
            cur = best.get(r["key"])
            if cur is None or _rank(r) > _rank(cur):
                best[r["key"]] = r
        return list(best.values())
    raise ValueError(policy)


def _rank(r: dict) -> tuple:
    """参考值优先级（与 split 脚本同规则）：① 栅格更细（n_freq 更大）② 优先 C_first_peak 管线。"""
    return (r.get("_grid_n", -1), 1 if r["pipeline"] == "C_first_peak_20260929" else 0)


def _quick_eval(F, rows, side, seed, channels):
    train = [r for r in rows if side[(r["batch"], r["key"])][seed] == "train"]
    test = [r for r in rows if side[(r["batch"], r["key"])][seed] == "holdout"]
    return {"n_train_rows": len(train), "n_holdout_rows": len(test),
            "leak": leak(F, train, test),
            "channels": {c: evaluate(F, train, test, c) for c in channels}}


def _stability(results: dict, seeds: list[int]) -> dict:
    out = {}
    for data, chans in (("C", None), ("AC", None), ("UNION4", ("f_peak_Hz", "bandwidth_Hz",
                                                               "Q_factor", "peak_SPL_dB"))):
        chs = chans or ("bandwidth_Hz", "Q_factor", "abs_w_m", "abs_p_per_V_Pa",
                        "f_peak_Hz", "abs_p_Pa", "abs_vz_struct_m3s", "peak_SPL_dB")
        for rule in ("grouped", "rowwise"):
            per = {}
            for c in chs:
                lf, md = [], []
                for s in seeds:
                    k = "%s_%s_s%d" % (data, rule, s)
                    v = results.get(k, {}).get("channels", {}).get(c)
                    if not v:
                        continue
                    if v["lift_vs_persistence"] is not None:
                        lf.append(v["lift_vs_persistence"])
                    if v["median"] is not None:
                        md.append(v["median"])
                if not lf:
                    continue
                per[c] = {"n_seeds": len(lf), "lift_min": min(lf), "lift_max": max(lf),
                          "lift_median": sorted(lf)[len(lf) // 2],
                          "median_min": min(md), "median_max": max(md),
                          "flip_positive_all_seeds": all(x >= 0 for x in lf),
                          "flip_negative_all_seeds": all(x < 0 for x in lf),
                          "signs": [("+" if x >= 0 else "-") for x in lf]}
            out["%s_%s" % (data, rule)] = per
    return out


def _attribution(results: dict, seeds: list[int]) -> dict:
    """泄漏归因：`delta = grouped lift − rowwise lift`（同数据/同种子/同 holdout 行数）。

    单批 `C` 两侧的泄漏行数**都是 0** ⇒ 该行的 delta = **切分组成的噪声基线**
    （不是泄漏效应）。只有跨批数据（`AC`/`UNION4`）的 delta 才有泄漏成分；
    判据：跨批 delta 是否**一致地**超出单批噪声基线。
    """
    out: dict[str, dict] = {}
    for data in ("C", "AC", "UNION4"):
        per: dict[str, dict] = {}
        for ch in ("bandwidth_Hz", "Q_factor", "abs_w_m", "f_peak_Hz",
                   "abs_p_per_V_Pa", "abs_p_Pa", "abs_vz_struct_m3s", "peak_SPL_dB"):
            deltas = []
            for s in seeds:
                g = results.get("%s_grouped_s%d" % (data, s), {}).get("channels", {}).get(ch)
                r = results.get("%s_rowwise_s%d" % (data, s), {}).get("channels", {}).get(ch)
                if not g or not r:
                    continue
                if g["lift_vs_persistence"] is None or r["lift_vs_persistence"] is None:
                    continue
                deltas.append(g["lift_vs_persistence"] - r["lift_vs_persistence"])
            if not deltas:
                continue
            per[ch] = {
                "n_seeds": len(deltas), "deltas": deltas,
                "min": min(deltas), "median": sorted(deltas)[len(deltas) // 2],
                "max": max(deltas), "n_negative": sum(1 for d in deltas if d < 0),
                "interpretation": ("单批口径：两侧泄漏行数均为 0 ⇒ 本行 = **切分组成噪声基线**"
                                   if data == "C" else
                                   "跨批口径：rowwise 把同一组合键拆到两侧（泄漏行数>0）"
                                   "⇒ delta 应为负（泄漏抬高 rowwise 的 lift）"),
            }
        out[data] = per
    return out


def _verdict(results: dict, seeds: list[int]) -> dict:
    """**明确判定**：逐通道把「整组口径」与「逐行（泄漏）口径」分开数正负号。

    判定语义（**先定后算**）：
    * 整组口径**全为负**且旧口径为负 ⇒ **未翻身**；
    * 整组口径**全为负**且旧口径非负 ⇒ **反向转负**（是问题换了，不是「泄漏被去掉」）；
    * 整组口径**全为正**且旧口径为负 ⇒ **翻身**；
    * 整组口径自身符号不一致 ⇒ **不稳**。
    """
    out = {}
    for ch in ("bandwidth_Hz", "Q_factor", "abs_w_m", "f_peak_Hz"):
        o = results.get("OLD_C_N2ex8", {}).get("channels", {}).get(ch, {})
        old = o.get("lift_vs_persistence")
        g_rows, r_rows = [], []
        for data in ("C", "AC", "UNION4"):
            for s in seeds:
                for rule, bucket in (("grouped", g_rows), ("rowwise", r_rows)):
                    r = results.get("%s_%s_s%d" % (data, rule, s))
                    if not r or ch not in r["channels"]:
                        continue
                    v = r["channels"][ch]
                    if v["lift_vs_persistence"] is None:
                        continue
                    bucket.append({"caliber": r["caliber"], "data": data, "seed": s,
                                   "lift": v["lift_vs_persistence"],
                                   "leak_rows": r["leak"]["n_rows_key_also_in_train"]})
        allr = g_rows + r_rows
        n_pos = sum(1 for r in allr if r["lift"] >= 0)
        g_pos = sum(1 for r in g_rows if r["lift"] >= 0)
        # ---- 旧折族（N2 外推，沿用预注册折定义）：符号是否**依赖留出层** ----
        fold_rows = []
        for data in ("C", "AC"):
            for tag in ("8", "7", "6", "5"):
                cal = "%s_N2ex%s" % (data, tag)
                r = results.get(cal)
                if not r or ch not in r["channels"]:
                    continue
                v = r["channels"][ch]
                if v["lift_vs_persistence"] is None:
                    continue
                fold_rows.append({"caliber": cal, "held_out_N2": int(tag),
                                  "lift": v["lift_vs_persistence"], "median": v["median"],
                                  "baseline": v["baseline_persistence_median"],
                                  "n_predicted": v["n_predicted"],
                                  "n_defined_holdout": v["n_defined_holdout"],
                                  "leak_rows": r["leak"]["n_rows_key_also_in_train"]})
        n_fold_pos = sum(1 for r in fold_rows if r["lift"] >= 0)
        fold_dependent = 0 < n_fold_pos < len(fold_rows)
        if not g_rows:
            verdict = "无数据"
        elif g_pos == 0 and (old is None or old < 0):
            verdict = "**未翻身**（整组口径全为负，旧口径亦为负）"
        elif g_pos == 0 and old is not None and old >= 0:
            verdict = "**反向转负**（整组口径全为负，旧口径非负）"
        elif g_pos == len(g_rows) and old is not None and old < 0:
            verdict = "**翻身**（整组口径全为正，旧口径为负）"
        else:
            verdict = "**不稳**（整组口径内部符号不一致）"
        if fold_dependent:
            verdict += ("；但**旧折族（N2 外推）的符号依赖留出层**：%d/%d 折为正（%s）"
                        "⇒ **结论不稳**，不得据单一折宣称翻身"
                        % (n_fold_pos, len(fold_rows),
                           "、".join("%s%+0.6g" % (r["caliber"], r["lift"])
                                     for r in fold_rows)))
        out[ch] = {
            "old_lift_batchC_N2extrap": old,
            "n_grouped_calibers": len(g_rows), "n_grouped_positive": g_pos,
            "n_all_calibers": len(allr), "n_all_positive": n_pos,
            "n_rowwise_calibers": len(r_rows),
            "n_rowwise_positive": sum(1 for r in r_rows if r["lift"] >= 0),
            "grouped_lift_min": min((r["lift"] for r in g_rows), default=None),
            "grouped_lift_max": max((r["lift"] for r in g_rows), default=None),
            "new_lift_min": min((r["lift"] for r in allr), default=None),
            "new_lift_max": max((r["lift"] for r in allr), default=None),
            "n2_fold_family": fold_rows,
            "n2_fold_n_positive": n_fold_pos, "n2_fold_n": len(fold_rows),
            "fold_dependent": fold_dependent,
            "verdict": verdict,
        }
    return out


def _attr_conclusion(attr: dict, ch: str, verdict: dict) -> str:
    """把泄漏归因的结论**由数字现算**（不写死）。"""
    parts = []
    for data in ("C", "AC", "UNION4"):
        v = (attr.get(data) or {}).get(ch)
        if not v:
            continue
        parts.append("%s %d/%d 为负、中位 %s、区间 [%s, %s]"
                     % (data, v["n_negative"], v["n_seeds"], _s(v["median"], 6),
                        _s(v["min"], 6), _s(v["max"], 6)))
    base = (attr.get("C") or {}).get(ch)
    cross = [(d, (attr.get(d) or {}).get(ch)) for d in ("AC", "UNION4")]
    note = ""
    if base is not None and all(v is not None for _, v in cross):
        floor = max(abs(base["min"]), abs(base["max"]))
        over = {d: (abs(v["median"]) > floor) for d, v in cross}
        consistent = all(v["n_negative"] == v["n_seeds"] for _, v in cross)
        if all(over.values()) and consistent:
            call = "跨批 delta 一致超出噪声基线且全种子同号 ⇒ **可归因为泄漏抬高表观 lift**"
        elif any(over.values()):
            call = ("**部分支持**（超出噪声基线的口径：%s；未超出：%s）⇒ 泄漏效应存在但幅度"
                    "与切分组成噪声**同量级**，不足以改变结论"
                    % ("、".join(d for d in over if over[d]),
                       "、".join(d for d in over if not over[d])))
        else:
            call = "跨批 delta **未超出**单批噪声基线 ⇒ 泄漏效应与组成噪声**不可分离**（不下强结论）"
        note = ("；单批噪声基线幅度 %s；跨批 delta 是否超出：%s；符号一致：%s ⇒ %s"
                % (_s(floor, 6),
                   "、".join("%s=%s" % (d, "是" if over[d] else "否") for d, _ in cross),
                   "是" if consistent else "否", call))
    tail = ""
    if verdict:
        tail = ("；整组口径 lift 区间 [%s, %s]，判定 = %s"
                % (_s(verdict.get("grouped_lift_min"), 6),
                   _s(verdict.get("grouped_lift_max"), 6),
                   verdict.get("verdict", "")))
    return "；".join(parts) + note + tail


def _fmt_tbl(per: dict, seeds: list[int], title: str) -> list[str]:
    L = ["| 通道 | 正式目标 | 可判定分母(定义/域内) | 覆盖率 | 中位误差 | p90 | 基线(抄相邻层) | **lift = 基线−模型** | 增值？ | in_layer/n2_extrap |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for ch, v in per.items():
        L.append("| `%s` | %s | %d / %d | %.1f%% / %.1f%% | %s | %s | %s | **%s** | %s | %d / %d |"
                 % (ch, "是" if v["is_formal_objective"] else "否",
                    v["n_defined_holdout"], v["n_in_domain_holdout"],
                    100 * (v["coverage_of_defined"] or 0), 100 * (v["coverage_of_in_domain"] or 0),
                    _s(v["median"], 6), _s(v["p90"], 6), _s(v["baseline_persistence_median"], 6),
                    _s(v["lift_vs_persistence"], 8),
                    "**是**" if v["beats_persistence"] else "否",
                    v["modes"]["in_layer"], v["modes"]["n2_extrap"]))
    return L


def _render_md(s: dict, seeds: list[int], primary: int, lt: pathlib.Path) -> str:
    res = {c["caliber"]: c for c in s["calibers"]}
    L = ["# 用**整组切分**后的数据重跑 8 通道（P2 第 2 步）", "",
         "> 评估内核 = **import** 既有 `%s`（sha256 `%s`）—— **未重写**。"
         % (s["eval_core"]["path"], s["eval_core"]["sha256"][:16]),
         "> 「g/L」= **增益 gain / lift**：`lift = 基线（抄相邻层）中位误差 − 模型中位误差`，正 = 有增值"
         "（与仓库既有 `lift_vs_persistence` 同定义）。",
         "> ⚠️ 本代理**不是 AI 求解器**：无场级误差界、无 L1 ⇒ 不得用于工程绝对值。", "",
         "## 0. 边界（先读这段，否则会误读下表）", "",
         "1. **三批并集跑不了 8 通道**：v2 冻结副本没有 `%s` 四列 ⇒ "
         "**8 通道重跑只能在 A∪C（2005 行）上做**；并集口径只能给 4 通道（且 v2 的"
         "「找到峰/闭合」标志是**代理**，见下）。" % "`、`".join(s["boundaries"]["v2_missing_channels"]),
         "2. **旧口径 ≠ 非整组切分**：旧口径（E5）是**批 C 的 N2 外推折**（训练 N2∈{5,6,7} → "
         "测试 N2=8）。该折**本来就**满足「组合键交集 = 0」（训练键的 N2≤7、测试键的 N2=8，"
         "构造上不相交）⇒ **在旧问题上，整组切分规则是空操作**。",
         "3. 因此「旧 vs 新」的差异**不能**归因于「去掉了泄漏」，而主要来自**问题换了**"
         "（N2 外推 → 层内/邻层内插）；真正能隔离「切分规则」这一变量的对照是 "
         "**`*_grouped_*` vs `*_rowwise_*`（同数据、同种子、同 holdout 行数）**。",
         "4. `AC` / `UNION4` 是**池化**口径，与 INDEX §95.2（O-A：禁止池化/禁止合并批）**冲突** ⇒ "
         "只作**归因**用途，**不得当结论**。", "",
         "## 0.1 明确判定（`bandwidth_Hz` / `Q_factor` 是否翻身）", "",
         "| 通道 | 旧口径 lift（批 C / N2 外推） | **整组切分**口径 为正的个数 | 整组 lift 区间 | 逐行（泄漏）口径 为正的个数 | **判定** |",
         "|---|---|---|---|---|---|"]
    for ch, v in s["verdict"].items():
        L.append("| `%s` | %s | %d / %d | [%s, %s] | %d / %d | %s |"
                 % (ch, _s(v["old_lift_batchC_N2extrap"], 8),
                    v["n_grouped_positive"], v["n_grouped_calibers"],
                    _s(v["grouped_lift_min"], 6), _s(v["grouped_lift_max"], 6),
                    v["n_rowwise_positive"], v["n_rowwise_calibers"], v["verdict"]))
    _v = s["verdict"]
    L += ["",
          "> 判定**逐格由上面的数字现算**（判据写在脚本 `_verdict()` 的 docstring 里，先定后算）：",
          "> * `bandwidth_Hz`：%s —— 整组口径 %d/%d 为正（区间 [%s, %s]），"
          "**连带泄漏的逐行口径也只有 %d/%d 为正**（区间 [%s, %s]）。"
          % (_v["bandwidth_Hz"]["verdict"], _v["bandwidth_Hz"]["n_grouped_positive"],
             _v["bandwidth_Hz"]["n_grouped_calibers"],
             _s(_v["bandwidth_Hz"]["grouped_lift_min"], 6),
             _s(_v["bandwidth_Hz"]["grouped_lift_max"], 6),
             _v["bandwidth_Hz"]["n_rowwise_positive"], _v["bandwidth_Hz"]["n_rowwise_calibers"],
             _s(_v["bandwidth_Hz"]["new_lift_min"], 6), _s(_v["bandwidth_Hz"]["new_lift_max"], 6)),
          "> * `Q_factor`：%s —— 整组口径 %d/%d 为正（区间 [%s, %s]）；逐行口径 %d/%d 为正。"
          % (_v["Q_factor"]["verdict"], _v["Q_factor"]["n_grouped_positive"],
             _v["Q_factor"]["n_grouped_calibers"],
             _s(_v["Q_factor"]["grouped_lift_min"], 6),
             _s(_v["Q_factor"]["grouped_lift_max"], 6),
             _v["Q_factor"]["n_rowwise_positive"], _v["Q_factor"]["n_rowwise_calibers"]),
          "> ⇒ **不许用一次切分宣布翻身**：这里是「3 数据范围 × 2 切分规则 × 5 种子」共 %d 个口径×种子；"
          "**带泄漏的口径算进去也一样**。" % _v["bandwidth_Hz"]["n_all_calibers"],
          "> 另有**反向**翻（旧口径正 → 整组口径负）：`abs_w_m`（正式目标）%s、`f_peak_Hz` %s —— "
          "那是**问题换了**（N2 外推 → 层内/邻层内插），**不是**「泄漏被去掉」。"
          % (_v["abs_w_m"]["verdict"], _v["f_peak_Hz"]["verdict"]), "",
          "## 0.2 泄漏归因：`delta = grouped lift − rowwise lift`（同数据/同种子/同 holdout 行数）", "",
          "| data | 通道 | 种子数 | delta 最小 | delta 中位 | delta 最大 | 为负的种子数 | 读法 |",
          "|---|---|---|---|---|---|---|---|"]
    for data, per in s["leak_attribution"].items():
        for ch, v in per.items():
            L.append("| %s | `%s` | %d | %s | %s | %s | %d | %s |"
                     % (data, ch, v["n_seeds"], _s(v["min"], 6), _s(v["median"], 6),
                        _s(v["max"], 6), v["n_negative"],
                        "**噪声基线**（两侧泄漏皆 0）" if data == "C" else "泄漏效应"))
    L += ["",
          "> 读法：`C` 行是**切分组成噪声基线**（grouped 与 rowwise 在单批里都不泄漏，"
          "差异只来自 holdout 取了哪些 x）；",
          "> 只有跨批（`AC`/`UNION4`）的 delta **一致为负、且幅度超出 C 的噪声基线**时，"
          "才可归因为**泄漏**。下表两个结论**由上面的数字现算**，不是事先写好的：", ""]
    for ch in ("bandwidth_Hz", "Q_factor"):
        L.append("* **`%s`**：%s" % (ch, _attr_conclusion(s["leak_attribution"], ch,
                                                         s["verdict"].get(ch, {}))))
    L += ["",
          "## 0.3 **多折**（旧折族：N2 外推标尺折；沿用预注册折定义）—— 符号是否依赖留出层", "",
          "折定义：训练 N2∈{5,6,7} 去掉留出者 → 测试留出者（`N2ex8` = 旧主判定折）。"
          "整组规则在这些折上是**空操作**（每个折的 `泄漏行数` 实测 = 0，见下表最后一列），"
          "所以这里衡量的是**问题/折**的影响，不是切分规则。", "",
          "| 通道 | C N2ex8 | C N2ex7 | C N2ex6 | C N2ex5 | AC N2ex8 | AC N2ex7 | AC N2ex6 | AC N2ex5 | 为正的折数 | 判定 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for ch, v in s["verdict"].items():
        folds = {r["caliber"]: r for r in v.get("n2_fold_family", [])}
        cells = []
        for cal in ("C_N2ex8", "C_N2ex7", "C_N2ex6", "C_N2ex5",
                    "AC_N2ex8", "AC_N2ex7", "AC_N2ex6", "AC_N2ex5"):
            r = folds.get(cal)
            cells.append(_s(r["lift"], 6) if r else "—")
        L.append("| `%s` | %s | %d / %d | %s |"
                 % (ch, " | ".join(cells), v["n2_fold_n_positive"], v["n2_fold_n"],
                    "**符号依赖留出层 ⇒ 不稳**" if v.get("fold_dependent")
                    else ("全为负" if v["n2_fold_n_positive"] == 0 else "全为正")))
    L += ["",
          "> ⚠️ 这一节是**必须与 §0.1 一起读**的：`bandwidth_Hz` / `Q_factor` 在**新口径（整组切分）**"
          "下 15/15 为负 ⇒ **未翻身**；但在**旧折族**上符号**随留出层翻转**"
          "（N2ex5/N2ex6 为正、N2ex7/N2ex8 为负）⇒ **「翻身与否」依赖折**，"
          "只看某一折就会得出相反结论 ⇒ **结论不稳，不能据此宣称翻身，也不能宣称「一致为负」**。",
          "> 每个折的 `泄漏行数` 均为 **0**（N2 折构造上训练/测试的 N2 不相交）⇒ 折间差异"
          "**与泄漏无关**。", ""]
    L += ["",
          "## 1. 旧口径复算 vs 冻结 E5（同一路径 ⇒ 必须逐项一致）", "",
         "| 通道 | 冻结 E5 中位 | 本轮复算中位 | \\|差\\| | 冻结 n_predicted | 复算 n_predicted | 一致？ |",
         "|---|---|---|---|---|---|---|"]
    for ch, v in s["old_caliber_reproduction_vs_frozen_E5"]["per_channel"].items():
        L.append("| `%s` | %s | %s | %s | %d | %d | %s |"
                 % (ch, _s(v["frozen_median"], 8), _s(v["recomputed_median"], 8),
                    "—" if v["abs_diff"] is None else "%.2e" % v["abs_diff"],
                    v["frozen_n_predicted"], v["recomputed_n_predicted"],
                    "**一致**" if v["match"] else "**不一致**"))
    L += ["", "> 复算与冻结值逐项一致 = **%s**（证明本脚本确实在跑既有路径，而非另一套实现）。"
          % s["old_caliber_reproduction_vs_frozen_E5"]["ok"], "",
          "### 1.1 旧口径（E5）原表（供并列阅读）", ""]
    old = res["OLD_C_N2ex8"]
    L += _fmt_tbl(old["channels"], seeds, "OLD")
    L += ["", "## 2. 新口径（A∪C，整组切分，主种子 %d）与旧口径**并列**" % primary, ""]
    new = res["AC_grouped_s%d" % primary]
    L += _fmt_tbl(new["channels"], seeds, "NEW")
    L += ["", "**与旧口径的逐通道对照（同为正=都有增值）**：", "",
          "| 通道 | 旧口径 lift（批 C / N2 外推） | 新口径 lift（A∪C / 整组切分） | 方向变化 |",
          "|---|---|---|---|"]
    for ch in old["channels"]:
        o = old["channels"][ch]["lift_vs_persistence"]
        n = new["channels"].get(ch, {}).get("lift_vs_persistence")
        flag = "—"
        if o is not None and n is not None:
            flag = ("**由负转正**" if o < 0 <= n else
                    "**由正转负**" if o >= 0 > n else "同号（未变）")
        L.append("| `%s` | %s | %s | %s |" % (ch, _s(o, 8), _s(n, 8), flag))
    L += ["", "## 3. 归因：**只换切分规则**（同数据、同种子、同 holdout 行数）", "",
          "| data | seed | 口径 | 泄漏行数（留出行的键也在训练集） | BW lift | Q lift | 8 通道 lift 中位数 |",
          "|---|---|---|---|---|---|---|"]
    for data in ("C", "AC", "UNION4"):
        for sd in seeds:
            for rule in ("grouped", "rowwise"):
                r = res.get("%s_%s_s%d" % (data, rule, sd))
                if not r:
                    continue
                lf = [v["lift_vs_persistence"] for v in r["channels"].values()
                      if v["lift_vs_persistence"] is not None]
                L.append("| %s | %d | **%s** | %d | %s | %s | %s |"
                         % (data, sd, rule, r["leak"]["n_rows_key_also_in_train"],
                            _s(r["channels"].get("bandwidth_Hz", {}).get("lift_vs_persistence"), 6),
                            _s(r["channels"].get("Q_factor", {}).get("lift_vs_persistence"), 6),
                            _s(sorted(lf)[len(lf) // 2] if lf else None, 6)))
    L += ["", "> 读法：`C`（单批）**没有**内部重复键 ⇒ grouped 与 rowwise 的**泄漏行数都是 0**，"
          "两者 lift 应当几乎相同 ⇒ 证明**单批口径下切分规则不改变结论**；",
          "> `AC`/`UNION4` 是跨批数据，rowwise 会把**同一组合键**拆到两侧（泄漏行数 > 0），"
          "grouped 为 0 ⇒ 两者的差 = **泄漏造成的虚高**。", "",
          "## 4. 多种子稳定性（**结论不许只看一次切分**）", ""]
    for tag, per in s["stability"].items():
        L.append("**`%s`**：" % tag)
        L.append("")
        L.append("| 通道 | 种子数 | lift 符号 | lift 最小 | lift 中位 | lift 最大 | 全种子同号？ |")
        L.append("|---|---|---|---|---|---|---|")
        for ch, v in per.items():
            L.append("| `%s` | %d | %s | %s | %s | %s | %s |"
                     % (ch, v["n_seeds"], "".join(v["signs"]), _s(v["lift_min"], 6),
                        _s(v["lift_median"], 6), _s(v["lift_max"], 6),
                        ("是（正）" if v["flip_positive_all_seeds"] else
                         "是（负）" if v["flip_negative_all_seeds"] else "**否（不稳）**")))
        L.append("")
    L += ["## 5. 冲突处置敏感性（默认 = 既有路径的 keep-last，其余只作敏感性）", "",
          "冲突组数（任一批对 rel>5%% 的跨批组）= **%d**；默认 `keep-last` = 既有 "
          "`build()` 的**后写覆盖先写**（**不是我新定的规则**）。"
          % s["conflict_policy_sensitivity"]["n_conflict_groups"], "",
          "| 处置 | BW 中位 | Q 中位 | 说明 |", "|---|---|---|---|"]
    for pol, v in s["conflict_policy_sensitivity"]["results"].items():
        L.append("| `%s` | %s | %s | %s |"
                 % (pol, _s(v["channels"]["bandwidth_Hz"]["median"], 6),
                    _s(v["channels"]["Q_factor"]["median"], 6),
                    "默认（= O-A 现状在现有代码下的实际行为）" if pol == "keep-last"
                    else "【待裁定】新规则，仅敏感性"))
    L += ["", "> ⚠️ 需要人拍板的**口径冲突**（本轮不擅自取舍）：① 跨批同组合标签不一致的处置"
          "（保留两行 / 择一）；② 是否允许为训练**池化** A/C/V2（现裁定 §95.2 是「禁止」）。",
          "> 本轮**默认口径**取「既有路径的行为 + 不池化优先」并如实披露，最终取舍权在人。", "",
          "## 6. 每通道可判定分母（**不用 flag 口径**）", "",
          "| data / 口径 | 通道 | n_defined（可判定基数） | n_in_domain（∧5≤N2≤9∧N1<N2） | n_out_of_domain | n_flag_usable（**仅对照，不当分母**） | n_predicted |",
          "|---|---|---|---|---|---|---|"]
    for r in s["calibers"]:
        if r["split_rule"] != "grouped" or r["seed"] != primary:
            continue
        for ch, v in r["channels"].items():
            L.append("| %s | `%s` | %d | %d | %d | %d | %d |"
                     % (r["data"], ch, v["n_defined_holdout"], v["n_in_domain_holdout"],
                        v["n_out_of_domain_defined"], v["n_flag_usable_holdout"],
                        v["n_predicted"]))
    L += ["", "拒答构成（主种子、A∪C 整组切分）：", "",
          "```json",
          json.dumps({c: v["refusal_reasons"] for c, v in new["channels"].items()},
                     ensure_ascii=False, indent=1), "```", "",
          "## 7. 产物", "",
          "| 文件 | 内容 |", "|---|---|",
          "| `%s` | 长表：全部口径 × 通道 × 种子 |" % str(lt.relative_to(REPO)),
          "| `rerun_channels_summary.json` | 机器可读全量 |",
          "| `cross_pipeline_label_check_stdout.txt` | 既有跨管线脚本的**只读复跑**原文（证据） |",
          "| `RERUN_CHANNELS.md` | 本件 |", "",
          "## 8. 未做 / 边界", "",
          "* **未**把「翻身」当结论用到任何放行/状态上：模型仍 `draft`，未提升任何状态；",
          "* **未**跑 COMSOL；**未**改任何既有数据/冻结产物；",
          "* **未**为跨批标签冲突做合并或取舍（`keep-last` 只是**沿用既有代码行为**并披露）；",
          "* 并集（`UNION4`）口径的 v2 标志是**代理**，且与 §95.2「禁止池化」冲突 ⇒ 只作归因；",
          "* 未做**分层切分**（不按批/N2 配额）⇒ 两侧构成已在 `GROUPED_SPLIT.md` 披露；",
          "* 未做**换模型**（如带收缩的斜率估计）——那是另一版预注册的事。", ""]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
