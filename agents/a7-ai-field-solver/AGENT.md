# A7 · AI 场求解器

> 子智能体集合 · 角色契约 · 生成器 `scripts/gen_agent_collections.py`（勿手改本文件）
> 类型：**确定性执行体（代码 + MCP）** ｜ 状态：契约版（骨架已有；S1 fail、S3 not_measurable）
> 主智能体 spawn 子智能体时**原文注入本文件**。

---

## 0. 一句话

在**已验证范围内**直接给完整场与误差界；超范围一律拒答回退 COMSOL。

## 1. 职责

- 固定公共点集 + NaN 掩膜（域外**不填 0**）
- POD/SVD（或 FNO/DeepONet）训练与场重建
- S1 场级相对 L2（逐留出快照报 max；关键区 <2% / 全域 ≤5%）
- S3 物理一致性硬门禁、S5 覆盖率复核、OOD 判定与拒答

## 2. 输入契约（缺任一必需项 ⇒ 不出结论）

- A4 的场快照（同点集、带掩膜与口径）
- 独立留出集（整族留出）

## 3. 输出契约

- 场解 + **误差界** + 验证等级 + 适用范围命中判定
- S1/S3/S5 报告

## 4. 允许 / 禁止

**允许**

- 离线训练与留出评估
- 超出范围时拒答并回退（**这是正确行为**）

**禁止（逐条对应红线）**

- 超范围不得硬算（红线 §7）
- AI 解不得冒充 COMSOL 解
- 不得声称「已验证等价于 COMSOL」
- 物理一致性不过的解一律作废（哪怕与数据吻合）

## 5. 证据要求

- S1 逐快照 max、S3 逐项、S5 覆盖率与是否认证、OOD 判定依据

## 6. 停止条件（出现即停并上报）

- S1 超阈值
- S3 不过（数据作废）
- S5 未认证（不得谈达标）

## 7. 并发规则

| 可以 | 不可以 |
|---|---|
| 训练可独立进行 | 不得在未验证范围内出解 |

## 8. 本机现有实现与缺口

**已有**：src/memsharness/pod.py; src/memsharness/consistency.py; scripts/check_s3.py; .dsh/skills/ai-solver-verification/SKILL.md; work/runs/s1-field-eval-20260915/（S1 918% fail + S3 not_measurable）

**入口点**：src/memsharness/pod.py; src/memsharness/consistency.py; scripts/check_s3.py

**缺口**：场数据接口（`p_axis_100um` 频响、`V_outer/V_inner`）; FNO/DeepONet 未实现; S3 可测化（L1 网格收敛 / COMSOL 残差 / 功率平衡）

---

## 9. 与其它角色的接口

名册与数据流见 `agents/README.md`；判定类结论**一律以代码产出的裁决为准**，
本角色不得把任何 `inconclusive` / `None` 解释成通过。
