# MEMS 平台与 PMUT 一阶峰代理建模：论文材料（交给 Codex 起草用）

> **这份文件是什么**：把当前仓库里**已经做完、可复现**的工作，按"论文写作需要的顺序"讲一遍。
> 目标读者是**起草论文的模型（Codex）**，所以它同时包含：研究问题、系统、数据、方法、**可追溯的结果数字**、
> 负结果、限制、复现命令，以及**明确的写作边界**（哪些能当贡献写、哪些只能写进 limitation、哪些词不许用）。
>
> **证据规则（红线，必须遵守）**：
> 1. 本文件里的**每个数字**都带出处（文件路径 + 必要时 sha256 前 16 位）。起草时若要用某个数字，
>    请连同出处一起保留到论文的"数据可得性/复现"部分。
> 2. **没有出处的数字一个都不许写**。本文件刻意留了「未取到」的位置，那些就是**不要写**的地方。
> 3. 本文件**不是**论文，也**不是**结论：它只是材料。凡是这里标 `draft` / `draft_surrogate` 的模型，
>    论文里**不得**描述成已验证（见 §9.2 禁用清单）。
>
> 全部证据由 `work/tools/collect_paper_evidence.py` 在 2026-09-30 从产物**现取**，
> 摘要输出在 `work/paper_brief/evidence_digest.txt`（本文引用的哈希与它一致）。

---

## 1 一句话概括与研究问题

**一句话**：为"参数化 PMUT（压电微机械超声换能器）阵列的一阶谐振峰性能"建立一条
**从 COMSOL 高保真仿真 → 结构化数据集 → 代理模型（带保形误差界与拒答域）→ fail-closed 验证与冻结**的闭环，
并把这套闭环平台本身当作可复现的工程方法学来报告。

**研究问题（可写进 Abstract 的三问）**：

1. **RQ1（口径）**：一阶谐振峰的性能指标（振幅、−3 dB 带宽、灵敏度、品质因数）在**不同口径**
   （拟合 / 网格点 / marker）下差多少？这个差异会不会改变**排名**结论？
2. **RQ2（可预测性）**：在**只有标量标签、没有场数据**的条件下，一阶峰指标能被代理模型预测到什么程度？
   哪些通道**优于"抄相邻层"基线**（即有真实增值）？哪些**不如基线**（必须明说不增值）？
3. **RQ3（可信边界）**：怎样让"代理给出的数"**自带边界**——误差界、适用范围、超范围**拒答**——
   使得它**不能**被误当作求解器使用？

---

## 2 系统：平台做了什么

平台（仓库 `memsharness`）的设计前提是"**COMSOL 是教师 + 验证器 + 兜底裁判，日常出解由 AI 完成**"，
但在当前阶段，**AI 求解器尚未获得放行**（见 §7），所以论文里应把平台描述为
**"面向该终局的、已实现的数据与验证基础设施"**，而不是"已实现免仿真求解"。

已实现且可用用例锁定的部分：

| 能力 | 实现 | 规模（现取） |
|---|---|---|
| 任务白名单 + 子进程 + 真超时 + 进程树终止 | `scripts/webapp_server.py` | 任务注册表内置超时（`TASK_TIMEOUTS`）；超时**不产出结果** |
| MCP 工具面（供智能体调用） | `src/memsharness/mcp_server.py` | **22** 个 `@mcp.tool`（`sha256=01e1768e9e9ca082`） |
| 数据版本冻结 / 隔离表 append-only 修订 | `scripts/freeze_data_version.py`、`scripts/amend_data_version_quarantine.py` | 版本 `C_v20260929`；隔离裁决 append-only |
| 目录树一致性 / 门禁 | `work/tools/check_report_md.py`（含**数字政策**）、`find_nested_quote_traps.py`、`check_page_ids.py` 等 | 报告类文档 5 份严格档通过 |
| 失败通道（失败 → 可发送分析包，可选一键交给 harness 只读分析） | `src/memsharness/incidents.py`、`src/memsharness/dsh_report.py` | 8 类失败面；密钥入库前脱敏 |
| Web 控制台（离线优先） | `scripts/webapp_server.py` + `scripts/webapp_page.html` | 默认**离线**（不发网络请求）；13 个侧栏分区 |

**平台自身不是本文的科学贡献**，但它是**可复现性的载体**：所有数字都能从平台产物里重新取出。
论文里建议把它写成 "an auditable data-and-validation platform"，并把
**fail-closed** 与 **append-only** 作为方法学主张来写（见 §4.5）。

---

## 3 数据资产（三个批次，全部离线重导）

> 论文里请务必区分三个批次：它们**频段与 x 网格密度不同**，跨批比较必须分层（§6.2）。

