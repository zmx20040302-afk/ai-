"""一次性探明 COMSOL 几何面积与 Mesh 数据集的**可用调用式**（单次 COMSOL 会话）。

背景（哨兵实测 2026-09-13）：v3 的两种面积通路都失败。
- 官方 API：`GeomObjectSelection.set(java.lang.String oname, int[] entities)` —— **必须带几何对象名**；
  可用重载里**没有** `set(int[])`，所以纯 Python 列表匹配不到重载 → "No matching overloads"。
- `comp.measure()` 返回的是**网格**测量（报错里是 `MeshSelectionClient`）；几何测量应走 `geom.measure()`。
- Mesh 数据集：`ds.create(tag,"Mesh")` 被静默吞掉异常，之后 `evaluate(dataset=tag)` 报 "does not exist"。

用法：python work\\tools\\probe_area_api.py --model "<m>.mph" [--x 0.6] [--n 4]
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from memsharness import onboard as ob  # noqa: E402


def try_(label, fn):
    try:
        val = fn()
        print(f"  [OK  ] {label} → {val!r}")
        return val
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        print(f"  [FAIL] {label}: {msg[:500]}")
        return None


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--x", type=float, default=0.6)
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--port", type=int, default=2036)
    args = ap.parse_args()

    import jpype
    import mph

    def port_open(p):
        try:
            with socket.create_connection(("127.0.0.1", p), timeout=1.5):
                return True
        except OSError:
            return False

    staging = ob.stage_model(Path(args.model), "ge-task3-area-probe")
    started = not port_open(args.port)
    client = mph.Client(port=args.port) if not started else mph.start(cores=1, port=args.port)
    model = client.load(staging["staged"])
    java = model.java
    comp = java.modelNode("comp1")
    geom = comp.geom("geom1")
    mesh = comp.mesh("mesh1")
    print(f"COMSOL {client.version}｜server_started={started}")
    java.param().set("x_scale", f"{args.x:g}")
    java.param().set("N_w_te1", f"{args.n:d}")
    geom.run()
    print(f"参数 x_scale={args.x:g} N_w_te1={args.n:d}；几何已构建")

    ents_outer = sorted(int(v) for v in comp.physics("es").feature("term1").selection().entities())
    ents_inner = sorted(int(v) for v in comp.physics("es").feature("pot2").selection().entities())
    ents_ptot = sorted(int(v) for v in comp.cpl("intop5").selection().entities())
    print(f"term1 实体={ents_outer}｜pot2 实体={ents_inner}｜intop5 实体={ents_ptot}")

    # ---------- A. 几何测量：穷举访问器 × 对象名 × 参数类型 ----------
    print("\n=== A. 几何面积 getArea() 变体 ===")
    JIntArr = jpype.JArray(jpype.JInt)
    measures = {
        "geom.measure()": lambda: geom.measure(),
        "geom.getMeasureGen()": lambda: geom.getMeasureGen(),
        "geom.measureFinal()": lambda: geom.measureFinal(),
    }
    obj_candidates = []
    for getter in (lambda: geom.getObjNames(), lambda: geom.getValidObjNames()):
        v = try_("geom 对象名枚举", getter)
        if v:
            obj_candidates = [str(x) for x in v]
            break
    if not obj_candidates:
        obj_candidates = ["fin", "sca1", "rev1"]
    print(f"  候选几何对象名：{obj_candidates}")

    winner = None
    for mname, getter in measures.items():
        m = None
        print(f"\n -- {mname} --")
        m = try_(f"{mname}", getter)
        if m is None:
            continue
        sel = try_(f"{mname}.selection()", lambda: m.selection())
        if sel is None:
            continue
        try_("sel.init(2)", lambda: sel.init(2))
        try_("sel.objects()", lambda: [str(x) for x in sel.objects()])
        try_("sel.dim()", lambda: sel.dim())
        for oname in obj_candidates:
            for argname, mk in (("JArray(JInt)", lambda ids: JIntArr(ids)),
                                ("python-list", lambda ids: list(ids)),
                                ("tuple", lambda ids: tuple(ids))):
                ok = try_(f"sel.set({oname!r}, {argname})", lambda: sel.set(oname, mk(ents_outer)))
                if ok is None:
                    continue
                got = try_(f"sel.entities({oname!r}, 2)", lambda: sorted(int(v) for v in sel.entities(oname, 2)))
                area = try_("m.getArea()", lambda: float(m.getArea()))
                if area is not None and area > 0:
                    print(f"  ==> 可用组合：{mname} + init(2) + set({oname!r}, {argname}) ⇒ area={area!r}"
                          f"（回读实体 {got}）")
                    winner = (mname, oname, argname, area)
                    break
            if winner:
                break
        if winner:
            break
    print(f"\n几何面积可用组合：{winner}")

    # ---------- B. Mesh 数据集 ----------
    print("\n=== B. Mesh 数据集与 intopN(1) ===")
    try:
        mesh.run()
        print("  网格已构建")
    except Exception as exc:
        print(f"  [FAIL] mesh.run(): {type(exc).__name__}: {str(exc)[:300]}")
    ds = java.result().dataset()
    try_("dataset.tags()（建前）", lambda: [str(x) for x in ds.tags()])
    print("  create:")
    try:
        ds.create("dset_mesh_probe", "Mesh")
        print("  [OK  ] create('dset_mesh_probe','Mesh')")
    except Exception as exc:
        print(f"  [FAIL] create: {type(exc).__name__}: {str(exc)[:300]}")
    try_("dataset.tags()（建后）", lambda: [str(x) for x in ds.tags()])
    for expr in ("intop4(1)", "intop3(1)", "intop5(1)"):
        for dsname in ("dset_mesh_probe", None):
            label = f"evaluate({expr!r}, dataset={dsname})"
            try:
                vals = model.evaluate(expr, dataset=dsname) if dsname else model.evaluate(expr)
                print(f"  [OK  ] {label} → {list(vals)[:2]}")
            except Exception as exc:
                print(f"  [FAIL] {label}: {type(exc).__name__}: {str(exc)[:200]}")

    try:
        client.clear()
        client.disconnect()
    except Exception:
        pass
    time.sleep(1)
    print(f"\n端口 {args.port} 仍开放={port_open(args.port)}")
    return 0


if __name__ == "__main__":
    import os as _os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(code)
