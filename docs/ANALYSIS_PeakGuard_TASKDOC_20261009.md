# 外部任务书对账分析：《给 DeepSeek Harness 的 PeakGuard 模型修改完善任务书》

> 分析日期：2026-10-09
> 被审对象：`TO_DEEPSEEK_HARNESS_PeakGuard模型修改完善任务书_20261009.md`
> 21,126 B ／ sha256 `a5af81d1d2eca913c9ebd2e6ea2531f021279080296d2c84ac18162ecca491f4`（本轮实测，与工单给定值逐位一致）
> 被审文件**只读**，本分析**未改**该文件一个字节。
>
> **本分析的性质与边界**：纯只读对账 + 结构化清单。**未改任何代码、未改任何既有产物、未改论文、未跑 COMSOL、未跑 pytest、未提升任何状态**
> （`work/runs/solver/pmut-f1/solver_spec.json` 仍 `state=draft`；`work/runs/multichannel-surrogate-20260929/multichannel_model.json` 仍 `status=draft`）。
> 拿不准的一律写「需人工核对」，不做推测。机读版见同目录 `ANALYSIS_PeakGuard_TASKDOC_20261009.json`。

---

## 0. 一句话结论

任务书描述的「PCHIP + 一步线性外推原型」**确实就是本仓库的多通道一阶峰代理**
（`src/memsharness/multichannel_surrogate.py` + `work/runs/multichannel-surrogate-20260929/`），
但它把论文方法名 **`PeakGuard`** 当成一个待建的代码产品来下指令 ⇒

1. **「PeakGuard」在代码里 0 命中**（它只是 `docs/PMUT_DAC2027_初稿_v2…v6_20261009.md` 里的方法名）；
2. 任务书 §3.2 新引入的五个状态名 `valid_closed` / `no_internal_peak` / `open_left` / `open_right` / `isolated`
   **正是本仓库已被裁定为「无来源（自造分类）」并已从论文删除的五个名字**（`PAPER_REVIEW_DAC2027_20261009.md` N69 / D-03）；
3. 任务书 §2 的十个「当前问题」中，**M4（保形校准）、M6（部分）、M7（persistence 基线）、§4.2 标签重建的 5/6/8 条、§8.1 两条**在本仓库**已经实现**；
4. 任务书**没有提到**本仓库当前真正的阻塞链（S3 `failed`、S0 缺闭式解、te2_9 导出【待产物】、四项口径待裁定、跨批 137 组标签冲突【待裁定】），
   其 §9「P0 立即执行」把**改判定语义**（默认禁止 N2 外推、软拒答阈值）排在**需要人拍板**的位置上。

⇒ **按原文整体执行会造成第二/第三套并行事实源，并触碰多处「改判定语义」红线；必须先拍板 8 个问题（见 §5）。**

---

## 1. 它到底要什么（客观复述，不评价）

任务书要求把「以 PCHIP 和一步线性外推为主的原型」升级为 **PeakGuard v2**，用于 DAC 2027 论文实验：

1. **窗口语义层**：区分「扫描窗口内未观测到峰」与「物理上不存在谐振峰」，引入 `canonical_window_id` 与 `censored/unknown` 状态；
2. **层级状态模型 B1/B2/B3**（峰可观测性 → 带宽闭合性 → 未闭合方向）＋ 行政状态（`isolated`/`invalid_solver`/`missing_channel`/`hash/provenance_failed`）不走物理分类器；
3. **条件多目标回归**：仅在标签有效时预测三个正式目标（`abs_w_m`、`bandwidth_Hz`、`abs_p_per_V_Pa`），允许目标级缺失掩码；
4. **独立不确定性校准**：分类概率校准（Platt / isotonic / temperature）＋ 回归 split conformal，`in_layer` 与 `cross_layer` 分别校准；
5. **fail-closed 拒答**：硬拒答（结构/域/隔离/版本/通道/N2 层/场级 N1）＋ 软拒答（概率阈值、区间宽度、模型分歧、到训练样本距离、低密度、物理一致性），阈值冻结在 calibration 集；
6. **固定预算闭环 DSE**：统一 DOE／候选空间／COMSOL 预算／三个目标，`acquisition = EHVI × P(valid_closed) × P(pass_Q_and_safety) × uncertainty_gate`，候选经 COMSOL 回算才计入 Pareto；
7. **强基线 + 消融**：persistence / 分层线性 / PCHIP / RBF / GP / XGBoost-CatBoost / MLP / 标准 BO，9 项消融 × ≥5 种子；
8. **交付**：新建 `work/runs/peakguard-v2-YYYYMMDD/`，含 24 件具名产物（`MANIFEST.json`、`DATA_CONTRACT.md`、`data_manifest.tsv`、`split_manifest.tsv`、`thresholds_preregistered.json`、`refusal_ledger.tsv`、`hypervolume_by_budget.tsv` …），全部非空、有 schema/version、有 SHA-256、可从冻结输入重建、不覆盖既有冻结结果。

执行顺序：**P0 立即执行（原则上不需新增 COMSOL）** → **P1 协议冻结后（需新增高保真计算）** → **P2 主论文完成后再考虑**（更多连续变量、N2=9 泛化、全场 POD-ROM/神经算子、多器件族迁移、实验样机校准）。

---

## 2. 「PeakGuard」在本仓库现在对应什么（重复造轮子检查）

| 检索 | 结果（本轮实测） |
|---|---|
| `PeakGuard` 在 `src/`、`scripts/`、`tests/`、`schemas/`、`.dsh/` | **0 命中** |
| `PeakGuard` 在 `docs/` | 仅出现在 `PMUT_DAC2027_初稿_v2/v3/v4/v5/v6_20261009.md`、`PAPER_REVIEW_DAC2027_20261009.md(.json)`、`PAPER_REVISION_LOG_20261009.md` —— **全部是论文文本** |
| 任务书所指「原型」 | `src/memsharness/multichannel_surrogate.py`（8 通道、层内 PCHIP + N2 一步线性外推）＋ `work/runs/multichannel-surrogate-20260929/`（预注册 / 拟合脚本 / 结果 JSON / 报告），状态 `status=draft`、`version=v1` |

**判定**：`PeakGuard` = **论文里的方法名**，不是代码对象，**与本仓库 P1 刚落地的 `guards_*` 毫无关系**。

> ⚠️ **同名不同物风险（高）**：`guards_metatest.py` / `guards_readonly.py` / `guards_denominator.py` /
> `guards_envfacts.py` / `guards_indexlock.py` 是 §116 登记的**五条元守卫**（可失败性元测试 / 证据只读 R16 /
> 分母纪律 / 环境事实时间戳 / 索引单写者），与代理模型、拒答、校准**没有任何关系**。
> 本仓库已有**多起同类前科**，任务书新增命名会继续加剧：
> - `p_total` vs `acpr.p_t`（§97，最终查明 `p_total_Pa = acpr.p_t`）；
> - **三套隔离键**：标签表 `quarantined`（`first_peak.py`）／模型 `excluded_quarantine`（`multichannel_surrogate.py`）／响应级 `quarantined_combos`（`surrogate.py`）——§109.9、§101.2 记录「三者不得混称」；
> - **flag 口径（`ranking_eligible` 222/236 行）vs 可判定口径（478/520、509/537）**——§113.3/§116.4，差 2 倍以上；
> - **`batch` 标签 vs 真实子批**——§94 把 C 批里那 223 行 5–35 MHz 数据**改登记为独立子批**。

