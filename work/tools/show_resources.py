"""打印一次预检 run 的资源监控字段（Codex §5.1/§5.2 要求）。

用法：python work\\tools\\show_resources.py <run_dir>
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
    d = json.loads((Path(sys.argv[1]) / "geometry_selection_precheck.json").read_text(encoding="utf-8"))
    print(f"run_id={d.get('run_id')}｜phase={d.get('phase')}｜wall={d.get('wall_seconds')} s")
    print(f"server memory：{json.dumps(d.get('server_memory'), ensure_ascii=False)}")
    print(f"cleanup：{json.dumps(d.get('cleanup'), ensure_ascii=False)}")
    print(f"\n{'x':>5} {'N1':>3} {'geom_s':>7} {'mesh_s':>7} {'elems':>9} {'mesh':>5} "
          f"{'A_ptot_geom':>14} {'intop5==swr1':>12} {'bbox(x)':>10}")
    for r in d.get("rows", []):
        bb = r.get("ptot_boundary_bounding_box")
        print(f"{r['x_scale']:>5g} {r['N_w_te1']:>3d} {r.get('geometry_seconds'):>7} "
              f"{r.get('mesh_seconds'):>7} {str(r.get('mesh_element_count')):>9} "
              f"{str(r.get('mesh_status')):>5} {r.get('area_ptot_geometry'):>14.6e} "
              f"{str(r.get('intop5_eq_swr1')):>12} "
              f"{(f'{bb[0]:.3e}..{bb[1]:.3e}' if bb else 'None'):>24}")
    elems = [r.get("mesh_element_count") for r in d.get("rows", [])
             if isinstance(r.get("mesh_element_count"), int)]
    if elems:
        print(f"\n单元数：n={len(elems)} min={min(elems)} max={max(elems)} "
              f"递增={elems == sorted(elems)}")
    gs = [r.get("geometry_seconds") for r in d.get("rows", [])
          if isinstance(r.get("geometry_seconds"), (int, float))]
    ms = [r.get("mesh_seconds") for r in d.get("rows", [])
          if isinstance(r.get("mesh_seconds"), (int, float))]
    if gs:
        print(f"几何耗时：min={min(gs)} max={max(gs)} 合计={sum(gs):.1f} s")
    if ms:
        print(f"网格耗时：min={min(ms)} max={max(ms)} 合计={sum(ms):.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
