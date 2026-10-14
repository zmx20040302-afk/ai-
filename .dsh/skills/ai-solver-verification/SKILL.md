---
name: ai-solver-verification
description: AI 求解器（免 COMSOL 出解）的验证与放行 SOP：S0–S5 指标、降阶路线、保形校准与样本量下限、S3 硬门禁、放行条件与 OOD 拒答。
whenToUse: 训练/评估任何"不调用 COMSOL 直接出场解"的模型，或判断某个 AI 解能否被采信时使用。
---

# AI 求解器验证 SOP

## 0. 底线

- **AI 解是独立来源**：入库必须 `source_type='ai_solver'`，带 `model_id`（具体模型版本）与 `uncertainty`（误差界）。缺任一 → 拒绝入库。
- **不得声称"已验证等价于 COMSOL"**；不得与 `simulation` 混列统计。
- 超出已声明适用范围 → **拒答 + 回退 COMSOL**，并如实写明回退原因。

## 1. 首选路线：降阶（POD/ROM），不是先上深度算子

固定拓扑 + 参数少（1–2 个）时，场解落在低维流形上：

```
采样 30–60 点 → 场快照对齐到固定公共点集 → 减均值 → POD 基（能量占比 ≥99.9%）
→ 基系数对参数回归 → 场 = 均值 + Σaᵢ(θ)φᵢ(x) → 留出场算相对 L2 → 误差界 → S3 自校验 → 放行
```

理由：CPU 分钟级可训、样本需求比算子学习低一个量级、基函数可解释。
**系数回归默认用线性（岭回归）**：快照少时 MLP 只能逼近线性映射（实测训练点重构误差 ~1e-4）；系数确实非线性时才换 `coeff_model="mlp"`。

## 2. 指标（S0–S5，与代理层的 L 级**分开**）

| 级 | 内容 | 默认阈值 |
|---|---|---|
| S0 | 极限一致性（静态/低频极限 vs 闭式解） | < 1% |
| S1 | **场级相对 L2**（独立 COMSOL 留出集逐点） | 关键区 < 2%，全域 ≤ 5% |
| S2 | 工程量误差（由场解导出） | < 3% |
| S3 | **物理一致性**（守恒/边界/对称/极限+单调） | 守恒残差 < 0.5–1%；BC 残差 ≤ 1e-6 |
| S4 | 离散/网格无关性 | < 2% |
| S5 | **误差界校准**（90% 区间覆盖率） | 85–95% |

## 3. S3 是硬门禁

`memsharness.consistency.evaluate_s3`：**任一检查 False → 整体不通过**；**无法判定（None）≠ 通过**，整体标为 `inconclusive`，`release_allowed=False`。
只有 `verdict == "passed"` 才允许放行。**与数据吻合不能替代物理成立。**

S3 检查在真实解上的参考量级（`scripts/check_s3.py` 实测）：守恒残差 5.6e-12、边界残差 5.7e-15、镜像对称 7.6e-3（离散残余）。
**注意**：检查器自身写错时它会把错误报成"不通过"——这是期望行为，先核对检查代码再改阈值。

## 4. 误差界必须用保形预测，不能拿残差标准差凑

- 非一致性得分：`max |真值−预测| / σ`（逐快照一个标量）；用 **LOO 重拟合**取分，避免用训练偏差自证校准。
- 保形分位数：第 `⌈(n+1)(1−α)⌉` 小的得分；**n 个校准点最多保证 n/(n+1)**。
- 因此 **90% 区间至少需要 9 个校准点**；样本不足时函数返回 `inf` 并标注 `certified: false`——
  这是正确结论，**不得**用残差标准差硬凑窄区间（实测后果：标称 90% 实际覆盖率 **0.030**）。
- 加校准后同一数据覆盖率恢复到 **0.998**（目标 85.7%，6 个校准点的上限）。
- 未认证时 `s5_passed = null`（不是 True）。

## 5. 放行门禁（6.4）

```
draft → (S0/S3 通过) → physics_consistent
      → (S1/S2 达标 + S5 已认证 + 独立留出集) → solver_certified
      → (人工评审 + 适用范围签字) → approved_solver
      → (漂移/越界复检失败) → suspended
```

运行时每次出解必须附：**场级误差界 + 验证等级 + 适用范围命中判定**；按 `schedule` 定期抽样用 COMSOL 复检。