---

## 3. 与现状冲突 / 已重复的项（逐条：原文 ｜ 证据 ｜ 判定）

> 每条给「任务书原文片段（`§` = 任务书节号）」＋「仓库证据位置」＋「判定」。
> 判定用语：**已重复** / **口径冲突** / **与既有裁定冲突** / **过时** / **新增（非冲突）**。

### C1 状态名去而复返 —— `valid_closed` / `no_internal_peak` / `open_left` / `open_right`

- **原文**：任务书 §3.2「B1: `peak_observed_in_window = 1/0`」「B2: `bandwidth_closed = 1/0`」「B3: `open_left`；`open_right`；`open_both/insufficient_grid`」；§5.3「`P(valid_closed)` 低于校准阈值」。
- **证据**：`docs/PAPER_REVIEW_DAC2027_20261009.md` **N69**：`valid_closed`/`no_internal_peak`/`open_left`/`open_right`/`isolated` 在 `src/memsharness/*.py`、`scripts/*.py` 中出现次数**均为 0** ⇒ 判定 **「无来源（自造分类）」**；`PAPER_REVISION_LOG_20261009.md` **D-03** 已把这五个名字从论文 §3.2 **替换**为真实字段表；`docs/PMUT_DAC2027_初稿_v6_20261009.md` **L116** 原文：「v1 稿中的五个状态名 `valid_closed` / `no_internal_peak` / `open_left` / `open_right` / `isolated` 在仓库源码与表列中检索为 **0** 次，故本节改为真实字段」。
- **判定**：**与既有裁定冲突（回退）**。任务书把它们当 v2 新架构引入，等于把**已删除的自造状态名重新写回**。仓库真实字段是 `first_peak_found` / `peak_closed` / `bandwidth_closed` / `ranking_eligible` / `quarantined` / `peak_at_scan_endpoint` / `bw_upper_cutoff_at_endpoint`（`multichannel_labels.csv` 64 列实测）。另：`open_left` 在现有数据里**从未独立计数**——C 批不闭合的实测口径是**「89 例右截止超 50 MHz」**（§70.2），即只有 `open_right` 方向有数；照任务书写「`open_left` 若未闭合则…」会给出**无数据的桶**。

### C2 M4「各通道仅有经验残差区间」——已经就是独立校准集 + split conformal

- **原文**：§2-M4「各通道仅有经验残差区间 / 区间可能欠覆盖 / 独立校准集 + split conformal/等价严格协议」。
- **证据**：`work/runs/multichannel-surrogate-20260929/PREREG_multichannel_surrogate.md` **§7「保形区间与覆盖率」**原文：「**n2_extrap 模式**：用**标尺折**（L-N2ex 5/6/7）的残差作**保形校准集**…；**in-layer 模式**：用 S-D(h=0.02) 的测试点按 seed=0 **对半切**——一半作校准、一半作评估，**两半不重叠**」「α ∈ {0.10, 0.05, 0.01}」；`multichannel_model.json` 的 `conformal` 块实测含 `in_layer` 与 `n2_extrap` 两个模式，**8 个通道 × 3 个 α** 全部有半宽值（例：`in_layer.bandwidth_Hz = {0.1: 0.0206, 0.05: 0.0354, 0.01: 0.0954}`）。
- **判定**：**已重复**。任务书 §5.2 的六条协议中 **第 1–5 条（train 只看 train／非一致性分数由 calibration 生成／test 不参与定宽／两模式不同校准器／逐通道分别校准）在本仓库已经满足**；只有第 6 条（三目标**联合**覆盖）未做 —— 而论文已按 A5 明确「不要宣称严格 conformal guarantee」。

### C3 M6「缺少冻结的 train/cal/test」——部分已做，且已有更强的东西

- **原文**：§2-M6「缺少冻结的 train/cal/test / 存在调参泄漏风险 / 按完整设计组合冻结三分法和哈希」。
- **证据**：`PREREG_multichannel_surrogate.md` 在**看任何留出集指标之前**写定折与判定带，其 sha256 被结果 JSON 记录并被用例断言「当前哈希 == 记录哈希」**（判定带被事后改动会立刻失败）**；`INDEX §113.1` 已落地**防泄漏整组切分**：以 `(round(x_scale,6), N_w_te1, N_w_te2)` 为组，**1926 组**、train 1578 / holdout 677（seed 0），`train ∩ holdout` 组合键 **0**（字面/repr/round-6 三口径同时为 0，seed 0–4 全部成立），产物 `grouped_split_assignments.csv`（sha `30f75893…`）等 4 件。
- **判定**：**部分已重复 + 部分新增**。已做：预注册冻结、组合键防泄漏整组切分、哈希锁定、5 种子。**未做**（任务书这点成立）：**单一冻结的 train/cal/test 三分清单 + 种子 + SHA**（§113.6 明写「**未做分层切分**」、`PREREG §7` 的校准集是从各折残差临时取的**不是独立冻结清单**）。

### C4 M3「N2 一步外推默认禁止」——与已冻结的预注册结构冲突

- **原文**：§2-M3「N2 一步线性外推缺少稳定增值证据 / 产生看似合理但无依据的结果 / **默认禁止外推**；单独建立跨层测试与门禁」；§3.4「如果跨层模型不优于 persistence 基线，则该模式保持拒答」。
- **证据**：`PREREG §4.2` 把「固定 `(N1,x)` 用**最近的两层**在 N2 上线性外推，**只允许 1 步**」**写进预注册**；`multichannel_surrogate.py` **L252–277** 是它的实现；`structure.n2_direction` 原文即此；§113.3/§114 已用 30 个「口径×种子」实测该模式的 lift（`bandwidth_Hz` 旧 −0.00180 → 整组 −0.00716；且 §114 登记**符号依赖留出层** ⇒ 结论不稳）。
- **判定**：**与既有裁定/预注册冲突**。「默认禁止外推」是**改判定语义 + 缩小已冻结能力域**，红线 5（人保留放行权）范围，**必须人拍板**；不能由任务书自行决定。且任务书说「缺少稳定增值证据」——仓库已有 persistence 基线证据并把 `channels_without_lift = ['bandwidth_Hz','Q_factor']` 写进冻结模型，任务书**未引用**。

### C5 扫描窗口口径不完整 —— 仓库有三套并存栅格，任务书只提「5–50 MHz」

- **原文**：§1.4「原 `5–50 MHz` 窗口中的 `no_internal_peak` 只能表示…」；§2-M9「多批次窗口、步长、通道不同」；§4.3「训练主模型时，建议只使用同一规范窗口或已由扩扫补全状态的样本」。
- **证据**：`work/runs/labels-dupkind-refined/20261008T215100/labels_two_batch_dupkind_refined.csv`（2255×31，sha `21e807ee…`）实测按批计数 = **`A_5-35MHz` 223 / `C_5-50MHz` 1782 / `V2_5-35MHz` 250**；V2 是 **0.5 MHz 步长 / 61 点**（§92.1），且**缺 `abs_w_m`/`abs_p_Pa`/`abs_p_per_V_Pa`/`abs_vz_struct_m3s` 四列** ⇒ **三批并集跑不了 8 通道**（§113.3）；跨批同组合标签**确实不一致**（`bandwidth_Hz` 中位相对差 **0.2301**、`>5%` 200/324；§113.2）且**137 组**冲突标 **【待裁定】**；§95 用户裁定 **O-A：不去重、一行不删**；§92.3 记录组合身份键**必须先做 ulp 归一化**（否则新增数虚高 34）。
- **判定**：**口径含糊 + 遗漏既有未决裁定**。任务书用「5–50 MHz 窗口」一个词覆盖三套不同栅格、两种步长、四列缺失与一处未决裁定；而它 §4.3 只给「建议」。**照做会在未裁决的 137 组冲突上默认选边。**

