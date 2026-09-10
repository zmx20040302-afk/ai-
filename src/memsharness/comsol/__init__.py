"""L1 仿真执行层：COMSOL 参数化模型生成、队列化求解、失败诊断与溯源。

对应 ``WORKING_PLAN.md`` 第 4.1 节。当前实现范围（P0/P2）：

- ``backend``      ``ExecutionBackend`` 协议 + ``local`` 实现（Java API + comsolcompile
                   + comsolbatch，**不依赖 MATLAB**）；``remote`` 只留 seam，未实现
- ``queue``        文件队列 + 单实例串行 worker（msvcrt 文件锁）+ 溯源入库助手
- ``java_model``   参数化模型源码生成（全 ASCII）、闭式解参考、日志结果解析
- ``diagnostics``  失败分类（分类码 + 处置建议 + 是否可重试）

三条通路的现状（WORKING_PLAN 4.1）：
    A. LiveLink/MPh（Python mph + JPype） —— 未实现
    B. ``comsolcompile`` + ``comsolbatch`` + Java API —— **本包已实现并实测跑通**
    C. 模板直连 —— 由 ``java_model.TEMPLATES`` 的模板注册表承担

红线提醒（AGENTS.md）：求解环节禁止并行；每次运行一个目录；读不到的设置写 ``null``
并记录原因，绝不猜测 ``.mph`` 内部结构。
"""

from __future__ import annotations

from . import backend, diagnostics, java_model, queue
from .backend import (
    BackendError,
    ExecutionBackend,
    ExecutionOutcome,
    LocalComsolBackend,
    PreparedRun,
    get_backend,
)
from .diagnostics import classify_failure, retry_plan
from .java_model import (
    EXTRACTOR_VERSION,
    TEMPLATES,
    TemplateSpec,
    analytic_values,
    get_template,
    list_templates,
    render_source,
    validate_values,
)
from .queue import JobQueue, JobSpec, ingest_run, worker_main

__all__ = [
    "backend",
    "diagnostics",
    "java_model",
    "queue",
    "BackendError",
    "ExecutionBackend",
    "ExecutionOutcome",
    "LocalComsolBackend",
    "PreparedRun",
    "get_backend",
    "classify_failure",
    "retry_plan",
    "EXTRACTOR_VERSION",
    "TEMPLATES",
    "TemplateSpec",
    "analytic_values",
    "get_template",
    "list_templates",
    "render_source",
    "validate_values",
    "JobQueue",
    "JobSpec",
    "ingest_run",
    "worker_main",
]

__version__ = "0.1.0"
