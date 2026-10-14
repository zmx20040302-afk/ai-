"""决定性判据：用 **Java mesh API** 直接读网格规模，而不是 evaluate('x')（可能读陈旧数据集）。"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

_REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
sys.path.insert(0, str(_REPO / "src"))

from memsharness import onboard as ob  # noqa: E402

STAGED = _REPO / "work" / "devices" / "ge-task3-audit" / "b_GE_task3_2-new.mph"


def safe(obj, method: str):
    try:
        return int(getattr(obj, method)())
    except Exception as exc:
        return f"<{type(exc).__name__}: {exc}>"


def report(model, mesh, geom, label: str) -> dict:
    xs = ob.eval_vector(model, "x")
    data = {
        "label": label,
        "mesh_num_elem": safe(mesh, "getNumElem"),
        "mesh_num_vertex": safe(mesh, "getNumVertex"),
        "eval_x_len": None if not xs else len(xs),
        "geom_entities": {k: safe(geom, k) for k in
                          ("getNVertices", "getNEdges", "getNBoundaries", "getNDomains")},
    }
    print(f"  {label}: mesh.getNumElem={data['mesh_num_elem']} "
          f"mesh.getNumVertex={data['mesh_num_vertex']} len(evaluate('x'))={data['eval_x_len']} "
          f"geom={data['geom_entities']}")
    return data


def main() -> int:
    import mph

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

    print("\n== 0) 首次网格构建（副本里没有网格）==")
    geom.run()
    mesh.run()
    base = report(model, mesh, geom, "基线（未扰动）")

    print("\n== 1) N_mem 10 → 20（半径翻倍，几何必然变）==")
    java.param().set("N_mem", "20")
    geom.run()
    mesh.run()
    a = report(model, mesh, geom, "N_mem=20")

    print("\n== 2) 在 N_mem=20 基础上重建全部几何特征（逐特征 run，最后 fin）==")
    try:
        for tag in ("wp1", "rev1", "sca1", "sph1", "wp2", "par1", "del1", "fin"):
            try:
                geom.run(tag)
                print(f"    run({tag}) OK")
            except Exception as exc:
                print(f"    run({tag}) 失败: {type(exc).__name__}: {exc}")
        mesh.run()
        b = report(model, mesh, geom, "逐特征 run 后")
    except Exception as exc:
        print(f"    失败：{type(exc).__name__}: {exc}")

    print("\n== 3) 恢复 N_mem=10 并重建 ==")
    java.param().set("N_mem", "10")
    geom.run()
    mesh.run()
    c = report(model, mesh, geom, "恢复后")

    print("\n== 结论素材 ==")
    print(f"  N_mem=20 时 mesh.getNumElem 与基线相同？ {a['mesh_num_elem'] == base['mesh_num_elem']}")
    print(f"  逐特征 run 后与基线相同？        {b['mesh_num_elem'] == base['mesh_num_elem'] if 'b' in dir() else 'n/a'}")
    print(f"  evaluate('x') 长度是否恒定？     {len({base['eval_x_len'], a['eval_x_len'], c['eval_x_len']}) == 1}")
    print(f"  几何实体是否恒定？               {base['geom_entities'] == a['geom_entities'] == c['geom_entities']}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
