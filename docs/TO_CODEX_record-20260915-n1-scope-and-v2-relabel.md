# TO_CODEX 记录：`N_w_te1` 范围更正（本意 1–8）与 V2 重定性为"仅诊断"

- 日期：2026-09-15
- 性质：**范围归属更正（append-only）**。**不重跑任何 CV/留出指标、不按新范围重新选模型、不改任何阈值、
  不改任何已交付数字**；只把"哪些组合属于有效设计域"这一条**归属事实**改对。
- 触发：用户澄清（原话逐字）**「本意是1-8」**，经父代理以任务单形式转达。
- 新增目录：`work\ai-solver\step5b\`（**未改动** `work\ai-solver\step4\`、`work\ai-solver\step5\` 的任何字节）
- 新增记录：本文件
- 未运行 COMSOL / `mphserver` / pytest；未改 `work\tools\`、`src\`、`work\models\`、`work\store\`、用户目录

---

## 0. 一句话

`N_w_te1 = 9–18` 这 **90 个组合 / 630 行（55.6%）** 是**扫描表达式写法**造成的**非预期**数据，
不是设计意图；平台一级预检**独立地**把这同一批 90 组全部判为不合格 ⇒ **有效域 = `N_w_te1` 1–8（72 组合）**，
与用户本意一致。因此：**主模型的适用范围改挂 `V1_intended72`**，**`V2_all162` 降级为"仅诊断、非全域"**。
主模型本身（`M2_log10_gp`）**没有变**——它在 step5 的**预注册规则**下本来就在**两个变体上都被选中**，
所以这次改挂**不涉及任何基于指标的重新选择**。**全部数字、阈值、放行结论一字未动。**

---

## 1. 事实链（每条都带证据与证据级别）

### F0 用户澄清（`source_type = 'human_feedback'`）

| 项 | 值 |
|---|---|
| 原话（逐字） | **「本意是1-8」** |
| 说话人 | 用户（本项目直接人类负责人） |
| 转达渠道 | 经父代理（任务单 §一） |
| 登记时刻 | **2026-09-15T16:12:34+08:00**（= 本更正件写入时刻，机读见 `scope_correction.json.human_feedback.recorded_at`） |
| 含义 | 设计空间本意 `N_w_te1 ∈ {1,…,8}`；数据里的 9–18 属非预期 |
| 人在拍板什么 | **范围归属**（哪些组合算有效设计点）——不是数据真值、不是误差/覆盖率、不是阈值 |

### F1 两份 `.m` 的**批处理**里都是 1..8（L2401）—— 直接实测（本轮只读打开）

| 文件 | 字节 | sha256 | 行数 | L2401 原文 |
|---|---|---|---|---|
| `C:\Users\zmx\Desktop\b_GE_task3_2new.m` | 159,756 | `1ec837d4133cd7c9b3d79a57e293474b11f076a4b28edb240db1e5b87046a9bb` | 2,712 | `model.batch('p1').set('plistarr', {'range(0.1,0.1,1)' 'range(1,1,8)'});` |
| `C:\Users\zmx\Desktop\b_GE_task3_2newrange005.m` | 162,759 | `35f907670e756e97ca5496689df2da9e363ff4e5cc4ae33e019ea8430ad9a6ae` | 2,751 | 同上（逐字相同） |
| 仓库内同基座导出 `work\runs\gui-sweep-20260912T113936Z-bd387a56\model_export.m` | — | 见 `raw\...`（step5 未引用） | — | 同上（L2401） |

⇒ **批处理口径 = 1..8**，与用户本意一致。（两个桌面 `.m` 为**用户目录文件，只读打开，未修改**。）

### F2 range005 的 **study `param` 步**末尾把 N_w_te1 覆盖成 `range(1,18)`（L2713/L2714）—— 直接实测 + 平台 diff 记录

`b_GE_task3_2newrange005.m` 中该属性**最后一次赋值**（`AGENTS.md` §4：同名属性取最后一次）：

```
L2713: model.study('std1').feature('param').setIndex('plistarr', 'range(0.4,0.05,0.8)', 0);
L2714: model.study('std1').feature('param').setIndex('plistarr', 'range(1,18)', 1);
```

对比与旁证：

- 旧模型 `b_GE_task3_2new.m` **没有** L2713/L2714；它的 study param 末尾是 L2658/L2659 的稀疏列表 `1` / `8`
  （更早 L2362 是 `range(1,1,8)`）⇒ 旧模型运行态 = 1..8；
- 平台 diff 记录 `work\reports\modelio\diff-newrange005-vs-old.json`（3,948 B / sha256
  `8e14d6877dffdb6432363f17ba27daba392a6ad3c3ec0c35cb4714ba8be0aae8`）把这两条列为**唯二**
  `param_other.changed` 键（`plistarr[0]`、`plistarr[1]`），值分别是 `range(0.4,0.05,0.8)`、`range(1,18)`；
- 平台 brief `docs\TO_CODEX_brief-20260913-batch2.md` L39/L40 记同一对改动，并注明
  L2713/L2714 **覆盖** L2658 的 `1` 与 L2659 的 `8`；索引→参数名映射见该文件 L2337/L2354
  （`pname[0]='x_scale'`、`pname[1]='N_w_te1'`）。

**语义说明**：COMSOL `range(a,b,c)` 为 start/step/stop；两参数写法 `range(1,18)` 等价于 start=1、stop=18、步长 1。
**这条语义来自平台记录**（下一条 F4 的 M7 回读），而"18 档"这一事实由 **F3 的数据实测**独立坐实——本轮**未跑 COMSOL**。

### F3 数据实测：1134 行 = 9 档 `x_scale` × **18 档 `N_w_te1`（1..18）** × 7 频点

- 冻结副本（data of record）：sha256 `33ed711c8d53bf02f69686e8e1c62815587919588d73293a5ce899c903951403`，
  1134 行 / 162 组合 / 7 频点（`work\ai-solver\step5\raw\inputs.json.data_positivity` 亦记录同源）；
- `x_scale` 九档：0.4, 0.45, …, 0.8；`N_w_te1` 十八档：1,…,18；
- 平台记录同：`docs\TO_CODEX_brief-20260913-batch2.md` §2.2（1134 = 9×18×7，满格零缺失）。

### F4 平台 M7 运行时回读：study `param` 步 outer = **162** ⇒ 真正产出数据的是 `param` 步

**证据级别 = 平台记录（本轮未独立复跑 COMSOL，因为明令不许启动 COMSOL）**：
`docs\INDEX-records-and-rulings.md` L592（`plistarr index0='range(0.4,0.05,0.8)', index1='range(1,18)'` ⇒ 9×18=162）、
L891（M7 实测 outer 162）、L895（"用户的本意（1–8）写在**批处理**里；实际产出数据的是**study 的 param 步**"）。

### F5 平台一级预检对同一批 90 组的**独立**判定 —— 直接实测（本轮统计）

预检 CSV：`work\runs\precheck-batch2-phase1-v5\geometry_selection_precheck.csv`
（74,745 B / sha256 `a8d77f0a5439fad7e925546d4f9381abf49bd43062339968354678650841d2d0` / 162 行）：

| `N_w_te1` | 组合数 | `design_status` | `selection_status` | `eligible_for_ranking` | 备注 |
|---|---|---|---|---|---|
| **1–8** | **72** | `intended_design` | `verified` | **True** | 有效域 |
| **9** | 9 | `design_boundary_coincident` | `verified` | **False** | 边界重合 |
| **10–18** | 81 | `design_region_reversed` | **`selection_mismatch`** | **False** | 其中 **72** 个 `physical_extent_suspect=True`；`eligibility_reason` = `design_region_reversed; selection:selection_mismatch[; physical_extent_suspect]` |

> **用词更正（如实登记）**：父代理的表述是"`N1 10–18` = `design_region_reversed + selection_mismatch`"。
> 实测该 CSV **没有**名为 `selection_mismatch` 的列——`selection_mismatch` 是 **`selection_status` 列的取值**
> （81 行）；`N1=9` 那 9 组的 `selection_status` 是 `verified`，其不合格理由是 `design_boundary_coincident`。

### F6 结论：平台排除的 90 组 == 非预期的 90 组；有效 72 组 == 用户本意的 72 组

机器校验（`impact_selfcheck.json.partition_check`）：
`162 = 72 + 90` 且两集合**不相交且覆盖全部**；`eligible == {N1 ≤ 8}`、`flagged == {N1 ≥ 9}` 均为 `true`。
行数口径：非预期 **90 × 7 = 630 行 / 1134 = 55.5556%**。

---

## 2. 处置（新增文件清单）

| 文件 | 字节 | sha256 | 作用 |
|---|---|---|---|
| `work/ai-solver/step5b/scope_correction.json` | 51,436 | `e08aeced8f11ac42fb98943be69e91223f72da4db14aada156f41e7ca281f04f` | **范围更正件**：用户原话 + `source_type='human_feedback'` + 完整事实链（F1–F6，含行号、`.m` 哈希、预检判定）+ **90 个非预期组合的显式清单**（每个含 `design_status`/`selection_status`/`eligible_for_ranking`/`physical_extent_suspect`）+ "不删除、数值不改、只改范围归属" |
| `work/ai-solver/step5b/s_grade_after_scope_correction.json` | 15,100 | `6267c8602bc7d13e47ffa52074f9b5d0b9f05890422fb14b3ab9263397a54e9c` | **`s_grade.json` 的范围更正后副本**：逐字段照抄，**只新增 2 个顶层键**（见 §3） |
| `work/ai-solver/step5b/s_grade_diff_evidence.json` | 4,884 | `f85f0cc2fe58a6b55e85e77f665becb024f076a133f158af65eb1670ca25d854` | 逐叶子路径 diff 证据（53 个公共路径全部相等；0 修改 / 0 删除 / 新增 2 键 20 叶子） |
| `work/ai-solver/step5b/solve_cli_scoped.py` | 16,227 | `efacc4d04e38f773d2b85dd01067607a9c06678ff3800167f97ec15592bf0a62` | **新调试入口**：`solve_cli.py` 的副本，**默认 `--dataset-scope v1_intended72`**；`v2_diagnostic` 模式显式打印"仅诊断、非全域" |
| `work/ai-solver/step5b/scoped_cli_diff.txt` | 10,382 | `b00073b207ce77b6db199d36fa77d155dd35315023e1c666e37647df46fcb4f6` | 与 step5 `solve_cli.py` 的统一 diff（169 行） |
| `work/ai-solver/step5b/scoped_cli_diff_evidence.json` | 9,711 | `521c0da363f0fa7e2de9547a4b7344e149d3e9763596d68cb62fa680ddd49a3c` | 15 处替换的逐条登记（每处"为什么改"）+ 行为等价声明 |
| `work/ai-solver/step5b/cli_scope_comparison.txt` | 29,860 | `31b98ea403b33dcf70aee6b71e3c88e4179e664de6786752b47deb8ede205bd3` | 8 次真实调用的**原文**（含默认口径 vs 诊断口径） |
| `work/ai-solver/step5b/cli_scope_equivalence.json` | 1,383 | `912a0e75f864e1b18db7c8afa276d17bd7c002974faa0ab83a8fd95a6c513e02` | 逐行等价核查：step5b 默认 == step5 + `--variant V1_intended72`（剔除口径行后 **0 行差异**） |
| `work/ai-solver/step5b/queries_scope_demo.csv` | 199 | `f4c6e4af7f73c7dca753193eeca7fad77fb33593ba639ec96f3de91b6ae5053f` | 批量演示输入（4 行，含 N1=12 与 N1=9） |
| `work/ai-solver/step5b/answers_scope_demo_v1_default.csv` | 2,119 | `c318a58377a5e1653dee967dede9a7983b799737a61cec8f1af90d7fb1f94487` | 批量结果（默认口径；含 `dataset_scope` 两列） |
| `work/ai-solver/step5b/answers_scope_demo_v2_diagnostic.csv` | 2,576 | `1405c72735a0268382a49c9dadacb76a47d21539d25abc1b20d89797a7ee1243` | 批量结果（诊断口径） |
| `work/ai-solver/step5b/refusal_replay_both_scopes.json` | 4,781 | `92d1a3bc017f4838c65f4c250409d21887b08679686d955aab07b91c19cab722` | 第 4 步 11 例**只读重放**：9 拒答 / 原因 **11/11 逐字相同** |
| `work/ai-solver/step5b/impact_selfcheck.json` | 6,855 | `735c4c89fb9b39efc6e18ab561595d38d83036ff413c0b7aaa2ce20a1eee0fa5` | 影响面逐项自查（见 §5） |
| `work/ai-solver/step5b/step4_step5_untouched_verification.json` | 27,767 | `bbb6f87f8e8809840a2d7d4084439ce672c4d4ae5e90da9b81a7340c9cd2ea1f` | **未改动证明**：step5 38/38、step4 39/39 逐件哈希相同（见 §6） |
| `work/ai-solver/step5b/step5b_scope_correction.py` | 32,872 | `389bc42b89ad13904f5752896183a90cb325ab87df8e5ee2819b6deebcce07a8` | 生成器（可重放 §2 前五件） |
| `work/ai-solver/step5b/step5b_make_scoped_cli.py` | 14,932 | `15dd65a404e20654b12c06da987e0e08b3ce3085c27cc082cb63957cefad7455` | scoped CLI 生成器（15 处替换必须恰好命中 1 次，否则 raise） |
| `work/ai-solver/step5b/manifest_step5b.json` | 4,007 | `9bb6d1a0f58dfa2face4a14762f61da117e853b9b13aed1be3a62ccd35be0486` | step5b 产物清单（对上表 16 件逐件核对通过） |

---

## 3. "只改了三处"的证据（对 `s_grade.json` 的**逐字段** diff）

更正后副本 = step5 `s_grade.json`（12,606 B / sha256
`a96bed031807bd377af25bd363f890784319d8c3b949d4ad5d003e7e9da7ffbd`）**逐字段照抄** + 仅新增 2 个顶层键：

1. **`primary_model_scope` = `"V1_intended72"`**；
2. **`scope_correction.v2_all162_qualification` = `"diagnostic_only_not_a_valid_全域"`**（附理由）；
3. **`scope_correction.why_no_selection_leakage`**＝"没有选择泄漏"的说明（第三处"改动"是这条**说明性新增**）：

> step5 的**预注册规则 R1**（规则文件在跑任何留出指标之前落盘）在 `V1_intended72` 与 `V2_all162`
> **两个变体上独立选中了同一个候选 `M2_log10_gp`**：V1 总分 `0.05565914101498737`（14 单元中位，第 1 名）、
> V2 总分 `0.1409929401218602`（14 单元中位，第 1 名）。因此把主模型的**适用范围**由 V2 改挂 V1
> **不涉及任何基于指标的重新选择**；原始证据 `work/ai-solver/step5/raw/primary_models.json`
> （sha256 `27c4c0a1bb1af9af22869bc06691e8106adc4f373d6c90c62e1b4eae4066c96b`，
> `generated_at = 2026-09-15T12:42:40` 早于 compute 的 12:46:54，`used_holdout_data=false`）。
>
> 同时登记一处**数字更正**：本次任务的上游通报里 V2 总分曾被写作 `0.14099342…`；
> `primary_models.json` 里的真值是 **`0.1409929401218602`**，本文件与 step5b 的全部产物一律用真值。

**逐叶子路径 diff（机读 `s_grade_diff_evidence.json`）**：

| 项 | 值 |
|---|---|
| 公共叶子路径数 | **53** |
| 其中取值相同 | **53（100%）** |
| **被修改** | **0** |
| **被删除** | **0** |
| 新增叶子路径 | 20（全部位于 2 个新增顶层键之下） |
| 新增顶层键 | `primary_model_scope`、`scope_correction` |
| 判定 | **"只新增 2 个顶层键；既有字段 0 修改 / 0 删除"** |

即：`solver_certified=false` / `releasable_as_solver=false` / `approved_for_use=false` / `model_state=draft`、
S0–S5 的全部状态与数字（含 `by_regime` 的 16 条指标记录、`blocked_by` 列表、`positivity_weak_check`）
**逐字段一字未改**。**step5 的原件 `s_grade.json` 也未被改动**（在 §6 的 38/38 里）。

---

## 4. CLI 的默认范围变更（真实调用对照）

`solve_cli_scoped.py` 由 step5 的 `solve_cli.py` **复制 + 15 处受控替换**生成（每处要求恰好命中 1 次；
统一 diff 169 行见 `scoped_cli_diff.txt`）。其中**唯一的行为性改动**是"默认数据集口径"：

```
--dataset-scope {v1_intended72, v2_diagnostic}   默认 = v1_intended72（= 有效域）
--variant       变为可选覆盖（默认 None；显式给出时优先，便于复现第 4 步示例）
```

其余替换为：文档头、把 step5 目录加入 `sys.path`（复用其核心模块与冻结件，只读）、
口径常量、口径声明行/警告、批量 CSV 的两列口径字段。

### 4.1 等价性：默认口径 == step5 + 显式 V1（剔除口径行后 0 行差异）

`cli_scope_equivalence.json`：`lines_identical_after_dropping_scope_lines = true`，`n_diff_lines = 0`
（对照双方：`step5/solve_cli.py --variant V1_intended72` 与 `step5b/solve_cli_scoped.py`（默认））。

### 4.2 同一查询在两种范围下的差异（原文节选，全文 8 次调用见 `cli_scope_comparison.txt`）

```text
### [A2] solve_cli_scoped.py（默认口径）
第 5b 步调试入口（**范围更正后**）| 旧参数（legacy 单电极 / 1 Ω 驱动）标量代理
数据集口径 dataset_scope = v1_intended72：有效域（= 用户本意 N_w_te1 1–8；平台预检 intended_design + eligible_for_ranking=True）
查询: variant=V1_intended72 target=Ptot x_scale=0.6 N_w_te1=6 freq=20 MHz
判定: 域内接受   预测: Ptot = 6.582e-06 W
90% 保形区间（值空间）: [6.35713e-06 , 6.80687e-06] W  相对半宽 ±3.416%
  校准证据: q=5.22644  sigma_rel(MAD)=0.00653673  n_calibration=72  certified=True
