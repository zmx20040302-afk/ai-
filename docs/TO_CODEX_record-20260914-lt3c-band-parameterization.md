# TO_CODEX 记录：LT3-D-1 频段上界参数化 + 45 MHz data gap 登记（2026-09-14）

- 性质：**准备性工作**（承接 `docs\TO_CODEX_record-20260914-lt3b-response-metrics.md`，**不覆盖**）
- 用户答复（原话）：**「可以尝试修改，但是我现在没有 45MHz 的计算数据」**
- 本轮口径（严格照此）：

```text
可以做的：把频段上界参数化，使将来 45 MHz 数据到位时管线可直接用；并显式登记「45 MHz 数据当前不存在」。
不可以做：不跑 COMSOL、不改 fmax、不生成任何 45 MHz 数值、不推测 45 MHz 带宽。
```

- **未运行 COMSOL / comsolbatch / mphserver**；**未写 `work\runs\`**；**未改任何被冻结文件**
- 授权不变：`provisional_legacy_not_formal`、`formal_ranking = false`（LT2 未通过 ⇒ 仍不得正式反相排名）

---

## 1. 改动摘要

| 项 | 内容 |
|---|---|
| 新增 CLI | `--band-min-mhz`（默认 `None`）｜`--band-max-mhz`（默认 `None`） |
| 默认行为 | **`None` ⇒ 从输入数据自动探测**（per-combo 最小/最大频点）⇒ 与参数化前**逐值一致** |
| 新增登记列 | `band_min_MHz`、`band_max_MHz`、`band_source`（`auto_detected` \| `cli`）、`band_data_fmin_MHz`、`band_data_fmax_MHz` |
| 校验 | `--band-min-mhz >= --band-max-mhz` ⇒ exit 2；`band_max` 超出数据范围 ⇒ 打印警告并置 `override_exceeds_data_range=true` |
| **不外推** | 界外无数据 ⇒ 边频仍标 `*_bound_not_found`，**不生成任何界外数值**（已实测） |
| 登记到产物 | 质量报告 `response_metrics.band` 与 `response_metrics.frequency_domain_coverage.data_gap_45MHz`；契约 MD 新增 §3.1 频段界 + §3.2 data gap + 重做清单 |
| manifest 收紧 | `lt3_manifest.json` 现在**排除以 `_` 开头的辅助子目录**（守卫验证、快照、演示），只登记本次运行产物与 `inputs` |
| 未新增指标 | **四对 Pareto 与 P2 前沿结论不变**；本轮的**唯一**新列是 `band_*` 登记列 |

## 2. 默认口径未变的自证（同命令跑一次，逐列逐行比对）

命令（与 LT3-B 完全相同的命令行，**不加** `--band-*`）：

```powershell
work\.venv\Scripts\python.exe work\tools\lt3_prep.py `
  --input "C:\Users\zmx\Desktop\换能器\扫描阵列Xrange(0.4,0.05,0.8).xlsx" `
  --source-run-id "batch2-legacy-newrange005-xlsx-33ed711c" `
  --precheck "work\runs\precheck-b2-phase2-v5-aggregate\geometry_selection_precheck.json" `
  --legacy-vdiff-V 1.0 --legacy-vdiff-feedback-id "fb-20260914-legacy-drive-amplitude" `
  --legacy-vdiff-feedback-doc "docs\TO_USER-feedback-20260914-legacy-drive-amplitude.md" `
  --compare-reverse "work\runs\lt1-reverse-sample\lt1_validated_results_v2.csv" `
  --out-dir "work\lt3"     # exit 0
```

