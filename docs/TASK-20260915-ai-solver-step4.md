# 任务单：AI 求解器「第 4 步」——用单电极驱动数据拟合代理模型

- 下达时间：2026-09-15 11:05
- 下达人：用户（选择「用它拟合/训练代理模型（启动 AI 求解器第 4 步）」）
- 执行者：实现者子代理
- 前置：第 1–3 步已完成并收口（`work\ai-solver\`、报告 `docs\TO_CODEX_record-20260915-ai-solver-baseline.md`）
- 数据：**用户自己单电极驱动测出来的数据**（已核对，见 §1）

---

## 0. 一句话目标

在**用户已有的单电极（legacy 1 Ω）数据域内**，把代理模型真正拟合出来，并同时给出
**可复核的误差界（保形预测 S5）**、**适用域命中判定**与**越域拒答**；
不得声称超出该域的能力，不得声称等价于 COMSOL，不得入库为 `source_type='ai_solver'`。

## 1. 数据身份（已由父代理核对，不必重查，但要在产物里引用）

| 项 | 值 |
|---|---|
| 用户原文件 | `C:\Users\zmx\Desktop\换能器\扫描阵列Xrange(0.4,0.05,0.8).xlsx` |
| sha256 | `33ed711c8d53bf02f69686e8e1c62815587919588d73293a5ce899c903951403`（141,355 B） |
| 平台已入库副本 | `work\reports\analysis_decision\newrange005\raw_source_table.csv`，sha256 `777d0306c569a874086d231130cfdf75808d3fe87cda3f7bfc0dffc4fbe3210a` |
| 逐格比对 | 用户 xlsx vs 平台副本 **4536 个单元 0 处不一致**（父代理实测） |
| 形状 | 1134 行 = 162 组合（x_scale 9 档 × N_w_te1 1..18）× 7 频点（5..35 MHz，步长 5） |
| 模型 | `b_GE_task3_2new.mph`，sha256 `0f75ca1df9262f27…`（legacy 单电极驱动模型） |
| 驱动 | `legacy_1ohm_to_reference`（**只有这一种**；反相驱动数据尚不存在） |
| 已有列 | `x_scale, N_w_te1, freq(Hz), Zin1_R/X, Zin2_R/X, Ptot(W), V_center(m/s)[复数串], Vave(m/s)` |
| 已知数据缺陷 | `Zin1 ≡ Zin2` 逐位相同（公式复制错误）⇒ **电气指标不得当独立量使用** |
| 族划分（已有） | intended 72 / reversed 81 / boundary 9（见 `work\ai-solver\domain\applicable_domain.json`） |

## 2. 必须复用的既有能力（不要重写）

先读这些文件确认接口，再写代码；在报告里列出**实际调用的函数名与文件 sha256**：

- `src\memsharness\dataset.py`：`load_groupable_samples` / `split_by_family` / `build_dataset`（含族泄漏检查）
- `src\memsharness\ml\surrogate.py`：`load_samples` / `grouped_split` / `SurrogateEnsemble` / `score` /
  `save_model` / `write_model_card` / `register_model` / `new_model_id` / `discover_columns`
- `src\memsharness\pod.py`：`conformal_quantile`（**保形分位数**）
- `src\memsharness\consistency.py`：S3 原语 + `evaluate_s3`（硬门禁，`release_allowed` 只有 `verdict=="passed"` 才为真）
- `work\tools\lt3_prep.py`：`read_grid`/`parse_complex`/`to_float` 等（只读 import，沿用第 1–3 步做法）
- 第 1–3 步产物：`work\ai-solver\domain\applicable_domain.json`、`cv\split_assignments.csv`

若某个接口不适用（例如 `load_samples` 要求 `store` 里的表），**如实说明并给出你实际用的路径**，不要硬套。

## 3. 要交付的东西

### 3.1 拟合（域内，可复核）

- 逐频点建模（沿用第 1–3 步的结论：响应在频率上强非单调，单频基必错设）。
- 目标：`Ptot`、`Vave`（**不给** `Zin*` 的独立模型，理由写进报告：`Zin1≡Zin2` 已知缺陷）。
- 至少三个模型 + 一个对照：**岭回归**、**高斯过程**、**梯度提升**，对照用常数/全局均值。
- 超参**只在训练部分**选（内层 CV），不得用留出集调参。
- 特征：`x_scale`、`N_w_te1`（可加你认为有物理依据的派生特征，但必须写明并做消融）。

### 3.2 切分（诚实性优先）

必须同时给出并对比：

1. **整族留出**（跨族）：train = intended(72)，test = reversed(81)。这是第 1–3 步认定的唯一正当 OOD 口径；
   预期它**会**失败——那正是有价值的负结果，如实报告，不要调参去救。
2. **族内分块留出（不得泄漏）**：在 intended 族内，分别做
   ① 留出整列 `x_scale`（留一列）、② 留出整行 `N_w_te1`（留一行）、③ 分组 k 折（**按 x 列或按 N1 行分组**，不能按点随机）。
   每个都必须**通过族泄漏检查**才算有效 OOD；不通过就标 `valid_ood_estimate=false`。
3. **随机切分**：只作**泄漏对照**，必须明确标注 `kind=random_LEAKY_REFERENCE`，
   并给出「随机 vs 诚实分块」的误差比值表（这是有结论价值的对照）。

### 3.3 误差界：保形预测（**这是本轮的关键新增**）

第 1–3 步的结论是「无法做保形误差界」——**该结论要重新检验**。保形预测用的是**留出真值**，
不是逐样本不确定度字段，所以在本数据上应当**可做**。请：

- 非一致性得分：`|真值 − 预测| / σ`（逐组合一个标量；σ 用训练部分残差的稳健尺度，写明定义）；
- 用 **LOO 重拟合**取分（不得用训练偏差自证校准）；
- 分位数用 `pod.conformal_quantile`；`alpha=0.1` ⇒ **至少需要 9 个校准点**，不足时返回 `inf` 且 `certified=false`（这是正确结论）；
- 在**未参与校准**的留出块上报告**实测覆盖率**（目标 85–95%），并与「用残差标准差硬凑的区间」做对照（后者覆盖率会崩，要给出实测数字）；
- `s5_passed` 未认证时必须是 `null`，**不是** `True`。

### 3.4 适用域与拒答（要**真的**触发）

沿用并代码化 `applicable_domain.json`，实现一个 `predict(...)`：越域即**拒答**，返回
`{refused: true, reason, fallback: "COMSOL"}`。至少覆盖这五类越域，并各给一个真实调用示例与返回：

1. `drive_mode != legacy_1ohm_to_reference`（例如反相驱动查询）；
2. `freq` 不在 5/10/15/20/25/30/35 这 7 个精确值上（**不声明**频率插值能力）；
3. 族不在允许集合内；
4. `x_scale` / `N_w_te1` 超出观测盒；
5. 目标量不在 `{Ptot, Vave}` 内。

并给出**域内**正常调用的示例（同一函数、同一入口），证明拒答不是"永远拒答"。

### 3.5 S 级状态（如实，不许凑）

按技能 `ai-solver-verification` §2 逐级给结论，**每一项都要写"能不能测、为什么"**：

| 级 | 本轮预期 | 要求 |
|---|---|---|
| S0 极限一致性 | 不可测（需闭式解/低频极限） | 说明缺什么 |
| S1 场级相对 L2 | **不可测**（本数据只有标量指标，没有场快照） | 说明要 COMSOL 场留出 |
| S2 工程量误差 | **可测** | 给留出集误差 |
| S3 物理一致性 | 多半 `inconclusive` | 用 `evaluate_s3` 跑，**如实**接受 `release_allowed=False`，不得改阈值凑通过 |
| S4 网格无关性 | 不可测（单网格） | 说明缺什么 |
| S5 误差界校准 | **可测**（本轮新增） | 给覆盖率 |

**最终放行状态**：预计**不能**达到 `solver_certified`（缺 S1）。给出你的判定与理由，
并明确写出「因此本模型只允许用于**域内筛选/趋势**，不得输出用于工程判断的绝对值」。

### 3.6 来源分离（红线 4/8）

- 真值 `source_type='simulation'`、预测 `source_type='ai_solver'`，**分列**存放；
- **禁止**把两者合并成一个统计量；所有统计只对**相对误差**（派生诊断量）做；
- 明确写「本产物**不得**入库为 `source_type='ai_solver'` 样本」及原因（缺 S1/`model_id` 级验证）。

## 4. 硬约束（违反即本轮作废）

1. **不改**：`work\tools\` 下任何文件、`src\memsharness\` 下任何文件、`work\runs\` 下任何**既有**目录、
   用户目录 `C:\Users\zmx\Desktop\换能器\` 下任何文件、`work\reports\analysis_decision\newrange005\` 下任何文件。
2. **只写**：`work\ai-solver\step4\`（新建）与 `docs\`（新增文件）。不要覆盖第 1–3 步产物。
3. **不跑 COMSOL**、**不启动 mphserver**、**不跑 pytest**。
4. Python 一律加 `-B` 且设 `PYTHONDONTWRITEBYTECODE=1` + `PYTHONPYCACHEPREFIX`，**不得留下 `__pycache__`**
   （历史上一次 `__pycache__` 直接作废了一整个冻结）。
5. 报告必须**每个数字可回溯**到具体产物文件 + sha256；不得凭记忆写数。
6. 不得晋升任何模型状态（`draft` 就是 `draft`）；不得声称「已验证等价于 COMSOL」。

## 5. 必须报告的内容（提交时逐条给出）

1. 实际调用的既有函数清单 + 其文件 sha256；哪些接口不适用、替代路径是什么；
2. 三套切分的误差表（含随机对照与「诚实/随机」比值），并标明哪些是**有效 OOD**；
3. 保形校准：校准点数、`alpha`、分位数、`certified`、留出集**实测覆盖率**、与「残差标准差硬凑」的对照数字；
4. 五类越域拒答的**真实调用与返回**（原文），以及一次域内正常调用；
5. S0–S5 逐级结论 + 最终放行状态 + 为什么；
6. 产物清单（路径 + 字节数 + sha256）；
7. **主动披露**任何越界写入、任何"为了让测试通过"的改动、任何你不确定的地方。

## 6. 允许的结论形态

「域内可用、有实测覆盖率、有拒答边界，但**未达 S1 ⇒ 不构成免 COMSOL 求解器**」
是本轮**完全可接受且预期**的结论。**不要**为了好看去凑 S 级或放行状态。
