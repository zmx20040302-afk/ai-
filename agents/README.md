# 子智能体集合（名册与数据流）

> 由 `scripts/gen_agent_collections.py` 生成。**每个子智能体一个独立目录** `agents/<id>-<slug>/`。
> 本文件只是索引；契约正文在各自集合的 `AGENT.md`。
> **点名与原文注入**（方案 A，不改 DSH preset）：`scripts/spawn_role.py list|show|build|verify`，
> 用法与边界见 `docs/ROLE_SPAWN.md`；账本 `work/role-spawns/spawn_ledger.jsonl`（append-only）。

| 集合 | 类型 | 状态 | 一句话 |
|---|---|---|---|
| [`a1-contract-governance/`](./a1-contract-governance/) | LLM 角色（判断/撰写） | 契约版（待实现工具） | 把用户的一句话变成**可校验、可审计、口径明确**的任务合同；口径不明确时提问而不是猜。 |
| [`a2-model-onboarding-audit/`](./a2-model-onboarding-audit/) | 混合（代码读/算 + LLM 判断） | 契约版（工具已在，输出契约缺） | 把生产模型**只读**接进来，运行态读取 + `.m` 静态交叉验证，产出**可修改参数白名单**。 |
| [`a3-comsol-execution/`](./a3-comsol-execution/) | 确定性执行体（代码 + MCP） | 已实现（单组合真机验证） | 把「一组参数」安全地变成「一份可追溯的结果」：排队→门禁→改参→几何→网格→求解→存档。 |
| [`a4-data-provenance/`](./a4-data-provenance/) | 确定性执行体（代码 + MCP） | 已实现（基础能力） | 只让**带来源、带单位、带口径标签**的数字进库；历史只追加不覆盖。 |
| [`a5-sweep-analysis-optimization/`](./a5-sweep-analysis-optimization/) | LLM 角色（判断/撰写） | **已实现并验证**（本会话：分指标排名 + Pareto + 选点） | 把合格数据变成**分指标的排名 + Pareto + 下一批点建议**；绝不合成一个总分。 |
| [`a6-scalar-surrogate/`](./a6-scalar-surrogate/) | 混合（代码读/算 + LLM 判断） | 契约版（训练骨架已有；本会话标量通道首轮 fail） | 对阵内标量做**可核验**的快速预测（含不确定度）；未过门槛只谈趋势，不给工程绝对值。 |
| [`a7-ai-field-solver/`](./a7-ai-field-solver/) | 确定性执行体（代码 + MCP） | 契约版（骨架已有；S1 fail、S3 not_measurable） | 在**已验证范围内**直接给完整场与误差界；超范围一律拒答回退 COMSOL。 |
| [`a8-verification-freeze/`](./a8-verification-freeze/) | 确定性执行体（代码 + MCP） | **已实现并验证**（本会话） | 核对字节与证据，fail-closed 给出裁定；LLM 只能做红队审计（不得上调结论）。 |
| [`a9-report-augment/`](./a9-report-augment/) | LLM 角色（判断/撰写） | **已实现并验证**（本会话：可溯源报告门禁 + 反馈闭环） | 把一切写成**每个数字都能回溯**的报告，并把实验/文献/人反馈接回来触发再训练建议。 |

## 数据流

```text
A1 合同 ──► A2 模型审计 ──► A3 执行(求解, **串行**) ──► A4 入库/溯源
                                                      │
        ┌─────────────────────────────────────────────┼──────────────┐
        ▼                                             ▼              ▼
  A5 分析与选点 ◄── A6 标量代理                 A7 场求解器      A8 验证与冻结
        │              │                              │              │
        └──────────────┴──────────────► A9 报告与增强 ◄──────────────┘
                                              │
                                    实验/文献/人反馈 → 再训练
```

## 并发铁律

- **只有 A3 能触发 COMSOL，且单实例串行**（license 与内存受限）；
- 其余角色可并行，但**只读**：不得改冻结件、不得改别人的 run 目录；
- **判定类结论一律由代码产出**（A8 门禁、S3、资源门禁），LLM 角色只能维持或下调。

