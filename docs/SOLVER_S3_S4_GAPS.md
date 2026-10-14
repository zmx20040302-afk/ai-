# S3 / S4 的 COMSOL 侧缺口清单（可执行）

> 用途：路线甲（x 单参数族 POD 场求解器）能清 **S1/S2/S5**（场数据已具备），
> 但 **S3 物理一致性**与 **S4 离散无关性**是硬门禁，**无法从现有 `.mat` 快照算出**——
> 已实测：快照变量只有 `x_m/y_m/z_m`、`p_total_Pa`、`p_finite_mask`、参数与来源元数据，
> **没有单元、没有边界、没有域标记**（`grep elem/mesh/tri/tet/bnd/boundary/region/domain` 全为空）。
> 本清单把这两级需要的东西列成**可执行项**：做什么、怎么验、验收判据、接到哪里。

## 0 结论先行

| 级别 | 现状 | 缺口在哪 |
|---|---|---|
| S1 场级精度 | ✅ 可做 | 导出方已切 `x_holdout_role`（每层 5/81）与 `n_holdout_role`；用 POD + 留出即可 |
| S2 工程量精度 | ✅ 可做 | 首峰标签表已有（f_peak/SPL/带宽/Q） |
| S5 误差界校准 | ✅ 可做 | 快照数足够做保形校准（90% 界 ≥9 个校准点） |
| **S3 物理一致性** | ❌ **缺 COMSOL 侧接口** | 守恒/边界/对称需要**域、边界标记、单元连通与面积/体积**；快照里没有 |
| **S4 离散无关性** | ❌ **缺网格扫描** | 需要**同一设计 2–3 套网格**的场；现在每设计只有 1 套 |

## 1 S3：需要从 COMSOL 导出什么（三选一，按代价从低到高）

**S3-a 复用平台既有检查器（最省）**
`src/memsharness/consistency.py` 已有 `conservation_residual` / `boundary_condition_residual` /
`mirror_symmetry_residual` / `limit_consistency`，以及 `evaluate_s3(checks)`
（任一 False ⇒ 不通过；任一 None ⇒ **inconclusive，不算通过**）。
要跑它们，需要**在 COMSOL 侧**取到：
* 域的**面积/体积**与积分算子（用于守恒残差）；
* 边界上的法向通量/固定约束（用于 BC 残差）；
* 结构的镜像对称面（PMUT 为回转体 ⇒ 可用关于 y=0 平面的对称性）。

**S3-b 从快照本身能做的部分（现在就能做，不需新仿真）**
* **镜像对称**：快照带 `x_m/y_m/z_m` ⇒ 可检查 `|p(x,y,z)| ≈ |p(x,−y,z)|`（下半球域内配对点）。
  这是**唯一**能纯靠 `.mat` 做的 S3 子项；其余子项**如实标 None**（⇒ S3 整体 inconclusive ⇒ 不放行）。

**S3-c 最稳（推荐给"要放行"的目标）**
在 COMSOL 侧写一个**一次性导出**：对某个固定设计导出
`{域标记, 边界标记, 单元连通, 每单元面积/体积, 边界法向}`（小体量，几 MB），
之后 S3 全部子项都能在本地算，**不必每次开 COMSOL**。

**验收判据**（§6.1.1 原文）：守恒残差 **< 0.5%**、BC 残差 **< 1%**（对称性按离散残余给量级即可）。
参考量级（`scripts/check_s3.py` 在真实解上实测）：守恒残差 5.6e-12、边界残差 5.7e-15、镜像对称 7.6e-3。

## 2 S4：需要跑网格扫描（2–3 套网格，同一设计）

* **做什么**：固定一个设计（建议取 `x_scale=1.00, N1=4, N2=8, f=20 MHz`），
  用 2–3 个网格尺寸（例如 `hmax = 3e-6 / 1e-6 / 2e-6`——`.m` 里就有这三档的痕迹）各解一次，
  导出**同一个公共点集上**的场（用现有导出器即可），比较场级相对 L2。
* **验收判据**：三套网格两两场级差异 **< 2%**（§6.1.1 的 S4）。
* **产物**：每套网格一个 `.mat`（同一命名规则），并在清单里标明 `mesh_level`。
* **注意**：这与"训练数据"无关，是**网格收敛证据**；不要混进 POD 训练集。

## 3 接入点（这两级齐了之后，代码里怎么用）

* `schemas/solver_spec.schema.json` 的 `thresholds` 已含 `S3_conservation_residual_max`（0.005）、
  `S3_bc_residual_max`（0.01）、`S4_mesh_diff_max`（0.02）——**不需要改 schema**；
* 评估入口：`src/memsharness/solver.py::evaluate_levels(spec, evidence)`，其中
  `evidence["s3"]` 传 `consistency.evaluate_s3(...)` 的结果，`evidence["s4"]` 传
  `{"mesh_diff_max": …, "n_meshes": …}`；
* 状态机：S3 未过 ⇒ 不许进入 `physics_consistent`；S4 属于 `solver_certified` 之前必须过的证据之一
  （口径见 `docs/SOLVER_CONFIG.md`）；`approved_solver` **只能人工签字**。

## 4 现在的坦率结论

**在 S3/S4 补齐前，路线甲最多做到 `physics_consistent` 之前一步都过不去**
（因为 S3 的多数子项会是 `None` ⇒ inconclusive ⇒ 不放行）。
所以可交付的东西只有两种口径，**必须二选一并写进模型卡**：

* **口径一（推荐）**：先把 POD 场求解器在 **S1/S2/S5** 上做到过阈，状态停在 `draft`，
  模型卡写明"**S3/S4 未做 ⇒ 不构成放行**"；同时按 §1/§2 去补 COMSOL 侧证据；
* **口径二**：只声称"S1 达标"的**离线复算**（在已知留出集上重算），**不叫求解器部署**。

**禁止**：在 S3 未过的情况下使用 `solver_certified` / `approved_solver` 字样，或对外声称"免 COMSOL 出解已放行"。
