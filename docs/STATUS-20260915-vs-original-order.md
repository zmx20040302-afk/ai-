# 对照原始计划表：做了什么、没做什么（截至 2026-09-15 15:40）

> ⚠️ **本文档的状态/计划部分已过时（截至 2026-09-29 晚）**：此后仓库又推进了多轮，
> 以 **`docs/INDEX-records-and-rulings.md` §30–§80** 与 **`docs/UNFINISHED_TASKS_AUDIT.md`** 为准；
> 阶段现状见 **`WORKING_PLAN.md` §7.1**。本文档保留作**历史记录**，不改写。


**对照基准（三份，按优先级）**

1. `docs\TO_CODEX_order-20260913-LT0-LT3.md` —— 原始工单（**只读冻结**，LT0/LT1/LT2/LT3 逐项验收门槛在第 2–5 节，全局 STOP 在第 8 节，最终提交清单在第 9 节）
2. `docs\TO_CODEX_order-20260914-LT2-superseding-LT2B-LT2D.md` —— 后继执行令，**取代**原工单 §LT2-B（批次组织）与 §LT2-D（资源停止线）
3. `WORKING_PLAN.md` §7 —— P0–P7 阶段与验收标准（AGENTS §1 指定的当前阶段依据）

**结论一句话**：**LT0 有 2 项未通过/未定论、LT1 全过、LT2 的执行系统全过但 504 点本身没跑、LT3 只完成了"分析管线与 legacy 对照"、正式排名因无数据而无法生成。** 另有大量计划外工作（生产执行系统、冻结验收、AI 求解器、场级准备）。

---

## 一、LT0（工具与审计修复）

| 子项 | 工单要求 | 实测证据 | 状态 |
|---|---|---|---|
| **LT0-A** Circuit 已停用 | 独立证据证明 `cir` 停用；`term1_active=false`；必要时 `.m` 旁证 | `work\models\lt0_audit.json`（4,508 B）：`physics_isActive=false` ✓；**`term1_active = null`**（未判定）；**`.m` 导出失败**（`文件名无效，只允许 'a'-'z'`） | ⚠️ **部分通过**：cir 停用有 API 证据；`term1_active` 未判定、`.m` 旁证缺失 |
| **LT0-B** Ground 记录 | 删 `gnd1.set('V0')`、保持 active、参考电位≈0V | 同文件：`gnd1_V0_property = absent`（Ground 固有 0 V）、`ground_voltage_verified=true`、5/20/35 MHz 参考电位 `[0,0,0]`、change-log 措辞就位 | ✅ **通过** |
| **LT0-C** 端口电流与 KCL | 完整法向电流 `JX*nx+JY*ny+JZ*nz`；KCL ≤ 1%；**不通过时允许"排除全部电气指标"继续** | `kcl_max_relative = 0.1886` ⇒ `kcl_pass=false` ⇒ 按工单允许口径置 `electrical_current_metrics_excluded=true`；此后**每一次 LT2 run 的 checkpoint 都带该标记**（reason `LT0_C_KCL_relative_gt_1pct`） | ⚠️ KCL 未过，但**走的是工单明许的替代路径**，属**合规通过** |
| **LT0-D** 脚本健壮性 | `None` 打印/docstring/`try-finally`/端口 30 s/记录 PID 与峰值/补测试/`pytest -q` ≥ 240 passed | 端口与 PID 记录在 LT2 全线有证据（各 run `port_closed_within_30s=true`）；`pytest` 曾因 Windows SxS 收集失败，后**恢复为 240 passed / 4 skipped，3/3 稳定**（索引 §8.2，边界：属"当前可用"而非受控复现根因） | ✅ **基本通过** |
| **LT0-E** 参数生效性补测 | `x_scale`/`N_w_te1`(4→5)/`vamp`(0.5→1 V)/`fmax`(35→45) 四类签名 | `work\models\lt0e_signatures.json`（2,957 B）：**`LT0_E_N_w_te1.pass = false`**（选择集未变、内电极面积变了：5.31e-10→8.29e-10）；**`LT0_E_fmax`：`lamda_ratio_45/35 = 1.0`（期望 0.7778）** —— 因为读的是**全局 `size.hmax = 2.0E-5`**，而真正挂 `lamda/5` 的是 **`ftet1.size1`**（测量对象错） | ❌ **未通过**：N_w_te1 判 false；fmax 一条**因测量对象错误而无效**（未定论） |

