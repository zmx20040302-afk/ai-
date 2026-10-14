"""诊断：读取 heat_slab_2d 生成模型的解，判定边界条件实际落在哪条边上。

背景（A2 未决疑点）：模拟 T_max = 308.85 K，而模板解析预期 = 310 K（ΔT = q_in·Lx/k = 10 K）。
网格从 56 加密到 828 单元时 T_max 只变 1e-8，所以差异**不是离散误差**，而是建模/边界条件。

判定思路：找出**热点（T 最大处）的坐标**，它直接告诉我们是哪种情形：
- 热点在 x=Lx 的整条边上、且等温 → 一维沿 x 导热（解析假设）→ 期望 310 K
- 热点在某个角点附近 → 二维扩散（热流与低温边不在对边）→ T_max 低于一维估计
- 热点在 y=Ly 边上 → 一维沿 y 导热 → 期望 300 + q·Ly/k = 308 K

用法（在仓库根下执行）：
    work\\.venv\\Scripts\\python.exe -u ^
      scripts\\diag_heat_slab.py [--run <run_id>]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
COMSOL_HOME = os.environ.get("MEMS_COMSOL_HOME", r"D:\COMSOL64\Multiphysics")
os.environ["PATH"] = f"{Path(COMSOL_HOME) / 'bin' / 'win64'}{os.pathsep}{os.environ.get('PATH', '')}"
os.environ.setdefault("COMSOL_HOME", COMSOL_HOME)


def flatten(values):
    import numpy as np

    return np.asarray(values, dtype=float).ravel()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="判定 heat_slab_2d 的边界条件落点")
    ap.add_argument("--run", default=None, help="run_id（默认取最近一个成功的 run）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("MEMS_MPH_PORT", "2036")))
    args = ap.parse_args(argv)

    import mph
    import numpy as np

    runs_root = _REPO_ROOT / "work" / "runs"
    if args.run:
        run_dir = runs_root / args.run
    else:
        candidates = [p for p in sorted(runs_root.glob("run-*")) if (p / "out.mph").is_file()]
        assert candidates, "找不到含 out.mph 的 run"
        run_dir = candidates[-1]

    job = json.loads((run_dir / "job.json").read_text(encoding="utf-8"))
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    params = job.get("params", {})
    Lx, Ly = float(params.get("Lx", 0.01)), float(params.get("Ly", 0.008))
    q, k, T0 = float(params.get("q_in", 1000.0)), float(params.get("k_cond", 1.0)), float(params.get("T0", 300.0))

    print(f"run = {run_dir.name}")
    print(f"参数: Lx={Lx} m, Ly={Ly} m, q_in={q} W/m^2, k={k} W/(m*K), T0={T0} K")
    print(f"解析预期: 沿x一维 ΔT=q·Lx/k={q * Lx / k:.4f} K → T_max={T0 + q * Lx / k:.4f} K")
    print(f"          沿y一维 ΔT=q·Ly/k={q * Ly / k:.4f} K → T_max={T0 + q * Ly / k:.4f} K")
    print(f"模拟结果: {json.dumps(result.get('result'), ensure_ascii=False)}")

    client = mph.Client(port=args.port)
    try:
        client.clear()
    except Exception:
        pass
    model = client.load(run_dir / "out.mph")
    java = model.java

    xs, ys, T = flatten(model.evaluate("x")), flatten(model.evaluate("y")), flatten(model.evaluate("T"))
    n = min(xs.size, ys.size, T.size)
    xs, ys, T = xs[:n], ys[:n], T[:n]
    print(f"\n节点数 = {n};  x∈[{xs.min():.4g},{xs.max():.4g}]  y∈[{ys.min():.4g},{ys.max():.4g}]")
    print(f"T ∈ [{T.min():.4f}, {T.max():.4f}] K")

    hot = int(np.argmax(T))
    print(f"\n热点: x={xs[hot]:.6g}, y={ys[hot]:.6g}, T={T[hot]:.4f} K")
    # 热点是否落在某条边上：取 T 接近最大值的节点，看它们的坐标分布
    near = T > (T.max() - 1e-6)
    print(f"与热点等温(±1e-6)的节点数 = {int(near.sum())}")
    if near.sum() > 0:
        print(f"  这些节点的 x 范围 [{xs[near].min():.6g},{xs[near].max():.6g}]  "
              f"y 范围 [{ys[near].min():.6g},{ys[near].max():.6g}]")

    corners = {(0.0, 0.0): "左下", (Lx, 0.0): "右下", (0.0, Ly): "左上", (Lx, Ly): "右上"}
    print("\n四角温度（取最近节点）：")
    for (cx, cy), name in corners.items():
        dist = (xs - cx) ** 2 + (ys - cy) ** 2
        idx = int(np.argmin(dist))
        print(f"  {name} ({cx:g},{cy:g}): T={T[idx]:.4f} K  (距该角 {np.sqrt(dist[idx]):.3g} m)")

    # 物理场与材料的关键设置（读不到就如实报 null）
    try:
        phys = java.component("comp1").physics("ht")
        for feat in ("temp1", "hf1"):
            sel = [int(v) for v in phys.feature(feat).selection().entities()]
            print(f"\n物理特征 {feat}: 类型={phys.feature(feat).getType()} 选择实体={sel}")
        print(f"  temp1.T0 = {phys.feature('temp1').getString('T0')}")
        print(f"  hf1.q0   = {phys.feature('hf1').getString('q0')}")
    except Exception as exc:
        print(f"\n[读物理特征失败] {type(exc).__name__}: {exc}")

    try:
        mat = java.component("comp1").material("mat1").propertyGroup("def")
        kexpr = mat.getString("thermalconductivity")
        print(f"\n材料热导率表达式 = {kexpr!r} → 求值 = {java.param().evaluate(kexpr)}")
    except Exception as exc:
        print(f"[读材料失败] {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
