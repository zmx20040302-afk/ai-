"""LT2 sidecar 采样器（独立进程，运行期实时判定）—— v2（Codex §7.2 / §7.3 修复）

v2 相对 v1 的改动
-----------------
1. **目录隔离（P0-2）**：产物写入 `--state-dir` 指定的 child/attempt 目录
   （`<run_id>/child_00_attempt_1/`），不再写 run 根目录，**绝不删除或覆盖任何既有证据**。
2. **状态文件拆分（P1-a）**：本进程是 `sampler_state.json` 的**唯一写入者**。
   控制通道（pid / stage / combo / stop / cancel_requested）在 `worker_state.json` 里，
   由 worker 独占写入、本进程**只读**。
   ⇒ 两个文件各自单写者，**不存在跨进程读-改-写竞争**（v1 的 `merge_state` 已移除）。
   注意：`atomic_write_json` 只能避免半写文件，**不能让并发读-改-写变安全**；
   v1 把两者混为一谈是错的，这里用「单写者」从根上消除竞争。

产物（全部在 `--state-dir` 下）
------------------------------
- `resource_timeline.jsonl` —— **完整**事件流，一行一样本（不截断）
- `resource_timeline.csv`   —— 人读用，列名与 R0 的 `COLS` 一致
- `sampler_state.json`      —— 本进程独占写：`last_sample_ts`(epoch 秒)、`sample_index`、
  `verdict`、`reasons`、`warnings`、`counters`、`worker_stop_seen` 等

退出码：0 = 收到 worker 的 `stop=true` 或模拟轮次结束；2 = 循环内异常（外层可检出）

用法
----
真实（由 worker 进程自动拉起）：
    python work/tools/lt2_sampler.py --run-id <run_id> --state-dir <abs child dir> --interval 5
自检（不启动 COMSOL）：
    python work/tools/lt2_sampler.py --run-id <run_id> --simulate 12 --simulate-dir dryrun
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rt_gate import (  # noqa: E402  纯逻辑门禁，复用不重写
    GateEngine,
    Thresholds,
    atomic_write_json,
    read_json_safe,
)

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
RUNS = REPO / "work" / "runs"

# 与 R0 完全一致的列名（人读 CSV 保持兼容）
COLS = ["timestamp", "elapsed_s", "server_pid", "server_working_set_mb",
        "server_peak_working_set_mb", "system_available_physical_mb",
        "system_memory_load_percent", "commit_available_mb",
        "current_combo", "current_stage"]

WORKER_STATE_NAME = "worker_state.json"


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def sysmem() -> dict:
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return {"system_available_physical_mb": round(m.ullAvailPhys / 1048576, 1),
            "system_memory_load_percent": int(m.dwMemoryLoad),
            "commit_available_mb": round(m.ullAvailPageFile / 1048576, 1)}


def procmem(pid: int) -> dict:
    """目标进程 WS / Peak WS。

    `PeakWorkingSetSize` **单调不减**，只作审计；rt_gate 的 ws 硬线用实时 `WorkingSetSize`。
    """
    if not pid:
        return {}
    h = ctypes.windll.kernel32.OpenProcess(0x0410, False, int(pid))
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


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# 确定性模式的固定基准时刻（**只用于自测/证据复算**，真实运行不使用）。
# 取值本身无物理含义，只需固定；对应 2026-09-14T04:00:00Z。
FIXED_BASE_TS = 1789358400.0


def fixed_iso(base_ts: float, n: int, interval: float) -> str:
    """由固定基准派生的时间戳（用 gmtime ⇒ 与本地时区无关）。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(base_ts + n * interval))


def build_sample(worker: dict, t0: float, simulated: bool,
                 override: dict | None = None,
                 ts: str | None = None, elapsed: float | None = None) -> dict:
    """采一个样本。pid/stage/combo 一律来自 `worker_state.json`（控制通道）。

    `ts` / `elapsed` 由调用方注入时（确定性模式）**不使用墙钟** ⇒ 产物逐字节可复算。
    """
    s: dict = {"timestamp": ts if ts is not None else now_iso(),
               "elapsed_s": (elapsed if elapsed is not None
                             else round(time.perf_counter() - t0, 1)),
               "server_pid": worker.get("pid"),
               "current_combo": worker.get("combo"),
               "current_stage": worker.get("stage")}
    if simulated:
        s.update(override or {})
    else:
        s.update(procmem(worker.get("pid") or 0))
        s.update(sysmem())
    return s


