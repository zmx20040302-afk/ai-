# 任务单：按用户参数网格做**模型构建**（72 组合）+ 选择集复核 + 用用户数据对账

- 下达时间：2026-09-15 12:50
- 下达人：用户（原话「现在先按照我计算得到的参数进行模型构建」；并就两个选项确认为：
  **只用有效的 72 组**、**要含选择集复核 + 用用户自己的数据对账**）
- 执行者：实现者子代理
- 与其它线的关系：**独立于 LT2 生产线**（不用 `lt2_production.py`、不参与 504 点冻结批次）；
  也不得触碰 AI 求解器第 4/5 步产物（`work\ai-solver\`）

---

## 0. 参数网格的权威定义（已由父代理落表，直接用，不要重新解析）

`work\runs\user-param-grid-20260915\parameter_grid.csv`（sha256 `e6217c8c3ed3f9a3…`）
与 `parameter_grid.json`（sha256 `68b63aafbe385ca7…`）：

- 用户扫描表 = `C:\Users\zmx\Desktop\换能器\扫描阵列Xrange(0.4,0.05,0.8).xlsx`（现场 sha256 `4874b50d…`；
  **冻结副本** `33ed711c…` 在 `work\ai-solver\inputs\` —— 对账时以冻结副本 + 平台入库副本
  `work\reports\analysis_decision\newrange005\raw_source_table.csv`（`777d0306…`）为**数据 of record**）
- 网格 = x_scale 9 档（0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8）× N_w_te1 1..18 = 162 组
- **本轮只用 `admissible_for_model_build == True` 的 72 组**（即 N1 1..8 × 9 档 x_scale）。
  其余 90 组（N1=9 boundary_coincident；N1 10..18 design_region_reversed + **selection_mismatch**）
  **本轮不建**，但要在报告里如实登记"为什么不建"。

## 1. 基座模型与参数事实（已实测，引用即可）

| 项 | 值 |
|---|---|
| 基座（legacy 单电极驱动） | `work\models\b_GE_task3_2new_legacy_1ohm_drive_v1.mph`，sha256 `0f75ca1df9262f27…`，103,681,444 B |
| 该副本与桌面原件 | **逐字节相同**（同一 sha256）⇒ 可作只读基座，**不必**去动用户桌面文件 |
| 反相模型（本任务**不用**） | `b_GE_task3_2new_reverse_voltage_drive_v1.mph`，`cbe9ccc18e51005f…` |
| `x_scale` | 台账末次赋值 L176 = 0.600000；**downstream_geometry_references = L234** |
| `N_w_te1` | 台账末次赋值 L147 = 4；geometry refs L219 |
| 派生关系 | `W_min = 4.2[um]`、`N_mem = 10`、`R_mem = N_mem*W_min = 42[um]`、`w_te1 = N_w_te1*W_min`、`w_te2 = N_w_te2*W_min` |
| `N_w_te2` | 末次赋值 **L2389 = 9**（文件末尾覆盖；AGENTS §4 明文要求"取最后一次 param.set"） |
| `fmax` | 35[MHz]（**本轮不改频段**，用户已明确不做 45 MHz） |

⇒ 两个待变参数**都属几何类**，按技能 `model-io` 的 SOP：**几何类变更后必须重做选择集核对**，
不能只改参数就求解。

⚠️ 用户此刻可能正开着 COMSOL GUI（`b_GE_task3_2new.mph` 有 `.lock`）。
**绝对不要**写用户的桌面文件、不要删/动那个 `.lock`、不要对用户打开的模型做任何写操作。
本任务一律在 `work\` 下的**副本**上做。

## 2. 要交付的三件事

### 2.1 选择集复核（全部 72 组，**不建网格、不求解**）

对 72 组逐一：在副本上设 `x_scale` 与 `N_w_te1` → `geom.run('fin')` → 用平台既有能力
（参考 `src\memsharness\onboard.py` 的 `measure` / `EVAL` 路径与 `work\tools` 里既有的选择集预检脚本，
**不要重写**已有逻辑）核对：

- 电极/接地/积分面等**关键选择集的实体集合**是否仍指向**预期区域**（与基准 `N_w_te1=4, x_scale=0.6` 的
  选择集语义一致：内电极 = 指定实体内侧、外电极 = 外侧、积分面 = `intop5` 的 `[1 3 70 104]` 一族）；
- `Ptot` 积分面**面积与包围盒**是否与冻结控制面一致（平台已有 `ptot_surface_area_unchanged` /
  `ptot_surface_bbox_unchanged` 这类判据，可复用其口径与容差 `AREA_REL_TOL = 1e-6` / `BBOX_REL_TOL = 1e-6`）；
- **每个组合都要落一行机读结果**（x_scale, N_w_te1, 实体集合、面积、bbox、判定、失败原因）。

要求：72/72 都有结论，**不允许**"跑通了就跳过没记"；任一组合选择集异常必须**如实报为异常**，
不得靠放宽容差让它变成通过。

### 2.2 数值对账（**2 个组合 × 7 个频点全对**）

选两个组合做完整对账，建议 `(0.4, 4)` 与 `(0.8, 4)`（x 两端），或你有更好理由的组合，但必须说明理由：

- 在每个副本上设参数 → 重建几何与网格 → 按模型原有的 7 个频点（5/10/15/20/25/30/35 MHz）求解；
- 与用户在 xlsx 里**已经测过的** `Ptot (W)` 与 `Vave (m/s)` 逐点比对（数据 of record 见 §0）；
- 报**每个频点的相对误差**并给出**判定阈值**（自定，但要先写明，例如 `rtol 1e-3`；若超出，如实报并**停**，
  不要为了对上而改模型或改口径）；
- 说明网格口径是否与用户当时一致；若不一致（例如网格设置被改过），**必须写明**这会让对账失去严格意义。

### 2.3 结论与可复现性

- 报告必须能回答：**"按用户参数网格建出来的模型，是否等于用户扫描时用的那个模型？"**
  —— 用 2.1（选择集）与 2.2（数值），而不是靠"看起来一样"。
- 每行数字可回溯到产物文件 + sha256；不跑 COMSOL 的部分与跑 COMSOL 的部分要分清。

## 3. 硬约束

1. 只写 `work\runs\model-build-72-20260915\`（新建；内含每组合的子目录或一份汇总表 + 原始日志）
   与 `docs\`（新增报告）。**不覆盖**任何既有 run 目录。
2. 不改 `work\tools\`、`src\memsharness\`、`work\ai-solver\`、`work\models\`（只读引用基座）、用户目录、库。
3. **不要**用 `lt2_production.py`；不要参与/影响 LT2 冻结批次。
4. COMSOL 一律：一次一个实例、串行、不得并行扇出；启 server 前先探端口 2036；用完关掉自己的 server。
5. **资源**：跑任何求解前先实测并按**显式写明的 ad-hoc 阈值**判断（建议
   `available_physical ≥ 14000 MB` 且 `commit_available ≥ 16000 MB`，连续两次间隔 5 s）；不达标就**停**并报告，
   **不要**放宽阈值硬跑。记录每次求解前的实测值。**用户 GUI 若开着属于允许但必须记录**（不要碰它）。
6. 进程存活判定用 `GetExitCodeProcess == 259`（**不要**用 `OpenProcess` 能否成功）；
   终止后带超时轮询并留痕（见 `AGENTS.md` §3）。
7. Python 一律 `-B` + `PYTHONDONTWRITEBYTECODE=1` + `PYTHONPYCACHEPREFIX`；不得留 `__pycache__`；
   `import mph` 只在真正需要求解的进程内。
8. 不跑 pytest；COMSOL 步骤必须在当前（放宽的）文件策略下执行。
9. **报告里不许出现"看起来一致""应该相同"**——只写实测与判定。

## 4. 交付

- 报告：`docs\TO_CODEX_record-20260915-model-build-72-grid.md`（新增）
- 产物：`work\runs\model-build-72-20260915\`（含 `selection_recheck.csv`、每组合日志、对账表、
  `manifest.json` 带路径+字节+sha256）
- 最终回复我时用中文、简明给出：72 组选择集复核的**通过/异常计数与异常清单**；
  2 个组合 × 7 频的对账**逐点相对误差**与判定；**"是否等于用户当时的模型"的结论**；
  产物路径 + sha256；以及你**没做到/不确定**的地方。
