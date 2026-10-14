# TO_CODEX 记录：LT3-D 归一化阻塞解除 + legacy vs 反相并排对照（2026-09-14）

- 性质：**准备性工作**（承接 `docs\TO_CODEX_record-20260914-lt3-prep-pipeline.md`，**不覆盖**该记录）
- 触发：用户人反馈给出 legacy 批次2 的 `|Vdiff|`
- **未运行 COMSOL / comsolbatch / mphserver**；**未写 `work\runs\`**；**未改任何被冻结文件**
- 状态：`provisional_legacy_vs_reverse_normalized_not_formal`，`formal_ranking = false`
  （LT2 未通过 ⇒ **仍不得制作正式反相排名**）

---

## 1. 人反馈来源（红线 4：来源永不混同）

| 项 | 内容 |
|---|---|
| 来源文件 | `docs\TO_USER-feedback-20260914-legacy-drive-amplitude.md` |
| sha256 | `4d09c6ffe1ab2b8f6d615e8efea71b8223bf1a79793e246eceb160703b8b3476` |
| `source_type` | **`human_feedback`** |
| `feedback_id` | `fb-20260914-legacy-drive-amplitude` |
| 用户原话 | 「legacy 批次2使用 v0=1 V；实际工况为内电极 −1 V，外电极经 1 Ω 支路近接 0 V，所以有效差分激励约为 1 V。该数据不是 ±1 V 反相驱动。」 |

提取量（**人反馈**，不是模型读数、不是导出表）：

```text
legacy  |Vdiff| = 1.000 V   （用户原话为「约」）
reverse |Vdiff| = 2 V       （vamp=1 V 反相：pot1=+1, pot2=-1）
关键：legacy 不是 ±1 V 反相驱动
```

**归一化量的来源是分离的**（这一条必须随任何结论声明）：

| 角色 | 量 | `source_type` | 值 |
|---|---|---|---|
| **分子** | `Ptot` / `Vave` | `simulation` | 各自 COMSOL 导出表列 |
| **分母（legacy）** | `abs(Vdiff)` | **`human_feedback`** | 1.000 V（`fb-20260914-legacy-drive-amplitude`） |
| **分母（反相）** | `abs(Vdiff)` | `simulation` | 2 V（导出 `Vdiff_abs` 列 / drive manifest） |

⇒ 归一化量是**混合来源**（simulation + human_feedback）。
**不得**把 legacy 的归一化量写成「由模型或导出表得到」：
批次2 导出表**没有**任何电位/差分电压列（表头实核：`x_scale, N_w_te1, freq (Hz), Zin1_R/X, Zin2_R/X,
Ptot (W), V_center (m/s), Vave (m/s)`），分母只能来自人反馈。

---

## 2. 命令与退出码

解释器 `work\.venv\Scripts\python.exe`。

### 运行 A —— legacy 主批 + 人反馈分母 + LT3-D 对照（**exit 0**）

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

### 守卫验证（全部 fail-closed）

| 运行 | 输入 / 参数 | exit |
|---|---|---|
| B | 反相数据（LT1 15 点），`--out-dir work\lt3\_guard_test_reverse` | **3**（拒绝排名/Pareto，只出中间量） |
| C | 反相数据 + `--legacy-vdiff-V`（人反馈分母只能用于 legacy） | **2** |
| D | `--legacy-vdiff-V` 但缺 `--legacy-vdiff-feedback-doc` | **2** |
| E | `--formal`（请求正式排名） | **2** |
| F | `--out-dir work\runs\...` | **2**（且不创建文件） |

---

## 3. 产物路径与 sha256

工具：`work\tools\lt3_prep.py`，94,223 B，
sha256 `566320b07c70987788c9f6bd2889dc85ebdbfd8779af33d355a2fef6251f6c31`

### 3.1 主交付（`work\lt3\`，运行 A）

| 产物 | 字节 | sha256 |
|---|---|---|
| `work\lt3\legacy_vs_reverse_normalized.csv` | 30,199 | `ec69687568545f6b50660a4b74657c1e3af7d4e9140cc2c686e13d396da5a7a2` |
| `work\lt3\lt3_legacy_vs_reverse_normalized.md` | 5,944 | `209c7f52d7f8bf39da20a955ea7389f72e62b86d413b472548f6d2bfe72e31d0` |
| `work\lt3\lt3_normalization_contract.md` | 8,064 | `f03289d71c67e5e1259649ae4e7c6059a7e30a34f579ccd99698845b4b756fc2` |
| `work\lt3\lt3_metrics.csv` | 222,039 | `e5321a297ba8ba40d725c7f50a1f73276a61f249a06a1eb3a5af2c47cf100e0a` |
| `work\lt3\lt3_ranking.csv` | 20,901 | `76d5315c81c5469b10f84b95463cbf1ae8772f6cdec9ac55add51763c0c0bcf6` |
| `work\lt3\lt3_pareto.csv` | 257,258 | `b70ab0765f7e676f84829c0613a6a16f6f3d6a3573281af3de5aee28d54116bf` |
| `work\lt3\lt3_pareto_dominance.csv` | 659,355 | `db139d6ccaf88f07b8176e75752b50c7db39d249855edc33042a81ae5c768c0d` |
| `work\lt3\lt3_quality_report.json` | 13,228 | `240b851966d3e2bafb0b6d2168f3c9116c2a9e89c09601226ee49c7f741e9dc2` |
| `work\lt3\lt3_ranking_status.json` | 1,266 | `f338ff9e6c8557a5670c02a453d0c071a0a9ccc5a3626f51fed77949b23c4f1d` |
| `work\lt3\lt3_manifest.json` | 3,034 | `f879de53f8c4ba9ead608888ddd60b1c791568a2ea8149c57ca44426486bfd80` |

### 3.2 守卫验证产物（`work\lt3\_guard_test_reverse\`，运行 B）

| 产物 | 字节 | sha256 |
|---|---|---|
| `lt3_guard_refusal.json` | 1,215 | `f56c3842ab7a4199da517c133ff8f1f4a8fbadcdace0f182a38801004189b764` |
| `lt3_intermediate_comparison.csv` | 1,596 | `7d03affd393c4893d8334ff0bf91d9310e61e4999a97c6597c7c39de782a81b9` |
| `lt3_quality_report.json` | 8,588 | `6cb115a2b11341fac01767bea31003fcca4b7f5c1bcedc7d03dc4ef2eb033f7a` |
| `lt3_metrics.csv` | 3,672 | `7658dfe7751e9935d09f8bcf2130e8d9279b6d89f79421cefe09f41227a50476` |
| `lt3_normalization_contract.md` | 6,224 | `07f8952d010bf9cb8f4f56e6a5b556ecbd4a80c4ec0317009b49dea6c866fb26` |
| `lt3_manifest.json` | 1,966 | `52490bb676dc71acde5a5d8098b253934f196e8dcf24dc80f0b5d375ade9c9f9` |

**该目录下无** `lt3_pareto.csv` / `lt3_pareto_dominance.csv` / `lt3_ranking.csv` / `lt3_ranking_status.json`
/ `legacy_vs_reverse_normalized.csv`。

---

## 4. 落实来源分离标注的位置（逐项可查）

| 要求 | 落实位置 |
|---|---|
| `normalization_denominator_source = human_feedback` | `lt3_metrics.csv`、`legacy_vs_reverse_normalized.csv` **每一行**的 `normalization_denominator_source_legacy`（162/162 与 15/15 均为 `human_feedback`） |
| `feedback_id` | 同上每一行的 `normalization_denominator_feedback_id`（= `fb-20260914-legacy-drive-amplitude`） |
| 原话摘要 | 同上每一行的 `normalization_denominator_quote`；`lt3_quality_report.json` → `normalization_source_separation.denominator_legacy.quote` |
| 证据文件 sha256 | 同上 `normalization_denominator_evidence_sha256` = `4d09c6ffe1ab2b8f…` |
| 「不得写成由模型/导出表得到」 | `lt3_quality_report.json` → `...denominator_legacy.must_not_be_described_as = "由模型或导出表得到"`；`lt3_normalization_contract.md` §3b 明文；`lt3_legacy_vs_reverse_normalized.md` §1 明文 |
| 分子来源 | 每行 `normalization_numerator_source_type = simulation` + `source_file_sha256_legacy` |
| 限制随产物保留 | 每行 `normalization_limitation`；契约 §3c；对照 MD §3；质量报告 `...denominator_legacy.limitation` —— 均为 `LEGACY_VDIFF_LIMITATION` 常量（**写在代码里**，`work\tools\lt3_prep.py`） |

### 4.1 必须保留的限制（原文照录）

> 用户原话为「**约** 1 V」。外电极经 1 Ω 支路接参考端时其电位并非精确 0 V（有电流即有压降），
> 故 `|Vdiff|` 严格小于 1 V ⇒ 用 1.000 V 做分母引入一个**方向已知、量级未量化**的系统偏差。
> 该量级**无法从现有资料界定**：本应由电气电流/阻抗量估计，而那些量已因 LT0-C 实测
> KCL 相对误差 16.6–18.9% > 1% 被整体排除。**不得编造 `V_outer` 数值**；只能如实标为未量化的限制。

本目录内**没有** `V_outer` 的数值；也**没有**用任何电气量去反推该偏差。

---

## 5. 对照表规模与关键数字

对照表：`work\lt3\legacy_vs_reverse_normalized.csv`（sha256 `ec69687568545f6b…`）

| 项 | 值 |
|---|---|
| 规模 | **15 行 = 5 组合 × 3 频点（5 / 20 / 35 MHz）** |
| 组合 | `(0.45,6)`、`(0.5,5)`、`(0.6,4)`、`(0.7,5)`、`(0.75,5)` |
| 反相侧来源 | `work\runs\lt1-reverse-sample\lt1_validated_results_v2.csv`（15 行，sha256 `43d5711cbb2d7141…`） |
| legacy 侧匹配 | 15/15 全部匹配（`unmatched_reverse_rows = []`） |
| 反相侧自带归一量交叉核对 | 15 行全查，**0 处不一致**（我用 `/4`、`/2` 与文件自带 `Ptot_norm`/`Vave_norm` 逐位核对） |
| 原始 `Ptot` 比值 | **0.8377 – 4.297** |
| 归一化后 `Ptot_norm` 比值 | **0.2094 – 1.0743** |
| 归一化后 `Vave_norm` 比值 | **0.3860 – 1.0436** |

### 5.1 关键实质发现（不得省略）

1. **原始 `Ptot` 比值并不恒为 4**（实测 0.84–4.30）。理论上的 `4 = 2²` 是**电压因子**，
   只在电压是唯一差异时成立；实测比值离散，说明两批差异**不只是电压缩放**。
2. **归一化后两批并不可比到一致**：`Ptot_norm` 比值仍跨 0.21–1.07，`Vave_norm` 比值跨 0.39–1.04。
   归一化只消去了驱动电压因子；**残余偏差来自两批的模型/选择/网格差异**
   （`model_sha256` 不同）。
   ⇒ **不得**把归一化后的差异解读为结构收益或结构劣势；
   本表只能说明「**电压口径已对齐**」，**不能**说明「两批物理一致」。
3. **示范性对照，不是完整对比**：反相侧目前只有 LT1 的 15 点；
   LT2 的 504 点（72 组合 × 7 频点）**尚不存在**。
   本表只证明**管线与口径可用**，不能用于任何工程判断或排名。

### 5.2 可比性前提（逐条，逐行留痕）

| 前提 | 状态（本表实测） |
|---|---|
| 控制面同一：`intop5 == swr1` | 15/15 `True`（来自 level-2 预检聚合） |
| 控制面同一：`intop5 == efc1` | 15/15 `True` |
| `area_ptot` / bbox 唯一 | 15/15 `single_value_in_aggregate`（聚合 manifest：`area_ptot` 唯一值 1 个、bbox 唯一 1 个） |
| 网格上界同一（`fmax = 35 MHz`） | `declared_not_independently_verified`（**本脚本未独立核验网格**） |
| 几何族可比 | `declared_same_device_family_not_independently_verified` |
| `model_sha256` 不同 | 15/15 `True`：legacy `0f75ca1df9262f27…`（来自 `aggregate_manifest.json` 的 `source_model_sha256`）vs 反相 `cbe9ccc18e51005f…`（来自 LT1 表的 `model_sha256` 列）⇒ **只能并排对照，不得合并成同一来源的统计** |

### 5.3 频率单位归一（本轮修掉的一个真实缺陷）

批次2 导出列名为 `freq (Hz)`，LT1 反相表列名为 `freq_MHz`。
脚本第一版按「一律 Hz」处理，导致反相 `20 MHz` 被当成 `20 Hz`，
**15/15 行 join 全部失败**（`unmatched` 15 条）。
已修：新增 `freq_scale_to_hz()`，按**列名**判定单位（`GHz/MHz/kHz/Hz`），
列名无单位时按量级启发式判定并把 `heuristic_assumption=True` 留痕，
读表后**就地归一到 Hz**，再统一按 `f/1e6 → MHz` 处理（`dataset-contract` §5：禁止 Hz 与 MHz 混为同一列）。
本批实测：legacy `freq (Hz)` → ×1（`column_name_hz`）；反相 `freq_MHz` → ×1e6（`column_name_mhz`），**均非启发式**。

### 5.4 另一处修正：预检记录合并优先级

聚合预检 JSON 同时含 `phase2_rows`（72 组，**含控制面证据**）与 `phase1_rows_with_pattern_id`（162 组，含资格判定）。
第一版按 `phase2 → phase1` 顺序载入 ⇒ phase1 覆盖 phase2，**丢失 `intop5_eq_*` / bbox 证据**。
已改为 `phase1 → phase2`（phase2 最后载入，覆盖/补充），既保住 162 组的资格判定，又拿到 72 组的控制面证据。
`precheck_class` 取该记录里的 `classification`（若有）否则 `eligibility_level`；聚合件记录的是后者，
`full = 预检全量合格`（等价于 `sweep-analysis` SOP 的 `clean` 排名资格），已在质量报告 `precheck.class_semantics` 写明。

---

## 6. 已实现 / 未验证 / 限制

### 6.1 已实现（本机实测，exit 0/2/3 均可复现）

- `legacy_export_lacks_Vdiff__normalization_not_computable` **按人反馈解除**：
  legacy `Ptot_norm = Ptot/1²`、`Vave_norm = Vave/1`；反相 `/4` 与 `/2`（沿用已固化契约）；
  `lt3_metrics.csv` 162/162 行归一化量已算出，`normalization_reason` 全为空。
- **来源分离**：分子/分母 `source_type` 分列，逐行带 `feedback_id`、原话摘要、证据文件 sha256。
- `legacy_vs_reverse_normalized.csv`（15 行）并排对照 + 逐行 `source_run_id` 与源文件 sha256。
- 状态恒为 `provisional_legacy_vs_reverse_normalized_not_formal`、`formal_ranking = false`。
- 可比性前提逐条进 CSV（控制面 15/15 已验；网格与几何族标为「仅声明，未独立核验」）。
- 归一化契约与限制**写进代码常量**（`LEGACY_VDIFF_LIMITATION`、`LEGACY_VDIFF_SOURCE_TYPE`、
  `LEGACY_VDIFF_FEEDBACK_ID`），并导出到契约 MD、对照 MD、质量报告、逐行 CSV。
- 新增守卫：人反馈分母只能用于 legacy（否则 exit 2）；给了值但缺 `feedback_id`/证据文件 → exit 2。

### 6.2 未验证

- **归一化后两批为何仍不一致，未查明**：残余 0.21–1.07 的比值差异**未归因**。
  候选原因（模型/选择集/网格差异）本轮**没有独立证据**，故只陈述「不一致」，**不做归因**。
- **`|Vdiff|` 的偏差量级未量化**：用户原话为「约 1 V」；因电气量被整体排除，无法估计。
- 网格上界是否两批真为 35 MHz、几何族是否真可比：**仅据工单/清单声明，未独立核验**。
- 反相侧 `Ptot`/`Vave` 的抽取器一致性：仅核对了其自带 `Ptot_norm`/`Vave_norm` 与我的 `/4`、`/2` 一致（15/15），
  **未核对**其 `Ptot`/`Vave` 的抽取过程。
- LT2 504 点数据不存在 ⇒ **完整对照未做**。
- `-6 dB` 带宽 / `FBW` / 平坦度 / 7R 轴向声压：**未实现**（LT3-B，需数据 + COMSOL）。本轮对照表**不含**这些量。

### 6.3 限制

| 限制 | 说明 |
|---|---|
| legacy 归一化分母是人反馈且为「约」值 | 引入**方向已知、量级未量化**的系统偏差（用 1.000 V 偏大 ⇒ 归一化后 legacy 值偏小）。**不得**编造 `V_outer` 或用电气量反推。 |
| 归一化 ≠ 可比到一致 | 见 §5.1 第 2 条；**不得**把残余差异读成结构收益。 |
| 原始 `Ptot` 比值不恒为 4 | 见 §5.1 第 1 条；「约 4 倍差 = 电压所致」是**理论电压因子**，实测比值有离散。 |
| 仅 15 点、1 个频点集 | **示范性对照**，不构成完整对比，不得用于工程判断或排名。 |
| 仍不得正式排名 | LT2 = `BLOCKED_BEFORE_PRODUCTION`；本表只是诊断/中间产物。 |
| 来源不得混同 | 两批 `model_sha256` 不同 ⇒ 只能并排；**禁止**合并成同一来源的统计或平均值。 |
| 电气量仍整体排除 | LT0-C KCL 16.6–18.9% > 1%；归一化只作用于声学量，**不改变**该排除。 |
| 命名限制 | `Vave` 是**面平均法向速度（响应量）**；`Ptot` 是**发射声功率**。不得称往返/脉冲回波/阵列带宽。 |
| 外推限制 | 单 PMUT 单元模型结论**不得**外推为阵列性能。 |

---

## 7. 交付声明

- 未运行 COMSOL / `comsolbatch` / `mphserver`；
- 未写 `work\runs\` 下任何内容（运行 A/B 的 `--out-dir` 均在 `work\lt3\`；`--out-dir work\runs\...` 已被实测拒绝 exit 2）；
- 未修改任何被冻结文件（`lt2_production.py` / `lt2_sampler.py` / `tests_lt2_supervisor.py` / `rt_gate.py` /
  `tests_rt_gate.py` / `lt2r0_v2.py` / `lt2_acceptance_r4.py` / `lt2_flake_hunt.py` / `check_undefined_names.py` /
  `freeze_snapshot.py` / `check_r3_conditions.py` / `AGENTS.md` / `WORKING_PLAN.md`）；
- 未运行 `tests_lt2_supervisor.py` / `lt2_acceptance_r4.py` / `tests_rt_gate.py`；未使用 pytest；
- 产物只写在 `work\lt3\` 与本文件；用户原始导出与人反馈记录文件均**只读引用**
  （人反馈文件只取 sha256，未改动）；
- 本记录**不覆盖** `docs\TO_CODEX_record-20260914-lt3-prep-pipeline.md`（历史 append-only，
  该文件另有后继更正附录）。

---

## 附：后继更正（2026-09-14，**append-only**，不覆盖上文）

> 依据 `AGENTS.md` 红线 6：本附录只**新增**。
> 其后补齐了 LT3-B 频响形状类指标（−6 dB 带宽 / FBW / 平坦度 / 带宽交叠）并重算了 Pareto，
> 最新哈希与结论见 `docs\TO_CODEX_record-20260914-lt3b-response-metrics.md`。

**被取代的产物哈希**（上文 §3.1 所记，已失效）：

| 产物 | 旧 sha256（上文） | 新 sha256 |
|---|---|---|
| `work\lt3\lt3_metrics.csv` | `e5321a297ba8ba40…` | `fa2aff7b9689d3e80ac15c4cdfab6d298cf06ae4eeb9342b2341da05640aba20` |
| `work\lt3\lt3_quality_report.json` | `240b851966d3e2ba…` | `74e58fa88d4d658ffa8a65db796e4437ddd1812e05e1918fc7157bf39fc83322` |
| `work\lt3\lt3_normalization_contract.md` | `f03289d71c67e5e1…` | `946b37515f7fb4b8be9d3bf3cb3cf11a0eba4c64488b779789799ad24aeea9bc` |
| `work\lt3\lt3_pareto.csv` | `b70ab0765f7e676f…` | `6ae6f9f5b84180260b3772650a1b324a9f9c9296a739de8ee745d7cfe27b5bbe` |
| `work\lt3\lt3_manifest.json` | `f879de53f8c4ba9e…` | `2be7e4977d7819caad305a06d3b3aa429225125d2d9b06980935315de6c21b87` |
| `work\tools\lt3_prep.py` | `566320b07c709877…` | `0af7b4d70817e2c4f1ec6a7efd71cbba11e2b5c7449fb02ce8b845cfe8393248` |

**哈希未变**（仍可用）：`work\lt3\legacy_vs_reverse_normalized.csv` `ec69687568545f6b…`、
`work\lt3\lt3_legacy_vs_reverse_normalized.md` `209c7f52d7f8bf39…`、
`work\lt3\lt3_ranking.csv` `76d5315c81c5469b…`、
`work\lt3\lt3_pareto_dominance.csv` `db139d6ccaf88f07…`、
`work\lt3\lt3_ranking_status.json` `f338ff9e6c8557a5…`、
`work\lt3\_guard_test_reverse\lt3_guard_refusal.json` `f56c3842ab7a4199…`、`work\lt3\inputs\*`。

**上文 §6.2「未验证」中「−6 dB 带宽 / FBW / 平坦度…未实现」一条现已部分实现**：
带宽/FBW/平坦度/带宽交叠**已实现**（见后继记录）；**7R 轴向声压仍需 COMSOL，仍未实现**。
上文 §5.1~§5.4 的对照结论**不变**（15 行、原始 `Ptot` 比值 0.8377–4.297、归一化后仍不可比到一致、
频率单位归一修复、预检合并优先级修复）。

