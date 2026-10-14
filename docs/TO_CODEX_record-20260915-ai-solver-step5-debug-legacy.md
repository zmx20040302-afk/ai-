# TO_CODEX 记录：AI 求解器 第 5 步 —— 用**旧参数**（legacy 单电极）调试求解器（负值修复 + 预注册选模型 + 交互调试入口）

- 日期：2026-09-15
- 任务单：`docs\TASK-20260915-ai-solver-step5-debug.md`（2026-09-15 12:35 下达）
- 执行者：实现者子代理
- 前置：第 4 步已交付并独立复核（`work\ai-solver\step4\`；报告
  `docs\TO_CODEX_record-20260915-ai-solver-step4-single-electrode.md`；勘误
  `docs\TO_CODEX_errata-20260915-step4-smoke-artifact-overwritten.md`）
- 数据：**旧参数**（legacy 单电极）冻结副本，sha256
  `33ed711c8d53bf02f69686e8e1c62815587919588d73293a5ce899c903951403`（1134 行 = 162 组合 × 7 频点）。
  **未换数据、未等新数据。**
- 性质：**域内标量代理 + 标量保形误差界 + 拒答边界 + 正值化修复**；**不是**免 COMSOL 求解器（缺 S1）
- 未运行 COMSOL / `comsolbatch` / `mphserver` / `comsolcompile`；未跑 pytest；
  **未在 `work\ai-solver\step4\` 目录内执行任何东西**（只读复制到 scratch 后从副本 import）；
  未修改 `work\tools\` / `src\memsharness\` / 任何既有 `work\runs\` 目录 / 用户目录 / `work\models\` / 元数据库

---

## 0. 一句话结论

**负值问题用有原理的方式修掉了**（`log10` 正值化）：以 `M2` 家族为例，域内非正比例
V1 由 **3.89%**、V2 由 **16.20%** 降到 **0**；V2 的 `Ptot` 网格上**四个原值候选合计 716 次**
非正判定（M1 168 + M2 347 + M3 201，与第 4 步 §8 完全一致）也全部归零，且是**结构性**的（`10^x>0`）。**预注册规则 R1 选出的主模型是 `M2_log10_gp`**
（两个变体都选中它）；**域内相对误差在 12/16 个格子上改善**（0.16×–0.90×），**区间半宽大幅收窄**（0.04×–0.89×）。
但代价必须一起说：**收窄后的区间在诚实分块/跨族下覆盖率跌破名义值**（V1 分块 0.54–0.71，跨族 0.004–0.056），
所以「域内可用」成立的范围是**趋势与相对比较**，**不是**工程绝对值，也**不是**"误差界在漂移下可信"。
**S1 仍不可测（无场快照）⇒ `release_allowed=false`、`model_state=draft`**——本次没有为了"调试成功"抬 S 级或放行状态。

---

## 1. 定位声明（写进代码常量 `POSITIONING`，每个产物都带）

```text
model_id                = mdl-step5-20260915-legacy-debug
model_state             = draft            ← 红线 5：晋升权在人，本轮不晋升
solver_certified        = False            ← 缺 S1（无场快照 ⇒ 场级相对 L2 不可测）
has_error_bounds        = True             ← **标量** Ptot/Vave 的 90% 保形区间
field_level_error_bound = None             ← 本数据没有任何场级量
allowed_use             = "域内筛选 / 趋势与相对比较"
forbidden_use           = "工程绝对值判断"
s_grade                 = S0 不可测 / S1 不可测 / S2 已测未达标 / S3 inconclusive（四项无法判定，硬门禁 release_allowed=false）
                          / S4 不可测 / S5 已认证但覆盖率可迁移性未通过
