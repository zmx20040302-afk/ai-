"""解析/降阶数据工厂 CLI：跑自基准 → 扫掠生成 → 写入元数据库（source_type=analytic）。

用法：
    python scripts/generate_analytic.py --benchmark                 # 只跑自基准
    python scripts/generate_analytic.py --model heat_slab_1d --n 200
    python scripts/generate_analytic.py --all --n 100                # 每个模型各 100 点
    python scripts/generate_analytic.py --model cantilever_resonance --n 50 --set E=170e9 --set rho=2330

约定：**自基准不过就不生成**——没有基准的解析数据不得进入训练集。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from memsharness import analytic as an  # noqa: E402
from memsharness.store import connect  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="解析数据工厂：基准 + 生成 + 入库")
    ap.add_argument("--model", default=None, help="模型名（见 --list）")
    ap.add_argument("--all", action="store_true", help="对全部模型各生成 N 点")
    ap.add_argument("--n", type=int, default=64, help="每个模型生成的设计点数")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="固定某个参数（可重复）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--benchmark", action="store_true", help="只跑自基准后退出")
    ap.add_argument("--list", action="store_true", help="列出模型后退出")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.list:
        print(json.dumps(an.list_models(), ensure_ascii=False, indent=2))
        return 0

    benchmarks = an.run_benchmarks()
    if args.json:
        print(json.dumps({"benchmarks": benchmarks}, ensure_ascii=False, indent=2))
    else:
        for name, info in benchmarks["models"].items():
            print(f"[基准] {name:<28} {info['n_checks']} 项，失败 {info['n_failed']}")
    if not benchmarks["all_passed"]:
        print("自基准未全部通过：**拒绝生成数据**（没有基准的解析数据不得入训练集）", file=sys.stderr)
        return 3
    if args.benchmark:
        return 0

    overrides = {}
    for item in args.set:
        key, _, value = item.partition("=")
        overrides[key.strip()] = float(value)

    targets = list(an.MODELS) if args.all else ([args.model] if args.model else [])
    if not targets:
        print("请用 --model 指定模型，或用 --all（--list 可查看模型清单）", file=sys.stderr)
        return 2

    total = 0
    with connect() as conn:
        for name in targets:
            rows = an.generate_designs(name, n_samples=args.n, overrides=overrides or None, seed=args.seed)
            prefix = f"an-{name}"
            result = an.insert_analytic_samples(conn, rows, design_prefix=prefix)
            total += result["inserted"]
            print(f"[生成] {name:<28} {result['inserted']} 条（design 前缀 {prefix}）")
    print(f"合计入库 {total} 条解析样本（source_type='analytic'，保真度见各模型 fidelity）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
