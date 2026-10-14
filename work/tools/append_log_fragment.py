# -*- coding: utf-8 -*-
"""通用 append-only 片段追加器（带 fail-closed 守卫）。

用法：
  python work/tools/append_log_fragment.py <target> <fragment> <guard-substring>

守卫：
* 片段非空且行尾为 LF；
* 目标文件行尾 LF；
* 目标文件里**已含 guard 子串** ⇒ 拒绝重复追加；
* 追加后校验**旧全文是新文件逐字节前缀**；
* 追加前备份到 work/logs/。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]


def main() -> int:
    if len(sys.argv) != 4:
        print("用法: append_log_fragment.py <target> <fragment> <guard>")
        return 2
    tgt = REPO / sys.argv[1]
    frag_p = REPO / sys.argv[2]
    guard = sys.argv[3].encode("utf-8")
    old = tgt.read_bytes()
    frag = frag_p.read_bytes().replace(b"\r\n", b"\n")
    if not frag.strip():
        print("[FAIL] 片段为空")
        return 2
    if guard in old:
        print("[SKIP] 目标已含守卫子串 %r，未重复追加" % guard.decode("utf-8"))
        return 0
    if old.count(b"\r\n") != 0:
        print("[FAIL] 目标不是纯 LF")
        return 2
    bk = REPO / "work/logs" / ("%s.%s.bak" % (tgt.name, _dt.datetime.now().strftime("%Y%m%dT%H%M%S")))
    bk.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tgt, bk)
    if not old.endswith(b"\n"):
        frag = b"\n" + frag
    new = old + frag
    if len(new) <= len(old):
        print("[FAIL] 字符数未增加")
        return 2
    tgt.write_bytes(new)
    back = tgt.read_bytes()
    ok = back.startswith(old)
    if back != new or not ok:
        print("[FAIL] 回读/前缀守卫不通过（ok_prefix=%s）" % ok)
        return 2
    print("目标 = %s" % tgt.relative_to(REPO))
    print("旧 sha256 = %s（%d B / %d 行）" % (hashlib.sha256(old).hexdigest(), len(old), old.count(b"\n")))
    print("新 sha256 = %s（%d B / %d 行）" % (hashlib.sha256(back).hexdigest(), len(back), back.count(b"\n")))
    print("字节 %d -> %d（+%d）" % (len(old), len(back), len(back) - len(old)))
    print("旧全文是新文件逐字节前缀？ %s" % ok)
    print("备份 = %s" % bk.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
