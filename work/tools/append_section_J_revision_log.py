# -*- coding: utf-8 -*-
"""把 §6.5 拒答分类更正一节**追加**到 PAPER_REVISION_LOG_20261009.md（append-only）。

守卫：
  * 追加前校验日志 sha256 = d50c985571bf5a95fb0a18e68d0a5ab5c0f04efea3b26bb7f01fa34ad933c84e；
  * 追加后校验「旧全文是新文件逐字节前缀」（既有条目一字未改）；
  * 拒绝重复追加（片段标题已存在时跳过）。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

from memsharness.guards_inplace import backup_before_edit

REPO = pathlib.Path(__file__).resolve().parents[2]
LOG = REPO / "docs/PAPER_REVISION_LOG_20261009.md"
FRAG = REPO / "work/tools/section_J_revision_log.md"
LOG_SHA = "d50c985571bf5a95fb0a18e68d0a5ab5c0f04efea3b26bb7f01fa34ad933c84e"
TITLE = "## J. 本轮追加"


def main() -> int:
    b0 = LOG.read_bytes()
    got = hashlib.sha256(b0).hexdigest()
    if got != LOG_SHA:
        print("[FAIL] 日志基线哈希不符：%s" % got)
        return 2
    t0 = b0.decode("utf-8")
    if TITLE in t0:
        print("[SKIP] 已存在 %r，未重复追加（append-only）" % TITLE)
        return 0
    frag = FRAG.read_text(encoding="utf-8").rstrip("\n")
    new = t0.rstrip("\n") + "\n\n---\n\n" + frag + "\n"
    b1 = new.encode("utf-8")
    # 就地改守卫（`INDEX §131.2` 的新规矩）：LOG 必存在（上一行刚按 sha 校验过）
    # ⇒ 无条件备份；备不了就抛 `InplaceEditRefused`，**不许继续写**（fail-closed）。
    backup_before_edit(LOG)
    LOG.write_bytes(b1)
    back = LOG.read_bytes()
    # 核心自证：旧全文是新文件逐字节前缀
    prefix_ok = back[:len(b0)] == b0
    tail_ok = back[len(b0):] == b1[len(b0):]
    print("旧 %d B / %d 字符 -> 新 %d B / %d 字符（+%d B / +%d 字符）"
          % (len(b0), len(t0), len(back), len(back.decode("utf-8")),
             len(back) - len(b0), len(back.decode("utf-8")) - len(t0)))
    print("旧全文是新文件逐字节前缀 = %s" % prefix_ok)
    print("追加段回读一致 = %s" % tail_ok)
    print("新 sha256 = %s" % hashlib.sha256(back).hexdigest())
    return 0 if (prefix_ok and tail_ok) else 2


if __name__ == "__main__":
    sys.exit(main())
