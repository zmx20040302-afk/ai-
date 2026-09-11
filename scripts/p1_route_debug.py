"""P1 深入调试：找出「把场导出到固定规则网格」的可用路线（打印**完整**错误信息）。

已确认事实（见 scripts/mph_introspect.py 与 p1_field_grid_probe.py 的实测）：
- `comp.geom('geom1')` 可用；本机既有小模型是 **2D**
- Grid 数据集属性名为 `par1/parmin1/parmax1/res1`、来源数据集属性为 `data`
- 基线用 Eval 取值返回 35724 个点 = **网格节点数**（说明没走上网格数据集）
- 把 Eval 的 `data` 设为 `pgrid` 报「数据集类型无效」，但错误信息此前被截断

本脚本依次尝试两条路线，并把每条路线的**完整异常文本**打出来：
  路线 A：Grid2D 数据集 + 数值节点 Eval
  路线 B：Export → Data 节点（location=grid）直接写出规则网格 CSV

用法（经 ASCII 交汇点，-u 保证实时输出）：
    C:\\Users\\18161\\memsharness_work\\repo\\work\\.venv\\Scripts\\python.exe -u ^
      C:\\Users\\18161\\memsharness_work\\repo\\scripts\\p1_route_debug.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
COMSOL_HOME = os.environ.get("MEMS_COMSOL_HOME", r"D:\COMSOL64\Multiphysics")
os.environ["PATH"] = f"{Path(COMSOL_HOME) / 'bin' / 'win64'}{os.pathsep}{os.environ.get('PATH', '')}"
os.environ.setdefault("COMSOL_HOME", COMSOL_HOME)


def attempt(label: str, fn) -> object | None:
    """执行一次尝试；失败时打印**完整**异常（不截断）。"""
    try:
        value = fn()
        print(f"\n[OK ] {label}\n      -> {str(value)[:200]}", flush=True)
        return value
    except Exception as exc:
        print(f"\n[ERR] {label}\n      {type(exc).__name__}: {exc}", flush=True)
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

    comp = java.modelNode("comp1")
    geom = comp.geom("geom1")
    mesh = comp.mesh("mesh1")
    ndim = int(geom.getSDim())
    print(f"模型={model_path.name} 维度={ndim}D study={study}", flush=True)

    # 先解一次，保证有解
    model.solve(study)

    # ---------------- 路线 A：Grid 数据集 + Eval ----------------
    print("\n======== 路线 A：Grid2D 数据集 + Eval ========", flush=True)
    try:
        java.result().dataset().remove("pgrid")
    except Exception:
        pass
    ds = java.result().dataset().create("pgrid", "Grid2D")
    ds.set("data", "dset1")          # 来源数据集
    ds.set("par1", "x"); ds.set("parmin1", "0"); ds.set("parmax1", "4"); ds.set("res1", "31")
    ds.set("par2", "y"); ds.set("parmin2", "0"); ds.set("parmax2", "3"); ds.set("res2", "23")
    attempt("读取 Grid 数据集回读设置", lambda: {
        "data": ds.getString("data"), "par1": ds.getString("par1"),
        "parmin1": ds.getString("parmin1"), "parmax1": ds.getString("parmax1"),
        "res1": ds.getString("res1"), "type": ds.getType(),
    })
    attempt("列出数据集标签", lambda: [str(t) for t in java.result().dataset().tags()])

    try:
        java.result().numerical().remove("pev")
    except Exception:
        pass
    ev = java.result().numerical().create("pev", "Eval")
    ev.set("expr", "abs(p)")
    attempt("A1: Eval.set('data','pgrid')", lambda: ev.set("data", "pgrid"))
    attempt("A2: Eval.set('data','dset1')  (对照组)", lambda: ev.set("data", "dset1"))
    attempt("A3: 用 MPh evaluate 走 pgrid 名字", lambda: model.evaluate("abs(p)", dataset="pgrid"))
    attempt("A4: Eval 在 pgrid 上 getReal 的长度",
            lambda: (ev.set("data", "pgrid"), len(ev.getReal()[0]))[1])

    # ---------------- 路线 B：Export → Data（规则网格 CSV）----------------
    print("\n======== 路线 B：Export Data 节点（location=grid）========", flush=True)
    export_dir = _REPO_ROOT / "work" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    out_csv = export_dir / "p1_grid_export.csv"

    try:
        java.result().export().remove("data1")
    except Exception:
        pass
    exp = attempt("创建 export Data 节点",
                  lambda: java.result().export().create("data1", "Data"))
    if exp is not None:
        props = attempt("Data 节点属性列表",
                        lambda: sorted(str(p) for p in exp.properties())) or []
        # 打印与网格/表达式/文件相关的属性名，便于确定该填哪些
        interesting = [p for p in props if any(k in p.lower() for k in
                       ("expr", "data", "location", "grid", "file", "header", "precision", "separator", "sort"))]
        print(f"      关注属性: {interesting}", flush=True)

        def configure():
            exp.set("expr", ["abs(p)"])
            exp.set("data", "dset1")
            exp.set("location", "grid")
            # 规则网格的定义：COMSOL 用 gridx1/gridx2 表达式（range(start,step,stop)）
            for name, value in (("gridx1", "range(0,4/30,4)"), ("gridx2", "range(0,3/22,3)")):
                try:
                    exp.set(name, value)
                    print(f"      set {name} = {value}", flush=True)
                except Exception as exc:
                    print(f"      set {name} 失败: {type(exc).__name__}: {str(exc)[:120]}", flush=True)
            exp.set("filename", str(out_csv).replace("\\", "/"))
            return "configured"

        attempt("配置 Data 导出节点", configure)
        attempt("执行导出", lambda: (exp.run(), "run 完成")[1])
        attempt("导出文件是否存在/行数", lambda: {
            "path": str(out_csv), "exists": out_csv.is_file(),
            "lines": (sum(1 for _ in out_csv.open(encoding="utf-8", errors="replace"))
                      if out_csv.is_file() else 0),
        })
        if out_csv.is_file():
            head = out_csv.read_text(encoding="utf-8", errors="replace").splitlines()[:6]
            print("      文件前几行：", flush=True)
            for line in head:
                print(f"        {line}", flush=True)

    print("\n======== 调试结束 ========", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
