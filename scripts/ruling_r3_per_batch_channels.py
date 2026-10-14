# -*- coding: utf-8 -*-
"""R3 落表：8 通道 lift **按批分列**（C 单批 / A 单批 / A∪C 参考）。

## 裁决（R3｜用户 2026-10-09 拍板）

**按批分列**：**C 单批为 8 通道权威口径**，**A 单批单列并标 n 不足**
（其 4/8 通道反号必须随列标注），**A∪C 仍作参考并带可判定分母**。
**判定自洽**：`channels_without_lift` 与 `draft` **不变**；**不得据任一口径宣布翻身**。

## 口径与复用

* 评估内核 **import** 既有 `work/runs/multichannel-surrogate-20260929/fit_multichannel_surrogate.py`
  （`build / predict_one / baseline_persistence / stats / defined / err / CHANNELS`）—— **不重写**；
* 切分 = `work/runs/grouped-split-20261009/grouped_split_assignments.csv` 的**整组切分**（seed 0），
  与 §113/§114/§136 同一切分（**同一脚本的同一函数**，经 `scripts/rerun_grouped_split_channels.py`
  的 `load_assignments / rows_ac / evaluate` 复用）；
* `lift = 基线（抄相邻层）中位误差 − 模型中位误差`（正 = 有增值）。

## 分母纪律（§116.4）

每个「列 × 通道」都同时给：

* `denominator` = **可判定基数**（域内、`in_domain` 的行数，逐行现算）；
* `flag_basis_count` = **标志口径计数**（该通道 holdout 里 `ranking_eligible` 为真的行数）；
* `n_nondecidable` = 两者之差（显式给出，哪怕为 0）。

⚠️ **不用 flag 口径当分母**。本表的 `ranking_eligible` 比可判定集**更窄**（见脚本输出），
故本表**不**把它当分母、也**不**据此算比例；脚本另跑一次
`guards_denominator.check_rate_record()` 把守卫的裁定**原文打印**出来留档
（守卫假定 `flag_basis_count ≥ denominator`；本数据不满足该假定 ⇒ 这是一条**实测事实**）。

## 纪律

只读；产物只落 `--out-dir`（缺省新目录 `work/runs/rulings-20261009/`）；
**不改** `build()`、**不改** `solver.py` 阈值、**不改**模型 JSON、**不跑 COMSOL**、**不提升任何状态**。

退出码：`0` 成功；`2` 输入不可用；`3` 与 §113.3 登记值不符（A∪C 列必须逐位复现）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

EXIT_OK, EXIT_INPUT, EXIT_REGRESSED = 0, 2, 3

RERUN = REPO / "scripts/rerun_grouped_split_channels.py"
LABELS_AC = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"
MODEL_JSON = REPO / "work/runs/multichannel-surrogate-20260929/multichannel_model.json"
SOLVER_SPEC = REPO / "work/runs/solver/pmut-f1/solver_spec.json"
DEFAULT_OUT = REPO / "work/runs/rulings-20261009"

#: §113.3 冻结的 A∪C 新口径 lift（**引用基线**；A∪C 列必须逐位复现）
REGISTERED_AC_LIFT = {
    "bandwidth_Hz": -0.00716005, "Q_factor": -0.00335461, "abs_w_m": -0.00222458,
    "abs_p_per_V_Pa": 0.00373186, "abs_p_Pa": 0.00373186,
    "abs_vz_struct_m3s": 0.00159686, "f_peak_Hz": -0.00512314, "peak_SPL_dB": 0.07463710,
}
#: §113.3 冻结的 A∪C 可判定分母（可判定 / 域内）
REGISTERED_AC_DENOM = {"bandwidth_Hz": (509, 501), "Q_factor": (509, 501),
                       "abs_w_m": (537, 529), "abs_p_per_V_Pa": (537, 529),
                       "abs_p_Pa": (537, 529), "abs_vz_struct_m3s": (537, 529),
                       "f_peak_Hz": (537, 529), "peak_SPL_dB": (537, 529)}
#: 冻结模型登记值（本脚本**现读现比**，不改它）
FROZEN_EXPECT = {"status": "draft",
                 "channels_without_lift": ["bandwidth_Hz", "Q_factor"],
                 "solver_state": "draft"}
#: A 批「成因数据不存在」的出处
CAUSE_ABSENT = {
    "reference": "INDEX §96.4 / §96.3",
    "fact": ("A 批（`a_5-35mhz`，223 行）的 `peak_at_scan_endpoint` 与 "
             "`bw_upper_cutoff_at_endpoint` 两列**整列为空**（`n_flag_nonempty` 都是 0），"
             "§96.3 记「原表根本没有这两列」⇒ **A 单批反号的成因（删失/截断 vs 样本量）"
             "所需的数据不存在**。"),
    "rule": "**不许推测成因**（判不了就说判不了）。",
}
UNION4_CHANNELS = ("f_peak_Hz", "bandwidth_Hz", "Q_factor", "peak_SPL_dB")


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load_module(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def header_of(p: pathlib.Path) -> list[str]:
    with p.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh).fieldnames or [])


def run_col(F, rgsc, side, rows, channels, seed: int, data: str) -> dict:
    train = [r for r in rows if side[(r["batch"], r["key"])][seed] == "train"]
    test = [r for r in rows if side[(r["batch"], r["key"])][seed] == "holdout"]
    chans = {c: rgsc.evaluate(F, train, test, c) for c in channels}
    return {"data": data, "seed": seed, "n_train_rows": len(train),
            "n_holdout_rows": len(test), "leak": rgsc.leak(F, train, test),
            "channels": chans}


def rate_diag(ch: str, v: dict) -> dict:
    """分母纪律：把两个口径同时列出，并**打印**守卫对本形态的裁定（留档，不算比例）。"""
    from memsharness.guards_denominator import check_rate_record
    rec = {"metric": "coverage_within_domain(%s)" % ch,
           "numerator": int(v["n_predicted"]),
           "denominator": int(v["n_in_domain_holdout"]),
           "flag_basis_count": int(v["n_flag_usable_holdout"]),
           "n_nondecidable": int(v["n_in_domain_holdout"] - v["n_predicted"]),
           "flag_key": "ranking_eligible", "value_key": ch}
    return {"record_two_calibers": {k: rec[k] for k in
                                    ("denominator", "flag_basis_count", "n_nondecidable")},
            "flag_wider_than_denominator": bool(rec["flag_basis_count"]
                                                >= rec["denominator"]),
            "guard_verdict_on_raw_record": check_rate_record(rec),
            "note": ("本表**不**用 flag 口径当分母；`guard_verdict_on_raw_record` 非空"
                     "说明该记录**不适合**当比例记录（本数据 flag 口径更窄），"
                     "正是 §116.4 要防的混用 ⇒ 两个口径只并列、不相除。")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R3 按批分列 8 通道 lift（只读）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    a = ap.parse_args(argv)

    for p in (RERUN, LABELS_AC, MODEL_JSON, SOLVER_SPEC):
        if not p.is_file():
            print("[FAIL] 缺输入：%s" % p)
            return EXIT_INPUT
    rgsc = load_module(RERUN, "_rgsc")
    F = rgsc.load_fitter()
    side = rgsc.load_assignments([a.seed])
    ac, ac_meta = rgsc.rows_ac(F)
    fixtures = {"C": [r for r in ac if r["batch"] == "C_5-50MHz"],
                "A": [r for r in ac if r["batch"] == "A_5-35MHz"],
                "AC": list(ac)}

    cols = {k: run_col(F, rgsc, side, v, tuple(F.CHANNELS), a.seed, k)
            for k, v in fixtures.items()}

    # ---- UNION4（4 通道）参考：仅作跨管线旁证，不进 8 通道表 ----
    v2, v2_meta = rgsc.rows_v2(F, rgsc.SHARED4)
    u4 = run_col(F, rgsc, side, list(ac) + list(v2), UNION4_CHANNELS, a.seed, "UNION4")

    model = json.loads(MODEL_JSON.read_text(encoding="utf-8"))
    spec = json.loads(SOLVER_SPEC.read_text(encoding="utf-8"))
    frozen_now = {"status": model.get("status"),
                  "channels_without_lift": model.get("evaluation", {})
                  .get("channels_without_lift"),
                  "solver_state": spec.get("state")}
    frozen_ok = {
        "status_draft": frozen_now["status"] == FROZEN_EXPECT["status"],
        "channels_without_lift_unchanged":
            frozen_now["channels_without_lift"] == FROZEN_EXPECT["channels_without_lift"],
        "solver_state_draft": frozen_now["solver_state"] == FROZEN_EXPECT["solver_state"],
    }
    frozen_ok["all"] = all(frozen_ok.values())

    ac_cols = header_of(LABELS_AC)
    cause_measured = {
        "ac_table_columns": len(ac_cols),
        "has_peak_at_scan_endpoint": "peak_at_scan_endpoint" in ac_cols,
        "has_bw_upper_cutoff_at_endpoint": "bw_upper_cutoff_at_endpoint" in ac_cols,
        "measured_note": ("本脚本现读 A∪C 母表表头：%s"
                          % ("两列**都不存在**" if "peak_at_scan_endpoint" not in ac_cols
                             and "bw_upper_cutoff_at_endpoint" not in ac_cols
                             else "至少一列存在（与 §96.4 的登记不同，须核实）")),
    }

    # ---- 判定自洽：A∪C 列逐位复现 §113.3 ----
    repro = {}
    for ch, exp in REGISTERED_AC_LIFT.items():
        got = cols["AC"]["channels"][ch]["lift_vs_persistence"]
        d = None if got is None else abs(got - exp)
        nd, ni = REGISTERED_AC_DENOM[ch]
        repro[ch] = {"registered_lift": exp, "recomputed_lift": got,
                     "abs_diff": d, "match_lift": bool(d is not None and d < 1e-8),
                     "registered_denominator": nd, "registered_in_domain": ni,
                     "recomputed_defined": cols["AC"]["channels"][ch]["n_defined_holdout"],
                     "recomputed_in_domain": cols["AC"]["channels"][ch]["n_in_domain_holdout"],
                     "match_denominator": bool(
                         cols["AC"]["channels"][ch]["n_defined_holdout"] == nd
                         and cols["AC"]["channels"][ch]["n_in_domain_holdout"] == ni)}
    repro_ok = all(v["match_lift"] and v["match_denominator"] for v in repro.values())

    # ---- 反号检测（A vs C，逐通道现算） ----
    flips = []
    for ch in F.CHANNELS:
        la = cols["A"]["channels"][ch]["lift_vs_persistence"]
        lc = cols["C"]["channels"][ch]["lift_vs_persistence"]
        if la is None or lc is None:
            continue
        if (la >= 0) != (lc >= 0):
            flips.append(ch)

    rows_out = []
    for ch in F.CHANNELS:
        row = {"channel": ch, "group": F.CHANNELS[ch][0],
               "is_formal_objective": F.CHANNELS[ch][1],
               "space": F.CHANNELS[ch][2]}
        for k in ("C", "A", "AC"):
            v = cols[k]["channels"][ch]
            p = "%s__" % k.lower()
            row[p + "lift"] = v["lift_vs_persistence"]
            row[p + "median_err"] = v["median"]
            row[p + "baseline_persistence_median"] = v["baseline_persistence_median"]
            row[p + "n_defined_holdout"] = v["n_defined_holdout"]
            row[p + "denominator_in_domain"] = v["n_in_domain_holdout"]
            row[p + "flag_basis_count"] = v["n_flag_usable_holdout"]
            row[p + "n_nondecidable"] = v["n_in_domain_holdout"] - v["n_predicted"]
            row[p + "n_predicted"] = v["n_predicted"]
            row[p + "coverage_of_in_domain"] = v["coverage_of_in_domain"]
            row[p + "n_out_of_domain_defined"] = v["n_out_of_domain_defined"]
        row["a_minus_c_lift"] = (None if (row["a__lift"] is None or row["c__lift"] is None)
                                 else row["a__lift"] - row["c__lift"])
        row["sign_flip_a_vs_c"] = ch in flips
        row["a_denominator_insufficient"] = bool(
            row["a__denominator_in_domain"] < 50 or row["a__n_predicted"] < 20)
        rows_out.append(row)

    outdir = pathlib.Path(a.out_dir)
    if not outdir.is_absolute():
        outdir = REPO / outdir
    outdir.mkdir(parents=True, exist_ok=True)

    fields = list(rows_out[0].keys())
    with (outdir / "R3_per_batch_8ch.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows_out)

    u4_out = {ch: {"lift": u4["channels"][ch]["lift_vs_persistence"],
                   "denominator_in_domain": u4["channels"][ch]["n_in_domain_holdout"],
                   "flag_basis_count": u4["channels"][ch]["n_flag_usable_holdout"],
                   "n_predicted": u4["channels"][ch]["n_predicted"]}
              for ch in UNION4_CHANNELS}

    diag = {k: {ch: rate_diag(ch, cols[k]["channels"][ch]) for ch in F.CHANNELS}
            for k in ("C", "A", "AC")}

    payload = {
        "kind": "r3_per_batch_8ch_v1",
        "seed": a.seed,
        "eval_core": {"path": str(rgsc.FITTER.relative_to(REPO)).replace("\\", "/"),
                      "sha256": sha256_file(rgsc.FITTER),
                      "reuse": ("import 既有 fit_multichannel_surrogate + "
                                "scripts/rerun_grouped_split_channels.py 的 "
                                "load_assignments/rows_ac/evaluate/leak（**未改写**）")},
        "inputs": {"labels_ac": ac_meta,
                   "assignments": {"path": str(rgsc.ASSIGN.relative_to(REPO)).replace("\\", "/"),
                                   "sha256": sha256_file(rgsc.ASSIGN)}},
        "ruling": ("按批分列：C 单批 = 8 通道**权威口径**；A 单批单列并标 **n 不足**"
                   "（4/8 通道反号随列标注）；A∪C 仍作**参考**并带可判定分母。"),
        "columns": rows_out,
        "authoritative_column": "C（单批）",
        "reference_column": "AC（A∪C，与 INDEX §95.2「禁止池化」的 O-A 条款冲突 ⇒ 只作参考/归因）",
        "a_column_warnings": {
            "n_insufficient": ("A 单批**可判定分母** `n_defined` 仅 **38–41**"
                               "（= §136 登记口径；再 ∧ 代理适用域 `5≤N2≤9 ∧ N1<N2` 后为 "
                               "**30–33**）、`n_predicted` **11–12** ⇒ "
                               "**不得单独据此下结论**（远低于 ai-solver-verification 的样本量下限口径）"),
            "measured_now": {
                "n_defined_holdout": {"bandwidth_Hz": cols["A"]["channels"]["bandwidth_Hz"]["n_defined_holdout"],
                                      "Q_factor": cols["A"]["channels"]["Q_factor"]["n_defined_holdout"],
                                      "others": cols["A"]["channels"]["abs_w_m"]["n_defined_holdout"]},
                "n_in_domain_holdout": {"bandwidth_Hz": cols["A"]["channels"]["bandwidth_Hz"]["n_in_domain_holdout"],
                                        "Q_factor": cols["A"]["channels"]["Q_factor"]["n_in_domain_holdout"],
                                        "others": cols["A"]["channels"]["abs_w_m"]["n_in_domain_holdout"]},
                "n_predicted": {"bandwidth_Hz": cols["A"]["channels"]["bandwidth_Hz"]["n_predicted"],
                                "Q_factor": cols["A"]["channels"]["Q_factor"]["n_predicted"],
                                "others": cols["A"]["channels"]["abs_w_m"]["n_predicted"]},
                "flag_basis_count": {"bandwidth_Hz": cols["A"]["channels"]["bandwidth_Hz"]["n_flag_usable_holdout"],
                                     "others": cols["A"]["channels"]["abs_w_m"]["n_flag_usable_holdout"]},
            },
            "sign_flips_vs_C": flips,
            "n_sign_flips": len(flips),
            "cause_data_absent": CAUSE_ABSENT,
            "cause_measured_now": cause_measured,
        },
        "denominator_discipline": diag,
        "self_consistency": {
            "channels_without_lift": frozen_now["channels_without_lift"],
            "model_status": frozen_now["status"],
            "solver_state": frozen_now["solver_state"],
            "unchanged": frozen_ok,
            "statement": ("`channels_without_lift` 与 `draft` **不变** ⇒ "
                          "**不得据任一口径宣布翻身**"),
        },
        "consistency_with_113_114": {
            "AC_reproduces_113_3": repro, "AC_reproduces_113_3_all": repro_ok,
            "statement": ("A∪C 列与 §113.3 登记的 lift 及可判定分母**逐位一致**；"
                          "A/C 逐批在 §114 的折依赖声明下仍**同号**（不改变 §114 的"
                          "「未翻身但折依赖 ⇒ 不稳」判定）。"),
        },
        "union4_reference_4ch": u4_out,
        "union4_note": ("UNION4 = 三批并集（4 通道，v2 缺 4 列）⇒ 只作跨管线旁证，"
                        "不进 8 通道三列表。"),
        "no_state_promotion": True,
        "not_a_solver": ("本代理只预测一阶峰标量，无场级误差界、无 L1 网格收敛 ⇒ "
                         "不得用于工程绝对值。"),
        "not_done": ["未跑多 seed（仅 seed 0，与 §136 同口径）",
                     "未做 A-only 分层切分读数（§132 只覆盖 C/AC/UNION4）",
                     "未分离「池化差」与「组成差」",
                     "未推测 A 单批反号成因（数据不存在）"],
    }
    (outdir / "R3_per_batch_8ch.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "R3_per_batch_8ch.md").write_text(render_md(payload, cols, flips, repro,
                                                          repro_ok, cause_measured),
                                                encoding="utf-8")

    print("== R3 按批分列（seed %d）==" % a.seed)
    print("%-22s %10s %10s %10s ｜ A 分母(n_pred/域内) ｜ 反号" % ("通道", "C", "A", "A∪C"))
    for r in rows_out:
        print("%-22s %+10.6g %+10.6g %+10.6g ｜ %2d/%-3d ｜ %s"
              % (r["channel"], r["c__lift"], r["a__lift"], r["ac__lift"],
                 r["a__n_predicted"], r["a__denominator_in_domain"],
                 "**反号**" if r["sign_flip_a_vs_c"] else ""))
    print("A 单批反号通道数 %d/8：%s" % (len(flips), flips))
    print("A∪C 列逐位复现 §113.3：%s（8/8 lift 与分母）" % repro_ok)
    print("判定自洽：channels_without_lift=%s status=%s solver state=%s ⇒ 不变：%s"
          % (frozen_now["channels_without_lift"], frozen_now["status"],
             frozen_now["solver_state"], frozen_ok["all"]))
    print("A 单批成因数据：%s" % cause_measured["measured_note"])
    print("产物：%s" % (outdir.relative_to(REPO) if outdir.is_relative_to(REPO) else outdir))
    if not (repro_ok and frozen_ok["all"]):
        print("[FAIL] 与 §113.3 不符或冻结判定被改动（fail-closed）")
        return EXIT_REGRESSED
    return EXIT_OK


def render_md(p: dict, cols: dict, flips: list, repro: dict, repro_ok: bool,
              cause_measured: dict) -> str:
    L = ["# R3 落表：8 通道 lift **按批分列**（C 权威 / A 单列并标 n 不足 / A∪C 参考）", "",
         "> 裁决（用户 2026-10-09，逐字）：**按批分列**：**C 单批为 8 通道权威口径**，"
         "**A 单批单列并标 n 不足**（其 4/8 通道反号必须随列标注），"
         "**A∪C 仍作参考并带可判定分母**。", "",
         "> 内核：`%s`（sha256 `%s`）—— **import 复用、未重写**；"
         "切分 = 整组切分 seed %d（与 §113/§114/§136 同一 `grouped_split_assignments.csv`）。"
         % (p["eval_core"]["path"], p["eval_core"]["sha256"][:16], p["seed"]), "",
         "## 0. 三列 8 通道表（列 = 口径，行 = 通道）", "",
         "| 通道 | 正式目标 | **C 单批（权威）** lift | C 分母（可判定/域内/n_pred/flag） | **A 单批** lift | A 分母（可判定/域内/n_pred/flag） | **A∪C（参考）** lift | A∪C 分母（可判定/域内/n_pred/flag） | A−C | A 反号？ |",
         "|---|---|---:|---|---:|---|---:|---|---:|---|"]
    for r in p["columns"]:
        L.append("| `%s` | %s | **%+0.8g** | %d / %d / %d / %d | %+0.8g | %d / %d / %d / %d | %+0.8g | %d / %d / %d / %d | %s | %s |"
                 % (r["channel"], "是" if r["is_formal_objective"] else "否",
                    r["c__lift"], r["c__n_defined_holdout"], r["c__denominator_in_domain"],
                    r["c__n_predicted"], r["c__flag_basis_count"],
                    r["a__lift"], r["a__n_defined_holdout"], r["a__denominator_in_domain"],
                    r["a__n_predicted"], r["a__flag_basis_count"],
                    r["ac__lift"], r["ac__n_defined_holdout"], r["ac__denominator_in_domain"],
                    r["ac__n_predicted"], r["ac__flag_basis_count"],
                    "—" if r["a_minus_c_lift"] is None else "%+0.6g" % r["a_minus_c_lift"],
                    "**是**" if r["sign_flip_a_vs_c"] else "否"))
    L += ["", "> **分母纪律（§116.4）**：上表每列给出**四个数** —— `可判定`（`n_defined_holdout`："
          "该通道有定义的行数；**§136 登记的「A 单批 38–41」就是这一档**）、"
          "`域内`（再 ∧ 代理适用域 `5≤N2≤9 ∧ N1<N2`；**本表与 §113.3 的 501/529 用这一档**）、"
          "`n_pred`（真正出预测的行数）、`flag`（`ranking_eligible` **标志口径计数**）。"
          "**flag 口径不当分母**；差额已在上表可现算。", "",
          "> ⚠️ 读法：A 单批 `可判定` 38–41 ≠ `域内` 30–33（A 有 `N2∈{3,4}` 落在代理适用域外，"
          "§113.1 已单列分母）⇒ **引用分母时必须写明是哪一档**，否则两个数会互相打架。", "",
          "## 1. A 列必须读的警示（**不得单独据此下结论**）", "",
          "1. **n 不足**：A 单批**可判定分母** `n_defined` 仅 **%d–%d**（∧ 代理适用域后 "
          "**%d–%d**）、`n_predicted` **%d–%d**、`flag` 口径 **%d** ⇒ "
          "远低于 `ai-solver-verification` 的样本量下限口径；"
          % (min(r["a__n_defined_holdout"] for r in p["columns"]),
             max(r["a__n_defined_holdout"] for r in p["columns"]),
             min(r["a__denominator_in_domain"] for r in p["columns"]),
             max(r["a__denominator_in_domain"] for r in p["columns"]),
             min(r["a__n_predicted"] for r in p["columns"]),
             max(r["a__n_predicted"] for r in p["columns"]),
             max(r["a__flag_basis_count"] for r in p["columns"])),
          "2. **反号**：A 单批相对 C 单批有 **%d/8 通道符号相反**：%s "
          "（正式目标 `abs_p_per_V_Pa` 也在其中）⇒ **必须随列标注**；"
          % (len(flips), "、".join("`%s`" % c for c in flips)),
          "3. **成因：数据不存在** —— %s" % p["a_column_warnings"]["cause_data_absent"]["fact"],
          "   本脚本现读 A∪C 母表表头（%d 列）：%s"
          % (cause_measured["ac_table_columns"],
             cause_measured["measured_note"].replace("本脚本现读 A∪C 母表表头：", "")),
          "   ⇒ %s" % p["a_column_warnings"]["cause_data_absent"]["rule"], "",
          "## 2. 与 §113 / §114 的自洽声明", "",
          "* **A∪C 列逐位复现 §113.3**：lift 与可判定分母 8/8 通道一致 = **%s**" % repro_ok,
          "  （脚本 `--seed 0` 与 §113.3 同一切分/同一内核；不符即 rc=3）。", "",
          "| 通道 | §113.3 登记 lift | 本轮复算 | \\|差\\| | 登记分母(可判定/域内) | 复算 | 一致 |",
          "|---|---:|---:|---:|---|---|---|"]
    for ch, v in repro.items():
        L.append("| `%s` | %+0.8g | %s | %s | %d / %d | %d / %d | %s |"
                 % (ch, v["registered_lift"],
                    "—" if v["recomputed_lift"] is None else "%+0.8g" % v["recomputed_lift"],
                    "—" if v["abs_diff"] is None else "%.1e" % v["abs_diff"],
                    v["registered_denominator"], v["registered_in_domain"],
                    v["recomputed_defined"], v["recomputed_in_domain"],
                    "**是**" if (v["match_lift"] and v["match_denominator"]) else "**否**"))
    L += ["* §113.3/§113.4 的口径（A∪C，整组切分）与 §114 的**折依赖**声明**均未被本轮改动**；"
          "§114 的判定「未翻身但结论不稳」原样有效；", "",
          "## 3. 判定自洽（**不得据任一口径宣布翻身**）", "",
          "| 项 | 现读值 | 期望（冻结） | 不变？ |", "|---|---|---|---|",
          "| `multichannel_model.json` `status` | `%s` | `draft` | %s |"
          % (p["self_consistency"]["model_status"], "**是**"
             if p["self_consistency"]["unchanged"]["status_draft"] else "**否**"),
          "| `evaluation.channels_without_lift` | `%s` | `[\"bandwidth_Hz\", \"Q_factor\"]` | %s |"
          % (p["self_consistency"]["channels_without_lift"],
             "**是**" if p["self_consistency"]["unchanged"]["channels_without_lift_unchanged"]
             else "**否**"),
          "| `solver_spec.json` `state` | `%s` | `draft` | %s |"
          % (p["self_consistency"]["solver_state"], "**是**"
             if p["self_consistency"]["unchanged"]["solver_state_draft"] else "**否**"),
          "", "⇒ %s" % p["self_consistency"]["statement"], "",
          "## 4. UNION4（4 通道）参考 —— 只作跨管线旁证，**不进 8 通道三列表**", "",
          "| 通道 | UNION4 lift | 域内分母 | flag 口径 | n_pred |", "|---|---:|---:|---:|---:|"]
    for ch, v in p["union4_reference_4ch"].items():
        L.append("| `%s` | %+0.8g | %d | %d | %d |"
                 % (ch, v["lift"], v["denominator_in_domain"], v["flag_basis_count"],
                    v["n_predicted"]))
    L += ["", "> %s" % p["union4_note"], "",
          "## 5. 分母纪律的**实测留档**（守卫原文，不修饰）", "",
          "脚本对「每通道 × 每列」构造了一条比例记录并调用 "
          "`guards_denominator.check_rate_record()`；下表给出守卫的裁定**原文**。"
          "⚠️ 本数据里 **flag 口径比可判定集更窄**（`ranking_eligible` ⊂ 域内），"
          "与守卫「标志口径 ⊇ 可判定」的假设相反 ⇒ 记录被判「两个口径矛盾」。"
          "这是**实测事实**（不是本表的失败）：本表因此**只并列两个口径、不相除**。", "",
          "| 通道 | C: 守卫裁定 | A: 守卫裁定 | A∪C: 守卫裁定 |", "|---|---|---|---|"]
    for ch in (r["channel"] for r in p["columns"]):
        cells = []
        for k in ("C", "A", "AC"):
            g = p["denominator_discipline"][k][ch]
            cells.append("域内 %d / flag %d ⇒ %s"
                         % (g["record_two_calibers"]["denominator"],
                            g["record_two_calibers"]["flag_basis_count"],
                            "合格" if not g["guard_verdict_on_raw_record"]
                            else "判不合格（%s）" % g["guard_verdict_on_raw_record"][0][:70]))
        L.append("| `%s` | %s | %s | %s |" % (ch, cells[0], cells[1], cells[2]))
    L += ["", "## 6. 未做 / 没做成（如实）", ""]
    for x in p["not_done"]:
        L.append("* %s" % x)
    L += ["", "**一句话确认**：本表**按批分列**、**不改判定语义**（`channels_without_lift` 与 "
          "`draft` 不变）、**未删任何行**、**未提升状态**、**未跑 COMSOL**、"
          "**未据任一口径宣布翻身**。", ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