### C6 §4.2「重新生成标签」的 10 条中已有多条是现行做法

- **原文**：§4.2「5. 使用同一峰计算左右 `-3 dB` 交点；6. 未闭合带宽写空，不得写零或伪造边界值；8. **同时保留网格点带宽与插值带宽两列，正式口径只能选一列**」；§8.1「未闭合带宽为空，不为 0」。
- **证据**：§69 用户裁定原文「峰被扫频边界截断或 −3 dB 带不闭合 ⇒ **记空并标注，绝不填 0**」；§70.2「正式带宽方法 `single_dof_fit`（RMSE 中位 0.0096、max 0.114 dB）；**网格交点值另列 `bw_grid_Hz/Q_grid` 供审计**」；§71.1 用户裁定「带宽组**只用绝对 −3 dB 带宽**排名」；`multichannel_labels.csv` 实含 `bw_grid_Hz`… 对应列（`f_lo_3dB_Hz`/`f_hi_3dB_Hz`/`bandwidth_Hz`/`method`/`extrapolated`）。
- **判定**：**已重复**（任务书第 5/6/8 条均已落地；第 8 条「两列并存、正式口径选一」仓库已在 §70.2/§71.1 做完并裁定）。

### C7 §3.2「行政状态」含 `isolated` —— 该门在预测路径上**不生效**（实测）

- **原文**：§3.2「以下状态不进入物理分类器：`isolated`；…这些状态由预处理硬门禁处理」；§5.3 硬拒答「命中隔离或求解失败记录」。
- **证据**：§109.9 表格原文：「`predict()` 对 `excluded_quarantine` 的读取 —— **一字未动**（隔离议题仍「另议」；该字段在预测路径上**仍未生效**）」；§101.2 第 3 条：`excluded_quarantine = [[0.2,1,7],[0.2,1,8]]` **只出现在 `model_card()`**（`multichannel_surrogate.py` L112），`predict()`（L222）/`check_domain()`（L168–L178 四条分支）**均无该分支**；`docs/PMUT_DAC2027_初稿_v6_20261009.md` **L183/L185** 已按此改写并注明「\(I_{iso}\) **仍为未生效的披露项**」；实测那两点在该 476 点网格被拒的**真实原因是 `x=0.20` 低于层标定下界 `0.31`**，「命中隔离记录」**触发 0 次**。
- **判定**：**与既有实测冲突 / 高风险**。任务书把「隔离」写成一条硬门禁并在 §3.2 把它当作**已生效的预处理**；照做会再次产出「看起来生效的门」（本仓库已有前科，§103/§109 专门为此做过措辞更正）。**要真生效必须先改 `predict()` —— 属改判定语义，须人拍板。**

### C8 `cross_layer` vs 仓库 `n2_extrap` —— 同物异名

- **原文**：§3.4「N2 跨层预测必须作为独立模式 `cross_layer`，与层内模式 `in_layer` 分开训练、校准和报告」；§5.2 第 4 条「`in_layer` 与 `cross_layer` 使用不同校准器」。
- **证据**：`PREREG §4.2` / `structure.n2_direction` / `conformal` 的模式键实测为 **`("in_layer", "n2_extrap")`**；`predict()` 返回 `"mode": "in_layer" | "n2_extrap"`；`model_card()` 的 `half_width_by_mode` 同样用这两个键。
- **判定**：**同义不同名（须先定名）**。语义一一可映射，但若照任务书改名，会改掉冻结产物 `multichannel_model.json`（sha `0d872fb1…`）的键 ⇒ 所有引用它的用例、网页端点、E3 证据包与论文数字都要重锚。

### C9 §4.1 样本主键字段名与仓库现有列不一致

- **原文**：§4.1 列出 `sample_id` / `run_id` / `model_sha256` / `window_id` / `batch_id` / `peak_state` / `bandwidth_state` / `is_isolated` / `is_valid_solver` / `source_artifact_sha256` 等 24 个字段。
- **证据**：`labels_two_batch_dupkind_refined.csv`（2255×31）实测列：`batch`/`source_file`/`x_scale`/`N_w_te1`/`N_w_te2`/`freq_range_MHz`/`peak_freq_Hz`/`bandwidth_Hz`/`Q`/`zeta`/`spl_dB`/`peak_closed`/`ranking_eligible`/`usable`/`source_type`/`source_pipeline`/`source_dataset`/`x_density_class`/`freq_grid_MHz`/`n_freq`/`source_model`/`peak_at_scan_endpoint`/`bw_upper_cutoff_at_endpoint`/`dup_score`/`dup_of`/`dup_kind`/`batch_v2_original`/`freq_range_v2_original`/`batch_basis`/`freq_range_source`/`dup_kind_refined`；`multichannel_labels.csv`（2005×64）另有 `quarantined`/`q_gate_pass`/`first_peak_found`/`bandwidth_closed` 等。
- **判定**：**须先给映射表**。`is_isolated`→`quarantined`、`is_valid_solver`→**无对应列（需人工核对）**、`window_id`→**无对应列**、`peak_state`/`bandwidth_state`→需由 `first_peak_found`/`bandwidth_closed`/两个端点标志组合导出。**不先映射就是第三套命名。**（§4.1 末句「不允许依靠表格行号、marker 顺序或文件名隐式推断参数归属」仓库已吃过亏并已裁定，见 §69.1/§70.2 —— 这条属**已重复**。）

### C10 §8.1 驱动电压元数据 —— 已是裁定并已入表

- **原文**：§8.1「驱动电压元数据均为内 `-1 V`、外 `0 V`、`ΔV=1 V`」。
- **证据**：§70.1 原文：「⚠️ **更正：驱动电压是 1 V，不是 2 V**（我的错误）…裁定 §2：**内电极 −1 V、外电极 0 V ⇒ ΔV = 1 V**；**禁止**表述为「外电极 +1 V、内电极 −1 V 的 2 V 反相驱动」」；`multichannel_labels.csv` 实含 `v_inner_V`/`v_outer_V`/`delta_V_V`/`normalization_formula`/`abs_p_per_V_Pa`/`spl_per_V_dB`。
- **判定**：**已重复**（已裁定、已入表、已归一）。

### C11 §1.5 场级 POD 口径滞后

- **原文**：§1.5「当前 7 快照场级模型最坏 `rel_L2` 仍很高，不能作为可信 ROM…场级 POD 暂不作为 PeakGuard v2 主模型」「不得宣称…场级代理已放行」。
- **证据**：§87.3 实测 7 快照在 2%/5% 两阈值下都**不放行**（最坏折 0.8089）；但仓库**已推进**：§88–§90 路线甲 x 单参数族（`N1=4`、81 快照）**S1 转 passed**（§92.4：关键区 max **0.0070**、全域 max **0.0109**，模型 B）；场级对象已改为**离散查表 + 拒答**（`src/memsharness/field_lookup.py`，§87.4：小数 N1 ⇒ 拒答、源码禁出现任何插值调用）；`S3 failed`、`S4` 旧阶梯口径 O `failed`/新 6 档 `passed`、**405 组不得展开**（§104/§111）。
- **判定**：**部分已重复 + 口径过时**。「不宣称已放行」与仓库一致 ✓；但「7 快照最坏 rel_L2 仍很高」已不是当前最前沿证据，任务书据此下的结论**低于仓库现有实测**。

