# -*- coding: utf-8 -*-
"""只读辅助：显示 v8 指定行区间（按 LF 切、去行尾 CR），供人工核对片段。

用法： python -X utf8 work\tools\_v9_show.py <from> <to> [path]
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "docs" / "PMUT_DAC2027_初稿_v8_20261009.md"


def main() -> int:
    a = int(sys.argv[1])
    b = int(sys.argv[2])
    p = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT
    raw = p.read_bytes()
    if raw.count(b"\r\n") != raw.count(b"\n") or raw.count(b"\r") != raw.count(b"\n"):
        print("WARN not pure CRLF")
        return 1
    lines = raw.decode("utf-8").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    print("lines(total by LF, excl trailing empty) = %d" % len(lines))
    for i in range(a, min(b, len(lines)) + 1):
        print("===L%d=== len=%d" % (i, len(lines[i - 1])))
        print(lines[i - 1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
