# -*- coding: utf-8 -*-
"""T1/T2 的**泄漏敏感性对照臂**（块留出 / spacing-disjoint，仅 C 批）—— 零求解。

本件是自包含基准包里的一个任务脚本（放在包的 `tasks/` 下），**只读包内相对路径**。
复用同目录 `t1_t2.py` 的装载与指标函数（不重写口径）——用普通的 `import t1_t2`，
因此本件必须与 `t1_t2.py` 同目录（包内即 `tasks/`）。

输入 `results/T1_T2_RESULT.json`（由 `tasks/t1_t2.py` 产生）；输出 `results/T1_T2_SPACING_RESULT.json`。
口径冻结：原件的预注册件（PREREG_T1_T2_SPACING_ADDENDUM.json）不随包发布，故
  (a) 其**文件名与 sha256** 按注册读数原样内联为 `PREREG` 常量，写进输出的 `prereg` 块；
  (b) 块定义（BLOCK / BLOCKS_HELD）与「块留出对 5 个种子完全一致」固化为断言（fail-closed）。
"""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import statistics
import sys
import time

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent
RESULTS = PKG / "results"
REG_RESULT = RESULTS / "T1_T2_RESULT.json"
OUT = RESULTS / "T1_T2_SPACING_RESULT.json"

if str(HERE) not in sys.path:          # 同目录导入（脚本被从别处拉起时也成立）
    sys.path.insert(0, str(HERE))
import t1_t2  # noqa: E402  （纯函数式模块，import 无副作用）
import _text  # noqa: E402  （自由文本的英文渲染表；见其 docstring）

BLOCK = 5
BLOCKS_HELD = (1, 4, 7)
EXPECTED_GAP_ROWS = 330               # 来源 = 注册读数 results/T1_T2_SPACING_RESULT.json 的 spacing_check.n

# 预注册件的名与 sha256：**按注册读数原样内联**（该件不随包发布；与注册输出逐字相同）。
PREREG = {"file": "PREREG_T1_T2_SPACING_ADDENDUM.json",
          "sha256": "137ed9361d86b37c227be3b6fc710c535f967b8a3f3ea5c56d71bc40bb4b2095"}


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rel(p: pathlib.Path) -> str:
    return str(p.relative_to(PKG)).replace("\\", "/")


