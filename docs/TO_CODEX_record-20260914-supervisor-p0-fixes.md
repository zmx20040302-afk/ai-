# TO CODEX — LT2 supervisor 两个 P0 + 两个 P1 修复记录（2026-09-14 第二轮）

- 依据：`TO_DEEPSEEK_HARNESS_页面文件授权与实时门禁复核回复.md` §5/§6/§7.1/§7.2/§7.3/§7.4/§8
- 约束遵守：**未运行任何 COMSOL / comsolbatch / mphserver**；**未改系统配置（未碰页面文件）**；
  未改 `AGENTS.md`/`WORKING_PLAN.md`/`rt_gate.py`/`tests_rt_gate.py`/`lt2r0_v2.py`；
  未提权、未重启。
- 本文件**取代** `TO_CODEX_record-20260914-supervisor-implementation.md` 第 1 节的哈希表（append-only，不覆盖原文）。

---

## 1. 交付物与哈希（引用时刻：2026-09-14 12:47:04）

| 文件 | 字节 | sha256 |
|---|---|---|
| `work\tools\lt2_sampler.py` | 10,397 | `d4b68ff19637a7a8300464eed8e85a185a2b68f36286108873c94d7ead19ed84` |
| `work\tools\lt2_production.py` | 85,747 | `d56d722ff1f2b51feb7ea35f31e3f73ae7efd5b8c6d0f914fad1598da96cfa00` |
| `work\tools\tests_lt2_supervisor.py`（新增） | 21,401 | `711f569a46c27c07a3ef58ba70d42e84b283832975fe8b9b0afd67278260d0d4` |
| `work\tools\rt_gate.py`（父 agent 维护，未改） | 9,466 | `e99e76b76db1cd413ec5961c5dbca8379bd4a03ced4ddb24b2fd1c303cf3f5db` |
| `work\tools\tests_rt_gate.py`（父 agent 维护，未改） | 9,455 | `d15dddc0d9c33c3e52c7a76542927607ccd80476f749caade2f56f849ae6febc` |

---

## 2. 改动摘要

### 2.1 P0-1：硬停现在**在运行期真正触发动作**（原来只是"实时判定、事后动作"）

原缺陷（Codex §7.1 认定）：supervisor 只查 `sidecar_health()`，不读 `state.verdict`；
worker watchdog 只设 `cancel_requested`，而主线程阻塞在 `study.run()`，
于是 `cancel_server()` 要等 study 返回才执行 —— 不是可用的实时中止。

修复后的判定与动作：

1. **supervisor 每轮同时检查** `sampler_state.verdict` + `reasons` + `worker_state.cancel_requested`
   + `sidecar_health`；`decide_next_action()` 判定顺序为
   `sampler_state.verdict → worker_state.cancel_requested → sidecar_health`。
   因此「sidecar 完全健康 + verdict=hard_stop」也会**立即**动作，等待停更不再必要。
2. 触发后按 §7.1 的顺序执行（全部落痕）：
   `freeze_new_delivery → save_trigger_sample → request_worker_end →`（宽限期）
   `verify_ownership → terminate_server → post_termination_verification → reclaim_worker`。
3. **worker 侧不再跨线程触碰 MPh client**：watchdog 只读 `sampler_state` 并写
   `worker_state.cancel_requested`。若 study 自行返回，则主线程做**同线程**清理。
4. **命名纪律**：动作如实命名为 **`verified_emergency_termination`**。
   记录里带 `naming_note` 明示：本架构无法证明能在另一线程安全取消阻塞中的 study，
   **不是**已验证的 COMSOL graceful cancel。
5. 归属核验三项：`port_owner_ok`（端口 owner PID）+ 进程启动时间（`StartTime.ToFileTime()`）
   + run_id 标识；**任一项不符即拒绝终止**并写 `REFUSED_identity_or_ownership_check_failed`。
6. 终止路径的全部外部副作用经 `TerminationDeps` 注入 ⇒ 可在不启动 COMSOL 的前提下做故障注入。

### 2.2 P0-2：child / attempt 证据隔离

- 目录约定：`<run_id>/child_00_attempt_1/{resource_timeline.jsonl,resource_timeline.csv,sampler_state.json,worker_state.json,checkpoint.json}`
  （`CHILD_DIR_FMT = "child_{idx:02d}_attempt_{attempt}"`）。
- **删除了 v1 里"worker 启动时清空时间线"的逻辑**；worker 若发现自己的 child 目录已存在且非空
  则**拒绝复用**并写 `<child>_refused.json`（append-only 保护）。
