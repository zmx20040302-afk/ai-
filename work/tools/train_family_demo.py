"""按「器件族」过滤的代理模型训练驱动（复现历史 A3 口径）。

为什么需要这个脚本（实测事实，2026-09-11）：
    ``scripts/train_surrogate.py`` 只支持按 ``--fidelity`` 过滤，不支持按器件族过滤。
    而当前 ``work/store/mems.duckdb`` 的 ``sample`` 表里混有**多个器件族**的样本：
        heat_slab_2d   : k_cond/q_in/T0/...  -> T_max_K/T_min_K
        cantilever_2d  : E/L/h/nu/p_load/... -> d_tip_m
    ``discover_columns`` 取的是**并集**列，跨族样本在对方族的列上全是 NaN，
    于是在 ``dropna`` 后剩 0 条，CLI 报「有效样本 0 条，低于最小训练量」。
    实测：F2 组 49 条中键全齐的 0 条；F0 组 423 条中键全齐的 0 条。

本脚本不改仓库代码，只做一件 CLI 缺的事：**先按 geometry_family 过滤，再走仓库原有
的训练/评分/落盘/登记函数**，从而复现历史模型卡的口径（fidelity=F2，source=simulation，
族=GF-heat-slab-2d）。

来源声明（AGENTS.md 红线 4/8）：本脚本只用**单一来源**训练，且训练前会断言这一点；
混源训练必须显式声明，本脚本拒绝混源。

用法：
    python work\\tools\\train_family_demo.py --family GF-heat-slab-2d --fidelity F2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from memsharness.ml.surrogate import (  # noqa: E402
    MIN_ROWS_FOR_TRAINING,
    SurrogateEnsemble,
    discover_columns,
    drop_constant_columns,
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
    ap = argparse.ArgumentParser(description="按器件族过滤的代理模型训练（单一来源）")
    ap.add_argument("--family", required=True, help="geometry_family，如 GF-heat-slab-2d")
    ap.add_argument("--fidelity", nargs="*", default=None, help="保真度过滤，如 F2")
    ap.add_argument("--test-frac", type=float, default=0.25)
    ap.add_argument("--members", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model-id", default=None)
    args = ap.parse_args(argv)

    with connect(read_only=True) as conn:
        all_frame = load_samples(conn, fidelity=args.fidelity)
    if all_frame.empty:
        print("元数据库中没有符合条件的样本", file=sys.stderr)
        return 2

    frame = all_frame[all_frame["geometry_family"] == args.family].copy()
    print(
        f"[过滤] fidelity={args.fidelity} 全量 {len(all_frame)} 条 "
        f"-> 族 {args.family} {len(frame)} 条"
    )
    if frame.empty:
        print(f"族 {args.family} 没有样本", file=sys.stderr)
        return 2

    # 关键一步：``load_samples`` 展开的是**全表 JSON 键的并集**，按行过滤族之后，
    # 其它族的列仍然存在且在本族内**整列全 NaN**；若不先丢弃全空列，
    # discover_columns 会把这些列也当成自变量/目标，dropna 会把所有样本删光。
    before_cols = len(frame.columns)
    frame = frame.dropna(axis=1, how="all")
    if len(frame.columns) != before_cols:
        print(f"[过滤] 丢弃整列全空的跨族列 {before_cols - len(frame.columns)} 个")

    inputs, outputs = discover_columns(frame)
    frame = frame.dropna(subset=inputs + outputs)
    if len(frame) < MIN_ROWS_FOR_TRAINING:
        print(
            f"有效样本 {len(frame)} 条，低于最小训练量 {MIN_ROWS_FOR_TRAINING}；拒绝训练",
            file=sys.stderr,
        )
        return 3

    # ---- 来源声明与硬断言：拒绝混源训练 ----
    source_types = sorted(frame["source_type"].dropna().unique().tolist())
    print(f"[来源] source_type={source_types}  fidelity={sorted(frame['fidelity'].dropna().unique())}")
    if len(source_types) != 1:
        print(f"拒绝训练：样本混用了多个来源 {source_types}（须显式声明）", file=sys.stderr)
        return 3

    inputs, dropped = drop_constant_columns(frame, inputs)
    if dropped:
        print(f"[提示] 剔除恒定输入列：{dropped}")
    if not inputs:
        print("所有输入列恒定，无可训练自变量", file=sys.stderr)
        return 3

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
            "dropped_constant_inputs": dropped,
            "outputs": outputs,
            "fidelity_filter": args.fidelity,
            "source_types": source_types,
            "geometry_family_filter": args.family,
            "model_dir": str(model_dir),
            "driver": "work/tools/train_family_demo.py（CLI 缺族过滤的替代驱动）",
        },
    )
    with connect() as conn:
        register_model(
            conn,
            model_id=model_id,
            card=card,
            card_path=card_path,
            algorithm="mlp_ensemble",
            uq_method="ensemble_std",
            hyperparams={"members": args.members, "hidden": list(model.hidden), "seed": args.seed},
            scope={"inputs": inputs, "outputs": outputs, "geometry_family": args.family},
        )

    result = {
        "model_id": model_id,
        "state": "draft",
        "model_card": str(card_path),
        "scorecard": card.to_dict(),
        "split": split_report,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("=" * 68)
    print(f"模型 {model_id}（draft —— 不得用于工程判断，晋升需人工门禁）")
    print(f"样本：总 {len(frame)} / 训练 {card.n_train} / 测试 {card.n_test}")
    for name, m in card.outputs.items():
        r2 = "n/a" if m["r2"] is None else f"{m['r2']:.4f}"
        print(f"  {name}: RMSE={m['rmse']:.6g}  R2={r2}")
    for w in card.warnings:
        print(f"  [警告] {w}")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
