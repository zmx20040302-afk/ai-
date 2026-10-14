# -*- coding: utf-8 -*-
"""把 §L 片段 append-only 追加到改动说明，并做 fail-closed 守卫。

* 追加前记录旧文件字节；追加后校验**旧全文是新文件逐字节前缀**；
* 片段行尾统一为 LF（与目标文件一致），按二进制读写，避免二次翻译。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TARGET = REPO / "docs/PAPER_REVISION_LOG_20261009.md"
FRAG = REPO / "work/tools/revision_log_section_L.md"


def main() -> int:
    old = TARGET.read_bytes()
    old_sha = hashlib.sha256(old).hexdigest()
    frag = FRAG.read_bytes()
    if not frag.strip():
        print("[FAIL] 片段为空")
        return 2
    if b"## L." not in frag:
        print("[FAIL] 片段缺 `## L.` 节标题")
        return 2
    # 行尾统一为 LF
    frag = frag.replace(b"\r\n", b"\n")
    if b"\r\n" in frag:
        print("[FAIL] 片段仍含 CRLF")
        return 2
    if old.count(b"\r\n") != 0:
        print("[FAIL] 目标文件不是纯 LF，拒绝")
        return 2
    if b"## L." in old:
        print("[SKIP] 目标已存在 `## L.` 节，未重复追加")
        return 0
    bk = REPO / "work/logs" / ("PAPER_REVISION_LOG_20261009.%s.md.bak"
                              % _dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    bk.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, bk)
    if not old.endswith(b"\n"):
        frag = b"\n" + frag
    new = old + frag
    if len(new) <= len(old):
        print("[FAIL] 字符数未增加")
        return 2
    TARGET.write_bytes(new)
    back = TARGET.read_bytes()
    ok_prefix = back.startswith(old)
    if back != new or not ok_prefix:
        print("[FAIL] 回读校验/前缀守卫不通过（ok_prefix=%s）" % ok_prefix)
        return 2
    if b"## L." not in back:
        print("[FAIL] 回读缺 `## L.`")
        return 2
    print("旧 sha256 = %s（%d B / %d 行）" % (old_sha, len(old), old.count(b"\n")))
    print("新 sha256 = %s（%d B / %d 行）" % (hashlib.sha256(back).hexdigest(), len(back), back.count(b"\n")))
    print("字符/字节 %d -> %d（+%d）" % (len(old), len(back), len(back) - len(old)))
    print("旧全文是新文件逐字节前缀？ %s" % ok_prefix)
    print("备份 = %s" % bk.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
