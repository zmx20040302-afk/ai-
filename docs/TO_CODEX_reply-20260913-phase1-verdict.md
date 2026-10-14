# PMUT 批2：162组一级预检结果裁决回复

> 交付对象：DeepSeek Harness  
> 回应文件：`TO_CODEX_progress-20260913-phase1-162.md` / `TO_CODEX_162组一级预检结果.md`  
> 日期：2026-09-13  
> 当前裁决：162组一级预检通过；72个正常设计组合获准进入临时粗扫分析和二级网格检查，另外90组继续排除。

---

## 0. 总体结论

一级预检已经达到预期目标，可以进入下一阶段。

本轮实测结果为：

```text
总组合数                         = 162
intended_design                  = 72
design_boundary_coincident       = 9
design_region_reversed           = 81
geometry_status == ok            = 162
selection_status == verified     = 81
selection_status == mismatch     = 81
area_status == valid_geometry    = 162
bc_conflict                      = 0
empty_selection                  = 0
eligible_for_ranking             = 72
ineligible                       = 90
```

核心裁决：

- `N_w_te1=1…8`的72组可以进入临时粗扫排名，并进入二级网格检查；
- `N_w_te1=9`的9组属于设计边界重合，不进入主排名；
- `N_w_te1=10…18`的81组属于设计区域反序，不进入主排名；
- 退化设计没有表现为内外BC实体直接相交，而是表现为设计半径反序以及命名选择与物理BC选择发生分叉；
- 原先“41/81实体电极重叠”的推断已经被本次实体级预检取代，不应继续作为最终结论使用。

两份待审报告SHA256完全相同，是同一份内容。建议以`memsharness/docs/TO_CODEX_progress-20260913-phase1-162.md`为主文件，另一份只作为冻结副本。

---

## 1. 一级预检验收结果

以下要求已经满足：

- 162组均有checkpoint记录；
- 设计、几何、选择、面积和排名资格已经分列保存；
- 三种几何面积均通过最终对象`fin`取得；
- 162/162组合的面积状态为`valid_geometry`；
- 内电极、外电极和`intop5`各完成144对相邻`x_scale`比较；
- 三种面积均没有检测到超过当前阈值的突变；
- 命名选择和物理BC选择已逐组合比较；
- 固定`run-id`的`--resume`已经验证；
- checkpoint没有重复行；
- COMSOL模型、客户端和server均已正确释放；
- 一级任务没有构建有限元网格，也没有运行频域求解器。

因此，一级预检结果可以作为后续参数筛选和二级网格检查的正式输入。

---

## 2. Q-A：`intop5`控制面判据

接受以72个可排名候选组合判定：

```text
ptot_control_surface_status = stable_fixed_hemisphere
ptot_cross_x_comparable = true
```

### 2.1 候选子集结论

在72个`N_w_te1=1…8`组合中：

```text
intop5_entities = [1,3,70,104]
实体集合唯一
area_ptot唯一值数 = 1
area_ptot = 6.2661535589e-08 m²
selection_status = verified
```

这说明用于候选排名的`Ptot`控制面在整个`x_scale=0.4…0.8`范围内稳定，`Ptot`可以跨`x_scale`比较。

### 2.2 全162组实体编号漂移的解释

全量数据出现三套实体编号：

```text
[1,3,70,104]
[1,3,48,71]
[1,3,54,80]
```

但实体编号变化本身不能直接证明物理控制面发生变化。COMSOL在参数化几何拓扑重建后，边界编号可能改变。判断物理表面是否稳定，应检查其几何和物理签名，而不仅仅比较编号字符串。

建议增加以下检查：

```text
intop5_entities == swr1_entities
intop5_entities == efc1_entities
area_ptot_geometry
ptot_boundary_bounding_box
ptot_boundary_acoustic_domain_membership
ptot_boundary_normal_or_orientation
```

如果`intop5`始终与`SphericalWaveRadiation`和`ExteriorFieldCalculation`选择相同，且面积、位置和声学域归属保持稳定，则它仍是同一个物理半球控制面，即使实体编号发生改变。

因此全量状态不建议写成：

```text
unstable_or_entities_changed
cross_x_comparable = false
```

建议改为：

```text
entity_ids_changed = true
physical_surface_stability = pending_signature_check
cross_x_comparable = not_applicable_for_ineligible_designs
```

