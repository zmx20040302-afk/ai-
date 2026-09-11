# MEMS 仿真–数据–AI 闭环自动化平台 · 工作计划（Working Plan v0.2）

> 平台代号：**MEMS Harness**（工作目录 `D:\桌面\memsharness`）
> 宿主智能体：DeepSeek Harness（`@deepseek-ai/dsh` v0.1.0-rc.7，Web 模式 `http://127.0.0.1:3080`）
> 文档状态：草案，待确认第 11 节决策点后进入 P0
> 撰写日期：2026-06（基于本机实测环境）
> **v0.2 修订（按用户方向调整）**：把「**AI 求解器替代求解器**」确立为终局目标——经多轮迭代后，平台应能**在不调用 COMSOL 的前提下完成求解**，COMSOL 降级为**教师 + 验证器 + 兜底裁判**。本版新增：场级算子学习（4.4B）、免求解器验证与放行门禁（6.4）、免求解器阶段 P4.5 与 KPI（第 8 节）、相关风险（R13–R16）。v0.1 中「AI 不替代求解器」的原则**已被本版取代**。

---

## 0. 一句话定位

把「**人给一句需求**」变成「**平台自动跑 COMSOL → 自动生成/扩充数据 → 训练 AI 求解器与代理模型 → 用实验、文献、人反馈持续增强 → 最终在不调用 COMSOL 的前提下完成求解 → 输出可追溯、带误差界的设计结论**」的闭环系统。

**终局形态（v0.2 明确）**：COMSOL 的角色从「唯一求解器」降级为**教师 + 验证器 + 裁判**——由它生成高保真真值、做独立留出集验证、在 AI 超出适用范围时兜底；**日常求解由 AI 求解器完成**。这不是"锦上添花的加速"，而是平台的目标能力。

核心原则（贯穿全文、不可协商）：

1. **没有证据就不出数字**：任何进入报告或训练集的数值，必须能追溯到「哪次求解 / 哪篇文献哪一页 / 哪次实验 / 哪条人反馈」；AI 求解器的输出同样必须携带**误差界与验证状态**。
2. **物理正确性优先于 AI 表现**：AI 模型的指标只在解析解校验（L0）与网格收敛校验（L1）通过后才被采信；物理一致性检查（守恒、边界条件满足度、对称性、渐近极限、网格无关性）不过关的解一律作废——**哪怕它与数据高度吻合**。
3. **人保留放行权**：模型从「草稿」到「可免 COMSOL 求解」必须经过显式人工门禁。
4. **免求解器可以，无边界不行**：允许 AI 在**已声明的适用范围**内替代求解器；超出范围必须**拒答并回退 COMSOL**。「能算」与「算得对」之间由**误差界 + 适用范围 + 验证等级**连接，绝不允许无界外推。

---

## 1. 目标与范围

### 1.1 北极星目标（P0–P6 合计约 12–16 周）

给定一次任务描述，例如：

> 「以现有 20 MHz PMUT（OvalDE 系列）为基础，在 18–22 MHz 谐振频率、灵敏度不低于现状、工艺尺寸不超标的约束下，给出 5 个候选设计并说明置信度。」

平台能自主完成：

| 步骤 | 平台动作 | 关键产物 |
|---|---|---|
| 1 | 解析模型/降阶模型快速扫掠，粗筛设计域 | 候选域 + 物理量级估计 |
| 2 | 生成 COMSOL 参数扫描任务，排队执行真实求解 | `.mph` 结果 + 结构化样本 |
| 3 | 抽取特征并写入带溯源的数据集 | `dataset` 版本快照 |
| 4 | 训练/更新代理模型（含不确定度） | 模型卡 + 注册表条目 |
| 5 | 用主动学习给出「下一个最值得算/最值得做的实验」 | 采样建议 + 预期信息增益 |
| 6 | 输出候选设计、置信区间、外推风险、证据链 | 可复现报告（Markdown/PDF） |
| 7 | 接收人的评审意见与实验结果，写回并触发再训练 | 增强后的模型版本 |
| 8 | **（终局）不调用 COMSOL，由 AI 求解器直接给出场解 + 误差界** | 场级解 + 误差界 + 验证等级 |

**终局目标（v0.2 新增，P4.5–P6 交付）**：在同一物理族内把流程推进到「**零 COMSOL 调用完成求解**」——给定设计点，AI 求解器直接给出**场级解**（位移/应力/电势/声压/温度场等）及误差界。COMSOL 仅在这些时刻被调用：
① 训练与主动学习的采样点；② **独立留出集**验证；③ AI 拒答（超出适用范围）时的兜底；④ 定期漂移复检。
**免求解器占比与场级误差是本平台的核心 KPI（第 8 节）。**

### 1.2 范围（做）

- COMSOL 6.4 自动化：模型参数化、参数扫描、批量求解、结果抽取、失败诊断与重试（作为**教师与验证器**）。
- **AI 求解器（场级算子学习）**：FNO / DeepONet / 图神经算子 / 降阶+残差学习，带物理约束与守恒检查，携带**场级误差界与适用范围**；目标是在免 COMSOL 的情况下完成求解。
- **免求解器求解服务**：给定设计点直接前向求解（不启动 COMSOL 进程），超范围自动拒答并排队回退。
- 多保真数据生成：解析解 / 1D 降阶模型 / 2D / 3D COMSOL 四类数据源统一入库，按 F0–F3 标注。
- 代理模型与不确定度：GP、深度集成、保形预测（用于标量指标，与 AI 求解器分开管理）。
- 增强闭环：实验数据校准、文献证据抽取、人反馈修正、漂移监控与再训练触发。
- 面向 MEMS/PMUT 的验证体系、**免求解器放行门禁（6.4）**与模型注册表。

### 1.3 非目标（本期不做）

- 不自研**通用**有限元/边界元求解器：AI 求解器是**数据 + 物理驱动的算子近似**，不追求复刻 COMSOL 的全部物理场、几何能力与求解器鲁棒性。
- **不做无边界外推**：AI 求解器只在已声明的物理族、几何拓扑、参数范围与保真度内出解；超出即拒答并回退 COMSOL。「任意 COMSOL 模型都能免求解器」属于**禁止出现的宣传口径**。
- 不因为 AI「已经能用」就停止验证：独立留出集验证、漂移复检、网格无关性检查必须长期保留。
- 不做公网多租户 SaaS（本期为单机/局域网科研平台）。
- 不自动投稿、不自动生成无法复核的论文级结论。

---

## 2. 现状勘察（本机实测，非假设）

> **修订说明**：本节最初为 v0.1 的首次勘察。后续一轮实测（记录见第 13 节）推翻了其中若干条目，**已在本节原处直接更正**（工作区状态、DSH 补丁层状态、中文路径结论）；仍未完成确认的条目保留"待确认"标记（如授权的逐模块求解冒烟）。

### 2.1 计算环境