### C12 §6.1/§6.3 强基线与指标 —— 多数不存在（新增）

- **原文**：§6.1「强制基线：nearest-neighbor/persistence；分层线性插值；PCHIP；RBF；Gaussian Process；XGBoost/CatBoost；小型 MLP；标准 Bayesian optimization；与 PeakGuard 使用相同回归器但不带拒答的模型」；§6.3 设计层「Hypervolume；Pareto regret；达到指定 Hypervolume 所需的仿真次数」。
- **证据**：全仓 `src/`+`scripts/`+`tests/` 的 `.py` 检索：**`hypervolume`/`qEHVI`/`EHVI`/`pareto_regret`/`bayesopt`/`skopt`/`botorch` 全部 0 命中**（仅命中 `bo_` 子串，来自 `both_` 等）；**无 GP / RBF 拟合 / XGBoost / CatBoost**；MLP 只在 `src/memsharness/ml/surrogate.py`（sklearn `MLPRegressor` 集成，服务的是**旧的 93 维响应级代理**，不是 8 通道一阶峰代理）。**已有**：persistence 基线（`lift_vs_persistence`、`beats_persistence`）与 PCHIP（生产结构本身）。
- **判定**：**新增（非冲突），但需新依赖**。AGENTS.md §3 实测网络受限：「官方 `files.pythonhosted.org` 读超时；`pypi.tuna.tsinghua.edu.cn` 可用但索引页偶发截断；**`mirrors.aliyun.com` 会截断大 wheel**」⇒ 安装 GP/XGBoost/CatBoost 是**有风险的额外前置**，任务书未提。

### C13 §5.1 分类概率校准与分类指标 —— 完全不存在（新增）

- **原文**：§5.1「未校准概率；Platt scaling；isotonic calibration；temperature scaling」＋「macro-F1；valid 类召回率；…Brier score；ECE；混淆矩阵」；§8.2「状态模型报告混淆矩阵、FAR、FRR、Brier/ECE」。
- **证据**：全仓 `.py` 检索 `Platt|isotonic|temperature_scaling` = **0**；`confusion_matrix|macro.?F1|f1_score|brier|ECE|false_accept|FAR|FRR` = **0**。
- **判定**：**新增**。但注意**前提不成立**：仓库当前**没有状态分类器**（只有参数域判定 `check_domain()` 与频谱状态**列**），所以要跑 §5.1 必须先**先建分类器**（= C1 的状态名问题）——任务书把这件事当成「对状态分类器至少比较」的增量，实际是**从零开始**。

### C14 §5.3 软拒答 —— 新增，且属改判定语义

- **原文**：§5.3 软拒答「`P(valid_closed)` 低于校准阈值；预测区间相对宽度超过阈值；Deep Ensemble/多模型分歧超过阈值；到最近训练样本的标准化距离过大；位于训练数据低密度区；多通道预测违反物理一致性…」「阈值必须在 calibration 集上冻结，并输出 accuracy–coverage–false-accept 曲线」。
- **证据**：当前拒答只有**硬**的两类：`check_domain()` 四条（x 域 / N1 整数≥1 / N2∈[5,9] / `N1<N2`）＋ 预测可得性（层内 x 越界、N2 外推 >1 步、缺同 x 标定值）；`_classify_refusal()` 只是**把拒答原因归类**（其 docstring 明写「**只归类，不改变拒答本身**」）。**无** P(valid) / 多模型分歧 / 马氏距离门槛。距离类分数在旧响应级模块有（`ml/surrogate.py::ood_score` 马氏距离），但**不在 8 通道代理上**。
- **判定**：**新增（非重复）**，但**改动 `predict()` 的接受/拒答行为 = 改判定语义** ⇒ 红线 5，须人拍板；且「模型分歧」一类**依赖尚未拟合的 GP/XGB/MLP**（见 C12）。

### C15 §10 交付落点会制造第二套事实源

- **原文**：§10「建议新建版本化运行目录，例如 `work/runs/peakguard-v2-YYYYMMDD/`」＋ 24 件具名产物；「不覆盖既有冻结结果」。
- **证据**：同类产物**已分散在既有 run 目录**：标签表 `work/runs/first-peak-20260929/`（`multichannel_labels.csv` sha `d06edfe1…`）与 `work/runs/labels-dupkind-refined/20261008T215100/`（sha `21e807ee…`）；代理 `work/runs/multichannel-surrogate-20260929/`；切分 `work/runs/grouped-split-20261009/`；证据包 `work/runs/paper-evidence-20261009/`（§109.3 记录它**被就地重生成 3 次**、「非 append-only」）。
- **判定**：**「不覆盖」✓ 与 append-only/§95 O-A 一致；但「建议新建」= 第二/第三套事实源**。仓库刚因 E3 证据包「就地重生成」付出过代价（§105–§109 的 append-only 更正链 + R16 纪律），**再多一套平行表会让「哪个是权威」无法回答**。

### C16 §11 回报模板要求 `git commit` —— 本机不可执行

- **原文**：§11「## 2. 输入与版本 … `- git commit:`」。
- **证据**：本轮实测 `& git --version` **抛错（git 不可运行）**；仓库根虽有 `.git` 目录与 `memsharness-history.bundle`，但 PATH 上无 git 可执行文件（与工单给定前提「无 git」一致）。
- **判定**：**不可执行**（详见 §4-U1）。

### C17 §1.1/§1.2 物理模型与三个正式目标 —— 与仓库完全一致（无冲突）

- **原文**：§1.1「内电极：`-1 V`；外电极：`0 V`；有效差分驱动电压：`ΔV = 1 V`」「主设计变量…`x_scale`、`N1 = N_w_te1`、`N2 = N_w_te2`」「结构约束 `1 <= N1 < N2`」「7R 路线已经放弃」；§1.2「三个正式优化目标是…`abs_w_m`；…`bandwidth_Hz`；…`abs_p_per_V_Pa`」「`Q = f_peak / bandwidth`：门禁与报告量，不作为 Pareto 主目标」。
- **证据**：§70.1（−1/0/ΔV=1）、§72.2（「Q 作门槛、ζ 仅报告」「正式排名只用：绝对 −3 dB 带宽、振幅、单位电压灵敏度」）、`multichannel_surrogate.py` L28/L30（`FORMAL_OBJECTIVES`、`CONSTRAINT_ONLY`）；`check_domain()` L177（`round(n1) >= n2 ⇒ Refused`）。
- **判定**：**一致（无冲突）**。这是任务书中**唯一与仓库完全对得上的硬事实块**。

### C18 §1.3 峰的命名 —— 与仓库一致（无冲突）

- **原文**：§1.3「统一使用：『扫描窗口内首个可观测的内部局部峰』…不得仅凭频率最低就直接称为『物理一阶模态』」。
- **证据**：§72.1 第 ⑥ 条用户裁定原文：「**只发现高频局部峰时先称「首个可观测局部峰」，不得直接称「一阶模态」**——必须结合**位移场型**确认模态阶次」，并注明这是**结构性约束**（「SPL 曲线上的局部极大不足以判定模态阶次」）。
- **判定**：**一致（无冲突）**，且仓库口径比任务书更严（要求位移场型证据）。

---

## 4. 不可执行 / 不可验证的项（逐条）