**LT0 门槛（12 项）**：`reverse_drive_voltage_gate=pass` ✓、`ground_voltage_verified=true` ✓、`cir_inactive_verified=true` ✓、`electrical_bc_conflict=false` ✓、`port_2036_closed_within_30s=true` ✓、`pytest_regression`（已恢复）、`parameter_signature_x_scale=pass` ✓；
**`term1_active=false` 未判定**、**`parameter_signature_N_w_te1` 实测 false** ⇒ **门槛未全绿**。

> **重要旁注**：`LT0-E` 的 `fmax` 错误（读错特征）与 2026-09-15 网格诊断里会话 A 的同一个错误**同源**；后者已自查更正并确认 `ftet1.size1.hmax='lamda/5'`。
> ⇒ **LT0-E 应重做**（1–2 次求解），目前**未做**。

---

## 二、LT1（五组合三频点小样）—— **通过**

| 验收项（工单 §LT1-C） | 要求 | 实测 |
|---|---|---|
| `expected_points` / `successful_points` | 15 / 15 | **15 / 15**（`runs\lt1-reverse-sample\lt1_validated_results_v2.csv`） |
| `duplicate_keys` / `missing_keys` | 0 / 0 | **0 / 0** |
| `nan_or_inf` / `negative_Ptot` | 0 / 0 | **0 / 0** |
| `drive_voltage_mismatch` | 0 | **0** |
| `selection_drift` / `server_cleanup_failures` | 0 / 0 | **0 / 0** |

- 汇总：`lt1_validation_summary_v2.json`（模型 `cbe9ccc18e51005f…`、`raw_rows=15`、`validated=15`、`electrical_current_metrics_excluded=true`）。
- **LT1 STOP 条件未触发**（电位口径外 +1/内 −1/参考 0、`term1`/Circuit 未复启、选择集未空/未重叠、`intop5=swr1=efc1`）。
- 完成报告：`docs\TO_CODEX_progress-20260914-LT1-complete.md`；Codex 审阅：`docs\TO_CODEX_reply-20260914-LT1-review.md`。

---

## 三、LT2（72 组合 × 7 频点反相粗扫）

| 子项 | 状态 | 证据 / 备注 |
|---|---|---|
| **LT2-A** 固定口径 | ✅ | 驱动 `dual_electrode_antiphase_voltage_drive`、模型 `b_GE_task3_2new_reverse_voltage_drive_v1.mph`（`cbe9ccc1…`）、7 频点、批组织固化在 `work\tools\lt2_production.py` |
| **LT2-B** 批次组织（**已被后继执行令取代**） | ✅ | 按后继令：**每组合一个全新 worker 实例**、单实例串行；实测 `server_identity.parent_is_worker=true` |
| **LT2-C** 每组合快速门禁 | ✅ | `lt2c_quick_gate` 18 项（选择集非空/不重叠、`named_cyl8=pot1`、`term1_active=false`、`cir_inactive_verified`、`intop5=swr1=efc1`、冻结控制面面积/bbox 不变）——r3d/r3g/r3h 全 `true` |
| **LT2-D** 资源停止线（**已被后继执行令取代**） | ✅ | 阈值 12288/4096/6144（2 连采样）；前置双门禁 18000/21500（间隔 5 s）；**真实硬停演练 U1–U3 达成**（`drill_gate`、启动时间四元组核验、用户 GUI 未触碰）；**r3e：首次真实资源硬停被正确处置**（`enforced_by=resource_gate`、不重跑） |
| **LT2-E** 聚合验收 | ⚠️ **部分** | 单组合（r3d/r3g/r3h）与小批（4 组合 / 28 点，aggregate 11 项全 `true`）均已验；但工单门槛要求 `unique_parameter_keys=72`、`frequency_rows=504` ⇒ **未达成** |
| **504 点本身** | ❌ **未跑** | 原因：资源与授权序列；**2026-09-15 用户决定"反相问题先保留、现有任务完成后再谈"** ⇒ 搁置（未取消） |

