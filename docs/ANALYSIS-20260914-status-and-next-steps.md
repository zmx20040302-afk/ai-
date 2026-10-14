# 现状问题分析与下一步工作规划

> ⚠️ **本文档的状态/计划部分已过时（截至 2026-09-29 晚）**：此后仓库又推进了多轮，
> 以 **`docs/INDEX-records-and-rulings.md` §30–§80** 与 **`docs/UNFINISHED_TASKS_AUDIT.md`** 为准；
> 阶段现状见 **`WORKING_PLAN.md` §7.1**。本文档保留作**历史记录**，不改写。


- 日期：2026-09-14
- 范围：PMUT 端到端首个器件的 **LT0–LT3** 工作流 + 平台主线
- 口径：本文区分**已确诊（有可复算证据）**、**假设（待检验）**、**未知**三类；不得混用
- 结论先行：**当前唯一阻塞项是「正式验收批次未通过」**；物理与数据分析侧的瓶颈是
  **7R 轴向声压判据缺位**与**频段上界不足**

---

## 1. 目标与当前位置

终局目标（`AGENTS.md` §1）：人给一句需求 → 平台自动跑 COMSOL 产数据 → 训练代理模型/AI 求解器
→ 最终**不调 COMSOL 也能出带误差界的解**。COMSOL = 教师 + 验证器 + 兜底裁判。

当前位置：**§4.1 执行与验收层**（作业队列 / 单实例串行 / 资源门禁 / 实时监控 / 冻结与验收）。
这一层不产物理结论，但它是「L0 数据可信」的前置——没有它，LT2 的 504 点跑出来也说不清挂在哪个版本上。

```
§4.1 执行与验收层   ← 现在在这里（唯一阻塞处）
§4.2 L0 数据与溯源层 ← LT2 504 点将进入这里（尚未开始）
§4.4 / §4.4B 代理模型 / 场级 AI 求解器 ← 很远
§6.3 / §6.4 放行门禁 ← 未来模型晋升时才用
```

---

## 2. 已确诊的事实（可复算，带证据锚点）

### 2.1 资源轴：已解决

| 项 | 值 | 证据 |
|---|---|---|
| 页面文件 | 固定 12,288 MB（原自动管理 4,873 MB） | 用户授权后重启生效 |
| commit limit | **44,477.4 MB**（原 37,063.0） | 预测 44,478 / 实测 44,477.4（误差 1.4e-5） |
| 求解期 commit 最低 | **17,409.9 MB**（原 647.3 MB，**27 倍**） | `lt2-resource-confirm-x080-n02-postpagefile-r2`，154/154 采样 `ok` |
| 判定 | `post_pagefile_runtime_resource_axis = PASS` | 仅限当前机器/负载/模型/单 server 串行 |

### 2.2 架构关键假设：已真机证实

- **U5**：`parent_is_worker = true` ⇒ 每组合一个全新 combo-worker 进程**确实绕开**「MPh 单会话单 client」约束；
- **U7**：`pid_source = port_owner`（等 0.6 s）⇒ 端口取 PID + 父子关系在真实 MPh 链上可用。

### 2.3 已确诊的生产缺陷 B（本次最重要的收获）

```text
症状 = sampler 产出 3 个样本后 rc=2 自杀 ⇒ supervisor 见 sidecar_exited
       ⇒ sampler_supervisor_integrity ⇒ 整个逻辑批 blocked
根因 = Windows os.replace(tmp → target) 在目标被读取时抛 WinError 5，
       而 rt_gate.atomic_write_json **无重试**
必要条件 = 「有人同时读 state」——生产天然成立（supervisor 每 2.5–3 s 轮询 vs sampler 每 5 s 写）
证据链 = 冻结无漂移 → namespace 隔离已修掉目录争用 → 40 轮直接调用不复现
        → 定向复现（加并发读）拿到 traceback → 受控 A/B 7/80 → 0/80 → retried=204 证明触发过
修复 = rt_gate.atomic_write_json 加 WinError 5/32 有界重试 5×50 ms（fail-closed 未软化）
范围验证 = 以 1750 快照作基线 diff：64 处改动**全部落在该函数内，函数外 0 行**
```

