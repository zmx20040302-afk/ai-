"""决定性诊断：几何/网格重建是否真的响应参数变化？

背景：`audit_parameters --no-solve` 对 25 个数值参数全部给出「几何偏移 = 0.0」，
且 `n_nodes` 恒为 234108、每个参数耗时仅 ~1.6 s。两种可能：
    A. 这些参数确实不参与几何（真实结论，但需证）；
    B. `geom.run()/mesh.run()` 没有真正重建（工具/框架问题）。
判据：把**必然影响几何**的参数做 ±100% 的大幅扰动，看
    ① 几何实体计数、② 网格节点数、③ 节点坐标包围盒、④ 几何自报包围盒 是否变化。

用法：
    python work\\tools\\diag_geometry_sensitivity.py
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

_REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "scripts"))

from baseline_solve import finite_max  # noqa: E402
from memsharness import onboard as ob  # noqa: E402

STAGED = _REPO / "work" / "devices" / "ge-task3-audit" / "b_GE_task3_2-new.mph"
PROBES = ("W_min", "x_scale", "h_parylene", "N_mem")


def state(model, java) -> dict:
    xs = ob.eval_vector(model, "x")
    ys = ob.eval_vector(model, "y")
    zs = ob.eval_vector(model, "z")

    def bbox(values):
        return None if not values else [min(values), max(values)]

    def safe_int(obj, method: str):
        try:
            return int(getattr(obj, method)())
        except Exception:
            return None

    geom = java.modelNode("comp1").geom("geom1")
    geom_box = None
    for getter in ("getBoundingBox", "getBndBox"):
        try:
            box = getattr(geom, getter)()
            geom_box = [list(row) for row in box]
            break
        except Exception:
            continue
    return {
        "n_nodes": len(xs) if xs else None,
        "bbox": {"x": bbox(xs), "y": bbox(ys), "z": bbox(zs)},
        "geom_entities": {
            key: safe_int(geom, key)
            for key in ("getNVertices", "getNEdges", "getNBoundaries", "getNDomains")
        },
        "geom_box": geom_box,
    }


def main() -> int:
    import mph

    if not STAGED.is_file():
        print(f"[错误] 找不到副本：{STAGED}")
        return 2

    def port_open(port: int = 2036) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                return True
        except OSError:
            return False

    if port_open():
        client = mph.Client(port=2036)
    else:
        client = mph.start(cores=1, port=2036)
    model = client.load(str(STAGED))
    java = model.java
    print(f"载入：{model.name()}（COMSOL {client.version}）")

    geom = java.modelNode("comp1").geom("geom1")
    mesh = java.modelNode("comp1").mesh("mesh1")

    print("\n== 几何特征里引用了哪些参数（从特征表达式读，不猜）==")
    hits: dict[str, list[str]] = {}
    for tag in geom.feature().tags():
        feature = geom.feature(tag)
        for key in ("size", "pos", "size", "displacement", "r", "h", "scale", "sx", "sy", "sz"):
            try:
                value = str(feature.getStringArray(key))
            except Exception:
                try:
                    value = str(feature.getString(key))
                except Exception:
                    continue
            for name in ("W_min", "R_mem", "N_mem", "h_parylene", "H_mem", "x_scale", "x_scale_2", "R_fill"):
                if name in value:
                    hits.setdefault(name, []).append(f"{tag}.{key}={value[:60]}")
    for name, where in hits.items():
        print(f"  {name}: {where[:3]}")
    if not hits:
        print("  （顶层几何特征未直接引用这些参数——可能都在工作平面 wp1 的子序列里）")

    print("\n== 工作平面子序列里的引用 ==")
    for tag in geom.feature().tags():
        feature = geom.feature(tag)
        try:
            sub = feature.geom()
        except Exception:
            continue
        for stag in sub.feature().tags():
            sf = sub.feature(stag)
            for key in ("size", "pos", "r", "h"):
                try:
                    value = str(sf.getStringArray(key))
                except Exception:
                    try:
                        value = str(sf.getString(key))
                    except Exception:
                        continue
                for name in ("W_min", "R_mem", "N_mem", "h_parylene", "H_mem", "x_scale_2"):
                    if name in value:
                        print(f"  {tag}/{stag}.{key} 引用 {name}: {value[:70]}")

    print("\n== 归一化基线 ==")
    geom.run()
    mesh.run()
    base = state(model, java)
    print(f"  {json.dumps(base, ensure_ascii=False)[:300]}")

    originals = {p: str(java.param().get(p)) for p in PROBES}
    print(f"\n== 大幅扰动测试（原值 → 2×，再恢复）==\n  原值：{originals}")
    for name in PROBES:
        original = originals[name]
        # 取原值的数值部分（如 4.200000[um] → 4.2*2[um]）
        digits = "".join(c for c in original if c.isdigit() or c in ".-")
        unit = original[len(digits):] if digits else ""
        try:
            new_value = f"{float(digits) * 2:g}{unit}"
        except ValueError:
            print(f"  {name}: 无法解析原值 {original!r}，跳过")
            continue
        java.param().set(name, new_value)
        geom.run()
        mesh.run()
        now = state(model, java)
        same_nodes = now["n_nodes"] == base["n_nodes"]
        same_bbox = now["bbox"] == base["bbox"]
        print(
            f"  {name}: {original} → {new_value} | n_nodes {base['n_nodes']} → {now['n_nodes']}"
            f"（相同={same_nodes}）| 包围盒相同={same_bbox} | 实体={now['geom_entities']}"
            f" | geom_box={now['geom_box']}"
        )
        if not same_bbox:
            print(f"      新包围盒: {json.dumps(now['bbox'], ensure_ascii=False)}")
        java.param().set(name, original)
        geom.run()
        mesh.run()
        after = state(model, java)
        print(f"      恢复后 n_nodes={after['n_nodes']}（与基线相同={after['n_nodes'] == base['n_nodes']}）")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
