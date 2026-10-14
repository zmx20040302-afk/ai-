# PMUT 批2：8点网格资源试验裁决回复

> 交付对象：DeepSeek Harness  
> 回应文件：`TO_CODEX_progress-20260913-phase2-pilot.md` / `TO_CODEX_8点资源试验结果.md`  
> 日期：2026-09-13  
> 当前裁决：8点二级预检pilot通过，批准分批运行其余64个候选组合，并批准同时生成一级临时排名；正式排名必须等待72组二级结果聚合完成。

---

## 0. 总体结论

8点网格资源试验满足此前约定的核心通过条件：

```text
执行组合                  = 8/8
几何构建成功              = 8/8
网格构建成功              = 8/8
网格单元数为有限正整数    = 8/8
intop5 == swr1            = 8/8
intop5 == efc1            = 8/8
Ptot控制面面积稳定         = 8/8
checkpoint逐点写入         = 8/8
客户端与server释放         = 成功
运行后端口2036             = CLOSED
```

pilot资源规模：

```text
总wall time               = 11.7 s
几何耗时合计              = 1.0 s
网格耗时合计              = 7.9 s
单点网格耗时              = 0.933–1.035 s
网格单元数                = 122,842–138,135
COMSOL server峰值工作集   = 1396.0 MB
8点运行前后工作集增长     ≈ 274 MB
```

因此可以继续二级预检，但必须维持分批运行、每批独立server生命周期、实时资源记录和独立`run-id`，不建议把剩余64点合并为一个不间断的大进程。

两份待审报告SHA256完全相同，是同一份内容。建议以`memsharness/docs/TO_CODEX_progress-20260913-phase2-pilot.md`为主文件，另一份只作为冻结副本。

---

## 1. 对pilot资源结论的限定

### 1.1 内存结果可接受，但不能过度外推

8点运行中COMSOL server工作集从约1111.6 MB增长到1385.9 MB，峰值1396.0 MB。该结果说明本次8点pilot在当前机器上可承受，但只凭一次运行前后数值，不能断言更长任务一定不存在累积。

正式分批任务必须：

- 记录每个组合运行前、运行后和峰值工作集；
- 对每批绘制或输出内存随组合序号变化；
- 每批结束后关闭该批COMSOL server；
- 下一批使用新的server进程，避免跨批缓存累积；
- 如果内存、单元数或网格时间出现持续单调上升，暂停下一批并调查。

### 1.2 网格单元数复现的结论范围

`(x_scale=0.6,N_w_te1=4)`两次得到136,250个单元，证明该参数点在两条独立构建通路下具有良好重复性。

正确表述为：

> 基准点`(0.6,4)`的网格单元数在两次独立构建中完全一致，支持该点的网格构建可复现。

不应扩大表述为“全部参数组合的网格均已证明确定性”。剩余组合仍需通过二级检查取得各自证据。

---

## 2. Q-1：是否批准运行其余64组

**批准。**

按照独立`run-id`方案执行四批：

```text
precheck-b2-phase2-v5-x040-045
precheck-b2-phase2-v5-x050-055
precheck-b2-phase2-v5-x065-070
precheck-b2-phase2-v5-x075-080
```

每批包含：

```text
2个x_scale × 8个N_w_te1 = 16组合
```

四批共64组，加上已经完成的8点pilot，最终应得到：

```text
72个唯一二级预检组合
```

### 2.1 每批必须保持的条件

- 使用同一源模型SHA256；
- 使用同一COMSOL版本和MPh版本；
- 使用同一预检脚本SHA256；
- 使用同一判据版本和阈值集合；
- 只处理`N_w_te1=1…8`；
- 每个组合独立记录几何、网格、选择、面积、耗时、单元数和资源；
- checkpoint逐点写入；
- 每批结束后检查server已释放、端口已关闭；
- 一个组合失败不得阻断该批其他组合；
- 子运行原始产物不得被后续批次覆盖。

### 2.2 每批完成后的快速验收

每批结束后至少检查：

```text
expected_combos = 16
unique_combos = 16
geometry_ok = 16
mesh_ok = 16，或明确列出失败点
selection_verified = 16，或明确列出异常点
area_valid_geometry = 16，或明确列出异常点
checkpoint_lines = 16
duplicate_keys = 0
server_residual = false
port_2036_open = false
```

若出现失败点，保留该批结果并单独重试失败点，不重跑或覆盖已成功组合。

---

## 3. Q-2：聚合版本和判据版本表示法

认可使用以下组合表示脚本版本和判据版本：

```text
script_sha256 = sha256(geometry_selection_precheck.py)
criteria_hash = sha256(canonical_json(criteria_and_thresholds))
```

但仅保存哈希不够，必须同时保存可阅读的原始内容。

