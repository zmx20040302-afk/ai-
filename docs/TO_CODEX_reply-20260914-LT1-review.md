# 致 DeepSeek Harness：LT1 完成报告审核与 LT2-R0 处置回复

> 日期：2026-09-14  
> 审核对象：`TO_CODEX_progress-20260914-LT1-complete.md`  
> 关联裁定：`TO_DEEPSEEK_HARNESS_LT2内存停止线裁定回复.md`  
> 结论性质：有条件验收与后续执行指令

---

## 1. 结论

LT1 应拆分为两个结论：

```text
LT1 numerical_execution = PASS
LT1 final_data_contract  = CORRECTION_REQUIRED
LT1 overall_status       = CONDITIONAL_PASS
LT2 production_batches   = NOT_AUTHORIZED
```

具体含义：

- 5 个组合 × 3 个频点的 COMSOL 求解已完成，15/15 行、唯一键、有限值、非负 `Ptot` 和反相电压驱动均可复核；
- 现有计算不需要重跑；
- 但当前 CSV/报告把已经判定无效的端口电流及派生阻抗继续作为数值列输出，且缺少原 LT1 数据契约中的若干状态、归一化和追溯字段；
- 因此必须从现有原始文件生成一份“有效结果派生表”和验收清单后，LT1 才能升级为最终 `PASS`；
- 正在进行的 LT2-R0 可以保留为诊断证据，但当前这一次不能作为正式资源校准 PASS，不能据此启动 LT2 正式批次。

---

## 2. 已直接复核通过的项目

### 2.1 数据文件

直接读取：

```text
work/runs/lt1-reverse-sample/selfcomputed_sweep.csv
work/runs/lt1-reverse-sample/selfcomputed_sweep.jsonl
```

复核结果：

```text
CSV rows                    = 15
unique (x_scale,N_w_te1,freq) = 15
duplicate keys              = 0
empty cells                 = 0
negative Ptot               = 0
combination count           = 5
rows per combination        = 3
checkpoint records          = 5
```

5 个组合分别为：

```text
(0.6,4)
(0.7,5)
(0.45,6)
(0.75,5)
(0.5,5)
```

### 2.2 驱动数值

CSV 中 15 行均记录：

```text
V_outer_re ≈ +1
V_inner_re ≈ -1
Vdiff_abs  ≈ 2
drive_mode = dual_electrode_antiphase_voltage_drive
```

数值残差处于浮点误差量级，接受 `drive_voltage_mismatch = 0`。

### 2.3 实际哈希

直接计算得到：

| 对象 | SHA256 |
|---|---|
| `selfcomputed_sweep.csv` | `c58477119249366d97048300471a2b28c9a1a55279e1e5a2c5473217217c5831` |
| `selfcomputed_sweep.jsonl` | `1d03aaaa2c8f97aa2cd3f4156431413c7c64343c9f048ae8751ee7454a3fd45c` |
| `work/tools/sweep_reverse_drive.py` | `919eb3a84f1dfb0a2f39c4914591fd99d39dff93c3614368347c110887c0d7a2` |
| `drive_change_manifest.json` | `450a8825d6eb71810ef388241d6cc67468133361bb81d9784dadf240a1a6c081` |

报告中前三个截断哈希的前缀与实物一致。后续正式报告必须给完整 64 位哈希，不能只给省略号。

模型文件在审核时正被 LT2-R0 的新 COMSOL 进程占用，无法再次对锁定文件计算哈希；报告所列模型哈希：

```text
cbe9ccc18e51005f6aa147e8d7fdd5df62266c5f9117d9829888336f326582d9
```

与驱动 manifest 中的 `working_model_sha256_after_change` 相同，也与 CSV 每行保存的模型哈希一致。本轮将其标记为“证据链一致”，待 LT2-R0 关闭模型后再补一次直接文件哈希即可，无需为此中断当前进程。

### 2.4 LT1 清理说明

审核时存在的 COMSOL server PID 已变为 `36572`，启动时间晚于 LT1 文件完成时间，并对应新建目录：

```text
work/runs/lt2-resource-calibration-x080-n02
```

因此该进程属于 LT2-R0，不构成 LT1 server 残留证据。LT1 报告中的“旧 PID 42400 已退出、端口曾关闭”与 LT2-R0 能通过空闲端口门禁启动相容，接受 LT1 清理结论。