**影响判断**：这不是测试卫生问题，而是**生产缺陷**——一个偶发崩溃可作废 16 小时无人值守批次。

### 2.4 数据分析侧：LT3 三层已完成

| 层 | 产出 | 关键结论 |
|---|---|---|
| 前置管线 | 质检 / 指标拆分 / Pareto / 归一化契约 / 守卫三重 | 1134 行唯一键、0 重复、0 缺、0 负 `Ptot` |
| LT3-D 归一化对照 | 15 行（5 组合×3 频点） | 原始 `Ptot` 比值 **0.8377–4.2974（不恒为 4）**；归一化后仍 0.2094–1.0743 ⇒ **不得读成结构收益** |
| LT3-B 频响指标 | `lt3_response_metrics.csv`(162×88) 等 | **四对 Pareto 全部不再退化**；P2 前沿 4 点全在 `x=0.75, N1=2…5`（同缩放下用内电极宽度换带宽–平坦度） |

---

## 3. 现有问题（按阻塞程度分层）

### 3.1 阻塞级

| # | 问题 | 状态 | 影响 |
|---|---|---|---|
| P1 | **正式验收批次未通过** | `credit = ABORTED_WITHOUT_SUMMARY`（原因无法判定；13 iso summary，1 失败） | `G1 = OPEN`、`G2/G3 = OPEN_PENDING_CLEAN_RERUN`；LT2 生产被阻断 |
| P2 | **B 修复尚未经正式批次验证** | `FIXED_PENDING_FREEZE`（A/B 已过、最小执行已过、冻结已建 `freeze-1810-post-atomic-retry`） | 30/30 未跑出 ⇒ 不得进入长时无人值守 |
| P3 | **7R 轴向声压判据缺位** | 需 COMSOL，本轮 `DO_NOT_RUN` | 所有带宽/平坦度指标**只是替代性粗筛**，不是最终判据 |
| P4 | **频段上界不足** | `Ptot` 153/162、`Vave` 113/162 的 −6 dB **上边频在 35 MHz 之外**；峰位顶边界 83/162、72/162 | 多数组合真实带宽**未知**（不是"很大"）；工单本轮禁止改 `fmax=45 MHz` |

### 3.2 证据与机制级（影响可信度，不直接阻塞）

| # | 问题 | 处置 |
|---|---|---|
| M1 | `read_json_safe` 遇瞬时读失败返回 `{}` ⇒ 最坏「健康 worker 被误判启动失败并重跑一次」 | **只报告不修**（稳健性缺陷、非正确性缺陷），与 R4 同窗口 |
| M2 | `rt_gate` 的 `resource_hard_stop` 判据依赖 `reasons` **文本匹配**（R4） | 延后到下一冻结窗口；失配时 fail-closed（退化为 `unclassified_failure`） |
| M3 | `atomic_write_retries` 计数**只在返回 dict**，未落进 `sampler_state.json` 等 | 延后；触发条件：出现 `sidecar_exited` 而无 traceback |
| M4 | **历史 `81/82` 的原始失败日志已丢失**（因复用 `lt2-acceptance-flake` 目录） | 永久损失；今后任何"未复现"不得声称有原始日志支撑 |
| M5 | 1423 报告曾混入**旧轮次残留产物**（`tree_manifest_run*.json` 实为 13:54–13:55 生成） | 已写 append-only 更正；根因是我复用了输出目录 |
| M6 | 极端压测下仍有 **15/615 ≈ 2.4%** 写失败（4 写 4 读 ≈2500× 生产读频率） | 登记为**已知限制**；非生产工况；fail-closed 未软化 |

### 3.3 过程级（我自己的执行缺陷，如实登记）

- **冻结纪律曾反复失效**：同一天出现 **7 份冻结**（1402/1423/165357/165457/170522/1722/1725/1745/1747/1750/1810），
  其中多次因"声明冻结后又被编辑"而作废；
