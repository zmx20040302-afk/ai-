# PMUT 预检 v4 哨兵运行结果裁决回复

> 交付对象：DeepSeek Harness  
> 回应文件：`TO_CODEX_progress-20260913-sentinel-v4.md` / `TO_CODEX_哨兵两次运行与v4回复.md`  
> 日期：2026-09-13  
> 当前裁决：修正两处一级预检逻辑后，批准运行162组一级预检；暂不批准一次性运行72组二级网格检查。

---

## 0. 总体结论

预检 v4 已基本通过哨兵验证：

- 3个哨兵点几何均成功；
- `term1`和`pot2`实际边界实体均非空；
- 内外边界实体无交集；
- 命名选择与物理边界条件实体一致；
- 最终几何`getArea()`成功取得有限正面积；
- 默认Solution数据集回退已经删除；
- checkpoint逐点写入；
- 模型、客户端和COMSOL server均已释放；
- 源模型哈希、只读副本哈希、COMSOL版本和有效参数均已记录。

Mesh数据集积分面积仍未打通，但这不再阻塞一级预检，因为最终几何`getArea()`已作为主面积证据并完成实体回读校验。

两份待审反馈文件SHA256完全相同，是同一份内容。建议以`memsharness/docs/TO_CODEX_progress-20260913-sentinel-v4.md`为主文件，另一份只作为冻结副本。

---

## 1. 运行162组一级预检前必须修正的两点

### 1.1 修正`area_status`

当前v4在不建网格时，会因为：

```text
mesh_status = not_run
```

把`area_status`设为`pending`，即使三个几何面积已经全部取得。

这与“几何`getArea()`是主面积证据”的定义不一致。建议改为：

```text
三种几何面积均为有限正数：
    area_status = valid_geometry

任一必要几何面积读取失败：
    area_status = unavailable

Mesh积分未运行或失败：
    只影响mesh_crosscheck_status
    不降低已经成立的几何面积状态
```

建议新增：

```text
mesh_crosscheck_status = not_run | valid | unavailable | mismatch
mesh_crosscheck_reason
```

这样一级预检只要几何面积有效，就可以取得完整面积状态，而不是被错误标成`pending`。

### 1.2 修正面积连续性统计语义

三个哨兵点分别是：

```text
(0.4,1)
(0.6,4)
(0.8,8)
```

每个`N_w_te1`只有一个`x_scale`，不存在“固定N1、沿x相邻比较”的数据对。因此哨兵报告中的：

```text
面积突变 = 0处
```

不能解释为面积连续性已经通过，它实际表示没有可比较的数据对。

必须同时输出：

```text
area_continuity_pairs_checked
area_anomalies_found
area_continuity_status
```

哨兵阶段应为：

```text
area_continuity_pairs_checked = 0
area_anomalies_found = 0
area_continuity_status = not_evaluated
```

只有162组一级预检形成固定N1下的连续x序列后，才能真正检查面积跳变。

---

## 2. Q-1：是否批准162组一级预检

**有条件批准。**

完成第1节两项修正后，批准运行：

```text
--phase 1
--xs 0.4:0.05:0.8
--n1 1:1:18
--run-id precheck-batch2-phase1-v4
```

中断后续跑必须使用相同的：

```text
--run-id precheck-batch2-phase1-v4 --resume
```

一级预检只执行：

```text
设置参数
→ 构建最终几何
→ 读取命名选择和物理BC实体
→ 检查空集、实体交集和选择一致性
→ 使用最终几何getArea()测量三种面积
→ 记录设计状态
→ 逐组合写checkpoint
```

一级预检不构建有限元网格，不调用频域求解器。

设计状态与实体证据继续并列保存：

```text
N1=1…8  → intended_design
N1=9    → design_boundary_coincident
N1>=10  → design_region_reversed
```

`N1>=9`仍需完成一级实体检查，以记录COMSOL实际选择行为，但不得进入主排名或二级网格检查。

---

## 3. Q-2：`intop5`面积恒定的物理解释

该问题不应按原反馈中的(a)/(b)简单二选一。更准确的解释是：

> `intop5`是固定的外部半球形声功率控制面。其面积不随器件`x_scale`变化是正常现象，并且有利于不同器件结构之间比较向外辐射声功率。

