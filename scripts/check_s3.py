"""在**真实 COMSOL 解**上跑 S3 物理一致性检查（守恒 / 边界条件 / 对称性）。

用法（经 ASCII 交汇点）：
    C:\\Users\\18161\\memsharness_work\\repo\\work\\.venv\\Scripts\\python.exe -u ^
      C:\\Users\\18161\\memsharness_work\\repo\\scripts\\check_s3.py [--run <run_id>]

输出：S3 报告（verdict + 逐项 metric/threshold/reason + release_allowed）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
COMSOL_HOME = os.environ.get("MEMS_COMSOL_HOME", r"D:\COMSOL64\Multiphysics")
os.environ["PATH"] = f"{Path(COMSOL_HOME) / 'bin' / 'win64'}{os.pathsep}{os.environ.get('PATH', '')}"
os.environ.setdefault("COMSOL_HOME", COMSOL_HOME)

from memsharness import consistency as cs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="S3 物理一致性检查（真实解）")
    ap.add_argument("--run", default=None)
    ap.add_argument("--port", type=int, default=int(os.environ.get("MEMS_MPH_PORT", "2036")))
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    import mph
    import numpy as np

    runs = sorted((_REPO_ROOT / "work" / "runs").glob("run-*"), key=lambda p: p.stat().st_mtime)
    runs = [p for p in runs if (p / "out.mph").is_file()]
    run_dir = (runs and (_REPO_ROOT / "work" / "runs" / args.run)) if args.run else (runs[-1] if runs else None)
    assert run_dir and run_dir.is_dir(), "找不到含 out.mph 的 run"

    job = json.loads((run_dir / "job.json").read_text(encoding="utf-8"))
    p = job["params"]
    Lx, Ly, q, T0, k = (float(p["Lx"]), float(p["Ly"]), float(p["q_in"]), float(p["T0"]), float(p["k_cond"]))
    bnd_t, bnd_q = int(p["bnd_t"]), int(p["bnd_q"])
    dT_ref = q * Lx / k  # 解析温升

    client = mph.Client(port=args.port)
    try:
        client.clear()
    except Exception:
        pass
    model = client.load(run_dir / "out.mph")
    java = model.java

    def vec(expr: str) -> "np.ndarray":
        return np.asarray(model.evaluate(expr), dtype=float).ravel()

    xs, ys, T = vec("x"), vec("y"), vec("T")
    n = min(xs.size, ys.size, T.size)
    xs, ys, T = xs[:n], ys[:n], T[:n]

    # ---- 1) 守恒：直接比较**入口边**与**出口边**的通量积分（不依赖解析公式）----
    def edge_flux(tag: str, name: str) -> float:
        ev = java.result().numerical().create(name, "IntLine")
        ev.set("expr", "ht.ntflux")
        ev.selection().set([tag])
        try:
            ds = [str(t) for t in java.result().dataset().tags()]
            if ds:
                ev.set("data", ds[0])
        except Exception:
            pass
        return float(np.asarray(ev.getReal(), dtype=float).ravel()[0])

    flux_hot = edge_flux(bnd_q, "s3flux_hot")     # 入口边（热流）
    flux_cold = edge_flux(bnd_t, "s3flux_cold")   # 出口边（定温）
    # 用绝对值比较：符号取决于外法向方向，守恒判据只看量值是否相等
    c1 = cs.conservation_residual(
        influx=abs(flux_hot), outflux=abs(flux_cold), threshold=0.01, name="conservation_energy"
    )

    # ---- 2) 边界条件：**严格落在温度边**上的节点，T 应等于 T0（温升作尺度）----
    on_edge = np.isclose(xs, Lx, rtol=0.0, atol=1e-12) if bnd_t == 4 else np.isclose(xs, 0.0, rtol=0.0, atol=1e-12)
    if int(on_edge.sum()) < 3:
        c2 = cs.CheckResult("bc_temperature_edge", None, None, 1e-6, "温度边上节点不足 3 个，无法判定")
    else:
        c2 = cs.boundary_condition_residual(
            values=T[on_edge].tolist(), prescribed=T0, threshold=1e-6, scale=dT_ref, name="bc_temperature_edge"
        )

    # ---- 3) 对称性：一维沿 x 导热 ⇒ 场关于 y=Ly/2 镜像对称 ----
    coords = np.column_stack([xs, ys])
    c3 = cs.mirror_symmetry_residual(
        coords=coords, values=T, axis=1, axis_value=Ly / 2.0, threshold=0.02, scale=dT_ref, name="symmetry_y_mid"
    )

    report = cs.evaluate_s3([c1, c2, c3])
    report.update({
        "run_id": run_dir.name, "params": p, "analytic_rise_K": dT_ref,
        "flux_hot_edge_W_per_m": flux_hot, "flux_cold_edge_W_per_m": flux_cold,
        "hint": "入口边是 bnd_q、出口边是 bnd_t；两侧通量量值应相等（符号取决于外法向）",
    })

    out = Path(args.out) if args.out else (run_dir / "s3_report.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 70)
    print(f"S3 物理一致性检查 —— {run_dir.name}")
    print("=" * 70)
    for entry in report["checks"]:
        flag = {True: "通过", False: "**不通过**", None: "无法判定"}[entry["passed"]]
        metric = "n/a" if entry["metric"] is None else f"{entry['metric']:.3e}"
        print(f"  [{flag}] {entry['name']:<24} metric={metric:<12} thr={entry['threshold']}")
        if entry["reason"]:
            print(f"           {entry['reason']}")
    print("-" * 70)
    print(f"结论：{report['verdict']}｜允许放行：{report['release_allowed']}")
    print(f"守恒：热流边 {flux_hot:.6g} W/m，定温边 {flux_cold:.6g} W/m｜解析温升 {dT_ref:.6g} K")
    print(f"报告：{out}")
    return 0 if report["release_allowed"] else 2


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
