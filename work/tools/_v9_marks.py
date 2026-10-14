# -*- coding: utf-8 -*-
"""只读：统计 v8 中标记字面出现位置与计数。"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
V8 = ROOT / "docs" / "PMUT_DAC2027_初稿_v8_20261009.md"

MARKS = ["【待裁定】", "【待产物】", "【待补】"]


def main() -> int:
    raw = V8.read_bytes()
    text = raw.decode("utf-8")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    for m in MARKS:
        print("=" * 20, m, "total =", text.count(m))
        for i, ln in enumerate(lines, 1):
            c = ln.count(m)
            if c:
                print("  L%d x%d: %s" % (i, c, ln[:150]))
    print("=" * 20)
    for kw in ["λ/11", "l/11", "2.272", "1.685", "0.827", "~2.6%", "8 档", "56 有序对", "9 档", "72 有序对"]:
        print("%-12s total=%d" % (kw, text.count(kw)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