must_not_be_stored_as   = source_type='ai_solver' 样本（缺 S1 与 model_id 级放行）
```

---

## 2. 命令、环境与产物

```powershell
# 环境：Windows PowerShell 5.1；Python = work\.venv\Scripts\python.exe（3.12.14）
#        numpy 2.x + scipy + pandas + scikit-learn + duckdb；一律 -B + PYTHONDONTWRITEBYTECODE=1 + PYTHONPYCACHEPREFIX
# ① 预注册（**先落盘**）
#    预注册文件：work\ai-solver\step5\selection_rule_preregistered.md
#    6559 B / sha256 cfde5d27a2990d25e22a8f37c52a745711cfd7ddcad2dfeaab43824119866290 / mtime 2026-09-15 12:39:47
python -B work\ai-solver\step5\ai_step5_debug_legacy.py prereg-check
# ② 与第 4 步的口径等价性交叉核对（切分/折/超参网格/超参/校准）
python -B work\ai-solver\step5\ai_step5_debug_legacy.py equivalence
# ③ 只用训练数据的内层 CV 选主模型（**不读任何留出点**）→ raw\primary_models.json
python -B work\ai-solver\step5\ai_step5_debug_legacy.py select
# ④ 全量重计算（8 场景 × 8 候选 × 7 频点 × 2 目标；同折同口径）→ raw\*
python -B work\ai-solver\step5\ai_step5_debug_legacy.py compute
# ⑤ 域内正定性扫描 + 代码路径不变性核查
python -B work\ai-solver\step5\ai_step5_debug_legacy.py guards
python -B work\ai-solver\step5\ai_step5_debug_legacy.py recheck
# ⑥ 汇总 + 冒烟自测（assemble 内部会调用 smoke_step5）
python -B work\ai-solver\step5\ai_step5_debug_legacy.py assemble
# ⑦ 调试入口的真实调用（单点 + 批量），原文写入 cli_calls.txt
python -B work\ai-solver\step5\solve_cli.py --x-scale 0.6 --N-w-te1 6 --freq-MHz 20 --target Ptot
python -B work\ai-solver\step5\solve_cli.py --input cli_demo_queries.csv --output cli_demo_answers.csv
```

**第 4 步的复用方式（事故规避）**：第 4 步目录已被哈希锁定且**只读**。本轮的**唯一**复用办法是先把整个目录
**逐字节复制**到 `work\runs\_scratch-step5\`（39/39 文件 sha256 相同，证据
`raw\scratch_step4_copy_manifest.json`），再从该副本 `import step4_solver`；
`work\ai-solver\step4\` 在整个会话内**零写入、零执行**。这样第 4 步的数据读取、切分构造、内层折、
超参网格、保形分位数、适用域判定与拒答文案全部是**同一份代码**（见 §5 的等价性核查）。

### 2.1 实际调用的既有函数（同一实现，非重新实现）

| 模块 | 关键符号 | 用途 |
|---|---|---|
| `src\memsharness\pod.py` | `conformal_quantile` | 保形分位数（第 ⌈(n+1)(1−α)⌉ 小得分；n<9 返回 `inf`） |
| `src\memsharness\consistency.py` | `CheckResult`、`evaluate_s3` | S3 硬门禁（任一 False ⇒ 不通过；None ≠ 通过） |
| `work\tools\lt3_prep.py` | `read_grid` / `locate_header` / `map_columns` / `parse_complex` / `normalize_freq_column` / `sha256_file` | 读表 / 复数解析 / 频率归一 / 哈希 |
| 第 4 步（scratch 副本） | `read_batch2` / `read_precheck` / `build_scenarios` / `inner_folds` / `select_hparams` / `robust_scale` / `conformal_calibrate` / `halfwidth` / `make_estimator` / `HP_GRIDS` / `FrozenSolver.check_domain` / `FAMILY_FROM_DESIGN_STATUS` | 数据 / 切分 / 内层折 / 超参网格 / 保形校准 / **适用域与拒答** |

**不适用 / 未调用**（与第 4 步同因）：`ml.surrogate.load_samples`、`dataset.build_dataset`（需元数据库且会写库，
批次2 在库内 0 条样本）、`save_model` / `write_model_card` / `register_model`（会写 `work\models\` 与 DuckDB）、
`pod.fit` / `PodModel`（本数据无场快照）。`ml.surrogate.score` 只在第 4 步用过，本轮未用。

---

## 3. §1 负值修复：有原理的做法 + 同口径证明

### 3.1 做法（写进预注册与代码）

- `Ptot`（输入电功率）与 `Vave`（速度**幅值**，原表复数取模）在物理上**恒正**；
- 因此对每个候选增加一个**正值化变体**：在 `log10(y)` 上拟合，预测 `10^ŷ_log`。
  这是**保序双射变换**，反变换**结构性地**不可能给出非正值；
- **不使用** `max(pred, ε)` 之类事后截断（任务单 §1.1 明令禁止），也**不改**任何阈值、切分或超参网格；
- 实测前提：1134 个 `Ptot` 与 1134 个 `Vave` **全部严格为正**（`raw\inputs.json.data_positivity`，
  `min(Ptot)=6.64597e-08 W`、`min(Vave)` 见文件），故变换在训练标签上处处有定义。

候选集合（**闭集** 8 个，跑完未增删）：原值 `M0_global_mean / M1_ridge / M2_gp / M3_gbr`
＋ 正值化 `M0_log10_geomean / M1_log10_ridge / M2_log10_gp / M3_log10_gbr`。

### 3.2 三件事的**前 → 后**（同一套切分、同一批折）

#### ① 域内非正比例（**V1 = 952 点、V2 = 2142 点的声明域网格，步长 0.025**）

来源：`positivity_fix_comparison.csv`、`raw\domain_guard_scan.csv`（32 行 = 2 变体 × 2 目标 × 8 候选）。

| 变体（域内网格） | 目标 | 候选家族 | 非正比例 前 | 非正比例 后 | 值空间区间下界 ≤0 前 | 后 |
|---|---|---|---|---|---|---|
| V1（952 点） | Ptot | M2_gp → M2_log10_gp | **3.89%**（37/952） | **0.00%** | 0.5714 | **0.0000** |
| V1（952 点） | Ptot | M3_gbr → M3_log10_gbr | **7.04%**（67/952） | **0.00%** | 0.8613 | **0.0000** |
| V1（952 点） | Vave | M2_gp → M2_log10_gp | 0.00% | 0.00% | 0.0000 | 0.0000 |
| V1（952 点） | Vave | M3_gbr → M3_log10_gbr | 0.11%（1/952） | **0.00%** | 0.0011 | **0.0000** |
| V2（2142 点） | Ptot | M2_gp → M2_log10_gp | **16.20%**（347/2142） | **0.00%** | 1.0000 | 0.1429 |
| V2（2142 点） | Ptot | M3_gbr → M3_log10_gbr | **9.38%**（201/2142） | **0.00%** | 0.5808 | **0.0000** |
| V2（2142 点） | Vave | M2_gp → M2_log10_gp | 1.17%（25/2142） | **0.00%** | 0.2857 | 0.0000 |
| V2（2142 点） | Vave | M3_gbr → M3_log10_gbr | 0.23%（5/2142） | **0.00%** | 0.0023 | **0.0000** |

- 原值候选的 8 个数字与第 4 步 `domain_guard_scan.csv` **逐格一致**（V2 M2 16.20%、M3 9.38%、
  V1 M2 3.89%、M3 7.04%）⇒ 这次对比确实是在**同一口径**下做的。
- **必须同时说清的一处限制**：正值化只保证**点预测**恒正。**值空间**的乘性区间的下界仍可能 ≤0
  （主模型 `M2_log10_gp` 在 V2 的 Ptot 网格上有 **14.29%** 的点如此）；因此 CLI 同时给出**严格为正**的
  `log10` 空间区间（`10^(ŷ_log ∓ q·σ_log)`）。**不要把值空间区间当作物理界**。

#### ② 留出误差（`median_of_fold_median_rel_err`，口径与第 4 步一致：折内跨频点取中位 → 跨折取中位）

主模型家族 `M2`（`fix_holdout_metrics.csv`，16 个格子）：

| 场景 | 目标 | 误差 前 → 后 | 比值 |
|---|---|---|---|
| V1 整列留出 x | Ptot | 0.1566 → **0.0571** | 0.36× |
| V1 整列留出 x | Vave | 0.0703 → **0.0284** | 0.40× |
| V1 整行留出 N1 | Ptot | 0.0565 → 0.0580 | 1.03× |
| V1 整行留出 N1 | Vave | 0.0217 → 0.0276 | **1.27×** |
| V1 分组5折·按 x | Ptot | 0.1701 → **0.0853** | 0.50× |
| V1 分组5折·按 x | Vave | 0.0752 → **0.0496** | 0.66× |
| V1 分组5折·按 N1 | Ptot | 0.1334 → 0.1431 | 1.07× |
| V1 分组5折·按 N1 | Vave | 0.0233 → 0.0642 | **2.76×** |
| V1 随机（泄漏对照） | Ptot | 0.0918 → **0.0491** | 0.53× |
| V1 随机（泄漏对照） | Vave | 0.0383 → **0.0293** | 0.77× |
| **V1 跨族（合法 OOD）** | Ptot | 16.7967 → **4.9465** | 0.29× |
| **V1 跨族（合法 OOD）** | Vave | 1.5102 → **0.9940** | 0.66× |
| V2 随机（泄漏对照） | Ptot | 0.7508 → **0.2687** | 0.36× |
| V2 随机（泄漏对照） | Vave | 0.1061 → **0.0956** | 0.90× |
| **V2 整族留出（合法 OOD）** | Ptot | 6.1209 → **1.0000** | 0.16× |
| **V2 整族留出（合法 OOD）** | Vave | 0.7706 → **0.6416** | 0.83× |

**12/16 改善，4/16 变差（V1 按 N1 方向的两格，1.03×–2.76×）——如实保留，不做平均掩盖。**
`M3` 家族（第 4 步的原主模型）见 §3.3。

#### ③ 90% 保形覆盖率与区间半宽（**必须成对读**）

主模型家族 `M2`：

| 场景 | 目标 | 覆盖率 前 → 后 | 相对半宽 前 → 后 | 半宽比 |
|---|---|---|---|---|
| V1 整列留出 x | Ptot | 0.855 → **0.669** | 0.673 → **0.081** | 0.12× |
| V1 整列留出 x | Vave | 0.679 → 0.710 | 0.130 → **0.085** | 0.65× |
| V1 整行留出 N1 | Ptot | 0.903 → **0.637** | 1.098 → **0.119** | 0.11× |
| V1 整行留出 N1 | Vave | 0.808 → **0.700** | 0.174 → **0.066** | 0.38× |
| V1 分组5折·按 x | Ptot | 0.933 → **0.681** | 1.867 → **0.125** | 0.07× |
| V1 分组5折·按 x | Vave | 0.669 → 0.667 | 0.147 → **0.077** | 0.52× |
| V1 分组5折·按 N1 | Ptot | 0.893 → **0.544** | 1.202 → **0.122** | 0.10× |
| V1 分组5折·按 N1 | Vave | 0.800 → **0.675** | 0.179 → **0.085** | 0.47× |
| V1 随机（泄漏对照） | Ptot | 0.964 → 0.938 | 2.019 → **0.270** | 0.13× |
| V1 随机（泄漏对照） | Vave | 0.940 → 0.937 | 0.212 → **0.144** | 0.68× |
| **V1 跨族（合法 OOD）** | Ptot | 0.568 → **0.004** | 1.541 → **0.057** | 0.04× |
| **V1 跨族（合法 OOD）** | Vave | 0.069 → 0.056 | 0.171 → **0.048** | 0.28× |
| V2 随机（泄漏对照） | Ptot | 0.968 → 0.911 | 10.483 → **0.895** | 0.09× |
| V2 随机（泄漏对照） | Vave | 0.903 → 0.907 | 0.545 → **0.348** | 0.64× |
| **V2 整族留出（合法 OOD）** | Ptot | 0.436 → **0.033** | 0.855 → **0.281** | 0.33× |
| **V2 整族留出（合法 OOD）** | Vave | 0.098 → 0.053 | 0.127 → **0.112** | 0.89× |

**这是本轮最重要的一条"坏消息"，必须写清**：修复让**点估计**更准、区间更窄，但**没有让覆盖率更可信**；
在诚实分块/跨族口径上覆盖率从 0.44–0.93 掉到 **0.03–0.71**（跨族 Ptot 只剩 **0.4%**）。
原因是"更窄的区间 + 残留系统偏差"：区间窄了，偏差没消 ⇒ 盖不住。
`log10` 空间区间与值空间区间覆盖率几乎相同（例如 V1 整列留出 Ptot 跨频点 0.569 与 0.639，
见 `coverage_by_frequency.csv`），所以**换区间口径并不能救覆盖率**。
按任务单 §1.4 的口径如实登记：**修复改善了误差（12/16）与区间宽度（0.04×–0.89×），
但把覆盖率推离名义值 ⇒ 完整结论是"负值修好了、精度改善了、误差界的可迁移性反而更差"，不是"整体变好"。**

### 3.3 第 4 步原主模型家族 `M3` 的同一张表（供对照，`fix_holdout_metrics.csv`）

| 场景 | 目标 | 误差 前 → 后 | 覆盖率 前 → 后 | 半宽 前 → 后 |
|---|---|---|---|---|
| V1 整列留出 x | Ptot | 0.3536 → 0.2780 | 0.933 → **0.496** | 2.539 → 0.371 |
| V1 整列留出 x | Vave | 0.2286 → 0.2240 | 0.738 → **0.464** | 0.428 → 0.212 |
| V1 跨族 OOD | Ptot | 13.8580 → 13.7898 | 0.857 → **0.048** | 1.801 → 0.375 |
| V2 整族留出 OOD | Ptot | 0.9215 → 0.9213 | 0.570 → 0.444 | 1.272 → 0.311 |
| V2 随机（泄漏） | Ptot | 0.2437 → **0.0888** | 0.942 → 0.908 | 1.921 → 0.327 |

即：**`M3` 家族的 log10 变体几乎不改善误差（1.00×–1.37×），却把覆盖率砍半**——
这正是"预注册规则必须在跑留出指标之前定死"的现实理由：若看留出集挑，很容易挑到一个
"误差稍好、区间窄一半、覆盖率崩掉"的候选而不自知。

---

## 4. §2 预注册选模型（规则先落盘，再算指标）

### 4.1 顺序证据（机读）

| 时刻（文件内记录） | 事件 | 证据文件 |
|---|---|---|
| 2026-09-15 **12:39:47** | 预注册规则写定：`selection_rule_preregistered.md`（6559 B，sha256 `cfde5d27…`） | 该文件自身 + `manifest.json.timestamped_or_excluded` |
| **12:42:40** | `select` 只用**训练数据**内层 CV 选出主模型 | `raw\primary_models.json.generated_at`（并声明 `used_holdout_data=false`） |
| **12:46:54** | `compute` 才开始计算留出/跨族指标 | `raw\preregistration_binding.json.computed_started_at`（记录预注册件 sha256 与 select 产物 sha256） |

`compute` 在缺少预注册件或 `primary_models.json` 时**直接 raise**，不静默继续（代码：`require_preregistration()`）。

### 4.2 规则 R1（摘要，全文见预注册件）

对 `V1_intended72`(72 组合) 与 `V2_all162`(162 组合) **各自**：14 个 `(target, freq)` 单元上，
用**与第 4 步同一实现**的内层折（`GroupKFold(3)` 按 `x_scale` 分组）算每个候选的"折内中位相对误差 → 跨折中位"，
取 14 个单元得分的**中位**为总分；按 ① 总分低 → ② 复杂度低（global_mean<ridge<gp<gbr）→
③ 原值优先于 log10 → ④ 候选 id 字典序 依次判胜。**选择过程不接收任何留出点**。

### 4.3 结果：两个变体都选中 `M2_log10_gp`（全部候选指标见下）

| 排名 | V1_intended72 候选 | 总分 | V2_all162 候选 | 总分 |
|---|---|---|---|---|
| 1 | **M2_log10_gp** | **0.055659** | **M2_log10_gp** | **0.140993** |
| 2 | M2_gp | 0.079825 | M3_log10_gbr | 0.194849 |
| 3 | M3_log10_gbr | 0.218286 | M3_gbr | 0.233086 |
| 4 | M3_gbr | 0.242369 | M2_gp | 0.302073 |
| 5 | M1_ridge | 0.414024 | M1_log10_ridge | 0.525389 |
| 6 | M1_log10_ridge | 0.427081 | M0_log10_geomean | 0.702861 |
| 7 | M0_global_mean | 0.475337 | M1_ridge | 0.731727 |
| 8 | M0_log10_geomean | 0.526883 | M0_global_mean | 1.715064 |

**正式"主模型" = `V2_all162` 上胜出的 `M2_log10_gp`**（CLI 默认变体即 V2）。
按照预注册 §3 的事前约定：R1 选中 log10 候选 ⇒ **采用该正值化主模型**（不是事后择优）。

### 4.4 全部候选的留出指标（含落选者；完整 128 行见 `candidate_metrics_all.csv`）

选取 5 个代表性口径（8 个候选 × 2 目标；`err` = `median_of_fold_median_rel_err`，`cov` = 90% 覆盖率，
`hw` = 相对半宽）：

**V1 整列留出 x（诚实插值，`valid_cross_family_ood=false`）**

| 候选 | Ptot err | Ptot cov | Ptot hw | Vave err | Vave cov | Vave hw |
|---|---|---|---|---|---|---|
| M0_global_mean | 0.5786 | 1.000 | 61.202 | 0.4254 | 1.000 | 5.244 |
| M1_ridge | 0.7147 | 0.996 | 13.417 | 0.2790 | 0.984 | 2.065 |
| M2_gp | 0.1566 | 0.855 | 0.673 | 0.0703 | 0.679 | 0.130 |
| M3_gbr | 0.3536 | 0.933 | 2.539 | 0.2286 | 0.738 | 0.428 |
| M0_log10_geomean | 0.6512 | 0.982 | 28.273 | 0.4354 | 0.986 | 3.865 |
| M1_log10_ridge | 0.5496 | 0.960 | 4.699 | 0.3322 | 0.938 | 1.606 |
| **M2_log10_gp** | **0.0571** | 0.669 | **0.081** | **0.0284** | 0.710 | **0.085** |
| M3_log10_gbr | 0.2780 | 0.496 | 0.371 | 0.2240 | 0.464 | 0.212 |

**V1 分组 5 折·按 N1（诚实分块）**

| 候选 | Ptot err | Ptot cov | Ptot hw | Vave err | Vave cov | Vave hw |
|---|---|---|---|---|---|---|
| M0_global_mean | 0.5789 | 1.000 | 56.472 | 0.3443 | 0.994 | 4.931 |
| M1_ridge | 0.6530 | 0.980 | 16.329 | 0.3028 | 0.966 | 1.990 |
| M2_gp | 0.1334 | 0.893 | 1.202 | **0.0233** | 0.800 | 0.179 |
| M3_gbr | 0.4737 | 0.861 | 2.414 | 0.3581 | 0.575 | 0.382 |
| M0_log10_geomean | 0.6122 | 0.984 | 22.834 | 0.4133 | 0.980 | 3.637 |
| M1_log10_ridge | 0.6289 | 0.923 | 3.800 | 0.4173 | 0.893 | 1.190 |
| **M2_log10_gp** | 0.1431 | 0.544 | **0.122** | 0.0642 | 0.675 | **0.085** |
| M3_log10_gbr | 0.6504 | 0.333 | 0.354 | 0.4130 | 0.383 | 0.217 |

**V1 跨族（唯一合法 OOD #1，`valid_cross_family_ood=true`）**

| 候选 | Ptot err | Ptot cov | Ptot hw | Vave err | Vave cov | Vave hw |
|---|---|---|---|---|---|---|
| M0_global_mean | 20.0453 | 1.000 | 57.792 | 1.8610 | 1.000 | 4.984 |
| M1_ridge | 69.8467 | 1.000 | 18.054 | 5.1814 | 1.000 | 1.901 |
| M2_gp | 16.7967 | 0.568 | 1.541 | 1.5102 | 0.069 | 0.171 |
| M3_gbr | 13.8580 | 0.857 | 1.801 | 1.3208 | 0.273 | 0.299 |
| M0_log10_geomean | 5.8858 | 1.000 | 26.933 | 0.9892 | 1.000 | 3.754 |
| M1_log10_ridge | **494.8577** | 1.000 | 4.651 | 17.8592 | 0.880 | 1.541 |
| **M2_log10_gp** | **4.9465** | 0.004 | **0.057** | **0.9940** | 0.056 | **0.048** |
| M3_log10_gbr | 13.7898 | 0.048 | 0.375 | 1.3285 | 0.106 | 0.148 |

**V2 整族留出（合法 OOD #2）**

| 候选 | Ptot err | Ptot cov | Ptot hw | Vave err | Vave cov | Vave hw |
|---|---|---|---|---|---|---|
| M0_global_mean | 8.6081 | 0.660 | 11.358 | 0.8047 | 0.649 | 3.126 |
| M1_ridge | 9.1808 | 0.622 | 10.344 | 0.7951 | 0.642 | 2.378 |
| M2_gp | 6.1209 | 0.436 | 0.855 | 0.7706 | 0.098 | 0.127 |
| M3_gbr | 0.9215 | 0.570 | 1.272 | 0.6093 | 0.479 | 0.276 |
| M0_log10_geomean | 1.2189 | 0.645 | 6.690 | 0.6266 | 0.635 | 2.353 |
| M1_log10_ridge | 1.2847 | 0.602 | 7.299 | 0.6166 | 0.631 | 1.668 |
| **M2_log10_gp** | 1.0000 | 0.033 | **0.281** | 0.6416 | 0.053 | **0.112** |
| M3_log10_gbr | **0.9213** | 0.444 | 0.311 | **0.6088** | 0.462 | 0.186 |

**V2 随机（泄漏对照，`valid_cross_family_ood=false`）**

| 候选 | Ptot err | Ptot cov | Ptot hw | Vave err | Vave cov | Vave hw |
|---|---|---|---|---|---|---|
| M0_global_mean | 4.1521 | 0.997 | 24.609 | 0.6650 | 0.929 | 1.150 |
| M1_ridge | 2.2892 | 0.992 | 27.775 | 0.3794 | 0.957 | 1.908 |
| M2_gp | 0.7508 | 0.968 | 10.483 | 0.1061 | 0.903 | 0.545 |
| M3_gbr | 0.2437 | 0.942 | 1.921 | 0.0580 | 0.908 | 0.276 |
| M0_log10_geomean | 0.9251 | 0.813 | 4.771 | 0.3832 | 0.822 | 0.858 |
| M1_log10_ridge | 0.7226 | 0.850 | 2.901 | 0.3203 | 0.849 | 0.879 |
| **M2_log10_gp** | 0.2687 | 0.911 | **0.895** | 0.0956 | 0.907 | 0.348 |
| M3_log10_gbr | **0.0888** | 0.908 | 0.327 | **0.0535** | 0.901 | 0.198 |

### 4.5 事后观察（**如实写出，但不改选**）

1. 主模型 `M2_log10_gp` 只在"点误差"与"区间宽度"上最优；**在跨族/整族留出上覆盖率最差**
   （0.004 / 0.033）。若改用 `M3_log10_gbr`，V2 整族留出的误差与覆盖率都更好
   （Ptot 0.9213 / 0.444），**但 V1 分块上差得多**（by-N1 Ptot 0.6504 / 0.333）。**没有全局最优候选。**
2. `M1_log10_ridge` 在跨族 Ptot 上误差 **494.86**（495 倍）——**线性模型 + log10 变换在外推上会灾难性放大**，
   这是"log10 正值化不等于安全外推"的直接反例。
3. **每折内层 CV 独立选模型**（同样只用训练折，无泄漏）的稳健性口径（`foldwise_selection_summary.csv`）：
   `M2_log10_gp` 在多数单元被选中（V1 整列留出 Ptot 61/63、按 x 33/35、按 N1 31/35），
   但在 **V2 随机 Ptot 上只有 6/35**（`M3_log10_gbr` 27/35）⇒ **模型选择本身并不一致**，
   主模型是"按预注册规则的平均最优"，不是"每个点上最优"。

---

## 5. 与第 4 步"同一套切分、同一批折、同一口径"的证明

全部只读比对，产物 `raw\equivalence_checks.json`、`step4_parity_after_compute.json`。

| 核查 | 结果 |
|---|---|
| A. 8 个场景的折定义（测试集合的多重集 + 训练 = 该变体全集 − 测试） | **8/8 完全一致**（`A_all_scenarios_match=true`） |
| B. 特征集（两变体均为 `base`）与 8 个候选的超参网格 | **8/8 网格逐字相同**（`B_all_hp_grids_identical=true`） |
| C. 我的通用实现重算 112 个 (变体×目标×频点×原值候选) 单元的超参 | **112/112 与第 4 步冻结件相同** |
| D. 同上单元的保形校准量（q / σ_rel / n_calibration / naive_std / certified） | **112/112 相同**（`D_q_sigma_ncal_all_match=true`） |
| E. 留出误差逐格（64 格：8 场景 × 2 目标 × 4 原值候选） | **64/64 一致**（`error_parity_all_match=true`） |
| F. 覆盖率逐格（64 格） | **64/64 逐位一致** |
| G. 相对半宽逐格（64 格） | **64/64 一致** |
| H. 域内正定性守门扫描（17 行原值候选） | **逐格一致**（点数 952/2142 与拒绝数完全相同） |

⇒ 「负值修复的对比是在**同一套切分、同一批折**下做的」这句话有逐格证据，**不是换口径**。
`log10` 候选是第 4 步没有的**新增**候选，故不在 C/D/E–H 的比对范围内（已如实标注）。

---

## 6. §3 可交互调试入口（`solve_cli.py`）

```
python -B work\ai-solver\step5\solve_cli.py --x-scale <x> --N-w-te1 <n> --freq-MHz <f> --target <Ptot|Vave>
        [--variant V2_all162|V1_intended72] [--model <候选>] [--drive-mode ...] [--geometry-family ...]
        [--json] [--show-all-candidates] [--transcript cli_calls.txt] [--frozen <冻结件>]
