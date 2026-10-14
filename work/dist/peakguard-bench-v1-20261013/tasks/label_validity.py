# -*- coding: utf-8 -*-
"""Label validity: how many rows per batch have an **undefined two-sided -3 dB bandwidth**
(the counts quoted in the paper's sections 5 and 6.1).

Why this is a separate task: the package's own `peak_semantics_audit` only checks value/state
self-consistency (both zero, or symmetric); it does not produce the *counts* that the paper reports
(259 of 1,782 = 14.5 % and 69 of 223 = 30.9 %).

The caliber is identical to the package's evaluator: this task imports `bench` and uses its
`load_all()` row assembly, so `row["closed"]` is the A/C native `bandwidth_closed` flag or the V2
endpoint-proxy flag.
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))

import bench  # noqa: E402


def main() -> int:
    rows, meta = bench.load_all()
    out = {"kind": "peakguard_label_validity",
           "caliber": ("row[\"closed\"] comes from bench.load_all(): A/C use the native `bandwidth_closed` "
                       "flag, V2 uses the endpoint proxy (neither the peak nor the bandwidth upper cutoff "
                       "touches the scan endpoint)"),
           "n_rows_union": len(rows),
           "batch_counts": meta.get("batch_counts"),
           "flag_note_by_batch": meta.get("flag_note_by_batch"),
           "per_batch": {}, "inputs": meta.get("inputs")}

    for b in bench.BATCHES:
        rb = [r for r in rows if r["batch"] == b]
        n = len(rb)
        n_closed = sum(1 for r in rb if r["closed"])
        per = {"n_rows": n,
               "n_bandwidth_closed": n_closed,
               "n_bandwidth_not_closed": n - n_closed,
               "frac_not_closed": (n - n_closed) / n if n else None,
               "n_peak_found": sum(1 for r in rb if r["peaked"]),
               "n_quarantined": sum(1 for r in rb if r["quarantined"]),
               "n_flag_usable": sum(1 for r in rb if r["flag_usable"]),
               "flag_note": (meta.get("flag_note_by_batch") or {}).get(b)}
        per["per_channel_defined"] = {
            ch: sum(1 for r in rb if bench.defined(r, ch)) for ch in bench.CH8}
        out["per_batch"][b] = per

    out["not_claimed"] = [
        "No claim that the closure verdict is physically correct: it only records whether a two-sided "
        "-3 dB crossing can be defined inside the scan window;",
        "No claim that the three batches are comparable: A/C use native flags and V2 a proxy flag "
        "(flag_note marks this per batch);",
        "No claim of any engineering absolute value."]
    outp = PKG / "results/label_validity.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_bytes((json.dumps(out, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print("wrote", outp)
    for b, p in out["per_batch"].items():
        print("  %-12s rows %4d | closed %4d | not closed %3d (%.1f%%) | peaked %4d | flag=%s"
              % (b, p["n_rows"], p["n_bandwidth_closed"], p["n_bandwidth_not_closed"],
                 100 * p["frac_not_closed"], p["n_peak_found"], p["flag_note"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