| 项目 | 实测结果 | 对设计的影响 |
|---|---|---|
| GPU | NVIDIA RTX 3060 Laptop，**6 GB VRAM**，驱动 546.30 | 只能训中小模型（MLP/GP/小型算子网络）；大模型走 CPU 或分块训练 |
| Python | 3.12.10 @ `D:\pathon\python.exe`，`uv` 可用 | 用 `uv` 建独立 venv，避免污染全局 |
| 已装科学栈 | numpy 2.5.0 / scipy 1.18.0 / pandas 3.0.3 / scikit-learn 1.9.0 | 代理模型基线可立即开工 |
| 缺 | **无 torch、无 jpype、无 mph、无 botorch/gpytorch** | P0 需安装（注意 6 GB 显存选 cu121/cu124 版 torch） |
| 工作区 | `D:\桌面\memsharness`（**已在 P0 实测中建立运行区 `work\`**） | 新平台落地点。实测结论：中文路径本身可用，但**任何启动 JVM 的工具（MPh/JPype、Java 客户端）必须经 ASCII 交汇点 `C:\Users\18161\memsharness_work\repo` 启动**，否则报 `UnsatisfiedLinkError`（详见第 13 节与风险 R7） |

### 2.2 COMSOL

| 项目 | 实测结果 |
|---|---|
| 安装 | `D:\COMSOL64\Multiphysics`，版本 **6.4.0.293** |
| 可执行 | `bin\win64\` 下 `comsol.exe`、`comsolbatch.exe`、`comsolmphserver.exe`、`comsolcompile.exe` 等齐备 |
| 授权 | `license\license.dat` + `license.paid` 存在，`licenseinfo.ini` 有 LicenseNumber 6464550；`license.dat` 中可见 `Batch` / `Client-Server` / `Compiler` 能力项 |
| 模块文档（PDF 已在本机） | MEMS、Structural Mechanics、Acoustics、RF、Heat Transfer、Optimization、Nonlinear Structural Materials、LiveLink for MATLAB/Simulink… |
| 服务状态 | **`comsolmphserver.exe` 正在运行（PID 6044），`127.0.0.1:2036` 已监听** |
| 待确认 | 授权产品清单需 P0 用最小模型逐模块冒烟枚举（文档存在 ≠ 授权包含） |

### 2.3 MATLAB / LiveLink

| 项目 | 实测结果 |
|---|---|
| MATLAB | `D:\MATLAB2025\bin\matlab.exe`（R2025b） |
| LiveLink | `D:\COMSOL64\Multiphysics\mli` |
| 结论 | LiveLink + mphserver 通路**已被既有系统验证可用**（见 2.5） |

### 2.4 DeepSeek Harness 可用的扩展点（本方案的技术地基）

DSH 以 npm 包形式安装（非源码 checkout），profile 位于 `C:\Users\18161\.dsh\profiles\web`，`bundles = [dsh-base, dsh-web-app]`。用户补丁层 `cordis.patch.yml` **已写入本平台的 MCP 服务器注册**（见 `docs/dsh_mcp_registration.md`）；注意补丁条目是**定向补丁**，新增必须写成 `- insert: [...]`，且 HMR 不会新增条目、需重启 DSH 才在 GUI 生效。可用扩展点：

| 能力 | 载体 | 本方案用途 |
|---|---|---|
| **MCP 客户端** | `@deepseek-ai/dsh-mcp-client`，在 `cordis.patch.yml` 里一个实例一个 server，工具以 `mcp__<server>__<tool>` 暴露 | **主通道**：把平台的 Python 工具暴露给智能体 |
| **技能（Skills）** | `@deepseek-ai/dsh-skill-filesystem`，扫描 `<项目>/.dsh/skills`、`<项目>/.agents/skills`、`~/.dsh/skills`（`SKILL.md` 或扁平 `.md`） | 沉淀 COMSOL 建模 SOP、数据契约、训练规范 |
| **项目指令** | `AGENTS.md`（项目根 + `$DSH_HOME/AGENTS.md`） | 写死物理红线、单位规范、禁止编造数字 |
| **后台作业** | `jobs`（`run_in_background` + `job_output`） | 承载小时级 COMSOL 求解，避免工具调用超时 |
| **子代理 / 工作流** | `subagent`、`subagent_fork`、`workflow` | 文献抽取、报告撰写、代码审查并行 |
| **目标 / Ralph** | `goal`（同会话多轮自主推进）、`ralph`（每轮全新子代理迭代） | 长周期攻坚（如「让某模板稳定收敛」） |
| **定时提醒** | `@deepseek-ai/dsh-schedule`（最小 5 分钟、会话内） | 队列巡检、漂移监控、每日进展汇总 |
| **网页 UI** | `dsh web`（已运行 3080） | 人反馈入口、报告查看 |
| 待启用 | `dsh plugin --profile web add <pkg>`（需 pnpm；`D:\corepack.cmd` 可 `corepack enable pnpm`） | 仅当需要自写 TypeScript 插件面板时才用 |

> **关键工程约束**：MCP 单次工具调用默认超时 60 s（`toolCallTimeoutMs`）。因此所有 COMSOL 求解类工具必须设计为**「提交即返回 run_id + 轮询状态」**，绝不做同步长阻塞。

### 2.5 既有资产盘点（重要：不要从零开始）

`D:\桌面\codex\comsol1` 已经是一个可运行的 COMSOL 自动化原型，含大量可直接吸收的模块：

| 现有资产 | 位置 | 复用方式 |
|---|---|---|
| 执行队列 + 单实例 worker（文件锁） | `comsol_training_small_model\execution_worker.py`、`src\...\execution_jobs.py`（52 KB） | 升级为通用 run queue（保留 msvcrt 文件锁思路） |
| mphserver 启动/复用逻辑 | `src\...\comsol_server.py`、`configs\execution_node.json`（端口 2036、超时 3600 s） | 抽取为 `comsol/adapter` 基础 |
| 失败诊断分类 | `src\...\execution_diagnostics.py` | 扩成求解失败知识库 + 自动重试策略 |
| 代理模型训练/运行时/模型卡/校验 | `surrogate.py`、`surrogate_runtime.py`、`surrogate_model_card.py`、`surrogate_validation.py`、`holdout_independence.py` | 提取为 `ml/` 包，补上不确定度与主动学习 |
| 网格收敛、参数覆盖、结果验证 | `mesh_convergence.py`、`parameter_coverage.py`、`result_validation.py` | 直接进入验证等级体系（第 6 节） |
| 一维基准模型库（解析解校验） | `ONE_DIMENSIONAL_MODEL_LIBRARY.md` + `configs\one_dimensional_*.json` | 扩展为 MEMS 解析基准库 |
| 独立 1D 物理场实验台（含打包 exe） | `one_dimensional_web_lab\` | 作为「解析/降阶数据工厂」的起点 |
| COMSOL 案例证据检索库（TF-IDF + 强制引用） | `comsol_kb.py`、`comsol_docs_kb.py`、`data\*.json`、`COMSOL_MASTER_KNOWLEDGE_BASE.md` | 直接继承其「无来源摘录就不输出设置」原则 |
| 案例记忆库（35 MB） | `generated\case_memory\case_memory.json` | **迁移到 SQLite/DuckDB**（见风险 R8） |
| 人反馈与工作流反馈 | `work_feedback.py`、`staged_modeling.py` | 演进为人反馈事件流（第 5.4 节） |
| 知识模块（几何/材料/边界/耦合/求解器/结果） | `*_knowledge.py` 系列 | 直接作为技能（Skill）素材来源 |
| 领域模型样本 | `D:\桌面\换能器学习\OvalDE_20MHz_*.mph`、`a_Oval shape.mph`(1 GB)、`PMUT_SAL_GE_20210316_V2.2.pdf` | 首个端到端示范的真实对象 |
| 领域文献 | `D:\桌面\mems论文\`（AgenticSciML、NYU 反馈学习博士论文、transducer 手册等） | 文献抽取闭环的种子语料 |

**结论：本平台应定位为对既有原型的「重构 + 泛化 + 增强」，而不是另起炉灶。**

---

## 3. 总体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│ L4 交互与增强层（DSH 智能体）                                          │
│  人（自然语言/评审/实验数据） ↔ 技能库 ↔ MCP 工具 ↔ 报告与门禁          │
├──────────────────────────────────────────────────────────────────────┤
│ L3 模型层  ml/  —— 两条路线（v0.2）                                    │
│  4.4A 代理层: 标量/曲线(GP/DeepEnsemble) · UQ · 主动学习 · 校准         │
│  4.4B AI 求解器: 场级算子(FNO/DeepONet/GNO) · 物理约束 · 场级误差界      │
│        · OOD 拒答与回退 COMSOL · 独立注册表 + S0–S5 门禁                │
├──────────────────────────────────────────────────────────────────────┤
│ L2 数据工厂  data/                                                   │
│  解析解/降阶(1D) · 多保真融合 · 采样设计(DOE/LHS/BO) · 增强计划         │
├──────────────────────────────────────────────────────────────────────┤
│ L1 仿真执行层  comsol/                                               │
│  模型参数化 · 队列与单实例调度 · 求解 · 抽取 · 失败诊断 · 重试 · 产物    │
├──────────────────────────────────────────────────────────────────────┤
│ L0 资产与溯源层  store/                                              │
│  DuckDB(元数据) + Parquet(样本) + Artifact(文件) + 证据引用 + 版本快照  │
└──────────────────────────────────────────────────────────────────────┘
        ▲                                              ▲
        │  实验数据 / 文献 / 人反馈（增量增强）           │  COMSOL 6.4 + MATLAB R2025b + mphserver:2036
```

数据流（一次完整闭环）：

