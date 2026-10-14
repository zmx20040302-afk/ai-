"""自算参数扫描：用 COMSOL 真实求解整张网格（**不读取用户导出的表格**）。

对每个 (x_scale, N_w_te1)：
    设参 -> 重建几何 -> 重建网格 -> 一次求解 7 个频点 -> 逐频点按真实频率回读并落盘
落盘策略：**每个组合求解完成后立即追加** CSV + JSONL（可断点续跑，`--resume`）。

用法：
    python work/tools/sweep_reverse_drive.py --xs 0.4:0.05:0.8 --n1 1:1:18 \
        --run-id sweep-rev-20260913 --freqs 5,10,15,20,25,30,35
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
DEFAULT_MODEL = MODELS / "b_GE_task3_2new_reverse_voltage_drive_v1.mph"
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


COLS = ["x_scale", "N_w_te1", "freq_MHz", "Ptot_W", "Vave_mps", "V_center_re", "V_center_im",
        "Zin1_R_Ohm", "Zin1_X_Ohm", "V_outer_re", "V_inner_re", "Vdiff_abs",
        "I_inner_abs", "I_outer_abs", "mesh_element_count", "geometry_seconds", "mesh_seconds",
        "solve_seconds", "drive_mode", "model_sha256", "run_id"]


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="COMSOL 自算参数扫描（可断点续跑）")
    ap.add_argument("--model", default=str(DEFAULT_MODEL))
    ap.add_argument("--xs", default="0.4:0.05:0.8")
    ap.add_argument("--n1", default="1:1:18")
    ap.add_argument("--freqs", default="5,10,15,20,25,30,35")
    ap.add_argument("--combos", default=None,
                    help="显式组合列表（覆盖 --xs/--n1），形如 '0.6:4,0.7:5,0.45:6'")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    import numpy as np
    import mph

    a, st, b = (float(v) for v in args.xs.split(":"))
    xs = [round(a + st * i, 4) for i in range(round((b - a) / st) + 1)]
    n1a, n1b = (int(v) for v in args.n1.split(":")[::2])
    n1s = list(range(n1a, n1b + 1))
    freqs = [f.strip() for f in args.freqs.split(",") if f.strip()]
    combos = ([(round(float(t.split(":")[0]), 4), int(t.split(":")[1]))
               for t in args.combos.split(",") if t.strip()]
              if args.combos else [(x, n) for x in xs for n in n1s])

    run_dir = RUNS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    csv_path = run_dir / "selfcomputed_sweep.csv"
    done: set = set()
    if args.resume and csv_path.is_file():
        with csv_path.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                done.add((float(r["x_scale"]), int(float(r["N_w_te1"]))))
        print("resume: 已完成", len(done), "个组合", flush=True)

    model_sha = sha256(Path(args.model))
    print(f"model={Path(args.model).name} sha256={model_sha[:16]}…", flush=True)
    print(f"网格: x {xs} × N1 {n1s} = {len(combos)} 组合 × {len(freqs)} 频点"
          f" = {len(combos) * len(freqs)} 次求解", flush=True)
    print(f"run_id={args.run_id}｜落盘 {csv_path}", flush=True)

    started = not port_open(args.port)
    client = mph.Client(port=args.port) if not started else mph.start(cores=1, port=args.port)
    model = client.load(args.model)
    java = model.java
    comp = java.modelNode("comp1")
    geom = comp.geom("geom1")
    mesh = comp.mesh("mesh1")
    print(f"COMSOL {client.version}｜self-started server={started}", flush=True)
    for tag in ("param", "param2"):
        try:
            java.study("std1").feature(tag).active(False)
        except Exception:
            pass
    java.study("std1").feature("freq").set("plist", " ".join(f + "[MHz]" for f in freqs))

    def cx(expr, i):
        try:
            r = float(np.asarray(model.evaluate("real(" + expr + ")", inner=[i]),
                                 dtype=float).ravel()[0])
            m = float(np.asarray(model.evaluate("imag(" + expr + ")", inner=[i]),
                                 dtype=float).ravel()[0])
            return r, m
        except Exception:
            return None, None

    new_file = not csv_path.is_file()
    fh = csv_path.open("a", newline="", encoding="utf-8-sig")
    wr = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
    if new_file:
        wr.writeheader()
        fh.flush()
    jsonl = (run_dir / "selfcomputed_sweep.jsonl").open("a", encoding="utf-8")
    t_start = time.perf_counter()
    n_rows = 0
    try:
        for ci, (x, n) in enumerate(combos, start=1):
            if (x, n) in done:
                print(f"[{ci}/{len(combos)}] ({x:g},{n}) 已存在，跳过", flush=True)
                continue
            java.param().set("x_scale", f"{x:g}")
            java.param().set("N_w_te1", f"{n:d}")
            t0 = time.perf_counter()
            try:
                geom.run()
                g_ok = True
            except Exception as exc:
                g_ok = False
                print(f"[{ci}/{len(combos)}] ({x:g},{n}) 几何失败: {exc}", flush=True)
            tg = round(time.perf_counter() - t0, 1)
            tm = ts = None
            nel = None
            if g_ok:
                t1 = time.perf_counter()
                try:
                    mesh.run()
                    m_ok = True
                except Exception as exc:
                    m_ok = False
                    print(f"[{ci}/{len(combos)}] ({x:g},{n}) 网格失败: {exc}", flush=True)
                tm = round(time.perf_counter() - t1, 1)
                if m_ok:
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
                        row = {"x_scale": x, "N_w_te1": n,
                               "freq_MHz": (fhz / 1e6) if fhz else None,
                               "Ptot_W": cx("Ptot", i)[0], "Vave_mps": cx("Vave", i)[0],
                               "V_center_re": cx("V_center", i)[0],
                               "V_center_im": cx("V_center", i)[1],
                               "Zin1_R_Ohm": cx("Zin1", i)[0], "Zin1_X_Ohm": cx("Zin1", i)[1],
                               "V_outer_re": cx("ave_outer(V)", i)[0],
                               "V_inner_re": cx("ave_inner(V)", i)[0],
                               "mesh_element_count": nel, "geometry_seconds": tg,
                               "mesh_seconds": tm, "solve_seconds": ts,
                               "drive_mode": "dual_electrode_antiphase_voltage_drive",
                               "model_sha256": model_sha, "run_id": args.run_id}
                        vo = cx("ave_outer(V)", i)
                        vi = cx("ave_inner(V)", i)
                        row["Vdiff_abs"] = (abs(complex(vo[0], vo[1]) - complex(vi[0], vi[1]))
                                            if vo[0] is not None and vi[0] is not None else None)
                        ii = cx("intop3(es.JZ)", i)
                        io = cx("intop4(es.JZ)", i)
                        row["I_inner_abs"] = None if ii[0] is None else abs(complex(*ii))
                        row["I_outer_abs"] = None if io[0] is None else abs(complex(*io))
                        wr.writerow(row)
                        n_rows += 1
                    fh.flush()
                    jsonl.write(json.dumps({"x_scale": x, "N_w_te1": n, "elems": nel,
                                            "solve_s": ts, "n_freq": len(freqs)},
                                           ensure_ascii=False) + "\n")
                    jsonl.flush()
                    el = (time.perf_counter() - t_start) / 60
                    print(f"[{ci}/{len(combos)}] ({x:g},{n}) ok｜elems={nel}｜几何 {tg}s "
                          f"网格 {tm}s 求解 {ts}s｜累计 {n_rows} 行｜已用 {el:.1f} min", flush=True)
                else:
                    print(f"[{ci}/{len(combos)}] ({x:g},{n}) 网格失败，记 0 行", flush=True)
    finally:
        fh.close()
        jsonl.close()
        try:
            client.clear()
            client.disconnect()
        except Exception:
            pass
        time.sleep(1)
        print(f"\n完成 {n_rows} 行；端口 {args.port} 仍开放={port_open(args.port)}", flush=True)
        print(f"产物：{csv_path}", flush=True)
    return 0


if __name__ == "__main__":
    import os as _os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(code)
