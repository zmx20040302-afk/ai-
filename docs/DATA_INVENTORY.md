# 现有数据清单（DATA INVENTORY）

> 生成时间：2026-09-23。**所有数字都在本机实测**（只读查询 `work/store/mems.duckdb` + 直接读文件），
> 每项都标了可复现的来源路径与哈希。**没有的项单独列在 §7**——不要拿"计划中"当"已有"。
> 本文件只描述**已有数据**，不含结论；结论分别见 `A5_RESULT.md`、`A6_*_CONCLUSIONS.md`。

## 0. 一句话

真正能用于 PMUT 建模的**只有两批真实仿真数据**（A：新族 `cell_te2_*`，223 组合；
B：旧机 GUI 扫描 70 组合）＋ 一批**纯解析基准夹具**（423 条，用来验证平台本身）。
**没有实验数据、没有文献证据、没有场级数据、没有一条 PMUT 的网格收敛(L1)通过记录。**

---

## 1. 数据 A（主体）：`cell_te2_*` 远端导出扫描

**位置**：`work/runs/remote-exported-20260922/`
**来源**：远端服务器 `ubuntu-10-180-7-46:/home/lab/projAI4US/autodesign/exported_results`（**只读**）
**搬运**：ssh+tar/scp → 本地镜像 `mirror/`（269 文件 / 31.13 MB），**269/269 文件 sha256 与远端逐一一致**
（`verify_mirror.py`，清单 `remote_sha256.txt`）
**来源类型**：`source_type = simulation`；**fidelity = F3**（COMSOL 6.4.0.293 全阶频域）
**模型族**：`cell_te2_<N_w_te2>_v1`（**单胞**，与 `b_GE_task3_2new` 是**不同族，禁止混池**）
**导出链**：MATLAB LiveLink + COMSOL Server，作业 `PmutResultExportJob1`

| 项 | 实测值 |
|---|---|
| run 目录 | **23**（22 完整 + 1 个未完成的 `cell_te2_9_test_v1` 批次） |
| 参数组合 | **223** |
| 频点 | **61 点 / 5–35 MHz / 步长 0.5 MHz**（每个参数块内严格升序，`freq_grid_ok=true`） |
| 数据行 | **13,603** 行 × 3 张表（points / power / mech） |
| 参数覆盖 | `x_scale ∈ 0.1…1.0`（12 个值）、`N_w_te1 ∈ 1…7`、`N_w_te2 ∈ {3,4,6,7,8,9}`；**全部 `N1 < N2`** |

**三张表**（`dataset/*.csv`）：
- `points.csv`（13,603×15）：`x_scale, N_w_te1, N_w_te2, freq_Hz, v_tz_re/im, c_tz_cplx, p_re, p_im, p_abs_Pa` …
- `power.csv`（13,603×11）：`p_total_N, p_total_im, v_z_m3s, vv, pv_W_re/im` …
- `mech.csv`（13,603×11）：`disp_z_m, v_z_m3s, w_re_m, w_im_m, src, point_z_m` …
- `combos.csv`（**223 行 × 23 列**）：每组合一行，含 `spl_max_dB, f_peak_Hz, n_local_maxima, f_low/high_3dB_Hz, bandwidth_3dB_Hz, q_from_points, flags` …

**口径（必须随数一起引用，否则数字无意义）**：
- 判据点实测为 **(0,0,−10 µm)**；**双方裁定的判据是 −100 µm** ⇒ 本批 SPL **不得**标注为 100 µm 判据。
- `SPL[dB] = 20·log10(|p|/√2/20µPa)`，`|p|` 取复声压模（已数值验证）。
- `总声压` 列是**复数字符串**（`a+bi`）；`_test_scal_*` 与 `_test_xscal_*` 两种写法**都指 `x_scale`**。

**数据质量旗标（223 组合上的计数，不是"少量异常"）**：