```
需求 → 任务规格(task spec) → 采样点生成 → [仿真队列] → 原始产物(.mph/csv/log)
     → 抽取(特征+溯源) → 数据集版本 → 训练 → 评估(留出/解析/实验) → 模型卡
     → 门禁(人放行) → 注册表 → 服务(预测/优化建议) → 反馈事件 → 再训练触发

训练期（教练关系，v0.2 起）：
  COMSOL = 教师（生成真值）+ 验证器（独立留出集）+ 裁判（漂移复检与兜底）

运行期（v0.2 终局目标：免求解器）：
  设计点 → 适用范围/OOD 判定 ──命中──→ AI 求解器前向 → 场解 + 场级误差界
                              └─超出──→ 拒答 → 自动排队 COMSOL → 回写 + 复检
  其中：任何一次免求解器出解都要先过物理一致性自校验（守恒/边界/对称/极限），
        不通过即作废并回退——"与数据吻合"不能替代"物理成立"。
```

---

## 4. 核心模块设计

### 4.1 L1 仿真执行层（`comsol/`）

三条通路，按优先级自动降级：

| 通路 | 机制 | 适用 | 备注 |
|---|---|---|---|
| **A. LiveLink/MPh（首选）** | `comsolmphserver` (2036) + MATLAB LiveLink（已验证）或 Python `mph`+JPype | 需要读取/修改模型树、参数化扫描、抽任意导出量 | 既有系统已验证；Python 侧需装 `mph`/`jpype1` |
| **B. `comsolbatch.exe`（批量/无 GUI）** | `comsolbatch -inputfile model.mph -outputfile out.mph`，配合 Java API（`comsolcompile` + `-inputfile x.java`）或 `-methodcall` | 无人值守长跑、集群化、无 MATLAB 依赖 | 已验证 `comsolbatch.exe` 存在；具体参数需 P0 冒烟 |
| **C. 模板直连** | 对已验证模板（1D 传热/扩散/电热/2D 力学）直接用既有 `validated_templates.py` 路径 | 高频、低风险数据生成 | 立刻可用 |

必须实现的能力：

- `submit(job_spec) -> run_id`：非阻塞；job 落到文件队列（复用现有 worker 模式）。
- **单实例串行 + license 感知并发**：COMSOL 求解**禁止**用 DSH `workflow` 并行 fan-out（会抢 license/内存）；并行只用于非求解工作（解析计算、文献抽取、报告）。
- 每次运行固定记录：COMSOL 版本、license、mphserver 端口、模型文件 SHA256、参数快照、网格设置、求解器设置、墙钟/CPU 时间、日志、产物哈希。
- 失败诊断：复用并扩展 `execution_diagnostics.py`（连接失败 / 不收敛 / 内存不足 / 几何错误 / 选择集失效），给出分类 + 处置建议 + 是否可重试。
- 前置校验：单位完整性、参数范围、`.mph` 是否被 GUI 占用（曾观察到 `a_Oval shape.mph.lock`）、运行前复制到 ASCII 工作目录。

### 4.2 L0 数据与溯源层（`store/`）

- 元数据：**DuckDB**（单文件、零运维、列式分析快），Parquet 存样本表，文件产物走内容寻址目录。
- 单位：全链路 `pint` 校验，入库强制 SI 规范化 + 原始单位保留。
- 核心表（草案）：

| 表 | 关键字段 |
|---|---|
| `task` | task_id, 需求原文, 约束, 创建人, 状态 |
| `design` | design_id, 参数向量(JSON), 单位, 几何族(group_key), 来源(解析/仿真/文献/实验) |
| `run` | run_id, design_id, 通路(A/B/C), 模型哈希, 软件版本, 状态, 耗时, 日志路径 |
| `sample` | sample_id, run_id, 输入特征, 输出指标 + 不确定度, 提取器版本, 质量标记 |
| `artifact` | artifact_id, run_id, 类型(mph/csv/png/log), sha256, 路径, 大小 |
| `dataset` | dataset_id, 语义版本, 样本集, 划分(group-aware), 过滤规则, 校验报告 |
| `model` | model_id, 版本, 训练集, 超参, 指标, 不确定度方法, 适用范围, 门禁状态 |
| `prediction` | prediction_id, model_id, 输入, 输出, 区间, OOD 分数, 时间 |
| `experiment` | exp_id, 设备, 条件, 原始数据, 与预测的偏差, 来源人 |
| `evidence` | evidence_id, 类型(文献/文档/案例页), 引文, 定位(页码/行), 摘录原文, 置信 |
| `feedback` | feedback_id, 对象(模型/预测/报告), 评价, 修正值, 理由, 人, 时间 |
| `validation` | validation_id, 等级(L0–L5), 方法, 结果, 阈值, 通过与否 |

- **防泄漏**：数据集划分按 `geometry_family`（几何族）分组切分，禁止同一族几何的扫描点同时出现在训练/测试集（继承既有 `holdout_independence.py`）。

### 4.3 L2 解析/降阶数据工厂（`data/analytic/`）

这是实现「**用解析解方法生成更多数据**」的模块，也是**多保真**的廉价端：

| 保真度 | 手段 | 单点成本 | 用途 |
|---|---|---|---|
| F0 | 闭式解析（1D 厚度模 `f = (1/2t)√(c/ρ)`、板弯曲、梁谐振、pull-in、辐射阻抗、热噪声） | µs–ms | 预训练、约束、量级 sanity check、初值 |
| F1 | 降阶模型（1D Mason/KLM 等效电路、集总参数、模态展开） | ms–s | 大批量生成、域粗筛、频率响应曲线 |
| F2 | COMSOL 2D 轴对称 / 简化 3D | min–h | 中等保真训练样本 |
| F3 | COMSOL 全 3D / 多物理耦合 | h–天 | 真值标定与关键验证点 |

实现要点：

- 每个解析模型必须自带**基准测试**（对已知解/极限情况断言），CI 里跑（继承 `ONE_DIMENSIONAL_MODEL_LIBRARY.md` 的做法）。
- 解析与仿真在同一 `design` 空间下有对应样本时，自动做**交叉一致性检查**（相对偏差 > 阈值 → 报警而非静默入库）。
- 多保真融合：先训 F0/F1 → 迁移到 F2 → 用 F3 做少量校准（而非直接用 F3 从零训练）。

### 4.4 L3 模型层（`ml/`）——两条路线，必须分开

**关键区分（v0.2）**：本层承担两类**目标不同**的模型，必须分开训练、分开验证、分开注册，禁止互相冒用指标：

| 路线 | 输出 | 用途 | 能否免 COMSOL 求解 |
|---|---|---|---|
| **4.4A 代理层** | 标量 / 曲线（f_r、Q、灵敏度、阻抗谱） | 快速筛选、优化、主动学习 | 只能回答「指标」，给不出场解 |
| **4.4B AI 求解器** | **场级解**（位移/应力/电势/声压/温度场…） | 直接替代求解器出解 | **可以**（受 6.4 门禁约束） |

#### 4.4A 代理层（标量 / 曲线）

| 组件 | 方法（起步 → 进阶） | 说明 |
|---|---|---|
| 代理模型 | 标准化 + MLP 深度集成 → GP（小样本） → 多保真 GP / 残差学习 | 起步复用既有 `surrogate.py` 的 MLP 管线，补集成与不确定度 |
| 频率响应类输出 | PCA/模态压缩 + 少量分量回归；进阶 DeepONet/FNO（小规模，受 6 GB 显存约束） | 阻抗谱、位移谱等曲线型输出 |
| 不确定度 | 深度集成方差 → GP 后验 → 保形预测（conformal）校准区间 | 目标：90% 区间实际覆盖率 85–95% |
| 主动学习 | 方差/信息增益采样 → qEI/qNEI（BoTorch）→ 多目标（性能+工艺成本） | 输出「下一个最值得算的 COMSOL 点」和「最值得做的实验」 |
| 物理约束 | 单调性/对称性/极限行为硬约束；PINN 仅用于可控子问题 | 避免「数据拟合但违反物理」 |
| 外推防护 | OOD 检测（马氏距离/密度比）+ 适用范围硬边界 | 超范围直接拒绝出数，继承既有「越界不出代理结果」策略 |
| 注册表 | 模型卡 + 状态机：`draft → validated_on_holdout → calibrated_to_experiment → approved_for_use → deprecated` | 状态跃迁必须过门禁（第 6.3 节） |

#### 4.4B AI 求解器（场级算子）——免 COMSOL 求解的核心

