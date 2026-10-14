# -*- coding: utf-8 -*-
"""裁定 §7 要求的**跨批一致性固定 5 项报告**（R-CB-N28）。

裁定 §7 原文要求该报告**固定包含 5 项**：
  ① 20 MHz 标量误差；② 频谱误差 median/p90/max；③ 最差组合及其参数；
  ④ 逐组合误差排名；⑤ 异常点是否被隔离。

此前的情况：①②③⑤ 散落在 `A6_ROUND6_RESULT.md` 里，**④ 完全没有产物**
（结果 JSON 只有聚合分位数，没有逐组合误差）。本脚本把它补成**一份固定格式**的报告。

设计要点：
* **不修改任何已预注册的脚本**（它们的 sha256 被留档）。改为 `importlib` 加载
  `a6_round5_eval.py` / `a6_round6_eval.py` 并复用其 `MODELS` / `target_of` / `fold_rcb_n28`，
  从而**保证模型定义与判定口径与历史轮次逐字一致**，不重新实现。
* 逐组合误差由**同一批预测**直接得出（`P[:, -2] - Yte[:, -2]`，即 20 MHz 的 SPL 差），
  因此 ④ 与 ①② 天然自洽；脚本还会**回算 ①** 并与历史 JSON 对照，不一致就报错（fail-closed）。
* 任何一项拿不到就写 `not_available` 且**说明原因**，绝不编数。

用法：
    python -B work/tools/cross_batch_consistency_report.py
产物：
    work/runs/x-densify-20260928/a6/CROSS_BATCH_CONSISTENCY_R-CB-N28.md
    work/runs/x-densify-20260928/a6/cross_batch_consistency_R-CB-N28.json
    work/runs/x-densify-20260928/a6/per_combo_R-CB-N28.csv
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import pathlib
import sys

import numpy as np

REPO = pathlib.Path(__file__).resolve().parents[2]
A6 = REPO / "work/runs/x-densify-20260928/a6"
RESULT_JSON = A6 / "a6_round6_result.json"
OUT_MD = A6 / "CROSS_BATCH_CONSISTENCY_R-CB-N28.md"
OUT_JSON = A6 / "cross_batch_consistency_R-CB-N28.json"
OUT_CSV = A6 / "per_combo_R-CB-N28.csv"

FOLD_KEY = "R-CB-N28"
#: R-CB-N28 折按设计只用 B3-G（最近邻）作口径一致性检查
RCB_MODELS = ["B3-G"]
#: 输出名由 `--out-prefix` 派生（默认前缀 = `R-CB-N28` ⇒ **不传参时逐字节复现历史产物**）


def _set_outputs(prefix: str) -> None:
    """按前缀重定向三份产物；供 `te2_9` 等**将来的折**复用同一模板。

    为什么要把输出名参数化：模板本来是好的，但输出路径写死了 `R-CB-N28`，
    下一批数据（N2=9）到达时只能改代码 ⇒ 改代码就有偏离预注册的风险。
    """
    global OUT_MD, OUT_JSON, OUT_CSV
    OUT_MD = A6 / ("CROSS_BATCH_CONSISTENCY_%s.md" % prefix)
    OUT_JSON = A6 / ("cross_batch_consistency_%s.json" % prefix)
    OUT_CSV = A6 / ("per_combo_%s.csv" % prefix)


_set_outputs("R-CB-N28")


def load_mod(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def per_combo(r5, models, trk2, Ytr, tek2, Yte):
    """跑模型并返回**逐组合**误差（与 `run_fold` 同一套模型函数与目标列）。"""
    out = {}
    for m in models:
        fn = r5.MODELS.get(m)
        if fn is None:
            out[m] = {"error": "未知模型 %s（不在冻结的 MODELS 里）" % m}
            continue
        P, na = fn(trk2, Ytr, tek2)
        mask = ~na if na is not None else np.ones(len(P), bool)
        idx = [i for i in range(len(P)) if mask[i]]
        rows = []
        for i in idx:
            e_spl = float(P[i, -2] - Yte[i, -2])          # 20 MHz SPL 有符号差（主指标）
            d_spec = np.abs(P[i, :-2] - Yte[i, :-2])      # 逐频点 |ΔdB|
            rows.append({
                "model": m,
                "x_scale": tek2[i][0], "N_w_te1": tek2[i][1], "N_w_te2": tek2[i][2],
                "dSPL20_dB": e_spl,
                "abs_dSPL20_dB": abs(e_spl),
                "spec_median_abs_dB": float(np.median(d_spec)),
                "spec_max_abs_dB": float(np.max(d_spec)),
            })
        out[m] = {"n_used": len(rows), "not_applicable": int(len(P) - mask.sum()),
                  "rows": sorted(rows, key=lambda r: -r["abs_dSPL20_dB"])}
    return out


def main(argv=None) -> int:
    global FOLD_KEY, RCB_MODELS
    ap = argparse.ArgumentParser(
        description="按裁定 §7 生成**固定 5 项**的跨批一致性报告（模板可复用）")
    ap.add_argument("--fold", default=FOLD_KEY,
                    help="要在结果 JSON 里匹配的折关键字（默认 %s）" % FOLD_KEY)
    ap.add_argument("--models", default=",".join(RCB_MODELS),
                    help="参与对照的模型（逗号分隔，默认 %s）" % ",".join(RCB_MODELS))
    ap.add_argument("--out-prefix", default=FOLD_KEY,
                    help="三份产物的文件名前缀（默认 %s）" % FOLD_KEY)
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    FOLD_KEY = args.fold
    RCB_MODELS = [m.strip() for m in args.models.split(",") if m.strip()]
    _set_outputs(args.out_prefix)
    if not RESULT_JSON.is_file():
        print("[FAIL] 缺历史结果：%s" % RESULT_JSON)
        return 2
    hist = json.loads(RESULT_JSON.read_text(encoding="utf-8"))
    # 折不存在时要**说清楚**（例如 `te2_9` 数据还没到），不要产出一份空报告
    if not any(FOLD_KEY in f.get("fold", "") for f in hist.get("folds", [])):
        print("[FAIL] 结果 JSON 里没有含 %r 的折；现有折：%s"
              % (FOLD_KEY, [f.get("fold", "")[:40] for f in hist.get("folds", [])]))
        print("       （数据未到/折名写错时会出现这种情况；本模板不做猜测。）")
        return 4

    r5 = load_mod("a6_r5", A6 / "a6_round5_eval.py")
    r6 = load_mod("a6_r6", A6 / "a6_round6_eval.py")
    r5.MODELS.update(r6.NEW_MODELS)
    m2 = r5.m2                                            # 判定协议模块（metric_protocol_v2）

    d_all = r6.load_all()
    dq = {k: v for k, v in d_all.items() if k != r6.QUARANTINE}
    A = r5.load_a()
    trk, tek = r6.fold_rcb_n28(A, dq)

    # 与 run_fold 同口径地准备训练/测试矩阵（含 NA 过滤）
    tr = {k: t for k in trk if (t := r5.target_of(A[k])) is not None}
    te = {k: t for k in tek if (t := r5.target_of(dq[k])) is not None}
    trk2, tek2 = sorted(tr), sorted(te)
    Ytr = np.array([np.append(tr[k][2], [tr[k][0], tr[k][1]]) for k in trk2])
    Yte = np.array([np.append(te[k][2], [te[k][0], te[k][1]]) for k in tek2])

    pc = per_combo(r5, RCB_MODELS, trk2, Ytr, tek2, Yte)

    # ---------- ① 20 MHz 标量误差：回算并与历史 JSON 对照 ----------
    hist_fold = next((f for f in hist["folds"] if FOLD_KEY in f["fold"]), None)
    if hist_fold is None:
        print("[FAIL] 历史 JSON 里找不到 %s 折" % FOLD_KEY)
        return 3
    item1 = {"source": "回算（用冻结 MODELS 重跑同一折）", "models": {}}
    mismatch = []
    for m, d in pc.items():
        if "rows" not in d:
            continue
        e = np.abs([r["dSPL20_dB"] for r in d["rows"]])
        st = m2.db_error_stats(e)
        item1["models"][m] = st
        ref = hist_fold["models"].get(m, {}).get("spl20_abs_dB")
        if ref:
            for k in ("median", "p90", "max"):
                if k in ref and abs(float(ref[k]) - float(st[k])) > 1e-9:
                    mismatch.append("%s.%s 回算 %.6g ≠ 历史 %.6g" % (m, k, st[k], ref[k]))
    item1["recompute_matches_history"] = (not mismatch)
    item1["mismatch"] = mismatch

    # ---------- ② 频谱误差 median/p90/max（取历史 JSON 的 spectrum 段） ----------
    item2 = {"source": "历史 JSON `spectrum`（同一折、同一模型）", "models": {}}
    for m in RCB_MODELS:
        sp = hist_fold["models"].get(m, {}).get("spectrum")
        item2["models"][m] = sp if sp else {"not_available": "历史 JSON 无 spectrum 段"}

    # ---------- ③ 最差组合及其参数（取自 ④ 的排序首位） ----------
    item3 = {"source": "由逐组合 ① 排序得到", "models": {}}
    for m, d in pc.items():
        if "rows" in d and d["rows"]:
            w = d["rows"][0]
            item3["models"][m] = {
                "worst": {k: w[k] for k in ("x_scale", "N_w_te1", "N_w_te2")},
                "abs_dSPL20_dB": w["abs_dSPL20_dB"], "dSPL20_dB": w["dSPL20_dB"],
                "spec_max_abs_dB": w["spec_max_abs_dB"],
                "top5": [{k: r[k] for k in ("x_scale", "N_w_te1", "N_w_te2",
                                            "abs_dSPL20_dB")} for r in d["rows"][:5]],
            }
        else:
            item3["models"][m] = {"not_available": "该模型无可用预测点"}

    # ---------- ④ 逐组合误差排名（**此前完全缺失**，本次补上） ----------
    all_rows = []
    for m, d in pc.items():
        all_rows += d.get("rows", [])
    with OUT_CSV.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.DictWriter(fh, fieldnames=["model", "rank", "x_scale", "N_w_te1", "N_w_te2",
                                          "abs_dSPL20_dB", "dSPL20_dB",
                                          "spec_median_abs_dB", "spec_max_abs_dB"],
                           extrasaction="ignore")
        w.writeheader()
        rk = {}
        for row in sorted(all_rows, key=lambda r: -r["abs_dSPL20_dB"]):
            rk[row["model"]] = rk.get(row["model"], 0) + 1
            row = dict(row); row["rank"] = rk[row["model"]]
            w.writerow(row)
    _abs = sorted(r["abs_dSPL20_dB"] for r in all_rows)
    item4 = {"source": "本脚本由同一批预测逐点算出（新增）",
             "csv": str(OUT_CSV.relative_to(REPO)).replace("\\", "/"),
             "n_rows": len(all_rows),
             "quantiles_of_abs_dSPL20_dB": ({
                 "median": float(np.median(_abs)),
                 "p90": float(np.percentile(_abs, 90)),
                 "max": float(_abs[-1])} if _abs else None)}

    # ---------- ⑤ 异常点是否被隔离 ----------
    # ⚠️ `r6.QUARANTINE` 是**单个**组合（主统计排除的那一个）；
    # 两个角点的完整集合在 `r6.POSTHOC_CORNER`（事后同时排除用）。
    q = [r6.QUARANTINE]
    q_all = sorted(set(q) | set(r6.POSTHOC_CORNER))
    q_in_test = [list(k) for k in tek2 if k in set(q_all)]
    item5 = {
        "main_exclusion": [list(k) for k in q],
        "corner_pair_posthoc": [list(k) for k in r6.POSTHOC_CORNER],
        "main_fold_excludes_them": True,
        "present_in_r_cb_test_set": q_in_test,
        "isolation_effect": "见 `sensitivity_with_quarantined`（把隔离点放回训练集）与"
                            " `sensitivity_posthoc_excl_corner`（事后同时排除两角点）",
        "with_quarantined_fold": [f["fold"] for f in hist.get("sensitivity_with_quarantined", [])],
        "note": ("隔离组合是**跨批比对中异常**的角点；它们是否出现在本折测试集决定了本折是否受影响。"
                 "本折（同参数跨批）测试集为 te2_8 的坐标，若含角点则须在报告中标出。"),
    }

    out = {
        "kind": "cross_batch_consistency_report",
        "ruling": "裁定 §7：跨批一致性报告固定 5 项",
        "fold": hist_fold["fold"], "batch_pair": "批 A 的 N2=8 ↔ te2_8 同坐标",
        "is_generalization_test": False,
        "nature_note": "同参数跨批（按设计）；**不是泛化测试**，只作重复性/口径一致性检查",
        "protocol": hist.get("protocol"), "data_version": hist.get("data_version"),
        "n_train": len(trk2), "n_test": len(tek2),
        "items": {"1_scalar_20MHz": item1, "2_spectrum": item2, "3_worst_combo": item3,
                  "4_per_combo_ranking": item4, "5_quarantine": item5},
        "coverage": {},
    }
    gaps = []
    if not item1["recompute_matches_history"]:
        gaps.append("① 回算与历史 JSON 不一致：%s" % mismatch)
    if not isinstance(item2["models"].get("B3-G"), dict) or \
            "not_available" in item2["models"].get("B3-G", {}):
        gaps.append("② 历史 JSON 无 spectrum 段")
    if item4["n_rows"] == 0:
        gaps.append("④ 无逐组合行")
    out["coverage"] = {
        "1": "ok", "2": "ok" if not any("②" in g for g in gaps) else "缺",
        "3": "ok", "4": "ok" if item4["n_rows"] else "缺", "5": "ok",
    }
    out["gaps"] = gaps
    out["verdict"] = ("**5 项齐备**（①回算与历史一致）" if not gaps
                      else "**有 %d 项未满足**：%s" % (len(gaps), gaps))
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- 渲染 markdown ----------
    L = []
    L.append("# 跨批一致性报告（R-CB-N28）— 按裁定 §7 固定 5 项")
    L.append("")
    L.append("> 折：%s" % hist_fold["fold"])
    L.append("> 性质：**同参数跨批，不是泛化测试**，只作重复性/口径一致性检查")
    L.append("> 训练 %d / 测试 %d ｜ 协议 %s ｜ 数据版本 %s"
             % (len(trk2), len(tek2), hist.get("protocol"), hist.get("data_version")))
    L.append("> 由 `work/tools/cross_batch_consistency_report.py` 生成（复用冻结的评估模块，"
             "不修改预注册脚本）")
    L.append("")
    L.append("## ① 20 MHz 标量误差（dB，绝对误差分位数）")
    L.append("")
    L.append("| 模型 | n | NA | 中位 | p90 | p99 | max | >0.5dB | >1dB | 回算=历史 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for m, st in item1["models"].items():
        L.append("| **%s** | %d | %d | %.4f | %.4f | %.4f | %.4f | %.1f%% | %.1f%% | %s |"
                 % (m, st["n"], st["n_not_applicable"] if "n_not_applicable" in st else pc[m]["not_applicable"],
                    st["median"], st["p90"], st.get("p99", float("nan")), st["max"],
                    100 * st.get("frac_gt_0p5", float("nan")), 100 * st.get("frac_gt_1", float("nan")),
                    "是" if item1["recompute_matches_history"] else "**否**"))
    L.append("")
    L.append("## ② 频谱误差 median / p90 / max")
    L.append("")
    for m, sp in item2["models"].items():
        L.append("* `%s`：`%s`" % (m, json.dumps(sp, ensure_ascii=False)))
    L.append("")
    L.append("## ③ 最差组合及其参数")
    L.append("")
    for m, d in item3["models"].items():
        if "worst" in d:
            w = d["worst"]
            L.append("* `%s` 最差 `(x=%g, N1=%g, N2=%g)`：|ΔSPL@20MHz| = **%.4f dB**"
                     "（有符号 %.4f），谱内 max |Δ| = %.4f dB"
                     % (m, w["x_scale"], w["N_w_te1"], w["N_w_te2"],
                        d["abs_dSPL20_dB"], d["dSPL20_dB"], d["spec_max_abs_dB"]))
        else:
            L.append("* `%s`：%s" % (m, d.get("not_available")))
    L.append("")
    L.append("## ④ 逐组合误差排名（**此前缺失，本轮补上**）")
    L.append("")
    L.append("完整表：`%s`（%d 行，按 |ΔSPL@20MHz| 降序，含谱内 max |Δ|）"
             % (item4["csv"], item4["n_rows"]))
    L.append("")
    L.append("## ⑤ 异常点是否被隔离")
    L.append("")
    L.append("* 主统计排除的组合：%s" % "、".join("`(x=%g,N1=%g,N2=%g)`" % tuple(k)
                                                  for k in item5["main_exclusion"]))
    L.append("* 事后同时排除的角点对：%s" % "、".join("`(x=%g,N1=%g,N2=%g)`" % tuple(k)
                                                      for k in item5["corner_pair_posthoc"]))
    L.append("* 本折测试集中出现的异常点：%s"
             % ("、".join("`(x=%g,N1=%g,N2=%g)`" % tuple(k) for k in q_in_test) or "**无**（本折不受其影响）"))
    L.append("* 敏感性对照：%s" % "；".join(item5["with_quarantined_fold"]) or "无")
    L.append("")
    L.append("## 判定")
    L.append("")
    L.append(out["verdict"])
    if gaps:
        for g in gaps:
            L.append("* ⚠️ %s" % g)
    L.append("")
    L.append("> ⚠️ 本报告**不外推为泛化能力**：同参数跨批折的用途是口径一致性/重复性；"
             "泛化能力见 `A6_ROUND6_RESULT.md` 的 `L-N2ex(8)` 主判定折。")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print("已生成：")
    for p in (OUT_MD, OUT_JSON, OUT_CSV):
        print("   %s（%d B）" % (p.relative_to(REPO), p.stat().st_size))
    print("① 回算与历史一致：", item1["recompute_matches_history"], item1["mismatch"] or "")
    print("④ 逐组合行数：", item4["n_rows"])
    print("判定：", out["verdict"])
    return 0 if not gaps else 1


if __name__ == "__main__":
    sys.exit(main())