旧数据真值: y_true=6.56232e-06 W  →  并排相对误差 0.2999%

### [A3] 同上 + --dataset-scope v2_diagnostic
数据集口径 dataset_scope = v2_diagnostic：**仅诊断、非全域**（162 组合中 90 个 N_w_te1 9–18 属本意之外，平台预检判为 boundary/reversed + selection_mismatch）
!! **本模式仅诊断、非全域**：V2（162 组合）含 90 个非预期组合（N_w_te1 9–18），不得作为有效设计域；有效域请用默认 --dataset-scope v1_intended72。
查询: variant=V2_all162 target=Ptot x_scale=0.6 N_w_te1=6 freq=20 MHz
判定: 域内接受   预测: Ptot = 8.16275e-06 W
90% 保形区间（值空间）: [3.22571e-06 , 1.30998e-05] W  相对半宽 ±60.48%
  校准证据: q=4.34057  sigma_rel(MAD)=0.139342  n_calibration=162  certified=True
旧数据真值: y_true=6.56232e-06 W  →  并排相对误差 24.39%
```

**这条对照本身就是范围更正的价值证据**：同一个已测点上，**有效域模型（V1，72 组合训练）误差 0.30%、
区间 ±3.4%**；**混合口径模型（V2，162 组合训练）误差 24.4%、区间 ±60.5%**——两者的差别
**不是新算出来的**（两个模型在 step5 就已存在、且都由预注册规则选中），只是**挂载范围**改对了。

### 4.3 范围改动的实际后果：有效域外的点被拒答

```text
### [A4] N1=12（默认口径）→ **拒答**：N_w_te1=12 超出适用盒 [1, 8]        fallback: COMSOL
### [A5] N1=12（--dataset-scope v2_diagnostic）→ 域内接受：Ptot = 2.36385e-07 W（真值 2.3644e-07 W，误差 0.0233%）
### [A6] N1=9（默认口径）→ **拒答**：N_w_te1=9 超出适用盒 [1, 8]         fallback: COMSOL
### [A7] x=0.9（默认口径）→ **拒答**：x_scale=0.9 超出适用盒 [0.4, 0.8]（行为与 step5 相同）
```

批量（`queries_scope_demo.csv` 4 行）：默认口径下 N1=12 与 N1=9 两行**拒答**、其余两行出解；
诊断口径下 4 行全部出解但 CSV 与文本都带"仅诊断、非全域"标签
（`answers_scope_demo_v1_default.csv` / `answers_scope_demo_v2_diagnostic.csv`）。

---

## 5. 影响面逐项自查（`impact_selfcheck.json`）

**核心论证**：*范围归属不是任何指标计算的输入*。所有已算数字都是
"在给定 `(variant, target, freq, fold, candidate)` 上拟合/预测/校准"的结果，输入只有
**冻结数据值、切分定义、超参网格、来源/保真度标签**。改变"哪些组合算有效设计点"改变的是
**解释与使用范围**，不改变上述任何输入 ⇒ **数字不会变**。因此本轮**不重算**：重算只会重复得到同一批数字，
却会破坏 append-only 与既有哈希引用（且任务单明令禁止重跑/改选）。

| 既有产物 | sha256 | 是否受影响 | 结论与证据 | 为什么不重算 |
|---|---|---|---|---|
| `work/ai-solver/dataset/ds_V1_eligible72_grouped.json` | `c63632cd8f4fcbad854177ec6eced024d709fab6fe971e76bf7045fdb4b426c9` | **否** | 它就是 intended 72 组合 × 7 频 = **504** 个 sample_id、单族 ⇒ **与更正后的有效域完全一致**；`v1 ⊂ v2` 成立 | 它是**声明件**且内容已等于更正后主范围；重算会改动一个已被第 1–3 步报告哈希引用的文件 |
| `work/ai-solver/dataset/ds_V2_all162_grouped.json` | `0c6d83d7dc48149af9f025bbc3ad7c547c27595455c7d9e5f0d5faa6ee0541f9` | **仅角色标签**（`role_label_only`） | 1,134 个 sample_id；`v2 \ v1` = **630** 个 id（= 90 组合 × 7 频）；其 `cross_family_holdout=true` 作为**评估口径**的陈述仍为真；但**用途标签**降级为"仅诊断、非全域" | 若把 90 组**剔除**再生成，那是**新数据集版本**而不是更正（append-only 要求修正以新增实现）。本轮不做，也不改本文件 |
| `work/ai-solver/step5/candidate_metrics_all.csv` | `e3c9aa68445ea98c35f4b50252561dc13497606c3ec0537741802427c60148f9` | **否（数字）** | 128 行全部保持原样；改变的只是**读法**：V2 相关场景的指标现在只能作诊断口径解读，V1 行是更正后的主口径 | 同上（范围归属不在指标输入里）；且 step5 已用**逐格**证据证明同代码重算逐值复现（recheck 64/64、与第 4 步误差/覆盖率/半宽各 64/64 一致） |
| `work/ai-solver/step5/s_grade.json` | `a96bed031807bd377af25bd363f890784319d8c3b949d4ad5d003e7e9da7ffbd` | **否**（原件不动；更正写进**新文件**） | 见 §3：更正后副本仅新增 2 个顶层键，53 个公共叶子路径 100% 相等 | S 级/放行依赖的阈值与实测数字都没变；需要更正的只有"挂载范围"与"V2 定性"两条归属信息 |
| `work/ai-solver/step4/refusal_examples.json`（+ `.csv`） | `18b39bec783f83806d49fcb8e24f4e193f45e17a781441d2b4910a4e7b5887a0` | **否** | 拒答规则基于"适用盒 / 精确频点 / 族 / 驱动口径 / 目标量"，与"有效设计点归属"无关；**只读重放 11 例，9 拒答、原因 11/11 逐字相同**（`refusal_replay_both_scopes.json`） | 拒答是**域判定**结果，与指标无关；本轮只做只读重放复核 |
| `work/ai-solver/step5/refusal_replay.json` | `d3225dc01feae0b9a4230fe16197b080c822cf391ab754f0cfaa8855a888faee` | **否** | 同上；且它被 step5 报告与 manifest 哈希引用 | 同上 |

**如果不许重算却"当作数据改了"会怎样**（登记为反事实，未执行）：把 90 组从训练集剔除后重训，
V2 模型的训练集将从 162 降到 72，会得到**另一批数字**——那是**新实验**，本轮明确不做。

---

## 6. "未改动什么"（逐件证据）

`work/ai-solver/step5b/step4_step5_untouched_verification.json`：

| 对象 | 基准 | 核对结果 |
|---|---|---|
| `work\ai-solver\step5\` | 它自己的 `manifest.json`（35 件可复现产物 + 3 件含时间戳件的 sha256） | **38/38 逐件哈希相同**（`all_match=true`） |
| `work\ai-solver\step4\` | `work\ai-solver\step5\raw\scratch_step4_copy_manifest.json`（39 件，step5 计算阶段登记） | **39/39 与登记哈希相同**；且与 scratch 副本现状 39/39 相同 |

未改动的范围还包括：**全部指标**（误差 / 覆盖率 / 半宽 / 域内非正比例 / 候选排名）、
**全部阈值**（S0 <1%、S1 关键区<2%/全域≤5%、S2 <3%、S3 硬门禁、S4 <2%、S5 85–95%）、
**放行结论**（`solver_certified=false` / `releasable_as_solver=false` / `approved_for_use=false` / `model_state=draft`）、
第 4 步与第 5 步的全部报告文本、`work\tools\` / `src\` / `work\models\` / `work\store\` / 用户目录。

**本轮唯一的新增写入** = `work\ai-solver\step5b\`（17 件，含 manifest）与本文件（`docs\` 新增）。

---

## 7. 未做到 / 不确定（主动列出）

1. **F4 未能独立复跑**：M7 的运行时回读是**平台记录级**证据（本轮不许启动 COMSOL）。
   但"18 档"由 F3 的数据实测独立坐实，F2 的 `.m` 末尾赋值由本轮直接读取坐实 ⇒ 结论不依赖单一来源。
2. **用户原话的时间戳**：我登记的是**转达给我的时刻**（2026-09-15T16:12:34+08:00），
   不是用户说这句话的原始时刻（我无法观测）。
3. **"有效域 = 1–8"是意图层面的更正**；V2 口径下的既有指标仍是**混合口径**（含 90 个非预期点）——
   这在标签上已写清，但**没有**把 V2 的指标重算成"仅 1–8"。若将来需要"只按 1–8 训练并评估"，
   那是**新实验**（本轮明令禁止）。
4. **父代理表述的一处细化**（非分歧）：`N1=9` 的定性是 `design_boundary_coincident`（`selection_status` 仍是
   `verified`），与 `N1 10–18` 的 `design_region_reversed + selection_status=selection_mismatch` **不是同一类**；
   本文件按预检 CSV 的原始取值分列（9 + 81 = 90）。
5. **未把 90 组建任何"黑名单"数据结构**（如独立的 `excluded_combos.csv`）：
   它们已完整列在 `scope_correction.json.expected_vs_unexpected_partition.explicit_combos`（90 条，
   带预检判定字段），本轮不再另建一份可能与之漂移的副本。
6. **CLI 的 `--variant` 与 `--dataset-scope` 同时给出且冲突时**：以 `--variant` 为准（写入代码注释），
   此时打印的 `dataset_scope` 标签仍按 `--dataset-scope` 显示——这是一个已知的**显示层**不一致，
   本轮未加互斥校验（避免为一个小分支改动出解路径的代码）。
