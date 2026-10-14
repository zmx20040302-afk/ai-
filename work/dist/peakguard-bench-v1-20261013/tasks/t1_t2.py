# -*- coding: utf-8 -*-
"""T1（峰身份）/ T2（带宽闭合）的评测（**零 COMSOL 求解**）。

本件是自包含基准包里的一个任务脚本（放在包的 `tasks/` 下），**只读包内相对路径**：

  * 语料 = `data/channels_multichannel.csv` 中 A/C 两批的**原生标志**（2,005 行），V2 排除；
  * 特征只用 (x, N1, N2)；分组拆分沿用 `data/splits_grouped_five_seeds.csv` 的冻结指派；
  * 行索引回接用 `data/labels_two_batch_v3.csv`（2,255 行并集标签表）；
  * 三个模型：majority / knn1 / hgb(5 种子)；
  * 逐状态 recall 全报；拒答覆盖率与被接受子集精度**并置**；命中 DR1 不写通过。

输出 `results/T1_T2_RESULT.json`。

口径冻结：原件的预注册件（PREREG_T1_T2_T5.json）不随包发布，故
  (a) 其**文件名与 sha256** 按注册读数原样内联为 `PREREG` 常量，写进输出的 `prereg` 块；
  (b) 其中**可核查**的部分固化为 `EXPECTED_CORPUS` 断言——语料规模、五类状态计数与输入表
      批次构成不符即停（fail-closed）。

`results/baselines_by_seed.json` 与 `results/M3_RESULT.json` 只用于记录**输入 sha256**（溯源），
不参与任何数值计算；两者缺失时记为 null 并在 stdout 给出警告。
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import statistics
import sys
import time

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _text  # noqa: E402  （自由文本的英文渲染表；见其 docstring）
PKG = HERE.parent
DATA = PKG / "data"
RESULTS = PKG / "results"
AC = DATA / "channels_multichannel.csv"
ASSIGN = DATA / "splits_grouped_five_seeds.csv"
V3 = DATA / "labels_two_batch_v3.csv"
N2REG = RESULTS / "baselines_by_seed.json"
M3REG = RESULTS / "M3_RESULT.json"
OUT = RESULTS / "T1_T2_RESULT.json"
SEEDS = (0, 1, 2, 3, 4)
STATES = ("complete", "unclosed", "truncated", "censored", "no_peak")

# 冻结语料事实（来源 = 注册读数 results/T1_T2_RESULT.json 的 corpus 块 + 输入表的批次构成）。
EXPECTED_CORPUS = {"n_rows": 2005,
                   "state_counts": {"complete": 1677, "no_peak": 232, "unclosed": 96},
                   # 渠道表（原生标志）只含 A/C 两批：
                   "channels_batches": {"A": 223, "C": 1782},
                   # 并集标签表 2,255 行 = 2,005（A/C）+ 250（V2 代理标志，不参与）：
                   "v3_rows": 2255,
                   "v3_batches": {"A_5-35MHz": 223, "C_5-50MHz": 1782, "V2_5-35MHz": 250}}

# 预注册件的名与 sha256：**按注册读数原样内联**（该件不随包发布；与注册输出逐字相同）。
PREREG = {"file": "PREREG_T1_T2_T5.json",
          "sha256": "85afa8abbec347ba2fe03cc03593123af8e0bb68c868fb72a19d9ed4bf6ecb5b"}


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rel(p: pathlib.Path) -> str:
    """包内相对路径（POSIX 分隔符）——只写进溯源块，不参与数值。"""
    return str(p.relative_to(PKG)).replace("\\", "/")


def input_sha(p: pathlib.Path):
    """溯源用 sha256；该件缺失时返回 None（它不参与任何数值计算）。"""
    if not p.exists():
        print("警告：缺少输入 %s ⇒ 其 sha256 记为 null（不影响任何数值）" % rel(p))
        return None
    return sha(p)


def truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "y", "t")


def state_of(r: dict) -> str:
    """按预注册优先级映射（高者先判）。"""
    if not truthy(r.get("first_peak_found")):
        return "no_peak"
    if truthy(r.get("peak_at_scan_endpoint")):
        return "censored"
    if truthy(r.get("bw_upper_cutoff_at_endpoint")):
        return "truncated"
    if not truthy(r.get("bandwidth_closed")):
        return "unclosed"
    return "complete"


def batch_frame() -> tuple:
    """渠道表（原生标志）与并集标签表的批次计数——用于冻结断言。

    V2（代理标志）只出现在并集标签表与冻结拆分里，不在渠道表里，也不参与本评测。
    """
    ch = collections.Counter()
    with AC.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            ch[str(r.get("source_dataset", "")).strip()] += 1
    v3c = collections.Counter()
    n_v3 = 0
    with V3.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            n_v3 += 1
            v3c[r["batch"]] += 1
    return dict(ch), n_v3, dict(v3c)


def load_rows():
    """A/C 两批 + 冻结拆分的 side；只用原生标志。"""
    for p in (ASSIGN, V3, AC):
        if not p.exists():
            raise SystemExit("缺少包内数据文件：%s" % rel(p))
    with ASSIGN.open(encoding="utf-8-sig", newline="") as fh:
        side = {int(r["row_index"]): {s: r["side_seed%d" % s] for s in SEEDS}
                for r in csv.DictReader(fh)}
    with V3.open(encoding="utf-8-sig", newline="") as fh:
        v3 = list(csv.DictReader(fh))
    rows = []
    with AC.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            ds = str(r.get("source_dataset", "")).strip()
            if ds not in ("A", "C"):
                continue
            try:
                x, n1, n2 = float(r["x_scale"]), int(float(r["N_w_te1"])), int(float(r["N_w_te2"]))
            except Exception:
                continue
            rows.append({"batch": "A_5-35MHz" if ds == "A" else "C_5-50MHz",
                         "x": x, "n1": n1, "n2": n2,
                         "state": state_of(r), "closed": truthy(r.get("bandwidth_closed")),
                         "row_index": None})
    # 把行索引接回（v3 与 AC 的 A/C 部分同序同键）
    idx_by_key = {}
    for i, r in enumerate(v3):
        if r["batch"] in ("A_5-35MHz", "C_5-50MHz"):
            idx_by_key[(r["batch"], round(float(r["x_scale"]), 6),
                        int(float(r["N_w_te1"])), int(float(r["N_w_te2"])))] = i
    miss = 0
    for r in rows:
        k = (r["batch"], round(r["x"], 6), r["n1"], r["n2"])
        r["row_index"] = idx_by_key.get(k)
        if r["row_index"] is None:
            miss += 1
    assert miss == 0, "%d 行在 v3 里找不到索引 ⇒ 停" % miss
    for r in rows:
        r["side"] = side[r["row_index"]]
    return rows


def norm_feats(rows):
    X = np.array([[r["x"], r["n1"], r["n2"]] for r in rows], float)
    lo, hi = X.min(axis=0), X.max(axis=0)
    return (X - lo) / np.maximum(hi - lo, 1e-12)


def domain_pairs(train):
    return {(r["n1"], r["n2"]) for r in train}


def metrics(y_true, y_pred, classes):
    n = len(y_true)
    acc = sum(1 for a, b in zip(y_true, y_pred) if a == b) / n if n else None
    rec = {}
    for c in classes:
        idx = [i for i, v in enumerate(y_true) if v == c]
        rec[c] = (sum(1 for i in idx if y_pred[i] == c) / len(idx)) if idx else None
    present = [c for c in classes if rec[c] is not None]
    bal = (sum(rec[c] for c in present) / len(present)) if present else None
    return {"n": n, "accuracy": acc, "balanced_accuracy": bal, "per_class_recall": rec}


def knn1_predict(P, tr_idx, te_idx, y_pool):
    pred = []
    for i in te_idx:
        d = [float(np.sum((P[i] - P[j]) ** 2)) for j in tr_idx]
        pred.append(y_pool[tr_idx[int(np.argmin(d))]])
    return pred


def main() -> int:
    t0 = time.time()
    rows = load_rows()
    got_counts = dict(collections.Counter(r["state"] for r in rows))
    if len(rows) != EXPECTED_CORPUS["n_rows"] or got_counts != EXPECTED_CORPUS["state_counts"]:
        raise SystemExit("冻结语料断言失败：n_rows=%d（期望 %d），state_counts=%s（期望 %s）"
                         % (len(rows), EXPECTED_CORPUS["n_rows"], got_counts,
                            EXPECTED_CORPUS["state_counts"]))
    ch, n_v3, v3c = batch_frame()
    if ch != EXPECTED_CORPUS["channels_batches"] or n_v3 != EXPECTED_CORPUS["v3_rows"]:
        raise SystemExit("冻结输入断言失败：channels_batches=%s（期望 %s），v3_rows=%d（期望 %d）"
                         % (ch, EXPECTED_CORPUS["channels_batches"], n_v3, EXPECTED_CORPUS["v3_rows"]))
    if v3c != EXPECTED_CORPUS["v3_batches"]:
        raise SystemExit("冻结输入断言失败：v3_batches=%s（期望 %s）"
                         % (v3c, EXPECTED_CORPUS["v3_batches"]))
    v2 = {k: v for k, v in v3c.items() if k not in ("A_5-35MHz", "C_5-50MHz")}
    if not v2:
        raise SystemExit("并集标签表里没有 V2 代理标志批 ⇒ 停：读到的不是预期输入")
    checks = ["n_rows==%d" % EXPECTED_CORPUS["n_rows"],
              "state_counts==%s" % json.dumps(EXPECTED_CORPUS["state_counts"], ensure_ascii=False, sort_keys=True),
              "channels_batches==%s（原生标志只含 A/C）" % json.dumps(ch, ensure_ascii=False, sort_keys=True),
              "v3_rows==%d，v3_batches==%s（V2 代理标志不参与）"
              % (n_v3, json.dumps(v3c, ensure_ascii=False, sort_keys=True))]
    P = norm_feats(rows)
    print("语料：%d 行（A/C 原生标志）；状态分布 = %s"
          % (len(rows), json.dumps(dict(collections.Counter(r["state"] for r in rows)), ensure_ascii=False)))
    print("闭合分布 = %s" % json.dumps(dict(collections.Counter(r["closed"] for r in rows)), ensure_ascii=False))

    tasks = {"T1_state": [r["state"] for r in rows],
             "T2_closed": ["closed" if r["closed"] else "open" for r in rows]}
    labels = [r["state"] for r in rows]
    out = {"kind": "ai11_t1_t2_result", "created_local": "2026-10-13",
           "prereg": dict(PREREG),
           "frozen_assertions_checked": checks,
           "inputs": {rel(AC): sha(AC), rel(ASSIGN): sha(ASSIGN),
                      rel(N2REG): input_sha(N2REG), rel(M3REG): input_sha(M3REG)},
           "corpus": {"n_rows": len(rows),
                      "state_counts": dict(collections.Counter(labels)),
                      "excluded": "V2_5-35MHz（代理标志）"},
           "T1": {}, "T2": {}, "verdicts": {}}

    from sklearn.ensemble import HistGradientBoostingClassifier
    for tname, y in tasks.items():
        classes = sorted(set(y))
        per_batch = {}
        for b in ("A_5-35MHz", "C_5-50MHz"):
            bidx = [i for i, r in enumerate(rows) if r["batch"] == b]
            res = {"classes": classes, "by_seed": {}}
            for s in SEEDS:
                tr = [i for i in bidx if rows[i]["side"][s] == "train"]
                ho = [i for i in bidx if rows[i]["side"][s] == "holdout"]
                dom = domain_pairs([rows[i] for i in tr])
                acc_idx = [i for i in ho if (rows[i]["n1"], rows[i]["n2"]) in dom]
                ref = [i for i in ho if (rows[i]["n1"], rows[i]["n2"]) not in dom]
                y_tr = [y[i] for i in tr]
                maj = collections.Counter(y_tr).most_common(1)[0][0]
                y_te = [y[i] for i in acc_idx]
                preds = {"majority": [maj] * len(acc_idx),
                         "knn1": knn1_predict(P, tr, acc_idx, y),
                         "hgb": None}
                clf = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08,
                                                     random_state=s)
                clf.fit(P[tr], y_tr)
                preds["hgb"] = list(clf.predict(P[acc_idx]))
                res["by_seed"][str(s)] = {
                    "n_train": len(tr), "n_holdout": len(ho),
                    "n_accepted": len(acc_idx), "n_refused": len(ref),
                    "coverage_of_holdout": len(acc_idx) / len(ho) if ho else None,
                    "models": {m: metrics(y_te, p, classes) for m, p in preds.items() if p is not None}}
            # 跨种子中位
            agg = {}
            for m in ("majority", "knn1", "hgb"):
                agg[m] = {
                    "acc_median": statistics.median([res["by_seed"][str(s)]["models"][m]["accuracy"]
                                                     for s in SEEDS]),
                    "bal_median": statistics.median([res["by_seed"][str(s)]["models"][m]["balanced_accuracy"]
                                                     for s in SEEDS]),
                    "per_class_recall_median": {
                        c: statistics.median([res["by_seed"][str(s)]["models"][m]["per_class_recall"][c]
                                              for s in SEEDS
                                              if res["by_seed"][str(s)]["models"][m]["per_class_recall"][c] is not None])
                        for c in classes},
                    "coverage_median": statistics.median([res["by_seed"][str(s)]["coverage_of_holdout"]
                                                          for s in SEEDS])}
            res["across_seeds"] = agg
            per_batch[b] = res
        out[tname.split("_")[0]] = per_batch

    # ---- 预注册判定
    for tname, key in (("T1", "T1"), ("T2", "T2")):
        v = {}
        for b, res in out[key].items():
            h, m = res["across_seeds"]["hgb"], res["across_seeds"]["majority"]
            zero = [c for c, r in h["per_class_recall_median"].items() if r == 0.0]
            v[b] = {"DR1_hgb_le_majority": bool(h["bal_median"] <= m["bal_median"]),
                    "DR1_detail": {"hgb_bal_median": h["bal_median"], "majority_bal_median": m["bal_median"]},
                    "DR2_states_never_predicted": zero,
                    "DR3_coverage_median": h["coverage_median"],
                    "reading": ("**该状态不能仅由 (x,N1,N2) 预测**（hgb 的平衡精度未超过多数类基线）"
                                if h["bal_median"] <= m["bal_median"]
                                else "hgb 的平衡精度高于多数类基线（但仍须看逐状态 recall）")}
        out["verdicts"][tname] = v

    RESULTS.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes((json.dumps(_text.to_en(out), ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8"))
    print("已写 %s" % rel(OUT))

    # ---- 人读摘要（原来另写 T1_T2_REPORT.md；包内不再落 md，改为打到 stdout）
    print("\n任务  批            模型       acc中位   bal中位   拒答覆盖")
    for key in ("T1", "T2"):
        for b, res in out[key].items():
            for m in ("majority", "knn1", "hgb"):
                a = res["across_seeds"][m]
                print("  %s  %-11s  %-8s  %.4f   %.4f    %.4f"
                      % (key, b, m, a["acc_median"], a["bal_median"], a["coverage_median"]))
    print("T1/T2 完成（%.1f s）" % (time.time() - t0))
    for t, v in out["verdicts"].items():
        for b, d in v.items():
            print("  %s %-11s hgb_bal=%.4f vs maj=%.4f  DR1=%s  zero-recall=%s"
                  % (t, b, d["DR1_detail"]["hgb_bal_median"], d["DR1_detail"]["majority_bal_median"],
                     d["DR1_hgb_le_majority"], d["DR2_states_never_predicted"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