python -B work\ai-solver\step5\solve_cli.py --input cli_demo_queries.csv --output cli_demo_answers.csv
```

输出：预测值 + 单位、90% 保形区间（**绝对**与**相对**半宽都给）、校准证据（q/σ/n_cal/certified）、
**log10 正值空间区间**（严格为正、非对称）、物理守门结论、**是否拒答及原因/`fallback="COMSOL"`**、
若该点已测过则并排给出 COMSOL 真值与相对误差（真值与预测**分列**，`no_pooled_value_statistic`）、
放行状态与允许/禁止用途。

**真实调用**：13 次单点 + 1 次批量，全部 `exit 0`；原文（UTF-8）在 `cli_calls.txt`
（30266 B / sha256 `2b01b0949183b47d067e2b33203be8787cfb7596ca646e5760c9ac21bd594916`），
批量的机读结果在 `cli_demo_answers.csv`。

### 6.1 三次"域内接受"原文（逐字）

```text
==============================================================================
第 5 步调试入口 | 旧参数（legacy 单电极 / 1 Ω 驱动）标量代理
查询: variant=V2_all162 target=Ptot x_scale=0.6 N_w_te1=6 freq=20 MHz
      drive_mode=legacy_1ohm_to_reference geometry_family=GF-pmut-ge-task3-b2-intended
