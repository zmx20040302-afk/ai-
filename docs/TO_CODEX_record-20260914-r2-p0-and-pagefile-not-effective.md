# 裁定记录（append-only）续 — 2026-09-14 第二轮 Codex 回复的接受、事实更正与 P0 待修

- 来源裁定：`TO_DEEPSEEK_HARNESS_页面文件授权与实时门禁复核回复.md`
  sha256 `0c5181a6d9e1f5be6eebf467b6b05ed08ebc529e726cd8410a5c2274bf9c322b`
- 前置：`docs\TO_CODEX_record-20260914-rulings-accepted.md`（本文件是其 append-only 续篇，不覆盖）
- 本文件同时记录一项**与裁定不一致的实测事实**（页面文件未生效），见 §1。

---

## 1. 实测事实：页面文件设置已登记，但**未生效**；机器今天没有真正重启过

用户告知「我已经完成重启」。我按承诺复核，**结果与告知不符**，如实记录：

```text
LastBootUpTime        = 2026-09-12 15:02:59
已运行                = 45.6 小时（当前时间 2026-09-14 12:40）
近 24 小时内核启动事件 = 0 条（Microsoft-Windows-Kernel-Boot / 6005,6006,6008,1074 均无）
HiberbootEnabled      = 1   ← 快速启动（混合关机）开启
```

设置侧**已正确登记**，但**尚未生效**：

| 项 | 期望 | 实测 | 判定 |
|---|---|---|---|
| `AutomaticManagedPagefile` | False | **False** | ✓ 已登记 |
| `Win32_PageFileSetting` 初始/最大 | 12288 / 12288 MB | **12288 / 12288 MB** | ✓ 已登记 |
| `Win32_PageFileUsage` 已分配 | 12288 MB | **4,873 MB** | ✗ 未生效 |
| `commit limit` | ≈44,478 MB | **37,063.0 MB** | ✗ 未生效 |
| C 盘可用 | 约 188 GB | **195.2 GB** | ✗ 未生效（文件未重分配） |

**结论**：页面文件改动**没有生效**，因此**不得**按「已调整」继续；门禁口径仍按未调整状态对待。

**最可能的原因**：`HiberbootEnabled = 1` 时，**「关机」再开机是从休眠恢复内核会话**，
`LastBootUpTime` 不变，页面文件的重新分配也不会发生。→ 需要的是**「重启」**（开始 → 电源 → 重新启动），
`重启` 即使开着快速启动也会走完整引导；或先关闭快速启动再关机开机。

**我不会自行重启**（无管理员权限，且裁定明确禁止）。此项退回用户执行。

---

## 2. 更正：Codex 判定的「无可追溯用户授权」与事实不符

裁定 §1/§2.1 判定：

```text
user_pagefile_approval = not_yet_observed_in_this_thread
pagefile_change_status = PENDING_USER_APPROVAL
```

**该判定基于不完整信息**（Codex 只能看到我发出的三份文档，看不到本会话内的交互记录）。
本线程内**存在**可追溯的用户授权：

```text
证据 1（明确选择）：我以结构化提问「是否批准把页面文件初始分配提到 ≥12 GB（需重启）？」向用户征询，
                    用户选择了「批准：调大页面文件到 ≥12 GB（推荐）」。
证据 2（执行确认）：用户随后告知「我已经完成重启」。
证据 3（客观旁证）：`AutomaticManagedPagefile=False` 与 `12288/12288` 已实际写入系统
                    —— 非授权方不可能产生这两个改动的结果。
```

因此正确状态是：

```text
user_pagefile_approval = GRANTED（本线程内明确选择 + 执行确认 + 系统侧旁证）
pagefile_change_status = REGISTERED_NOT_YET_EFFECTIVE   ← 见 §1
```

**但我接受裁定中的过程性批评并已改进**：我此前在 `TO_USER_pagefile-change-20260914.md` 里写了
「用户明确批准」却**没有记录授权来源与原文**，导致外部审阅方无法核验。这是我的记录缺陷。
今后任何授权类事实必须同时记录：**授权来源、原话摘要、时间**。
（本节即为该改进的示范。）

---

## 3. 接受的技术性更正

### 3.1 「本机理论上限 11,759.6 MB」措辞不严谨 —— 接受

裁定 §3.2 正确：`37,055.6 − 25,296 = 11,759.6` 得到的是**该快照背景负载下的可用 commit**，
不是本机不变的理论上限；关闭应用后基础 committed bytes 会下降，可用量会上升。
**我的表述作废**，改为：

