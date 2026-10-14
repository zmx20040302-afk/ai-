"""紧凑打印某个预检 run 的关键数字（供人读/写报告用，避免 dump 整个 JSON）。

用法：python work\\tools\\show_sentinel.py <run_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    run = Path(sys.argv[1])
    kind = "sentinel_report.json" if (run / "sentinel_report.json").is_file() else \
        "geometry_selection_precheck.json"
    d = json.loads((run / kind).read_text(encoding="utf-8"))
    print(f"文件：{kind}")
    print(f"run_id       : {d.get('run_id')}")
    print(f"source_model : {d.get('source_model')}")
    print(f"source_sha256: {d.get('source_sha256')}")
    print(f"staged_sha256: {d.get('staged_sha256')}")
    print(f"comsol/mph   : {d.get('comsol_version')} / {d.get('mph_version')}")
    ep = d.get("effective_params_raw", {})
    print("effective    : " + ", ".join(
        f"{k}={ep[k]}" for k in ("W_min_expression", "N_w_te2_expression", "R_mem_raw_value") if k in ep))

    checks = d.get("checks", [])
    if checks:
        ok = sum(1 for c in checks if c["pass"])
        tot = sum(1 for c in checks if c["pass"] is not None)
        print(f"\n哨兵验收：{ok}/{tot}")
        for c in checks:
            mark = "PASS" if c["pass"] else ("N/A " if c["pass"] is None else "FAIL")
            print(f"  [{mark}] {c['check']}  {c['detail']}")
    if "counts" in d:
        print(f"\n统计：{json.dumps(d['counts'], ensure_ascii=False)}")
    if d.get("cleanup"):
        print(f"cleanup：{d['cleanup']}")

    print("\n逐组合：")
    for r in d.get("rows", []):
        print(f'  ({r["x_scale"]:g},{r["N_w_te1"]})  design={r.get("design_status")}'
              f' sel={r.get("selection_status")} area={r.get("area_status")}'
              f' mesh={r.get("mesh_status")} elig={r.get("eligibility_level")}')
        if r.get("outer_bc_entities") is not None:
            print(f'      outer={r.get("outer_bc_entities")} inner={r.get("inner_bc_entities")}'
                  f' intop5={r.get("intop5_entities")} ∩={r.get("bc_intersection_count")}')
        for k in ("outer", "inner", "ptot"):
            g, m = r.get(f"area_{k}_geometry"), r.get(f"area_{k}_mesh_integral")
            src = r.get(f"area_{k}_source")
            err = r.get(f"area_{k}_mesh_error") or r.get(f"area_{k}_geometry_error")
            print(f'      A_{k}: geom={g}  mesh={m}  src={src}'
                  + (f'  err={str(err)[:90]}' if (err and not m) else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