目标：**给定设计参数与边界/载荷条件，不启动 COMSOL 直接输出场解**，并给出可信的误差界。

| 组件 | 方法（起步 → 进阶） | 关键要求 |
|---|---|---|
| 算子主干 | 固定网格场到扬 CNN/U-Net（起步） → FNO / DeepONet / 图神经算子（进阶） | 输入 = 几何参数 + 材料参数 + 边界/载荷 + 频率等；输出 = 场 |
| 几何表达 | 参数化几何向量（起步） → 隐式场/SDF 或网格图（进阶，可覆盖拓扑变化） | 拓扑变化是最大难点，必须单独声明适用范围 |
| 物理约束 | PDE 残差损失（PINN 风格）+ 边界条件硬约束 + 守恒项（能量/通量/质量） | 边界条件满足度要作为**独立指标**上报，不能只看总损失 |
| 多保真与迁移 | F1 降阶预训练 → F2 COMSOL 微调 → F3 少量残差校准 | 与 4.3 保真度体系直接对接，训练集必须标 F 级 |
| 离散无关性 | 同一设计在 2–3 套网格上求解，结果差异需 < 阈值 | 防止模型「记住训练网格」而非学到物理 |
| 自校验（安全网） | 守恒量、对称性、极限一致性（静态极限/低频极限）、边界残差 | **任一不过 → 本次求解作废，转 COMSOL**，不得放行 |
| 误差界 | 集成分歧 + 保形预测（conformal）给出**逐点场误差界** | 必须报场级误差界，不能只报一个全局标量误差 |
| 拒答与回退 | OOD 检测（参数马氏距离 + 密度比 + 物理量级越界）→ 拒答并自动排队 COMSOL | **宁拒答，不错答**；拒答率本身是 KPI |
| 注册与放行 | 独立的 `ai_solver` 注册表与状态机；门禁见 6.4 | 与 4.4A 分开，禁止混用状态与指标 |
| 训练成本 | 6 GB 显存下用小批量/梯度检查点/混合精度；必要时借服务器（`ExecutionBackend.remote` 已预留） | 场级模型比标量模型重得多，需排队与显存预算 |

**必须写进任何对外说明的现实边界**：AI 求解器在**同一物理族 + 参数化几何 + 已见拓扑 + 已声明范围**内可以做到免 COMSOL 求解；对**未见拓扑、强非线性/接触/失稳、强多物理耦合、需极高局部保真度**的问题，本阶段仍必须回退 COMSOL。**把这条边界写清楚，才是这个平台能被工程信任的前提。**

### 4.5 L4 增强闭环（三个增量来源）

**(a) 实验数据增强**

- 接入方式：结构化录入（CSV/JSON）或 DSH 网页对话录入；必填：设备、条件、原始数据、不确定度、操作人。
- 融合方式：不直接微调覆盖，而用**偏差/标定模型**（Kennedy–O'Hagan 风格：`y_exp = ρ·y_sim(x, θ) + δ(x) + ε`），同时反演不确定的物理参数（如材料常数、阻尼）。
- 触发出：实验点落在高不确定度区域 → 自动建议补充实验/仿真。

**(b) 文献数据增强**

- 管线：检索 → PDF 解析 → LLM 抽取 → **强制原文摘录 + 页码定位** → 人工/自动一致性校验 → 入库为 `evidence`。
- 硬规则（继承既有检索库原则）：**没有来源摘录，不输出具体设置/数值**；文献值默认标记为「文献级证据」，只有多源一致或被仿真复现后才可升级为训练标签。
- 抽取对象：材料参数（密度/弹性常数/压电系数/损耗）、几何典型值、工艺限制、实测性能指标、失效模式。
- 工具：DSH `web_search` + 本地 PDF 解析；`subagent` 并行抽取，交叉复核。

**(c) 人反馈增强**

- 反馈类型：①对预测的修正（给正确值/范围）；②对方案的取舍偏好（A 优于 B 及理由）；③对报告结论的接受/驳回 + 意见；④对失败案例的归因。
- 机制：全部落 `feedback` 事件表（append-only，不可改写历史）；反馈进入三类消费路径：
  - 修正值 → 作为校准数据（带权重，低于实验结果）；
  - 偏好对 → 排序/偏好模型（用于方案推荐排序）；
  - 驳回 + 意见 → 触发该条结论的重算与再评审，并作为 Skill/AGENTS.md 的规则候选。
- 在 DSH 里落点：报告生成时调用 `feedback_submit` 工具；`schedule` 定期汇总未处理反馈。

### 4.6 与 DSH 的耦合方式（关键实现）

**主通道 = 一个本地 Python MCP 服务器**（FastMCP，stdio），工具清单草案见附录 A。

`C:\Users\18161\.dsh\profiles\web\cordis.patch.yml` 追加：

```yaml
- id: mcp-mems-harness
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: mems
    transport: stdio
    command: D:\pathon\python.exe
    args: ['-m', 'memsharness.mcp_server']
    cwd: D:\memsharness_work          # ASCII 路径
    env:
      MEMS_DB: D:\memsharness_work\store\mems.duckdb
      COMSOL_MPH_PORT: '2036'
      COMSOL_HOME: D:\COMSOL64\Multiphysics
    toolCallTimeoutMs: 120000           # 提交类工具仍需秒级返回
    failOnStartupError: false
```

配合：

- 项目根 `AGENTS.md`：物理红线、单位、溯源、禁止编造数字、语言风格。
- `D:\桌面\memsharness\.dsh\skills\`：技能库（**需要项目根含 `.git`**，否则技能根回退到 cwd；因此 P0 执行 `git init`）。技能清单见附录 B。
- 长任务的三种编排模板：
  1. **小时级求解** → MCP `sim_submit` 返回 `run_id`，随后 DSH `jobs` / 轮询 `sim_status`；
  2. **多环节批处理** → DSH `workflow`，但**只并行非求解环节**；
  3. **多轮自主攻坚** → DSH `goal`（同会话多轮）或 `ralph`（每轮全新子代理，用文件做长期记忆）。

---

## 5. 仓库结构与产出物

```
D:\桌面\memsharness\                  # 文档 / 技能 / 配置（本工作区，可含中文）
├─ WORKING_PLAN.md                    # 本文档
├─ AGENTS.md                          # 项目级智能体指令（物理红线等）
├─ .git\                              # 使 .dsh/skills 成为有效技能根
├─ .dsh\skills\                       # 技能库（SOP/契约/规范）
├─ docs\                              # 设计文档、验收记录、模型卡导出
├─ schemas\                           # JSON Schema：job/dataset/model/evidence/feedback
├─ vendor\                            # 从 codex\comsol1 吸收的代码快照（注明来源与许可）

└─ work\                              # 运行区（数据/模型/产物；已在 .gitignore 中排除）
   ├─ .venv\                          # uv 建的独立 Python 环境（实测可用）
   ├─ store\mems.duckdb               # 元数据库
   ├─ data\{raw,interim,samples,parquet}
   ├─ artifacts\{mph,csv,fig,log}\    # 内容寻址产物
   ├─ runs\<run_id>\                  # 单次运行全部材料（可复现单元）
   ├─ models\{registry.json,cards\,ckpt\}
   ├─ reports\                        # 生成的报告（含证据链）
   └─ logs\
