# 致 DeepSeek Harness：LT0–LT3 反相驱动粗扫执行工单

> 日期：2026-09-13  
> 授权范围：仅执行 LT0、LT1、LT2、LT3  
> 预计连续墙钟时间：理想约 12–16 小时；保守约 18–25 小时  
> 强制停止点：LT3 排名与候选建议生成后停止，禁止自动进入 45 MHz 网格或精扫

## 0. 当前模型与物理口径

本轮使用反相恒压模型：

```text
model = work/models/b_GE_task3_2new_reverse_voltage_drive_v1.mph
model_sha256 = cbe9ccc18e51005f6aa147e8d7fdd5df62266c5f9117d9829888336f326582d9
drive_mode = dual_electrode_antiphase_voltage_drive
vamp = 1[V]
V_outer = +vamp
V_inner = -vamp
V_reference = 0[V]
Vdiff = 2*vamp
```

旧的 1 Ω 电路驱动数据只作为 legacy 对照，不得混入本轮排名：

```text
legacy_drive_mode = inner_fixed_minus_v0_outer_circuit_terminal_1ohm_to_reference
```

本轮不使用旧 `Zin1/Zin2` 进行排名或工程判断。

## 1. 总执行顺序

```text
LT0 工具与审计修复
  → LT0 验收
  → LT1 五组合×三频点小样
  → LT1 验收
  → LT2 72组合×7频点正式粗扫
  → LT2 聚合验收
  → LT3 质检、Pareto、候选重选
  → STOP，提交总报告
```

LT0、LT1完全通过后可自动进入下一阶段。任何 STOP 条件触发时立即停止并保存现场。

## 2. LT0：工具与审计修复

### LT0-A：确认 Circuit 已停用

现有脚本执行了：

```python
comp.physics("cir").active(False)
```

但旧 manifest 中 `cir_active=null`，原因是读取方法不正确。必须补充独立证据：

1. 保存后重新加载反相模型；
2. 使用 physics-level API 检查 `cir`；
3. 检查反相 Study 中 `cir` 是否参与；
4. 检查求解器变量中是否仍有 `cir.*` 自由度；
5. 必要时导出 `.m` 静态文本作为旁证。

最终写入：

```text
cir_inactive_verified = true
cir_inactive_evidence = api_readback | static_export_and_solver_signature
term1_active = false
```

若无法证明 Circuit 停用，停止，不执行 LT1。

### LT0-B：修正 Ground 记录

`gnd1` 是 Ground 特征，0 V 是其固有物理定义，不应设置不存在的 `V0` 参数。

要求：

- 删除 `gnd1.set("V0",...)`；
- 保持 `gnd1.active(true)`；
- 创建 `ave_ref` 或等价边界探针；
- 验证 5/20/35 MHz 的参考电极复电位均约为 0 V；
- change log 写为 `gnd1 active; zero potential inherent to Ground feature`；
- 不再把 `gnd1 FAILED` 作为最终状态。

### LT0-C：修正端口电流与 KCL

旧算法仅积分 `es.JZ`，不能用于多方向边界的严格 KCL。优先使用 COMSOL Terminal/Ground 自带总电流变量；若不可用，积分完整法向电流密度，并明确边界侧别：

```text
Jnormal = es.JX*nx + es.JY*ny + es.JZ*nz
```

内部边界必须确认使用 `up()` 还是 `down()`。保存三个端口原始复电流及每个电流的正方向。

定义：

```text
kcl_relative = abs(I_outer + I_inner + I_ref) /
               (abs(I_outer) + abs(I_inner) + abs(I_ref))
```

暂定工程门槛：

```text
kcl_relative <= 1%
```

若仍不通过，不得靠任意翻转符号凑零。可将状态固定为：

```text
electrical_current_metrics_excluded = true
```

并继续机械/声学粗扫，但禁止输出阻抗、电流效率和电功率结论。

### LT0-D：修正脚本健壮性

- 修复 `None` 打印导致的非零退出；
- 修复 docstring 转义告警；
- 所有 server 清理逻辑放入 `try/finally`；
- `disconnect()` 后每秒检查一次端口，最多等待30秒；
- 30秒仍开放时，只处理本 run 明确拥有的 PID；
- 记录 PID、启动/退出时间、峰值工作集和最终端口状态；
- 补频率唯一性、manifest字段、线性比值、重复/缺失键测试；
- 完整运行 `pytest -q`，不得低于当前 `240 passed / 4 skipped` 基线。

### LT0-E：参数生效性补测

| 参数 | 测试 | 必须得到的证据 |
|---|---|---|
| `x_scale` | 基准上下各一个合法小步 | 几何尺寸、面积或包围盒发生预期变化，网格统计同步变化 |
| `N_w_te1` | 4→5 | 内电极几何/选择签名改变，无空选择、重叠或反转 |
| `vamp` | 0.5→1 V | 电极电位和 `Vave` 约2倍，`Ptot` 约4倍 |
| `fmax` | 35→45 MHz，仅作表达式预判 | `L_min`/网格尺寸求值发生变化；此阶段不保存为生产网格模型 |

