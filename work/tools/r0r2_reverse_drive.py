"""R0-R2: build the dual-electrode antiphase voltage drive branch and validate at 3 frequencies.

R0 changes ONLY the drive (geometry/material/structure/acoustics/mesh untouched):
    pot1 -> cyl8 outer, V0=+vamp ; pot2 -> cyl9 inner, V0=-vamp ; gnd1 -> cyl7 reference 0 V
    term1 disabled ; cir interface disabled (both kept for audit/rollback, logged)
R1 observables: Boundary Average couplings ave_outer/ave_inner + reference integral int_gnd,
    with electrode-potential expression probing.
R2 baseline (0.6,4) at 5/20/35 MHz, plus a 20 MHz linearity check (vamp = 0.5 / 1.0).

Artifacts: work/models/{drive_change_manifest.json, reverse_drive_audit.json, reverse_drive_audit.csv}
Usage: python work/tools/r0r2_reverse_drive.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import socket
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
MODELS = REPO / "work" / "models"
MASTER = Path(r"C:\Users\zmx\Desktop\b_GE_task3_2new.mph")
LEGACY = MODELS / "b_GE_task3_2new_currentdrive_fmax45_v1.mph"
ARCHIVE = MODELS / "b_GE_task3_2new_legacy_1ohm_drive_v1.mph"
REVERSE = MODELS / "b_GE_task3_2new_reverse_voltage_drive_v1.mph"
PORT = 2036
FREQS = ("5", "20", "35")
VAMP = 1.0
VMETA = ("ave_outer(V)", "comp1.ave_outer(V)", "ave_outer(es.V)")


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


def fmt(v) -> str:
    return "None" if v is None else f"{v:.6g}"


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    import numpy as np
    import mph

    if not ARCHIVE.is_file():
        shutil.copy2(LEGACY, ARCHIVE)
        print("[setup] legacy archive created:", ARCHIVE.name)
    if not REVERSE.is_file():
        shutil.copy2(MASTER, REVERSE)
        print("[setup] reverse branch created from master:", REVERSE.name)
    for p in (MASTER, LEGACY, ARCHIVE, REVERSE):
        if not p.is_file():
            print("[STOP] missing:", p)
            return 2

    manifest = {
        "kind": "drive_change_manifest", "phase": "R0",
        "parent_model_sha256": sha256(MASTER),
        "legacy_working_copy": {"path": str(LEGACY), "sha256": sha256(LEGACY)},
        "legacy_archive": {"path": str(ARCHIVE), "sha256": sha256(ARCHIVE)},
        "working_model_path": str(REVERSE),
        "working_model_sha256_before_change": sha256(REVERSE),
        "working_model_sha256_after_change": None,
        "comsol_version": "6.4", "mph_version": "1.4.0",
        "drive_mode": "dual_electrode_antiphase_voltage_drive",
        "legacy_drive_mode": "inner_fixed_minus_v0_outer_circuit_terminal_1ohm_to_reference",
        "drive_amplitude_convention": {"vamp": "1[V]", "V_outer": "+vamp", "V_inner": "-vamp",
                                       "V_reference": "0[V]", "Vdiff": "V_outer-V_inner=2*vamp"},
        "change_log": [], "script_sha256": sha256(Path(__file__).resolve()),
    }

    started = not port_open()
    client = mph.Client(port=PORT) if not started else mph.start(cores=1, port=PORT)
    model = client.load(str(REVERSE))
    java = model.java
    comp = java.modelNode("comp1")
    print("loaded", REVERSE.name, "| COMSOL", client.version, "| self-started server =", started)

    def log(what, detail=""):
        manifest["change_log"].append({"what": what, "detail": str(detail)[:200],
                                       "at": time.strftime("%H:%M:%S")})
        print("  [R0]", what, detail)

    java.param().set("vamp", f"{VAMP}[V]")
    log("param.set", "vamp = 1[V]")

    f = comp.physics("es").feature
    for tag, val, note in (("pot1", "vamp", "outer cyl8 enabled, +vamp"),
                           ("pot2", "-vamp", "inner cyl9 kept, -vamp")):
        try:
            f(tag).active(True)
            f(tag).set("V0", val)
            log(tag, note)
        except Exception as exc:
            log(tag + " FAILED", f"{type(exc).__name__}: {exc}")
    try:
        f("gnd1").active(True)
        f("gnd1").set("V0", "0[V]")
        log("gnd1", "reference cyl7 = 0 V")
    except Exception as exc:
        log("gnd1 FAILED", f"{type(exc).__name__}: {exc}")
    try:
        f("term1").active(False)
        log("term1", "disabled (kept for audit/rollback)")
    except Exception as exc:
        log("term1 FAILED", f"{type(exc).__name__}: {exc}")
    try:
        comp.physics("cir").active(False)
        log("cir", "Circuit interface disabled (kept)")
    except Exception as exc:
        log("cir FAILED", f"{type(exc).__name__}: {exc}")

    def ents(tag):
        try:
            return sorted(int(v) for v in comp.selection(tag).entities())
        except Exception as exc:
            return "<" + type(exc).__name__ + ">"

    def active(tag):
        try:
            return bool(f(tag).isActive())
        except Exception:
            return None

    sig = {"pot1": ents("cyl8"), "pot2": ents("cyl9"), "gnd1": ents("cyl7")}
    sets = {k: set(v) for k, v in sig.items() if isinstance(v, list)}
    keys = list(sets)
    overlaps = {a + "&" + b: sorted(sets[a] & sets[b])
                for i, a in enumerate(keys) for b in keys[i + 1:]}
    gate = {"pot1_active": active("pot1"), "pot2_active": active("pot2"),
            "gnd1_active": active("gnd1"), "term1_active": active("term1"),
            "cir_active": active("cir"),
            "pot1_selection_nonempty": bool(sets.get("pot1")),
            "pot2_selection_nonempty": bool(sets.get("pot2")),
            "gnd1_selection_nonempty": bool(sets.get("gnd1")),
            "pairwise_selection_overlap": overlaps,
            "electrical_bc_conflict": any(bool(v) for v in overlaps.values())}
    manifest["active_boundary_features"] = {k: gate[k + "_active"] for k in ("pot1", "pot2", "gnd1")}
    manifest["inactive_boundary_features"] = {"term1": gate["term1_active"], "cir": gate["cir_active"]}
    manifest["feature_selection_ids"] = {k: (v if isinstance(v, list) else str(v))
                                         for k, v in sig.items()}
    print("  boundary gate:", json.dumps(gate, ensure_ascii=False))
    if gate["electrical_bc_conflict"] or not all(
            gate[k] for k in ("pot1_selection_nonempty", "pot2_selection_nonempty",
                              "gnd1_selection_nonempty")):
        print("[STOP] boundary gate failed; not solving")
        try:
            client.clear()
            client.disconnect()
        except Exception:
            pass
        return 3

    for tag, sel, ctype in (("ave_outer", "cyl8", "Average"), ("ave_inner", "cyl9", "Average"),
                            ("int_gnd", "cyl7", "Integration")):
        try:
            comp.cpl(tag).selection().named(sel)
            log(tag, "coupling present -> " + sel)
        except Exception:
            try:
                comp.cpl().create(tag, ctype)
                comp.cpl(tag).selection().named(sel)
                log(tag, "created " + ctype + " -> " + sel)
            except Exception as exc:
                log(tag + " FAILED", f"{type(exc).__name__}: {exc}")

    for tag in ("param", "param2"):
        try:
            java.study("std1").feature(tag).active(False)
        except Exception:
            pass
    java.study("std1").feature("freq").set("plist", " ".join(x + "[MHz]" for x in FREQS))

    def cx(expr, i):
        try:
            re_ = float(np.asarray(model.evaluate("real(" + expr + ")", inner=[i]),
                                   dtype=float).ravel()[0])
            im_ = float(np.asarray(model.evaluate("imag(" + expr + ")", inner=[i]),
                                   dtype=float).ravel()[0])
            return re_, im_
        except Exception:
            return None, None

    t0 = time.perf_counter()
    java.study("std1").run()
    solve_s = round(time.perf_counter() - t0, 1)
    print("  solved", len(FREQS), "frequencies in", solve_s, "s")

    vmeta = None
    for cand in VMETA:
        r, _ = cx(cand, 0)
        if r is not None:
            vmeta = cand
            print("  electrode-potential expression OK:", cand)
            break
    if vmeta is None:
        print("  [warn] all electrode-potential expressions failed; left blank (no pass claim)")
    manifest["electrode_potential_expression"] = vmeta

    rows = []
    for i in range(len(FREQS)):
        fhz = None
        try:
            fhz = float(np.asarray(model.evaluate("freq", inner=[i]), dtype=float).ravel()[0])
        except Exception:
            pass
        rec = {"index": i, "freq_MHz": (fhz / 1e6) if fhz else None}
        if vmeta:
            vo = cx(vmeta, i)
            vi = cx(vmeta.replace("outer", "inner"), i)
            rec["V_outer_re"], rec["V_outer_im"] = vo
            rec["V_inner_re"], rec["V_inner_im"] = vi
            if vo[0] is not None and vi[0] is not None:
                d = complex(vo[0], vo[1]) - complex(vi[0], vi[1])
                rec["Vdiff_abs"] = abs(d)
                rec["Vdiff_arg_deg"] = math.degrees(math.atan2(d.imag, d.real))
        for label, expr in (("I_outer", "intop4(es.JZ)"), ("I_inner", "intop3(es.JZ)"),
                            ("I_ref", "int_gnd(es.JZ)"), ("Ptot", "Ptot"),
                            ("Vave", "Vave"), ("V_center", "V_center")):
            r, im = cx(expr, i)
            rec[label + "_re"], rec[label + "_im"] = r, im
            rec[label + "_abs"] = None if r is None else abs(complex(r, im))
        if rec.get("I_inner_re") is not None and rec.get("I_outer_re") is not None:
            iin = complex(rec["I_inner_re"], rec["I_inner_im"])
            iout = complex(rec["I_outer_re"], rec["I_outer_im"])
            iref = (complex(rec["I_ref_re"], rec["I_ref_im"])
                    if rec.get("I_ref_re") is not None else None)
            rec["KCL_residual_abs"] = abs(iin + iout + iref) if iref is not None else None
            rec["KCL_note"] = ("I_inner+I_outer+I_ref, signs per each intop face normal; preliminary"
                               if iref is not None
                               else "reference current unavailable; residual left blank")
        rows.append(rec)

    lin = []
    for amp in (0.5, 1.0):
        java.param().set("vamp", f"{amp}[V]")
        java.study("std1").feature("freq").set("plist", "20[MHz]")
        t1 = time.perf_counter()
        java.study("std1").run()
        dt = round(time.perf_counter() - t1, 1)
        entry = {"vamp_V": amp, "Vave": cx("Vave", 0)[0], "Ptot": cx("Ptot", 0)[0],
                 "I_inner_re": cx("intop3(es.JZ)", 0)[0], "solve_s": dt}
        lin.append(entry)
        print("  linearity vamp =", amp, "V: Vave =", fmt(entry["Vave"]),
              "Ptot =", fmt(entry["Ptot"]), "(" + str(dt) + " s)")
    ratio = None
    if len(lin) == 2 and lin[0]["Vave"] and lin[0]["Ptot"]:
        ratio = {"Vave_ratio": lin[1]["Vave"] / lin[0]["Vave"],
                 "Ptot_ratio": lin[1]["Ptot"] / lin[0]["Ptot"],
                 "expected": {"Vave_ratio": 2.0, "Ptot_ratio": 4.0}}
        print("  linearity ratios:", json.dumps(ratio, ensure_ascii=False))

    java.param().set("vamp", f"{VAMP}[V]")
    model.save(str(REVERSE))
    manifest["working_model_sha256_after_change"] = sha256(REVERSE)
    manifest["criteria_object"] = {
        "drive_mode": manifest["drive_mode"], "vamp_V": VAMP, "freqs_MHz": list(FREQS),
        "gate": {k: v for k, v in gate.items() if k != "pairwise_selection_overlap"}}
    manifest["criteria_hash"] = hashlib.sha256(json.dumps(
        manifest["criteria_object"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (MODELS / "drive_change_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    audit = {"model": str(REVERSE),
             "model_sha256_after": manifest["working_model_sha256_after_change"],
             "comsol_version": str(client.version), "mph_version": mph.__version__,
             "drive_mode": manifest["drive_mode"], "vamp_V": VAMP, "boundary_gate": gate,
             "electrode_potential_expression": vmeta, "solve_seconds_3freq": solve_s,
             "rows": rows, "linearity_check": lin, "linearity_ratios": ratio}
    (MODELS / "reverse_drive_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if rows:
        with (MODELS / "reverse_drive_audit.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    try:
        client.clear()
        client.disconnect()
    except Exception:
        pass
    time.sleep(1)
    print("\nport 2036 open after run =", port_open())
    print("artifacts:", MODELS / "drive_change_manifest.json", "|", MODELS / "reverse_drive_audit.json")
    print("\n== 3-freq summary ==")
    for r in rows:
        print("  ", fmt(r.get("freq_MHz")), "MHz | Vout =", fmt(r.get("V_outer_re")),
              "| Vin =", fmt(r.get("V_inner_re")), "| |Vdiff| =", fmt(r.get("Vdiff_abs")),
              "| |I_in| =", fmt(r.get("I_inner_abs")), "| |I_out| =", fmt(r.get("I_outer_abs")),
              "| Ptot =", fmt(r.get("Ptot_abs")), "| Vave =", fmt(r.get("Vave_abs")))
    return 0


if __name__ == "__main__":
    import os as _os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(code)
