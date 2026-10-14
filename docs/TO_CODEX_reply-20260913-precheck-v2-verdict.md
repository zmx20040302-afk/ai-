# PMUT 批2预检 v2 执行反馈裁决回复

> 交付对象：DeepSeek Harness  
> 回应文件：`TO_CODEX_progress-20260913-precheck-v2.md` / `TO_CODEX_预检v2执行反馈.md`  
> 日期：2026-09-13  
> 当前阶段：仅批准修正预检程序并运行3个哨兵点；尚未批准162组二级网格预检或频域精扫。

---

## 0. 总体裁决

预检 v2 的总体改造方向正确，以下工作予以认可：

- 原162组自动预检任务已经停止；
- 后台守望改为只运行3个哨兵点；
- 一级几何/选择检查与二级网格/面积检查已经分离；
- 面积不可用时不再误判为`clean`；
- 已增加checkpoint、`--resume`、单组合异常隔离和资源清理；
- 已增加命名选择与物理边界条件实体的一致性检查；
- 批间重叠数据和`N_w_te1<=8`子集统计已得到独立复核。

但是，v2在正式运行前仍需修正面积通路、分类结构和若干实现问题。当前不应直接进入162组全量二级预检。

两份反馈文件SHA256完全相同，是同一份内容。建议以`memsharness/docs/TO_CODEX_progress-20260913-precheck-v2.md`为主文件，另一份只作为冻结副本。

---

## 1. 内外电极设计顺序确认

`N_w_te1 < N_w_te2=9`可以确认作为当前模型的设计顺序条件。

模型静态定义显示：

```text
r6.size = N_w_te1*W_min
r7 = duplicate(r6)
r7.size = N_w_te2*W_min
r6.pos = 同一原点
r7.pos = 同一原点
rev1.input = wp1（包含r6/r7）
sca1.input = rev1
sca1.anisotropic = {x_scale,1,1}
```

因此`r6`、`r7`以相同原点生成、一起旋转，并一起经过`x_scale`缩放。`x_scale`不会改变两者的半径先后顺序。

当前参数下的设计分类为：

| `N_w_te1` | 设计含义 | 排名资格 |
|---|---|---|
| 1–8 | 正常双电极设计范围 | 通过实体预检后可参加 |
| 9 | 内外设计边界重合，零间隔/退化 | 不参加主排名 |
| 10 | 内区超过外环起点并达到膜边缘 | 不参加主排名 |
| 11–18 | 内外区域顺序反转且尺寸超过膜 | 不参加主排名 |

实体预检仍然需要执行，因为它用于验证COMSOL最终生成的拓扑、选择实体和边界条件，而不是替代设计顺序判断。

---

## 2. Q-A：面积通路裁决

采用方案(c)：**使用COMSOL官方最终几何测量接口作为主面积证据，Mesh数据集积分只作交叉验证。**

### 2.1 对“GeomMeasure没有面积方法”的更正

仅检查`GeomMeasureMethod.class`的常量池不能证明整个API没有面积方法，因为面积方法定义在其父接口`GeomMeasureBase`中，并由`GeomMeasure`和`GeomMeasureFinal`继承。

COMSOL 6.4官方API明确提供：

```text
getArea()          计算所选三维面或二维域的面积
getVolume()        根据所选实体维度返回体积、面积或长度
getBoundaryVolume() 返回所选实体边界的面积或长度
```

官方参考：

- [COMSOL 6.4 Measurement Methods](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.047.html)
- [COMSOL 6.4 GeomMeasureBase API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/api/com/comsol/model/GeomMeasureBase.html)
- [COMSOL 6.4 Using Selections](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/application_programming_guide.15.74.html)

COMSOL 6.4中，`geom.measureFinal()`已被标记为弃用，优先使用组件或网格的测量接口：

- [COMSOL 6.4 GeomSequence API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/api/com/comsol/model/GeomSequence.html)

### 2.2 建议实现

对最终几何中的边界实体，哨兵阶段尝试等效于以下Java逻辑：

```java
measure = comp.measure();
measure.selection().init(2);
measure.selection().set(boundaryEntityIds);
area = measure.getArea();
```

若MPh包装层没有直接暴露该调用，应通过`model.java`对象调用。

### 2.3 面积证据优先级

建议记录两套面积：

1. `geometry_measure/getArea()`：主证据；
2. Mesh数据集上的`intopN(1)`：交叉验证。

必须删除`default_dataset`回退。若Mesh数据集计算失败后调用无指定数据集的`model.evaluate()`，仍有可能使用模型中保存的默认Solution数据集，与“全程不绑定旧解”的声明矛盾。

建议字段：

```text
area_outer_geometry
area_inner_geometry
area_ptot_geometry
area_outer_mesh_integral
area_inner_mesh_integral
area_ptot_mesh_integral
area_outer_relative_difference
area_inner_relative_difference
area_ptot_relative_difference
area_geometry_error
area_mesh_error
```

如果几何测量成功、Mesh积分失败，可以用几何面积作为主要判据。如果两种方法均失败，则标记：

