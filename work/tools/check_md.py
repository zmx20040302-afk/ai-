"""Markdown 简报自检：行数、标题层级、行内代码反引号配平、表格列数一致性。

用法：python work\\tools\\check_md.py <file.md>
不用 PowerShell here-string 传代码（双引号 here-string 会把反引号当转义符，实测会毁掉检查本身）。
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    p = Path(sys.argv[1])
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    print(f"文件：{p}")
    print(f"字节：{p.stat().st_size}｜行数：{len(lines)}｜以换行结尾：{text.endswith(chr(10))}")

    odd = [(i + 1, l.count("`"), l[:60]) for i, l in enumerate(lines) if l.count("`") % 2]
    print(f"\n反引号奇数行（代码跨度跨行时会正常出现，需人工看）：{len(odd)}")
    for n, c, t in odd[:10]:
        print(f"  L{n} count={c}: {t}")

    print("\n标题层级：")
    for i, l in enumerate(lines, 1):
        if l.startswith("#"):
            print(f"  L{i}: {l[:70]}")

    # 表格：连续以 | 开头的行块内，列数是否一致
    bad = []
    block = []
    start = 0
    for i, l in enumerate(lines + [""], 1):
        if l.startswith("|"):
            if not block:
                start = i
            block.append((i, l.count("|")))
        else:
            if len(block) > 1:
                counts = {c for _, c in block}
                if len(counts) > 1:
                    bad.append((start, counts, [b[0] for b in block]))
            block = []
    print(f"\n列数不一致的表格块：{len(bad)}")
    for s, counts, rows in bad[:6]:
        print(f"  起始 L{s}｜列管道数 {sorted(counts)}｜行 {rows[:6]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
