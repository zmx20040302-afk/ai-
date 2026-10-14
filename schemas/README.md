# `schemas/` —— MEMS Harness 契约层（机器可校验）

> 落点依据：`AGENTS.md` §5「契约与 schema → `schemas\`」。
> 本目录是**平台主线的欠账补齐**（2026-09-14），此前 `schemas\` 为空。

## 0. 为什么选 JSON Schema（而不是 Markdown + 示例）

| 选项 | 结论 |
|---|---|
| **JSON Schema Draft 2020-12（选它）** | ① 仓库**已依赖 `jsonschema`**（`pyproject.toml` dependencies）——不引入新依赖；② 能**机器校验**（本次要求），错误带关键字与字段路径，可直接作为 CI/门禁；③ 条件规则（`if/then`、`const`、`enum`）能把「红线」写成**可执行**约束，而不是靠人记住；④ 与 `store.py` 的 JSON 列（`inputs/outputs/uncertainty/quality`）天然同构 |
| Markdown + 示例 | 只能靠人读，无法 fail-closed；但**可读性更好** ⇒ 本目录保留 `README.md`（本文件）作为人读层，JSON Schema 作为机读层，二者互补 |
| 直接写 Python dataclass/校验器 | 会把契约与实现耦合；且跨语言（未来的 Web/其它工具）不可用。**契约应独立于实现** |

**校验入口**（在仓库根执行，fail-closed：任何期望不成立 ⇒ 退出码 2）：

```powershell
# 本机是 PowerShell 5.1（无 pwsh）
work\.venv\Scripts\python.exe scripts\validate_schemas.py
work\.venv\Scripts\python.exe scripts\validate_schemas.py --verbose   # 逐条打印
```

退出码：`0` = 全部期望成立；`2` = 有期望未成立（合法样例被拒 / 非法样例未被拒 / 拒绝理由与声明不符 / 文件缺失）。

## 1. 文件清单

| 文件 | 作用 | 对应库表 |
|---|---|---|
| `sample.schema.json` | **样本契约**（核心）：六种 `source_type` 互斥且各自强制溯源 ID、`fidelity`、SI 单位 + 原始单位换算记录、逐指标不确定度、抽取器版本、`geometry_family` 与防泄漏切分字段、AI 解三件套 | `sample` + `design.geometry_family` |
| `dataset.schema.json` | **数据集契约**：按族整族切分、`leak_check_passed` 恒真、无跨族留出必须显式降级、来源/保真度构成必须声明、被排除样本必须列原因 | `dataset` |
| `evidence.schema.json` | **证据契约**：文献必须有**页码 + 原文摘录 + 摘录类型**；载体文件必须记哈希；抽取的数值保留原单位与 SI 换算 | `evidence` |
| `experiment.schema.json` | **实验契约**：器件/条件/原始数据哈希/测量不确定度/仪器校准期；与仿真比对必须声明基准 | `experiment` |
| `feedback.schema.json` | **人反馈契约**：`correct` 必须带修正值、必须给理由（可复核）、append-only 取代关系 | `feedback` |
| `run.schema.json` | **运行契约**：可复现单元；成功必须 `exit_code=0`、失败必须带诊断分类、**缺什么就声明什么**（`provenance_gaps`） | `run` |
| `device_spec.schema.json` | **器件规格（器件无关）**：参数/目标/约束/公共点集/保真度；器件专有内容只能进 `extensions`（顶层 `additionalProperties:false` 强制） | 落 `work\devices\<name>\device_spec.yaml` |
| `task_spec.schema.json` | **任务合同（器件无关）**：目标/约束/可改参数/硬预算/停止条件/审批/交付物；参数与目标只能引用 `device_spec` 已声明的名字 | 人写的唯一必填输入（`WORKING_PLAN` §4.7.2） |
| `verification_verdict.schema.json` | **A8 验证与冻结裁定**：7 项字节/证据检查 + `not_checked` + fail-closed 语义；`release_allowed` 仅 `verdict=passed` 为真 | 代码产物（`work/runs/**/verdicts.json`，非库表） |
| `scan_analysis.schema.json` | **A5 扫描分析**：逐 `(family, metric)` 排名 + 口径声明 + 质量门排除条目逐条单列 + 逐族判定；**结构上没有加权/总分字段**（`no_composite_score` 恒真） | 代码产物（`scripts/run_sweep_analysis.py`） |
| `next_batch.schema.json` | **A5 下一批选点**：只在已声明候选网格上、每个建议必须带依据（实测邻居 ID + 一阶差分幅度）、成本与停止条件；上游未放行 ⇒ `blocked` 且 `selected` 为空 | 代码产物（同上） |
| `analysis_report.schema.json` | **A9 可溯源报告**：每个数值必须挂 `run_id/evidence_id/experiment_id/feedback_id`；必需段落（含非空 `not_checked`/`failures`）；缺口五要素；`publish_allowed` 仅 `verdict=passed` 为真 | 代码产物（`scripts/run_report_augment.py`） |
| `../scripts/validate_schemas.py` | **校验入口**（2026-09-14 由本目录移入 `scripts\`，内容等价、仅改路径推导）：schema 校验 + 15 项语义检查 + 期望比对（`examples/manifest.json`） | — |
| `examples/valid/*` | **合法样例**（8 个）：全部取自本机**实测**数据，逐字段标注来源 | — |
| `examples/invalid/*` | **非法样例**（17 个）：**非数据夹具**，故意违规，用于证明校验会拒绝 | — |
| `examples/manifest.json` | 期望清单：每个非法样例「期望被哪个关键字/哪个语义检查拒绝」+ 对应红线 | — |

### 1.1 红线 → 可执行约束 的对应表

| 红线（`AGENTS.md` §2） | 机械执行点 |
|---|---|
| 1 没有证据就不出数字 | `sample` 按来源强制 `run_id`/`evidence_id`/`experiment_id`/`feedback_id`/`model_id`；`evidence` 强制页码+原文摘录；`run` 失败必须带诊断；语义检查 S2（文献证据必须可解析） |
| 4 来源永不混同 | `sample` 的条件规则**同时**要求对应 ID 且**置空其它来源 ID**（`simulation` 带 `evidence_id` 即被拒） |
| 6 历史 append-only | `dataset.supersedes` / `feedback.supersedes`；契约破坏性变更必须升 `contract_version`（老样例不原地改写） |
| 7 AI 解必须有界 | `ai_solver` 分支强制 `model_id` + `uncertainty` + `ai_solver{validation_level, field_error_bound, applicability.in_scope=true}`；禁止携带 `run_id` |
| 8 AI 解是独立来源 | `source_type=ai_solver` 与 `simulation` 互斥；`model_state` 必填（不得把 draft 说成已验证） |
| 器件无关（`WORKING_PLAN` D1） | `device_spec`/`task_spec` 顶层 `additionalProperties:false`；参数/目标名必须存在于 `device_spec`（T1/T2）；器件专有内容只能进 `extensions` |
| 防泄漏 R15 | `design.geometry_family` 必填；`dataset.split.leak_check_passed` 恒 `true`；语义检查 S1 实算族交集 |

## 2. 语义检查（JSON Schema 表达不了的部分）

在 `validate_examples.py` 中实现，清单同时写在 `examples/manifest.json`：

| id | 规则 |
|---|---|
| `S1_dataset_no_family_leak` | 训练/留出族交集必须为空；`leak_overlap_families` 必须为空；声明跨族留出时留出族不得为空 |
| `S2_literature_evidence_resolvable` | `literature` 样本的 `evidence_id` 必须解析到一条**本身合法**的 evidence 记录 |
| `S3_sample_split_group_key_matches_family` | `split.group_key` 必须等于 `design.geometry_family` |
| `S4_sample_parameter_units_cover_parameters` | 逐参数有单位；换算记录自洽（`si_value = raw_value × factor`，且原始单位≠SI 单位） |
| `S5_frequency_values_ascending` | `frequency_set.values` 严格升序不重复 |
| `S6_uncertainty_present_or_explained` | 样本级 `uncertainty` 为空时必须写明原因（哪怕分量已逐指标给出） |
| `S7_ai_solver_not_disguised_as_simulation` | AI 解不得带 `run_id`；三件套齐备；`in_scope` 必须为 true |
| `D1/D2/D3_device_spec_*` | 口径未定 / 可自动改参却无范围 / 模型哈希为空 ⇒ 必须在 `pending_human` 声明 |
| `T1..T4_task_spec_*` | 参数与目标名必须存在于 `device_spec`；范围不得越界；口径不得漂移；把 `measure_only` 观测量当目标必须在 `placeholders` 声明 |
| `R1_run_gaps_declared` | 成功运行的 `model_sha256`/`wall_seconds`/`finished_at` 为空时必须逐项出现在 `provenance_gaps` |

## 3. 样例的数值来源（红线 1：不得编造）

所有 `examples/valid/*` 的**每个数值都取自本机实测记录**，并在文件内 `source_note` + 逐字段块（`evidence.ref`/`derivation_ref`/`provenance`/`notes`）标注出处。汇总：

| 样例 | 数值来源 | 关键 provenance |
|---|---|---|
| `sample_simulation_heat_slab_2d.json` | `work\store\mems.duckdb` 表 `sample` 行 `smpl-run-20260911T013401Z-7708b95e-sim` + `design` 行 | `run_id=run-20260911T013401Z-7708b95e`；数据集 `ds-20260911T014216Z-42bf22` |
| `sample_simulation_pmut_f3_gui_sweep.json` | `sample` 行 `smpl-gui-sweep-20260912T113936Z-bd387a56-0001` + `design` 行 | `run_id=gui-sweep-20260912T113936Z-bd387a56` |
| `sample_analytic_heat_slab_2d.json` | `sample` 行 `smpl-run-20260911T013524Z-80f89728-analytic`（F0 解析参照） | 配对仿真 `related_run_id=run-20260911T013524Z-80f89728`；公式 `T_max=T0+q_in*Lx/k` 已算术验算 = 305 K |
| `dataset_heat_slab_train.json` | `dataset` 表唯一一行 | `dataset_id=ds-20260911T014216Z-42bf22`（含真实降级结论：`cross_family_holdout=false`） |
| `feedback_parameter_fmax_accept.json` | `feedback` 行 `fb-20260912T023045Z-ef2ad6aa` | 用户 2026-09-12 确认 `fmax=35 MHz` |
| `run_gui_sweep_pmut_f3.json` | `run` 行 `gui-sweep-20260912T113936Z-bd387a56` | `.mph` 哈希 `a9a177ad…`（口径：GUI 通路存 .mph 哈希） |
| `device_spec_ge_task3_draft.json` | 3 条 `feedback_id` + GUI 扫描 run 的 `settings.batch_node` + `mspec-b_GE_task3_2new.json` | 未确认项全在 `pending_human`（含**目标器件完整 SHA256 留空**） |
| `task_spec_ge_task3_draft.json` | 结构取自 `WORKING_PLAN` §4.7.2；实测值仅 3 处；其余全部列入 `placeholders` | 不得当作既定计划执行 |

**契约化改写**（不是新数值）：`extractor` 串按 `@`/`+` 拆成 `name`/`version`；库中按指标键控的 `uncertainty` 落回各 `metric`；`quality` 平铺字段归位。每次改写都在样例 `notes` 中逐条列出。

## 4. 覆盖情况：哪些来源**暂无**合法样例（如实声明）

实测（`work\store\mems.duckdb`，2026-09-14）：

```text
sample 总数            = 962
source_type 分布        = simulation(F3)=490, simulation(F2)=49, analytic(F0)=423
evidence 表行数         = 0
experiment 表行数       = 0
feedback 表行数         = 3
sample.evidence_id 非空 = 0
```

⇒ **`literature` / `experiment` / `ai_solver` 三种来源没有任何真实样本**，因此本目录**不提供**它们的合法样例（编造一条"看起来合法"的文献样例会直接违反红线 1）。它们只以「schema + 非法夹具」形式存在：

- `literature`：`invalid/sample_literature_unresolvable_evidence.json`、`invalid/evidence_literature_no_quote.json`、`invalid/evidence_literature_no_page.json`
- `experiment`：仅有 schema（`experiment.schema.json`）；库中 0 行 ⇒ 无样例
- `ai_solver`：`invalid/sample_ai_solver_missing_error_bound.json`（证明缺误差界会被拒）

**注意**：`invalid/*` 是**非数据夹具**（内容故意错误、引用是占位串），**绝不可**被引用为证据或数值。

## 5. 存量数据对新契约的符合度（实测，用于评估影响范围）

只读查询结果（未改动任何数据）：

| 项 | 数值 | 含义 |
|---|---|---|
| 样本总数 | 962 | — |
| `design.geometry_family` 可解析 | 962 / 962 | 存量分组键是齐的（0 缺失） |
| `uncertainty` 字段为空 | **417** | 违反「必须记录不确定度与方法」 |
| `uncertainty` 存在但**各分量全为 null** | **490** | 违反「分量 value=null 必须给 reason」 |
| `extractor` 为空 | 0 | 齐 |
| `quality` 为空 | 0 | 齐 |
| `evidence_id` 非空 | 0 | 无任何文献来源样本 |
| `experiment_id` / `feedback_id` / `model_id` 非空 | 0 / 0 / 0 | 同上 |

⇒ **至少 907/962（94.3%）的存量样本不满足本契约的不确定度条款**（417 缺字段 + 490 分量全 null；剩余 55 条含分量结构，未逐条判定）。

### 5.1 存量处置：`legacy_pre_contract`（**已执行**，2026-09-14 裁定）

**裁定**：契约自 **2026-09-14** 起对**新样本**强制；存量样本**不回填**、**不补 `uncertainty`**——补值等于替历史数据编一个不确定度（红线 1 + 红线 4 双重违反），空着才是如实的。

**落地方式（附加元数据，不改任何数值）**：给 `sample` 表新增一列 `contract_status`，把存量标记为 `legacy_pre_contract`。

```sql
-- 已在本机执行一次；幂等，可重跑（不会覆盖已标记的新样本之外的任何值）
BEGIN TRANSACTION;
ALTER TABLE sample ADD COLUMN IF NOT EXISTS contract_status VARCHAR;
UPDATE sample SET contract_status = 'legacy_pre_contract' WHERE contract_status IS NULL;
COMMIT;
```

**实测结果**：`n_samples before/after = 962 / 962`；`n_updated_legacy = 962`；
**数值列指纹改动前后逐字节相同**（14 个数值/溯源列的规范化 JSON 的 SHA256 =
`c3c12ae1cebf930bc3a4eecab1ece3ce9e4168de2d037a1f5ecb6e3555151181`，改写前 = 改写后）⇒ 证明**只加了列、没动数值**。

**引用存量数据时的硬规则**：
- 标了 `legacy_pre_contract` 的样本，其 `uncertainty` **一律按「缺失」处理**，不得当成「不确定度为 0」，也不得据此给出误差界或置信区间；
- 因此**不得**用存量样本声称「带误差界的结论」；只能用于历史趋势对照与管线回归；
- 想让某批存量数据参与带误差界的结论 ⇒ 只能**新增**合规样本（新记录），不能就地升级旧记录（红线 6）。

> ⚠️ **可复算的统计口径与命令**（`ADMIN`；只读，不改数据）：
> ```powershell
> work\.venv\Scripts\python.exe -c "import duckdb;con=duckdb.connect(r'work\store\mems.duckdb',read_only=True);print(con.execute('''SELECT count(*) n, sum(CASE WHEN d.geometry_family IS NULL THEN 1 ELSE 0 END) missing_family, sum(CASE WHEN s.uncertainty IS NULL THEN 1 ELSE 0 END) unc_absent, sum(CASE WHEN s.uncertainty LIKE '%\"numerical_discretization\": null%' OR s.uncertainty LIKE '%\"model_form\": null%' THEN 1 ELSE 0 END) unc_all_null FROM sample s LEFT JOIN design d ON s.design_id=d.design_id''').fetchone());print(con.execute('SELECT contract_status, count(*) FROM sample GROUP BY 1').fetchall())"
> ```
> 口径说明：`unc_absent` = `uncertainty IS NULL`；`unc_all_null` = `uncertainty` 里出现
> `"numerical_discretization": null` 或 `"model_form": null`（即分量未逐条给 reason 的那批 F3 GUI 样本）；
> `≥907/962` = `unc_absent + unc_all_null`（两个集合互斥，实测 417 + 490）。**该统计为字符串/空值判定，
> 不是逐条跑 schema**——逐条符合度未验证，见 §7。

> ⚠️ **同一限制必须写进人读层**：看到 962 条样本**不等于**962 条都能带误差界使用；
> 其中 ≥907 条的 `legacy_pre_contract` 样本的不确定度是**缺失**的。

## 6. 与现有代码的关系（本次**未改动** store.py/dataset.py）

- `store.insert_sample()` 已实现四条运行时检查（六种来源、对应溯源 ID、inputs/outputs 非空、ai_solver 必须有 uncertainty）——本契约是其**超集**：新增了 `geometry_family`、单位换算、逐分量不确定度、`frequency_set`、防泄漏切分字段、`device_spec`/`task_spec` 的器件无关约束。
- `dataset.build_dataset()`/`split_by_family()` 已强制按族整族切分并把结论写进 `dataset.report`——`dataset.schema.json` 把该结论的**形状**固定下来（并额外要求 `leak_check_passed` 恒真）。
- 契约是**独立于实现**的一层：本目录不 import `memsharness`，可被将来的 CI、Web 端或第三方工具直接复用。
- 已知不一致（已在 schema 注释中标注，未改代码）：`store.py` 注释把 `feedback.target_kind` 写成 `model|prediction|report|run`，而**实测存量数据**使用的是 `parameter`；`run.pathway` 注释只列 `livelink|comsolbatch|template`，而实测存在 `comsol-gui-batch`。契约按**实测**取值。

## 7. 已知限制（不做静默处理）

1. **「用 0 冒充未知」只能机械拦住 `uncertainty.value=0`**（要求显式 `zero_is_known=true`）；把 0 写进 `metrics.value` 冒充真实读数无法机械识别，需人工审查 + `quality.flags`。
2. **`S2` 的证据索引当前是「样例集」**（`examples/valid/*`），而**不是** `work\store\mems.duckdb`：因为库中 evidence 表 0 行。这意味着现在任何 `literature` 样本都会被 S2 拒绝——这是**如实反映**，不是缺陷；接入真实文献后应把索引改为读库。
3. **JSON Schema 不能表达数值区间交集**（如「留出集必须含未见族」的完整语义），因此这类规则放在语义检查里，Python 实现需与 README 同步维护。
4. **`device_spec` 的 `pending_human` 是必填且非空**——这是刻意的：任何一个器件在接入当天都不可能"全确认"，强迫写清未确认项比假装完备安全。
5. ~~**`sample.contract_status` 只存在于本机库文件里**~~ —— ✅ **已闭环（2026-09-14 追加）**：该列已补进 `src\memsharness\store.py` 的
   `SCHEMA_SQL`（`sample` 建表语句）**与** `MIGRATIONS`（`ALTER TABLE sample ADD COLUMN IF NOT EXISTS contract_status VARCHAR`），
   与 `evidence_id`/`model_id` 等列同一处理方式：可空、默认 `NULL`。
   **自证**：① 新建库 → `sample` 16 列、含 `contract_status VARCHAR / is_nullable=YES / default=NULL`；② 模拟旧库（`sample` 不含该列）跑 `init_schema()` → 被 `MIGRATIONS` 补上（补列前 False → 补列后 True）；③ 现有库再跑幂等迁移 → `n_samples 962→962`、`contract_status` 计数不变（`legacy_pre_contract`=962）；④ 数值列指纹迁移前后 = `c3c12ae1cebf930bc3a4eecab1ece3ce9e4168de2d037a1f5ecb6e3555151181`（与打标记前一致）⇒ 补 schema 定义**未碰任何数值**。
   ⇒ 新建库/迁移**不再静默丢列**，契约的人读层与数据层重新一致。
