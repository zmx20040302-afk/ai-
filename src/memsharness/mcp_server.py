"""面向 DeepSeek Harness 的 MCP 工具入口（stdio）。

在 ``~/.dsh/profiles/web/cordis.patch.yml`` 中注册后，这些工具会以
``mcp__mems__<tool>`` 的形式暴露给智能体。

P0 阶段只暴露**只读**工具：环境事实、模块能力表、数据统计、记录查询。
求解类（sim_submit/sim_status）与训练类工具在 P1/P2 加入，且必须是
「提交即返回 run_id + 轮询」的非阻塞形态（MCP 默认 60 s 超时）。

本地自测：
    work\\.venv\\Scripts\\python.exe -m memsharness.mcp_server --selftest
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from . import __version__
from .env import capability_matrix, collect_env, load_report, render_summary, save_report
from .paths import ensure_work_tree, repo_root, work_root
from .store import connect, list_tables, query, store_stats

mcp = FastMCP(
    name="mems-harness",
    instructions=(
        "MEMS 仿真–数据–AI 闭环自动化平台。"
        "红线：没有证据就不出数字；读不到 .mph 内部就如实报告，不要猜测；"
        "长求解必须走提交+轮询，禁止同步阻塞。"
    ),
)

# 可查询的表白名单（防止任意 SQL/表名注入）
_QUERYABLE_TABLES = (
    "task", "design", "run", "sample", "artifact", "dataset",
    "model", "prediction", "experiment", "evidence", "feedback", "validation",
)


# ---------------------------------------------------------------------------------------
# P0-6：MCP 服务端 run_id 路径校验
# ---------------------------------------------------------------------------------------
# 背景：`sim_logs` 会按 run_id 拼出 run 目录并**读文件**，`sim_status`/`sim_cancel` 会写
# `cancel.flag`；未校验的 run_id 形如 `..\..\work\devices\x` 即可让工具越过工作区。
# supervisor（work\tools\lt2_production.py）已有 `validate_run_id()`，MCP 侧此前缺失，
# 本函数按同一口径补齐（拒绝口径一致，基准目录改为运行区 `work\runs`）。
#
# 约束：**只拦非法值**，合法 run_id 的既有成功路径一字不改（拒绝分支只返回错误结构）。
_BAD_RUN_ID_CHARS = ("/", "\\", ":", "*", "?", '"', "<", ">", "|")
_MAX_RUN_ID_LEN = 120


def runs_root() -> Path:
    """运行区 run 目录的根：``work\\runs``。"""
    return work_root() / "runs"


def validate_run_id(run_id: Any, root: Path | None = None) -> dict[str, Any]:
    """校验 run_id 是否是**安全的单个目录名**（不返回异常，只返回结构化结论）。

    拒绝：空值 / 非字符串、含 ``/ \\ : * ? " < > |``、含 ``..``、首尾空白、超长（>120）、
    以及 ``resolve()`` 后落在 ``work\\runs`` 之外（含 Windows 上 ``name.`` 与 ``name`` 同指的别名）。
    """
    problems: list[str] = []
    if not isinstance(run_id, str):
        return {"ok": False, "reasons": [f"run_id 必须是字符串，收到 {type(run_id).__name__}"]}
    if not run_id or not run_id.strip():
        problems.append("为空")
    if any(c in run_id for c in _BAD_RUN_ID_CHARS):
        problems.append(f"含路径/非法字符 {_BAD_RUN_ID_CHARS}")
    if run_id.strip() in (".", "..") or ".." in run_id:
        problems.append("含 '..'")
    if run_id != run_id.strip():
        problems.append("首尾有空白")
    if len(run_id) > _MAX_RUN_ID_LEN:
        problems.append(f"过长(>{_MAX_RUN_ID_LEN})")
    # Windows 会忽略目录名末尾的 '.' 与 ' '（`a.` 与 `a` 同指），会把两个名字混成同一个目录，
    # 破坏 append-only 的「一次运行一个目录」，因此显式拒绝（不影响真实 run_id：无尾点）。
    if run_id[-1:] in (".", " "):
        problems.append("目录名以 '.' 或空格结尾（Windows 下会与去尾后的名字混为同一目录）")
    if problems:
        return {"ok": False, "reasons": problems, "run_id": run_id}

    base = Path(root) if root else runs_root()
    target = (base / run_id).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return {"ok": False, "reasons": [f"解析后落在 {base} 之外：{target}"], "run_id": run_id}
    return {"ok": True, "run_id": run_id, "target": str(target)}


def _reject_run_id(run_id: Any, tool: str, **extra: Any) -> dict[str, Any] | None:
    """非法 run_id 的统一拒绝结构；合法时返回 ``None``（调用方继续走原路径）。"""
    verdict = validate_run_id(run_id)
    if verdict.get("ok"):
        return None
    return {
        "run_id": run_id,
        "rejected": True,
        "tool": tool,
        "error": f"非法 run_id（P0-6 路径校验拒绝）：{verdict.get('reasons')}",
        "reasons": verdict.get("reasons"),
        **extra,
    }


@mcp.tool
def ping() -> dict[str, Any]:
    """平台健康检查：返回版本与运行区路径。

    **与数据库解耦**（Codex MCP 审核 P0-1）：`ping` 本身不写库；库被锁/只读/暂不可用时
    返回结构化降级状态（`store_ok=false` + `store_error`），**不抛异常**，因此 MCP 自测不会因
    数据库问题整体失败。
    """
    ensure_work_tree()
    out: dict[str, Any] = {
        "ok": True,
        "tool": "mems-harness",
        "version": __version__,
        "repo_root": str(repo_root()),
        "work_root": str(work_root()),
        "mcp_server_ok": True,
        "store_ok": False,
        "store_tables": None,
        "store_error": None,
    }
    try:
        with connect(read_only=True) as conn:
            out["store_tables"] = len(list_tables(conn))
        out["store_ok"] = True
    except Exception as exc:  # 结构化降级，不向上抛
        out["store_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return out


@mcp.tool
def env_report(refresh: bool = False) -> dict[str, Any]:
    """COMSOL/MATLAB/mphserver 环境事实快照。

    参数 refresh=True 时重新实测（会探测端口与文件版本）；否则读取上次保存的快照。
    """
    report = None if refresh else load_report()
    if report is None:
        report = collect_env()
        save_report(report)
    return {"summary": render_summary(report), "report": report}


@mcp.tool
def module_capability() -> dict[str, Any]:
    """模块能力表：区分「文档存在」（实测）与「求解已验证」（未验证前为 null）。"""
    return capability_matrix()


@mcp.tool
def data_stats() -> dict[str, Any]:
    """元数据库各表行数统计，用于判断平台当前有多少仿真/样本/模型/证据。

    **只读连接**（Codex MCP 审核 P0-1）：库不可用时返回 `store_unavailable=true` 与错误原文，
    不与队列 worker 争 DuckDB 单写者。
    """
    ensure_work_tree()
    db = str(work_root() / "store" / "mems.duckdb")
    try:
        with connect(read_only=True) as conn:
            return {"store_ok": True, "db": db, "tables": store_stats(conn)}
    except Exception as exc:
        return {"store_ok": False, "store_unavailable": True, "db": db,
                "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


@mcp.tool
def records(table: str, limit: int = 20, run_id: str | None = None) -> dict[str, Any]:
    """查询指定表的最近记录（只读、强制行数上限）。

    参数 table 必须是白名单表名之一；run_id 可选，用于按运行过滤带 run_id 列的表。
    """
    if table not in _QUERYABLE_TABLES:
        return {"error": f"不允许查询表 {table!r}", "allowed": list(_QUERYABLE_TABLES)}
    if run_id:
        rejected = _reject_run_id(run_id, "records")
        if rejected:
            return rejected
    sql = f"SELECT * FROM {table}"
    params: list[Any] = []
    if run_id:
        sql += " WHERE run_id = ?"
        params.append(run_id)
    sql += " LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    with connect(read_only=True) as conn:
        return {"table": table, "rows": query(conn, sql, params, limit=limit)}


@mcp.tool
def run_trace(run_id: str) -> dict[str, Any]:
    """按 run_id 追溯一次运行的全部材料：运行记录 + 样本 + 产物。"""
    rejected = _reject_run_id(run_id, "run_trace")
    if rejected:
        return rejected
    with connect(read_only=True) as conn:
        run = query(conn, "SELECT * FROM run WHERE run_id = ?", [run_id], limit=1)
        samples = query(conn, "SELECT * FROM sample WHERE run_id = ?", [run_id], limit=200)
        artifacts = query(conn, "SELECT * FROM artifact WHERE run_id = ?", [run_id], limit=200)
    return {"run_id": run_id, "run": run, "samples": samples, "artifacts": artifacts}


# ---------------------------------------------------------------------------------------
# A2：COMSOL 求解队列（提交即返回；求解由单实例 worker 串行执行）
# ---------------------------------------------------------------------------------------

_WORKER_COMMAND = (
    "python -m memsharness.comsol.queue --max-jobs N"
    "（--once 只跑一个；--queue-root/--runs-root 可覆盖默认目录）"
)


@contextmanager
def _open_queue(need_db: bool = False):
    """打开队列；``need_db`` 为真时附带元数据库连接，用完立即关闭。

    注意：DuckDB 同一文件只允许一个写进程，因此状态/日志类工具默认**不碰数据库**，
    避免与 worker 的写入相互阻塞。
    """
    from .comsol.queue import JobQueue
    from .store import connect as _connect

    if not need_db:
        yield JobQueue()
        return
    conn = _connect()
    try:
        yield JobQueue(conn=conn)
    finally:
        conn.close()


@mcp.tool
def sim_templates() -> dict[str, Any]:
    """列出已注册的 COMSOL 模板及其参数（名称/单位/默认值/是否可扫描）。提交任务前先用它确定参数名。"""
    from .comsol import java_model as jm

    return {"templates": jm.list_templates()}


@mcp.tool
def sim_submit(
    template: str,
    params: dict[str, Any] | None = None,
    backend: str = "local",
    timeout_seconds: int = 3600,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """把一个 COMSOL 求解任务**提交到队列并立即返回 run_id**（不阻塞、不在本工具内求解）。

    求解耗时可远超 MCP 调用超时，因此执行必须交给单实例 worker（求解环节禁止并行）。
    参数名与合法范围见 ``sim_templates``；任务状态用 ``sim_status`` 查询。
    """
    from .comsol.queue import JobSpec

    try:
        spec = JobSpec.from_dict(
            {
                "template": template,
                "params": params or {},
                "backend": backend,
                "timeout_seconds": timeout_seconds,
                "notes": notes or [],
            }
        )
    except Exception as exc:
        return {"error": f"任务规格非法：{type(exc).__name__}: {exc}"}

    try:
        with _open_queue(need_db=True) as queue:
            run_id = queue.submit(spec)
            status = queue.status(run_id)
    except Exception as exc:
        return {"error": f"提交失败：{type(exc).__name__}: {exc}"}

    return {
        "run_id": run_id,
        "status": status,
        "how_to_execute": _WORKER_COMMAND,
        "note": "任务处于 queued；必须由 worker 串行执行，本工具不会启动求解",
    }


@mcp.tool
def sim_status(run_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    """查询队列状态：给定 run_id 返回该任务状态；否则返回最近任务列表与 worker 是否在跑。"""
    with _open_queue() as queue:
        if run_id:
            rejected = _reject_run_id(run_id, "sim_status")
            if rejected:
                return {"run": rejected}
            return {"run": queue.status(run_id)}
        jobs = queue.list_jobs(limit=max(1, min(int(limit), 100)))
        return {"count": len(jobs), "jobs": jobs, "worker_running": queue.worker_locked()}


@mcp.tool
def sim_logs(run_id: str, tail_lines: int = 40) -> dict[str, Any]:
    """读取某个 run 的日志尾部（worker/编译/批处理日志），用于定位失败原因。"""
    rejected = _reject_run_id(run_id, "sim_logs")
    if rejected:
        return rejected
    capped = max(1, min(int(tail_lines), 400))
    with _open_queue() as queue:
        run_dir = queue.run_dir(run_id)
    if not run_dir.is_dir():
        return {"error": f"run 目录不存在：{run_dir}"}

    wanted = (
        "worker.log", "compile.stdout.log", "compile.stderr.log",
        "batch.stdout.log", "batch.stderr.log", "batchlog.txt",
    )
    tails: dict[str, str] = {}
    for name in wanted:
        path = run_dir / name
        if path.is_file():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            tails[name] = "\n".join(lines[-capped:])
    return {"run_id": run_id, "run_dir": str(run_dir), "logs": tails}


@mcp.tool
def sim_cancel(run_id: str, force_kill: bool = True) -> dict[str, Any]:
    """取消一个排队中或正在运行的任务（运行中默认强制结束其进程）。"""
    rejected = _reject_run_id(run_id, "sim_cancel", cancelled=False)
    if rejected:
        return rejected
    with _open_queue() as queue:
        return queue.cancel(run_id, force_kill=force_kill)


# ---------------------------------------------------------------------------------------
# A5/A8/A9 + 角色点名：把本会话新交付的四层能力也暴露成 mcp__mems__* 工具
# ---------------------------------------------------------------------------------------
# 目的：任何 MEMS 模式会话都能**直接调用**这些确定性层，而不是靠记忆去拼命令行。
# 共同约束（与既有工具一致）：
#   * **全部离线**：不触发 COMSOL、不写元数据库（只往 work/ 下落产物文件）；
#   * **只能在工作区内操作**：输入路径必须存在且在仓库内，输出目录必须在 work/ 下；
#   * **判定以代码为准**：返回体里带 verdict / release_allowed / publish_allowed，
#     调用方不得把 inconclusive / None 复述成"通过"。
def _inside(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except Exception:
        return False


def _checked_in_path(raw: str, *, what: str) -> tuple[Path | None, dict | None]:
    p = Path(raw)
    if not p.is_absolute():
        p = repo_root() / p
    if not _inside(p, repo_root()):
        return None, {"error": f"{what} 必须在仓库内：{raw}", "repo_root": str(repo_root())}
    if not p.exists():
        return None, {"error": f"{what} 不存在：{raw}"}
    return p, None


def _checked_out_dir(raw: str | None, default_rel: str) -> tuple[Path | None, dict | None]:
    p = Path(raw) if raw else (work_root() / default_rel)
    if not p.is_absolute():
        p = repo_root() / p
    if not _inside(p, work_root()):
        return None, {"error": f"输出目录必须在运行区 work/ 下：{raw}",
                      "work_root": str(work_root())}
    p.mkdir(parents=True, exist_ok=True)
    return p, None


@mcp.tool
def freeze_gate(target_dir: str) -> dict[str, Any]:
    """A8 验证与冻结：对一个冻结目录跑 fail-closed 门禁（只读，不写任何文件）。

    返回 `verdict` / `release_allowed` / 逐项检查。**不得把 inconclusive/None 复述成通过**；
    `release_allowed` 只表示"字节与证据自洽"，不表示模型状态可升级（放行权在人）。
    """
    from .freeze_gate import run_gate

    p, err = _checked_in_path(target_dir, what="冻结目录")
    if err:
        return err
    v = run_gate(p)
    return {"target_dir": v["target_dir"], "freeze_id": v.get("freeze_id"),
            "verdict": v["verdict"], "release_allowed": v["release_allowed"],
            "n_checks": v["n_checks"], "n_failed": v["n_failed"],
            "n_inconclusive": v["n_inconclusive"], "reason": v["reason"],
            "failed_or_unknown": [{"name": c["name"], "passed": c["passed"],
                                   "reason": c["reason"]}
                                  for c in v["checks"] if c["passed"] is not True],
            "not_checked": v["not_checked"]}


@mcp.tool
def sweep_analysis(csv: str, out_dir: str | None = None,
                   preset: str = "pmut-structure-summary",
                   model_sha256: str | None = None,
                   precheck: str | None = None,
                   candidate_grid: str | None = None,
                   budget: int = 6,
                   min_effective: int = 5) -> dict[str, Any]:
    """A5 扫描分析：分族分指标排名 + Pareto +（可选）下一批选点。**不含任何加权总分。**

    产物落在 `out_dir`（缺省 `work/runs/mcp-sweep-analysis/`）：
    `scan_analysis.json`、`scan_analysis.md`、（给 candidate_grid 时）`next_batch.json|.md`。
    `precheck` 必须是**非空且可解析**的预检 JSON；否则排名按规则降级为 provisional。
    """
    import json as _json

    from .sweep_analysis import MetricSpec, analyze, build_next_batch, render_md, \
        render_next_batch_md, rows_from_records, sha256_file
    from .sweep_analysis import _exclusion_by_family  # noqa: F401  (保持导入面稳定)

    sys.path.insert(0, str(repo_root() / "scripts"))
    import run_sweep_analysis as cli  # noqa: E402

    csv_p, err = _checked_in_path(csv, what="扫描表 CSV")
    if err:
        return err
    out, err = _checked_out_dir(out_dir, "mcp-sweep-analysis")
    if err:
        return err
    if preset not in cli.PRESETS:
        return {"error": f"未知 preset {preset!r}", "available": sorted(cli.PRESETS)}
    spec = cli.PRESETS[preset]
    metrics = list(spec["metrics"])
    unwired = cli.assert_flag_rules_wired(metrics, spec["flag_rules"])
    if unwired:
        return {"error": "质量标记规则声明了却没接线", "unwired": unwired}
    pre = None
    if precheck:
        pre_p, err = _checked_in_path(precheck, what="预检 JSON")
        if err:
            return err
        pre = _json.loads(pre_p.read_text(encoding="utf-8"))

    records = cli.read_csv_rows(csv_p)
    rows = rows_from_records(records, family_key=spec["family_col"],
                            param_keys=spec["params"],
                            metric_keys=[m.name for m in metrics],
                            flag_rules=spec["flag_rules"])
    scan = analyze(rows, metrics, top_n=10, min_effective=int(min_effective),
                   model_sha256=model_sha256, precheck=pre,
                   rows_path=str(csv_p), rows_sha256=sha256_file(csv_p),
                   pareto_metrics=spec.get("pareto") or None,
                   script_sha256=sha256_file(repo_root() / "scripts" / "run_sweep_analysis.py"))
    (out / "scan_analysis.json").write_text(
        _json.dumps(scan, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "scan_analysis.md").write_text(render_md(scan), encoding="utf-8")

    res: dict[str, Any] = {
        "verdict": scan["verdict"], "release_allowed": scan["release_allowed"],
        "provisional": scan["provisional"],
        "provisional_reasons": scan["provisional_reasons"],
        "stop_reasons": scan["stop_reasons"],
        "verdict_by_family": scan["verdict_by_family"],
        "released_families": scan["released_families"],
        "precheck": scan["precheck"],
        "quality": {"n_rows": scan["quality"]["n_rows"],
                    "exclusion_rate": scan["quality"]["exclusion_rate"],
                    "exclusion_rate_by_family": scan["quality"]["exclusion_rate_by_family"],
                    "flag_counts": scan["quality"]["flag_counts"]},
        "rankings": [{"family": r["family"], "metric": r["metric"], "caliber": r["caliber"],
                      "n_available": r["n_available"], "n_excluded": r["n_excluded"],
                      "top": r["top"][:3]} for r in scan["rankings"]],
        "artifacts": {"scan_analysis_json": str(out / "scan_analysis.json"),
                      "scan_analysis_md": str(out / "scan_analysis.md")},
        "no_composite_score": scan["no_composite_score"],
        "semantics": scan["semantics"],
    }
    if candidate_grid:
        grid_p, err = _checked_in_path(candidate_grid, what="候选网格 JSON")
        if err:
            return err
        nb = build_next_batch(scan, candidate_grid=_json.loads(grid_p.read_text(encoding="utf-8")),
                              budget=int(budget), param_keys=spec["params"],
                              primary_metric=spec.get("primary_metric"))
        (out / "next_batch.json").write_text(
            _json.dumps(nb, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        (out / "next_batch.md").write_text(render_next_batch_md(nb), encoding="utf-8")
        res["next_batch"] = {"verdict": nb["verdict"], "release_allowed": nb["release_allowed"],
                             "provisional": nb["provisional"],
                             "budget": nb["budget"], "selected": nb["selected"],
                             "n_rejected": len(nb["rejected"]),
                             "stop_conditions": nb["stop_conditions"]}
        res["artifacts"]["next_batch_json"] = str(out / "next_batch.json")
        res["artifacts"]["next_batch_md"] = str(out / "next_batch.md")
    return res


@mcp.tool
def make_report(bundle: str, out_dir: str | None = None, gate: str | None = None,
                known_ids: str | None = None) -> dict[str, Any]:
    """A9 报告门禁：按 bundle 生成报告并给出 `verdict` / `publish_allowed`。

    `bundle` 是报告输入 JSON（title/sections/claims/gaps/failures/not_checked/…）。
    `gate` 若提供，必须是**与本报告主体绑定**的 A8 裁定（正文提及 freeze_id/run_id/target_dir
    或声明 gate_binding）；确无覆盖时在 bundle 里写 `gate_not_applicable_reason`。
    产物：`analysis_report.md` + `report_bundle.json`（落 `out_dir`，缺省 work/runs/mcp-report/）。
    """
    import json as _json

    from .report_augment import (Claim, Gap, build_report, render_md, sha256_file,
                                 suggest_retraining)

    bp, err = _checked_in_path(bundle, what="报告 bundle JSON")
    if err:
        return err
    out, err = _checked_out_dir(out_dir, "mcp-report")
    if err:
        return err
    spec = _json.loads(bp.read_text(encoding="utf-8"))
    gate_doc, gate_path, gate_prov = None, None, {}
    if gate:
        gate_path, err = _checked_in_path(gate, what="A8 裁定 JSON")
        if err:
            return err
        g = _json.loads(gate_path.read_text(encoding="utf-8"))
        if isinstance(g, dict) and g.get("kind") == "verification_verdict_set":
            g = (g.get("verdicts") or [None])[0]
        gate_doc = g
        gate_prov = {"gate_source": str(gate_path), "gate_sha256": sha256_file(gate_path)}
    known, known_prov = None, {}
    if known_ids:
        kp, err = _checked_in_path(known_ids, what="已知 ID 集 JSON")
        if err:
            return err
        kd = _json.loads(kp.read_text(encoding="utf-8"))
        known = kd.get("ids") if isinstance(kd, dict) and isinstance(kd.get("ids"), dict) else kd
        known_prov = {"known_ids_source": str(kp), "known_ids_sha256": sha256_file(kp),
                      "n_by_kind": {k: len(list(v)) for k, v in (known or {}).items()}}

    def _claims(items):
        out_c = []
        for it in items or []:
            kw = {k: v for k, v in it.items() if k in Claim.__dataclass_fields__}
            if isinstance(kw.get("derived_from"), list):
                kw["derived_from"] = tuple(kw["derived_from"])
            out_c.append(Claim(**kw))
        return out_c

    def _gaps(items):
        return [Gap(**{k: it.get(k, "") for k in
                       ("missing", "why", "unlock", "how", "cost")}) for it in items or []]

    doc = build_report(
        title=spec.get("title") or "（未命名报告）", sections=spec.get("sections") or {},
        claims=_claims(spec.get("claims")), gaps=_gaps(spec.get("gaps")),
        failures=spec.get("failures") or [], not_checked=spec.get("not_checked") or [],
        gate=gate_doc, model_state=spec.get("model_state"),
        declared_state=spec.get("declared_state"), known_ids=known,
        mixed_sources=spec.get("mixed_sources"),
        retraining_suggestions=suggest_retraining([], gate=gate_doc),
        gate_not_applicable_reason=spec.get("gate_not_applicable_reason"),
        gate_binding=spec.get("gate_binding"),
        upstream={"bundle": str(bp), "bundle_sha256": sha256_file(bp), **gate_prov,
                  **known_prov})
    (out / "analysis_report.md").write_text(render_md(doc), encoding="utf-8")
    (out / "report_bundle.json").write_text(
        _json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return {"verdict": doc["verdict"], "publish_allowed": doc["publish_allowed"],
            "reason": doc["reason"], "n_checks": doc["n_checks"],
            "n_failed": doc["n_failed"], "n_inconclusive": doc["n_inconclusive"],
            "blocking": [{"name": c["name"], "passed": c["passed"], "reason": c["reason"]}
                         for c in doc["checks"] if c["passed"] is not True],
            "gate_binding": next((c["detail"] for c in doc["checks"]
                                  if c["name"] == "gate_binding"), None),
            "artifacts": {"analysis_report_md": str(out / "analysis_report.md"),
                          "report_bundle_json": str(out / "report_bundle.json")},
            "semantics": doc["semantics"]}


def _spawn_role_module():
    """加载 `scripts/spawn_role.py`（单一来源，避免在 MCP 侧复制一份角色逻辑）。"""
    import importlib.util

    p = repo_root() / "scripts" / "spawn_role.py"
    spec = importlib.util.spec_from_file_location("_mems_spawn_role", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@mcp.tool
def role_list() -> dict[str, Any]:
    """列出 9 个子智能体角色（id/名称/类型/状态/一句话）。"""
    mod = _spawn_role_module()
    roles = mod.find_roles()
    rows = []
    for key, d in sorted(roles.items()):
        meta = json.loads((d / "agent.json").read_text(encoding="utf-8"))
        rows.append({"key": key, "role_id": mod._canon_id(meta, d), "name": meta.get("name"),
                     "kind": meta.get("kind"), "status": meta.get("status"),
                     "dir": mod.rel(d), "one_liner": meta.get("one_liner")})
    return {"n_roles": len(rows), "roles": rows,
            "how_to_use": "role_payload(role=..., task=...) 生成载荷；把载荷**原文**注入 subagent"}


@mcp.tool
def role_payload(role: str, task: str, fields: dict[str, Any] | None = None,
                 record: bool = True, include_payload: bool = False,
                 out_root: str | None = None, ledger_path: str | None = None) -> dict[str, Any]:
    """按角色契约生成**可注入**的子智能体载荷（契约原文 + 任务 + 交付要求）。

    契约段落是 `agents/<role>/AGENT.md` 的逐字节原文；`record=True` 会把一条记录追加进
    `ledger_path`（缺省 `work/role-spawns/spawn_ledger.jsonl`，append-only，同 id 冲突拒收）。
    **本工具不 spawn**：DSH 的 spawn 是模型侧动作，请把 `payload_path` 的全文作为 subagent 的
    prompt 注入。`out_root`/`ledger_path` 用于把产物落到别处（仍必须在 `work/` 下）。
    """
    mod = _spawn_role_module()
    existing = {k.lower() for k in mod.find_roles()}
    if role.strip().lower() not in existing and not any(
            d.name.lower() == role.strip().lower() for d in mod.find_roles().values()):
        return {"error": f"未知角色 {role!r}", "available": sorted(mod.find_roles())}
    body, rec = mod.build_payload(role, task, fields={k: str(v) for k, v in (fields or {}).items()})
    if out_root:
        root_p, err = _checked_out_dir(out_root, "role-spawns")
        if err:
            return err
        out = root_p / rec["spawn_id"]
    else:
        out = mod.SPAWN_ROOT / rec["spawn_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "prompt.md").write_text(body, encoding="utf-8")
    rec["payload_path"] = str(out / "prompt.md")
    (out / "spawn_record.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    if record:
        ledger = Path(ledger_path) if ledger_path else mod.LEDGER
        if not _inside(ledger, work_root()):
            return {"error": f"ledger_path 必须在运行区 work/ 下：{ledger_path}"}
        ledger_res = mod.append_ledger(rec, ledger)
    else:
        ledger_res = {"status": "skipped"}
    res = {"spawn_id": rec["spawn_id"], "role_id": rec["role_id"],
           "contract_path": rec["contract_path"], "contract_sha256": rec["contract_sha256"],
           "task_sha256": rec["task_sha256"], "payload_sha256": rec["payload_sha256"],
           "payload_path": rec["payload_path"], "n_bytes": len(body.encode("utf-8")),
           "ledger": ledger_res,
           "next_step": ("把 payload_path 的**全文**作为 subagent 的 prompt 注入；"
                         "如需核对：python scripts/spawn_role.py verify <payload_path>")}
    if include_payload:
        res["payload"] = body
    return res


# ---------------------------------------------------------------------------
# 网页控制台 / 看板 → MCP 工具（**控制台是执行方，MCP 只做客户端**）
#
# 为什么走 HTTP 而不是在 MCP 进程内直接 import 控制台模块：
#   控制台用 `EXEC_LOCK` 把"写产物/写库"的任务**串行化**。若 MCP 在**另一个进程**里
#   直接调用同一个任务函数，两把不同的锁 ⇒ 会出现两个任务同时写库/写产物，
#   破坏"求解环节禁止并行"的既有约束。所以 MCP 一律**通过控制台的 HTTP 接口**，
#   让控制台继续当唯一执行者；控制台没在跑就如实说"没在跑"，不绕过它。
# ---------------------------------------------------------------------------
CONSOLE_URL = os.environ.get("MEMS_CONSOLE_URL", "http://127.0.0.1:8877")
CONSOLE_TOKEN = os.environ.get("MEMS_CONSOLE_TOKEN", "")


def _console(method: str, path: str, body: dict | None = None,
             timeout: int = 60) -> dict[str, Any]:
    """调用控制台 HTTP 接口。**连不上就如实返回「没在跑」**，不静默失败。"""
    import urllib.error
    import urllib.request

    url = CONSOLE_URL.rstrip("/") + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if CONSOLE_TOKEN:
        req.add_header("Authorization", "Bearer " + CONSOLE_TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return {"error": "控制台返回 HTTP %d：%s"
                             % (exc.code, exc.read().decode("utf-8")[:300])}
        except Exception:
            return {"error": "控制台返回 HTTP %d" % exc.code}
    except Exception as exc:
        return {"console_unavailable": True, "url": url,
                "error": "%s: %s" % (type(exc).__name__, exc),
                "how_to_start": ("控制台未在运行。启动：`work\\tools\\open_console.cmd`，"
                                 "或 `powershell -File scripts\\serve_detached.ps1 -Action start`。"
                                 "控制台**按需启动、不常驻**（既有策略）。")}


@mcp.tool
def console_status() -> dict[str, Any]:
    """网页控制台/看板状态：是否在跑、默认模式、任务台账里的超时计数、页面哈希。

    **只读**。控制台没在跑时返回 `console_unavailable=true` 与启动方法（不静默失败）。
    """
    mode = _console("GET", "/api/mode")
    if mode.get("console_unavailable"):
        return mode
    act = _console("GET", "/api/tasks/active")
    st = _console("GET", "/api/task/state")
    return {
        "url": CONSOLE_URL,
        "up": True,
        "mode": mode.get("mode"), "network_allowed": mode.get("network_allowed"),
        "key_present": mode.get("key_present"),
        "n_tasks": st.get("n_tasks"), "n_write_tasks": st.get("n_writes"),
        "active": act.get("active", []), "n_active": act.get("n_active"),
        "n_timeouts_logged": act.get("n_timeouts_logged"),
        "default_timeout_s": act.get("default_timeout_s"),
        "task_log": act.get("log"),
        "note": ("控制台**默认离线**（不发网络请求）；切换 DeepSeek 需服务端凭据。"
                 "写产物任务一律需要 confirm。"),
    }


@mcp.tool
def console_tasks() -> dict[str, Any]:
    """列出控制台**已登记的任务**及其 `timeout_s`（只读；超时额度先可见）。"""
    r = _console("GET", "/api/jobs")
    if r.get("console_unavailable"):
        return r
    tasks = r.get("tasks") or {}
    return {"n_tasks": len(tasks), "default_timeout_s": r.get("default_timeout_s"),
            "tasks": [{"task": k, "title": v.get("title"), "group": v.get("group"),
                       "writes": v.get("writes"), "timeout_s": v.get("timeout_s")}
                      for k, v in sorted(tasks.items())]}


@mcp.tool
def console_run_task(task: str, args: dict[str, Any] | None = None,
                     confirm: bool = False, wait_seconds: int = 60) -> dict[str, Any]:
    """在控制台里**运行一个已登记任务**并轮询到结束或超时。

    * **写产物任务必须 `confirm=True`**（控制台也会再拦一次，双重把关）；
    * 只允许白名单任务（控制台维护），**不存在任意命令执行**；
    * `wait_seconds` 只决定本工具等多久（不是任务自己的 `timeout_s`）；
      等不到就返回 `job_id` 让人自己轮询——**不假装完成**。
    """
    if not task:
        return {"error": "必须给 task 名称（用 console_tasks 查可用值）"}
    body = {"task": task, "args": dict(args or {})}
    if confirm:
        body["args"]["confirm"] = True
    j = _console("POST", "/api/run", body)
    if j.get("console_unavailable") or j.get("error"):
        return j
    jid = j.get("job_id")
    deadline = time.time() + max(0, int(wait_seconds))
    while time.time() < deadline:
        s = _console("GET", "/api/job/%s" % jid)
        if s.get("status") != "running":
            return {"job_id": jid, "task": task, "status": s.get("status"),
                    "duration_s": s.get("duration_s"), "timeout_s": s.get("timeout_s"),
                    "timed_out": bool(s.get("timed_out")),
                    "error": s.get("error"), "result": s.get("result"),
                    "stdout_tail": (s.get("stdout") or "")[-1500:]}
        time.sleep(1.0)
    return {"job_id": jid, "task": task, "status": "running",
            "note": "本工具等待已到上限，任务仍在跑；用 console_job(job_id) 继续查",
            "poll": "/api/job/%s" % jid}


@mcp.tool
def console_job(job_id: str) -> dict[str, Any]:
    """查一个控制台任务的当前状态（含 elapsed/剩余/是否超时/终止证据）。"""
    if not job_id:
        return {"error": "必须给 job_id"}
    return _console("GET", "/api/job/%s" % job_id)


def _mc_module():
    """多通道一阶峰代理运行时（**进程内只读**，不经过控制台）。"""
    from memsharness import multichannel_surrogate as mod
    return mod


@mcp.tool
def monitor_model_card() -> dict[str, Any]:
    """多通道一阶峰代理的**模型卡**（8 通道、适用域、逐通道短板）。

    ⚠️ 该代理**不是 AI 求解器**：只预测一阶峰标量，无场级误差界、无 L1 网格收敛。
    """
    try:
        return _mc_module().model_card()
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


@mcp.tool
def monitor_predict(x: float, n1: int, n2: int, alpha: float = 0.05,
                    channels: str | None = None) -> dict[str, Any]:
    """多通道一阶峰代理**预测**（带宽/位移/灵敏度等，带区间与拒答域）。

    * 越界/无可用预测 ⇒ `refused=true` 且**不返回任何数字**；
    * `alpha` 只认 0.10/0.05/0.01；`channels` 逗号分隔，缺省为三个正式目标；
    * **不是 AI 求解器**：不得用于工程绝对值。
    """
    try:
        ch = [c for c in channels.split(",") if c] if channels else None
        return _mc_module().predict(x, n1, n2, channels=ch, alpha=float(alpha))
    except Exception as exc:
        if type(exc).__name__ == "Refused":
            return {"refused": True, "reason": str(exc),
                    "action": "请改到适用域内，或改用 COMSOL / 一阶峰标签表核对"}
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _selftest() -> int:
    """不启动 stdio 服务，直接在内存里列工具并调用 ping，用于本地验证。"""
    from fastmcp import Client

    REQUIRED = ("ping", "env_report", "module_capability", "data_stats", "records",
                "run_trace", "sim_templates", "sim_submit", "sim_status", "sim_logs",
                "sim_cancel", "freeze_gate", "sweep_analysis", "make_report",
                "role_list", "role_payload",
                "console_status", "console_tasks", "console_run_task", "console_job",
                "monitor_model_card", "monitor_predict")

    async def _run() -> int:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            names = sorted(t.name for t in tools)
            print("已注册工具:", ", ".join(names))
            missing = [t for t in REQUIRED if t not in names]
            if missing:
                print("缺少必需工具:", ", ".join(missing))
                return 2
            result = await client.call_tool("ping", {})
            print("ping 返回:", json.dumps(result.data, ensure_ascii=False))
            rl = await client.call_tool("role_list", {})
            print("role_list：%d 个角色" % rl.data["n_roles"])
        return 0

    return asyncio.run(_run())


def main() -> None:
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    mcp.run()  # 默认 stdio 传输


if __name__ == "__main__":
    main()