```

> **路径策略（P0 实测后修订）**：原计划把运行区放在纯 ASCII 路径 `D:\memsharness_work`，实测被两个约束否决——`D:\` 与 `C:\` 根目录受系统 ACL 限制无法创建目录，而工作区之外的目录每次写入都需要人工审批。实测又证明 `uv venv` 在中文路径下工作正常（仅 `python -m venv` 的 `ensurepip` 失败），且既有原型 `D:\桌面\codex\comsol1` 在此中文路径下已成功运行过 mphserver 与批量求解。**因此运行区确定为工作区内 `work\`**；同时在 `C:\Users\18161\memsharness_work` 保留了一个已建的 ASCII 目录作为「逃生舱」——仅当将来某项工具确实无法处理中文路径时，才把对应重活迁到那里（需人工授权写入）。

> 复现单元原则：`runs/<run_id>/` 必须能独立回答「这次数字是怎么来的」——含输入、模型哈希、软件版本、命令、日志、输出、抽取脚本版本。

---

## 6. 验证与可信度体系（平台的差异化价值）

### 6.1 验证等级

| 等级 | 内容 | 通过标准（示例） |
|---|---|---|
| L0 解析基准 | 每个模板对闭式解/极限情况 | 关键量相对误差 < 1%（1D），< 3%（2D） |
| L1 网格收敛 | 3 组网格 + Richardson 外推 | 相邻加密差异 < 1% 才允许进入扫描 |
| L2 守恒/能量 | 通量守恒、能量平衡、对称性 | 残差在容差内 |
| L3 交叉模型 | 2D vs 3D、降阶 vs 全阶 | 偏差可解释且 < 阈值 |
| L4 仿真留出集 | 未参与训练的 COMSOL 点 | 相对误差 < 用户设定阈值（默认 3%） |
| L5 实验对标 | 实测 vs 预测 | 落在预测区间内；否则触发校准 |

#### 6.1.1 AI 求解器（免 COMSOL）专用验证等级 S0–S5

代理层的 L 级指标衡量的是**标量/曲线**精度；AI 求解器给出的是**场**，必须用另一套指标，且**不得与 L 级混用**：

| 等级 | 内容 | 通过标准（示例，按问题标定） |
|---|---|---|
| S0 极限一致性 | 静态极限、低频极限、小信号极限与闭式解比对 | 极限下相对误差 < 1% |
| S1 场级精度 | 与 **COMSOL 独立留出集**逐点比对的相对 L2 误差 | 关键区域 < 2%，全域 < 5% |
| S2 工程量精度 | 由场解导出的工程量（f_r、Q、最大应力、灵敏度）误差 | < 3% |
| S3 物理一致性 | 守恒残差、边界条件满足度、对称性 | 守恒残差 < 0.5%；BC 残差 < 1% |
| S4 离散无关性 | 2–3 套网格上同一设计的结果一致性 | 差异 < 2% |
| S5 误差界校准 | 场级误差界的实际覆盖率 | 90% 界覆盖率 85–95% |

### 6.2 代理模型评分卡（每次训练必出）

- 误差：相对 RMSE / MAE / R²（按输出分量分别报，不做平均掩盖）。
- 不确定度校准：90% 区间覆盖率、区间宽度、CRPS。
- 泛化压力测试：几何族外推、极端参数、噪声注入。
- 外推风险：OOD 检测率、被拒请求统计。
- 成本：训练时间、推理延迟、显存占用。

### 6.3 放行门禁（Gate）

```
draft → (L0–L3 通过) → validated_on_holdout → (人工评审 + L4 阈值) →
calibrated_to_experiment → (人工评审 + L5 证据) → approved_for_use
```

门禁不通过时的固定动作：**不输出数值，只输出「需要补什么数据/做什么实验」**。

### 6.4 免求解器放行门禁（AI Solver Gate）

AI 求解器的状态机与代理层**完全独立**（不得用 L4 指标冒充放行依据）：

```
draft →（S0/S3 通过）→ physics_consistent
      →（S1/S2 达标 + S5 校准 + 独立留出集）→ solver_certified
      →（人工评审 + 适用范围签字）→ approved_solver
      →（漂移复检失败 / 越界误用）→ suspended
