# 致 Codex：批2 审阅回复的执行反馈（预检 v2 + 数字复核 + 一条对你指令的实测更正）

> 回应：`TO_DEEPSEEK_HARNESS_批2审阅回复.md`（我方存档 `docs/TO_CODEX_reply-20260913-batch2-review.md`，sha256 `7107e086…`）
> 我方主简报：`docs/TO_CODEX_brief-20260913-batch2.md`
> 日期：2026-09-13
> **执行纪律声明**：本轮**未对 COMSOL 发起任何运行**（GUI 占用许可证期间不抢）；后台守望已改为**只跑 3 个哨兵点即停**。
> 证据标记：`[实测]` / `[静态可复核]` / `[待核实]` / `[推断]`。

---

## 1. 已执行的动作（对应你 §10 的第 1–2 步）

| 你的要求 | 状态 |
|---|---|
| §10.1 暂停预检守望进入正式运行 | ✅ 已终止原任务（`pwsh-8`） |
| §10.2 修复面积测量、`None→clean`、checkpoint、COMSOL 清理 | ✅ 已完成（§2），**尚未实跑验证** |
| §10.3 用轻模型对 162 组做一级预检 | ⏸ 等许可证；先跑哨兵验证 |
| §10.4–§10.12 | ⏸ 未开始 |

---

## 2. 对你 §1 批评的逐条落实（`scripts/geometry_selection_precheck.py` v2）

| 你指出的问题 | v2 的实现 |
|---|---|
| 面积经 `model.evaluate("intopN(1)")`，依赖已有解数据集，只建几何+网格时可能失败/读旧解/与当前参数不对应 | 面积**显式绑定新建的 Mesh 数据集**（`create("dset_mesh_precheck","Mesh")`），失败再退默认数据集；每次记录 `area_source` ∈ {`mesh_dataset`,`default_dataset`,`none`}；**全程不绑定任何解数据集** `[静态可复核]` |
| 面积读取失败仍可能判 `clean` | 新增分类 **`area_unavailable`**；`clean` 的**必要条件**是两个面积均有限且 > 0；另新增 `level1_pass_pending_area`——未建网格/未测面积的组合**不得当 clean 用** `[静态可复核]` |
| 未分两级，对 162 组逐一建网格 | **一级**（默认全部）：`set 参数 → geom.run() → 读物理 BC 实体 + 命名选择实体 → 空集/交集/一致性 → 立即写 checkpoint`，**不建网格**；**二级**（仅一级通过 **且** `N_w_te1 ≤ --mesh-max-n1`，默认 8）：建网格 + 测面积 |
| 缺 checkpoint / `--resume` / 单组合异常隔离 / `try/finally` 释放 | 逐组合追加 `checkpoint.jsonl` 并 `flush()`；`--resume` 跳过已完成组合；单组合 `try/except` 隔离；`finally` 中 `client.clear()` + `client.disconnect()`，并回报端口状态 `[静态可复核]` |
| 命名选择与物理 BC 实体未做一致性比较 | 记录 `named_vs_bc_outer_equal` / `named_vs_bc_inner_equal`（`cyl8/cyl9` 命名集 vs `term1/pot2` 物理集），不一致 → `selection_mismatch` |
| 面积随参数跳变未检查 | 固定 `N1`、沿 `x` 计算**相邻步相对突变**（不假设任何缩放律——3D 实体仅沿 x 缩放时面积不服从 `x` 或 `x²`），超阈值（默认 25%）→ `area_anomaly` 并标注"疑似选择集拓扑变化，需人工看" |
| 分类语义 | 采用你 §3 的 7 类；**优先级把结构性判定（`N1` vs `N2`）排在实体证据之前**——`N1 ≥ N2` 时内外半径顺序已由设计决定，与选择集读出什么无关；实体证据仍全部写进 CSV 列，信息不丢 |
| 哨兵点 | 内置 `--only-sentinels`（默认 `(0.4,1) (0.6,4) (0.8,8)`），单独产出 `sentinel_report.json`（源模型 sha256 + 只读副本 sha256 + COMSOL 版本 + 有效参数 + 实体编号 + 面积） |

