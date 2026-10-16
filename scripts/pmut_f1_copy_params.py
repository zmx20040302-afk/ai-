#!/usr/bin/env python
"""PMUT-F1 现有模型快速路径：只在副本中写入三参数并读回。

本脚本不求解、不覆盖源模型、不宣称候选点最优。COMSOL 调用必须由外层保证串行。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness import modelio  # noqa: E402
from memsharness.pmut_f1 import validate_design_point  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def parameter_expressions(x_scale: float, n1: int, n2: int) -> dict[str, str]:
    """返回 COMSOL 表达式；离散参数禁止写成小数。"""
    point = validate_design_point(x_scale, n1, n2)
    params = point["parameters"]
    return {
        "x_scale": format(float(params["x_scale"]), ".12g"),
        "N_w_te1": str(int(params["N_w_te1"])),
        "N_w_te2": str(int(params["N_w_te2"])),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="只读 PMUT .mph 源模型")
    parser.add_argument("--x", required=True, type=float, dest="x_scale")
    parser.add_argument("--n1", required=True, type=int)
    parser.add_argument("--n2", required=True, type=int)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--no-geometry-baseline", action="store_true",
        help="跳过写前/写后包围盒探针；此时 geometry_changing 必为未知",
    )
    return parser


def evaluate_copy_result(result: dict, requested: dict, before: str, after: str) -> dict:
    """写入与几何重建分别判定；包围盒不变不能免除选择集复核。"""
    diff_by_name = {row.get("name"): row for row in result.get("diff", [])}
    all_applied = all(diff_by_name.get(name, {}).get("applied") is True
                      for name in requested)
    source_untouched = before == after and result.get("source_original_untouched") is True
    write_ok = result.get("ok") is True and all_applied and source_untouched
    geometry_ok = (result.get("geometry_after_set") or {}).get("rebuilt_ok") is True
    return {
        "ok": write_ok and geometry_ok,
        "parameter_write_ok": write_ok,
        "all_three_read_back": all_applied,
        "source_untouched": source_untouched,
        "geometry_rebuilt_ok": geometry_ok,
        "required_reverification": True,
        "named_selections_verified": False,
        "ready_for_solve": False,
        "release_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.source.resolve()
    if not source.is_file() or source.suffix.lower() != ".mph":
        raise FileNotFoundError("PMUT 源模型不存在或不是 .mph：%s" % source)
    requested = parameter_expressions(args.x_scale, args.n1, args.n2)
    before = _sha256(source)
    result = modelio.set_parameters(
        source,
        requested,
        work_root=REPO / "work",
        timeout_seconds=args.timeout,
        baseline_geometry=not args.no_geometry_baseline,
    )
    after = _sha256(source)
    checks = evaluate_copy_result(result, requested, before, after)
    report = {
        "schema": "memsharness.pmut_f1_copy_params/v0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "three_parameter_copy_write_readback_smoke_not_optimization",
        "source": {"path": str(source), "sha256_before": before, "sha256_after": after,
                   "untouched": checks["source_untouched"]},
        "requested": requested,
        "result": result,
        "checks": checks,
        "all_three_read_back": checks["all_three_read_back"],
        "release_allowed": False,
    }
    out_dir = REPO / "work/reports/pmut-f1"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ("copy-params-%s.json" % result.get("run_id", "failed"))
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        **checks,
        "run_id": result.get("run_id"),
        "output_path": result.get("output_path"),
        "output_sha256": result.get("output_sha256"),
        "geometry_changing": result.get("geometry_changing"),
        "report": str(out_path),
        "diff": result.get("diff"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
