# TO_CODEX 记录：LT3 前置管线（代码与口径先行，批次2 legacy 数据跑通）

- 日期：2026-09-14
- 性质：**独立的准备性工作**（preparatory）。目标是在 LT2 反相驱动 504 点数据到位之前，
  把 LT3 分析管线的**代码与口径**先建好并跑通，使数据到位后可直接套用。
- 本轮**未运行 COMSOL / comsolbatch / mphserver**，**未写 `work\runs\`**，**未修改任何禁改文件**。
- 依据工单：`docs\TO_CODEX_order-20260913-LT0-LT3.md` §5（LT3-A/B/C/D）；
  授权限制：`docs\TO_CODEX_order-20260914-LT2-superseding-LT2B-LT2D.md` §7（`LT2 = BLOCKED_BEFORE_PRODUCTION`）。

---

## 1. 命令与退出码

解释器：`work\.venv\Scripts\python.exe`（Python 3.12.14）。

### 运行 A —— 批次2 legacy 数据（主交付，exit 0）

```powershell
work\.venv\Scripts\python.exe work\tools\lt3_prep.py `
  --input "C:\Users\zmx\Desktop\换能器\扫描阵列Xrange(0.4,0.05,0.8).xlsx" `
  --source-run-id "batch2-legacy-newrange005-xlsx-33ed711c" `
  --precheck "work\runs\precheck-b2-phase2-v5-aggregate\geometry_selection_precheck.json" `
  --out-dir "work\lt3"
# exit code = 0
```

> 说明：输入用的是**用户原始导出 xlsx**（sha256 `33ed711c8d53bf02f69686e8e1c62815587919588d73293a5ce899c903951403`），
> 走的是脚本内置的**标准库 xlsx 读取路径**（zipfile + XML，本机 venv 无 openpyxl），
> 因此同一条命令对未来的反相 xlsx 导出同样适用。输入已复制到 `work\lt3\inputs\`。

### 运行 B —— LT1 反相数据（守卫验证，exit 3 = fail-closed 生效）

```powershell
work\.venv\Scripts\python.exe work\tools\lt3_prep.py `
  --input "work\runs\lt1-reverse-sample\lt1_validated_results_v2.csv" `
  --source-run-id "lt1-reverse-sample" `
  --out-dir "work\lt3\_guard_test_reverse"
# exit code = 3（拒绝输出排名/Pareto）
```

### 运行 C/D —— 守卫的反向验证（exit 2）

```powershell
# 请求正式排名：直接拒绝
... --formal   -> exit 2（不产出任何排名）
# 试图写 work\runs：直接拒绝
... --out-dir "work\runs\_lt3_should_fail"  -> exit 2（未创建任何文件）
```

---

## 2. 产物路径与 sha256

工具：`work\tools\lt3_prep.py`，58,348 B，sha256 `c5e6923593d6e9960e94332e973c4be95529744111b31fc86c0af82d4415af05`