其余13个 `unverified_or_inactive` 参数继续冻结。

### LT0 验收门槛

```text
reverse_drive_voltage_gate = pass
ground_voltage_verified = true
cir_inactive_verified = true
term1_active = false
electrical_bc_conflict = false
script_exit_code = 0
port_2036_closed_within_30s = true
parameter_signature_x_scale = pass
parameter_signature_N_w_te1 = pass
linearity_check = pass
pytest_regression = false
```

LT0失败时停止。只有KCL未通过时允许按“排除全部电气指标”继续。

## 3. LT1：五组合三频点小样

### LT1-A：运行范围

继续使用35 MHz旧网格口径，不修改生产网格：

```text
combinations:
  (0.6,4)
  (0.7,5)
  (0.45,6)
  (0.75,5)
  (0.5,5)

freq = 5, 20, 35 MHz
vamp = 1 V
Vdiff = 2 V
total_points = 15
```

这5组只是旧排名提供的哨兵样本，不是反相驱动的预定赢家。

### LT1-B：逐点输出

```text
x_scale
N_w_te1
freq_MHz
V_outer_complex
V_inner_complex
V_ref_complex
Vdiff_complex
Ptot
Vave
V_center_complex
Ptot_norm = Ptot/abs(Vdiff)^2
Vave_norm = Vave/abs(Vdiff)
geometry_status
mesh_status
selection_status
solve_status
solve_seconds
peak_server_ws_mb
model_sha256
script_sha256
criteria_hash
source_run_id
```

端口电流只在 LT0-C 通过时作为有效数据输出；否则保留空列并写明排除状态。

### LT1-C：验收

```text
expected_points = 15
successful_points = 15
duplicate_keys = 0
missing_keys = 0
nan_or_inf = 0
negative_Ptot = 0
drive_voltage_mismatch = 0
selection_drift = 0
server_cleanup_failures = 0
```

完成后根据实测 `seconds_per_frequency`、高分位耗时和峰值内存重新估算 LT2。

### LT1 STOP条件

- 电极电位不再是外 `+1 V`、内 `−1 V`、参考 `0 V`；
- `term1` 或 Circuit 被重新启用；
- 电极边界为空、重叠或物理身份改变；
- `intop5/swr1/efc1` 不一致；
- 同一组合重试一次后仍失败；
- server 30秒后仍不关闭；
- 模型/脚本/判据哈希意外变化。

## 4. LT2：72组合×7频点反相驱动粗扫

### LT2-A：固定口径

```text
drive_mode = dual_electrode_antiphase_voltage_drive
vamp = 1 V
Vdiff = 2 V
freq_MHz = 5,10,15,20,25,30,35
eligible_combinations = 72
frequency_count_per_combo = 7
expected_rows = 504
mesh_fmax = 35 MHz
```

本阶段禁止将 `fmax` 改为45 MHz。

### LT2-B：批次组织

- 严格串行，不并行运行 COMSOL；
- 根据LT1资源实测，每批安排8–16个组合；
- 每个组合完成7频点后立即写checkpoint；
- 每个批次使用独立server生命周期；
- 批次结束后执行最多30秒的端口关闭检查；
- 失败只重跑失败组合，不覆盖已通过数据；
- 每行保留 `source_run_id` 与 `source_artifact_sha256`；
- 每个child payload写入模型、脚本和判据哈希。

### LT2-C：每个组合的快速门禁

```text
geometry_status = ok
mesh_status = ok
pot1/pot2/gnd1 selections nonempty
pairwise_electrode_overlap = 0
term1_active = false
cir_inactive_verified = true
intop5 == swr1 == efc1
ptot_surface_area_unchanged = true
ptot_surface_bbox_unchanged = true
```

### LT2-D：资源停止线

- 单批次峰值 server WS ≥ 2.5 GB；
- 连续两个组合出现同类求解错误；
- server 30秒后仍未退出；
- 端口被非本任务PID占用；
- checkpoint出现重复、缺失或越界键；
- 模型SHA或drive manifest在批次间改变。

触发后写 `blocked_reason` 并停止，不得提高并行度或静默扩大资源上限。

### LT2-E：聚合验收

```text
unique_parameter_keys = 72
duplicate_parameter_keys = 0
missing_parameter_keys = 0
frequency_rows = 504
frequency_count_per_combo = 7
failed_frequency_points = 0
all_drive_mode_equal = true
all_model_sha256_equal = true
all_script_sha256_equal = true
all_criteria_hash_equal = true
all_control_surface_signatures_equal = true
child_runs_preserved = true
```

LT2未完全通过时不得制作“正式反相粗扫排名”。

## 5. LT3：质检、排名、Pareto与候选重选

### LT3-A：数据质量

输出独立质量报告，至少检查：

