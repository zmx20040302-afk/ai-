# 角色 → 代码索引（子智能体集合）

> 由 `scripts/gen_agent_collections.py` 生成。契约正文见 `agents/<id>-<slug>/AGENT.md`。

| 集合 | 类型 | 入口点（代码） | 契约(schema) | 测试 | 缺口 |
|---|---|---|---|---|---|
| **A1 合同与治理** | LLM 角色（判断/撰写） | — | `schemas/task_spec.schema.json`; `schemas/device_spec.schema.json` | — | 自然语言→合同的**模板**（本会话多轮口径讨论应固化）; `pending_human` 的强制清单与阻塞语义 |
| **A2 模型接入与审计** | 混合（代码读/算 + LLM 判断） | `src/memsharness/onboard.py`; `src/memsharness/modelio.py`; `scripts/audit_parameters.py`; `scripts/geometry_selection_precheck.py` | — | — | 审计输出契约（`audit_report` schema）; 仍有未效验参数（如 `term1_active`） |
| **A3 COMSOL 执行** | 确定性执行体（代码 + MCP） | `src/memsharness/comsol/queue.py`; `src/memsharness/comsol/backend.py`; `src/memsharness/comsol/diagnostics.py` | `schemas/run.schema.json` | `tests/test_comsol_queue.py` | PMUT 专用 MCP 模板（把冻结执行器包成一句话可调）; 多频点批量的默认分块策略 |
| **A4 数据与溯源** | 确定性执行体（代码 + MCP） | `src/memsharness/store.py`; `src/memsharness/dataset.py`; `scripts/validate_schemas.py` | `schemas/sample.schema.json`; `schemas/dataset.schema.json`; `schemas/run.schema.json` | `tests/test_dataset.py`; `tests/test_p0_foundation.py` | 口径标签（族/驱动/判据）的强制字段; 标量通道与场通道的统一入口 |
| **A5 扫描分析与优化** | LLM 角色（判断/撰写） | `scripts/run_sweep_analysis.py`; `src/memsharness/sweep_analysis.py` | `schemas/scan_analysis.schema.json`; `schemas/next_batch.schema.json` | `tests/test_sweep_analysis_offline.py`; `tests/test_report.py` | 预检产物（几何/选择集分类）尚未接入 ⇒ 排名目前自动降级为**临时**; 主动学习（DOE/LHS/贝叶斯）只实现了「有依据的选点」，未实现采集函数比较 |
| **A6 标量代理模型** | 混合（代码读/算 + LLM 判断） | `src/memsharness/ml/surrogate.py` | — | `tests/test_ml_pipeline.py` | PMUT 专用放行门槛（当前四族全 fail）; 共振参数（f0/Q/峰值）作为目标量的下一轮 |
| **A7 AI 场求解器** | 确定性执行体（代码 + MCP） | `src/memsharness/pod.py`; `src/memsharness/consistency.py`; `scripts/check_s3.py` | — | `tests/test_pod.py`; `tests/test_consistency.py` | 场数据接口（`p_axis_100um` 频响、`V_outer/V_inner`）; FNO/DeepONet 未实现; S3 可测化（L1 网格收敛 / COMSOL 残差 / 功率平衡） |
| **A8 验证与冻结** | 确定性执行体（代码 + MCP） | `scripts/verify_and_freeze.py`; `src/memsharness/freeze_gate.py` | `schemas/verification_verdict.schema.json` | `tests/test_freeze_gate_offline.py` | 把 S3/S1/资源门禁统一到同一 verdict 契约; 跨模型红队（`subagent_codex` 当前 disabled，**本机未实测**） |
| **A9 报告与增强** | LLM 角色（判断/撰写） | `scripts/run_report_augment.py`; `src/memsharness/report_augment.py` | `schemas/analysis_report.schema.json`; `schemas/evidence.schema.json`; `schemas/feedback.schema.json` | `tests/test_report_augment_offline.py`; `tests/test_report.py` | 实验/文献接入闭环只到「写进缺口」，尚无 experiment 表读写通道（平台表为空）; 正文数字扫描只覆盖结果段落中的小数/科学计数法，整数仍在网外（已在 detail 声明） |

**注**：入口点与契约路径由 `tests/test_agent_collections.py` 逐个校验存在性——声明的工具不许是空头支票。

