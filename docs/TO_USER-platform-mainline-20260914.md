# 致用户：平台主线独立欠账交付（schemas 契约 / pytest 收集失败 / MCP P0-2·P0-6）

> 日期：2026-09-14｜执行者：平台主线独立欠账 agent（DSH 会话，工作区 `C:\Users\zmx\Desktop\memsharness`）
> 证据等级标记：`[实测]` 现场命令产出 / `[静态可复核]` 读文件或算数得出的确定结论 / `[待核实]` 需要人确认
> 本任务**与 COMSOL 求解无关**；全程未运行 COMSOL/comsolbatch/mphserver，未调用任何 MCP 求解类工具。

---

## 0. 交付总览与边界

| 项 | 结果 |
|---|---|
| 任务 1 `schemas\` 契约 | ✅ 建成：8 个 JSON Schema + 校验入口 `scripts\validate_schemas.py` + 8 合法样例 + 17 非法样例；退出码 **0** `[实测]` |
| 任务 2 `pytest -q` 收集失败 | ⚠️ **当前不复现且稳定**：连续 3 次 `pytest -q` = **240 passed, 4 skipped, exit 0**（`pytest_recovered_stable`，见 §7.4）；已给出诊断（基解释器缓存运行时问题）与恢复条件，并写进 `pyproject.toml` `[实测]` |
| 任务 3 P0-2（旧机路径） | ✅ `work\mcp-overlay.patch.yml` 已改本机路径；`dsh-config\` 两文件（4 行）**已按追加裁定清理并加「非权威副本」头注**（§7.2）`[实测]` |
| 任务 3 P0-6（run_id 路径校验） | ✅ MCP 侧新增 `validate_run_id()` 并挂到 5 个入口；**363 个既有 run 目录 0 误拒**；非法值全拒 `[实测]` |
| 任务 3 P0-3/P0-4/P0-5 | 📋 **未动代码**，只写建议与风险（§4） |
| 追加裁定 1（存量标记） | ✅ `sample.contract_status = 'legacy_pre_contract'`（962 行）；数值列指纹改动前后相同（§7.1）`[实测]` |
| 追加裁定 3（入口归位） | ✅ 移入 `scripts\validate_schemas.py`；三种 cwd 下 exit=0、8/17 结论不变（§7.3）`[实测]` |
| 追加裁定 4（补建库定义） | ✅ `store.py` 的 `SCHEMA_SQL` + `MIGRATIONS` 各补一处；新库含列、模拟旧库可迁移、现库 962 不变、指纹仍 `c3c12ae1…`（§7.5）`[实测]` |
| COMSOL | ❌ 未运行任何 COMSOL 步骤 |
| `work\tools\` | ❌ 未写入任何文件（仅只读引用 `lt2_production.py` 的 `validate_run_id()` 实现思路） |
| 禁改文件 | ❌ 未改 `AGENTS.md`、`WORKING_PLAN.md`、`docs\` 既有记录、`work\runs\` 任何内容 |
| 禁跑脚本 | ❌ 未运行 `tests_lt2_supervisor.py`、`lt2_acceptance_r4.py`、`tests_rt_gate.py`、`lt2_conc_tests.py` |

**新建/修改文件清单**（本次仅有这些）：

```text
新建  schemas\README.md
新建  schemas\sample.schema.json / dataset.schema.json / evidence.schema.json / experiment.schema.json
新建  schemas\feedback.schema.json / run.schema.json / device_spec.schema.json / task_spec.schema.json
新建  scripts\validate_schemas.py          （2026-09-14 由 schemas\validate_examples.py 归位，见 §7.3）
新建  schemas\examples\manifest.json
新建  schemas\examples\valid\*.json      （8 个，全部取自实测数据）
新建  schemas\examples\invalid\*.json    （17 个，非数据夹具，故意违规）
新建  docs\TO_USER-platform-mainline-20260914.md  ← 本文件
修改  src\memsharness\mcp_server.py      （仅 P0-6：新增校验函数 + 5 个入口的前置拒绝分支）
修改  work\mcp-overlay.patch.yml         （仅 P0-2：旧机路径 → 本机路径）
修改  pyproject.toml                     （仅 [tool.pytest.ini_options] 注释块：写明 DLL 故障诊断与隔离开关）
修改  src\memsharness\store.py           （仅追加裁定 4：SCHEMA_SQL + MIGRATIONS 各补 contract_status 一处，见 §7.5）
修改  dsh-config\profiles-web-cordis.patch.yml / dsh-config\agent-presets-mems\agent.cordis.yml
                                         （仅追加裁定 2：清旧机路径 + 加「非权威副本」头注，见 §7.2）
数据层 work\store\mems.duckdb            （仅追加裁定 1：sample 表新增列 contract_status 并标 962 行
                                         legacy_pre_contract；数值列指纹改动前后相同，见 §7.1）