- supervisor **只在批次根目录写聚合 manifest**（`batch_manifest.json`），
  其中 `child_dirs[]` 列出每个 child 的目录、状态与各文件 sha256；不再写 run 根级的 checkpoint/时序。

### 2.3 P1-a：state 竞争 —— 用「单写者拆分」从结构上消除，而不是靠原子替换

v1 的错：worker 与 sidecar 都对同一个 `sampler_state.json` 做「读整个 JSON → 改 → 原子替换」。
原子替换**只能**避免半写文件，**不能**避免两个进程基于旧版本互相覆盖字段。已按 Codex 建议的第 1 种修法拆分：

| 文件 | 唯一写者 | 内容 |
|---|---|---|
| `worker_state.json` | combo-worker | pid / stage / combo / stop / cancel_requested / sampler_pid / server_identity |
| `sampler_state.json` | sidecar | last_sample_ts / sample_index / verdict / reasons / warnings / counters |
| `supervisor_signal.json` | supervisor | `request=graceful_worker_end` + 原因 |

每个文件只有一个写入者 ⇒ 跨进程读-改-写竞争**不存在**。
`worker_state` 的 `stop` 是控制通道（sidecar 只读），`sampler_state` 里保留 `worker_stop_seen` 回显。

### 2.4 P1-b：PID 获取与终止后二次确认

- server 启动后**优先用监听端口取 PID**：`server_pid_from_port()`（轮询 `port_owner_pid(2036)`，
  超时才回退 `find_pid()`），并把 `pid_source`（`port_owner` / `find_pid_fallback`）与等待秒数写进产物。
- `proc_identity()` 增加**父进程 PID**，并记录 `parent_is_worker`（父子关系）。
- 终止后二次确认 `verify_termination()` 四项：终止命令退出码、expected PID 消失、端口 2036 关闭、
  无意外的 `comsolmphserver`；**PID 与端口都带超时轮询**确认。

### 2.5 容差（§5）

`AREA_REL_TOL = BBOX_REL_TOL = 1e-6` 批准范围已落实为 `TOLERANCE_SCOPE` 常量，写进每个 checkpoint 的
`tolerance_evidence`，并且**每个 checkpoint 同时保存**：
冻结面积、当前面积、相对差、冻结 bbox、当前 bbox、两个容差、冻结证据 `run_id` + `path` + `sha256`、
冻结/当前 `intop5` 实体、比对调用串与错误。
另附 `analytic_geometry_comparison: null` 与说明：**不得**用该容差声称与解析几何一致，
也**不得**因 2πR² 的 0.271% 差异把回归容差放宽到 0.271%。

### 2.6 重跑策略（§6）

`classify_retry()` 实现分类；`run_supervisor()` 仅在 `retry=True` 时用 **attempt=2** 重跑一次（新 server、新目录、保留 attempt_1 全部证据）：

- **允许重跑一次**：`server_startup_transient`、`solver_exception_transient`（不伴随 LT2-C/哈希/资源违规）、`port_cleanup_timeout`（归属已核验且清理完成）。
- **拒绝重跑**：`resource_hard_stop`、`lt2c_gate_failure`、`hash_drift`、`checkpoint_problem`、`port_ownership`、`sampler_supervisor_integrity`、`unclassified`（fail-closed）。
- attempt 2 仍失败即写 `blocked_reason` 停止逻辑批；若与 attempt 1 同类错误，理由里显式注明**禁止第三次**。
- `--no-retry` 可关闭自动重跑。

### 2.7 前置门禁改为 §3.3 的 fallback 值

`PREFLIGHT_AVAIL_MB = PREFLIGHT_COMMIT_MB = 16384.0`（原 commit 13,500 已作废），
并新增 `ATTENDED_OPERATION = True` 写入产物。达不到就不启动；**不得降低数字迁就机器状态**。

---

## 3. 两个**实测新发现**（都由本次故障注入测试暴露，均为 Windows 行为陷阱）

### 3.1 `OpenProcess` 判定存活是错的（P1-b 的关键）

Windows 上进程被终止后，只要父进程（`subprocess.Popen`）**仍持有进程句柄**，
`OpenProcess` 依然成功 —— 用「能否 OpenProcess」判断存活会**永远为真**，
把成功的终止误判为「进程仍在」。
已改为 `GetExitCodeProcess(...) == STILL_ACTIVE(259)`。
（这是测试先失败 4 项、定位后才通过的；若不修，`verify_termination` 会永久判失败。）

### 3.2 终止后「立即查一次」也是错的