> 哈希稳定性说明：`lt3_metrics.csv`、`lt3_pareto.csv`、`lt3_pareto_dominance.csv`、`lt3_ranking.csv`
> 在**同一输入 + 同一命令行**下重跑哈希逐字节稳定（已实测）。
> `lt3_quality_report.json` 与 `lt3_manifest.json` 会把「输入是否被复制到 `work\lt3\inputs\`」
> （含绝对路径）写进报告，因此改变 `--no-copy-inputs` 或输入路径会改变这两个文件的哈希；
> 这是**输入依赖**，不是时间戳噪声，已在 `inputs_copied_to_lt3` 字段留痕。

### 2.1 主交付（`work\lt3\`，运行 A）

| 产物 | 字节 | sha256 |
|---|---|---|
| `work\lt3\lt3_quality_report.json` | 8,521 | `06e89dd9a7def86ce8d50209ca1bbcf155e56fb5f25c5a52d189408eabd62ff9` |
| `work\lt3\lt3_ranking.csv` | 20,901 | `76d5315c81c5469b10f84b95463cbf1ae8772f6cdec9ac55add51763c0c0bcf6` |
| `work\lt3\lt3_pareto.csv` | 131,642 | `d9de7cb749b87080f5d10ae6a6a9df6adf55007ddcf1e4c8782e428f8e41d46f` |
| `work\lt3\lt3_pareto_dominance.csv` | 659,355 | `db139d6ccaf88f07b8176e75752b50c7db39d249855edc33042a81ae5c768c0d` |
| `work\lt3\lt3_metrics.csv` | 96,423 | `6681c70e5a0a1d56e01e3e937750b5782dc58e50439c935589aed2e704b7d97a` |
| `work\lt3\lt3_normalization_contract.md` | 4,659 | `b6e7bcc6ae918f510ae1dcb6d4b640e639eaf86c54b7d5f73c59608b55796936` |
| `work\lt3\lt3_ranking_status.json` | 1,266 | `f338ff9e6c8557a5670c02a453d0c071a0a9ccc5a3626f51fed77949b23c4f1d` |
| `work\lt3\lt3_manifest.json` | 2,549 | `46495a92685d11af7e2aaccbbe0caf09a58df58a3593637e08021d12ad44f9ed` |
| `work\lt3\inputs\扫描阵列Xrange(0.4,0.05,0.8).xlsx` | 141,355 | `33ed711c8d53bf02f69686e8e1c62815587919588d73293a5ce899c903951403` |
| `work\lt3\inputs\geometry_selection_precheck.json` | 764,321 | `b26193fea3f56a6ebab6c36456f23a7dd37d58c757fd3ce80ef3edf6f03c6b4a` |

### 2.2 守卫验证产物（`work\lt3\_guard_test_reverse\`，运行 B）

| 产物 | 字节 | sha256 |
|---|---|---|
| `lt3_guard_refusal.json` | 1,215 | `f56c3842ab7a4199da517c133ff8f1f4a8fbadcdace0f182a38801004189b764` |
| `lt3_intermediate_comparison.csv` | 1,393 | `a582f304717f9fe52d34f7e02da4861657ce4ee03f849d0dc28e337df14cc05f` |
| `lt3_quality_report.json` | 7,706 | `90a89ea6610ca456b7b3f95499452a0ca973d4b6019f387f7c2781a42f4f2f0c` |
| `lt3_metrics.csv` | 2,824 | `58e826cc3589fa390f354777a6654015234db42a42cf71b890bece74f53ad71a` |
| `lt3_normalization_contract.md` | 4,345 | `49c8eec4947e3ad16c8ff91e53c50fe92ac9d198869aa11d7c51adba7f6fd144` |
| `lt3_manifest.json` | 1,966 | `da4b034ee3fdf6949e3587bb2426e492d09623225effa46b02fe8eb5f1233152` |

**该目录下没有** `lt3_pareto.csv` / `lt3_pareto_dominance.csv` / `lt3_ranking.csv` / `lt3_ranking_status.json`
—— 这正是 fail-closed 的落地证据。

---

## 3. 实际发现的既有产物清单（路径 + sha256 前 16）

以下每一项都经 `sha256` 实算，**未复制粘贴旧记录**。

### 3.1 几何/选择预检（level-1 与 level-2）

| 路径 | 字节 | sha256[:16] |
|---|---|---|
| `work\runs\precheck-b2-phase2-v5-aggregate\aggregate_manifest.json` | 10,170 | `3089c844d1ae8480` |
| `work\runs\precheck-b2-phase2-v5-aggregate\geometry_selection_precheck.json` | 764,321 | `b26193fea3f56a6e` |
| `work\runs\precheck-b2-phase2-v5-aggregate\geometry_selection_precheck.csv` | 22,589 | `513c0b8c20787950` |
| `work\runs\precheck-b2-phase2-v5-aggregate\quality_report.md` | 1,012 | `d7d6221a7cd07f95` |
| `work\runs\precheck-b2-phase2-v5-aggregate\source_runs.json` | 6,351 | `e3f2d257c37d8a22` |
| `work\runs\precheck-b2-phase2-v5-aggregate\selection_mismatch_patterns.json` | 1,565 | `c32b527e0eba45fc` |
| `work\runs\precheck-batch2-phase1-v5\geometry_selection_precheck.json` | 444,875 | `e771fd3e21d24af9` |
| `work\runs\precheck-batch2-phase1-v5\geometry_selection_precheck.csv` | 74,745 | `a8d77f0a5439fad7` |
| `work\runs\precheck-batch2-phase1-v5\sentinel_report.json` | 8,873 | `152ba5fa68c03790` |
| `work\runs\precheck-batch2-phase1-v5\checkpoint.jsonl` | 262,894 | `c468e52c8ee49bdb` |

实测内容（供口径核对）：聚合件含 `phase2_rows`=72、`phase1_rows_with_pattern_id`=162；
一级预检 162 组分类分布 = `intended_design/verified/eligible` **72** 组、
`design_region_reversed/selection_mismatch` **81** 组、`design_boundary_coincident` **9** 组；
`mesh_status` 在一级预检全为 `not_run`（一级不建网格），level-2 聚合 `mesh_ok_all = true`。

### 3.2 决策/分析报告（`work\reports\analysis_decision\`）

| 路径 | 字节 | sha256[:16] |
|---|---|---|
| `...\newrange005\raw_source_table.csv` | 208,503 | `777d0306c569a874` |
| `...\newrange005\_data_quality.json` | 1,099 | `f3cdbbaf15307881` |
| `...\newrange005\freeze_inputs.json` | 1,603 | `6f9b9a48fc73ec77` |
| `...\newrange005\02_data_quality_report.md` | 2,267 | `5a0aa32c9df6695f` |
| `...\newrange005\03_codex_numbers_verification.md` | 5,108 | `50c131373854f4e7` |
| `...\_data_quality.json`（批次1，490 行） | 903 | `dc8dde02c7ae29ea` |
| `...\freeze_inputs.json`（批次1） | 3,814 | `8644019c2afde68d` |
| `...\final_phase2_ranking\00_provenance.json` | 1,634 | `0b418a752401c9a3` |
| `...\final_phase2_ranking\01_cleaned_results.csv` | 392,019 | `7ca99902dd2ed9bb` |
| `...\final_phase2_ranking\03_coarse_sweep_metrics.csv` | 82,582 | `9d6bd15365c1a009` |
| `...\final_phase2_ranking\04_pareto_candidates.csv` | 9,231 | `8ba53d4cd5d20312` |
| `...\final_phase2_ranking\ranking_status.json` | 459 | `46d492bf452dcc27` |
| `...\final_phase2_ranking\precheck_compat.json` | 11,391 | `9311b92ce15b5341` |

口径事实：`final_phase2_ranking\00_provenance.json` 记 `drive_mode = circuit_terminal_1ohm_current_model`
（= legacy 别名）、`model_version = original_selection_original_drive`、
`model_sha256 = 0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d`、
`precheck_combos_loaded = 72`；`ranking_status.json` 自述
“『正式』仅指粗频网格筛选完成，不能替代 5–45 MHz 精扫与 7R 声压评价”——与本轮 fail-closed 立场一致。

### 3.3 既有分析代码（复用对象）

| 路径 | 字节 | sha256[:16] |
|---|---|---|
| `scripts\analyze_sweep.py` | 32,283 | `4a8b72aafb4e014d` |
| `scripts\geometry_selection_precheck.py` | 46,889 | `dded1fe6f6d013e6` |

`lt3_prep.py` **复用**了 `analyze_sweep.py` 的口径，而不是另起一套：
① `20*log10`（幅值，用于 `Vave`）/ `10*log10`（功率，用于 `Ptot`）绝不混用；
② −6 dB 交点相邻点线性插值、找不到就标 `*_bound_not_found`、**不拿边界冒充交点**；
③ 只在预检 `clean/eligible` 子集内排名，未提供预检则显式降级；
④ **不做无依据单一加权总分**，改为多指标 + Pareto 非支配前沿；
⑤ 复用了它的编码级联读表、`parse_complex` 复数解析、列关键词识别（`COL_PATTERNS`）与
   `sha256_file` 溯源写法；⑥ 同样对 stdout 设 `errors="replace"`（Windows GBK 控制台踩坑）。

### 3.4 模型侧审计与驱动清单（`work\models\`）

| 路径 | 字节 | sha256[:16] |
|---|---|---|
| `work\models\drive_change_manifest.json` | 3,734 | `450a8825d6eb7181` |
| `work\models\port_audit.json` | 7,043 | `437bc89459f13233` |
| `work\models\port_audit.csv` | 2,606 | `122766216df1e455` |
| `work\models\lt0_audit.json` | 4,508 | `f74851c9d4775156` |
| `work\models\reverse_drive_audit.json` | 4,703 | `91ebebfa1ffeb02b` |
| `work\models\reverse_drive_audit.csv` | 1,745 | `652fa832b6a0350c` |
| `work\models\effective_parameter_ledger.csv` | 5,929 | `e7611cb37714d6af` |
| `work\models\b_GE_task3_2new_reverse_voltage_drive_v1.mph` | 138,959,575 | `cbe9ccc18e51005f` |

**LT0-C 电气排除的依据**（本轮直接引用，未重算）：
`work\models\lt0_audit.json` 中 `kcl_max_relative = 0.18863816663610675`，
三频点 `kcl_relative` = 0.16623 / 0.17968 / 0.18864（5/20/35 MHz），
`kcl_pass = false`、`electrical_current_metrics_excluded = true`。

### 3.5 用户的批次2 原始导出（只读引用）

| 路径 | 字节 | sha256 |
|---|---|---|
| `C:\Users\zmx\Desktop\换能器\扫描阵列Xrange(0.4,0.05,0.8).xlsx` | 141,355 | `33ed711c8d53bf02f69686e8e1c62815587919588d73293a5ce899c903951403` |
| `C:\Users\zmx\Desktop\换能器\扫面x&N1，间隔阵列扫描.csv`（批次1，对照） | 87,065 | `0a49d5a1f0fbe5e2` |

批次2 xlsx 的 sha256 与任务书给出的 `33ed711c…` **一致**。原件未改动，
仅复制到 `work\lt3\inputs\`（复制后 sha256 复核相等）。

### 3.6 意外发现：**已存在反相驱动实测数据**（LT1 小样）

| 路径 | 字节 | sha256[:16] |
|---|---|---|
| `work\runs\lt1-reverse-sample\lt1_validated_results_v2.csv` | 11,971 | `43d5711cbb2d7141` |
| `work\runs\lt1-reverse-sample\lt1_validation_summary_v2.json` | 2,152 | `5bb36377a82d4442` |
| `work\runs\lt1-reverse-sample\final_drive_state_verification.json` | 968 | `169f4af611bd7213` |

这是 **5 组合 × 3 频点 = 15 点**的 LT1 反相小样（`drive_mode = dual_electrode_antiphase_voltage_drive`，
`Vdiff_abs = 2.0`，`Ptot_norm`/`Vave_norm` 已给出），**不是** LT2 的 504 点粗扫。
本轮把它用作**守卫验证输入**（运行 B），验证「检测到反相驱动数据 ⇒ 拒绝排名」确实生效。

### 3.7 **未找到**的项（如实列出，未编造）

| 期望项 | 结论 |
|---|---|
| LT2 反相驱动 504 点粗扫原始表（72 组合 × 7 频点） | **未找到**。`work\runs\` 下无任何 `reverse_drive_coarse_raw*`、无 504 行反相结果表；`lt2-prod-b2-r1\` 只有 `dryrun\resource_timeline.*`（资源试跑，非求解结果）。 |
| LT2 聚合验收产物（`reverse_drive_coarse_aggregate`、`reverse_drive_coarse_quality_report`） | **未找到**（LT2 处于 `BLOCKED_BEFORE_PRODUCTION`，符合预期）。 |
| `work\reports\analysis_decision\final_phase2_ranking\02_*` | **未找到**。该目录编号从 `01_` 直接跳到 `03_`；未发现 `02_` 系列文件（`02_data_quality_report.md` 只在 `analysis_decision\` 根与 `newrange005\` 下）。 |
| 64 组合聚合产物（`TO_CODEX_64组与72组聚合结果.md` 提到的 64 组） | 在 `work\runs\` 下**未找到**独立的 64 组聚合运行；只有 `precheck-b2-phase2-v5-*`（72 组）与 `precheck-b2-phase2-v5-x060-pilot`（8 组试跑）。 |
| 批次2 所用 7.93 GB `.mph` 的 sha256 | **未找到**（`work\reports\analysis_decision\newrange005\freeze_inputs.json` 记为 `sha256: null` + `lock_present: true`，即当时 GUI 打开中，按 SOP 不取哈希）。 |
| `work\lt3\` | 运行前**不存在**（由本轮创建）。 |

---

## 4. 质检结果（关键数字及其来源文件）

来源文件：`C:\Users\zmx\Desktop\换能器\扫描阵列Xrange(0.4,0.05,0.8).xlsx`
sha256 `33ed711c8d53bf02f69686e8e1c62815587919588d73293a5ce899c903951403`（141,355 B）。
机读报告：`work\lt3\lt3_quality_report.json`（sha256 `06e89dd9a7def86c…`）。
本批 `source_run_id = batch2-legacy-newrange005-xlsx-33ed711c`。

| 检查项 | 实测值 |
|---|---|
**唯一键** | 1134（= 162 组合 × 7 频点）
**重复键** | **0**
**缺失键／缺失组合** | **0**（对照预检 162 组网格，`extra` 也为 0）
**每组合频点数** | 全为 7（分布 `{7: 162}`，一致）
**必需声学量空值** | `Ptot` 0、`Vave` 0、`V_center` 0
**NaN / Inf / 不可解析** | 全为 0（含 `Vave`/`V_center` 复数解析）
**负 `Ptot`** | **0**；`Ptot = 0` 行 **0**
**驱动失配** | 行级 `drive_mismatch_rows = 0`；声明 vs 推断不一致 = `false`（本批导出**无** drive_mode 列，故声明值集合为空，靠列结构推断为 legacy）
**驱动电位一致性** | `applicable = false`（legacy 导出无 `V_outer/V_inner/Vdiff` 列 ⇒ 不可核验，**不填推测值**）
**频率顺序** | 频点非严格递增的组合 **0**
**`Zin1 ≡ Zin2` 逐位相同** | **1134 / 1134**（已知公式缺陷；本管线不使用任何一个 `Zin`）
**电气指标排除** | `electrical_metrics_excluded = true`，`reason = LT0_C_KCL_relative_gt_1pct`
**几何/选择预检** | 已提供；载入 162 组，其中 **eligible = 72**（`intended_design + verified`）
**归一化量** | `Ptot_norm` / `Vave_norm` **全部留空**，`normalization_reason = legacy_export_lacks_Vdiff__normalization_not_computable`

列实核（批次2 导出表头）：
`x_scale, N_w_te1, freq (Hz), Zin1_R (Ω), Zin1_X (Ω), Zin2_R (Ω), Zin2_X (Ω), Ptot (W), V_center (m/s), Vave (m/s)`
—— **没有**任何电位/差分电压列。这是「legacy 归一化不可计算」的**直接证据**。

---

## 5. Pareto 前沿与支配关系

- 口径：两个**声学**指标 `Ptot@20 MHz`（W）与 `Vave@20 MHz`（m/s），均**最大化**；
  只在预检 `eligible` 子集（72/162）内计算；被排除的 90 个组合（`design_region_reversed` 81 + `design_region_boundary_coincident` 9）
  一律不参与，并在 `lt3_pareto.csv` 里标 `pareto_exclusion_reason = not_eligible_for_ranking`。
- 结果：可算两指标 **72** 个；**Pareto 前沿 = 1 个**：`(x_scale = 0.45, N_w_te1 = 6)`，
  `Ptot@20 MHz = 2.64977457801718e-05 W`，`Vave@20 MHz = 0.0904587950136826 m/s`；
  **被支配 = 71 个**；支配对 **2323** 对（写入 `lt3_pareto_dominance.csv`）。
- ⚠️ **重要实质发现**：在 20 MHz 这一个频点上，本批 legacy 数据的 `Ptot` 与 `Vave` **高度同序**
  （Top-5 两者的组合次序几乎相同），因此 Pareto 前沿**退化为单点**——
  这对指标在此数据上**不构成权衡（no trade-off）**，Pareto 方法对本组合**不提供额外设计信息**。
  LT3-C 的候选角色（最大归一化声功率 / 带宽闭合且平坦的均衡代表 / 15–25 MHz 最平坦）
  必须依赖**带宽与平坦度**类指标才能产生区分度；本脚本已把 `-6 dB 交点 / FBW / 平坦度` 列为
  **待补指标**（见 §7），数据到位后按同一口径补算。**本结论不外推到反相驱动数据**。
- **多指标排名表**（`lt3_ranking.csv`，72 行，sha256 `76d5315c81c5469b…`）：
  四个声学指标各自独立排名，前 4 名如下（`row_order` 只表示按这四个名次依次排列，**不是综合得分**）：

| row_order | x_scale | N_w_te1 | Ptot@20MHz (W) | rank_Ptot | rank_Vave | Pareto | dominated_by_count |
|---|---|---|---|---|---|---|---|
| 1 | 0.45 | 6 | 2.64977457801718e-05 | 1 | 1 | True | 0 |
| 2 | 0.45 | 7 | 2.27880895666485e-05 | 2 | 2 | False | 1 |
| 3 | 0.45 | 5 | 2.23791769880876e-05 | 3 | 3 | False | 2 |
| 4 | 0.5 | 6 | 1.6262218765022e-05 | 4 | 5 | False | 3 |

> 注意：`Ptot@20 MHz` 与 `Vave@20 MHz` 的名次几乎完全同序，进一步印证 §5 的退化结论。
> 表中 `Vave@20MHz` 为**面平均法向速度（响应量）**，**不得**称往返/脉冲回波/阵列带宽。

---

## 6. 归一化口径：哪些量可跨驱动比较、哪些不可

完整口径说明见 `work\lt3\lt3_normalization_contract.md`（sha256 `b6e7bcc6ae918f51…`）。
脚本内以 `normalization_contract()` 函数固化（**写进代码**，不只在文档里）。

公式：

```text
Ptot_norm = Ptot / |Vdiff|^2      [W/V^2]   （功率量）
Vave_norm = Vave / |Vdiff|        [(m/s)/V]（幅值量）
dB：幅值 20*log10，功率 10*log10，绝不混用
```

| 驱动 | `Vdiff` | 导出含 `Vdiff` | `Ptot_norm` | `Vave_norm` |
|---|---|---|---|---|
| `legacy_1ohm_to_reference` | **未记录** | **否** | **不可计算** | **不可计算** |
| `dual_electrode_antiphase_voltage_drive` | 2 V（`V_outer=+1`, `V_inner=-1`, `V_ref=0`） | 是 | 可计算 | 可计算 |

### 6.1 **可**跨驱动比较（有条件）

| 量 | 条件 |
|---|---|
| `Ptot_norm = Ptot/\|Vdiff\|²` | ①两侧都记录 `\|Vdiff\|`；②控制面同一（`intop5==swr1==efc1` 且 `area_ptot`/bbox 唯一）；③网格上界同一（本批 `fmax = 35 MHz`）；④几何族/选择语义可比且 `model_sha256` 不得混用 |
| `Vave_norm = Vave/\|Vdiff\|` | 同上四条；且 `Vave` 只能称「面平均法向速度（响应量）」，**不得**称往返/脉冲回波/阵列带宽 |

### 6.2 **不可**跨驱动比较（硬禁止）

| 量 | 依据 |
|---|---|
| `Ptot`（原始 W） | LT3-D 明文：legacy 约 1 V 单端 vs 反相 `±1 V`（`Vdiff=2 V`），电压口径不同；**约 4 倍功率差是驱动电压造成的，不是结构收益** |
| `Vave`（原始 m/s） | 同上，缺 `\|Vdiff\|` 归一，幅值不可直接并列 |
| `Zin1_*/Zin2_*/I_*`（电气量） | LT0-C 实测 KCL 相对误差 16.6–18.9% > 1% 门槛 ⇒ 电气指标整体排除，**既不参与排名也不参与跨驱动比较** |
| 反相 vs legacy 的绝对电平差 | 红线 4（来源永不混同）：两批 `model_sha256` 不同（legacy `0f75ca1d…` vs 反相 `cbe9ccc1…`），只能**并排对照**，不得合并统计 |

### 6.3 本批的**实际**答案（重要）

本批是 legacy 导出且**未记录 `Vdiff`** ⇒ `Ptot_norm` / `Vave_norm` **都不可能算**（产物中留空，
不填推测值）。因此**本批与未来反相批之间，目前没有任何一个已记录的归一化量可用于量化对照**；
`legacy_vs_reverse_normalized` 对照表在 legacy 侧**补记录 `Vdiff` 之前无法成立**。
这一点必须在 LT2 数据到位前解决，否则 LT3-D 的对照要求无法满足。

---

## 7. 已实现 / 未验证 / 已知风险

### 7.1 已实现（本机实测，exit 0 / 3 / 2 均可复现）

| 项 | 说明 |
|---|---|
| 数据质量检查 | 唯一键/重复键/缺失键/多余键、每组合频点数一致性、空值/NaN/Inf/不可解析复数、负 `Ptot`、频率递增、驱动失配、`Zin1≡Zin2` |
| 指标物理分离 | **声学**（`Ptot`/`Vave`/`V_center`）与**被排除电气**（`Zin1_R/X`、`Zin2_R/X`、`I_*`、`I01/I02`）在数据结构上分离；被排除项**不进入**任何排名/Pareto 池，且 `--pareto-metrics` 若传入 `Zin*`/`I_*` 会**直接报错退出** |
| Pareto 前沿 + 支配关系 | 两个声学指标、最大化、仅 eligible 子集；输出 `pareto_front`、`dominated_by_count`、`dominated_by`，并另出逐对 `lt3_pareto_dominance.csv` |
| 多指标排名表 | `lt3_ranking.csv`：`Ptot@20MHz`、`Vave@20MHz`、`Ptot_peak`、`Vave_peak` **各自独立排名**（名次 1 = 该指标最大），并带 `pareto_front`/`dominated_by_count`；**明确不合成加权总分**（`composite_score = false`） |
| 归一化契约 | `normalization_contract()` 固化两套驱动的公式、可得性、可/不可跨驱动比较清单及各自依据 |
| formal-ranking 守卫 | `FORMAL_RANKING_AUTHORIZED = False` 常量 + `--formal` 硬拒绝（exit 2）+ 反相数据 fail-closed（exit 3）+ legacy 数据每行强制 `drive_mode = legacy_1ohm_to_reference`、`status = provisional_legacy_not_formal`、`formal_ranking = False` |
| 溯源 | 每行带 `source_run_id` + `source_file_sha256`；质检报告引用工单文档 sha256；`lt3_manifest.json` 记录全部产物 sha256；输入自动复制到 `work\lt3\inputs\` 并复核 sha256 相等 |
| 防误写 | `--out-dir` 若位于 `work\runs\` 之下一律拒绝（exit 2），已实测 |
| 复用既有口径 | 复用 `analyze_sweep.py` 的 dB 规则、−6 dB 插值规则、预检 gate、无加权总分原则、`parse_complex`、编码级联读表 |
| 无 COMSOL 依赖 | 纯标准库（`csv/json/hashlib/math/re/shutil/sys/zipfile/xml`），不 import numpy/matplotlib，不调用 COMSOL |

### 7.2 未验证（明确列出，未填推测值）

| 项 | 状态 |
|---|---|
| 反相驱动 504 点数据的端到端跑通 | **未验证**——数据不存在（LT2 = `BLOCKED_BEFORE_PRODUCTION`）。仅用 LT1 15 点验证了守卫路径；`Ptot_norm`/`Vave_norm` 的正向计算路径**尚未在真实反相数据上跑过** |
| 驱动口径判定 | **未验证**——由导出列结构**启发式推断**，不是 COMSOL 模型读数（红线 3）。若与模型实际不符，本报告结论作废 |
| legacy 的 `Vdiff` | **未验证/未知**——导出未记录，本轮未做任何反推 |
| −6 dB 带宽 / `FBW` / 上下交点 / 平坦度 / `Ptot/Vave` 峰值 | **未实现**（属 LT3-B，本轮范围外），已列入 `not_verified` |
| 7R 轴向声压 `H_p(f)=|p(f,0,0,7R)|/|V|` | **未计算**（需 COMSOL，本机当前处于 no-COMSOL 窗口） |
| 网格收敛 / 单元数与指标的关系 | **未验证**——level-2 预检 `mesh_element_count` 106,212–157,390，未做收敛性分析 |
| 插值取值的精度 | **未验证**——`Ptot@20 MHz`/`Vave@20 MHz` 在 5 MHz 步长下为**采样点命中**（20 MHz 是采样点，`interpolated = False`），但 15/25 MHz 等仍属粗网格 |
| 批次2 所用 7.93 GB `.mph` 的身份 | **未验证**——`freeze_inputs.json` 记 `sha256: null`（当时带 `.mph.lock`），按 SOP 不取哈希 |
| 反相批的 `intop5/swr1/efc1` 控制面一致性 | **未验证**（无数据）；legacy 批已由 level-2 聚合验证：`area_ptot` 唯一值 1 个、bbox 唯一 1 个、`intop5_eq_swr1_all/efc1_all = true` |

### 7.3 已知风险

| 风险 | 影响与缓解 |
|---|---|
| Pareto 前沿在 `Ptot@20MHz × Vave@20MHz` 上**退化为 1 点** | 该指标对无权衡信息；LT3-C 候选角色须改用带宽/平坦度指标。已在本报告显式声明，**不得**把单点前沿解读为「该组合全面最优」 |
| 驱动口径靠列结构推断 | 若未来反相导出恰好只含 `Zin*` 而无 `Vdiff`，会被误判为 legacy ⇒ 建议反相导出**必须**带 `Vdiff_abs`/`V_outer`/`V_inner` 列；缓解手段是 `--drive-mode` 显式声明 + 声明/推断矛盾时 fail-closed（已实现） |
| legacy 无 `Vdiff` ⇒ LT3-D 对照不可完成 | 需在反相数据到位前，决定是否为 legacy 侧补记录 `Vdiff`（或正式声明「对照不可行」并写入报告限制） |
| 预检只覆盖 `N_w_te1 ≤ 8` | 批次2 数据的 162 组里有 90 组（`N1 = 9…18`）为 `design_region_reversed`，一律不参与排名；若要评价这些组合需先修选择集 |
| 5 MHz 频率步长 | −6 dB 交点为插值估计，**仅为粗筛**；峰值顶在 35 MHz 上边界的组合不得解释为「带宽无限」 |
| 单元模型结论不可外推 | 单 PMUT 单元模型的 `Ptot`/`Vave` 结论**不得**外推为阵列性能 |
| 控制台编码 | 中文 stdout 在 GBK 控制台显示为乱码（已设 `errors="replace"`，**不中断管线**）；文件内容为正确 UTF-8，核验须用 Python 而非 `Get-Content`（`AGENTS.md` §3） |

---

## 8. 交付声明

- 本轮**未运行** COMSOL / `comsolbatch` / `mphserver`；
- **未写入 `work\runs\`** 下任何内容（脚本内置 `--out-dir` 拒绝逻辑，已实测 exit 2）；
- **未修改**任何禁改文件（`lt2_production.py`、`lt2_sampler.py`、`tests_lt2_supervisor.py`、`rt_gate.py`、
  `tests_rt_gate.py`、`lt2r0_v2.py`、`lt2_acceptance_r4.py`、`lt2_flake_hunt.py`、`check_undefined_names.py`、
  `freeze_snapshot.py`、`check_r3_conditions.py`、`AGENTS.md`、`WORKING_PLAN.md`）；
- **未运行** `tests_lt2_supervisor.py` / `lt2_acceptance_r4.py` / `tests_rt_gate.py`；**未使用 pytest**；
- 产物**只写在 `work\lt3\`** 与 `docs\TO_CODEX_record-20260914-lt3-prep-pipeline.md`；
- 用户原始导出与生产模型**只读**（复制到 `work\lt3\inputs\` 后处理，复制后 sha256 复核相等）。

---

## 附：后继更正（2026-09-14，**append-only**，不覆盖上文）

> 依据 `AGENTS.md` 红线 6（历史 append-only）：本附录只**新增**，不删改上文任何内容。
> 上文记录的是**第一次跑通**（`lt3_prep.py` sha256 `c5e6923593d6e996…`）时的产物哈希；
> 其后收到用户人反馈（legacy `|Vdiff| ≈ 1 V`）并据此扩展了管线，
> **下列产物已被重新生成、哈希失效**，最新哈希见后继记录：
> `docs\TO_CODEX_record-20260914-lt3d-legacy-vs-reverse-normalized.md`。

### 被取代的产物哈希（旧值 → 已失效）

| 产物 | 旧 sha256（上文所记，已失效） | 新 sha256 |
|---|---|---|
| `work\lt3\lt3_quality_report.json` | `06e89dd9a7def86c…` | `240b851966d3e2bafb0b6d2168f3c9116c2a9e89c09601226ee49c7f741e9dc2` |
| `work\lt3\lt3_metrics.csv` | `6681c70e5a0a1d56…` | `e5321a297ba8ba40d725c7f50a1f73276a61f249a06a1eb3a5af2c47cf100e0a` |
| `work\lt3\lt3_pareto.csv` | `d9de7cb749b87080…` | `b70ab0765f7e676f84829c0613a6a16f6f3d6a3573281af3de5aee28d54116bf` |
| `work\lt3\lt3_normalization_contract.md` | `b6e7bcc6ae918f51…` | `f03289d71c67e5e1259649ae4e7c6059a7e30a34f579ccd99698845b4b756fc2` |
| `work\lt3\lt3_manifest.json` | `46495a92685d11af…` | `f879de53f8c4ba9ead608888ddd60b1c791568a2ea8149c57ca44426486bfd80` |
| `work\tools\lt3_prep.py` | `c5e6923593d6e996…` | `566320b07c70987788c9f6bd2889dc85ebdbfd8779af33d355a2fef6251f6c31` |
| `work\lt3\_guard_test_reverse\*` | 见上文 §2.2 | 见后继记录 §3.2 |

**哈希未变**（仍可用）：`work\lt3\lt3_ranking.csv` `76d5315c81c5469b…`、
`work\lt3\lt3_pareto_dominance.csv` `db139d6ccaf88f07…`、
`work\lt3\lt3_ranking_status.json` `f338ff9e6c8557a5…`、
`work\lt3\inputs\扫描阵列Xrange(0.4,0.05,0.8).xlsx` `33ed711c8d53bf02…`、
`work\lt3\inputs\geometry_selection_precheck.json` `b26193fea3f56a6e…`。

### 导致变更的两处真实缺陷修复

1. **频率单位混用**：批次2 列为 `freq (Hz)`、LT1 反相表为 `freq_MHz`；旧版一律按 Hz 处理
   ⇒ 跨批 join 全部失败。已加 `freq_scale_to_hz()`（按列名判定，无单位时启发式并留痕）。
2. **预检记录合并优先级**：旧版 `phase2 → phase1` 载入顺序使 phase1 覆盖 phase2，
   丢失 `intop5_eq_swr1/efc1`、bbox 等控制面证据。已改为 `phase1 → phase2`。

另：旧版把 `legacy_export_lacks_Vdiff__normalization_not_computable` 记为**不可计算**；
该判定现已按**人反馈**（`fb-20260914-legacy-drive-amplitude`）解除，
但**来源必须标注为 `human_feedback`**，见后继记录 §1/§4。

---

## 附二：后继更正（2026-09-14，**append-only**，不覆盖上文与附一）

> 依据 `AGENTS.md` 红线 6：本附录只**新增**。
> 其后补齐了 LT3-B 频响形状类指标（−6 dB 带宽 / FBW / 带内平坦度 / 带宽交叠 / 峰值峰位 / 比值峰）
> 并重算了 4 个指标对的 Pareto。最新记录：
> `docs\TO_CODEX_record-20260914-lt3b-response-metrics.md`。

**再次被取代的哈希**：

| 产物 | 附一所记 | 最新 |
|---|---|---|
| `work\tools\lt3_prep.py` | `566320b07c709877…` | `0af7b4d70817e2c4f1ec6a7efd71cbba11e2b5c7449fb02ce8b845cfe8393248`（127,547 B） |
| `work\lt3\lt3_metrics.csv` | `e5321a297ba8ba40…` | `fa2aff7b9689d3e80ac15c4cdfab6d298cf06ae4eeb9342b2341da05640aba20` |
| `work\lt3\lt3_quality_report.json` | `240b851966d3e2ba…` | `74e58fa88d4d658ffa8a65db796e4437ddd1812e05e1918fc7157bf39fc83322` |
| `work\lt3\lt3_pareto.csv` | `b70ab0765f7e676f…` | `6ae6f9f5b84180260b3772650a1b324a9f9c9296a739de8ee745d7cfe27b5bbe` |
| `work\lt3\lt3_normalization_contract.md` | `f03289d71c67e5e1…` | `946b37515f7fb4b8be9d3bf3cb3cf11a0eba4c64488b779789799ad24aeea9bc` |
| `work\lt3\lt3_manifest.json` | `46495a92685d11af…` | `2be7e4977d7819caad305a06d3b3aa429225125d2d9b06980935315de6c21b87` |

**新增产物**：`work\lt3\lt3_response_metrics.csv`（162×88，`e5eb535a8ceaefeb…`）、
`work\lt3\lt3_response_metrics_contract.md`（`c1d8542947d4e37c…`）、
`work\lt3\lt3_pareto_pairs.csv`（116×19，`6027f07629211722…`）。

**哈希未变**：`lt3_ranking.csv`、`lt3_pareto_dominance.csv`、`lt3_ranking_status.json`、
`legacy_vs_reverse_normalized.csv`、`lt3_legacy_vs_reverse_normalized.md`、`work\lt3\inputs\*`。

**本文件 §7.2「未验证」中「−6 dB 带宽 / FBW / 上下交点 / 平坦度 / `Ptot/Vave` 峰值：未实现」
一条现已部分实现**：这些指标**已实现**并已独立复算验证（162 组合 × 12 量 = 1944 值，0 处不一致）；
**7R 轴向声压仍需 COMSOL，仍未实现**。
本文件 §4/§5/§6 的**结论全部不变**（批次2 legacy 质检数字、`Ptot@20MHz × Vave@20MHz` 单点退化、
legacy 归一化不可计算的原判随后由人反馈解除）。