- 504行完整性；
- 参数与频率唯一键；
- NaN/Inf/空值；
- `Ptot<0`；
- 频率顺序；
- 驱动电位一致性；
- 控制面一致性；
- 单位和复数解析；
- 插值和带宽边界状态；
- 重试记录及最终采用的source run。

### LT3-B：分别计算的指标

不得使用无依据加权总分。分别报告：

- `Ptot@20MHz`、`Ptot_norm@20MHz`；
- `Vave@20MHz`、`Vave_norm@20MHz`；
- `Ptot/Vave`峰值与峰值频率；
- 两者−6 dB上下交点、中心频率、FBW；
- `lower_bound_not_found`；
- `upper_bound_not_found`；
- `bandwidth_closed`；
- 10–30 MHz与15–25 MHz平坦度；
- 相对反相基准 `(0.6,4)` 的倍率；
- 求解、插值和右删失标志。

规则：幅值使用 `20log10`，功率使用 `10log10`。5 MHz间隔结果只作粗筛；扫描上界未取到不能解释为无限带宽。

### LT3-C：Pareto与候选角色

从反相驱动新数据生成Pareto，再提出：

1. 基准 `(0.6,4)`；
2. 最大归一化声功率代表；
3. `Ptot/Vave`带宽闭合且平坦的均衡代表；
4. 15–25 MHz最平坦代表；
5. 可选中间稳健代表。

如果同一组合承担多个角色，应减少重复并选择能提供不同设计信息的候选。旧4+1名单没有自动入选权。

### LT3-D：与legacy驱动比较

只建立独立对照表，不混入反相排名。必须按差分电压归一化：

```text
Vave_norm = Vave/abs(Vdiff)
Ptot_norm = Ptot/abs(Vdiff)^2
```

不得用新模型 `±1 V` 的原始声功率直接与旧模型约1 V单端结果比较，也不得把电压倍增造成的约4倍功率误称为结构收益。

### LT3-E：最终产物

```text
reverse_drive_coarse_raw.csv
reverse_drive_coarse_aggregate.csv/json
reverse_drive_coarse_quality_report.md
reverse_drive_coarse_metrics.csv
reverse_drive_pareto.csv
reverse_drive_candidate_plan.csv
legacy_vs_reverse_normalized.csv
figures/
evidence_manifest.json
TO_CODEX_progress-20260914-reverse-coarse-ranking.md
```

## 6. LT3后强制停止

完成以下条件后，本轮任务状态设为 `PASS_WAITING_REVIEW`：

```text
LT0 = PASS
LT1 = PASS
LT2 = PASS
LT3 = PASS
reverse_drive_combos = 72
reverse_drive_rows = 504
reverse_drive_ranking_complete = true
fine_sweep_candidates_proposed = true
```

然后停止，不得执行：

- `fmax=45 MHz`生产网格；
- 5–45 MHz @0.5 MHz精扫；
- 网格桥接或细网格收敛；
- 全候选7R外场计算；
- 代理模型、阵列模型或实验外推。

这些项目必须等待新反相排名和候选名单复核。

## 7. 阶段回报格式

每个阶段状态只能是：

```text
NOT_STARTED
RUNNING
PASS
FAILED
BLOCKED
```

每次回报至少包含：

```text
phase
status
start_time
end_time
completed_units
expected_units
model_sha256
script_sha256
criteria_hash
failed_units
retry_count
peak_server_ws_mb
server_cleanup_result
artifacts
next_phase_eligible
blocking_reason
```

## 8. 全局STOP条件

遇到任一条件立即停止并回报：

- 母版或工作模型SHA意外变化；
- 反相电位不再是外 `+vamp`、内 `−vamp`、参考0 V；
- `term1` 或Circuit重新参与反相Study；
- 电极选择为空、重叠或物理身份改变；
- `intop5/swr1/efc1`控制面不一致；
- 同一组合连续两次求解失败；
- 内存超过2.5 GB停止线；
- 端口被非本任务进程占用；
- 参数/频率出现重复、缺失或越界；
- 需要改变几何、材料、驱动或声学边界才能继续；
- 报告指标与manifest口径冲突。

## 9. 最终提交清单

LT3完成后向Codex提交Markdown总报告，并附：

1. 修正后的 `drive_change_manifest.json`；
2. Circuit停用和Ground 0 V证据；
3. 法向电流/KCL审计，或明确的电气指标排除状态；
4. `x_scale/N_w_te1/vamp/fmax`扰动签名；
5. LT1的15点小样；
6. LT2的504点原始表、所有child run和聚合质量报告；
7. 新反相驱动指标、Pareto和候选计划；
8. 与legacy驱动的归一化对照；
9. 每批耗时、峰值内存、重试和server清理记录；
10. 全部关键产物SHA256；
11. 是否具备进入45 MHz网格阶段的明确结论。

---

**执行令：立即执行LT0。LT0通过后自动执行LT1；LT1的15/15点全部通过后自动执行LT2；LT2的72组合、504频率点完整通过后执行LT3。LT3生成反相驱动排名、Pareto和新候选建议后强制停止，等待Codex复核。**