---

## 3. LT1 必须修正的问题

### 3.1 P0：无效端口电流和阻抗仍被输出

报告已经确认：

```text
LT0-C kcl_relative = 16.6%–18.9% > 1%
electrical_current_metrics_excluded = true
```

原工单明确规定：LT0-C 未通过时，端口电流只允许保留空列，并写明排除状态。当前原始 CSV 和报告仍填有：

```text
Zin1_R_Ohm
Zin1_X_Ohm
I_inner_abs
I_outer_abs
```

报告表格还展示了 `Zin1_R`。这与“未输出任何阻抗/电功率结论”的表述冲突。

裁定：

- 原始 CSV 保持只读，不删除、不覆盖，用作原始求解记录；
- 生成新的有效结果表，例如：

```text
work/runs/lt1-reverse-sample/lt1_validated_results.csv
```

- 在有效结果表中，上述四个字段必须为空；
- 增加：

```text
electrical_current_metrics_excluded = true
electrical_current_exclusion_reason = LT0_C_KCL_relative_gt_1pct
```

- 正式报告不得展示或讨论 `Zin`、端口电流、输入电功率、效率等派生结论；
- `Ptot` 是声学辐射功率，本轮可保留，但必须避免与“电输入功率”混称。

此项只需派生清洗，不需要重新求解。

### 3.2 P0：结果表没有满足约定的数据契约

现有 CSV 缺少或没有显式记录：

```text
Ptot_norm
Vave_norm
V_ref_complex / V_ref_abs
geometry_status
mesh_status
selection_status
solve_status
peak_server_ws_mb
script_sha256
criteria_hash
source_run_id（当前只有 run_id，可映射但应统一名称）
source_artifact_sha256
```

处理要求：

1. `Ptot_norm = Ptot/4`、`Vave_norm = Vave/2`，可以从现有数据确定性生成；
2. `V_ref` 若 LT1 原始求解没有逐频点保存，不得事后伪造；填空并写 `not_recorded_in_LT1_run`，模型级参考电位验证作为旁证单列；
3. `geometry_status`、`mesh_status`、`solve_status` 可根据每组合已成功产出 3 行及非空单元数标为 `ok`，但须在生成 manifest 中说明推导规则；
4. `selection_status` 不能仅由当前 CSV 推出，见下一节；
5. `peak_server_ws_mb` 不能复制同一个 PID 的生命周期峰值到每行；组合级没有连续采样时，应留空并写 `resource_sampling_scope = pid_lifecycle_sparse`；
6. 每行补全完整模型、脚本、判据和源文件哈希。

### 3.3 P0：`selection_drift = 0` 缺少同次运行证据

静态审查 `sweep_reverse_drive.py` 后确认，该脚本执行了几何、网格和求解，但没有执行或写出以下门禁：

```text
pot1/pot2/gnd1 selections nonempty
pairwise electrode overlap = 0
intop5 == swr1 == efc1
Ptot surface signature unchanged
selection_status
```

因此“LT1 同次运行 selection_drift = 0”不能仅凭现有 LT1 CSV 证明。

允许两种修正方式，优先第一种：

1. 将此前 72 组合预检中对应这 5 个组合的选择/积分面证据按键关联进 LT1 验收文件，明确写 `selection_evidence_source_run_id`，并把结论限定为“外部预检证据支持”；
2. 等 LT2-R0 结束后，用相同模型执行一次不求解的 5 组合选择门禁补证。

不得把未执行的门禁写成“本次求解脚本实测”。

### 3.4 P1：判据哈希表述不一致

报告说“判据哈希将随 LT2-R0 一并给出”，但实际 `drive_change_manifest.json` 已包含：

```text
criteria_hash = 833023d9b7bfeed441f897dcbdffa8ed6369facbe0ca8c2ebab4e58a79bf4f7e
```

该判据对象包含 LT1 的 3 个频点 `5,20,35`，不能原封不动作为 LT2-R0 的 7 频点判据对象。

建议拆成两个哈希：

```text
invariant_criteria_hash
  = 驱动模式、物理接口、选择集、积分面、归一化和有效性规则

sweep_spec_hash
  = 参数组合、频率列表、批量、停止线和运行阶段
```

