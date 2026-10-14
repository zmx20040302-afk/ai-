"""查「几何不重建」的根因：参数回读 + 几何序列构成 + 各种重建路径对比。

已知：把 W_min/x_scale/h_parylene/N_mem 翻倍后，几何实体数、网格节点数、包围盒全不变，
而几何特征确实引用了这些参数。本脚本按顺序排除：
    ① param().set() 是否真的写进去（**回读**）
    ② 几何序列到底由哪些特征构成（create 调用与当前 tag/type）
    ③ geom.run() / 工作平面自身 run() / 删网格重建 三条路径各能否触发变化
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

from memsharness import onboard as ob  # noqa: E402

STAGED = _REPO / "work" / "devices" / "ge-task3-audit" / "b_GE_task3_2-new.mph"
M = "C:\\Users\\zmx\\Desktop\\b_GE_task3_2-new.mph"  # 仅用于从 .m 对照（不加载）
M_FILE = Path(r"C:\Users\zmx\Desktop\b_GE_task3_2new.m")


def n_nodes(model) -> int | None:
    xs = ob.eval_vector(model, "x")
    return len(xs) if xs else None


def entities(geom) -> dict:
    out = {}
    for key in ("getNVertices", "getNEdges", "getNBoundaries", "getNDomains"):
        try:
            out[key] = int(getattr(geom, key)())
        except Exception as exc:
            out[key] = f"<{type(exc).__name__}>"
    return out


def main() -> int:
    import mph

    if not STAGED.is_file():
        print(f"[错误] 缺副本：{STAGED}")
        return 2

    def port_open(port: int = 2036) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                return True
        except OSError:
            return False

    client = mph.Client(port=2036) if port_open() else mph.start(cores=1, port=2036)
    model = client.load(str(STAGED))
    java = model.java
    comp = java.modelNode("comp1")
    geom = comp.geom("geom1")
    mesh = comp.mesh("mesh1")
    print(f"载入：{model.name()}（COMSOL {client.version}）")

    print("\n=== ① 参数回读测试 ===")
    for name, new in (("N_mem", "20"), ("W_min", "8.4[um]")):
        before = str(java.param().get(name))
        java.param().set(name, new)
        after = str(java.param().get(name))
        print(f"  {name}: 设前={before} 设后={after}  写入成功={after.replace(' ', '') == new.replace(' ', '')}")
        java.param().set(name, before)

    print("\n=== ② 几何序列构成（Java 侧实测）===")
    tags = [str(t) for t in geom.feature().tags()]
    print(f"  geom1 特征 {len(tags)} 个：")
    for tag in tags:
        f = geom.feature(tag)
        try:
            ftype = str(f.type())
        except Exception as exc:
            ftype = f"<{type(exc).__name__}>"
        print(f"    {tag:10s} {ftype}")
    print(f"  几何实体：{entities(geom)}")

    print("\n=== ③ 对照 .m 里的几何 create 调用 ===")
    if M_FILE.is_file():
        text = M_FILE.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if "geom('geom1')" in line and ("create(" in line or "run(" in line):
                print(f"    L{i}: {line.strip()[:120]}")

    print("\n=== ④ 三条重建路径对比（把 N_mem 10 → 20）===")
    original = str(java.param().get("N_mem"))
    base_nodes = n_nodes(model)
    print(f"  基线：n_nodes={base_nodes} 实体={entities(geom)}")
    java.param().set("N_mem", "20")
    print(f"  设 N_mem=20，回读={java.param().get('N_mem')}")

    print("  路径 A：geom.run() + mesh.run()")
    geom.run()
    mesh.run()
    print(f"    n_nodes={n_nodes(model)} 实体={entities(geom)}")

    print("  路径 B：先跑工作平面子序列，再 geom.run() + mesh.run()")
    try:
        sub = geom.feature("wp1").geom()
        sub.run()
        geom.run()
        mesh.run()
        print(f"    n_nodes={n_nodes(model)} 实体={entities(geom)}")
    except Exception as exc:
        print(f"    失败：{type(exc).__name__}: {exc}")

    print("  路径 C：删掉网格再重建 + geom.run()")
    try:
        mesh.remove()
        geom.run()
        mesh.run()
        print(f"    n_nodes={n_nodes(model)} 实体={entities(geom)}")
    except Exception as exc:
        print(f"    失败：{type(exc).__name__}: {exc}")

    print("  路径 D：直接读最终几何特征（rev/scale/ext）的参数，看是否随参数变")
    for tag in tags:
        f = geom.feature(tag)
        if str(f.type()) in ("Revolve", "Scale", "Extrude", "Difference", "Union", "Array"):
            try:
                print(f"    {tag}({f.type()}) 属性键={list(f.properties())[:12]}")
            except Exception as exc:
                print(f"    {tag}: 读属性失败 {type(exc).__name__}")

    java.param().set("N_mem", original)
    geom.run()
    mesh.run()
    print(f"\n  已恢复 N_mem={original}，n_nodes={n_nodes(model)}（与基线相同={n_nodes(model) == base_nodes}）")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
