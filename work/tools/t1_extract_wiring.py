"""T1 结构化取证：把电气接线、积分算子、电极几何与列表一致性抽成 JSON，并核算重叠表。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
sys.path.insert(0, str(REPO / "src"))
from memsharness import modelio as mio  # noqa: E402

M = Path(r"C:\Users\zmx\Desktop\换能器\b_GE_task3_2newyizu.m")
OUT = REPO / "work" / "reports" / "modelio"

spec = mio.parse_matlab_export(M)
(OUT / "mspec-b_GE_task3_2newyizu.json").write_text(
    json.dumps(spec, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
print(f"已落 mspec：{OUT / 'mspec-b_GE_task3_2newyizu.json'}（参数 {len(spec['parameters'])} 条记录）")

text = M.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()

PATTERNS = {
    "electrodes": r"physics\('(es|cir)'\)\.(feature|selection)\.?(create|duplicate)?\('?(\w+)?'?",
    "electrode_assign": r"physics\('(es|cir)'\)\.feature\('(\w+)'\)\.(set|selection|active)\(",
    "intop": r"cpl(?:\.duplicate)?\('?(intop\d)'?|cpl\.create\('(intop\d)'",
    "variables": r"variable\('var1'\)\.(set|rename|descr)\(",
    "batch": r"batch\('p1'\)\.(set|create|study|attach)\(",
    "study_param": r"study\('std1'\)\.feature\('(param|param2|freq)'\)\.(set|active)\(",
    "solver_param": r"sol\('sol1'\)\.feature\('s1'\)\.feature\('p1'\)\.set\(",
}

facts: dict = {"source": str(M), "sha256": mio.__dict__.get("_", None), "sections": {}}
for name, pattern in PATTERNS.items():
    hits = [
        {"line": i, "text": ln.strip()}
        for i, ln in enumerate(lines, 1)
        if re.search(pattern, ln)
    ]
    facts["sections"][name] = hits
    print(f"  {name}: {len(hits)} 行")

# ---- 电极几何核算（用 .m 里实际的参数值，不猜） ----
params = {p["name"]: p["expression"] for p in spec["parameters"]}
print("\n== 相关参数（来自 .m）==")
for key in ("v0", "W_min", "N_mem", "R_mem", "N_w_te1", "N_p_te1", "N_w_te2", "N_p_te2", "x_scale", "x_scale_2"):
    print(f"  {key:10s} = {params.get(key)}")

W_min = 4.2e-6
N_mem = 10
R_mem = N_mem * W_min
N_w_te1, N_w_te2 = 4, 9
inner_r = N_w_te1 * W_min + 1e-6          # cyl9: r = (N_w_te1*W_min)+1[um]，**不含 x_scale**
table = []
print("\n== 电极几何重叠核算（内电极圆 vs 外环内径 vs 膜半短轴）==")
print(f"{'x_scale':>8}{'膜半短轴b':>12}{'内电极r':>10}{'外环内径':>10}{'间隙':>10}  判定")
for i in range(1, 11):
    xs = round(i * 0.1, 2)
    b = R_mem * xs
    outer_rin = N_w_te2 * W_min * xs - 1e-6
    gap = outer_rin - inner_r
    verdict = "重叠" if gap < 0 else ("临界" if gap < 0.5e-6 else "分离")
    if inner_r > b:
        verdict += "+内电极超出膜短轴"
    row = {
        "x_scale": xs,
        "membrane_semi_minor_um": round(b * 1e6, 2),
        "inner_electrode_r_um": round(inner_r * 1e6, 2),
        "outer_ring_inner_r_um": round(outer_rin * 1e6, 2),
        "gap_um": round(gap * 1e6, 2),
        "verdict": verdict,
    }
    table.append(row)
    print(f"{xs:>8.2f}{row['membrane_semi_minor_um']:>12.2f}{row['inner_electrode_r_um']:>10.2f}"
          f"{row['outer_ring_inner_r_um']:>10.2f}{row['gap_um']:>10.2f}  {verdict}")

facts["electrode_geometry_um"] = table
facts["overlap_combos"] = [r["x_scale"] for r in table if "重叠" in r["verdict"]]
facts["overlap_combo_count"] = len(facts["overlap_combos"]) * 7  # × 7 个 N_w_te1 取值
(OUT / "T1-wiring-facts.json").write_text(
    json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"\n已落结构化取证：{OUT / 'T1-wiring-facts.json'}")
print(f"重叠的 x_scale 档位：{facts['overlap_combos']}（共 {facts['overlap_combo_count']} 个组合）")
