"""把**人的裁决/反馈**写入溯源库的 ``feedback`` 表（append-only）。

为什么需要这个脚本：
    仓库里有 ``feedback`` 表与 ``sample.feedback_id`` 溯源列，但**没有写入接口**
    （`store.py` 只有 `insert_run` / `insert_sample`），因此人反馈实际上进不了库。
    红线 1/5 要求「每个数值能指回 feedback_id」且「人保留放行权」——没有写入通路，
    人工放行就只能停留在对话里，无法追溯。本脚本补上这条通路。

设计约束（与 store.py 的既有契约一致）：
    - ``verdict`` 只接受 accept|reject|correct|prefer；
    - ``feedback_id`` 形如 ``fb-<UTC 时间戳>-<8 位随机>``，**append-only**（不更新既有行）；
    - ``created_at`` 用 ``store.now_utc()``，全库时间口径统一。

用法：
    python scripts\\ingest_feedback.py --target-kind run --target-id probe-2026... --verdict accept \\
        --correction "fmax = 35[MHz] 为当前设计口径" --reason "用户 2026-09-12 确认" --author user:zmx
    python scripts\\ingest_feedback.py --list 10
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from memsharness.store import connect, now_utc  # noqa: E402

VERDICTS = ("accept", "reject", "correct", "prefer")
TARGET_KINDS = ("model", "prediction", "report", "run", "parameter", "design")


def new_feedback_id() -> str:
    stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    return f"fb-{stamp}-{uuid.uuid4().hex[:8]}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="写入/查看人反馈（feedback 表，append-only）")
    ap.add_argument("--target-kind", choices=TARGET_KINDS)
    ap.add_argument("--target-id")
    ap.add_argument("--verdict", choices=VERDICTS)
    ap.add_argument("--correction", help="裁决/修正内容（人说了什么）")
    ap.add_argument("--reason", help="理由/证据线索")
    ap.add_argument("--author", default="user")
    ap.add_argument("--list", type=int, nargs="?", const=10, help="列出最近 N 条，不写入")
    args = ap.parse_args(argv)

    with connect() as conn:
        if args.list is not None:
            rows = conn.execute(
                "SELECT feedback_id, target_kind, target_id, verdict, correction, author, created_at"
                " FROM feedback ORDER BY created_at DESC LIMIT ?",
                [args.list],
            ).fetchall()
            if not rows:
                print("feedback 表为空")
                return 0
            print(f"最近 {len(rows)} 条人反馈：")
            for r in rows:
                print(f"  {r[0]}  [{r[1]}:{r[2]}]  verdict={r[3]}  by {r[5]}  {r[6]}")
                print(f"      correction: {r[4]}")
            return 0

        missing = [
            name
            for name, value in (
                ("--target-kind", args.target_kind),
                ("--target-id", args.target_id),
                ("--verdict", args.verdict),
                ("--correction", args.correction),
            )
            if not value
        ]
        if missing:
            print(f"[错误] 缺少必填参数：{missing}", file=sys.stderr)
            return 2

        feedback_id = new_feedback_id()
        conn.execute(
            "INSERT INTO feedback (feedback_id, target_kind, target_id, verdict, correction,"
            " reason, author, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                feedback_id,
                args.target_kind,
                args.target_id,
                args.verdict,
                args.correction,
                args.reason,
                args.author,
                now_utc(),
            ],
        )
        print(f"✅ 已写入人反馈：{feedback_id}")
        print(f"   target : {args.target_kind}:{args.target_id}")
        print(f"   verdict: {args.verdict}")
        print(f"   content: {args.correction}")
        print(f"   by     : {args.author} @ {now_utc().isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