| 批次 | 位置 | 规模（现取） | sha256(前16) | 关键性质 |
|---|---|---|---|---|
| **A**（早期导出，粗网格） | `work/runs/remote-exported-20260922/dataset/` | `points.csv` 13603×15；`power.csv` 13603×11；`mech.csv` 27206×16；`combos.csv` 223×24 | `250c2715bf94ead0` / `1f703b97d4b1b139` / `b6e472eb9cf6bac6` / `ad844f8506a3a334` | x 步长 0.1；5–35 MHz；**含自带的两套带宽/Q 口径**（`from_points`、`from_marker`）⇒ 可做外部对照（§5.2） |
| **B**（GUI 扫描导出） | `work/runs/gui-sweep-20260912T113936Z-bd387a56/source_table.csv` | 490 行×10 列（**前 4 行是 `%` 前导**） | `0a49d5a1f0fbe5e2` | **无压力通道**；`N_w_te2` 硬接为 9；列含 `Ptot(Zin1/2_R,X)`、`Vave`、`V_center` ⇒ 只作**跨批电压/速度量级**对照 |
| **C**（当前主数据，细网格） | `C_v20260929`（主标签表见下） | 主标签表 2005 行×64 列 | `d06edfe199943499` | x 步长 0.01；5–50 MHz；**含隔离组合**（`quarantined`）与两套外推标志 |

**主标签表**：`work/runs/first-peak-20260929/multichannel_labels.csv`（**2005 行 × 64 列**，`sha256=d06edfe199943499`）。
其列名（现取，前 24 个）：
`x_scale, N_w_te1, N_w_te2, f_peak_Hz, peak_SPL_dB, peak_displacement_m, f_lo_3dB_Hz, f_hi_3dB_Hz,
bandwidth_Hz, Q_factor, damping_ratio, peak_closed, bandwidth_closed, method, extrapolated,
ranking_eligible, source_model, source_dataset, x_density_class, freq_grid_MHz, n_freq,
first_peak_found, damping_ratio_report_only, q_gate_applicable`。

**首峰指标明细表**：`work/runs/first-peak-20260929/first_peak_metrics.csv`（**1612 行 × 48 列**，`sha256=dc4d6ae16ffdbddf`）。

### 3.1 主标签表现算统计（**n=2005，可直接写进论文**）

* **按 N2（外圈电极对数）**的分层行数：N2=3:20、4:27、**5:324、6:450、7:546、8:637**、9:**1**。
  → 这是**最重要的数据事实**：N2=9 只有 1 个组合 ⇒ 论文里**不能**报告"N2=9 的代理性能"；
  代理对 N2=9 只能做**一步外推**（§4.4）。
* `bandwidth_closed=true`：**1677/2005**（其余 328 行的 −3 dB 交点未闭合，按门禁**不进带宽排名**）。
* `ranking_eligible=true`：**728/2005**。
* **Q 门禁（2.5 ≤ Q ≤ 3.5）通过：728/1677 = 43.4%**（分母是 Q 有定义的行）。
* Q 分布：**p10 = 2.75、p50 = 3.69、p90 = 4.61**（n=1677）。
  → 中位数 3.69 **在门禁带之外**；这解释了为什么通过率只有 43%。论文里这是一个**实质发现**：
  **门禁的紧致程度决定了可用样本量**，而不是"性能差"。
* `quarantined=true`：**4/2005**（2 个组合 × 2 批，见 §6.3）。

---

## 4 方法

### 4.1 一阶峰范式（本文所有指标都取在"第一个内峰"上）

**定义**：在 SPL 频率曲线上取**第一个内部局部极大**（两端不算）作为"一阶峰"；
所有指标都在这个峰上取。这样做的动机：PMUT 的高阶模态与扫频窗口边界会造成多峰，
若各家各自取"最大峰"，跨批/跨口径的对比会失去可比性。

**指标族（都已落进主标签表，列名见 §3）**：

| 族 | 指标 | 单位 | 方向 | 是否参与排名（裁定 §3） |
|---|---|---|---|---|
| 振幅 | `peak_SPL_dB`、`abs_w_m`（中心位移模）、`abs_p_Pa`（判据点声压模）、`abs_vz_struct_m3s`（结构体积速度模） | dB / m / Pa / m³·s⁻¹ | max | **`abs_w_m` 与 `abs_p_per_V_Pa` 是正式目标**；SPL 与体积速度作报告 |
| 带宽 | `f_lo_3dB_Hz`、`f_hi_3dB_Hz`、`bandwidth_Hz`、`Q_factor`、`damping_ratio` | Hz / — | **带宽 max** | **`bandwidth_Hz` 是正式目标**；**Q/ζ 只作门禁**（2.5–3.5），**从不参与排名** |
| 灵敏度 | `abs_p_per_V_Pa` 等每伏量（ΔV = |0 −(−1)| = **1 V**） | Pa/V | max | 正式目标（裁定 §3.3） |
| 约束（只作约束，**永不排名**） | `abs_pv_W`、`abs_stress_zz_N`、`sGp_du_W`、`u_du_m4s2` | W / N / … | min | 裁定 §3.4 |

