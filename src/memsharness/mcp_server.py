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
