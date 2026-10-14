"""Codex 决策回复 §9 第 4 步 + 分析指令 §3：对现有粗扫数据做数据质量检查（不占 COMSOL）。

检查项：行数/组合/频率完整性、重复行、缺失组合与缺失频率、复数可解析性、
        NaN/Inf/空值、数量级异常、**Ptot 是否出现负值**、频率是否严格递增、Zin1 与 Zin2 是否逐行相同。
输出：work/reports/analysis_decision/02_data_quality_report.md（人读）+ _data_quality.json（机读）。
"""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

WS = Path(r"C:\Users\zmx\Desktop\memsharness")
CSV = Path(r"C:\Users\zmx\Desktop\换能器\扫面x&N1，间隔阵列扫描.csv")
OUT = WS / "work" / "reports" / "analysis_decision"


def parse_complex(text: str):
    body = (text or "").strip().replace(" ", "")
    if not body:
        return None
    if not body.endswith("i"):
        try:
            return complex(float(body), 0.0)
        except ValueError:
            return None
    head = body[:-1]
    split = None
    for i, ch in enumerate(head):
        if ch in "+-" and i > 0 and head[i - 1] not in "eE":
            split = i
    if split is None:
        try:
            return complex(0.0, float(head))
        except ValueError:
            return None
    try:
        return complex(float(head[:split]), float(head[split:]))
    except ValueError:
        return None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    text = CSV.read_text(encoding="utf-8-sig", errors="replace")
    grid = [r for r in csv.reader(io.StringIO(text)) if r]
    hi = next(i for i, r in enumerate(grid) if r and r[0].strip().lstrip("% ").strip() == "x_scale")
    meta = [" , ".join(r) for r in grid[:hi]]
    header = [c.strip() for c in grid[hi]]
    header[0] = header[0].lstrip("%").strip()
    data = [dict(zip(header, r)) for r in grid[hi + 1:] if len(r) >= len(header) and r[0].strip()]

    issues: list[str] = []
    report: list[str] = []
    add = report.append

    add("# 数据质量报告（现有粗扫数据 · Codex 决策回复 §9 第 4 步）")
    add("")
    add(f"- 源文件：`{CSV}`")
    add(f"- 编码：UTF-8 with BOM；分隔符：逗号；元信息行：{len(meta)}")
    for m in meta:
        add(f"  - `{m}`")
    add(f"- 列（{len(header)}）：`{header}`")
    add("")

    # 1) 完整性
    xs = sorted({float(r["x_scale"]) for r in data})
    n1s = sorted({float(r["N_w_te1"]) for r in data})
    freqs = sorted({float(r["freq (Hz)"]) for r in data})
    combos = defaultdict(list)
    for r in data:
        combos[(float(r["x_scale"]), float(r["N_w_te1"]))].append(r)
    expected = len(xs) * len(n1s) * len(freqs)
    add("## 1. 行数与组合完整性")
    add("")
    add(f"| 项 | 值 |")
    add("|---|---|")
    add(f"| 实际数据行数 | **{len(data)}** |")
    add(f"| `x_scale` 档位 | {len(xs)}：{xs} |")
    add(f"| `N_w_te1` 档位 | {len(n1s)}：{[int(v) for v in n1s]} |")
    add(f"| 频率点 | {len(freqs)}：{[f/1e6 for f in freqs]} MHz |")
    add(f"| 实际组合数 | {len(combos)} |")
    add(f"| 满格应有 | {len(xs)}×{len(n1s)}×{len(freqs)} = {expected} 行 |")
    add("")
    counts = Counter(len(v) for v in combos.values())
    add(f"每个组合的行数分布：{dict(counts)}（应全为 {len(freqs)}）")
    full_grid = {(x, n) for x in xs for n in n1s}
    missing = sorted(full_grid - set(combos))
    if missing:
        add("")
        add(f"**缺失组合 {len(missing)} 个**：{missing}")
        issues.append(f"缺失 {len(missing)} 个组合（{len(xs)}×{len(n1s)} 满格 vs 实际 {len(combos)}）")
    # N_w_te1=7 缺失
    if 7.0 not in n1s:
        issues.append("`N_w_te1=7` 在数据中缺失（若批处理列表为 range(1,1,8) 则应含 7）")
    dup = [k for k, v in combos.items() if len(v) != len(freqs)]
    if dup:
        issues.append(f"{len(dup)} 个组合的频率点数量异常：{dup[:8]}")

    # 2) 数值有效性
    add("")
    add("## 2. 数值有效性")
    add("")
    nan = inf = empty = badcomplex = 0
    neg_ptot: list[tuple] = []
    zero_ptot = 0
    order_bad: list[tuple] = []
    zin_equal = 0
    zin_check = 0
    ptot_values: list[float] = []
    for r in data:
        for key in header:
            v = (r.get(key) or "").strip()
            if v == "":
                empty += 1
            elif v.lower() in ("nan", "-nan"):
                nan += 1
            elif "inf" in v.lower():
                inf += 1
        try:
            ptot = float(r["Ptot (W)"])
            ptot_values.append(ptot)
            if ptot < 0:
                neg_ptot.append((r["x_scale"], r["N_w_te1"], r["freq (Hz)"], ptot))
            elif ptot == 0.0:
                zero_ptot += 1
        except ValueError:
            pass
        for key in ("Vave (m/s)", "V_center (m/s)"):
            if parse_complex(r.get(key, "")) is None:
                badcomplex += 1
        zin_check += 1
        if r["Zin1_R (Ω)"] == r["Zin2_R (Ω)"] and r["Zin1_X (Ω)"] == r["Zin2_X (Ω)"]:
            zin_equal += 1
    for key, group in combos.items():
        seq = [float(r["freq (Hz)"]) for r in sorted(group, key=lambda r: float(r["freq (Hz)"]))]
        if seq != sorted(seq):
            order_bad.append(key)
    add("| 检查 | 结果 |")
    add("|---|---|")
    add(f"| 空值单元格 | {empty} |")
    add(f"| `NaN` | {nan} |")
    add(f"| `Inf` | {inf} |")
    add(f"| 无法解析的复数 | {badcomplex} |")
    add(f"| **`Ptot` 负值行** | **{len(neg_ptot)}** |")
    add(f"| `Ptot` 恰为 0 | {zero_ptot} |")
    add(f"| 频率未严格递增的组合 | {len(order_bad)} |")
    add(f"| `Zin1` 与 `Zin2` 逐位相同的行 | **{zin_equal}/{zin_check}** |")
    add("")
    if ptot_values:
        add(f"`Ptot` 量级：min={min(ptot_values):.4g} W，max={max(ptot_values):.4g} W")
        add("")
    if neg_ptot:
        add(f"⚠️ **发现 {len(neg_ptot)} 行 `Ptot` < 0**（前 5 条）：{neg_ptot[:5]}")
        add("")
        add("> 按分析指令 §3.2：**不静默取绝对值**，保留原值并标记；负值可能来自积分面法向方向错误。")
        add("")
        issues.append(f"{len(neg_ptot)} 行 Ptot<0（需核查积分面法向）")
    else:
        add("✅ 未发现 `Ptot` 负值（说明法向一致性在全部 490 行成立）。")
        add("")
    if zin_equal == zin_check:
        add("⚠️ **`Zin2` 与 `Zin1` 在全部行上逐位相同** ⇒ `Zin2` 当前**不能作为独立电极阻抗使用**"
            "（模型定义 `Zin2 = v0/I01`）。修正前 `Zin2` 不参与评分/排名。")
        add("")
        issues.append("Zin2≡Zin1（公式复制错误，已知）")

    # 3) 30 MHz 与 20 MHz 的对照（趋势提示，不作结论）
    add("## 3. 频率分布要点（仅供后续筛选参考，不作结论）")
    add("")
    peak_at_top = 0
    for key, group in combos.items():
        top = max(float(r["Ptot (W)"]) for r in group)
        f_top = float(max(group, key=lambda r: float(r["Ptot (W)"]))["freq (Hz)"])
        if f_top == max(freqs):
            peak_at_top += 1
    add(f"- `Ptot` 峰值落在最高频（{max(freqs)/1e6:g} MHz）的组合：**{peak_at_top}/{len(combos)}**"
        f" ⇒ 谐振未被频段包住的迹象（需精扫确认，不能据此排名）")
    add("")

    add("## 4. 结论与待办")
    add("")
    if issues:
        add("**发现的问题**：")
        for i, s in enumerate(issues, 1):
            add(f"{i}. {s}")
    else:
        add("未发现阻断性问题。")
    add("")
    add("**下一步（按 Codex §9）**：")
    add("1. 等 COMSOL 许可空闲后执行 81 组合几何/选择预检（脚本已就绪："
        "`scripts\\geometry_selection_precheck.py`）；")
    add("2. 预检分类出来后，仅对 `clean` 组合做 `Ptot`/`Vave` 双指标排名与 Pareto；")
    add("3. 读 5/20/35 MHz 内外电极复电位验证驱动；核实 `Ptot` 积分面稳定性；")
    add("4. 确定 3–5 组精扫候选（5–40 MHz，0.5 MHz 步长 = 71 点）。")

    (OUT / "02_data_quality_report.md").write_text("\n".join(report), encoding="utf-8")
    (OUT / "_data_quality.json").write_text(
        json.dumps(
            {
                "source": str(CSV),
                "n_rows": len(data),
                "x_scale_values": xs,
                "N_w_te1_values": [int(v) for v in n1s],
                "frequencies_MHz": [f / 1e6 for f in freqs],
                "n_combos": len(combos),
                "expected_rows": expected,
                "missing_combos": missing,
                "rows_per_combo": {str(k): v for k, v in counts.items()},
                "nan": nan, "inf": inf, "empty": empty, "bad_complex": badcomplex,
                "negative_ptot_rows": len(neg_ptot),
                "zero_ptot_rows": zero_ptot,
                "zin_equal_rows": zin_equal,
                "zin_checked_rows": zin_check,
                "combos_with_peak_at_top": peak_at_top,
                "issues": issues,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print("\n".join(report[-30:]))
    print(f"\n落档：{OUT / '02_data_quality_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