使用模型: M2_log10_gp（--model 可覆盖；默认 = 预注册规则 R1 选出的主模型）
判定: 域内接受 refused=false accepted=true role=in_domain_scalar_prediction_not_an_engineering_value
预测: Ptot = 8.16275e-06 W   [source_type=ai_solver, model=M2_log10_gp, output_space=log10]
  模型选择: 该变体主模型（全局主模型 M2_log10_gp）
90% 保形区间（值空间乘性；与第 4 步同口径，便于前后对比）: [3.22571e-06 , 1.30998e-05] W  绝对半宽 ±4.93704e-06 W  相对半宽 ±60.48%
  校准证据: q=4.34057  sigma_rel(MAD)=0.139342  n_calibration=162  alpha=0.1  certified=True
90% 保形区间（log10 正值空间；**严格为正**、非对称）: [3.95881e-06 , 1.68309e-05] W  ×2.062 / ÷2.062  半宽 0.3143 decades
物理守门: Ptot=8.16275e-06 > 0（log10 正值化候选：正值是**结构性**保证）
  正值是否结构性保证: True
旧数据真值（该 (x,N1,freq) **已测过**）: y_true=6.56232e-06 W  [source_type=simulation｜旧参数（legacy）冻结副本 33ed711c…（COMSOL 6.4.0.293 导出）]
  并排相对误差（只做诊断，**不合并统计**）: 24.39%
放行: release_allowed=False  阻塞项=S1 场级相对 L2 不可测（无场快照）; S3 未通过（verdict=inconclusive：4 项物理检查无法判定，见 s3_report.json）; 模型状态 draft；晋升需人工门禁
允许用途: 域内筛选 / 趋势与相对比较；禁止用途: 工程绝对值判断
model_id=mdl-step5-20260915-legacy-debug  model_state=draft  solver_certified=False
```

```text
==============================================================================
第 5 步调试入口 | 旧参数（legacy 单电极 / 1 Ω 驱动）标量代理
查询: variant=V2_all162 target=Vave x_scale=0.6 N_w_te1=6 freq=20 MHz
      drive_mode=legacy_1ohm_to_reference geometry_family=GF-pmut-ge-task3-b2-intended
使用模型: M2_log10_gp（--model 可覆盖；默认 = 预注册规则 R1 选出的主模型）
判定: 域内接受 refused=false accepted=true role=in_domain_scalar_prediction_not_an_engineering_value
预测: Vave = 0.0372559 m/s   [source_type=ai_solver, model=M2_log10_gp, output_space=log10]
  模型选择: 该变体主模型（全局主模型 M2_log10_gp）
90% 保形区间（值空间乘性；与第 4 步同口径，便于前后对比）: [0.028592 , 0.0459197] m/s  绝对半宽 ±0.00866382 m/s  相对半宽 ±23.25%
  校准证据: q=3.91289  sigma_rel(MAD)=0.0594316  n_calibration=162  alpha=0.1  certified=True
90% 保形区间（log10 正值空间；**严格为正**、非对称）: [0.0291615 , 0.047597] m/s  ×1.278 / ÷1.278  半宽 0.1064 decades
物理守门: Vave=0.0372559 > 0（log10 正值化候选：正值是**结构性**保证）
  正值是否结构性保证: True
旧数据真值（该 (x,N1,freq) **已测过**）: y_true=0.0351264 m/s  [source_type=simulation｜旧参数（legacy）冻结副本 33ed711c…（COMSOL 6.4.0.293 导出）]
  并排相对误差（只做诊断，**不合并统计**）: 6.062%
放行: release_allowed=False  阻塞项=S1 场级相对 L2 不可测（无场快照）; S3 未通过（verdict=inconclusive：4 项物理检查无法判定，见 s3_report.json）; 模型状态 draft；晋升需人工门禁
允许用途: 域内筛选 / 趋势与相对比较；禁止用途: 工程绝对值判断
model_id=mdl-step5-20260915-legacy-debug  model_state=draft  solver_certified=False
```

```text
==============================================================================
第 5 步调试入口 | 旧参数（legacy 单电极 / 1 Ω 驱动）标量代理
查询: variant=V2_all162 target=Ptot x_scale=0.425 N_w_te1=6 freq=20 MHz
      drive_mode=legacy_1ohm_to_reference geometry_family=GF-pmut-ge-task3-b2-intended
使用模型: M2_log10_gp（--model 可覆盖；默认 = 预注册规则 R1 选出的主模型）
判定: 域内接受 refused=false accepted=true role=in_domain_scalar_prediction_not_an_engineering_value
预测: Ptot = 2.65335e-05 W   [source_type=ai_solver, model=M2_log10_gp, output_space=log10]
  模型选择: 该变体主模型（全局主模型 M2_log10_gp）