参数化**前**的产物已快照到 `work\lt3\_v1_band35_preserved\`（13 个文件 + `_preserved_manifest.json`，
快照时工具 sha256 `0af7b4d70817e2c4…`），随后逐列逐行比对：

| 产物 | 行数 | 共享列 | 新增列 | 删除列 | **共享列取值差异** | 逐字节相同 |
|---|---|---|---|---|---|---|
| `lt3_response_metrics.csv` | 162 | 88 | 5 | 0 | **0** | 否（仅多新列） |
| `lt3_pareto_pairs.csv` | 116 | 19 | 0 | 0 | **0** | **是** |
| `lt3_metrics.csv` | 162 | 110 | 5 | 0 | **0** | 否（仅多新列） |
| `lt3_pareto.csv` | 162 | 117 | 5 | 0 | **0** | 否（仅多新列） |
| `lt3_ranking.csv` | 72 | 20 | 0 | 0 | **0** | **是** |
| `lt3_pareto_dominance.csv` | 2323 | 15 | 0 | 0 | **0** | **是** |

**结论：默认口径未变** —— 6 个产物**共享列零差异、零删除列**，只新增 `band_*` 登记列
（`band_min_MHz`、`band_max_MHz`、`band_source`、`band_data_fmin_MHz`、`band_data_fmax_MHz`）。
`lt3_pareto_pairs.csv` / `lt3_ranking.csv` / `lt3_pareto_dominance.csv` **逐字节相同**。
机读证据：`work\lt3\lt3_band_parameterization_check.json`。

复算方式（一次性辅助脚本，非交付主体）：

```powershell
work\.venv\Scripts\python.exe work\lt3\_gen_evidence.py
```

## 3. data gap 登记：**45 MHz 计算数据当前不存在**

### 3.1 检索证据（实检索，非推断）

| 项 | 结果 |
|---|---|
| 扫描范围 | `work\runs`、`work/reports`、`work/exports`、`work/data`、`work/artifacts`、`work/models` |
| 候选表（`.csv`/`.xlsx`，≤8 MB） | **3206** 张 |
| 其中含频率列并**逐格扫描**的 | **1021** 张（`.xlsx` 未逐格扫描；批次2 的 xlsx 已单独核验） |
| **频率最大值 > 36 MHz 的表** | **0 张** |
| 全仓频率最大值 | **35,000,000 Hz**（恰为 35 MHz），出现在 `work\runs\gui-sweep-20260912T113936Z-bd387a56\source_table.csv` 与 `work\reports\analysis_decision\newrange005\raw_source_table.csv` |
| 输入侧核验 | 批次2 xlsx（`33ed711c…`）频率集合 `{5,10,15,20,25,30,35}` MHz（7 点）；LT1 反相小样（`43d5711c…`）`{5,20,35}` MHz（3 点） |
| 45 MHz 字样命中 | **6 个文件**，**全部是精扫计划/口径/状态文档**（如 `05_fine_sweep_plan.csv` 的 `5–45 MHz @0.5 MHz = 81 点`、`06_final_comparison.md`、`ranking_status.json`、`00_executive_summary.md`），**没有一个是结果表** |

⇒ **「81 点 5–45 MHz」是计划，不是已算数据**；没有任何结果表的频率列达到 45 MHz。

机读证据文件：`work\lt3\lt3_45mhz_data_gap.json`（含 `n_tables_with_max_freq_gt_36MHz = 0`、
`global_max_freq_value = 35000000.0`、`top_freq_tables`、6 条命中明细、输入核验、边界事实、policy）。

### 3.2 文件名陷阱（已登记，避免误判）

`work\models\b_GE_task3_2new_currentdrive_fmax45_v1.mph` 的**文件名含 `fmax45`**，
但本批数据频段为 5–35 MHz。该模型的**实际 `fmax` 设置未经 API 核验**（红线 3：不猜测模型内部）。
⇒ **文件名不得**当作「已有 45 MHz 数据」的证据。该文件即 `drive_change_manifest.json` 的
`legacy_working_copy`（sha256 `0f75ca1df9262f27…`）。

### 3.3 已有的边界事实（当前 5–35 MHz 频段下）

```text
Ptot : 带宽闭合 9/162  ；上边频未找到 153/162 ；峰位顶 35 MHz 83/162
Vave : 带宽闭合 49/162 ；上边频未找到 111/162 ；峰位顶 35 MHz 72/162
下边频未找到：Ptot 0/162 ；Vave 4/162        峰位顶下边界：均为 0
```

⇒ 多数组合的 −6 dB 上边频在 35 MHz 之外、**谐振没被频段包住**；按 `sweep-analysis` SOP §0 铁律 2，
**不得**据此选「最优参数」，**更不得**把边界解释为无限带宽。

### 3.4 参数化实测：声明上界 45 MHz 也**不会**凭空产生数据

演示命令（输出到 `work\lt3\_demo_band45\`，**不影响**主产物）：

```powershell
work\.venv\Scripts\python.exe work\tools\lt3_prep.py `
  --input "C:\Users\zmx\Desktop\换能器\扫描阵列Xrange(0.4,0.05,0.8).xlsx" `
  --source-run-id "batch2-legacy-newrange005-xlsx-33ed711c" `
  --precheck "work\runs\precheck-b2-phase2-v5-aggregate\geometry_selection_precheck.json" `
  --band-max-mhz 45 --out-dir "work\lt3\_demo_band45"     # exit 0
