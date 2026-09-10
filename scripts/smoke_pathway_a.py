"""A 通路冒烟：通过 Python MPh API 连接**已运行**的 comsolmphserver。

WORKING_PLAN.md 4.1 节把「LiveLink/MPh」列为首选通路（需要读取/修改模型树、
参数化扫描时最灵活）。本脚本实测它是否真的能用，并把证据写成 JSON。

设计约束（AGENTS.md）：
- 只连接已存在的 mphserver，不重复启动服务；
- 只加载工作区里的**模型副本**，绝不动生产模型；
- 无论成败都落盘证据：失败也是结论，必须如实记录，不得粉饰。

用法：
    work\\.venv\\Scripts\\python.exe scripts\\smoke_pathway_a.py
    work\\.venv\\Scripts\\python.exe scripts\\smoke_pathway_a.py --solve
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _candidate in (_REPO_ROOT / "src",):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

COMSOL_HOME = os.environ.get("MEMS_COMSOL_HOME", r"D:\COMSOL64\Multiphysics")
COMSOL_BIN = Path(COMSOL_HOME) / "bin" / "win64"


def _probe(label: str, fn, evidence: dict) -> object | None:
    """执行一次只读探测；失败只记录，不中断（局部失败不掩盖已达成的结论）。"""
    try:
        value = fn()
        evidence["steps"].append(f"{label}: OK")
        return value
    except Exception as exc:  # noqa: BLE001 - 探测失败必须记录原始信息
        evidence["errors"].append(f"{label}: {type(exc).__name__}: {exc}")
        evidence["steps"].append(f"{label}: FAILED")
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A 通路（MPh + mphserver）冒烟")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MEMS_MPH_PORT", "2036")))
    parser.add_argument("--model", default=None, help="要加载的 .mph 副本（默认取 work/runs 下最新）")
    parser.add_argument("--solve", action="store_true", help="尝试求解第一个研究（可能耗时较长）")
    parser.add_argument("--out", default="work/reports/pathway_a_mph.json")
    args = parser.parse_args(argv)

    # MPh 需要能从 PATH 上找到 comsol 才能定位安装目录来取客户端 jar
    os.environ["PATH"] = f"{COMSOL_BIN}{os.pathsep}{os.environ.get('PATH', '')}"
    os.environ.setdefault("COMSOL_HOME", COMSOL_HOME)

    evidence: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pathway": "A: Python MPh API + 已运行的 mphserver",
        "port": args.port,
        "comsol_home": COMSOL_HOME,
        "python": sys.version.split()[0],
        "ok": False,
        "steps": [],
        "errors": [],
    }

    model_path = Path(args.model) if args.model else None
    if model_path is None:
        candidates = sorted((_REPO_ROOT / "work" / "runs").glob("*/input.mph"))
        model_path = candidates[-1] if candidates else None

    try:
        import mph  # 延迟导入：让缺失依赖以证据形式体现，而不是 import 崩溃

        evidence["mph_version"] = getattr(mph, "__version__", "unknown")
        evidence["steps"].append(f"import mph {evidence['mph_version']}: OK")

        client = _probe(f"连接 mphserver 127.0.0.1:{args.port}", lambda: mph.Client(port=args.port), evidence)
        if client is None:
            raise RuntimeError(f"无法连接 mphserver 端口 {args.port}")

        evidence["client_version"] = _probe("读取 COMSOL 版本", lambda: str(client.version), evidence)
        evidence["loaded_models_before"] = _probe("列出现有模型", lambda: list(client.names()), evidence)

        if model_path is None or not Path(model_path).is_file():
            raise RuntimeError(f"找不到可加载的模型副本：{model_path}")
        evidence["model_path"] = str(model_path)

        t0 = time.perf_counter()
        model = _probe(f"加载模型 {Path(model_path).name}", lambda: client.load(model_path), evidence)
        if model is None:
            raise RuntimeError("模型加载失败")
        evidence["load_seconds"] = round(time.perf_counter() - t0, 2)

        # ---- 只读探测模型结构：参数 / 物理场 / 研究 ----
        params = _probe("读取参数", lambda: dict(model.parameters()), evidence)
        if params is not None:
            evidence["parameters"] = {k: str(v) for k, v in list(params.items())[:30]}
            evidence["parameter_count"] = len(params)

        physics = _probe("读取物理场", lambda: list(model.physics()), evidence)
        evidence["physics"] = [str(p) for p in physics] if physics is not None else None

        studies = _probe("读取研究", lambda: list(model.studies()), evidence)
        evidence["studies"] = [str(s) for s in studies] if studies is not None else None

        # ---- 可选求解 ----
        if args.solve and studies:
            def _solve() -> float:
                t = time.perf_counter()
                model.solve(studies[0])
                return round(time.perf_counter() - t, 1)

            evidence["solve_seconds"] = _probe(f"求解研究 {studies[0]}", _solve, evidence)
            evidence["solve_ok"] = evidence["solve_seconds"] is not None
        elif args.solve:
            evidence["steps"].append("无研究可求解：跳过")

        evidence["ok"] = True
    except Exception as exc:  # noqa: BLE001 - 顶层失败必须完整记录
        evidence["errors"].append(f"fatal: {type(exc).__name__}: {exc}")
        evidence["traceback"] = traceback.format_exc()

    out_path = _REPO_ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 68)
    print("A 通路冒烟（MPh + mphserver）")
    print("=" * 68)
    for step in evidence["steps"]:
        print(f"  - {step}")
    for err in evidence["errors"]:
        print(f"  [错误] {err}")
    print(f"结论：ok={evidence['ok']}")
    print(f"证据：{out_path}")
    print("=" * 68)
    return 0 if evidence["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