> 在已观测的当前应用负载下，commit 可用量没有达到 13,500 MB；若不调整页面文件，
> 必须显著降低背景提交量才可能满足更高前置门禁。

（这也是我该避免的错误类型：把单次快照的派生值说成结构常量。）

### 3.2 回退前置门禁重定 —— 接受

```text
fallback_preflight_commit_available_mb  >= 16384
fallback_preflight_physical_available_mb >= 16384
server_lifecycle_size = 1
attended_operation    = true
```

推导：COMSOL commit 增量 11,112 + 运行硬线 4,096 + 背景波动余量 1,024 = 16,232 → 向上取整 16,384。
**这是 fail-closed 启动门槛，不是保证值**；达不到就不启动，不得下调数字来迁就机器状态。
不改页面文件时：只允许有人值守、一组合一 server、每个组合启动前重测两项余量、
不允许过夜无人值守 72 组合任务、**不得把「曾经成功跑过」当成后续资源安全保证**。

### 3.3 容差批准范围 —— 接受

`AREA_REL_TOL = BBOX_REL_TOL = 1e-6` 批准，**但仅限「冻结控制面重建一致性门禁」**。
不得用它声称与解析几何一致；报告里 Ptot 面积与 2πR² 差 0.271% 是**另一个问题**，
不得据此把回归容差放宽到 0.271%。
依据（裁定直接统计 72 组二级预检）：area 唯一值 1 个、相对跨度 0、bbox 唯一值 1 个。
每个 checkpoint 必须同时保存：冻结面积值 / 当前面积值 / 相对差 / 冻结 bbox / 当前 bbox /
容差 / 冻结证据 run_id 与 sha256。

### 3.4 失败重跑策略 —— 接受

允许**可判定为瞬态**的单组合失败自动重跑**最多一次**（新 server、新 attempt 标识、
保留第一次失败证据）。允许：server 启动瞬态失败、COMSOL 连接中断、不伴随 LT2-C/哈希/资源违规的
求解异常、归属已核验且清理完成后的端口清理超时。
禁止：资源硬停、LT2-C 失败、哈希漂移、checkpoint 重复/损坏/越界、端口归属未知或属他进程、
sampler/supervisor 完整性失败、attempt 2 重复同一瞬态错误。
第二次仍失败 → 写 `blocked_reason` 停止逻辑批，**不得第三次自动重跑**。

---

## 4. 接受的两个 P0 与两个 P1（`lt2_production.py`）

### 4.1 P0-1：硬线判定不能在 `study.run()` 阻塞期间真正触发取消

裁定查明：sidecar 能每 5 s 算出 `verdict=hard_stop` 并写 state，但
（a）worker watchdog 只设 `cancel_requested`，`cancel_server()` 要等 `study.run()` 返回才被调用；
（b）**supervisor 只检查 `sidecar_health()`，根本不读 `state.verdict`**。
→ 我此前把它称为「实时中止」是**过度声称**，实际是「实时判定、事后动作」。**接受，列为 P0。**

修复要求：supervisor 每轮同时检查 `sidecar health + state.verdict + state.reasons + cancel_requested`；
`verdict==hard_stop` → 立即冻结新投递、保存触发样本与身份信息、请求 worker 正常结束，
宽限期后若 study 仍阻塞则核对归属后终止 server、回收 worker、验证端口关闭与进程消失。

**命名纠正（接受）**：既然无法证明能在另一线程安全调用同一 MPh client 取消阻塞中的 study，
可靠动作应命名为 **`verified_emergency_termination`**，**不得**称为「已验证的 graceful cancel」。

### 4.2 P0-2：后续 child 会覆盖前一 child 的完整时间线

worker 复用同一 `resource_timeline.jsonl/csv` 与 `sampler_state.json`，且启动时删除时间线
→ 逻辑批第二个组合会覆盖第一个的原始时序，最终只剩最后一个 child 的完整资源文件；
checkpoint 里的摘要不足以满足「每个 server 生命周期保存完整时序」。
**接受，列为 P0。** 改为 `<run_id>/child_00_attempt_1/…`、`child_01_attempt_1/…`，
supervisor 只在批次根目录写聚合 manifest，不得删除/复用/覆盖前一 child 的证据。

### 4.3 P1-a：共享 state 的竞争写入

worker `set_state()` 与 sidecar `merge_state()` 均为「读整份 JSON → 改 → 原子替换」，
跨进程无锁 → 会基于旧版本互相覆盖字段。atomic replace 只防半文件，**不防竞争**。
**接受**，按裁定择一修（状态分文件 / sidecar 只 append 由 supervisor 读末条 / 加锁 + 版本号）。
禁止把 atomic replace 描述为「无竞争」。

