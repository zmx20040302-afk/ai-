# -*- coding: utf-8 -*-
"""§104 分类修复的**实测**对照件（只读输入、只写 stdout，不写任何 work/runs 产物）。

做三件事：
1. 用 E3 的同一网格（x 0.20→1.00 step 0.05 × N1 1..7 × N2 5..8 = 476）重跑逐点分类，
   给出**修复前 vs 修复后**的计数对照；
2. 用一个**更宽的探针网格**（含 N2=9 外推、x 越域、N1 非整数等）枚举所有**实际会出现**的
   拒答原文，逐条比对「旧顺序」与「新顺序」的归类，证明只有结构约束那一类发生迁移；
3. 打印接受/拒答/网格三项与冻结产物是否逐项一致。

「修复前」用本文件内的**旧顺序副本**复现（不改模块），保证两边输入逐字节相同。
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from memsharness import multichannel_surrogate as MCS  # noqa: E402

FROZEN_JSON = REPO / "work/runs/paper-evidence-20261009/E3_refusal_screen.json"
FROZEN_CSV = REPO / "work/runs/paper-evidence-20261009/E3_refusal_grid_points.csv"

#: 修复**前**的顺序（逐字抄自改动前的 L316-L319）
OLD_ORDER = (("no_layer_for_n1", "没有该 N1"), ("need_two_layers", "只有一层"),
             ("x_outside_layer_range", "超出该层标定"), ("x_out_of_domain", "x_scale"),
             ("n2_out_of_domain", "N_w_te2"), ("layer_does_not_exist", "该层不存在"),
             ("n2_extrap_too_far", "外推超过"), ("x_missing", "同一个 x"))


def classify_old(msg: str) -> str:
    for key, pat in OLD_ORDER:
        if pat in msg:
            return key
    return "other"


def e3_grid():
    xs = [round(min(1.00, 0.20 + i * 0.05), 6)
          for i in range(int(round((1.00 - 0.20) / 0.05)) + 1)]
    for x in xs:
        for n1 in range(1, 8):
            for n2 in range(5, 9):
                yield x, n1, n2


def run_grid(grid, cls):
    names = list(MCS.FORMAL_OBJECTIVES)
    reasons, modes, rows = collections.Counter(), collections.Counter(), []
    by_pair = collections.defaultdict(collections.Counter)
    n_grid = 0
    for x, n1, n2 in grid:
        n_grid += 1
        try:
            r = MCS.predict(x, n1, n2, channels=names, alpha=0.05)
            modes[r["mode"]] += 1
            rows.append([x, n1, n2, "accepted", r["mode"], ""])
        except MCS.Refused as exc:
            k = cls(str(exc))
            reasons[k] += 1
            by_pair[(n1, n2)][k] += 1
            rows.append([x, n1, n2, "refused", k, str(exc)])
    return {"n_grid": n_grid, "n_predicted": sum(modes.values()),
            "n_refused": sum(reasons.values()), "modes": dict(modes),
            "reasons": dict(reasons), "by_pair": by_pair}, rows


def main() -> int:
    out = {}

    # ---------- A. E3 476 网格：修复前 vs 修复后 ----------
    before, rows_before = run_grid(e3_grid(), classify_old)
    after, rows_after = run_grid(e3_grid(), MCS._classify_refusal)

    print("=== A. E3 同一网格（476 点）分类计数对照 ===")
    keys = sorted(set(before["reasons"]) | set(after["reasons"]))
    print("%-24s %8s %8s %8s" % ("refusal_reason", "修复前", "修复后", "差"))
    for k in keys:
        b, a = before["reasons"].get(k, 0), after["reasons"].get(k, 0)
        print("%-24s %8d %8d %+8d" % (k, b, a, a - b))
    print("%-24s %8d %8d %+8d" % ("[拒答合计]", before["n_refused"],
                                  after["n_refused"], after["n_refused"] - before["n_refused"]))
    print("\n%-24s %8d %8d %+8d" % ("n_predicted", before["n_predicted"],
                                    after["n_predicted"],
                                    after["n_predicted"] - before["n_predicted"]))
    print("%-24s %8d %8d %+8d" % ("n_grid", before["n_grid"], after["n_grid"],
                                  after["n_grid"] - before["n_grid"]))
    print("modes before =", before["modes"], " after =", after["modes"])

    # ---------- B. 与冻结产物逐项核对 ----------
    # ⚠️ 本轮开工时读到的 E3 产物（修复前口径）——以下三条是**当时实测值**，硬编码留档：
    #     E3_refusal_screen.json sha256 = cecd9d384afd62bd849314414f133ba8031f2dee84efdb49b132833c3efc083e
    #     E3_refusal_grid_points.csv sha256 = 7867df3953d0662135f657336452f6388f8d7748c202bb46ae651133624b56db
    #     refusal_reasons_as_reported = {n2_out_of_domain: 102, x_outside_layer_range: 51}
    PRE_FIX_JSON_SHA = "cecd9d384afd62bd849314414f133ba8031f2dee84efdb49b132833c3efc083e"
    PRE_FIX_CSV_SHA = "7867df3953d0662135f657336452f6388f8d7748c202bb46ae651133624b56db"
    print("\n=== B. 冻结产物对照 ===")
    print("B0 本轮开工时读到的（修复前口径）：json sha = %s…；csv sha = %s…" %
          (PRE_FIX_JSON_SHA[:12], PRE_FIX_CSV_SHA[:12]))
    print("B0 我的『旧顺序』副本复现当时产物 refusal_reasons =",
          json.dumps(before["reasons"], ensure_ascii=False, sort_keys=True))
    print("B0 ⇒ 旧顺序副本 == 开工时产物 = %s（故『修复前』一列可信）"
          % (before["reasons"] == {"n2_out_of_domain": 102, "x_outside_layer_range": 51}))

    live_sha = hashlib.sha256(FROZEN_JSON.read_bytes()).hexdigest()
    print("\nB1 当前磁盘上的 E3 产物：json sha = %s…（%s）"
          % (live_sha[:12],
             "与开工时**同一版**" if live_sha == PRE_FIX_JSON_SHA else "**已被外部重生成**"))
    live = json.loads(FROZEN_JSON.read_text(encoding="utf-8"))
    fr = live["counts"]["refusal_reasons_as_reported"]
    print("B1 当前 refusal_reasons_as_reported =",
          json.dumps(fr, ensure_ascii=False, sort_keys=True))
    print("B1 当前 refusal_attribution =",
          json.dumps(live.get("refusal_attribution"), ensure_ascii=False, sort_keys=True))
    print("B1 当前 counts 三项 = %s / %s / %s"
          % (live["counts"]["n_grid"], live["counts"]["n_predicted"], live["counts"]["n_refused"]))
    print("B1 三项与修复后重算一致 = %s"
          % ((live["counts"]["n_grid"], live["counts"]["n_predicted"],
              live["counts"]["n_refused"]) ==
             (after["n_grid"], after["n_predicted"], after["n_refused"])))
    print("B1 当前标签归属与修复后重算一致 = %s"
          % (dict(fr) == after["reasons"]))

    # 逐点 decision 列：与**当前**磁盘 CSV 对照（只允许 mode_or_reason 变）
    dec_a = [(r[0], r[1], r[2], r[3]) for r in rows_after]
    dec_b = [(r[0], r[1], r[2], r[3]) for r in rows_before]
    print("B2 修复前/后逐点 decision 列完全一致（接受/拒答判定未变） =", dec_b == dec_a)
    with FROZEN_CSV.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    dec_f = [(float(r["x_scale"]), int(r["N_w_te1"]), int(r["N_w_te2"]), r["decision"])
             for r in rows]
    print("B2 当前 CSV 行数 = %d；decision 列与重算逐点一致 = %s" % (len(rows), dec_f == dec_a))
    lbl_f = [(int(r["N_w_te1"]), int(r["N_w_te2"])) for r in rows
             if r["mode_or_reason"] == "layer_does_not_exist"]
    print("B2 当前 CSV 里 layer_does_not_exist 行数 = %d" % len(lbl_f))
    # 逐点 message 也逐字节一致？（分类只改标签，不改消息）
    msg_b = [r[5] for r in rows_before]
    msg_a = [r[5] for r in rows_after]
    print("B3 拒答原文逐条一致（未改任何消息文本） =", msg_b == msg_a)
    lab_b = [(r[0], r[1], r[2], r[4]) for r in rows_before if r[3] == "refused"]
    lab_a = [(r[0], r[1], r[2], r[4]) for r in rows_after if r[3] == "refused"]
    moved = [b for b, a in zip(lab_b, lab_a) if b != a]
    print("B3 标签发生迁移的点数 = %d" % len(moved))
    xset = collections.Counter(float(r[0]) for r in rows_after
                              if r[3] == "refused" and r[4] == "x_outside_layer_range")
    print("B3 修复后 x_outside_layer_range 的 x 分布 =", dict(sorted(xset.items())))
    pairs = collections.Counter((r[1], r[2]) for r in rows_after
                                if r[3] == "refused" and r[4] == "layer_does_not_exist")
    print("B3 修复后 layer_does_not_exist 的 (N1,N2) 分布 =",
          {("%d|%d" % k): v for k, v in sorted(pairs.items())})

    # ---------- C. 宽探针：枚举所有实际会出现的拒答原文 ----------
    print("\n=== C. 宽探针：所有实际拒答原文逐条新旧归类 ===")
    probes = []
    for x in (0.05, 0.20, 0.25, 0.30, 0.50, 1.00, 1.20):     # 含 x 越域
        for n1 in (0, 1, 2, 3, 5, 6, 7, 8):                    # 含 N1 ≥ N2
            for n2 in (4, 5, 6, 7, 8, 9, 10):                  # 含 N2 越域
                probes.append((x, n1, n2))
    probes += [("abc", 1, 6), (0.5, 1.5, 6)]                    # 非数字 / 非整数 N1
    msgs = collections.Counter()
    for x, n1, n2 in probes:
        try:
            MCS.predict(x, n1, n2, channels=list(MCS.FORMAL_OBJECTIVES), alpha=0.05)
        except MCS.Refused as exc:
            msgs[str(exc)] += 1
    # 额外的模块级拒答（非 predict 路径）
    for m in ("α 只认 [0.1, 0.05, 0.01]（其它取值没有校准记录）",
              "['abs_pv_W'] 是 §3.4 的约束量（功率/应力/能量），**只作约束、不进预测目标**",
              "未知通道 ['nope']；可用：['abs_w_m']"):
        msgs[m] += 1
    diff = 0
    print("%-6s %-8s %-8s %s" % ("标记", "旧", "新", "拒答原文（截断 90）"))
    for msg, n in sorted(msgs.items(), key=lambda kv: (classify_old(kv[0]), kv[0])):
        o, w = classify_old(msg), MCS._classify_refusal(msg)
        flag = "**变了**" if o != w else ""
        if o != w:
            diff += 1
        print("%-6s %-8s %-8s %s" % (flag, o, w, msg.replace("\n", " ")[:90]))
    print("\n归类发生变化的**不同原文条数** = %d" % diff)
    print("旧归类直方图 =", dict(collections.Counter(classify_old(m) for m in msgs)))
    print("新归类直方图 =", dict(collections.Counter(MCS._classify_refusal(m) for m in msgs)))

    # ---------- D. 消费点影响面（实测，不写任何产物） ----------
    print("\n=== D. 消费点影响面（实测） ===")
    # D1 `screen()`：键名变化，但「拒答合计」不变 ⇒ 依赖「合计」的断言不受影响
    sc = MCS.screen(x_min=0.20, x_max=1.00, x_step=0.05, n1_min=1, n1_max=7,
                    n2_min=5, n2_max=8, top=2)
    print("D1 screen() 修复后 refusal_reasons =",
          json.dumps(sc["refusal_reasons"], ensure_ascii=False, sort_keys=True))
    print("D1 screen() n_predicted/n_refused/n_points = %d/%d/%d；"
          "sum(refusal_reasons)==n_refused ⇒ %s"
          % (sc["n_predicted"], sc["n_refused"], sc["grid"]["n_points"],
             sum(sc["refusal_reasons"].values()) == sc["n_refused"]))
    # D2 `scripts/paper_evidence_dac2027.py` 的 E3 派生量：按**原来那段代码**复算
    lb_new = {k: v for k, v in after["by_pair"].items() if v.get("n2_out_of_domain")}
    lb_old = {k: v for k, v in before["by_pair"].items() if v.get("n2_out_of_domain")}
    print("D2 E3 派生量 label_collision 条目数：旧 %d → 新 %d" % (len(lb_old), len(lb_new)))
    print("D2 E3 派生量 refusal_attribution['layer_does_not_exist_structural_N1_ge_N2']："
          "旧 %d → 新 %d"
          % (sum(v["n2_out_of_domain"] for v in lb_old.values()),
             sum(v["n2_out_of_domain"] for v in lb_new.values())))
    print("D2 ⇒ 若**重跑** E3 生成脚本，这两个字段会变 0；而 "
          "scripts\\verify_paper_evidence.py L236-240 硬编码断言 102/51 ⇒ 会失败。"
          "本轮**不重跑、不改脚本、不改产物**（产物仍与旧代码一致，见 B 段）。")
    # D3 model_card() 是否消费 _classify_refusal
    src = pathlib.Path(MCS.__file__).read_text(encoding="utf-8")
    body_card = src.split("def model_card", 1)[1].split("\ndef ", 1)[0]
    n_use = src.count("_classify_refusal(")
    print("D3 模块内出现 `_classify_refusal(` 次数 = %d（含 1 处 def）⇒ 调用点 %d 个"
          % (n_use, n_use - 1))
    print("D3 `model_card()` 函数体内引用 `_classify_refusal` = %s ⇒ 模型卡不受影响"
          % ("_classify_refusal" in body_card))
    out["ok"] = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
