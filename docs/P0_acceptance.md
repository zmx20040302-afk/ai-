# P0 验收记录（含 A1–A3 扩展）

> 状态：**待用户验收**｜生成：2026-09-11｜执行环境：本机（Windows / COMSOL 6.4 / MPh 1.4）
> 原则：本记录只写**实测证据**；未验证项一律标注为未验证，不用推测填空。

---

## 1. P0 目标与结论

| P0 原定目标 | 结论 | 证据位置 |
|---|---|---|
| 环境打通（venv、依赖、COMSOL 通路） | ✅ | §2 |
| MCP 接入 DSH，工具可用 | ✅ 链路已验证；GUI 需重启 DSH 生效 | §3 |
| 元数据库与数据契约 | ✅ | §4 |
| 文件队列 + 单实例 worker | ✅ | §5 |
| 最小闭环（扫描 → 入库 → 训练 → 模型卡） | ✅ | §6 |
| 模块能力表 | ⚠️ 部分：文档层实测；**求解层仅 heat_slab_2d 已验证** | §7 |

---

## 2. 环境（实测）

| 项 | 实测值 |
|---|---|
| COMSOL | **6.4.0.293**（`D:\COMSOL64\Multiphysics`），6/6 可执行文件、授权文件齐备 |
| mphserver | 常驻，`127.0.0.1:2036` 已监听 |
| MATLAB / LiveLink | R2025b + `mli` 在位（未使用，B 通路不依赖它） |
| Python | 3.12.10，venv 用 `uv` 创建（`python -m venv` 在中文路径下必失败） |
| **ASCII 交汇点** | `C:\Users\18161\memsharness_work\repo`：凡启动 JVM 的工具必须经它（否则 JPype 报 `UnsatisfiedLinkError`） |

**三通路实测**：
- **A 通路（MPh + mphserver）**：✅ 连通、加载模型 8.39 s、读参数/物理场/研究、求解、求值（`work/reports/pathway_a_mph.json`）
- **B 通路（Java API + `comsolcompile` + `comsolbatch`）**：✅ **真实跑通**，单点 ~23 s（见 §5、§6）
- C 通路（模板直连）：由 B 通路承载

---

## 3. MCP 接入（`mcp__mems__*`）

补丁写入 `~\.dsh\profiles\web\cordis.patch.yml`（**必须用 `- insert:` 形式**，否则报 `patch: entry not found`）。
**已注册 11 个工具**（`--selftest` 实测）：`ping`、`env_report`、`module_capability`、`data_stats`、`records`、`run_trace`、`sim_templates`、`sim_submit`、`sim_status`、`sim_logs`、`sim_cancel`。

端到端验证（headless 会话，不经 GUI）：模型成功调用 `mcp__mems__env_report`（返回 6.4.0.293、mphserver 监听=True）、`module_capability`（`solve_verified` 全为 `null`）、`data_stats`、`records`（越权表名被正确拒绝）。
**注意**：HMR 不会新增插件条目 → GUI 内生效需重启 DSH。

---

## 4. 元数据库与契约

12 张表：`task/design/run/sample/artifact/dataset/model/prediction/experiment/evidence/feedback/validation`。
强制约束（有测试守住）：`source_type` 白名单 + **按来源类型强制溯源链**（simulation→run_id、literature→evidence_id、experiment→experiment_id、human_feedback→feedback_id）；`inputs`/`outputs` 不得同时为空；`extractor` 必填。

---

## 5. 队列与执行层

**8 点真实参数扫描**（`k_cond ∈ {1,2}` × `q_in ∈ {500,1000,1500,2000}`）：

| 项 | 实测 |
|---|---|
| 任务状态 | **8/8 `succeeded`**，单点 **22.4–23.3 s** |
| 单实例串行 | 扫描中 `worker_locked = True`；状态流转 `queued → running → succeeded` |
| **L1 网格收敛** | `passed = true`；hmax 0.002/0.001/0.0005 → 单元 56/212/828，T_max 相邻差异 **4.3e-08 / 7.5e-09** |
| 失败诊断 | 编译失败被正确分类（`code=api`、`stage=compile`、含处置建议、`retryable=false`） |
| 产物 | 每个 run 目录含 `.java/.class`、`out.mph`、`commands.json`、`batchlog.txt`、`db_record.json` |

**修掉的关键缺陷（本轮实测暴露，原代码从未跑过）**：worker 不认 `--drain`（任务僵死）；Java `selection("tag")` 用法错；`model.save()` 未声明 `IOException`；生成源码含非 ASCII（已加显式校验）；数值节点未绑定数据集 → **求解成功却返回 NaN**；热流用域积分恒为 0 → 改边界积分；batchlog 中文标签解析失效。

