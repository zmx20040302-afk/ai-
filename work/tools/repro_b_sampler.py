"""B 的定向复现器（测试侧，**不改被测物**，因此无需 freeze）。

背景：冻结版 sampler 单独跑 40/40 干净，但套件里 T2 出现 1 次 `rc=2`（异常出口）。
本器精确复制 T2 相对"直接调用"的**两个差异条件**，并循环 60–100 次，捕获 stderr：

  条件①：先写 `worker_state.json`（T2 用 ensure_worker_state；直接调用时该文件不存在）
  条件②：同目录/同 namespace 内维持**其它文件与子进程活动**（模拟套件侧并发）

记录：每轮 rc、jsonl 行数、stderr 字节与完整内容；rc!=0 时把现场原样留档。
**注意**：本器只服务"拿到 traceback"，**不作 B 的证明或反证**。

用法：python work/tools/repro_b_sampler.py --sampler <abs> --out <abs> [--n 80]
退出码：0 = 全轮 rc==0；2 = 出现过 rc!=0（现场已留档）
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

PY = sys.executable
FIXED_TS = "2026-09-14T04:00:00"


def write_worker_state(d: Path) -> None:
    """条件①：与 tests_lt2_supervisor.ensure_worker_state 同构（worker 单写者文件）。"""
    payload = {"writer": "lt2_combo_worker", "pid": None, "server_identity": None,
               "stage": "solve", "combo": "(0.7,5)", "stop": False,
               "cancel_requested": False, "updated_at": FIXED_TS}
    tmp = d / "worker_state.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(d / "worker_state.json")


READ_STATS: dict = {}


def noise_thread(d: Path, stop: threading.Event) -> None:
    """条件②③：同目录内的其它文件写入活动 **+ 持续读取 state 文件**。

    条件③ 的依据（**假设，须由 traceback 判定**）：套件/supervisor 会在 sampler 写
    `sampler_state.json` 的同时反复读它；Windows 上 `os.replace` 覆盖一个正被其它进程
    打开读取的文件可能抛共享冲突。本器用读取线程复刻该并发，写入计数供报告引用。
    """
    i = 0
    while not stop.is_set():
        i += 1
        try:
            (d / f"noise_{threading.get_ident()}_{i}.tmp").write_text("x" * 200, encoding="utf-8")
            (d / f"noise_{threading.get_ident()}_{i}.tmp").replace(
                d / f"noise_{threading.get_ident()}_{i}.log")
        except OSError:
            pass
        for name in ("sampler_state.json", "worker_state.json"):
            try:
                (d / name).read_bytes()
                READ_STATS["reads"] = READ_STATS.get("reads", 0) + 1
            except OSError as exc:
                READ_STATS["oserror"] = f"{type(exc).__name__}: {exc}"
        time.sleep(0.01)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--sampler", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--noise", type=int, default=3, help="并发噪声线程数（0=关闭条件②）")
    ap.add_argument("--no-worker-state", action="store_true", help="关闭条件①")
    args = ap.parse_args(argv)

    sampler = Path(args.sampler)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, bad = [], []
    for i in range(1, args.n + 1):
        d = out / f"r_{i:03d}"
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
        if not args.no_worker_state:
            write_worker_state(d)                      # 条件①
        stop = threading.Event()
        ths = [threading.Thread(target=noise_thread, args=(d, stop), daemon=True)
               for _ in range(args.noise)]             # 条件②
        for t in ths:
            t.start()
        try:
            p = subprocess.run([PY, "-B", "-X", "utf8", str(sampler),
                                "--run-id", f"reproB-{i}", "--state-dir", str(d),
                                "--simulate", "8", "--fixed-timestamps"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=120)
            rc, err, so = p.returncode, p.stderr or "", p.stdout or ""
        except Exception as exc:  # noqa: BLE001
            rc, err, so = -999, f"{type(exc).__name__}: {exc}", ""
        finally:
            stop.set()
            for t in ths:
                t.join(timeout=2)
        jl = d / "resource_timeline.jsonl"
        lines = len([l for l in jl.read_text(encoding="utf-8").splitlines() if l.strip()]) \
            if jl.is_file() else 0
        (d / "sampler_stderr.log").write_text(err, encoding="utf-8")
        (d / "sampler_stdout.log").write_text(so, encoding="utf-8")
        rec = {"i": i, "rc": rc, "jsonl_lines": lines,
               "stderr_bytes": len(err.encode("utf-8")), "stdout_bytes": len(so.encode("utf-8"))}
        rows.append(rec)
        if rc != 0 or lines != 8:
            bad.append({**rec, "stderr": err[-4000:], "dir": str(d)})
            print(f"  ** r_{i:03d} rc={rc} lines={lines} stderr_bytes={rec['stderr_bytes']}",
                  flush=True)
            if err:
                print("     --- stderr ---", flush=True)
                for l in err.strip().splitlines()[-12:]:
                    print("     " + l, flush=True)

    summary = {"n": args.n, "conditions": {"worker_state_present": not args.no_worker_state,
                                           "noise_threads": args.noise},
               "rc_histogram": {str(r["rc"]): sum(1 for x in rows if x["rc"] == r["rc"])
                                for r in rows},
               "bad_count": len(bad), "bad": bad, "rows": rows,
               "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "note": "仅用于拿到 traceback；不作 B 的证明或反证"}
    (out / "repro_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print(f"\n复现器完成：n={args.n} 异常轮={len(bad)} rc分布={summary['rc_histogram']}", flush=True)
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
