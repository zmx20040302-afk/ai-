# 致 DeepSeek Harness：M1 端口审计裁决与反相驱动模型搭建指令

> 日期：2026-09-13  
> 审阅对象：两份同内容的 `STATUS-20260913.md` / `STATUS-工作与问题-20260913.md`，以及 M1 原始 `port_audit.csv/json`、母版 `.m` 静态导出  
> 执行优先级：本文件取代此前“端口通过后直接进入旧候选 45 MHz 精扫”的安排

## 0. 总裁决

1. **M0 通过。** 母版 SHA256、工作副本、参数账本和不覆盖原件的纪律符合要求。
2. **M1 的停止动作正确。** 它没有完成全部电极面平均电位，但已经发现足以改变研究路线的驱动问题。
3. **纠正 P-1 的物理措辞：外电极不是“近乎浮置”。** 现有证据更支持：内电极由 `pot2 = -1 V` 单端激励；外电极通过 Circuit Terminal 接到电路节点，该节点经 `R1 = 1 Ω` 接参考节点，因此外电极为**低阻近接地/近零电位负载**，不是开路浮置。
4. 当前 1134 行结果与旧排名可保留，但只代表：

```text
legacy_drive_mode = inner_fixed_minus_v0_outer_circuit_terminal_1ohm_to_reference
```

不得再简称为“反相驱动”，也不应继续对该旧驱动做昂贵的 45 MHz 全候选精扫。
5. **批准另建反相恒压驱动分支。** 初始映射按母版被停用前的明确设置恢复：外电极 `pot1 = +vamp`，内电极 `pot2 = -vamp`，底部参考电极 `gnd1 = 0 V`。全局反号不会改变线性幅值/功率，但标签必须固定，禁止前后互换。
6. 反相分支改变了激励物理定义，**旧驱动下的 Pareto 排名和 4+1 候选不能直接继承**。新分支通过验证后，必须重新计算 72 组的 7 点粗扫并重新排名，然后才能裁定反相驱动的精扫候选。
7. 旧 `Zin1`、`Zin2` 均不参与工程判断或排名。新模型不要继续使用 `v0/I01` 这类未经端口方向验证的快捷公式。

## 1. 两份状态文件的一致性

两份状态文件 SHA256 完全相同：

```text
433427842d280eb1086094a8e3f759937599e62503197071e5f43ad006ee332a
```

因此它们是同一状态快照的两份副本，不存在内容冲突。后续可保留仓库 `docs/STATUS-20260913.md` 为主记录，工作区副本仅用于转发。

## 2. 对 M1 实测结果的重新解释

### 2.1 已经确认的事实

母版 `.m` 中可静态复核：

```text
gnd1  → cyl7
pot1  → cyl8，原设置 +v0，后在 L1142 停用
pot2  → cyl9，设置 -v0，保持启用
term1 → cyl8，TerminalType = Circuit
R1    → Connections 0–1，R = 1 Ω
termI1→ Connections 1，V_src = root.comp1.es.V0_1
```

M1 三频点又实测到：

- `es.term1.V0_ode` 只有约 3–8 µV；
- `I02` 为数 µA，`I01` 为约 0.15–1.0 mA；
- 内电极仍由 `pot2 = -1 V` 约束；
- `Zin1` 与 `Zin2` 三频点逐位相同；
- `.m` 明确写有 `Zin2 = v0/I01`，确认是复制错误。

### 2.2 为什么不能称“外电极浮置”

浮置意味着没有确定的低阻参考通路；但现模型的 `R1` 明确连接电路节点 1 与参考节点 0，阻值仅 1 Ω。端口电压接近 0 V 与这种低阻连接是一致的。准确表述应为：

> **现有模型是内电极 −1 V 单端激励，外电极通过 1 Ω 电路支路近似接参考端。**

除非后续电路节点审计推翻上述连接关系，否则所有历史报告统一使用该表述。

### 2.3 `Ptot`/`Vave` 是否作废

数值本身不作废；它们是该历史驱动工况下的有效求解结果。需要改变的是解释和用途：

- 可作为 legacy 单端/近接地工况的数据集；
- 可用于验证重跑重复性；
- 可与新反相模型做归一化对照；
- 不得作为“反相驱动设计”的 Pareto 排名；
- 不得直接决定新反相模型的精扫候选。

## 3. 对问题清单逐项裁决