```

**关于写入口径的两点说明**（本任务工单的"只写…"清单与具体任务条目存在交叉，按"更具体的任务条目优先"处理，均在此声明）：

1. `work\mcp-overlay.patch.yml`：工单 §任务 3 明确要求"需改为本机路径"，但 §硬性约束的写入清单未包含它。该文件是 `work\` 下的临时覆盖层（不是 `work\tools\`、不是 `work\runs\`），修改它不触碰禁改范围，故按任务条目执行。
2. `pyproject.toml`：工单任务 2 明确给出落点"用 `pytest.ini`/`pyproject.toml` 的 `collect_ignore`"，而 pytest 配置本身就在 `pyproject.toml`，故按任务条目执行（只改 `[tool.pytest.ini_options]` 段，未动依赖/构建配置）。

---

## 1. 任务 1：`schemas\` 契约

### 1.1 选择：JSON Schema Draft 2020-12（+ Markdown 人读层）

**理由**（不是偏好，是可核查的三条）：① `jsonschema` **已在** `pyproject.toml` 的 dependencies 里 ⇒ 不引入新依赖；② 要求"能机器校验"，Markdown+示例做不到 fail-closed；③ 条件规则（`if/then`、`const`、`enum`）能把**红线写成可执行约束**，例如"simulation 必须带 run_id **且** 不得夹带 evidence_id"（红线 1+4）、"`ai_solver` 必须有误差界与 S 级状态且不得带 run_id"（红线 7/8）、"`device_spec` 顶层不得出现器件专有字段"（器件无关）。
同时保留 `schemas\README.md` 作为人读层（红线↔约束对应表、语义检查清单、样例来源表）。

### 1.2 机器校验入口 + 实测输出

```powershell
# 可在任意 cwd 运行（脚本按 __file__ 推导仓库根）；本机 PowerShell 5.1，无 pwsh
work\.venv\Scripts\python.exe scripts\validate_schemas.py
```

`[实测]` 输出（节选，完整表格见命令输出）：

```text
schema 文件 8 个；样例 8 合法 / 17 非法；语义检查 15 项
--------------------------------------------------------------------------------------------------
schema+语义通过  通过   valid/sample_simulation_heat_slab_2d.json   0 error；语义检查 15 项全过
schema+语义通过  通过   valid/sample_simulation_pmut_f3_gui_sweep.json   0 error；语义检查 15 项全过
schema+语义通过  通过   valid/sample_analytic_heat_slab_2d.json     0 error；语义检查 15 项全过
schema+语义通过  通过   valid/dataset_heat_slab_train.json          0 error；语义检查 15 项全过
schema+语义通过  通过   valid/feedback_parameter_fmax_accept.json   0 error；语义检查 15 项全过
schema+语义通过  通过   valid/run_gui_sweep_pmut_f3.json            0 error；语义检查 15 项全过
schema+语义通过  通过   valid/device_spec_ge_task3_draft.json       0 error；语义检查 15 项全过
schema+语义通过  通过   valid/task_spec_ge_task3_draft.json         0 error；语义检查 15 项全过
被拒  通过  invalid/sample_simulation_missing_run_id.json       required@<root>
被拒  通过  invalid/sample_source_mixing_simulation_with_evidence.json  type@evidence_id
被拒  通过  invalid/sample_ai_solver_missing_error_bound.json   required@<root>
被拒  通过  invalid/sample_bad_source_type.json                 enum@source_type
被拒  通过  invalid/sample_missing_geometry_family.json         required@design
被拒  通过  invalid/sample_uncertainty_zero_as_unknown.json     required@metrics/T_max_K/uncertainty/components/numerical_discretization
被拒  通过  invalid/sample_unit_conversion_factor_mismatch.json S4_sample_parameter_units_cover_parameters
被拒  通过  invalid/sample_literature_unresolvable_evidence.json S2_literature_evidence_resolvable
被拒  通过  invalid/evidence_literature_no_quote.json           type@quote
被拒  通过  invalid/evidence_literature_no_page.json            required@<root>
被拒  通过  invalid/dataset_leaky_split.json                    S1_dataset_no_family_leak
被拒  通过  invalid/dataset_leak_check_false.json               const@split/leak_check_passed
被拒  通过  invalid/device_spec_hardcoded_pmut_field.json       additionalProperties@<root>
被拒  通过  invalid/task_spec_unknown_parameter.json            T1_task_params_exist_in_device_spec
被拒  通过  invalid/task_spec_save_new_unauthorized.json        required@automation
被拒  通过  invalid/run_failed_without_diagnostic.json          required@<root>
被拒  通过  invalid/run_succeeded_undeclared_gaps.json          R1_run_gaps_declared
--------------------------------------------------------------------------------------------------
结论：全部通过 —— 8 个合法样例通过、17 个非法样例按声明理由被拒
```

退出码语义（fail-closed）：`0` = 全部期望成立；`2` = 有期望未成立（合法被拒 / 非法未被拒 / **拒绝理由与声明不符** / 文件缺失）。`[实测] exit=0`

### 1.3 契约覆盖（工单逐项对照）

| 工单要求 | 落点 |
|---|---|
| 样本必填：`sample_id`、`run_id`、`geometry_family`、参数向量、频率集合、指标值 | `sample.schema.json` `required` + `design`（含 `geometry_family` 必填）+ `frequency_set`（**必填**：稳态工况也要声明 `kind=steady_state` 并给原因）+ `metrics`（非空） |
| `source_type` 六种 + 来源永不混同（红线 4） | `source_type` 枚举六种；`allOf` 六条条件规则：**要求本来源的溯源 ID，并把其余来源 ID 约束为 `null`**（`simulation` 带 `evidence_id` 直接失败） |
| `fidelity` 标注 | 枚举 `F0..F3`；`dataset.report.fidelity_counts` 必须给构成 |
| 单位：内部 SI + 保留原始单位与换算记录 | `units.system` 常量 `"SI"`；`design.parameter_units` 逐参数；`units.original_values[]` 强制 `si_value = raw_value × factor` 自洽（语义检查 S4） |
| 不确定度字段与方法 | `uncertainty{method, type, components{}, interval}`；分量 `value=null` 必须给 `reason`；**`value=0` 必须显式 `zero_is_known=true`**（机械拦住"用 0 冒充未知"） |
| 抽取器版本 | `extractor{name, version}` 必填；`analytic` 额外强制 `formula_ref` |
| 按 `geometry_family` 分组切分防泄漏 | `design.geometry_family` 必填 + `dataset.split`（`strategy` 常量 `grouped_by_family`、`leak_check_passed` 常量 `true`、无跨族留出必须 `degraded_reason`）+ 语义检查 S1 实算族交集 |
| 证据契约（文献带页码+原文摘录）、`experiment_id`/`feedback_id`/`run_id` 必填与关联 | `evidence.schema.json`（`kind=literature` ⇒ 强制 `page` + `quote_type`；`quote` 长度 ≥10；载体文件哈希）+ `experiment/feedback/run.schema.json`；跨文件解析由 S2/T1/T2 完成 |
| `device_spec`/`task_spec` 草稿、器件无关、用当前器件当示例但字段通用 | 两个 schema **顶层 `additionalProperties:false`** ⇒ 把 PMUT 专有字段写进顶层会**校验失败**；器件专有内容只能进 `extensions`（且注明内核不得读取）；参数/目标只能引用 `device_spec` 已声明的名字（T1/T2/T3/T4） |
| 合法样例 + 故意非法样例，证明校验会拒后者 | `examples/valid/` 8 个、`examples/invalid/` 17 个；每个非法样例在 `manifest.json` 里声明"期望被哪个关键字/语义检查拒绝"并对应到具体红线 |
| 样例数值必须标注来源、不得编造、没有真实数据就留空说明 | 见 §1.4 |

### 1.4 样例数值的来源（红线 1）

- 8 个合法样例**全部取自本机实测记录**（`work\store\mems.duckdb` 的 `sample`/`design`/`run`/`dataset`/`feedback` 行，以及 `work\reports\modelio\mspec-*.json`、`docs\TO_CODEX_progress-20260914-LT1-complete.md`），每个文件都有 `source_note` 逐条标注出处；对库中 JSON 做了**契约化改写**（`extractor` 串拆分、`uncertainty` 归位到 `metric`、`quality` 平铺字段归位），每次改写逐条列在样例的 `notes` 里，**未新增任何数值**。
  - 例：`sample_analytic_heat_slab_2d.json` 的 `T_max = 305.0 K` 已用库中原文公式 `T_max = T0 + q_in*Lx/k = 300 + 500*0.01/1` 独立验算一致 `[静态可复核]`。
- **没有真实数据的字段一律留空并说明**：
  - `device_spec_ge_task3_draft.json` 的 `source_model.sha256` 留 **null**（`AGENTS.md` §3 只给了前 8 位 `3efa34cc…`），并把"回填完整哈希"写进 `pending_human`；`v0` 的数值留空（对应 feedback 未给具体电压值）。
  - `task_spec_ge_task3_draft.json` 的**预算/停止条件/优化方向**全部列入 `placeholders` 并注明"是草稿占位，不是批准值"。
- **三种来源没有任何真实样本，故不提供合法样例**（编造会直接违反红线 1）`[实测]`：

```text
sample 总数 962；source_type 分布 = simulation(F3) 490 / analytic(F0) 423 / simulation(F2) 49
evidence 表 0 行；experiment 表 0 行；feedback 表 3 行；sample.evidence_id 非空 0 行
⇒ literature / experiment / ai_solver 只有「schema + 非法夹具」，没有合法样例
```

- `examples\invalid\*` 是**非数据夹具**（内容故意错误、ID 明显是 `fixture-*`、引用是占位串），已在 `manifest.json` 与 `schemas\README.md` 中写明**绝不可当作证据或数值引用**。

### 1.5 顺带查出的存量数据符合度（只读查询，未改数据）`[实测]`

| 项 | 数值 |
|---|---|
| 样本总数 | 962 |
| `design.geometry_family` 可解析 | 962 / 962（分组键齐） |
| `sample.uncertainty` 为空 | **417**（违反"必须记录不确定度与方法"） |
| `uncertainty` 存在但**各分量全为 null** | **490**（违反"value=null 必须给 reason"） |
| `extractor` / `quality` 为空 | 0 / 0 |

⇒ **至少 907/962（94.3%）的存量样本不满足本契约的不确定度条款**。
**建议（需人拍板，本次未动数据）**：不要回填历史（红线 6 append-only）；改为在**新增**样本上强制本契约，存量标 `legacy_pre_contract` 只用于历史趋势对照。

另发现两处**代码注释与实测不一致**（已在 schema 注释中标注，**未改代码**）：`store.py` 把 `feedback.target_kind` 写作 `model|prediction|report|run`，实测存量用的是 `parameter`；`run.pathway` 注释只列 `livelink|comsolbatch|template`，实测存在 `comsol-gui-batch`。契约按**实测**取值。

---

## 2. 任务 2：`pytest -q` 收集失败的诊断与处置

### 2.1 诊断（确切命令与结论）

**复现命令**（`[实测]`）：

```powershell
cd C:\Users\zmx\Desktop\memsharness
work\.venv\Scripts\python.exe -m pytest -q
work\.venv\Scripts\python.exe -m pytest -q --collect-only tests\test_ml_pipeline.py tests\test_pod.py
```

**当前结果**：`240 passed, 4 skipped in 12.09s`，退出码 **0**；两个目标文件单独采集 **21 tests collected**，单独运行 **21 passed** `[实测]`。
⇒ **工单描述的"收集阶段失败"在本机当前状态下不复现**。

**历史报错原文**（引自 `docs\TO_CODEX_progress-20260913-LT0-kickoff.md` §3，2026-09-13 记录，非我本次复现）：

```text
ERROR tests/test_ml_pipeline.py / tests/test_pod.py（采集期）
ImportError: DLL load failed while importing _radius_neighbors:
             应用程序无法启动，因为并行配置不正确（Windows SxS）