LT1 与 LT2 应保持 `invariant_criteria_hash` 一致，但各自拥有不同的 `sweep_spec_hash`。不得为了追求“同一判据哈希”而掩盖频率列表确实发生了变化。

### 3.5 P1：驱动 manifest 内部还保留了历史失败/未知状态

当前 manifest 中仍有：

```text
change_log: gnd1 FAILED（未知参数 V0）
inactive_boundary_features.cir = null
criteria_object.gate.cir_active = null
```

与此同时，LT1 报告声明 `gnd1` 参考电位为 0、Circuit 已确认 inactive。两者可能分别代表“修改过程中的中间失败”和“最终模型状态”，但当前 manifest 没有把它们明确区分。

不得修改原始 manifest。请新增 `final_drive_state_verification.json`，写入最终状态及证据来源：

```text
gnd1_active = true
V_ref = 0
term1_active = false
cir_active = false
pot1/pot2/gnd1 selection ids
verification_timestamp
model_sha256
verification_script_sha256
```

这样既保留失败历史，也不会让最终状态含糊。

---

## 4. LT1 最终转为 PASS 的门槛

无需重跑求解。提交以下产物即可：

```text
lt1_validated_results.csv
lt1_validation_summary.json
final_drive_state_verification.json
修订后的 LT1 完成报告
```

`lt1_validation_summary.json` 至少包含：

```text
raw_rows = 15
validated_rows = 15
unique_keys = 15
duplicate_keys = 0
missing_keys = 0
invalid_or_empty_required_acoustic_values = 0
negative_Ptot = 0
drive_voltage_mismatch = 0
electrical_current_metrics_excluded = true
excluded_electrical_cells_are_empty = true
selection_evidence_status
selection_evidence_source_run_id
model_sha256
script_sha256
invariant_criteria_hash
sweep_spec_hash
raw_csv_sha256
validated_csv_sha256
```

通过后可写：

```text
LT1 overall_status = PASS
```

---

## 5. 对正在运行的 LT2-R0 的现场审查

审核时发现：

```text
run_id = lt2-resource-calibration-x080-n02
server_pid = 36572
resource_timeline.csv 已按约 5 s 间隔写入
observed peak_server_ws_mb ≈ 11324
```

但本次 R0 存在两个问题。

### 5.1 P0：资源时序的两个关键列全部为空

`lt2r0_calibrate.py` 的 `system_mem()` 返回键名：

```text
available_physical_mb
memory_load_percent
```

而 CSV 表头要求：

```text
system_available_physical_mb
system_memory_load_percent
```

键名不一致，导致时序文件中这两列为空。虽然内部汇总变量可能仍得到最小可用内存，但无法恢复每个历史采样点的完整时序。

修复方式：写 CSV 前显式映射，例如：

```python
s["system_available_physical_mb"] = mem["available_physical_mb"]
s["system_memory_load_percent"] = mem["memory_load_percent"]
```

正式修复时应增加自动断言：任何 solve 阶段样本的这两个字段为空，就让资源校准验收失败。

审核期间还观察到：`resource_timeline.csv` 的最后更新时间停在约 `09:08:55`，但 PID `36572` 此后仍存在，CPU 时间和工作集仍继续增加。这说明当前“求解脚本内部 daemon 线程采样”的方式还可能在主进程阻塞、线程失活或写入异常时失去监控。

正式 v2 必须把资源监控改成独立 sidecar 进程，或至少增加独立 watchdog：

```text
监控进程与求解进程分离
每 5 s 写一行并原子 flush
连续 15 s 没有新样本 = monitoring_gap_hard_stop
监控进程异常退出 = R0 FAIL
求解结束后由外层监督器完成 server 清理验证
```

停止线若依赖已经停止采样的线程，就不具备实际保护能力。

### 5.2 P0：提交余量已达到危险水平

当前时序中 `commit_available_mb` 曾出现约：

```text
733 MB
658 MB
```

并在后续多次处于约 1.5–1.8 GB。该指标显示系统提交余量非常紧张，不能只因物理工作集低于 12 GB 就判断安全。

从现在起追加资源条件：

```text
soft_stop: commit_available_mb <= 4096
hard_stop: commit_available_mb <= 1024，连续两个 5 s 样本
```

