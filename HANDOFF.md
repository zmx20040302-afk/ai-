# MEMSHARNESS 交接说明（当前工作机）

> 更新时间：2026-09-11 ｜ 仓库根：`C:\Users\zmx\Desktop\memsharness` ｜ git HEAD：`e31ccc7`（25 提交）
> 阶段：**P2 仿真内核**（模型参数读写层已就绪，目标器件已接入但未求解）
> 旧机（`D:\桌面\memsharness`）的交接原文已归档为 `work/reports/HANDOFF-旧机版-归档-20260911.md`。
> **本机环境事实的权威版本是 `AGENTS.md` 第 3 节**，本文只做上手引导。

## 0. 这是什么

MEMS 仿真自动化平台：`人给一句需求 → 平台自动跑 COMSOL → 生成/扩充数据 → 训练 AI 求解器与代理模型 → 用实验/文献/人反馈持续增强 → 最终在不调用 COMSOL 的前提下完成求解`。
COMSOL 的定位是**教师 + 验证器 + 兜底裁判**。设计与红线见 `WORKING_PLAN.md` 与 `AGENTS.md`（后者是最高优先级工作约定，**上手第一件事就是读它**）。

## 1. 本机 30 秒上手

本机运行环境**已装好并验证过**（2026-09-11 恢复），以下命令可直接复现：

```powershell
$ws = "C:\Users\zmx\Desktop\memsharness"
$vpy = "$ws\work\.venv\Scripts\python.exe"

# 运行环境变量（编码、临时目录、matplotlib 缓存都要落在工作区内）
$env:TMP = "$ws\work\tmp"; $env:TEMP = $env:TMP
$env:MPLCONFIGDIR = "$ws\work\.mplconfig"
$env:PYTHONIOENCODING = "utf-8"

# 1) 自检（不需要 COMSOL）——期望 240 passed, 4 skipped
& $vpy -m pytest -q

# 2) 环境事实探测（COMSOL 路径/版本/授权/mphserver/MATLAB）
& $vpy -m memsharness.env          # 会写 work/reports/env_report.json
#    不想覆盖历史报告时：$env:MEMS_WORK_ROOT="$ws\work\recovery-env"

# 3) 解析数据工厂自基准（不需要 COMSOL）——期望 16/16
& $vpy scripts\generate_analytic.py --benchmark

# 4) 训练代理模型（**必须指定器件族**，否则有效样本归零）
& $vpy scripts\train_surrogate.py --fidelity F2 --family GF-heat-slab-2d

# 5) 生成报告（图 + 证据表）
& $vpy scripts\make_report.py --prefix my-demo

# 6) 真实模型只读探针（需要 COMSOL，见下节的文件策略要求）
& $vpy scripts\modelio_probe_real.py "C:\Users\zmx\Desktop\b_GE_task3_2-new.mph"
```

**四条硬性前提（本机实测，别踩）**：

1. **COMSOL 步骤必须在放宽的文件策略下跑。** 受限策略下 `comsolcompile`/`comsolbatch` 统一
   **rc=15、无输出、无产物**（连最小 `Hello.java` 都失败），三种用户目录重定向均无效。
2. `TMP/TEMP` 指向 `work\tmp`、`MPLCONFIGDIR` 指向 `work\.mplconfig`，否则 matplotlib 与 pip 会去写受限位置。
3. 中文输出设 `PYTHONIOENCODING=utf-8`，否则控制台乱码（文件内容本身没问题）。
4. 本机**未装 uv**；venv 用系统解释器 `python -m venv` 建（仓库路径为纯 ASCII，不存在旧机的中文路径问题）。

