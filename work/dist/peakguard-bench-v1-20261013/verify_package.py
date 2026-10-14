# -*- coding: utf-8 -*-
"""Fast integrity check - fits nothing, solves nothing. Takes seconds.

  1. every file listed in `MANIFEST.json` is compared against its recorded sha256 (is this copy intact?);
  2. `expected/EXPECTED_OUTPUTS.json` and `expected/EXPECTED_TASKS.json` are checked for internal
     consistency (tolerance, stripping policy, task entries, provenance record for every expected output);
  3. `check_solution_identity.py` runs its self-test (the four-step solution-identity rule is executable).

Typical use: a reviewer confirms the copy is intact before spending ~16 minutes on the full pipeline.
We use it as the post-build gate as well.

Exit codes: 0 = all pass; 1 = something failed; 2 = missing file.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_manifest() -> tuple[bool, list[str]]:
    p = HERE / "MANIFEST.json"
    if not p.is_file():
        return False, ["MANIFEST.json is missing"]
    man = json.loads(p.read_text(encoding="utf-8"))
    bad, n = [], 0
    for rel, rec in sorted((man.get("files") or {}).items()):
        n += 1
        f = HERE / rel
        if not f.is_file():
            bad.append("missing: %s" % rel)
            continue
        if sha(f) != rec["sha256"]:
            bad.append("hash mismatch: %s" % rel)
    print("  MANIFEST: %d files checked, %d mismatched" % (n, len(bad)))
    return not bad, bad


def check_expected() -> tuple[bool, list[str]]:
    bad = []
    eo = HERE / "expected/EXPECTED_OUTPUTS.json"
    if not eo.is_file():
        bad.append("expected/EXPECTED_OUTPUTS.json is missing")
    else:
        d = json.loads(eo.read_text(encoding="utf-8"))
        for k in ("tolerance_rel", "per_seed_cell_medians", "anchors", "source_sha256"):
            if k not in d:
                bad.append("EXPECTED_OUTPUTS.json lacks key %s" % k)
        n = sum(len(v) for b in (d.get("per_seed_cell_medians") or {}).values() for v in b.values())
        print("  EXPECTED_OUTPUTS: tolerance %.1e, %d method x seed cells" % (float(d.get("tolerance_rel", 0)), n))
    et = HERE / "expected/EXPECTED_TASKS.json"
    if not et.is_file():
        bad.append("expected/EXPECTED_TASKS.json is missing")
    else:
        d = json.loads(et.read_text(encoding="utf-8"))
        for k in ("tolerance_rel", "strip_policy", "tasks", "sources", "removed_keys"):
            if k not in d:
                bad.append("EXPECTED_TASKS.json lacks key %s" % k)
        n_out = sum(len(v) for v in (d.get("tasks") or {}).values())
        miss_src = [rel for rel in (d.get("tasks") or {}) for rel in d["tasks"][rel]
                    if rel not in (d.get("sources") or {})]
        if miss_src:
            bad.append("EXPECTED_TASKS.json has outputs without a provenance record: %s" % miss_src[:3])
        print("  EXPECTED_TASKS: %d tasks, %d output files, %d stripped keys"
              % (len(d.get("tasks") or {}), n_out, len(d.get("removed_keys") or [])))
        if "text_rendering_note" not in d:
            bad.append("EXPECTED_TASKS.json lacks the text_rendering_note "
                       "(the package documents how its English rendering is produced)")
    return not bad, bad


def check_identity() -> tuple[bool, list[str]]:
    p = HERE / "check_solution_identity.py"
    if not p.is_file():
        return False, ["check_solution_identity.py is missing"]
    r = subprocess.run([sys.executable, "-X", "utf8", str(p)], cwd=str(HERE),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = r.stdout.decode("utf-8", "replace")
    ok = r.returncode == 0 and "self-test: PASS" in out
    print("  solution-identity self-test: %s" % ("PASS" if ok else "FAIL"))
    return ok, ([] if ok else ["check_solution_identity.py self-test did not pass"])


def main() -> int:
    print("package directory: %s" % HERE)
    allbad: list[str] = []
    for name, fn in (("manifest integrity", check_manifest), ("expected-file sanity", check_expected),
                     ("solution-identity rule", check_identity)):
        print("\n== %s ==" % name)
        ok, bad = fn()
        allbad += bad
    print("\nverdict:", "PASS" if not allbad else "FAIL")
    for b in allbad:
        print("  x %s" % b)
    if any("MANIFEST.json is missing" in b for b in allbad):
        return 2
    return 0 if not allbad else 1


if __name__ == "__main__":
    raise SystemExit(main())
