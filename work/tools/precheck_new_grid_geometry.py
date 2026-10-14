"""新扫描网格（x_scale=0.4:0.05:0.8 × N_w_te1=0:1:8）的**几何自洽性预判**（零机时、纯静态）。

依据：T1 从 b_GE_task3_2newyizu.m 取证到的选择集定义
    cyl9 (Vin 内电极, 圆):  rin = 0,                 r = (N_w_te1*W_min) + 1[um]
    cyl8 (Vout 外电极, 环): rin = (N_w_te2*W_min)*x_scale - 1[um],  r = R_mem + 1[um]
    膜为椭圆: 半长轴 a = R_mem = N_mem*W_min, 半短轴 b = R_mem*x_scale
两条几何约束：
    ① 内电极不得与外环重叠：  N_w_te1*W_min + 1um  >  N_w_te2*W_min*x_scale - 1um   → 重叠
    ② 内电极圆须落在膜内：    N_w_te1*W_min + 1um  >  R_mem*x_scale                   → 超出膜短轴
假设：W_min=4.2um, N_mem=10, N_w_te2=9（沿用当前模型值；新批次到场后需用其 .m 复核）。
N_w_te1=0 时内电极宽为 0、选择集可能为空/退化 → 单独标记。
"""

from __future__ import annotations

import json
from pathlib import Path

W_min = 4.2e-6
N_mem = 10
N_w_te2 = 9
R_mem = N_mem * W_min

xs = [round(0.4 + 0.05 * i, 2) for i in range(9)]      # 0.40 … 0.80
n1s = list(range(0, 9))                                 # 0 … 8

rows = []
for x in xs:
    for n in n1s:
        inner_r = n * W_min + 1e-6
        outer_rin = N_w_te2 * W_min * x - 1e-6
        membrane_b = R_mem * x
        overlap = inner_r > outer_rin
        exceeds = inner_r > membrane_b
        flags = []
        if n == 0:
            flags.append("N_w_te1=0（内电极宽为 0，几何可能退化/选择集为空）")
        if overlap:
            flags.append("内外电极重叠")
        if exceeds:
            flags.append("内电极圆超出膜短轴")
        rows.append(
            {
                "x_scale": x,
                "N_w_te1": n,
                "inner_r_um": round(inner_r * 1e6, 2),
                "outer_ring_inner_r_um": round(outer_rin * 1e6, 2),
                "membrane_semi_minor_um": round(membrane_b * 1e6, 2),
                "overlap": overlap,
                "exceeds_membrane": exceeds,
                "geometrically_clean": (not overlap) and (not exceeds) and n > 0,
                "flags": flags,
            }
        )

clean = [r for r in rows if r["geometrically_clean"]]
overlap_only = [r for r in rows if r["overlap"] and not r["exceeds_membrane"]]
print(f"网格：{len(xs)} × {len(n1s)} = {len(rows)} 个组合")
print(f"  几何自洽（无重叠、内电极在膜内、N>0）：{len(clean)} 个")
print(f"  仅内外电极重叠：{len(overlap_only)} 个")
print(f"  内电极超出膜短轴：{sum(1 for r in rows if r['exceeds_membrane'])} 个")
print(f"  其中 N_w_te1=0：{sum(1 for r in rows if r['N_w_te1'] == 0)} 个")
print()
print("== 逐 x_scale 的边界（沿用当前 N_w_te2=9、W_min=4.2um、N_mem=10）==")
print(f"{'x_scale':>8}{'膜半短轴':>10}{'外环内径':>10}{'重叠起点N':>10}{'超膜起点N':>10}{'自洽 N 范围':>16}")
for x in xs:
    outer_rin = N_w_te2 * W_min * x - 1e-6
    membrane_b = R_mem * x
    # 重叠：N*W_min+1 > outer_rin  →  N > (outer_rin-1um)/W_min
    n_overlap_from = int((outer_rin - 1e-6) // W_min) + 1
    n_exceed_from = int((membrane_b - 1e-6) // W_min) + 1
    ok = [r["N_w_te1"] for r in rows if r["x_scale"] == x and r["geometrically_clean"]]
    rng = f"{min(ok)}–{max(ok)}" if ok else "无"
    print(f"{x:>8.2f}{membrane_b*1e6:>10.2f}{outer_rin*1e6:>10.2f}"
          f"{n_overlap_from:>10d}{n_exceed_from:>10d}{rng:>16}")

out = Path(r"C:\Users\zmx\Desktop\memsharness\work\reports\modelio")
out.mkdir(parents=True, exist_ok=True)
(out / "new-grid-geometry-precheck.json").write_text(
    json.dumps(
        {
            "assumptions": {"W_min_um": 4.2, "N_mem": 10, "N_w_te2": 9,
                            "source": "b_GE_task3_2newyizu.m（T1 取证）；新批次需用其 .m 复核"},
            "grid": {"x_scale": xs, "N_w_te1": n1s, "n_combos": len(rows)},
            "counts": {
                "clean": len(clean),
                "overlap": sum(1 for r in rows if r["overlap"]),
                "exceeds_membrane": sum(1 for r in rows if r["exceeds_membrane"]),
                "n_w_te1_zero": sum(1 for r in rows if r["N_w_te1"] == 0),
            },
            "rows": rows,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(f"\n落档：{out / 'new-grid-geometry-precheck.json'}")