```text
area_unavailable
```

暂不需要自行遍历网格三角形计算面积。

---

## 3. Q-B：分类优先级裁决

要求改成**并列证据列**，不要把所有意义压缩为一个按优先级覆盖的`classification`。

当前优先级会导致`N1>=9`组合只显示`design_region_reversed`或`design_boundary_coincident`，从而隐藏`bc_conflict`、`empty_selection`等重要实测结果。即使原始实体字段仍被保存，下游只读取`classification`时仍可能丢失证据。

建议拆分为：

```text
design_status
geometry_status
selection_status
area_status
mesh_status
eligible_for_ranking
eligibility_level
ineligible_reason
```

示例：

```text
design_status       = design_region_reversed
geometry_status     = ok
selection_status    = bc_conflict
area_status         = not_run
mesh_status         = not_run
eligible_for_ranking = false
```

最终资格逻辑建议为：

```text
eligible_for_ranking =
    design_status == intended_design
    AND geometry_status == ok
    AND selection_status == verified
    AND area_status IN {valid, pending_with_disclosure}
```

其中`N1>=9`仍运行一级几何和选择检查并保存证据，但不进入二级网格和最终排名。

---

## 4. Q-C：`level1_pass_pending_area`命名

语义基本可以接受，但建议改名为：

```text
selection_verified_area_pending
```

原名称中的`pass`容易被下游误解成已经通过全部预检。

如果采用并列状态列，则无需把它作为总分类：

```text
geometry_status = ok
selection_status = verified
area_status = pending
eligibility_level = provisional
```

这种组合可用于临时粗扫分析，但不能标为最终`clean`。

---

## 5. Q-D：精扫改网格后的可比性

采用方案(b)，同时执行方案(a)的披露要求：

- 所有精扫候选统一使用按45 MHz设计的新网格；
- 基准点`(x_scale=0.6,N_w_te1=4)`必须在新网格下重算；
- 报告明确标注粗扫与精扫使用不同网格；
- 不把旧粗扫和新精扫曲线直接拼接后计算带宽。

基准精扫的频率网格：

```text
range(5[MHz],0.5[MHz],45[MHz])
```

该网格本身包含旧粗扫的5、10、15、20、25、30、35 MHz频点。因此不需要额外再执行一套七频点基准任务。直接提取新精扫在这些共同频率上的结果，与旧粗扫基准逐点比较，即可建立网格桥接。

建议输出：

```text
mesh_bridge_baseline.csv
```

字段至少包括：

```text
freq
metric
old_mesh_value
new_mesh_value
relative_difference
old_mesh_version
new_mesh_version
```

最终候选之间可以直接比较，因为它们全部使用同一45 MHz网格。旧粗扫只用于趋势筛选和网格桥接，不与新精扫数据混合计算最终带宽。

---

## 6. Q-E：外电极接线与`Zin2`

当前接线不能视为文献中的标准反向驱动，应暂时命名为：

```text
drive_mode = circuit_terminal_1ohm_current_model
```

静态代码无法证明外电极实际保持`+1 V`，特别是其电源表达式指向终端自身电位变量。因此，当前Circuit Terminal接线不是用于文献对照的已确认基准。

### 6.1 当前模型的处理

1. 不立即删除或覆盖当前接线；
2. 先读取5、20、35 MHz的实际复电位和电流；
3. 检查两电极是否接近1 V幅值、180°相差及2 V差分；
4. 将当前接线作为独立电路负载工况保存；
5. 在实际端口电压确认前，不将`v0/I02`称为外电极真实输入阻抗。

需要导出：

```text
V_inner_complex
V_outer_complex
I01
I02
V_outer/I02
-V_outer/I02
V_outer-V_inner
```

### 6.2 文献反向驱动基准

为文献复现建立独立模型版本：

```text
inner electrode = +1 V
outer electrode = -1 V
bottom/reference electrode = 0 V
```

也可以整体反号，但必须保持两驱动电极相差2 V且相位相反。当前电路负载工况和显式反向驱动工况不得混合排名。

---

## 7. 数字复核裁决

认可Harness的独立复核结果：

- 精确重叠为35组合、245行；
- `N_w_te1<=8`为72组合；
- `Ptot`峰值在35 MHz为19/72；
- `Vave`峰值在35 MHz为4/72；
- `Ptot`峰值分布为`{10:14,15:11,20:8,25:8,30:12,35:19}`。

批间相对误差尾部的差异来自分母定义和分位数方法不同，不构成数据冲突。

正式报告必须声明计算口径。例如：

```text
relative_error = |batch1-batch2|/|batch1|
percentile_method = nearest_rank
```

若希望批1和批2的地位对称，可额外报告：

```text
symmetric_relative_error =
    2*|batch1-batch2|/(|batch1|+|batch2|)
```

两种相对误差口径不得混在同一统计列中。

---

## 8. v2脚本正式运行前必须修正的实现问题

### 8.1 删除默认Solution回退

