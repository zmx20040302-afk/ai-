# 已完成工作清单（本机恢复 → 至今）

> ⚠️ **本文档的状态/计划部分已过时（截至 2026-09-29 晚）**：此后仓库又推进了多轮，
> 以 **`docs/INDEX-records-and-rulings.md` §30–§80** 与 **`docs/UNFINISHED_TASKS_AUDIT.md`** 为准；
> 阶段现状见 **`WORKING_PLAN.md` §7.1**。本文档保留作**历史记录**，不改写。


> 文档定位：**事实清单**。每条都带可追溯的落点（`run_id` / 文件路径 / 哈希 / 代码行号），
> 不做"已完成但无证据"的表述；未做的部分单独列在 §10，避免与已完成混淆。
> 时间范围：2026-09-11（本机恢复）～ 2026-09-12（T1 静态审计）
> 权威约定：`AGENTS.md`（红线与环境事实）；本文件是进度快照，不替代 `WORKING_PLAN.md`。

---

## 1. 一句话概览

在这台新机器上完成了「**仓库与运行环境恢复 → 目标器件接入 → 基线求解 → 参数效验 → GUI 扫描数据入库 → 静态电气审计**」六步，
期间**发现并修复了 11 处平台/流程缺陷**（其中 4 处会导致"静默错误结论"），
当前状态：**可复现的求解与溯源链路已打通，数据层已可用，器件的物理口径尚有 3 项待人工裁决**。

---

## 2. 仓库与运行环境恢复