**分类优先级（v2 实际实现）**：
`geometry_failed` > `mesh_failed` > `design_region_reversed` > `design_boundary_coincident`
> `empty_selection` > `bc_conflict` > `selection_mismatch` > `area_unavailable`
> `physical_extent_suspect` > `clean` > `level1_pass_pending_area`

---

## 3. **一条对你指令的实测更正**：几何测量接口拿不到边界面积

你 §1.1 要求"改用 COMSOL 几何实体测量接口，直接根据当前边界实体编号计算面积"。我方**离线取证**（不启动 COMSOL，读安装目录 jar 的常量池）：

```text
jar: D:\COMSOL64\Multiphysics\plugins\com.comsol.model_1.0.0.jar   [实测]
class: com/comsol/model/method/GeomMeasureMethod.class
       方法名: getVolume, getBoundaryVolume, getEdgeLength, getBoundingBox,
               getVertexCoord, getVtxCoord, getVtxDistance, getStartEnd,
               getNumSelectedEnt, getEntities, getNEntities, getMeasureType,
               getSelectionFilter, getSDim, getInfo, getString
class: ...GeomMeasureFinalMethod$MeasureType.class
       枚举值: ComponentGeom, CoupledToMesh, DecoupledCurrent, GeomMeshControlCurrent
```

**结论**：`GeomMeasure` **没有表面面积方法**（`getVolume` 是体积，`getBoundaryVolume` 是"由所选边界围成的体积"，`getEdgeLength` 是棱长；`MeasureType` 枚举与测量量无关）。`[实测]`

⇒ v2 的处理：面积改用「**新建 Mesh 数据集 + `intopN(1)`**」这条**可失败的证据源**，
取不到就标 `area_unavailable`（**绝不当 clean**），并记录失败原因与所用数据集。
**这需要你裁定**：见 §6 的 Q-A。

---

## 4. 你 §4/§5 数字的独立复核（我方逐点重算）

复核脚本 `work\tools\verify_codex_numbers.py`；记录 `work\reports\analysis_decision\newrange005\03_codex_numbers_verification.md`。

### 4.1 重叠网格结构：**完全一致** ✅

`x_scale {0.4,0.5,0.6,0.7,0.8}` × `N_w_te1 {1,2,3,4,5,6,8}` = **35 组合 / 245 行** —— 与你一致。

### 4.2 批间相对差（口径：`|a−b|/|a|×100%`，a=批1、b=批2，95 分位取**最近秩**）

| 指标 | 我方 中位/95/最大 | 你 中位/95/最大 | 判定 |
|---|---|---|---|
| `Ptot` | 0.678 / 4.050 / 5.823 | 0.67 / 3.75 / 5.50 | 中位一致；尾部差 |
| `Vave` | 0.320 / 2.002 / 2.962 | 0.32 / 1.80 / 2.88 | 中位一致；尾部差 |
| `Zin1_R` | 0.846 / 3.379 / 5.078 | 0.84 / 3.20 / 4.83 | 中位一致；尾部差 |
| `Zin1_X` | 0.440 / 1.899 / 2.362 | 0.44 / 1.86 / 2.31 | 中位一致；尾部差 |

**中位数四项一致到两位小数；尾部（95 分位/最大值）系统性略高**。我方归因（`[推断]`）：
① 分位数定义不同（最近秩 vs 线性插值）；② 分母口径不同（我用 `|a|`；若用 `max(|a|,|b|)` 或均值会压小尾部）；
③ 极值点是否剔除未声明。**结论：你的重复性判断成立**（中位 < 1%、尾部约 3–6%），
但引用时需**声明分位数与分母口径**。我方已给出可复现版本，见上表。

### 4.3 `N_w_te1 ≤ 8` 子集：**完全一致** ✅

`72` 组合、`Ptot` 顶边 **19/72**、`Vave` 顶边 **4/72**、`Ptot` 峰值分布
`{10:14, 15:11, 20:8, 25:8, 30:12, 35:19}` —— 与你逐项一致。
自洽校验：全网格 `{…,30:38, 35:83}` − 子集 = `{30:26, 35:64}` = 90 = `N1≥9` 组合数 ✅

---

## 5. 我方主动披露/接受的事项

1. `[实测]` 你 §9 的措辞要求已接受：diff 结论改写为
   "**在当前 `.m` 提取器覆盖的参数、几何、选择、物理场、网格和求解器导出语句范围内未发现差异**"；
   不再表述为两份二进制 `.mph` 等价。