| 问题 | 裁决 |
|---|---|
| P-1 驱动定性 | 采用“内电极 −1 V 单端激励，外电极经 1 Ω 近接参考端”，不采用“近乎浮置”。另建反相恒压分支。 |
| P-2 电极面电位缺失 | 不再为旧分支重复耗时补算；在新分支中建立显式 Boundary Average/Probe 后一次性验证。P-2 不阻止创建新分支，但新分支三点求解必须取得电极电位。 |
| P-3 `Zin1/Zin2` | 旧两列一并降级为 `legacy_nominal_impedance_unverified_sign`，不参与评分。新分支先保存原始端口电压/电流，再定义阻抗。 |
| P-4 旧批2表述 | 保留数据，修改 drive mode 的可读说明；排名归档为 legacy drive screening。 |
| P-5 扰动签名 | **必须补做。** 在新反相分支至少验证 `x_scale`、`N_w_te1`、`vamp`、`fmax` 的下游生效证据。 |
| P-6 网格积分交叉验证 | 暂不阻塞；保留技术债，不允许用失败的 dataset 回退值代替。 |
| P-7 45 MHz 网格 | 暂缓。先完成反相分支三点验证和反相驱动 72 组粗扫，再建立 45 MHz 精扫网格。 |
| P-8 7R 声压 | 保持原裁决：优先验证 `efc1` 外场算子，不扩大有限元域；在反相粗扫/精扫路线稳定后执行。 |
| P-9 网格收敛 | 保持要求，但对象改为新反相驱动最终候选；阈值仍为暂定工程门槛，不得称通用标准。 |
| P-10 API 读取 | 允许用 `.m` 静态文本提供表达式证据；同时记录 API 缺口，不阻塞新分支。 |
| P-11 脚本健壮性 | 下一次真实求解前必须修复 `None` 打印导致的 `exit=1` 和 docstring 转义告警，并补测试。 |
| P-12 历史子运行哈希 | 已披露状态继续接受；所有新 run 必须在 child payload 内写齐版本字段。 |
| P-13 批1与 x=1.0 | 不阻塞当前反相分支；继续冻结并登记。 |

## 4. 新模型分支的版本结构

不得在现有工作副本上直接覆盖接线。建议保留三个清楚分开的对象：

```text
母版（只读）
  C:\Users\zmx\Desktop\b_GE_task3_2new.mph
  sha256 = 0f75ca1d...9552d

旧驱动归档副本（只读归档）
  work/models/b_GE_task3_2new_legacy_1ohm_drive_v1.mph

新反相驱动工作副本
  work/models/b_GE_task3_2new_reverse_voltage_drive_v1.mph
```

新分支 manifest 必须有自己的：

```text
parent_model_sha256
working_model_sha256_before_change
working_model_sha256_after_change
drive_mode
drive_amplitude_convention
active_boundary_features
inactive_boundary_features
feature_selection_ids
change_log
script_sha256
criteria_object
criteria_hash
```

推荐的新驱动标签：

```text
drive_mode = dual_electrode_antiphase_voltage_drive
```

## 5. R0：搭建反相恒压驱动，不改其他物理定义

### 5.1 驱动参数化

定义一个无歧义参数：

```text
vamp = 1[V]
V_outer = +vamp
V_inner = -vamp
V_reference = 0[V]
Vdiff = V_outer - V_inner = 2*vamp
```

注意：这里的 `vamp` 是每个有源电极相对参考端的复幅值；差分幅值为 2 V。报告中必须同时保存 `vamp` 和 `Vdiff`，不能笼统写“驱动电压 1 V”。

### 5.2 物理节点修改

在新副本中：

1. 恢复/启用 `pot1`，选择仍为外电极 `cyl8`，设置 `+vamp`；
2. 保持 `pot2`，选择仍为内电极 `cyl9`，设置 `-vamp`；
3. 保持 `gnd1`，选择仍为参考电极 `cyl7`，设置 0 V；
4. 停用 `term1`，避免它与 `pot1` 在同一外电极边界冲突；
5. 在新 Study 中停用 `cir` 或确保 Circuit 接口不再参与该反相恒压求解；
6. 不删除 `term1/R1/termI1`，只停用并在 change log 中记录，以便审计和回退；
7. 几何、材料、结构边界、声学边界、耦合、积分面和网格暂时保持母版原状。

如果 Harness 发现 `cyl8/cyl9/cyl7` 的物理身份与上述文字不符，必须停止并输出选择截图/实体签名；不得仅凭旧编号继续。

### 5.3 边界冲突门槛

在任何求解前验证：

```text
pot1_active = true
pot2_active = true
gnd1_active = true
term1_active = false
cir_active_in_study = false
pot1_selection_nonempty = true
pot2_selection_nonempty = true
gnd1_selection_nonempty = true
pairwise_selection_overlap = 0
electrical_bc_conflict = false
```

