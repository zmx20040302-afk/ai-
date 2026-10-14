"""Peek 一个扫描结果表（CSV/XLSX）：行列数、列名、各扫描量的取值集合。

用法：python work\\tools\\peek_sweep_table.py <表路径>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    p = Path(sys.argv[1])
    print(f"文件：{p}")
    print(f"大小：{p.stat().st_size} B")
    if p.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        sheets = pd.read_excel(p, sheet_name=None)
        print(f"工作表：{list(sheets)}")
        df = next(iter(sheets.values()))
        if len(sheets) > 1:
            print("（只分析第一张表）")
    else:
        df = pd.read_csv(p, encoding="utf-8-sig")
    print(f"形状：{df.shape[0]} 行 × {df.shape[1]} 列")
    print("\n列名：")
    for i, c in enumerate(df.columns):
        nn = df[c].notna().sum()
        print(f"  [{i:2d}] {c!r}  非空={nn}")
    print("\n前 3 行：")
    print(df.head(3).to_string())

    # 猜测扫描量与频率列
    low = {c: str(c).lower() for c in df.columns}
    for key in ("x_scale", "n_w_te1", "freq", "ptot", "vave", "zin1_r", "zin1_x", "zin2"):
        hits = [c for c in df.columns if key.replace("_", "") in low[c].replace("_", "").replace(" ", "")]
        for h in hits:
            vals = df[h].dropna()
            uniq = np.unique(vals.values) if vals.dtype.kind in "if" else sorted(set(vals.astype(str)))
            print(f"\n[{key}] 列={h!r} 唯一值 {len(uniq)} 个：{list(uniq)[:20]}{' …' if len(uniq) > 20 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