- **三次在"看起来就差一点"的位置翻车**：`OUT` 作用域错误、`bytes` 未脱敏、条件清单口径不一致；
- **我的两个假设被证据推翻**：`sampler_state.json` 半写（被逐字段 diff 排除）、
  以及「停止线是实时中止」（实为事后审计）。⇒ 已定规：**任何人的假设（含父 agent）都必须被证据检验**；
- **我采信他人结论过早**：曾把实现的"并发向量已从结构上关闭"写进报告，Codex 查代码后指出那只是
  check-then-create。⇒ 已定规：**转述结论前先读代码**。

### 3.4 平台主线欠账（不阻塞 LT2，但属 `WORKING_PLAN` P0–P7）

```text
MCP 加固 P0-2（补丁仍指向旧机路径 D:\桌面\memsharness）、P0-3（无 PMUT 模板）、
        P0-4（worker 关闭）、P0-5（sim_cancel force_kill 默认值与 PID 身份）、P0-6（MCP 侧 run_id 路径校验）
schemas\ 契约（数据集/证据/device_spec）——AGENTS.md §5 指定落点但至今为空
pytest -q 收集失败（tests/test_ml_pipeline.py、tests/test_pod.py，Windows SxS DLL）——既未修也未隔离说明
git 身份未设、无提交
7R 轴向声压 / 网格收敛 L1 / 场快照与 POD / 代理模型训练 / AI 求解器 —— 均未开始
```

---

## 4. 下一步工作（按顺序，带前置与放行判据）

### 阶段 A：关闭验收门（当前唯一阻塞链）

```text
A1. 从 freeze-20260914-1810-post-atomic-retry\snapshot 跑正式批次
    前置：layout.tools 指向该 snapshot 且 executed_from_snapshot = true（否则停手定位）
    内容：两次正式验收 + 30 次隔离 + 前后四项校验
    放行判据（全部满足才算过）：
      · 两轮结构化 total=82 pass=82 fail=0、exception=null
      · deterministic manifest 非空、different_files/only_left/only_right 均为空
      · 30/30 隔离全过；每轮日志 path/bytes/SHA256 齐备
      · --verify：snapshot_added_untracked 为空、drift_count=0
      · acceptance_summary.json 自身 bytes+SHA256 给出
      · evidence_files_complete=true 且八个具名证据文件齐全
      · comsol_started=false、mph_imported=false
    失败处理：保留现场并停止，不清理不覆盖
A2. 全过后：关闭 G1，再用同一冻结证据重验 G2/G3
A3. 用新 run-id 跑正常资源确认 r3（不故意触发硬线）
    放行判据：rows=7、唯一频率 7、drive mismatch 0、LT2-C PASS、无 >15 s 空档、
             三类硬停采样 0、commit 最低 >6144 MB、PID/端口证据链完整、
             checkpoint 有效、端口 30 s 内关闭
    工具：work\tools\check_r3_conditions.py（21 项 fail-closed，已用 r2 实测验证）
```

### 阶段 B：真实硬停演练（用户已给知情同意，Codex 本轮 `DO_NOT_RUN`，排在 A3 之后）

```text
B1. --drill --ws-hard-stop-mb 5000，单组合单频点，安全早触发（禁止压真实内存）
    预期退出码 6（BLOCKED_OR_LIMITED 为预期结果，不是失败）
B2. 目标：U1（verified_emergency_termination 全路径）、U2（终止真实 comsolmphserver）、
        U3（study 阻塞期间被终止的行为）
```

### 阶段 C：LT2 生产（504 点）

```text
C1. logical_batch_size = 4、server_lifecycle_size = 1（每组合一个全新 server）
C2. 首个逻辑批通过后再议「两组合共用一 server」试验
C3. 估算：约 15–17 h（同模型同环境的线性估算）；一组合一 server 会更长；
        首批 4 组合完成后据实测 P50/P75 更新
C4. 前置：A 阶段全过 + B 阶段（或用户明确豁免）
```