**关键口径修正（论文里值得作为"方法学教训"写）**：
驱动电压差 **ΔV = 1 V**（内电极 −1 V、外圈 0 V 参考地），**不是**早先误记的 2 V。
因为 ΔV = 1，线性量除以 1、dB 量减 20·log10(1) = 0 dB ⇒ 每伏量的**数值与原始相同**，
但元数据必须留痕（否则"灵敏度"这一列会被误读成"除以 2"）。

### 4.2 度量协议 v2（`metric_protocol_v2`）：**没有加权总分**

协议把误差切成**判定带**与**配对检验**两类，**刻意不做"综合评分"**（A5 规则）：

* 判定带：`pass` 要求 `median ≤ 0.05`（dB/L2 口径）、`p90 ≤ 0.2`（另设 `frac>0.5 ≤ 0.05`）；
  `partial` 允许 `p90 ≤ 0.5`、`frac>1 ≤ 0.05`；另有 `hotspot_max_db = 3.0` 作为**局部热点**标记。
* 配对检验：`win_rate ≥ 0.55`、`p90` 增益 `≥ 0.1 dB`、最差恶化 `≤ 0.5 dB`，bootstrap `n = 10000`、`seed = 0`。
* **`max` 只用来标 `local_hotspot`，不作为判定依据**。
* 误差**地板** `p_floor` 只用**训练集**估计（避免把测试集信息漏进阈值）。

代码：`src/memsharness/metrics_v2.py`（`sha256=1c7cdc47bf40943d`）。

### 4.3 两个代理模型（一个预测频谱，一个预测首峰标量）

**（a）响应级代理**（`work/runs/surrogate-response-20260929/`，`response_surrogate.json` `sha256=1f2803b793300f36`）

| 项 | 值（现取） |
|---|---|
| `model_id` | `a60584b67b510effd9cf122f855d1158861810467ffb22a7b08443261eb176f1` |
| 状态 | `draft_surrogate`（**未放行**） |
| 输出维度 | `target.dim = 93` = 91 个 SPL 频点（5–50 MHz，0.5 MHz 步长） + 标量 `SPL20_dB`、`p20_Pa` |
| 已拟合层 | `n2_fitted = [5, 6, 7, 8]`；`n2_extrap_allowed_max = 9` |
| 其他产物 | `surrogate_model.npz`（1,197,094 B）、`SURROGATE_SPEC.md`、`SURROGATE_REPORT.md`、`fit_response_surrogate.py` |
| 自带声明 | `NOT_a_solver = 「不是 AI 求解器：无场数据 ⇒ S1 场级误差界不可测；无 L1 ⇒ 不给工程绝对值；不得声称等价于 COMSOL；放行权在人」`（原文见 JSON） |

**（b）多通道一阶峰代理**（`work/runs/multichannel-surrogate-20260929/`）

| 项 | 值（现取） |
|---|---|
| `model_id` | `74e5127f77a353ec01bd07520ec6cc34a24d169b3c657de27a55cbf36b301b59` |
| 预注册 | `PREREG_multichannel_surrogate.md` `sha256=e90c315f9ad880423ee4be9c48d531189d4c379bc75d332fd7b13a70e3c63796`（**先注册、后看指标**） |
| 拟合行数 | `n_rows_fit = 1780`；标签 `sha256=d06edfe199943499…`（与 §3 主标签表一致 ⇒ 可核对） |
| 结构 | `in_layer`：固定 (N2,N1) 沿 x 做 **PCHIP 保形插值**，超出该层 x 范围 ⇒ **拒答**；`n2_direction`：固定 (N1,x) 用最近两层**线性外推，只允许 1 步**；空间：正定量取 log10，dB 量取 identity |
| 拒答域 | `alphas = [0.10, 0.05, 0.01]`；`n1` 为整数且 `1 ≤ N1 < N2`；`n2 ∈ [5, 9]` 且最多 1 步外推；`x ∈ [0.20, 1.00]` |
| 排除 | `excluded_quarantine = [[0.2, 1.0, 7.0], [0.2, 1.0, 8.0]]`（隔离组合不进拟合） |
| 自带声明 | `NOT_a_solver = 「只预测一阶峰标量（带宽/振幅/灵敏度等），没有场级误差界、没有 L1 网格收敛 ⇒ 不得用于工程绝对值判断，不得称为免 COMSOL 出解，不得声称等价于 COMSOL」` |

**通道分组（现取自模型 JSON）**：`bandwidth_Hz`（§3.2 带宽，**正式目标**）、
`abs_w_m`（§3.1 振幅，**正式目标**）、`abs_p_per_V_Pa`（§3.3 灵敏度，**正式目标**）、
`abs_p_Pa` / `abs_vz_struct_m3s` / `peak_SPL_dB`（§3.1 振幅，报告）、
`f_peak_Hz`（描述）、`Q_factor`（**门槛，只报告**，`is_formal_objective=false`）。

### 4.4 保形（conformal）误差界与拒答域

多通道代理对**每个通道 × 每个显著性水平**给出**半宽**（`conformal` 字段，现取，单位与通道一致）：