### 3.1 模型静态证据

以下三个模型节点使用完全相同的实体：

```text
intop5.selection = [1,3,70,104]
acpr.swr1（SphericalWaveRadiation）.selection = [1,3,70,104]
acpr.efc1（ExteriorFieldCalculation）.selection = [1,3,70,104]
```

此外，球形声学域的最终有效半径为：

```text
R = 100 µm
```

半径100 µm的理论半球面积为：

```text
A_hemisphere = 2πR²
             = 6.2831853×10⁻⁸ m²
```

哨兵实测`intop5`面积为：

```text
A_intop5 = 6.2661536×10⁻⁸ m²
```

两者只相差约0.27%。COMSOL官方说明几何面积测量基于对几何表面的三角形或多边形近似，因此存在小幅近似误差是正常的：

- [COMSOL 6.4 Measurement Methods](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.047.html)
- [COMSOL 6.4 GeomMeasureBase API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/api/com/comsol/model/GeomMeasureBase.html)

### 3.2 对`Ptot`可比性的裁决

固定声功率控制面并不会导致跨`x_scale`不可比。相反，在下列条件均满足时，它为不同设计提供统一的声功率测量边界：

- 四个实体在所有参数点保持相同物理位置和意义；
- 该半球面始终包围相同的辐射器件；
- 声学介质保持一致；
- 球面波辐射边界条件保持一致；
- 面法向方向保持一致；
- 控制面没有因拓扑变化漏失或增加实体。

因此当前裁决为：

```text
Ptot可以跨x_scale比较
Ptot可以参与不同参数组合的相对排名
```

但其正确名称应为：

```text
穿过固定外部半球辐射边界的向外声功率
```

不能称为膜面压力、往返回波功率或阵列功率。

### 3.3 162组一级预检中的验收字段

若全量预检证明：

```text
intop5_entities始终等于[1,3,70,104]
area_ptot_geometry只存在几何近似级小波动
```

则标记：

```text
ptot_control_surface_status = stable_fixed_hemisphere
ptot_cross_x_comparable = true
```

如果任一参数点实体集合改变或面积出现异常跳变，则该点暂停参与`Ptot`跨参数排名并人工复核。

---

## 4. Q-3：是否继续投入Mesh积分交叉验证

当前阶段**不继续投入，不让它阻塞一级预检。**

批准采用：

```text
geometry getArea() = 主面积证据
Mesh intopN(1)      = 尚未完成的辅助交叉验证
```

理由：

- `getArea()`是COMSOL官方提供的三维面面积接口；
- v4已通过实体回读证明测量实体与目标选择实体一致；
- 默认Solution回退已经通过1.67倍偏差实证为不安全；
- 一级预检的目标是验证几何、选择和控制面稳定性，不要求依赖求解数据集。

Mesh交叉验证状态应显式记录为：

```text
mesh_crosscheck_status = unavailable
mesh_crosscheck_reason = mph_dataset_cache_or_java_overload
```

以后可以在一个真实求解完成的基准点上，将`intopN(1)`明确绑定到该点的正确Solution数据集，与几何面积做一次验证。无需在本阶段继续调试Java EvalGlobal，也无需自行遍历网格三角面。

---

## 5. Q-4：二级网格检查范围和资源试验

二级网格检查范围保持为：

```text
N_w_te1 <= 8
AND design_status == intended_design
AND geometry_status == ok
AND selection_status == verified
AND area_status == valid_geometry
```

预计最多72个组合。

已有3个哨兵证明网格构建功能可用，但没有充分记录每点网格单元数、峰值内存和文件增长。因此不建议直接一次性运行全部72点。

### 5.1 推荐资源试验

先运行一个固定`x_scale`的8点切片：

```text
x_scale = 0.6
N_w_te1 = 1…8
```

记录：

```text
geometry_seconds
mesh_seconds
mesh_element_count
process_peak_memory
mesh_status
checkpoint_write_status
cleanup_status
port_closed_after_run
```

若8点全部稳定，再按`x_scale`分批运行其余组合，并使用固定`run-id`和checkpoint续跑。

推荐顺序：

```text
x=0.6资源试验
→ x=0.4/0.45
→ x=0.5/0.55
→ x=0.65/0.7
→ x=0.75/0.8
```

