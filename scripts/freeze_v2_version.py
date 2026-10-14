# -*- coding: utf-8 -*-
"""把 v2 提取**冻结为不可变版本**，并统计「删失/截断过滤后」还剩多少可用组合。

冻结 = 写出带时间戳的只读副本 + `VERSION_v2.json`（含 sha256、行数、标志定义、过滤规则），
草稿 `v2_labels_draft.csv` **保留不动**（append-only：新版本不覆盖旧产物）。

过滤规则（不得放松）：
`usable = (not peak_at_scan_endpoint) and (not bw_upper_cutoff_at_endpoint)`
—— 峰值落在扫描端点 ⇒ 频率只是**下界**；上截止点等于端点 ⇒ 宽度/Q 被截断。

分批报告：本批 5–35 MHz 与既有批次（5–50 MHz）**分别出数，绝不合成一个通过率**（红线 §4）。
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
V2 = REPO / "work/runs/remote-exported-v2-20260922"
DRAFT = V2 / "v2_labels_draft.csv"
OLD = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"
Q_LO, Q_HI = 2.5, 3.5


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    rows = list(csv.DictReader(DRAFT.open("r", encoding="utf-8", newline="")))
    def b(v: str) -> bool:
        return str(v).strip().lower() in ("true", "1", "yes")
    def f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    for r in rows:
        r["_usable"] = (not b(r["peak_at_scan_endpoint"])) and \
                       (not b(r["bw_upper_cutoff_at_endpoint"]))
        r["_q_ok"] = (f(r["Q"]) is not None) and (Q_LO <= f(r["Q"]) <= Q_HI)

    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    frozen = V2 / ("v2_labels_frozen_%s.csv" % ts)
    shutil.copy2(DRAFT, frozen)
    ver = {"version_id": "V2_v%s" % ts, "frozen_at_local": ts,
           "kind": "immutable_data_version", "frozen": True,
           "source_draft": DRAFT.name, "source_draft_sha256": sha(DRAFT),
           "frozen_sha256": sha(frozen),
           "scan_range_MHz": [5.0, 35.0], "n_rows": len(rows),
           "flags": {"peak_at_scan_endpoint": "峰值频率是下界（右删失）",
                     "bw_upper_cutoff_at_endpoint": "宽度/Q/阻尼比被截断",
                     "freq_range": "5–35 MHz，与批次 C 的 5–50 MHz 不同源，不得混算"},
           "filter_rule": "usable = not peak_at_scan_endpoint and not bw_upper_cutoff_at_endpoint",
           "q_gate": [Q_LO, Q_HI]}
    (V2 / ("VERSION_%s.json" % ver["version_id"])).write_text(
        json.dumps(ver, ensure_ascii=False, indent=2), encoding="utf-8")

    def stats(sel: list[dict], name: str) -> dict:
        n = len(sel)
        u = [r for r in sel if r["_usable"]]
        q = [r for r in u if r["_q_ok"]]
        d = {"name": name, "n": n, "usable": len(u),
             "usable_pct": 100 * len(u) / n if n else 0.0,
             "q_gate_pass": len(q),
             "q_gate_pct_of_usable": 100 * len(q) / len(u) if u else 0.0}
        print("  %-34s 组合 %3d ｜ 可用 %3d（%5.1f%%）｜ Q∈[%.1f,%.1f] %3d（可用中 %5.1f%%）"
              % (name, n, len(u), d["usable_pct"], Q_LO, Q_HI, len(q), d["q_gate_pct_of_usable"]))
        return d

    print("== 本批 V2（5–35 MHz，扫描上限 35 MHz）==")
    res = [stats(rows, "全部 250 组合")]
    for cell in sorted({r["cell"] for r in rows}):
        res.append(stats([r for r in rows if r["cell"] == cell], cell))
    print("  --- 新增组合按 N2 分（与既有 1843 组合表比对结果）---")
    try:
        old = list(csv.DictReader(OLD.open("r", encoding="utf-8", newline="")))
        okset = {(round(float(r["x_scale"]), 6), int(float(r["N_w_te1"])),
                  int(float(r["N_w_te2"]))) for r in old}
    except Exception as e:                                     # noqa: BLE001
        print("  [WARN] 读既有标签失败：%s" % e)
        okset = set()
    if okset:
        newrows = [r for r in rows
                   if (round(float(r["x_scale"]), 6), int(float(r["N_w_te1"])),
                       int(float(r["N_w_te2"]))) not in okset]
        res.append(stats(newrows, "全部新增组合"))
        n9 = [r for r in newrows if int(float(r["N_w_te2"])) == 9]
        res.append(stats(n9, "新增 N2=9"))
        print("\n== 参照：既有批次（5–50 MHz，不混算）==")
        qcol = next((c for c in old[0] if c.strip().lower() in ("q", "q_factor")), None)
        ccol = next((c for c in old[0] if "closed" in c.lower()), None)
        n_bc = sum(1 for r in old if str(r.get(ccol, "")).lower() == "true") if ccol else None
        n_q = sum(1 for r in old if qcol and (lambda v: v is not None and Q_LO <= v <= Q_HI)(
            (lambda s: float(s) if s not in ("", "nan", None) else None)(r.get(qcol)))) if qcol else None
        print("  既有标签 %d 行 ｜ bandwidth_closed 列=%r（true %s）｜ Q 列=%r（Q∈门槛 %s）"
              % (len(old), ccol, n_bc, qcol, n_q))
        ver["old_batch_reference"] = {"csv": str(OLD.relative_to(REPO)), "n_rows": len(old),
                                      "closed_col": ccol, "n_closed": n_bc,
                                      "q_col": qcol, "n_q_in_gate": n_q}
    ver["stats"] = res
    (V2 / ("VERSION_%s.json" % ver["version_id"])).write_text(
        json.dumps(ver, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n版本已冻结：%s（sha256 %s…）"
          % ((V2 / ("VERSION_%s.json" % ver["version_id"])).relative_to(REPO),
             ver["frozen_sha256"][:16]))
    print("冻结副本：%s" % frozen.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
