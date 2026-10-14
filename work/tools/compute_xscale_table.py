"""只算 x_scale = 0.6 与 0.7 两个状态，但**把表里的每个变量都算出来**（COMSOL 自算）。

对每个分支（legacy = 你那张表的原始驱动；reverse = 当前反相驱动分支）：
    设 x_scale、N_w_te1=4 -> 重建几何+网格 -> 一次求解 7 个频点
    逐频点按真实频率回读：Zin1_R/X、Zin2_R/X、Ptot、V_center(复)、Vave
    另附自算附加量：|V_outer|、|V_inner|、|Vdiff|、|I_inner|、|I_outer|、单元数、耗时

可选 `--compare` 会把 legacy 分支的自算值与用户导出表**同参数行**做相对差对照
（仅作对照，不作为数据来源）。

用法：python work/tools/compute_xscale_table.py --run-id xscale-0607
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import socket
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
MODELS = REPO / "work" / "models"
RUNS = REPO / "work" / "runs"
LEGACY = MODELS / "b_GE_task3_2new_legacy_1ohm_drive_v1.mph"
REVERSE = MODELS / "b_GE_task3_2new_reverse_voltage_drive_v1.mph"
USER_CSV = REPO / "work" / "reports" / "analysis_decision" / "newrange005" / "raw_source_table.csv"
PORT = 2036
COLS = ["x_scale", "N_w_te1", "freq_MHz", "Zin1_R_Ohm", "Zin1_X_Ohm", "Zin2_R_Ohm",
        "Zin2_X_Ohm", "Ptot_W", "V_center_re", "V_center_im", "Vave_mps",
        "V_outer_abs", "V_inner_abs", "Vdiff_abs", "I_inner_abs", "I_outer_abs",
        "mesh_element_count", "geometry_seconds", "mesh_seconds", "solve_seconds",
        "branch", "drive_mode", "model_sha256", "run_id"]


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--xs", default="0.6,0.7")
    ap.add_argument("--n1", type=int, default=4)
    ap.add_argument("--freqs", default="5,10,15,20,25,30,35")
    ap.add_argument("--branches", default="legacy,reverse")
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()

    import numpy as np
    import mph

    xs = [round(float(v), 4) for v in args.xs.split(",")]
    freqs = [f.strip() for f in args.freqs.split(",") if f.strip()]
    run_dir = RUNS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    branches = {"legacy": (LEGACY, "inner_fixed_minus_v0_outer_circuit_terminal_1ohm_to_reference"),
                "reverse": (REVERSE, "dual_electrode_antiphase_voltage_drive")}
    want = [b.strip() for b in args.branches.split(",") if b.strip()]

    all_rows = {}
    for bname in want:
        mpath, dmode = branches[bname]
        if not mpath.is_file():
            print("[skip] missing:", mpath, flush=True)
            continue
        msha = sha256(mpath)
        print(f"\n=== 分支 {bname}｜{mpath.name}｜sha256 {msha[:16]}…｜drive={dmode} ===", flush=True)
        started = not port_open()
        client = mph.Client(port=PORT) if not started else mph.start(cores=1, port=PORT)
        model = client.load(str(mpath))
        java = model.java
        comp = java.modelNode("comp1")
        geom = comp.geom("geom1")
        mesh = comp.mesh("mesh1")
        for tag in ("param", "param2"):
            try:
                java.study("std1").feature(tag).active(False)
            except Exception:
                pass
        java.study("std1").feature("freq").set("plist", " ".join(f + "[MHz]" for f in freqs))
        java.param().set("N_w_te1", str(args.n1))

        def cx(expr, i):
            try:
                r = float(np.asarray(model.evaluate("real(" + expr + ")", inner=[i]),
                                     dtype=float).ravel()[0])
                m = float(np.asarray(model.evaluate("imag(" + expr + ")", inner=[i]),
                                     dtype=float).ravel()[0])
                return r, m
            except Exception:
                return None, None

        rows = []
        for x in xs:
            java.param().set("x_scale", f"{x:g}")
            t0 = time.perf_counter()
            geom.run()
            tg = round(time.perf_counter() - t0, 1)
            t1 = time.perf_counter()
            mesh.run()
            tm = round(time.perf_counter() - t1, 1)
            try:
                nel = int(mesh.getNumElem())
            except Exception:
                nel = None
            t2 = time.perf_counter()
            java.study("std1").run()
            ts = round(time.perf_counter() - t2, 1)
            for i in range(len(freqs)):
                fhz = None
                try:
                    fhz = float(np.asarray(model.evaluate("freq", inner=[i]),
                                           dtype=float).ravel()[0])
                except Exception:
                    pass
                z1r, z1x = cx("Zin1", i)
                z2r, z2x = cx("Zin2", i)
                vcr, vci = cx("V_center", i)
                vo = cx("ave_outer(V)", i)
                vi = cx("ave_inner(V)", i)
                ii = cx("intop3(es.JZ)", i)
                io = cx("intop4(es.JZ)", i)
                rows.append({
                    "x_scale": x, "N_w_te1": args.n1,
                    "freq_MHz": (fhz / 1e6) if fhz else None,
                    "Zin1_R_Ohm": z1r, "Zin1_X_Ohm": z1x, "Zin2_R_Ohm": z2r, "Zin2_X_Ohm": z2x,
                    "Ptot_W": cx("Ptot", i)[0], "V_center_re": vcr, "V_center_im": vci,
                    "Vave_mps": cx("Vave", i)[0],
                    "V_outer_abs": None if vo[0] is None else abs(complex(*vo)),
                    "V_inner_abs": None if vi[0] is None else abs(complex(*vi)),
                    "Vdiff_abs": (abs(complex(*vo) - complex(*vi))
                                  if vo[0] is not None and vi[0] is not None else None),
                    "I_inner_abs": None if ii[0] is None else abs(complex(*ii)),
                    "I_outer_abs": None if io[0] is None else abs(complex(*io)),
                    "mesh_element_count": nel, "geometry_seconds": tg, "mesh_seconds": tm,
                    "solve_seconds": ts, "branch": bname, "drive_mode": dmode,
                    "model_sha256": msha, "run_id": args.run_id})
            print(f"  x_scale={x:g}: {len(freqs)} 频点完成｜elems={nel}｜几何 {tg}s 网格 {tm}s "
                  f"求解 {ts}s｜Ptot@20MHz={cx('Ptot', 3)[0]}", flush=True)
        all_rows[bname] = rows
        cp = run_dir / f"selfcomputed_xscale_{bname}.csv"
        with cp.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print("  → ", cp, flush=True)
        try:
            client.clear()
            client.disconnect()
        except Exception:
            pass
        time.sleep(1)
        print(f"  端口 {PORT} 仍开放={port_open()}", flush=True)

    # 合并 CSV
    merged = run_dir / "selfcomputed_xscale_all.csv"
    with merged.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for b in all_rows:
            w.writerows(all_rows[b])

    # 与用户导出表对照（仅 legacy、x=0.6/0.7、N1=4）
    cmp_out = None
    if args.compare and "legacy" in all_rows and USER_CSV.is_file():
        user = {}
        with USER_CSV.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                try:
                    k = (round(float(r["x_scale"]), 4), int(float(r["N_w_te1"])),
                         round(float(r["freq (Hz)"]) / 1e6))
                except Exception:
                    continue
                if k[1] == args.n1 and k[0] in xs:
                    user[k] = r
        cmp_rows = []
        for r in all_rows["legacy"]:
            k = (r["x_scale"], r["N_w_te1"], round(r["freq_MHz"]))
            u = user.get(k)
            if not u:
                continue
            for mine, theirs in (("Zin1_R_Ohm", "Zin1_R (Ω)"), ("Zin1_X_Ohm", "Zin1_X (Ω)"),
                                 ("Zin2_R_Ohm", "Zin2_R (Ω)"), ("Zin2_X_Ohm", "Zin2_X (Ω)"),
                                 ("Ptot_W", "Ptot (W)"), ("Vave_mps", "Vave (m/s)")):
                a, b = r.get(mine), None
                try:
                    b = float(u[theirs])
                except Exception:
                    pass
                rel = (abs(a - b) / abs(b)) if (a not in (None, 0) and b not in (None, 0)) else None
                cmp_rows.append({"x_scale": k[0], "N_w_te1": k[1], "freq_MHz": k[2],
                                 "quantity": mine, "selfcomputed": a, "user_export": b,
                                 "relative_difference": rel})
        cmp_out = run_dir / "selfcomputed_vs_user_export.csv"
        with cmp_out.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(cmp_rows[0]) if cmp_rows else ["x_scale"])
            w.writeheader()
            w.writerows(cmp_rows)
        nz = [c["relative_difference"] for c in cmp_rows if c["relative_difference"] is not None]
        print(f"\n对照表：{cmp_out}（{len(cmp_rows)} 条；中位相对差 "
              f"{sorted(nz)[len(nz) // 2] if nz else None}）", flush=True)

    (run_dir / "selfcomputed_xscale_manifest.json").write_text(json.dumps(
        {"run_id": args.run_id, "x_scale_values": xs, "N_w_te1": args.n1, "freqs_MHz": freqs,
         "branches": {b: {"model": str(branches[b][0]),
                          "model_sha256": sha256(branches[b][0]),
                          "drive_mode": branches[b][1], "n_rows": len(all_rows[b])}
                      for b in all_rows},
         "script_sha256": sha256(Path(__file__).resolve()),
         "note": "全部数值由本机 COMSOL 6.4 求解得到；未从用户导出表取数（对照表仅用于验证）"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n合并表：", merged, flush=True)
    return 0


if __name__ == "__main__":
    import os as _os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(code)