### 阶段 D：LT3 收口（可与 C 并行准备，但**不得**在 LT2 通过前出正式反相排名）

```text
D1. 扩展频段上界（改 fmax 到 45 MHz）——**需用户与 Codex 双重授权**，会变动网格口径
    （动机：见 P4，多数组合谐振未被 35 MHz 包住 ⇒ 带宽类指标不可用）
D2. 实现 7R 轴向声压 H_p(f)=|p(f,0,0,7R)|/|V|（需 COMSOL + 坐标原点平移 + 场级导出）
    —— 这是最终主判据
D3. 网格收敛（L1）对带宽/峰值的影响
D4. 反相侧频响指标（待 LT2 504 点到位；LT1 仅 3 频点不足以算 −6 dB 带宽）
D5. LT3-D 补充：legacy `|Vdiff| ≈ 1 V` 的「约」所对应的偏差量级**仍未量化**
    （电气量已因 KCL 16.6–18.9% > 1% 整体排除，无法反推 ⇒ 只能标为未量化限制）
```

### 阶段 E：平台主线（可在 A–C 等待期间并行，均不碰冻结件）

```text
E1. MCP 加固 P0-2～P0-6
E2. schemas\ 契约（数据集/证据/device_spec）
E3. pytest 收集失败的修或显式隔离说明
E4. 记录索引维护（docs\INDEX-records-and-rulings.md）
```

---

## 5. 风险与止损线

```text
1. B 未在正式批次验证前 ⇒ 禁止任何长时无人值守运行
2. 7R 判据缺位 ⇒ 一切带宽/平坦度结论**只能作粗筛**，不得作工程指标对外引用
3. FBW 插值口径差与 FBW 本身同阶（Ptot 中位 27.6 个百分点）⇒ 报任何单值必须同时给差值
4. 两批 model_sha256 不同（0f75ca1d… vs cbe9ccc1…）⇒ 只能并排对照，禁止合并统计
5. Zin*/I_* 因 KCL 16.6–18.9% > 1% 整体排除 ⇒ 不得参与排名/训练/报告
6. 单 PMUT 单元模型 ⇒ 不得外推阵列；`Vave` 只是响应量 ⇒ 不得称往返/阵列带宽
7. 冻结纪律：任何编辑后必须新建 freeze_id 并从 T1 整轮重跑；不得覆盖 freeze manifest
8. 不得复用/清理任何既有 run 目录（历史失败现场永久保留）
```

---

## 6. 需要决策的事项

| # | 事项 | 需谁定 | 我的建议 |
|---|---|---|---|
| D-1 | 是否扩展频段上界（`fmax` 35 → 45 MHz） | 用户 + Codex | 倾向**是**：P4 表明多数组合谐振未被包住，带宽类指标当前不可用；但会变动网格口径，须重新预检选择集 |
| D-2 | 真机硬停演练的执行时点 | Codex（用户已同意） | 排在 A3 之后，不提前 |
| D-3 | M2（R4 结构化 reason）/ M1（`read_json_safe`）/ M3（计数落产物）是否同批处理 | Codex | 建议**同窗口但分批**：一次只改一个关注点，避免重演"顺手多改"导致的翻车 |
| D-4 | 是否启动平台主线 E1–E4 | 用户 | 可与 A–C 并行，不冲突 |

---

## 7. 一页速览

```text
已解决：页面文件/commit 贴地（27 倍改善）、U5/U7 真机证实、B 根因确诊并修复（A/B 7/80→0/80）
已交付：LT3 前置管线 + 归一化对照 + 频响指标；四对 Pareto 全部不再退化
唯一阻塞：正式验收批次未通过（G1 OPEN）——B 的修复已冻结待验（freeze-1810-post-atomic-retry）
最大未知：7R 轴向声压（最终判据，需 COMSOL）与频段上界不足（多数谐振未被包住）
最大教训：冻结必须是机制而非观察；任何人的假设都必须被证据检验；
         改动被测件须用上一份冻结快照作 diff 基线并验证改动范围
```