```

**判断：属 venv 基解释器（缓存运行时）问题，不是缺 VC runtime，也不是 sklearn wheel 损坏。** `[实测]` 证据链：

| 观察 | 数值/时间 | 推论 |
|---|---|---|
| venv 基解释器目录 `C:\Users\zmx\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\` 下**全部**文件（`python.exe`/`python312.dll`/`python3.dll`/`vcruntime140.dll`/`vcruntime140_1.dll`/`LICENSE.txt`）的 **CreationTime = 2026-09-13 21:46:33**（LastWriteTime 仍保留 2026-09-10 构建时间） | 故障记录于 09-13，缓存文件在**之后**被整体重新落盘 | 该缓存运行时在故障期间不可用/被刷新——与历史记录里的"缓存 Python 被刷新/移动"假设**方向一致** |
| System32 的 `msvcp140.dll`/`vcruntime140.dll`/`vcruntime140_1.dll` 均为 **14.50.35719.0**，CreationTime 与 LastWriteTime 都是 **2025-11-21** | 故障前后**未变** | 排除"缺 VC runtime / 事后补装 redist 才好转" |
| `scikit-learn 1.9.1` 与 `scipy 1.18.1` 的 dist-info / `.pyd` 时间戳均为 **2026-09-11 20:49**（未重装）；`.pyd` 与当前解释器同为 `cp312-win_amd64` | 故障前后**未变** | 排除"wheel 损坏/ABI 不匹配" |
| 显式导入目标模块成功：`sklearn.metrics._pairwise_distances_reduction._radius_neighbors` → `.pyd` 路径正常返回 | 现在 | 该原生扩展本身可用 |
| venv 用 `python -m venv` 建于 2026-09-11 19:44，`pyvenv.cfg` 的 `home` 指向上述**缓存运行时** | — | 基解释器是"缓存运行时"这一结构性事实 |

**复核命令（可日常自查）**：

```powershell
work\.venv\Scripts\python.exe -c "import sklearn.metrics._pairwise_distances_reduction._radius_neighbors as m; print(m.__file__)"
work\.venv\Scripts\python.exe -m pytest -q tests\test_ml_pipeline.py tests\test_pod.py
```

### 2.2 选择的路线：**不隔离，保持全量运行**（并用配置把"这件事"写清楚）

- 不是"能安全修 → 修"：**没有东西需要我修**——故障已不复现，`pytest -q` 全绿 `[实测]`。
- 也不是"不能安全修 → 显式隔离"：隔离会**静默丢掉** 4 个测试文件中的 21 个用例，而现在它们都能跑。按工单"让'没有跑'这件事可见，而不是静默跳过"的原意，**跑起来**才是最优解。
- 因此我改的是**可见性**而不是排除：在 `pyproject.toml` 的 `[tool.pytest.ini_options]` 里加入注释块，写明 ① 历史报错原文与出处、② 当前实测结论、③ 诊断证据（文件时间戳/版本）、④ 两条复核命令、⑤ **恢复条件**、⑥ **已备好但注释掉的 `collect_ignore` 隔离开关**（只有在确认无法修复时才启用）。
  该修改不影响 pytest 行为：`pyproject.toml` 解析复核 `[实测]` `{'testpaths': ['tests'], 'addopts': '-p no:cacheprovider'}`，改后 `pytest -q` 仍 `240 passed, 4 skipped` `[实测]`。

### 2.3 恢复条件（若故障再次出现）

1. 先用 §2.1 的两条复核命令确认是"采集期 `ImportError: DLL load failed ... 并行配置不正确`"，而不是用例失败。
2. **首选**：检查 venv 基解释器目录（`pyvenv.cfg` 的 `home`）是否被刷新/移动/删除；如被移动，用 `python -m venv --upgrade work\.venv` 或按 `AGENTS.md` §3 的方式重建 venv（本机未装 uv，用 `python -m venv`）。
3. **其次**：`pip install --force-reinstall scikit-learn`（注意本机网络实测：官方 PyPI 读超时、清华源可用但索引页偶发截断、**阿里云会截断大 wheel**，见 `AGENTS.md` §3——不要反复换镜像硬试）。
4. **只有确认无法修复**时才启用 `pyproject.toml` 里注释掉的 `collect_ignore`，并在当批次报告里如实标注 `pytest_regression = false（仅 ml 支线，环境级）`，同时列出被排除的用例数（`tests/test_ml_pipeline.py` + `tests/test_pod.py` 当前共 21 个）。
5. **影响范围**（若降级）：仅 `memsharness.ml`（代理模型/POD）支线；COMSOL 链路（`duckdb`/`pandas`/`numpy`）不受影响 `[静态可复核]`（本次全量 `pytest -q` 覆盖了 `test_comsol_queue`/`test_modelio` 等）。**本次未降级**。

---

## 3. 任务 3：MCP 加固（只做低风险两项）

### 3.1 P0-2：旧机路径

**当前 MCP 补丁的真实落点**（工单要求说明）`[实测]`：

| 文件 | 作用 | 是否生效 | 路径状态 |
|---|---|---|---|
| `C:\Users\zmx\.dsh\profiles\web\cordis.patch.yml` | **用户级 profile 补丁层 = 当前 GUI 会话实际装载的 MCP 注册** | ✅ 生效（本会话 `mcp__mems__*` 工具可用即证据） | **已是本机路径**（无需改动） |
| `work\mcp-overlay.patch.yml` | `dsh --profile headless --patch <本文件>` 的**临时覆盖层**（headless 端到端自测用） | 仅在被显式 `--patch` 时生效 | **本次修复**：旧机路径 → 本机路径 |
| `work\dsh-install\cordis.patch.yml` | `install_mems_preset.py` 的 dry-run 产物 | 参考件 | 已是本机路径 |
| `dsh-config\profiles-web-cordis.patch.yml` | 随仓库保存的**旧一代参考件** | 不生效（脚本是动态生成，`install_mems_preset.py` 文档明确说明**不拷贝**该目录） | ⚠️ **仍含旧机路径（见 §3.3）** |

**改动摘要**：`work\mcp-overlay.patch.yml` 的 `command`/`cwd` 由旧机路径改为
`C:\Users\zmx\Desktop\memsharness\work\.venv\Scripts\python.exe` 与 `C:\Users\zmx\Desktop\memsharness`；并加注释记录 P0-2 由来与复核口径（注释内**不含**旧机路径字面量，避免 `install_mems_preset.py` 的 `"D:\\" in text` 式检查误判）。

**实测复核** `[实测]`：

```text
work/mcp-overlay.patch.yml | parse=OK | command= C:\Users\zmx\Desktop\memsharness\work\.venv\Scripts\python.exe | cwd= C:\Users\zmx\Desktop\memsharness
work/dsh-install/cordis.patch.yml | parse=OK | command= C:\Users\zmx\Desktop\memsharness\... | cwd= C:\Users\zmx\Desktop\memsharness
LIVE C:\Users\zmx\.dsh\profiles\web\cordis.patch.yml | parse=OK | command= C:\Users\zmx\Desktop\memsharness\...
```

### 3.2 P0-6：MCP 服务端 `run_id` 路径校验

**实现**（`src\memsharness\mcp_server.py`，参考 `work\tools\lt2_production.py:426-449` 的口径，基线目录改为运行区 `work\runs`）：

```python
_BAD_RUN_ID_CHARS = ("/", "\\", ":", "*", "?", '"', "<", ">", "|")
_MAX_RUN_ID_LEN = 120