| 旗标 | 条数 | 含义 / 后果 |
|---|---|---|
| `exporter_warning_cutoff_at_endpoint` | 218 | 导出器告警：−3 dB 截止点落在扫描端点 |
| `exporter_warning_peak_at_boundary` | 193 | 导出器告警：峰在扫描边界，宽度可能被截断 |
| `exporter_warning_marker_pairing_ambiguous` | 190 | 标记行数与"每峰两截断点"不符 |
| `marker_table_not_attributable` | 190 | `Bandwidth.txt` 无参数列、行数与组合不成比例 ⇒ **无法归属，本数据集不用它** |
| `bandwidth_not_closed` | 93 | 两侧 −3 dB 交点未同时落在范围内 ⇒ 带宽/Q 不可用 |
| `peak_at_range_edge` | 80 | SPL 最大值落 35 MHz 端点 |
| `marker_peak_mismatch` | 33 | 仅在可归属的子集里比较，仍不一致（33/33） |

⇒ **带宽可用的组合只有 130 个**（中位带宽 4.65 MHz，中位 Q 3.13）。**峰位置有 80/223 顶在扫描上界**，
不是"测量到了 35 MHz 谐振"，是**扫描窗口不够**。

**派生分析层**（同一目录下，均由上面这批数据算出）：
- `a5/`：`metric_table.csv`、`candidate_grid.json`、`scan_analysis.json|.md`、`A5_RESULT.md` —— A5 分族分指标排名（**整体 inconclusive**）。
- `a6/`：三轮预注册评估（`a6_round2/3_result.json`、各轮 `CONCLUSIONS.md`）、方差分解、
  `first_mode_distribution.json`（一阶峰统计）、`X_DENSIFY_PLAN.json|md`（x 加密选点清单，**只出清单不求解**）、`prereg_registry.json`（seq 1–4，append-only）。
- `store_ingest_report.json`：入库幂等复核（22 runs / 223 samples / 277 artifacts **noop**，0 conflict）。
- `bundle_platform.json` / `bundle_pmut_session.json`：A9 报告输入；`report_platform/`、`report_pmut_session/`：报告产物。

---

## 2. 数据 B：旧机 GUI 参数扫描（目标器件本体）

**位置**：`work/runs/gui-sweep-20260912T113936Z-bd387a56/`
**来源**：用户在 COMSOL GUI 里 `model.batch('p1')` 跑的扫描，导出"全局计算"表后入库
（**不是平台队列执行**，`pathway = comsol-gui-batch`，`provenance.json` 留档）
**被扫模型**：`b_GE_task3_2-newyizu.mph`（4.25 GB，sha256 `a9a177ad…`）
**表格**：`source_table.csv`（sha256 `0a49d5a1…`）＋ `.xlsx`

| 项 | 实测值 |
|---|---|
| 数据行 | **490** = **70 组合** × **7 频点** |
| `x_scale` | 10 个值：0.1, 0.2, …, 1.0 |
| `N_w_te1` | 7 个值：1, 2, 3, 4, 5, 6, **8**（⚠️ **缺 7**） |
| 频点 | 5, 10, 15, 20, 25, 30, 35 MHz（**粗网格，5 MHz 步长**） |
| 输出 | `Ptot (W)`、`Zin1_R/X`、`Zin2_R/X`、`Vave (m/s)`、`V_center (m/s)` |
| **没有** | **无 SPL / 无声压**（与数据 A 的输出集**不重叠**，不能替代 A） |

**两个解析陷阱（已实测）**：
1. 表头第一格是 `% x_scale`（COMSOL 导出带 `% ` 前缀），照 `x_scale` 取列会 `KeyError`；
   且文件前 4 行是元信息，第 5 行才是表头。
2. `V_center (m/s)` 是**复数字符串**（如 `0.03967-0.06814i`），直接 `float()` 会失败。

---

## 3. 元数据库现状（`work/store/mems.duckdb`，15.3 MB）

| 表 | 行数 | 说明 |
|---|---|---|
| `run` | **132** | 其中 `cell_te2` 22；按 pathway：comsolbatch 94 / livelink 22 / mph-client 15 / gui-batch 1；按 status：succeeded 82 / failed 34 / cancelled 13 / queued 3 |
| `sample` | **1185** | `source_type`：**simulation 762 / analytic 423**（**无 experiment / literature / ai_solver**） |
| `design` | **586** | analytic 400 / simulation 186 |
| `artifact` | **1297** | json 380 / log 369 / txt 134 / mat 132 / model_source 125 / mph 96 / csv 4 / md 1 |
| `dataset` | **2** | 见下 |
| `model` | **3** | **全部 `mlp_ensemble`、`state=draft`、`approved_by=None`** |
| `prediction` | **0** | 无任何已登记 AI 预测 |
| `validation` | **11** | **全部 L1**；10 条 `passed=false`（queued/failed/running），**唯一 1 条 passed 是 `heat_slab_2d` 玩具模板**（其自身 caveat 写明"不能替代非线性模型的网格收敛研究"） |
| `evidence` | **0** | **无文献证据** |
| `experiment` | **0** | **无实验数据** |
| `feedback` | **3** | 全部是用户对 `b_GE_task3_2-new.mph` 参数的裁定（见下） |
| `task` | 0 | 未使用 |

