---
name: model-io
description: 任意 COMSOL 模型的参数读取与修改 SOP：只读复制与哈希保护、API 读取与 .m 导出交叉校验、参数效验四分类、白名单写入与异步重算、几何类变更后的选择集复核。
---

# 模型参数读写 SOP（model-io）

## 何时使用

- 需要让 AI **读取**一个 COMSOL 模型（`.mph`）里到底有什么：参数、物理场、选择集、研究、网格；
- 需要**改动参数并重算**，或为自主寻优闭环准备"改参 → 重算 → 看响应"的能力；
- 接入一个新模型（配合 `model-onboarding` 技能使用）。

## 铁律（违反即作废）

1. **绝不猜 `.mph` 内部。** `.mph` 是专有二进制格式；读不到就如实报「需要 API 读取」或「需要导出 Model M-file」，不得依据文件名、目录名或行业惯例编造设置。
2. **原模型永远只读。** 一切操作先复制到 `work\` 暂存区；操作前后核对原件 SHA256，必须不变。GUI 打开中会有 `.mph.lock`，先复制再动。
3. **每次写入产生新副本 + 一条 append-only 记录**：参数 diff、源模型哈希、`run_id`、时间、操作者。递增命名，绝不覆盖历史副本。
4. **没有 `run_id` 的数值不进报告。** 改参必然伴随重算，证据链必须自动闭合。
5. **名字对上 ≠ 改得动。** 参数必须经过效验分类（见下）才能进入寻优空间。

## 三条读取来源与优先级

| 来源 | 内容 | 地位 |
|---|---|---|
| GUI 导出的 MATLAB Model M-file（`.m`，`File > Save As → *.m`） | 参数表、物理场属性**准确键名与枚举原文**、选择集实体编号、研究设置 | 权威**文本**来源 |
| 运行时 API 读回（Java 探针 / MPh） | 实际生效值、可扫性、求解自由度、网格统计 | 权威**运行时**来源 |
| `D:\COMSOL64\Multiphysics\data\completion\physics.xml`（COMSOL 自带 API 补全数据） | 每个物理场特征的**真实属性名、默认值、合法枚举值** | 本地权威 **schema** 来源；未列入 `values` 的枚举一律不合法 |
| `.mph` 二进制本身 | —— | **禁止直接解析** |

**两个来源不一致时：列出差异并上报，不合并、不取平均、不选一个当作对的。**

## 标准步骤

1. **锁检查** → 只读复制到 `work\models\<name>-<时间戳>\` → 记录源路径与 SHA256。
2. `probe_model()` 读取：参数表（名称/表达式/描述/数值）、物理场接口与特征标签、命名选择集与实体编号、研究/求解器标签、网格统计、COMSOL 版本。
3. 若有 `.m` 导出：`parse_matlab_export()` 解析成结构化 spec。
4. `cross_check(spec, probe)` 交叉校验，差异写入报告。
5. **参数分类**：可扫 / 惰性 / 几何类 / 保留名冲突（判据见下）。
6. `set_parameters()` 只改**白名单内**参数 → 新副本 → 提交异步求解（`sim_submit`，禁止同步等待求解）。
7. `effect_audit()` 逐参数给出分类与**证据行**（改了哪个参数、输出变化多少、run_id）。
8. **几何类参数变更后必须重新核对全部选择集**，核对结果留档；选择集失效会让结果静默错误。

## 效验四分类

| 分类 | 判据 | 后果 |
|---|---|---|
| `effective` | 改动使目标输出显著变化（超过 `EFFECT_TOL`） | 进入寻优空间 |
| `inert` | 改了输出不变（例：稳态下的热容、未被研究的载荷通道） | 剔除并记录理由 |
| `geometry_changing` | 改动导致几何重建 | 必须重新核对选择集；几何变更要人工批准 |
| `rejected_reserved` | 命中内建变量或材料别名 | 直接拒绝，**不许试错** |

## 保留名黑名单（均为实测踩坑，不是推测）

- `h` —— COMSOL 内建**网格尺寸**变量，用作全局参数会编译失败：
  `Duplicate variable name - Variable: h - Global scope`；
- `E` / `nu` / `rho` —— **材料属性自身的别名**，用作参数名会让材料读到自己：
  `Undefined variable comp1.mat1.def.E ... Defined as comp1.mat1.def.E`；
- `T` / `k` —— 温度与热导率的常规内建名，同样需避开。

处置方式：**内部名加后缀**（`h_beam` / `E_young` / `nu_pois` / `rho_beam`），**外部任务参数名保持不变**，避免破坏既有合同与数据。

## 人工复核门（智能体不得自行越过）

1. **参数白名单**：哪些参数允许改、范围与单位（授权动作，必须人给）；
2. **保留名/冲突处置**：改名方案确认；
3. **效验分类结果**：说某参数"惰性"必须附证据行，不接受一句结论；
4. **几何类参数变更**：改前核对选择集、改后复核，结果给人看；
5. **模型状态晋升**：`draft → approved_for_use` 只能人工放行，智能体不得把"待验证"说成"已验证"。

## 已知实测坑（直接复用，勿重复试错）

- **中文路径**：凡要启动 JVM / 交给 Java 的工具，必须经 ASCII 交汇点 `C:\Users\18161\memsharness_work\repo` 启动解释器，否则 `UnsatisfiedLinkError: D:\: Can't find dependent libraries`。
- **批处理暴露的 `PhysicsFeature` 没有 `getEnum()`**（`cannot find symbol`），枚举值要另找来源（GUI 原文或 `.m` 导出）。
- **2D 边界载荷没有 `Fy` 属性**；向量属性 `F` 要求**长度 3**（`A vector of length X expected#3`）。
- **属性名不可猜**：先用 `feature.properties()` 打印真实属性清单再设值。
- **数值结果节点必须显式绑定 dataset**，否则求解成功却读到 NaN；`Max/Av/Int` 作用在 `Surface` 上还需要显式选择集。
- **生成的 Java 源码必须全 ASCII**（含注释），否则 `UnicodeEncodeError`；模板层有守卫会直接拦下。
- **`comsolbatch` 下 Java 侧不能读写自己的工作文件**：用"跑完写哨兵文件"传递结果的方案会失败（实测），必须改用 **stdout 单行标记**。
- **`comsolcompile` 会在 `.class` 看起来较新时跳过重编译**：改了 `.java` 却没重编，会拿到旧行为（实测）。生成脚本应**先强制删除旧 `.class`** 再编译。
- **结果目录里的边界/选择集读数只证明"这次运行"**：几何或网格变更后必须重跑探针复核，不能沿用旧读数（技能第 8 步）。
- **枚举赋值失败会被静默吞掉，必须回读**：实测 `set("forceType", "Pressure")` 抛异常被 `catch` 吞掉，`forceType` 停留默认 `ForceArea`，而该模式下 `pressure` 属性**不生效** → 载荷为零、位移恒为 0。合法枚举值查 `physics.xml`：Solid Mechanics 边界载荷的压力选项是 **`FollowerPressure`**（**不存在 `"Pressure"`**）。设完必须 `getString()` 回读，**回读值才是事实**。

## 产物与落点

| 内容 | 位置 |
|---|---|
| 模型暂存副本与探针产物 | `work\models\<name>-<时间戳>\` |
| 求解运行目录（含探针 stdout） | `work\runs\<run_id>\` |
| 参数读写与效验记录 | `work\store\mems.duckdb`（append-only） |
| 代码 | `src\memsharness\modelio.py` |
