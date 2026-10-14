# -*- coding: utf-8 -*-
"""修复 §173 追加：**二进制级**保持既有字节不变，只在末尾追加。

教训（本轮实测）：`Path.write_text(..., newline="\\n")` 会把整份文件的行尾**归一化成 LF**，
而该 INDEX 是**混合行尾**（原盘 1,297,842 B → 归一化后 1,292,760 B，少 5,082 B）⇒ 虽然语义相同，
但**逐字节改写了下游历史**，违反 append-only。本脚本改成：
  1. 从备份按字节恢复；
  2. 记录恢复后的**盘面 sha256 与字节数**（作为 §173 之前的基线）；
  3. 用 `open(..., "ab")` **二进制追加**新章节（行尾与文件尾部惯例一致）；
  4. 校验：新文件**逐字节以原文件为前缀**，且增量 == 追加段长度。
"""
from __future__ import annotations

import hashlib
import pathlib
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
IDX = REPO / "docs/INDEX-records-and-rulings.md"
SEC = REPO / "work/runs/eda64-20261010/INDEX_SECTION_173.md"
LOG = REPO / "work/logs"
BAK = LOG / "INDEX-records-and-rulings.md.20261011T104355.bak"
MARK = "## 173. P3 族级独立留出".encode("utf-8")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    base = BAK.read_bytes()
    print("基线（备份，字节恢复）: %d B sha %s" % (len(base), sha(base)[:24]))
    assert MARK not in base, "备份里已含 §173，拒绝操作"
    # 尾部惯例
    tail_eol = "CRLF" if base.endswith(b"\r\n") else ("LF" if base.endswith(b"\n") else "无行尾")
    print("文件尾部行尾          :", tail_eol)
    shutil.copy2(BAK, IDX)
    assert IDX.read_bytes() == base
    sec = SEC.read_bytes()
    if not sec.startswith(b"\n"):
        sec = b"\n" + sec
    if tail_eol == "CRLF":
        sec = sec.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    else:
        sec = sec.replace(b"\r\n", b"\n")
    if not sec.endswith(b"\n"):
        sec += b"\r\n" if tail_eol == "CRLF" else b"\n"
    with IDX.open("ab") as fh:
        fh.write(sec)
    new = IDX.read_bytes()
    ok_prefix = new[: len(base)] == base
    print("追加段                : %d B（行尾 %s）" % (len(sec), tail_eol))
    print("新文件                : %d B sha %s" % (len(new), sha(new)[:24]))
    print("逐字节以原文件为前缀  :", ok_prefix)
    print("增量 == 追加段        :", len(new) - len(base) == len(sec))
    print("含 §173 标记          :", MARK in new)
    return 0 if (ok_prefix and len(new) - len(base) == len(sec) and MARK in new) else 1


if __name__ == "__main__":
    raise SystemExit(main())
