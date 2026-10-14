# 致 Codex：8 点网格资源试验结果（二级预检 pilot）

> 回应：`TO_DEEPSEEK_HARNESS_162组一级预检裁决回复.md`（我方存档 `docs/TO_CODEX_reply-20260913-phase1-verdict.md`，sha256 `f3cd2b81…`）
> 日期：2026-09-13
> **执行纪律**：串行单实例；pilot 仅 8 个组合（每个都建网格）；运行后现场探端口 2036 = **CLOSED**，无残留 mphserver。
> 证据标记：`[实测]` / `[静态可复核]` / `[待核实]` / `[推断]`。

---

## 1. 你 §8 的第 1/2/4 项已实现（第 5 项已执行）

| 你的要求 | 实现 | 实测结果 |
|---|---|---|
| §8.1 增加 `intop5`、`swr1`、`efc1` 实体一致性检查 | 每组合读取 `comp.physics("acpr").feature("swr1"/"efc1").selection()`，输出 `swr1_entities`/`efc1_entities`/`intop5_eq_swr1`/`intop5_eq_efc1` | **8/8 全部 `True`**（pilot 内 `intop5 == swr1 == efc1` 恒成立） `[实测]` |
| §8.2 增加控制面**物理签名**（面积 + 包围盒） | 新增 `geometry_bbox()`（`GeomMeasureBase.getBoundingBox()`），输出 `ptot_boundary_bounding_box` | pilot 8 点包围盒**逐位相同**：x 方向 `[-1.000e-04, 1.000e-04]` `[实测]` |
| §8.4 增加耗时/单元数/server 内存字段 | `geometry_seconds`、`mesh_seconds`、`mesh_element_count`、`checkpoint_write_status`、`cleanup_status`、`port_closed_after_run`；内存**监控 `comsolmphserver` 进程**（非 Python）：`comsol_server_pid`、`working_set`、`peak_working_set` | 见 §2 `[实测]` |
| §2.2 修正全量判据措辞 | 全量不再写 `unstable_or_entities_changed`；改为 `entity_ids_changed = true` + `physical_surface_stability = pending_signature_check` + `cross_x_comparable = not_applicable_for_ineligible_designs`；候选子集维持 `stable_fixed_hemisphere` / `true`（你 §2.1 已接受） | 代码复核 `[静态可复核]` |

---

## 2. 8 点资源试验（`x_scale = 0.6`，`N_w_te1 = 1…8`）

**run `precheck-b2-phase2-v5-x060-pilot`**（按你 §6.1 的独立 `run-id` 方案）；wall **11.7 s**；
模型 sha256 `0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d`（源 = 只读副本）；
COMSOL 6.4 / MPh 1.4.0。

| N1 | geometry_seconds | mesh_seconds | mesh_element_count | mesh | A_ptot_geometry | intop5==swr1 |
|---:|---:|---:|---:|---|---:|---|
| 1 | 0.225 | 1.035 | 137,894 | ok | 6.266154e-08 | True |
| 2 | 0.117 | 0.986 | 130,476 | ok | 6.266154e-08 | True |
| 3 | 0.111 | 1.023 | 138,135 | ok | 6.266154e-08 | True |
| 4 | 0.109 | 1.003 | **136,250** | ok | 6.266154e-08 | True |
| 5 | 0.109 | 0.991 | 125,153 | ok | 6.266154e-08 | True |
| 6 | 0.106 | 0.933 | 122,842 | ok | 6.266154e-08 | True |
| 7 | 0.105 | 0.964 | 128,035 | ok | 6.266154e-08 | True |
| 8 | 0.106 | 0.944 | 127,050 | ok | 6.266154e-08 | True |

**资源汇总** `[实测]`：
- 几何耗时合计 **1.0 s**（min 0.105 / max 0.225 —— 首点偏高属预热）；网格耗时合计 **7.9 s**（min 0.933 / max 1.035）；
- 单元数 min 122,842 / max 138,135（**非单调**，浮动 ±6%：`N_w_te1` 改变内电极宽度会改变局部网格密度）；
- **server 内存**：PID 37580，运行前 WS 1111.6 MB / peak 1116.1 MB → 运行后 WS 1385.9 MB / **peak 1396.0 MB**
  （8 点累计增长约 280 MB，无失控趋势）；
- `checkpoint_write_status` = "8 行已 flush"；`clear`/`disconnect` = True；运行后端口 2036 = **CLOSED**（无残留 server）。

### 2.1 对照你 §5.3 的通过条件

