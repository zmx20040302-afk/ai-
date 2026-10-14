# -*- coding: utf-8 -*-
"""对账：批次 C 自带的权威门禁列 vs 我重算的 Q∈[2.5,3.5]。

若两者不一致，说明**我的重算口径与既有管线不同** ⇒ 必须查清后才能用它做两批比较，
不能拿"我算的数"去和"别人的数"并列（这正是最容易出错的地方）。
"""
import csv
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
OLD = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"
Q_LO, Q_HI = 2.5, 3.5

rows = list(csv.DictReader(OLD.open("r", encoding="utf-8", newline="")))
cols = list(rows[0].keys())


def cnt(key: str) -> int:
    return sum(1 for x in rows if str(x.get(key, "")).strip().lower() == "true")


print("列数 %d ｜ 行数 %d" % (len(cols), len(rows)))
for k in ("q_gate_pass", "q_gate_applicable", "bandwidth_closed", "peak_closed",
          "ranking_eligible", "quarantined"):
    print("  %-22s true = %d" % (k, cnt(k) if k in cols else -1))


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


mine = [r for r in rows if f(r.get("Q_factor")) is not None and Q_LO <= f(r["Q_factor"]) <= Q_HI]
print("\n我重算 Q∈[%.1f,%.1f] = %d" % (Q_LO, Q_HI, len(mine)))
if "q_gate_pass" in cols:
    theirs = {i for i, r in enumerate(rows) if str(r["q_gate_pass"]).strip().lower() == "true"}
    myset = {i for i, r in enumerate(rows)
             if f(r.get("Q_factor")) is not None and Q_LO <= f(r["Q_factor"]) <= Q_HI}
    print("既有权威 q_gate_pass = %d" % len(theirs))
    print("  交集 %d ｜ 仅我有 %d ｜ 仅它有过 %d"
          % (len(theirs & myset), len(myset - theirs), len(theirs - myset)))
    if theirs - myset:
        i = sorted(theirs - myset)[0]
        print("  样例（它通过、我未通过）：Q_factor=%r q_gate_applicable=%r quarantined=%r"
              % (rows[i].get("Q_factor"), rows[i].get("q_gate_applicable"),
                 rows[i].get("quarantined")))
    if myset - theirs:
        i = sorted(myset - theirs)[0]
        print("  样例（我通过、它未通过）：Q_factor=%r q_gate_applicable=%r quarantined=%r"
              % (rows[i].get("Q_factor"), rows[i].get("q_gate_applicable"),
                 rows[i].get("quarantined")))
    ok = theirs == myset
    print("\n一致性：%s" % ("**完全一致**" if ok else "**不一致 —— 不得混用两套口径**"))
    sys.exit(0 if ok else 3)
print("无 q_gate_pass 列，无法对账")
sys.exit(0)
