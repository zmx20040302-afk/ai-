# -*- coding: utf-8 -*-
"""只读：对给定关键词打印「行号 + 上下文」，用于精确构造替换锚点。

用法： python -X utf8 work\tools\_v9_ctx.py <kw> [<kw> ...]
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
V8 = ROOT / "docs" / "PMUT_DAC2027_初稿_v8_20261009.md"
WIN = 90


def main() -> int:
    text = V8.read_bytes().decode("utf-8")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    for kw in sys.argv[1:]:
        print("#" * 30, kw)
        for i, ln in enumerate(lines, 1):
            start = 0
            while True:
                j = ln.find(kw, start)
                if j < 0:
                    break
                a = max(0, j - WIN)
                b = min(len(ln), j + len(kw) + WIN)
                print("L%d [%d] ...%s..." % (i, j, ln[a:b]))
                start = j + 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
