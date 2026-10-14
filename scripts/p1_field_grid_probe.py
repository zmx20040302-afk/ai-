"""P1 技术验证：场快照能否对齐到同一套固定公共点集（POD 降阶的前提）。

## 结论性的技术选择（依据本轮多次实测）
尝试过并被否决的路线：
- **Grid 数据集 + Eval**：Eval 数值节点拒绝 Grid 数据集（「数据集类型无效」）——Grid 数据集只服务绘图/导出
- **Interp / 插值数据集**：在 batch/API 上下文中无法创建（「在这个情景中不能创建本操作」）
- **Export→Data (location=grid)**：`location` 能设成 `grid`，但网格定义未生效（导出节点数=0），
  且其属性族（`gridx1` vs `gridx1_vector_*` vs `regulargrid*`）需按版本摸索，稳定性差

**采用的路线（本脚本）**：
1. 用**已实测可用**的 MPh 求值取每个网格节点的**坐标**（`x`、`y`）与**场值**（如 `abs(p)`）；
2. 在 Python 侧把这些散点**插值到一套固定的公共点集**（规则网格）；
3. 于是无论几何/网格如何变化，每次快照都落在**同一批点、同一顺序**上 → 可直接做 POD。

优点：只依赖已验证的求值 API；与 COMSOL 版本/导出属性名解耦；几何变化时天然支持（域外点记为 NaN，用掩膜处理）。

## 用法（**必须经 ASCII 交汇点启动**，否则 JPype 因中文路径报 UnsatisfiedLinkError）
    work\\.venv\\Scripts\\python.exe -u ^
      scripts\\p1_field_grid_probe.py
"""

from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
COMSOL_HOME = os.environ.get("MEMS_COMSOL_HOME", r"D:\COMSOL64\Multiphysics")
COMSOL_BIN = Path(COMSOL_HOME) / "bin" / "win64"

GRID_NX, GRID_NY = 31, 23          # 公共点集：31×23 = 713 个点
L_BOX = {"x": 4.0, "y": 3.0}       # 由模型参数 Lx/Ly 得到（脚本内会回读校正）


def log(ev: dict, msg: str) -> None:
    ev["steps"].append(msg)
    print(f"[p1] {msg}", flush=True)


def flatten(values):
    import numpy as np

    arr = np.asarray(values, dtype=float)
    return arr.ravel()


def describe(arr) -> dict:
    import numpy as np

    finite = np.isfinite(arr)
    return {
        "count": int(arr.size),
        "finite_count": int(finite.sum()),
        "nan_count": int((~finite).sum()),
        "finite_ratio": float(finite.mean()) if arr.size else 0.0,
        "min": float(np.nanmin(arr)) if finite.any() else None,
        "max": float(np.nanmax(arr)) if finite.any() else None,
        "l2_norm": float(np.sqrt(np.nansum(arr**2))),
    }


