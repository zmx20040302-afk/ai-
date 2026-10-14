# 记录：读取 8.31 GB 扫描模型的**已存解**，给残差定论

- 对应任务：父代理 2026-09-15 放行（读那份 8.31 GB 扫描模型的已存解）
- 执行日期：2026-09-15 14:02–15:0x（本机时区 +08:00）
- 运行目录（run_id）：`work\runs\scan-model-solution-20260915\`
- COMSOL 6.4.0.293 / MPh 1.4.0；Python `work\.venv\Scripts\python.exe`（3.12.14）
- **本轮全程不求解**：未调用 `std.run()` / `sol.run()` / `geom.run()` / `mesh.run()` / `batch.run()`
- 阈值、中止规则与判据在任何 COMSOL 动作之前落盘：`thresholds_and_plan_declared_before_load.json`（`91e30dfa5e9e565f…`，14:05）

---

## 0. 结论：落在**情形 A**，而且不是"≈"，是**机器精度级相等**

> **用户 xlsx 里 `(0.6, 4) @ 15 MHz` 的 `Ptot = 7.18100466652816e-06 W`，就是这个 8.31 GB 模型 `sol2` 已存解在该案例上的值。**
> 已存解回读 = `7.181004666528165e-06`，相对差 **7.08e-16**（双精度舍入量级）。

放大到**全网格**：1134 个（组合 × 频点）× 6 个量 = **6804 次比较全部通过严格阈值 1e-3，最大相对差 9.871e-15**
（`Ptot` 9.074e-15、`Vave` 9.871e-15、`Zin1_R/Zin2_R` 9.642e-15、`Zin1_X/Zin2_X` 9.072e-15）。

**含义（照父代理给的表落格）**：
1. **溯源成立**：用户表确实是这份模型已存解的直接导出（无额外后处理、无另一轮跑）；
2. **我方的 0.16%–2.14% 残差是「重建态 vs 已存解态」的差异**，不是模型配置差异
   —— 因为用户数据本身与已存解逐位一致，而两份 `.m` 的网格/求解器/物理配置逐行相同（父代理已查实）。

---

## 1. 用户反馈（独立来源，按 AGENTS 红线 1/4 单列）

| 项 | 内容 |
|---|---|
| `source_type` | `human_feedback` |
| 渠道 | 父代理转达用户原话（用户当下口头确认） |
| **原话（逐字）** | **「这个就是你在读取文件的解的导出文件」** |
| 指涉 | `扫描阵列Xrange(0.4,0.05,0.8).xlsx` 就是**正在被加载的那份 8.31 GB `range005` 模型的已存解的导出文件** |
| 记录时间 | 2026-09-15T14:04:13+08:00（由实现者子代理落盘） |
| 落盘位置 | `user_feedback_addendum_declared_before_load.json`（`aae8a5e09c020fe8…`，append-only；`thresholds_*.json` 已声明"不可修改"，故另立文件） |
| 影响 | 阈值**不变**；比对性质由"猜来源"变为**直接一致性检验** |

**数据 of record**：本轮数值比较一律用**冻结副本的平台入库副本** `work\reports\analysis_decision\newrange005\raw_source_table.csv`
（`777d0306c569a874…`）；冻结 xlsx 副本 `work\ai-solver\inputs\扫描阵列Xrange(0.4,0.05,0.8).xlsx`（`33ed711c8d53bf02…`）为同源。
用户附件那份（父代理实测 `4874b50d14c22188…`，与冻结副本逐格相同：11,358 个单元格 0 处差异）**本轮未读取、未引路径**。

---

## 2. 只读复制与副本校验

| 项 | 值 |
|---|---|
| 源（桌面） | `C:\Users\zmx\Desktop\b_GE_task3_2new   range（0.4，0.05，0.8）.mph` |
| 源字节 / mtime | 8,311,574,097 / 2026-09-13T15:46:21；**无 `.lock`** |
| 副本 | `work\runs\scan-model-solution-20260915\staging\b_GE_task3_2new_range_0.4_0.05_0.8.mph` |
| **副本 sha256** | **`0208017edcbcd9287928257bd8b6f65ca4ac62992ea36486012d3f4836a017de`** |
| 与父代理给定前缀 `0208017edcbcd9287928257b` | **一致**（脚本以此作为前置门禁，不一致即退出；本轮通过） |
| 桌面原件 | **零写操作**；复制后 mtime 未变（仍 2026-09-13T15:46:21） |

---

## 3. 加载：耗时、内存、中止规则

**（a）加载前门禁**（连续两次、间隔 5 s；声明阈值 `avail ≥ 14000 MB` 且 `commit ≥ 16000 MB`）

| # | 时刻 | available_physical_mb | commit_available_mb |
|---|---|---:|---:|
| 1 | 14:33:52 | 18293.4 | 20141.9 |
| 2 | 14:33:57 | 18243.5 | 20060.1 |

⇒ **pass**。

**（b）加载中**（独立采样线程；系统内存 5 s、server WS 30 s）

| 项 | 实测 |
|---|---|
| 加载耗时 | **9.55 s**（无错误） |
| 采样区间 / 样本数 | 14:34:04 – 14:34:09 / 2 |
| `available_physical_mb` | 17784.5 → **17229.3** |
| `commit_available_mb` | 19259.3 → **18544.5** |
| `comsolmphserver` WorkingSet | 最大 **318.7 MB**（加载本身是惰性/内存映射式的，文件大但加载不占内存） |
| **中止规则**（声明：`commit < 2500` 或 `avail < 1500` 即终止我方 server） | **全程未触发**（`abort=false`、`abort_action=[]`） |

**（c）全网格求值阶段的外部观测（我在运行中用 `Get-Process`/`Win32_OperatingSystem` 采样，非脚本内采样器）**：
server WS 峰值约 **4.5 GB**（14:35 实测 4500.2 MB），system `commit_available` 约 14.2–14.5 GB、`available_physical` 约 12.7–14.5 GB，
**始终远高于中止线**。

**（d）收尾**

| 项 | 实测 |
|---|---|
| `clear` / `disconnect` | true / true |
| 端口 2036 | **closed**（`port_open_after_disconnect=false`、`port_open_after_terminate=false`） |
| `comsolmphserver` | 无（`comsolmphserver_after_disconnect=[]`、`comsol_procs_final=[]`，无需强杀） |
| 收尾后 avail / commit | **18464.6 / 19914.6 MB** |
| 用户 `ComsolUI` | 期间出现过（pid 30724），仅登记，**未触碰**；全程未碰桌面原件 |

---

## 4. 枚举交付物：这个模型里到底存了什么解

（第 1 轮 `inspect_stored_solution.py` 产出；`inspect/inspect_result.json` = `89b643ac6c9474c0…`）

| 项 | 实测 |
|---|---|
| **solution 总数** | **164**（`sol1` … `sol164`） |
| **dataset** | **3** 个：`dset1`→`sol1`、`dset2`→`sol1`、`dset3`→**`sol2`**（三者 `type=Solution`、`frametype=spatial`） |
| **batch** | **1** 个：`p1`；`pname = {"x_scale", "N_w_te1"}`、`plistarr = {"range(0.4,0.05,0.8)", "range(1,18)"}` |
| **扫描解 `sol2`** | `isEmpty = false`；`getMaxLevels()=3`、`getLevels()=3`；`getLevelNames() = ["freq","N_w_te1","x_scale"]`；`getPNames = ["x_scale","N_w_te1","freq"]` |
| `sol2` 的 outer 案例 | **162** 个（`getOuterSolnum()` = 1…162），与 `p1` 的 9×18 吻合 |
| `sol2` 的 inner 案例 | **7** 个（`getSolnum(1,True)` = 1…7），= 7 个频点 |
| 其余 162 个 solution | `sol3`…`sol164`，均 `levels=1`（每案例一个单解） |

**162 组合是否真的都在里面？—— 是，且每格的 7 个频点都非空**：

| 表达式 | 第一块长度 | 非空数 | 零值数 | 逐案例 7 频点齐全 |
|---|---:|---:|---:|---|
| `freq` | 1134 | 1134 | 0 | **162/162** |
| `Ptot` | 1134 | 1134 | 0 | **162/162** |
| `Vave` | 1134 | 1134 | 0 | **162/162** |
| `real(Zin1)` / `imag(Zin1)` | 1134 | 1134 | 0 | **162/162** |

（1134 = 162 × 7；每表达式返回两块各 1134 个值，第一块为实部、第二块为虚部——`freq` 的第二块全为 0。）

---

## 5. 读取路线与两处实测坑（含 API 取证）

### 5.1 路线（不靠记忆猜 API）

| 环节 | 依据（离线核 `com.comsol.model_1.0.0.jar` **接口/基类层**，并与 MPh 1.4.0 源码交叉验证） |
|---|---|
| 取解的参数值 | `com.comsol.model.dbimodel.SolverSequence.getSolutioninfo()` → `dbimodel.SolutionInfo`；jar 内 **13 个 class** 含该符号。`SolutionInfo` 含 `getPvals` / `getPvalsImag` / `getOuterSolnum` / `getSolnum` / `getPNames` / `getMaxLevels` / `getLevels` / `getLevelNames` |
| MPh 的用法 | `mph/model.py` L391-396（`java.getSolutioninfo()`、`info.getSolnum(1,True)`、`java.getPVals()`）、L434-438（`info.getOuterSolnum()`、`info.getPvals([[index,1]])`）、L534-565（EvalGlobal：`expr`/`data`/`outersolnum` + `computeResult()` + `isComplex()`） |
| 节点访问 | 特征列表对象**不可调用**，须 `.get(tag)`（`mph/node.py` L233-236） |

### 5.2 坑 1：MPh 的数据集缓存 ⇒ `dset3` 用不了

`model.evaluate(..., dataset="dset3")` 报 `ValueError: Dataset "dset3" does not exist.`，
而 Java 侧 `java.result().dataset().tags()` 明确列出 `dset1,dset2,dset3`。
⇒ MPh 在 `load()` 时缓存了数据集名单；**绕行**：直接用 Java 侧 `result().numerical()` 建 `EvalGlobal` 节点自取（§5.1）。
（同款缓存坑此前已在 `scripts/geometry_selection_precheck.py` 里被记录过。）

### 5.3 坑 2：`num(tag)` 不可调用；数据集属性名是 `data`

- `java.result().numerical()` 返回 `NumericalFeatureListClient`，`num(TAG)` → `TypeError: ... not callable`；须 `num.get(TAG)`。
- 数据集属性：MPh 用 **`data`**，平台旧脚本写的是 `dataset`。实测**两个都试、以回读为准** ⇒ **`data` + 字符串 `"dset3"` 生效**（回读 = `dset3`），`innerinput = "all"`。

### 5.4 坑 3（v1 挂起，留档）：逐案例求值实际每次都在算全部 1134 个案例

第 2 轮（`read_stored_solution.py`）用「设 `outersolnum` 再逐案例求值」：
- `outersolnum` 的整数回读失败（`属性"outersolnum"无法转换为整数`）；
- 每次求值实际计算**全部 1134 个案例**（单次约 25 s、server WS 涨到 ~5 GB），51 次求值会拖很久，且结果转换还因返回结构是 `double[][][][2]` 而失败。

⇒ 我在 14:32 **主动终止了该作业**（只读、无副作用），核对 `port=false`、无 `comsolmphserver` 残留；
第 3 轮改为 **v2**：每个表达式**只求值一次**（`innerinput=all`），拿回整块 1134 值并**立即落盘**，再离线索引。
v1 的留痕（`read/read_events.jsonl` = `7c8178b6a4dc1094…`）与两个 0 字节 CSV 一并保留，**不覆盖、不删除**。

---

## 6. 三方对照

### 6.1 `(0.6, 4) @ 15 MHz` 焦点（任务单问的那一个数）

| 来源 | `Ptot` @ 15 MHz | 与"已存解"的相对差 | 与"用户导出"的相对差 |
|---|---|---|---|
| **已存解**（`sol2`，`dset3`，outer `solnum=76`） | **7.181004666528165e-06** | — | **7.077e-16** |
| 用户导出（冻结副本） | 7.18100466652816e-06 | 7.077e-16 | — |
| 我方重建（2026-09-15 的 0604 单次求解） | 7.031303720021646e-06 | **2.0847e-02** | 2.0847e-02 |

### 6.2 三个 `x` 的 15 MHz（`N_w_te1 = 4`，用于看清 0.4/0.6/0.8 的差别）

| `x_scale` | outer `solnum` | 已存解 `Ptot`@15MHz | 用户导出 | 相对差 |
|---:|---:|---|---|---:|
| 0.4 | 4 | 4.212652401911424e-07 | 4.21265240191142e-07 | **1.005e-15** |
| **0.6** | **76** | **7.181004666528165e-06** | **7.18100466652816e-06** | **7.077e-16** |
| 0.8 | 148 | 2.7661969980311422e-06 | 2.76619699803114e-06 | **7.655e-16** |

### 6.3 3 个组合 × 7 频点 × 6 个量 = 126 条

**126/126 `pass_target`（≤1e-3）**，最大相对差 **7.429e-15**；
分项最大：`Ptot` 2.335e-15、`Vave` 4.646e-15、`Zin1_R` 4.602e-15、`Zin1_X` 7.429e-15。
（表：`read2/stored_solution_values.csv` = `44dddea6664d349c…`、`read2/three_way_comparison.csv` = `d84417b189bebdd3…`）

### 6.4 全网格 1134 点（离线对照，`read2/fullgrid_vs_user.csv` = `f3a392c4f75c08d3…`）

| 量 | 比较点数 | 最大相对差 | 最小相对差 |
|---|---:|---:|---:|
| `Ptot (W)` | 1134 | 9.074e-15 | 0.0 |
| `Vave (m/s)` | 1134 | 9.871e-15 | 0.0 |
| `Zin1_R (Ω)` | 1134 | 9.642e-15 | 0.0 |
| `Zin1_X (Ω)` | 1134 | 9.072e-15 | 0.0 |
| `Zin2_R (Ω)` | 1134 | 9.642e-15 | 0.0 |
| `Zin2_X (Ω)` | 1134 | 9.072e-15 | 0.0 |
| **全局** | **6804** | **9.871e-15** | 0.0 |

**索引口径的独立校验**（不是假设）：`getPvals` 回读得 `(0.6,4)` 的 `outer_list_index0 = 75`，
与算式 `4×18 + (4−1) = 75` **一致**（`index_convention_check.consistent = true`）；
`freq` 数组前 7 个值 = 5/10/15/20/25/30/35 MHz ⇒ 内层频点最快；162×7 = 1134 完全覆盖。

⇒ **已存解 ≡ 用户表，逐位（≤9.87e-15，即双精度舍入量级）**。

---

## 7. 本轮没取到的量（如实登记）

| 表达式 | 结果 | 说明 |
|---|---|---|
| `real/imag(ave_outer(V))`、`real/imag(ave_inner(V))` | **失败**：`FlException`（每次 0.0–0.1 s 即返回） | 这两个是 **R0 驱动改动时在另一份工作副本上新建的变量**（`work\models\drive_change_manifest.json` 记 "created Average -> cyl8/cyl9"），**本份扫描母版里不存在**。⇒ 本轮不报这两个量 |
| `real/imag(V_center)`、`real/imag(intop3(es.JZ))`、`real/imag(intop4(es.JZ))` | 成功（各 1134 值） | 已落盘（`read2/fullgrid_*`），但用户表里没有对应列，故未参与判定 |

---

## 8. 产物清单（路径 + 字节 + sha256）

完整清单：`work\runs\scan-model-solution-20260915\manifest.json`
（30,433 B，**`ca62ef5992eb4c805d392cf4d04c0b4b575b6b0e7e711765a92ded9f25a02018`**，47 个产物）。
本报告生成于清单之后，故不在清单内；本报告 sha256 记录在 `report_pointer.json`。

| 角色 | 相对路径 | 字节 | sha256 |
|---|---|---:|---|
| 阈值/中止规则/判据声明 | `thresholds_and_plan_declared_before_load.json` | 4,190 | `91e30dfa5e9e565f563f1107e0de13fca6c1c54f14e0d6f44ca6628a032f2644` |
| 人反馈附言 | `user_feedback_addendum_declared_before_load.json` | 3,244 | `aae8a5e09c020fe82ba9ce97dd4bccafd54f9422155c644b3634f55193d58ebb` |
| **枚举结果（164 解/3 数据集/1 batch/162 案例）** | `inspect\inspect_result.json` | 267,385 | `89b643ac6c9474c0…` |
| 枚举留痕 | `inspect\inspect_events.jsonl` | 2,651 | `0f31fa2e02f90395…` |
| **全网格 1134 点 vs 用户表** | `read2\fullgrid_vs_user.csv` | 433,580 | `f3a392c4f75c08d310d292bcbdb40002a2609fd9b08404b82f919c1de6b9fdef` |
| 全网格对照汇总 | `read2\fullgrid_vs_user_summary.json` | 4,343 | `794ab3a26371dbed…` |
| 已存解取值表（3×7） | `read2\stored_solution_values.csv` | 8,027 | `44dddea6664d349c…` |
| 三方对照（126 条） | `read2\three_way_comparison.csv` | 15,906 | `d84417b189bebdd3…` |
| v2 结果（层级/索引/收尾） | `read2\read2_result.json` | 66,724 | `c2d20d4a0004b482…` |
| v2 逐事件留痕 | `read2\read2_events.jsonl` | 554,430 | `0091c18443833af6…` |
| 全网格原始数组（17 个表达式） | `read2\fullgrid_*.json` | 各 ~1.4–75 KB | 见 manifest（如 `fullgrid_Ptot.json` = `8701bd6b85634113…`） |
| v1 留痕（逐案例，未成功） | `read\read_events.jsonl` | 60,302 | `7c8178b6a4dc1094…` |
| 第 3 轮脚本（有效） | `tools\read_stored_solution_v2.py` | 26,663 | `aa2ccfddc2bd3952…` |
| 第 1 轮脚本（枚举） | `tools\inspect_stored_solution.py` | 30,065 | `b153654f3f699589…` |
| 第 2 轮脚本（v1） | `tools\read_stored_solution.py` | 26,003 | `894e421fdd333d42…` |
| 全网格离线对照脚本 | `tools\compare_fullgrid_offline.py` | 6,708 | `32601e3ef608d26a…` |
| 8.31 GB 副本 | `staging\b_GE_task3_2new_range_0.4_0.05_0.8.mph` | 8,311,574,097 | `0208017edcbcd9287928257bd8b6f65ca4ac62992ea36486012d3f4836a017de` |

只读输入（不在本 run 目录）：桌面源模型（同上哈希）、`raw_source_table.csv` `777d0306…`、冻结 xlsx 副本 `33ed711c…`、
`0604` 自算/对账表、`model_1.0.0.jar`、MPh `model.py`/`node.py`（哈希见 manifest）。

---

## 9. 证据等级、不确定度、没做到的地方

**证据等级**
- 「用户表 = 该模型已存解」：**强**（6804 次比较，最大相对差 9.87e-15；且覆盖全部 1134 点、每点非空）。
- 「残差 = 重建态 vs 已存解态」：**强**（残差不可能来自来源不明；用户数据已与已存解逐位对齐）。
- 枚举（164 解 / 162 案例 / 7 频点 / batch p1）：**强**（运行时 API 回读 + 全网格 1134 值非空）。

**不确定度 / 没做到**
1. **未**求出"为什么重建态与已存解态在 `x_scale=0.6/0.8` 上差 0.1%–2.1%、而在 `0.4` 上差 1e-12"的**机制**。
   本轮只完成了定性（残差属于重建/网格层面）。要定位机制需要一个**受控对比**（例如：以 `sol2` 已存解的网格状态为基准，
   分步替换"只重建几何 / 只重建网格 / 都重建"），且必须在**新会话**里做，本轮未获授权、未做。
2. `ave_outer(V)` / `ave_inner(V)` 在本份母版里不存在 ⇒ 这两个量本轮**没有**已存解取值。
3. 加载期采样只有 2 个样本（加载仅 9.55 s）；全网格求值阶段的内存峰值是**外部观测**（约 4.5 GB server WS），
   非脚本内采样器记录。若要严谨的"求值期内存时序"，需把采样器扩到求值阶段（脚本已具备该能力，本轮只用在加载段）。
4. 本轮**未**把 1134 点全部与"我方重建"三方对齐——我方重建只有 `(0.6,4)` 一个组合（0604 那一轮）。
   其余 1133 点的"重建态"值不存在，故"残差"只在 `(0.6,4)` 上被直接观测到（另有两个 `x` 的**端点**来自 72-grid 那轮的 `(0.4,4)/(0.8,4)`）。
5. v1 那一轮浪费了约 20 分钟机时（只读求值，无副作用），已留痕（§5.4）。
6. `sol3`…`sol164` 这 162 个单解与 `sol2` 的关系（是否为同一批案例的镜像存储）**未查**，本轮未需要。
