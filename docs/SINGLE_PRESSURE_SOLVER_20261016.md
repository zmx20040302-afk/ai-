# 单一复声压场求解器：实测结论与 v1 边界（2026-10-16）

## 结论

当前场管线确实只处理复声压 `p_total_Pa`，不是声学—固体/压电—静电—电路的联合场 ROM。
本次先把可成立的单一方向封装为可加载求解器：固定离散结构和频率，在同一分支内只沿
`x_scale` 做幅值/形状分离的 POD-PCHIP；未命中分支或证据范围时拒答并生成 5 个串行
COMSOL 补点（3 train + 2 holdout），不再沿 N1 或频率无界插值。

## 原始证据（运行区只读）

- PMUT 模型 probe `work/models/bGEtask2-20260911T064304Z/probe_mph.json` 显示四类物理接口：
  `acpr`（PressureAcoustics）、`solid`（含 `pzm1`）、`es`、`cir`；还包含
  `AcousticStructureBoundary` 与 `PiezoelectricEffect` 多物理耦合。
- 实测 MAT 的变量清单只有坐标、`p_total_Pa`、有限掩膜、参数与来源元数据；
  `scripts/pipeline_pod_fields.py` 和 `scripts/fetch_and_align_x_family.py` 都只读取
  `p_total_Pa`。因此“模型有四类物理接口”不等于“现有 POD 联合了四个场”。
- `pod_pipeline_x020_v2/shape_diag/shape_diag_x020.json`：N1=2→3 的单位范数场相关性
  `0.2070107382`；N1=3→4 的场范数比 `4.285660955`。这支持把 N1 当离散分支、禁止跨层插值。
- `eda64-20261010/n4_multifreq/N4_CORRECTED_CELLS.json` 的未见几何/未见频率交叉测试，
  关键区最大相对 L2 为 N1=4 `0.2775751`、N1=7 `0.3218850`（27.76% / 32.19%），
  均远高于关键区域 2% 门槛。
- `eda64-20261010/n5_stage3/REPR2_RESULT.json` 与
  `docs/TRACK_CHOICE_ASSESSMENT_20261013.md` 记录：线性、三次插值、vector fitting、
  相位显式和 operator MLP 均未通过预注册交叉门禁。增加网络规模不是当前主矛盾。

## v1 可用分支与误差声明

数据均来自 `te2_8_pod_fields_20261005/x_family`，每个分支 81 个快照，固定 N2=8、20 MHz；
冻结切分为 76 train + 5 holdout。声明范围只取留出点覆盖的 `x_scale∈[0.33,0.93]`。

| 分支 | 全域 max 相对 L2 | 关键区 max 相对 L2 | S2 max\|p\| 相对误差 | 90% 目标相对 L2 带 | 冻结门禁 |
|---|---:|---:|---:|---:|---|
| N1=4 | 1.091% | 0.700% | 0.739% | 1.516% | S1/S2 passed；S5 inconclusive |
| N1=7 | 1.133% | 0.957% | 1.268% | 1.969% | S1/S2 passed；S5 inconclusive |

数字来自各分支 `route_a_gate_n1_4.json` / `route_a_gate_n1_7.json`。S5 的 90% 目标带在
5 个留出点上覆盖率为 100%，但 5 点的覆盖率分辨率只有 20%，不能落入 85–95% 判定窗，
因此保持 `inconclusive`，不得写成“已全面认证”。模型状态保持 `draft`，未获人工放行。

## 运行契约

- 输入：`x_scale, N_w_te1, N_w_te2, freq_Hz`。
- 命中：只对 N1=4 或 7、N2=8、20 MHz、`x_scale∈[0.33,0.93]` 返回复场；输出明确标记
  `source_type=ai_solver`、模型状态、S 级与场级相对 L2 误差带。
- 未命中：`refused=true`，不含预测场；给出新分支的五点串行 COMSOL 计划。
- 小数 N1：直接拒绝自动补点，因为它不是已定义的离散电极结构。
- 五点计划只是最小 pilot；若重新评估未通过，不得注册该分支。S5 样本仍不足时继续保持
  `inconclusive`，不能用训练拟合误差代替独立证据。

代码入口：`src/memsharness/single_pressure_solver.py`；构建入口：
`scripts/build_single_pressure_solver.py`；发布产物：`work/dist/single-pressure-solver-v1/`。