由于编号漂移只发生在已经被设计判据排除的90组中，它不影响72个候选组合的`Ptot`排名资格。

---

## 3. `Ptot`的物理口径

模型静态定义显示，`intop5`与下列节点使用相同的声学外边界：

```text
SphericalWaveRadiation
ExteriorFieldCalculation
```

其面积接近半径100 µm的理论半球面积：

```text
2πR² = 6.283185307e-08 m²
实测  = 6.266153559e-08 m²
相差约0.271%
```

因此`Ptot`的建议名称为：

```text
穿过固定外部半球辐射边界的向外声功率
```

在72个候选组合中，它可以用于跨`x_scale`和`N_w_te1`的相对比较。

但仍不得称为：

- 膜面局部压力；
- 往返回波功率；
- 接收灵敏度；
- 阵列声功率或阵列带宽。

---

## 4. Q-B：是否导出命名选择与BC分叉实体差集

建议导出，但使用**聚合附录**，不必把长实体数组重复写入81行主结果表。

建议输出：

```text
selection_mismatch_patterns.csv
selection_mismatch_patterns.json
```

字段：

```text
pattern_id
design_status
N_w_te1_values_or_range
x_scale_values_or_range
named_outer_entities
outer_bc_entities
named_outer_minus_bc
outer_bc_minus_named
named_inner_entities
inner_bc_entities
named_inner_minus_bc
inner_bc_minus_named
affected_combo_count
```

主表只保留：

```text
selection_status
selection_mismatch_pattern_id
```

这样既能保存诊断证据，又不会显著增加主表体积。

需要明确：

- `N_w_te1=9`的选择状态仍可能为`verified`，但它的设计边界重合，因此仍不可排名；
- `N_w_te1>=10`同时存在`design_region_reversed`和`selection_mismatch`，两种证据应并列保留。

---

## 5. Q-C：8点网格资源试验

批准增加监控字段后执行：

```text
x_scale = 0.6
N_w_te1 = 1,2,3,4,5,6,7,8
```

二级资格条件保持：

```text
N_w_te1 <= 8
AND design_status == intended_design
AND geometry_status == ok
AND selection_status == verified
AND area_status == valid_geometry
```

### 5.1 必须记录的字段

```text
geometry_seconds
mesh_seconds
mesh_element_count
checkpoint_write_status
cleanup_status
port_closed_after_run
```

### 5.2 建议记录的内存字段

```text
comsol_server_pid
comsol_server_working_set_before
comsol_server_working_set_after
comsol_server_peak_working_set
```

峰值内存必须监控`comsolmphserver`进程，而不是Python进程。如果暂时不能可靠取得峰值内存，不必阻塞8点试验，但至少必须记录网格单元数、每点几何耗时、每点网格耗时以及任务结束后的资源释放状态。

### 5.3 通过条件

8点资源试验通过需满足：

- 8/8几何构建成功；
- 8/8网格构建成功；
- 网格单元数均为有限正整数；
- 没有随`N_w_te1`出现不可解释的单元数或耗时突变；
- checkpoint逐点写入；
- COMSOL server没有残留；
- 内存没有持续累积到不可控水平；
- 二级检查不修改原始模型和粗扫数据。

8点试验通过后，批准继续处理其余64个候选组合。

72个一级合格组合现在可以先生成“临时粗扫排名”，但正式候选资格仍应等待二级网格检查。

---

## 6. Q-D：二级检查的分批`run-id`方案

当前不批准不同`x_scale`子集直接共用一个`run-id`，除非脚本已经修改为从完整checkpoint重新聚合最终JSON/CSV。

原因是：

- checkpoint可以保留历史行；
- 但当前每次运行结束生成的最终JSON/CSV可能只包含本次参数网格；
- 后一批可能覆盖前一批汇总文件；
- 最终报告可能误以为只有最后一个批次。

### 6.1 当前推荐的安全方案

为每批使用独立`run-id`：

```text
precheck-b2-phase2-v5-x060-pilot
precheck-b2-phase2-v5-x040-045
precheck-b2-phase2-v5-x050-055
precheck-b2-phase2-v5-x065-070
precheck-b2-phase2-v5-x075-080
```

其中`x=0.6`已经在pilot中完成，后续批次不重复运行。

全部结束后生成独立聚合产物：

```text
precheck-b2-phase2-v5-aggregate/
├── aggregate_manifest.json
├── geometry_selection_precheck.csv
├── geometry_selection_precheck.json
├── source_runs.json
└── quality_report.md
```

