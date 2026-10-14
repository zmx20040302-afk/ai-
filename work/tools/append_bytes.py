# -*- coding: utf-8 -*-
"""按二进制方式把一段 CRLF markdown 追加到既有文本产物（复用第 173 节的字节级校验）。

用法：`python append_bytes.py <目标文件> <追加段文件>`
校验：新文件逐字节以原文件为前缀 + 增量 == 追加段长度（行尾按目标文件尾部惯例对齐）。
"""
from __future__ import annotations

import hashlib
import pathlib
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
LOG = REPO / "work/logs"


def main() -> int:
    tgt = pathlib.Path(sys.argv[1])
    src = pathlib.Path(sys.argv[2])
    base = tgt.read_bytes()
    h0 = hashlib.sha256(base).hexdigest()
    LOG.mkdir(parents=True, exist_ok=True)
    bak = LOG / ("%s.%s.bak" % (tgt.name, time.strftime("%Y%m%dT%H%M%S")))
    shutil.copy2(tgt, bak)
    tail_eol = "CRLF" if base.endswith(b"\r\n") else ("LF" if base.endswith(b"\n") else "无行尾")
    sec = src.read_bytes()
    if not sec.startswith(b"\n"):
        sec = b"\n" + sec
    sec = sec.replace(b"\r\n", b"\n")
    sec = sec.replace(b"\n", b"\r\n") if tail_eol == "CRLF" else sec
    if not sec.endswith(b"\n"):
        sec += b"\r\n" if tail_eol == "CRLF" else b"\n"
    with tgt.open("ab") as fh:
        fh.write(sec)
    new = tgt.read_bytes()
    ok = new[: len(base)] == base and len(new) - len(base) == len(sec)
    print("备份      :", bak)
    print("原文件    : %d B sha %s" % (len(base), h0[:24]))
    print("追加段    : %d B（行尾 %s）" % (len(sec), tail_eol))
    print("新文件    : %d B sha %s" % (len(new), hashlib.sha256(new).hexdigest()[:24]))
    print("字节级校验:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
