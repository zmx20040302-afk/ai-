# TO_CODEX 记录：AI 求解器 第 4 步 —— 单电极（legacy）驱动数据域内的代理拟合 + 保形误差界 + 适用域拒答

- 日期：2026-09-15
- 任务单：`docs\TASK-20260915-ai-solver-step4.md`（2026-09-15 11:05 下达）
- 执行者：实现者子代理
- 前置：第 1–3 步已收口（`work\ai-solver\ai_baseline.py` sha256 `9c0a192c…`；
  报告 `docs\TO_CODEX_record-20260915-ai-solver-baseline.md`）
- 性质：**域内标量代理 + 标量保形误差界 + 拒答边界**；**不是**免 COMSOL 求解器（缺 S1）
- **未运行 COMSOL / comsolbatch / mphserver / comsolcompile**；**未写 `work\runs\`**；
  **未修改 `work\tools\` / `src\memsharness\` 下任何文件**（仅只读 import）；
  **未写 `work\models\` / 未写元数据库**；**未跑 pytest**；未新建 `.ps1`

---

## 0. 定位声明（写进代码常量 `POSITIONING`，每个产物都带）

```text
model_id            = mdl-step4-20260915-single-electrode-legacy
model_state         = draft          ← 红线 5：不自行晋升
solver_certified    = False          ← 缺 S1（无场快照 ⇒ 场级相对 L2 不可测）
has_error_bounds    = True           ← **标量** Ptot/Vave 的 90% 保形区间
field_level_error_bound = None       ← 本数据没有任何场级量
allowed_use         = "域内筛选 / 趋势与相对比较"
forbidden_use       = "工程绝对值判断"
s_grade             = S0 不可测 / S1 不可测 / S2 已测(未达标) / S3 failed / S4 不可测 / S5 已认证但仅在随机口径落在 85–95%
must_not_be_stored_as = source_type='ai_solver' 样本（缺 S1 与 model_id 级放行）
```

**允许的结论形态**（任务单 §6）：本轮结论就是
「域内可用、有实测覆盖率、有拒答边界，但**未达 S1 ⇒ 不构成免 COMSOL 求解器**」。
**没有**为了好看去凑 S 级或放行状态。

---

## 1. 命令与产物

```powershell
work\.venv\Scripts\python.exe -B work\ai-solver\step4\probe_input_identity.py   # 输入同一性核查（只读）
work\.venv\Scripts\python.exe -B work\ai-solver\step4\smoke_step4.py            # 冒烟自测（16 项全过）
work\.venv\Scripts\python.exe -B work\ai-solver\step4\ai_step4_single_electrode.py all
# 复现性核查：再跑一次 assemble，逐产物比对 sha256（见 §11）
work\.venv\Scripts\python.exe -B work\ai-solver\step4\ai_step4_single_electrode.py assemble
```

- 环境：Python 3.12.14 + numpy 2.5.3 + scikit-learn 1.9.1 + scipy 1.18.1 + pandas 3.0.5 + duckdb 1.5.5（实测）
- 主脚本耗时：重计算（LOO 重拟合 × 8 场景 × 41 折 × 7 频点 × 2 目标 × 4 模型）≈ 16 min；
  冻结 + 汇总 ≈ 2 min。**第一阶段因特征消融函数的一处索引 bug 崩过一次**，重计算已重跑完成，
  落盘口径见 §11。
- 全部产物清单与 sha256 见 `work\ai-solver\step4\manifest.json`（32 件，见 §6 表；
  运行日志因含墙钟时间戳**已按 `AGENTS.md` §3 第 ④ 条排除**，不给 sha256）。

### 1.1 数据 of record（哈希引用，不引路径）

| 用途 | 文件 | 字节 | sha256 |
|---|---|---|---|
| **训练数据（data of record）** | `work\ai-solver\inputs\扫描阵列Xrange(0.4,0.05,0.8).xlsx`（第 1–3 步冻结副本） | 141,355 | `33ed711c8d53bf02f69686e8e1c62815587919588d73293a5ce899c903951403` |
| 族键来源 | `work\runs\precheck-batch2-phase1-v5\geometry_selection_precheck.csv` | 74,745 | `a8d77f0a5439fad7e925546d4f9381abf49bd43062339968354678650841d2d0` |
| 族划分（引用） | `work\ai-solver\domain\applicable_domain.json` | 4,135 | `94d49121e8e00f1a3b90108141dcfc3a8231272c44d9727468978d32de6037f7` |
| 第 1–3 步切分（引用） | `work\ai-solver\cv\split_assignments.csv` | 2,029 | `e23e06f12f086dc8be55c662c9aa70af2bec74e043ab0a90474cdbb5cbb980b3` |

> 任务单登记的用户原文件 `C:\Users\zmx\Desktop\换能器\扫描阵列Xrange(0.4,0.05,0.8).xlsx`
> **现场字节已变**（见 §2），因此训练一律用上表的**冻结副本**（sha256 与任务单登记值一致）。

---

## 2. 数据身份核查（**新发现，必须登记**）

**事实**：任务单 §1 登记的 sha256 `33ed711c…`（141,355 B）与**现场文件**已不一致。

| | 路径 | 字节 | sha256 | mtime |
|---|---|---|---|---|
| 现场用户文件 | `C:\Users\zmx\Desktop\换能器\扫描阵列Xrange(0.4,0.05,0.8).xlsx` | 141,511 | `4874b50d14c221881b287d370eaa3f26a5a1eb1b115adda8483e5059b870e7b6` | 2026-09-15 11:02:09 |
| 冻结副本 | `work\ai-solver\inputs\…xlsx` | 141,355 | `33ed711c…`（= 任务单登记值） | 2026-09-13 14:25:56 |
| 平台入库副本 | `work\reports\analysis_decision\newrange005\raw_source_table.csv` | 208,503 | `777d0306c569a874086d231130cfdf75808d3fe87cda3f7bfc0dffc4fbe3210a` | — |

**逐格核查（只读；产物 `raw\input_identity.json`，sha256 `3372e535b4e6ca459edb3d889faa1ed4c0452d6755a0bc6dff95755fb084b6cd`）**：

1. **整张工作表**（表头前 4 行元数据 + 表头 + 1134 数据行 = 1139 行 × 10 列 = **11,390 个单元格**）：
   现场文件 vs 冻结副本 **0 处不一致**；
   若只数**非空**单元格 = **11,358**，与父代理独立复核的数字一致（差异仅"空单元格是否计入"）。
2. 表头 + 数据行（11,350 单元格）**0 处不一致**，1134 行 / 162 组合 / 7 频点全同。
3. 现场文件 vs 平台入库副本：**1134 个键全部命中，Ptot 0 处不一致**。
4. 元数据行两文件**逐字相同**：`Model b_GE_task3_2new.mph`、`Version COMSOL 6.4.0.293`、
   `Date Sep 13 2026, 14:25`、`Table 表格 8 - 全局计算 9` —— 与冻结副本 mtime（09-13 14:25:56）吻合。

**结论（按父代理要求的口径写）**：**数据内容未变，仅 xlsx 容器字节因重存而变**（用户机上的活文件，
父代理实测 10:48 有 `~$` 锁、11:02:09 被重存过）。**data of record = `33ed711c…`**；
父代理上一轮「与平台入库副本逐格 4536 单元 0 处不一致」的结论**不受影响**。
本轮所有数字都指向**冻结副本的 sha256**，不指向路径。

---

## 3. 实际调用的既有函数清单（含文件 sha256）

| 模块（文件） | sha256 | 实际调用的符号 | 用途 |
|---|---|---|---|
| `src\memsharness\pod.py` | `ad5774e4c559418e14210f198cecf4d971eb9d283d0507e4f276a0a3b0596fa2` | `conformal_quantile` | **保形分位数**（第 ⌈(n+1)(1−α)⌉ 小得分；不足返回 inf） |
| `src\memsharness\consistency.py` | `3b33756bed2fc6a0badaf109f8b3c95b61d542a85be6bd5d8db66c0a3cacb907` | `CheckResult`、`evaluate_s3` | S3 原语 + **硬门禁**（任一 False ⇒ 不通过；None ≠ 通过） |
| `src\memsharness\dataset.py` | `a811e4c871a7caa995c19be4582190d315fe539b46b68dbc3b604465fb97c9a1` | `split_by_family` | **族整族切分 + 契约强制降级声明**（结果见 §4.3） |
| `src\memsharness\ml\surrogate.py` | `8854c03810e4ee13e60fd23f47f3d6c2cdba774c34da80b42116037e84186947` | `score`、`discover_columns` | `score` 用于「残差标准差硬凑」覆盖率的**交叉核对**（§6.4） |
| `work\tools\lt3_prep.py` | `5b53b1d7c15e22f4cb91382116c08fb4bcdb925c74ae7c0d5382f6317bee3c55` | `read_grid` / `locate_header` / `map_columns` / `parse_complex` / `to_float` / `normalize_freq_column` / `sha256_file` | 读表 / 编码级联 / 复数解析 / 频率单位归一 / 哈希（与 LT3 管线同一套实现） |

### 3.1 **不适用**的接口与替代路径（不硬套）

| 接口 | 为何不适用（实测） | 我实际走的路 |
|---|---|---|
| `ml.surrogate.load_samples` | 需要元数据库连接与 `sample` 表 | 批次2 在库内 **0 条**样本（只读查询实测：`b2_family_samples = 0`，库内只有 `GF-pmut-ge-task3-oval` 等 6 族）⇒ 改为文件空间数据集（`work\ai-solver\` 冻结副本） |
| `dataset.load_groupable_samples` / `build_dataset` | 同上（且 `build_dataset` 会**写库**，本任务禁止写库） | 不调用；改用纯函数 `split_by_family`（见下），并把数据集声明写进文件产物 |
| `dataset.split_by_family` | **适用** | 把 162 个组合构造成 dataset-contract 形状的样本字典后**真实调用**：3 族集 → `cross_family_holdout=true`（留出 `…-boundary` 9 个组合）；V1 单族集 → `cross_family_holdout=false` + `degraded_reason="只有 1 个几何族…"`（契约强制降级，复现第 1–3 步结论）。原文见 `raw\scenarios.json` |
| `ml.surrogate.SurrogateEnsemble` | 本任务要的是岭回归 / 高斯过程 / 梯度提升，不是 MLP 集成 | 未使用；只调用同模块的 `score` 做对照，并显式说明 `score` 的 `1.6449·σ` **是未校准区间** |
| `ml.surrogate.save_model` / `write_model_card` / `register_model` | **会写 `work\models\` 与 DuckDB**，超出本任务允许的写入范围（只许写 `work\ai-solver\step4\` 与 `docs\`） | 一律**不调用**；等价的模型卡/冻结件写在 `step4\models_frozen.json`（超参 + 训练组合索引 + 校准量，载入时用**已登记 sha256 的原始导出**重新拟合 ⇒ 无 pickle、可审计） |
| `ml.surrogate.new_model_id` | 返回 uuid4 ⇒ 产物**不可逐字节复现** | 用固定 `model_id = mdl-step4-20260915-single-electrode-legacy` |
| `pod.fit` / `pod.PodModel` / `pod.relative_l2_field` | 需要**场快照**；本数据每个 (组合,频点) 只有 2 个标量 | 不使用。**不得**用标量误差冒充场级相对 L2（这正是 S1 不可测的原因） |

---

## 4. 切分（诚实性优先）

### 4.1 数据集形态（为什么随机切分必然泄漏）

批次2 = 9 档 `x_scale` × 18 档 `N_w_te1` 的规则网格 × 7 频点 = **1134 行 / 162 组合**。
切分单位是**组合**（同一组合 7 个频点同侧）。族键由预检 `design_status` 派生：
`intended 72 / reversed 81 / boundary 9`；`eligible_for_ranking=true` 只落在 intended ⇒ **V1 = 72 组合（单族）**，
`V2 = 162 组合（3 族）`。

**新增的「近重复泄漏」定量诊断**（`splits.csv` 的 `nn_median_min_nn_dist_grid_median`）：
δ = sqrt((Δx_scale/0.05)² + (ΔN_w_te1)²)，单位 = 网格步。

> **关键发现**：**除跨族切分外，所有切分的 δ 中位数都 = 1 网格步**（精确重复点 0 个）。
> 原因是网格在两个方向上都以 1 步为间距 —— 「整列留出」只清除了被留出轴上的邻居，
> **另一轴的最近邻仍然只有 1 步远**。所以整列/整行留出是「沿该轴的诚实插值估计」，
> 但它**不是**「无近重复」的估计。跨族切分的 δ 中位数分别为 **6**（intended→reversed）与 **4.5**（V2 整族留出）。

### 4.2 三套切分与有效性判据（`splits.csv`，sha256 `94fcc37e0a3dacb4ad6eeb46cac869f3a242c1423242052f5c5bae577583caa9`）

| # | 场景 | kind | 折数 | 族泄漏检查（全折） | **有效 OOD** | δ 中位 |
|---|---|---|---|---|---|---|
| 1 | `V1_intended72/leave_one_xscale_out` | 整列留出 | 9 | ✗ | `valid_ood_estimate=false` | 1 |
| 2 | `V1_intended72/leave_one_N1_out` | 整行留出 | 8 | ✗ | `false` | 1 |
| 3 | `V1_intended72/group_kfold_by_xscale_k5` | 分组 k 折（按 x 列） | 5 | ✗ | `false` | 1 |
| 4 | `V1_intended72/group_kfold_by_N1_k5` | 分组 k 折（按 N1 行） | 5 | ✗ | `false` | 1 |
| 5 | `V1_intended72/random_kfold_k5_seed0` | **random_LEAKY_REFERENCE** | 5 | ✗ | `false` | 1 |
| 6 | `V2_all162/random_kfold_k5_seed0` | **random_LEAKY_REFERENCE** | 5 | ✗ | `false` | 1 |
| 7 | **`V1_intended72/cross_family_train_intended__test_reversed`** | 跨族（**任务指定**） | 1 | **✓** | **`true`** | 6 |
| 8 | **`V2_all162/leave_one_family_out`** | 跨族（3 族各留一次） | 3 | **✓** | **`true`** | 4.5 |

- **只有跨族留出（#7/#8）通过族泄漏检查 ⇒ 只有它们的误差可当 OOD 估计**；其余 6 个按
  `dataset-contract` §6 一律标 `valid_ood_estimate=false`（族键相同 ⇒ 不得声称跨族泛化）。
- 场景 #7 正是任务单 §3.2 要求的 `train=intended(72) / test=reversed(81)`。
- **必须声明的口径限制**：#7 的留出集不只在**族**上不同，还在**特征盒**上外推 ——
  intended 族的 `N_w_te1` 只到 **8**，而 reversed 族到 **18**。因此 #7 的误差同时含
  「跨族」+「N1 方向外推」两种成分，**本轮不做归因**（无独立证据）。

### 4.3 误差表（`model_errors.csv`，sha256 `fc24801fc474f44f8685058791d7ce0934c86109dcda526019f40e8f309a792b`）

口径：`median_of_fold_median_rel_err`（**折内取中位 → 跨折取中位**，与第 1–3 步一致；全部来自留出集）。

| 场景 | 目标 | M0 均值 | M1 岭回归 | **M2 高斯过程** | **M3 梯度提升（主模型）** |
|---|---|---|---|---|---|
| V1 整列留出 x | Ptot | 0.5786 | 0.7147 | **0.1566** | 0.3536 |
| V1 整列留出 x | Vave | 0.4254 | 0.2790 | **0.0703** | 0.2286 |
| V1 整行留出 N1 | Ptot | 0.4723 | 0.5625 | **0.0565** | 0.4973 |
| V1 整行留出 N1 | Vave | 0.3500 | 0.2337 | **0.0217** | 0.2912 |
| V1 分组k折 按x | Ptot | 0.7091 | 0.6791 | **0.1701** | 0.4426 |
| V1 分组k折 按x | Vave | 0.4467 | 0.2799 | **0.0752** | 0.2396 |
| V1 分组k折 按N1 | Ptot | 0.5789 | 0.6530 | **0.1334** | 0.4737 |
| V1 分组k折 按N1 | Vave | 0.3443 | 0.3028 | **0.0233** | 0.3581 |
| V1 **随机（泄漏）** | Ptot | 0.6728 | 0.7626 | **0.0918** | 0.2125 |
| V1 **随机（泄漏）** | Vave | 0.4442 | 0.3187 | **0.0383** | 0.1005 |
| V2 随机（泄漏） | Ptot | 4.1521 | 2.2892 | 0.7508 | **0.2437** |
| V2 随机（泄漏） | Vave | 0.6650 | 0.3794 | 0.1061 | **0.0580** |
| **V1 跨族（唯一合法 OOD）** | Ptot | 20.0453 | 69.8467 | 16.7967 | **13.8580** |
| **V1 跨族（唯一合法 OOD）** | Vave | 1.8610 | 5.1814 | 1.5102 | **1.3208** |
| V2 整族留出（合法 OOD） | Ptot | 8.6081 | 9.1808 | 6.1209 | **0.9215** |
| V2 整族留出（合法 OOD） | Vave | 0.8047 | 0.7951 | 0.7706 | **0.6093** |

**判读**：

1. **跨族 OOD 彻底失败**：主模型 `Ptot` 中位相对误差 **1386%**、`Vave` **132%** —— 远高于任何可用门槛。
   （第 1–3 步报的 `Ptot≈100%` 是核岭回归 + 另一套聚合口径；本轮的 GBR 更差，因为它**不能外推**
   树只会在训练范围内常数外延，而 #7 的 N1 上界超出训练盒。）
2. **诚实分块留出也远超 S2 的 3%**：主模型最好的一格是 `V1 整列留出 x` 的 `Ptot` 35.4%、`Vave` 22.9%。
3. **唯一落在 3% 以下的格子是 M2 高斯过程的 `Vave` 在 N1 行方向**（2.17% / 2.33%），但它
   **不迁移**：同一个 M2 的 `Vave` 在整列留出 x 上 7.03%、在跨族 OOD 上 151.0%。⇒ **不能据此宣称达标**。
4. **模型选择纪律（必须声明）**：主模型 **M3 梯度提升是"先验指定"**（理由写在
   `models_frozen.json.primary_model_rationale`：响应强非单调、`Ptot` 跨 6 个数量级，树集成不需要核平稳假设），
   **不是**用留出集挑的。但本轮实测显示 **M2 高斯过程在几乎所有诚实口径上都比 M3 好 2–4×**。
   **这条观察是事后（post-hoc）的**：若现在改用 M2 当主模型，它的留出指标就变成"在同一批数据上挑过"的
   乐观值。⇒ 本轮**不换主模型**，但把四个模型的点预测与各自的保形区间**全部**返回
   （`predict()` 的 `all_models_point_prediction` 与 `uncertainty_90_by_model`），
   并建议下一轮**预注册**选择规则（训练部分内层 CV）后重测。

### 4.4 随机 vs 分块：泄漏效应（`leak_ratio_random_vs_block.csv`，sha256 `c15caeaed4272d5652a908c733db7b734f6af15517c9703d521429a101e4321b`）

48 组对比（2 变体 × 2 目标 × 4 模型 × 分块场景）：**比值 = 分块中位误差 / 随机中位误差**，
min **0.568**，中位 **1.844**，max **182.9**。

主模型（M3）逐条：

| 变体 | 目标 | 分块场景 | 随机 | 分块 | **比值** | 有效 OOD |
|---|---|---|---|---|---|---|
| V1 | Ptot | 整列留出 x | 0.2125 | 0.3536 | **1.66×** | 否 |
| V1 | Ptot | 整行留出 N1 | 0.2125 | 0.4973 | **2.34×** | 否 |
| V1 | Ptot | 分组k折 按x | 0.2125 | 0.4426 | **2.08×** | 否 |
| V1 | Ptot | 分组k折 按N1 | 0.2125 | 0.4737 | **2.23×** | 否 |
| V1 | Ptot | **跨族** | 0.2125 | 13.8580 | **65.2×** | **是** |
| V1 | Vave | 整列留出 x | 0.1005 | 0.2286 | **2.28×** | 否 |
| V1 | Vave | 整行留出 N1 | 0.1005 | 0.2912 | **2.90×** | 否 |
| V1 | Vave | 分组k折 按x | 0.1005 | 0.2396 | **2.39×** | 否 |
| V1 | Vave | 分组k折 按N1 | 0.1005 | 0.3581 | **3.56×** | 否 |
| V1 | Vave | **跨族** | 0.1005 | 1.3208 | **13.1×** | **是** |
| V2 | Ptot | 整族留出 | 0.2437 | 0.9215 | **3.78×** | **是** |
| V2 | Vave | 整族留出 | 0.0580 | 0.6093 | **10.5×** | **是** |

- 对**有真实拟合能力的模型**，分块的误差**一致高于**随机（1.66–65×）⇒ 随机切分确实给出**虚假信心**。
- **反例必须保留**：48 组里最小值 **0.568 < 1**（M2 高斯过程 `Vave` 整行留出 N1：随机 3.83% → 分块 2.17%），
  即"沿 N1 留一行"在该子集上**不比随机切分更难**；第 1–3 步也报过同类反例。**不修饰。**
- 全局最大比值 **182.9×**（M2 `Ptot` 跨族：随机 9.18% → 跨族 1679.7%）。

---

## 5. 拟合设置（`raw\model_fits.csv`，sha256 `4fb7209353d1766bc301664d79d09d4b514fc1ea3e1e16b22d45f15dc943c167`）

- **逐频点建模**（7 个频点各一个模型），沿用第 1–3 步的结论（响应在频率上强非单调）；
  每个 (场景, 折, 频点, 目标, 模型) 一个实例，共 **2,296 个模型实例**，留出点 **42,840 个**。
- 特征集 `base = [x_scale, N_w_te1]`；`derived = base + [N_w_te1/x_scale, x_scale·N_w_te1]`。
  **派生特征是纯经验交互项，不声称来自已验证物理定律**（红线 3：不猜模型内部）。
- 超参**只在训练部分用内层 CV 选**，且内层折**按 `x_scale` 分组**（`GroupKFold(3)`）以避免
  相邻网格点近重复造成的选择泄漏；分组数不足时退化为随机 k 折并留痕（`inner_cv_grouped_by`）。
- 四个模型：`M0` 训练部分全局均值（对照）、`M1` 岭回归（α 网格 5）、`M2` 高斯过程
  （核超参 = RBF 长度尺度 × 白噪声，内层 CV 选定后 `optimizer=None` 固定）、`M3` 梯度提升
  （深度 2/3 二选一）。**留出集从未参与任何超参选择**。
- **特征消融**（`feature_ablation.csv`，sha256 `c9dbf81f79d68e18b641e12664287ff3bfd2fc2cc20b638475582ea18b6d76d5`；
  场景 = V1 整列留出 x，中位相对误差的中位）：

| 目标 | 模型 | base | derived | 变化 |
|---|---|---|---|---|
| Ptot | M1 岭 | 0.6119 | 0.4752 | −22% |
| Ptot | M2 GP | 0.2366 | 0.1576 | −33% |
| Ptot | M3 GBR | 0.3783 | 0.3106 | −18% |
| Vave | M1 岭 | 0.3074 | 0.2668 | −13% |
| Vave | M2 GP | 0.0556 | 0.0625 | **+12%（变差）** |
| Vave | M3 GBR | 0.2490 | 0.1762 | −29% |

⇒ 派生特征在多数格子上略好、在 `Vave×GP` 上变差，**不是一致改善**；故**冻结件仍用 `base`**
（避免在留出集上挑特征，那也是一种泄漏）。消融数字如实保留。

---

## 6. 误差界：保形预测（**本轮关键新增，并且推翻了第 1–3 步的结论**）

### 6.1 第 1–3 步的结论是**错的**，本轮已用实测覆盖率推翻

第 1–3 步断言：「无逐样本不确定度 + 无场级留出 ⇒ **无法**做保形预测误差界」。
**这个推论不成立**：保形预测的非一致性得分来自**校准集/留出集真值**，与逐样本不确定度字段无关。
本轮实测：**64/64 个 (场景 × 目标 × 模型) 单元全部 certified=true**，每折校准点 **54–130 个**（≥ 9）。
→ 第 1–3 步报告 §6「误差界不可得」一行**以本条为准**（append-only 更正）。

### 6.2 方法与定义

- 非一致性得分：`s_i = |y_i − ŷ_{-i}| / |y_i| / σ_rel`，其中 σ_rel 是**训练部分 LOO 相对残差的稳健尺度**
  （`1.4826 × MAD`），**用 LOO 重拟合取分**（不用训练偏差自证校准）。
- 区间（乘性/相对，适配 `Ptot` 跨 6 个数量级的重尾分布）：`ŷ ± q·σ_rel·|ŷ|`，
  `q = pod.conformal_quantile(scores, alpha=0.1)`。
- **校准点 < 9 时 `conformal_quantile` 返回 inf、`certified=false`**，此时覆盖率一律记 `null`
  （无穷区间覆盖率恒为 1，那是假象，**不得**当通过）。
- 覆盖率在**未参与校准**的留出块上实测。

### 6.3 实测覆盖率（`conformal_summary.csv`，sha256 `e60ba4cda754bff11d79677d95f5afe2a2fc6ebd86433452fd9c951248792eda`）

**必须与"相对半宽"一起读**：覆盖率只说明"区间盖住了真值"，半宽才说明区间有没有用。

主模型 M3 梯度提升：

| 场景 | 目标 | 校准点 | q 中位 | **保形覆盖率** | 保形相对半宽 | **残差标准差硬凑覆盖率** | 硬凑相对半宽 | 留出中位相对误差 |
|---|---|---|---|---|---|---|---|---|
| V1 整列留出 x | Ptot | 64 | 16.22 | **0.933** | ±254% | 0.984 | ±772% | 42.8% |
| V1 整列留出 x | Vave | 64 | 4.90 | **0.738** | ±42.8% | 0.825 | ±46.7% | 23.6% |
| V1 整行留出 N1 | Ptot | 63 | 16.72 | **0.825** | ±230% | 0.875 | ±740% | 51.8% |
| V1 整行留出 N1 | Vave | 63 | 5.04 | **0.550** | ±39.5% | 0.593 | ±44.7% | 29.7% |
| V1 分组k折 按x | Ptot | 56 | 17.96 | **0.933** | ±257% | 0.994 | ±772% | 43.1% |
| V1 分组k折 按x | Vave | 56 | 5.87 | **0.768** | ±46.9% | 0.817 | ±42.5% | 24.3% |
| V1 分组k折 按N1 | Ptot | 54 | 17.01 | **0.861** | ±241% | 0.897 | ±760% | 50.4% |
| V1 分组k折 按N1 | Vave | 54 | 5.73 | **0.575** | ±38.2% | 0.597 | ±43.0% | 29.5% |
| V1 **随机（泄漏）** | Ptot | 58 | 21.13 | **0.966** | ±443% | 0.992 | ±642% | 21.2% |
| V1 **随机（泄漏）** | Vave | 58 | 5.67 | **0.933** | ±45.5% | 0.929 | ±46.5% | 9.5% |
| V2 随机（泄漏） | Ptot | 130 | 7.07 | **0.942** | ±192% | 0.995 | ±959% | 22.8% |
| V2 随机（泄漏） | Vave | 130 | 4.86 | **0.908** | ±27.6% | 0.959 | ±54.8% | 5.9% |
| **V1 跨族（合法 OOD）** | Ptot | 72 | 13.70 | **0.857** | ±180% | 1.000 | ±706% | 1386% |
| **V1 跨族（合法 OOD）** | Vave | 72 | 4.02 | **0.273** | ±29.9% | 0.279 | ±42.4% | 132% |
| V2 整族留出（合法 OOD） | Ptot | 90 | 8.22 | **0.570** | ±127% | 0.590 | ±207% | 92.2% |
| V2 整族留出（合法 OOD） | Vave | 90 | 4.86 | **0.479** | ±27.6% | 0.508 | ±38.6% | 38.2% |

> 最后一列取自 `conformal_summary.csv` 的 `median_rel_err_on_holdout`（**逐点**中位误差），
> 与 §4.3 的 `median_of_fold_median_rel_err`（**折内先取中位、再跨折取中位**）是两套聚合口径，
> 数值会有差异（例：V2 整族留出 `Vave` 逐点 **38.2%** vs 折中位 **60.9%**）。
> **两列都来自文件，不互相替代。**

**判读（三条，缺一不可）**：

1. **保形校准本身成立**：64/64 单元 certified，校准点 54–130（≥9），q 有限。
   **第 1–3 步「无法做保形误差界」被推翻。**
2. **但覆盖率只在"可交换"口径下接近名义值**：随机切分下 0.908–0.966（目标 0.85–0.95 附近）；
   **一旦换成诚实分块或跨族，覆盖率就跌破名义值**，`Vave` 最惨：
   跨族 **0.273**（名义 0.90）、V2 整族留出 0.479、整行留出 N1 0.550。
   这是保形预测的**边际保证依赖可交换性**的直接实测：留出整个族/整行/整列是**分布漂移**，
   不是可交换抽样。**（`Vave` 的塌陷比 `Ptot` 明显，因为 `Ptot` 的区间宽到没有信息量 —— 见第 3 条。）**
3. **`Ptot` 的高覆盖率是"用无用的宽度换来的"**：保形相对半宽 **±127% ~ ±443%**
   （`V1 整列留出` 为 **±254%**，即区间上界约为点预测的 3.5 倍、下界为负）。
   所以「`Ptot` 覆盖率 0.933」**不能**读成"误差界好用"。反过来，M2 高斯过程的 `Vave`
   半宽只有 ±13%（整列留出），覆盖率 0.679 —— **窄区间在漂移下会崩**（跨族 0.069）。
   ⇒ **覆盖率和半宽必须成对报告**，本轮已把两列都落盘。

**汇总数字**：64 个单元里，覆盖率落在技能要求的 **85–95% 带内的只有 14 个**。
因此 **S5 的判据"90% 区间覆盖率 85–95%"并没有被普遍满足**：校准**已认证**，
但**覆盖率的可迁移性未通过**。`s5_passed` 在这些口径下**不是 `true`**。

### 6.4 「残差标准差硬凑」对照：**本轮它没有崩，反而更宽**（如实报告）

技能 §4 记录：用残差标准差硬凑窄区间的后果是「标称 90% 实际覆盖率 **0.030**」。
**本轮实测不是这个方向**：硬凑区间的覆盖率**普遍高于**保形区间（M3：Ptot 0.984 vs 0.933、
Vave 0.825 vs 0.738；V2 随机 Ptot 0.995 vs 0.942）。

**原因（可复核）**：本数据的**相对残差重尾**，`std` 远大于 `1.4826×MAD`，
所以 `1.6449×std` 造出的区间比保形区间**更宽**（M3 Ptot 整列留出：±772% vs ±254%）。
⇒ 本数据上"硬凑"是**过度保守**，不是崩塌。

**但结论不变、仍然禁止用它当误差界**，理由与数值无关的只有一条：
**它没有任何有限样本覆盖率保证** —— 它的宽度完全由重尾决定，换一批数据可以任意窄，
技能记录的 0.030 正是那条路径。本轮用**校准点数敏感性**复现了那一路径（见 §6.5：
校准点 < 9 时保形返回 `inf`/`certified=false`；硬凑没有这个保护，会照样给出一个"看起来正常"的窄区间）。

**交叉核对**：用平台 `ml.surrogate.score`（它会用 `1.6449·σ` 且**会警告覆盖率偏离目标**）
在全部 64 个单元上复算硬凑覆盖率，**63/64 与本脚本直算值逐位一致**；
唯一一处差异是 `V1 整行留出 N1 / Vave / M3`：平台 0.595238（=300/504）vs 直算 0.593254（=299/504），
差 **1 个边界点** —— 原因是平台 `score` 用字面量 `1.6449`，本脚本用精确 `Z90=1.6448536269514722`。
**如实登记，不当成 bug 隐藏**。产物 `raw\score_module_check.csv`
（sha256 `e1742319edb7cb0d1c2a8c9cfbcb78403df03b15e7e0042fc5d8e06fca4def61`）。

### 6.5 校准点数敏感性（`conformal_calibration_size.csv`，sha256 `12ede55c4e5aa66362a0d9b5a88b9c94a5cc0a4bbd5a437ea3c29610f3944159`）

用 `V1 整列留出 x` 的真实 LOO 得分向量，确定性地随机抽取 m 个校准点（seed=0），只改 q、σ 不变：

| m（校准点） | certified 的模型实例数（共 63 个折×频点） | q | 实测覆盖率 |
|---|---|---|---|
| **4** | **0** | **inf** | **null**（区间不可用） |
| **6** | **0** | **inf** | **null** |
| **8** | **0** | **inf** | **null** |
| **9** | 63 | 有限（6.07–105.7） | 0.764–1.000 |
| 12 / 16 / 24 / 32 / 48 / 64 | 63 | 有限（4.33–130.2） | 0.679–1.000 |
| **9 – 64（全区间）** | 63 | 有限（4.33–130.2） | 0.679–1.000 |

⇒ **恰好在 m=9 处跨越 `ceil((m+1)(1−α)) ≤ m` 的门槛**（α=0.1），完全符合技能 §4 的
「90% 区间至少需要 9 个校准点」。`m<9` 时 `conformal_quantile` 返回 `inf`、`certified=false`、
覆盖率记 `null` —— **这是正确结论**，也说明第 1–3 步"样本不足 ⇒ 不可做"的逻辑只在本数据
**校准点 ≤ 8** 时才成立，而本数据每折有 54–130 个校准点，**远够**。

---

## 7. 适用域与拒答（**真实调用，原文**）

API：`work\ai-solver\step4\step4_solver.py` 的 `FrozenSolver.predict(...)` —— **同一函数、同一入口**
既做域判定也出解。完整原文见 `refusal_examples.json`
（sha256 `18b39bec783f83806d49fcb8e24f4e193f45e17a781441d2b4910a4e7b5887a0`）。
**11 个真实调用：9 个拒答、2 个域内接受**（证明拒答不是"永远拒答"）。

| # | 输入 | 返回（原文） |
|---|---|---|
| 1 | `x=0.6, N1=6, 20 MHz, drive=dual_electrode_antiphase_voltage_drive, intended, Ptot, V2` | `refused=true, fallback="COMSOL"`；`drive_mode='dual_electrode_antiphase_voltage_drive' 不是训练时的驱动口径 ['legacy_1ohm_to_reference']（本数据**只有** legacy 1 Ω 驱动；反相驱动数据尚不存在，迁移性未验证）` |
| 2 | `…, 22.0 MHz, legacy, intended, Vave, V2` | `refused=true`；`freq=22 MHz 不在训练过的精确频点集 [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0] 内（7 点不足以支撑插值误差界 ⇒ 本模型**不声明**频率插值能力）` |
| 2b | `…, 45.0 MHz, …` | 同上（并与全仓 45 MHz 数据缺口一致） |
| 3 | `…, 20 MHz, legacy, geometry_family='GF-pmut-ge-task3-oval', Ptot, V2` | `refused=true`；`geometry_family='GF-pmut-ge-task3-oval' 不在训练族 ['GF-pmut-ge-task3-b2-boundary','…-intended','…-reversed'] 内` |
| 4a | `x_scale=0.9, N1=6, …` | `refused=true`；`x_scale=0.9 超出适用盒 [0.4, 0.8]` |
| 4b | `x=0.6, N_w_te1=25, …` | `refused=true`；`N_w_te1=25 超出适用盒 [1, 18]` |
| 5 | `…, target='Zin1_R', …` | `refused=true`；`目标量 'Zin1_R' 不在 ['Ptot','Vave'] 内（不提供 Zin* 的独立模型：Zin1≡Zin2 是已知公式复制缺陷，电气指标不得当独立量使用）` |
| 附加 | `N_w_te1=5.5` | `refused=true`；`N_w_te1=5.5 不是整数：匝数是**离散**设计变量，本模型只声明整数匝数之间的插值，不对半匝外推` |
| 附加 | `N1=12` 查 **V1** 模型 | `refused=true`；`N_w_te1=12 超出适用盒 [1, 8]`（同一点在 V2 内 → 域随模型版本变化，已实测） |
| **域内 A** | `x_scale=0.425（未观测档位）, N1=6, 20 MHz, legacy, intended, Ptot, V2` | `refused=false, accepted=true`；`value=2.3334685e-05 W`；`interval_90 = [-1.7128428e-05, 6.3797798e-05]`，`q=10.1909`、`σ_rel=0.17016`、`n_calibration=162`、`certified=true`、`相对半宽 +173.4%` |
| **域内 B** | `x=0.6, N1=6, 20 MHz, legacy, intended, Vave, V2` | `refused=false, accepted=true`；`value=0.035037434806 m/s`；`interval_90=[0.028884350019, 0.041190519593]`、`相对半宽 +17.6%` |

- 全部拒答都带 `extrapolation_attempted=false`、`fallback="COMSOL"`、
  `allowed_use="域内筛选 / 趋势与相对比较"`、`forbidden_use="工程绝对值判断"`、`model_state="draft"`。
- **必须指出的两点**：
  1. **域内 A 的保形区间下界为负**（−1.71e-05 W）。保形区间是**统计**区间，**不在 0 处截断**，
     所以它包含物理上不可能的值；它不是物理界。
  2. **域内 A 的相对半宽 +173%** —— 覆盖率"达标"但这区间对工程无用。
     这与 §6.3 第 3 条是同一件事的两个视角。`predict()` 会同时返回四个模型各自的区间
     （`uncertainty_90_by_model`），让调用方看得见模型间差异。

---

## 8. 域内物理守门：**新发现的实质性缺陷**（红线 7）

S3 的"域内正定性"是**真的算得出来**的必要条件：`Ptot` 是输入电功率、`Vave` 是速度**幅值**（原表是复数串，
本脚本取模）⇒ 二者必须 > 0。在**声明的域内**网格（`x_scale` 0.4→0.8 步长 0.025 × `N_w_te1` 全档 × 7 频点）
上逐模型扫描（`domain_guard_scan.csv` sha256 `07bd54ede150cf030992b68fbdba89650f37b1f513e8e9278cf1979c02d24cd7`）：

| 变体 | 目标 | M0 均值 | M1 岭 | M2 GP | **M3 GBR（主）** |
|---|---|---|---|---|---|
| V2（2142 点） | Ptot | 0 (0%) | 168 (**7.84%**) | 347 (**16.20%**) | **201 (9.38%)** |
| V2（2142 点） | Vave | 0 | 21 (0.98%) | 25 (1.17%) | 5 (0.23%) |
| V1（952 点） | Ptot | 0 | 60 (6.30%) | 37 (3.89%) | **67 (7.04%)** |
| V1（952 点） | Vave | 0 | 17 (1.79%) | 0 | 1 (0.11%) |

**触发位置有结构**（`domain_guard_by_axis.csv`，sha256 `992ff27d720692a19aed863a665609b3efe578fbebeac884a2ed61c9f2c746bd`）：
主模型 `Ptot` 在 **5 MHz 且 `x_scale ≤ 0.525` 时 18 档 N1 里有 13 档被拒（72.2%）**，
在 **10 MHz 且 `x_scale ≥ 0.725` 时 18 档里有 10 档被拒（55.6%）**；其余区域基本为 0。

**处置（未改任何阈值）**：

- `predict()` 内建**运行时物理守门**：预测值 ≤ 0 ⇒ **拒答并回退 COMSOL**
  （`role="refused_physics_invalid_prediction"`、`physics_check_passed=false`）。
  这是**实测会触发的守门**，不是理论担忧。
- **结论**：**声明的盒式域对 M1/M2/M3 偏乐观**（7–16% 的域内网格点在物理上不成立）。
  这是本轮暴露的**新限制**，必须随模型一起声明：**「域内可用」必须再加一条"且通过正定性守门"**。

---

## 9. S 级状态与放行结论（`s_grade.json` sha256 `a47d7d9e0d8de30a6be41a939c416a3b2f1e28a9ba2edc58c86d363105ebc125`）

| 级 | 能力 | 状态 | 能不能测 / 为什么 |
|---|---|---|---|
| **S0** 极限一致性 | 阈值 < 1% | **不可测** | 需要闭式/解析极限解或低频（→0 Hz）扫描。本数据频点下界 **5 MHz**，没有该器件的解析模型；legacy 驱动只有单一 \|Vdiff\|=1 V，**无法做驱动→0 的极限**。缺：解析解 或 专用低频 COMSOL 扫描 |
| **S1** 场级相对 L2 | 关键区 < 2%、全域 ≤ 5% | **不可测** | 每个 (组合,频点) 只有 **2 个标量**（`Ptot`、`Vave`）加一个**单点复数** `V_center (m/s)`；**没有任何场快照、没有公共点集**。缺：按 `field-io-contract` 用 COMSOL 导出固定公共点集上的场快照（含掩膜）再做独立场留出。**严禁**用标量误差替代 S1 |
| **S2** 工程量误差 | 阈值 < 3% | **已测，未达标** | 见 §4.3：主模型诚实分块 `Ptot` 35.4–49.7%、`Vave` 22.9–35.8%；跨族 OOD `Ptot` 1386%、`Vave` 132%。全部 64 个 (场景×目标×模型) 单元里**只有 2 格**低于 3%（M2 高斯过程的 `Vave` 在 N1 行方向 2.17% / 2.33%）且**不迁移**（同一 M2 的 `Vave` 在整列留出 x 上 7.03%、跨族 151.0%） |
| **S3** 物理一致性 | 任一 False ⇒ 不通过 | **`failed`**（`release_allowed=false`） | `evaluate_s3` 原文：`n_checks=5, n_failed=1, n_inconclusive=4`。技能 §2 的四项（守恒/边界/对称/极限）本数据上**全部 `passed=None`**（无场级量、无进出量对、无驱动扫描）；附加的**域内正定性**弱必要条件 **passed=False**（域内网格上四个模型合计 **716 次** `Ptot ≤ 0` 判定，8568 次判定中的 8.36%；见 §8）。**阈值原样取自技能默认值，一个都没改** |
| **S4** 网格无关性 | 阈值 < 2% | **不可测** | 批次2 全部结果来自**同一个网格**，导出里没有网格信息。缺：同模型多套网格（粗/中/细）+ Richardson 外推。单网格数据**不可**推断网格无关性 |
| **S5** 误差界校准 | 90% 覆盖率 85–95% | **已认证；覆盖率可迁移性未通过** | 64/64 单元 `certified=true`（校准点 54–130 ≥ 9）。但覆盖率落在 85–95% 带内的只有 **14/64**；随机口径 0.908–0.966，**跨族/整族留出塌到 0.273–0.857**（`Vave` 最差 0.273）。且 `Ptot` 的"达标"靠 ±127%~±443% 的无用宽度换来 |

### 9.1 最终放行判定：**不能放行**

```text
solver_certified        = false
releasable_as_solver    = false
approved_for_use        = false
model_state             = draft        ← 红线 5：晋升需人工门禁，本轮不晋升
```

**为什么**：

1. **S1 不可测**（无场快照）⇒ 不满足 `solver_certified` 的必需项；
2. **S2 未达 3%**（诚实分块与跨族均远超）；
3. **S3 = `failed`**（硬门禁：`release_allowed=false`）；
4. S0/S4 不可测；S5 只在随机口径成立、且区间宽度对 `Ptot` 无工程价值；
5. 红线 5：状态晋升权在人。

**因此本模型只允许用于「域内筛选 / 趋势与相对比较」，不得输出用于工程判断的绝对值。
它不是免 COMSOL 求解器。** 域内使用还必须再加一条：**通过 `predict()` 的正定性守门**
（否则约 9% 的域内点会给出物理上不成立的解 —— 见 §8）。

---

## 10. 来源分离（红线 4 / 8）

- 真值 `source_type='simulation'`（COMSOL 导出）与预测 `source_type='ai_solver'` **分列存放**；
  每一行都带 `y_true_source_type` / `y_pred_source_type` / `role="cv_diagnostic_not_an_engineering_value"`
  （`raw\cv_detail.csv`，42,840 行；sha256 `2b417c219aa170a20a8a0290a438849b2bef759a74c58efb53964ef5580ccb48`）。
- **`no_pooled_value_statistic = true`**：所有统计只对 `rel_err_derived_diagnostic`（派生相对误差）做，
  **没有任何**把 `simulation` 与 `ai_solver` 取值合并的统计量。计数见 `source_separation.csv`
  （sha256 `1dfd0e8c7e07dbbb1c9d60ade383e2ed4655be9a6d372c9cd59540aa8de49534`）。
- **本产物不得入库为 `source_type='ai_solver'` 样本**，原因：缺 **S1 场级验证**与 `model_id` 级放行，
  模型状态仅为 `draft`（`AGENTS.md` 红线 7–8；`ai-solver-verification` §0 的入库条件要求
  `model_id` + `uncertainty` **且** 已放行）。**本轮未对 `work\store\mems.duckdb` 做任何写操作**
  （只在 `compute` 里做了一次**只读**探测，用于判定 store 路径是否适用；探测失败也已容错留痕）。

---

## 11. 复现性与自检

1. **冒烟自测**：`smoke_step4.py` **18 项全过**（`raw\smoke.json`，sha256 `1d1701f3636a16180b1595b29ba98a2f64830e4973c58ec1604b42576edcb411`），
   覆盖：输入 sha256 一致 / 1134 行 / 8 场景 / 跨族判定 / 近重复 δ=1 / 全模型 certified /
   跨族误差 > 0.3 / `conformal_quantile` 的 n=0/8/9 行为 / 五类拒答 + 域内出解 / S3 `release_allowed=false` /
   `surrogate.score` 可复用。
2. **确定性核查**：连跑两次 `assemble`，逐产物比对 sha256：
   **32/32 件逐字节相同**（清单副本 `raw\determinism_manifest_run1.json` / `run2.json`，已从 manifest 排除）。
   产物中**不含任何时间戳**（`run_date` 是固定字符串）。
3. **诚实披露的失败**：重计算阶段第一次运行**崩在特征消融函数**（`sorted({c[0] for c in v1})` 取到了 float 而不是组合集合
   → `TypeError: 'float' object is not iterable`）。当时昂贵结果（42,840 行 CV 明细）**已在场景循环末尾落盘**，
   因此未丢；修好后用 `--reuse` 只重跑消融/交叉核对/冻结。**修复后全流程 `exit 0`。**
4. **未给 sha256 的文件**：`raw\run_log*.txt`（运行日志，含墙钟时间戳，按 `AGENTS.md` §3 第 ④ 条排除）
   与 `raw\determinism_manifest_run*.json`（复现性核查的派生物）。manifest 里已写明排除原因。

---

## 12. 未做到 / 不确定（主动列出）

1. **没有 S1**：本数据无场快照 ⇒ 场级相对 L2 不可测。**这是本轮不能称求解器的唯一根本原因**，
   需要一条 COMSOL 场导出链（`field-io-contract`）才能补。
2. **没有 S0 / S4**：需要解析解/低频扫描与多网格重算，本轮均无数据。
3. **不声明频率插值**：只允许 5/10/15/20/25/30/35 MHz 这 7 个精确频点（22/45 MHz 一律拒答）。
4. **不声明反相驱动迁移**：反相驱动数据尚不存在 ⇒ 一律拒答（未验证 ≠ 不可用，只是没有证据）。
5. **`x_scale` 盒式插值的能力**只由「整列留出」间接支撑，而该口径
   **未通过族泄漏检查**（`valid_ood_estimate=false`）；且 §4.1 的近重复诊断显示它清不干净另一轴的邻居。
   ⇒ 我对"盒内任意 `x_scale` 都能用"这句话**没有**合格的 OOD 证据，只有"沿该列的诚实插值误差 35%/23%"。
6. **跨族 OOD 的成因未归因**：场景 #7 同时含"跨族"与"`N1` 外推（训练盒上界 8 vs 留出到 18）"两种成分，
   本轮**没有**做分离实验，故**不做归因**。
7. **模型选择是事后观察**：M2 高斯过程在诚实口径上明显优于先验指定的 M3（§4.3 第 4 条），
   但本轮**没有**换主模型，也**没有**为选择规则做预注册重测。下一轮若要换，必须重新测一遍留出指标。
8. **域内正定性守门只覆盖了 0 与正负号这一条必要条件**，不是完整 S3；
   且守门只在 `predict()` 的**主模型**输出上执行，其它三个模型的点预测是原样返回的（不过区间是各自算的）。
9. **超参搜索空间很小**（`M1` α 5 档、`M2` 核 6 组、`M3` 深度 2 档）。
10. **校准点敏感性实验只做了 `V1 整列留出 x` 一个场景**（其余场景的定性行为应相同，但未逐场景复测）。
11. **报告未登记进 `docs\INDEX-records-and-rulings.md`**：该文件在本轮进行中被**另一个 agent**
    写入（11:22:22）。按任务硬约束"只写新增文件"，我**没有**改动它 —— 需要登记请由索引所有者补。

---

## 13. 交付声明

- 未运行 COMSOL / `comsolbatch` / `mphserver` / `comsolcompile`；
- 未写 `work\runs\` 下任何内容（本轮窗口内 `work\runs\` 的写入全部来自**另一个 agent** 的 LT2 生产运行，
  已在 §14 留痕）；未修改 `work\runs\` 任何**既有**目录；
- 未修改 `work\tools\` 下任何文件、未修改 `src\memsharness\` 下任何文件（两者均**只读 import**）；
- 未修改用户目录 `C:\Users\zmx\Desktop\换能器\` 下任何文件、未修改
  `work\reports\analysis_decision\newrange005\` 下任何文件；未修改第 1–3 步任何产物；
- **未在 `work\tools\` / `src\` 下新增任何文件**：全流程 `-B` + `PYTHONDONTWRITEBYTECODE=1` +
  `PYTHONPYCACHEPREFIX`，并**逐一核查**了两目录下所有 `__pycache__` 文件的 mtime ——
  **无一落在本会话窗口（≥ 11:00）内**，`lt3_prep` 的 `.pyc` **不存在**（第 1–3 步踩过的坑未复发）；
- 未调用 `save_model` / `write_model_card` / `register_model`（会写 `work\models\` 与 DuckDB）；
  未写 `work\store\mems.duckdb`（只有一次只读探测且带容错）；
- 未跑 pytest；
- 只新建/写入了 `work\ai-solver\step4\`（新建目录，39 个文件）与本报告 `docs\` 下**新增**一个文件；
- 拿不到的数字（S1/S0/S4、场级误差界、反相迁移性、跨族归因）**留空并说明**，未编造。

### 14. 主动披露（越界 / 为好看做的改动 / 不确定处）

1. **越界写入：无。** 已按 §13 逐项核查。附带留痕：本会话窗口（≥11:00）内仓库其它位置
   确实有新写入，但**全部来自另一个 agent 的 LT2 生产运行与 r3h 证据**
   （`work\runs\lt2-resource-confirm-…`、`work\runs\lt2-prod-trial4-combo-20260915\`、
   `work\runs\_evidence-r3h\`、`docs\TO_CODEX_record-20260915-r3h-production-path-endorsement.md`、
   `docs\INDEX-records-and-rulings.md`），**与本轮无关**，我未触碰。
2. **为让结果好看而做的改动：无。** 相反，有几处是"主动把结论写坏"的：
   ① 明确写出 `Ptot` 的达标覆盖率是靠 ±254% 的无用宽度换来的；② 明确写出唯一低于 3% 的两格
   **不迁移**；③ 明确写出本数据上"残差标准差硬凑"**没有崩、反而更宽**，因此**不能**用技能的
   0.030 数字来论证本轮的结论；④ 明确写出事后发现 M2 优于先验主模型 M3 但**不换**（换了就是选择泄漏）。
3. **改过一次阈值吗？没有。** S3 阈值原样取自技能 §2（守恒 0.01 / 边界 1e-6 / 对称 0.02 / 极限 0.02），
   并在 `s3_report.json.threshold_provenance` 留痕；S2 的 3%、S5 的 85–95% 亦原样。
4. **不确定的地方**：
   - `conformal_quantile` 的 σ 我取"训练部分 LOO 相对残差的 MAD"，这是**乘性归一**；
     若换成加性 σ（绝对尺度），`Ptot` 的区间会因为跨 6 个数量级而完全无意义 ——
     这个选择我写在 §6.2，但**没有**做加性/乘性对照实验。
   - 覆盖率的**逐折样本量很小**（每折 8–32 个留出点 × 7 频点），所以单格覆盖率的标准误约 ±0.02–0.05；
     表中差异小的格子（例如 0.9325 vs 0.933）不应被过度解读。
   - `M2` 高斯过程在 `S3` 正定性上最差（V2 `Ptot` 16.2% 域内点为负）却在误差上最好 ——
     "哪个模型更好"取决于用哪把尺子，本轮**没有**做加权裁决。
   - `V_center (m/s)` 这一列（单点复数值）**本轮未使用**；它**不是**场量，用了也补不出 S1。

---

## 附录 A：产物清单（路径 + 字节数 + sha256）

来源：work\ai-solver\step4\manifest.json（sha256 9ac4855a7055247d41b876263c86b1b722c74ea3b4b3bd23cb36c772ee30d23c），共 32 件。

| 路径 | 字节 | sha256 |
|---|---|---|
| work/ai-solver/step4/ai_step4_single_electrode.py | 60251 | ec693e514d63044877a8d7bdeb4880f342dae5f08730882d0682d8a60f259213 |
| work/ai-solver/step4/conformal_calibration_size.csv | 10701 | 12ede55c4e5aa66362a0d9b5a88b9c94a5cc0a4bbd5a437ea3c29610f3944159 |
| work/ai-solver/step4/conformal_summary.csv | 28778 | e60ba4cda754bff11d79677d95f5afe2a2fc6ebd86433452fd9c951248792eda |
| work/ai-solver/step4/domain_guard_by_axis.csv | 10026 | 992ff27d720692a19aed863a665609b3efe578fbebeac884a2ed61c9f2c746bd |
| work/ai-solver/step4/domain_guard_scan.csv | 3254 | 07bd54ede150cf030992b68fbdba89650f37b1f513e8e9278cf1979c02d24cd7 |
| work/ai-solver/step4/feature_ablation.csv | 1486 | c9dbf81f79d68e18b641e12664287ff3bfd2fc2cc20b638475582ea18b6d76d5 |
| work/ai-solver/step4/leak_ratio_random_vs_block.csv | 7408 | c15caeaed4272d5652a908c733db7b734f6af15517c9703d521429a101e4321b |
| work/ai-solver/step4/model_errors.csv | 13087 | fc24801fc474f44f8685058791d7ce0934c86109dcda526019f40e8f309a792b |
| work/ai-solver/step4/model_errors_by_frequency.csv | 64629 | 0ba005260dda0c7e379f33a1dc8de4bebe575d4bcb8106a80a886ba1dfe6c12e |
| work/ai-solver/step4/models_frozen.json | 118058 | 3809648d3b03a075516b2707f54e690c600f628908c5825b0706a6cfef752056 |
| work/ai-solver/step4/probe_input_identity.py | 7260 | 795ca7a5225665e75fe54d3aeae10cc19385bec36ac8ac9cf6ea0a6b017b3cc5 |
| work/ai-solver/step4/probe_step4_data.py | 6323 | dc5f0303a53ce6aa868764863f7844b569f14376b3232286f84926a35237137f |
| work/ai-solver/step4/raw/ablation.csv | 67574 | 9fae7d83b9c4d04d28905c5ccde29a9ba7b69c09d1be572c46eb46bf372dbb81 |
| work/ai-solver/step4/raw/conformal_scores.csv | 15516393 | a7bb0fead5ff94a27771c4e828bc3a6ebbd2433486aa2bdc9bdd8a4d011057b6 |
| work/ai-solver/step4/raw/cv_detail.csv | 13505974 | 2b417c219aa170a20a8a0290a438849b2bef759a74c58efb53964ef5580ccb48 |
| work/ai-solver/step4/raw/frozen_raw.json | 118058 | 3809648d3b03a075516b2707f54e690c600f628908c5825b0706a6cfef752056 |
| work/ai-solver/step4/raw/input_identity.json | 3372 | 3372e535b4e6ca459edb3d889faa1ed4c0452d6755a0bc6dff95755fb084b6cd |
| work/ai-solver/step4/raw/inputs.json | 4283 | 0114b5ea804771d6ec78bba6a3283d6de719275b3c92aae19dde8f583b34f7b0 |
| work/ai-solver/step4/raw/model_fits.csv | 687018 | 4fb7209353d1766bc301664d79d09d4b514fc1ea3e1e16b22d45f15dc943c167 |
| work/ai-solver/step4/raw/scenarios.json | 98657 | 8d3dc498719bc3d59cb6c46e5cc0872808eb61143ed010d3b9911c6fac40543e |
| work/ai-solver/step4/raw/score_module_check.csv | 13533 | e1742319edb7cb0d1c2a8c9cfbcb78403df03b15e7e0042fc5d8e06fca4def61 |
| work/ai-solver/step4/raw/smoke.json | 8436 | 1d1701f3636a16180b1595b29ba98a2f64830e4973c58ec1604b42576edcb411 |
| work/ai-solver/step4/refusal_examples.csv | 3302 | 918e864d5428a37b8d42c6daa3a022fda6695d2dd6737dc920d1d7f2c8580105 |
| work/ai-solver/step4/refusal_examples.json | 21550 | 18b39bec783f83806d49fcb8e24f4e193f45e17a781441d2b4910a4e7b5887a0 |
| work/ai-solver/step4/s3_report.json | 3892 | b3b579e0b57675478a666f17714ecac3d6a54b05b8f3c16b4dfbb0826b7b6ef7 |
| work/ai-solver/step4/s_grade.json | 11177 | a47d7d9e0d8de30a6be41a939c416a3b2f1e28a9ba2edc58c86d363105ebc125 |
| work/ai-solver/step4/smoke_step4.py | 9920 | 1ea8127d5d0f4fb6ae940183d70972382c62de98686f5600e64a24b3ba93a707 |
| work/ai-solver/step4/source_separation.csv | 2361 | 1dfd0e8c7e07dbbb1c9d60ade383e2ed4655be9a6d372c9cd59540aa8de49534 |
| work/ai-solver/step4/splits.csv | 3519 | 94fcc37e0a3dacb4ad6eeb46cac869f3a242c1423242052f5c5bae577583caa9 |
| work/ai-solver/step4/splits.json | 13890 | 67f7b9e3f4704450ecd2eb4e16e880ed83648994382aae3ce4a0e63e32f0dd0d |
| work/ai-solver/step4/step4_report.json | 232611 | a010172e8653a90dd2b6caf9610648b824811a202ff9661629808cbe77978ebd |
| work/ai-solver/step4/step4_solver.py | 56402 | dfef437263c735f9fc2cab51382c4790df28c7e2d32513b8f9f15cd975c159a4 |

排除在 manifest 之外的文件（原因见 manifest.json.excluded_from_manifest）：
- work/ai-solver/step4/raw/determinism_manifest_run1.json
- work/ai-solver/step4/raw/determinism_manifest_run2.json
- work/ai-solver/step4/raw/run_log.txt
- work/ai-solver/step4/raw/run_log2.txt
- work/ai-solver/step4/raw/run_log3.txt
- work/ai-solver/step4/raw/run_log4.txt