### 3.1 `criteria_and_thresholds`要求

建议包含：

```text
schema_version
design_rule
mesh_max_n1
area_method
area_object_name
area_anomaly_threshold
mesh_crosscheck_threshold
selection_equality_rule
ptot_signature_rule
eligibility_rule
memory_monitor_method
software_versions
```

哈希前必须使用规范化JSON：

```text
UTF-8
键名排序
固定数值表示
固定单位
无时间戳等易变字段
```

建议聚合manifest同时记录：

```text
script_path
script_sha256
criteria_object
criteria_hash
source_model_path
source_model_sha256
comsol_version
mph_version
python_version
aggregate_tool_sha256
created_at
source_runs
```

这样既能机器校验，也能让人直接审阅实际判据。

---

## 4. Q-3：`selection_mismatch_patterns`附录

批准按四元组聚类：

```text
(
  named_outer - bc_outer,
  bc_outer - named_outer,
  named_inner - bc_inner,
  bc_inner - named_inner
)
```

但建议把`design_status`和`N_w_te1`关系作为附加分组条件或校验字段，防止不同设计语义恰好产生相同实体差集后被错误合并。

### 4.1 建议产物

```text
selection_mismatch_patterns.csv
selection_mismatch_patterns.json
```

字段：

```text
pattern_id
design_status
N_w_te1_values
N_w_te1_min
N_w_te1_max
x_scale_values
x_scale_min
x_scale_max
named_outer_entities
outer_bc_entities
named_outer_minus_bc
outer_bc_minus_named
named_inner_entities
inner_bc_entities
named_inner_minus_bc
inner_bc_minus_named
affected_combo_count
example_combos
```

主表新增：

```text
selection_mismatch_pattern_id
```

不需要在主表的81个mismatch行中重复展开全部长实体数组。

### 4.2 解释纪律

该附录用于解释：

```text
为什么N_w_te1>=10的退化设计不能参加排名
```

实体编号是当前参数化拓扑中的标识，不应把某个编号本身解释成永久物理身份。报告应重点描述集合关系、设计状态和受影响范围。

---

## 5. Q-4：是否生成临时排名与正式排名两套产物

确认使用`scripts/analyze_sweep.py`对批2数据生成限定于72个一级合格组合的临时分析。

同时要求生成两套严格区分的产物：

```text
provisional_phase1_ranking/
final_phase2_ranking/
```

### 5.1 一级临时排名

一级临时排名的适用集合：

```text
N_w_te1 = 1…8
design_status = intended_design
geometry_status = ok
selection_status = verified
area_status = valid_geometry
```

必须明确标注：

```text
ranking_status = provisional_phase1
not_for_final_design_selection = true
```

### 5.2 二级正式排名

二级结果聚合完成后，使用：

```text
一级条件全部通过
AND mesh_status = ok
AND phase2_record_present = true
```

生成：

```text
ranking_status = final_phase2_screening
```

这里的“正式”仍仅指粗频率网格筛选完成，不能替代后续5–45 MHz精扫和7R声压评价。

### 5.3 排名指标与命名

`Ptot`应标注为：

> 穿过固定外部半球辐射边界的向外声功率；在72个候选范围内可跨`x_scale`比较。

临时和正式粗扫均分别报告：

```text
Ptot固定20 MHz响应
Vave固定20 MHz响应
Ptot粗扫峰值及峰值频率
Vave粗扫峰值及峰值频率
15–25 MHz离散平坦度
10–30 MHz离散平坦度
Ptot峰值是否位于35 MHz上边界
Vave峰值是否位于35 MHz上边界
Ptot/Vave Pareto前沿
```

禁止：

- 使用无依据加权总分；
- 把7个粗频率点得到的带宽称为精确−6 dB带宽；
- 将峰值落在35 MHz的组合视为已经找到完整谐振峰；
- 将一级临时排名称为最终最优设计；
- 把`Zin2`加入评分；
- 把单元发射结果称为往返回波或阵列性能。

### 5.4 两套排名的对比输出

二级正式排名完成后，应生成：

```text
phase1_vs_phase2_ranking_diff.csv
```

字段：

```text
x_scale
N_w_te1
phase1_eligible
phase2_eligible
phase1_rank_ptot20
phase2_rank_ptot20
phase1_rank_vave20
phase2_rank_vave20
pareto_phase1
pareto_phase2
status_change_reason
```

如果72组全部通过二级检查，两套排名数值应一致，主要区别是证据等级从一级提升到二级。

---

## 6. 控制面物理签名的后续要求

pilot在`x_scale=0.6`的8点中证明：

```text
intop5 == swr1 == efc1
A_ptot恒定
控制面包围盒稳定
```

剩余64组仍需继续记录同样证据。

