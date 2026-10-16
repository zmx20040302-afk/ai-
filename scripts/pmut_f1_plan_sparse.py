"""从既有点谱冻结稀疏复场候选及两套几何分组；不启动远端或 COMSOL。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from memsharness.pmut_f1_dataset import sha256
from memsharness.pmut_f1_sparse_plan import build_sparse_plan, read_historical_hints, write_plan_run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--exposed-manifest", type=Path, action="append", required=True)
    parser.add_argument("--source-index", type=Path)
    parser.add_argument("--historical-model-manifest", type=Path)
    parser.add_argument("--model-path-hint", action="append", default=[], help="N2=/existing/source/path.mph；仅记录线索")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        raise FileExistsError("Output must be a new run directory")
    paths = [args.inventory, *args.exposed_manifest]
    if args.source_index:
        paths.append(args.source_index)
    if args.historical_model_manifest:
        paths.append(args.historical_model_manifest)
    inputs = [{"path": str(path.resolve()), "sha256": sha256(path)} for path in paths]
    read = lambda path: json.loads(path.read_text(encoding="utf-8-sig"))
    inventory = read(args.inventory)
    exposed = {case["case_id"] for path in args.exposed_manifest for case in read(path)["cases"]}
    hints = read_historical_hints(args.historical_model_manifest, args.model_path_hint)
    plan, splits, pending = build_sparse_plan(inventory, exposed,
        source_index=read(args.source_index) if args.source_index else None, source_hints=hints)
    for item in inputs:
        if sha256(Path(item["path"])) != item["sha256"]:
            raise ValueError("Input changed during planning")
    for payload in (plan, splits, pending):
        payload["inputs"] = inputs
    hashes = write_plan_run(args.output_dir, plan, splits, pending)
    print(json.dumps({"output_dir": str(args.output_dir.resolve()), "n_selected": plan["n_selected"],
        "n_export_ready": plan["n_export_ready"], "n_lineage_quarantined": plan["n_lineage_quarantined"],
        "split_counts": plan["split_counts"], "shortages": plan["shortages"], "files": hashes}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