**样本按几何族分布（`sample ⋈ design`）**——看清"1185 条"里到底有什么：

| 几何族 | source_type | 样本数 | 是什么 |
|---|---|---|---|
| `GF-pmut-ge-task3-oval` | simulation | **490** | **数据 B**（旧机 GUI 扫描，70 设计） |
| `cell_te2_N28/N27/N26/N24/N23/N29` | simulation | 70/60/45/27/20/1 = **223** | **数据 A**（新族） |
| `GF-heat-slab-2d` | analytic | 108 | 解析基准（平台自测夹具） |
| `GF-cantilever-beam` | analytic | 100 | 同上 |
| `GF-plate-thickness-mode` | analytic | 100 | 同上 |
| `GF-resonator-thermal-noise` | analytic | 100 | 同上 |
| `GF-cantilever-beam-2d` | analytic | 15 | 同上 |
| `GF-heat-slab-2d` | simulation | 17 | 早期平台通路验证（与器件无关） |
| `GF-cantilever-beam-2d` | simulation | 32 | 同上 |

⇒ **423 条 analytic + 49 条玩具仿真 = 472 条与 PMUT 无关**（都是"证明平台能跑通/算得对"的夹具）。

**两个 dataset 记录**：
- `ds-20260911T014216Z-42bf22`：`train`，420 样本，`bootstrap`（玩具问题）。
- `ds-cellte2-exported-20260922`：`analysis`，**223 样本**（已逐一核对：223 个 id 全部存在于 `sample` 表，且全部是 `cell_te2`），
  其 `report` 明写：**"不得直接当训练/评估集使用；若用于 A6 训练，必须先按 geometry_family 整族留出"**。

**3 条人反馈（`feedback`，全部 append-only 留档）**：
`b_GE_task3_2-new.mph:fmax = 35 MHz`（.m 历史值 20/30/35，末次 35 生效）、
`v0` 为激励接入方式（`pot1.V0=+v0, pot2.V0=−v0`）、`N_w_te2 = 9` 保持不改。

---

## 4. 模型与器件副本（磁盘，**不是数据**，但决定能算什么）

| 位置 | 大小 | 内容 |
|---|---|---|
| `work/devices/` | 16 文件 / **1.19 GB** | **12 份 `b_GE_task3_2_*new.mph` 只读工作副本**（每份 98.88 MB；probe / baseline / precheck-sentinel / audit / phase1-2 等各一份），另有 `acoustic-cavity-2d-pilot/` |
| `work/models/` | 466 文件 / **340 MB** | 3 个**变体模型**：`b_GE_task3_2new_reverse_voltage_drive_v1.mph`(132 MB)、`..._currentdrive_fmax45_v1.mph`、`..._legacy_1ohm_drive_v1.mph`；3 个 `model.joblib`（MLP，各 0.74 MB）；`bGEtask2` 的 `.m` 解析与审计产物 |
| `work/ai-solver/` | 114 文件 / **89 MB** | step4/step5 的 CV 与保形校准产物：`cv_detail.csv`(25–30 MB)、`conformal_scores.csv`(14.8 MB)、`models_frozen.json`、`lt3_metrics.csv`、以及用户给的 `扫描阵列Xrange(0.4,0.05,0.8).xlsx` |
| `work/lt3/` | 52 文件 / 6.7 MB | L3 Pareto / 指标 CSV（含 `_v1_band35_preserved`、`_demo_band45` 两个变体目录） |
| `work/exports/` | 3 文件 / ~30 KB | 场级试点：`pod_points.txt`、`p1_snapshots.npz`、`p1_grid_export.csv`（**体量极小，仅通路验证**） |
| `work/reports/` | 363 文件 / 17.1 MB | 历次报告（含 `mems-dashboard/` 静态看板） |
| `work/runs/` | 29,681 文件 / **16.8 GB** | ⚠️ **绝大多数是平台自身的测试/演练/验收 run**（`lt2-*`、`iso-*`、`probe-*`、`_evidence-*`），**不是器件数据**；真正的器件数据只有 §1、§2 两处 |