**DSH 集成（MEMS 模式）**：预设装在**用户级目录** `C:\Users\zmx\.dsh\.agent-presets\mems\`，MCP 条目在
`C:\Users\zmx\.dsh\profiles\web\cordis.patch.yml`。两者都在 **DSH 启动时装载**，且 **agent preset 在会话创建时锁定** →
装完必须**重启 DSH 并新建会话**才会看到「MEMS 模式」与 `mcp__mems__*` 工具。重装/校验：

```powershell
& $vpy scripts\install_mems_preset.py --dry-run   # 只生成到 work/dsh-install 并校验
& $vpy scripts\install_mems_preset.py             # 真正写入 ~/.dsh（含 MCP 补丁；会先备份）
& $vpy scripts\verify_mems_install.py             # 回读校验
```

## 2. 仓库结构（找东西用）

| 路径 | 内容 |
|---|---|
| `WORKING_PLAN.md` | 设计与计划（P0–P7、门禁、KPI、风险、决策点）；第 13 节含**机器迁移后的实测修正** |
| `AGENTS.md` | **红线 + 本机环境事实**（最高优先级约定） |
| `docs/` | `REQUIREMENTS.md`、`PROJECT_BRIEF.md`、`P0_acceptance.md`、`dsh_mcp_registration.md` |
| `src/memsharness/` | 平台代码：`comsol/`（队列、后端、诊断、Java 模型）、`store.py`、`onboard.py`、`pod.py`、`analytic.py`、`dataset.py`、`report.py`、`modelio.py`、`ml/`、`mcp_server.py`、`env.py`、`paths.py` |
| `tests/` | 244 项（4 项真起 COMSOL，默认 skip） |
| `scripts/` | 运维/一次性脚本（onboarding、扫描、训练、报告、probe、DSH 预设安装） |
| `.dsh/skills/` | 8 个 SOP 技能（`comsol-modeling-sop`、`model-io`、`model-onboarding`、`ai-solver-verification`、`autonomous-optimization-loop`、`dataset-contract`、`field-io-contract`、`report-and-evidence`） |
| `work/` | 运行区（**不进 git**）：`runs/`、`devices/`、`models/`、`reports/`、`store/`、`exports/` |

## 3. 本机环境事实（摘要，权威见 `AGENTS.md` 第 3 节）

| 项 | 值 |
|---|---|
| Python | `work\.venv\Scripts\python.exe`，3.12.14；依赖含 numpy 2.5.3 / scipy 1.18.1 / pandas 3.0.5 / scikit-learn 1.9.1 / matplotlib 3.11.1 / duckdb 1.5.5 / pyarrow 25.0.1 / pint 0.26.1 / fastmcp 4.0.3 / pytest 9.1.1 / **MPh 1.4.0 + JPype1 1.7.1** |
| COMSOL | `D:\COMSOL64\Multiphysics`（**6.4.0.293**）；另装有 6.2（`D:\COMSOL62`） |
| mphserver | `127.0.0.1:2036`；**默认不常驻**，用前显式启动并探测端口 |
| MATLAB | `D:\matlab\bin\matlab.exe`（**R2023b**）；另有 `D:\Matlab2023b`；LiveLink `D:\COMSOL64\Multiphysics\mli` |
| COMSOL API schema | `D:\COMSOL64\Multiphysics\data\completion\physics.xml`（1750 特征 / 7239 变体 / 16886 枚举属性） |
| 硬件 | 24 逻辑核；空闲内存 ≈22.5 GB；**GPU RTX 5070 Laptop 12 GB**（旧文档的 RTX 3060 6 GB 是旧机） |
| DSH | GUI `http://127.0.0.1:3080`；MEMS 预设与 MCP 补丁路径见上节 |

## 4. 目标器件（用户 2026-09-11 确认）

| 文件 | 大小 | 用途 |
|---|---|---|
| `C:\Users\zmx\Desktop\b_GE_task3_2-new.mph` | 98.9 MB | **目标器件**（已只读 probe） |
| `C:\Users\zmx\Desktop\b_GE_task3_2-new  n7.mph` | 528 MB | 参数化扫描用 |
| `C:\Users\zmx\Desktop\b_GE_task3_2-newyizu.mph` | 4.25 GB | 参数化扫描用 |

**只读 probe 实测**（`work/reports/modelio/probe-probe-20260911T153110Z-75135037.json`，源 SHA256 `3efa34cc…`，原件未改动）：

- COMSOL 6.4(293)；**37 个参数**（`h_device=4.2µm`、`N_mem=10`、`R_mem=42µm`、`f_min=4MHz`、`f_max=40MHz`、`fmax=35MHz`、`v0=1V`、`V_te1=1V`、`V_te2=-1V`、`V_be1=0V`、`c_water=1481m/s`）
- 几何：3D，83 顶点 / 217 边 / 152 边界 / **16 域**
- 4 个物理场接口 `acpr`（压力声学）/ `solid`（含 `pzm1` 压电材料）/ `es`（静电）/ `cir`（电路）+ **19 个命名选择集**
- 研究 `std1` = `param` + `param2` + `freq`（**频域**）；3 个求解器 `sol1..sol3`
- **mesh 未构建**（0 单元）→ 包围盒为空；`work/runs` 里也**没有任何 `.mph`**
- 40 项属性回读中 4 项不可读，全是接触对 `pairs`（`Value_has_length_zero`）