## 6. 数据前提

训练集必须过 `memsharness.dataset.build_dataset` 的泄漏检查：缺 `geometry_family` 的样本被排除；按族整族切分；
族数 < 2 时报告 `cross_family_holdout=false` 并警告"指标只反映族内插值"——**不得当作跨族泛化证据**。
需要声称跨族泛化时用 `require_cross_family=True`，不满足即拒绝构建。

## 7. R13：门禁必须区分「不达标」与「判不了」

**现象（错误归因）**：判据在**评估网格上不可达**。5 个留出点上覆盖率只能取
`{0, 0.2, …, 1.0}`，而判据区间是 `[0.85, 0.95]` ⇒ 真值 `coverage=1.0` 被旧实现记成 `failed` ——
等于把「点太少」报成「误差界不达标」。

**要求**：

```text
· 判据在评估规模上不可达 ⇒ 记 inconclusive，`s5_passed = None`（**不是 True**）
· 必须输出「评估点分辨率不足」的理由（含 n_holdout 与 k/n 步长），使其与「不达标」一眼可分
· 不得因为「界偏保守、方向安全」就改记 passed —— 那正是把 None 复述成通过（红线）
```

**已落成（不要重复实现）**：`src/memsharness/solver.py` 的 `evaluate_levels` S5 段
（`n_holdout` 存在且无任何 `k/n` 落在 `[lo, hi]` 内 ⇒ 覆盖率判据置 `None`，
并在 `notes` 写明原因）。用例：
`tests/test_solver.py::test_unreachable_coverage_grid_is_inconclusive_not_failed` 与
`::test_coverage_grid_reachable_keeps_the_gate_strict`（后者锁住**没有放宽**：
n=20 时 0.90 仍通过、1.0 仍 failed）。

**推广**：这条不只管 S5 覆盖率。**任何**判据只要其取值集合在评估规模上是离散且有限的
（覆盖率 k/n、通过折数 m/n、分位数在 n 点上的可取值），都要先算「目标区间是否可达」，
不可达即 inconclusive。

## 8. R14：复核脚本必须自证分辨率

**现象（方法自身误差大于被测的量）**：用最近节点采样复算网格差异得 **13–17%**，
而 λ(20 MHz, 水) ≈ 75 µm、最粗网格节点间距 3 µm ⇒ **分段常数采样自身误差 ~10%**，
**大于被测的量** ⇒ 那个 13–17% 没有任何判读力（它测的主要是采样方法自己的误差）。

**要求**：

```text
· 任何「复算 / 独立复核」都必须报出**自身方法的误差量级**（离散阶数 + 特征尺度 + 采样间距）
· 判据量小于或接近方法误差时**不得出结论**：换方法（本例必须用 O(h²) 插值）或记 inconclusive
· 复核结论必须给「两套实现同向 / 同量级」的对照，而不是只报一个新数字
```

**已落成范式**：`scripts/verify_s34_s4_interp.py`（独立线性插值实现，自证分辨率）。
实测对照：报告最差有序对 **2.31%**，独立复算 **2.27%**，**同向且都超 2% 线** ⇒ `failed` 成立
（两套实现差 ≤ 0.05 pp）—— 这正是「复核支持结论」应有的形态。

**与 §7 的关系**：R13 是「判据在网格上不可达」，R14 是「复核方法本身不够准」。
两者通向同一条纪律：**判不了就说判不了，不要给出一个说不清来源的数。**

## 9. 预注册补充协议的用法（**不取代**冻结口径）

**场景**：判据在冻结评估集上**不可达**（如 §7 的 5 点覆盖率），但换一个**更大且事先声明**的
评估协议就能判定 —— 这时**用补充协议，不是改冻结口径**。

**硬要求**：

```text
· 协议原文必须写在**看到任何覆盖数字之前**（母版：scripts/s5_8fold_coverage_n1_4.py 的模块文档串）
· 划分规则必须**确定**（本例：81 个 x 点按 x 升序、fold = i % 8，无随机种子）
· 阈值**沿用冻结值**（本例 [0.85, 0.95]，不放宽）
· 校准与测试必须严格不相交（折内半宽取训练折内部 LOO 的分位）
· 产物必须显式标注 `supplemental: true` 与 `supersedes: null`
· 报告里冻结口径的结论**原样保留**（append-only）：本例冻结 5 点协议仍是 inconclusive，
  只有补充 8 折协议报 0.9259 / 0.9383 passed
· 口径是否正式改为补充协议 **需人拍板**（不得自行替换预注册口径）
```

