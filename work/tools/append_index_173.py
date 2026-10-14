# -*- coding: utf-8 -*-
"""把 §173 追加进 docs/INDEX-records-and-rulings.md（append-only；先备份、再校验）。"""
from __future__ import annotations

import hashlib
import io
import pathlib
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
IDX = REPO / "docs/INDEX-records-and-rulings.md"
SEC = REPO / "work/runs/eda64-20261010/INDEX_SECTION_173.md"
LOG = REPO / "work/logs"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    before = IDX.read_text(encoding="utf-8")
    if "## 173. P3 族级独立留出" in before:
        print("已存在 §173，拒绝重复追加")
        return 1
    sec = SEC.read_text(encoding="utf-8")
    LOG.mkdir(parents=True, exist_ok=True)
    bak = LOG / ("INDEX-records-and-rulings.md.%s.bak" % time.strftime("%Y%m%dT%H%M%S"))
    shutil.copy2(IDX, bak)
    h0, n0 = sha(IDX), before.count("\n") + 1
    tail = before if before.endswith("\n") else before + "\n"
    IDX.write_text(tail + sec, encoding="utf-8", newline="\n")
    after = IDX.read_text(encoding="utf-8")
    ok_prefix = after.startswith(before.rstrip("\n"))
    print("backup      :", bak)
    print("before      : %d 行 %d B sha %s" % (n0, IDX.stat().st_size, h0[:16]))
    print("after       : %d 行 %d B sha %s" % (after.count("\n") + 1, IDX.stat().st_size, sha(IDX)[:16]))
    print("前缀未改写  :", ok_prefix)
    print("含 §173     :", "## 173. P3 族级独立留出" in after)
    return 0 if ok_prefix and "## 173." in after else 1


if __name__ == "__main__":
    raise SystemExit(main())