### 4.4 P1-b：PID 获取与终止后验证

`find_pid()` 取「最新 `comsolmphserver`」仍是启发式；应优先用 `port_owner_pid(2036)` 取 PID，
并记录启动时间与父子关系。终止后必须二次验证：expected PID 消失 / 端口 2036 关闭 /
无新的意外 `comsolmphserver` / 终止命令退出码。**不得**只调 `Stop-Process` 就记为成功。
**接受。**

---

## 5. 测试结论的降级（接受裁定 §8）

裁定**不接受**把已有测试概括为「实时 supervisor 已完成」。**我接受并撤回该表述**：
已通过的 33 项只证明**纯逻辑判定**与阈值连续样本语义，**没有覆盖**关键链路
（sidecar 存活 + hard verdict → supervisor 在 worker 阻塞时动作 → 归属核验 → 终止 server →
回收 worker → 端口关闭 → blocked checkpoint 保留）。

必须补的 7 项模拟故障注入测试（不启动 COMSOL、不用真实内存压力）已在派工中：
长期不返回的 worker；第 N 个样本置 hard_stop；验证动作由 **gate verdict** 而非 sidecar stale 触发；
4 个 child 时序目录全部保留；共享状态不丢 hard-stop 信号；PID/启动时间/端口 owner 任一不符即拒绝终止；
终止后端口与 PID 二次确认。

之后才允许一次**真实 COMSOL 硬停演练**——用安全、早触发的模拟门禁或可快速取消的小模型，
**不得**把真实机器内存压到危险水平来触发。

---

## 6. 事实更正：当前不是「无可追溯授权」，但确实「未生效」

```text
LT1                   = PASS_WITH_LIMITATIONS
LT2-R0 v2 measurement = PASS
LT2-R0 v2 safety gate = FAIL
pagefile_change       = REGISTERED_NOT_YET_EFFECTIVE（授权已在 §2 记录；需用户执行「重启」）
LT2 production        = BLOCKED_BEFORE_PRODUCTION
```

执行顺序（裁定 §9，已按本机事实调整第 8/9 步）：

```text
[x] 1. append-only 更正授权状态                     （本文件 §2，用事实更正而非降级）
[~] 2. 修复 supervisor 不读 gate hard-stop 的 P0-1   （派工中）
[~] 3. 每 child/attempt 的状态、时序、checkpoint 隔离（派工中）
[~] 4. 消除共享 state 竞争                          （派工中）
[~] 5. port owner PID 取代 find_pid + 终止后验证      （派工中）
[~] 6. 阻塞 worker + hard verdict 的端到端模拟测试    （派工中）
[~] 7. 一次性、分类重试策略                          （派工中）
[ ] 8. 用户执行「重启」（**不是「关机」再开机**，因 HiberbootEnabled=1）→ 我复核 commit limit
[ ] 9. 新 run-id 做 (0.8,2) 资源确认 + U1/U5 验证
[ ] 10. 全部通过后运行首个「逻辑批 4、每组合独立 server」生产批
```

---

## 7. P0/P1 修复的独立复核（2026-09-14 12:48，父代理亲自核验）

实现方报告「2 个 P0 + 2 个 P1 已修、§8 的 7 项测试全绿（29/29）」。**我逐项复核如下**：

### 7.1 复核通过的部分

| 项 | 我的核验方式 | 结果 |
|---|---|---|
| 三个脚本哈希 | 自算 sha256 | 全部一致（`d56d722ff1f2b51f` / `d4b68ff19637a7a8` / `711f569a46c27c07`） |
| `rt_gate.py`/`tests_rt_gate.py` 未被改动 | 自算 | `e99e76b7…` / `d15dddc0…`，与上轮一致 ✓ |
| 两套测试 | **自己重跑** | `tests_lt2_supervisor.py` exit 0；`tests_rt_gate.py` 33/33 exit 0 |
| P0-1 supervisor 读 verdict | 读代码正则 | `decide_next_action` 确含 verdict ✓；命名 `verified_emergency_termination` ✓ |
| P0-2 不再删时间线 | 读代码正则 | 无 `unlink/rmtree/remove(resource_timeline)` ✓ |
| P1-a 单写者拆分 | 读代码 | 三份 state 齐备（`worker_state`/`sampler_state`/`supervisor_signal`）✓ |
| 双 16,384 门禁 | 读代码 | 存在 ✓ |
| 未运行 COMSOL | 现场探测 | `comsolmphserver 0`、`comsolbatch 0`、端口 2036 CLOSED ✓ |

