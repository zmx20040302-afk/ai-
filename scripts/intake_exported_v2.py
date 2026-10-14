# -*- coding: utf-8 -*-
"""盘点 `exported_results_v2`（远端第二条导出管线）并落 sha256 清单。

只读本地副本，不改任何既有数据。输出：
* `inventory.json`：逐文件 sha256 / 大小 + 每个 cell 的表结构（列名、行数、参数列取值）；
* 屏幕摘要：cell → 参数组合、表行数、是否含 N2=9 等关键信息。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "work/runs/remote-exported-v2-20260922/exported_results_v2"


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def head_rows(p: pathlib.Path, n: int = 6) -> list[str]:
    out: list[str] = []
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for i, ln in enumerate(fh):
            if i >= n:
                break
            out.append(ln.rstrip("\n")[:200])
    return out


def main() -> int:
    if not SRC.exists():
        print("[FAIL] 缺目录：%s" % SRC)
        return 2
    inv: dict = {"source": "ubuntu-10-180-7-46:/home/lab/projAI4US/autodesign/exported_results_v2",
                 "downloaded_local": str(SRC.relative_to(REPO)), "cells": {}, "files": {}}
    files = sorted(p for p in SRC.rglob("*") if p.is_file())
    for p in files:
        inv["files"][str(p.relative_to(SRC))] = {"sha256": sha(p), "bytes": p.stat().st_size}
    print("== 文件清单 ==")
    for rel, m in inv["files"].items():
        print("  %-72s %9d B  %s" % (rel, m["bytes"], m["sha256"][:16] + "…"))

    print("\n== 批次元数据 ==")
    for name in ("_batch_20260922_193356_3617633/exit_code.txt",
                 "_batch_20260922_193356_3617633/status.txt",
                 "_batch_20260922_193356_3617633/server.log",
                 "_batch_20260922_193356_3617633/matlab.log"):
        p = SRC / name
        if p.exists():
            print("  --- %s ---" % name)
            for ln in head_rows(p, 40):
                print("     ", ln)

    print("\n== 各 cell 的表结构 ==")
    for cell in sorted(p for p in SRC.iterdir() if p.is_dir() and p.name.startswith("cell_")):
        info: dict = {"txt": {}}
        print("\n  ### %s" % cell.name)
        for t in sorted(cell.glob("*.txt")):
            lines = head_rows(t, 6)
            n_rows = sum(1 for _ in t.open("r", encoding="utf-8", errors="replace"))
            info["txt"][t.name] = {"n_lines": n_rows, "head": lines}
            print("    %-22s 行 %7d" % (t.name, n_rows))
            for ln in lines[:4]:
                print("        %s" % ln)
        inv["cells"][cell.name] = info

    out = SRC.parent / "inventory.json"
    out.write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n清单：", out.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
