"""命令行：提交并执行一次 COMSOL 参数扫描，把每个点的结果入库。

用法示例：

    # 1) 先做 L1 网格收敛检查（3 组网格；SOP 第 5 节的硬门槛）
    python scripts/run_sweep.py --template heat_slab_2d --mesh-convergence \
        --set q_in=4000 --hmax 0.002,0.001,0.0005

    # 2) 再跑参数扫描（8 个点）
    python scripts/run_sweep.py --template heat_slab_2d \
        --sweep q_in=1000,2000,3000,4000,5000,6000,7000,8000

    # 只看扫什么点、解析预期是多少，不提交
    python scripts/run_sweep.py --template heat_slab_2d \
        --sweep q_in=1000,2000,3000 --dry-run

这个脚本做四件事：
1. 把参数网格展开成逐个 job_spec，交给 ``JobQueue``（提交即返回 run_id）；
2. 用**独立子进程**启动单实例 worker（文件锁保证同一时刻只有一个 COMSOL 求解）；
3. 逐个 run 读回 result.json，调 ``ingest_run`` 写 ``sample`` / ``artifact``，并补写 ``run`` 行；
4. 汇总成 ``work/reports/sweep_<sweep_id>.json``，并把真实执行的命令与退出码一并留档。

数据库写入全部发生在**本进程**（DuckDB 单写者），worker 子进程只写 run 目录，
避免多进程抢 DuckDB 锁。
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from memsharness import store  # noqa: E402
from memsharness.comsol import java_model  # noqa: E402
from memsharness.comsol import queue as queue_mod  # noqa: E402
from memsharness.paths import work_root  # noqa: E402

DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_HMAX_LEVELS = (0.002, 0.001, 0.0005)


# --------------------------------------------------------------------------------------
# 参数解析助手
# --------------------------------------------------------------------------------------


def _parse_value_list(text: str) -> tuple[str, list[float]]:
    """``q_in=1000,2000,3000`` -> ("q_in", [1000.0, 2000.0, 3000.0])。"""
    name, sep, values = text.partition("=")
    name = name.strip()
    if not sep or not name:
        raise argparse.ArgumentTypeError(f"参数网格格式应为 NAME=v1,v2,...，收到 {text!r}")
    parsed: list[float] = []
    for chunk in values.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            parsed.append(float(chunk))
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{name} 的取值 {chunk!r} 不是数值") from exc
    if not parsed:
        raise argparse.ArgumentTypeError(f"{name} 的取值列表为空")
    return name, parsed


def _parse_scalar(text: str) -> tuple[str, float]:
    name, values = _parse_value_list(text)
    if len(values) != 1:
        raise argparse.ArgumentTypeError(f"--set 只接受单值：{text!r}")
    return name, values[0]


def new_sweep_id(prefix: str = "sweep") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}"


def build_grid(fixed: dict[str, float], sweeps: dict[str, list[float]]) -> list[dict[str, float]]:
    """笛卡尔积展开参数网格（顺序稳定，便于复现）。"""
    names = sorted(sweeps)
    points: list[dict[str, float]] = []
    for combo in itertools.product(*(sweeps[name] for name in names)):
        point = dict(fixed)
        point.update(dict(zip(names, combo)))
        points.append(point)
    return points


# --------------------------------------------------------------------------------------
# 单位与网格收敛
# --------------------------------------------------------------------------------------


def unit_report(template: java_model.TemplateSpec, params: dict[str, float]) -> dict[str, Any]:
    """用 pint 校验模板声明的单位并给出 SI 换算记录（内部一律 SI）。"""
    report: dict[str, Any] = {"pint_available": True, "entries": {}, "errors": []}
    try:
        import pint
    except ImportError:  # pragma: no cover
        report["pint_available"] = False
        report["errors"].append("pint 未安装，单位未做量纲校验")
        return report
    ureg = pint.UnitRegistry()
    for spec in template.params:
        value = params.get(spec.name)
        try:
            quantity = ureg.Quantity(float(value), spec.unit)
            base = quantity.to_base_units()
            factor = float(base.magnitude) / float(value) if value else 1.0
            report["entries"][spec.name] = {
                "declared_unit": spec.unit,
                "raw_value": float(value),
                "si_value": float(base.magnitude),
                "si_unit": str(base.units),
                "conversion_factor": factor,
                "dimensionality": str(ureg.get_dimensionality(spec.unit)),
            }
            if abs(factor - 1.0) > 1e-12:
                report["errors"].append(
                    f"{spec.name} 声明单位 {spec.unit} 非严格 SI，换算系数 {factor}（入库前必须换算）"
                )
        except Exception as exc:  # 量纲异常要报错，不静默
            report["errors"].append(f"{spec.name}: {type(exc).__name__}: {exc}")
    return report


def mesh_convergence_report_path(template_name: str) -> Path:
    return work_root() / "reports" / f"mesh_convergence_{template_name}.json"


def load_l1_report(template_name: str) -> dict[str, Any] | None:
    path = mesh_convergence_report_path(template_name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------------------
# worker 子进程
# --------------------------------------------------------------------------------------


def run_worker(job_queue: queue_mod.JobQueue, sweep_id: str, jobs: int) -> dict[str, Any]:
    """在独立进程里跑单实例 worker（文件锁跨进程生效），输出落到 work/logs/。"""
    log_path = work_root() / "logs" / f"worker_{sweep_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable,
        "-m",
        "memsharness.comsol.queue",
        "--drain",
        "--max-jobs",
        str(jobs),
        "--queue-root",
        str(job_queue.root),
        "--runs-root",
        str(job_queue.runs_root),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    print(f"[worker] {' '.join(argv)}", flush=True)
    print(f"[worker] stdout/stderr -> {log_path}", flush=True)
    with log_path.open("w", encoding="utf-8") as handle:
        proc = subprocess.run(
            argv,
            cwd=str(_REPO_ROOT),
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=env,
        )
    text = log_path.read_text(encoding="utf-8", errors="replace")
    tail = "\n".join(text.splitlines()[-30:])
    if tail:
        print("[worker tail]\n" + tail, flush=True)
    return {"argv": argv, "returncode": proc.returncode, "log_path": str(log_path)}


# --------------------------------------------------------------------------------------
# 扫描主体
# --------------------------------------------------------------------------------------


def submit_points(
    job_queue: queue_mod.JobQueue,
    template_name: str,
    points: list[dict[str, float]],
    sweep_id: str,
    timeout: int,
) -> list[str]:
    run_ids: list[str] = []
    for index, point in enumerate(points, start=1):
        run_id = job_queue.submit(
            queue_mod.JobSpec(
                template=template_name,
                params=point,
                timeout_seconds=timeout,
                sweep_id=sweep_id,
                tags={"point_index": str(index)},
                notes=[f"{sweep_id} 第 {index}/{len(points)} 点"],
            )
        )
        run_ids.append(run_id)
        print(f"[submit] {index}/{len(points)} params={point} -> run_id={run_id}", flush=True)
    return run_ids


def summarise_run(job_queue: queue_mod.JobQueue, run_id: str) -> dict[str, Any]:
    status = job_queue.status(run_id)
    result = json.loads((job_queue.run_dir(run_id) / "result.json").read_text(encoding="utf-8")) \
        if (job_queue.run_dir(run_id) / "result.json").exists() else {}
    comparison = result.get("comparison") or {}
    primary = next(iter(comparison.values()), {})
    return {
        "run_id": run_id,
        "status": status.get("status"),
        "params": status.get("params"),
        "exit_code": status.get("exit_code"),
        "wall_seconds": status.get("wall_seconds"),
        "diagnostic": (status.get("diagnostic") or {}).get("code"),
        "outputs": result.get("result"),
        "analytic": result.get("analytic"),
        "l0_rel_error": primary.get("rel_error"),
        "l0_passed": primary.get("passed"),
        "run_dir": status.get("run_dir"),
    }


def cmd_mesh_convergence(args: argparse.Namespace) -> int:
    """L1：3 组网格跑同一点，相邻差异 < 1% 才算收敛（SOP 第 5 节）。"""
    template = java_model.get_template(args.template)
    levels = [float(x) for x in args.hmax.split(",") if x.strip()]
    if len(levels) < 3:
        print("网格收敛检查至少需要 3 组网格（--hmax a,b,c）", file=sys.stderr)
        return 2
    base = java_model.validate_values(template, args.set)
    if "hmax_mesh" not in template.param_names:
        print(f"模板 {template.name} 没有 hmax_mesh 参数，无法做网格收敛检查", file=sys.stderr)
        return 2
    points = []
    for level in levels:
        point = dict(base)
        point["hmax_mesh"] = level
        points.append(point)
    if args.dry_run:
        for point in points:
            print(f"[dry-run] hmax_mesh={point['hmax_mesh']} 解析预期={template.analytic(point)}")
        return 0

    sweep_id = new_sweep_id("meshc")
    # 网格收敛探测点属于**验证活动**，不作为数据集样本（避免把重复几何点当训练数据）；
    # 但仍写 run/artifact 记录以便溯源，validation 表的 result 里记录全部 run_id。
    with store.connect() as conn:
        store.init_schema(conn)
        job_queue = queue_mod.JobQueue(
            root=args.queue_root, runs_root=args.runs_root, conn=conn
        )
        run_ids = submit_points(job_queue, template.name, points, sweep_id, args.timeout)

    worker_info = run_worker(job_queue, sweep_id, len(run_ids))

    with store.connect() as conn:
        job_queue = queue_mod.JobQueue(root=args.queue_root, runs_root=args.runs_root, conn=conn)
        for run_id in run_ids:
            queue_mod.ingest_run(conn, job_queue, run_id, write_samples=False)

    levels_out: list[dict[str, Any]] = []
    for point, run_id in zip(points, run_ids):
        summary = summarise_run(job_queue, run_id)
        values = summary.get("outputs") or {}
        levels_out.append(
            {
                "hmax_mesh_m": point["hmax_mesh"],
                "run_id": run_id,
                "status": summary.get("status"),
                "elements": ((summary.get("outputs") or {}).get("batchlog_facts") or {}).get("elements"),
                "T_max_K": values.get("T_max_K"),
                "wall_seconds": summary.get("wall_seconds"),
            }
        )
    diffs: list[dict[str, Any]] = []
    for previous, current in zip(levels_out, levels_out[1:]):
        a, b = previous.get("T_max_K"), current.get("T_max_K")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b:
            rel = abs(float(b) - float(a)) / abs(float(b))
            diffs.append(
                {
                    "from_hmax_m": previous["hmax_mesh_m"],
                    "to_hmax_m": current["hmax_mesh_m"],
                    "rel_diff": rel,
                    "abs_diff_K": abs(float(b) - float(a)),
                }
            )
    max_rel = max((d["rel_diff"] for d in diffs), default=None)
    max_abs = max((d["abs_diff_K"] for d in diffs), default=None)
    passed = bool(diffs) and max_rel is not None and max_rel < 0.01
    report = {
        "template": template.name,
        "sweep_id": sweep_id,
        "purpose": "L1 网格收敛检查（SOP 第 5 节：3 组网格、相邻差异 < 1%）",
        "caveat": (
            "本模板的精确解是线性场，线性单元可精确表示，因此相邻网格差异预期接近机器精度；"
            "该检查证明的是「网格/求解通路一致」，不能替代非线性模型的网格收敛研究。"
        ),
        "levels": levels_out,
        "diffs": diffs,
        "max_rel_diff": max_rel,
        "max_abs_diff_K": max_abs,
        "threshold_rel": 0.01,
        "passed": passed,
        "worker": worker_info,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = mesh_convergence_report_path(template.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with store.connect() as conn:
        store.init_schema(conn)
        validation_id = f"val-{sweep_id}-L1"
        conn.execute(
            "INSERT INTO validation (validation_id, target_kind, target_id, level, method, result, "
            "threshold, passed, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                validation_id,
                "run",
                ",".join(run_ids),
                "L1",
                "3 组网格（FreeTri，hmax 逐级减半）同点求解，比较 T_max_K 相邻差异",
                json.dumps(report, ensure_ascii=False),
                json.dumps({"max_rel_diff": 0.01}),
                passed,
                store.now_utc(),
            ],
        )
    print(json.dumps({k: report[k] for k in ("levels", "diffs", "max_rel_diff", "passed")},
                     ensure_ascii=False, indent=2))
    print(f"[L1] 报告：{path}")
    return 0 if passed else 1


def cmd_sweep(args: argparse.Namespace) -> int:
    template = java_model.get_template(args.template)
    points = build_grid(args.set, args.sweep)
    resolved: list[dict[str, float]] = []
    for point in points:
        resolved.append(java_model.validate_values(template, point))

    print(f"模板：{template.name}（{template.title}）；保真度 {template.fidelity}；"
          f"几何族 {template.geometry_family}")
    print(f"将提交 {len(resolved)} 个参数点，后端 {args.backend}，单点超时 {args.timeout} s")
    for index, point in enumerate(resolved, start=1):
        analytic = template.analytic(point)
        swept = {k: v for k, v in point.items() if k in args.sweep}
        print(f"  {index:>2}. {swept}  解析预期 {analytic}")
    if args.dry_run:
        print("[dry-run] 未提交任何任务。")
        return 0

    l1 = load_l1_report(template.name)
    if not l1 or not l1.get("passed"):
        message = (
            f"未找到通过的 L1 网格收敛报告（{mesh_convergence_report_path(template.name)}）。"
            "SOP 第 5 节要求 3 组网格相邻差异 < 1% 才进入参数扫描。"
            f"请先运行：python scripts/run_sweep.py --template {template.name} --mesh-convergence"
        )
        if not args.allow_no_l1:
            print("[阻断] " + message, file=sys.stderr)
            return 4
        print("[警告] " + message + " —— 已用 --allow-no-l1 继续，样本 quality 会标注该项为 null。")

    sweep_id = new_sweep_id("sweep")
    with store.connect() as conn:
        store.init_schema(conn)
        job_queue = queue_mod.JobQueue(root=args.queue_root, runs_root=args.runs_root, conn=conn)
        run_ids = submit_points(job_queue, template.name, resolved, sweep_id, args.timeout)

    worker_info: dict[str, Any] | None = None
    if args.skip_solve:
        print("[skip-solve] 只提交，不启动 worker。")
    else:
        worker_info = run_worker(job_queue, sweep_id, len(run_ids))

    summaries: list[dict[str, Any]] = []
    ingested: list[dict[str, Any]] = []
    with store.connect() as conn:
        store.init_schema(conn)
        job_queue = queue_mod.JobQueue(root=args.queue_root, runs_root=args.runs_root, conn=conn)
        for index, (point, run_id) in enumerate(zip(resolved, run_ids), start=1):
            summary = summarise_run(job_queue, run_id)
            unit_check = unit_report(template, point)
            extra_quality = {
                "l1_mesh_convergence": (
                    {
                        "passed": l1.get("passed"),
                        "max_rel_diff": l1.get("max_rel_diff"),
                        "levels": [
                            {"hmax_mesh_m": lv.get("hmax_mesh_m"), "T_max_K": lv.get("T_max_K")}
                            for lv in l1.get("levels", [])
                        ],
                        "report_path": str(mesh_convergence_report_path(template.name)),
                    }
                    if l1
                    else None
                ),
                "l1_max_abs_diff_K": (l1 or {}).get("max_abs_diff_K"),
                "unit_check": unit_check,
                "notes": [
                    "本样本是通路验证用数值实验（模板 heat_slab_2d），用于证明执行层可跑通并可溯源。",
                ],
            }
            info = queue_mod.ingest_run(
                conn,
                job_queue,
                run_id,
                extra_quality=extra_quality,
                include_analytic_sample=not args.no_analytic_samples,
            )
            ingested.append(info)
            summary["sweep_index"] = index
            summary["sample_ids"] = info.get("sample_ids")
            summary["artifact_rows"] = info.get("artifact_rows")
            summaries.append(summary)
            print(
                f"[result] {index}/{len(run_ids)} {run_id} status={summary['status']} "
                f"T_max_K={(summary.get('outputs') or {}).get('T_max_K')} "
                f"L0_rel_err={summary.get('l0_rel_error')}",
                flush=True,
            )

        counts = {
            "run": int(conn.execute("SELECT count(*) FROM run WHERE run_id IN "
                                    f"({','.join('?' * len(run_ids))})", run_ids).fetchone()[0]),
            "sample_simulation": int(conn.execute(
                "SELECT count(*) FROM sample WHERE run_id IN "
                f"({','.join('?' * len(run_ids))}) AND source_type = 'simulation'", run_ids
            ).fetchone()[0]),
            "sample_analytic": int(conn.execute(
                "SELECT count(*) FROM sample WHERE run_id IN "
                f"({','.join('?' * len(run_ids))}) AND source_type = 'analytic'", run_ids
            ).fetchone()[0]),
            "artifact": int(conn.execute(
                "SELECT count(*) FROM artifact WHERE run_id IN "
                f"({','.join('?' * len(run_ids))})", run_ids
            ).fetchone()[0]),
        }

    report = {
        "sweep_id": sweep_id,
        "template": template.name,
        "template_title": template.title,
        "fidelity": template.fidelity,
        "geometry_family": template.geometry_family,
        "backend": args.backend,
        "pathway": "comsolbatch",
        "matlab_used": False,
        "timeout_seconds": args.timeout,
        "points": resolved,
        "run_ids": run_ids,
        "worker": worker_info,
        "l1_mesh_convergence": {
            "passed": (l1 or {}).get("passed"),
            "max_rel_diff": (l1 or {}).get("max_rel_diff"),
            "report_path": str(mesh_convergence_report_path(template.name)),
        },
        "summaries": summaries,
        "ingested": ingested,
        "db_counts": counts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    report_path = work_root() / "reports" / f"{sweep_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 汇总 ===")
    print(f"run_ids（{len(run_ids)}）：{', '.join(run_ids)}")
    print(f"入库计数：{counts}")
    print(f"报告：{report_path}")
    failed = [s for s in summaries if s.get("status") != "succeeded"]
    print(f"成功 {len(summaries) - len(failed)}/{len(summaries)}；失败：{[s['run_id'] for s in failed]}")
    return 0 if not failed else 1


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="提交并执行 COMSOL 参数扫描，结果入库（DuckDB）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--template", required=True, help="模板名（见 java_model.TEMPLATES）")
    parser.add_argument(
        "--sweep",
        action="append",
        type=_parse_value_list,
        default=[],
        metavar="NAME=v1,v2,...",
        help="要扫描的参数（可重复，多个参数取笛卡尔积）",
    )
    parser.add_argument(
        "--set",
        action="append",
        type=_parse_scalar,
        default=[],
        metavar="NAME=VALUE",
        help="固定参数（可重复）",
    )
    parser.add_argument("--backend", default="local", help="执行后端（当前只支持 local）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="单点超时秒数")
    parser.add_argument("--queue-root", default=None, help="队列根目录（默认 work/queue）")
    parser.add_argument("--runs-root", default=None, help="run 根目录（默认 work/runs）")
    parser.add_argument("--dry-run", action="store_true", help="只展开参数网格并打印解析预期")
    parser.add_argument("--no-analytic-samples", action="store_true", help="不写 analytic 对照样本")
    parser.add_argument("--skip-solve", action="store_true", help="只提交，不启动 worker")
    parser.add_argument(
        "--allow-no-l1",
        action="store_true",
        help="没有通过的 L1 网格收敛报告时仍然继续（样本会标注该项为 null）",
    )
    parser.add_argument("--mesh-convergence", action="store_true", help="只做 L1 网格收敛检查")
    parser.add_argument(
        "--hmax",
        default=",".join(str(x) for x in DEFAULT_HMAX_LEVELS),
        help="网格收敛检查的 hmax 级别（逗号分隔，至少 3 个）",
    )
    parser.add_argument("--list-templates", action="store_true", help="列出已注册模板后退出")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_templates:
        print(json.dumps(java_model.list_templates(), ensure_ascii=False, indent=2))
        return 0
    if args.backend != "local":
        print(
            f"backend={args.backend!r} 未实现（P0–P2 只实现 local，WORKING_PLAN 决策点 D4）。",
            file=sys.stderr,
        )
        return 2
    args.set = dict(args.set)
    args.sweep = dict(args.sweep)
    overlap = sorted(set(args.set) & set(args.sweep))
    if overlap:
        print(f"参数同时出现在 --set 与 --sweep：{overlap}", file=sys.stderr)
        return 2
    if not args.sweep and not args.mesh_convergence and not args.list_templates:
        print("必须用 --sweep 指定至少一个扫描参数（或用 --mesh-convergence）", file=sys.stderr)
        return 2
    if args.mesh_convergence:
        return cmd_mesh_convergence(args)
    return cmd_sweep(args)


if __name__ == "__main__":
    # --list-templates 不应要求 --template：先做一次短路处理（argparse 里 --template 是 required）
    if "--list-templates" in sys.argv[1:]:
        import json as _json

        from memsharness.comsol import java_model as _jm

        print(_json.dumps(_jm.list_templates(), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    raise SystemExit(main())