90% 保形区间（值空间乘性；与第 4 步同口径，便于前后对比）: [1.04853e-05 , 4.25816e-05] W  绝对半宽 ±1.60481e-05 W  相对半宽 ±60.48%
  校准证据: q=4.34057  sigma_rel(MAD)=0.139342  n_calibration=162  alpha=0.1  certified=True
90% 保形区间（log10 正值空间；**严格为正**、非对称）: [1.28683e-05 , 5.47098e-05] W  ×2.062 / ÷2.062  半宽 0.3143 decades
物理守门: Ptot=2.65335e-05 > 0（log10 正值化候选：正值是**结构性**保证）
  正值是否结构性保证: True
旧数据真值: 该点在旧数据中**未测过**（外推/插值点，无真值可比）
放行: release_allowed=False  阻塞项=S1 场级相对 L2 不可测（无场快照）; S3 未通过（verdict=inconclusive：4 项物理检查无法判定，见 s3_report.json）; 模型状态 draft；晋升需人工门禁
允许用途: 域内筛选 / 趋势与相对比较；禁止用途: 工程绝对值判断
model_id=mdl-step5-20260915-legacy-debug  model_state=draft  solver_certified=False
全部 8 个候选的点预测（供调试对照）:
  M0_global_mean        2.30852e-06  值空间90%=[-6.9968e-05, 7.4585e-05]
  M1_ridge              4.36427e-06  值空间90%=[-0.000119022, 0.000127751]
  M2_gp                 2.15846e-05  值空间90%=[-0.000138561, 0.00018173]
  M3_gbr                2.33347e-05  值空间90%=[-1.71284e-05, 6.37978e-05]
  M0_log10_geomean      6.18519e-07  值空间90%=[-4.1567e-06, 5.39374e-06]
  M1_log10_ridge        9.95232e-07  值空间90%=[-3.3554e-06, 5.34586e-06]
  M2_log10_gp           2.65335e-05  值空间90%=[1.04853e-05, 4.25816e-05]
  M3_log10_gbr          2.38571e-05  值空间90%=[1.98056e-05, 2.79086e-05]
```

### 6.2 三次"拒答"原文（逐字；均 `fallback="COMSOL"`）

```text
==============================================================================
第 5 步调试入口 | 旧参数（legacy 单电极 / 1 Ω 驱动）标量代理
查询: variant=V2_all162 target=Vave x_scale=0.6 N_w_te1=6 freq=22 MHz
      drive_mode=legacy_1ohm_to_reference geometry_family=GF-pmut-ge-task3-b2-intended
使用模型: M2_log10_gp（--model 可覆盖；默认 = 预注册规则 R1 选出的主模型）
判定: **拒答** refused=true accepted=false role=refusal_due_to_out_of_domain
拒答原因: freq=22 MHz 不在训练过的精确频点集 [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0] 内（7 点不足以支撑插值误差界 ⇒ 本模型**不声明**频率插值能力）
fallback: COMSOL
回退说明: 回退 COMSOL（comsolbatch；注意本机受限文件策略下 COMSOL 会静默失败 rc=15，必须在放宽策略下执行）
外推尝试: extrapolation_attempted=false（**拒绝**无界外推）
允许用途: 域内筛选 / 趋势与相对比较；禁止用途: 工程绝对值判断
```

```text
==============================================================================
第 5 步调试入口 | 旧参数（legacy 单电极 / 1 Ω 驱动）标量代理
查询: variant=V2_all162 target=Ptot x_scale=0.9 N_w_te1=6 freq=20 MHz
      drive_mode=legacy_1ohm_to_reference geometry_family=GF-pmut-ge-task3-b2-intended
使用模型: M2_log10_gp（--model 可覆盖；默认 = 预注册规则 R1 选出的主模型）
判定: **拒答** refused=true accepted=false role=refusal_due_to_out_of_domain
拒答原因: x_scale=0.9 超出适用盒 [0.4, 0.8]
fallback: COMSOL
回退说明: 回退 COMSOL（comsolbatch；注意本机受限文件策略下 COMSOL 会静默失败 rc=15，必须在放宽策略下执行）
外推尝试: extrapolation_attempted=false（**拒绝**无界外推）
允许用途: 域内筛选 / 趋势与相对比较；禁止用途: 工程绝对值判断
```

```text
==============================================================================
第 5 步调试入口 | 旧参数（legacy 单电极 / 1 Ω 驱动）标量代理
查询: variant=V2_all162 target=Zin1_R x_scale=0.6 N_w_te1=6 freq=20 MHz
      drive_mode=legacy_1ohm_to_reference geometry_family=GF-pmut-ge-task3-b2-intended
使用模型: M2_log10_gp（--model 可覆盖；默认 = 预注册规则 R1 选出的主模型）
判定: **拒答** refused=true accepted=false role=refusal_due_to_out_of_domain
拒答原因: 目标量 'Zin1_R' 不在 ['Ptot', 'Vave'] 内（不提供 Zin* 的独立模型：Zin1≡Zin2 是已知公式复制缺陷，电气指标不得当独立量使用）
fallback: COMSOL
回退说明: 回退 COMSOL（comsolbatch；注意本机受限文件策略下 COMSOL 会静默失败 rc=15，必须在放宽策略下执行）
外推尝试: extrapolation_attempted=false（**拒绝**无界外推）
允许用途: 域内筛选 / 趋势与相对比较；禁止用途: 工程绝对值判断
```

### 6.3 负值修复的"调试用法"：同一点的前后对照（`0.4, N1=1, 5 MHz, Ptot`）

```text
# ── 前：第 4 步的原值主模型（--model M3_gbr）→ 物理守门拒答
使用模型: M3_gbr（--model 可覆盖；默认 = 预注册规则 R1 选出的主模型）
判定: **拒答** refused=true accepted=false role=refused_physics_invalid_prediction
拒答原因: physics_invalid_prediction: Ptot=-1.32405e-08 ≤ 0
fallback: COMSOL
外推尝试: extrapolation_attempted=false（**拒绝**无界外推）

# ── 后：预注册主模型（M2_log10_gp）→ 恒正出解，且该点真值 2.9e-11 W，误差 1.96%
使用模型: M2_log10_gp（--model 可覆盖；默认 = 预注册规则 R1 选出的主模型）
判定: 域内接受 refused=false accepted=true role=in_domain_scalar_prediction_not_an_engineering_value
预测: Ptot = 3e-11 W   [source_type=ai_solver, model=M2_log10_gp, output_space=log10]
90% 保形区间（值空间乘性；与第 4 步同口径，便于前后对比）: [1.3e-11 , 4.6e-11] W  绝对半宽 ±1.7e-11 W  相对半宽 ±56.35%
90% 保形区间（log10 正值空间；**严格为正**、非对称）: [1.6e-11 , 5.4e-11] W  ×1.823 / ÷1.823  半宽 0.2609 decades
物理守门: Ptot=2.95594e-11 > 0（log10 正值化候选：正值是**结构性**保证）
旧数据真值（该 (x,N1,freq) **已测过**）: y_true=2.9e-11 W  [source_type=simulation｜旧参数（legacy）冻结副本 33ed711c…（COMSOL 6.4.0.293 导出）]
  并排相对误差（只做诊断，**不合并统计**）: 1.96%