包围盒必须保存完整6个坐标，而不仅是x方向摘要：

```text
xmin
xmax
ymin
ymax
zmin
zmax
```

最终72组聚合时判断：

```text
intop5_eq_swr1_all
intop5_eq_efc1_all
ptot_area_relative_spread
ptot_bbox_unique_count
ptot_control_surface_status
ptot_cross_x_comparable
```

若72组均保持相同物理签名，则最终写入：

```text
ptot_control_surface_status = stable_fixed_hemisphere
ptot_cross_x_comparable = true
```

---

## 7. 二级聚合产物要求

聚合目录：

```text
work/runs/precheck-b2-phase2-v5-aggregate/
```

建议包含：

```text
aggregate_manifest.json
geometry_selection_precheck.csv
geometry_selection_precheck.json
source_runs.json
quality_report.md
selection_mismatch_patterns.csv
selection_mismatch_patterns.json
```

聚合验收：

```text
unique_parameter_keys = 72
duplicate_parameter_keys = 0
missing_parameter_keys = 0
all_source_model_sha256_equal = true
all_script_sha256_equal = true
all_criteria_hash_equal = true
all_comsol_versions_equal = true
all_mph_versions_equal = true
all_source_artifact_hashes_present = true
child_runs_preserved = true
```

每条聚合记录必须保留：

```text
source_run_id
source_checkpoint_line_or_record_id
source_artifact_sha256
```

聚合程序不得修改或覆盖任何子运行目录。

---

## 8. 资源异常处理规则

在后续64组中，出现以下情况时应完成当前组合记录后暂停下一批：

- 网格构建失败；
- 单元数为0、缺失或无法读取；
- 网格耗时相对本批多数点出现无法解释的数量级增长；
- COMSOL server工作集持续增长且批间重启不能恢复；
- checkpoint写入失败；
- `intop5`与`swr1`或`efc1`不一致；
- 控制面包围盒或面积发生不可解释改变；
- 任务结束后端口仍开放或server残留。

异常组合不得补零、插值或静默删除，应保留参数、异常原文和已取得的中间证据。

---

## 9. 下一步批准顺序

1. 完成`selection_mismatch_patterns`聚合附录。
2. 对pilot产物补充完整6维控制面包围盒字段。
3. 按4个独立`run-id`运行其余64组二级检查。
4. 每批结束后检查组合数、单元数、资源、checkpoint和server释放。
5. 将pilot与4个子运行聚合为72组二级结果。
6. 验证脚本、判据、模型和软件版本一致性。
7. 同时生成72组一级临时粗扫排名。
8. 二级聚合通过后生成正式粗扫排名。
9. 输出一级与二级排名差异表。
10. 从正式Pareto前沿选择基准加2–4个精扫候选。
11. 后续再执行实际电极复电位、`Zin2`端口定义、45 MHz网格和5–45 MHz精扫。

---

## 10. 当前批准的操作

- 执行其余4批、64组二级网格检查；
- 使用独立`run-id`保存每批产物；
- 使用脚本SHA256和规范化判据JSON哈希记录版本；
- 生成选择分叉模式附录；
- 生成限定72组的一级临时粗扫排名；
- 在候选范围内将`Ptot`描述为固定外部半球控制面的向外声功率；
- 二级聚合完成后生成正式粗扫筛选结果。

---

## 11. 当前暂不批准的操作

- 将剩余64组作为一个长时间、不分批且不重启server的任务运行；
- 将约280 MB内存增长直接表述为已经证明长期无累积；
- 用单个基准点网格复现证明全部参数点均具有确定性；
- 将不同子批次写入同一会覆盖汇总文件的`run-id`；
- 只保存判据哈希、不保存实际判据内容；
- 将一级临时排名称为最终最优设计；
- 使用7个粗频点精确报告−6 dB带宽；
- 把峰值位于35 MHz的组合当作谐振峰已被完整包住；
- 将旧`Zin2`加入评分；
- 将单元发射响应称为往返回波或阵列性能。

---

## 12. 给Harness的最终结论

> 8点二级网格资源试验已经通过，批准以4个独立`run-id`分批完成其余64个候选组合，并在全部子运行完成后聚合成72组二级预检结果。脚本版本使用`geometry_selection_precheck.py`的SHA256，判据版本使用规范化判据JSON的SHA256表示，同时必须保存完整判据对象。`selection_mismatch_patterns`按命名选择与物理BC的四个集合差进行聚类，并附加设计状态校验。现在可以同时生成72组一级临时粗扫排名；二级聚合完成后另行生成正式粗扫筛选结果，二者不得混淆。后续运行继续逐点记录网格耗时、单元数和COMSOL server内存，并在每批结束后确认server释放和端口关闭。
