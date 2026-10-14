"""用 MPh（运行态）读取研究步的**扫描取值**与网格统计，补齐 probe 读不到的部分。

背景（对应「第一次阅读」的缺口②a）：
    modelio 的 Java 探针只返回研究步的属性**名**清单，读不到 `plist`/`pname` 等取值。
    本脚本连到 mphserver（`-login auto`），载入模型（**不保存**），用 Java API 读：
      - 每个研究步的类型与关键取值（`plist`/`plistarr`/`pname`/`punit`/`sweeptype`…）
      - 参数表的名称与表达式（与 probe 交叉核对）
      - 网格单元/顶点数、几何计数
    读到的每一项都标明来源属性名，便于回溯（AGENTS.md 红线 1）。

用法：
    python work\\tools\\mph_read_study.py "C:\\Users\\zmx\\Desktop\\b_GE_task3_2-new.mph"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

PROPS_OF_INTEREST = (
    "plist", "plistarr", "pname", "punit", "sweeptype", "pcontinuationmode",
    "loadparameters", "usefrequnit", "pdistrib", "keepsol", "paramselect",
)


def read_prop(feature, name: str) -> str:
    """读一个字符串属性；读不到时返回可识别的标记。

    注意：JPype 返回的是 ``java.lang.String``（没有 Python 的 ``startswith`` 等方法），
    所以这里统一先 ``str()`` 转换，避免调用方踩类型坑（实测踩过）。
    """
    try:
        value = feature.getString(name)
    except Exception as exc:  # 属性不存在/类型不符
        return f"<读不到: {type(exc).__name__}>"
    return str(value)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MPh 运行态读取研究步取值")
    ap.add_argument("model", help=".mph 路径（只读载入，不保存）")
    ap.add_argument("--port", type=int, default=2036)
    ap.add_argument("--out", default=None, help="结果 JSON 落点")
    args = ap.parse_args(argv)

    import mph

    model_path = Path(args.model)
    if not model_path.is_file():
        print(f"[错误] 模型不存在：{model_path}", file=sys.stderr)
        return 2

    print(f"# 连接 mphserver 127.0.0.1:{args.port} …")
    # 用 Client(port=...) 连**已存在**的服务端；mph.start() 会另起一个服务端实例
    # （AGENTS.md：求解环节单实例串行，不要起第二个服务端）
    client = mph.Client(port=args.port)
    print(f"# 已连接：{client}")
    print(f"# 载入（只读，不保存）：{model_path}")
    model = client.load(str(model_path))
    print(f"# 载入完成，模型名：{model.name()}")

    jm = model.java
    result: dict = {
        "model_path": str(model_path),
        "comsol_version": str(client.version) if hasattr(client, "version") else None,
        "parameters": [],
        "studies": [],
        "meshes": [],
        "geometries": [],
    }

    try:
        varnames = list(jm.param().varnames())
        for name in varnames:
            try:
                expr = jm.param().get(name)
            except Exception:
                expr = None
            result["parameters"].append({"name": str(name), "expression": str(expr)})
        print(f"\n== 参数 {len(result['parameters'])} 个（读自 param().varnames()/get()）==")
        for p in result["parameters"]:
            print(f"  {p['name']:14s} = {p['expression']}")
    except Exception as exc:
        print(f"[警告] 参数读取失败：{type(exc).__name__}: {exc}")

    try:
        study_tags = list(jm.study().tags())
        print(f"\n== 研究 {len(study_tags)} 个 ==")
        for stag in study_tags:
            study = jm.study(stag)
            entry: dict = {"tag": str(stag), "label": str(study.label()), "steps": []}
            print(f"  [{stag}] {study.label()}")
            for ftag in study.feature().tags():
                feature = study.feature(ftag)
                step = {
                    "tag": str(ftag),
                    "type": str(feature.type()),
                    "label": str(feature.label()),
                    "properties": {},
                }
                print(f"      step {ftag} type={feature.type()}")
                for prop in PROPS_OF_INTEREST:
                    value = read_prop(feature, prop)
                    if not value.startswith("<读不到"):
                        step["properties"][prop] = value
                        print(f"          {prop:18s} = {value}")
                entry["steps"].append(step)
            result["studies"].append(entry)
    except Exception as exc:
        print(f"[警告] 研究读取失败：{type(exc).__name__}: {exc}")

    try:
        for mtag in jm.mesh().tags():
            mesh = jm.mesh(mtag)
            entry = {"tag": str(mtag), "num_elements": None, "num_vertices": None}
            try:
                entry["num_elements"] = int(mesh.getNumElem())
            except Exception:
                pass
            try:
                entry["num_vertices"] = int(mesh.getNumVertex())
            except Exception:
                pass
            result["meshes"].append(entry)
        print(f"\n== 网格 ==")
        for m in result["meshes"]:
            print(f"  [{m['tag']}] num_elements={m['num_elements']} num_vertices={m['num_vertices']}")
    except Exception as exc:
        print(f"[警告] 网格读取失败：{type(exc).__name__}: {exc}")

    try:
        for gtag in jm.geom().tags():
            geom = jm.geom(gtag)
            entry = {"tag": str(gtag)}
            for key, fn in (("n_vertices", "getNVertices"), ("n_edges", "getNEdges"),
                            ("n_boundaries", "getNBoundaries"), ("n_domains", "getNDomains")):
                try:
                    entry[key] = int(getattr(geom, fn)())
                except Exception:
                    entry[key] = None
            result["geometries"].append(entry)
        print("\n== 几何 ==")
        for g in result["geometries"]:
            print(f"  [{g['tag']}] {g}")
    except Exception as exc:
        print(f"[警告] 几何读取失败：{type(exc).__name__}: {exc}")

    out = Path(args.out) if args.out else (
        _REPO_ROOT / "work" / "reports" / "modelio" / f"mph-runtime-{model_path.stem}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n落档：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