```

放行三条硬条件（缺一不可）：

1. **误差有界**：在**独立 COMSOL 留出集**（非训练点）上满足 S1/S2 阈值，且误差界覆盖率达标（S5）；
2. **物理自洽**：S3 全部通过；任一守恒/边界检查失败即不得放行——**与数据吻合不算数**；
3. **边界明确**：适用范围（物理族、几何拓扑、参数上下界、保真度、频率范围）与拒答率同时登记进 `ai_solver` 模型卡。

运行时强制规则：

- 每次免求解器出解都必须附 **场级误差界 + 验证等级 + 适用范围命中情况**；
- OOD 判定为超范围 → **拒绝出解**，自动排队 COMSOL，并在报告中如实写明回退原因；
- 按 `schedule` 定期抽样用 COMSOL 复检；命中漂移 → 状态降级 `suspended` 并触发再训练。

---

## 7. 阶段计划（P0–P7）

| 阶段 | 目标 | 主要交付物 | 验收标准 | 建议工期 |
|---|---|---|---|---|
| **P0 环境打通** | 端到端最小可跑 | venv（torch/mph/jpype/pint/duckdb/fastmcp）、COMSOL 三通路冒烟记录、`git init`、MCP server 空壳接进 DSH、`AGENTS.md` | 在 DSH 会话里能调用 `mcp__mems__ping` 且返回 COMSOL 版本与 license 状态；`comsolbatch` 跑通一个 1D 案例 | 2–3 天 |
| **P1 资产整合** | 吸收既有原型 | `vendor/` 快照 + 提取 `comsol/`、`ml/`、`store/` 骨架；`case_memory.json` 迁移 DuckDB | 既有 MLP 代理管线在新仓库跑通；旧案例记忆可查询 | 1 周 |
| **P2 仿真内核** | 可靠的求解服务 | 队列化 submit/poll、单实例调度、失败分类与重试、run 目录与溯源、网格收敛自动化 | 无人值守连续跑完 50 个扫描点，0 人工干预，失败可归因 | 1–2 周 |
| **P3 数据工厂** | 解析+多保真 | 解析模型库（MEMS 版）、降阶 1D 模型、DOE/LHS 采样器、增强计划生成、交叉一致性检查 | 解析基准测试全绿；能自动产出 ≥10⁴ 条 F0/F1 样本并标注保真度 | 1–2 周 |
| **P4 代理模型** | 带 UQ 的可用模型 | 训练管线（MLP 集成/GP）、UQ 校准、主动学习采样、OOD 防护、注册表 + 模型卡 | 留出集相对误差 ≤3%；90% 区间覆盖率 85–95%；主动学习比随机采样样本效率提升 ≥2× | 2 周 |
| **P4.5 AI 求解器** | **场级算子学习（免 COMSOL 求解）** | 固定网格场到场模型 → FNO/DeepONet；物理约束损失；场级 UQ（保形预测）；OOD 拒答与自动回退；独立 `ai_solver` 注册表与状态机 | 独立 COMSOL 留出集上场级相对 L2 ≤5%、工程量误差 ≤3%；S3 守恒/边界检查通过；**至少一个任务的端到端流程在零 COMSOL 调用下完成**并经 COMSOL 抽查验证 | 3–4 周 |
| **P5 增强闭环** | 三源持续增强 | 实验接入与校准模块、文献抽取管线（强制引用）、人反馈事件流与偏好模型、漂移监控与再训练触发 | 一轮实验数据接入后，目标量误差相对下降 ≥30%；文献数值 100% 带页码摘录；反馈可在 UI 提交并生效 | 2 周 |
| **P6 端到端示范** | 真实器件闭环 + 免求解器演示 | 以用户指定器件为对象，从需求到 5 个候选设计 + 置信度 + 证据链报告；**另跑一条"零 COMSOL"支线** | 全流程无需手工干预可复现；报告含每条数字的来源；零 COMSOL 支线的解经 COMSOL 抽查落在所报误差界内 | 1–2 周 |
| **P7 平台化** | 长期可用 | 可选 Web UI 面板（复用/重写 `web_app.py`）、多器件模板库、复现包导出、定时巡检与周报 | 连续运行 7 天无人工维护；新器件接入 ≤2 天 | 持续 |

**推荐节奏**：P0–P2 先做「能跑、能溯源」，再谈 AI 精度；避免在求解内核不稳时投入建模。

**工期口径（修订：消除原先"12 周"与阶段之和的矛盾）**：按第 7 节各阶段工期相加，P0–P6 合计 **约 11.5 周（乐观）～15.5 周（保守）**，因此全文统一表述为「**约 12–16 周**」，不再写"12 周内可达"（原表述只在乐观情形成立）。P7 为持续项、不计入。若必须压到 12 周以内，可选的取舍是：① P4.5 收窄到**单一物理族**（其余族延后）；② P5 的文献/实验闭环延到 P6 之后；③ P3 的解析模型库只做**首批 3 个**基准（其余按需补）。**取舍需你拍板，文档不擅自删减范围。**

**v0.2 节奏补充（针对"AI 替代求解器"）**：P4.5 是免求解器的关键阶段，但它**必须建立在 P2（可靠求解与溯源）与 P3（多保真数据）之上**——没有足量、带保真度标注、且不泄漏的数据，场级算子根本无法被验证。因此**不要把 P4.5 提前**；但可以从 P1 起并行准备三件事：数据契约（含场级输出存储格式）、留出集的几何族划分、以及"回退到 COMSOL"的接口。**允许先在小问题上做到免求解器（例如 2D 简化模型的单一物理场），再逐族扩展**——这比一开始就追求大而全的通用算子现实得多。

---

## 8. 关键指标（KPI）

| 维度 | 指标 | 阶段目标（P0–P6，约 12–16 周） |
|---|---|---|
| 仿真吞吐 | 无人值守完成的 COMSOL 扫描点数/天 | ≥ 50（2D 级） |
| 可靠性 | 任务成功率（失败可自动归因比例） | ≥ 95%（归因率 100%） |
| 数据质量 | 样本带完整溯源比例 | 100% |
| 代理精度 | 留出集相对误差（谐振频率/关键性能） | ≤ 3% |
| 不确定度 | 90% 预测区间覆盖率 | 85–95% |
| 样本效率 | 达到同等精度所需 COMSOL 点数（vs 随机采样） | 下降 ≥ 50% |
| 增强效果 | 接入实验数据后误差相对下降 | ≥ 30% |
| 可追溯 | 报告中每个数字可回溯到来源的比例 | 100% |
| 人机效率 | 需求 → 候选设计建议的墙钟时间 | ≤ 4 h（含真实求解） |
| **免求解器占比** | 在已放行范围内、**零 COMSOL 调用**完成的任务比例 | ≥ 80%（P6 之后） |
| **场级精度** | 独立 COMSOL 留出集上场级相对 L2 误差 | ≤ 5%（关键区域 ≤ 2%） |
| **免求解器加速比** | AI 前向场内求解 vs COMSOL 同一模型的墙钟时间 | ≥ 100× |
| **拒答质量** | OOD 拒答中确实超范围的比例（宁拒答不错答） | 拒答精确率 ≥ 90% |
| **验证成本** | 每个放行的 AI 求解器所需 COMSOL 留出点数 / 训练点数 | ≤ 20% |

---

## 9. 风险登记册

| ID | 风险 | 影响 | 缓解措施 |
|---|---|---|---|
| R1 | COMSOL license 并发/占用限制 | 并行任务互相拖垮或直接失败 | 单实例串行队列；求解环节禁用 `workflow` 并行；排队等待可见 |
| R2 | `.mph` 被 GUI 打开（已见 `.lock` 文件） | 无法写入/求解 | 运行前检查锁文件；复制到运行区后再改；生产模型只读 |
| R3 | 1 GB 级模型（`a_Oval shape.mph`）内存/IO 压力 | 求解失败或极慢 | 对称/2D 降维；参数化精简模型；大模型只用于少数验证点 |
| R4 | 求解不收敛 | 数据缺口、时间浪费 | 失败分类 + 自动降级（网格/求解器/初值）+ 记录为负样本 |
| R5 | 6 GB 显存 | 无法训大模型 | 限定中小模型；GP/集成走 CPU；必要时云端训练（留接口） |
| R6 | 数据泄漏（同族几何跨集） | 指标虚高，工程失效 | 按几何族分组切分 + 强制独立性检查 |
| R7 | 中文路径 / 编码混乱 | **P0 实测两次命中**：① `python -m venv` 的 `ensurepip` 在中文路径下直接失败（报错出现 `D:\????\memsharness`）；② **JPype/JVM**：从中文路径启动解释器时，MPh 连接 mphserver 报 `java.lang.UnsatisfiedLinkError: D:\: Can't find dependent libraries`（JVM 读到含中文的 site-packages 路径后被截断） | ① 改用 `uv venv`；② **建立 ASCII 交汇点**：`C:\Users\18161\memsharness_work\repo` junction → 仓库根，凡启动 JVM 或把路径交给 Java/COMSOL 的工具一律经该交汇点启动（实测 `sys.prefix`、`mph` 路径全为 ASCII，A 通路随即连通）。两条均写入 `AGENTS.md`；运行区收进 `work\`；全链路 UTF-8 |
| R8 | 35 MB 单文件案例记忆 | 加载慢、并发冲突 | 迁移 DuckDB，原文件冻结归档 |
| R9 | LLM 幻觉产出数值/设置 | 学术与工程风险 | 「无来源不出数」硬规则；工具返回值才可引用；文献强制页码摘录 |
| R10 | 授权模块与文档不一致 | 计划中的物理场不可用 | P0 逐模块冒烟枚举，把结果写入平台能力表 |
| R11 | MCP 60 s 超时误用 | 长任务被中断 | 提交/轮询分离；长跑走 DSH `jobs` |
| R12 | 平台与既有原型并行演化 | 维护双份、结论冲突 | P1 明确「吸收/冻结/废弃」三分类，旧目录只读封存 |
| **R13** | **AI 求解器 OOD 误用**：把超范围的解当成可信解 | 工程结论错误，后果严重 | 双 OOD 检测（参数马氏距离 + 物理量级越界）；无界外推一律拒答；报告强制显示适用范围命中情况；`schedule` 定期 COMSOL 复检 |
| **R14** | **"像样但物理错误"的平滑解**（损失降了、物理不成立） | 比明显报错更危险（会被当真值使用） | S3 物理一致性作为**硬门禁**；守恒/边界残差独立上报；极限与渐近检验；解析基准回归测试 |
| **R15** | **场级训练数据泄漏**（留出集与训练集同族几何） | 误差被系统性低估，放行判断失效 | 按 `geometry_family` **整族切分**；留出集必须含未见族；泄漏检查结果写入 `dataset.report` 后才允许训练 |
| **R16** | **场级模型超出本机资源**（6 GB 显存/内存） | 训练失败或被迫缩小到失真规模 | 小批量 + 梯度检查点 + 混合精度；必要时经 `ExecutionBackend.remote` 借服务器；**先在 2D 简化模型上做出来**再上 3D |

---

## 10. 治理与红线

1. 任何模型输出必须携带：模型 ID + 版本 + **验证等级（L 级或 S 级）** + 适用范围 + 不确定度/误差界 + OOD 标记。
2. 报告中的每个数字必须能一键回溯到 `run_id` / `evidence_id` / `experiment_id` / `feedback_id`；**免求解器输出额外必须回溯到 AI 求解器版本 + 该次适用范围命中判定 + 误差界**。
3. **两类模型、两套放行口径**：代理层未过 L4 阈值的只允许「比较趋势」；AI 求解器未过 **S1/S2/S3/S5（6.4 门禁）** 的，**禁止在不调用 COMSOL 的情况下给出场解或工程量绝对值**。
4. **必须新增第六种来源 `ai_solver`**：AI 求解值与 COMSOL 仿真值在可信度与验证要求上根本不同，混为一类会污染数据层。因此 `source_type` 从五种扩为六种（`simulation` / `analytic` / `literature` / `experiment` / `human_feedback` / **`ai_solver`**），并同步更新 `store.py` 与 `dataset-contract` 技能。**AI 求解值禁止伪装成 COMSOL 结果**，必须带误差界、验证等级与拒答判定。
5. 文献值、人反馈值、实验值、仿真值、AI 求解值在数据库里**永不混同**，各带 `source_type` 与独立权重。
6. 所有历史 append-only；修正通过新增记录实现，不覆盖。
7. 平台不猜测 `.mph` 内部结构：读不到就报「需要导出报告」，不编造模型设置（继承既有检索库原则）。
8. **免求解器不得无界外推**：超出已声明适用范围 → 拒答 + 回退 COMSOL + 报告写明原因。「能算」不得当作「算得对」；**任何把 AI 解包装成"已验证等价于 COMSOL"的表述都属于违规**。

---

## 11. 待确认的决策点

