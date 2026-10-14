"""内省 MPh / COMSOL Java API：找出「跑几何序列」与「在固定网格上取值」的正确调用方式。

背景：`comp.geom()` 返回的是列表对象，JPype 把带参重载 `geom(String)` 解析错了，
导致 `comp.geom(tag)` 报 "object is not callable"。本脚本把候选调用方式逐个试一遍，
把成功/失败如实打印出来，避免继续猜 API。

用法（在仓库根下执行）：
    work\\.venv\\Scripts\\python.exe -u ^
      scripts\\mph_introspect.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
COMSOL_HOME = os.environ.get("MEMS_COMSOL_HOME", r"D:\COMSOL64\Multiphysics")
os.environ["PATH"] = f"{Path(COMSOL_HOME) / 'bin' / 'win64'}{os.pathsep}{os.environ.get('PATH', '')}"
os.environ.setdefault("COMSOL_HOME", COMSOL_HOME)


def show(label: str, fn) -> None:
    """执行一次探测并打印结果；失败也打印，不掩盖。"""
    try:
        value = fn()
        text = repr(value)
        print(f"[OK ] {label}: {text[:300]}", flush=True)
    except Exception as exc:
        print(f"[ERR] {label}: {type(exc).__name__}: {str(exc)[:200]}", flush=True)


def main() -> int:
    import mph

    print("=== MPh Model 公开方法 ===", flush=True)
    print([m for m in dir(mph.Model) if not m.startswith("_")], flush=True)

    candidates = sorted((_REPO_ROOT / "work" / "runs").glob("*/input.mph"))
    model_path = candidates[-1] if candidates else None
    assert model_path, "找不到模型副本"
    print(f"=== 模型：{model_path.name} ===", flush=True)

    client = mph.Client(port=int(os.environ.get("MEMS_MPH_PORT", "2036")))
    model = client.load(model_path)
    java = model.java

    print("=== MPh 层面的清单 ===", flush=True)
    for name in ("geometries", "meshes", "studies", "datasets", "physics", "parameters"):
        show(f"model.{name}()", lambda n=name: getattr(model, n)())

    print("=== Java 层面：组件与几何 ===", flush=True)
    comp_tags = [str(t) for t in java.modelNode().tags()]
    print(f"组件标签: {comp_tags}", flush=True)
    comp = java.modelNode(comp_tags[0])

    show("comp.geom()  (列表)", lambda: [str(t) for t in comp.geom().tags()])
    show("comp.geom('geom1')  (带参重载)", lambda: comp.geom("geom1"))
    show("comp.geom().get('geom1')", lambda: comp.geom().get("geom1"))
    show("java.geom('geom1')  (模型级快捷)", lambda: java.geom("geom1"))
    show("java.modelNode('comp1').geom('geom1').getSDim()",
         lambda: java.modelNode(comp_tags[0]).geom().get("geom1").getSDim())

    print("=== Java 层面：网格 ===", flush=True)
    show("comp.mesh()  (列表)", lambda: [str(t) for t in comp.mesh().tags()])
    show("comp.mesh('mesh1')", lambda: comp.mesh("mesh1"))
    show("comp.mesh().get('mesh1')", lambda: comp.mesh().get("mesh1"))

    print("=== Java 层面：结果数据集与数值节点 ===", flush=True)
    show("java.result().dataset() 列表", lambda: [str(t) for t in java.result().dataset().tags()])
    show("java.result().dataset().create('probe_grid','Grid3D')",
         lambda: java.result().dataset().create("probe_grid", "Grid3D"))
    show("probe_grid.properties()",
         lambda: sorted(str(p) for p in java.result().dataset("probe_grid").properties()))
    show("probe_grid 尝试 set('xmin','0')",
         lambda: java.result().dataset("probe_grid").set("xmin", "0"))
    show("probe_grid 尝试 setxmin 类方法", lambda: java.result().dataset("probe_grid").setxmin(0))
    show("java.result().numerical() 列表", lambda: [str(t) for t in java.result().numerical().tags()])
    show("create('probe_eval','Eval')",
         lambda: java.result().numerical().create("probe_eval", "Eval"))
    show("probe_eval.properties()",
         lambda: sorted(str(p) for p in java.result().numerical("probe_eval").properties()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
