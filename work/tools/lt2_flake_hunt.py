"""间歇性失败定位器（flake hunter）—— **不靠"多跑几次蒙过去"**。

对 `tests_lt2_supervisor.py` 连续运行 N 次，每次：
  - 完整保存 stdout/stderr 到 `work/runs/lt2-acceptance-flake/run_<NN>.log`（不是只留末行）；
  - 解析 `合计 X 项，通过 Y，失败 Z`；
  - 任一非全绿（rc!=0 或 Z>0）时，把**失败断言原文 + 前后各 20 行**、
    以及当时的**进程/端口/目录现场**全部留档为 `failure_<NN>.json`。

**串行执行**：测试套件会重建 `lt2-supervisor-selftest*` 目录，并发跑只会互相干扰并制造假 flake。
本脚本自己负责清理这些自测根目录，**不触碰** `lt2-resource-confirm-*` 等既有 run。

用法：python work/tools/lt2_flake_hunt.py [N]     （默认 12）
退出码：0 = N 次全绿；2 = 出现过非全绿（已留档）
"""

from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent.parent
RUNS = REPO / "work" / "runs"
# R7 §4.5：每次执行唯一输出目录，禁止复用 lt2-acceptance-flake（旧产物为历史留档）
OUT = RUNS / f"lt2-flake-{time.strftime('%Y%m%d-%H%M%S')}-pid{__import__('os').getpid()}"
TESTS = TOOLS / "tests_lt2_supervisor.py"
PY = sys.executable
SUMMARY_RE = re.compile(r"合计\s*(\d+)\s*项，通过\s*(\d+)，失败\s*(\d+)")


def ps(script: str) -> str:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        return (r.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001
        return f"<error {type(exc).__name__}>"


def clean_selftest() -> list[str]:
    removed = []
    for p in RUNS.glob("lt2-supervisor-selftest*"):
        if p.is_dir() and p.name.startswith("lt2-supervisor-selftest"):
            shutil.rmtree(p, ignore_errors=True)
            removed.append(p.name)
    return removed


def scene() -> dict:
    """失败现场：端口 / COMSOL 进程 / 残留 python 替身 / 自测目录清单。"""
    return {
        "port_2036_listening": ps("(Get-NetTCPConnection -LocalPort 2036 -State Listen "
                                  "-ErrorAction SilentlyContinue).Count"),
        "comsolmphserver": ps("(Get-Process comsolmphserver -ErrorAction SilentlyContinue).Count"),
        "comsolbatch": ps("(Get-Process comsolbatch -ErrorAction SilentlyContinue).Count"),
        "python_sleep_doubles": ps(
            "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*time.sleep*' } | "
            "Select-Object -ExpandProperty ProcessId) -join ','"),
        "selftest_roots": sorted(p.name for p in RUNS.glob("lt2-supervisor-selftest*") if p.is_dir()),
    }


def failed_context(lines: list[str], width: int = 20) -> list[dict]:
    """失败断言原文 + 前后各 width 行。"""
    out = []
    for i, ln in enumerate(lines):
        if ln.startswith("[FAIL]"):
            lo, hi = max(0, i - width), min(len(lines), i + width + 1)
            out.append({"line_no": i + 1, "assertion": ln,
                        "context_before": lines[lo:i],
                        "context_after": lines[i + 1:hi]})
    return out


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    n_runs = int(argv[1]) if len(argv) > 1 else 12
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    results, failures = [], []

    stamp = time.strftime("%H%M%S")
    for i in range(1, n_runs + 1):
        # R7 §4.4/4.5：每轮**唯一 namespace** 并显式传给测试脚本；不再做全局共享目录清理
        ns = f"flake-{stamp}-{i:02d}"
        removed = []
        env = dict(os.environ); env["LT2_TEST_NAMESPACE"] = ns; env.pop("LT2_RUNS_ROOT", None)
        t0 = time.time()
        p = subprocess.run([PY, "-B", "-X", "utf8", str(TESTS), "--namespace", ns],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=1800, env=env)
        dur = round(time.time() - t0, 1)
        log = OUT / f"run_{i:02d}.log"
        lines = (p.stdout or "").splitlines()
        log.write_text(
            "\n".join([f"# cmd: {PY} -X utf8 {TESTS}",
                       f"# run {i}/{n_runs}",
                       f"# started_at: {time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t0))}",
                       f"# seconds: {dur}",
                       f"# returncode: {p.returncode}",
                       f"# cleaned_before: {removed}",
                       "# ---- stdout ----"] + lines
                      + ["# ---- stderr ----"] + (p.stderr or "").splitlines()),
            encoding="utf-8")
        m = SUMMARY_RE.search(p.stdout or "")
        total, npass, nfail = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (None, None, None)
        rec = {"run": i, "returncode": p.returncode, "seconds": dur,
               "total": total, "pass": npass, "fail": nfail, "log": str(log)}
        results.append(rec)
        ok = (p.returncode == 0 and nfail == 0)
        print(f"run {i:02d}: rc={p.returncode} {dur:6.1f}s  "
              f"合计={total} 通过={npass} 失败={nfail} {'OK' if ok else '*** FLAKE ***'}",
              flush=True)
        if not ok:
            f = {"run": i, "returncode": p.returncode, "seconds": dur,
                 "summary": {"total": total, "pass": npass, "fail": nfail},
                 "failed_assertions": failed_context(lines),
                 "scene": scene(),
                 "tail": lines[-25:],
                 "log": str(log)}
            (OUT / f"failure_{i:02d}.json").write_text(
                json.dumps(f, ensure_ascii=False, indent=1), encoding="utf-8")
            failures.append(f)
        # 每次运行后也记录一次现场（便于对比"干净"与"脏"状态）
        (OUT / f"scene_{i:02d}.json").write_text(
            json.dumps(scene(), ensure_ascii=False, indent=1), encoding="utf-8")

    summary = {"started_at": started, "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "n_runs": n_runs, "tests_sha256": __import__("hashlib").sha256(
                   TESTS.read_bytes()).hexdigest(),
               "results": results,
               "flake_count": len(failures),
               "flake_runs": [f["run"] for f in failures],
               "conclusion": ("ALL_GREEN_NO_FLAKE_OBSERVED" if not failures
                              else "FLAKE_OBSERVED")}
    (OUT / "flake_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n=== {n_runs} 次运行：非全绿 {len(failures)} 次 "
          f"{'(runs ' + ','.join(str(x) for x in summary['flake_runs']) + ')' if failures else ''} ===",
          flush=True)
    if failures:
        for f in failures:
            for a in f["failed_assertions"]:
                print(f"  失败断言(run {f['run']}, L{a['line_no']}): {a['assertion']}", flush=True)
        print(f"  现场留档：{OUT}\\failure_*.json", flush=True)
    print(f"  日志：{OUT}\\run_*.log   汇总：{OUT}\\flake_summary.json", flush=True)
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
