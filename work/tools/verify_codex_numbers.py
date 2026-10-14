"""独立复核 Codex 回复中两类数字（我发出的简报里**并不包含**逐行数据，故必须自证）：

A. 批1/批2 重叠点的批间重复性（Codex §4.2 给的相对差中位数/95 分位/最大值）
B. 批2 限制到 N_w_te1<=8 后的顶边比例与峰值分布（Codex §5 给的 19/72、4/72 与分布表）

用法：python work\\tools\\verify_codex_numbers.py
"""

from __future__ import annotations

import csv
import io
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

B1 = Path(r"C:\Users\zmx\Desktop\换能器\扫面x&N1，间隔阵列扫描.csv")
B2 = Path(r"C:\Users\zmx\Desktop\memsharness\work\reports\analysis_decision\newrange005\raw_source_table.csv")


def load(path: Path) -> tuple[list[str], list[dict]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    grid = [r for r in csv.reader(io.StringIO(text)) if r]
    hi = next(i for i, r in enumerate(grid)
              if r and r[0].strip().lstrip("% ").strip() == "x_scale")
    header = [c.strip().lstrip("%").strip() for c in grid[hi]]
    rows = [dict(zip(header, r)) for r in grid[hi + 1:] if len(r) >= len(header) and r[0].strip()]
    return header, rows


def pct(vals: list[float], q: float) -> float:
    s = sorted(vals)
    if not s:
        return float("nan")
    idx = min(len(s) - 1, int(round(q * (len(s) - 1))))
    return s[idx]


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    h1, r1 = load(B1)
    h2, r2 = load(B2)
    print(f"批1：{len(r1)} 行；批2：{len(r2)} 行")

    key = lambda r: (round(float(r["x_scale"]), 4), int(float(r["N_w_te1"])), round(float(r["freq (Hz)"])))
    m1 = {key(r): r for r in r1}
    m2 = {key(r): r for r in r2}
    common = sorted(set(m1) & set(m2))
    xs = sorted({k[0] for k in common})
    n1s = sorted({k[1] for k in common})
    print(f"\n[A] 重叠：{len(common)} 行｜x_scale={xs}｜N_w_te1={n1s}"
          f"｜组合 {len(xs) * len(n1s)}")
    print("    Codex 声称：x=0.4,0.5,0.6,0.7,0.8；N1=1,2,3,4,5,6,8；35 组合 245 行")

    print("\n[A] 批间相对差 |a-b|/|a|（a=批1，b=批2）：")
    print(f"    {'指标':<12}{'中位数%':>10}{'95分位%':>10}{'最大%':>10}")
    codex_claim = {"Ptot": (0.67, 3.75, 5.50), "Vave": (0.32, 1.80, 2.88),
                   "Zin1_R": (0.84, 3.20, 4.83), "Zin1_X": (0.44, 1.86, 2.31)}
    for col in ("Ptot (W)", "Vave (m/s)", "Zin1_R (Ω)", "Zin1_X (Ω)"):
        diffs = []
        for k in common:
            try:
                a = float(m1[k][col]); b = float(m2[k][col])
            except (KeyError, ValueError):
                continue
            if a == 0:
                continue
            diffs.append(abs(b - a) / abs(a) * 100.0)
        name = col.split(" (")[0]
        cl = codex_claim.get(name)
        print(f"    {name:<12}{st.median(diffs):>10.3f}{pct(diffs, 0.95):>10.3f}{max(diffs):>10.3f}"
              f"   ← Codex 声称 {cl}")

    print("\n[B] 批2 限制 N_w_te1<=8 的顶边统计：")
    sub = defaultdict(list)
    for r in r2:
        n1 = int(float(r["N_w_te1"]))
        if n1 <= 8:
            sub[(float(r["x_scale"]), n1)].append(r)
    print(f"    组合数 = {len(sub)}（Codex 声称 72）")
    dist_p = Counter()
    dist_v = Counter()
    for g in sub.values():
        bp = max(g, key=lambda r: float(r["Ptot (W)"]))
        bv = max(g, key=lambda r: abs(float(r["Vave (m/s)"])))
        dist_p[round(float(bp["freq (Hz)"]) / 1e6)] += 1
        dist_v[round(float(bv["freq (Hz)"]) / 1e6)] += 1
    print(f"    Ptot 峰值落 35 MHz：{dist_p.get(35.0, 0)}/{len(sub)}（Codex 声称 19/72）")
    print(f"    Vave 峰值落 35 MHz：{dist_v.get(35.0, 0)}/{len(sub)}（Codex 声称 4/72）")
    print(f"    Ptot 峰值分布：{dict(sorted(dist_p.items()))}")
    print("    Codex 声称分布：{10:14, 15:11, 20:8, 25:8, 30:12, 35:19}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