**LT2 的额外完成度（计划外但已做）**

- 三进程生产执行系统（supervisor→**每组合全新 worker**→sampler 侧车 + 实时门禁 + 原子写 + 失败分类 + 证据隔离）；
- 真实资源确认 **r3d / r3g / r3h 三次 PASS**（r3g 首次让"正常收尾写 `completion_record.json`"落地；r3h 在真实生产路径上背书 A/B/C/F5 四项改动）；
- 小批试探 **4 组合 / 28 点全过**，并与 LT1 反相基线在 12 个可比点上**逐字节一致（120 单元 0 差异）**；
- 冻结点 **13+ 个**，当前 `freeze-20260915-1055-post-f5-t1t2-abc-records` 前后均 MATCH、可用于后续批次。

---

## 四、LT3（质检、排名、Pareto 与候选重选）

| 子项 | 状态 | 证据 / 备注 |
|---|---|---|
| **LT3-A** 数据质量 | ✅（但**跑在 legacy 数据上**） | `work\lt3\lt3_quality_report.json`；**注**：反相数据不存在，LT3 用的是用户 legacy 单电极数据（1134 行） |
| **LT3-B** 指标 | ✅ | `lt3_metrics.csv`、`lt3_response_metrics.csv`（含**两套插值口径与其实测不确定度**：`Ptot` FBW 口径差中位 27.6 个百分点、`Vave` 7.3） |
| **LT3-C** Pareto 与候选角色 | ✅（带口径限制） | `lt3_pareto.csv`、`lt3_pareto_dominance.csv`、`lt3_pareto_pairs.csv`；`Ptot@20MHz × Vave@20MHz` **退化为 1 点**，另 4 对非退化；结论**不得外推** |
| **LT3-D** 与 legacy 驱动比较 | ✅ | `work\lt3\legacy_vs_reverse_normalized.csv`（15 行）；按 `Vave/\|Vdiff\|`、`Ptot/\|Vdiff\|²` 归一化；**明文禁止**读成结构收益 |
| **LT3-E** 最终产物 | ❌ **无法生成** | 工单要求的 `reverse_drive_coarse_raw.csv` / `_aggregate` / `_metrics` / `_pareto` / `_candidate_plan` **全部不存在**（没有反相数据）；`lt3_prep.py` 守卫：`FORMAL_RANKING_AUTHORIZED=False`、反相数据 **exit 3** |
| **§6 LT3 后强制停止** | ❌ **未到达** | 因为正式排名没做（缺 504 点） |

---

## 五、计划外但已完成（本次会话新增，工单里没有）