| 通道 | `in_layer` α=0.05 | `in_layer` α=0.01 |
|---|---|---|
| `Q_factor` | 0.03544 | 0.09537 |
| `abs_p_Pa` / `abs_p_per_V_Pa` | 0.007907 | 0.18660 |
| `abs_vz_struct_m3s` | 0.023561 | 0.19872 |
| `abs_w_m` | 0.039646 | 0.15559 |
| `bandwidth_Hz` | 0.039737 | 0.10263 |
| `f_peak_Hz` | 0.017381 | 0.043335 |

**可以直接写进论文的两点**：
1. α 从 0.05 收紧到 0.01 时半宽**放大 2.4–24 倍**（例如 `abs_p_Pa`：0.0079 → 0.1866，约 24×）
   ⇒ **尾部很重**，这是"小样本 + 保形"的必然结果，论文里应当如实报告这个代价，而不是只报 α=0.10。
2. 误差界是**逐模式**给的（`in_layer` vs `n2_extrap`），因为后者是外推、不确定度更大（判定带也另有一套）。

### 4.5 可信性与放行：验证等级、冻结、append-only

论文里建议把这一节写成**方法学主张**（这是本工作与"直接训个模型就报误差"最不同的地方）：

* **验证等级**：L0 解析解、L1 网格收敛、L4 留出集阈值、L5 跨族。
  **没有 L1 就不能谈工程绝对值**（只谈趋势）。当前状态见 §7：**PMUT 自身的 L1 = 0**。
* **冻结（freeze）**：把"被测版本"用 sha256 锁住后再做正式验收；产物哈希、模型 `content_sha256`、
  数据版本 `data_version_sha256`、代码 `code_sha256` 都写进模型 JSON ⇒ 任何结论可定位到具体版本。
* **append-only**：数据修正与隔离裁决**只能新增记录**，不覆盖历史；例如隔离修订走
  `QUARANTINE_AMENDMENTS.jsonl` 追加。
* **fail-closed**：适用范围外**拒答**而不是外推；超时**不产出结果**；门禁不过**不放行**。
  这些在代码里是硬门禁（有用例锁定），不是文档承诺。

---

## 5 结果（每个数字都带出处；请连同出处一起引用）

### 5.1 数据资产的覆盖（现取）

* 主标签表 **2005 行**，覆盖 **N2 ∈ {3,4,5,6,7,8,9}**，其中 N2=5/6/7/8 是主体（324/450/546/637 行）。
* −3 dB 带宽**闭合率 1677/2005 = 83.7%**；其余 328 行**不闭合**（峰贴近窗口边界或只交到一侧）
  ⇒ 这部分**不进带宽排名**（fail-closed）。论文里应把"闭合率"作为**口径质量指标**报告。
* **Q 门禁通过率 43.4%（728/1677）**，Q 中位数 3.69（p10 2.75 / p90 4.61）。

### 5.2 带宽口径一致性：**存在约 20% 的系统偏差**（这是 RQ1 的直接答案）

来源：`work/runs/first-peak-20260929/bw_method_validation.json`（`sha256=e84720a28975c41e`）。
做法：把本文的**单自由度谐振拟合**得到的 BW/Q，与**批 A 自带的两套独立估计**对照；
**先过"同一个峰"闸门**——要求 |A 的 `f_peak` − 本文一阶峰| **≤ 0.5 MHz**，不满足者跳过。

* 总对照：`n_A_combos = 223`，**成功对号 `n_compared = 182`**，**因峰不一致跳过 63**。
  → 论文里必须写这个 63：**约 28% 的组合两套口径连"是哪个峰"都不一致**。
* 与 `from_points`（n=91）：**中位相对差 20.25%**，p90 27.2%，10% 以内仅 11.0%，20% 以内 47.3%；
  Q 中位数：本文 **3.277** vs 参考 **2.715**。
* 与 `from_marker`（n=91）：**中位相对差 19.99%**，但 p90 **88.7%**（尾部极差），
  10% 以内 17.6%，20% 以内 50.5%。
* 原文件 `verdict`（原文）：**「拟合方法与批 A 估计存在系统偏差（中位 20%）⇒ 带宽标签需以批 A 口径为准并说明差异」**。

**可以写成贡献的结论**：带宽这个量**对口径高度敏感**（系统偏差 ~20%，且 28% 的组合连峰都对不上），
因此**排名类结论必须绑定口径**；单看"绝对带宽"跨口径不可比。
⚠️ **不要把 20% 写成"我们的方法更准"**——本对照**不能**判定谁更接近真值（两者都是数值估计，无实验真值）。

### 5.3 跨批重复性（**注意：这不是泛化测试**）

来源：`work/runs/x-densify-20260928/a6/cross_batch_consistency_R-CB-N28.json`（`sha256=f9fc1625bdb2333f`）。

* 折 `R-CB-N28`：**批 A 的 N2=8 ↔ `te2_8` 同坐标**；`is_generalization_test = false`；
  文件内 `nature_note` 原文写的是"同参数跨批（按设计）；**不是泛化测试**，只作重复性/口径一致性检查"。
