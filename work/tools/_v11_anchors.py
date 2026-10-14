# -*- coding: utf-8 -*-
"""为 v11 生成器取**逐字**锚点（打印 repr 与出现次数；不改任何文件）。"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
V10 = REPO / "docs" / "PMUT_DAC2027_初稿_v10_20261010.md"
b = V10.read_bytes()
t = b.decode("utf-8")
lines = t.split("\n")          # 末元素为空；每个非末行以 \r 结尾
print("v10 bytes=%d lines=%d sha256=%s" % (len(b), len(lines) - 1, hashlib.sha256(b).hexdigest()))
print("CRLF 纯？", b.count(b"\r\n") == b.count(b"\n") == b.count(b"\r"))

CANDS = [
    r"8 个代理通道中有 2 个未优于复制相邻层的 persistence 基线，其中包含正式设计目标 `bandwidth_Hz`（中位误差 0.00502 vs 基线 0.00322）",
    r"8 个代理通道中 2 个（含正式设计目标 `bandwidth_Hz`）未优于 persistence 基线",
    r"跨口径审计显示，不同带宽提取方法之间存在约 20% 的中位相对差异，但排序稳健（Spearman 0.9888）；",
    r"不同带宽提取口径存在约 20% 的中位差异（排序稳健：Spearman 0.9888），但绝对值不可跨口径混用；",
    r"；且实测该残差与 11.12% **同源于端口/电流口径缺陷**（`∫Jz` vs `∫J·n`、电路未闭合） |",
    r"**v10**（**只做 S3 / S0 / 模型身份的账目对齐**",
    r"> 日期：2026-10-10（**v10 修订日**；v9 同日；v1–v8 的修订日均为 2026-10-09）",
    r"> **v10 修订（本轮；",
    r"## 7. 讨论",
]
for c in CANDS:
    n = t.count(c)
    print("\n--- count=%d" % n)
    print("OLD = %r" % c)
    if n == 1:
        i = t.index(c)
        print("  上下文: %r" % t[max(0, i - 30):i + len(c) + 30])
for pat in ("## D. 图表", "## E. 写作与格式", "## A. 必须完成"):
    for m in re.finditer(re.escape(pat), t):
        j = t.index("\n", m.start())
        print("\n[%s] 行首: %r" % (pat, t[m.start():m.start() + 60]))
