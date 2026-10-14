"""对真实 ``.mph`` 跑一次**只读** ``probe_model``，并把证据落档。

这是**实测证据生成器**（运维脚本，不是平台代码）。与旧版的区别：旧版把目标路径
**写死**成一个迁移包里已被剥离的 ``work/runs/.../out_Model.mph``，本版改为命令行传参，
便于对仓库外的生产模型做只读探针。

安全约定（AGENTS.md 红线 3 + 执行约定）：
    ``probe_model`` 自己会把模型复制到暂存区，**绝不改动原件**，并记录源路径 / SHA256 /
    ``lock_present`` / ``original_untouched``；本脚本只负责传参、落档与摘要打印。

前置：COMSOL 步骤要求**放宽的文件策略**——受限策略下 ``comsolcompile`` 会静默失败（rc=15、无输出）。

用法：
    python scripts\\modelio_probe_real.py "C:\\Users\\zmx\\Desktop\\b_GE_task3_2-new.mph"
    python scripts\\modelio_probe_real.py                 # 自动在 work/runs 下找最新的 .mph
    python scripts\\modelio_probe_real.py <path> --json   # 打印完整 JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness import modelio as mio  # noqa: E402


def find_model(explicit: str | None) -> Path | None:
    """没有显式给路径时，在 work/runs 下找最新（按 mtime）的 .mph。"""
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    runs = REPO / "work" / "runs"
    if not runs.is_dir():
        return None
    candidates = [p for p in runs.rglob("*.mph") if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="真实 .mph 只读探针（证据落档）")
    ap.add_argument("model", nargs="?", default=None, help=".mph 路径；缺省则取 work/runs 下最新")
    ap.add_argument("--json", action="store_true", help="额外打印完整 JSON")
    args = ap.parse_args(argv)

    model = find_model(args.model)
    if model is None:
        print("[错误] 没给出可用的 .mph，且 work/runs 下也没有（迁移包通常不含 .mph）。", file=sys.stderr)
        print("       本机目标器件在仓库外，例如：", file=sys.stderr)
        for name in ("b_GE_task3_2-new.mph", "b_GE_task3_2-new  n7.mph", "b_GE_task3_2-newyizu.mph"):
            print(f"         C:\\Users\\zmx\\Desktop\\{name}", file=sys.stderr)
        return 2

    lock = model.with_suffix(model.suffix + ".lock")
    print(f"# 目标模型：{model}")
    print(f"# 大小：{model.stat().st_size} bytes")
    print(f"# 旁路 .lock 存在（GUI 打开中）：{lock.exists()}")

    result = mio.probe_model(model)

    out_dir = REPO / "work" / "reports" / "modelio"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"probe-{result['run_id']}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    src = result.get("source", {})
    print("=" * 70)
    print(f"run_id        : {result['run_id']}")
    print(f"ok            : {result['ok']}")
    print(f"run_dir       : {result['run_dir']}")
    print(f"COMSOL 版本   : {result.get('comsol_version')}")
    print(f"源 SHA256     : {src.get('sha256')}")
    print(f"原件未被改动  : {src.get('original_untouched')}（lock_present={src.get('lock_present')}）")
    print(f"参数条数      : {len(result.get('parameters') or [])}")
    print(f"几何体        : {len(result.get('geometry') or [])}")
    print(f"物理场节点    : {len(result.get('physics') or [])}")
    print(f"研究          : {[s.get('tag') for s in (result.get('studies') or [])]}")
    print(f"网格统计      : {result.get('mesh')}")
    if result.get("payload_error"):
        print(f"payload_error : {result['payload_error']}")
        print(f"diagnostic    : {json.dumps(result.get('diagnostic'), ensure_ascii=False, default=str)}")
    print(f"落档          : {target}")
    print("=" * 70)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
