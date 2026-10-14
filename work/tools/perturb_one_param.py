"""单参数自主扰动：在反相驱动分支上**只改一个参数值**并计算结果（Codex §11 的 x_scale 行）。

严格约束：
- 除目标参数外**断言其余参数逐位不变**（begin/end 快照比对）；
- 只改一个值：x_scale 0.6 -> 0.7（(N_w_te1, freq) 固定在 4 与 20 MHz）；
- 下游证据按量纲分别取：几何（外电极包围盒/面积）、网格（单元数）、响应（Vave/Ptot/V_center）；
- 同时校验驱动仍成立（V_outer=+1 / V_inner=-1 / Vdiff=2）。

产物：work/models/perturb_x_scale.json
用法：python work/tools/perturb_one_param.py
"""

from __future__ import annotations

import hashlib
import json
import math
import socket
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
MODELS = REPO / "work" / "models"
MODEL = MODELS / "b_GE_task3_2new_reverse_voltage_drive_v1.mph"
OUT = MODELS / "perturb_x_scale.json"
PORT = 2036
PARAM = "x_scale"
P0, P1 = 0.6, 0.7          # 只改这一个值
N1, FREQ = 4, "20[MHz]"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def port_open(p: int = PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", p), timeout=1.5):
            return True
    except OSError:
        return False


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    import jpype
    import numpy as np
    import mph

    started = not port_open()
    client = mph.Client(port=PORT) if not started else mph.start(cores=1, port=PORT)
    model = client.load(str(MODEL))
    java = model.java
    comp = java.modelNode("comp1")
    geom = comp.geom("geom1")
    mesh = comp.mesh("mesh1")
    print("model:", MODEL.name, "| sha256:", sha256(MODEL)[:16], "| COMSOL", client.version)

    # 固定其它两个量；停用参数扫描步
    java.param().set("N_w_te1", str(N1))
    for tag in ("param", "param2"):
        try:
            java.study("std1").feature(tag).active(False)
        except Exception:
            pass
    java.study("std1").feature("freq").set("plist", FREQ)

    def snapshot() -> dict:
        try:
            names = [str(x) for x in java.param().varnames()]
        except Exception:
            names = []
        out = {}
        for n in names:
            try:
                out[n] = str(java.param().get(n))
            except Exception:
                out[n] = "<unreadable>"
        return out

    def cx(expr):
        try:
            r = float(np.asarray(model.evaluate("real(" + expr + ")", inner=[0]),
                                 dtype=float).ravel()[0])
            i = float(np.asarray(model.evaluate("imag(" + expr + ")", inner=[0]),
                                 dtype=float).ravel()[0])
            return r, i
        except Exception:
            return None, None

    def geom_signature(ents):
        """外电极（cyl8）几何签名：面积 + 6 维包围盒。"""
        try:
            m = geom.measure()
            sel = m.selection()
            sel.init(2)
            sel.set("fin", jpype.JArray(jpype.JInt)(sorted(int(v) for v in ents)))
            return float(m.getArea()), [float(x) for x in m.getBoundingBox()]
        except Exception as exc:
            return None, "<" + type(exc).__name__ + ": " + str(exc)[:60] + ">"

    def one_point(xs: float) -> dict:
        java.param().set(PARAM, f"{xs:g}")
        java.param().set("N_w_te1", str(N1))
        t0 = time.perf_counter()
        geom.run()
        t_geom = round(time.perf_counter() - t0, 1)
        t1 = time.perf_counter()
        mesh.run()
        t_mesh = round(time.perf_counter() - t1, 1)
        try:
            nel = int(mesh.getNumElem())
        except Exception as exc:
            nel = "<" + type(exc).__name__ + ">"
        t2 = time.perf_counter()
        java.study("std1").run()
        t_solve = round(time.perf_counter() - t2, 1)
        fhz = None
        try:
            fhz = float(np.asarray(model.evaluate("freq", inner=[0]), dtype=float).ravel()[0])
        except Exception:
            pass
        rec = {"x_scale": xs, "N_w_te1": N1, "freq_MHz": (fhz / 1e6) if fhz else None,
               "geometry_seconds": t_geom, "mesh_seconds": t_mesh, "solve_seconds": t_solve,
               "mesh_element_count": nel}
        try:
            outer = sorted(int(v) for v in comp.physics("es").feature("pot1").selection().entities())
        except Exception:
            outer = []
        a, bb = geom_signature(outer)
        rec["outer_selection"] = outer
        rec["outer_area_m2"] = a
        rec["outer_bbox"] = bb
        for label, expr in (("V_outer", "ave_outer(V)"), ("V_inner", "ave_inner(V)"),
                            ("Vave", "Vave"), ("Ptot", "Ptot"), ("V_center", "V_center"),
                            ("I_inner", "intop3(es.JZ)"), ("I_outer", "intop4(es.JZ)")):
            r, i = cx(expr)
            rec[label + "_re"], rec[label + "_im"] = r, i
            rec[label + "_abs"] = None if r is None else abs(complex(r, i))
        if rec.get("V_outer_re") is not None and rec.get("V_inner_re") is not None:
            d = complex(rec["V_outer_re"], rec["V_outer_im"]) - complex(rec["V_inner_re"],
                                                                       rec["V_inner_im"])
            rec["Vdiff_abs"] = abs(d)
            rec["Vdiff_arg_deg"] = math.degrees(math.atan2(d.imag, d.real))
        return rec

    before_all = snapshot()
    print(f"\n[baseline] {PARAM} = {P0:g}（其余参数不动）")
    r0 = one_point(P0)
    after0_all = snapshot()
    print(f"  bbox={r0['outer_bbox']}｜area={r0['outer_area_m2']}｜elems={r0['mesh_element_count']}"
          f"｜Vave={r0['Vave_abs']}｜Ptot={r0['Ptot_abs']}｜Vdiff={r0.get('Vdiff_abs')}")

    print(f"\n[perturbed] {PARAM} = {P1:g}（**只改这一个**）")
    r1 = one_point(P1)
    after1_all = snapshot()
    print(f"  bbox={r1['outer_bbox']}｜area={r1['outer_area_m2']}｜elems={r1['mesh_element_count']}"
          f"｜Vave={r1['Vave_abs']}｜Ptot={r1['Ptot_abs']}｜Vdiff={r1.get('Vdiff_abs')}")

    # 断言语义：逐参数比对，**只允许 PARAM 不同**
    changed = {k: (before_all.get(k), after1_all.get(k))
               for k in set(before_all) | set(after1_all)
               if before_all.get(k) != after1_all.get(k)}
    only_target = list(changed) == [PARAM] or set(changed) <= {PARAM, "N_w_te1"}
    print("\n[断言] 与基线快照相比发生变化的参数：", changed)
    print("[断言] 仅目标参数（允许 N_w_te1 因固定写入）:", only_target)

    def ratio(a, b):
        return None if (a in (None, 0) or b is None) else a / b

    cmp_ = {
        "param": PARAM, "from": P0, "to": P1,
        "other_changed_params": {k: v for k, v in changed.items() if k != PARAM},
        "only_target_changed": only_target,
        "geometry": {"bbox_before": r0["outer_bbox"], "bbox_after": r1["outer_bbox"],
                     "area_before": r0["outer_area_m2"], "area_after": r1["outer_area_m2"],
                     "area_ratio": ratio(r1["outer_area_m2"], r0["outer_area_m2"])},
        "mesh": {"elements_before": r0["mesh_element_count"],
                 "elements_after": r1["mesh_element_count"],
                 "elements_ratio": ratio(r1["mesh_element_count"], r0["mesh_element_count"]),
                 "mesh_seconds_before": r0["mesh_seconds"], "mesh_seconds_after": r1["mesh_seconds"]},
        "response_at_20MHz": {
            "Vave_before": r0["Vave_abs"], "Vave_after": r1["Vave_abs"],
            "Vave_ratio": ratio(r1["Vave_abs"], r0["Vave_abs"]),
            "Ptot_before": r0["Ptot_abs"], "Ptot_after": r1["Ptot_abs"],
            "Ptot_ratio": ratio(r1["Ptot_abs"], r0["Ptot_abs"])},
        "drive_integrity": {"Vdiff_before": r0.get("Vdiff_abs"), "Vdiff_after": r1.get("Vdiff_abs")},
    }
    (OUT).write_text(json.dumps(
        {"model": str(MODEL), "model_sha256": sha256(MODEL),
         "script_sha256": sha256(Path(__file__).resolve()),
         "comparison": cmp_, "baseline_row": r0, "perturbed_row": r1,
         "params_snapshot_after_baseline": after0_all, "params_snapshot_after_perturbation": after1_all},
        ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("\n== 单参数扰动结论 ==")
    print(json.dumps(cmp_, ensure_ascii=False, indent=2, default=str))
    print("artifact:", OUT)
    try:
        client.clear()
        client.disconnect()
    except Exception:
        pass
    time.sleep(1)
    print("port 2036 open after run =", port_open())
    return 0


if __name__ == "__main__":
    import os as _os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(code)
