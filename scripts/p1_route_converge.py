"""P1 路线收敛：确定「固定网格场导出」的可用方式。

已知实测结论：
- Eval 数值节点**拒绝** Grid2D 数据集（「数据集类型无效」），Grid 数据集只服务绘图/导出
- Export→Data 节点可运行，但我的 `location=grid` 配置没生效（导出节点数=0）

本脚本验证两条候选路线，并打印回读值以确认哪些设置真正生效：
  路线 B：Export→Data，逐个试 `location` 的候选取值，回读确认，再统计导出行数
  路线 E：**Interp 数据集**（按坐标文件插值）——它是"解派生"数据集，Eval 应能接受；
          这条路线最贴合 POD：坐标文件固定 → 每次求值都落在同一批点上

用法（经 ASCII 交汇点）：
    C:\\Users\\18161\\memsharness_work\\repo\\work\\.venv\\Scripts\\python.exe -u ^
      C:\\Users\\18161\\memsharness_work\\repo\\scripts\\p1_route_converge.py
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
COMSOL_HOME = os.environ.get("MEMS_COMSOL_HOME", r"D:\COMSOL64\Multiphysics")
os.environ["PATH"] = f"{Path(COMSOL_HOME) / 'bin' / 'win64'}{os.pathsep}{os.environ.get('PATH', '')}"
os.environ.setdefault("COMSOL_HOME", COMSOL_HOME)

# 固定网格：4×3 的矩形腔，取 31×23 个点
GRID = {"nx": 31, "ny": 23, "Lx": 4.0, "Ly": 3.0}


def show(label: str, fn) -> object | None:
    try:
        value = fn()
        print(f"[OK ] {label}: {str(value)[:220]}", flush=True)
        return value
    except Exception as exc:
        print(f"[ERR] {label}: {type(exc).__name__}: {str(exc)[:220]}", flush=True)
        return None


def main() -> int:
    import mph

    candidates = sorted((_REPO_ROOT / "work" / "runs").glob("*/input.mph"))
    assert candidates, "找不到模型副本"
    model_path = candidates[-1]
    client = mph.Client(port=int(os.environ.get("MEMS_MPH_PORT", "2036")))
    model = client.load(model_path)
    java = model.java
    study = [str(s) for s in model.studies()][0]
    model.solve(study)
    print(f"模型={model_path.name} study={study}", flush=True)

    # ---------- 固定坐标点文件（POD 的公共采样点）----------
    pts_dir = _REPO_ROOT / "work" / "exports"
    pts_dir.mkdir(parents=True, exist_ok=True)
    pts_file = pts_dir / "pod_points.txt"
    with pts_file.open("w", encoding="utf-8") as fh:
        for iy in range(GRID["ny"]):
            for ix in range(GRID["nx"]):
                x = GRID["Lx"] * ix / (GRID["nx"] - 1)
                y = GRID["Ly"] * iy / (GRID["ny"] - 1)
                fh.write(f"{x:.6f} {y:.6f}\n")
    n_points = GRID["nx"] * GRID["ny"]
    print(f"坐标点文件：{pts_file}（{n_points} 个点）", flush=True)

    # ================= 路线 E：Interp 数据集 + Eval =================
    print("\n======== 路线 E：Interp 数据集 + Eval ========", flush=True)
    created = None
    for type_name in ("Interp", "Interpolation", "Grid2D"):
        try:
            java.result().dataset().remove("pinterp")
        except Exception:
            pass
        ds = show(f"创建数据集类型 {type_name}", lambda t=type_name: java.result().dataset().create("pinterp", t))
        if ds is None:
            continue
        props = show("  属性列表", lambda d=ds: sorted(str(p) for p in d.properties())) or []
        interesting = [p for p in props if any(k in p.lower() for k in ("coord", "data", "file", "interp", "method", "def"))]
        print(f"  关注属性: {interesting}", flush=True)
        coord_prop = next((p for p in props if "coord" in p.lower() and "file" in p.lower()), None) \
            or next((p for p in props if p.lower() in ("coordfilename", "filename")), None)
        if coord_prop:
            ok_data = show("  设置 data=dset1", lambda d=ds: d.set("data", "dset1"))
            ok_coord = show(f"  设置 {coord_prop}=坐标文件",
                            lambda d=ds, p=coord_prop: d.set(p, str(pts_file).replace(chr(92), "/")))
            if ok_data is not None and ok_coord is not None:
                created = (type_name, ds)
                break

    if created:
        type_name, ds = created
        try:
            java.result().numerical().remove("pev")
        except Exception:
            pass
        ev = java.result().numerical().create("pev", "Eval")
        ev.set("expr", "abs(p)")
        set_ok = show("Eval.set('data','pinterp')", lambda: ev.set("data", "pinterp"))
        if set_ok is not None:
            vals = show("Eval.getReal() 点数", lambda: len(ev.getReal()[0]))
            print(f"  → 路线 E 可用性：类型={type_name}，取值点数={vals}（期望 {n_points}）", flush=True)

    # ================= 路线 B：Export Data（逐个试 location）=================
    print("\n======== 路线 B：Export Data 逐个试 location ========", flush=True)
    try:
        java.result().export().remove("data2")
    except Exception:
        pass
    exp = show("创建 export Data", lambda: java.result().export().create("data2", "Data"))
    if exp is not None:
        exp.set("expr", ["abs(p)"])
        exp.set("data", "dset1")
        for loc in ("grid", "regulargrid", "fromdataset", "Grid", "RegularGrid"):
            try:
                exp.set("location", loc)
            except Exception as exc:
                print(f"  location={loc!r} 设置失败: {str(exc)[:100]}", flush=True)
                continue
            readback = exp.getString("location")
            print(f"  location 设为 {loc!r} → 回读 {readback!r}", flush=True)
            if readback.lower() != loc.lower():
                continue
            # 网格定义：表达式形式 + 规则网格属性都试
            for name, value in (("gridx1", f"range(0,{GRID['Lx']/(GRID['nx']-1)},{GRID['Lx']})"),
                                ("gridx2", f"range(0,{GRID['Ly']/(GRID['ny']-1)},{GRID['Ly']})")):
                try:
                    exp.set(name, value)
                except Exception as exc:
                    print(f"    {name} 失败: {str(exc)[:90]}", flush=True)
            for name, value in (("regulargridx1", str(GRID["nx"])), ("regulargridx2", str(GRID["ny"]))):
                try:
                    exp.set(name, value)
                except Exception:
                    pass
            csv = pts_dir / f"p1_export_{loc}.csv"
            exp.set("filename", str(csv).replace("\\", "/"))
            show("  执行导出", lambda: (exp.run(), "ok")[1])
            if csv.is_file():
                lines = csv.read_text(encoding="utf-8", errors="replace").splitlines()
                data_lines = [ln for ln in lines if ln and not ln.startswith("%")]
                print(f"  → 文件 {csv.name}: 总行={len(lines)} 数据行={len(data_lines)}"
                      f"（期望 {n_points}）", flush=True)
                if data_lines[:2]:
                    print(f"    示例: {data_lines[0][:120]}", flush=True)

    print("\n======== 收敛测试结束 ========", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