* `n_train = 63`、`n_test = 63`；协议 `metric_protocol_v2`；数据版本 `C_v20260929`。
* **标量 @20 MHz**：`median = 5.29e-12`、`p90 = 3.99e-4`、`p99 = 0.188`、**`max = 0.493`**、
  `frac>0.5 = 0`（单位：dB 口径，见原文件）。
* **频谱**（n=3843 点）：`median = 7.90e-12`、`p90 = 8.40e-4`、`p99 = 1.114`、**`max = 8.150`**、
  `frac>0.5 = 1.35%`、`frac>1 = 1.09%`、**RMSE = 0.330 dB**、线性幅值 `relL2 = 1.06e-4`。
* **最差组合**：`(x_scale=0.2, N_w_te1=1, N_w_te2=8)`，`|ΔSPL20| = 0.493 dB`。
* 该文件同时**复算了历史折**并记录 `recompute_matches_history = true`、`mismatch = []`
  ⇒ 历史结论**可重算**（这是可复现性的直接证据，论文里值得写一句）。

**诚实提示**：中位数小到 1e-12 说明这批同坐标组合在两次导出间**几乎逐点相同**；
真正的信息在**尾部**（p99/max）与**RMSE 0.330 dB**。论文里不要把 1e-12 当成"模型精度极高"。

### 5.4 全参数扫描的代理表现（多通道，8 通道）

来源：`multichannel_model.json` 的 `evaluation.per_channel`（完整表见该 JSON；下面给**现取**的代表值）。

* `Q_factor`：`n_predicted = 350`、`coverage = 0.732`、`median = 0.00347`、`p90 = 0.0323`、
  **`max = 0.3055`**、`hotspot = true`；
  **`beats_persistence = false`**、`lift_vs_persistence = −0.00099`
  （基线 `baseline_persistence_median = 0.00248`）。
  ⇒ **Q 通道的代理不比"抄相邻层"更好**，甚至略差 ⇒ 论文里**只能**把它写成"门槛/报告量，未获增值"，
  **不能**写成预测成果。这与"Q 从不参与排名"的裁定一致。
* 预注册判定带（`evaluation.bands`）分 `in_layer` 与 `n2_extrap` 两套，
  例如 `in_layer`：`pass = {median 0.004, p90 0.012, frac_gt 0.03, frac_max 0.02}`、
  `partial = {p90 0.03}`、`hotspot = 0.3`；
  `n2_extrap`（外推）：`pass = {median 0.02, p90 0.06, frac_max 0.05, frac_gt 0.1}`、
  `partial = {p90 0.15}`、`hotspot = 0.3`。
  → **判定带是预注册的**（在 `PREREG_multichannel_surrogate.md`，`sha256=e90c315f…`），
  论文里应强调"阈值在看结果之前就定好了"。
* 拒答统计（GUI/接口实测）：一次覆盖 `x∈[0.2,1.0]` 步长 0.05、`N1∈[1,7]`、`N2∈[5,8]` 的网格筛查：
  **网格 476 点，可预测 323 / 拒答 153，覆盖率 67.9%**，模式分布 `{in_layer: 323}`，
  拒答原因 `{x_outside_layer_range: 51, n2_out_of_domain: 1, …}`（完整直方图见 `/api/mc/screen` 输出）。

### 5.5 数据 B 的交叉检查（**范围极窄，只能当量级核对**）

`work/runs/data-b-crosscheck-20260929/data_b_vs_a.json`（`sha256=f99da766d6a97e64`）。
**能力上限先说清**：批 A 的 **N2=9 只有 1 个组合**，批 B 的 N2 硬接为 9
⇒ **A∩B = 1 组合 × 7 频点**，**不能**排名、不能谈趋势、不能做跨批统计。

在该 7 点切片上，比值**恒定**的候选（`Vave`/`V_center` 与 A 的体积速度列）：
`Vave ↔ abs_vz_global_m3s` 比值中位 5.099e-10、**CV 0.15%**；
`Vave ↔ mech_abs_vz_m3s` 45.48、CV 0.61%；`V_center ↔ mech_abs_vz_m3s` 16.32、CV 0.96%；
`V_center/Vave = 0.3589`、CV 1.55%（恒定）。
**方法学警告（原文件已写，论文里要保留）**：n=7 且各列随频率单调 ⇒ **相关系数几乎必然接近 1、不具判别力**；
真正带信息的只有"比值是否恒定"，而 7 点上"恰好成比例"仍可能是巧合
⇒ 本检查只产出**候选短名单 + 可排除名单**，**不能**证明"是同一物理量"（需表达式原文）。

---

## 6 负结果与"坑"（本文最有价值的部分，建议单列一节）

### 6.1 我（智能体）犯过并已更正的**口径错误**，每一个都值得写进论文的"threats to validity"