def runs_root() -> Path: ...                     # work\runs
def validate_run_id(run_id, root=None) -> dict   # 空/非字符串、非法字符、'..'、首尾空白、超长、
                                                 # 尾点/尾空格（Windows 别名）、resolve 后必须落在 runs_root 内
def _reject_run_id(run_id, tool, **extra)        # 合法返回 None（原路径一字不改）；非法返回结构化错误
```

**挂载点（5 个入口，均为"进入文件系统/SQL 之前"）**：`sim_status`（有 run_id 时）、`sim_logs`、`sim_cancel`、`run_trace`、`records`（有 run_id 时）。
**不改成功路径的证据**：合法值一律返回 `None` 继续走原逻辑；`records(run_id="")` 仍按原语义"不过滤"（只在 `if run_id:` 真值时校验）`[静态可复核]`。

**实测** `[实测]`：

```text
# 1) 既有 run 目录零误拒
existing_run_dirs= 363   false_positive_rejections= 0
REJECT example: {'ok': False, 'reasons': ["含路径/非法字符 ('/', '\\', ':', '*', '?', '"', '<', '>', '|')", "含 '..'"], 'run_id': '../../etc'}
PASS example : {'ok': True, 'run_id': 'ok-run-20260914', 'target': 'C:\\Users\\zmx\\Desktop\\memsharness\\work\\runs\\ok-run-20260914'}

# 2) 工具级拒绝（被拒的 run_id 示例）
REJECT sim_status: {"run": {"run_id": "../../etc", "rejected": true, "tool": "sim_status",
                            "error": "非法 run_id（P0-6 路径校验拒绝）：[...含 '..']", "reasons": [...]}}
REJECT sim_logs  : {"run_id": "..\\..\\work\\devices", "rejected": true, "tool": "sim_logs", ...}
REJECT sim_cancel: {"run_id": "C:evil", "rejected": true, "tool": "sim_cancel", "cancelled": false, ...}
REJECT run_trace : {"run_id": "a/b", "rejected": true, "tool": "run_trace", ...}
REJECT records   : {"run_id": "xxx…(121)", "rejected": true, "tool": "records", "reasons": ["过长(>120)"]}

# 3) 合法但不存在的 run_id：与原行为同形（仍走原路径）
PASS  sim_status('ok-run-not-exist-xyz') -> {"run": {"run_id": "...", "status": "missing", "error": "run 目录不存在：…"}}
PASS  sim_logs('ok-run-not-exist-xyz')   -> {"error": "run 目录不存在：…"}
PASS  run_trace('ok-run-not-exist-xyz')  -> {"run_id": "...", "run": [], "samples": [], "artifacts": []}
```

复现命令（PowerShell 5.1 单行，内层用单引号）：

```powershell
work\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); from memsharness.mcp_server import validate_run_id, runs_root; names=[p.name for p in runs_root().iterdir() if p.is_dir()]; bad=[n for n in names if not validate_run_id(n)['ok']]; print('existing_run_dirs=', len(names), 'false_positive_rejections=', len(bad)); print('REJECT example:', validate_run_id('../../etc')); print('PASS example :', validate_run_id('ok-run-20260914'))"
work\.venv\Scripts\python.exe -c "import sys, json; sys.path.insert(0,'src'); from memsharness import mcp_server as S; print('REJECT sim_status:', json.dumps(S.sim_status('../../etc'), ensure_ascii=False)[:260]); print('PASS  sim_status :', json.dumps(S.sim_status('ok-run-not-exist-xyz'), ensure_ascii=False)[:200])"
work\.venv\Scripts\python.exe -m memsharness.mcp_server --selftest     # [实测] exit=0，11 工具，ping.ok=true, store_ok=true
```

**注**：上述第 2 条命令里 `S.sim_cancel` 只在**非法** id 上验证过（在校验失败即返回，构造函数都不会执行）⇒ 不写票据、不碰进程、不启动 COMSOL。

### 3.3 ~~P0-2 残留~~ → **已闭环**（2026-09-14 追加裁定授权修改）

`[实测]` 仓库内曾有四处旧机路径（`dsh-config\` 两个文件、共 4 行）。**父 agent 已授权修改**，现已全部清理（改前/改后哈希与 YAML 解析实测见 **§7.2**）：

```text
改前（留档）：
dsh-config\profiles-web-cordis.patch.yml:22  # 说明与回滚方式见 D:\桌面\memsharness\docs\dsh_mcp_registration.md
dsh-config\profiles-web-cordis.patch.yml:29  command: 'D:\桌面\memsharness\work\.venv\Scripts\python.exe'
dsh-config\profiles-web-cordis.patch.yml:31  cwd: 'D:\桌面\memsharness'
dsh-config\agent-presets-mems\agent.cordis.yml:29  Your platform repo is D:\桌面\memsharness.
改后：全目录扫描 `D:<中文目录>` / `18161` 两个标记 = 0 命中
```

**关键处置（不只是换路径）**：按裁定要求，两文件头部都加了「这是**生成副本 / 非权威来源**」头注 + 权威落点绝对路径 + 生成器 + 复核命令 + 「若冲突以权威落点为准」。理由：把过期副本伪装成"当前版本"比留着旧路径更危险。
**未推翻裁定**：有独立证据表明这两个文件在本机**不可装载**（`agent.cordis.yml` 用旧代 `text:` persona 键 + `!!js` 条件行，而本机 `dsh-persona` schema 只接受 `prefix`），因此权威落点是
`C:\Users\zmx\.dsh\.agent-presets\mems\agent.cordis.yml` 与 `C:\Users\zmx\.dsh\profiles\web\cordis.patch.yml`。

---

## 4. P0-3 / P0-4 / P0-5：建议与风险（**未动代码**）

> 这三项都会改变用户当前正在依赖的行为（新增模板、worker 启停、取消语义），按工单要求**只写建议与风险**。
> 需求原文见 `docs\TO_CODEX_reply-20260914-mcp-registration-review.md` §P0-3/§P0-4/§P0-5 与 §G5/§G6。

### 4.1 P0-3 新增 PMUT 模板（`pmut_reverse_drive_coarse_v1`）

**为什么不能随手加**：`java_model.TEMPLATES` 现有 `heat_slab_2d`/`cantilever_beam_2d` 都是**可解析验证的玩具模板**；PMUT 模板一旦注册，`sim_submit` 就会具备"真跑生产器件"的能力，而 `sim_submit` 是**无人工确认的同步入口**（提交即入队，worker 一启动就跑）。

**建议的最小安全形态**（与 Codex 提的口径一致，逐条可机器校验）：

```text
① 模板必须哈希锁定：source_model_sha256 = cbe9ccc18e51005f6aa147e8d7fdd5df62266c5f9117d9829888336f326582d9
   （该值已在 docs/TO_CODEX_progress-20260914-LT1-complete.md §5 留痕，可直接引用，不必重新计算）
② 不得开放任意文件路径/任意 COMSOL 表达式：参数只能在模板内声明的白名单+范围内（x_scale、N_w_te1、freq）
③ 频率不得超出已建网格口径：fmax=35 MHz（**不要**默认加 45 MHz，用户已明确"本轮不做"）
④ 模板元数据必须含 drive_mode/vamp/term1_active/cir_inactive_verified/outputs 等自证字段
⑤ 注册前必须过 G6（固定 SHA 的单组合 (0.6,4) × 5/20/35 MHz smoke test + 电极±1V/参考0V/Circuit 停用核对 +
   Ptot/Vave 有限 + server 清理 + 全哈希）
```

**风险**：
- 🔴 **过早开放真实仿真提交**：`sim_submit` 无人工门禁；若模板注册但 G6 未过，MCP 可在无人看管下消耗 COMSOL license 与 commit 余量（本机 commit limit 仅 37.1 GB，见 `AGENTS.md` §3）。
- 🟠 **哈希口径混淆**：本平台存在两种 `model_sha256` 口径（模板通路 = 生成的 Java 源码哈希；GUI 通路 = `.mph` 哈希），模板若不明写在元数据里，后续会把两种哈希当同一物比对。
- 🟠 **参数语义坑**：`fmax` 同时驱动 `lamda→网格 hmax` 与频率上限（见 `feedback_id=fb-20260912T023045Z-ef2ad6aa`），把它放进"可扫描参数"会让扫描同时改网格 ⇒ 目标量的变化无法归因。**必须在模板里把 `fmax` 标为不可扫描。**

**建议顺序**：先落 `device_spec`（本任务已给出草稿 `schemas\examples\valid\device_spec_ge_task3_draft.json`，含 `pending_human` 9 项）→ 人工确认范围/口径 → 再注册模板 → 再过 G6 → 才允许 MCP 提交 PMUT。

### 4.2 P0-4 worker 关闭逻辑（生命周期闭环）

**现状**（`[静态可复核]`）：`sim_submit` 只写队列票据并返回 `run_id`，返回文本让人"另行运行 `python -m memsharness.comsol.queue --max-jobs N`"。若没有外部 worker，任务**永久停在 queued**（无超时、无告警）。

**建议**：采用 Codex 的**方案 1（外部受监督单实例 worker）**，MCP 只提交与查询，不新增"启动任意进程"的工具。理由：`sim_worker_start` 类工具一旦存在，就等于给 MCP 一个"启动进程"的原语，与"只开放监控工具"的当前裁决冲突，收益（省一次手动启动）远小于攻击面。
**必须补齐的可观测字段**（否则"卡在 queued"无法与"worker 崩了"区分）：
`worker_running`、`worker_pid`、`worker_started_at`、`worker_lock_owner`、`last_heartbeat`、`current_run_id`、`processed_jobs`。

**风险**：
- 🔴 **静默悬挂**：现在"提交成功"与"任务真的会跑"之间没有闭环；用户看到 `status=queued` 无法判断是排队还是无人认领。
- 🟠 **心跳字段容易被写成假信号**：`last_heartbeat` 必须是 worker 真的周期性写盘（且**不能**只靠"锁文件存在"推断存活——`AGENTS.md` §3 已实测"锁/句柄存在 ≠ 进程活着"）。
- 🟢 本项**不改求解语义**、不改队列格式，因此是三项里最适合先做的一项（但需要新增一个受监督启动脚本，属新增能力，需单独授权）。

### 4.3 P0-5 `sim_cancel` 的 `force_kill` 默认值与 PID 身份

**现状**（`[静态可复核]`）：`sim_cancel(run_id, force_kill: bool = True)` —— 默认**强杀**。且 `queue.cancel()` 的强杀路径只检查 `status.pid` 是正整数就 `_terminate_pid(pid)`，**不核对该 PID 的启动时间/可执行文件/命令行/run 标识**。

**建议（三步走，任一步都可独立授权）**：

```text
第 1 步（纯默认值）：把默认改成 force_kill=False，并让返回体显式区分
   "已置 cancel.flag（由 worker 在阶段边界安全退出）" vs "已强杀"。
   ⇒ 行为变化：调用方不传 force_kill 时不再杀进程。**这正是工单禁止我擅自改的原因**：
     若当前有人在依赖"不传参就强杀"来止血，改默认会让它在超时场景下变成"只置标志"。
第 2 步（身份核对）：强杀前核对 expected_pid 与现场 PID 的
   CreationTime / 可执行文件路径 / 命令行 / run 标识 四元组一致，且**拒绝**终止
   MCP server / DSH GUI / 非本任务 COMSOL / 系统进程。
第 3 步（终止后验证）：带超时轮询 PID 与端口，留痕 waited_s / timed_out，
   并只用 GetExitCodeProcess == STILL_ACTIVE(259) 判存活（**不要**用 OpenProcess 能否打开）。
```

**风险**：
- 🔴 **PID 复用 ⇒ 误杀无关进程**：Windows PID 会复用；仅凭 `status.json` 里的历史 PID 强杀，可能杀掉一个恰好复用了该 PID 的 COMSOL/mphserver 甚至系统进程。这是 P0-5 里**唯一真正的安全项**，优先级高于"改默认值"。
- 🔴 **改默认值会改变用户正在依赖的行为**：需先确认没有自动化脚本/人工习惯依赖"默认强杀"；`AGENTS.md` §3 的实测（PID 约 15 s 才消失、端口约 10 s）意味着"改完默认"后必须给出更明确的等待与提示，否则会被误读成"取消失败"。
- 🟠 与正在运行的正式验收冲突：任何对取消路径的改动都可能影响 `work\tools\` 下的 supervisor/验收脚本（本次已按约束回避该目录）。
- 🟢 兼容做法：保留默认值不变，**新增** `sim_cancel(..., force_kill=None)` 的显式三态（None=只置标志 / True=强杀+身份核对 / False=只置标志+提示），在不破坏现有调用的前提下把安全路径变成可选默认。**需用户拍板选哪一种。**

---

## 5. 已实现 / 未验证 / 已知风险

### 5.1 已实现（有本次实测证据）

| # | 事项 | 证据 |
|---|---|---|
| 1 | `schemas\` 8 个契约 schema（样本/数据集/证据/实验/反馈/运行/器件规格/任务合同），红线 1/4/6/7/8 与"器件无关"均有机械执行点 | `scripts\validate_schemas.py` exit=0 `[实测]` |
| 2 | 机器校验入口 `scripts\validate_schemas.py`（2026-09-14 按 `AGENTS.md` §5 由 `schemas\` 归位）：schema 校验 + 15 项语义检查 + 期望比对，fail-closed（exit 2）；任意 cwd 均可运行 | 同上 + §7.3 三种 cwd 实测 |
| 3 | 8 个**合法样例**（全部取自实测记录、逐字段标注来源）与 17 个**非法样例**（每个都按声明的关键字/语义检查被拒） | 校验表格逐行 `[实测]` |
| 4 | `device_spec` / `task_spec` 草稿：顶层 `additionalProperties:false` ⇒ 器件专有字段进顶层即校验失败；参数/目标只能引用 `device_spec` | `invalid/device_spec_hardcoded_pmut_field.json`、`invalid/task_spec_unknown_parameter.json` 被拒 `[实测]` |
| 5 | 存量数据符合度量化（962 样本 / 417 缺 uncertainty / 490 分量全 null / 0 有 evidence_id） | 只读 DuckDB 查询 `[实测]` |
| 6 | `pytest -q` 全量通过（240 passed, 4 skipped, exit 0），两个历史故障文件单独采集 21 tests 且 21 passed | `[实测]` |
| 7 | DLL 故障根因定位到"venv 基解释器（缓存运行时）"，并用文件时间戳/版本排除 VC runtime 与 wheel 两类原因 | `[实测]` |
| 8 | `work\mcp-overlay.patch.yml` 旧机路径 → 本机路径，YAML 解析通过 | `[实测]` |
| 9 | MCP 侧 `validate_run_id()` + 5 个入口前置拒绝；363 个既有 run 目录 **0 误拒**；5 类非法值全拒；合法值行为不变 | `[实测]` |
| 10 | MCP 自测未回归：`--selftest` exit 0、11 工具、`ping.ok=true`/`store_ok=true` | `[实测]` |
| 11 | `pytest` 配置层写明 DLL 故障的历史/现状/复核命令/恢复条件/隔离开关 | `pyproject.toml` 解析复核 + `pytest -q` 复跑 `[实测]` |

### 5.2 未验证（本次**没有**做，不得当作已完成）

| # | 事项 | 为什么没做 |
|---|---|---|
| 1 | 契约与 `store.py` 的**运行时联动** | 工单把 `src\memsharness\` 的写入限制为"MCP 那两处"；契约目前是**独立一层**，尚未接进 `insert_sample`/`build_dataset` |
| 2 | 存量 962 样本的逐条符合度判定 | 只做了三项计数（不确定性条款），未逐条跑 schema（需要把库行映射成契约结构，属新增能力） |
| 3 | `literature`/`experiment`/`ai_solver` 的**合法样例** | 库中这三种来源 0 行；按红线 1 不编造 |
| 4 | headless 端到端（`dsh --profile headless --patch work\mcp-overlay.patch.yml` 实调 ping/sim_templates/sim_status） | 属 Codex 的 G4，需要另起 DSH 会话；本次只做了 overlay 的路径与 YAML 校验 |
| 5 | `--dump-config`（G3）复核 | 同上，需重启/另起 DSH；当前 LIVE 补丁已实测为本机路径 |
| 6 | 隔离路线本身（`collect_ignore` 被启用后的行为） | 故障不复现，未启用；隔离开关已写好但保持注释 |
| 7 | `scikit-learn` 重装/repair 验证 | 无需修，且本机网络受限（阿里云截断大 wheel），不做无意义重试 |
| 8 | P0-3/P0-4/P0-5 的任何代码改动 | 工单明确禁止 |

### 5.3 已知风险

| # | 风险 | 等级 | 说明与缓解 |
|---|---|---|---|
| 1 | **合同比实现严 ⇒ 新样本可能被拒** | 🟠 | 契约要求逐分量不确定度；而存量 94.3% 不满足。若把契约直接接到 `insert_sample`，当前生成路径会大量报错 ⇒ 应先让生成端补齐分量，再接门禁 |
| 2 | **语义检查 S2 的证据索引是"样例集"而非数据库** | 🟠 | 库中 evidence 0 行，故现在任何 literature 样本都被 S2 拒。这是如实反映；接入真实文献后必须把索引改为读库，否则会误伤 |
| 3 | **"用 0 冒充未知"只能拦住 `uncertainty.value`** | 🟠 | `metrics.value` 里的 0 无法机械识别（0 可能是真实读数）。需人工审查 + `quality.flags` |
| 4 | **MCP 校验只在 MCP 边界** | 🟠 | `JobQueue.run_dir()/status()/cancel()` 内部仍无校验。已核实仓内其它调用方（`scripts\run_sweep.py`）用的是 `submit()` 自生成的 run_id，`work\tools\` 不在本次范围；建议将来在 `JobQueue.run_dir()` 里做同样校验（纵深防御） |
| 5 | **Windows 保留设备名未拦** | 🟢 | `validate_run_id("nul")` 判为合法：它不含路径分隔符、resolve 后仍在 runs 根内；`mkdir("nul")` 会直接报错，`open("nul/status.json")` 读的是空设备（无害）。已如实记录，未过度收紧以免误伤真实 run_id |
| 6 | **DEVICE_SPEC 草案含未确认项** | 🟠 | `device_spec_ge_task3_draft.json` 的 `pending_human` 有 9 项（含目标器件完整 SHA256 缺失、目标口径未定、范围未确认）。**不得**当已批准配置使用 |
| 7 | ~~**`dsh-config\` 两处旧机路径残留**~~ | ✅ 已闭环 | 2026-09-14 追加裁定授权修改，已清理旧机路径并加「非权威副本」头注，见 §7.2 |
| 8 | **`docs\TO_CODEX_progress-20260913-LT0-kickoff.md` §3 的 `pytest_regression=false` 状态已过期** | 🟡 | 该文档说"未修"，而现在实测全绿。本次**未改**该文档（禁改既有 docs），故在此显式更正：截至 2026-09-14，ml 支线采集失败**不复现** |
| 9 | ~~**`sample.contract_status` 未进 `store.py` 的 `SCHEMA_SQL`/`MIGRATIONS`**~~ | ✅ 已闭环 | 2026-09-14 追加授权：已补进建库/迁移定义并自证（新库含列 / 旧库可迁移 / 现有库不变 / 指纹一致），见 §7.5 |
| 10 | **S2 证据索引仍是样例集（非库）** | 🟠 | 库中 evidence 0 行；接入真实文献后必须改索引，否则 literature 样本恒被拒 |

---

## 6. 边界声明

- ✅ **未运行 COMSOL / comsolbatch / mphserver**，未启动任何求解，未调用 `sim_submit`/`sim_cancel` 做任何真实提交或取消（`sim_cancel` 仅在**非法** run_id 上验证，且在构造队列对象之前即返回）。
- ✅ **未写 `work\tools\` 下任何文件**（只读取 `lt2_production.py` 的 `validate_run_id()` 作为口径参考）。
- ✅ **未改** `AGENTS.md`、`WORKING_PLAN.md`、`docs\` 下既有记录、`work\runs\` 下任何内容。
- ✅ **未运行** `tests_lt2_supervisor.py`、`lt2_acceptance_r4.py`、`tests_rt_gate.py`、`lt2_conc_tests.py`。
- ✅ 所有 `.ps1`：本次**未新建任何 `.ps1`**（无 UTF-8 BOM 风险）；UTF-8 文本统计/校验一律用 Python（未用 `Get-Content`）。
- ✅ 所有 Python 命令使用 `work\.venv\Scripts\python.exe`，stdout 带 `errors="replace"` 语义（`PYTHONIOENCODING=utf-8` + 读取用 `errors="replace"`）。
- ✅ 拿不到的数字一律留空并说明（如目标器件完整 SHA256、`v0` 数值、优化方向、预算/停止条件）。
- ✅ ~~一处**刻意偏离**：机器校验入口放在 `schemas\`~~ —— 已于 2026-09-14 按 `AGENTS.md` §5 归位到 `scripts\validate_schemas.py`（见 §7.3），偏离取消。

---

## 7. 父 agent 三项裁定 + 一条补验证的落地（2026-09-14 追加）

### 7.1 裁定 1：存量标 `legacy_pre_contract`，**不回填**（已执行）

**裁定要点（原文口径）**：新增强制 + 存量标 `legacy_pre_contract`，绝不回填；**更不能补 `uncertainty`**——那等于替历史数据编一个不确定度（红线 1 + 红线 4 双重违反）。

**落地方式（附加元数据，不改数值）**：

```sql
-- 只在本机执行一次；幂等
BEGIN TRANSACTION;
ALTER TABLE sample ADD COLUMN IF NOT EXISTS contract_status VARCHAR;
UPDATE sample SET contract_status = 'legacy_pre_contract' WHERE contract_status IS NULL;
COMMIT;
```

**实测证据** `[实测]`：

```text
n_samples before/after = 962 962
n_updated_legacy       = 962
value_fingerprint_same = True
  before = c3c12ae1cebf930bc3a4eecab1ece3ce9e4168de2d037a1f5ecb6e3555151181
  after  = c3c12ae1cebf930bc3a4eecab1ece3ce9e4168de2d037a1f5ecb6e3555151181
```

- 指纹 = 14 个数值/溯源列（`sample_id/run_id/design_id/fidelity/source_type/inputs/outputs/uncertainty/extractor/quality/evidence_id/experiment_id/feedback_id/model_id`）按 `sample_id` 排序后的规范化 JSON 的 SHA256；改动前 = 改动后 ⇒ **只加了列，没动数值**。
- 读回验证（MCP `records(sample, limit=1)`，`SELECT *`）末字段已出现 `"contract_status":"legacy_pre_contract"`；`data_stats` 各表行数不变（sample 仍 962）`[实测]`。

**可复算的口径与命令**（只读）：

```powershell
work\.venv\Scripts\python.exe -c "import duckdb;con=duckdb.connect(r'work\store\mems.duckdb',read_only=True);print(con.execute('SELECT count(*) n, sum(CASE WHEN d.geometry_family IS NULL THEN 1 ELSE 0 END) missing_family, sum(CASE WHEN s.uncertainty IS NULL THEN 1 ELSE 0 END) unc_absent, sum(CASE WHEN s.uncertainty LIKE ''%\"numerical_discretization\": null%'' OR s.uncertainty LIKE ''%\"model_form\": null%'' THEN 1 ELSE 0 END) unc_all_null FROM sample s LEFT JOIN design d ON s.design_id=d.design_id').fetchone())"
```

口径：`unc_absent` = `uncertainty IS NULL`；`unc_all_null` = `uncertainty` 文本中出现 `"numerical_discretization": null` 或 `"model_form": null`；两集合互斥，实测 **417 + 490 = 907**（≥907/962 = 94.3%）。**该统计是空值/字符串判定，不是逐条跑 schema**（逐条符合度仍未验证）。
**落地位置**：`schemas\README.md` §5.1（含 SQL、指纹、命令、"引用存量必须按缺失处理"的硬规则与人读层警示）；`schemas\legacy` 无新建文件——标记在数据层（`sample.contract_status`）。

### 7.2 裁定 2：`dsh-config\` 旧机路径（已授权修改并已闭环）

**先回答"是否权威来源"：不是权威来源，我不推翻这条裁定，且新增一条独立证据。**
证据一：`scripts\install_mems_preset.py` 文档字符串明确写了"**为什么必须动态生成，而不能直接拷贝 `dsh-config/agent-presets-mems/`**"——本机 `@deepseek-ai/dsh-persona` schema 只接受 `prefix`，而该副本用的是 `text:`；直接拷贝会挂载失败。
证据二 `[实测]`：`dsh-config\agent-presets-mems\agent.cordis.yml` 的 persona 块确实是 `text: >-`（第 27 行起），且含 DSH 旧代格式的 `!!js` 条件行（第 73/77 行）⇒ 该副本**在本机根本不可装载**。
⇒ 权威落点是用户级 `C:\Users\zmx\.dsh\.agent-presets\mems\agent.cordis.yml` 与 `C:\Users\zmx\.dsh\profiles\web\cordis.patch.yml`。

**改动（a 修路径 + b 加"非权威副本"头注）实测** `[实测]`：

| 文件 | 改前 bytes / SHA256 | 改后 bytes / SHA256 | 旧机路径标记 | YAML |
|---|---|---|---|---|
| `dsh-config\profiles-web-cordis.patch.yml` | 1853 / `40a82d2d64b9cc31c9ba533fc0dd4cbddc491029a186f1ecb3825c09368ac2d9` | 2811 / `32723c0874ad63e41bedf064f742bb7a642bc62ef97c82addc57464f206c3e15` | 改前 L22/L29/L31 → **改后 0 处** | `yaml.safe_load` = **OK** |
| `dsh-config\agent-presets-mems\agent.cordis.yml` | 14552 / `151cda0956a706bb69c8b388d2b4e4cb0ea39955666014ea18b321061e8b5c33` | 15490 / `18939e116d506ebdec51750a3efa157a61a19ccbe13d49f57f8d50cc8cc0502d` | 改前 L29 → **改后 0 处** | `yaml.parse`（纯语法）= **OK**，313 events；用忽略 `!!js` 的 loader 构造 = **OK**，16 个顶层条目、首条 `id: persona` |
| `dsh-config\agent-presets-mems\preset.yml` | 195 / `6895c0ef43cfad62dffa0c3e2b6edd17b0511191fa49b64410ab8d972d87160c` | 未改动（本就干净） | 0 处 | OK |

- **关于 `agent.cordis.yml` 的 YAML 可解析性**：`yaml.safe_load` 会失败，原因是**本文件自有**的 DSH 专有标签 `disabled: !!js process.platform === 'win32'`（第 73/77 行，**在我改动的第 1–10 行头注与第 39 行路径之外**），纯 PyYAML 无该标签构造器。故改用 ① `yaml.parse()`（只做语法解析，不受标签影响）通过、② 注入 `!!js` 空构造器后 `yaml.load()` 通过。这是**事前就存在**的属性，不是本次改动引入的。
- 头注内容（两文件均以 `#` 注释给出）：**这是生成副本/非权威来源**、权威落点绝对路径、生成器与"为何不能直接拷贝"、复核命令、保留目的（审计对照）、以及"若冲突一律以权威落点为准"。
- 清理范围：全目录扫描 `D:<中文目录>` 与 `18161` 两个标记，改后 **0 命中**（改前 3 个文件里 2 个文件共 4 行命中）。

### 7.3 裁定 3：校验入口归位 `scripts\`（已移动并重跑证明）

- 移动：`schemas\validate_examples.py` → **`scripts\validate_schemas.py`**（旧文件已删除；`schemas\README.md` 留一行指针）。
- **路径推导必须改，已改**：原实现 `HERE = Path(__file__).resolve().parent; EXAMPLES = HERE/"examples"`，移一层后会去 `scripts\` 找 schema ⇒ 全量报「文件缺失」。改为

```python
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
EXAMPLES = SCHEMAS / "examples"
# load_schemas(): SCHEMAS.glob("*.schema.json")
```

  并在 docstring 里写明"**不要**改成 `Path(__file__).parent`"的原因（防止后人"顺手优化"回去）。
- 移动后实测 `[实测]`：

```text
从仓库根  : 结论：全部通过 —— 8 个合法样例通过、17 个非法样例按声明理由被拒   exit=0
从 C:\Users\zmx        : 同上  exit=0     （证明路径推导与 cwd 无关）
从 <repo>\work        : 同上  exit=0
文件指纹  : bytes= 21827  lines= 489
            sha256= 30fec2e614f66205e1cba61292c9dbe5c7d048daacb7ebd5a68cc6ba799c0320
```

### 7.4 补验证：3 次 `pytest -q` 稳定性（结论 `pytest_recovered_stable`）

**3/3 稳定通过** `[实测]`：

| 次序 | 结果 | exit code |
|---|---|---|
| run 1 | `240 passed, 4 skipped in 12.08s` | **0** |
| run 2 | `240 passed, 4 skipped in 12.02s` | **0** |
| run 3 | `240 passed, 4 skipped in 12.04s` | **0** |

同一 venv 的**环境指纹**（3 次运行之间未变；每次运行前记录）：

```text
python            3.12.14
exe               C:\Users\zmx\Desktop\memsharness\work\.venv\Scripts\python.exe
base_prefix       C:\Users\zmx\.cache\codex-runtimes\codex-primary-runtime\dependencies\python
scikit-learn      1.9.1   (site-packages\sklearn\__init__.py)
numpy             2.5.3
scipy             1.18.1
_radius_neighbors.cp312-win_amd64.pyd  158208 B  Creation=2026-09-11 20:49:44  LastWrite=2026-09-11 20:49:44
基解释器文件（CreationTime 全为 2026-09-13 21:46:33；LastWriteTime 保留构建时间 2026-09-10 17:56）：
  python.exe          Ver=3.12.14        LastWrite=2026/9/10 17:56:00
  python312.dll       Ver=3.12.14        LastWrite=2026/9/10 17:56:06
  vcruntime140.dll    Ver=14.44.35211.0  LastWrite=2024/1/1  8:00:00
```

**结论**：`pytest_recovered_stable`（3/3 通过、退出码全 0、环境指纹在三次之间未变）。
**注意区分**：这证明的是"**当前状态下稳定可用**"，**不**等于"根因已被隔离到某一处并复现过"——根因判定（缓存运行时被整体重落盘）依据的是 CreationTime 与"未重装任何 wheel / 未改 VC runtime"的对照，属**排除法**；若要坐实根因，需在**故意破坏**缓存运行时的受控实验里复现（本机当前不具备该条件，且会破坏正在跑的验收，故未做）。
**未做隔离**（避免静默丢掉 21 个可跑用例）；恢复条件与隔离开关见 §2.3 与 `pyproject.toml` 注释块。

### 7.5 追加裁定 4：把 `contract_status` 补进 `store.py`（已执行并自证）

**为什么补（隐患是真的）**：该列此前只存在于**当前库文件**里，而 `store.py` 的建库/迁移定义没有它 ⇒ 新建库/换机器/重建时**该列静默消失**、962 条 `legacy_pre_contract` 标记随之丢失，**且不报错**——契约人读层还在说"存量已标记"，库里已经没有那个字段。**不报错但事实已变**，必须处置。

**不推翻裁定**：该列**应当**进 `SCHEMA_SQL`——本仓库既有约定就是"表内列写在 `CREATE TABLE`，同时用 `MIGRATIONS` 补旧库"（`evidence_id`/`experiment_id`/`feedback_id`/`model_id`/`owner`/`created_by`/`approved_by` 全都是这样），故按同一模式处理，未另立机制。

**补法（只改 `src\memsharness\store.py` 这一处，两行）**：

```python
# ① SCHEMA_SQL 的 sample 建表语句（新库）
contract_status VARCHAR,         -- 契约状态：NULL | 'legacy_pre_contract'
                                 --   'legacy_pre_contract' = 该样本写于 schemas/ 契约生效（2026-09-14）之前，
                                 --   其 uncertainty **按缺失处理**（不得当 0、不得据此给误差界）。
                                 --   只加列不改数值；修正只能新增记录（append-only）。

# ② MIGRATIONS（旧库；与其它列同语义：可空、默认 NULL）
"ALTER TABLE sample ADD COLUMN IF NOT EXISTS contract_status VARCHAR",
```

**自证实测** `[实测]`：

```text
a) 新建库（store.init_schema 全量建库）
   tables= 12 | sample 列数= 16
   contract_status present = True | 定义 = ('contract_status', 'VARCHAR', 'YES', None)
   ⇒ 可空、默认 NULL

