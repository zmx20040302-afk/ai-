# -*- coding: utf-8 -*-
"""只读：把指定行按固定宽度切块打印，避免 read 工具 2000 字符截断。

用法： python -X utf8 work\tools\_v9_chunk.py <lineno> [<lineno> ...]
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
V8 = ROOT / "docs" / "PMUT_DAC2027_初稿_v8_20261009.md"
W = 700


def main() -> int:
    lines = V8.read_bytes().decode("utf-8").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    for spec in sys.argv[1:]:
        n = int(spec)
        ln = lines[n - 1]
        print("===L%d=== len=%d chunks=%d" % (n, len(ln), (len(ln) + W - 1) // W))
        for k in range(0, len(ln), W):
            print("  [%05d] %s" % (k, ln[k:k + W]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