## 6. R1：建立可计算的电极电位与电流观测量

旧的 `intop3(es.V)` 失败不能靠留空绕过。新分支应建立两个专用 Boundary Average 耦合算子，例如：

```text
ave_outer → 外电极选择 cyl8
ave_inner → 内电极选择 cyl9
```

先测试电势依赖变量的实际名称，优先顺序：

```text
ave_outer(V)
ave_inner(V)
comp1.ave_outer(V)
comp1.ave_inner(V)
```

只有模型实际支持时才使用 `es.V`，不要预先写死。若平均算子仍失败，使用电极内部点探针和边界最小/最大值交叉检查；固定电位边界上应近似满足最小值 = 最大值 = 设定复电位。

每个频点保存：

- `V_outer_complex`、`V_inner_complex`、`Vdiff_complex`；
- 每个有源电极的积分电流复数值；
- 电流积分使用的边界、法向和符号定义；
- 参考电极电流（若可取）；
- KCL 残差；
- `Ptot`、`Vave`、`V_center`。

## 7. R2：反相分支的最小求解验证

第一轮只求基准 `(0.6,4)`：

```text
freq = 5, 20, 35 MHz
vamp = 1 V
```

放行条件：

1. 三个频点全部收敛；
2. `V_outer ≈ +1 V`、`V_inner ≈ -1 V`、`Vdiff ≈ 2 V`，复相位符合设置；
3. `term1` 和电路不参与求解；
4. `Ptot >= 0`，`Vave/Ptot/V_center` 均为有限值；
5. 电极电流均能取得复数，方向有文字定义；
6. 无边界冲突、空选择或选择漂移；
7. server 正常退出，端口 2036 关闭；
8. 模型、脚本、判据和结果全部有 SHA256。

再做一个 20 MHz 线性检查：

```text
case A: vamp = 0.5 V
case B: vamp = 1.0 V
```

在线性模型中预期：`Vave` 约为 2 倍、`Ptot` 约为 4 倍。此检查用于发现驱动幅值或后处理归一化错误；容差必须根据数值结果报告，不能只写“线性通过”。

## 8. 新模型的阻抗与电功率定义

### 8.1 旧阻抗列的处理

历史数据中：

```text
Zin1 = v0/I01
Zin2 = v0/I01
```

两列都不再作为工程阻抗。旧 CSV 不必删除或改数值，但元数据改为：

```text
Zin1_status = legacy_nominal_unverified_reference_and_sign
Zin2_status = invalid_copy_expression
exclude_impedance_from_ranking = true
```

### 8.2 新反相驱动不要随意定义两个 `V/I`

该结构有外电极、内电极和公共参考电极，两个有源端口存在电耦合。在两端同时驱动时，`V_outer/I_outer` 和 `V_inner/I_inner` 只是该特定激励下的“加载端口比值”，不能自动解释为独立的 `Z11/Z22`。

本阶段先保存原始复电压、复电流，并计算总复输入功率。若确实需要严格的双端口电气模型，应另做两次独立激励：

```text
激励 A：V_outer = 1 V，V_inner = 0 V
激励 B：V_outer = 0 V，V_inner = 1 V
```

由两次求解得到 2×2 导纳矩阵，再计算反相电压向量下的电流和输入功率。未完成此步骤前，不输出“第二端口阻抗已修复”的结论。

### 8.3 不同驱动之间必须归一化

旧模型的主要激励约为 1 V 单端；新模型 `+1/-1 V` 的差分幅值是 2 V。线性系统中，仅电压倍增就可能使速度约增至 2 倍、声功率约增至 4 倍。因此比较旧/新驱动时必须同时给出：

```text
Vave_norm = Vave / abs(Vdiff)
Ptot_norm = Ptot / abs(Vdiff)^2
```

也可额外给出每个电源的总复输入功率归一化效率。不得直接用未归一化 `Ptot` 宣称反相驱动“提高了 4 倍”。

## 9. R3：新驱动必须重新粗扫，旧 4+1 候选暂时冻结

反相分支 R0–R2 通过后，先沿用原 5–35 MHz 粗网格，不立即建立 45 MHz 精扫网格。

### 9.1 小样比较

先对以下 5 组运行 5/20/35 MHz：

```text
(0.6,4)
(0.7,5)
(0.45,6)
(0.75,5)
(0.5,5)
```

目的不是确认旧候选，而是检查新驱动下响应是否稳定、候选相对关系是否明显改变。

### 9.2 72 组正式新粗扫

小样通过后，对二级预检合格的原 72 个几何组合重新求解：

