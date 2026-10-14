"""基线求解的后处理：从已求解的 `out.mph` 算**逐频点**目标量曲线，并把落档改紧凑。

为什么需要它：
    `baseline_solve.py` 首版把 ``model.evaluate(expr)`` 的**整段数组**写进了 JSON
    （abs(p) 773,444 个值、u 3,463,040 个值 → baseline.json 膨胀到 198 MB），
    而且那只是「求值集上的最大幅值」一个标量，**没有逐频点曲线**。
    正确口径是用 MPh 的 ``evaluate(expr, inner=[i])`` 按频率索引单独求值，再对节点取最大幅值。

本脚本**不重新求解**：直接载入 run 目录里已保存的 ``out.mph``（求解已发生过），
所以代价只有一次载入 + N×目标量 次求值。

用法：
    python scripts\\baseline_postprocess.py --run-dir work\\runs\\baseline-2026...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from memsharness.paths import work_root  # noqa: E402


def finite_max(values) -> float | None:
    import numpy as np

    arr = np.asarray(values)
    if np.iscomplexobj(arr):
        arr = np.abs(arr)
    arr = np.asarray(arr, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(arr.max())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="基线求解后处理：逐频点目标量曲线")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--port", type=int, default=2036)
    ap.add_argument("--dataset", default=None, help="指定解数据集名（缺省用默认）")
    args = ap.parse_args(argv)

    # --run-dir 既接受 run_id（如 baseline-2026...），也接受相对/绝对路径
    raw_arg = Path(args.run_dir)
    if raw_arg.is_absolute():
        run_dir = raw_arg
    else:
        candidates = [
            work_root() / "runs" / raw_arg,
            _REPO_ROOT / raw_arg,
            work_root() / raw_arg,
        ]
        run_dir = next(
            (c for c in candidates if (c / "out.mph").is_file()),
            candidates[0],
        )
    out_mph = run_dir / "out.mph"
    if not out_mph.is_file():
        print(f"[错误] 找不到已求解模型：{out_mph}", file=sys.stderr)
        return 2
    baseline_path = run_dir / "baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.is_file() else {}
    expressions = list((baseline.get("targets") or {}).keys()) or ["abs(p)", "u", "w", "V"]

    import socket

    import mph

    def port_open(port: int, timeout: float = 1.5) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                return True
        except OSError:
            return False

    print(f"载入已求解模型（不重新求解）：{out_mph}")
    if port_open(args.port):
        client = mph.Client(port=args.port)
    else:
        client = mph.start(cores=1, port=args.port)
    model = client.load(str(out_mph))
    print(f"载入完成：{model.name()}（COMSOL {client.version}）")

    import numpy as np

    # 频率轴：**必须按 inner 索引逐个回读**，不能假设 `evaluate('freq')` 的顺序
    # 与 `evaluate(expr, inner=[i])` 的索引一致。
    # 实测教训（2026-09-12）：7 点模型上顺序取到的轴是 [5,10,15,20,25,30,35] MHz，
    # 但 inner=[3] 的场值对应的其实是 **15 MHz**（用单频点 15 MHz 独立求解验证过），
    # 直接 zip 会把整张表标注错位。
    probed = model.evaluate("freq")
    n = len(np.asarray(probed, dtype=float).ravel())
    index_freqs: list[float] = []
    for index in range(n):
        value = np.asarray(model.evaluate("freq", inner=[index]), dtype=float).ravel()
        index_freqs.append(float(value[0]) if value.size else float("nan"))
    print(f"解数量（inner 索引数）：{n}")
    print(f"  轴顺序值       : {[f'{v/1e6:g}' for v in np.asarray(probed, dtype=float).ravel()]} MHz")
    print(f"  逐索引回读频率 : {[f'{v/1e6:g}' for v in index_freqs]} MHz")
    if list(np.asarray(probed, dtype=float).ravel()) != index_freqs:
        print("  ⚠️ 轴顺序 ≠ 解索引顺序：曲线按**逐索引回读值**标注（这正是不直接 zip 的原因）")

    curves: dict[str, list[dict]] = {}
    for expr in expressions:
        points: list[dict] = []
        for index in range(n):
            try:
                values = model.evaluate(expr, inner=[index])
            except Exception as exc:
                print(f"  [警告] {expr} @ inner={index} 求值失败：{type(exc).__name__}: {exc}")
                points.append({"inner_index": index, "frequency_hz": index_freqs[index], "value": None})
                continue
            points.append(
                {
                    "inner_index": index,
                    "frequency_hz": index_freqs[index],
                    "value": finite_max(values),
                }
            )
        curves[expr] = points
        shown = [None if p["value"] is None else f"{p['value']:.4g}" for p in points]
        print(f"  {expr:8s} 逐频点最大幅值 = {shown}")

    compact = {
        "run_id": baseline.get("run_id", run_dir.name),
        "source": "out.mph（求解产物）+ MPh evaluate(inner=[i]) 逐索引求值",
        "out_mph": str(out_mph),
        "n_solutions": n,
        "axis_order_hz": [float(v) for v in np.asarray(probed, dtype=float).ravel()],
        "index_frequency_hz": index_freqs,
        "curves": curves,
        "curve_definition": "每个解索引上对求值集取 |值| 的最大值；频率按**逐索引回读**标注（不是轴顺序）",
    }
    targets_path = run_dir / "baseline_targets.json"
    targets_path.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"逐频点曲线落档：{targets_path}")

    if baseline:
        baseline.pop("target_series", None)
        baseline["target_curves"] = curves
        baseline["target_curves_note"] = (
            "逐频点最大幅值由 baseline_postprocess.py 从 out.mph 现算；"
            "首版曾把整段原始数组写入本文件（膨胀到 198 MB）已移除——"
            "原始场数据可由 out.mph + 该脚本复现。"
        )
        baseline_path.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"紧凑化后 baseline.json：{baseline_path.stat().st_size/1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    import os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