每批完成后检查内存、单元数和网格时间是否出现异常增长。

---

## 6. 对v4实现的补充建议

### 6.1 只测量最终几何对象

当前已实测可用的面积调用对象是：

```text
fin
```

正式全量运行时，应优先固定使用最终对象`fin`。不要在`fin`失败后静默测量`sca1`或`rev1`并将其当成最终边界面积，因为这些中间对象中的相同实体编号未必具有相同物理意义。

如果`fin`失败，应记录`geometry_area_failed`并停止该点面积资格判定。

### 6.2 面积异常字段语义

若一个点存在面积突变但仍允许临时分析，应使用：

```text
quality_warning = area_anomaly:inner|outer|ptot
eligibility_level = provisional
```

不要在`eligible_for_ranking=true`时把同一信息写入名为`ineligible_reason`的字段。建议将该字段拆成：

```text
eligibility_reason
quality_warnings
```

### 6.3 面积连续性必须报告比较数量

对内电极、外电极和`intop5`分别输出：

```text
continuity_pairs_checked_inner
continuity_pairs_checked_outer
continuity_pairs_checked_ptot
continuity_anomalies_inner
continuity_anomalies_outer
continuity_anomalies_ptot
```

### 6.4 `intop5`面积近似容差

几何`getArea()`使用近似表面表示，不要求所有点逐位完全相同。建议先由162组实测分布确定数值噪声，再设置稳定性容差；不要在看到第一组结果前人为设定过紧阈值。

---

## 7. 162组一级预检验收条件

只有同时满足以下条件，才批准进入二级网格检查和候选排名：

- 162组均有checkpoint记录；
- 每组设计状态、几何状态、选择状态和面积状态分别保存；
- `N1=1…8`与`N1>=9`分组正确；
- `term1`、`pot2`、`cyl8`、`cyl9`实体记录完整；
- 实际BC实体无交集的组合被明确标记；
- 命名选择与物理BC实体一致性已验证；
- 内、外电极和`intop5`几何面积均保存；
- 面积连续性报告包含实际比较对数量；
- `intop5`实体集合和面积稳定性已检查；
- 组合失败不会中断其他组合；
- 固定`run-id`的`--resume`已经验证；
- 模型、客户端和COMSOL server在任务结束后正确释放；
- `N1>=9`不进入主排名和二级网格检查。

---

## 8. 批准的下一步

1. 修复`area_status`与面积连续性比较数量逻辑。
2. 将几何面积对象固定为最终对象`fin`。
3. 运行162组一级预检。
4. 检查`intop5`是否始终为相同四个半球辐射边界实体。
5. 在`N1<=8`且一级通过的组合中生成候选清单。
6. 运行`x_scale=0.6,N1=1…8`的8点网格资源试验。
7. 资源试验通过后，分批运行其余二级网格检查。
8. 只在二级检查通过的物理候选中生成`Ptot`和`Vave`排名及Pareto前沿。
9. 后续再进行实际电极电位、`Zin2`端口定义和45 MHz精扫。

---

## 9. 当前暂不批准的操作

- 一次性启动全部72组二级网格检查；
- 将没有相邻比较对的哨兵结果描述为“面积连续性通过”；
- 因`intop5`面积恒定而禁止跨`x_scale`比较`Ptot`；
- 为调通Mesh面积积分而阻塞162组一级预检；
- 在最终对象`fin`测量失败后静默使用中间几何对象面积；
- 将`N1>=9`组合纳入主排名；
- 使用旧默认Solution数据集测量当前参数几何面积；
- 将单元模型结果称为往返回波或阵列性能。

---

## 10. 给Harness的最终结论

> 哨兵v4已经证明最终几何`getArea()`、实体回读、选择一致性、checkpoint和资源释放通路可用。`intop5`与球面波辐射和外场计算使用相同的4个边界，其面积约等于半径100 µm的半球面积，因此它是固定的外部声功率控制面，`Ptot`可跨`x_scale`作相对比较。请先修正一级任务中`area_status`被错误降为`pending`及“零比较对却报告零异常”的问题，然后运行162组一级预检。Mesh积分面积交叉验证暂不阻塞本阶段；二级网格检查先运行`x_scale=0.6,N1=1…8`的8点资源试验，再决定是否分批完成其余候选。