| # | 错误 | 后果 | 更正方式 |
|---|---|---|---|
| 1 | 把 ΔV 记成 **2 V**（"±1 V 反相驱动"） | 每伏灵敏度会整体差 2× | 用户裁定：内 −1 V、外 0 V ⇒ **ΔV = 1 V**；元数据留痕 |
| 2 | 用 `float()` 解析**复数文本列**（形如 `(a+bj)`） | 结构通道整列为空，却被算成"已覆盖" | 改用 `_cx()` 解析，并按 `math.isfinite` 计数覆盖（**覆盖率不能用"键存在"判**） |
| 3 | 把 `quarantined` 列**静默丢掉**（`DictWriter(extrasaction="ignore")`） | 隔离信息消失 | 显式加列 + fail-closed 断言（任何未声明键即报错） |
| 4 | 多批数据用 `{**A, **C}` 合并 | **C 静默覆盖了 A 的 162 个同参数三元组** | 改按 `(batch,x,N1,N2)` 键做**并排**记录（2005 行）。出处：`docs/INDEX-records-and-rulings.md` L3394 / L3445（`A∩C = 162`） |
| 5 | 自检把"含隔离点"折与主折**互相比较** | 假不一致（主折 614/599 与另一折 615/600 被混比） | 两折各自互比。出处：同文件 L2772 |
| 6 | **我把两个不同的量混为一谈**（准备本文件时被自己抓到） | 原稿写成「170 个 `bandwidth_closed=false` 组合全部集中在低 x 端」——**两处都错**：`170` 说的是**无局部极大**（峰不存在），而 `bandwidth_closed=false` 是**交点未闭合**；且逐行核对后未闭合行**并不只**在低 x 端（见 §6.2） | 已把两个量分开陈述并各附出处；连同本行记为一次真实的 over-claim |

### 6.2 跨批比较**必须分层**（否则结论是错的）

批 A 的 x 步长 **0.1**、频段 **5–35 MHz**；主批 **0.01**、**5–50 MHz**。
⇒ 跨批比较带宽、峰位、是否贴边等**范围依赖量**时，粗网格会**系统性扭曲趋势**。

**两个必须分开说的量**（我在准备本文件时把它们**混为一谈**，见 §6.1 #6）：

* **无局部极大（一阶峰根本不存在）= 170 个组合，100% 落在 `x_scale ∈ [0.20, 0.28]`**
  （出处：`docs/INDEX-records-and-rulings.md` L3243，当时已逐 x 统计"每个 x 值 15–22 个"）。
  ⇒ 这是**扫频窗口问题**（低频侧峰跑出窗口），**不是**"性能差"；
  处理建议当时已提出：对 `x ∈ [0.20,0.28]` 把扫频下限从 5 MHz 下探（**需用户批准**）。
* **`bandwidth_closed = true` 的有 1677/2005**（出处：证据摘要 §1.1，现算自
  `multichannel_labels.csv`）；其余 328 行不是"峰不存在"，而是**−3 dB 交点未闭合**
  ⇒ 按门禁**不进带宽排名**。
  逐行核对（现取）：字面值为 `false` 的 96 行里，`x_scale` 最大到 **0.5**，
  其中 **81 行 x > 0.28** ⇒ **未闭合行并不只集中在低 x 端**，
  不能像"无局部极大"那样一句话归因，必须逐点看峰位与窗口边界。

### 6.3 异常归因曾被**反转**（append-only 留痕的实例）

`(0.2, 1, 7)` 与 `(0.2, 1, 8)` 两个角点在跨批比对中出现 **7.036 dB** 的凹陷。
我最初把嫌疑方定成批 C，**随后被证据推翻**：在 N2=6 处两批**逐点相同**
（**95.562 ↔ 95.562**）却**共有**同一凹陷 ⇒ 凹陷是**真实的**，可疑的是**批 A 在 N2=7/8**
（A 的凹陷沿 N2 为 7.036→1.071→−0.327，**跳变 5.965 dB、不连续**；
新批为 7.036→7.580→7.823，**跳变 0.544 dB、连续单调**）。
出处：`docs/INDEX-records-and-rulings.md` L2735–L2743。
已按 append-only 追加 3 条修订（`QUARANTINE_AMENDMENTS.jsonl`）并写
`ROUND5_ANOMALY_ATTRIBUTION_RETRACTION.md`；**归因尚未定论**，需 `mesh_fingerprint` 才能定。
⇒ 论文里这是一个**很好的方法学案例**：证据不足时，"隔离但不宣称谁错"。

### 6.4 一次**我自己的**测试事故（可写进"工程实践教训"，也可不写）

冒烟测试误启动了真实的一次性 agent 运行（DSH `--profile headless`）并消耗了 token。
此后加了两道结构性护栏（必须显式 `confirm_spawn=True`；测试期必须用替身脚本）。
同类教训还有若干（假守卫、子串判定误报、桩不全导致假失败），完整记录见
`docs/INDEX-records-and-rulings.md` §81–§85。

---

## 7 限制与未完成（**必须**写进 Limitation 的清单）