| 项 | 结果 | 落点/证据 |
|---|---|---|
| git 历史 | 25 提交恢复，`master` → `e31ccc7`；67 个受控文件与 bundle 顶点树**逐 blob 哈希一致** | `git log`；`HANDOFF.md` |
| Python 环境 | `work\.venv`（3.12.14）：numpy 2.5.3 / scipy 1.18.1 / pandas 3.0.5 / scikit-learn 1.9.1 / matplotlib 3.11.1 / duckdb 1.5.5 / pyarrow 25.0.1 / pint 0.26.1 / fastmcp 4.0.3 / pytest 9.1.1 / **MPh 1.4.0 + JPype1 1.7.1** | `work\.venv` |
| 自检 | **240 passed, 4 skipped**（多次复现，13–14 s） | `pytest -q` |
| 沙箱适配 | 受限策略下 pip/venv 必失败（沙箱拒绝写入「以 0o700 创建」的目录，而 `tempfile.mkdtemp` 正是如此）→ venv 内 `sitecustomize.py` 对**所有子进程**生效强制 `0o777` | `work\.venv\Lib\site-packages\sitecustomize.py` |
| 环境事实探测 | COMSOL 6.4.0.293（6/6 可执行文件）、授权 `Name=zmx`、**MATLAB R2023b**（`D:\matlab`）、LiveLink 在位、mphserver 默认不常驻；另装有 COMSOL 6.2 | `work\recovery-env\reports\env_report.json` |
| COMSOL × 文件策略（硬约束） | 受限策略下 `comsolcompile`/`comsolbatch` **统一 rc=15、stdout/stderr 全空**（连最小 `Hello.java` 都失败）；`-userdir`／`COMSOL_USERHOME`／覆盖 `USERPROFILE` 三种重定向**均无效**；放宽策略后 rc=0 | `AGENTS.md` §3 |
| DSH「MEMS 模式」 | 装在用户级目录 `C:\Users\zmx\.dsh\.agent-presets\mems\`；MCP 条目已并入 profile 补丁层；**用 DSH 自身发现逻辑验证：`id=mems`、无 `broken` 字段** | `scripts\install_mems_preset.py`、`scripts\verify_mems_install.py`、`scripts\verify_mems_preset.mjs` |
| 文档同步 | `AGENTS.md` 环境表/执行约定/决策状态全部换成本机实测；`WORKING_PLAN.md` 新增第 13 节「机器迁移后的实测修正」**12 条**；`HANDOFF.md` 重写为本机版（旧机版归档） | `AGENTS.md`、`WORKING_PLAN.md`、`HANDOFF.md`、`work\reports\HANDOFF-旧机版-归档-20260911.md` |

---

## 3. 目标器件接入与「第一次阅读」

| 项 | 结果 | 落点 |
|---|---|---|
| 目标器件 | `b_GE_task3_2-new.mph`（98.9 MB，sha256 `3efa34cc…`）；**与 `yizu` 变体为同一器件**（两份 `.m` 的 37 个参数名与表达式完全一致） | `work\reports\modelio\probe-*.json`、`mspec-*.json` |
| 只读 probe | ok=True：**37 参数**、3D 几何 83 顶点/217 边/152 边界/**16 域**、4 物理场接口（`acpr`/`solid`/`es`/`cir`）、**19 个命名选择集**、研究 `std1`、三个求解器、**保存态未建网格** | `work\reports\modelio\probe-probe-20260911T153110Z-75135037.json`（573 KB） |
| 三方交叉校验 | Java 探针 + Model M-file + MPh 运行态：参数/几何/网格三侧一致；研究步取值（`param`/`param2`/`freq`）由 `.m` 与运行态互相印证 | 同上 + `mph-runtime-*.json` |
| 《第一次阅读报告》 | 333 行，含参数表（37）、物理场特征、19 选择集、研究步、几何/网格、回读校验、缺口清单 | `work\reports\modelio\READING-…md`、`scripts\render_reading_report.py` |
| `.m` ↔ 运行态差异 | `cross_check` 报 55 条：`missing_in_spec` 21、`value_mismatch` 7、`illegal_enum_value` **5（经运行态回读证伪为 schema 联合取值误报）**、`variant_dependent` 7、`enum_not_checked` 11、`unreadable_in_probe` 4 | `work\reports\modelio\crosscheck-b_GE_task3_2new.json` |

---

## 4. 基线求解（真实 COMSOL，7 频点）

| 项 | 结果 | 落点 |
|---|---|---|
| run | `baseline-20260912T024332Z-8ab4eb6e`（`pathway=mph-client`，status=succeeded） | `run` 表 |
| 口径 | 在**副本**上停用两个 Parametric 步、**只跑 `freq`**（回读确认 `param`/`param2` 均 inactive）；原件 SHA256 未变 | `baseline.json:disabled_steps` |
| 反向验证 | 解数量 = **7** = 频点数（若扫描步仍生效会是更多） | `n_solutions=7` |
| 耗时 | **875.14 s**（含首次建网格），wall 906.9 s | 同上 |
| 产物 | `out.mph`（160.89 MB）+ 紧凑落档（198 MB → **0.01 MB**，见 §8 缺陷 5） | `work\runs\baseline-…/` |
| 逐频点响应 | **纠正了索引映射后**：位移峰值在 **10 MHz**（`|u|=6.842e-10 m`、`|w|=2.729e-9 m`），声压峰值在 **30 MHz**（`|p|=2.424e5 Pa`）；5 MHz 最低（1.573e4 Pa） | `baseline_targets.json`（含 `axis_order_hz` 与 `index_frequency_hz` 双记录） |

---

## 5. 参数效验（第一轮，两遍走）

| 遍 | 口径 | 结果 | 落点 |
|---|---|---|---|
| 第一遍（不求解） | 25 个数值参数 +5%，重建几何/网格 | **11 个几何类**（`h_te`/`h_pzt`/`h_device`/`h_parylene`/`W_min`/`N_mem`/`N_w_te1`/`N_w_te2`/`x_scale`/`c_water`/`fmax`）+ 14 个非几何类；12 个派生表达式按设计跳过；82.9 s | `work\runs\audit-20260912T030822Z-12538b50\audit.json` |
| 第二遍（求解，10 MHz 单频点） | 14 个非几何参数 +5% | **只有 `v0` 有效**（目标量变化 **5.000e-02**，与扰动幅度**完全相等** ⇒ 纯线性增益）；**13 个逐位 0.0**；3629.5 s | `work\runs\audit-20260912T072644Z-fffb8987\audit.json` |
| 与旧机结论 | 旧机在 `bGEtask2` 上「非几何参数里只有 `v0` 有效、噪声地板 0」——**在新模型、独立口径下完全复现** | `work\reports\modelio\AUDIT-b_GE_task3_2-new-10MHz.md` |
| 方法学局限（如实声明） | ① 零值参数（`N_p_te1=0`、`p_be1=0`、`V_be1=0`）相对扰动是恒等变换，**无法判定**；② 单频点结论只在该频率成立；③ 几何类 11 个参数**未做响应效验** | 同上 |

---

## 6. GUI 批处理扫描数据入库

| 项 | 结果 | 落点 |
|---|---|---|
| 数据源 | `扫面x&N1，间隔阵列扫描.csv`（18:12）+ `扫描x&N1，间隔扫描.xlsx`（18:16）——同一张 COMSOL 全局计算表 | `C:\Users\zmx\Desktop\换能器\` |
| 规模 | **70 组合（`x_scale` 10 档 × `N_w_te1` 7 档）× 7 频点 = 490 行**，无缺失组合 | — |
| run | `gui-sweep-20260912T113936Z-bd387a56`（`pathway=comsol-gui-batch`）；证据锚：CSV sha256 `0a49d5a1…`、`.m` sha256 `c1344709…` | `run` 表 + `work\runs\gui-sweep-…/provenance.json` |
| 入库 | **design 70 条**（`geometry_family=GF-pmut-ge-task3-oval`）+ **sample 490 条**（`source_type=simulation`、`fidelity=F3`） | — |
| 逐位核对 | 与源 CSV 比对 21 个标量 + 复数量：**不一致 0 个** | `work\tools\verify_ingest.py` |
| 数据质量标记 | 每条样本带 `zin2_equals_zin1_known_defect`、`frequency_grid_5MHz_coarse`、`no_mesh_convergence_L1`；组合级 `combo_peak_at_upper_frequency_boundary` | `sample.quality` |
| 关键统计 | **31/70 个组合的 `Ptot` 峰值顶在 35 MHz 上边界** ⇒ 谐振未被频段包住 | `T1`/分析脚本 |
| 溯源库现状 | sample **962**（F0 analytic 423 / F2 simulation 49 / **F3 simulation 490**）、design 564、run 101、feedback 3、validation 11 | `work\store\mems.duckdb` |

---

## 7. T1 静态电气审计（不做求解）

**报告**：`work\reports\modelio\T1-electrode-wiring-audit.md`；**结构化取证**：`T1-wiring-facts.json`、`mspec-b_GE_task3_2newyizu.json`

| # | 发现 | 证据（行号） |
|---|---|---|
| 1 | **极性/接线与文献基准不一致**：内电极 `cyl9`(Vin) 固定 `V0='-v0'`（−1 V）；外电极 `cyl8`(Vout) 的 `pot1`(+v0) **已停用**，改由 `term1`(Terminal/Circuit) + `R1`(1 Ω) + `termI1`(`V_src='root.comp1.es.V0_1'`) 驱动 ⇒ 「反向驱动」静态不成立 | L675-677 / L672-674 / **L1142** / L1143-1155 |
| 2 | **`x_scale ≤ 0.4` 时内外电极选择重叠**（内电极半径 `N_w_te1*W_min+1µm` **不含 x_scale**；外环内径含）⇒ 70 组合里 **28 个**（x_scale=0.1/0.2/0.3/0.4）与设计意图不符 | L345-348 vs L330-344 |
| 3 | **`Ptot` 口径存疑**：生效版本是 `intop5(...)`，选择集为**显式实体 `[1 3 70 104]`**；历史版本为 `4*intop4(...)`（4× 因子）⇒ 绝对值可能差一个倍数 | L775-776, L796-807 |
| 4 | `Zin2 = v0/I01`（应为 `I02`）**确认**；且 `intop3`→`cyl9`、`intop4`→`cyl8`，两积分区域**确实不同** ⇒ 修公式会真正改变数值（符号仍待定） | L826 / L770-774 |
| 5 | `Vave` 是**幅值**（`abs(...)`，恒非负）；`V_center` 是中心点(实体 45)的**复数**位移 | L779 / L786 |

---

## 8. 发现并修复的缺陷清单（11 项）

| # | 缺陷 | 后果 | 修法 | 验证 |
|---|---|---|---|---|
| 1 | `make_report.py` 图 2 未按器件族过滤 | `KeyError: 'k_cond'`，报告直接失败 | 查询加 `geometry_family` 过滤 | 报告重生成成功 |
| 2 | `train_surrogate.py` 无族过滤 + 跨族全空列 | 多族入库后 `dropna` 归零（**静默产出空训练**） | 加 `--family`；先丢整列全空列；给出可操作提示 | 17 样本训练成功（R²=0.9709） |
| 3 | `pyproject.toml` 缺依赖声明 | 干净环境 `matplotlib` 缺失 → 测试必失败；`joblib` 仅靠传递提供 | 补 `matplotlib`/`joblib` + 可选组 `[comsol]`（`mph`,`JPype1`） | 测试 240 passed |
| 4 | `env.py` MATLAB 默认路径写死旧机 | 误报"MATLAB 未装" | 改为候选列表探测 | 探测到 `D:\matlab\bin\matlab.exe` |
| 5 | **`onboard.measure()` 用 `evaluate('x')` 判几何变化** | 在已网格化模型上该表达式取固定数据集 ⇒ 几何判据**完全失明**（第一遍效验得出"25 个参数都不影响几何"的**假结论**） | 新增 `_mesh_shift()`（Java mesh API）+ `measure(mesh_tag=)` + `classify_parameter(mesh_shift=)`（向后兼容） | `N_mem` 10→20 时 136,250→151,945；重跑后 11/14 分类正确 |
| 6 | **`parse_matlab_export` 只扫 `("parameters","main")` 两个块** | COMSOL 导出**函数名跟随文件名**（如 `function out = foo`）⇒ 参数表整段丢失，下游把 37 个参数全记成 `missing_in_spec` | 扫描全部块（块名仍如实记录） | 同一份 `.m` 从 **0 → 88 条**记录；240 passed |
| 7 | `install_mems_preset.py` 路径写死旧机 + persona 用旧版 `text:` 键 | 换机后装不上（症状：选完跳回原模式） | 整体重写：动态解析本机 DSH 包、以本机 standard 为基底注入 `prefix` 人格、dry-run/install/force、自动备份并合并 MCP | DSH 自身发现逻辑确认 `id=mems` 健康 |
| 8 | 两个 `.mjs` 包路径写死 + **调用 DSH 发现 API 参数错误** | 校验脚本从未跑通过 | 动态解析包路径 + 传必填 `harnessBase` + roots 用 `trust` 键 | `发现 1 个用户 preset` |
| 9 | `modelio_probe_real.py` 目标路径写死已剥离文件 | 探针永远报"模型不存在" | 参数化（CLI 传参 / 缺省取 `work/runs` 最新） | 对目标模型 probe ok=True |
| 10 | 新脚本/摘要把原始数组写入 JSON | `baseline.json` 膨胀到 **198 MB**（信息量却只是一个标量） | 改为 `evaluate(expr, inner=[i])` 逐索引求值 + 逐索引回读频率 | 0.01 MB；索引映射用独立求解验证 |
| 11 | 9 个脚本/模块的用法示例写死旧机交汇点路径（23 处） | 照示例敲命令必然失败 | 前缀清除 + 「经 ASCII 交汇点」改为「在仓库根下执行」 | 仅动注释/文档串 |

**另附**（环境级，非仓库缺陷）：pip/venv 在受限策略下必失败 → `sitecustomize.py` 补丁；COMSOL 静默 rc=15 → 记入 `AGENTS.md`。

---

## 9. 新增脚本与产物

| 脚本（`scripts\`） | 作用 |
|---|---|
| `baseline_solve.py` | 任意用户模型的**基线口径**求解（只跑指定研究步、停用扫描步、自管 mphserver、Java API 绕开 MPh 名称查询、`os._exit` 防挂起） |
| `baseline_postprocess.py` | 从 `out.mph` 现算逐频点曲线（不重新求解；**逐索引回读频率**，避免标注错位） |
| `audit_parameters.py` | 参数效验 CLI（两遍走、单频点口径、参数子集过滤、频率轴回读） |
| `ingest_feedback.py` | 人反馈写入（仓库原本只有 `feedback` 表、**无写入通路**） |
| `ingest_gui_sweep.py` | GUI 批处理扫描结果入库（run 目录 + 证据哈希 + SI 单位 + 不确定度 + 质量标记 + 重复入库防护） |
| `render_reading_report.py` | 三方合成《模型第一次阅读报告》 |
| `verify_mems_install.py` | MEMS 模式安装回读校验 |
| `analyze_sweep.py` | **扫描结果分析管线**：清洗 → 逐组合指标（`Vave`/`Ptot` 双口径，幅值 `20log10`、功率 `10log10`）→ 多指标 top-N + Pareto → 精扫候选 → 图 → 报告；**每行钉批次溯源**（`batch_label`/`model_version`/`model_sha256`/`source_csv_sha256`）并产出 `00_provenance.json` |
| `geometry_selection_precheck.py` | **批量几何/选择/网格预检**（不做频域求解）：逐组合读实际生效的边界实体并量取面积，分类 `clean`/`N0_control`/`empty_selection`/`bc_conflict`/`geometry_failed`/`mesh_failed`/`area_anomaly` |
| `work\tools\*.py`（不追踪） | 20+ 个一次性诊断/分析脚本（几何敏感性、重建根因、mesh 判据、扫描解析、T1 取证…） |
| `work\tools\diff_model_m.py` | **模型 `.m` 全量差异比对**：对每行 `model.*` 语句通用归一化（不按类别白名单，避免漏掉 `setIndex` 这类赋值），同名取**最后一次**赋值，按类别输出改值/独有项 |
| `work\tools\xlsx_to_csv.py` | **只用标准库**（zipfile + XML）把 `.xlsx` 转 CSV，支持选表——绕开未安装的 `openpyxl` |
| `work\tools\batch_quality.py` | 批次数据质量检查 + 输入冻结（sha256、`.mph.lock` 时跳过取哈希）→ `02_data_quality_report.md` + `_data_quality.json` |
| `work\tools\peek_sweep_table.py` | 扫描表速览（行列数、列名、各扫描量取值集合） |

**技能层（`.dsh\skills\`，由 `skill-filesystem` 从仓库根自动发现；实测新增技能即时生效、无需重启 DSH）**

共 **9** 个：`ai-solver-verification`、`autonomous-optimization-loop`、`comsol-modeling-sop`、`dataset-contract`、
`field-io-contract`、`model-io`、`model-onboarding`、`report-and-evidence`，以及本轮新增
**`sweep-analysis`**（参数扫描分析与决策 SOP：冻结哈希 → 数据质量 → 几何/选择预检 → 双指标排名 → 精扫候选；
含"多批次绝不混排"、预检缺失时排名降级为临时的规则，以及 6 条实测踩坑清单）。

**关键产物路径**

- 效验报告 `work\reports\modelio\AUDIT-b_GE_task3_2-new-10MHz.md`
- T1 报告 `work\reports\modelio\T1-electrode-wiring-audit.md`
- 阅读报告 `work\reports\modelio\READING-…md`
- 扫描摘要 `work\reports\modelio\sweep-xN1-summary.json`
- run 目录：`work\runs\{baseline-…, audit-…×3, gui-sweep-…, probe-…×2}`

---

## 10. 尚未完成 / 明确未做（避免与上面混淆）

| 项 | 状态 |
|---|---|
| 网格收敛（L1）与网格依赖假最优排查 | **未做**（所有扫描数据的网格相关性未验证） |
| 场级快照导出、公共点集、POD/降维 | **未做**（`work/runs` 里此前的真实解域快照缺失） |
| 代理模型训练（本器件族） | **未做**（数据刚入库；且按族切分需要 ≥2 族或明确降级声明） |
| AI 求解器（免 COMSOL 出解）与 S 级验证 | **未做**（P4.5 阶段，未开始） |
| 阵列模型（pitch/多单元/波束/衍射） | **未做**（当前是单单元模型，不能据此宣称阵列性能） |
| −6 dB 带宽的**评价对象与观察位置** | **未钉死**（压力幅值/声功率/往返响应？膜面/近场/20 mm？） |
| 外电极实际电位、`Zin2` 符号、`Ptot` 实体口径 | **待核实**（T2，需少量机时） |
| `N_w_te1=7` 缺失原因 | **待查**（`err='on'` 会静默跳过失败点；`换能器\` 下无 Batch 日志文件） |
| 文献/实验/人反馈三类来源接入 | **未做**（`evidence`/`experiment` 表仍为 0 行；三份 PPTX 尚未读取） |
| 代码提交 | **未提交**（20 个改动文件 + 3 个未追踪文件；git 身份未配置） |
| `schemas/` 目录（AGENTS §5 要求的契约落点） | **不存在**，待建立 |
| **`.xlsx` 读取依赖缺失** | venv 内**没有 `openpyxl`**，`pyproject.toml` 也**未声明**它 ⇒ `pandas.read_excel` 直接 `ImportError`（2026-09-13 实测）。已用标准库写 `work\tools\xlsx_to_csv.py`（zipfile + XML）绕开并跑通；**待补装并写入依赖**。⚠️ 当时清华镜像为 **SSL EOF 断连**（不是截断），`pip install` 无法完成 |
| MEMS 模式的 **MCP 工具层**覆盖范围 | 现仅"求解提交/查询 + 只读查库"共 11 个 `mcp__mems__*` 工具；**分析/预检/导入能力仍只在 Shell**（不是 agent 可直接调的工具）。`sim_templates` 只有 `heat_slab_2d`/`cantilever_beam_2d` 两个通用解析验证模板，**PMUT 器件没有模板 ⇒ 改参重算无法经 `sim_submit` 提交**，只能走 `scripts\`。注意 MCP 超时 60 s、几何预检需 5–15 min ⇒ 长能力做成 MCP 工具必须走队列异步，不能同步暴露 |
| **MATLAB / LiveLink 通路**（改 `.m`，或在 MATLAB 里驱动求解） | **未实现**。`comsol\__init__.py` L12 与 `java_model.py` L3 明确留作 seam（"未实现"／"留到以后（WORKING_PLAN 4.1 通路 A）"）；能力表 `LiveLink_for_MATLAB` = `documented=true, solve_verified=null`（**license 在位、从未冒烟**，按红线 5 只能称"待验证"）；`.m` 仅作**只读权威文本来源**（`parse_matlab_export` L3478 / `cross_check` L4533），平台**不生成也不执行** `.m`；`env.py` 只探测 `matlab.exe` 与 `mli` 存在（实测均 True），无代码用它求解；`store.pathway` 的 `livelink` 枚举**从未被任何 run 使用**。⚠️ 对照：**"改参 → 重算"能力本身已有且已实测**，走的是 COMSOL Java/MPh + `comsolbatch` 通路（`matlab_used: False`）——`audit_parameters.py` 改 14 参数重算 3629.5 s、`baseline_solve.py` 7 频点 875.14 s |