---

## 5. 平台自身产出的"能否被信任"的证据

- **A8 冻结门禁 / A9 报告门禁**：代码 + schema 在 `src/memsharness/{freeze_gate,report_augment}.py`、`schemas/`；
  已对 `report_platform/`、`report_pmut_session/` 出过报告（含 `gate_binding` 与溯源检查）。
- **回归**：`tests/` 全仓 **388 passed / 4 skipped**（离线，不含真实 COMSOL 求解）。
- **一阶谐振统计**（数据 A）：`n_total=223`、有内部一阶峰的 **161**、**中位 9.5 MHz**、
  直方图 `{5-10:92, 10-15:23, 15-20:23, 20-25:0, 25-30:23}`、**落在 18–22 MHz 的只有 3 个**
  ⇒ **一阶谐振不在 20 MHz 附近**；20 MHz 是**设计工作频率**，不是谐振点。
  产物 `first_mode_distribution.json@7398593ff6`。

---

## 6. 复现入口（点一下就能重跑，且都带哈希）

| 想做什么 | 命令 |
|---|---|
| 校验本地镜像与远端一致 | `python -B work/runs/remote-exported-20260922/verify_mirror.py`（或网页控制台 `verify_mirror`） |
| 从镜像重解析数据集 | `python -B work/runs/remote-exported-20260922/ingest_exported_results.py` |
| 重新排名（A5） | `python -B scripts/run_sweep_analysis.py --preset cell_te2-exported …` |
| 一阶峰统计 | `python -B work/runs/remote-exported-20260922/a6/first_mode_distribution.py` |
| x 加密选点清单 | `python -B work/runs/remote-exported-20260922/a6/x_densify_plan.py` |
| 对话式网页（14 个功能） | `http://127.0.0.1:8877/` |
| 元数据库行数 | MCP `data_stats` / 网页 `state` |

---

## 7. **明确没有的东西**（不要假设存在）

1. **实验数据：0 条**（`experiment=0`）。任何"仿真 vs 实验"的偏差结论目前都**无法给**。
2. **文献证据：0 条**（`evidence=0`）。没有带页码与原文摘录的文献数值。
3. **场级数据：没有**。数据 A/B 都是**标量导出**（点值/全局量）；`work/exports/` 只有几十 KB 的通路试点。
   ⇒ 场级相对 L2、S1 级验证**无数据基础**。
4. **PMUT 的网格收敛（L1）：不通过**。唯一 `passed=true` 的是 `heat_slab_2d` 玩具模板（线性场，其 caveat 自认不可外推）。
   ⇒ 按红线第 2 条，**目前只能谈趋势，不能输出用于工程判断的绝对值**。
5. **已放行的 AI 模型：0 个**。3 个 `model` 记录全是 `draft`、`approved_by=None`，且训练用的是玩具热板 `T_max_K`，**与 PMUT 无关**。
6. **AI 预测记录：0 条**（`prediction=0`）。
7. **超出扫描窗口的信息**：35 MHz 以上没测（80 个组合的峰顶在边界上）；数据 A 的判据点是 −10 µm 而非裁定的 −100 µm。
8. **未完成的 run**：`cell_te2_9_test_v1`（1 组合）批次目录存在但无完整产物，未入库。
9. **数据 B 缺 `N_w_te1 = 7`**，且频点只有 7 个（5 MHz 步长）⇒ 与数据 A **不可直接拼接**（族不同、输出不同、频网格不同）。

---

## 8. 使用这批数据的三条硬约束（来自仓库红线，非建议）

1. **族不得混**：`cell_te2_*`、`b_GE_task3_2new`（yizu/oval）是不同族，**禁止跨族合并排名或训练**。
2. **来源不得混**：`simulation` / `analytic` / `experiment` / `literature` / `ai_solver` 各自独立 `source_type`；
   当前库里前两者存在，后三者**为空**，不得用前者冒充后者。
3. **越界即拒答**：AI 求解只在已声明范围内出解，超出范围必须拒答并回退 COMSOL；
   物理一致性检查不通过的解**哪怕与数据吻合也作废**。

