"""路径解析：仓库根、运行区与标准子目录。

约定（见 AGENTS.md）：
- 仓库根：源码、文档、技能、schema（可进版本库）
- 运行区：``work/``（数据、模型、产物、日志；不进版本库）
- 允许用环境变量 ``MEMS_WORK_ROOT`` 覆盖运行区位置（例如迁到 ASCII 路径）。
"""

from __future__ import annotations

import os
from pathlib import Path

# 运行区标准子目录（模块级常量，供 store / comsol / mcp_server 共用）
_SUBDIRS = (
    "store",       # DuckDB 元数据库
    "data",        # 分层数据（raw/interim/samples/parquet）
    "artifacts",   # 内容寻址产物（mph/csv/fig/log）
    "runs",        # 每次运行一个目录（可复现单元）
    "models",      # 模型权重、注册表、模型卡
    "reports",     # 环境报告、评估报告
    "logs",        # 平台日志
)


def repo_root() -> Path:
    """仓库根目录（本文件位于 <root>/src/memsharness/paths.py）。"""
    return Path(__file__).resolve().parents[2]


def work_root() -> Path:
    """运行区根目录，可用 ``MEMS_WORK_ROOT`` 覆盖。"""
    override = os.environ.get("MEMS_WORK_ROOT")
    if override:
        return Path(override).expanduser()
    return repo_root() / "work"


def work_dirs() -> dict[str, Path]:
    """运行区各标准子目录的路径映射（不创建目录）。"""
    root = work_root()
    return {name: root / name for name in _SUBDIRS}


def ensure_work_tree() -> dict[str, Path]:
    """创建运行区目录树并返回路径映射。"""
    root = work_root()
    root.mkdir(parents=True, exist_ok=True)
    dirs = work_dirs()
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def db_path() -> Path:
    """元数据库文件路径。"""
    return work_root() / "store" / "mems.duckdb"