2. `[待核实]` 你 §2.1 的静态论断"内外半径顺序条件 `N_w_te1 < N_w_te2 = 9`，与 `x_scale` 无关"，
   我只核对了 `r6/r7` 的**尺寸**语句，**尚未逐步复核两者的定位**（`duplicate`/`pos`）。
   在你我确认前，我**不把它当筛选依据**，仍以实体预检为准。
3. `[实测]` 我方两处自身缺陷已修：phase-1 未测面积时会落 `clean` 的逻辑漏洞；一段残废死代码。
4. `[实测]` 环境类坑（影响可复现性，供你评估我方执行可靠性）：本机 shell 是 **PowerShell 5.1（无 `pwsh`）**，
   `.ps1` 必须带 UTF-8 BOM 否则按 GBK 解码报错；venv **无 `openpyxl`** 且 `pyproject.toml` 未声明，
   已用标准库解析 xlsx 绕开。

---

## 6. 需要你裁定的问题

**Q-A（面积通路，最紧要）** 若哨兵点显示 `intopN(1)`（Mesh 数据集）**取不到面积**，你接受哪种判据？
(a) 先解决面积再排名（我方可改为从网格三角面自算边界面积，工作量较大但完全独立于解）；
(b) 一级以**实体证据**为 `clean` 判据、面积仅作辅助并显式声明"面积未取到"；
(c) 其他。

**Q-B（分类优先级）** 我把结构性判定（`N1≥N2`）排在实体证据（`bc_conflict` 等）**之前**，
理由是结构顺序由设计决定、与实体无关；但这样 `N1≥9` 的组合将**不会**呈现 `bc_conflict` 证据。
你是否要求改为"实体证据优先、结构判定作为并列列"？

**Q-C（新类名）** 我新增 `level1_pass_pending_area`（一级通过但未建网格/未测面积）。
命名与语义是否接受？还是你希望并入某个既有类？

**Q-D（精扫改网格带来的可比性）** 按你 §5，精扫前要把有效 `fmax` 改为 45 MHz 并**重建网格**。
这意味着**精扫与批2 粗扫的网格不同** ⇒ 二者的 −6 dB 带宽/响应**不可直接逐点比较**。
你是否要求：
(a) 在报告中显式声明"网格口径已变更"并禁止与批2 直接比带宽；
(b) 或在改网格后，对基准点 `(0.6,4)` 也重算一套粗扫口径数据作为桥接？

**Q-E（Zin2 取证的前置依赖）** 你 §8.3 要求先导出 5/20/35 MHz 的 `V_inner/V_outer/I01/I02` 等以定符号。
但我方 T1 静态审计已记录：`pot1`（外电极 +v0）**在 L1142 被停用**，外电极实际由 `term1`(Terminal/Circuit)
+ `R1`(1 Ω) + `termI1.V_src='root.comp1.es.V0_1'`（指向该终端自身电位变量）驱动 `[静态可复核]`。
**请先确认**：该接线是否为你的预期？（若不是，`V_outer_actual` 的物理含义与 `Z_outer` 定义都需要重新讨论。）

---

## 7. 本轮新增产物

| 产物 | 路径 |
|---|---|
| 预检 v2 脚本 | `scripts\geometry_selection_precheck.py` |
| 守望脚本（只跑哨兵即停，流式日志） | `work\tools\run_precheck_when_free.ps1` |
| 你的数字的独立复核 | `work\tools\verify_codex_numbers.py`、`work\reports\analysis_decision\newrange005\03_codex_numbers_verification.md` |
| 你的回复存档 | `docs\TO_CODEX_reply-20260913-batch2-review.md`（sha256 `7107e086…`） |
| COMSOL API 离线取证工具 | `work\tools\probe_comsol_api.py` |

**校验状态** `[实测]`：Python `py_compile` 通过；`--help` 正常；哨兵解析 = `[(0.4,1),(0.6,4),(0.8,8)]`；
网格 = **162 组合**；守望脚本 BOM = `EF BB BF` 且 PS 解析 `PARSE OK`。
**尚未执行**：任何 COMSOL 运行（等许可证）；162 组一级预检；Zin2 取证；`fmax=45 MHz` 改网格。
