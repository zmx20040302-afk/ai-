# -*- coding: utf-8 -*-
"""扫描仓库文档里的**未完成项标记**，为「遗留任务盘点」提供原始清单。

为什么需要脚本：遗留项散落在几十个 md 里（docs/、work/runs/*/），人眼扫必漏；
且必须**连行号一起**给出，才能逐条回原文核对上下文，避免把"已经说完成"的句子误读成"待办"。

用法：
    python -B work/tools/scan_pending_items.py [--json]
输出：按文件分组的命中行（行号 + 截断原文）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

#: 待办/未完成标记（中文为主，兼顾英文）
MARKERS = [
    "TODO", "FIXME", "待办", "未完成", "待定", "待用户", "待数据", "待确认",
    "尚未", "还没", "暂不", "待补", "toBeDone", "TBD", "未做", "需要补",
    "等待", "阻塞", "挂起", "下一步", "待办事项", "遗留", "未接",
]
#: 「已说明完成」的措辞：命中这些的句子**优先级降低**（但仍列出，供人工确认）
DONE_HINTS = ["已完成", "已补", "已修", "已解决", "已关闭", "已通过", "已实现", "已固化"]
#: 只扫这些目录下的 md（避免把 work/runs 里的海量产物日志全扫进来）
SCAN_DIRS = ["docs", "."]
EXTRA_GLOBS = ["work/runs/*/*.md", "work/*.md"]


def iter_files() -> list[pathlib.Path]:
    out: set[pathlib.Path] = set()
    for d in SCAN_DIRS:
        base = REPO if d == "." else REPO / d
        if not base.is_dir():
            continue
        depth = 1 if d == "." else 2
        for p in base.glob("*.md" if depth == 1 else "**/*.md"):
            out.add(p)
    for g in EXTRA_GLOBS:
        for p in REPO.glob(g):
            out.add(p)
    # 排除明显的产物/历史归档
    skip = ("node_modules", ".git", ".venv")
    return sorted(p for p in out if not any(s in p.parts for s in skip))


def main(argv: list[str]) -> int:
    want_json = "--json" in argv
    rows = []
    for p in iter_files():
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines, 1):
            hit = [m for m in MARKERS if m in ln]
            if not hit:
                continue
            low_pri = any(d in ln for d in DONE_HINTS)
            rows.append({
                "file": str(p.relative_to(REPO)).replace("\\", "/"),
                "line": i, "markers": hit, "done_hint": low_pri,
                "text": re.sub(r"\s+", " ", ln.strip())[:190],
            })
    if want_json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    by = {}
    for r in rows:
        by.setdefault(r["file"], []).append(r)
    print("命中行合计 %d，涉及文件 %d 个\n" % (len(rows), len(by)))
    for f in sorted(by, key=lambda k: -len(by[k])):
        rs = by[f]
        hi = [r for r in rs if not r["done_hint"]]
        print("%-58s %3d 行（其中未带「已…」说明 %d）" % (f, len(rs), len(hi)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