---

## 6. 最小闭环（8 点 → 入库 → 训练 → 模型卡）

**入库**：`run=8`、`sample_simulation=8`、`sample_analytic=8`、`artifact=128`（来源分列，不混同；保真度 F2/F0 分列）。

**每个点的仿真值 vs 解析值**（`T_max = T0 + q_in·Lx/k`）：

| k_cond \ q_in | 500 | 1000 | 1500 | 2000 |
|---|---|---|---|---|
| **1.0** | 305.0 / 305.0 | 310.0 / 310.0 | 315.0 / 315.0 | 320.0 / 320.0 |
| **2.0** | 302.5 / 302.5 | 305.0 / 305.0 | 307.5 / 307.5 | 310.0 / 310.0 |

**8/8 的 L0 相对误差 = 0.0**（仿真实测 / 解析预期）。

**模型卡**（`mdl-20260911-1c9212`，状态 `draft`）：
- 训练 8 条 / 测试 2 条（仅用 F2 仿真样本）
- `T_max_K`：RMSE **0.41 K**、R² **0.9956**、相对 RMSE **0.13%**
- **如实警告 3 条**：样本量 8 远低于可靠阈值 100（指标仅供管线验证）；`T_min_K` 在测试集方差为零（R² 无意义）；90% 区间覆盖率 1.00 偏离目标（不确定度未校准）
- 剔除 7 个恒定输入列（`Lx/Ly/T0/rho_mat/Cp_mat/bnd_t/hmax_mesh`）并**记录在模型卡**中

---

## 7. 其它交付物（A1–A3）

| 项 | 状态 |
|---|---|
| **A1 模型接入 SOP** | ✅ `src/memsharness/onboard.py` + `scripts/onboard_model.py`；八步自动部分跑通，产出 `device_report.json`/`param_audit.json`/`device_spec.yaml`/`pod_points.txt`；参数审计白名单有实测证据（示例：Lx/Ly→geometry、c_air→material、rho_air→无可测影响） |
| **A2 队列产品化** | ✅ 见 §5、§3 |
| **P1 场快照对齐** | ✅ 713 点公共点集；几何变化后快照仍等长；域外 NaN 需掩膜（`work/reports/p1_field_grid.json`） |
| 技能库 | ✅ 3 个：`comsol-modeling-sop`、`dataset-contract`、`report-and-evidence` |
| 测试 | ✅ **77 passed** |

**模块能力表**：文档层 8 个模块齐备；**求解层仅 `heat_slab_2d` 经真实求解验证**（`module_capability` 里其余仍为 `null`，符合"未验证就不冒充已验证"）。

---

## 8. 已知问题与未完成（如实列出）

1. **L0 对标口径偏松**：当前用绝对温度 + 3% 容差；3% × 300 K = 9 K，而总温升仅 10 K → 容差几乎等于放行一切（错误的 2D 模型 308.85 K 也能"通过"）。**建议改为对温升 ΔT 设容差**（如 1%）。**尚未实施**。
2. **孤立 `queued` 记录**：A2 调试中删除队列票据留下的 13 条 `run` 记录仍为 `queued`，未标记为 cancelled（不影响数据正确性，但账目不清）。
3. **无法做族间切分**：本批数据只有 1 个几何族（`GF-heat-slab-2d`），切分退化为随机并如实警告；跨族泛化能力**未验证**。
4. **场级免求解器未开始**（A6/P4.5）：P1 已验证前提，尚无实现。
5. **用户模型未到位**：所有器件物理结论**不做**；本记录中的结论仅限平台管线。
6. **`__init__.py` 曾声称"已实测跑通"**：该断言在其编写时**不成立**（本轮才真正跑通）；现已通过真实运行成立，但此事说明**子代理的"已完成"声明必须复核**。

---

## 9. 复现命令

```powershell
$py = "C:\Users\18161\memsharness_work\repo\work\.venv\Scripts\python.exe"   # 必须经 ASCII 交汇点
$r  = "C:\Users\18161\memsharness_work\repo"

& $py "$r\scripts\smoke_comsol.py"                                  # 环境快照
& $py "$r\scripts\run_sweep.py" --template heat_slab_2d --mesh-convergence          # L1（必须先过）
& $py "$r\scripts\run_sweep.py" --template heat_slab_2d --sweep "k_cond=1.0,2.0" --sweep "q_in=500,1000,1500,2000"
& $py "$r\scripts\train_surrogate.py" --fidelity F2 --json          # 模型卡
& $py -m memsharness.mcp_server --selftest                          # MCP 工具清单
& $py -m pytest "$r\tests" -q                                       # 测试
```
