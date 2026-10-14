# -*- coding: utf-8 -*-
"""M4 包**完整冒烟**驱动：在包目录内依次跑

  1. `python run_benchmark.py --check-only`（秒级：清单完整性 + 期望件自洽 + 解身份自测）
  2. `python run_benchmark.py --check`     （基线 800 格 + 6 项消融 + 解身份自测）
  3. `python run_tasks.py --check`         （6 个任务 + 与 EXPECTED_TASKS 深度比对）

把**事实**记录成 JSON（不手写任何数字），产物：`work/runs/ai11-m4-20261013/smoke_run_<stamp>.json`。
任一步非零退出即整体失败。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
PKG = REPO / "work/dist/peakguard-bench-v1-20261013"
EVID = REPO / "work/runs/ai11-m4-20261013"
STAMP = time.strftime("%Y%m%dT%H%M%S")
PY = sys.executable


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def step(name: str, args: list[str], log: pathlib.Path) -> dict:
    print("\n" + "=" * 78)
    print("== %s:  %s" % (name, " ".join(args)))
    print("=" * 78)
    t0 = time.time()
    with open(log, "wb") as fh:
        rc = subprocess.run([PY, "-X", "utf8"] + args, cwd=str(PKG),
                            stdout=fh, stderr=subprocess.STDOUT).returncode
    wall = time.time() - t0
    txt = log.read_text(encoding="utf-8", errors="replace")
    print(txt)
    print("-- %s: exit=%d，%.1f s" % (name, rc, wall))
    return {"name": name, "command": " ".join(args), "exit_code": rc,
            "wall_seconds": round(wall, 1), "log_file": log.name,
            "log_sha256": sha(log), "log_bytes": log.stat().st_size, "output": txt}


def main() -> int:
    if not (PKG / "run_benchmark.py").is_file():
        raise SystemExit("[FAIL] 包未构建：%s" % PKG)
    for d in (PKG / "results", PKG / "__pycache__"):
        if d.is_dir():
            shutil.rmtree(d)
    EVID.mkdir(parents=True, exist_ok=True)

    steps = [step("check-only（秒级完整性）", ["run_benchmark.py", "--check-only"],
                  EVID / ("smoke_%s_checkonly.log" % STAMP)),
             step("基线 + 消融 + 解身份", ["run_benchmark.py", "--check"],
                  EVID / ("smoke_%s_bench.log" % STAMP)),
             step("任务套件 + 深度比对", ["run_tasks.py", "--check"],
                  EVID / ("smoke_%s_tasks.log" % STAMP))]

    txt = {s["name"]: s["output"] for s in steps}
    m = re.search(r"per-cell comparison: OK (\d+) \| over tolerance (\d+) \| missing (\d+) "
                  r"\| max relative deviation ([\d.eE+-]+) \(tolerance ([\d.eE+-]+)\)",
                  txt["基线 + 消融 + 解身份"])
    st = re.search(r"verdict:\s*(PASS|FAIL)", txt["基线 + 消融 + 解身份"])
    ident = re.search(r"self-test:\s*(PASS|FAIL)", txt["基线 + 消融 + 解身份"])
    tsum = re.search(r"summary: PASS (\d+) \| FAIL (\d+) \| missing artefact (\d+)",
                     txt["任务套件 + 深度比对"])
    tverd = re.search(r"verdict:\s*(PASS|FAIL)", txt["任务套件 + 深度比对"])
    csum = re.search(r"MANIFEST: (\d+) files checked, (\d+) mismatched", txt["check-only（秒级完整性）"])
    cverd = re.search(r"verdict:\s*(PASS|FAIL)", txt["check-only（秒级完整性）"])
    if not (m and st and ident and tsum and tverd and csum and cverd):
        raise SystemExit("[FAIL] 无法从日志解析冒烟结果：m=%s st=%s ident=%s tsum=%s tverd=%s csum=%s cverd=%s"
                         % (bool(m), bool(st), bool(ident), bool(tsum), bool(tverd), bool(csum), bool(cverd)))

    facts = {"kind": "ai11_m4_package_smoke_run", "stamp": STAMP,
             "package": str(PKG.relative_to(REPO)),
             "steps": [{k: v for k, v in s.items() if k != "output"} for s in steps],
             "wall_seconds_total": round(sum(s["wall_seconds"] for s in steps), 1),
             "check_only": {"verdict": cverd.group(1), "files_checked": int(csum.group(1)),
                            "files_mismatched": int(csum.group(2))},
             "benchmark": {"verdict": st.group(1), "cells_compared_ok": int(m.group(1)),
                           "cells_over_tolerance": int(m.group(2)), "cells_missing": int(m.group(3)),
                           "max_relative_deviation": float(m.group(4)), "tolerance_rel": float(m.group(5)),
                           "solution_identity_self_test": ident.group(1)},
             "tasks": {"verdict": tverd.group(1), "outputs_pass": int(tsum.group(1)),
                       "outputs_fail": int(tsum.group(2)), "outputs_missing": int(tsum.group(3))},
             "numbers_are_parsed_not_handwritten": True,
             "note": "三步依次在包目录内运行；任一步非零退出即整体失败；数字全部从日志解析"}

    # --- 关键：**当场**把 results/ 快照到留证目录 ---------------------------------
    # 为什么不能等 finalize：只要中间再重建一次包（rmtree），results/ 就没了，
    # 而留证必须与**这次冒烟的字节**对应。冒烟一结束就快照，证据不再依赖后续步骤。
    snap = EVID / ("smoke_results_%s" % STAMP)
    if snap.exists():
        shutil.rmtree(snap)
    if (PKG / "results").is_dir():
        shutil.copytree(PKG / "results", snap)
        files = sorted(p for p in snap.rglob("*") if p.is_file())
        facts["produced_artifacts_snapshot"] = {
            "dir": str(snap.relative_to(REPO)), "n_files": len(files),
            "files": [{"file": p.relative_to(snap).as_posix(), "bytes": p.stat().st_size,
                       "sha256": sha(p)} for p in files]}
        print("\n冒烟产物快照：%s（%d 个文件）" % (snap.relative_to(REPO), len(files)))
    else:
        facts["produced_artifacts_snapshot"] = None
        print("\n⚠️ 包内没有 results/ —— 无产物可留证")

    out = EVID / ("smoke_run_%s.json" % STAMP)
    out.write_bytes((json.dumps(facts, ensure_ascii=False, indent=2) + "\n").replace("\n", "\r\n").encode("utf-8"))
    (EVID / "SMOKE_RUN_LATEST.json").write_bytes(out.read_bytes())
    print("\n事实件：%s" % out.relative_to(REPO))
    print("check-only %s（%d 件，%d 不符）｜基线 %s（OK %d，偏差 %.3e）｜任务 %s（PASS %d / FAIL %d）｜总 %.1f s"
          % (facts["check_only"]["verdict"], facts["check_only"]["files_checked"],
             facts["check_only"]["files_mismatched"], facts["benchmark"]["verdict"],
             facts["benchmark"]["cells_compared_ok"], facts["benchmark"]["max_relative_deviation"],
             facts["tasks"]["verdict"], facts["tasks"]["outputs_pass"], facts["tasks"]["outputs_fail"],
             facts["wall_seconds_total"]))
    ok = all(s["exit_code"] == 0 for s in steps)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