def run_sampler(state_dir: Path, interval: float, simulated: int, th: Thresholds,
                fixed_base_ts: float | None = None,
                drill: bool = False, drill_meta: dict | None = None,
                simulate_profile: str = "default") -> int:
    state_dir.mkdir(parents=True, exist_ok=True)
    worker_f = state_dir / WORKER_STATE_NAME
    sampler_f = state_dir / "sampler_state.json"
    jsonl_f = state_dir / "resource_timeline.jsonl"
    csv_f = state_dir / "resource_timeline.csv"

    engine = GateEngine(th=th)
    t0 = time.perf_counter()

    new_csv = not csv_f.is_file()
    csv_fh = csv_f.open("a", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(csv_fh, fieldnames=COLS, extrasaction="ignore")
    if new_csv:
        writer.writeheader()
        csv_fh.flush()
    jsonl_fh = jsonl_f.open("a", encoding="utf-8")

    # 模拟脚本（三种剖面）：
    #   default —— 会越过 commit 硬线（用于验证越线判定）
    #   safe    —— 所有值都在裁定阈值的安全侧（用于"正常链路"冒烟，不得触发任何硬线）
    #   ramp_ws —— 启动阶段低、进入 solve 后才升高（演练用：压低 ws 阈值后才会触发）
    sim_profiles = {
        "default": [
            {"system_available_physical_mb": 16000.0, "system_memory_load_percent": 48,
             "commit_available_mb": 11000.0, "server_working_set_mb": 1200.0,
             "server_peak_working_set_mb": 1200.0, "current_stage": "startup"},
            {"system_available_physical_mb": 9000.0, "system_memory_load_percent": 72,
             "commit_available_mb": 5000.0, "server_working_set_mb": 9000.0,
             "server_peak_working_set_mb": 9000.0, "current_stage": "solve"},
            {"system_available_physical_mb": 7000.0, "system_memory_load_percent": 80,
             "commit_available_mb": 3000.0, "server_working_set_mb": 11000.0,
             "server_peak_working_set_mb": 11000.0, "current_stage": "solve"},
            {"system_available_physical_mb": 6000.0, "system_memory_load_percent": 84,
             "commit_available_mb": 2000.0, "server_working_set_mb": 11900.0,
             "server_peak_working_set_mb": 11900.0, "current_stage": "solve"},
        ],
        "safe": [
            {"system_available_physical_mb": 16000.0, "system_memory_load_percent": 45,
             "commit_available_mb": 12000.0, "server_working_set_mb": 1200.0,
             "server_peak_working_set_mb": 1200.0, "current_stage": "startup"},
            {"system_available_physical_mb": 15500.0, "system_memory_load_percent": 48,
             "commit_available_mb": 11800.0, "server_working_set_mb": 4000.0,
             "server_peak_working_set_mb": 4000.0, "current_stage": "solve"},
        ],
        "ramp_ws": [
            {"system_available_physical_mb": 16000.0, "system_memory_load_percent": 45,
             "commit_available_mb": 12000.0, "server_working_set_mb": 1200.0,
             "server_peak_working_set_mb": 1200.0, "current_stage": "startup"},
            {"system_available_physical_mb": 15000.0, "system_memory_load_percent": 52,
             "commit_available_mb": 11500.0, "server_working_set_mb": 6500.0,
             "server_peak_working_set_mb": 6500.0, "current_stage": "solve"},
        ],
    }
    sim_script = sim_profiles.get(simulate_profile, sim_profiles["default"])

    try:
        n = 0
        while True:
            worker = read_json_safe(worker_f)
            stop_seen = bool(worker.get("stop"))
            if stop_seen:
                break
            fixed = fixed_base_ts is not None
            if fixed:
                ts = fixed_iso(fixed_base_ts, n, interval)
                elapsed = round(n * interval, 1)
                now_val: float | None = fixed_base_ts + n * interval
            else:
                ts = None
                elapsed = None
                now_val = None
            if simulated:
                if n >= simulated:
                    break
                s = build_sample(worker, t0, True,
                                 dict(sim_script[min(n, len(sim_script) - 1)]),
                                 ts=ts, elapsed=elapsed)
            else:
                s = build_sample(worker, t0, False, ts=ts, elapsed=elapsed)
            v = engine.evaluate(s, now=now_val)   # ← 运行期实时判定
            s.update({"sample_index": engine.n_samples, "verdict": v["verdict"],
                      "reasons": v["reasons"], "warnings": v["warnings"],
                      "counters": v["counters"], "gap_s": v.get("gap_s"),
                      "simulated": bool(simulated),
                      "drill": bool(drill),
                      "drill_thresholds": (drill_meta or {}).get("overrides") if drill else None,
                      "drill_note": (drill_meta or {}).get("note") if drill else None})
            jsonl_fh.write(json.dumps(s, ensure_ascii=False) + "\n")
            jsonl_fh.flush()
            writer.writerow({k: s.get(k) for k in COLS})
            csv_fh.flush()
            # 本进程是 sampler_state.json 的唯一写入者 → 无跨进程竞争
            w = atomic_write_json(sampler_f, {
                "writer": "lt2_sampler",
                "updated_at": ts if fixed else now_iso(),
                "last_sample_ts": round(now_val if fixed else time.time(), 3),
                "sample_index": engine.n_samples,
                "pid": worker.get("pid"), "combo": worker.get("combo"),
                "stage": worker.get("stage"),
                "verdict": v["verdict"], "reasons": v["reasons"], "warnings": v["warnings"],
                "counters": v["counters"], "gap_s": v.get("gap_s"),
                "worker_stop_seen": stop_seen,
                "simulated": bool(simulated),
                "drill": bool(drill),
                "drill_thresholds": (drill_meta or {}).get("overrides") if drill else None,
                "drill_note": (drill_meta or {}).get("note") if drill else None,
                "thresholds_effective": th.to_dict(),
                "clock_mode": "fixed" if fixed else "wallclock"})
            if not w.get("ok"):
                raise RuntimeError(f"sampler_state 原子写失败: {w.get('error')}")
            n += 1
            if simulated:
                continue
            time.sleep(interval)
        return 0
    finally:
        jsonl_fh.close()
        csv_fh.close()


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="LT2 sidecar 采样器（运行期实时门禁判定）")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--state-dir", default=None,
                    help="产物目录（child/attempt 隔离目录，绝对路径优先）")
    ap.add_argument("--simulate-dir", default="",
                    help="兼容用法：相对 <run_id> 的子目录（仅自检）")
    ap.add_argument("--interval", type=float, default=5.0, help="采样间隔秒（裁定 5 s）")
    ap.add_argument("--simulate", type=int, default=0,
                    help=">0 时生成 N 个模拟样本（不启动 COMSOL），用于自检")
    ap.add_argument("--simulate-profile", default="default",
                    choices=["default", "safe", "ramp_ws"],
                    help="模拟剖面：default 会越线；safe 全程在安全侧；ramp_ws 进入 solve 后才升高")
    ap.add_argument("--fixed-timestamps", action="store_true",
                    help="确定性时钟：时间戳/elapsed 由固定基准派生 ⇒ 同命令两次运行产物逐字节一致"
                         "（**仅供自测与证据复算**，真实运行不要用）")
    ap.add_argument("--drill", action="store_true",
                    help="演练模式标记：产物带 drill 字段（阈值覆盖由 production CLI 负责裁定）")
    ap.add_argument("--ws-hard-stop-mb", type=float, default=None)
    ap.add_argument("--commit-hard-stop-mb", type=float, default=None)
    ap.add_argument("--physical-hard-stop-mb", type=float, default=None)
    args = ap.parse_args()

    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        state_dir = RUNS / args.run_id / (args.simulate_dir if args.simulate else "")
    th = Thresholds()  # 默认值 = 裁定值
    # 阈值覆盖**只**在 --drill 下应用；由 production CLI 强制把关（防止误用于生产）
    overrides = {}
    if args.drill:
        for k, v in (("ws_hard_stop_mb", args.ws_hard_stop_mb),
                     ("commit_hard_stop_mb", args.commit_hard_stop_mb),
                     ("physical_avail_hard_stop_mb", args.physical_hard_stop_mb)):
            if v is not None:
                overrides[k] = {"default": getattr(th, k), "drill_value": float(v)}
                setattr(th, k, float(v))
    drill_meta = {"overrides": overrides,
                  "note": ("演练阈值覆盖：本次硬停**不是**真实资源越线，"
                           "禁止用于生产资源判断")} if args.drill else {}
    fixed = FIXED_BASE_TS if args.fixed_timestamps else None
    try:
        return run_sampler(state_dir, args.interval, args.simulate, th,
                           fixed_base_ts=fixed, drill=args.drill, drill_meta=drill_meta,
                           simulate_profile=args.simulate_profile)
    except Exception as exc:  # noqa: BLE001 - 必须让外层可检出
        print(f"[sampler] 异常退出: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
