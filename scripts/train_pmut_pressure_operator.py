"""复声压算子输入验收/研究训练；不启动COMSOL、不自动安装依赖、不放行。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from memsharness.pmut_pressure_operator import dataset_audit, load_dataset, train_operator, write_new_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New run directory; never overwritten")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--research-only", action="store_true", help="Allow explicitly incomplete physics, never production use")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--width", type=int, default=64)
    parser.add_argument("--latent", type=int, default=32)
    parser.add_argument("--query-points-per-design", type=int, default=2048)
    parser.add_argument("--max-condition-points", type=int, default=4096)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-seconds", type=float, default=600)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--torch-threads", type=int, default=1)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError("Output must be a new evidence directory")
    dataset = load_dataset(args.manifest, research_only=args.research_only)
    if args.audit_only:
        args.output.mkdir(parents=True, exist_ok=False)
        report = dataset_audit(dataset)
        write_new_json(args.output / "dataset_audit.json", report)
    else:
        report = train_operator(dataset, args.output, research_only=args.research_only, epochs=args.epochs,
            width=args.width, latent=args.latent, query_points_per_design=args.query_points_per_design,
            max_condition_points=args.max_condition_points, learning_rate=args.learning_rate,
            seed=args.seed, max_seconds=args.max_seconds, device=args.device, torch_threads=args.torch_threads)
    print(json.dumps({"output": str(args.output), "n_designs": report["n_designs"],
        "blockers": report["blockers"], "training_ready": False, "release_allowed": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
