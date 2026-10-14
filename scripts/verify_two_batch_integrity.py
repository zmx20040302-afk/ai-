# -*- coding: utf-8 -*-
"""两批数据的两项独立自检（只读，不写任何产物）。

1. **冻结完整性**：`v2_labels_frozen_*.csv` 的现算 sha256 是否仍等于版本清单里的 `frozen_sha256`
   —— 冻结版本若被改动过，后面所有数字都失去锚点。
2. **组合重叠（泄漏前提）**：两批 `(x_scale, N_w_te1, N_w_te2)` 是否有交集。
   若有交集，则"按 batch 整组切分"会产生**同组合既在训练又在留出**⇒ 必须先解决，
   否则任何跨批指标都是泄漏出来的。
另外核对 C 批的 `q_gate_applicable` 是否等于 `bandwidth_closed`（口径同源的旁证）。
"""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
V2 = REPO / "work/runs/remote-exported-v2-20260922"
TWO = sorted((REPO / "work/runs/labels-two-batch").glob("*/labels_two_batch.csv"))
OLD = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"


def main() -> int:
    ok = True
    vers = sorted(V2.glob("VERSION_V2_*.json"))
    froz = sorted(V2.glob("v2_labels_frozen_*.csv"))
    if not vers or not froz:
        print("[FAIL] 缺版本清单或冻结副本")
        return 2
    j = json.loads(vers[-1].read_text(encoding="utf-8"))
    now = hashlib.sha256(froz[-1].read_bytes()).hexdigest()
    print("== 1. 冻结完整性 ==")
    print("  清单 %s" % vers[-1].name)
    print("  副本 %s" % froz[-1].name)
    print("  清单 frozen_sha256 = %s" % j["frozen_sha256"])
    print("  现算 sha256        = %s" % now)
    ok &= (now == j["frozen_sha256"])
    print("  一致：%s" % (now == j["frozen_sha256"]))

    print("\n== 2. 两批组合重叠（整组切分的前提）==")
    if not TWO:
        print("  [FAIL] 未找到并集表")
        return 2
    rows = list(csv.DictReader(TWO[-1].open("r", encoding="utf-8", newline="")))
    key = lambda r: (round(float(r["x_scale"]), 6), int(float(r["N_w_te1"])), int(float(r["N_w_te2"])))
    sets: dict[str, set] = {}
    for r in rows:
        sets.setdefault(r["batch"], set()).add(key(r))
    for b, s in sorted(sets.items()):
        print("  %-12s 组合 %d" % (b, len(s)))
    inter = sets.get("C_5-50MHz", set()) & sets.get("V2_5-35MHz", set())
    print("  交集 %d 个 %s" % (len(inter), sorted(inter)[:5]))
    if inter:
        print("  ⚠️ 有交集 ⇒ 按 batch 整组切分会出现同组合跨组；须先处置（去重规则或排除该组），"
              "否则跨批指标是泄漏出来的")
    else:
        print("  ✅ 无交集 ⇒ batch 可作为整组切分键")
    ok &= (not inter)

    print("\n== 3. C 批口径旁证 ==")
    old = list(csv.DictReader(OLD.open("r", encoding="utf-8", newline="")))
    def same(a: str, b: str) -> bool:
        return all(str(r.get(a, "")).strip().lower() == str(r.get(b, "")).strip().lower()
                   for r in old)
    print("  rows=%d ｜ q_gate_applicable == bandwidth_closed 逐行一致：%s"
          % (len(old), same("q_gate_applicable", "bandwidth_closed")))
    print("\n自检结论：%s" % ("全部通过" if ok else "**有未通过项，见上**"))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