def relative_l2(a, b) -> float | None:
    import numpy as np

    x, y = np.asarray(a, float).ravel(), np.asarray(b, float).ravel()
    if x.size != y.size or x.size == 0:
        return None
    mask = np.isfinite(x) & np.isfinite(y)
    if not mask.any():
        return None
    denom = float(np.sqrt(np.sum(x[mask] ** 2)))
    return float(np.sqrt(np.sum((x[mask] - y[mask]) ** 2)) / denom) if denom else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P1：场快照对齐到固定公共点集")
    ap.add_argument("--model", default=None)
    ap.add_argument("--port", type=int, default=int(os.environ.get("MEMS_MPH_PORT", "2036")))
    ap.add_argument("--expr", default="abs(p)")
    ap.add_argument("--material-param", default="c_air")
    ap.add_argument("--material-value", default="300[m/s]")
    ap.add_argument("--geometry-param", default="Lx")
    ap.add_argument("--geometry-value", default="3.5[m]")
    ap.add_argument("--out", default="work/reports/p1_field_grid.json")
    ap.add_argument("--npz", default="work/exports/p1_snapshots.npz")
    args = ap.parse_args(argv)

    os.environ["PATH"] = f"{COMSOL_BIN}{os.pathsep}{os.environ.get('PATH', '')}"
    os.environ.setdefault("COMSOL_HOME", COMSOL_HOME)

    ev: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "purpose": "验证场快照能否对齐到同一套固定公共点集（POD 前提 P1）",
        "route": "MPh 求值取节点坐标+场值 → Python 侧插值到固定规则点集",
        "rejected_routes": {
            "grid_dataset_plus_eval": "Eval 拒绝 Grid 数据集（数据集类型无效）",
            "interp_dataset": "batch/API 上下文无法创建插值数据集",
            "export_data_grid": "location=grid 可设但网格定义未生效（导出 0 节点），属性族随版本变化",
        },
        "expression": args.expr,
        "grid": {"nx": GRID_NX, "ny": GRID_NY},
        "ok": False,
        "steps": [],
        "errors": [],
    }

    model_path = Path(args.model) if args.model else None
    if model_path is None:
        cands = sorted((_REPO_ROOT / "work" / "runs").glob("*/input.mph"))
        model_path = cands[-1] if cands else None

    try:
        import mph
        import numpy as np
        from scipy.interpolate import griddata

        client = mph.Client(port=args.port)
        log(ev, f"连接 mphserver:{args.port} OK（COMSOL {client.version}，MPh {mph.__version__}）")
        assert model_path and Path(model_path).is_file(), f"找不到模型副本: {model_path}"
        ev["model_path"] = str(model_path)
        model = client.load(model_path)
        java = model.java
        study = [str(s) for s in model.studies()][0]
        log(ev, f"加载 {Path(model_path).name}，研究 = {study}")

        comp = java.modelNode(str(java.modelNode().tags()[0]))
        geom = comp.geom(str(comp.geom().tags()[0]))
        mesh = comp.mesh(str(comp.mesh().tags()[0]))
        ndim = int(geom.getSDim())
        ev["space_dim"] = ndim
        log(ev, f"维度 = {ndim}D")

        # 公共点集：覆盖包围盒的固定规则网格（域外点后续以 NaN 处理）
        for key, default in (("Lx", 4.0), ("Ly", 3.0)):
            try:
                numeric = "".join(ch for ch in str(java.param().get(key)) if ch.isdigit() or ch in ".-")
                if numeric:
                    L_BOX[key[-1].lower()] = float(numeric)
            except Exception:
                pass
        ev["box"] = dict(L_BOX)
        gx = np.linspace(0.0, L_BOX["x"], GRID_NX)
        gy = np.linspace(0.0, L_BOX["y"], GRID_NY)
        GX, GY = np.meshgrid(gx, gy)
        log(ev, f"公共点集：{GRID_NX}×{GRID_NY} = {GX.size} 点，包围盒 {L_BOX}")

        def snapshot() -> tuple:
            """取当前解的 (节点坐标, 场值)，再插值到公共点集。"""
            xs = flatten(model.evaluate("x"))
            ys = flatten(model.evaluate("y"))
            vals = flatten(model.evaluate(args.expr))
            n = min(xs.size, ys.size, vals.size)
            pts = np.column_stack([xs[:n], ys[:n]])
            zi = griddata(pts, vals[:n], (GX, GY), method="linear")
            return {"n_nodes": int(n), "xs": xs[:n], "ys": ys[:n], "vals": vals[:n], "grid_values": zi}

        # ---- 1) 基线 ----
        t0 = time.perf_counter()
        model.solve(study)
        ev["baseline_solve_seconds"] = round(time.perf_counter() - t0, 1)
        base = snapshot()
        ev["baseline"] = {"n_nodes": base["n_nodes"], **describe(base["grid_values"])}
        log(ev, f"基线：求解 {ev['baseline_solve_seconds']}s，网格节点 {base['n_nodes']} 个 → "
                f"插值到公共点集后 {ev['baseline']['count']} 点，NaN={ev['baseline']['nan_count']}")

        # ---- 2) 材料参数（几何不变）----
        case_m = None
        try:
            java.param().set(args.material_param, args.material_value)
            model.solve(study)
            snap = snapshot()
            case_m = {
                "param": args.material_param, "value": args.material_value,
                "n_nodes": snap["n_nodes"], **describe(snap["grid_values"]),
                "same_length": bool(snap["grid_values"].size == base["grid_values"].size),
                "rel_l2_vs_baseline": relative_l2(base["grid_values"], snap["grid_values"]),
            }
            ev["material_case"] = case_m
            log(ev, f"材料参数：等长={case_m['same_length']}，相对L2={case_m['rel_l2_vs_baseline']}")
        except Exception as exc:
            ev["errors"].append(f"材料用例: {type(exc).__name__}: {exc}")

        # ---- 3) 几何参数（重建几何+网格；POD 最关心这一条）----
        case_g = None
        try:
            java.param().set(args.geometry_param, args.geometry_value)
            geom.run()
            mesh.run()
            model.solve(study)
            snap = snapshot()
            case_g = {
                "param": args.geometry_param, "value": args.geometry_value,
                "n_nodes": snap["n_nodes"], **describe(snap["grid_values"]),
                "same_length": bool(snap["grid_values"].size == base["grid_values"].size),
                "rel_l2_vs_baseline": relative_l2(base["grid_values"], snap["grid_values"]),
                "note": "几何缩小后，公共点集中落在域外的点会变成 NaN（需掩膜）",
            }
            ev["geometry_case"] = case_g
            log(ev, f"几何参数：等长={case_g['same_length']}，域外NaN={case_g['nan_count']}，"
                    f"相对L2={case_g['rel_l2_vs_baseline']}")
            # 保存三组快照，供后续 POD 试验
            npz = Path(args.npz)
            if not npz.is_absolute():
                npz = _REPO_ROOT / npz
            npz.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(npz, gx=gx, gy=gy, base=base["grid_values"],
                                material=snap["grid_values"])
            ev["snapshot_file"] = str(npz)
        except Exception as exc:
            ev["errors"].append(f"几何用例: {type(exc).__name__}: {exc}")

        # ---- 结论 ----
        lengths = [c["same_length"] for c in (case_m, case_g) if c]
        aligned = bool(base["grid_values"].size == GX.size and lengths and all(lengths))
        base_desc = ev["baseline"]          # 基线统计（含 nan_count），注意别与上面 base（快照）混淆
        ev["conclusion"] = {
            "public_point_set_size": int(GX.size),
            "grid_export_works": bool(base["grid_values"].size == GX.size),
            "snapshots_aligned_across_parameter_changes": aligned,
            "point_count_stable_across_geometry_change": bool(case_g and case_g["same_length"]),
            "nan_handling_required": bool(
                base_desc["nan_count"] > 0
                or any(c["nan_count"] > 0 for c in (case_m, case_g) if c)
            ),
            "note": (
                "公共点集固定且各次快照等长 → POD 可直接做；"
                + ("几何变化会引入域外 NaN，必须用掩膜；" if case_g and case_g["nan_count"] else "")
                + "实现方式为 Python 侧插值，不依赖 COMSOL Grid 导出"
            ) if aligned else "未确认对齐：查看 errors 与各 case 明细",
        }
        ev["ok"] = aligned
        log(ev, f"结论：{ev['conclusion']}")
    except Exception as exc:
        ev["errors"].append(f"fatal: {type(exc).__name__}: {exc}")
        ev["traceback"] = traceback.format_exc()
        print(f"[p1][ERROR] {exc}", flush=True)

    out = Path(args.out)
    if not out.is_absolute():
        out = _REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ev, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("=" * 68)
    print(f"P1 结论：ok={ev['ok']}")
    if ev.get("conclusion"):
        print(f"  {ev['conclusion']}")
    for err in ev["errors"][:5]:
        print(f"  [错误] {err}")
    print(f"证据：{out}")
    print("=" * 68)
    return 0 if ev["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
