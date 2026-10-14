"""解析用户 COMSOL 扫描结果（x_scale × N_w_te1），做数据质量与趋势分析。

不改动原文件；只读、只报告，不做物理外推（超出数据的结论一律标注为"待验证"）。
"""

from __future__ import annotations

import cmath
import re
from collections import defaultdict
from pathlib import Path

D = Path(r"C:\Users\zmx\Desktop\换能器")
CSV = D / "扫面x&N1，间隔阵列扫描.csv"

HEADER_KEYS = ("x_scale", "N_w_te1", "freq (Hz)", "Ptot (W)")


def parse_complex(text: str) -> complex | None:
    """解析 COMSOL 复数字符串：'1.2e-4' / '4.06e-9-3.54e-4i' / '-0.5i'。"""
    text = text.strip().replace(" ", "")
    if not text:
        return None
    if text.endswith("i"):
        body = text[:-1]
        # 找到最后一个 +/-（且不在指数里）作为实部/虚部分界
        match = None
        for m in re.finditer(r"[+-](?![0-9]*[eE][+-]?$)", body):
            match = m
        if match and match.start() != 0 and body[match.start() - 1] not in "eE":
            real, imag = body[: match.start()], body[match.start():]
            try:
                return complex(float(real), float(imag))
            except ValueError:
                return None
        try:
            return complex(0.0, float(body))
        except ValueError:
            return None
    try:
        return complex(float(text), 0.0)
    except ValueError:
        return None


text = CSV.read_text(encoding="utf-8-sig", errors="replace")
import csv as _csv
import io as _io

grid = [r for r in _csv.reader(_io.StringIO(text)) if r]
header_idx = next(i for i, r in enumerate(grid) if r and "x_scale" in r[0])
meta = [" , ".join(r) for r in grid[:header_idx]]
header = [c.strip() for c in grid[header_idx]]
header[0] = header[0].lstrip("%").strip()
print("== 文件头（元信息）==")
for ln in meta:
    print("  " + ln)
print(f"\n== 表头（{len(header)} 列）==\n  {header}")

rows = []
for r in grid[header_idx + 1:]:
    if len(r) < len(header) or not r[0].strip():
        continue
    rows.append(dict(zip(header, r)))
print(f"\n数据行数：{len(rows)}")

by_combo: dict[tuple[float, float], list[dict]] = defaultdict(list)
for r in rows:
    by_combo[(float(r["x_scale"]), float(r["N_w_te1"]))].append(r)

xs = sorted({k[0] for k in by_combo})
n1s = sorted({k[1] for k in by_combo})
print(f"x_scale 取值 {len(xs)} 个：{xs}")
print(f"N_w_te1 取值 {len(n1s)} 个：{n1s}")
print(f"组合数 {len(by_combo)}（满格应为 {len(xs) * len(n1s)}）")

freqs_global = sorted({float(r["freq (Hz)"]) for r in rows})
print(f"出现过的频率 {len(freqs_global)} 个：{[f/1e6 for f in freqs_global]} MHz")

counts = defaultdict(int)
for k, v in by_combo.items():
    counts[len(v)] += 1
print(f"每个组合的行数分布：{dict(counts)}")

missing = [(x, n) for x in xs for n in n1s if (x, n) not in by_combo]
print(f"缺失组合 {len(missing)} 个：{missing[:20]}")

incomplete = {k: len(v) for k, v in by_combo.items() if len(v) != max(counts)}
print(f"行数不足的组合 {len(incomplete)} 个：{dict(list(incomplete.items())[:20])}")

# ---- 数据质量 ----
same_zin = sum(
    1 for r in rows
    if r["Zin1_R (Ω)"] == r["Zin2_R (Ω)"] and r["Zin1_X (Ω)"] == r["Zin2_X (Ω)"]
)
print(f"\n== 数据质量 ==")
print(f"  Zin2 与 Zin1 完全相同的行：{same_zin}/{len(rows)}"
      f"（旧机在 bGEtask2 上发现 Zin2 用 I01 定义 ⇒ 恒等于 Zin1，此处一致）")