| 线 | 内容 |
|---|---|
| **冻结与验收基础设施** | 六步冻结流程；`--verify`（源 vs manifest）与 `--verify-snapshot`（精确文件集合）；**25 项 fail-closed 验收检查器**；空集合判失败、禁只留 tail、运行期门禁与事后审计严格区分 |
| **AI 求解器（WORKING_PLAN §6，非本工单）** | 第 1–3 步（切分防泄漏 + 基线代理 + 适用域/拒答）；**第 4 步**（域内代理 + 保形误差界 + 拒答 CLI）；**第 5 步**（**负值结构性修复**：`log10` 建模使域内非正比例 3.89%/16.20%→**0**，误差 35–50%→**5.7–14%**；**预注册选模型**选中 `M2_log10_gp`；可交互调试入口，第 4 步 11 例拒答逐字复现） |
| **用户参数网格** | 从用户 xlsx 落成机读表（162 组）；叠加平台预检判定：**仅 72 组为有效设计**（N1=9 边界重合、N1 10–18 区域反序） |
| **模型构建/对账** | 72/72 组**选择集复核零异常**；2 组合 × 7 频与用户数据对账（0 fail）；用户目标模型 `(0.6,4)` **完整求解成功**（823.83 s、网格 136,250） |
| **溯源定案** | 用户 xlsx = 8.31 GB `range005` 模型 `sol2` 已存解的**直接导出**：全网格 1134×6 = **6804 次比较、最大相对差 9.871e-15** |
| **网格/协议诊断** | 机制 = **两文件网格细化选择集口径不同**（协议无关：T2 与 T3 逐位相同）；同口径可复现性 **0.076%** |
| **场级 S1 准备（Phase 0）** | 公共点集规格（54,147 点）、场导出器（离线自测全过）、成本模型、冻结草案、M1–M10 门禁清单；**当前卡在一个阻断点**（见下） |
| **方法论沉淀** | 「`.m` 取最后一次赋值」一族**当日三次**踩坑（`N_w_te2`、`param.plistarr`、`sph1.r`）；PowerShell 反引号毁 Markdown；线程 `_stop` 遮蔽；`batch.run()` 清空内存解；`.m` 与 `.mph` 状态可能不一致 |

---

## 六、没做 / 受阻（含原因与解锁条件）

| # | 未做项 | 原因 | 解锁条件 |
|---|---|---|---|
| 1 | **504 点反相粗扫** | 用户 2026-09-15 决定"先保留" | 用户重新拍板（现有任务完成后讨论） |
| 2 | **LT3 正式排名/Pareto/候选** | 依赖第 1 项 | 同上 |
| 3 | **LT0-E 重做** | `N_w_te1` 判 false、`fmax` 测量对象错 | 1–2 次求解（可随时做） |
| 4 | **LT0-A 的 `term1_active` 判定 + `.m` 旁证** | `.m` 导出受 ASCII 文件名限制；未补判定 | 改用 ASCII 路径重导，或换判定路径 |
| 5 | **场级 S1（Phase 1，56 次求解）** | **阻断点：坐标点集 ≠ 场点集**（`x` 30,168 点 vs `p` 83,879 点，场是高阶）⇒ "取节点坐标+场值→插值"在当前调用式下不成立 | 正在试「一次调用同取 `['x','y','z','p']`」与「Java mesh 同阶节点」；**不需要重新求解** |
| 6 | **AI 求解器放行** | S1 不可测（无场）+ S2 未达标（跨族 `Ptot` 494.7%）+ S3 `inconclusive` | 第 5 项完成（补 S1） |
| 7 | **电气量（`Zin`）** | `Zin1 ≡ Zin2` 公式复制缺陷 | 先在模型上修公式，再定向重算 |
| 8 | **7R 轴向声压** | 本模型水域仅 100 µm，7R ≈ 294 µm **不可得** | 用户已改判为 **100 µm**（外边界/`Ptot` 控制面），须带变更声明引用 |
| 9 | **L1 网格收敛** | 未做（工程判断前必须过 L0/L1） | 可并入场战役（同批换网格） |
| 10 | **`device_spec` 9 项 `pending_human`** | 未清（含 `source_model.sha256` 留空、目标口径未定） | 人工确认 |
| 11 | **45 MHz 频段** | 用户明确本轮不做 | 用户 + Codex 双重授权 |
| 12 | **`N_w_te1` 口径（1–18 vs 1–8）** | 用户称"只设了 1–8"，但数据是 1–18（study `param` 步写的是 `range(1,18)`；批处理 `p1` 写的才是 `range(1,1,8)`） | **待用户确认本意**；不影响 Phase 1（只用 1–8） |

