# -*- coding: utf-8 -*-
"""Compare the outputs in `results/` against `expected/EXPECTED_OUTPUTS.json` (relative tolerance)."""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected/EXPECTED_OUTPUTS.json").read_text(encoding="utf-8"))
TOL = float(EXP.get("tolerance_rel", 1e-6))


def main() -> int:
    got_p = HERE / "results/baselines_by_seed.json"
    if not got_p.is_file():
        print("[FAIL] results/baselines_by_seed.json not found; run bench.py first")
        return 2
    got = json.loads(got_p.read_text(encoding="utf-8"))["per_seed"]
    worst, n_ok, n_bad, n_missing = 0.0, 0, 0, 0
    bad = []
    for b, chans in EXP["per_seed_cell_medians"].items():
        for ch, methods in chans.items():
            for m, seeds in methods.items():
                for s, want in seeds.items():
                    cell = ((got.get(b) or {}).get(s) or {}).get("channels", {}).get(ch) or {}
                    md = (cell.get("methods") or {}).get(m) or {}
                    v = md.get("median")
                    if v is None:
                        n_missing += 1
                        continue
                    rel = abs(v - want) / abs(want) if want else abs(v - want)
                    worst = max(worst, rel)
                    if rel <= TOL:
                        n_ok += 1
                    else:
                        n_bad += 1
                        if len(bad) < 12:
                            bad.append({"batch": b, "seed": s, "channel": ch, "method": m,
                                        "expected": want, "got": v, "rel": rel})
    print("per-cell comparison: OK %d | over tolerance %d | missing %d | max relative deviation %.3e (tolerance %.1e)"
          % (n_ok, n_bad, n_missing, worst, TOL))
    for x in bad:
        print("   x", x)
    verdict = "PASS" if (n_bad == 0 and n_missing == 0) else "FAIL"
    print("verdict:", verdict)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
