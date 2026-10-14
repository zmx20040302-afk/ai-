# -*- coding: utf-8 -*-
"""自检 `docs/OPEN_ISSUES_FOR_CODEX.md`：结构 + 文中引用的仓库路径是否真实存在。

用途：这份文件要发给外部审阅方，**引用的路径如果不存在，等于给了坏线索**。
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
DOC = REPO / "docs/OPEN_ISSUES_FOR_CODEX.md"


def main() -> int:
    t = DOC.read_text(encoding="utf-8")
    print("bytes %d | lines %d | H2 节 %d | 表格 %d"
          % (len(t.encode("utf-8")), t.count("\n") + 1,
             len(re.findall(r"^## ", t, re.M)), t.count("|---")))
    print("sha256:", hashlib.sha256(DOC.read_bytes()).hexdigest()[:16])
    print()
    for h in re.findall(r"^## .*", t, re.M):
        print("  ", h)
    print()
    refs = re.findall(r"`((?:docs|work|scripts|tests|src)/[^`]+)`", t)
    missing = sorted({r for r in refs if not (REPO / r).exists()})
    print("引用仓库路径 %d 个；缺失 %d 个" % (len(set(refs)), len(missing)))
    for m in missing:
        print("   MISSING:", m)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