complex_cols = [c for c in header if c.endswith("(m/s)")]
print(f"  复数列：{complex_cols}（需按 a+bi 解析；本分析用 cmath 处理）")

# ---- 趋势：每个组合的谐振相关指标 ----
print("\n== 每个组合的指标（按 x_scale 排序，取 N_w_te1=1 与 =8 对照）==")
print(f"{'x_scale':>8}{'N_w_te1':>9}{'n_freq':>7}{'f@maxPtot':>11}{'Ptot_max':>12}"
      f"{'f@max|Vave|':>13}{'|Vave|max':>11}{'min|Zin1|':>11}{'f@min|Zin1|':>12}{'f@max|Vc|':>11}")
summary = {}
for key in sorted(by_combo):
    group = by_combo[key]
    if key[1] not in (1, 8):
        continue
    gp = max(group, key=lambda r: float(r["Ptot (W)"]))
    gv = max(group, key=lambda r: abs(float(r["Vave (m/s)"])))
    gz = min(group, key=lambda r: abs(complex(float(r["Zin1_R (Ω)"]), float(r["Zin1_X (Ω)"]))))
    vc = [(r, abs(parse_complex(r["V_center (m/s)"]) or 0j)) for r in group]
    gc = max(vc, key=lambda t: t[1])
    print(f"{key[0]:>8.2f}{key[1]:>9.0f}{len(group):>7}"
          f"{float(gp['freq (Hz)'])/1e6:>11.1f}{float(gp['Ptot (W)']):>12.4g}"
          f"{float(gv['freq (Hz)'])/1e6:>13.1f}{float(gv['Vave (m/s)']):>11.4g}"
          f"{abs(complex(float(gz['Zin1_R (Ω)']), float(gz['Zin1_X (Ω)']))):>11.4g}"
          f"{float(gz['freq (Hz)'])/1e6:>12.1f}{float(gc[0]['freq (Hz)'])/1e6:>11.1f}")
    summary[key] = {
        "f_maxPtot_MHz": float(gp["freq (Hz)"]) / 1e6,
        "Ptot_max": float(gp["Ptot (W)"]),
        "f_maxVave_MHz": float(gv["freq (Hz)"]) / 1e6,
        "Vave_max": float(gv["Vave (m/s)"]),
        "min_absZ_MHz": float(gz["freq (Hz)"]) / 1e6,
        "min_absZ": abs(complex(float(gz["Zin1_R (Ω)"]), float(gz["Zin1_X (Ω)"]))),
        "f_maxVc_MHz": float(gc[0]["freq (Hz)"]) / 1e6,
        "absVc_max": gc[1],
    }

print("\n== 该表覆盖的频率是否完整（抽查 3 个组合）==")
for key in list(sorted(by_combo))[:3]:
    fr = sorted(float(r["freq (Hz)"]) / 1e6 for r in by_combo[key])
    print(f"  x_scale={key[0]}, N_w_te1={key[1]}: {fr}")

# ---- 只输出可复算的摘要，供后续入库 ----
out = Path(r"C:\Users\zmx\Desktop\memsharness\work\reports\modelio\sweep-xN1-summary.json")
out.parent.mkdir(parents=True, exist_ok=True)
import json

out.write_text(
    json.dumps(
        {
            "source_csv": str(CSV),
            "header": header,
            "meta": meta,
            "n_rows": len(rows),
            "unique_x_scale": xs,
            "unique_N_w_te1": n1s,
            "frequencies_MHz": [f / 1e6 for f in freqs_global],
            "rows_per_combo_histogram": {str(k): v for k, v in counts.items()},
            "missing_combos": missing,
            "zin2_equals_zin1_rows": same_zin,
            "combo_summary": {f"{k[0]}|{k[1]}": v for k, v in summary.items()},
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(f"\n摘要已落档：{out}")