> 原则：**没做到就是没做到**。下面每一条都请如实写，不要用模糊表述掩盖。

1. **PMUT 自身没有 L1（网格收敛）**。库里 `validation` 表共 **11 行、全部是 L1**，
   其中 `passed = 1` —— 而这 1 条是**玩具模板**（`heat_slab_2d`，4 单元）
   ⇒ **PMUT 的 L1 通过数为 0**（现取，见 `work/paper_brief/evidence_digest.txt` §6）。
   直接后果：**任何绝对值都只能谈趋势**，论文里不得给"工程可用精度"。
2. **没有场级数据 ⇒ 无 S1（场级误差界）**。场快照只有 **57 个 `.npz`**
   （`work/runs/phase0-field-holdout-20260915/exports/**`，现取计数），且是**旧 phase0 网格、仅 20 MHz**，
   与批 A/C 不同源；**批 A/C 完全没有场数据**。用户已明确指示**暂停**场级工作。
3. **N2 = 9 只有 1 个组合** ⇒ 代理对 N2=9 **只能一步外推**；论文里不得报告 N2=9 的独立性能。
4. **无实验数据**：仓库内 `experiment` 表 **0 行**、`evidence`（文献）**0 行**。
   ⇒ 所有结论都是**仿真内部一致性**结论，**没有**实验或文献外部验证。
5. **Q 通道不优于基线**（§5.4）⇒ Q 只能作为门禁/报告量。
6. **带宽口径存在 ~20% 系统偏差且 28% 组合对不上峰**（§5.2）⇒ 绝对带宽跨口径不可比。
7. **模型状态是 `draft` / `draft_surrogate`**：`status` 字段原文如此，**未经人工放行**。
8. **未闭合的阻塞项**（需要外部输入，当前无法推进）：
   `mesh_fingerprint`、PMUT 最小 L1、`te2_9`（N2=9 数据）、Stage-1 双向扩扫数据、
   `base_model_id`（无共同模板）、`Vave/V_center` 的表达式原文（口径未书面确认）。

---

## 8 可复现指引（论文的"数据与代码可得性"可直接引用）

```powershell
# 环境：Windows + PowerShell 5.1；Python 在 work\.venv\Scripts\python.exe（3.12）
# 0) 重新生成证据摘要（本文所有数字的来源）
work\.venv\Scripts\python.exe -B work\tools\collect_paper_evidence.py
#    → work/paper_brief/evidence_digest.txt

# 1) 全仓自测（论文里可写「588 passed / 4 skipped」）
work\.venv\Scripts\python.exe -m pytest -q

# 2) 控制台自检（41 项，含门禁）
work\.venv\Scripts\python.exe scripts\webapp_server.py --selftest

# 3) 数据版本与隔离表（append-only）
work\.venv\Scripts\python.exe -B scripts\freeze_data_version.py --help
work\.venv\Scripts\python.exe -B scripts\amend_data_version_quarantine.py --help
```

**关键产物与哈希**（用于"结果可定位"）：

| 产物 | 路径 | sha256(前16) |
|---|---|---|
| 主标签表 | `work/runs/first-peak-20260929/multichannel_labels.csv` | `d06edfe199943499` |
| 首峰指标明细 | `work/runs/first-peak-20260929/first_peak_metrics.csv` | `dc4d6ae16ffdbddf` |
| 带宽口径对照 | `work/runs/first-peak-20260929/bw_method_validation.json` | `e84720a28975c41e` |
| 跨批重复性 | `work/runs/x-densify-20260928/a6/cross_batch_consistency_R-CB-N28.json` | `f9fc1625bdb2333f` |
| 响应级代理 | `work/runs/surrogate-response-20260929/response_surrogate.json` | `1f2803b793300f36` |
| 多通道代理（预注册） | `work/runs/multichannel-surrogate-20260929/PREREG_multichannel_surrogate.md` | `e90c315f9ad88042` |
| 多通道代理（模型） | `work/runs/multichannel-surrogate-20260929/multichannel_model.json` | `0d872fb14bb9093a` |
| 元数据库 | `work/store/mems.duckdb` | 存在，9,711,616 B |
| 度量协议 | `src/memsharness/metrics_v2.py` | `1c7cdc47bf40943d` |

---

## 9 给 Codex 的写作指令

### 9.1 建议的论文骨架（与本文结构一一对应）

1. **Introduction**：PMUT 设计空间与仿真成本；为什么需要"带边界的代理"而不是"更准的回归"。
2. **Related work**：PMUT 建模与代理/降阶；保形预测；数据版本化与 fail-closed 验证（可少量引用）。
3. **Platform & Data**（§2–§3）：数据资产表 + 哈希；三批次的差异与**不得混用**的理由。
4. **Method**（§4）：一阶峰范式、指标族与排名裁定、`metric_protocol_v2`、两个代理、
   保形误差界与拒答域、验证等级/冻结/append-only。
