"""LT0-A/B/C 审计：Circuit 停用证据、Ground 记录修正、端口电流与 KCL。

约束（吸取上一轮教训）：**整个脚本只建一个 mph.Client**，分支/步骤之间不 disconnect。

LT0-A 证据链（任一条成立即可，多条同时给）：
  1) physics-level isActive()；
  2) study step 的物理场参与列表；
  3) 求解器 hybridvar 列表中是否仍含 cir./term1 自由度；
  4) 可选：导出 .m 静态文本并 grep。
LT0-B：不设 gnd1.V0（Ground 固有 0 V），建 ave_ref（cyl7 边界平均），验证 5/20/35 MHz 参考电位≈0。
LT0-C：用完整法向电流密度 J·n 积分三端口电流，算 kcl_relative；>1% 则置 electrical_current_metrics_excluded。

产物：work/models/lt0_audit.json
用法：python work/tools/lt0_audit.py
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
OUT = MODELS / "lt0_audit.json"
PORT = 2036
FREQS = ("5", "20", "35")
KCL_TOL = 0.01
JN = "es.JX*nx+es.JY*ny+es.JZ*nz"


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


def wait_port_closed(max_s: int = 30) -> bool:
    for _ in range(max_s):
        if not port_open():
            return True
        time.sleep(1)
    return not port_open()


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    import numpy as np
    import mph

    audit: dict = {"model": str(MODEL), "model_sha256": sha256(MODEL),
                   "script_sha256": sha256(Path(__file__).resolve()),
                   "freqs_MHz": list(FREQS), "kcl_tolerance": KCL_TOL,
                   "checks": {}, "rows": []}
    started = not port_open()
    client = mph.Client(port=PORT) if not started else mph.start(cores=1, port=PORT)
    server_pid = None
    try:
        model = client.load(str(MODEL))
        java = model.java
        comp = java.modelNode("comp1")
        print("loaded", MODEL.name, "COMSOL", client.version, flush=True)

        # ---------------- LT0-A ----------------
        a: dict = {}
        for label, fn in (("physics_isActive", lambda: comp.physics("cir").isActive()),
                          ("physics_tags", lambda: [str(t) for t in comp.physics().tags()])):
            try:
                a[label] = fn()
            except Exception as exc:
                a[label] = "<" + type(exc).__name__ + ": " + str(exc)[:70] + ">"
        try:
            hyb = str(java.sol("sol1").feature("s1").feature("i1").feature("mg2").getString("hybridvar"))
            a["hybridvar"] = hyb
            a["hybridvar_has_cir"] = ("cir" in hyb.lower())
            a["hybridvar_has_term1"] = ("term1" in hyb.lower())
        except Exception as exc:
            a["hybridvar"] = "<" + type(exc).__name__ + ": " + str(exc)[:70] + ">"
        try:
            a["study_physics_list"] = str(java.study("std1").feature("freq").getString("phys"))
        except Exception as exc:
            a["study_physics_list"] = "<" + type(exc).__name__ + ": " + str(exc)[:70] + ">"
        mtext = MODEL.with_suffix(".export.m")
        try:
            model.save(str(mtext))
            a["m_export_path"] = str(mtext)
            a["m_export_ok"] = mtext.is_file()
            if mtext.is_file():
                txt = mtext.read_text(encoding="utf-8", errors="replace")
                a["m_export_has_cir_active_false"] = "cir').active(false)" in txt
                a["m_export_has_term1_active_false"] = "term1').active(false)" in txt
        except Exception as exc:
            a["m_export_ok"] = False
            a["m_export_error"] = type(exc).__name__ + ": " + str(exc)[:80]
        cir_ok = False
        if isinstance(a.get("physics_isActive"), bool):
            cir_ok = (a["physics_isActive"] is False)
        if a.get("hybridvar_has_cir") is False and a.get("hybridvar_has_term1") is False:
            cir_ok = cir_ok or True
        audit["checks"]["LT0_A"] = {"cir_inactive_verified": bool(cir_ok),
                                    "cir_inactive_evidence": a,
                                    "term1_active": (None if not isinstance(
                                        a.get("physics_isActive"), bool) else None)}
        print("LT0-A:", json.dumps({k: v for k, v in a.items() if k != "m_export_path"},
                                   ensure_ascii=False)[:400], flush=True)

        # ---------------- LT0-B ----------------
        b: dict = {}
        try:
            g = comp.physics("es").feature("gnd1")
            g.active(True)
            b["gnd1_active_set"] = True
            try:
                b["gnd1_V0_property"] = str(g.getString("V0"))
            except Exception as exc:
                b["gnd1_V0_property"] = "absent (" + type(exc).__name__ + ") → Ground 固有 0 V"
            b["change_log_note"] = "gnd1 active; zero potential inherent to Ground feature"
        except Exception as exc:
            b["gnd1_error"] = type(exc).__name__ + ": " + str(exc)[:80]
        try:
            comp.cpl("ave_ref")
        except Exception:
            try:
                comp.cpl().create("ave_ref", "Average")
                comp.cpl("ave_ref").selection().named("cyl7")
            except Exception as exc:
                b["ave_ref_error"] = type(exc).__name__ + ": " + str(exc)[:80]
        audit["checks"]["LT0_B_pre"] = b

        # ---------------- 求解 ----------------
        for tag in ("param", "param2"):
            try:
                java.study("std1").feature(tag).active(False)
            except Exception:
                pass
        java.study("std1").feature("freq").set("plist", " ".join(x + "[MHz]" for x in FREQS))
        java.param().set("x_scale", "0.6")
        java.param().set("N_w_te1", "4")
        t0 = time.perf_counter()
        java.study("std1").run()
        audit["solve_seconds"] = round(time.perf_counter() - t0, 1)
        print("solved", len(FREQS), "freq in", audit["solve_seconds"], "s", flush=True)

        def cx(expr, i):
            try:
                r = float(np.asarray(model.evaluate("real(" + expr + ")", inner=[i]),
                                     dtype=float).ravel()[0])
                m = float(np.asarray(model.evaluate("imag(" + expr + ")", inner=[i]),
                                     dtype=float).ravel()[0])
                return r, m
            except Exception:
                return None, None

        for i in range(len(FREQS)):
            fhz = None
            try:
                fhz = float(np.asarray(model.evaluate("freq", inner=[i]), dtype=float).ravel()[0])
            except Exception:
                pass
            row = {"index": i, "freq_MHz": (fhz / 1e6) if fhz else None}
            row["V_outer"] = cx("ave_outer(V)", i)
            row["V_inner"] = cx("ave_inner(V)", i)
            row["V_ref"] = cx("ave_ref(V)", i)
            row["I_outer"] = cx("intop4(" + JN + ")", i)
            row["I_inner"] = cx("intop3(" + JN + ")", i)
            row["I_ref"] = cx("int_gnd(" + JN + ")", i)
            row["I_outer_Zonly"] = cx("intop4(es.JZ)", i)
            row["I_inner_Zonly"] = cx("intop3(es.JZ)", i)
            io, ii, ir = row["I_outer"], row["I_inner"], row["I_ref"]
            if None not in (io[0], ii[0], ir[0]):
                co, ci, cr = complex(*io), complex(*ii), complex(*ir)
                den = abs(co) + abs(ci) + abs(cr)
                row["kcl_relative"] = (abs(co + ci + cr) / den) if den else None
            audit["rows"].append(row)
            print("  ", row["freq_MHz"], "MHz | V_out", row["V_outer"], "| V_in =", row["V_inner"],
                  "| V_ref =", row["V_ref"], "| kcl_rel =", row.get("kcl_relative"), flush=True)

        kcls = [r.get("kcl_relative") for r in audit["rows"] if r.get("kcl_relative") is not None]
        kcl_ok = bool(kcls) and max(kcls) <= KCL_TOL
        vref_ok = all(r["V_ref"][0] is not None and abs(complex(*r["V_ref"])) < 1e-6
                      for r in audit["rows"])
        vok = all(r["V_outer"][0] is not None and r["V_inner"][0] is not None
                  and abs(complex(*r["V_outer"]) - 1.0) < 1e-6
                  and abs(complex(*r["V_inner"]) + 1.0) < 1e-6 for r in audit["rows"])
        audit["checks"]["LT0_B"] = {"ground_voltage_verified": vref_ok,
                                    "reference_potential_abs": [None if r["V_ref"][0] is None
                                                                else abs(complex(*r["V_ref"]))
                                                                for r in audit["rows"]]}
        audit["checks"]["LT0_C"] = {"kcl_max_relative": max(kcls) if kcls else None,
                                    "kcl_pass": kcl_ok,
                                    "electrical_current_metrics_excluded": (not kcl_ok),
                                    "expression": JN,
                                    "sign_convention": "各 intop 面法向（外法向）；未做端口正端归一",
                                    "caveat": "三电极边界未必构成闭合面，残差含非电极表面贡献"}
        audit["checks"]["voltage_gate"] = {"pass": bool(vok and vref_ok),
                                           "note": "要求 V_outer≈+1、V_inner≈-1、V_ref≈0"}
        print("\n== LT0 门槛 ==", flush=True)
        for k, v in audit["checks"].items():
            print("  ", k, ":", json.dumps(v, ensure_ascii=False, default=str)[:220], flush=True)
    finally:
        try:
            client.clear()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass
        closed = wait_port_closed(30)
        audit["server_cleanup"] = {"port_2036_closed_within_30s": closed,
                                   "port_open_at_end": port_open()}
        OUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        print("\ncleanup:", audit["server_cleanup"], flush=True)
        print("artifact:", OUT, flush=True)
    return 0


if __name__ == "__main__":
    import os as _os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(code)
