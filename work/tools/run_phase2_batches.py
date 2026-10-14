"""按 Codex 裁决 §2 执行二级预检的 4 个批次，并逐批做 §2.2 的快速验收。

每批 = 2 个 x_scale × 8 个 N_w_te1 = 16 组合；每批独立 run-id、独立 server 生命周期
（脚本自身在端口空闲时启动 server，进程退出后 server 随之结束）。

用法：python work\\tools\\run_phase2_batches.py
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
PY = REPO / "work" / ".venv" / "Scripts" / "python.exe"
SCRIPT = REPO / "scripts" / "geometry_selection_precheck.py"
MODEL = Path(r"C:\Users\zmx\Desktop\b_GE_task3_2new.mph")
LOGS = REPO / "work" / "logs"
RUNS = REPO / "work" / "runs"

# 顺序按裁决 §5.1：x=0.6 已在 pilot 完成，不重复
BATCHES = [
    ("precheck-b2-phase2-v5-x040-045", "0.4:0.05:0.45"),
    ("precheck-b2-phase2-v5-x050-055", "0.5:0.05:0.55"),
    ("precheck-b2-phase2-v5-x065-070", "0.65:0.05:0.7"),
    ("precheck-b2-phase2-v5-x075-080", "0.75:0.05:0.8"),
]


def port_open(p: int = 2036) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", p), timeout=1.5):
            return True
    except OSError:
        return False


def acceptance(run_id: str) -> dict:
    """§2.2 的快速验收。"""
    d = json.loads((RUNS / run_id / "geometry_selection_precheck.json").read_text(encoding="utf-8"))
    rows = d.get("rows", [])
    keys = [(r["x_scale"], r["N_w_te1"]) for r in rows]
    ck = RUNS / run_id / "checkpoint.jsonl"
    ck_lines = len(ck.read_text(encoding="utf-8").splitlines()) if ck.is_file() else 0
    out = {
        "expected_combos": 16,
        "unique_combos": len(set(keys)),
        "geometry_ok": sum(1 for r in rows if r.get("geometry_status") == "ok"),
        "mesh_ok": sum(1 for r in rows if r.get("mesh_status") == "ok"),
        "selection_verified": sum(1 for r in rows if r.get("selection_status") == "verified"),
        "area_valid_geometry": sum(1 for r in rows if r.get("area_status") == "valid_geometry"),
        "checkpoint_lines": ck_lines,
        "duplicate_keys": len(keys) - len(set(keys)),
        "server_residual": bool(subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process comsolmphserver -ErrorAction SilentlyContinue | Measure-Object).Count"],
            capture_output=True, text=True, timeout=30).stdout.strip() not in ("0", "")),
        "port_2036_open": port_open(),
        "wall_seconds": d.get("wall_seconds"),
        "mesh_elements": [r.get("mesh_element_count") for r in rows],
        "intop5_eq_swr1_all": all(r.get("intop5_eq_swr1") for r in rows),
        "intop5_eq_efc1_all": all(r.get("intop5_eq_efc1") for r in rows),
        "server_memory": d.get("server_memory"),
    }
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    LOGS.mkdir(parents=True, exist_ok=True)
    results = {}
    for label, xs in BATCHES:
        log = LOGS / f"phase2-{label}.log"
        print(f"\n=== 批次 {label}（x={xs}）===", flush=True)
        t0 = time.perf_counter()
        with log.open("w", encoding="utf-8") as fh:          # 直接重定向到文件，不走管道
            code = subprocess.run([str(PY), str(SCRIPT), "--model", str(MODEL), "--phase", "both",
                                   "--xs", xs, "--n1", "1:1:8", "--mesh-max-n1", "8",
                                   "--run-id", label, "--device", "ge-task3-phase2"],
                                  stdout=fh, stderr=subprocess.STDOUT, cwd=str(REPO)).returncode
        dt = round(time.perf_counter() - t0, 1)
        print(f"  exit={code}｜本批墙钟 {dt} s", flush=True)
        if code != 0:
            print(f"  [FAIL] 批次退出码非 0，日志 {log}", flush=True)
            results[label] = {"exit": code}
            continue
        acc = acceptance(label)
        results[label] = {"exit": code, "wall_batch_s": dt, **acc}
        print(f"  组合 {acc['unique_combos']}/{acc['expected_combos']}｜"
              f"geometry_ok={acc['geometry_ok']}｜mesh_ok={acc['mesh_ok']}｜"
              f"selection_verified={acc['selection_verified']}｜"
              f"area_valid={acc['area_valid_geometry']}｜checkpoint={acc['checkpoint_lines']}｜"
              f"dup={acc['duplicate_keys']}｜server残留={acc['server_residual']}｜"
              f"端口开放={acc['port_2036_open']}｜"
              f"intop5==swr1/efc1={acc['intop5_eq_swr1_all']}/{acc['intop5_eq_efc1_all']}", flush=True)
        el = [e for e in acc["mesh_elements"] if isinstance(e, int)]
        if el:
            print(f"  单元数 min={min(el)} max={max(el)}；"
                  f"server 内存 {acc['server_memory']}", flush=True)
    (LOGS / "phase2-batches-summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n落档：{LOGS / 'phase2-batches-summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
