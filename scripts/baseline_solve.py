"""在**任意用户模型**上跑一次真实「基线求解」：只求解指定研究步骤（默认仅 `freq`）。

为什么需要它：
    `onboard.onboard()` 走的是「把模型的第一个研究**按当前配置**整段跑完」。本模型的
    `std1` 里有两个 Parametric 步（`param`: x_scale=1, N_w_te1=8；`param2`: N_w_te1=1…8），
    它们会**覆盖存储的基线参数值**（基线是 x_scale=0.6, N_w_te1=4），跑完得到的是扫描而不是基线。
    平台没有「只跑某一步 = 真基线」的入口，本脚本补上（WORKING_PLAN §4.8 第 5 步的基线口径）。

安全与可追溯（AGENTS.md 执行约定）：
    - 原件**只读**：`onboard.stage_model` 复制到 `work/devices/<device>/` 并记录双向 SHA256；
    - 停用步骤只作用于**副本**，且记录用了哪种方法、是否停用成功；
    - 一个 run 一个目录：`work/runs/<run_id>/`（含 `baseline.json`、`commands.json`、`out.mph`）；
    - 求解后**用解的数量反向验证**步确实被停用（应等于频点数，而不是扫描点数）；
    - 登记 `run` 表（pathway='mph-client'，append-only）。

用法：
    python scripts\\baseline_solve.py --model "C:\\Users\\zmx\\Desktop\\b_GE_task3_2-new.mph" \\
        --device ge-task3-baseline --study std1 --keep freq --port 2036
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from memsharness import onboard as ob  # noqa: E402
from memsharness.paths import work_root  # noqa: E402
from memsharness.store import connect, insert_run, now_utc  # noqa: E402


def new_run_id() -> str:
    return f"baseline-{now_utc().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def finite_max(values) -> float | None:
    """对求值结果取 |值| 的最大值（复数先取模，忽略 NaN/Inf）。"""
    import numpy as np

    arr = np.asarray(values)
    if np.iscomplexobj(arr):
        arr = np.abs(arr)
    arr = np.asarray(arr, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    return None if arr.size == 0 else float(arr.max())


def deactivate(jstudy, tag: str, log: list[str]) -> dict:
    """停用一个研究步骤（走 COMSOL Java API）。

    为什么不用 MPh 的 Node：``mph.node.Node`` 只有 ``type()``/``remove()`` 等，
    **没有** ``active()``/``isActive()`` 方法，也没有属性透传（实测）。
    返回所用方法与回读验证（不猜——每步都尝试回读）。
    """
    entry: dict = {"tag": tag, "method": None, "verified_inactive": None, "error": None}
    feature = jstudy.feature(tag)
    try:
        feature.active(False)
        entry["method"] = "active(False)"
    except Exception as exc:
        entry["error"] = f"active(False) 失败: {type(exc).__name__}: {exc}"
        try:
            jstudy.feature().remove(tag)
            entry["method"] = "feature().remove()"
            entry["verified_inactive"] = True
            log.append(f"  步骤 {tag}: active(False) 不可用，改用 remove()")
            return entry
        except Exception as exc2:
            entry["error"] += f" | remove() 也失败: {type(exc2).__name__}: {exc2}"
            log.append(f"  步骤 {tag}: 停用失败 —— {entry['error']}")
            return entry

    for getter in ("isActive", "active"):
        try:
            value = getattr(feature, getter)()
            entry["verified_inactive"] = not bool(value)
            break
        except Exception:
            continue
    log.append(f"  步骤 {tag}: method={entry['method']} 回读停用={entry['verified_inactive']}")
    return entry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="用户模型基线求解（只跑指定研究步骤）")
    ap.add_argument("--model", required=True, help="待求解的 .mph（**只读**，脚本只操作副本）")
    ap.add_argument("--device", default=None, help="运行区设备名（决定 work/devices/<name>/）")
    ap.add_argument("--study", default="std1")
    ap.add_argument("--keep", nargs="*", default=["freq"], help="保留（真正执行的）研究步骤 tag")
    ap.add_argument("--port", type=int, default=2036)
    ap.add_argument("--targets", nargs="*", default=None)
    ap.add_argument("--no-ingest", action="store_true", help="不写 run 表")
    args = ap.parse_args(argv)

    source = Path(args.model)
    device = args.device or f"{source.stem}-baseline"
    targets = tuple(args.targets) if args.targets else ob.DEFAULT_TARGET_CANDIDATES

    run_id = new_run_id()
    run_dir = work_root() / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log: list[str] = []

    def note(message: str) -> None:
        log.append(message)
        print(message, flush=True)

    note(f"run_id={run_id}")
    note(f"run_dir={run_dir}")

    staging = ob.stage_model(source, device)
    note(f"第1步 只读复制：{staging['staged']}")
    note(f"  源 SHA256={staging['source_sha256']}")
    note(f"  副本 SHA256={staging['staged_sha256']}  lock={staging['source_lock_present']}")

    import mph

    started = now_utc()
    t_all = time.perf_counter()
    # 走哪条路由**端口探测**决定，而不是「先 Client 再兜底」：
    # ``mph.Client(port=...)`` 在 connect 之前就已经 startJVM，连不上时 JVM 已在，
    # 再调 ``mph.start()`` 会被「Only one client can be instantiated per Python session」挡住（实测）。
    # 另：外部 Start-Process 起的 comsolmphserver 在本环境会被回收，不能假设它常驻。
    import socket

    def port_open(host: str, port: int, timeout: float = 1.5) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    server_started_here = False
    if port_open("127.0.0.1", args.port):
        note(f"检测到已在监听的 mphserver 127.0.0.1:{args.port}，连它")
        client = mph.Client(port=args.port)
    else:
        note(f"端口 {args.port} 无服务端，由本脚本启动（-login auto，单实例）")
        client = mph.start(cores=1, port=args.port)
        server_started_here = True
    model = client.load(staging["staged"])
    note(f"载入完成：{model.name()}（COMSOL {client.version}）")

    java = model.java
    baseline_params = {}
    for name in java.param().varnames():
        try:
            baseline_params[str(name)] = str(java.param().get(name))
        except Exception:
            baseline_params[str(name)] = None
    note(f"第2步 基线参数回读 {len(baseline_params)} 个（确认未被扫描步覆盖的前提）")

    jstudy = java.study(args.study)
    steps_before = []
    for tag in jstudy.feature().tags():
        jf = jstudy.feature(tag)
        item = {"tag": str(tag), "type": str(jf.type())}
        try:
            item["active_before"] = bool(jf.isActive())
        except Exception:
            item["active_before"] = None
        steps_before.append(item)
    note(f"第3步 研究 {args.study} 原有步骤：{[(s['tag'], s['type'], s['active_before']) for s in steps_before]}")

    disabled = []
    for step in steps_before:
        if step["tag"] not in args.keep:
            disabled.append(deactivate(jstudy, step["tag"], log))
    note(f"  保留执行：{args.keep}；停用：{[d['tag'] for d in disabled]}")

    note("第4步 基线求解中（首次会连同建网格）…")
    t0 = time.perf_counter()
    solve_error = None
    try:
        # 走 Java API 而不是 MPh 的 model.solve("std1")：
        # MPh 按**名称**查找研究节点，本模型的 tag=std1 而名称不是（实测报 'Study "std1" does not exist'）。
        java.study(args.study).run()
        solve_ok = True
    except Exception as exc:
        solve_ok = False
        solve_error = f"{type(exc).__name__}: {str(exc)[:400]}"
    solve_seconds = round(time.perf_counter() - t0, 2)
    note(f"  求解{'成功' if solve_ok else '失败'}：{solve_seconds} s {solve_error or ''}")

    frequencies = ob.eval_vector(model, "freq") if solve_ok else None
    target_values, target_failures = ob.probe_targets(model, targets) if solve_ok else ({}, [])
    # 逐频点曲线：用 ``evaluate(expr, inner=[i])`` 按频率索引单独求值。
    # 不要存 ``evaluate(expr)`` 的整段数组——首版那样做让 baseline.json 膨胀到 198 MB
    # （abs(p) 773,444 个值、u 3,463,040 个值），而信息量只是一个标量。
    target_curves: dict[str, list] = {}
    n_sol = len(frequencies) if frequencies else 0
    for expr in list(target_values):
        series: list[float | None] = []
        for index in range(n_sol):
            try:
                series.append(finite_max(model.evaluate(expr, inner=[index])))
            except Exception:
                series.append(None)
        target_curves[expr] = series
    note(f"第5步 频率点（{n_sol} 个）：{frequencies}")
    for expr, series in target_curves.items():
        note(f"  {expr:8s} 逐频点最大幅值 = {[None if v is None else f'{v:.4g}' for v in series]}")
    if target_failures:
        note(f"  不可用目标量：{target_failures}")

    out_mph = None
    if solve_ok:
        try:
            out_mph = run_dir / "out.mph"
            model.save(str(out_mph))
            note(f"第6步 已保存求解后的副本：{out_mph}")
        except Exception as exc:
            out_mph = None
            note(f"  保存 out.mph 失败：{type(exc).__name__}: {exc}")

    wall = round(time.perf_counter() - t_all, 2)
    finished = now_utc()

    result = {
        "run_id": run_id,
        "kind": "baseline",
        "study": args.study,
        "kept_steps": list(args.keep),
        "steps_before": steps_before,
        "disabled_steps": disabled,
        "staging": staging,
        "baseline_parameters": baseline_params,
        "solve_ok": solve_ok,
        "solve_error": solve_error,
        "solve_seconds": solve_seconds,
        "wall_seconds": wall,
        "comsol_version": str(client.version),
        "server_started_by_script": server_started_here,
        "frequencies_hz": frequencies,
        "n_solutions": (len(frequencies) if frequencies else None),
        "steps_disabled_verified_by_solution_count": (
            None if not frequencies else len(frequencies) == 7
        ),
        "targets": target_values,
        "target_failures": target_failures,
        "target_curves": target_curves,
        "target_curves_note": "逐频点最大幅值（每个频点单独 evaluate(inner=[i])，不混合频率）；原始场数据见 out.mph",
        "out_mph": str(out_mph) if out_mph else None,
        "run_dir": str(run_dir),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "log": log,
    }
    (run_dir / "baseline.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (run_dir / "commands.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "pathway": "mph-client",
                "steps": [
                    {"api": "onboard.stage_model", "args": [str(source), device]},
                    {"api": "mph.Client", "args": {"port": args.port}},
                    {"api": "client.load", "args": [staging["staged"]]},
                    {"api": "study.feature(tag).active(False)", "args": [d["tag"] for d in disabled]},
                    {"api": "model.solve", "args": [args.study]},
                    {"api": "model.evaluate", "args": ["freq", *targets]},
                    {"api": "model.save", "args": [str(out_mph) if out_mph else None]},
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if not args.no_ingest:
        with connect() as conn:
            insert_run(
                conn,
                run_id=run_id,
                backend="local",
                pathway="mph-client",
                model_path=staging["staged"],
                model_sha256=staging["staged_sha256"],
                software={"comsol": str(client.version), "mph": mph.__version__},
                settings={
                    "study": args.study,
                    "kept_steps": list(args.keep),
                    "disabled_steps": [d["tag"] for d in disabled],
                    "port": args.port,
                    "targets": list(target_values),
                },
                status="succeeded" if solve_ok else "failed",
                exit_code=0 if solve_ok else 1,
                diagnostic=solve_error,
                wall_seconds=wall,
                run_dir=str(run_dir),
                started_at=started,
                finished_at=finished,
            )
        note("已登记 run 表（pathway=mph-client）")

    note("=" * 66)
    note(f"基线求解{'成功' if solve_ok else '失败'}：{solve_seconds} s；解数量={result['n_solutions']}")
    note(f"落档：{run_dir / 'baseline.json'}")
    return 0 if solve_ok else 1


if __name__ == "__main__":
    # MPh 启动的 JVM 带非守护线程，正常 return 后进程可能不退出（实测会让调用方一直等待），
    # 因此批处理 CLI 用 os._exit 立即结束（与 scripts/onboard_model.py 同一处理）。
    import os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