`Stop-Process` 返回 rc=0 之后，PID 与端口并不会在同一个瞬间消失。
已改为 `_wait_until()` 带超时轮询（PID 15 s / 端口 10 s / worker 10 s），
并把 `waited_s`、`timed_out` 一并留痕。

> 这两条正对应 §7.4「不能只调用 `Stop-Process` 就把 action 记为成功」。

### 3.3 测试自身踩的坑（记录以免重犯）

`TerminationDeps` 把外部依赖存为**实例属性**，子类若只定义同名方法会被父类
`__init__` 设的实例属性遮蔽 ⇒ fake 不生效，导致误判「拒绝终止」。
测试里改为赋实例属性。

---

## 4. §8 要求的 7 项故障注入测试 —— 逐项结果

命令：`python work/tools/tests_lt2_supervisor.py` → **exit 0，合计 29 项断言，通过 29，失败 0**

| # | 要求 | 结果 | 证据（实测输出摘要） |
|---|---|---|---|
| T1 | 模拟**长期不返回的 worker** | PASS | 用真实 `python -c time.sleep(600)` 替身；宽限期（2 s）内不退出 ⇒ 升级执行终止。steps=`freeze_new_delivery → save_trigger_sample → request_worker_end → verify_ownership → terminate_server → post_termination_verification`；worker 已回收且 `pid_absent_after=true` |
| T2 | sidecar 持续给样本并在**第 N 个**置 hard_stop | PASS | 真实 sampler 进程（`--simulate 8`）：JSONL 8 行；首个 `hard_stop` 在 `sample_index=4`；`sampler_state.verdict=hard_stop`，reason=`commit_hard_stop(2000.0 <= 4096.0 x6)` |
| T3 | 因 **gate verdict** 动作，**不是**等 sidecar stale | PASS | `health=ok`（`last_sample_ts` 新鲜）时 action 仍为 `hard_stop_enforce`，`source=sampler_state.verdict`；反例：停更时 `source=sidecar_health`；再反例：`worker_state.cancel_requested` ⇒ `source=worker_state.cancel_requested` |
| T4 | **4 个 child 的时序目录全部保留**、各自 sha256 可列 | PASS | 4 个 `child_0N_attempt_1/` 全部存在；时间线 sha256 各不相同（见第 5 节）；再跑 `child_03_attempt_2` 后 attempt_1 的 sha256 **未变**且与 attempt_2 不同 |
| T5 | 共享状态**不丢 hard-stop 信号** | PASS | worker 连续写 25 次自己的状态后，`sampler_state.verdict` 仍为 `hard_stop` 且判定仍触发；反向 sampler 连写 25 次后 `worker_state.cancel_requested=true`、`stop=false` 未丢 |
| T6 | PID / 启动时间 / 端口 owner 任一不符 ⇒ **拒绝终止** | PASS | T6a 端口 owner 为别的 PID ⇒ `REFUSED_identity_or_ownership_check_failed`，且目标进程**仍存活**；T6b 启动时间不符（`identity_match=false`）⇒ 拒绝且进程仍存活；T6c PID 未知 ⇒ 拒绝 |
| T7 | 终止后端口与 PID 的**二次确认** | PASS | 正向：`termination_command_exit=0`、`expected_pid_absent=true`、`port_closed=true`、`no_new_unexpected_comsolmphserver=true`、`verified=true`，并真实验证进程已消失；反向（注入 rc=1）：`verified=false` 且进程**确实仍存活**（证明反例有效） |

测试自身的安全核验（每次运行都会打印）：

```text
测试期间 comsolmphserver 进程 = []（必须为空）
```

---

## 5. 4 个 child 目录树 + 各自时间线 sha256

`work\runs\lt2-supervisor-selftest\`（**全部为模拟样本，无 COMSOL 求解**）：

```text
child_00_attempt_1/
    resource_timeline.jsonl   2670 B  27f33dd1de18c2d548f300276ab87602d040338ef920056d57a3c1cf5ad8645c
    resource_timeline.csv      563 B  4a7153d2817d2c9c50fb1c0aaa2770e68d8b776d45388a6ec294d779e9602c4d
    sampler_state.json         543 B  d86bd8d0338723d4d54c5b6d9e1860f44028e29c9001f86714b6957bad28b3d6
    worker_state.json          154 B  7f28a5b24e0aabdc0712a01bfee91f0ca72e0c8531a0b2bb55744c3359aa9ed4