---

## 七、全局 STOP 条件（工单 §8）—— **未触发**

| 条件 | 现状 |
|---|---|
| 母版/工作模型 SHA 意外变化 | 未触发（冻结 + `--verify` 守护；`INVALIDATED_BY_CODE_DRIFT` 时按规则新建 freeze_id） |
| 反相电位不再是外 `+vamp`/内 `−vamp`/参考 0 V | 未触发（每个 run 的 `drive_voltage_mismatch_0` 均为 true） |
| `term1`/Circuit 重新参与反相 Study | 未触发（`term1_active_false`、`cir_inactive_verified` 逐 run 检查） |
| 电极选择为空/重叠/身份改变 | 未触发（72/72 选择集复核零异常） |
| `intop5/swr1/efc1` 不一致 | 未触发 |
| 同一组合连续两次求解失败 | 未触发（r3f 那次是**记账缺陷**，非求解失败，已修复并复现验证） |
| **内存超过 2.5 GB 停止线** | 该数字来自旧机；本机重定阈值（12288/4096/6144），**r3e 触发过一次真实资源硬停并被正确处置**（不属"意外触发"） |
| 端口被非本任务进程占用 | 未触发（每次起 server 前探端口） |
| 参数/频率重复、缺失、越界 | 未触发（`--freqs` fail-closed 解析；`--expect-freq-count`） |
| 需要改几何/材料/驱动/声学边界才能继续 | **未触发**（7R 判据改位置属"判据口径"，未改几何） |
| 报告指标与 manifest 口径冲突 | 未触发（多处反例已修：`min_commit_gt_4096` 改名、`thresholds` 口径单一真源） |

---

## 八、工单 §9「最终提交清单」11 项对照

| # | 要求 | 状态 |
|---|---|---|
| 1 | 修正后的 `drive_change_manifest.json` | ✅（3,734 B） |
| 2 | Circuit 停用 + Ground 0 V 证据 | ⚠️ Ground ✓、cir ✓；`term1_active` 未判定、`.m` 旁证缺 |
| 3 | 法向电流/KCL 审计或明确排除状态 | ✅（KCL 18.9% ⇒ 明许的"排除全部电气指标"口径，逐 run 落盘） |
| 4 | `x_scale`/`N_w_te1`/`vamp`/`fmax` 扰动签名 | ⚠️ `N_w_te1` 判 false、`fmax` 测量对象错 ⇒ **需重做** |
| 5 | LT1 的 15 点小样 | ✅ |
| 6 | **LT2 的 504 点原始表 + 全部 child run + 聚合质量报告** | ❌ **未达成**（只有 LT1 15 点 + 小批 28 点 + 若干单组合） |
| 7 | 反相指标/Pareto/候选计划 | ❌ 未做（无数据） |
| 8 | 与 legacy 的归一化对照 | ✅（15 行） |
| 9 | 每批耗时/峰值内存/重试/server 清理记录 | ✅（LT2 全线逐步记录） |
| 10 | 全部关键产物 SHA256 | ✅（大量，且已有 manifest 体系） |
| 11 | **是否具备进入 45 MHz 网格阶段的结论** | ❌ **未给出**（用户本轮不做；且反相数据缺） |

---

## 九、当前待拍板（4 件）

1. **`N_w_te1` 本意是 1–8 还是 1–18？**（决定那 90 组是否划为"非预期"、以及 AI 求解器 `V2_all162` 变体的去留）
2. **反相/504 是否重启讨论**（现为"保留待议"；LT2-E 与 LT3-E 都卡在它）
3. **LT0-E 是否重做**（1–2 次求解；不重做则 LT0 门槛一直不绿）
4. **场级阻断点**（坐标/场点集不匹配）的解法选择——我倾向"一次调用同取 `['x','y','z','p']`"，若不行则走 Java 同阶节点
