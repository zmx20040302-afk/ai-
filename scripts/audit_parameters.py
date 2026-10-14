"""用户模型的**参数效验**（WORKING_PLAN §4.8 第 3/4 步）：逐个参数微扰，判「真起作用 / 无效」。

为什么要单独写：
    `onboard.onboard()` 只能一次性跑「接入全流程」（含按模型原配置的教育式求解），
    而本模型的 `std1` 带两个 Parametric 步，会让每个审计点都变成一整轮扫描。
    本脚本复用 `onboard.audit_parameters` 的判据与分类，但：
      ① 在**副本**上先停用扫描步（只留 `freq`），使每个审计点 = 7 个频点；
      ② 支持 **两遍走**：先 `--no-solve` 定「几何类 / 选择集风险」，再对有必要的子集开求解；
      ③ 求解调用走 Java API（MPh 的 `model.solve("std1")` 按**名称**查研究会报 does not exist）。

用法：
    # 第一遍（便宜）：全部数值参数，不求解
    python scripts\\audit_parameters.py --model "C:\\...\\b_GE_task3_2-new.mph" --device ge-task3-audit --no-solve
    # 第二遍（贵）：只审指定参数并求解
    python scripts\\audit_parameters.py --model "C:\\...\\b_GE_task3_2-new.mph" --device ge-task3-audit \\
        --params v0 V_te1 V_te2 V_be1 c_water c_air --delta 0.05
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_HERE))  # 复用相邻脚本里的 deactivate / finite_max

from baseline_solve import deactivate, finite_max  # noqa: E402
from memsharness import onboard as ob  # noqa: E402
from memsharness.paths import work_root  # noqa: E402
from memsharness.store import connect, insert_run, now_utc  # noqa: E402


class JavaSolveProxy:
    """把 solve 换成 Java API 的薄代理（其余属性透传给 MPh Model）。

    `onboard.audit_parameters` 内部调用 ``model.solve(study)``（MPh 按名称查研究），
    本模型的 study tag=std1 而名称不匹配 → 实测报 ``Study "std1" does not exist``。
    这里只覆写 ``solve``，其余（parameters/evaluate/…）仍走 MPh。
    """

    def __init__(self, model, java, study: str):
        self._model = model
        self._java = java
        self._study = study

    def solve(self, study=None):
        self._java.study(self._study).run()

    def __getattr__(self, item):
        return getattr(self._model, item)


class FilteredAuditModel(JavaSolveProxy):
    """在 JavaSolveProxy 基础上再**限定参与审计的参数集**。

    为什么必须这么做：``onboard.audit_parameters`` 内部是
    ``params = {str(k): str(v) for k, v in model.parameters().items()}``
    ——它**自己从模型重读全部参数**，所以只在外层过滤字典是没用的（实测踩过：
    传了 14 个参数，实际仍去审全部 25 个）。
    """

    def __init__(self, model, java, study: str, allowed: set[str] | None):
        super().__init__(model, java, study)
        self._allowed = allowed

    def parameters(self):
        params = self._model.parameters()
        if not self._allowed:
            return params
        return {str(k): v for k, v in params.items() if str(k) in self._allowed}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="用户模型参数效验（可先不求解）")
    ap.add_argument("--model", required=True)
    ap.add_argument("--device", default=None)
    ap.add_argument("--study", default="std1")
    ap.add_argument("--keep", nargs="*", default=["freq"])
    ap.add_argument("--params", nargs="*", default=None, help="只审这些参数名（缺省=全部数值参数）")
    ap.add_argument("--delta", type=float, default=0.05)
    ap.add_argument("--max-params", type=int, default=40)
    ap.add_argument("--no-solve", action="store_true", help="只重建几何/网格，不求解（第一遍用）")
    ap.add_argument(
        "--freq-single",
        default=None,
        help="把 freq 步改成**单个频点**（如 15[MHz]）以降低效验机时；只作用于本副本，口径写进落档",
    )
    ap.add_argument("--targets", nargs="*", default=None)
    ap.add_argument("--port", type=int, default=2036)
    ap.add_argument("--out-mph", action="store_true", help="审计结束后把副本另存为 audit_model.mph")
    args = ap.parse_args(argv)

    source = Path(args.model)
    device = args.device or f"{source.stem}-audit"
    targets_expr = tuple(args.targets) if args.targets else ob.DEFAULT_TARGET_CANDIDATES

    run_id = f"audit-{now_utc().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = work_root() / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log: list[str] = []

    def note(message: str) -> None:
        log.append(str(message))
        print(message, flush=True)

    note(f"run_id={run_id}  求解={'否（第一遍）' if args.no_solve else '是'}")
    staging = ob.stage_model(source, device)
    note(f"只读复制：{staging['staged']}（源 SHA256={staging['source_sha256']}）")

    import mph

    def port_open(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                return True
        except OSError:
            return False

    if port_open(args.port):
        client = mph.Client(port=args.port)
    else:
        note(f"端口 {args.port} 无服务端 → 由本脚本启动（单实例）")
        client = mph.start(cores=1, port=args.port)

    started = now_utc()
    t_all = time.perf_counter()
    model = client.load(staging["staged"])
    java = model.java
    note(f"载入：{model.name()}（COMSOL {client.version}）")

    # 停用扫描步，使每个审计点 = 只跑 freq
    jstudy = java.study(args.study)
    disabled = []
    for tag in list(jstudy.feature().tags()):
        if str(tag) not in args.keep:
            disabled.append(deactivate(jstudy, str(tag), log))
    note(f"研究 {args.study}：保留 {args.keep}，停用 {[d['tag'] for d in disabled]}")

    # 单频点口径（可选）：只改副本的 freq 步，把「每参数两次求解」的机时压到可承受范围。
    freq_scope = None
    if args.freq_single:
        try:
            freq_step = jstudy.feature("freq")
            before = str(freq_step.getString("plist"))
            freq_step.set("plist", args.freq_single)
            after = str(freq_step.getString("plist"))
            freq_scope = {"requested": args.freq_single, "plist_before": before, "plist_after": after}
            note(f"口径变更：freq.plist {before!r} → {after!r}（只在本副本上）")
        except Exception as exc:
            freq_scope = {"requested": args.freq_single, "error": f"{type(exc).__name__}: {exc}"}
            note(f"[警告] 单频点设置失败：{freq_scope['error']}")

    all_params = {str(k): str(v) for k, v in model.parameters().items()}
    if args.params:
        missing = [p for p in args.params if p not in all_params]
        if missing:
            note(f"[警告] 指定参数不存在：{missing}")
        all_params = {k: v for k, v in all_params.items() if k in set(args.params)}
    note(f"待审参数 {len(all_params)} 个：{list(all_params)}")

    # 求解遍需要**归一化基线**上的目标量；不求解遍直接给空 dict（分类会得到 unknown_no_target，如实反映「未测」）
    baseline_targets: dict[str, float] = {}
    freq_axis_after_solve = None
    if not args.no_solve:
        note("归一化基线：重建几何+网格并求解一次，然后读目标量…")
        java.modelNode("comp1").geom("geom1").run()
        java.modelNode("comp1").mesh("mesh1").run()
        java.study(args.study).run()
        # ★ 必须回读频率轴：单频点口径是否真的生效、以及 inner 索引与频率的对应关系，
        #   都靠它说话（实测踩过：设了 15[MHz] 但目标量与 7 点口径的 20 MHz 值吻合，
        #   不回读就无法判断是口径错还是索引错）。
        freq_axis_after_solve = ob.eval_vector(model, "freq")
        note(f"  求解后频率轴（evaluate('freq')）：{freq_axis_after_solve}")
        baseline_targets, failures = ob.probe_targets(model, targets_expr)
        note(f"  基线目标量：{ {k: f'{v:.6g}' for k, v in baseline_targets.items()} }")
        if failures:
            note(f"  不可用：{failures}")

    allowed = set(args.params) if args.params else None
    audit = ob.audit_parameters(
        FilteredAuditModel(model, java, args.study, allowed),
        java,
        args.study,
        comp_tag="comp1",
        geom_tag="geom1",
        mesh_tag="mesh1",
        targets=baseline_targets,
        delta=args.delta,
        max_params=args.max_params,
        do_solve=not args.no_solve,
        log=note,
    )

    wall = round(time.perf_counter() - t_all, 2)
    result = {
        "run_id": run_id,
        "kind": "parameter_audit",
        "study": args.study,
        "kept_steps": list(args.keep),
        "disabled_steps": disabled,
        "staging": staging,
        "do_solve": not args.no_solve,
        "delta_fraction": args.delta,
        "freq_scope": freq_scope,
        "freq_axis_after_solve": freq_axis_after_solve,
        "params_audited": [r["name"] for r in (audit.get("results") or [])],
        "params_requested": args.params,
        "baseline_targets": baseline_targets,
        "audit": audit,
        "wall_seconds": wall,
        "comsol_version": str(client.version),
        "run_dir": str(run_dir),
        "started_at": started.isoformat(),
        "finished_at": now_utc().isoformat(),
        "log": log,
    }
    (run_dir / "audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    out_mph = None
    if args.out_mph:
        try:
            out_mph = run_dir / "audit_model.mph"
            model.save(str(out_mph))
            note(f"副本另存：{out_mph}")
        except Exception as exc:
            note(f"另存失败：{type(exc).__name__}: {exc}")

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
                "do_solve": not args.no_solve,
                "delta_fraction": args.delta,
                "n_params": len(audit.get("results") or []),
            },
            status="succeeded",
            exit_code=0,
            wall_seconds=wall,
            run_dir=str(run_dir),
            started_at=started,
            finished_at=now_utc(),
        )
    note("已登记 run 表（pathway=mph-client）")

    note("=" * 78)
    note(f"{'参数':<14}{'分类':<20}{'几何偏移':<14}{'选择集':<10}{'目标变化':<14}")
    for item in audit.get("results") or []:
        geo = item.get("bbox_relative_shift")
        tgt = item.get("target_relative_shift")
        note(
            f"{item['name']:<14}{item.get('classification', ''):<20}"
            f"{'n/a' if geo is None else f'{geo:.3e}':<14}"
            f"{'完整' if item.get('selection_intact') else '⚠变化':<10}"
            f"{'n/a' if tgt is None else f'{tgt:.3e}':<14}"
        )
    kinds: dict[str, int] = {}
    for item in audit.get("results") or []:
        kinds[item.get("classification")] = kinds.get(item.get("classification"), 0) + 1
    note(f"分类统计：{kinds}")
    note(f"白名单（geometry / material_or_load）：{[w['name'] for w in audit.get('whitelist') or []]}")
    note(f"跳过：{[(s['name'], s.get('reason', '')[:28]) for s in audit.get('skipped') or []]}")
    note(f"耗时 {wall} s；落档 {run_dir / 'audit.json'}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
