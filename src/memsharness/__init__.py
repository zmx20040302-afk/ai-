"""MEMS Harness —— MEMS 仿真–数据–AI 闭环自动化平台。

模块划分（对应 WORKING_PLAN.md 第 3 节的分层）：

- ``env``    环境探测（COMSOL / MATLAB / mphserver / 授权）
- ``store``  溯源数据层（DuckDB + Parquet 元数据与样本）
- ``comsol`` 仿真执行层（队列、后端抽象、诊断）
- ``ml``     模型层（代理模型、不确定度、主动学习）
- ``mcp_server`` 面向 DeepSeek Harness 的 MCP 工具入口

设计红线见仓库根 ``AGENTS.md``：没有证据就不出数字。
"""

__version__ = "0.0.1"
