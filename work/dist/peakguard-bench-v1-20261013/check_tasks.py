# -*- coding: utf-8 -*-
"""Deep-compare the task outputs in `results/` against `expected/EXPECTED_TASKS.json`.

How this differs from `check_results.py`:
  * `check_results.py` compares the per-cell **medians** of the baselines and ablations
    (8 methods x 5 seeds x 800 cells);
  * `check_tasks.py` (this file) compares the **task artefacts** (M1/M2/M3, T1/T2, T5, T7, label validity).

Why a *deep* comparison rather than a numeric-only one: the expected file is extracted from the
registered artefacts, so it carries structure, key names and values. A renamed key, a missing channel
or a changed nesting therefore fails - which detects a changed caliber, not just a changed number.

Both sides are put through the **same provenance stripping** (timings, timestamps, internal-path keys,
non-distributed pre-registration blocks) before comparison. The policy is read from
`expected/EXPECTED_TASKS.json` itself (`strip_policy`), so the two sides cannot drift apart.

Exit codes: 0 = every output within tolerance; 1 = any mismatch or missing key; 2 = missing artefact
or missing expected file.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected/EXPECTED_TASKS.json").read_text(encoding="utf-8"))
TOL = float(EXP.get("tolerance_rel", 1e-6))
POL = EXP.get("strip_policy") or {}
EXACT = set(POL.get("exact_keys") or [])
SUFFIX = tuple(POL.get("suffixes") or [])
NESTED = {tuple(p.split(".")) for p in (POL.get("nested_paths") or [])}
PER_OUTPUT = {k: set(v) for k, v in (POL.get("per_output") or {}).items()}


def strip(o, path=(), rel=""):
    """Apply exactly the policy the expected values were built with (including the per-output table)."""
    if isinstance(o, dict):
        out = {}
        extra = PER_OUTPUT.get(rel) or set()
        for k, v in o.items():
            if k in EXACT or (SUFFIX and any(k.endswith(s) for s in SUFFIX)) or k in extra:
                continue
            if (path + (k,)) in NESTED:
                continue
            out[k] = strip(v, path + (k,), rel)
        return out
    if isinstance(o, list):
        return [strip(x, path, rel) for x in o]
    return o


def cmp(exp, got, path="$"):
    """Return (mismatches, missing, extra, n_leaves, worst_rel)."""
    mm, miss, extra, leaves = [], [], [], [0]
    worst = [0.0]

    def rec(e, g, p):
        if isinstance(e, dict):
            if not isinstance(g, dict):
                mm.append((p, "<dict>", type(g).__name__))
                return
            for k in e:
                if k not in g:
                    miss.append(p + "." + k)
                else:
                    rec(e[k], g[k], p + "." + k)
            for k in g:
                if k not in e:
                    extra.append(p + "." + k)
        elif isinstance(e, list):
            if not isinstance(g, list):
                mm.append((p, "<list>", type(g).__name__))
                return
            if len(e) != len(g):
                mm.append((p + "[]", "len=%d" % len(e), "len=%d" % len(g)))
            for i, (x, y) in enumerate(zip(e, g)):
                rec(x, y, p + "[%d]" % i)
        else:
            leaves[0] += 1
            if isinstance(e, bool) or e is None or isinstance(e, str):
                if e != g:
                    mm.append((p, repr(e)[:60], repr(g)[:60]))
            else:
                try:
                    fg = float(g)
                except (TypeError, ValueError):
                    mm.append((p, repr(e)[:60], repr(g)[:60]))
                    return
                if not math.isfinite(fg):
                    mm.append((p, repr(e)[:60], repr(g)[:60]))
                    return
                rel = abs(fg - float(e)) / abs(float(e)) if e else abs(fg - float(e))
                worst[0] = max(worst[0], rel)
                if rel > TOL:
                    mm.append((p, repr(e)[:60], repr(g)[:60]))

    rec(exp, got, path)
    return mm, miss, extra, leaves[0], worst[0]


def main() -> int:
    tasks = EXP.get("tasks") or {}
    if not tasks:
        print("[FAIL] the expected file contains no tasks")
        return 2
    print("expected file: expected/EXPECTED_TASKS.json (tolerance %.1e, %d tasks)" % (TOL, len(tasks)))
    n_ok = n_bad = n_missing_file = 0
    for task, items in sorted(tasks.items()):
        print("\n== %s ==" % task)
        for rel, e in sorted(items.items()):
            p = HERE / rel
            if not p.is_file():
                print("  [MISSING] %s" % rel)
                n_missing_file += 1
                continue
            got = json.loads(p.read_text(encoding="utf-8"))
            mm, miss, extra, leaves, worst = cmp(strip(e, rel=rel), strip(got, rel=rel))
            ok = not mm and not miss
            n_ok += int(ok)
            n_bad += int(not ok)
            print("  [%s] %-38s leaves %5d | mismatch %d | missing keys %d | extra keys %d | max rel dev %.3e"
                  % ("PASS" if ok else "FAIL", rel, leaves, len(mm), len(miss), len(extra), worst))
            for x in mm[:6]:
                print("        x %s  expected %s  got %s" % x)
            for x in miss[:6]:
                print("        x missing key %s" % x)
            for x in extra[:3]:
                print("        . extra key (informational only) %s" % x)
    print("\nsummary: PASS %d | FAIL %d | missing artefact %d" % (n_ok, n_bad, n_missing_file))
    if n_missing_file:
        return 2
    print("verdict:", "PASS" if n_bad == 0 else "FAIL")
    return 0 if n_bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
