# -*- coding: utf-8 -*-
"""Solution-identity check: prove two stored solutions are comparable BEFORE re-evaluating anything.

Why this exists. One model file can hold several solutions. Re-evaluating post-processing on a stored
solution is unsafe once the model was re-meshed or its geometry edited after that solution was stored:
selection sets and entity numbers can go stale, so a selection that is valid for one solution can
silently address different faces on another. In the measured case behind this benchmark, a probe
evaluated from a hard-coded face list differed by a factor 6.667 between two solutions of the same file
that shared an identical geometry, an identical parameter read-back and a single mesh object.

The four-step checklist
  1. TAG          every solution is named, and the names are unique.
  2. STORED MESH  every solution carries a digest of the mesh it stored (not the model's current mesh).
  3. PARAMETERS   every compared solution reads back identical parameters at the design point.
  4. INVARIANT    a geometry-only integral agrees across the compared solutions within tolerance.

Admissibility of a quantity
  Steps 1-4 must pass. In addition, a quantity that declares depends_on_entity_numbering=true may be
  compared across solutions only if all of them share one stored-mesh digest, or if every record
  declares selection_re_resolved=true (the selection was re-resolved on that solution's own mesh by a
  geometric predicate). Copying entity indices between solutions is never admissible.

Usage
    python check_solution_identity.py                 # self-test on the bundled record
    python check_solution_identity.py RECORDS.json    # your own record

Exit code 0 means the checker reached the decision recorded in expected_decision (self-test), or that
every comparison is admissible. It never means the physics is right.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT = HERE / "data/solution_identity_example.json"
STEPS = ("tag", "stored_mesh", "parameters", "invariant")
STEP_TEXT = {
    "tag": "1 TAG: every solution named, names unique",
    "stored_mesh": "2 STORED MESH: a digest of the stored mesh per solution",
    "parameters": "3 PARAMETERS: identical read-back at the design point",
    "invariant": "4 INVARIANT: a geometry-only integral agrees",
}


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check(rec):
    """Return {steps, quantities, admissible, refused, comments} for one record."""
    sols = rec.get("solutions") or []
    tol = float(rec.get("tolerance_rel", 1e-9))
    comments, steps = [], {}

    tags = [s.get("tag") for s in sols]
    steps["tag"] = bool(sols) and all(isinstance(t, str) and t for t in tags) and len(set(tags)) == len(tags)
    if not steps["tag"]:
        comments.append("a solution has no tag, or two share one")

    digests = [s.get("stored_mesh_digest") for s in sols]
    steps["stored_mesh"] = all(isinstance(d, str) and d for d in digests)
    if not steps["stored_mesh"]:
        comments.append("a solution does not carry a stored-mesh digest: identity cannot be established")

    params = [json.dumps(s.get("params"), sort_keys=True) for s in sols]
    steps["parameters"] = len(set(params)) == 1 and params and params[0] != "null"
    if not steps["parameters"]:
        comments.append("the compared solutions do not read back identical parameters")

    keys = sorted({k for s in sols for k, q in (s.get("quantities") or {}).items()
                   if isinstance(q, dict) and q.get("geometry_only")})
    agree = True
    if not keys:
        agree = False
        comments.append("no geometry-only integral is declared, so step 4 cannot be evaluated")
    for k in keys:
        vals = [((s.get("quantities") or {}).get(k) or {}).get("value") for s in sols]
        if not all(_finite(v) for v in vals):
            agree = False
            comments.append("geometry-only integral " + k + " is not finite everywhere")
            continue
        lo, hi = min(vals), max(vals)
        spread = (hi - lo) / abs(lo) if lo else abs(hi - lo)
        if spread > tol:
            agree = False
            comments.append("geometry-only integral " + k + " disagrees by rel " + repr(spread))
    steps["invariant"] = agree

    one_digest = steps["stored_mesh"] and len(set(digests)) == 1
    quantities, admissible, refused = {}, [], []
    all_keys = sorted({k for s in sols for k in (s.get("quantities") or {})})
    for k in all_keys:
        qs = [((s.get("quantities") or {}).get(k) or {}) for s in sols]
        vals = [q.get("value") for q in qs]
        finite = [v for v in vals if _finite(v)]
        spread, ratio = None, None
        if len(finite) >= 2:
            lo, hi = min(finite), max(finite)
            spread = (hi - lo) / abs(lo) if lo else abs(hi - lo)
            ratio = (hi / lo) if lo else None
        geo = all(q.get("geometry_only") for q in qs)
        ent = any(q.get("depends_on_entity_numbering") for q in qs)
        re_res = all(q.get("selection_re_resolved") for q in qs)
        if not all(steps.values()):
            why = "identity steps failed"
            ok = False
        elif geo or not ent or one_digest or re_res:
            why = "geometry-only" if geo else ("not entity-numbered" if not ent else
                                               ("one stored mesh" if one_digest else "selection re-resolved"))
            ok = True
        else:
            why = "entity-numbered selection, different stored meshes, not re-resolved"
            ok = False
        quantities[k] = {"admissible": ok, "reason": why, "n_values": len(finite),
                         "max_rel_spread": spread, "max_ratio_hi_over_lo": ratio}
        (admissible if ok else refused).append(k)

    return {"steps": steps, "quantities": quantities, "admissible": admissible,
            "refused": refused, "comments": comments,
            "n_solutions": len(sols), "tags": tags, "n_stored_meshes": len(set(digests))}


def main(argv):
    path = pathlib.Path(argv[0]) if argv else DEFAULT
    rec = json.loads(path.read_text(encoding="utf-8"))
    res = check(rec)
    print("record:", path.name, "| solutions:", res["n_solutions"], "| distinct stored meshes:",
          res["n_stored_meshes"])
    for s in STEPS:
        print(("  OK   " if res["steps"][s] else "  FAIL ") + STEP_TEXT[s])
    for c in res["comments"]:
        print("     note:", c)
    print("  quantities:")
    for k, q in sorted(res["quantities"].items()):
        sp = "n/a" if q["max_rel_spread"] is None else ("%.4g" % q["max_rel_spread"])
        ra = "n/a" if q["max_ratio_hi_over_lo"] is None else ("%.4g" % q["max_ratio_hi_over_lo"])
        print("    " + ("ADMISSIBLE" if q["admissible"] else "REFUSED   ") + "  " + k +
              "  (n=" + str(q["n_values"]) + ", max rel spread=" + sp + ", max ratio hi/lo=" + ra +
              ") -- " + q["reason"])
    exp = rec.get("expected_decision")
    if exp is None:
        verdict = "PASS" if not res["refused"] else "REFUSED"
        print("verdict:", verdict, "(no expected_decision recorded; advisory only)")
        return 0 if not res["refused"] else 1
    got = {"steps": "pass" if all(res["steps"].values()) else "fail",
           "admissible": sorted(res["admissible"]), "refused": sorted(res["refused"]),
           "max_rel_spread_refused": {k: res["quantities"][k]["max_rel_spread"] for k in res["refused"]}}
    ok = True
    for k in ("steps", "admissible", "refused"):
        if got[k] != exp.get(k):
            ok = False
            print("  SELF-TEST MISMATCH on", k, ": got", got[k], "want", exp.get(k))
    for k, want in (exp.get("max_rel_spread_refused") or {}).items():
        a = got["max_rel_spread_refused"].get(k)
        if a is None or abs(a - want) / abs(want) > 1e-3:
            ok = False
            print("  SELF-TEST MISMATCH on max_rel_spread_refused[" + k + "]: got", a, "want", want)
    if set(got["max_rel_spread_refused"]) != set(exp.get("max_rel_spread_refused") or {}):
        ok = False
        print("  SELF-TEST MISMATCH on max_rel_spread_refused keys: got",
              sorted(got["max_rel_spread_refused"]), "want",
              sorted(exp.get("max_rel_spread_refused") or {}))
    print("self-test:", "PASS (checker reproduced the recorded decision)" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