a2) 模拟旧库（sample 表**不含**该列）→ 只靠 MIGRATIONS 补
   补列前含 contract_status = False
   补列后含 contract_status = True        ⇒ 迁移确实生效（不是靠新建库掩盖）

b) 现有库再跑一次幂等迁移（store.init_schema）
   n_samples before/after = 962 962
   contract_status counts before = [('legacy_pre_contract', 962)]
   contract_status counts after  = [('legacy_pre_contract', 962)]

c) 数值列指纹（与打标记前同一算法、同样 14 列）
   fingerprint = c3c12ae1cebf930bc3a4eecab1ece3ce9e4168de2d037a1f5ecb6e3555151181
   与父 agent 记录相同 = True | 迁移前后相同 = True
结论: PASS
```

**过程中自查出的两个问题（如实记录）**：
1. 我给自证脚本写的 `ROOT = Path(__file__).parents[1]` 把仓库根算成了 `work\`（脚本在 `work\tmp\` 下）⇒ 立刻以 `IOException: ...\work\work\store\...` 暴露；已改为 `parents[2]`。**这正是"移动/新增一层目录就改坏相对路径"的实例**，与 §7.3 同一类，故在此留痕。
2. 我在 `sample` 建表注释里写了 `schemas\ 契约生效`，Python 对该 docstring 报 `SyntaxWarning: invalid escape sequence '\ '`（每次 import 都会打印）⇒ 已改为 `schemas/`，并用 `-W error::SyntaxWarning` 复验 import 无告警。
   两个问题都是**我的改动引入并被工具当场暴露**的，未流入验收。

**最终回归**（`store.py` 改动后）`[实测]`：`pytest -q` = **240 passed, 4 skipped, exit 0**；
`scripts\validate_schemas.py` exit 0（8/17 结论不变）；MCP `--selftest` exit 0。
`store.py` 指纹：`bytes=15949 lines=379 sha256=d9ea747aa2545b57c6a2d68eabe852110aac9e4f2bdfa1b4ca9bd05bda9ac516`。
