"""把源码/脚本里残留的**旧机**路径从用法示例中清掉（只动注释与文档字符串）。

背景：这些文件里的「用法」示例写的是旧机的 ASCII 交汇点绝对路径
（``C:\\Users\\18161\\memsharness_work\\repo\\...``）。本机仓库根是纯 ASCII 路径
（``C:\\Users\\zmx\\Desktop\\memsharness``），不需要交汇点，且那条路径在本机不存在——
照着示例敲命令必然失败。本脚本把前缀删掉，改成相对仓库根的写法。

只删「用法示例」里的绝对前缀与「经 ASCII 交汇点」这半句；**不改任何可执行代码**。
``WORKING_PLAN.md`` 里的旧机记录属于历史事实，刻意不动。

用法：
    python work\\tools\\strip_old_paths.py --check    # 只报告
    python work\\tools\\strip_old_paths.py            # 就地替换
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# 文档字符串里是转义后的双反斜杠形式；两种写法都清
PATTERNS = (
    r"C:\\Users\\18161\\memsharness_work\\repo\\",
    r"C:\Users\18161\memsharness_work\repo\\",
    r"C:\Users\18161\memsharness_work\repo",
    "用法（经 ASCII 交汇点）：",
    "用法（经 ASCII 交汇点）:",
)

REPLACEMENTS = {
    "用法（经 ASCII 交汇点）：": "用法（在仓库根下执行）：",
    "用法（经 ASCII 交汇点）:": "用法（在仓库根下执行）:",
}


def targets() -> list[Path]:
    files = sorted((REPO / "scripts").glob("*.py"))
    files += sorted((REPO / "scripts").glob("*.mjs"))
    files += sorted((REPO / "src").rglob("*.py"))
    return [f for f in files if f.is_file()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只报告不修改")
    args = ap.parse_args()

    total = 0
    for path in targets():
        text = path.read_text(encoding="utf-8")
        original = text
        for pattern in PATTERNS:
            if pattern in text:
                text = text.replace(pattern, REPLACEMENTS.get(pattern, ""))
        if text != original:
            hits = sum(original.count(p) for p in PATTERNS)
            total += hits
            rel = path.relative_to(REPO)
            print(f"  {rel}：{hits} 处")
            if not args.check:
                path.write_text(text, encoding="utf-8")
    print(f"{'将修改' if args.check else '已修改'} {total} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
