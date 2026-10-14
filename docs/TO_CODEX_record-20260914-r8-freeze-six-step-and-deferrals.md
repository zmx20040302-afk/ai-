# 裁定记录（append-only）R8 — 补齐 R7 冻结流程、R4 延后处理、R6 勘误索引

- 日期：2026-09-14
- 触发：用户要求「修复之前发现但没有处理的问题」
- 前置：`docs\TO_CODEX_record-20260914-r7-codex-r6-accepted-and-two-corrections.md`

---

## 1. 处置原则（先说清楚哪些我**不动**）

我此前发现的部分问题**不应"修"**，因为修改会破坏可追溯性：

| 问题 | 为何不改 |
|---|---|
| `lt2r0_v2.py` 的 D1（`pass_conditions` 漏 commit 项）、D2（停止线为事后审计，运行期无中止）、D3（`events[:40]` 截断未在报告标注总数） | 该脚本的**产出一 R0 v2 资源基线**已被报告引用，其 sha256 `29712522…` 亦被引用。改动它会让「引用该证据的报告」与「可复算的脚本」脱钩。正确处置是**在记录中登记其为已知缺陷**（本表即登记），而不是改脚本。 |
| `rt_gate.py` 的 reason 文本匹配（风险 R4） | 正解是把 reason **结构化**（新增字段），但这要改 `rt_gate.py`；而它**正在被在飞冻结收录**，此刻改动会当场作废实现方正在跑的验收。**延后到下一个冻结窗口**统一处理（见 §2）。 |
| R6 表格里 `lt2_acceptance_r4.py = 8,596 B / 664e13c6…` 的抄录 | append-only：**不改 R6**，以 R7 §3 的解释 + 本节 §3 的勘误标记为准。 |

## 2. 已修：`freeze_snapshot.py` 补齐 Codex R7 §2.2 的 6 步冻结流程

**问题（我自己发现的，此前未处理）**：我的哈希锁只做了 source-vs-manifest 与 snapshot-vs-manifest 两项，
**缺少** R7 要求的「一次读取产生 inventory」「三方回读」「manifest 自身 SHA256 + 全过程日志写入不可复用 run-id」「窗口内变化即放弃」。

**已实现**（`work\tools\freeze_snapshot.py`）：

```text
步骤2  一次读取 -> source_inventory（path/bytes/sha256）
步骤3  立即复制 -> snapshot/
步骤4  snapshot_inventory；写 manifest 后**回读**（UTF-8 + JSON 可解析）；
       manifest 自身 SHA256 -> manifest.sha256 侧车文件 + freeze_procedure.log
步骤5  freeze_procedure.log 写入本 freeze 专属 run-id（freeze 目录 append-only 不可复用）
步骤6  窗口结束前回读 source，任一变化 => status=ABANDONED_CODE_CHANGED_IN_WINDOW 且 exit 6
```

**自测证据**（`freeze-toolselftest-r7sixstep`，**工具自测产物，非验收冻结**）：

```json
{"status": "ACTIVE",
 "manifest_sha256": "b527c4263952ebef2fdc204ec944150953d7a8e6dc9bfd47e608c61c6d51e876",
 "three_way": {"source_ok": true, "snapshot_ok": true, "manifest_ok": true, "all_ok": true},
 "readback": {"manifest_utf8_ok": true, "manifest_json_ok": true},
 "window_drift": [], "window_owner": "pid-21860"}
```
`manifest.sha256` 与 `freeze_procedure.log` 均已生成；`py_compile` exit 0。

**安全性确认**：动手前我核对了两个在飞冻结的收录清单，`freeze_snapshot.py` **不在其中**
（收录 `lt2_production.py`/`lt2_sampler.py`/`tests_lt2_supervisor.py`/`rt_gate.py`/`lt2_acceptance_r4.py`/
`check_undefined_names.py`/`lt2_flake_hunt.py`），故改它不会作废实现方正在跑的验收。

## 3. R6 表格的正式勘误索引（Codex R7 §2.2 要求）

**索引登记**：`docs\TO_CODEX_record-20260914-r7-codex-r6-accepted-and-two-corrections.md` §3
是 `docs\TO_CODEX_record-20260914-r6-flake-reproduced-and-g1-vacuous.md` §1 表格的**正式勘误**。
勘误内容：R6 表格中的 `lt2_acceptance_r4.py = 8,596 B / 664e13c6e85fdac6…` 系**冻结前读取值**；
1402 manifest 与快照实际收录 `11,072 B / 85d58c898a004526995b5a78d99806e8cefcd931f2e24244644779d0067f25c4`。
原因：冻结窗口内发生并发编辑（R7 §3）。R6 原文不改写。

## 4. 新发现（本轮实测）：在飞冻结不满足 R7 的 6 步流程

用升级后的工具对实现方的两个冻结做漂移检测：

```text
freeze-20260914-165357-post-namespace-atomic-lock     -> INVALIDATED_BY_CODE_DRIFT
    漂移: lt2_acceptance_r4.py frozen=5d8f759899fae4b7 current=28b856be3b351a1b
    （该判废正确 => R7 第 6 条在实践中生效）

freeze-20260914-165457-post-namespace-atomic-lock-v2  -> MATCH（17:01:46 校验）
    顶层键缺: source_inventory / snapshot_inventory / window / window_drift / status
```

⇒ **v2 是用升级前的工具建立的，缺少 R7 §2.2 的 6 步证据**。
基于它的验收报告会被判证据不足。已要求实现方：宣布冻结窗口 → 用升级后工具建**新 freeze_id** →
**从该新快照**重跑两次正式验收 + 30 次隔离运行 + 测试前后四项校验。
（它已跑的 30 次隔离运行结果仍有参考价值，但**必须挂到新 freeze 下重跑才算验收信用**。）

另外确认：P0–P3 期间**生产脚本也变过**（`lt2_production.py` `1974a607…` → `c03e2d5a…`；
测试脚本 `101b6034…` → `f81cca25…`），因此 14:23 的 `freeze-1423` 与更早的 1402 都不能用于关闭门禁。

## 5. 状态

```text
freeze_snapshot.py            = R7_SIX_STEP_IMPLEMENTED_AND_SELFTESTED
R6 table erratum              = INDEXED（R7 §3 为正式勘误；R6 原文不改）
rt_gate reason 文本匹配（R4）  = DEFERRED_TO_NEXT_FREEZE_WINDOW（此刻改动会作废在飞冻结）
lt2r0_v2.py D1/D2/D3          = REGISTERED_AS_KNOWN_DEFECTS（按可追溯性要求不改脚本）
在飞验收冻结（165457-v2）      = MATCH 但不满足 R7 6 步 => 须以新 freeze 重跑
G1                            = NOT_PASS
G2/G3                         = REVALIDATION_REQUIRED
LT2 production                = BLOCKED
real COMSOL hard-stop drill   = DO_NOT_RUN（本轮）
```