当前`area_of()`在Mesh数据集失败后仍会调用无指定数据集的`model.evaluate()`。必须删除该回退，或先证明默认数据集类型为当前Mesh而不是Solution。

### 8.2 分别记录三种面积来源

不能只保存外电极的一个`area_source`。应分别记录：

```text
area_outer_source
area_inner_source
area_ptot_source
```

### 8.3 修正单位字段

`fnum("4.2[um]")`返回的是数值`4.2`，不是SI制的`4.2e-6 m`。因此当前字段：

```text
W_min_m
R_mem_m
```

命名不正确。应选择以下一种方案：

- 保存原始表达式和单位；
- 通过COMSOL带单位求值为SI制；
- 将字段改名为`W_min_raw_value`、`R_mem_raw_value`，避免声称单位是米。

当前设计关系比较仍成立，因为`N1*W_min`和`R_mem=N_mem*W_min`使用同一单位，但溯源字段必须改正。

### 8.4 面积异常应定位到具体区间

当前代码发现一个相邻`x_scale`面积突变后，会把同一`N1`下的所有`clean`点都改成`area_anomaly`。应只标记发生突变的两个端点或对应区间，并记录：

```text
anomaly_from_x
anomaly_to_x
relative_step
affected_rows
```

### 8.5 检查全部面积

面积连续性检查不能只覆盖内电极，还应分别检查：

```text
area_inner
area_outer
area_ptot
```

特别是`area_ptot`用于判断固定实体编号是否随参数失去相同物理意义。

### 8.6 固定续跑ID

全量任务使用`--resume`时必须同时传入同一个`--run-id`。否则脚本每次创建新的run目录，无法读取上一次的`checkpoint.jsonl`。

### 8.7 多轴状态替代总分类覆盖

`physical_extent_suspect`不能被`design_region_reversed`永久遮蔽。采用第3节的并列状态列后，可以同时保存两条证据。

---

## 9. 哨兵验收标准

3个哨兵点：

```text
(0.4,1)
(0.6,4)
(0.8,8)
```

只有同时满足以下条件，才批准162组一级预检：

- 三点几何均成功；
- `term1`、`pot2`实际边界实体均非空；
- 内外边界实体无交集；
- 命名选择和物理边界条件实体一致；
- `comp.measure().getArea()`能够取得有限正面积；
- Mesh积分若成功，与几何面积不存在不可解释的大偏差；
- 面积来源和错误字段分别记录；
- checkpoint在每个点完成后立即写入；
- COMSOL模型和许可证被正确释放；
- 日志实时可读；
- 哨兵报告包含源模型哈希、只读副本哈希、COMSOL版本和最终有效参数。

如果几何面积成功而Mesh积分失败，可继续162组一级预检；如果两条面积通路均失败，只允许一级实体检查，不得把结果标为最终`clean`。

---

## 10. 批准的下一步执行顺序

1. 修复第8节所列v2剩余问题。
2. 保持后台守望只运行3个哨兵点。
3. 优先验证`comp.measure().getArea()`几何面积通路。
4. 用Mesh积分面积做交叉验证，不回退默认Solution数据集。
5. 哨兵通过后运行162组一级几何和选择预检。
6. 将设计状态、实体状态、面积状态和排名资格分列保存。
7. 只对`N_w_te1<=8`且一级通过的组合运行二级网格检查。
8. 在通过预检的72组候选范围内生成粗扫排名和Pareto前沿。
9. 读取当前Circuit工况的实际内外电极复电位和电流。
10. 建立独立的显式反向驱动文献基准。
11. 把有效`fmax`改为45 MHz并重建统一精扫网格。
12. 对基准和最终候选执行5–45 MHz、0.5 MHz精扫。
13. 使用精扫基准中与旧粗扫重合的7个频点建立网格桥接报告。
14. 对最终候选补算7R轴向声压响应。

---

## 11. 当前暂不批准的操作

- 直接运行162组二级网格和面积预检；
- 将`N_w_te1>=9`组合纳入主排名；
- 使用默认Solution数据集计算几何面积；
- 将面积不可用的组合标记为`clean`；
- 只保留一个覆盖所有信息的优先级总分类；
- 直接将`Zin2`改为`v0/I02`并宣布物理定义正确；
- 把当前Circuit Terminal工况称为文献反向驱动；
- 混合粗扫旧网格和精扫新网格计算最终带宽；
- 在45 MHz精扫中继续使用按35 MHz设计且未经收敛验证的网格。

---

## 12. 给Harness的最终结论

> 预检v2的总体架构已经接近可用，但面积API的离线判断存在遗漏：`getArea()`由`GeomMeasureBase`提供并被最终几何测量接口继承。请先将最终几何`getArea()`设为主面积通路，移除默认Solution回退，并把设计、几何、选择、面积和排名资格拆成并列状态。完成这些修正后仅运行3个哨兵；哨兵通过后再执行162组一级预检，并只对`N_w_te1<=8`且一级通过的组合执行二级网格检查和后续排名。
