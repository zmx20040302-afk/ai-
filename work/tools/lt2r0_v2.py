"""LT2-R0 v2：修正后的单组合资源校准（Codex 审核 §5/§6）。

相对 v1 的修复：
  1) 时序键名映射修正（system_available_physical_mb / system_memory_load_percent 不再为空）；
  2) 增加 solve 阶段断言：两列任一为空 → 该次校准 FAIL；
  3) 增加 **commit 软/硬停止线**，并在越线时写事件（不静默继续）；
  4) 电气电流列一律留空 + 排除标志；
  5) **独立 sidecar 监控进程**（本文件以 `--role sampler` 自行启动），主进程结束时校验
     "无 >15 s 采样空档"，以及 sidecar 是否正常退出；
  6) 启动前置门禁：端口空闲 / 无其他 server / 可用物理 ≥16384 MB / commit 可用 ≥8192 MB。

用法：
  主：python work/tools/lt2r0_v2.py --run-id lt2-resource-calibration-x080-n02-v2
  （sidecar 由主进程自动启动，无需手工调用）
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import csv
import hashlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
MODELS = REPO / "work" / "models"
RUNS = REPO / "work" / "runs"
MODEL = MODELS / "b_GE_task3_2new_reverse_voltage_drive_v1.mph"
PORT = 2036
FREQS = ("5", "10", "15", "20", "25", "30", "35")
X, N1 = 0.8, 2
SOFT_WS, HARD_WS = 10240, 12288
SOFT_AVAIL, HARD_AVAIL = 8192, 4096
SOFT_COMMIT, HARD_COMMIT = 4096, 1024
GAP_LIMIT = 15.0


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

COLS = ["timestamp", "elapsed_s", "server_pid", "server_working_set_mb",
        "server_peak_working_set_mb", "system_available_physical_mb",
        "system_memory_load_percent", "commit_available_mb",
        "current_combo", "current_stage"]


def sysmem() -> dict:
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return {"system_available_physical_mb": round(m.ullAvailPhys / 1048576, 1),
            "system_memory_load_percent": int(m.dwMemoryLoad),
            "commit_available_mb": round(m.ullAvailPageFile / 1048576, 1)}


def procmem(pid: int) -> dict:
    if not pid:
        return {}
    h = ctypes.windll.kernel32.OpenProcess(0x0410, False, pid)
    if not h:
        return {}
    try:
        c = PMC()
        c.cb = ctypes.sizeof(c)
        ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
        return {"server_working_set_mb": round(c.WorkingSetSize / 1048576, 1),
                "server_peak_working_set_mb": round(c.PeakWorkingSetSize / 1048576, 1)}
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def find_pid() -> int | None:
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


def run_sampler(run_id: str, interval: float) -> int:
    """sidecar：独立进程采样，读 state.json，追加写 timeline。"""
    rd = RUNS / run_id
    state_f = rd / "sampler_state.json"
    tl_path = rd / "resource_timeline.csv"
    new = not tl_path.is_file()
    fh = tl_path.open("a", newline="", encoding="utf-8-sig")
    w = csv.DictWriter(fh, fieldnames=COLS)
    if new:
        w.writeheader()
        fh.flush()
    t0 = time.perf_counter()
    while True:
        try:
            st = json.loads(state_f.read_text(encoding="utf-8"))
        except Exception:
            st = {}
        if st.get("stop"):
            break
        s = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "elapsed_s": round(time.perf_counter() - t0, 1),
             "server_pid": st.get("pid"), "current_combo": st.get("combo"),
             "current_stage": st.get("stage")}
        s.update(procmem(st.get("pid") or 0))
        s.update(sysmem())
        w.writerow({k: s.get(k) for k in COLS})
        fh.flush()
        time.sleep(interval)
    fh.close()
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="lt2-resource-calibration-x080-n02-v2")
    ap.add_argument("--role", choices=["main", "sampler"], default="main")
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()
    if args.role == "sampler":
        return run_sampler(args.run_id, args.interval)

    import numpy as np
    import mph

    rd = RUNS / args.run_id
    rd.mkdir(parents=True, exist_ok=True)
    state_f = rd / "sampler_state.json"
    tl_path = rd / "resource_timeline.csv"
    pre = {"port_free": not port_open(), "other_server": find_pid(), **sysmem()}
    gate = (pre["port_free"] and pre["other_server"] is None
            and pre["system_available_physical_mb"] >= 16384
            and pre["commit_available_mb"] >= 8192)
    print("preflight:", json.dumps(pre, ensure_ascii=False), "| gate_pass =", gate, flush=True)
    if not gate:
        (rd / "preflight_failed.json").write_text(json.dumps(pre, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
        print("[STOP] 前置门禁未通过（按审核 §6 拒绝启动）", flush=True)
        return 5

    state_f.write_text(json.dumps({"pid": None, "combo": f"({X},{N1})", "stage": "startup",
                                   "stop": False}), encoding="utf-8")
    sampler = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                "--role", "sampler", "--run-id", args.run_id,
                                "--interval", str(args.interval)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = mph.start(cores=1, port=PORT)
    time.sleep(3)
    pid = find_pid()

    def setstate(**kw):
        st = json.loads(state_f.read_text(encoding="utf-8"))
        st.update(kw)
        state_f.write_text(json.dumps(st), encoding="utf-8")

    setstate(pid=pid)
    print("server pid =", pid, flush=True)
    events, rows = [], []
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
        setstate(stage="geometry")
        geom.run()
        setstate(stage="mesh")
        mesh.run()
        try:
            nel = int(mesh.getNumElem())
        except Exception:
            nel = None
        setstate(stage="solve")
        t0 = time.perf_counter()
        java.study("std1").run()
        solve_s = round(time.perf_counter() - t0, 1)
        setstate(stage="postprocess")

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
            rows.append({"x_scale": X, "N_w_te1": N1, "freq_MHz": (fhz / 1e6) if fhz else None,
                         "Ptot_W": cx("Ptot", i)[0], "Vave_mps": cx("Vave", i)[0],
                         "Ptot_norm": None, "Vave_norm": None,
                         "V_center_re": cx("V_center", i)[0], "V_center_im": cx("V_center", i)[1],
                         "V_outer_re": vo[0], "V_inner_re": vi[0],
                         "V_ref_abs": None if vr[0] is None else abs(complex(*vr)),
                         "Vdiff_abs": (abs(complex(*vo) - complex(*vi))
                                       if vo[0] is not None and vi[0] is not None else None),
                         "I_inner_abs": "", "I_outer_abs": "",
                         "electrical_current_metrics_excluded": "true",
                         "electrical_current_exclusion_reason": "LT0_C_KCL_relative_gt_1pct",
                         "mesh_element_count": nel, "solve_seconds": solve_s,
                         "geometry_status": "ok", "mesh_status": "ok",
                         "solve_status": "ok" if cx("Ptot", i)[0] is not None else "failed"})
        for r in rows:
            vd = r.get("Vdiff_abs")
            if vd and r["Ptot_W"] is not None:
                r["Ptot_norm"] = r["Ptot_W"] / (float(vd) ** 2)
                r["Vave_norm"] = r["Vave_mps"] / float(vd)
    finally:
        setstate(stage="cleanup")
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
        setstate(stage="closed", stop=True)
        try:
            sampler.wait(timeout=20)
            sampler_rc = sampler.returncode
        except Exception:
            sampler.kill()
            sampler_rc = "killed"

        tl = list(csv.DictReader(tl_path.open(encoding="utf-8-sig")))
        gaps = []
        for a, b in zip(tl, tl[1:]):
            d = (__import__("datetime").datetime.fromisoformat(b["timestamp"])
                 - __import__("datetime").datetime.fromisoformat(a["timestamp"])).total_seconds()
            if d > GAP_LIMIT:
                gaps.append({"from": a["timestamp"], "to": b["timestamp"], "gap_s": d})
        solve_samples = [r for r in tl if r.get("current_stage") == "solve"]
        missing_cols = [c for c in ("system_available_physical_mb", "system_memory_load_percent",
                                    "commit_available_mb")
                        if any(not r.get(c) for r in solve_samples)]
        av = [float(r["system_available_physical_mb"]) for r in tl
              if r.get("system_available_physical_mb")]
        cm = [float(r["commit_available_mb"]) for r in tl if r.get("commit_available_mb")]
        ws = [float(r["server_working_set_mb"]) for r in tl if r.get("server_working_set_mb")]
        pk = [float(r["server_peak_working_set_mb"]) for r in tl if r.get("server_peak_working_set_mb")]
        for i, r in enumerate(tl):
            if r.get("server_working_set_mb") and float(r["server_working_set_mb"]) >= HARD_WS:
                events.append({"t": r["timestamp"], "kind": "hard_stop_ws"})
            elif r.get("server_working_set_mb") and float(r["server_working_set_mb"]) >= SOFT_WS:
                events.append({"t": r["timestamp"], "kind": "soft_stop_ws"})
            if r.get("commit_available_mb") and float(r["commit_available_mb"]) <= HARD_COMMIT:
                events.append({"t": r["timestamp"], "kind": "hard_stop_commit"})
            elif r.get("commit_available_mb") and float(r["commit_available_mb"]) <= SOFT_COMMIT:
                events.append({"t": r["timestamp"], "kind": "soft_stop_commit"})
            if r.get("system_available_physical_mb") and float(r["system_available_physical_mb"]) <= HARD_AVAIL:
                events.append({"t": r["timestamp"], "kind": "hard_stop_avail"})
            elif r.get("system_available_physical_mb") and float(r["system_available_physical_mb"]) <= SOFT_AVAIL:
                events.append({"t": r["timestamp"], "kind": "soft_stop_avail"})

        res = {"run_id": args.run_id, "role": "v2", "x_scale": X, "N_w_te1": N1,
               "freqs_MHz": list(FREQS), "server_pid": pid,
               "model_sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest(),
               "script_sha256": hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest(),
               "preflight": pre, "preflight_gate_pass": gate,
               "sampler_returncode": sampler_rc, "timeline_rows": len(tl),
               "timeline_gaps_over_15s": gaps,
               "solve_stage_missing_system_columns": missing_cols,
               "monitoring_ok": (not gaps) and (not missing_cols) and sampler_rc == 0,
               "server_ws_mb": {"min": min(ws) if ws else None, "max": max(ws) if ws else None},
               "server_peak_ws_mb": max(pk) if pk else None,
               "system_available_physical_mb": {"min": min(av) if av else None},
               "commit_available_mb": {"min": min(cm) if cm else None, "max": max(cm) if cm else None},
               "stop_line_events": events[:40], "stop_line_event_count": len(events),
               "port_closed_within_30s": closed, "port_open_at_end": port_open(),
               "rows_written": len(rows), "solve_seconds": solve_s, "mesh_element_count": nel}
        res["pass_conditions"] = {
            "frequency_rows_7": len(rows) == 7,
            "failed_frequency_points_0": all(r["solve_status"] == "ok" for r in rows),
            "drive_voltage_mismatch_0": all(abs(abs(float(r["Vdiff_abs"] or 0)) - 2.0) < 1e-6
                                            for r in rows if r["Vdiff_abs"]),
            "monitoring_ok": res["monitoring_ok"],
            "peak_ws_lt_12288": (res["server_peak_ws_mb"] or 0) < HARD_WS,
            "min_avail_ge_4096": (min(av) if av else 0) >= HARD_AVAIL,
            "server_cleanup_ok": closed and not port_open(),
        }
        res["R0_v2_status"] = "PASS" if all(res["pass_conditions"].values()) else "FAIL_OR_LIMITED"
        with (rd / "lt2r0_rows.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            if rows:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        (rd / "lt2r0_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str),
                                              encoding="utf-8")
        print("RESULT:", json.dumps({k: res[k] for k in
                                     ("timeline_rows", "monitoring_ok", "sampler_returncode",
                                      "server_peak_ws_mb", "commit_available_mb",
                                      "system_available_physical_mb", "stop_line_event_count",
                                      "R0_v2_status")}, ensure_ascii=False), flush=True)
        print("pass_conditions:", json.dumps(res["pass_conditions"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    import os as _os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(code)