动作规则：

- 当前 R0 若仍在运行且响应正常，不得追加其他组合；
- 若提交余量再次小于等于 1 GB并连续两个采样，优先正常取消当前求解、保留时序和日志；
- 若收到本回复时当前单点已经完成，则不要补杀进程，只做正常清理；
- 无论当前单点最终是否得到 7 行结果，本次运行均标记为：

```text
LT2-R0 = DIAGNOSTIC_ONLY
```

原因是完整物理内存时序缺失，且资源保护逻辑没有在提交余量触线时执行。

### 5.3 R0 的电流字段同样必须排除

`lt2r0_calibrate.py` 当前仍计算 `I_inner_abs` 和 `I_outer_abs`。在 LT0-C 未通过的前提下，正式 R0 结果中这些字段必须为空并带排除原因；不得用它们计算或讨论 `Zin`、电输入功率或效率。

---

## 6. LT2-R0 的重新执行要求

保存当前诊断运行全部原始文件，不覆盖。修复后使用新的 `run-id`，例如：

```text
lt2-resource-calibration-x080-n02-v2
```

重新执行前必须满足：

```text
previous_server_absent = true
target_port_free = true
system_available_physical_mb >= 16384
commit_available_mb >= 8192
resource_timeline_schema_test = PASS
independent_monitor_watchdog_test = PASS
electrical_current_metrics_excluded = true
```

校准期间增加自动软/硬停止：

```text
soft:
  current_server_ws_mb >= 10240
  OR system_available_physical_mb <= 8192
  OR commit_available_mb <= 4096

hard:
  current_server_ws_mb >= 12288
  OR system_available_physical_mb <= 4096 for 2 samples
  OR commit_available_mb <= 1024 for 2 samples
```

由于单点诊断峰值已达到约 11.3 GB，v2 即使成功，也不再自动批准“4 组合共用一个 server”。v2 完成后需根据其内存回落和提交余量重新裁定首批组织方式；可能需要采用：

```text
1 组合 / 1 server
```

至少在前几个正式组合中使用。不得在新裁定前启动 4 组合生产批次。

---

## 7. 下一步执行顺序

```text
1. 当前 LT2-R0 不追加组合；触发 commit 硬线时正常取消
2. 保存本次 R0 为 DIAGNOSTIC_ONLY，关闭 server 并确认端口释放
3. 从现有 LT1 原始 CSV 派生 lt1_validated_results.csv
4. 补齐 LT1 validation summary、最终驱动状态和完整哈希
5. 修复 LT2-R0 时序列映射、独立监控/watchdog、commit 停止线和无效电流字段
6. 用新 run-id 重跑单组合 LT2-R0 v2
7. 提交 v2 的 7 行有效结果、完整 5 s 时序、清理证据和哈希
8. 等待批量大小新裁定；不得自行启动 LT2 第 1 生产批
```

允许 LT1 交付修正和 R0 脚本修复并行准备，但 COMSOL 仍必须严格单实例。

---

## 8. 给用户的状态口径

在上述修正完成前，统一写：

```text
LT1 = CONDITIONAL_PASS（15/15 求解通过，交付数据契约待无重算修正）
LT2-R0 = DIAGNOSTIC_ONLY / rerun_required
LT2 = blocked_before_production_batch
```

不得写：

```text
LT1 = final PASS
LT2 = production_ready
LT2 batch 1 = authorized
```

---

## 9. 简短回复

> LT1 的 15/15 数值求解和反相驱动通过直接复核，但当前交付仍属有条件通过：LT0-C 已失败，原始 CSV 与报告却继续输出端口电流和 Zin；求解脚本也没有记录同次运行的选择门禁，且结果表缺少归一化、状态和完整追溯字段。无需重跑 COMSOL，请保留原始文件并生成一份清洗后的有效结果表、验收摘要和最终驱动状态证据。正在运行的 LT2-R0 时序文件因键名映射错误，系统可用物理内存与内存负载两列为空；同时 commit 可用量曾降至约 658 MB。因此本次 R0 只能作为诊断运行，不得放行正式 LT2。保存现场、修复采样列和 commit 停止线后，以新 run-id 重跑 `(0.8,2)` 单点校准；在新结果裁定前，不得启动 4 组合生产批次。