---

## 9. 2026-09-29 更新（本文件 §1–§8 写于 09-23，**其后新增了数据与分析产物**）

> 追加而非改写（原节保留）。**§7 有两条需要更正**，见 §9.3。

### 9.1 新增数据（相对 09-23）

| 项 | 内容 | 证据 |
|---|---|---|
| **批 C 补齐 N2=8** | `C_v20260929` = N2∈{5,6,7}（1215 组合）+ **N2=8（567 组合）** = **1782 组合**，5–50 MHz / 91 点 | `work/runs/n2-8-intake-20260929/raw`；镜像校验 12/12 `passed` |
| 数据版本不可变化 | `C_v20260928` → `C_v20260929`；**旧结论对旧快照仍有效**，新批先作**锁定外部增量测试** | `work/runs/x-densify-20260928/data_versions/` |
| 隔离台账 | `QUARANTINE_AMENDMENTS.jsonl`（**3 行**，append-only） | 见 §9.2 |

### 9.2 新增分析产物（全部可复算，带哈希）

| 产物 | 字节 | sha256(前16) |
|---|---|---|
| `work/runs/first-peak-20260929/multichannel_labels.csv`（**2005 行 × 64 列**，A+C 并排不覆盖） | 1,957,249 | `d06edfe199943499` |
| `work/runs/first-peak-20260929/first_peak_metrics.csv`（1612 行 × 48 列） | 1,490,696 | `dc4d6ae16ffdbddf` |
| `work/runs/first-peak-20260929/bw_method_validation.json`（带宽方法外部对照） | 72,472 | `e84720a28975c41e` |
| `work/runs/first-peak-20260929/stage1_request.json`（Stage-1 探测请求，**待数据侧执行**） | 15,927 | `a46ca3ac3cf208d5` |
| `work/runs/x-densify-20260928/a6/CROSS_BATCH_CONSISTENCY_R-CB-N28.md`（裁定 §7 固定 5 项，**本轮新增**） | 1,998 | `0c8ef6b8e31b4856` |
| `work/runs/x-densify-20260928/a6/cross_batch_consistency_R-CB-N28.json` | 3,857 | `f9fc1625bdb2333f` |
| `work/runs/x-densify-20260928/a6/per_combo_R-CB-N28.csv`（**逐组合误差排名，此前完全缺失**，63 行） | 6,995 | `fca08628437efe4b` |
| `work/runs/x-densify-20260928/data_versions/QUARANTINE_AMENDMENTS.jsonl` | 4,032 | `f1227fac88496346` |

### 9.3 ⚠️ 对 §7 的**两条更正**（原条不过删，以此为准）

* **§7 第 3 条「场级数据：没有」——不准确，应更正为：**
  **在当前 PMUT 设计空间（批 A / 批 C）没有场数据**，但磁盘上**存在 57 个 phase0 场快照**
  （`work/runs/phase0-field-holdout-20260915/exports/**/*.npz`，每个含 **35,301 点**、
  复声压 `f00_p_abs/re/im`），**限制是：只有 20 MHz 一个频点，且是旧 phase0 参数网格**。
  更重要的是：**S1 级场误差评估已经做过，结论是失败**——
  `s1-field-eval-20260915/S1_RESULT_result.json`：全局 max **9.18** vs 门槛 **0.05**、
  关键区 max **8.91** vs **0.02**，两项 `passed=false`；S3-A 亦失败（最差 R=0.232 vs 0.05）。
  ⇒ 「场级相对 L2、S1 级验证**无数据基础**」这句话对**当前数据**成立，
  但**不要说成"从来没有过场数据"**，也不要用这批快照暗示"接近求解器"。
  **用户 2026-09-29 指示：场级解这条线先不做。**
* **§7 第 8 条「`cell_te2_9_test_v1` 未入库」——仍然成立**：N2=9 数据**至今未到**
  （脚本取证：磁盘无任何 N2=9 组合）。Stage-1 双向探测请求已出但**未回**。

### 9.4 仍然没有的（09-23 之后**没有变化**）

实验数据 0、文献证据 0、**PMUT L1 网格收敛仍为 0 条通过**（`validation` 表 11 条 L1 仅 1 条通过，
且是 `heat_slab_2d` 玩具模板）、已放行的 AI 模型 0、AI 预测记录 0。

