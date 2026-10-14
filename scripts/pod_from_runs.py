"""A6 真实数据验证：从真实 COMSOL 解的 out.mph 抽场快照 → POD → 留出**场级**相对 L2。

流程（即 P1 已验证的路线，产品化）：
1. 遍历含 out.mph 的 run（仅取边界配置正确的那批：bnd_q 与 bnd_t 为对边）；
2. 用 MPh 取节点坐标 x,y 与场值 T，插值到**同一套固定公共点集**（几何变化也能对齐）；
3. 组快照矩阵 → 公共掩膜 → POD 基 → 系数回归（线性）→ 留出快照上报场级相对 L2 与 S1 判定。

用法（在仓库根下执行）：
    work\\.venv\\Scripts\\python.exe -u ^
      scripts\\pod_from_runs.py
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

from memsharness import pod  # noqa: E402

GRID = (31, 23)          # 公共点集 31×23 = 713 点（与 onboard/P1 一致）
FIELD_EXPR = "T"         # 场量：温度


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="真实解 → 快照 → POD → 场级留出误差")
    ap.add_argument("--port", type=int, default=int(os.environ.get("MEMS_MPH_PORT", "2036")))
    ap.add_argument("--holdout", type=int, default=3, help="留出快照数")
    ap.add_argument("--out", default="work/reports/pod_from_runs.json")
    args = ap.parse_args(argv)

    import mph
    import numpy as np
    from scipy.interpolate import griddata

    # ---- 1) 收集可用的 run（只取边界对边、成功的那些）----
    runs_root = _REPO_ROOT / "work" / "runs"
    candidates = []
    for run_dir in sorted(runs_root.glob("run-*")):
        if not (run_dir / "out.mph").is_file():
            continue
        try:
            job = json.loads((run_dir / "job.json").read_text(encoding="utf-8"))
            result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        params = job.get("params") or {}
        if int(params.get("bnd_t", -1)) != 4 or int(params.get("bnd_q", -1)) != 1:
            continue  # 非对边配置的模型物理上不等价，不能混进同一个流形
        if not (result.get("result") or {}).get("T_max_K"):
            continue
        candidates.append((run_dir, params))
    if len(candidates) < 4:
        print(f"可用 run 只有 {len(candidates)} 个，不足以做 POD（需要 ≥4）", file=sys.stderr)
        return 2

    # ---- 2) 逐个取场并插值到固定公共点集 ----
    bbox_lx = max(float(p["Lx"]) for _, p in candidates)
    bbox_ly = max(float(p["Ly"]) for _, p in candidates)
    gx = np.linspace(0.0, bbox_lx, GRID[0])
    gy = np.linspace(0.0, bbox_ly, GRID[1])
    GX, GY = np.meshgrid(gx, gy)

    client = mph.Client(port=args.port)
    params_list, snapshots, used = [], [], []
    for run_dir, params in candidates:
        try:
            client.clear()
        except Exception:
            pass
        model = client.load(run_dir / "out.mph")
        xs = np.asarray(model.evaluate("x"), dtype=float).ravel()
        ys = np.asarray(model.evaluate("y"), dtype=float).ravel()
        vals = np.asarray(model.evaluate(FIELD_EXPR), dtype=float).ravel()
        n = min(xs.size, ys.size, vals.size)
        snap = griddata(np.column_stack([xs[:n], ys[:n]]), vals[:n], (GX, GY), method="linear").ravel()
        params_list.append({"q_in": float(params["q_in"]), "k_cond": float(params["k_cond"])})
        snapshots.append(snap)
        used.append(run_dir.name)
        print(f"  取场 {run_dir.name}: T∈[{np.nanmin(snap):.4g},{np.nanmax(snap):.4g}] "
              f"NaN={int(np.isnan(snap).sum())}", flush=True)

    # 去重（同参数只留一份，避免训练/留出同点）
    unique: dict[tuple, int] = {}
    for i, p in enumerate(params_list):
        unique.setdefault((p["q_in"], p["k_cond"]), i)
    idx = sorted(unique.values())
    params_list = [params_list[i] for i in idx]
    snapshots = [snapshots[i] for i in idx]
    used = [used[i] for i in idx]
    print(f"去重后 {len(params_list)} 个不同参数点：{[(p['q_in'], p['k_cond']) for p in params_list]}", flush=True)

    n_holdout = min(args.holdout, max(1, len(params_list) // 3))
    train_p, train_s = params_list[:-n_holdout], snapshots[:-n_holdout]
    hold_p, hold_s = params_list[-n_holdout:], snapshots[-n_holdout:]

    # ---- 3) 拟合 POD（线性系数）+ 保形校准，并在留出快照上评估 ----
    model = pod.fit(train_p, train_s, energy_ratio=0.999999, coeff_model="linear")
    # 保形校准：n 个校准点最多保证 n/(n+1)；因此目标覆盖率必须与样本量相容
    n_cal = len(train_p)
    max_alpha = 1.0 / (n_cal + 1)                 # 可认证的最小 α
    alpha = max(0.1, max_alpha)                   # 90% 做不到时退到能认证的水平
    conformal = model.calibrate(train_p, train_s, alpha=alpha, leave_one_out=True)
    report = pod.holdout_report(model, hold_p, hold_s)
    report.update({
        "runs_used": used,
        "n_params": len(params_list),
        "n_train": len(train_p),
        "n_holdout": n_holdout,
        "grid": {"nx": GRID[0], "ny": GRID[1]},
        "masked_points": int(model.mask.sum()),
        "n_modes": model.n_modes,
        "energy_ratio_actual": model.meta.get("cumulative_energy_at_n"),
        "singular_values": [float(v) for v in model.singular_values],
        "coeff_model": model.meta.get("coeff_model"),
        "conformal": conformal,
    })

    out = Path(args.out)
    if not out.is_absolute():
        out = _REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("POD 场级留出评估（真实 COMSOL 数据）")
    print("=" * 72)
    print(f"  参数点 {len(params_list)}（训练 {len(train_p)} / 留出 {n_holdout}）｜"
          f"公共点集掩膜后 {int(model.mask.sum())} 点｜模态数 {model.n_modes}")
    print(f"  基能量占比：{model.meta.get('cumulative_energy_at_n'):.10f}｜奇异值：{report['singular_values']}")
    for p, err in zip(hold_p, report["field_rel_l2"]):
        print(f"  留出 q_in={p['q_in']:.0f}, k={p['k_cond']:.1f} → 场级相对 L2 = {err:.3e}")
    print(f"  平均 {report['field_rel_l2_mean']:.3e}｜最大 {report['field_rel_l2_max']:.3e}｜"
          f"S1(≤5%) 判定：{'通过' if report['s1_passed'] else '**不通过**'}")
    target = (conformal.get("target_coverage") or 0) if conformal else 0
    print(f"  区间覆盖率实测 {report['interval_coverage_90']:.3f}"
          f"｜校准目标 {target:.1%}（n={conformal.get('n_calibration')} 个校准点，"
          f"90% 需 ≥9 点才可认证）")
    print(f"  S5 认证：{'是' if conformal.get('certified') else '否'}｜{conformal.get('guarantee')}")
    print(f"  报告：{out}")
    return 0 if report["s1_passed"] else 2


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
