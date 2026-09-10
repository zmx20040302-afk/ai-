"""训练代理模型并登记模型卡（P0 最小闭环的最后一环）。

流程：
    读样本（DuckDB）→ 按几何族分组切分 → 训练深度集成 → 评分卡
    → 保存模型 → 写模型卡 → 登记 model 表（状态固定 draft）

用法：
    work\\.venv\\Scripts\\python.exe scripts\\train_surrogate.py
    work\\.venv\\Scripts\\python.exe scripts\\train_surrogate.py --fidelity F2 --test-frac 0.25 --json

退出码：0 成功；2 无样本；3 有效样本低于最小训练量（拒绝产出无意义模型）。
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

from memsharness.ml.surrogate import (  # noqa: E402
    MIN_ROWS_FOR_TRAINING,
    SurrogateEnsemble,
    discover_columns,
    grouped_split,
    load_samples,
    new_model_id,
    register_model,
    save_model,
    score,
    write_model_card,
)
from memsharness.store import connect  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="训练代理模型并写模型卡（状态 draft）")
    parser.add_argument("--fidelity", nargs="*", default=None, help="只使用指定保真度，如 F0 F1 F2")
    parser.add_argument("--test-frac", type=float, default=0.25, help="测试集比例（按几何族分组切分）")
    parser.add_argument("--members", type=int, default=5, help="深度集成成员数（用于不确定度）")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--json", action="store_true", help="仅输出机器可读结果")
    args = parser.parse_args(argv)

    # ---- 读数据（只读连接）----
    with connect(read_only=True) as conn:
        frame = load_samples(conn, fidelity=args.fidelity)
    if frame.empty:
        print("元数据库中没有可用样本：先跑一次参数扫描（scripts/run_sweep.py）", file=sys.stderr)
        return 2

    inputs, outputs = discover_columns(frame)
    if not inputs or not outputs:
        print(f"样本列不足：inputs={inputs} outputs={outputs}", file=sys.stderr)
        return 2

    frame = frame.dropna(subset=inputs + outputs)
    if len(frame) < MIN_ROWS_FOR_TRAINING:
        print(
            f"有效样本 {len(frame)} 条，低于最小训练量 {MIN_ROWS_FOR_TRAINING}；拒绝训练",
            file=sys.stderr,
        )
        return 3

    # ---- 切分 / 训练 / 评分 ----
    train, test, split_report = grouped_split(
        frame, group_col="geometry_family", test_frac=args.test_frac, seed=args.seed
    )
    model = SurrogateEnsemble(n_members=args.members, seed=args.seed)
    model.fit(train, inputs, outputs)
    card = score(model, train, test)

    model_id = args.model_id or new_model_id()
    model_dir = save_model(model, model_id)
    card_path = write_model_card(
        model_id,
        card,
        split_report,
        extras={
            "n_samples": len(frame),
            "inputs": inputs,
            "outputs": outputs,
            "fidelity_filter": args.fidelity,
            "source_types": sorted(frame["source_type"].dropna().unique().tolist()),
            "model_dir": str(model_dir),
        },
    )

    # ---- 登记（需要可写连接；状态固定 draft）----
    with connect() as conn:
        register_model(
            conn,
            model_id=model_id,
            card=card,
            card_path=card_path,
            algorithm="mlp_ensemble",
            uq_method="ensemble_std",
            hyperparams={"members": args.members, "hidden": list(model.hidden), "seed": args.seed},
            scope={"inputs": inputs, "outputs": outputs},
        )

    result = {
        "model_id": model_id,
        "state": "draft",
        "model_dir": str(model_dir),
        "model_card": str(card_path),
        "scorecard": card.to_dict(),
        "split": split_report,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print("=" * 68)
    print(f"模型 {model_id} 训练完成（状态：draft —— 不得用于工程判断，晋升需人工门禁）")
    print(
        f"样本：总 {len(frame)} / 训练 {card.n_train} / 测试 {card.n_test}"
        f"（切分策略：{split_report.get('strategy')}）"
    )
    print("-" * 68)
    for name, metrics in card.outputs.items():
        r2 = "n/a" if metrics["r2"] is None else f"{metrics['r2']:.4f}"
        rel = "n/a" if metrics["relative_rmse"] is None else f"{metrics['relative_rmse']:.4f}"
        print(f"  {name}: RMSE={metrics['rmse']:.6g}  MAE={metrics['mae']:.6g}  R2={r2}  相对RMSE={rel}")
    coverage = card.interval_coverage_90
    print(f"90% 区间覆盖率：{'n/a' if coverage is None else f'{coverage:.3f}'}")
    for warning in card.warnings:
        print(f"  [警告] {warning}")
    print("=" * 68)
    print(f"模型卡：{card_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
