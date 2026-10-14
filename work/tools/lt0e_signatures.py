"""LT0-E 剩余两项（无需求解，只读几何/选择/网格签名与表达式预判）。

1) N_w_te1 4 -> 5：内电极几何/选择签名改变，且无空选择/重叠/反转
2) fmax 35 -> 45：**仅表达式预判**（不保存为生产网格）——网格尺寸表达式求值应随之变化
整个脚本只建一个 mph.Client；不做任何频域求解。
产物：work/models/lt0e_signatures.json
"""

from __future__ import annotations

import hashlib
import json
import socket
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
MODELS = REPO / "work" / "models"
MODEL = MODELS / "b_GE_task3_2new_reverse_voltage_drive_v1.mph"
OUT = MODELS / "lt0e_signatures.json"
PORT = 2036


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
    import mph

    res: dict = {"model": str(MODEL), "model_sha256": sha256(MODEL),
                 "script_sha256": sha256(Path(__file__).resolve()), "checks": {}}
    started = not port_open()
    client = mph.Client(port=PORT) if not started else mph.start(cores=1, port=PORT)
    try:
        model = client.load(str(MODEL))
        java = model.java
        comp = java.modelNode("comp1")
        geom = comp.geom("geom1")
        mesh = comp.mesh("mesh1")
        java.param().set("x_scale", "0.6")
        print("loaded", MODEL.name, flush=True)

        def ents(tag):
            try:
                return sorted(int(v) for v in comp.selection(tag).entities())
            except Exception as exc:
                return "<" + type(exc).__name__ + ">"

        def measure(selection_ents):
            try:
                m = geom.measure()
                sel = m.selection()
                sel.init(2)
                sel.set("fin", jpype.JArray(jpype.JInt)(sorted(selection_ents)))
                return {"area_m2": float(m.getArea()),
                        "bbox": [float(x) for x in m.getBoundingBox()]}
            except Exception as exc:
                return {"error": type(exc).__name__ + ": " + str(exc)[:80]}

        def sig(n1):
            java.param().set("N_w_te1", str(n1))
            geom.run()
            mesh.run()
            try:
                nel = int(mesh.getNumElem())
            except Exception:
                nel = None
            inner = ents("cyl9")
            outer = ents("cyl8")
            ref = ents("cyl7")
            inter = sorted(set(inner if isinstance(inner, list) else [])
                           & set(outer if isinstance(outer, list) else []))
            return {"N_w_te1": n1, "inner_selection": inner, "outer_selection": outer,
                    "ref_selection": ref, "inner_count": len(inner) if isinstance(inner, list) else None,
                    "pairwise_inner_outer_overlap": inter,
                    "empty_selection": (not inner) or (not outer),
                    "inner_geometry": measure(inner if isinstance(inner, list) else []),
                    "mesh_element_count": nel}

        s4 = sig(4)
        s5 = sig(5)
        same_sel = s4["inner_selection"] == s5["inner_selection"]
        changed_area = (s4["inner_geometry"].get("area_m2") is not None
                        and s5["inner_geometry"].get("area_m2") is not None
                        and s4["inner_geometry"]["area_m2"] != s5["inner_geometry"]["area_m2"])
        res["checks"]["LT0_E_N_w_te1"] = {
            "n4": s4, "n5": s5,
            "selection_changed": (not same_sel),
            "inner_area_changed": changed_area,
            "no_empty_or_overlap": (not s5["empty_selection"]) and (not s5["pairwise_inner_outer_overlap"]),
            "pass": bool((not same_sel) and changed_area and (not s5["empty_selection"])
                         and (not s5["pairwise_inner_outer_overlap"])),
        }
        print("N_w_te1 4->5:", json.dumps({"sel_changed": not same_sel,
                                           "area_changed": changed_area,
                                           "elems": [s4["mesh_element_count"], s5["mesh_element_count"]],
                                           "inner_area": [s4["inner_geometry"].get("area_m2"),
                                                          s5["inner_geometry"].get("area_m2")]},
                                          ensure_ascii=False), flush=True)

        # ---- fmax 表达式预判（不保存模型）----
        f: dict = {}
        try:
            f["fmax_before"] = str(java.param().get("fmax"))
        except Exception as exc:
            f["fmax_before"] = "<" + type(exc).__name__ + ">"
        for tag in ("size", "ftri1", "size1"):
            try:
                f[f"mesh_feature_{tag}_hmax"] = str(mesh.feature(tag).getString("hmax"))
            except Exception:
                pass
        import numpy as np

        def val(expr):
            try:
                return float(np.asarray(model.evaluate(expr), dtype=float).ravel()[0])
            except Exception as exc:
                return "<" + type(exc).__name__ + ": " + str(exc)[:50] + ">"

        f["lamda_at_35"] = val("lamda")
        java.param().set("fmax", "45[MHz]")
        f["lamda_at_45"] = val("lamda")
        for tag in ("size", "ftri1", "size1"):
            try:
                f[f"mesh_feature_{tag}_hmax_at_45"] = str(mesh.feature(tag).getString("hmax"))
            except Exception:
                pass
        java.param().set("fmax", "35[MHz]")
        f["fmax_restored"] = str(java.param().get("fmax"))
        try:
            l35 = float(f["lamda_at_35"])
            l45 = float(f["lamda_at_45"])
            f["lamda_ratio_45_over_35"] = l45 / l35
            f["expected_ratio"] = 35.0 / 45.0
        except Exception:
            pass
        res["checks"]["LT0_E_fmax"] = f
        print("fmax 预判:", json.dumps(f, ensure_ascii=False, default=str)[:400], flush=True)
        res["note"] = ("fmax 只做表达式预判，**未保存**为生产网格；N_w_te1 签名不涉及频域求解")
    finally:
        try:
            client.clear()
            client.disconnect()
        except Exception:
            pass
        closed = False
        for _ in range(30):
            if not port_open():
                closed = True
                break
            time.sleep(1)
        res["server_cleanup"] = {"port_closed_within_30s": closed, "port_open_at_end": port_open()}
        OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print("cleanup:", res["server_cleanup"], flush=True)
        print("artifact:", OUT, flush=True)
    return 0


if __name__ == "__main__":
    import os as _os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(code)