| 编号 | 任务书原文 | 为何不可执行/不可验证 |
|---|---|---|
| **U1** | §11 回报模板「`- git commit:`」 | 本机 **git 不可运行**（实测 `& git --version` 抛错）。须改为「无版本库，用产物 sha256 代替」或由人决定是否初始化 git。 |
| **U2** | §8.3「多目标联合覆盖的算法和口径明确」 | 只说「明确」，**未给算法**（联合非一致性分数？Bonferroni 校正？），也**未给有限样本下的最小 n**；无法判定「明确」是否达成。 |
| **U3** | §5.3「阈值必须在 calibration 集上冻结」 | **未说 calibration 集从哪来、多大**。三批数据规模悬殊（A 223 / C 1782 / V2 250 行），按 §113 的整组切分是 1926 组；若把校准集独立切出，则主判定折会进一步变薄（§79.2 已实测主折覆盖率仅约 70%）。**谁切、切多少、能否与训练同批**均未定 ⇒ 不可验证。 |
| **U4** | §7.1「建议预算阶梯在资源评估后预注册，例如 `20/40/60` 次新增 COMSOL 调用」 | 「例如」＋「资源评估后」＝**没有判据、没有责任人、没有时点**。而本机资源是**硬约束且已实测**：单实例串行（AGENTS §4）、commit limit 37.1 GB、11 GB 级模型峰值提交 11.2 GB（AGENTS §3）。**须先由人指定预算与执行机**（本机 / `node01` / 集群）。 |
| **U5** | §7.3「PeakGuard 只有在至少一个核心设计指标上**稳定**优于普通代理/BO」 | 「稳定」**无判据**：几个种子？多大差值？是否要显著性检验？仓库现有纪律是先定判据再算（§113 的 `_verdict()` docstring「先定后算」）——任务书没有给出可落地的判定式。 |
| **U6** | §6.2「至少运行 5 个随机种子，报告均值、标准差和每个种子的原始结果」 | **未区分确定性模型**。persistence / 分层线性 / PCHIP **没有随机性**，照做会产生 5 份逐位相同的「种子结果」，其标准差恒为 0 —— 这是**伪随机重复**，不是稳健性证据。需先声明「哪些模型有随机性」。 |
| **U7** | §5.4 输出接口的 `data_manifest_sha256`、`provenance`、`state_probabilities` | **未给 schema、未给取值来源**。仓库已有 `schemas/*.schema.json`（15 个），但**没有本接口的 schema** ⇒ 新接口会绕过既有 schema 校验（`schemas/README.md` 与 `tests/` 的 schema 用例）。且 `state_probabilities` 依赖尚不存在的状态分类器（C13）。 |
| **U8** | §4.4 `test_cross_batch`：「相同参数坐标的重复性审计，**不计作泛化测试**」 | **与未决裁定相互牵制**：§113.2 的 **137 组**跨批标签冲突标【待裁定】；§113.6 第 4 条明写 `AC`/`UNION4` 池化「**与 §95.2 冲突** ⇒ 只作归因用途；**池化是否允许，须人拍板**」。任务书既要求它有该折，又没解决「冲突组算不算进分母」⇒ **判据缺失**。 |
| **U9** | §8.2「若不优于简单基线，明确记录失败」 | 「简单基线」**未点名**、**未给优于的判据**。仓库已有的判据是 `lift_vs_persistence` 的**符号** + §114 的**折依赖披露**（`N2ex5/6` 为正、`N2ex7/8` 为负 ⇒ 「不得据任一单折宣称翻身」）；任务书未引用，等于重开一套未定义判据。 |
| **U10** | §4.3「训练主模型时，**建议**只使用同一规范窗口或已由扩扫补全状态的样本」 | 「建议」出现在**数据分割的硬要求**段落里，与同段其他条目的强制语气不一致；而它决定的正是 §4.4 的全部集合构成 ⇒ **口径不可执行**（究竟强制还是建议？）。 |
| **U11** | §7.1「候选只有经 COMSOL **重新求解**后才能计入 Pareto 集」 | 未说**用哪个模型变体**。仓库实测存在**同源性未证**的模型分裂：§92.4/§97 记录 S3/S4 用的模型是 **currentdrive（Electrostatics + Circuit）**，与路线甲 x 族导出模型**不是同一变体**；§99 U1 进一步实测 `acpr.p_t` 与 `p` 逐位相等。**若不先钉死变体，「COMSOL 回算」不可复现。** |

---

## 5. 含糊需定义的名词（逐条）

| 编号 | 名词 | 含糊点 | 仓库现状 |
|---|---|---|---|
| **T1** | **PeakGuard / PeakGuard v2** | 是论文方法名？代码模块？运行目录名？**定义域与边界完全未给**；又称「模型」（§0「PeakGuard 模型」），与 §3 的「代理」、§5 的「分类器/回归器」混用。 | 代码 0 命中；只是论文方法名（见 §2） |
| **T2** | **「模型」**（全文最高频词，≥5 种含义） | §0「原型」=回归器；§2-M1「PCHIP 直接回归」=回归器；§3.2「状态模型」=分类器；§5「校准」=校准器；§1.5「7 快照**场级模型**」=POD-ROM；§7「普通**代理**/BO」=代理总体；§8.2「**状态模型**报告混淆矩阵」。**同一段内多义**。 | 仓库严格区分：`surrogate.py`（响应级 93 维）／`multichannel_surrogate.py`（8 通道标量）／`field_lookup.py`（场级查表，**不是模型**）／`ml/surrogate.py`（模型层管线） |
| **T3** | **「完善」的验收标准** | §0 只给 6 句动词目标（「正确区分…先判断…分别评估…输出…完成…用…证明」）；§8 四组门禁是**未量化的 checkbox**；**无通过线、无判定人**。 | 仓库有现成的可量化体系：`WORKING_PLAN §6.1.1`（S0–S5 带数值阈值）、§6.4（放行状态机）、预注册判定带（`PREREG §6`：in-layer 中位 ≤0.004 且 p90 ≤0.012 …）、`solver.py` 的 `THRESHOLDS` |
| **T4** | **`canonical_window_id` / `window_id`** | 「规范扫描窗口」**由谁定义、是哪一段**未给。 | 仓库**无此键**；只有 `freq_range_MHz` / `freq_grid_MHz` / `n_freq` / `batch` / `freq_range_v2_original` / `freq_range_source`。三套栅格并存（5–35 61 点 / 5–50 91 点 / 待产出的 5–50 648 组合） |
| **T5** | **八个新状态名**：`peak_observed_in_window`、`bandwidth_closed`（作状态）、`open_left`、`open_right`、`open_both/insufficient_grid`、`no_peak_in_window`、`peak_outside_window_confirmed`、`unknown_censored`、`no_resonance_physical` | 与仓库真实字段**无一对应**；且 `open_left` 从未独立计数。 | 真实列：`first_peak_found` / `peak_closed` / `bandwidth_closed` / `ranking_eligible` / `quarantined` / `peak_at_scan_endpoint` / `bw_upper_cutoff_at_endpoint` / `usable` / `extrapolated` / `method` |
| **T6** | **`cross_layer` vs `n2_extrap`** | 同物异名（见 C8）。 | `conformal` 的键 = `("in_layer","n2_extrap")` |
| **T7** | **「独立校准」**（§5 三处，含义不同） | §2-M4「独立**校准集**」=独立**数据**；§5.1「至少比较…」=独立**方法**；§5.2「等价的独立**校准协议**」=独立**流程**。 | 仓库：§7 已是**独立数据**（标尺折残差 / 对半切），且论文按 A5 明确**不得宣称严格 conformal guarantee** |
| **T8** | **「删失 / 截断」** | 任务书用 censored/truncated 笼统指两类；未区分**峰位删失**与**带宽截断**（二者的语义与后果不同：前者峰频只是**下界**，后者宽度**被高估、Q 被低估**）。 | §92.1 三条标志逐条带语义：「`peak_at_scan_endpoint`（右删失）、`bw_upper_cutoff_at_endpoint`（截断）、`freq_range`（**不得混算**）」；§115.4 另记 v2 的 SPL→带宽**桥接键歧义**致 `usable` 差 **3 格**且标 **【待裁定】** |
| **T9** | **「高保真复核 / COMSOL 回算」** | 新求解还是复用既有解？哪个模型变体？什么算「通过」？ | §112 已示范**零求解**补导出路线；§92.4/§97 记录变体分裂（currentdrive vs x 族导出模型）；§87.8 仍有「场级阈值适用对象」未确认 |
| **T10** | **「同一初始 DOE」** | 点数、采样法、随机种子**均未给**。 | `autonomous-optimization-loop` SKILL §2 建议 LHS **16–24 点**、§3 建议批 **20–24 点/轮**（前 2 轮逐轮批准） |

