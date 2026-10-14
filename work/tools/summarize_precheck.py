"""汇总一次预检 run 的结果（供写报告用）。

用法：python work\\tools\\summarize_precheck.py <run_dir>
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    run = Path(sys.argv[1])
    p = run / "geometry_selection_precheck.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = d.get("rows", [])
    print(f"run_id={d.get('run_id')}｜kind={d.get('kind')}｜phase={d.get('phase')}")
    print(f"model={d.get('source_model')}")
    print(f"sha256={d.get('source_sha256')}")
    print(f"comsol={d.get('comsol_version')} mph={d.get('mph_version')}｜wall={d.get('wall_seconds')} s")
    g = d.get("grid", {})
    print(f"grid: x={len(g.get('x_scale', []))} 档 × N1={len(g.get('N_w_te1', []))} 档｜"
          f"满格 {g.get('n_combos')}｜本次执行 {g.get('executed')}")
    print(f"有效参数(raw)：{ {k: v for k, v in d.get('effective_params_raw', {}).items() if k.endswith('raw_value')} }")

    print(f"\n== 统计 ==\n{json.dumps(d.get('counts'), ensure_ascii=False)}")
    print(f"cleanup={d.get('cleanup')}")

    ax = ["design_status", "geometry_status", "selection_status", "area_status",
          "mesh_status", "mesh_crosscheck_status"]
    for a in ax:
        print(f"  {a}: {dict(Counter(r.get(a) for r in rows))}")

    print(f"\narea_continuity_status={d.get('area_continuity_status')}")
    for k, v in (d.get("area_continuity") or {}).items():
        print(f"  {k}: pairs={v['pairs_checked']} anomalies={v['anomalies_found']} status={v['status']}")
    print(f"ptot_control_surface_status={d.get('ptot_control_surface_status')}")
    print(f"ptot_cross_x_comparable={d.get('ptot_cross_x_comparable')}")
    sp = d.get("area_ptot_spread")
    if sp:
        print(f"  area_ptot_spread: n={sp['n']} min={sp['min']:.6e} max={sp['max']:.6e} "
              f"rel_spread={sp['rel_spread']:.3e} 与理论半球差={sp['rel_diff_of_mean_vs_theory']:.3e}")

    # 按 N1 分组统计资格
    by = defaultdict(Counter)
    for r in rows:
        by[int(r["N_w_te1"])][r.get("eligibility_level")] += 1
    print("\n== 按 N1 的资格分布 ==")
    for n1 in sorted(by):
        print(f"  N1={n1:<2d} design={Counter(r.get('design_status') for r in rows if int(r['N_w_te1'])==n1).most_common(1)[0][0]:26s} {dict(by[n1])}")

    bad = [r for r in rows if r.get("area_status") != "valid_geometry"]
    print(f"\n== 面积非 valid_geometry 的组合：{len(bad)} ==")
    for r in bad[:10]:
        print(f"  ({r['x_scale']:g},{r['N_w_te1']}) {r.get('area_status')} err={str(r.get('area_outer_geometry_error'))[:120]}")

    intop5 = Counter(tuple(sorted(int(v) for v in r["intop5_entities"])) if r.get("intop5_entities") else None
                     for r in rows)
    print(f"\n== intop5 实体集合分布 ==\n  {dict(intop5)}")

    warn = [r for r in rows if r.get("quality_warnings")]
    print(f"\n== 有质量警告的组合：{len(warn)} ==")
    for r in warn[:10]:
        print(f"  ({r['x_scale']:g},{r['N_w_te1']}) {r.get('quality_warnings')}")

    elig = [r for r in rows if r.get("eligible_for_ranking")]
    print(f"\n== 可排名组合：{len(elig)}（其中 full={sum(1 for r in elig if r['eligibility_level']=='full')}"
          f"｜provisional={sum(1 for r in elig if r['eligibility_level']=='provisional')}）")
    print("  按 N1:", dict(Counter(int(r["N_w_te1"]) for r in elig)))

    # ---- 交叉核对：实体集合 / 选择状态 与 设计状态、资格 的对应关系 ----
    def ct(key_fn, label):
        tab = defaultdict(Counter)
        for r in rows:
            tab[key_fn(r)][r.get("design_status")] += 1
        print(f"\n== {label} × design_status ==")
        for k, c in sorted(tab.items(), key=lambda kv: str(kv[0])):
            print(f"  {k}: {dict(c)}")

    ct(lambda r: tuple(sorted(int(v) for v in r["intop5_entities"])) if r.get("intop5_entities") else None,
       "intop5 实体集合")
    ct(lambda r: r.get("selection_status"), "selection_status")

    print("\n== 可排名子集内的 intop5 实体集合 ==")
    print("  ", dict(Counter(tuple(sorted(int(v) for v in r["intop5_entities"]))
                            for r in elig if r.get("intop5_entities"))))
    print("== 可排名子集内的 selection_status ==")
    print("  ", dict(Counter(r.get("selection_status") for r in elig)))
    print("== 可排名子集内的 area_ptot 面积 ==")
    vals = [r.get("area_ptot_geometry") for r in elig if isinstance(r.get("area_ptot_geometry"), (int, float))]
    if vals:
        print(f"   n={len(vals)} min={min(vals):.10e} max={max(vals):.10e} 唯一值数={len(set(vals))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