5. **Results**（§5）：口径敏感性（20%/28%）；跨批重复性（尾部与 RMSE 0.330 dB）；
   代理性能与**拒答率**；Q 门禁通过率 43.4% 的含义。
6. **Negative results & Threats to validity**（§6）：口径错误清单、跨批分层、异常归因反转。
7. **Limitations**（§7）：必须逐条写全，尤其 **L1 = 0** 与 **无实验/文献验证**。
8. **Reproducibility**（§8）：命令 + 哈希表。

### 9.2 写作边界（**硬约束**）

* **可以写成贡献的**：
  (a) 一套**口径敏感性的量化证据**（带宽 20% 系统偏差 + 28% 峰不一致）；
  (b) 一个**带保形误差界与拒答域**的多通道首峰代理，且**预注册**判定带；
  (c) **拒答率**作为一等结果报告（覆盖率 67.9% 的网格筛查）；
  (d) 一套**fail-closed + append-only + 冻结哈希**的验证方法学，并给出**负结果**（L1=0、Q 不优于基线）。
* **只能写成 limitation / future work 的**：任何"工程精度"主张、任何"免仿真出解"暗示、
  场级结论、N2=9 的独立性能、实验验证。
* **禁止出现的措辞**（仓库门禁会拦）：
  「免 COMSOL 出解」「已验证等价」「可以替代 COMSOL」「solver_certified」——
  这些词**只能出现在明确的否定句**里（例如"本工作**不**声称免 COMSOL 出解"）。
* **状态词纪律**：`draft` / `draft_surrogate` **不得**改写成"validated/approved"；
  放行权在人，论文里也不得替人放行。

### 9.3 建议的图表（每张都已有所需数据）

| 图/表 | 内容 | 数据来源 |
|---|---|---|
| 表 1 | 三批次数据资产（行×列、频段、x 步长、哈希） | §3 |
| 图 1 | SPL 频谱 + 一阶峰定义示意（含 −3 dB 带宽与左右交点） | `multichannel_labels.csv` 任一行 + `points.csv` |
| 表 2 | 指标族 × 方向 × 是否参与排名（含裁定条款） | §4.1 |
| 图 2 | 带宽口径散点（本文拟合 vs `from_points`/`from_marker`），标出 20% 带 | `bw_method_validation.json` 的 182 行明细 |
| 图 3 | Q 分布直方图 + 门禁带 2.5–3.5（标注 43.4% 通过率） | `multichannel_labels.csv` 的 `Q_factor` |
| 图 4 | 覆盖率 vs (N2, x)：可预测 / 拒答（含拒绝原因分布） | `/api/mc/screen` 输出或模型 `channels.*.coverage_by_n2` |
| 表 3 | 逐通道误差（median/p90/max/coverage/是否优于 persistence） | `multichannel_model.json:evaluation.per_channel` |
| 图 5 | 保形半宽 vs α（对数轴），凸显 α=0.01 时放大 2.4–24× | `multichannel_model.json:conformal` |
| 表 4 | 跨批重复性（标量/频谱/最差组合） | `cross_batch_consistency_R-CB-N28.json` |
| 表 5 | **负结果与限制清单**（L1=0、无实验、Q 不增值、20% 偏差） | §6–§7 |

### 9.4 如果要我补数据

论文写作过程中若发现**某个数字本文件没有**：**不要**从别处推断或补写。
把它列成"缺口清单"交回来，我会从产物里**现取**（并附哈希）再补进本文件。

---

## 10 相关文档索引（论文之外的事实来源）

本文件是**论文材料**；若要更细的工程状态与裁定原文，按下列顺序查：

| 文档 | 里面有什么 |
|---|---|
| `WORKING_PLAN.md` | 总体设计与阶段验收标准（§6.1.1 / §6.4 免求解器指标与门禁；**§7 是 P0–P7 现状对照**） |
| `docs/INDEX-records-and-rulings.md` | **记录与裁定的总索引**（§30–§85）：每条结论的出处、口径修正、失效引用留痕 |
| `docs/UNFINISHED_TASKS_AUDIT.md` | 未完成任务审计：**哪些能现在做、哪些阻塞在外部输入**（23 项，其中 6 项阻塞） |
| `docs/OPEN_ISSUES_FOR_CODEX.md` | 交给外部复核方的问题清单与闭合状态 |
| `docs/RULING_COVERAGE_AUDIT.md` | 裁定字段的覆盖率审计（哪些裁定已被数据列覆盖、哪些还没有） |
| `docs/DATA_INVENTORY.md` | 数据清单（含"**场级数据：没有**"的明确记载） |
| `docs/WEB_SERVICES.md` | 控制台/看板的启动、诊断、失败通道与上报机制（含 API 端点表） |
| `work/paper_brief/evidence_digest.txt` | **本文件全部数字的现取摘要**（由 `work/tools/collect_paper_evidence.py` 生成） |
| `AGENTS.md` | 仓库级不可协商红线（**§2**：无证据不出数字、不猜测模型内部、来源永不混同、人保留放行权…） |
