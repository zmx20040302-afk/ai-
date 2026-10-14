# -*- coding: utf-8 -*-
"""**追加**数据版本隔离表的修订（append-only，裁定 §5.1 / §6）。

为什么需要它：数据版本清单（如 `C_v20260929.json`）是**不可变**的，但它绑定的**隔离表**
会在后续分析中需要增补（例如执行完一轮评估后才发现第二个角点异常）。
直接改冻结文件会破坏"不可变版本"；重建一个新版本又会把无关的 run 也卷进来。
⇒ 用 **append-only 的修订文件**：`data_versions/QUARANTINE_AMENDMENTS.jsonl`，
每条记录**绑定版本 manifest 的 sha256**，并记录"何时发现"（`discovered_after`）与证据文件。

fail-closed 守卫：
* 同一 `seq` 已存在 ⇒ 拒绝（append-only 不允许重写）；
* 同一 `(version, combo)` 已登记过 ⇒ 拒绝（避免重复隔离）；
* 目标版本 manifest 不存在 ⇒ 拒绝；
* 记录里**必须**有 `evidence` 与 `rule`，否则拒绝（不允许无证据隔离）。

用法：
    python -B scripts/amend_data_version_quarantine.py \
        --version-manifest work/runs/x-densify-20260928/data_versions/C_v20260929.json \
        --combo 0.2,1,8 --evidence work/runs/x-densify-20260928/a6/CORNER_ANOMALY.md \
        --why "..." --rule "..." --discovered-after "round6 L-N2ex(8) 主折执行后（post-hoc）"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = REPO / "work/runs/x-densify-20260928/data_versions/QUARANTINE_AMENDMENTS.jsonl"


def sha256_file(p: pathlib.Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="追加数据版本隔离表修订（append-only）")
    ap.add_argument("--version-manifest", type=pathlib.Path, required=True)
    ap.add_argument("--combo", required=True, help="x_scale,N_w_te1,N_w_te2（逗号分隔）")
    ap.add_argument("--action", default="add_quarantine",
                    choices=("add_quarantine", "reinterpret_attribution", "clear_quarantine"),
                    help="记录类型；`reinterpret_attribution` 用于**更正归因方向**（不改隔离决定）")
    ap.add_argument("--supersedes-seq", type=int, default=None,
                    help="本记录更正/取代哪一条 seq（append-only：旧记录保留）")
    ap.add_argument("--evidence", required=True, help="证据文件路径（会记其 sha256）")
    ap.add_argument("--why", required=True, help="为什么隔离（写实测数字）")
    ap.add_argument("--rule", required=True, help="判定规则原文")
    ap.add_argument("--discovered-after", default=None, help="何时发现（例：某折执行后 post-hoc）")
    ap.add_argument("--status", default="quarantined_pending_rerun")
    ap.add_argument("--ledger", type=pathlib.Path, default=DEFAULT_LEDGER)
    args = ap.parse_args(argv)

    if not args.version_manifest.is_file():
        print("[FAIL] 版本清单不存在：%s" % args.version_manifest, file=sys.stderr)
        return 2
    ev = pathlib.Path(args.evidence)
    if not ev.is_file():
        print("[FAIL] 证据文件不存在：%s ⇒ 不允许无证据隔离" % ev, file=sys.stderr)
        return 2
    try:
        parts = [float(v) for v in args.combo.split(",")]
        assert len(parts) == 3
    except Exception:
        print("[FAIL] --combo 必须是三个数（x_scale,N_w_te1,N_w_te2）", file=sys.stderr)
        return 2
    combo = {"x_scale": parts[0], "N_w_te1": parts[1], "N_w_te2": parts[2]}

    vj = json.loads(args.version_manifest.read_text(encoding="utf-8"))
    label = vj.get("label")
    vsha = sha256_file(args.version_manifest)

    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if args.ledger.is_file():
        for ln in args.ledger.read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if s:
                existing.append(json.loads(s))
    for rec in existing:
        # 同一 (版本, 组合, 记录类型) 只能出现一次；但**允许**对同一组合追加
        # `reinterpret_attribution`（归因更正）——这正是 append-only 的用法。
        if (rec.get("data_version") == label and rec.get("combo") == combo
                and rec.get("action", "add_quarantine") == args.action):
            print("[FAIL] 已登记过：%s / %s / action=%s ⇒ 拒绝重复（append-only）"
                  % (label, combo, args.action), file=sys.stderr)
            return 2
    if args.action == "reinterpret_attribution":
        if args.supersedes_seq is None:
            print("[FAIL] `reinterpret_attribution` 必须给 --supersedes-seq"
                  "（指向被更正的记录；`0` 表示更正**版本 manifest 自带**的 quarantine 表条目）",
                  file=sys.stderr)
            return 2
        if args.supersedes_seq != 0 and not any(r.get("seq") == args.supersedes_seq
                                                for r in existing):
            print("[FAIL] --supersedes-seq=%s 在 ledger 中不存在（`0` 专指 manifest 自带表）"
                  % args.supersedes_seq, file=sys.stderr)
            return 2
    if args.action == "clear_quarantine":
        print("[FAIL] 本轮不允许清除隔离（需人工拍板）：请改用人工流程。", file=sys.stderr)
        return 2

    rec = {
        "seq": len(existing) + 1,
        "amended_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "action": args.action,
        "supersedes_seq": args.supersedes_seq,
        "data_version": label,
        "data_version_manifest": str(args.version_manifest).replace("\\", "/"),
        "data_version_sha256": vsha,
        "combo": combo,
        "status": args.status,
        "why": args.why,
        "rule": args.rule,
        "evidence": {"path": str(ev).replace("\\", "/"), "sha256": sha256_file(ev)},
        "discovered_after": args.discovered_after,
        "semantics": ("修订**只增不改**：被绑定的版本 manifest 一字未动；"
                      "引用该版本时**必须**同时读取本 ledger"),
    }
    with args.ledger.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("appended seq=%d  %s / x=%s N1=%s N2=%s" % (rec["seq"], label, *parts))
    print("  version sha256=%s  证据=%s（%s）"
          % ((vsha or "")[:16], rec["evidence"]["path"], (rec["evidence"]["sha256"] or "")[:16]))
    print("  ledger=%s（现 %d 条）" % (args.ledger, len(existing) + 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
