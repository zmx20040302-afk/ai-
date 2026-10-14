# -*- coding: utf-8 -*-
"""Run the task suite and (optionally) compare it against the frozen expected values.

Prerequisite: run `python run_benchmark.py` first (baselines + ablations). This suite depends on the
baseline registry it produces, `results/baselines_by_seed.json`, and **fails closed** if that file is
absent rather than silently skipping stages.

    python run_tasks.py                # run the six stages in order
    python run_tasks.py --check        # run them, then deep-compare against expected/EXPECTED_TASKS.json
    python run_tasks.py --only t5      # run a single stage
    python run_tasks.py --check-only   # compare existing artefacts; compute nothing

Which paper numbers this suite is the executable counterpart of:
  label_validity  sections 5 / 6.1, undefined-bandwidth counts
  m1_m2_m3        sections 4.1 / 6.3, split structure, split-realisation sensitivity, risk-coverage,
                  cross-batch transfer
  t1_t2           section 6.3, peak-identity and bandwidth-closure classification
  t5              sections 6.2 / 7, refusal behaviour
  t7_scheduling   section 6.6, the four-arm closed-loop table (solver-free replay)

Runtime note: `m1_m2_m3` alone takes 8.7-10.4 minutes across four measured runs on the authors' machine
(about 520-624 s), so it can exceed a ten-minute budget on a loaded host; the whole suite measured
679 s in the packaged full-chain run. See REPRODUCIBILITY.md.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
STAGES = [("label_validity", "tasks/label_validity.py"),
          ("m1_m2_m3", "tasks/m1_m2_m3.py"),
          ("t1_t2", "tasks/t1_t2.py"),
          ("t1_t2_spacing", "tasks/t1_t2_spacing.py"),
          ("t5", "tasks/t5.py"),
          ("t7_scheduling", "tasks/t7_scheduling.py")]
NEEDS_BASELINE = HERE / "results/baselines_by_seed.json"


def run(stage: str, script: str) -> dict:
    p = HERE / script
    if not p.is_file():
        return {"stage": stage, "script": script, "status": "missing_script"}
    t0 = time.time()
    r = subprocess.run([sys.executable, "-X", "utf8", str(p)], cwd=str(HERE))
    return {"stage": stage, "script": script, "exit_code": r.returncode,
            "wall_seconds": round(time.time() - t0, 1),
            "status": "ok" if r.returncode == 0 else "failed"}


def main() -> int:
    argv = sys.argv[1:]
    only = None
    if "--only" in argv:
        only = argv[argv.index("--only") + 1]
    do_check = "--check" in argv or "--check-only" in argv
    check_only = "--check-only" in argv

    print("package directory: %s" % HERE)
    if not check_only and not NEEDS_BASELINE.is_file():
        print("[FAIL] missing %s - run this first: python run_benchmark.py"
              % NEEDS_BASELINE.relative_to(HERE))
        return 2

    runs = []
    if not check_only:
        stages = [s for s in STAGES if only is None or s[0] == only]
        if only is not None and not stages:
            print("[FAIL] unknown stage %r; available: %s" % (only, ", ".join(s[0] for s in STAGES)))
            return 2
        for stage, script in stages:
            print("\n" + "=" * 72)
            print("== %s  (%s)" % (stage, script))
            print("=" * 72)
            rec = run(stage, script)
            runs.append(rec)
            print("-- %s: %s (%.1f s)" % (stage, rec["status"], rec.get("wall_seconds", 0.0)))
            if rec["status"] != "ok":
                print("[FAIL] stage %s did not succeed; later stages still run, and the verdict below decides"
                      % stage)
        (HERE / "results/TASKS_RUN.json").write_bytes(
            (json.dumps({"kind": "peakguard_bench_tasks_run",
                         "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "runs": runs}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    if not do_check:
        print("\n(no comparison performed; add --check to enable it)")
        return 0

    print("\n" + "=" * 72)
    print("== comparison against the frozen expected values")
    print("=" * 72)
    r = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "check_tasks.py")], cwd=str(HERE))
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
