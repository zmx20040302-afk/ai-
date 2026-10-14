# -*- coding: utf-8 -*-
"""One-command entry point: run the benchmark, then optionally compare against the expected values.

    python run_benchmark.py                # baselines only: 8 methods x 5 seeds (~4 minutes)
    python run_benchmark.py --check        # run, compare per cell against expected/, then the identity self-test
    python run_benchmark.py --check-only   # seconds only: manifest integrity + expected-file sanity + identity self-test
    python run_benchmark.py --skip-ablations --check

The task suite (which needs the `results/baselines_by_seed.json` this script produces) has its own
entry point: `python run_tasks.py --check`.
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bench  # noqa: E402
import check_results  # noqa: E402
import check_solution_identity  # noqa: E402


def main() -> int:
    if "--check-only" in sys.argv:
        import verify_package  # noqa: E402
        return verify_package.main()
    argv = [a for a in sys.argv[1:] if a != "--check"]
    do_check = "--check" in sys.argv
    rc = bench.main(argv or ["--out", str(HERE / "results")])
    if rc:
        return rc
    if not do_check:
        return 0
    rc = check_results.main()
    if rc:
        return rc
    print()
    return check_solution_identity.main([])


if __name__ == "__main__":
    raise SystemExit(main())