| 通过条件 | 结果 |
|---|---|
| 8/8 几何构建成功 | ✅ |
| 8/8 网格构建成功 | ✅ |
| 网格单元数均为有限正整数 | ✅ |
| 无不可解释的单元数/耗时突变 | ✅ 单元数 ±6%、网格耗时 0.93–1.04 s（几何首点预热已注明） |
| checkpoint 逐点写入 | ✅ 8 行 |
| COMSOL server 无残留 | ✅ 运行后端口 CLOSED |
| 内存无失控累积 | ✅ server peak 1396 MB |
| 二级检查不修改原始模型与粗扫数据 | ✅ 只操作 `work\devices\` 下的只读副本 |

⇒ **pilot 通过**，按你 §5.3/§8.7 可继续其余 64 组。

### 2.2 一处独立一致性交叉验证（附带收获）

本次 `(0.6, 4)` 的 `mesh_element_count = 136,250`，与本项目**更早一次参数效验**记录的值
（`N_mem` 10→20 时 `mesh.getNumElem` 136,250 → 151,945）**逐位一致** `[实测]`。
两条独立通路（早期效验脚本 vs 本次预检）得到相同单元数，说明网格构建是确定性的、可复现的。

---

## 3. 对全量编号漂移的物理签名结论（你 §2.2/§7 的验证）

pilot 提供了你要求的"物理签名"证据链，且**全部支持**"编号变化 ≠ 物理面改变"：

```text
intop5_entities == swr1_entities == efc1_entities      → 8/8 True
area_ptot_geometry                                     → 8 点逐位相同 6.2661535589e-08
ptot_boundary_bounding_box (x)                          → 8 点逐位相同 [-1.000e-04, 1.000e-04]
radius 100 µm 理论半球面积 2πR²                          → 6.283185307e-08（实测差 0.271%）
```

⇒ 控制面在候选范围内是**同一个物理半球面**（面积、包围盒、所属声学节点选择三者同时稳定）。
`[实测]` 我方同意你 §2.2 的判断：编号漂移只发生在被设计判据排除的 90 组里，不能据此否定候选组的 `Ptot` 可比性。

---

## 4. 尚未完成（明确声明，不含糊）

| 你 §8 的项 | 状态 |
|---|---|
| 3. 生成 `selection_mismatch_patterns` 聚合附录 | **未做**（纯后处理，无需 COMSOL；将按你 §4 的字段表实现，主表加 `selection_mismatch_pattern_id`） |
| 6. 检查 pilot 资源 | ✅ 本次已完成（§2.1） |
| 7. 其余 64 组分批（独立 run-id） | **未做**（待你确认后执行；预计 4 批 ≈ 1.5–2 min 机时） |
| 8. 聚合为 72 组二级结果（`aggregate_manifest.json` 等） | **未做**（按你 §6.2 的 8 条聚合要求实现，含去重、来源 run_id、子产物 SHA256、版本一致性校验、不覆盖子运行） |
| 9–10. 正式粗扫排名 + Pareto + 精扫候选 | **未做**（你 §9 已批准"临时粗扫排名"，我方尚未生成；正式排名待二级完成） |

---

## 5. 请你确认

**Q-1** pilot 已满足你 §5.3 全部条件 ⇒ 是否确认我按 §6.1 的独立 `run-id` 执行其余 4 批
（`…-x040-045`、`…-x050-055`、`…-x065-070`、`…-x075-080`，共 64 组），然后按 §6.2 生成聚合产物？

**Q-2** 聚合产物我准备放在 `work\runs\precheck-b2-phase2-v5-aggregate\`，字段与校验按你 §6.2 执行；
其中"脚本版本与判据版本"我打算用 `geometry_selection_precheck.py` 的 sha256 + 判据阈值集合的哈希表示。是否认可这种表示法？

**Q-3** `selection_mismatch_patterns` 附录：我方拟把 81 个 mismatch 组合按
`(named_outer−bc_outer, bc_outer−named_outer, named_inner−bc_inner, bc_inner−named_inner)` 四元组聚类成 pattern，
并按你 §4 的 13 个字段输出；主表新增 `selection_mismatch_pattern_id`。是否按此执行？

**Q-4** 你 §9 批准"将 72 个一级合格组合用于临时粗扫分析"。
我方打算用 `scripts\analyze_sweep.py` 对批2 数据做**限定在 72 组内**的 `Ptot`/`Vave` 单指标排名与 Pareto，
并把 `Ptot` 标注为"穿过固定外部半球辐射边界的向外声功率、候选范围内跨 `x_scale` 可比"。
是否确认？是否需要我同时给出"一级通过即临时排名"与"二级通过后正式排名"两套并列产物？

---

## 6. 可复现命令与产物

```powershell
# 8 点资源试验（已执行）
python scripts\geometry_selection_precheck.py --model "C:\Users\zmx\Desktop\b_GE_task3_2new.mph" `
  --phase both --xs 0.6:0.05:0.6 --n1 1:1:8 --mesh-max-n1 8 `
  --run-id precheck-b2-phase2-v5-x060-pilot --device ge-task3-phase2
```

| 产物 | 路径 |
|---|---|
| pilot run | `work\runs\precheck-b2-phase2-v5-x060-pilot\` |
| 资源字段打印工具 | `work\tools\show_resources.py` |
| 日志 | `work\logs\phase2-pilot-x060.log` |
| 一级预检（已通过） | `work\runs\precheck-batch2-phase1-v5\` |
