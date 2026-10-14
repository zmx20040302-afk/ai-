# TO_CODEX 记录：LT3-B 频响形状类指标（−6 dB 带宽 / FBW / 平坦度 / 带宽交叠）+ Pareto 重算（2026-09-14）

- 性质：**准备性工作**（承接 `docs\TO_CODEX_record-20260914-lt3-prep-pipeline.md` 与
  `docs\TO_CODEX_record-20260914-lt3d-legacy-vs-reverse-normalized.md`，**不覆盖**）
- 动机（由前序发现直接触发）：`Ptot@20MHz` 与 `Vave@20MHz` 在批次2 legacy 数据上**高度同序**，
  其 Pareto 前沿**退化为单点** ⇒ 该指标对**做不出候选区分**。LT3-C 的候选角色必须依靠**频响形状类指标**。
- **未运行 COMSOL / comsolbatch / mphserver**；**未写 `work\runs\`**；**未改任何被冻结文件**
- 状态：`provisional_legacy_not_formal`，`formal_ranking = false`
  （LT2 未完全通过 ⇒ **仍不得制作正式反相排名**）

---

## 1. 命令与退出码

解释器 `work\.venv\Scripts\python.exe`。

```powershell
work\.venv\Scripts\python.exe work\tools\lt3_prep.py `
  --input "C:\Users\zmx\Desktop\换能器\扫描阵列Xrange(0.4,0.05,0.8).xlsx" `
  --source-run-id "batch2-legacy-newrange005-xlsx-33ed711c" `
  --precheck "work\runs\precheck-b2-phase2-v5-aggregate\geometry_selection_precheck.json" `
  --legacy-vdiff-V 1.0 `
  --legacy-vdiff-feedback-id "fb-20260914-legacy-drive-amplitude" `
  --legacy-vdiff-feedback-doc "docs\TO_USER-feedback-20260914-legacy-drive-amplitude.md" `
  --compare-reverse "work\runs\lt1-reverse-sample\lt1_validated_results_v2.csv" `
  --out-dir "work\lt3"
