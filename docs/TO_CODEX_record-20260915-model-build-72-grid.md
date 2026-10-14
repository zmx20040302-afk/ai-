# 记录：按用户参数网格做**模型构建**（72 组合）+ 选择集复核 + 与用户数据对账

- 对应任务单：`docs\TASK-20260915-model-build-72-grid.md`（下达 2026-09-15 12:50）
- 执行日期：2026-09-15 12:41–13:1x（本机时区 +08:00）
- 运行目录（run_id）：`work\runs\model-build-72-20260915\`
- COMSOL 6.4.0.293 / MPh 1.4.0；Python `work\.venv\Scripts\python.exe`（3.12.14）
- 证据等级说明：本报告所有数值均可回溯到本 run 目录或既有只读输入的文件 + sha256；**未跑**的部分单独标注。

---

## 0. 一句话结论

**是**——按用户参数网格重建出的模型，在**模型身份**（同一 `.mph` 哈希）、**选择集与控制面**（72/72 组逐位一致）、**数值**（`x_scale=0.4` 端点 7/7 频点与用户表一致到 1e-12 量级）三条独立证据上均与用户扫描所用模型一致；
**但** `x_scale=0.8` 端点的数值只一致到 **0.06%–1.38%**（在预先写定的接受带 2% 内、未达严格阈值 0.1%），
**该偏差的成因本轮未查实**，故**不得**声称"全网格数值逐位复现"。

---

## 1. 本轮范围与硬约束遵守

| 约束 | 遵守情况（实测） |
|---|---|
| 只写 `work\runs\model-build-72-20260915\` 与 `docs\` | 遵守。全部写入落点见 §8；含 `MEMS_WORK_ROOT` 重定向到本 run 目录后的 run/device 暂存、日志、产物 |
| 不覆盖既有 run | 遵守。本 run 目录为新建；未写过 `work\runs\precheck-*` 等既有目录 |
| 不改 `work\tools` / `src\memsharness` / `work\ai-solver` / `work\models` / 用户目录 / 库 | 遵守。基座与既有脚本均以**复制副本**使用（副本哈希见 §8）；未写 `work\store`（平台库）——本应写库的 run 记录被改写为本 run 目录的 `run_record_attempt.jsonl` |
| 不用 `lt2_production.py` | 遵守（仅作容差口径的**只读**参考，未执行；其 `AREA_REL_TOL/BBOX_REL_TOL/TOLERANCE_SCOPE` 定义被照抄进预先声明的阈值文件） |
| 不跑 pytest | 遵守 |
| COMSOL 一次一个实例、串行 | 遵守。两个阶段各起 **1** 个 `comsolmphserver`，无并行 |
| 用户 GUI 不碰 | 遵守。全程未对 `C:\Users\zmx\Desktop\*` 做任何读写；`ComsolUI` pid 31012 仅在进程清单里**登记**，未终止 |
| 不在别人交付目录里跑脚本 | 遵守。既有脚本先复制到本 run 的 `tools\` 再执行（副本与原文件哈希相同，见 §8） |

---

## 2. 输入与数据 of record

| 用途 | 路径 | sha256 |
|---|---|---|
| 基座模型（legacy 单电极驱动，**只读**） | `work\models\b_GE_task3_2new_legacy_1ohm_drive_v1.mph`（103,681,444 B） | `0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d` |
| 用户扫描表（数据 of record，平台入库副本） | `work\reports\analysis_decision\newrange005\raw_source_table.csv`（208,503 B） | `777d0306c569a874086d231130cfdf75808d3fe87cda3f7bfc0dffc4fbe3210a` |
| 用户扫描表冻结副本（xlsx） | `work\ai-solver\inputs\扫描阵列Xrange(0.4,0.05,0.8).xlsx`（141,355 B） | `33ed711c8d53bf02f69686e8e1c62815587919588d73293a5ce899c903951403` |
| 参数网格权威表 | `work\runs\user-param-grid-20260915\parameter_grid.csv` | `e6217c8c3ed3f9a39f50732d5186a6edabba0a4d14bf74486622115f10ad61e5` |
| 冻结控制面签名（既有证据，只读抽取） | `work\runs\precheck-b2-phase2-v5-aggregate\geometry_selection_precheck.json` | `b26193fea3f56a6ebab6c36456f23a7dd37d58c757fd3ce80ef3edf6f03c6b4a` |
| 冻结签名的源运行台账 | `work\runs\precheck-b2-phase2-v5-aggregate\source_runs.json` | `e3f2d257c37d8a22ef41b7be57c73cdb5fb4de51141f55101b5d6298b0095e8b` |

**关键事实（实测，非推断）**：冻结证据 `source_runs.json` 记载其源模型为
`C:\Users\zmx\Desktop\b_GE_task3_2new.mph`，sha256 = `0f75ca1df9262f27…`，
与上表基座模型的实测 sha256 **相同**；`work\models\model_build_manifest.json`（`dfd7183ab79ff10d…`）与
`work\models\drive_change_manifest.json`（`450a8825d6eb7181…`）同样记载：该基座是**未被改动过的母版**
（驱动改动只施加在**另一个**工作副本 `b_GE_task3_2new_reverse_voltage_drive_v1.mph` = `cbe9ccc1…` 上）。
⇒ 本轮用的基座 = 用户扫描所依据的那个文件的**逐字节同源副本**。

**一处必须登记的哈希不一致**：`AGENTS.md` §3 记桌面 `b_GE_task3_2new.mph` 为 `3efa34cc…`（2026-09-11 实测），
而 2026-09-13 的三份既有证据一致记为 `0f75ca1d…`。二者不符说明该桌面文件在 09-11 与 09-13 之间被重存过。
**本轮按指令未读取/未哈希桌面现场文件**，故无法给出该文件当前哈希，也无法判断 09-11 的 `3efa34cc…` 与
本轮主题是否同一版本。这是本报告的一处**外部不确定度**（不是本轮结果的不确定度）。

参数运行态事实（来源 `work\models\effective_parameter_ledger.csv` = `e7611cb37714d6af…`，取"最后一次赋值"口径）：
`x_scale` 末次赋值 L176 = 0.600000（几何引用 L234）；`N_w_te1` L147 = 4（L219）；`N_w_te2` L2389 = 9（L222）；
`W_min` L139 = 4.200000[um]；`N_mem` L142 = 10；`fmax` L990 = 35[MHz]（另有 `f_max` = 40[MHz] 为 `unverified_or_inactive`，本轮未动）。
两个待变参数均为**几何类**，故按技能 `model-io` 全部重做选择集核对（§3）。

---

## 3. §2.1 选择集复核：72 组全部通过，**0 异常**

### 3.1 方法与复用（不重写既有逻辑）

- 复用既有脚本 `scripts\geometry_selection_precheck.py`（sha256 `dded1fe6f6d013e6…`，与产出冻结聚合证据的脚本**同一哈希**）
  → 复制到本 run 的 `tools\geometry_selection_precheck_v3_reused.py`（副本 sha256 相同，逐字节一致）后执行。
- 对其施加的**最小环境改动**（全部记录在 `tools\run_recheck_72.py`，`6dda646f29b27607…`）：
  1. `MEMS_WORK_ROOT` 指向本 run 目录 ⇒ run 产物、暂存副本全部落在本 run 目录内；
  2. `insert_run` 替换为本 run 目录的 JSONL 记录器、`connect` 替换为空上下文 ⇒ **不触碰平台库**。
- 组合：`x_scale ∈ {0.4,0.45,…,0.8}` × `N_w_te1 ∈ {1,…,8}` = **72**，`--phase 1`（**只重建几何测选择集与面积，不建网格、不求解**）。
- 判据与容差取自**事先写定**的 `thresholds_declared_before_run.json`（`f5205ebec4ea6861…`，落盘时间 12:43:38，早于任何 COMSOL 步骤）：
  `AREA_REL_TOL = BBOX_REL_TOL = 1e-6`，沿用 `lt2_production.TOLERANCE_SCOPE` 口径（**仅**限"冻结控制面重建一致性"，不得用于声称与解析几何一致）。
  fail-closed：任一项取不到证据（null）即判异常。
- 参照值：`frozen_reference_72.csv`（`313ca8e6719dd2c7…`），从既有冻结证据的 `phase2_rows` **只读抽取**——该 key 恰好就是这 72 组，未自行构造参照值。

### 3.2 结果

| 项 | 实测 |
|---|---|
| 组合数 | **72**（逐组合机读行：`runs\selection-recheck-72\checkpoint.jsonl`，72 行） |
| **通过** | **72** |
| **异常** | **0**（异常清单为空） |
| 每组合通过的判据数 | 15/15（72 组全部 15/15） |
| 与冻结参照匹配的行数 | 72/72 |
| `area_ptot` 与冻结值的最大相对差 | **0.0** |
| 6 维包围盒最大分量相对差 | **0.0** |
| 交付表 | `selection_recheck.csv`（`bb710116fc73c59a…`），汇总 `selection_recheck_summary.json`（`48a952fbaa2207de…`） |

逐条判据（每组都判，全部为 True）：`geometry_ok`、`no_combo_error`、`outer_bc_nonempty`、`inner_bc_nonempty`、
`bc_disjoint`（两电极实体交集 = 0）、`named_eq_bc_outer`、`named_eq_bc_inner`、`intop5_eq_swr1`、`intop5_eq_efc1`、
`entity_sets_equal_frozen`、`area_ptot_close`、`area_outer_close`、`area_inner_close`、`bbox_close`、`geometry_area_call_ok`。

72 组内**取值恒定**（`derived_evidence.json`，`f456a8bfaaf82843…`）：

| 选择集 | 实体集合（72 组全同） |
|---|---|
| 外电极 `es.term1` / 命名集 `cyl8` / `intop4` | `[14, 15, 76, 132]` |
| 内电极 `es.pot2` / 命名集 `cyl9` / `intop3` | `[58, 59, 98, 110]` |
| Ptot 积分面 `intop5` = `acpr.swr1` = `acpr.efc1` | `[1, 3, 70, 104]` |
| Ptot 控制面面积 | `6.266153558917681e-08`（与冻结值逐位相同） |
| Ptot 控制面包围盒 | `[-1e-4, 1e-4, -1e-4, 1e-4, -1e-4, 0.0]`（6 分量，72 组全同） |

⇒ 72 组中，内外电极与积分面**始终指向同一批实体、同一物理面**，控制面面积/包围盒**跨 `x_scale` 与 `N_w_te1` 完全不变**
（与既有裁决 `ptot_control_surface_status = stable_fixed_hemisphere`、`ptot_cross_x_comparable = True` 一致）。

### 3.3 附带的几何自洽性实测（同一批几何测量的派生量）

- 外电极面积**只随 `x_scale` 变、与 `N_w_te1` 无关**（每档 `x_scale` 单值），`A_outer / x_scale` 在 9 档间的相对散布 **0.42%**。
- 内电极面积满足 `A_inner / (N_w_te1² · x_scale)` 在 9 档 `x_scale` 间相对散布 **0.13%**；
  且 `A_inner(N1) / A_inner(N1=1)` 与 `N1²` 的最大相对偏离 **0.26%**（72 组内）。
- `A_inner` 的 `+0.1%…+0.26%` 偏离随 `N1`、`x_scale` 单调增大，量级与几何测量对曲面边界离散的量级相当；
  该偏离**未被**判为异常（它不触发任何一条判据），仅作为观察记录，不用于任何结论。

### 3.4 两条必须写明的口径注意

1. 既有预检的 `physical_extent_suspect` 判据用 `N1·W_min > N_mem·W_min`（即与**未缩放**的 `R_mem` 比较），
   本轮 72 组实测**全部为 False**。该判据**不覆盖**"内电极半径 vs 椭圆膜短半轴（`R_mem·x_scale`）"这个几何问题，
   所以它取 False **不等于**"该几何问题已被排除"。
2. 另一份**先验**几何预判（`work\tools\precheck_new_grid_geometry.py` 的产物
   `work\reports\modelio\new-grid-geometry-precheck.json`，`cc73bba6be82a1dd…`）假设内电极半径
   `= N_w_te1·W_min + 1um` 且**不随 `x_scale` 缩放**；本轮 72 组的实测面积显示**内外电极都随 `x_scale` 缩放**
   （`A_outer ∝ x_scale`，`A_inner ∝ N1²·x_scale`），与该先验假设不符。
   ⇒ 该先验预判的"重叠/超膜"判据**不适用于**本批几何；本轮一律以**实测几何测量**为准（本节与 §3.2）。

---

## 4. §2.2 数值对账：2 组合 × 7 频点

### 4.1 组合选择理由（先定后跑）

选 `(x_scale, N_w_te1) = (0.4, 4)` 与 `(0.8, 4)`：
- `N_w_te1 = 4` 是基座台账末次赋值（L147=4），也是既有独立 run `work\runs\xscale-0607-3f` 用过的值，便于横向比较；
- `0.4` 与 `0.8` 是 admissible 区间的两端，几何形变最大、对网格口径最敏感，判别力最强（与任务单建议一致）。

### 4.2 阈值（**先写明**，`thresholds_declared_before_run.json` = `f5205ebec4ea6861…`，12:43:38 落盘）

- 严格阈值 `rtol_target = 1e-3`（任务单举例口径，"逐位复现"判定）；
- 接受带 `rtol_accept = 2e-2`（"同一模型/同一物理设置"判定）。声明理由：平台自身网格收敛硬门槛是相邻加密 <1%；
  用户当时所用网格/求解器口径**无证据可复原**（xlsx/CSV 均不含网格信息）；`Ptot` 在 20–25 MHz 附近接近反共振，对微小网格差异高度敏感；
  既有独立 run 在同模型同参数下已实测到 1.564e-02 的上界（`xscale-0607-3f`）。
- 停表规则：任一点 `> 2e-2` 即如实报出并停止结论，**不得**改模型/改口径/放宽容差。**本轮未触及停表规则**。

### 4.3 逐点相对误差与判定

相对差口径 `|a−b| / max(|a|,|b|)`（沿用 `lt2_production._rel_diff`）。`a` = 本轮本机自算，`b` = 用户表（数据 of record）。

**`Ptot (W)`**

| x_scale | f (MHz) | 本机自算 | 用户表 | 相对差 | 判定 |
|---:|---:|---|---|---:|---|
| 0.4 | 5 | 2.191492379707e-09 | 2.191492379721e-09 | 6.109e-12 | pass_target |
| 0.4 | 10 | 4.805231554535e-08 | 4.805231554562e-08 | 5.614e-12 | pass_target |
| 0.4 | 15 | 4.212652401886e-07 | 4.212652401911e-07 | 6.023e-12 | pass_target |
| 0.4 | 20 | 3.094450477429e-06 | 3.094450477449e-06 | 6.578e-12 | pass_target |
| 0.4 | 25 | 1.470319718404e-05 | 1.470319718413e-05 | 5.770e-12 | pass_target |
| 0.4 | 30 | 1.150347918507e-05 | 1.150347918508e-05 | 4.604e-13 | pass_target |
| 0.4 | 35 | 7.021467707402e-06 | 7.021467707407e-06 | 7.615e-13 | pass_target |
| 0.8 | 5 | 4.647063397934e-07 | 4.712086522206e-07 | **1.380e-02** | pass_accept |
| 0.8 | 10 | 4.632228421490e-06 | 4.694639979730e-06 | **1.329e-02** | pass_accept |
| 0.8 | 15 | 2.735378932297e-06 | 2.766196998031e-06 | **1.114e-02** | pass_accept |
| 0.8 | 20 | 3.327413227090e-06 | 3.354024606211e-06 | 7.934e-03 | pass_accept |
| 0.8 | 25 | 9.401630585740e-06 | 9.391072587567e-06 | 1.123e-03 | pass_accept |
| 0.8 | 30 | 9.914719555388e-06 | 9.875731682248e-06 | 3.932e-03 | pass_accept |
| 0.8 | 35 | 2.622597329262e-05 | 2.611700591175e-05 | 4.155e-03 | pass_accept |

**`Vave (m/s)`**

| x_scale | f (MHz) | 本机自算 | 用户表 | 相对差 | 判定 |
|---:|---:|---|---|---:|---|
| 0.4 | 5 | 2.941684072514e-03 | 2.941684072523e-03 | 3.055e-12 | pass_target |
| 0.4 | 10 | 7.162209984507e-03 | 7.162209984527e-03 | 2.780e-12 | pass_target |
| 0.4 | 15 | 1.508362610439e-02 | 1.508362610443e-02 | 2.986e-12 | pass_target |
| 0.4 | 20 | 3.344084161543e-02 | 3.344084161554e-02 | 3.305e-12 | pass_target |
| 0.4 | 25 | 6.494803026311e-02 | 6.494803026330e-02 | 2.904e-12 | pass_target |
| 0.4 | 30 | 5.467919385041e-02 | 5.467919385047e-02 | 1.146e-12 | pass_target |
| 0.4 | 35 | 4.244859102398e-02 | 4.244859102402e-02 | 8.499e-13 | pass_target |
| 0.8 | 5 | 2.166706391324e-02 | 2.181813941675e-02 | **6.924e-03** | pass_accept |
| 0.8 | 10 | 3.741299888197e-02 | 3.766199775284e-02 | **6.611e-03** | pass_accept |
| 0.8 | 15 | 2.291726230336e-02 | 2.303693799716e-02 | 5.195e-03 | pass_accept |
| 0.8 | 20 | 2.504508259476e-02 | 2.512258910357e-02 | 3.085e-03 | pass_accept |
| 0.8 | 25 | 2.646989445068e-02 | 2.653317851655e-02 | 2.385e-03 | pass_accept |
| 0.8 | 30 | 2.986213433612e-02 | 2.986029169510e-02 | 6.171e-05 | pass_target |
| 0.8 | 35 | 3.363418699497e-02 | 3.355744030753e-02 | 2.282e-03 | pass_accept |

**附带量（同一批求解额外回读，非任务单要求，仅作加强证据）**：`Zin1_R` 最大相对差 **1.413e-02**（(0.8,10)），
`Zin1_X` 最大 **5.935e-03**；(0.4,4) 上 `Zin1_R/X` 的相对差为 9.7e-15 … 1.6e-13。

**判定汇总（56 条 = 14 行 × 4 个量）**：`pass_target 29` / `pass_accept 27` / **`fail_accept 0`**。
其中任务单要求的两个量（`Ptot`、`Vave`，28 条）= `pass_target 15` / `pass_accept 13` / **fail 0**；
`(0.4,4)` 的 28 条**全部** `pass_target`（≤1e-3，实测 ≤6.9e-12），`(0.8,4)` 的 28 条中 1 条 `pass_target`、27 条 `pass_accept`。

### 4.4 网格口径（必须声明的限制）

- 本轮**重建几何 + 重建网格**后求解：`geom.run()` → `mesh.run()` → `std1.run()`，求解配方逐字沿用既有脚本
  `work\tools\compute_xscale_table.py`（`ad61e2557358fe61…`）；关闭了模型自带的扫描特征 `std1.param/param2`
  （`active(False)` 两个都成功），并把 `std1.freq.plist` 显式设为 `5 10 15 20 25 30 35 MHz`。
- **网格重建是可复现的**：本轮实测网格单元数 `(0.4,4) = 111754`、`(0.8,4) = 156578`，
  与冻结证据（**用户文件**在同一脚本下重建的结果）**逐一相同**。
- **但用户当时实际使用的网格口径无法从数据 of record 复原**（xlsx/CSV 里没有网格信息），
  且本轮**未做**三组网格收敛检查（技能 `comsol-modeling-sop` §5 的 <1% 硬门槛）。
  ⇒ 因此"`x_scale=0.8` 端 0.06%–1.38% 的偏差"**不能**归因于某一方，也**不能**据此宣称任何一方更准；
  严格意义上的"逐位复现"只在 `x_scale=0.4` 端成立（1e-12 量级）。
- 数据 of record 元信息（`raw_source_table.csv` 前 4 行）：`Model = b_GE_task3_2new.mph`、`Version = COMSOL 6.4.0.293`、
  `Date = Sep 13 2026, 14:25`、`Table = 表格 8 - 全局计算 9`；覆盖 162 组合 × 7 频点 = 1134 行，本轮用到的两个组合 7 频点**全部存在**。

### 4.5 资源门禁与实跑实测（含一次外部内存告警）

预先写定的门禁：`available_physical ≥ 14000 MB` **且** `commit_available ≥ 16000 MB`，间隔 5 s 连测两次；不达标即停。

| 阶段 | 第一次实测 | 第二次实测 | 判定 |
|---|---|---|---|
| 求解 `x=0.4` 前（12:45:45 / 12:45:50） | 16258.2 / 19297.8 MB | 16183.0 / 18409.5 MB | **pass** |
| 求解 `x=0.8` 前（12:53:45 / 12:53:50） | 14840.7 / 16586.5 MB | 14854.0 / 16576.2 MB | **pass** |

（数值为 `available_physical_mb / commit_available_mb`，口径与 `lt2_production.sysmem` 相同，取自 `GlobalMemoryStatusEx`。）

**求解中实测（贴地，非门禁判定依据）**：`x=0.4` 求解中 server `WorkingSet` 峰值约 7.9 GB、系统 `commit_free` 一度降至 ~4.5 GB；
`x=0.8` 求解中 `commit_free` 最低约 4518 MB。父代理于 12:47 独立实测到 `avail 12543.3 MB / commit 4282.7 MB`（求解中峰值），
并据此下达"让在跑的自然跑完、跑完立即关掉自己的 server、之后不得再启动新求解"的指令 —— 本轮**照此执行**，见 §7。

**收尾实测**（`reconciliation_manifest.json` = `f58b5adbe4c390b4…`，`cleanup` 字段）：
`clear=True`、`disconnect=True`、`port_still_open_after_disconnect=False`、`comsolmphserver_after_disconnect=[]`、
`terminate_own_server=[]`（无需强杀）、`port_open_after_terminate=False`、`comsol_procs_final=[]`。

**求解配置留痕**：`std1` 的 `param`/`param2` 扫描特征 `active(False)` 均成功；`freq.plist` = `5[MHz] 10[MHz] 15[MHz] 20[MHz] 25[MHz] 30[MHz] 35[MHz]`；
`N_w_te1=4`、`x_scale` 逐档 `param.set`；耗时 `(0.4,4)` 几何 0.6 s / 网格 1.1 s / 求解 451.5 s，`(0.8,4)` 几何 0.4 s / 网格 1.3 s / 求解 1365.9 s；三处 `geometry_error/mesh_error/solve_error` 均为 `None`。

---

## 5. 结论：**建出来的模型是否等于用户扫描时那个模型？**

用两条独立证据回答，**不靠"看起来一样"**：

### 证据 A —— 模型身份与选择集（选择集路径）

1. 基座 `b_GE_task3_2new_legacy_1ohm_drive_v1.mph` 的实测 sha256 = `0f75ca1d…`，与冻结预检证据所记载的**源文件**
   `C:\Users\zmx\Desktop\b_GE_task3_2new.mph` 的 sha256 **相同**；且既有台账明确该文件是**未改动的母版**（驱动改动在另一副本上）。
2. 本轮的 72 组在**同一驱动、同一几何序列**下，复现冻结证据的 `intop5/swr1/efc1`、内外电极实体集合、三处面积与 6 维包围盒，
   **面积与包围盒的最大相对差为 0.0（逐位相同）**，实体集合 72 组恒定；且网格单元数在重建路径上与冻结值逐一相同
   （111754 / 156578）。
⇒ **选择集与几何重建路径一致**：建立的模型在"几何 → 选择集 → 控制面"层面与用户扫描所用模型**一致**。

### 证据 B —— 数值（求解路径）

- `(0.4, 4)`：`Ptot` 与 `Vave` 各 7 个频点，相对差 **4.6e-13 … 6.9e-12**（约 11–12 位有效数字一致）；
  `Zin1_R/Zin1_X` 同量级（≤1.6e-13）。这是"同一离散化 + 同一求解路径"的量级（不同网格会带来 ~1e-3 级差异，此处相差约 10 个数量级）。
- `(0.8, 4)`：`Ptot` 相对差 1.12e-03 … **1.380e-02**，`Vave` 6.17e-05 … 6.924e-03。
  **全部在预先写定的接受带 2% 内，未触及停表规则**；但 27/28 条未达严格阈值 1e-3。

### 结论（分级）

| 命题 | 结论 | 证据 |
|---|---|---|
| 本轮基座 = 用户扫描所依据的文件 | **成立**（逐字节同源，sha256 相同） | §2、§5 证据 A-1 |
| 几何/选择集/控制面 = 用户当时模型 | **成立**（72/72 组逐位一致，面积与包围盒相对差 0.0） | §3.2、§5 证据 A-2 |
| 数值 = 用户当时模型（`x_scale=0.4` 端） | **成立到逐位量级**（≤6.9e-12） | §4.3、§5 证据 B |
| 数值 = 用户当时模型（`x_scale=0.8` 端） | **仅在 0.06%–1.38% 内一致，非逐位** | §4.3 |
| 全网格 72 组数值逐位复现 | **未验证**（只对账了 2 组；且其中 1 组非逐位） | §4.3 |

**成因未查实（明确列为未完成，不猜测）**：`x_scale=0.8` 端 0.06%–1.38% 偏差的来源，本轮**没有**给出结论。
本轮已排除与未排除的事实边界是：
- 已排除：驱动拓扑不同（实测 `Zin1 ≡ Zin2`：用户表 1134/1134 行成立、本轮自算 14/14 行成立）、几何/选择集不同（§3）、网格重建不可复现（网格单元数与冻结值相同）。
- 未排除、且**尚无证据**：用户扫描时该扫描点的网格/几何实际状态（数据 of record 不含网格信息）；
  以及扫描流程本身是否对所有参数点都做了完整重建——此项**需要用户侧的扫描设置证据或一次受控复算**才能判定，
  本轮不具备该条件（且 COMSOL 步骤已按内存告警暂停）。

---

## 6. 其余 90 组"为什么不建"（如实登记）

来源：`parameter_grid.csv` 的 `admissible_for_model_build` = False 共 **90** 组（= 162 − 72），逐组原因：

| `N_w_te1` | 组数 | `design_status` | `selection_status` | 不建的理由 |
|---|---:|---|---|---|
| 9 | 9 | `design_boundary_coincident` | `verified` | 内外电极设计边界**重合**（`N_w_te1 == N_w_te2 == 9`），不是"内电极在指定实体内侧"的预期设计 |
| 10 … 18 | 81（每档 9 组） | `design_region_reversed` | `selection_mismatch` | 设计域反转：选择集与预期区域不符（`selection_mismatch`），按 `model-onboarding` 第 4 步须**作废、不得入库/不得用于建模** |

⇒ 本轮**只**建了 `N_w_te1 ∈ {1..8} × x_scale ∈ {0.4..0.8}` 的 72 组；
上述 90 组**未建网格、未求解**，也未在本轮报告中给出任何数值。它们的既有预检证据保留在
`work\runs\precheck-batch2-phase1-v5\geometry_selection_precheck.csv`（`a8d77f0a5439fad7…`）与冻结聚合证据中，本轮未改动。

---

## 7. 暂停点与未完成事项（外部条件，非本轮失败）

- **暂停原因**：2026-09-15 12:47 父代理实测到求解中的内存峰值（`avail 12543.3 MB / commit 4282.7 MB`），
  判断我方 `comsolmphserver`（pid 16720）与用户 GUI `ComsolUI`（pid 31012，用户明确表示"要使用旧参数进行求解"）**抢占内存**，
  下令：让在跑的自然跑完 → 立即关闭自己的 server → 之后**不得再启动任何新求解**。
- **暂停点**：`§2.2` 第 2 个组合的求解**已自然完成**（12:53:50 起跑，求解 1365.9 s，结果文件落盘 13:17:07），
  随后收尾已关闭 server 并确认端口 2036 释放；**此后未再启动任何 COMSOL 会话**。
- **因该指令而未做的一项（原计划做的只读探查）**：`tools\inspect_study.py`（`b4464a1031d23dd5…`，**已写好但未执行**）
  原用于只读回读基座模型**自身**的研究特征（`std1` 的原始 `freq.plist`、`param/param2` 的扫描参数、各物理场特征 active 状态）。
  本轮因此**没有**"模型自带频点列表 = 7 频点"的直接证据；§4.4 中"按模型原有的 7 个频点"只能记为
  **口径假设**（任务单 §2.2 的陈述 + 我显式设定 plist 为同样 7 点），**不是**本轮实测所得。
- 停止时刻实测：`port 2036 = false`、`comsol* 进程列表为空`（用户 GUI 此时也已自行关闭）、
  `available_physical = 19289.3 MB`、`commit_available = 22590.8 MB`（memory load 40%）。
- 若需继续：唯一未做的 COMSOL 动作就是上面那项只读探查；其余工作（报告、清点、哈希）均不占用 COMSOL。

---

## 8. 产物清单（路径 + 字节 + sha256）

全部位于 `work\runs\model-build-72-20260915\`；完整清单见 `manifest.json`（20,662 B，**`a32f23091cd45dd9a7961266668758cbf576dc4344a77db77ecc2c47fa6e374e`**，含 34 个产物）。
本报告不在该清单内（清单生成于本报告之前）；本报告自身的 sha256 记录在 `report_pointer.json`。

| 角色 | 相对路径 | 字节 | sha256 |
|---|---|---:|---|
| 阈值声明（COMSOL 前落盘） | `thresholds_declared_before_run.json` | 5,700 | `f5205ebec4ea68612eccb334cbf123bca1182573b38a923ca67bc7fbd5baf10a` |
| **§2.1 交付表（72 行）** | `selection_recheck.csv` | 61,532 | `bb710116fc73c59a80e956017011729385ea6a734099a80450f7d19c190a95cb` |
| §2.1 汇总（通过/异常计数） | `selection_recheck_summary.json` | 1,568 | `48a952fbaa2207de…` |
| §2.1 逐组合机读 checkpoint（72 行） | `runs\selection-recheck-72\checkpoint.jsonl` | 139,730 | `9529c8fd2977b491…` |
| §2.1 复用脚本原始产出 | `runs\selection-recheck-72\geometry_selection_precheck.json` | 233,988 | `088818962411a19c…` |
| §2.1 复用脚本原始产出 CSV | `runs\selection-recheck-72\geometry_selection_precheck.csv` | 43,191 | `58047cad1bdb346f…` |
| §2.1 哨兵报告 | `runs\selection-recheck-72\sentinel_report.json` | 10,821 | `5d7e6a3be90e8ee6…` |
| 冻结参照表（72 组） | `frozen_reference_72.csv` | 39,195 | `313ca8e6719dd2c7…` |
| §2.2 自算（2×7 频点 + 附加量） | `reconciliation\reconciliation_selfcomputed.csv` | 6,157 | `42c6a513c8c98b30…` |
| **§2.2 对账表（逐点相对差与判定）** | `reconciliation\reconciliation_vs_user.csv` | 6,379 | `e1d97093f0f6a24a45bd8710ec70d4047ec4ea702640a1ac74f659ed8cd0c0ff` |
| §2.2 网格单元数 vs 冻结值 | `reconciliation\reconciliation_mesh_vs_frozen.csv` | 914 | `fa60effe38f6262a…` |
| §2.2 溯源（研究设置/资源门禁/cleanup） | `reconciliation\reconciliation_manifest.json` | 6,239 | `f58b5adbe4c390b4…` |
| 派生量（报告全部派生数字） | `derived_evidence.json` | 24,247 | `f456a8bfaaf82843…` |
| 输入源勘察 | `source_recon.json` | 7,634 | `3f9b31d210d59c2c…` |
| 冻结证据勘察 | `frozen_signature_recon.json` | 6,203 | `dead11e309053df6…` |
| §2.1 原始日志 | `logs\recheck72_stdout.log` | 11,891 | `c2a3b38cbd97eb37…` |
| §2.2 原始日志 | `logs\recon_stdout.log` | 3,443 | `f40afa5ec95421fa…` |
| 本 run 内暂存副本（= 基座，逐字节相同） | `devices\model-build-72-local\b_GE_task3_2new_legacy_1ohm_drive_v1.mph` | 103,681,444 | `0f75ca1df9262f27…` |
| 复用副本（= 既有选择集预检脚本，逐字节相同） | `tools\geometry_selection_precheck_v3_reused.py` | 46,889 | `dded1fe6f6d013e6…` |
| 复用副本（= 既有对账脚本，逐字节相同） | `tools\compute_xscale_table_reused.py` | 10,574 | `ad61e2557358fe61…` |
| §2.1 驱动 | `tools\run_recheck_72.py` | 2,963 | `6dda646f29b27607…` |
| §2.1 冻结比对 | `tools\compare_frozen_72.py` | 10,020 | `998cb3d29a6556d7…` |
| §2.2 对账脚本（改编） | `tools\run_recon_two.py` | 17,311 | `d4bb2fcded984d04…` |
| 资源/进程取证 | `tools\proc_util.py` | 5,006 | `07278dd69e186721…` |
| 只读探查脚本（**写好未执行**） | `tools\inspect_study.py` | 7,135 | `b4464a1031d23dd5…` |

只读输入（不在本 run 目录，仅引用）：`raw_source_table.csv` `777d0306…`、冻结 xlsx 副本 `33ed711c…`、
`parameter_grid.csv` `e6217c8c…`、冻结聚合证据 `b26193fe…`、基座 `0f75ca1d…`、
`model_build_manifest.json` `dfd7183a…`、`drive_change_manifest.json` `450a8825…`、
`effective_parameter_ledger.csv` `e7611cb3…`、既有预检 CSV `a8d77f0a…`、先验几何预判 `cc73bba6…`。

---

## 9. 证据等级、不确定度与未做到的地方

**证据等级**
- 模型身份（同一文件/哈希）：**强**（sha256 + 既有台账 + 冻结证据三处互证）。
- 选择集/控制面一致性：**强**（72/72 组、面积与包围盒相对差 0.0，且与冻结值逐位相同）。
- 数值一致性：**中**——`(0.4,4)` 为强（≤6.9e-12）；`(0.8,4)` 为"在接受带内但不严格"（≤1.38e-02），成因未查实。
- 网格收敛性：**未做**（无三组网格，未过 <1% 硬门槛）；因此本轮数值**不作为** L1 级验证证据，仅作模型一致性对账。

**不确定度 / 未做到**
1. §7 所述因内存告警暂停，**未执行**基座模型研究特征的只读探查 ⇒ "模型自带 7 频点"是口径假设而非实测。
2. `x_scale=0.8` 端 0.06%–1.38% 偏差**成因未查实**，未做受控复算（需新的 COMSOL 会话，已暂停）。
3. 未做网格收敛检查，故无法给出任何数值的离散误差界。
4. §2 登记的桌面文件哈希不一致（`3efa34cc…` vs `0f75ca1d…`）未解决——按指令未读取桌面现场文件。
5. §3.4 两条口径注意：既有 `physical_extent_suspect` 判据不覆盖椭圆短半轴问题；先验几何预判的电极半径不缩放假设与本批实测不符。
6. 本轮只对账 **2/72** 组数值，其余 70 组**只有选择集证据、无求解证据**。
7. 用户扫描的实际扫描设置（尤其是否对每个参数点都完整重建几何/网格）**无证据**，本轮不能判定。
