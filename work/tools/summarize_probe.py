"""把 probe 落档 JSON 提炼成可读摘要（不新增任何数值，只搬运已实测字段）。

用法：
    python work\\tools\\summarize_probe.py work\\reports\\modelio\\probe-<run_id>.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    data = json.loads(path.read_text(encoding="utf-8"))
    src = data.get("source", {})

    print(f"# probe 摘要：{path.name}")
    print(f"run_id       : {data.get('run_id')}")
    print(f"ok           : {data.get('ok')}")
    print(f"COMSOL 版本  : {data.get('comsol_version')}")
    print(f"源文件       : {src.get('path')}")
    print(f"源 SHA256    : {src.get('sha256')}")
    print(f"原件未被改动 : {src.get('original_untouched')}  lock={src.get('lock_present')}")
    print(f"暂存副本     : {src.get('staged_path')}")

    params = data.get("parameters") or []
    print(f"\n== 参数（{len(params)} 个）==")
    for p in params:
        val = p.get("value")
        err = p.get("value_error")
        note = f"  [value_error={err}]" if err else ""
        print(f"  {p.get('name'):22s} = {p.get('expression')!r:>18s}  value={val!r}{note}")

    geo = data.get("geometry") or []
    print(f"\n== 几何（{len(geo)}）==")
    for g in geo:
        print(f"  {g}")

    boxes = data.get("bounding_box") or []
    print(f"\n== 网格顶点包围盒（{len(boxes)}）==")
    for b in boxes:
        print(
            f"  comp={b.get('component')} mesh={b.get('mesh')} n_vertices={b.get('n_vertices')}"
            f"  x={b.get('x')}  y={b.get('y')}  z={b.get('z')}"
        )

    phys = data.get("physics") or []
    print(f"\n== 物理场/选择集节点（{len(phys)}）==")
    for node in phys:
        if node.get("kind") == "named_selection":
            print(f"  [选择集] {node.get('tag')} label={node.get('label')} dim={node.get('dimension')}")
            continue
        feats = node.get("features") or []
        print(
            f"  [{node.get('tag')}] {node.get('type')} selection={node.get('selection')}"
            f"  特征 {len(feats)} 个"
        )
        for f in feats:
            print(f"      - {f.get('tag')} :: {f.get('type')} ({f.get('label')})")

    studies = data.get("studies") or []
    print(f"\n== 研究（{len(studies)}）==")
    for s in studies:
        print(f"  [{s.get('tag')}] {s.get('label')}")
        for step in s.get("steps") or []:
            print(f"      step {step.get('tag')} type={step.get('type')}")
            props = step.get("properties")
            if isinstance(props, dict):
                for k, v in props.items():
                    print(f"          {k} = {v}")
            elif isinstance(props, str):
                shown = props if len(props) <= 300 else props[:300] + f"...(共 {len(props)} 字符)"
                print(f"          properties: {shown}")
            elif props:
                for item in props:
                    print(f"          {item}")

    print(f"\n== 求解器（{len(data.get('solvers') or [])}）==")
    for s in data.get("solvers") or []:
        print(f"  {s}")

    print(f"\n== 网格统计 ==")
    for m in data.get("mesh") or []:
        print(f"  {m}")

    print(f"\n== schema 来源 ==")
    print(f"  {json.dumps(data.get('schema_source'), ensure_ascii=False)}")

    rb = data.get("readback") or []
    bad = [r for r in rb if r.get("level") == "unreadable"]
    print(f"\n== 回读校验：{len(rb)} 项，其中不可读 {len(bad)} 项 ==")
    for r in bad:
        print(f"  [unreadable] {r.get('item')} :: {r.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
