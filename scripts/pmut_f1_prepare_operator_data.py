"""核验已回收的只读导出并形成研究数据；不启动COMSOL或训练。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from memsharness.pmut_f1_operator_data import prepare_operator_data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--split-policy", choices=("branch_holdout", "design_holdout"), default="branch_holdout")
    parser.add_argument("--export-dir", type=Path, action="append", required=True,
                        help="Completed recovered bundle including original manifest.json bytes")
    parser.add_argument("--output-dir", type=Path, required=True, help="New append-only evidence directory")
    args = parser.parse_args(argv)
    audit = prepare_operator_data(args.plan, args.export_dir, args.output_dir, split_policy=args.split_policy)
    print(json.dumps({"output": str(args.output_dir.resolve()), "n_designs": audit["n_designs"],
        "n_excluded": audit["n_excluded"], "designs_by_split": audit["designs_by_split"],
        "blockers": audit["blockers"], "training_ready": False, "release_allowed": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
