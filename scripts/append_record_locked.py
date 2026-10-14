# -*- coding: utf-8 -*-
"""**带互斥的**索引追加器（包装 `scripts\\append_record_section.py`，不改它一行逻辑）。

用法::

    python -X utf8 scripts/append_record_locked.py --section <片段文件>
    python -X utf8 scripts/append_record_locked.py --section s.md --heading "## 113."

为什么需要它（`INDEX §104` 实测）：两条线**同时**追加时，`读 max 节号 → 写` 这一段不是原子的
⇒ 发生了一次**节号竞争**。本包装脚本把这一段放进**独占锁**里（`work/locks/*.lock`），
拿不到锁就**拒绝写入并提示重试**（退出码 **3**），不抢锁、不自动破锁。

与直接跑原追加器的差异（**只有这些**）：

1. 先取独占锁，结束后释放；锁内才读 max、才写；
2. `--heading` 可省：缺省**要求片段首行的节号恰好 = 锁内读到的最大节号 + 1**
   （防跳号/撞号），并据此生成标题；对不上就**拒写**（原脚本对此只会「先写盘、再回读失败」）；
3. 追加后**复核**「新文本以旧文本开头」（append-only）与「字符数只增」；
4. 号被并发占用（原脚本报 `[SKIP]`）且标题是自动生成时，**重读 max 重试**（默认 3 次）。

原追加器的三道 fail-closed 守卫（重复标题拒收 / 字符数只增 / 回读校验）**原样生效**。
"""
from __future__ import annotations

import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:            # 允许直接跑脚本（不经 pip 安装）
    sys.path.insert(0, str(REPO / "src"))

from memsharness.guards_indexlock import (  # noqa: E402  —— 路径就位后再导入
    default_lock_path, locked_append,
)

#: 退出码：0 成功（含「已存在故跳过」）；2 追加失败；3 **拿不到锁 ⇒ 拒绝写入**
RC_OK, RC_FAIL, RC_LOCKED = 0, 2, 3


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="带独占锁的索引追加（append-only）")
    ap.add_argument("--section", required=True, help="片段文件（首行必须是 `## ` 标题）")
    ap.add_argument("--heading", default=None,
                    help="形如 '## 113.'；缺省自动（要求片段首行节号 = 锁内最大节号 + 1）")
    ap.add_argument("--index", default=None,
                    help="索引路径（缺省 <repo>/docs/INDEX-records-and-rulings.md）")
    ap.add_argument("--repo", default=str(REPO), help="仓库根（测试/迁移用；缺省本仓库）")
    ap.add_argument("--lock", default=None, help="锁文件路径（缺省 <repo>/work/locks/…）")
    ap.add_argument("--timeout-s", type=float, default=0.0,
                    help="等锁的秒数；0（缺省）= 只试一次 ⇒ 拿不到就拒")
    ap.add_argument("--break-stale", action="store_true",
                    help="仅在锁**确实超龄**（>900 s）时破锁一次；缺省关闭")
    ap.add_argument("--retry", type=int, default=3,
                    help="自动节号被并发占用时的重试次数（缺省 3）")
    a = ap.parse_args(argv)

    repo = pathlib.Path(a.repo)
    index = pathlib.Path(a.index) if a.index else repo / "docs/INDEX-records-and-rulings.md"
    lock = pathlib.Path(a.lock) if a.lock else default_lock_path(repo, index.name)
    sec = pathlib.Path(a.section)
    if not sec.is_absolute():
        sec = pathlib.Path.cwd() / sec

    res = locked_append(index, sec, heading=a.heading, repo=repo, lock_path=lock,
                        timeout_s=a.timeout_s, break_stale=a.break_stale,
                        max_retry=a.retry)

    if res.get("appender_stdout"):
        sys.stdout.write(res["appender_stdout"])      # 原追加器的输出**原文照转**
    if res.get("broke_stale"):
        print("[WARN] 破了一个超龄锁：%s" % res["broke_stale"])
    if res["status"] == "refused":
        print("[REFUSED] %s" % res["message"], file=sys.stderr)
        print("           锁文件：%s" % res["lock_path"], file=sys.stderr)
        return RC_LOCKED
    if res["status"] == "appended":
        print("[OK] %s" % res["message"])
        print("     节号 %s ｜ 锁 %s ｜ 复核：append-only + 字符数只增 + 标题存在，三项通过"
              % (res["heading"], res["lock_path"]))
        return RC_OK
    if res["status"] == "skipped":
        print("[SKIP] %s" % res["message"])
        return RC_OK if "[SKIP]" in (res.get("appender_stdout") or "") else RC_FAIL
    print("[FAIL] %s" % res["message"], file=sys.stderr)
    return RC_FAIL


if __name__ == "__main__":
    sys.exit(main())
