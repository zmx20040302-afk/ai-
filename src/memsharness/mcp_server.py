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
import sys
from contextlib import contextmanager
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


@mcp.tool
def ping() -> dict[str, Any]:
    """平台健康检查：返回版本、运行区路径与元数据库表数量。"""
    ensure_work_tree()
    with connect() as conn:
        tables = list_tables(conn)
    return {
        "ok": True,
        "tool": "mems-harness",
        "version": __version__,
        "repo_root": str(repo_root()),
        "work_root": str(work_root()),
        "store_tables": len(tables),
    }


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
    """元数据库各表行数统计，用于判断平台当前有多少仿真/样本/模型/证据。"""
    ensure_work_tree()
    with connect() as conn:
        return {"db": str(work_root() / "store" / "mems.duckdb"), "tables": store_stats(conn)}


@mcp.tool
def records(table: str, limit: int = 20, run_id: str | None = None) -> dict[str, Any]:
    """查询指定表的最近记录（只读、强制行数上限）。

    参数 table 必须是白名单表名之一；run_id 可选，用于按运行过滤带 run_id 列的表。
    """
    if table not in _QUERYABLE_TABLES:
        return {"error": f"不允许查询表 {table!r}", "allowed": list(_QUERYABLE_TABLES)}
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
            return {"run": queue.status(run_id)}
        jobs = queue.list_jobs(limit=max(1, min(int(limit), 100)))
        return {"count": len(jobs), "jobs": jobs, "worker_running": queue.worker_locked()}


@mcp.tool
def sim_logs(run_id: str, tail_lines: int = 40) -> dict[str, Any]:
    """读取某个 run 的日志尾部（worker/编译/批处理日志），用于定位失败原因。"""
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
    with _open_queue() as queue:
        return queue.cancel(run_id, force_kill=force_kill)


def _selftest() -> int:
    """不启动 stdio 服务，直接在内存里列工具并调用 ping，用于本地验证。"""
    from fastmcp import Client

    async def _run() -> int:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            names = sorted(t.name for t in tools)
            print("已注册工具:", ", ".join(names))
            result = await client.call_tool("ping", {})
            print("ping 返回:", json.dumps(result.data, ensure_ascii=False))
        return 0

    return asyncio.run(_run())


def main() -> None:
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    mcp.run()  # 默认 stdio 传输


if __name__ == "__main__":
    main()