## 5. 当前进度

**已完成（本机实测）**：git 历史恢复（25 提交，工作区与 `e31ccc7` 一致）；运行环境恢复（venv + 依赖，含 MPh）；
**自检 240 passed / 4 skipped**；环境探测；解析工厂自基准 **16/16**；训练管线复现（`mdl-20260911-906f5e`，draft，
17 样本 / 13 训练 / 4 测试，`T_max_K` R²=0.9709，**切分退化为随机 → 指标偏乐观**）；报告管线（3 图 + 12 行证据表 + 6 条声明）；
溯源库核对；目标器件只读 probe；**MEMS 模式已安装（待重启 DSH 生效）**。

**未开工 / 待推进**：

1. **基线求解**目标器件（未做；旧机 PMUT 参考：7 频点 ≈347 s、峰值内存 8.84 GB，本机需实测）
2. **参数效验第一/二轮**（哪些参数真起作用；需重核 19 个选择集）
3. **`device_spec` 草稿**（`scripts\onboard_model.py`，把 probe 结果接进声明式配置）
4. **mphserver + MPh 路线**未端到端跑通（MPh 已装，服务未起）
5. **4 个 COMSOL 用例**仍 skip：需 `MEMSHARNESS_RUN_COMSOL_TESTS=1`，且它们要找 `work/runs` 下的真实 `.mph`
   ——即使复制进去，该模型 **mesh 未构建**，包围盒断言大概率失败（需先建网格）
6. **场级 POD / AI 代理**（`scripts\pod_from_runs.py`）无法复现：需要真实解的 `out.mph`，本机 `work/runs` 里没有
7. **跨族泛化未验证**（训练数据单族 → `random_degraded`），数据集报告里 `cross_family_holdout=false` 必须继续如实标注
8. `evidence`/`experiment`/`feedback` 三张表**全空** → 文献/实验/人反馈来源尚未接入
9. `remote` 算力后端未实现（当前只有 `local`）

## 6. 证据索引（本机产出，均在 `work/`）

| 文件 | 里面是什么 |
|---|---|
| `work/store/mems.duckdb` | 溯源库：12 表；`run` 94、`design` 494（analytic 400 + simulation 94）、`sample` 472（F0 423 / F2 49）、`validation` 11 |
| `work/store/mems.duckdb.bak-20260911T204148Z` | 本机首次写库前的快照 |
| `work/reports/modelio/probe-probe-20260911T153110Z-75135037.json` | 目标器件只读 probe 全量证据 |
| `work/reports/modelio/probe-probe-20260911T150820Z-e3599a99.json` | **失败**的 probe 记录（受限策略下 rc=15），保留为环境事实证据 |
| `work/reports/recovery-demo/report.md` | 修复后重新生成的平台报告（3 图 + 证据表 + 声明） |
| `work/recovery-env/reports/env_report.json` | 本机环境探测报告（刻意写在独立 work root，未覆盖历史） |
| `work/reports/HANDOFF-旧机版-归档-20260911.md` | 旧机交接文档归档（SHA256 `499DC1EF…`） |
| `work/models/cards/mdl-20260911-906f5e.json` | 本次训练的模型卡（draft） |

## 7. 待用户决策

- **B1** 是否做基线求解（长任务，需放宽策略）；**B2** 参数效验范围（几何/网格类）；
- **B3** 两个 528 MB / 4.25 GB 扫描模型的参数集是否与目标器件一致（是否也接入）；
- **A1** 是否提交本机这批文档/代码修复（`git` 身份尚未配置：`user.name`/`user.email` 为空）；
- **A2** `HANDOFF.md`、`dsh-config/` 是否入库（当前未追踪）；
- **C1** 是否清理 `work/` 缓存（`.pip-cache` 194 MB、`.test-tmp` 232 MB、`devices` 198 MB、`tmp` 28 MB）；
- **C2** 文献/实验/人反馈是否现在开始接入（表全空）。

## 8. 不要做的事（红线摘要，全文见 `AGENTS.md`）

没有证据不出数字（每个数值要能指回 `run_id`/`evidence_id`/`experiment_id`/`feedback_id`）；物理正确性优先于 AI 指标；
不猜 `.mph` 内部；来源永不混同（`ai_solver` 独立于 `simulation`）；模型状态晋升必须人工放行；历史 append-only；
AI 求解必须有界（误差界 + S 级验证 + 适用范围命中，超范围拒答并回退 COMSOL）；**求解环节禁止并行扇出**（单实例串行队列）。