```

实测结果：`band_source = cli`、`band_min/max = 5/45`、`auto_detected_band_MHz = [5,35]`、
`override_exceeds_data_range = true`、`no_extrapolation = true`；
`Ptot` 的 `upper_bound_not_found` **仍为 153**，生成的 `f_high_Ptot` **最大仅 28.94 MHz**
——**没有任何 >35 MHz 的数值被生成**。
另：`peak_at_upper_boundary` 由 83 降到 **0** —— 因为 35 MHz 不再是「声明的上边界」。
**这不是问题缓解**，只是标记语义随声明界变化；曲线在数据范围内仍未回落 6 dB，
`upper_bound_not_found` 不变即可证明。该语义已在
`lt3_band_parameterization_check.json` 的 `band_semantics_note` 与契约 MD 中写明。

## 4. 「若扩到 45 MHz 需要重做什么」清单（**只列，本轮未执行**）

写进代码常量 `BAND_45MHZ_REDO_CHECKLIST`，并出现在 `lt3_response_metrics_contract.md` §3.2：

1. **网格上界与 `fmax` 口径变更 ⇒ 网格可比性失效**：现有 35 MHz 网格的 `mesh_element_count`
   （106,212–157,390）与 45 MHz 网格**不是同一离散**，两批 `Ptot`/`Vave` 与带宽**不得并排**
   （`source_type` 同为 `simulation` 但离散口径不同）；必须先做网格收敛或桥接证据。
2. **LT2-C 控制面/选择集需重新预检**：`intop5==swr1==efc1`、`area_ptot`、bbox 与选择集是
   **按网格/几何状态**记录的；重建网格后必须对新网格重跑几何/选择预检，
   旧证据（`precheck-b2-phase2-v5-aggregate`）**不得**直接沿用。
3. **带宽 / `fB` / 平坦度全部重算**：`f_high`、`fc`、`FBW`、`flatness_15_25`、`flatness_10_30`、
   `band_overlap_*`、`Ptot/|Vave|²` 峰位**全部**会变，不能复用任何旧值。
4. **峰值顶边界问题是否缓解：需重新统计，不得预设**。扩到 45 MHz 只是**有可能**把上边频包进来；
   无数据前无法断言，必须用新数据重跑 `*_upper_bound_not_found` / `*_peak_at_upper_boundary` 统计。
5. **两批（legacy/反相）口径是否仍可比：需重新论证**。legacy 批是 35 MHz 网格产出的；
   若反相批用 45 MHz 网格，则两批 `model_sha256` 不同**且网格离散不同** ⇒ 归一化对照
   （`legacy_vs_reverse_normalized`）的前提「控制面同一 + 网格上界同一」**不再成立**；
   在拿到 legacy 侧 45 MHz 数据（或网格桥接证据）前，跨批对照**不得**继续。
6. **插值口径与不确定度需重估**：若仍按 5 MHz 步长，插值不确定度同阶问题不解决；
   若改为 0.5 MHz 步长（精扫计划 5–45 MHz @0.5 MHz = 81 点），
   `interp_edge_spread_*` 需按新步长重算，「粗估」结论应相应更新。
7. **归一化与来源分离不受影响但需复述**：驱动口径（legacy `|Vdiff|` 来自人反馈、反相 2 V）与频段无关；
   重算产物仍须逐行带 `source_run_id`/`source_file_sha256` 与来源分离标注。
8. **授权状态需重新判定**：即便 45 MHz 数据到位，**LT2 未通过前仍不得制作正式反相排名**；
   `FORMAL_RANKING_AUTHORIZED` 不得因扩频段而放宽。
9. **7R 轴向声压仍缺**：扩到 45 MHz **不解决**最终主判据问题——
   `H_p(f)=|p(f,0,0,7R)|/|V|` 仍需 COMSOL 场级导出与坐标原点平移，本轮**未实现**。

## 5. 产物路径与 sha256

工具：`work\tools\lt3_prep.py`，137,711 B，
sha256 `5b53b1d7c15e22f4cb91382116c08fb4bcdb925c74ae7c0d5382f6317bee3c55`
（参数化前为 `0af7b4d70817e2c4…`）

| 产物 | 字节 | sha256 |
|---|---|---|
| `work\lt3\lt3_45mhz_data_gap.json` | 7,407 | `32ceef45a40e7da9f4636cab9702485f765a58168496dcbaedcc6922183dcaeb` |
| `work\lt3\lt3_band_parameterization_check.json` | 5,709 | `465db2b2023672f439d045138b95da16cce8b0de7d6eaa3006d24adf93d35231` |
| `work\lt3\lt3_response_metrics.csv`（162×93） | 201,501 | `275335756c6d839359ca8257f47e6a724efb8b86a191b9b172ad5c033c6fe36d` |
| `work\lt3\lt3_response_metrics_contract.md` | 11,806 | `0fd516dfa17990d8bf13cf661a658f7d65e20316ec1771b1e65bf435a7c6a29a` |
| `work\lt3\lt3_metrics.csv`（162 行） | 384,869 | `2f2abcbdbe58fe5bc2c64e796a76cae22ef98e7de2406929f91a8933c371e6de` |
| `work\lt3\lt3_pareto.csv` | 420,088 | `9d232343899721e338833646d8ef8f10c3d3ffdebc49f4ca20db520c9e082c50` |
| `work\lt3\lt3_quality_report.json` | 34,465 | `2106660d92b8e0be59af2dbbeaba017a5c290b8fbd671e6641f24c7032bb1e48` |
| `work\lt3\lt3_normalization_contract.md` | 8,064 | `eab633b41cac664263b7ba6438b14921f7a1673703185372a28a3ea7e6ac1522` |
| `work\lt3\lt3_manifest.json`（14 项，已排除 `_*`） | 3,712 | `701e3438ed1c3d732ac2b469c3adb9f0f5d371acb2875f1264c3c8f0c5e42a5c` |
| **未变**：`lt3_pareto_pairs.csv` | 43,498 | `6027f0762921172281334494533e67b54516a0129af7ea2d83caa8e1fb7a20b1` |
| **未变**：`lt3_ranking.csv` | 20,901 | `76d5315c81c5469b10f84b95463cbf1ae8772f6cdec9ac55add51763c0c0bcf6` |
| **未变**：`lt3_pareto_dominance.csv` | 659,355 | `db139d6ccaf88f07b8176e75752b50c7db39d249855edc33042a81ae5c768c0d` |
| **未变**：`lt3_ranking_status.json` | 1,266 | `f338ff9e6c8557a5670c02a453d0c071a0a9ccc5a3626f51fed77949b23c4f1d` |
| **未变**：`legacy_vs_reverse_normalized.csv` | 30,199 | `ec69687568545f6b50660a4b74657c1e3af7d4e9140cc2c686e13d396da5a7a2` |
| **未变**：`lt3_legacy_vs_reverse_normalized.md` | 5,944 | `209c7f52d7f8bf39da20a955ea7389f72e62b86d413b472548f6d2bfe72e31d0` |
| 旧产物快照（append-only） | — | `work\lt3\_v1_band35_preserved\`（13 文件 + `_preserved_manifest.json`，工具 `0af7b4d7…`） |
| 演示产物（非主口径） | — | `work\lt3\_demo_band45\`（`band_source=cli`、`band_max=45`，**无 >35 MHz 数值**） |
| 一次性证据脚本（非交付主体） | 13,620 | `9b868a9c7a70cdee6ade0a33617eb8641b595190a2bf661575120dbbe32d81da` |

守卫验证产物 `work\lt3\_guard_test_reverse\`（反相 15 点，exit 3）仍**无**
`lt3_pareto*.csv` / `lt3_ranking*.csv` / `legacy_vs_reverse_normalized.csv`。

## 6. 未验证 / 限制

**未验证**

- **45 MHz 的一切**：数据不存在；`f_high`/`FBW`/平坦度/是否缓解顶边界**全部未知**，本轮**未生成、未推测**。
- **`b_GE_task3_2new_currentdrive_fmax45_v1.mph` 的实际 `fmax`**：未用 API 核验（文件名不足以作证）。
- **LT2-C 控制面在 45 MHz 网格下是否成立**：未验证（需重跑预检）。
- **网格可比性**：35 MHz 与 45 MHz 网格之间的桥接/收敛证据**不存在**。
- **7R 轴向声压**：需 COMSOL，**未实现**（仍为最终主判据的缺口）。
- 反相侧带宽：LT1 仅 3 频点，点数不足以算 −6 dB 带宽 ⇒ **不出反相侧带宽结论**。

**限制**

| 限制 | 说明 |
|---|---|
| 不外推 | `--band-max-mhz` 只改变**声明的界**，不生成界外数值；界外边频仍标 `*_bound_not_found`（已实测：声明 45 MHz 时 `f_high_Ptot` 最大仍只有 28.94 MHz） |
| 标记语义依赖声明界 | `*_peak_at_*_boundary` 随 `--band-*` 变化（实测 83→0）；**不得**把该计数下降当作问题缓解，须同时看 `*_bound_not_found`（不变，153） |
| 分辨率 | 仍是 7 频点 / 步长 5 MHz；带宽皆插值粗估；FBW 口径差中位 7.3（`Vave`）～27.6（`Ptot`）个百分点，**与 FBW 同阶** |
| 顶边界 | 谐振未被频段包住；不得据此选「最优参数」，不得解释为无限带宽 |
| 授权 | **仍不得制作正式反相排名**（LT2 = `BLOCKED_BEFORE_PRODUCTION`）；一切产出 `provisional_legacy_not_formal`、`formal_ranking = false` |
| 无新指标 | 本轮**未新增**任何指标；四对 Pareto 与 P2 前沿（4 点，`x=0.75`、`N1=2…5`）结论**不变** |
| 来源分离 | legacy 归一化分母仍来自人反馈 `fb-20260914-legacy-drive-amplitude`；频段参数化不涉及该分母 |
| 命名 / 外推 | `Vave` 只能称响应带宽、`Ptot` 只能称功率带宽；单元模型不得外推阵列 |

## 7. 交付声明

- 未运行 COMSOL / `comsolbatch` / `mphserver`；未改任何 `fmax`；未生成任何 45 MHz 数值；未推测 45 MHz 带宽；
- 未写 `work\runs\` 下任何内容（三个 `--out-dir` 均为 `work\lt3\` 或其 `_` 子目录）；
- 未修改任何被冻结文件（含本轮新增列出的 `repro_b_sampler.py` / `test_atomic_retry.py`；
  本会话对冻结路径**无任何写操作**）；
- 未运行 `tests_lt2_supervisor.py` / `lt2_acceptance_r4.py` / `tests_rt_gate.py` / `lt2_conc_tests.py`；
  未使用 pytest；`work\tools\check_undefined_names.py` 仅**运行**（`lt3_prep.py` 报 0 个未定义名），未修改；
- 产物只写在 `work\lt3\` 与本文件；旧产物以**快照 + 本记录**方式保留（append-only），未覆盖；
- 用户原始导出、预检产物、LT1 小样、人反馈记录、模型文件均**只读引用**。