child_01_attempt_1/
    resource_timeline.jsonl   2675 B  4da582263a936304945593f64091457b1b2a9cfb6e619b75fddbd3bf9d501561
    resource_timeline.csv      568 B  5bb60631061cd0d8dadf0d4c6f91720bf754c0f492769b1bf0823216160089a8
    sampler_state.json         544 B  3296725254766ed0b9be19961b82535cdade182ec904450d0928b62112d653c8
    worker_state.json          155 B  44d67344e9c5352d27ac062040b30f4a706c87c8791a64e4965aa3a5c90dbc2a
child_02_attempt_1/
    resource_timeline.jsonl   2670 B  98d1133e8d6ee245065b1bb36c302a655835929f773315b53fa1ecd8218a0447
    resource_timeline.csv      563 B  9de70f32df4d9f695eff7e5e755da73bed2c7cd5f44c74ba8900431c20bf2ca6
    sampler_state.json         543 B  4d74c0c1f54e99483d091e2053c3bd7113ddf211e1b3baa40bfd0c217f418162
    worker_state.json          154 B  dd067a6450bfff75ea9f5e77624f0ddbbab07d9d6bb4d5c512ccb08645bbd817
child_03_attempt_1/
    resource_timeline.jsonl   2675 B  514291c93aaf9d42b87e608dbfe50b33d8f5ffca6369189d504539fb3473c437
    resource_timeline.csv      568 B  8c13134299b3bad1239310afe11840a6266ff8ccc3f146379645d57b97a9b75f
    sampler_state.json         544 B  778e3e07f0079ca1c4bdc8b0031f6be2cc85e7380442369efaf7ab4acb7b04c5
    worker_state.json          155 B  31174bb027fd2c16dc1d7dbf9c1459149f196b28508bc9270fd3be88d893209d
child_03_attempt_2/                      ← §6 重跑隔离：attempt_1 未被覆盖
    resource_timeline.jsonl   1481 B  44742d3ac36c92a5604a0b736a6ffc125ca0ecd0809993ce1bc2a97eafa72004
    resource_timeline.csv      386 B  f93157114a3530dfd39e46f996499958bdf82c728f96b8030c29238071d46d5a
    sampler_state.json         444 B  ceed837a7c8b64e6b85781cfea91c328d4ef9ca5ea08e02a9b8346cbbfed2451
child_04_attempt_1/                      ← T5 状态竞争测试
    sampler_state.json         174 B  2f5b83927ae3ba01c9a1c1778a7e8083557af826a86cf0668c0db9272474e665
    worker_state.json          178 B  7c1cc6ba291df10bce1303479912870c38a475e140975c69fd0d95e3decef32f
child_05_attempt_1/                      ← T6a/b/c 拒绝终止（**故意不含时间线**：无 sampler 运行）
    hard_stop_trigger.json     208 B  27d81a266211da0a56186b00d2b582ffcd2c412c39d67684ddce637e29c18a95
    supervisor_signal.json     132 B  5baf7a9e1b3da8645f28a094d0affc697b448acba6ba834d9ed89ecd1f7b70e6
child_06_attempt_1/                      ← T7a 二次确认（正向）
    hard_stop_trigger.json     327 B  cff661764aed3fe3af141cdfe12dcef17475ed101c2b7146bc87590605326318
    supervisor_signal.json     132 B  0aa4a7f4238e3862425550c9540ca06c1812f7fdf04447ef41f4f990a81d6d71
child_07_attempt_1/                      ← T7b rc≠0 反例
    hard_stop_trigger.json     322 B  e4f22af5de8d0ea287b99231407411fa28d889f9cafb4efd64c89e3c04d54b3f
    supervisor_signal.json     132 B  9a4d458c88530b402793016a8f7ce97fdf994240a0664ffac21f3e1fe585815d
```

**4 条 attempt_1 时间线互不相同、且后跑的 child 没有删除先跑的**（T4 断言直接验证）。

---

## 6. 拒绝终止测试结果（§8 第 6 项）

| 场景 | 注入 | 结果 |
|---|---|---|
| T6a 端口 owner 是别的 PID | `port_owner_pid → expected+12345` | `refused.reason = REFUSED_identity_or_ownership_check_failed`；`termination.performed=false`；**目标进程仍存活**（真实检查 `proc_exists=true`） |
| T6b 启动时间不符 | `proc_identity.start_filetime +1` | `ownership_checks.identity_match=false` ⇒ 拒绝；**目标进程仍存活** |
| T6c PID 未知 | `expected_pid=None` | 拒绝（`port_owner_ok` 返回 `expected_pid_unknown`） |

**拒绝路径不执行任何终止命令**，只写 `hard_stop_trigger.json` 与 `supervisor_signal.json`。

## 7. 终止后二次确认结果（§8 第 7 项）

正向（真实终止自建替身进程，`Stop-Process -Force` rc=0）：

```json
{"termination_command_exit": 0, "expected_pid_absent": true, "port_closed": true,
 "no_new_unexpected_comsolmphserver": true, "verified": true}
