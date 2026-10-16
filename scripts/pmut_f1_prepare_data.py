"""核实五层真实声压谱并生成清单；不联网、不启动 COMSOL、不训练。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from memsharness.pmut_f1_dataset import build_inventory, sha256, write_new_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="必须为新目录")
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError("Output must be a new run directory")
    root = args.data_root.resolve()
    patterns = [
        "work/runs/x-densify-20260928/mirror/cell_te2_5_*/Table_9.mat",
        "work/runs/x-densify-20260928/mirror/cell_te2_6_*/Table_9.mat",
        "work/runs/x-densify-20260928/mirror/cell_te2_7_*/Table_9.mat",
        "work/runs/n2-8-intake-20260929/raw/cell_te2_8_*/Table_9.mat",
        "work/runs/te29-freq5-50-server-20261009/out/cell_te2_9_*/Table_9.mat",
    ]
    tables = []
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        if len(matches) != 1:
            raise ValueError("Expected exactly one raw table for " + pattern)
        tables.extend(matches)
    inventory, manifest, pilot = build_inventory(
        tables, root / "work/runs/first-peak-20260929/multichannel_labels.csv",
        root / "work/runs/te2_8_pod_fields_20261005/snapshot_index.tsv")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    outputs = {"scalar_inventory.json": inventory, "export_candidates.json": manifest,
               "export_pilot.json": pilot, "summary.json": {k: v for k, v in inventory.items() if k != "records"}}
    for name, payload in outputs.items():
        write_new_json(out / name, payload)
    hashes = {name: sha256(out / name) for name in outputs}
    write_new_json(out / "file_hashes.json", hashes)
    print(json.dumps({"output": str(out), "n_designs": inventory["n_designs"],
                      "n_frequency_rows": inventory["n_frequency_rows"],
                      "n_first_observable_peaks": inventory["n_first_observable_peaks"],
                      "n_export_candidates": len(manifest["cases"]), "n_pilot_cases": len(pilot["cases"]),
                      "historical_label_audit": inventory["historical_label_audit"],
                      "files": hashes}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
