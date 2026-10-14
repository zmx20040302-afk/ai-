# -*- coding: utf-8 -*-
"""独立复核 `dup_kind_refined` 派生视图：行数 / 列数 / 前 30 列逐行逐字 / v3 未变（只读）。"""
from __future__ import annotations

import csv
import hashlib
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
V3 = REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv"
OUT = REPO / "work/runs/labels-dupkind-refined/20261008T215100/labels_two_batch_dupkind_refined.csv"
V3_SHA = "20e28ba12457ce5b553fce3d02c0e4f59e7861370775ecf4cf68b0dff6a3a590"


def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    a = list(csv.reader(V3.open(encoding="utf-8", newline="")))
    b = list(csv.reader(OUT.open(encoding="utf-8", newline="")))
    print("v3 rows/cols        :", len(a) - 1, len(a[0]))
    print("out rows/cols       :", len(b) - 1, len(b[0]))
    print("header 前30列相同   :", a[0] == b[0][:30])
    print("新增列名            :", b[0][30])
    diff = sum(1 for x, y in zip(a[1:], b[1:]) if x != y[:30])
    print("前30列有差异的行数  :", diff)
    print("行数相同            :", len(a) == len(b))
    print("v3 sha256 复核      :", sha(V3), sha(V3) == V3_SHA)
    print("out sha256          :", sha(OUT))
    print("out bytes           :", OUT.stat().st_size)
    # 空/非空统计
    ne = sum(1 for r in b[1:] if r[30].strip())
    print("新增列非空行数      :", ne, " 空行数:", len(b) - 1 - ne)
    return 0 if (len(a) == len(b) and a[0] == b[0][:30] and diff == 0
                 and sha(V3) == V3_SHA) else 2


if __name__ == "__main__":
    sys.exit(main())