```

并额外做**独立的真实检查**：`proc_exists(pid) == False`（进程确已消失）。
反向（注入终止命令 rc=1）：`verified=false`、`expected_pid_absent=false`，且进程**确实仍存活** ——
证明"只调用 `Stop-Process` 不能记为成功"这条要求已被测试真正覆盖。

---

## 8. 仍未验证清单（U1–U6 逐项更新）

| # | 状态 | 说明 |
|---|---|---|
| **U1** | **仍未见真机**（措辞已按裁定更正） | 真实 COMSOL 下 `verified_emergency_termination` 路径**未实测**。已实现并可被故障注入测试驱动；但对真实 `comsolmphserver` 的终止、以及"study 阻塞期间终止 server 后 study 报什么错、worker 如何退出"仍未知。**明确不称其为 graceful cancel** |
| U2 | 仍未见真机 | `Stop-Process` 对真实 `comsolmphserver` 的分支（对自建替身已实测通过）；`--force`/树状子进程是否需 `/T` 未验证 |
| U3 | 仍未见真机 | supervisor 升级路径本身已被 T1 用真实阻塞 worker 覆盖（含 worker 回收）；但"真实 worker 阻塞在 study.run() 时被终止"未验证 |
| U4 | 仍未见真机 | LT2-C 从未在真实 `fin` 几何上跑过。本轮新增：容差证据字段结构已实现，但**从未用真实面积/bbox 填过** |
| U5 | 仍未见真机 | 「每组合一个全新进程 ⇒ 全新 `mph.Client`」仍未在真机证实。本轮改动**加强了**该假设的必要性：worker 不再跨线程碰 client，因此单会话单 client 的约束更容易满足 |
| U6 | 已补强 | 采样节奏与停更判定：T2 用真实 sampler 进程（瞬时）与真实 `sidecar_health` 覆盖了"verdict 翻转 + 健康判定"，但**真实 5 s 计时下的停更**仍只有 `tests_rt_gate.py` 的 T2 覆盖 |

**本轮新增未验证**：

- U7 `server_pid_from_port()` 对真实 `comsolmphserver` 的端口归属取值（本机 2036 无 server，未实测），
  以及 `parent_is_worker` 父子关系判断在真实 MPh 启动链上的取值。
- U8 真实 `checkpoint.json` 里 `tolerance_evidence` 的数值（无真实求解 ⇒ 未填过）。

## 9. 已知风险

| # | 风险 |
|---|---|
| R1 | **LT2 生产仍 BLOCKED**：授权口径已按 §3.3 改为双 16,384 MB，本机当前观测远达不到；且页面文件授权状态为 `PENDING_USER_APPROVAL`，本轮**未触碰**页面文件 |
| R2 | `rt_gate.py`/`tests_rt_gate.py` 由父 agent 维护，本文哈希需标注引用时刻（12:47:04） |
| R3 | 容差 1e-6 的批准范围严格限定为冻结控制面重建一致性；已写进 `TOLERANCE_SCOPE` 与每个 checkpoint |
| R4 | `--force-reuse-run-id` 仍是显式逃生阀（打印 `[WARN]` 且留痕） |
| R5 | 自动重跑的分类是**基于错误字符串/阶段**的启发式判断，不是强类型；`unclassified` 一律 fail-closed 不重跑 |
| R6 | 测试中被真实终止的进程是本测试自建的 `time.sleep` 替身；测试结束已核验无残留（`comsolmphserver=[]`，无 `time.sleep` 替身残留） |

---

## 10. 状态用词

```text
LT2-P0-1 实时硬停动作      = IMPLEMENTED_AND_FAULT_INJECTION_TESTED（真机未测）
LT2-P0-2 child/attempt 隔离 = DONE
LT2-P1-a state 竞争        = FIXED_BY_SINGLE_WRITER_SPLIT
LT2-P1-b PID/终止后验证    = DONE（含两处 Windows 陷阱修正）
§8 七项故障注入测试        = 29/29 断言通过，exit 0
LT2 生产开跑               = 仍 BLOCKED（双 16,384 MB 门禁 + PENDING_USER_APPROVAL）
真机 COMSOL 硬停演练        = NOT_STARTED（需 Codex 放行，且应使用早触发的小模型）
```