---

## 6. 优先级与依赖是否合理

**仓库当前真实阻塞链（逐条有据）**：

| 阻塞项 | 证据 | 任务书是否对得上 |
|---|---|---|
| **S3 守恒项 `failed`** | §92.4 / §112：唯一独立守恒项 **6.021e-2 > 0.005**、`S3_complete=false`；§117 记另一设计点 **0.1112**（未收敛、无误差界） | ❌ **完全未提** |
| **S0 缺闭式解（`inconclusive`）** | §92.4「S0 inconclusive — 需闭式解」；§88.5 状态机视图 `S0 inconclusive` | ❌ **完全未提** |
| **te2_9 导出待重跑** | §115「新导出产物**尚未落地**（`work\runs\te29-freq5-50-server-20261009\` 下无 `Table_9.txt`）… 一律标【待产物】」；§119「导出**从未失败，此刻仍在跑**（3 h 07 m）」；本轮实测 `work/runs/te29-freq5-50-server-20261009` 有 107 个文件但无 `Table_9.txt` | ⚠️ 只在 §9-P2 把 N2=9 泛化排到「主论文完成后再考虑」，**未把它当作当前阻塞** |
| **四项口径待裁定** | §111（S4 新旧阶梯两个 2%）、§112（S3 三项 `None`）、§113.2（跨批 137 组）、§115.4（v2 选带口径 ±3 格） | ❌ 未提；且 §4.3/§5.3 会在这些未决口径之上**再叠新判据** |
| **405 组不得展开** | §92.7 第 8 条 / §104 / §111 | ✅ 与 §9-P2「不扩大场级 POD」方向一致（但任务书没引用该约束） |
| **PMUT L1 = 0 条通过** | §78.3 / `WORKING_PLAN §7.1` | ❌ 未提（而 §8.2 要求「报告工程数值」的语境下这会绊住） |
| **`device_spec` 9 个 `pending_human`** | `WORKING_PLAN §7.1` | ❌ 未提 |

**判定：任务书的优先级与本仓库阻塞链不匹配。**

- 它的 **P0** 把「实现层级状态模型、实现 GP/XGB/MLP 基线、实现独立校准和统一拒答 API」列为**立即执行**，
  但仓库当前连 **S0/S3 的第一次状态跃迁都够不着**（§92.4：`solver_spec.json` 仍 `draft`，「**连第一次状态跃迁都还够不着**」）。
- 它的 **P0 第 2 条「修正低 x 峰位叙述」** —— 仓库**已做完**（§71.2 / §72.1 / paper v6 §6.1 已按实测改写，Stage-1 已执行：13/13 低频侧无局部极大、x=0.24 族 65 MHz 闭合峰）。
- 它把 **te2_9 排到 P2**，而仓库的 te2_9 重导**此刻仍在服务器上跑**（§119），是 N2=9 与 P4 器械的**当前**前置。
- 它把 **闭环 DSE 排到 P1（需新增 COMSOL）**，但**没有先解决**「本机单实例 + commit limit 37.1 GB」与「405 组不得展开」两个硬约束。

---

## 7. 若照它执行可能造成的风险

| 风险 | 具体机制 | 仓库已有前科（作为证据） |
|---|---|---|
| **(a) 改动已被 sha 锚点引用的产物** | §3.4/§5.2 改名 `n2_extrap`→`cross_layer`、§3.2 改状态列、§5.4 换 `predict()` 返回结构 ⇒ 必须改 `multichannel_model.json`（sha `0d872fb1…`）与 `multichannel_surrogate.py`（sha `7ec83d3d…`），**其哈希被 §109.9/§113.5/§114.4 逐条锚定**，且论文 v6 §6.4 引用了 `model_id = 74e5127f…`、`prereg_sha256 = e90c315f…` | §109.3：一次「校验」把 **31 件产物整个重写**（E3 系 + `MANIFEST.{json,md}`），并同时报告「逐位相同」 |
| **(b) 让已有守卫失效** | ① 若把标签逻辑重写进新目录，`guards_readonly.py` 的静态扫描只覆盖 `scripts\verify_*.py`（§116.3 实测「默认 `scripts\`，8 个 `verify_*.py`」）⇒ 新脚本会落在扫描面之外；② 若新表另起列名，`guards_denominator.py` 要求的 `denominator`/`flag_basis_count`/`n_nondecidable`（§116.4）无法从新明细复算；③ 若新增并行事实源，`guards_indexlock.py` 只管索引单写者，管不了**多份标签表谁是权威** | §116.3 已登记**两处遗留写入点未修**（`verify_s34_s4_interp.py:74`、`verify_te2_9_value_profile.py:169`）—— 守卫的覆盖面本就是有限的 |
| **(c) 制造新的「状态字段非测量」** | §4.1 的 `is_valid_solver`、`peak_state`、`bandwidth_state`、`window_id`、`is_isolated` **在现有数据里没有对应测量**；而 §3.2「行政状态由预处理硬门禁处理」的 `isolated` **在 `predict()` 上不生效**（C7）⇒ 会产出「字段存在、门不存在」的组合 | §103/§109 专为「把 \(I_{iso}\) 读作生效的门」做过措辞更正（paper v6 L183/L185）；§92.1 三条标志「**不得当正常值用**」 |
| **(d) 绕开 R16（校验者不得改写被校验对象）** | §10 要求「能由脚本从冻结输入重建」+ §11 要求回报哈希；若这些「重建/校验」脚本沿用旧的「先重跑生成、再比对」写法，就会重犯 R16 | §109.7 R16 原文：「**校验脚本默认必须只读**；任何**重生成**必须**显式开关**（如 `--regen`）、**默认关闭**；**开关打开时不得声称完成了一次校验**」；§109.5 记录了旧版 `verify_paper_evidence.py` 第 0 项就是「先覆盖现场、再比对」 |
| **(e) 未列但同等重要：新增依赖的安装风险** | §6.1 要求 RBF/GP/XGBoost/CatBoost/标准 BO；网络实测受限（AGENTS §3） | §116.5 事故来源①「SAC 拦 sklearn ⇒ 3 个文件无法收集」曾当**当前事实**上报、后不复现 ⇒ 环境事实必须带观测时间 |
| **(f) 未列但同等重要：把 `inconclusive` 写成通过** | §8 的 checkbox 若按「勾选即通过」执行，会把仓库现存的 `S0 inconclusive`、S5 冻结口径 `inconclusive`、S4 冻结三档 `inconclusive`、`check_batch_isolation` 的 `verdict=inconclusive` 一并标成通过 | R13/R15（`ai-solver-verification` §7/§10）；§116.4 分母纪律；`_level()` 的「`None` 一律不等于通过」 |

---

## 8. 【需用户拍板的问题清单】（按重要性排序）

> 每条：**问题一句话** ｜ **为什么必须你定** ｜ **选项与后果**。
> 判断依据：红线 5「人保留放行权」、§92.6「凡涉及判定的措辞一律保留『inconclusive ≠ 通过』『放行权在人』」、
> §109.2「修复属变更判定语义 ⇒ 只登记、不修代码」的先例。

### Q1（最高）「PeakGuard」到底是什么？—— 先定名与定界，再谈改什么

- **问题**：PeakGuard 是论文方法名（代码里 0 命中）？还是新建的代码模块？还是仅仅一个新运行目录名？
- **为什么必须你定**：现在代码里 **0 命中**，只有论文文本。若照 §10 新建 `work/runs/peakguard-v2-*/` 并实现 §3 的 B1/B2/B3，仓库会出现**第四套并行代理事实源**（现有：`surrogate.py` 响应级 93 维、`multichannel_surrogate.py` 8 通道、`field_lookup.py` 场级查表）。谁权威、旧的三套是否冻结，只能由你定。
- **选项与后果**：
  - **(A) PeakGuard = 现有多通道代理的论文用名**：代码不动、不新建目录，任务书的技术条目**映射到现有模块与 run 目录**。后果：改动最小、不动任何 sha 锚点；代价是 §10 的 24 件产物名无法逐字满足（须给映射表）。
  - **(B) 新建 `src/memsharness/peakguard.py` 作为 v2**：旧模块冻结只读。后果：双源并存，必须同时定「哪一套是权威」；`multichannel_model.json` 的引用（论文 v6 §6.4 的 `model_id`）需重锚。
  - **(C) 只新建交付目录、代码复用现有模块**：折中。后果：满足目录要求、无代码分叉；但 §3.2 的状态名与 §5.4 的接口仍需你确认是否改。
  - **(D) 全面重写**：后果：§113/§114/§116 的冻结哈希与五条守卫全部需要重锚；风险最高。

### Q2 N2 一步外推：默认禁止，还是保留并标记？

- **问题**：任务书 §2-M3 要求「**默认禁止外推**」；仓库预注册 §4.2 已把「1 步线性外推」写进冻结结构并已实测其 lift。采哪一个？
- **为什么必须你定**：这是**改判定语义 + 缩小已冻结能力域**，属红线 5。
- **选项与后果**：
  - **(A) 保留 1 步外推，但默认标记 `experimental` 并在报告里单列**（推荐）：改动最小、不动冻结结构；代价是任务书 M3 的字面要求未满足。
  - **(B) 照任务书默认禁止**：N2 外推一律拒答。后果：**作废** `multichannel_model.json`（sha `0d872fb1…`）与 `structure.n2_direction`；§113/§114 的 lift 表全部变成历史证据；论文 v6 §6.4 的覆盖率数字需重算。
  - **(C) 只在 `cross_layer` 模式允许并单独校准**：等价于给现有 `n2_extrap` 改名并加标注。后果：需改冻结键名（C8 风险 (a)）。
  - **(D) 维持现状、M3 不采纳**：后果：任务书该条被明确拒绝，须书面记录理由。

### Q3 标签表：新建 v2 规范表，还是在既有表上追加？

- **问题**：任务书 §4.1/§4.2 要求「从原始频谱重新生成一组合一行的规范标签表」并新增 20+ 字段；仓库已有 `multichannel_labels.csv`（2005×64）与 `labels_two_batch_dupkind_refined.csv`（2255×31，冻结 sha `21e807ee…`）。走哪条？
- **为什么必须你定**：O-A 裁定是「**不去重、一行不删**」（§95）；重建会产生**同名不同物的第三张表** —— 本仓库已因同类问题付出过代价（flag 口径 vs 可判定口径、batch 标签 vs 真实子批、三套隔离键）。
- **选项与后果**：
  - **(A) 只追加列、另存新版本、保留父版本哈希**（推荐，符合 append-only）：后果：新字段有父可回溯；但「一组合一行」不成立（2255 行 / 1926 组），须在文档里说清。
  - **(B) 全新重建规范表、旧表冻结不再消费**：后果：所有下游（代理、证据包、论文数字）需重指向；旧冻结哈希成为历史。
  - **(C) 不重建，只补 `window_id`/`peak_state`/`bandwidth_state` 三列**：后果：最小改动；但 §4.2 的「重新生成」字面未执行，且缺 `sample_id` 主键。
  - **(D) 维持现状、§4 不采纳**：后果：任务书 §4 整节被拒，须记录理由。

### Q4 三批数据能否池化 + 跨批 137 组标签冲突怎么处置？

- **问题**：§113.2 的 137 组跨批标签冲突标 **【待裁定】**；§113.6 明写 `AC`/`UNION4` 池化「**与 §95.2 冲突**」。任务书 §4.3 只说「不可直接混为同一监督目标」。定哪条？
- **为什么必须你定**：它**直接决定 §4.4 的 train/cal/test 构成与 §6 全部基线比较的分母**；且下游默认是 `keep-last`（沉默 last-write-wins），已被登记为缺陷（`fit_multichannel_surrogate.build()` 对同一 `(n2,n1,round(x,6))` 是赋值 ⇒ 后写覆盖先写 ⇒ 报告必须披露、**不得称为「两条都用了」**）。
- **选项与后果**：
  - **(A) 严格按批分列、绝不池化，跨批组只做一致性审计**（推荐，与既有裁定一致）：后果：分母按批分列，唯一能用的是单批内结论；`UNION4` 只作归因（§113.6 第 4 条已如此处理）。
  - **(B) 允许池化，但强制 `batch` 作分层项并单列每批结果**：后果：需新预注册；且要处理「同一组合两行谁进训练」。
  - **(C) 先择一（按栅格更细 / 按管线优先 / 取均值）再池化**：后果：属**新规则**，未经拍板不得默认启用（§113.2 原文）。
  - **(D) 维持【待裁定】不动**：后果：任务书 §4.4/§6 无法落地（判据缺失，见 U8）。

### Q5 是否批准需要新增 COMSOL 求解的 P1（固定预算闭环 DSE）？

- **问题**：任务书 P1 要「冻结独立测试组合 → 对最终测试组合运行 COMSOL → 执行固定预算闭环 DSE（例如 20/40/60 次调用）→ 复核 Pareto → Hypervolume」。批不批？
- **为什么必须你定**：本机是**单实例串行 + commit limit 37.1 GB**（AGENTS §3/§4，11 GB 级模型峰值提交 11.2 GB）；且 §92.7 第 8 条「**405 组仍不得展开**」、§115 te2_9 重导【待产物】、§119 显示服务器导出**此刻仍在跑**。求解窗口是稀缺资源。
- **选项与后果**：
  - **(A) 只做 P0 离线部分；P1 等 te2_9 落地 + 资源评估后另批**（推荐）：后果：§7.3「闭环增值」主张继续 **【待补】**（论文 v6 闭环表本来就是「待补」），但不动任何硬约束。
  - **(B) 批准一个小预算闭环（如 20 次调用）作方法学演示**：后果：占用本机求解窗口、新增 `work/runs/` 求解证据（可追溯）；须同时定「用哪个模型变体」（U11）与「预算一旦冻结不得改」（任务书 §7.1）。
  - **(C) 用服务器 `node01`**（§111/§112 已在用）**而非本机**：后果：需确认服务器侧 COMSOL/内存（**需人工核对**）；避开本机 commit 约束。
  - **(D) 借集群**：后果：需先抽象 `ExecutionBackend` 的 `remote`（AGENTS §7 已预留，P0–P2 只实现 `local`）。

### Q6 软拒答门禁是否上线？上哪几类、阈值取什么？

- **问题**：任务书 §5.3 要求五类软门禁（`P(valid_closed)` / 区间相对宽度 / 模型分歧 / 到最近训练样本距离 / 低密度），阈值冻结在 calibration 集。上线吗？
- **为什么必须你定**：**改 `predict()` 的接受/拒答行为 = 改判定语义**（红线 5）；且「模型分歧」依赖**尚未拟合**的 GP/XGB/MLP（C12）。本仓库刚为「看起来生效的门」做过两次措辞更正（C7）。
- **选项与后果**：
  - **(A) 只上「区间相对宽度 + 到最近训练样本的标准化距离」两类可立即实现的软门禁**（推荐）：后果：可在现有 `conformal` 半宽与训练 x 网格上立即落地，不依赖新依赖；其余三类等基线齐备。
  - **(B) 五类全上**：后果：需先拟合 RBF/GP/XGBoost/CatBoost/MLP（含依赖安装风险，AGENTS §3 网络受限）；工期与不确定性最大。
  - **(C) 暂不上软门禁，只如实报告硬拒答 + 分模式半宽**：后果：零判定语义改动；任务书 §5.3 未满足。
  - **(D) 只在报告侧给风险指标，不改 `predict()` 行为**：后果：论文可谈「风险暴露」，但「拒答率」作为一等结果的主张弱化（与论文 v6 §7.3 定位「可信筛选和风险暴露」其实一致）。

### Q7 验收判据与判定人是谁？

- **问题**：任务书 §8 四组门禁全是**未量化的 checkbox**；§11 第 6 项说「只列确实会改变研究目标或新增高成本计算的事项」由人裁决。通过线谁给、谁判定？
- **为什么必须你定**：没有量化线与判定人就无法判定「完成」；而仓库纪律要求 **`inconclusive` ≠ 通过**（R13/R15，§92.6/§116.2）且不得把负结果写成通过。
- **选项与后果**：
  - **(A) 采用仓库既有阈值体系并把任务书门禁映射过去**（推荐）：`WORKING_PLAN §6.1.1`（S0–S5 数值阈值）+ §6.4 状态机 + `PREREG §6` 判定带（in-layer：中位 ≤0.004、p90 ≤0.012、frac(err>0.03) ≤2%；n2_extrap：中位 ≤0.020、p90 ≤0.060、frac(err>0.10) ≤5%）+ `solver.py::THRESHOLDS`。后果：不新造并行阈值，可复用既有测试。
  - **(B) 由你逐组给定新数值通过线**：后果：需同时声明「与既有阈值冲突时以哪个为准」。
  - **(C) 门禁只作 checklist 报告、不作放行判据**：后果：与「放行权在人」一致；但「完成」不可判定。
  - **(D) 交外部（Codex）裁定阈值**：后果：与 §63「codex 裁定」先例一致（metric_protocol_v2）；但需你转交且周期更长。

### Q8 场级 POD 与 405 组：任务书口径是否被采纳？

- **问题**：任务书 §1.5 说「场级 POD 暂不作为主模型、不占主线资源」，§9-P2 把「全场 POD-ROM/神经算子」排到主论文之后。这与仓库现状（S1 路线甲 **passed**、场级对象已改**离散查表**、`S3 failed`、S4 双结论、**405 组冻结**）如何对齐？
- **为什么必须你定**：这是「研究目标」级取舍，且仓库 §78.4 记录用户曾明确指示「**我现在没有场级解，我们先不进行这个工作**」——任务书在未引用该指示的情况下再排一次期。
- **选项与后果**：
  - **(A) 确认「场级线挂起、不上主线」，只在论文作 limitation**（推荐，与既有用户指示一致）：后果：不动现有资源分配；P4.5 里程碑继续挂起。
  - **(B) 恢复场级线以争取 P4.5**：后果：需先解 S0（闭式解）与 S3 三项 `None`；且 405 组仍受冻结约束。
  - **(C) 只补 S0 闭式解 + S3 缺失三项（低成本，解锁状态机第一次跃迁）**：后果：这是**唯一能推动 `draft → physics_consistent` 的路径**（§92.4 原文「连第一次状态跃迁都还够不着」）；但需新求解或新导出（§112 已示范零求解可补两项）。
  - **(D) 只有在你给出新的场级数据时才重启**：后果：与「场级被数据阻塞」的现状一致。

---

## 9. 若照它执行，最小安全路径（一句话）

**只做「零求解、只读、只追加」的离线增量**——在既有 `multichannel_surrogate` + 标签表**之上**加一张「任务书状态名 ↔ 仓库真实字段」映射表与逐态计数、补 §5.3 里可立即实现的两类软门禁的**只读评估**、补 §6.1 里不依赖新依赖的 persistence/PCHIP 对照，全部落到**新 run 目录且不覆盖任何冻结哈希**，并把「改判定语义（Q2/Q6）、新建并行事实源（Q1/Q3）、新增 COMSOL 预算（Q5）、新阈值体系（Q7）、场级取舍（Q8）」五类事项**挂起等你拍板**。

---

## 10. 本轮未做（如实）

1. **未改**任务书一个字节；未改任何代码、产物、论文、`WORKING_PLAN.md`、技能。
2. **未跑** pytest、未跑 COMSOL、未启动 mphserver、未联网。
3. **未提升**任何状态：`solver_spec.json` 仍 `state=draft`（sha `21315173fd2732c7384c4a3d437bb7f7c297d5c3047b5ff01094ca3553b6bd3f`）、
   `multichannel_model.json` 仍 `status=draft`（sha `0d872fb14bb9093a1a486327e3e24298af81290e58756ed9a70b8b2b3ef444b1`）—— 均为本轮实测复核值。
4. **需人工核对**（本轮只读未穷尽，不下结论）：
   - 任务书 §4.1 的 `is_valid_solver` 对应的仓库列 —— **未找到明确对应**；
   - 各原始导出目录的 `run_id` 是否已在 `run` 表登记（§4.1 要求逐样本 `run_id`）—— **未核**；
   - 服务器 `node01` 侧的 COMSOL/内存能力（Q5 选项 C 的前提）—— **未核**；
   - `data_versions/` 与 `VERSION_V2_v20261008T143151.json` 的现行清单是否覆盖 A 批与 C 批（本轮只核到 V2 冻结副本）—— **未穷尽**。
5. **索引登记**：本节分析按 `max+1` 追加为 **§121**（追加前实测 `## <n>.` 最大节号 = **120**），
   写入器为 `scripts\append_record_locked.py`（`guards_indexlock.py` 的独占锁包装，§116.6）。
