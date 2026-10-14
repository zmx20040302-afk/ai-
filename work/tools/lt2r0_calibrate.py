"""LT2-R0：单组合 (0.8,2) × 7 频点的资源校准（Codex 裁定 §4）。

要求：全新 server、单实例单 client、串行；**至少每 5 s 采样**：
    timestamp, server_pid, server_working_set_mb, server_peak_working_set_mb,
    system_available_physical_mb, system_memory_load_percent, current_combo, current_stage
另记 commit 可用（Codex 未要求，但 Windows 换页风险更直接的信号）。
产物：work/runs/<run-id>/{resource_timeline.csv, lt2r0_result.json, lt2r0_rows.csv}
用法：python work/tools/lt2r0_calibrate.py --run-id lt2-resource-calibration-x080-n02
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import csv
import hashlib
import json
import socket
import sys
import threading
import time
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
MODELS = REPO / "work" / "models"
RUNS = REPO / "work" / "runs"
MODEL = MODELS / "b_GE_task3_2new_reverse_voltage_drive_v1.mph"
PORT = 2036
FREQS = ("5", "10", "15", "20", "25", "30", "35")
X, N1 = 0.8, 2


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def system_mem() -> dict:
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return {"available_physical_mb": round(m.ullAvailPhys / 1048576, 1),
            "memory_load_percent": int(m.dwMemoryLoad),
            "commit_available_mb": round(m.ullAvailPageFile / 1048576, 1)}


def proc_mem(pid: int) -> dict:
    if not pid:
        return {}
    h = ctypes.windll.kernel32.OpenProcess(0x0410, False, pid)  # QUERY_INFORMATION|VM_READ
    if not h:
        return {}
    try:
        c = PROCESS_MEMORY_COUNTERS()
        c.cb = ctypes.sizeof(c)
        ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
        return {"server_working_set_mb": round(c.WorkingSetSize / 1048576, 1),
                "server_peak_working_set_mb": round(c.PeakWorkingSetSize / 1048576, 1)}
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def server_pid() -> int | None:
    import subprocess
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-Process comsolmphserver -ErrorAction SilentlyContinue | "
                              "Sort-Object StartTime -Descending | Select-Object -First 1).Id"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return int(out) if out.isdigit() else None
    except Exception:
        return None


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
    import numpy as np
    import mph

    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="lt2-resource-calibration-x080-n02")
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()

    run_dir = RUNS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    tl_path = run_dir / "resource_timeline.csv"

    assert not port_open(), f"端口 {PORT} 已被占用，拒绝启动（禁止并行 server）"
    state = {"pid": None, "combo": f"({X},{N1})", "stage": "startup", "stop": False}
    tl_file = tl_path.open("w", newline="", encoding="utf-8-sig")
    tl = csv.DictWriter(tl_file, fieldnames=["timestamp", "elapsed_s", "server_pid",
                                             "server_working_set_mb", "server_peak_working_set_mb",
                                             "system_available_physical_mb",
                                             "system_memory_load_percent", "commit_available_mb",
                                             "current_combo", "current_stage"])
    tl.writeheader()
    t_start = time.perf_counter()
    samples = {"min_avail": None, "max_ws": 0.0, "peak": 0.0}

    def sampler():
        while not state["stop"]:
            s = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "elapsed_s": round(time.perf_counter() - t_start, 1),
                 "server_pid": state["pid"], "current_combo": state["combo"],
                 "current_stage": state["stage"]}
            s.update(proc_mem(state["pid"]) if state["pid"] else {})
            s.update(system_mem())
            try:
                tl.writerow({k: s.get(k) for k in tl.fieldnames})
                tl_file.flush()
            except Exception:
                pass
            av = s.get("available_physical_mb")
            if av is not None and (samples["min_avail"] is None or av < samples["min_avail"]):
                samples["min_avail"] = av
            if s.get("server_working_set_mb"):
                samples["max_ws"] = max(samples["max_ws"], s["server_working_set_mb"])
            if s.get("server_peak_working_set_mb"):
                samples["peak"] = max(samples["peak"], s["server_peak_working_set_mb"])
            time.sleep(args.interval)

    client = mph.start(cores=1, port=PORT)
    time.sleep(3)
    state["pid"] = server_pid()
    print("server pid =", state["pid"], "| port open =", port_open(), flush=True)
    th = threading.Thread(target=sampler, daemon=True)
    th.start()

    res: dict = {"run_id": args.run_id, "model": str(MODEL), "x_scale": X, "N_w_te1": N1,
                 "freqs_MHz": list(FREQS), "sampling_interval_s": args.interval,
                 "server_pid": state["pid"], "model_sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest(),
                 "script_sha256": hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()}
    rows = []
    try:
        model = client.load(str(MODEL))
        java = model.java
        comp = java.modelNode("comp1")
        geom, mesh = comp.geom("geom1"), comp.mesh("mesh1")
        for tag in ("param", "param2"):
            try:
                java.study("std1").feature(tag).active(False)
            except Exception:
                pass
        java.study("std1").feature("freq").set("plist", " ".join(f + "[MHz]" for f in FREQS))
        java.param().set("x_scale", f"{X:g}")
        java.param().set("N_w_te1", str(N1))
        state["stage"] = "geometry"
        t0 = time.perf_counter()
        geom.run()
        tg = round(time.perf_counter() - t0, 1)
        state["stage"] = "mesh"
        t1 = time.perf_counter()
        mesh.run()
        tm = round(time.perf_counter() - t1, 1)
        try:
            nel = int(mesh.getNumElem())
        except Exception:
            nel = None
        state["stage"] = "solve"
        t2 = time.perf_counter()
        java.study("std1").run()
        ts = round(time.perf_counter() - t2, 1)
        state["stage"] = "postprocess"

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
            vo, vi, vr = cx("ave_outer(V)", i), cx("ave_inner(V)", i), cx("ave_ref(V)", i)
            ii, io = cx("intop3(es.JZ)", i), cx("intop4(es.JZ)", i)
            rows.append({"x_scale": X, "N_w_te1": N1, "freq_MHz": (fhz / 1e6) if fhz else None,
                         "Ptot_W": cx("Ptot", i)[0], "Vave_mps": cx("Vave", i)[0],
                         "V_center_re": cx("V_center", i)[0], "V_center_im": cx("V_center", i)[1],
                         "V_outer_re": vo[0], "V_inner_re": vi[0], "V_ref_abs":
                             None if vr[0] is None else abs(complex(*vr)),
                         "Vdiff_abs": (abs(complex(*vo) - complex(*vi))
                                       if vo[0] is not None and vi[0] is not None else None),
                         "I_inner_abs": None if ii[0] is None else abs(complex(*ii)),
                         "I_outer_abs": None if io[0] is None else abs(complex(*io)),
                         "mesh_element_count": nel, "geometry_seconds": tg, "mesh_seconds": tm,
                         "solve_seconds": ts})
        res.update({"geometry_seconds": tg, "mesh_seconds": tm, "solve_seconds": ts,
                    "mesh_element_count": nel, "rows_written": len(rows)})
        print(f"OK 7 freq: geom {tg}s mesh {tm}s solve {ts}s elems={nel}", flush=True)
    finally:
        state["stage"] = "cleanup"
        try:
            client.clear()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass
        closed = False
        for _ in range(30):
            if not port_open():
                closed = True
                break
            time.sleep(1)
        state["stage"] = "closed"
        time.sleep(args.interval * 1.2)
        state["stop"] = True
        th.join(timeout=10)
        tl_file.close()
        after = system_mem()
        res.update({"port_closed_within_30s": closed, "port_open_at_end": port_open(),
                    "min_available_physical_mb": samples["min_avail"],
                    "max_server_working_set_mb": samples["max_ws"],
                    "peak_server_ws_mb": samples["peak"],
                    "system_memory_after_shutdown": after,
                    "resource_timeline": str(tl_path)})
        with (run_dir / "lt2r0_rows.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            if rows:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        (run_dir / "lt2r0_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")
        print("RESULT:", json.dumps({k: res[k] for k in
                                     ("rows_written", "peak_server_ws_mb",
                                      "max_server_working_set_mb", "min_available_physical_mb",
                                      "port_closed_within_30s", "system_memory_after_shutdown")},
                                    ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    import os as _os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(code)