def main() -> int:
    t0 = time.time()
    if not REG_RESULT.exists():
        raise SystemExit("缺少 %s ⇒ 请先运行 tasks/t1_t2.py" % rel(REG_RESULT))
    reg = json.loads(REG_RESULT.read_text(encoding="utf-8"))
    rows = t1_t2.load_rows()
    P = t1_t2.norm_feats(rows)
    from sklearn.ensemble import HistGradientBoostingClassifier

    # ---- 构造块留出（仅 C 批，逐 (N1,N2) 元胞）
    cells = collections.defaultdict(list)
    for i, r in enumerate(rows):
        if r["batch"] == "C_5-50MHz":
            cells[(r["n1"], r["n2"])].append(i)
    splits = {s: {"train": [], "holdout": []} for s in t1_t2.SEEDS}
    for key, idxs in sorted(cells.items()):
        idxs = sorted(idxs, key=lambda i: rows[i]["x"])
        nb = (len(idxs) + BLOCK - 1) // BLOCK
        for bi in range(nb):
            chunk = idxs[bi * BLOCK:(bi + 1) * BLOCK]
            side = "holdout" if bi in BLOCKS_HELD else "train"
            for i in chunk:
                for s in t1_t2.SEEDS:            # 块留出对 5 个种子相同（它是确定性的）
                    splits[s][side].append(i)
    # ---- 最近间隔核查
    gaps = []
    for key, idxs in sorted(cells.items()):
        idxs = sorted(idxs, key=lambda i: rows[i]["x"])
        nb = (len(idxs) + BLOCK - 1) // BLOCK
        ho = [i for bi in BLOCKS_HELD for i in idxs[bi * BLOCK:(bi + 1) * BLOCK]]
        tr = [i for bi in range(nb) if bi not in BLOCKS_HELD for i in idxs[bi * BLOCK:(bi + 1) * BLOCK]]
        if tr:
            for i in ho:
                gaps.append(min(abs(rows[i]["x"] - rows[j]["x"]) for j in tr))
    # ---- 冻结断言（块定义 + 种子不变性 + 块留出规模）
    if not gaps:
        raise SystemExit("块留出核查为空集 ⇒ 停")
    if len(gaps) != EXPECTED_GAP_ROWS:
        raise SystemExit("块留出规模断言失败：gaps=%d（期望 %d）" % (len(gaps), EXPECTED_GAP_ROWS))
    for s in t1_t2.SEEDS[1:]:
        if splits[s] != splits[t1_t2.SEEDS[0]]:
            raise SystemExit("块留出对 5 个种子不一致（种子 %d）⇒ 停" % s)
    checks = ["block=%d, blocks_held=%s" % (BLOCK, list(BLOCKS_HELD)),
              "arm=C_5-50MHz only（唯一 x 步长 0.01 的批）",
              "block_holdout_identical_across_5_seeds=True",
              "gap_rows==%d" % EXPECTED_GAP_ROWS]

    tasks = {"T1_state": [r["state"] for r in rows],
             "T2_closed": ["closed" if r["closed"] else "open" for r in rows]}
    out = {"kind": "ai11_t1_t2_spacing_arm", "created_local": "2026-10-13",
           "prereg": dict(PREREG),
           "frozen_assertions_checked": checks,
           "registered_result": {"file": rel(REG_RESULT), "sha256": sha(REG_RESULT)},
           "block": BLOCK, "blocks_held": list(BLOCKS_HELD),
           "spacing_check": {"n": len(gaps), "min_gap": min(gaps), "median_gap": statistics.median(gaps),
                             "n_adjacent_or_less": sum(1 for g in gaps if g <= 0.0101)},
           "T1": {}, "T2": {}, "verdicts": {}}
    for tname, y in tasks.items():
        classes = sorted(set(y))
        by_seed = {}
        for s in t1_t2.SEEDS:
            tr, ho = splits[s]["train"], splits[s]["holdout"]
            dom = t1_t2.domain_pairs([rows[i] for i in tr])
            acc_idx = [i for i in ho if (rows[i]["n1"], rows[i]["n2"]) in dom]
            y_tr = [y[i] for i in tr]
            y_te = [y[i] for i in acc_idx]
            clf = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, random_state=s)
            clf.fit(P[tr], y_tr)
            pred = list(clf.predict(P[acc_idx]))
            by_seed[str(s)] = {"n_train": len(tr), "n_holdout": len(ho), "n_accepted": len(acc_idx),
                               "coverage_of_holdout": len(acc_idx) / len(ho) if ho else None,
                               "hgb": t1_t2.metrics(y_te, pred, classes)}
        agg = {"acc_median": statistics.median([by_seed[str(s)]["hgb"]["accuracy"] for s in t1_t2.SEEDS]),
               "bal_median": statistics.median([by_seed[str(s)]["hgb"]["balanced_accuracy"] for s in t1_t2.SEEDS]),
               "coverage_median": statistics.median([by_seed[str(s)]["coverage_of_holdout"] for s in t1_t2.SEEDS]),
               "per_class_recall_median": {
                   c: statistics.median([by_seed[str(s)]["hgb"]["per_class_recall"][c] for s in t1_t2.SEEDS
                                         if by_seed[str(s)]["hgb"]["per_class_recall"][c] is not None])
                   for c in classes}}
        key = "T1" if tname.startswith("T1") else "T2"
        out[key] = {"across_seeds": agg, "by_seed": by_seed}
    # ---- 与注册读数并置 + 判定
    for key in ("T1", "T2"):
        b_reg = reg[key]["C_5-50MHz"]["across_seeds"]["hgb"]
        b_blk = out[key]["across_seeds"]
        d = b_reg["bal_median"] - b_blk["bal_median"]
        out["verdicts"][key] = {
            "registered_bal_median": b_reg["bal_median"],
            "block_holdout_bal_median": b_blk["bal_median"],
            "drop": d,
            "D1_significant_inflation": bool(d > 0.10),
            "D2_no_detectable_inflation": bool(abs(d) <= 0.03),
            "verdict": ("**显著抬高**（降幅 > 0.10）" if d > 0.10 else
                        ("未检出显著抬高（降幅 ≤ 0.03）" if abs(d) <= 0.03 else "**中等敏感**（0.03–0.10）")),
            "zero_recall_states": [c for c, v in b_blk["per_class_recall_median"].items() if v == 0.0]}
    RESULTS.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes((json.dumps(_text.to_en(out), ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8"))
    print("已写 %s" % rel(OUT))

    # ---- 人读摘要（原来另写 T1_T2_SPACING_REPORT.md；包内不再落 md，改为打到 stdout）
    print("块留出核查：min_gap=%.4f 中位=%.4f 仍相邻的行数=%d"
          % (out["spacing_check"]["min_gap"], out["spacing_check"]["median_gap"],
             out["spacing_check"]["n_adjacent_or_less"]))
    for key in ("T1", "T2"):
        v = out["verdicts"][key]
        print("  %s 注册 %.4f → 块留出 %.4f（降 %.4f）⇒ %s"
              % (key, v["registered_bal_median"], v["block_holdout_bal_median"], v["drop"], v["verdict"]))
    print("耗时 %.1f s；写出 %s" % (time.time() - t0, rel(OUT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