| # | 决策 | 状态与结论 |
|---|---|---|
| D1 | 首个端到端目标器件 | ✅ **已确认：由用户稍后指定具体器件**（非 PMUT 默认方案）。因此 **P0–P5 必须先做「器件无关核心」**：参数空间、指标、模板、验证全部通过声明式配置（`device_spec`）定义，不把任何器件硬编码进内核。P6 示范对象待用户补充后填入；既有 20 MHz PMUT 资产（`D:\桌面\换能器学习\`）降级为「候选示范对象之一/回归测试语料」。 |
| D2 | AI 模型主要输出形态 | **按路线分开（v0.2 修订，原表述已作废）**：4.4A 代理层先做**标量/曲线 + 不确定度**（用于筛选与优化）；**4.4B AI 求解器直接做场级输出**——场级是免求解器的前提，**不存在"第二阶段才做场"**。两条路线的输出形态、指标与注册状态各自独立，禁止互相冒用 |
| D3 | 是否已有实验数据 | ✅ **已确认：暂无**。P5 先建「实验接入接口 + 模拟实验闭环（synthetic experiment，含噪声与系统偏差建模）」；同时产出「最小实验清单」作为后续真实验的前置条件。实验校准逻辑用模拟数据先行验证。 |
| D4 | 计算资源边界 | ✅ **已确认：本机为主 + 另有可借用的服务器/集群**。P0–P2 只实现本机执行后端，但 L1 从第一天就抽象 `ExecutionBackend` 接口（`local` / `remote`），为后续把重型 3D 求解与训练迁到集群预留 seam；本地保留 license/队列语义。 |
| D5 | 平台形态 | **DSH 会话驱动（MCP + Skills）为第一形态**；独立 Web UI 放 P7 |
| D6 | 与既有 `codex\comsol1` 的关系 | 吸收可复用模块后**冻结为只读**，新平台为唯一真相源 |
| D7 | 语言与规范 | 文档中文；代码注释中文为主、标识符英文；单位全程 SI + pint |
| **D8** | **AI 求解器的首个免求解器目标问题类** | **建议：从"单一物理场 + 参数化几何 + 已见拓扑"的 2D 简化模型起步**（例如 2D 传热/固体力学/声学腔体），先把「免 COMSOL 出解 + 误差界 + 拒答 + 复检」的完整闭环跑通，再按物理族逐个扩展。**不建议**首个目标就选强多物理耦合或含拓扑变化的问题 |
| **D9** | **免求解器输出的验收门槛** | 建议：场级相对 L2 ≤ 5%（关键区域 ≤ 2%）、工程量误差 ≤ 3%、守恒/边界检查必过、误差界 90% 覆盖 85–95%、拒答精确率 ≥ 90%。**具体阈值需按你的器件与容差要求拍板** |
| **D10** | **能否接受"拒答率"作为常态** | 建议接受：AI 只在已放行范围内出解，超范围一律回退 COMSOL。若你希望"尽量都让 AI 算"，则需要显著扩大数据与验证成本，请明确取舍 |

> **由 D1 派生的设计约束（重要）**：内核不得依赖任何具体器件。参数、性能指标、解析模型、验证阈值一律来自 `device_spec.yaml` / `task_spec.json`。P0–P2 的试点用既有的通用已验证模板（1D 传热/扩散/电热、2D 固体力学）作为「器件无关」的回归语料，验证管线本身而非器件物理。

---

## 12. 未来 3 天立即行动清单（P0）

**Day 1 — 通路验证**
1. `git init` 于 `D:\桌面\memsharness`（激活 `.dsh/skills` 技能根）。
2. 建运行区与 ASCII 交汇点：运行区用**仓库内 `work\`**；另建 `C:\Users\18161\memsharness_work\repo` junction 指向仓库根，供**任何启动 JVM 的工具**（MPh/JPype、Java 客户端）使用——实测 `D:\` 根目录被系统 ACL 拒绝，且中文路径会让 JPype 报 `UnsatisfiedLinkError`。
3. `uv venv` 建独立环境并装：`numpy scipy pandas scikit-learn pint duckdb pyarrow fastmcp mcp`（torch 留到 P4 再装）。
4. 写 `scripts/smoke_comsol.py`：读 COMSOL 版本 + license + 端口 2036 连通性；跑一个最小 1D 模型（复用既有 `one_dimensional_heat_conduction` 配置）。
5. 逐模块冒烟：MEMS / Structural Mechanics / Acoustics / RF / Heat Transfer / Optimization，产出「平台能力表」。

**Day 2 — MCP 接进 DSH**
6. 实现 `memsharness/mcp_server.py`，先暴露只读工具：`ping`、`env_report`、`module_capability`、`data_stats`、`records`、`run_trace`（P4.5 再增 `ai_solve`（免求解器求解）与 `solver_status`）。
7. 在 `~/.dsh/profiles/web/cordis.patch.yml` 注册 MCP server，重启 DSH Web，验证 `mcp__mems__*` 工具可用。
8. 写 `AGENTS.md`（红线 + 单位 + 溯源 + 语言）与首批 3 个 Skill（COMSOL 建模 SOP、数据契约、报告规范）。

**Day 3 — 最小闭环**
9. `sim_submit` / `sim_status`：文件队列 + 单实例 worker（移植既有 `execution_worker.py` 的锁与状态模式）。
10. 跑通「1 个模板 × 8 个参数点 → 入库 → 训练 MLP → 出模型卡」的端到端最小链路，并在 DSH 会话里由智能体自主完成一次。
11. 产出 P0 验收记录 `docs/P0_acceptance.md`（含实测命令、输出、结论、遗留问题）。

**v0.2 追加前置项（为「免求解器」铺路，P1–P3 期间完成）**

12. **场级输出存储格式**：定义场的落盘约定（建议 HDF5/Parquet + 显式网格/节点坐标 + 单位 + 提取器版本），让 F2/F3 求解结果的**场**（而不只是标量）可训练、可复算、可逐点比对。
13. **来源标识扩展**：新增 `source_type = 'ai_solver'`（与 `simulation` 严格区分），同步改 `store.py` 的 `SOURCE_TYPES` 与 `dataset-contract` 技能；AI 求解值必须携带误差界与验证等级。
14. **留出集划分脚本**：按 `geometry_family` 整族切分，强制「留出集含未见族」，产出 `dataset.report` 的泄漏检查结果（R15 的缓解手段）。
15. **回退接口预留**：先把「AI 拒答 → 自动排队 COMSOL → 结果回写并复检」的接口与状态字段留出来（P4.5 才实现算法本身）。
16. **物理一致性检查器**：先写 S3 的检查原语（守恒残差、边界条件残差、对称性、极限一致性），因为它是免求解器的**安全网**，必须先于算子模型存在。

---

## 附录 A：MCP 工具清单（草案，`mcp__mems__*`）

| 组 | 工具 | 说明 | 同步/异步 |
|---|---|---|---|
| 环境 | `ping`、`env_report`、`module_capability` | 健康检查、版本/授权/端口、模块能力表（区分「文档存在」与「求解已验证」） | 同步 |
| 模型 | `model_inspect`、`model_diff`、`model_export_summary` | 只读模型树/参数；不猜测内部设置 | 同步 |
| 仿真 | `sim_submit`、`sim_status`、`sim_logs`、`sim_cancel`、`sim_retry` | 队列化求解，返回 `run_id` | 提交同步/执行异步 |
| **AI 求解器** | `ai_solve`、`solver_status`、`solver_verify`、`solver_registry` | **免 COMSOL 出解**（返回场 + 误差界 + 适用范围判定）；超范围自动拒答并排队 COMSOL；`solver_verify` 触发留出集/物理一致性复检 | 同步（AI 前向很快）/复检异步 |
| 采样 | `design_sample`、`augmentation_plan`、`sweep_preview` | DOE/LHS/主动学习建议、增补工况计划 | 同步 |
| 数据 | `dataset_build`、`dataset_query`、`dataset_card`、`run_trace` | 数据集版本、查询、溯源追踪 | 同步 |
| 解析 | `analytic_eval`、`analytic_benchmark` | 解析解/降阶求值与其基准测试 | 同步 |
| 建模 | `train_surrogate`、`eval_surrogate`、`calibrate_model` | 训练、评分卡、校准 | 提交同步/执行异步 |
| 优化 | `suggest_next`、`rank_designs`、`optimize` | 主动学习/多目标推荐 | 同步（可流式） |
| 注册 | `registry_list`、`registry_promote`、`registry_deprecate` | 模型状态机与门禁 | 同步（晋升需人工批准） |
| 增强 | `experiment_ingest`、`literature_extract`、`evidence_query`、`feedback_submit` | 三源增强入口 | 同步/异步 |
| 报告 | `report_generate`、`report_export` | 带证据链的报告 | 同步 |

## 附录 B：Skill 清单（草案，`.dsh/skills/<name>/SKILL.md`）

1. `comsol-modeling-sop` —— 建模顺序、选择集核对、单位、常见失败与处置。
2. `comsol-batch-runbook` —— 队列、锁、license、日志、失败分类与重试。
3. `mems-analytic-benchmarks` —— MEMS 解析解公式与其适用边界（f_r、pull-in、阻尼、噪声）。
4. `dataset-contract` —— 样本/溯源必填字段、保真度标注、几何族划分防泄漏。
5. `surrogate-training-sop` —— 训练、UQ 校准、评分卡、门禁阈值。
6. `active-learning-playbook` —— 何时采样、采样准则、多目标权衡。
7. `literature-evidence-sop` —— 强制原文摘录与页码定位、多源一致性判定。
8. `experiment-calibration-sop` —— 实验录入、偏差模型、参数反演。
9. `report-and-evidence` —— 报告中每个数字的来源标注规范与免责表述。
10. `pmut-domain-brief` —— 本器件族（PMUT/OvalDE 20 MHz）的领域知识与既有模型索引。
11. **`ai-solver-verification`**（v0.2 新增，**优先级最高**）—— 免求解器放行流程：S0–S5 指标定义与测量方法、物理一致性检查（守恒/边界/对称/极限）、OOD 拒答判据与阈值、回退 COMSOL 的触发与记录、`ai_solver` 模型卡必填字段、以及「不得无界外推」的话术规范。
12. `field-io-contract`（v0.2 新增）—— 场级数据的存储与比对约定（网格/节点坐标/单位/提取器版本），以及场级误差（相对 L2）的计算口径。

## 附录 C：既有资产映射表

| 现位置 | 新位置 | 处理 |
|---|---|---|
| `comsol_training_small_model\execution_worker.py` + `execution_jobs.py` | `memsharness\comsol\queue.py` | 吸收重构 |
| `comsol_server.py` + `configs\execution_node.json` | `memsharness\comsol\adapter.py` + `config.yaml` | 吸收（补 B/C 通路） |
| `execution_diagnostics.py` | `memsharness\comsol\diagnostics.py` | 吸收扩展 |
| `surrogate*.py`、`holdout_independence.py`、`mesh_convergence.py`、`parameter_coverage.py`、`result_validation.py` | `memsharness\ml\`、`memsharness\verify\` | 吸收（补 UQ/主动学习） |
| `ONE_DIMENSIONAL_MODEL_LIBRARY.md`、`one_dimensional_web_lab\` | `memsharness\data\analytic\` | 泛化为 MEMS 版 |
| `comsol_kb.py`、`case_memory.json`、`*_knowledge.py` | `memsharness\knowledge\` + DuckDB | 迁移 + 保留引用原则 |
| `work_feedback.py`、`staged_modeling.py` | `memsharness\feedback\` | 演进为事件流 |
| `D:\桌面\换能器学习\*.mph`、`PMUT_SAL_GE_*.pdf` | 只读引用 | 首个示范对象的输入 |
| `D:\桌面\mems论文\*.pdf` | 文献抽取种子 | 文献闭环首批语料 |

---

## 13. 附：一次短暂 P0 实施的记录（**实施已暂停**）

> **说明（重要）**：本计划正文为第 1–12 节。本节只是「曾经动手搭过一小段 P0 骨架」的历史记录，
> 供你决定是否复用其中的环境结论；**不代表当前已承诺进入实施阶段**。若要纯计划版本，删除本节即可。
> 其中被实测确认的环境事实（第 2 节、风险 R7、第 5 节路径策略）已回写进正文，可独立阅读。

| P0 任务 | 状态 | 证据 / 产物 |
|---|---|---|
| 仓库骨架 + `git init`（激活技能根） | ✅ | `.git` 已初始化；目录 `.dsh/skills`、`docs`、`schemas`、`scripts`、`src/memsharness`、`tests`、`work`、`vendor` |
| 项目级智能体指令 | ✅ | `AGENTS.md`：6 条红线（无证据不出数、物理优先、不猜测 .mph、来源不混同、人工门禁、append-only）+ 环境事实 + 执行约定 |
| 运行区与 Python 环境 | ✅ | `work\.venv`（**用 uv 创建**）；numpy/scipy/pandas/scikit-learn/pint/duckdb/pyarrow/pyyaml/jsonschema/fastmcp/pytest；本包 editable 安装 |
| COMSOL 环境冒烟 | ✅ | `scripts\smoke_comsol.py` → COMSOL **6.4.0.293**、6/6 可执行文件、授权文件齐备、MATLAB R2025b + LiveLink 存在、**mphserver 在 127.0.0.1:2036 监听**、8 个相关模块文档齐备；报告落在 `work\reports\env_report.json` |
| **三通路实测（A/B/C）** | 🔄 A ✅ / B 🔄 / C ⏳ | **A 通路（Python MPh + mphserver）已实测通过**：`scripts\smoke_pathway_a.py` → `import mph 1.4.0` → 连接已运行的 mphserver（6.4）→ 8.39 s 载入模型 → 读到 10 个参数（含解析参考式 `f10_ref = c_air/(2*Lx)` 等）、物理场「压力声学，频域」、研究 1；证据 `work\reports\pathway_a_mph.json`。**注意**：必须经 ASCII 交汇点启动解释器（见风险 R7）。B 通路（Java API + `comsolbatch`）由子代理实测中；C 通路（既有 `.mph` 批量）待做 |
| 元数据库与数据契约 | ✅ | `src\memsharness\store.py`：12 张表；`insert_sample` 拒绝非法 `source_type` 与空样本；查询强制行数上限 |
| 模型层（不确定度 + 防泄漏切分） | ✅ | `src\memsharness\ml\surrogate.py` + `scripts\train_surrogate.py`：合成关系 y=2x+1 上 R²=0.9988；分组切分断言「同族几何不跨训练/测试集」；小样本与未校准区间被显式警告；新模型状态固定 `draft` |
| MCP 接入 DSH | ✅ 链路已验证 / ⏳ GUI 待重启 | 补丁写入 `~\.dsh\profiles\web\cordis.patch.yml`；`--dump-config` 组装通过；**headless 端到端验证 6 个工具中的 4 个**：`env_report` 返回 6.4.0.293 与 mphserver 监听=True、`module_capability` 的 `solve_verified` 全为 `null`（未验证就不冒充已验证）、`data_stats` 返回 12 张表、`records(table="sqlite_master")` 被白名单正确拒绝 |
| 测试 | ✅ | `14 passed`（`tests\test_p0_foundation.py`、`tests\test_ml_pipeline.py`） |
| 技能库（首批 3 个） | 🔄 | `comsol-modeling-sop` 已在会话技能目录中生效；`dataset-contract`、`report-and-evidence` 与 `docs\skills_enablement.md` 撰写中 |
| COMSOL 参数扫描队列 + 真实数据入库 | 🔄 | 进行中：`src\memsharness\comsol\`（后端抽象 / 文件队列 / 单实例锁 / 失败分类 / Java API 模型）+ `scripts\run_sweep.py`，目标 ≥8 点真实求解入库 |
| 逐模块求解能力冒烟 | ⏳ | 待真实扫描跑通后按模块回填 `module_capability` 的 `solve_verified` |
| P0 验收记录 | ⏳ | `docs\P0_acceptance.md` |

### P0 期间被实测推翻的假设（已回写文档）

1. **补丁层是定向补丁，不是新增列表**：不带 `insert` 的条目按「覆盖既有 id」处理，找不到 id 会报 `patch: entry "xxx" not found`；新增条目必须写成 `- insert: [...]`。（已修正 `docs/dsh_mcp_registration.md`）
2. **运行区不放在 `D:\memsharness_work`**：`D:\` 与 `C:\` 根目录受系统 ACL 限制无法创建目录；改用工作区内 `work\`。（已修正第 5 节与风险 R7）
3. **`python -m venv` 在中文路径下必失败**（`ensurepip` 报错路径出现 `D:\????\memsharness`），必须用 `uv venv`。（已写入 `AGENTS.md`）
4. **HMR 不会新增插件条目**：改完补丁层后并未出现 `memsharness.mcp_server` 子进程，MCP 需**重启 DSH 服务**才在 GUI 生效。
5. **技能能力实际可用**：会话技能目录中已动态出现 `comsol-modeling-sop`，说明技能发现链路是通的（此前对 `--dump-config` 输出的解读有误——那条 `disabled: true` 来自 bundle 层，已被 web-app 层重新启用）。

---

*本计划为 v0.1 草案，P0 执行记录见第 13 节。确认第 11 节决策点后即进入 P0，并在每阶段结束时更新本文档与验收记录。*
