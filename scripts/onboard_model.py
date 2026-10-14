"""模型接入命令行（WORKING_PLAN §4.8 八步 SOP 的自动部分）。

用法（**必须经 ASCII 交汇点启动**，否则 JPype 因中文路径报 UnsatisfiedLinkError）：

    work\\.venv\\Scripts\\python.exe -u ^
      scripts\\onboard_model.py ^
      --model "D:\\path\\to\\model.mph" ^
      --device pmut-3d ^
      --targets "abs(p)" "u"

退出码：0 成功；2 流程失败（原因写入报告）。
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

from memsharness.onboard import DEFAULT_TARGET_CANDIDATES, onboard, save_report  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="COMSOL 模型接入（§4.8 八步 SOP 自动部分）")
    parser.add_argument("--model", required=True, help="待接入的 .mph（只读，流程只操作副本）")
    parser.add_argument("--device", required=True, help="设备名（决定 work/devices/<name>/ 目录）")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MEMS_MPH_PORT", "2036")))
    parser.add_argument("--targets", nargs="*", default=None,
                        help=f"候选目标量表达式，默认 {' '.join(DEFAULT_TARGET_CANDIDATES)}")
    parser.add_argument("--delta", type=float, default=0.05, help="参数微扰幅度（相对值，默认 5%）")
    parser.add_argument("--max-params", type=int, default=12, help="本次最多审计多少个参数")
    parser.add_argument("--no-solve", action="store_true", help="审计时不求解（仅重建几何与网格，快很多）")
    parser.add_argument("--grid", nargs=3, type=int, default=[31, 23, 0], metavar=("NX", "NY", "NZ"),
                        help="公共点集分辨率（NZ=0 表示二维问题）")
    parser.add_argument("--json", action="store_true", help="仅输出机器可读结果")
    args = parser.parse_args(argv)

    targets = tuple(args.targets) if args.targets else DEFAULT_TARGET_CANDIDATES
    report = onboard(
        args.model, args.device,
        port=args.port, target_candidates=targets, delta=args.delta,
        max_params=args.max_params, do_solve=not args.no_solve,
        grid=tuple(args.grid),
    )
    paths = save_report(report, args.device)

    if args.json:
        print(json.dumps({"report": report, "paths": paths}, ensure_ascii=False, indent=2, default=str))
        return 0 if report.get("device_spec_draft") else 2

    audit = report.get("parameter_audit", {})
    print("=" * 72)
    print(f"模型接入报告 —— 设备：{args.device}")
    print("=" * 72)
    print(f"副本：{report.get('staging', {}).get('staged')}")
    print(f"原件哈希：{report.get('staging', {}).get('source_sha256')}")
    print(f"空间维度：{report.get('space_dim')}D　研究：{report.get('device', {}).get('studies')}")
    print(f"物理场：{[p.get('type') for p in report.get('device', {}).get('physics', [])]}")
    print(f"基线求解：{report.get('baseline_solve_seconds')} s")
    print(f"可用目标量：{list(report.get('targets', {}).keys())}")
    probe_failures = report.get("target_probe_failures") or []
    if probe_failures:
        print(f"  目标量候选失败：{probe_failures}")
    print(f"公共点集：{report.get('public_point_set', {}).get('grid_points')} 点")
    print("-" * 72)
    print(f"参数审计（微扰 {audit.get('delta_fraction')}，耗时 {audit.get('audit_seconds')} s）")
    print(f"{'参数':<16}{'分类':<22}{'几何偏移':<14}{'选择集':<10}{'目标变化':<14}")
    for item in audit.get("results", []):
        geo = item.get("bbox_relative_shift")
        tgt = item.get("target_relative_shift")
        print(f"{item['name']:<16}{item.get('classification', ''):<22}"
              f"{'n/a' if geo is None else f'{geo:.3e}':<14}"
              f"{'完整' if item.get('selection_intact') else '⚠变化':<10}"
              f"{'n/a' if tgt is None else f'{tgt:.3e}':<14}")
    print("-" * 72)
    print(f"✅ 可安全自动改参白名单（{len(audit.get('whitelist', []))} 个）："
          f"{[w['name'] for w in audit.get('whitelist', [])]}")
    print(f"⏭  跳过（{len(audit.get('skipped', []))} 个）："
          f"{[(s['name'], s.get('reason', '')[:24]) for s in audit.get('skipped', [])]}")
    print("-" * 72)
    print("待人工确认：")
    for item in report.get("pending_human", []):
        print(f"  - {item}")
    print("-" * 72)
    for key, path in paths.items():
        print(f"{key}: {path}")
    for err in report.get("errors", []):
        print(f"[错误] {err}")
    print("=" * 72)
    ok = bool(audit.get("whitelist"))
    return 0 if ok else 2


if __name__ == "__main__":
    # 注意：MPh 启动的 JVM 带非守护线程，正常 return 后进程可能不退出（实测会让调用方一直等待），
    # 因此批处理 CLI 用 os._exit 立即结束，避免"工作已完成但命令挂住"。
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