# exit code = 0
```

守卫（不变，均已实测）：反相数据 exit 3（无排名/Pareto/对照）；
反相数据 + `--legacy-vdiff-V` exit 2；有值缺证据文件 exit 2；`--formal` exit 2；
`--out-dir work\runs\...` exit 2（不建文件）。

---

## 2. 新增指标的定义式（全部写进代码常量 `BW_DEF` / `FLATNESS_DEF` / `OVERLAP_DEF`）

### 2.1 −6 dB 带宽与 FBW

```text
f_low / f_high : 从**曲线峰值**向两侧首次跌破 −6 dB 的频率（相邻频点线性插值）
BW_<q>_MHz     = f_high − f_low
fc_<q>_MHz     = (f_low + f_high) / 2        ← 分母取【上下边频的算术中心】
FBW_<q>_percent = (f_high − f_low) / fc × 100
```

- **分母取哪个中心，明确写定**：**上下边频的算术中心**，**不是**峰值频率 `f_peak`，**不是**几何平均。
- dB 规则：`Ptot` 用 **10·log10**（功率量）、`Vave` 用 **20·log10**（幅值量）——**绝不混用**
  （沿用 `scripts/analyze_sweep.py`；本批两处独立复算已逐位核对，见 §5）。
- `BW`/`FBW` **只在上下边频都取到**（`*_bandwidth_closed = true`）时给出，否则**留空**。

### 2.2 带内平坦度

```text
flatness_<band>_<q>_dB      = max(dB_band) − min(dB_band)     ← 带内【极差】
flatness_<band>_<q>_std_dB  = 带内 dB 的【总体标准差 σ】（分母 n）
band_min_dB_rel_global_peak_<band>_<q> = 带内最低电平（相对【整条 5–35 MHz 曲线的峰值】）
```

- **相对哪个电平**：dB 曲线对**整条曲线的峰值**（每量各自）归一。
  极差 `max−min` 是**平移不变量** ⇒ 该值与参考电平**无关**（这是选极差而非标准差作主指标的原因）；
  而 `band_min_dB_rel_global_peak` **依赖参考电平**，必须与极差**成对解读**。
- 取值带：`10_30`（10–30 MHz）、`15_25`（15–25 MHz）、`full`（全带 5–35 MHz）。

### 2.3 峰值与峰位（并确认与既有口径一致）

```text
Ptot_peak_W / f_peak_Ptot_MHz     （权威列，由 metric_row 产出）
Vave_peak   / f_peak_Vave_MHz     （同上）
```

**口径一致性已核对**：本脚本在 `response_metrics()` 里用 `resp_` 前缀**独立再算一遍**
峰值/峰位，与 `metric_row` 的结果逐项比较：

```text
rows_checked = 324（162 组合 × 2 量）
peak_value_mismatch = 0
peak_freq_mismatch  = 0
max_peak_rel_diff   = 0.0
```

⇒ 两处口径**完全一致**（`Ptot_peak_W` 与 `resp_Ptot_peak`、`f_peak_*_MHz` 与 `resp_f_peak_*_MHz`）。

### 2.4 交叠/交叉类指标与比值峰（**含物理含义**）

| 指标 | 定义 | 物理含义 |
|---|---|---|
| `band_overlap_Ptot_Vave_MHz` | `Ptot` 的 −6 dB 频带 ∩ `Vave` 的 −6 dB 频带的**长度** | **两者同时**处于各自峰值 6 dB 以内的**公共通带**——『输出不掉、响应也不掉』的可用频段，对换能器通带最有工程意义 |
| `band_overlap_fraction_of_union` | 交集 / 并集（Jaccard 型，0–1） | 两条带宽的**重合程度**；接近 1 表示功率带与响应带几乎重合 |
| `Ptot_over_Vave2_peak` / `f_peak_Ptot_over_Vave2_MHz` | `max(Ptot/\|Vave\|²)` 及其频位 | ∝ 给定模态下的**辐射电导**（单位 kg/s），**与驱动电平无关**的效率**形状**量 |
| `Ptot_over_Vave_peak` / `f_peak_Ptot_over_Vave_MHz` | `max(Ptot/\|Vave\|)` 及其频位 | 工单 LT3-B 要求；仍含 `\|Vave\|` 因子，**只作形状参考，不得当作效率** |

- 任一侧带宽未闭合 ⇒ `band_overlap_*` **留空**（`band_overlap_applicable=false`），
  **不得**用单侧带宽冒充交叠。

---

## 3. 插值口径与由此产生的不确定度（**不许省略**）

### 3.1 两种口径并行计算

| 口径 | 做法 | 用途 |
|---|---|---|
| `dB_domain_linear`（**主口径**，进入正式列） | 先转 dB（功率 10log10 / 幅值 20log10，各自对峰值归一），在相邻频点的 **dB 值**间线性插值求 −6 dB 交点（沿用 `analyze_sweep.py::cross_6db`） | `f_low_*`/`f_high_*`/`BW_*`/`FBW_*` |
| `linear_domain_linear`（对照） | 把 −6 dB 还原为**物理量阈值**（功率 `peak·10^(−6/10)`、幅值 `peak·10^(−6/20)`），在**物理量**上线性插值 | `*_lininterp_*`，仅用于估不确定度 |

### 3.2 不确定度来源与**实测**量级

不确定度来源 = **两套插值口径的差值**。这**不是**网格收敛/Richardson 外推，也**不是**实验或文献依据。

| 量 | n | 最小 | **中位** | 最大 |
|---|---|---|---|---|
| 下边频口径差 `Ptot` (MHz) | 162 | 0.0026 | **0.543** | 2.393 |
| 上边频口径差 `Ptot` (MHz) | 9 | 0.0149 | **0.153** | 0.238 |
| 下边频口径差 `Vave` (MHz) | 158 | 0.0047 | **0.252** | 1.108 |
| 上边频口径差 `Vave` (MHz) | 51 | 0.0042 | **0.185** | 0.605 |
| **`BW` 口径差 `Ptot` (MHz)** | 9 | 1.105 | **2.399** | 2.619 |
| **`BW` 口径差 `Vave` (MHz)** | 49 | 0.205 | **0.865** | 1.577 |
| **`FBW` 口径差 `Ptot` (百分点)** | 9 | 7.82 | **27.57** | **28.73** |
| **`FBW` 口径差 `Vave` (百分点)** | 49 | 1.43 | **7.32** | **16.45** |

**结论（必须随任何带宽结论声明）**：

- 插值域的选择会**实质性改变**带宽结论：`Ptot` 的 FBW 因口径不同可差 **最多 28.7 个百分点**，
  `Vave` 的 FBW 可差 **最多 16.4 个百分点**（中位 7.3）。
- 由于本批只有 **7 个频点、步长 5 MHz**，该相对不确定度**可与 FBW 本身同阶**
  ⇒ 带宽/FBW 只用于**粗筛与候选区分**，**不得**作为工程指标对外引用，也**不得**引用到小数点后多位。
- 对照口径的存在并不"修正"主口径；两者都只是假设。**报告任何单一数值时必须同时给出该差值。**

### 3.3 分辨率限制（原文照录，写进代码 `RESOLUTION_LIMITATION`）

> 本批只有 **7 个频点（5–35 MHz，步长 5 MHz）**。因此：① 任何『−6 dB 带宽』都是**粗估**，
> 边频由相邻频点**插值**得到，不是扫出来的；② 插值域的选择（dB 域线性 vs 物理量线性）会改变边频，
> 故同时给两套口径与其差值作为该假设的不确定度；③ 20/35 MHz 这类采样点上的取值是精确命中，
> 但**带宽边频几乎总落在采样点之间** ⇒ 仍是插值值；④ 曲线若在上/下边界仍未回落 6 dB，
> 标 `lower/upper_bound_not_found`，**不得**把边界当交点，**更不得**解释为无限带宽；
> ⑤ 5 MHz 步长下带宽/FBW 的相对不确定度可与 FBW 本身同阶 ⇒ 本批带宽指标只用于**粗筛与候选区分**，
> 不得作为工程指标对外引用。

---

## 4. 峰值/边频顶边界的打标结果

打标代码：`peak_or_edge_at_frequency_band_boundary__not_interpretable_as_unbounded`
（逐行写入 `*_bandwidth_boundary_warning`）。

| 量 | 有峰 | 带宽闭合 | 下界未找到 | **上界未找到** | 峰位在下边界 | **峰位在上边界** | 带 warning |
|---|---|---|---|---|---|---|---|
| `Ptot` | 162 | **9** | 0 | **153** | 0 | **83** | 153 |
| `Vave` | 162 | **49** | 4 | **111** | 0 | **72** | 113 |

- `Ptot` 只有 **9/162** 组合的功率带宽在 5–35 MHz 内**闭合**；**153/162** 的上边频**未找到**，
  其中 **83/162** 的峰位就顶在 **35 MHz 上边界**。`Vave` 为 49/162 闭合、111 未找到上界、72 峰位顶边界。
- ⇒ 这批数据**谐振没被频段包住**：多数组合的 −6 dB 上边频在 35 MHz 之外。
  按 `sweep-analysis` SOP §0 铁律 2，**不得**据此选"最优参数"，只能用于筛掉明显差的组合。
- 两类标记都已逐行落地：`*_upper_bound_not_found` / `*_lower_bound_not_found` /
  `*_peak_at_upper_boundary` / `*_peak_at_lower_boundary` / `*_bandwidth_boundary_warning`。
- 插值口径一致性：`Ptot` 为 `both_closed 9 / one_convention_only 0 / neither_closed 153`；
  `Vave` 为 `49 / 0 / 113` —— **没有**出现"只有一个口径能闭合"的组合（这类最危险，会掩盖分歧）。

---

## 5. Pareto 重算（换用有区分度的指标对）

在预检 `eligible` 子集（72/162）内计算，逐对独占；**不做加权总分**。

| 对 | 指标（方向） | 可用点 | **前沿** | 被支配 | 支配对 | 退化？ | 前沿组合 |
|---|---|---|---|---|---|---|---|
| **P1**（工单指定） | `Ptot_peak_W`(↑) × `FBW_Ptot_percent`(↑) | **9** | **2** | 7 | 22 | 否 | `(0.55,6)`、`(0.65,6)` |
| **P2**（本管线选择） | `FBW_Vave_percent`(↑) × `flatness_15_25_Vave_dB`(↓) | **49** | **4** | 45 | **628** | 否 | `(0.75,2)`、`(0.75,3)`、`(0.75,4)`、`(0.75,5)` |
| P3 | `FBW_Vave_percent`(↑) × `Vave_peak`(↑) | 49 | 12 | 37 | 283 | 否 | 12 个（见 CSV） |
| P4 | `FBW_Ptot_percent`(↑) × `flatness_15_25_Ptot_dB`(↓) | 9 | 3 | 6 | 21 | 否 | `(0.55,6)`、`(0.65,5)`、`(0.7,5)` |

### 5.1 结果解读（如实，不美化）

1. **原先的单点退化已消除**：`Ptot@20MHz × Vave@20MHz` 的前沿是 1 个点（被支配 71/71）；
   换用形状类指标后，四对前沿均为 **2–12 个点**，**无一对退化**。
2. **P1 是工单指定对，但它可用点只有 9/72** —— 因为 `FBW_Ptot` 需要功率带闭合，
   而只有 9/162 组合闭合（§4）。⇒ 用 P1 做候选区分**覆盖率很差**：63 个 eligible 组合因
   `FBW_Ptot` 为空被排除。**这一限制必须随 P1 结论一起声明**，不得只看"前沿有 2 个点"。
3. **P2 是可用性最好、区分度最高的一对**：49/72 可用，前沿 **4 个点**，且 4 个前沿点
   **同处 `x_scale = 0.75`、`N_te1 = 2…5`** —— 结构上自洽（同一缩放下用内电极宽度换
   带宽–平坦度权衡），比跨越多个 `x_scale` 的散点更有设计信息量。
   **这正是 LT3-C 需要的"均衡代表"来源**。
4. **P3 前沿达 12 个点**（≈25% 的可用点非支配）⇒ 区分度**弱**，只宜作交叉核对，
   不宜作为候选筛选的主依据。
5. 选择 P2 的**理由**（写进代码 `PARETO_PAIRS.P2.why`）：带宽与带内平坦度是通带的**两个正交要求**
   （『够宽』与『够平』），在单膜/单振子结构上通常**此消彼长**；两者都是**形状量**，
   不依赖驱动电平，因此不受 legacy/反相电压口径差异影响，比峰值类指标更稳健。
6. **P4（功率侧）前沿 3 点与 P1 部分重合**，说明功率侧确实受"上界未闭合"限制；
   P2/P3 的结论来自 `Vave` 口径。两口径**结论不一致**这件事本身应保留在报告里。
7. 全表逐行带 `source_run_id`、`source_file_sha256`、`drive_mode`、`status`、`formal_ranking=false`；
   退化标志 `degenerate_pair` 逐行给出（本批全为 `False`）。

---

## 6. 独立验证与口径一致性

| 检查 | 方法 | 结果 |
|---|---|---|
| 边频/平坦度**独立复算** | 用一个**不 import `lt3_prep`** 的独立脚本，重新解包 xlsx（zipfile+XML）、重解析复数、重算两套口径的 −6 dB 边频与 15–25 MHz 平坦度 | **162/162 组合、1944 个值、0 处不一致**（容差 1e-9） |
| 峰值/峰位**口径一致性** | `metric_row` 与 `response_metrics` 两处独立实现对比 | **324 项、0 处不一致**、`max_peak_rel_diff = 0.0` |
| 反相侧归一量交叉核对 | 反相表自带 `Ptot_norm`/`Vave_norm` vs 本管线的 `/4`、`/2` | 15/15 一致（见前一记录） |
| xlsx 键格式 | 实测 `x_scale` 字符串含 `0.55000000000000004` | 管线按 `round(...,6)` 归键，未受影响 |

---

## 7. 产物路径与 sha256

工具：`work\tools\lt3_prep.py`，127,547 B，
sha256 `0af7b4d70817e2c4f1ec6a7efd71cbba11e2b5c7449fb02ce8b845cfe8393248`

| 产物 | 字节 | sha256 |
|---|---|---|
| `work\lt3\lt3_response_metrics.csv`（162 行 × 88 列） | 196,241 | `e5eb535a8ceaefebf35c21db98181a832282b97553509ea446bc65101c8bdd7b` |
| `work\lt3\lt3_response_metrics_contract.md` | 7,679 | `c1d8542947d4e37ca5c27f88054045cf678423fb8dbd182a4a35f4029158a8c6` |
| `work\lt3\lt3_pareto_pairs.csv`（116 行 × 19 列） | 43,498 | `6027f0762921172281334494533e67b54516a0129af7ea2d83caa8e1fb7a20b1` |
| `work\lt3\lt3_metrics.csv`（162 行，已并入全部频响列） | 379,609 | `fa2aff7b9689d3e80ac15c4cdfab6d298cf06ae4eeb9342b2341da05640aba20` |
| `work\lt3\lt3_pareto.csv` | 414,828 | `6ae6f9f5b84180260b3772650a1b324a9f9c9296a739de8ee745d7cfe27b5bbe` |
| `work\lt3\lt3_quality_report.json` | 33,106 | `74e58fa88d4d658ffa8a65db796e4437ddd1812e05e1918fc7157bf39fc83322` |
| `work\lt3\lt3_normalization_contract.md` | 8,064 | `946b37515f7fb4b8be9d3bf3cb3cf11a0eba4c64488b779789799ad24aeea9bc` |
| `work\lt3\lt3_manifest.json` | 3,711 | `2be7e4977d7819caad305a06d3b3aa429225125d2d9b06980935315de6c21b87` |
| `work\lt3\legacy_vs_reverse_normalized.csv` | 30,199 | `ec69687568545f6b50660a4b74657c1e3af7d4e9140cc2c686e13d396da5a7a2`（未变） |
| `work\lt3\lt3_legacy_vs_reverse_normalized.md` | 5,944 | `209c7f52d7f8bf39da20a955ea7389f72e62b86d413b472548f6d2bfe72e31d0`（未变） |
| `work\lt3\lt3_ranking.csv` | 20,901 | `76d5315c81c5469b10f84b95463cbf1ae8772f6cdec9ac55add51763c0c0bcf6`（未变） |
| `work\lt3\lt3_pareto_dominance.csv` | 659,355 | `db139d6ccaf88f07b8176e75752b50c7db39d249855edc33042a81ae5c768c0d`（未变） |
| `work\lt3\lt3_ranking_status.json` | 1,266 | `f338ff9e6c8557a5670c02a453d0c071a0a9ccc5a3626f51fed77949b23c4f1d`（未变） |
| `work\lt3\inputs\...`（xlsx / 预检） | — | `33ed711c8d53bf02…` / `b26193fea3f56a6e…`（未变） |

守卫验证产物 `work\lt3\_guard_test_reverse\`（反相 15 点，exit 3）：该目录**仍无**
`lt3_pareto.csv` / `lt3_pareto_pairs.csv` / `lt3_ranking.csv` / `lt3_ranking_status.json` /
`legacy_vs_reverse_normalized.csv`。其中的 `lt3_metrics.csv`（含频响列）与
`lt3_quality_report.json` 的 sha256 见 `lt3_manifest.json`。

---

## 8. 已实现 / 未验证 / 限制

### 8.1 已实现

- `Ptot` 与 `Vave` 各自的 **−6 dB 带宽**（`f_low`/`f_high`/`BW`/`fc`/`FBW`），定义式写进代码常量；
- **两套插值口径**并行计算，并给出**实测不确定度**（逐行 + 汇总）；
- **带内平坦度**（10–30 / 15–25 / 全带 × 2 量）：dB 极差（主）、总体 σ、相对全带峰值最低电平；
- **峰值与峰位**，且与既有 `metric_row` 口径**逐位核对一致**（324 项 0 分歧）；
- **带宽交叠**（`Ptot` 带 ∩ `Vave` 带，及 Jaccard 比）与**比值峰** `Ptot/|Vave|`、`Ptot/|Vave|²`（含物理含义说明）；
- **边界打标**：`*_bound_not_found`、`*_peak_at_*_boundary`、`*_bandwidth_boundary_warning`（逐行）；
- **Pareto 重算**：4 个指标对（含工单指定的 `Ptot_peak × FBW`），前沿、被支配、支配对、退化标志全部逐行落盘；
- **独立复算验证**：162 组合 × 12 个量 = 1944 值，0 处不一致。

### 8.2 未验证

- **7R 轴向声压 `H_p(f)=|p(f,0,0,7R)|/|V|`：需 COMSOL，未实现**（本机当前处于 no-COMSOL 窗口；
  还需坐标原点平移与场级导出）。**它才是最终主判据，本轮所有带宽/平坦度结论都是它的替代性粗筛。**
- **`−6 dB` 上边频未闭合的 153/162（`Ptot`）、111/162（`Vave`）组合**：其真实带宽**未知**，
  本轮**没有**任何带宽结论（不是"带宽很大"）。
- **插值口径差**只是不确定性的一种**下界式代理**：它**不覆盖**离散误差、网格误差、模型口径差。
  真实带宽不确定度**未做**网格收敛或 Richardson 分析。
- **P1 的覆盖问题未解决**：63/72 eligible 组合因 `FBW_Ptot` 为空被排除；
  若要提高功率侧覆盖率，需要**扩展频段上界**（工单明确禁止本轮改 `fmax`）。
- **反相侧带宽未算**：LT1 只有 3 个频点（5/20/35），**点数不足以算 −6 dB 带宽**（至少需要峰值两侧各一点且能跌破）；
  故**不**对反相侧出任何带宽/平坦度结论。LT2 的 504 点（7 频点）尚不存在。
- 网格收敛、单元数对带宽的影响：**未做**。

### 8.3 限制

| 限制 | 说明 |
|---|---|
| 分辨率 | 只有 7 频点 / 步长 5 MHz；所有带宽都是**插值粗估**；`FBW` 口径差中位 7.3（`Vave`）～27.6（`Ptot`）个百分点，**与 FBW 本身同阶** ⇒ 只作粗筛，不得对外引用。 |
| 顶边界 | 83/162（`Ptot`）与 72/162（`Vave`）峰位顶在 35 MHz；多数组合上边频在带外 ⇒ **谐振未被频段包住**，不得据此选"最优参数"，**更不得**解释为无限带宽。 |
| 授权 | **仍不得制作正式反相排名**（LT2 = `BLOCKED_BEFORE_PRODUCTION`）；一切产出为 `provisional_legacy_not_formal`、`formal_ranking=false`。 |
| 排名范围 | Pareto 只在预检 `eligible` 子集（72/162）内计算；被排除的 90 组（`design_region_reversed` 81 + `boundary_coincident` 9）不参与。 |
| 不做总分 | 四个指标对**各自独立**，**不合成加权总分**；不同对的前沿**不一致**（P1/P4 与 P2/P3 口径不同）这件事必须保留，不得只报最好看的一对。 |
| 电气量 | `Zin*`/`I_*` 因 LT0-C KCL 16.6–18.9% > 1% **整体排除**；频响指标只作用于声学量，不改变该排除。 |
| 来源分离 | 归一化分母（legacy）来自**人反馈** `fb-20260914-legacy-drive-amplitude`，分子来自导出表；本轮的频率形状量本身**只用导出表**（不涉及归一化分母），但**跨批对照**仍受前记录 §1 的来源分离与限制约束。 |
| 命名 | `Vave` 的 −6 dB 带宽只能称**响应带宽**，`Ptot` 的只能称**功率带宽**；**禁止**往返/脉冲回波/阵列带宽。 |
| 外推 | 单 PMUT 单元模型结论**不得**外推为阵列性能。 |

---

## 9. 交付声明

- 未运行 COMSOL / `comsolbatch` / `mphserver`；
- 未写 `work\runs\` 下任何内容（`--out-dir` 均落在 `work\lt3\`；`--out-dir work\runs\...` 已实测拒绝 exit 2）；
- 未修改任何被冻结文件（`lt2_production.py` / `lt2_sampler.py` / `tests_lt2_supervisor.py` / `rt_gate.py` /
  `tests_rt_gate.py` / `lt2r0_v2.py` / `lt2_acceptance_r4.py` / `lt2_flake_hunt.py` / `check_undefined_names.py` /
  `freeze_snapshot.py` / `check_r3_conditions.py` / `AGENTS.md` / `WORKING_PLAN.md`）；
- 未运行 `tests_lt2_supervisor.py` / `lt2_acceptance_r4.py` / `tests_rt_gate.py`；未使用 pytest；
  `work\tools\check_undefined_names.py` 仅**运行**（`lt3_prep.py` 报 0 个未定义名），未修改；
- 产物只写在 `work\lt3\` 与本文件；用户原始导出、预检产物、LT1 反相小样、人反馈记录均**只读引用**；
- 本记录**不覆盖**既有两份记录；其被取代的哈希已在前两份文件中以**追加附录**方式标注。

---

## 附：后继更正（2026-09-14，**append-only**，不覆盖上文）

> 依据 `AGENTS.md` 红线 6：本附录只**新增**。
> 其后按用户答复（「可以尝试修改，但是我现在没有 45MHz 的计算数据」）把**频段上界参数化**，
> 并登记 45 MHz data gap。最新记录：
> `docs\TO_CODEX_record-20260914-lt3c-band-parameterization.md`
> （`7ad9e3222e1db3fcda4ea7eb698729c03236357cac2bafed4390cacb0431a599`）。

**工具与产物的哈希变化**：

| 项 | 本记录 §7 所记 | 最新 |
|---|---|---|
| `work\tools\lt3_prep.py` | `0af7b4d70817e2c4…` | `5b53b1d7c15e22f4cb91382116c08fb4bcdb925c74ae7c0d5382f6317bee3c55`（137,711 B） |
| `work\lt3\lt3_response_metrics.csv` | `e5eb535a8ceaefeb…` | `275335756c6d839359ca8257f47e6a724efb8b86a191b9b172ad5c033c6fe36d`（162×93；**+5 个 `band_*` 列**） |
| `work\lt3\lt3_response_metrics_contract.md` | `c1d8542947d4e37c…` | `0fd516dfa17990d8bf13cf661a658f7d65e20316ec1771b1e65bf435a7c6a29a`（新增 §3.1 频段界 / §3.2 data gap + 45 MHz 重做清单） |
| `work\lt3\lt3_metrics.csv` | `fa2aff7b9689d3e8…` | `2f2abcbdbe58fe5bc2c64e796a76cae22ef98e7de2406929f91a8933c371e6de` |
| `work\lt3\lt3_pareto.csv` | `6ae6f9f5b8418026…` | `9d232343899721e338833646d8ef8f10c3d3ffdebc49f4ca20db520c9e082c50` |
| `work\lt3\lt3_quality_report.json` | `74e58fa88d4d658f…` | `2106660d92b8e0be59af2dbbeaba017a5c290b8fbd671e6641f24c7032bb1e48` |
| `work\lt3\lt3_normalization_contract.md` | `946b37515f7fb4b8…` | `eab633b41cac664263b7ba6438b14921f7a1673703185372a28a3ea7e6ac1522` |
| `work\lt3\lt3_manifest.json` | `2be7e4977d7819ca…` | `701e3438ed1c3d732ac2b469c3adb9f0f5d371acb2875f1264c3c8f0c5e42a5c`（3,712 B；现排除 `_*` 辅助目录） |
| **未变（逐字节相同）**：`lt3_pareto_pairs.csv` | `6027f07629211722…` | `6027f0762921172281334494533e67b54516a0129af7ea2d83caa8e1fb7a20b1` |
| **未变（逐字节相同）**：`lt3_ranking.csv` / `lt3_pareto_dominance.csv` / `lt3_ranking_status.json` | — | 同本记录 §7 |

新增产物：`work\lt3\lt3_45mhz_data_gap.json`（`32ceef45a40e7da9…`，45 MHz data gap 检索证据）、
`work\lt3\lt3_band_parameterization_check.json`（`465db2b2023672f4…`，参数化前后逐列比对）。

**本记录 §2（定义式）、§3（插值口径与不确定度）、§4（边界打标）、§5（Pareto 重算：四对全部不退化、
P2 前沿 4 点位于 `x=0.75`、`N1=2…5`）、§6（独立验证 1944 值 0 分歧）的结论全部不变**：
参数化**未改变默认口径** —— 逐列逐行比对证实共享列零差异、零删除列，仅新增 5 个 `band_*` 登记列。

**§8.2「未验证」新增两条**：
(a) `--band-max-mhz` 只改变**声明的频段界**，不生成界外数值；声明 45 MHz 时 `*_upper_bound_not_found`
仍为 153，而 `*_peak_at_*_boundary` 计数会随声明界变化（实测 83→0）——
**不得**把该计数下降当作顶边界问题缓解；
(b) 45 MHz 数据**不存在**（全仓 1021 张含频率列的结果表中，频率最大值 >36 MHz 的表 **0** 张，
全局最大 35 MHz；「5–45 MHz @0.5 MHz = 81 点」只是**精扫计划**）。