```text
freq = 5, 10, 15, 20, 25, 30, 35 MHz
drive_mode = dual_electrode_antiphase_voltage_drive
```

几何资格可以引用原二级预检，但新分支仍需快速复核：

- 三个电极选择的身份、非空和互不冲突；
- `pot1/pot2/gnd1` 激活状态；
- `term1/cir` 停用状态；
- `intop5 == swr1 == efc1`；
- 模型和驱动 manifest 一致。

输出新目录，不覆盖旧粗扫：

```text
work/reports/analysis_decision/reverse_drive_coarse_ranking/
```

重新计算 `Ptot`、`Vave`、平坦度、峰值和带宽边界状态，生成新的 Pareto 和候选名单。只有新排名完成后，才重新决定“4 主 + 1 补充”是谁；旧名单只是小样种子，不是最终裁决。

## 10. R4：何时进入 45 MHz 新网格与精扫

只有满足以下条件才进入此前 M2–M6：

```text
reverse_drive_three_point_audit = pass
electrode_complex_voltage_available = true
current_direction_documented = true
electrical_bc_conflict = false
amplitude_linearity_check = pass
reverse_drive_coarse_combos = 72
reverse_drive_coarse_missing = 0
reverse_drive_ranking_complete = true
fine_sweep_candidates_reselected = true
```

之后再执行：

1. 将实际参与网格的 `fmax` 改为 45 MHz；
2. 建立 5–45 MHz @0.5 MHz 的 81 点 Study；
3. 基准哨兵与 4 个串行 chunk；
4. 旧/新网格桥接；
5. 生产网格与细一档网格抽查；
6. 新候选精扫；
7. `efc1` 外场算子 7R 声压评价。

## 11. 参数生效性补测

在反相分支上至少完成：

| 参数 | 必须证明的下游变化 |
|---|---|
| `x_scale` | 几何面积/包围盒或对应结构尺寸发生预期变化，网格统计同步变化 |
| `N_w_te1` | 内电极几何宽度/选择签名按预期变化，不产生空区或反转 |
| `vamp` | 电极复电位线性变化；`Vave` 一次比例、`Ptot` 二次比例变化 |
| `fmax` | 网格最大尺寸表达式的求值和单元统计变化，而非仅参数表数值变化 |

13 个 `unverified_or_inactive` 参数继续冻结，不进入任何扫描，直到逐项取得直接下游证据。

## 12. Harness 下一次只执行到哪里

下一轮只执行 **R0–R2**，完成后停止等待复核。不要提前运行 72 组，也不要修改 45 MHz 网格。

下一次回复必须包含：

1. 新反相驱动模型路径及修改前后 SHA256；
2. `drive_change_manifest.json` 与逐项 change log；
3. `pot1/pot2/gnd1/term1/cir` 的 active 状态和选择签名；
4. 基准 5/20/35 MHz 的电极复电位、电流、`Vdiff`、KCL 残差、`Ptot/Vave/V_center`；
5. 0.5 V 与 1 V 的 20 MHz 线性检查；
6. `x_scale`、`N_w_te1` 的最小扰动签名；
7. 修复后的脚本测试结果、退出码、日志；
8. server PID、峰值内存、退出状态和端口 2036 状态；
9. 新旧驱动物理定义的并列表；
10. 是否满足进入 R3 小样的明确判断。

失败时保留模型副本、日志和 JSON，不得用部分成功结果标记 R2 通过。

## 13. 本次复核证据

| 文件 | SHA256 |
|---|---|
| 两份相同的状态文件 | `433427842d280eb1086094a8e3f759937599e62503197071e5f43ad006ee332a` |
| `port_audit.csv` | `122766216df1e455fd7f163e2089550a188258dfd61d1f1645ad17348a295219` |
| `port_audit.json` | `437bc89459f13233434291a18230dbad3af2cc85101da2bc47467a4e91c755b3` |
| 母版 `.m` 静态导出 | `1ec837d4133cd7c9b3d79a57e293474b11f076a4b28edb240db1e5b87046a9bb` |

---

**最终执行令：保留旧数据但重标为“内电极单端 −1 V、外电极经 1 Ω 近接参考端”的 legacy 工况；另建 `dual_electrode_antiphase_voltage_drive` 分支，恢复外电极 `+vamp`、内电极 `-vamp`、参考端 0 V，并停用冲突的 Circuit Terminal。下一轮只完成新分支 R0–R2 三频点验证与线性检查。通过后先重做 72 组反相驱动粗扫和排名，再建立 45 MHz 网格并选择精扫候选。**
