# LT2 执行令（后继版本）— 取代 2026-09-13 工单中的 LT2-B / LT2-D 条款

- 日期：2026-09-14
- 取代对象：`docs\TO_CODEX_order-20260913-LT0-LT3.md` 的 §LT2-B、§LT2-D
  （该文件在本机为**只读冻结**属性，`IsReadOnly=True`，故不就地修改，改用本后继文件；
  这是 `TO_CODEX_record-20260914-rulings-accepted.md` §4 所述「正式后继版本」路线）
- 依据裁定：`TO_DEEPSEEK_HARNESS_LT2R0v2停止线裁定回复.md`
  sha256 `12d0a191019a48e3f7911c220fcb910b3cdc3b3677c7c97f73133d42c735b544`
- 原文件中 §LT2-A（固定口径）、§LT2-C（每组合快速门禁）、§LT2-E（聚合验收）**继续有效**，未被取代。

---

## 1. 取代 §LT2-D（资源停止线）

原文 `单批次峰值 server WS >= 2.5 GB -> stop` **废止**。理由：本机实测单组合峰值 11,236 MB
（run_id `lt2-resource-calibration-x080-n02-v2`），该线低 4.4 倍；且 `PeakWorkingSet` 单调不减，
不能作实时继续/停止信号，只作批后审计。

**新实时规则**（唯一权威实现：`work\tools\rt_gate.py` 的 `Thresholds` 默认值，不得静默放宽）：

```text
expected_high_water        current_server_ws_mb < 11500
ws_warning                 current_server_ws_mb >= 11500
ws_hard_stop               current_server_ws_mb >= 12288       连续 2 个 5 s 采样
physical_avail_hard_stop   system_available_physical_mb <= 4096 连续 2 个 5 s 采样
commit_warning             commit_available_mb <= 6144
commit_hard_stop           commit_available_mb <= 4096          连续 2 个 5 s 采样
sample_gap_hard_stop       连续 15 s 无新样本 -> 停止投递并报警
```

动作语义：

- **软线（warning）只阻止下一组合**，不取消当前组合；
- **硬线（hard_stop）**先正常取消（保存监控现场、`client.clear()`/`disconnect()`）；
  只有正常取消失败且系统风险继续扩大时，才允许终止**已核对归属**的 server
  （PID + 启动时间 + 端口 + run-id 全部匹配）；
- `PeakWorkingSet` 仅审计。

## 2. 取代 §LT2-B（批次组织）

```text
logical_batch_size    = 4 combinations      （汇报/checkpoint 批次）
server_lifecycle_size = 1 combination       （每组合一个全新 server）
```

- 禁止 12–16 组合大批量；旧文「每批 8–16」作废；
- 首逻辑批 4 个组合全部满足资源/求解/清理/端口条件后，才单独执行一次
  「两组合共用同一 server」的生命周期试验；该试验通过后才允许 `server_lifecycle_size = 2`；
- **不得**假设跨组合内存会被释放：R0 v2 只证明「单组合的一次 7 频点 study 可完成」，
  未提供任何跨组合证据（详见裁定记录 §2）。

## 3. 启动前置条件（全部满足才可开跑）

```text
LT1 minor artifact fixes complete                    （已完成，见裁定记录 §3）
real-time supervisor dry-run = PASS                  （rt_gate 30/30 通过；端到端待补）
pagefile-adjusted resource confirmation = PASS
  或 用户明确拒绝系统变更且有人值守回退门禁通过
no other COMSOL server
target port free
model / script / criteria / sweep hashes frozen
```

有人值守回退路线的启动门禁（Codex §Q3）：

```text
commit_available_mb     >= 13500
available_physical_mb   >= 16384
严格 1 组合 / 1 server，有人值守；任一门禁不满足即不启动
不得升级为无人值守长批次
```

## 4. 页面文件调整后的确认运行（若用户批准）

1. 先记录变更前：页面文件模式、已分配大小、commit limit、C 盘可用空间；
2. 修改系统设置并按系统要求重启；
3. 重启后记录同一组指标，证明**实际生效**；
4. 用**新 run-id** 对 `(0.8, 2)` 再做一次 7 频点资源确认（该次只验资源与实时门禁，不验模型可解性）；
5. 通过条件至少：`rows = 7`、`gaps > 15 s = 0`、三条硬线均未触发、`server cleanup = ok`、
   端口 30 s 内关闭。

> 页面文件是**系统级变更**，必须由用户明确授权；执行方不得自行修改或重启。

## 5. 每组合快速门禁（沿用 §LT2-C，并明确求解前记录）

```text
geometry_status = ok
mesh_status = ok
pot1 / pot2 / gnd1 selections nonempty
pairwise_electrode_overlap = 0
term1_active = false
cir_active = false
intop5 == swr1 == efc1
ptot_surface_area_unchanged = true
ptot_surface_bbox_unchanged = true
```

R0 v2 **没有**提供上述选择/积分面证据，正式生产脚本必须在求解前记录它们。

## 6. 事件与落盘要求

- 完整事件表以 **JSONL** 落盘；报告可摘要前 40 条，但**必须同时给出总数与完整文件 sha256**；
- 每组合完成后**先原子写 checkpoint，再关闭 server**；
- 每行保留 `source_run_id` 与 `source_artifact_sha256`；每个 child payload 写入模型/脚本/判据哈希；
- `pass_conditions` **必须包含 commit 项**（2026-09-14 裁定指出的缺陷 D1）。

## 7. 状态

```text
LT2 = BLOCKED_BEFORE_PRODUCTION   （直到 §3 前置条件全部满足）
```