### 7.2 我实测出的三个缺口（已退回修复，尚未关闭）

**G1（重要）自测产物的哈希不可复现。** 实现方报告了 4 个 child 的 `resource_timeline.jsonl` sha256；
我算出来的**5 个全部不同**（字节数完全一致）。原因：该 jsonl 每行含**墙钟时间戳**
（首行实测 `2026-09-14T12:48:41`），自测每次运行重新生成样本 ⇒ 内容变 ⇒ 哈希变。
**我按说明自己跑了一次自测，就把它的那批哈希全部覆盖了。**

后果：Codex §10.B 要求的「4 child/attempt 目录树及各自时间线 SHA256」作为证据，
**第三方无法复算**；任何人重跑一次都会得到不同哈希，看上去像篡改或声称不实
（我自己就先当成异常查了一轮）。→ 要求加 `--fixed-timestamps`/`--seed` 模式使产物逐字节可复现，
并现场演示「同命令连跑两次哈希相同」；默认墙钟模式必须显式标注不可复现。

**G2 `batch_manifest.json` 从未产出。** 实现方称「supervisor 只在批次根写 `batch_manifest.json`
（含每个 child 的目录与各文件 sha256）」。源码 L1476 确有该写入，但全盘搜索
`work/runs/**/batch_manifest.json` → **0 个**；`lt2-supervisor-selftest\` 批次根**无任何文件**。
说明该路径在自测中从未被触发 → 要求要么在故障注入里真正走通并产出该 manifest，
要么明确写成「仅 supervisor 完整路径会写，故障注入未覆盖」。**不得写成已完成。**

**G3 child/attempt 目录完整性不一致。** 实测 `lt2-supervisor-selftest\` 下有 **8 个** child 目录，
形态不齐：`child_00..03_attempt_1` 各 4 个文件；`child_03_attempt_2` 只 3 个（**缺 `worker_state.json`**）；
`child_04_attempt_1` 只有两个 state；`child_05..07_attempt_1` 只有 `hard_stop_trigger.json` +
`supervisor_signal.json`。→ 要求说明每个 child/attempt **应当**包含哪些文件、缺失是否合法，
并在报告中**如实覆盖全部 8 个**，不要只列前 4 个造成「只有 4 个 child」的误读。

### 7.3 沉淀进环境事实的两条 Windows 陷阱（已写入 `AGENTS.md` §3）

实现方在自测中踩到并修复，我确认其价值，已固化：

1. **不能用 `OpenProcess` 判进程存活**：目标被终止后，只要父进程（`subprocess.Popen`）仍持有句柄，
   `OpenProcess` 依然成功 ⇒「能否打开」恒为真，会把成功终止误判为失败（实测导致 4 项自测假失败）。
   正确：`GetExitCodeProcess(h) == STILL_ACTIVE(259)`。
2. **终止后不能只查一次**：`Stop-Process` 返回 rc=0 后 PID 与端口不会立刻同时消失，
   必须带超时轮询（实测 PID 约 15 s / 端口约 10 s），并留痕 `waited_s`/`timed_out`。

### 7.4 状态

```text
LT2-P0-1 = IMPLEMENTED_AND_FAULT_INJECTION_TESTED（真机未测；U1 仍开放）
LT2-P0-2 = CODE_DONE，但证据可复现性待修（G1）、聚合 manifest 未验证（G2）、目录完整性待说明（G3）
LT2-P1-a = FIXED_BY_SINGLE_WRITER_SPLIT
LT2-P1-b = DONE
§8 七项测试 = 29/29 exit 0（其中「目录树 + 哈希」类证据受 G1 影响，暂不可第三方复算）
真机 COMSOL 硬停演练 = NOT_STARTED（等放行；应用早触发模拟门禁或小模型，禁止压真实内存）
LT2 production = BLOCKED_BEFORE_PRODUCTION
```

**仍未验证（U1–U8）**：U1 真实 COMSOL 下 `verified_emergency_termination` 全路径未测（明确不称 graceful cancel）；
U2 对真实 `comsolmphserver` 的 `Stop-Process`（替身已过）；U3 真实 study 阻塞期间被终止的行为未测；
U4 LT2-C 与 `tolerance_evidence` 未用真实几何填过；U5 单会话单 client 未真机证实（本轮改动使其更可行）；
U6 真实 5 s 节奏下的停更仍仅由 `tests_rt_gate.py` T2 覆盖；U7 `server_pid_from_port()` 在真实 MPh 启动链上的
取值与 `parent_is_worker` 未测；U8 真实 `tolerance_evidence` 数值未填过。