**实测记录（记录 ≠ 放行依据）**：α=0.10 时 N1=4 覆盖率 **0.9259（75/81）**、
N1=7 **0.9383（76/81）**，两族都落在 `[0.85, 0.95]` 内；α=0.05/0.01 两行的 `failed`
是**口径错配**的同义反复（`[0.85,0.95]` 本就是 90% 间隔的判据），**不得**据此说误差界失效。

**放行仍不放行**：S5 转通过**不改变**放行结论 —— §5 状态机要求 S0/S3 通过才到
`physics_consistent`，而本轮 S0 `inconclusive`、S3 `failed` ⇒ **连第一次状态跃迁都还够不着**。
模型状态与 `source_type='ai_solver'` 的使用权保持不放行，**放行权在人**。

## 10. 「判不了」不得写成通过：整列为空 ⇒ inconclusive（R15）

**场景（2026-10-08 实测）**：批次隔离门禁 `check_batch_isolation` 的 `batch_censored_not_eligible`
检查「命中删失/截断标记的行不得同时被标为可排名」。并集表里 `C_5-50MHz`（1782 行）与
`A_5-35MHz`（223 行）的原始标志列（`peak_at_scan_endpoint` / `bw_upper_cutoff_at_endpoint`）
**整列为空**（原表没有这两列），只有 `V2_5-35MHz`（250 行）有值。收紧前的实现因为「表里存在该列」
就整体求值，而空列里扫不出违规 ⇒ 判 **PASS** —— 那是**假通过**。

**要求**：

```text
· 「某批的判据列整列为空」⇒ 该批**无法复验** ⇒ 整个检查项 inconclusive（passed=None），**不是 True**
· **逐批**判断：不是「整表有没有这一列」，而是「这一批有没有可复核的值」
· 空列里「没有违规」只是「没看到」，不是「没有」——**空列 ≠ 通过**
· 不得因此改判 failed：failed 是「产物不达标」，「整列为空」是「判不了」，两者不得混同（§7）
· 已有违规是硬事实 ⇒ 判定次序固定为「先违规（failed）→ 再整列为空（None）→ 否则通过」，
  保证相对收紧前**只可能把 True 变成 None**，不会把 False 降级成 None（那是放宽）
· reason 必须**指名**哪些批整列为空；detail 必须给逐批 n_flag_nonempty 与 n_rows
```

**已落成（不要重复实现）**：`src/memsharness/sweep_analysis.py` 的 `check_batch_isolation` 第 4 项
（L526–L584；2026-10-08 收紧，函数 sha256 `5a2146cc…` → `1f634902…`；判定语义未另造一套）。
用例在 `tests/test_batch_isolation.py`：
①`test_raw_flags_blank_for_a_whole_batch_is_inconclusive_not_passed`（整列为空 ⇒ None）、
②`test_all_batches_with_raw_flag_values_and_no_violation_still_pass`（全有值 ⇒ 仍 PASS，
证明没有变成「一律 inconclusive」）、③`test_raw_flag_values_with_violation_still_fail`（有违规 ⇒ 仍 failed）、
④`test_censor_columns_absent_entirely_is_inconclusive_and_names_the_reason`（缺列 ⇒ None）、
⑤`test_blank_batch_plus_violation_elsewhere_is_still_failed_not_downgraded`（不把 False 降级成 None）。

**实测后果（记录 ≠ 放行依据）**：v3 并集表与补列视图上该项由 **PASS → inconclusive**；
`worst_verdict` 仍 `inconclusive`、`release_allowed` 仍 `false`、退出码仍 **4**。
**没有**任何检查项由 failed 变 passed ⇒ 这不是「门禁放宽后通过」，而是**取消了一个假通过**。

**推广（与 §7 同一条纪律）**：任何「按批/按组核对标记列」的门禁都要先核**该组有没有值**。
「列在表里」≠「该组可复验」。缺列、整列空、列里只有空串，都必须通向 inconclusive，而不是通过。