### 6.2 聚合要求

- 以`(x_scale,N_w_te1)`作为唯一键；
- 最终应有72个唯一组合；
- 不允许重复或缺失；
- 每条记录保留来源`run_id`；
- 保存每个子运行产物的SHA256；
- 检查所有子运行使用相同源模型SHA256、COMSOL版本、脚本版本和判据版本；
- 汇总二级通过、失败和警告数量；
- 聚合产物不得覆盖任一原始子运行。

### 6.3 统一`run-id`的可选方案

如果希望使用统一：

```text
--run-id precheck-batch2-phase2-v5 --resume
```

必须先修改程序：

- 最终JSON/CSV从完整`checkpoint.jsonl`读取全部历史组合；
- 不是只根据本次`combos`生成；
- 对checkpoint按`(x_scale,N_w_te1)`去重；
- 验证72个唯一组合全部存在后才发布最终汇总。

在该修改完成并经过小批次测试前，优先使用独立`run-id`方案。

---

## 7. 对实体编号漂移的进一步说明

实体编号是参数化几何当前拓扑中的标识，不是永久物理身份。以下情况可能造成编号变化：

- 内部几何边界数量变化；
- 布尔运算输出拓扑变化；
- 重合边界出现或消失；
- 几何特征顺序重新编号；
- 选择集跟踪到相同物理表面但返回新的实体编号。

因此控制面稳定性应使用物理签名：

```text
surface_role
area
bounding_box
centroid_or_position
physics_membership
adjacent_domain
normal_orientation
```

而不能只使用：

```text
entity_id_list
```

对于本项目，候选72组的编号和面积均稳定，已经足以支持候选范围内的`Ptot`比较。其余90组无排名资格，编号变化只作为退化设计诊断证据保存。

---

## 8. 下一步批准顺序

1. 增加`intop5`、`swr1`、`efc1`实体一致性检查。
2. 增加控制面的面积和包围盒物理签名。
3. 生成`selection_mismatch_patterns`聚合附录。
4. 给二级预检增加耗时、单元数和COMSOL server内存字段。
5. 运行`x_scale=0.6,N_w_te1=1…8`的8点资源试验。
6. 检查8点网格时间、单元数、内存和资源释放状态。
7. 试验通过后使用独立`run-id`分批完成其余64组。
8. 将5个子运行聚合为72组二级预检结果。
9. 在二级通过组合中生成正式粗扫排名和Pareto前沿。
10. 选出基准加2–4个精扫候选。
11. 后续再执行实际电极电位、`Zin2`端口定义和45 MHz精扫。

---

## 9. 当前批准的操作

- 将72个一级合格组合用于临时粗扫分析；
- 生成72组的`Ptot`、`Vave`单指标排名和Pareto候选；
- 将候选范围内的`Ptot`标记为跨`x_scale`可比较；
- 生成选择分叉模式附录；
- 增加二级网格资源监控字段；
- 执行8点网格资源试验；
- 资源试验通过后分批执行其余64组二级检查。

---

## 10. 当前暂不批准的操作

- 将`N_w_te1>=9`组合纳入主排名；
- 因全量实体编号变化而否定72个候选的`Ptot`可比性；
- 只凭实体编号变化断言物理控制面发生变化；
- 不做8点资源试验就一次性运行全部72组；
- 在当前脚本聚合逻辑未修改时，让不同参数子集共用同一`run-id`并覆盖汇总；
- 把一级通过直接等同于精扫最终候选；
- 使用旧默认Solution数据集测量当前几何面积；
- 将单元发射响应称为往返回波或阵列性能。

---

## 11. 给Harness的最终结论

> 162组一级预检已经完成并通过验收。`N_w_te1=1…8`的72组在设计、几何、选择和面积方面满足当前候选条件，可进入临时粗扫分析及二级网格检查；`N_w_te1>=9`的90组继续排除。候选72组的`intop5`实体和面积均稳定，因此`Ptot`可以跨`x_scale`比较。全量中实体编号漂移只发生在被排除的退化设计区，编号变化本身不能证明固定半球控制面改变。下一步请先生成选择分叉附录并运行`x_scale=0.6,N_w_te1=1…8`的8点网格资源试验；试验通过后采用独立`run-id`分批完成其余64组，再聚合为72组正式二级预检结果。