```

### 6.4 第 4 步报告里的示例能否被本入口**原样复现**

程序化重放第 4 步 `refusal_examples.json` 的 **11 个真实调用**（产物 `refusal_replay.json`）：

| 检查 | 结果 |
|---|---|
| 9 个拒答示例的**拒答原因字符串**是否与第 4 步报告逐字相同 | **11/11 相同**（含 2 个域内示例的 `reason=null`） |
| 拒答/接受的**判定**是否一致（用第 5 步入口，含 `--model` 默认为新主模型） | **11/11 一致** |
| 2 个域内示例的**数值**是否与第 4 步逐位相同（`--model M3_gbr`） | **2/2 相同**（`≤1e-12` 相对差）——例如第 4 步「域内 A」= `2.33347e-05 W`、区间 `[-1.71284e-05, 6.37978e-05]`、`q=10.1909`、`σ=0.170156`、`n_cal=162`、相对半宽 `±173.4%`，本入口逐项复现 |

⇒ 「第 4 步报告里的拒答示例能被本入口原样复现」成立；域判定与拒答文案**复用第 4 步同一实现**（不是重写）。

---

## 7. S 级与放行判定（阈值一个都没改）

来源：`s3_report.json`、`s_grade.json`、`raw\smoke.json`。

| 级 | 阈值 | 本轮状态 | 依据 |
|---|---|---|---|
| **S0** 极限一致性 | <1% | **不可测** | 无闭式解、无低频(→0 Hz)扫描；legacy 只有单一 \|Vdiff\|=1 V ⇒ 无法做驱动→0 极限 |
| **S1** 场级相对 L2 | 关键区<2%、全域≤5% | **不可测** | 每个 (组合,频点) 只有 2 个标量 + 1 个单点复数 `V_center`；**无场快照、无公共点集** ⇒ 场级相对 L2 不可测。**严禁**用标量误差冒充 |
| **S2** 工程量误差 | <3% | **已测，未达标** | 主模型诚实分块 `Ptot` 5.7%–14.3%、`Vave` 2.8%–6.4%；跨族 OOD `Ptot` **494.7%**、`Vave` **99.4%**。最好的一格是 V1 整行留出 N1 的 `Vave` **2.76%**（<3%），但它不迁移 |
| **S3** 物理一致性 | 任一 False ⇒ 不通过 | **`inconclusive`**（`release_allowed=false`） | 技能四项（守恒/边界/对称/极限）**全部 `passed=None`**（无场级量/边界值/进出量对/驱动扫描）；本轮把可算的弱必要条件（域内 `Ptot>0`）改为**按各变体的预注册主模型**判定 ⇒ 两个变体 **0/952 与 0/2142** 非正 ⇒ 该检查**结构性通过** ⇒ 整体 verdict 由第 4 步的 `failed` 变为 **`inconclusive`**（`n_checks=6, n_failed=0, n_inconclusive=4`）。**阈值原样取自技能 §2，未改** |
| **S4** 网格无关性 | <2% | **不可测** | 全部结果来自同一网格，导出里没有网格信息 |
| **S5** 误差界校准 | 90% 覆盖率 85–95% | **已认证；覆盖率可迁移性未通过** | 8 场景 × 2 目标 × 8 候选 = 128 个单元里落在 85–95% 带的只有 **29** 个；**主模型只 4/16**（且全在随机/泄漏口径：V1 随机 0.938/0.937、V2 随机 0.911/0.907）；诚实分块 0.54–0.71、跨族 0.004–0.056。`log10` 空间区间覆盖率与值空间几乎相同 ⇒ 换区间口径救不了覆盖率 |

### 7.1 最终放行判定：**不能放行**（与第 4 步同一结论）

```text
solver_certified     = false
releasable_as_solver = false
approved_for_use     = false
model_state          = draft        ← 红线 5：晋升权在人，本轮不晋升
```

理由：① **S1 不可测**（无场快照）——这是"不能称免 COMSOL 求解器"的**唯一根本原因**；
② S2 未达 3%；③ S3 仍是 `inconclusive`（硬门禁语义下 `release_allowed=false`）；
④ S0/S4 不可测、S5 覆盖率可迁移性未通过；⑤ 状态晋升权在人。
**本轮没有为了"调试成功"抬 S 级或放行状态；也没有调整任何阈值。**

---

## 8. 明确回答：修掉负值之后，「域内可用」是否成立？

**成立，但范围比"可用"两个字小得多。** 逐条写清：

**成立的部分**

1. **正值性**：域内点预测的非正比例在两个网格上都降到 **0**，且是**结构性**的
   （`10^x>0`），不是靠守门拦下来的 ⇒ 域内不再需要"非正就拒答"这一层成本转嫁。
2. **精度确实改善**：主模型 V1 诚实分块的中位相对误差 `Ptot` 5.7%–14.3%、`Vave` 2.8%–6.4%
   （第 4 步先验主模型 M3 的对应值是 35.4%–49.7% / 22.9%–35.8%）。
3. **区间变窄且正值化**：V1 整列留出 `Ptot` 相对半宽由 0.673 → **0.081**；
   `log10` 空间区间严格为正。
4. **拒答边界完好**：五类越域（频点/盒/族/驱动/目标）+ 半匝 + 变体盒全部拒答并写 `fallback="COMSOL"`，
   外推尝试恒为 `false`。

**不成立 / 还剩的限制（必须与上面一起读）**

1. **不是工程绝对值**：S2 未达 3%（跨族 `Ptot` 494.7%）。
   允许用途仍是「域内筛选 / 趋势与相对比较」。
2. **误差界只在可交换口径下可信**：主模型 90% 区间在随机口径 0.907–0.938（带内），
   但在诚实分块 0.544–0.710、**跨族 0.004–0.056**。⇒ 区间**不能**跨族/跨盒外推使用；
   跨族查询必须回答"证据不足"（本轮**没有**为此新增拒答规则，因为第 4 步的族判定已经把它拦住：
   跨族 OOD 是**评估口径**，不是可查询的输入域）。
3. **值空间区间仍含非物理值**（主模型 V2 `Ptot` 网格 14.29% 的点下界 ≤0）⇒ 要正值就用 `log10` 空间区间。
4. **没有 S1/S0/S4**：无场快照 ⇒ 仍**不是**免 COMSOL 求解器。
5. **只支持 7 个精确频点**（不声明频率插值）、**只支持 legacy 1 Ω 驱动**（反相驱动无数据 ⇒ 一律拒答）、
   **只支持整数匝数**。
6. **模型选择本身不稳定**（每折内层 CV：V2 随机 `Ptot` 只有 6/35 折仍选主模型），
   `M1_log10_ridge` 在跨族上误差 495 倍 ⇒ **不要**把"log10 正值化"当成外推安全证书。

---

## 9. 来源分离与入库纪律（红线 4/8）

- 真值 `source_type='simulation'`（COMSOL 6.4.0.293 导出）与预测 `source_type='ai_solver'` **分列存放**；
  `raw\cv_detail.csv`（85,680 行）每行都带 `y_true_source_type` / `y_pred_source_type` /
  `role="cv_diagnostic_not_an_engineering_value"`；
- **`no_pooled_value_statistic = true`**：所有统计只对 `rel_err_derived_diagnostic`（派生相对误差）做，
  没有任何把 `simulation` 与 `ai_solver` 取值合并的统计量；
- CLI 的并排真值明确标注"只做诊断，不合并统计"；
- **本产物不得入库为 `source_type='ai_solver'` 样本**：缺 S1 场级验证与 `model_id` 级放行，状态仅 `draft`。
  本轮**未对 `work\store\mems.duckdb` 做任何写操作**（`compute` 里不再做只读探测，第 4 步的结论沿用）。

---

## 10. 复现性与自检

1. **冒烟自测** `smoke_step5.py`：**36/36 全过**（`raw\smoke.json`，
   sha256 `db8c674f3c584f44887d49901136084b16c7ab0041188945f705eb64a746c5bf`）。
   该脚本**确定性**（不含墙钟时间戳）⇒ 重跑逐字节相同，可安全纳入清单
   （与第 4 步 `smoke.json` 的教训相反：那份含耗时、重跑即变，因此被勘误登记）。
   覆盖：预注册绑定 / scratch 副本 39/39 / 数据身份与正值性 / R1 选出的是总分最小者 /
   log10 候选域内零非正 / 原值候选缺陷仍被记录 / 保形 9 点门槛 / 八类拒答 + 域内出解 /
   第 4 步 11 例逐字复现 / 切分与超参网格等价 / 112 单元超参与校准复现 /
   留出误差·覆盖率·半宽·域守门四类逐格一致 / S3 不放行 / 来源分列 / CLI 渲染 / manifest 自洽。
2. **口径等价性**：见 §5（8/8 场景折一致、8/8 网格一致、112/112 超参一致、112/112 校准一致、
   64/64 误差、64/64 覆盖率、64/64 半宽、17/17 域守门一致）。
3. **代码路径不变性核查** `raw\post_edit_code_path_recheck.json`：compute 跑完后我修过
   `domain_guard_scan` / `domain_guard_by_axis` / `s3_checks` 的一处 X/y 形状 bug
   （把**扫描网格** X 与**训练标签** y 一起 `fit` ⇒ `ValueError: inconsistent numbers of samples [136, 72]`）。
   修法是新增 `_train_combos()`：拟合用训练组合、预测用扫描网格。为证明**CV/校准路径未被触碰**，
   用最终代码**逐点重算** 8 个 (场景×折×目标×频点) 单元 × 8 候选 = **64/64 行**，
   与已落盘的 `cv_detail` / `model_fits` 在 1e-9 相对容差内一致（含超参 64/64、内层 CV 得分 64/64）。
   **代码哈希变更史**（机读留痕 `raw\code_hash_history.json`）：
   compute 开始时 `9aa9284e…` → 修 bug 后 `9fc5e1b4…` → 最终 `0373468d…`
   （最后一次只改了 `DebugSolver.predict` 里 `release_blocked_by` 的一句输出文案，不涉及数值路径）。
4. **端到端确定性核查**：见 §11（`raw\determinism_check_run2.json`）。
5. **未给 sha256 的文件**：`raw\run_log_compute.txt`、`raw\run_log_assemble.txt`（含墙钟时间戳，
   按 `AGENTS.md` §3④ 排除）；`selection_rule_preregistered.md`、`raw\primary_models.json`、
   `raw\preregistration_binding.json`（**含时间戳，但它们正是"预注册在前"的承诺证据**，
   按任务单 §5.6 在 `manifest.json.timestamped_or_excluded` 中**单列并给出 sha256**，不声称逐字节可复现）。

---

## 11. 端到端确定性（compute 整轮重跑，逐件比哈希）

同一代码（`step5_solver.py` 最终版 `0373468da569abd83c57d6825c8df4607f937d0be88316cbabe57071a29f1991`）、同一输入，
把 `P.RAW_DIR` 指到系统临时目录后**整轮重算**（8 场景 × 8 候选 × 7 频点 × 2 目标，含冻结件与两个域扫描），
再逐件比 sha256（机读结果 `raw\determinism_check_run2.json`，sha256 `263387a3450300e946719f057bbe160c80ea9621a7fa628e80a2b824a5f142f4`）：

| 产物 | 字节（run1 / run2） | 逐字节相同 |
|---|---|---|
| `raw/cv_detail.csv` | 31,487,381 / 31,487,381 | **相同** |
| `raw/model_fits.csv` | 1,500,997 / 1,500,997 | **相同** |
| `raw/foldwise_selection.csv` | 79,577 / 79,577 | **相同** |
| `raw/frozen_raw.json` | 343,199 / 343,199 | **相同** |
| `raw/domain_guard_scan.csv` | 5,722 / 5,722 | **相同** |
| `raw/domain_guard_by_axis.csv` | 10,320 / 10,320 | **相同** |
| `raw/inputs.json` | 4,878 / 4,878 | **相同** |
| `raw/scratch_step4_copy_manifest.json` | 12,759 / 未生成 | 不适用（见下） |

⇒ 由重算路径产生的 **7/7 件逐字节相同**（含 31 MB、85,680 行的 `cv_detail.csv`、冻结件、两个域扫描表与 `inputs.json`）。唯一未比对的一件是 `scratch_step4_copy_manifest.json`：它由**驱动脚本** `mode_compute` 写入（不在 `P.compute` 内），本次重跑只调用了 `P.compute` + 两个域扫描函数，该文件在 run2 里根本不会生成 ⇒ **这不是确定性失败**（原文见该 JSON 的 `diff_explained` 字段）。

⇒ 结合 §10 第 3 条的『代码路径不变性核查』，可以确认：本轮交付的**全部指标都是最终代码重算过的**，
不存在『改完代码没重算』的隐患。

---

## 12. 未做到 / 不确定（主动列出）

1. **没有 S1**：本数据无场快照 ⇒ 场级相对 L2 不可测。**这是不能称求解器的唯一根本原因**，
   需要按 `field-io-contract` 用 COMSOL 导出固定公共点集上的场快照才能补。
2. **没有 S0 / S4**：需要解析解/低频扫描与多套网格重算，本轮均无数据。
3. **不声明频率插值**（只有 7 个精确频点）、**不声明反相驱动迁移**（数据不存在）、
   **不对半匝外推**。
4. **`x_scale` 盒式插值的能力仍只有"整列留出"间接支撑**，而该口径未通过族泄漏检查
   （`valid_cross_family_ood=false`）；我仍**没有**合格的 OOD 证据支持"盒内任意 `x_scale` 都能用"。
5. **跨族 OOD 的成因未归因**（跨族 + `N1` 外推两种成分混在一起），本轮未做分离实验。
6. **修复的负面效应已如实登记**：区间收窄导致诚实口径覆盖率跌破名义值；`M1_log10_ridge` 跨族误差 495×；
   每折选模型不一致。**没有**为了让"修复成功"好看而隐藏这些。
7. **超参搜索空间仍很小**（M1 α 5 档、M2 核 6 组、M3 深度 2 档），且**只对 `(variant,target,freq)` 逐点选**。
8. **校准点敏感性实验未在本轮重做**（第 4 步已做，覆盖 `V1 整列留出 x`）；本轮沿用其结论。
9. **`V_center (m/s)`（单点复数）仍未使用**——它不是场量，用了也补不出 S1。
10. **COMSOL 侧完全未动**：用户此刻开着 COMSOL GUI（`b_GE_task3_2new.mph` 有 `.lock`），
    本轮**未**启动 COMSOL / mphserver，未触碰该 `.mph` 与其 lock。
11. **确定性核查只覆盖 compute 的重跑**（不重复覆盖 CLI 调用的人类可读文本格式；
    但 `cli_calls.txt` 是确定性渲染，同输入同输出）。
12. **本报告未登记进 `docs\INDEX-records-and-rulings.md`**：按任务硬约束"只写新增文件"，
    且该索引由其它所有者维护（第 4 步报告也遇到过同一情况）——需要登记请由索引所有者补。

---

## 13. 交付声明（越界核查）

- **未修改 `work\ai-solver\step4\` 下任何文件**：全流程只读；且**未在其目录内执行任何脚本/模块**
  （用 `work\runs\_scratch-step5\` 的逐字节副本 import；`all_identical=true`、39/39，
  证据 `raw\scratch_step4_copy_manifest.json`）；
- 未修改 `work\tools\`、`src\memsharness\`（只读 import）、任何**既有** `work\runs\` 目录、
  用户目录（`C:\Users\zmx\Desktop\换能器\`）、`work\models\`、元数据库；
- **新建**目录：`work\ai-solver\step5\`（交付）与 `work\runs\_scratch-step5\`（第 4 步只读副本；
  逐件哈希在 `raw\scratch_step4_copy_manifest.json`，未计入交付清单）；
- 未运行 COMSOL / `comsolbatch` / `mphserver` / `comsolcompile`；未跑 pytest；
- 全流程 `-B` + `PYTHONDONTWRITEBYTECODE=1` + `PYTHONPYCACHEPREFIX`；
  **未留下 `__pycache__`**（核查见 §14）；
- 未调用 `save_model` / `write_model_card` / `register_model`；未写 DuckDB；
- 拿不到的数字（S1/S0/S4、场级误差界、反相迁移性、跨族归因）**留空并说明**，未编造。

---

## 14. 主动披露（不确定处 / 为好看而做的改动 = 无）

1. **为好看而做的改动：无。** 相反有几处是主动把结论写坏：① 明说修复让跨族覆盖率崩到 0.004；
   ② 明说 4/16 格子的误差变差、`M3` 家族 log10 变体几乎不改善误差却砍半覆盖率；
   ③ 明说每折选模型不一致、`M1_log10_ridge` 跨族 495×；④ 明说主模型在跨族上覆盖率最差、
   `M3_log10_gbr` 在 V2 整族留出上更好但 V1 分块更差（**没有全局最优候选**）。
2. **改过阈值吗？没有。** S3 阈值原样取自技能 §2（守恒 0.01 / 边界 1e-6 / 对称 0.02 / 极限 0.02），
   S2 的 3%、S5 的 85–95% 亦原样；`threshold_provenance` 已写入 `s3_report.json`。
3. **`__pycache__` 核查**：见 §15 的最终自检输出。4. **不确定的地方**：
   - `log10` 正值化只保证点预测恒正；**值空间区间仍可能含非物理值**，本轮没有把它强行截断
     （截断就是任务单禁止的掩盖式处理）。
   - 覆盖率的逐折样本量小（每折 56–81 点 × 7 频点），单格覆盖率标准误约 ±0.02–0.05，
     表中 0.669 vs 0.681 这类小差异**不应过度解读**。
   - `S3` 从 `failed` 变 `inconclusive` 是**因为主模型换了**（正值化候选使弱必要条件结构性通过），
     不是物理检查变强了；四项核心检查仍**无法判定**。
   - 本轮**未做**"加性 σ 与乘性 σ"的对照实验（第 4 步的遗留不确定项，本轮沿用乘性口径）。

---

## 附录 A：产物清单（路径 + 字节 + sha256）

| 路径（相对 `work/ai-solver/step5/`） | 字节 | sha256 |
|---|---|---|
| `ai_step5_debug_legacy.py` | 23,901 | `721e1e34bb714dd724ba0562b5d9361d0922bf30ee85462ff59e92e6ebf50925` |
| `candidate_metrics_all.csv` | 76,264 | `e3c9aa68445ea98c35f4b50252561dc13497606c3ec0537741802427c60148f9` |
| `cli_calls.txt` | 30,266 | `2b01b0949183b47d067e2b33203be8787cfb7596ca646e5760c9ac21bd594916` |
| `cli_demo_answers.csv` | 3,343 | `8a2deb6d14fb9d6dcd390917b49142a7cf960c6de9acabaad526d5d41b879bdf` |
| `cli_demo_queries.csv` | 781 | `294374c4411112f06c8b63e94514463049114fc17d42f6926db2411aedfc3d81` |
| `coverage_by_frequency.csv` | 15,684 | `99c05959223ac67551bf0539425841251b3e30eb4742fee408ddc6e4ce69b1cd` |
| `fix_holdout_metrics.csv` | 14,071 | `a2a91730068a71df949d873f62214bb6c40c3f18cb80cea5354490428c384d1b` |
| `foldwise_selection_summary.csv` | 5,775 | `d81fa6950d47f0d399d11f92e77e04726e051440a74bc6f87d493ad4cfe12da3` |
| `models_frozen.json` | 353,594 | `3e24758f7c16554e04c386a0b910bbd99e2cda6b84dd6210adba02bdf5528231` |
| `positivity_fix_comparison.csv` | 4,052 | `670c44f029ba651e49ad231fccd59feb05c4e7143378234332be1c03602deba2` |
| `raw/code_hash_history.json` | 1,983 | `0621779bc7c1aea0207e7bf0caa418906277e621940005c704218f877eff649d` |
| `raw/cv_detail.csv` | 31,487,381 | `2a09a0880f4d4e9ae1606ff05d81253cddecdc5d03571453b896545c5150c4b0` |
| `raw/determinism_check_run2.json` | 3,427 | `263387a3450300e946719f057bbe160c80ea9621a7fa628e80a2b824a5f142f4` |
| `raw/domain_guard_by_axis.csv` | 10,320 | `529ca5a4f264872f45800130ce36256fabd565d4c309d4eea738c9289c317f69` |
| `raw/domain_guard_scan.csv` | 5,722 | `21faa4f824376893f47645096545b5cda8cdf72b61201f1f1a43624344ae72a5` |
| `raw/equivalence_checks.json` | 93,441 | `0b5cc253e4eed6a1a108d3815d853bb35d145f9b9b1617e212c112656b5b598f` |
| `raw/foldwise_selection.csv` | 79,577 | `73c7a5bdf6c9f1a74f4a3a2a606d7b3ab527ecc0b85f68a3fdd95b72fb3a9ee2` |
| `raw/frozen_raw.json` | 343,199 | `f411516ee89f3afa2ec0b298b1b90564910f23ab55d738beea99ca844898c296` |
| `raw/housekeeping_final.json` | 15,803 | `0c49ba4f20a524c3c62c9e8c43f8775b2b268ae15cce6bfe67c6127e769368dd` |
| `raw/inner_cv_selection.csv` | 156,457 | `45730680540a4eff598e6d9a4beaeb4b5d3364f00c3686b5f384038733a51492` |
| `raw/inputs.json` | 4,878 | `e85eba777636634433ef851b132b2eb92fe350df1c4f0745d2a495be05fe927c` |
| `raw/model_fits.csv` | 1,500,997 | `473d9ccb7097805c3b0b8b2b297d7c8f2f111ab47c9a1d02a1bc4bfbe8034251` |
| `raw/post_edit_code_path_recheck.json` | 38,749 | `00eedeadcc6648ae2fb295a719983351124a8f1b4010de7a364f51e92bc26f41` |
| `raw/scratch_step4_copy_manifest.json` | 12,759 | `5b2b3eaef049e35ca3f7daac0cdadc1c8990a6ab4427dfc7bb81fd72990691de` |
| `raw/smoke.json` | 5,133 | `db8c674f3c584f44887d49901136084b16c7ab0041188945f705eb64a746c5bf` |
| `refusal_replay.json` | 12,554 | `d3225dc01feae0b9a4230fe16197b080c822cf391ab754f0cfaa8855a888faee` |
| `s3_report.json` | 3,856 | `a675ecdc0448b2e0381a2d4bf9bf6b944e0b7bca08b1f2e78a91145ebd30d5f7` |
| `s_grade.json` | 12,606 | `a96bed031807bd377af25bd363f890784319d8c3b949d4ad5d003e7e9da7ffbd` |
| `selection_rule_preregistered.md` | 6,559 | `cfde5d27a2990d25e22a8f37c52a745711cfd7ddcad2dfeaab43824119866290` |
| `smoke_step5.py` | 11,006 | `6eec42289611f0163b5c787c42076cd4debffc194d6eb8bc5e531e7e2777ec22` |
| `solve_cli.py` | 13,333 | `6453b205bf744d2e87a798d7168ac4df8f344c086c476106a73f10807a6dfe4f` |
| `step4_parity_after_compute.json` | 48,474 | `56cdd60e0e0014cc61113de38a1d82782f48eca3bfa5443f054b99084b20e030` |
| `step5_assemble.py` | 43,082 | `500eb7c6cfa972231489059dba178438b89721ed83c53bdc8163797029d88ab3` |
| `step5_report.json` | 66,948 | `73cdf10be3b3bec01bb87c688e1fca41a106816860f75029accd2e004b4234bf` |
| `step5_solver.py` | 59,575 | `0373468da569abd83c57d6825c8df4607f937d0be88316cbabe57071a29f1991` |

共 **35 件**（`manifest.json.files`；`manifest.json` 自身不自我引用，故不在表内）。

含时间戳或排除的产物（按任务单 §5.6 单列，不声称逐字节可复现）：

- `work/ai-solver/step5/selection_rule_preregistered.md` — 6,559 B — `cfde5d27a2990d25e22a8f37c52a745711cfd7ddcad2dfeaab43824119866290`
  - 原因：**预注册件含墙钟时间戳**（其哈希是『先承诺』的证据：写入时刻早于任何留出指标计算）；按任务单 §5.6 单列：给出字节与 sha256，但不声称逐字节可复现
- `work/ai-solver/step5/raw/preregistration_binding.json` — 1,005 B — `5e8235a3963ea09f060acfbccb1f93b1b14b65fe656c0071cf281589075358dd`
  - 原因：含墙钟时间戳（generated_at / computed_started_at）⇒ 不声称逐字节可复现；其哈希仅作本次留痕。它是『预注册在前、留出指标在后』的**顺序证据**。
- `work/ai-solver/step5/raw/primary_models.json` — 21,138 B — `27c4c0a1bb1af9af22869bc06691e8106adc4f373d6c90c62e1b4eae4066c96b`
  - 原因：含墙钟时间戳（generated_at / computed_started_at）⇒ 不声称逐字节可复现；其哈希仅作本次留痕。它是『预注册在前、留出指标在后』的**顺序证据**。
- `work/ai-solver/step5/raw/run_log_assemble.txt` — 4,698 B — `（不给 sha256）`
  - 原因：运行日志含墙钟时间戳 ⇒ 按 AGENTS.md §3 第 ④ 条排除，不给 sha256
- `work/ai-solver/step5/raw/run_log_compute.txt` — 6,498 B — `（不给 sha256）`
  - 原因：运行日志含墙钟时间戳 ⇒ 按 AGENTS.md §3 第 ④ 条排除，不给 sha256
- （排除，不计入交付）`work/runs/_scratch-step5/**` — 第 4 步交付目录的**只读逐字节副本**（scratch，39 件）；逐件哈希见 work/ai-solver/step5/raw/scratch_step4_copy_manifest.json。不作为本轮交付物。
- （排除，不计入交付）`work/ai-solver/step5/manifest.json（自身）` — 清单文件自身不自我引用（避免自指哈希）

## 附录 B：与第 4 步交付件的只读引用哈希

| 第 4 步文件 | sha256（本轮只读引用，未改动） |
|---|---|
| `work/ai-solver/step4/models_frozen.json` | `3809648d3b03a075516b2707f54e690c600f628908c5825b0706a6cfef752056` |
| `work/ai-solver/step4/splits.json` | `67f7b9e3f4704450ecd2eb4e16e880ed83648994382aae3ce4a0e63e32f0dd0d` |
| `work/ai-solver/step4/domain_guard_scan.csv` | `07bd54ede150cf030992b68fbdba89650f37b1f513e8e9278cf1979c02d24cd7` |
| `work/ai-solver/step4/model_errors.csv` | `fc24801fc474f44f8685058791d7ce0934c86109dcda526019f40e8f309a792b` |
| `work/ai-solver/step4/conformal_summary.csv` | `e60ba4cda754bff11d79677d95f5afe2a2fc6ebd86433452fd9c951248792eda` |
| `work/ai-solver/step4/refusal_examples.json` | `18b39bec783f83806d49fcb8e24f4e193f45e17a781441d2b4910a4e7b5887a0` |
| `work/ai-solver/step4/raw/scenarios.json` | `8d3dc498719bc3d59cb6c46e5cc0872808eb61143ed010d3b9911c6fac40543e` |

（这些哈希也记录在 `raw\inputs.json.step4_sources` 与各核查产物里，供独立复核。）

---

## 附录 C / §15：最终卫生自检（越界写入与 `__pycache__`）

（只读自检，产物 `raw\housekeeping_final.json`，sha256 `0c49ba4f20a524c3c62c9e8c43f8775b2b268ae15cce6bfe67c6127e769368dd`；窗口 = 本会话 2026-09-15 12:35 起。）

| 检查 | 结果 |
|---|---|
| `work\ai-solver\step4\` 的 39 件与 scratch 副本逐件比对 | **39/39 现在仍然 sha256 相同**；step4 下**本窗口内被修改的文件数 = 0** |
| 全仓 `__pycache__` 条目 | 总计 **9075** 条（历史残留），**落在本窗口内的 0 条** ⇒ 本轮未新增任何字节码 |
| `work\tools\` + `src\`（99 个源文件） | 本窗口内被修改的 **0 个** |
| `work\runs\` 本窗口内的写入（排除 `_scratch-step5\`） | 43 件；抽样前 25 件**全部**落在其它 agent 的运行目录（`model-build-72-20260915` 21 件、`model-complete-solve-0604-20260915` 1 件、`user-param-grid-20260915` 3 件），**我未触碰这些目录**；完整抽样见 `raw\housekeeping_final.json.runs_written_in_window.sample` |
| `work\models\` / `work\store\mems.duckdb` | 未写入（未调用 `save_model` / `write_model_card` / `register_model`；未连库写） |

⇒ 第 4 步交付件在本轮**零字节变化、零执行**；本轮新增写入只落在 `work\ai-solver\step5\`（交付）与 `work\runs\_scratch-step5\`（第 4 步只读副本）两处。
