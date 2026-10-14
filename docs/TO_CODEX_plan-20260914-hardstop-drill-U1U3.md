# LT2 硬停演练（U1–U3）执行方案 —— **仅准备，尚未执行**

- 日期：2026-09-14
- 授权状态：**已授权「准备」**（写方案 + 无 COMSOL 回归）；**未授权执行真实 COMSOL 硬停演练**，
  等父 agent 拿到用户时点后另行确认。**本文件不含任何已执行的演练运行。**
- 目标冻结：`freeze-20260914-2040-post-guard-persistent`
  （manifest `1c87385b1cab54188c5d7d46075074d323d9442dc2a4874c8df5568cb74f9ce2`；
  `lt2_production.py` = `81936aeb0b5d42cbfdef5f973ba67c0abc9c21706d83dbd6cd1fe49cbf084f8a`，153,287 B）
- 前置：r3d 已通过（23/23 + 六项额外核对），见 `docs/TO_CODEX_report-20260914-r3d-resource-confirm-pass.md`

---

## 0. 本演练要证明什么（U1–U3）与对应证据字段

| 编号 | 目标 | 落地证据（必须能从产物读出） |
|---|---|---|
| **U1** | **全路径**：触发 → 归属核验 → 终止 → 二次确认 → worker 回收 | `termination_trigger.json`（顶层 `trigger_kind/enforced_by/is_drill_run`）+ `termination_rec.steps` 完整序列 + `ownership_checks` + `post_verification` |
| **U2** | **对真实 `comsolmphserver` 的终止** | `steps` 含 **`terminate_server`**（`command.rc=0`）+ 二次确认四项 + 身份/端口归属核验 |
| **U3** | **study 阻塞期间被终止后的行为** | 触发时刻 worker 仍阻塞在 `study.run()`；`worker_error.json` 带 `stage_at_error`；worker **未**声称 graceful cancel（`naming_note`）；`cancel_record` 记录"worker 只记触发、终止由 supervisor 执行" |

---

## 1. 确切命令（建议原样使用）

```powershell
$py   = "C:\Users\zmx\Desktop\memsharness\work\.venv\Scripts\python.exe"
$snap = "C:\Users\zmx\Desktop\memsharness\work\runs\lt2-supervisor-acceptance-freeze-20260914-2040-post-guard-persistent\snapshot"
$env:PYTHONDONTWRITEBYTECODE = "1"        # + -B：禁止往只读快照写 __pycache__
$run  = "lt2-drill-hardstop-u1u3-<YYYYmmdd-HHMM>"     # 新 run-id（绝不复用 r3/r3b/r3c/r3d）

$argv = @("-B", "$snap\lt2_production.py",
          "--run-id", $run,
          "--role", "supervisor",
          "--combos", "[[0.8,2]]",
          "--freqs", "5", "--expect-freq-count", "1",
          "--drill", "--ws-hard-stop-mb", "5000",
          "--freeze-id", "freeze-20260914-2040-post-guard-persistent")
$p = Start-Process -FilePath $py -ArgumentList $argv -NoNewWindow -Wait -PassThru `
     -RedirectStandardOutput "<证据目录>\drill_stdout.log" `
     -RedirectStandardError  "<证据目录>\drill_stderr.log"
"exit_code=" + $p.ExitCode
```

### 为什么是这些取值（逐条给依据，不是拍脑袋）

| 参数 | 取值 | 依据 |
|---|---|---|
| `--drill` | 必给 | 无 `--drill` 却传三个硬停阈值 ⇒ **exit 9 直接拒绝**（`main()` 第 2714–2719 行；T16a 已验）。这也是"演练阈值绝不误用于生产"的那道闸门 |
| `--ws-hard-stop-mb` | **5000** | 由 r3d/r3b **实测 WS 轨迹**反推：启动 1 个样本 695.6 / 571.9 MB；solve 期前 8 个样本 1370.9 → 2203.6 → 2624.5 → 3012.8 → 3997.6 → 4458.1 → 4888.0 → **5502.7**；峰值 11,149.5。⇒ 5000 在 **solve 期内约第 7–9 个样本**被跨过（采样间隔 5 s ⇒ 触发约在 solve 开始后 **35–45 s**），而完整求解需 **763.8 s** ⇒ **触发时 worker 必然仍阻塞在 `study.run()`**（U3 成立）。而加载/启动期 WS < 1,000 MB ⇒ **不会在加载阶段误触发**。且 `consecutive_samples=2` ⇒ 需连续 2 个样本越线才触发 |
| `--freqs 5` + `--expect-freq-count 1` | 单组合单频点 | 缩短**收尾**开销。**`--expect-freq-count 1` 必须给**：③ 的 fail-closed 会因「1 ≠ 默认 7」**拒绝启动**（exit 10），且该期望值会下传给 worker。这条本身也是一次真实演练：证明收紧后的解析器在生产/演练两条路径上都按同一口径把关 |
| 不加 `--avail-gate/--commit-gate` | 前置门禁照常 | 与 r3b/r3c/r3d 同口径：`avail ≥ 16,384 MB` 才能启动（启动前我会再实测一次） |
| 不加 `--fixed-timestamps` | 真实墙钟 | 演练要的是真实时间线；确定性时钟只用于自测 |
| 不加 `--worker-role` | 用**真** worker | 默认 `combo-worker`（会 `import mph` 并起真实 server） |
| 不加 `--max-combos/--batch-size` | 默认 | 只给 1 个组合 ⇒ 只跑 1 个 child；`server_lifecycle_size=1` 串行不变 |
| `-B` + `PYTHONDONTWRITEBYTECODE=1` | 必给 | 否则 worker 会在**只读快照**里创建 `__pycache__` ⇒ `--verify-snapshot` 的**精确文件集**校验会判 `SNAPSHOT_CORRUPTED` |
| 后台作业 | 必给 | 演练含真实求解，MCP/工具调用会超时 |

---

## 2. 预期结果清单（逐项，含依据）

### 2.1 批次级

| 项 | 期望 | 依据 |
|---|---|---|
| 退出码 | **6** | `run_supervisor` 末行 `return 0 if result["status"] == "PASS" else 6`；child 因求解被终止而不 pass ⇒ 聚合判据不全真 |
| `status` | `BLOCKED_OR_LIMITED` | 同上 |
| `blocked_reason` | 非空，形如 `child_00_not_pass:worker_failed` | `supervise_child` 的 `status = status or ("worker_failed" if rc != 0 else "no_checkpoint")` |
| `aggregate_pass_conditions` | 多项 `false`（`all_children_pass`、`lt2c_quick_gate_pass_all` 等） | 这是**预期**：演练不是"通过判定"，而是"证明终止机制" |
| 三布尔 | `freeze_hash_pre_post_match` / `executed_from_frozen_snapshot` / `freeze_evidence_complete` **全 true** | 显式传了 `--freeze-id`，且从快照执行 |
| run 根新增 | **`DRILL_README.txt`**（含 `run_id` / `drill_thresholds` / `DRILL_NOTE`） | `run_supervisor` 在 `args.drill` 时写出（第 2468–2477 行） |
| `check_r3_conditions.py` | **不适用**：会故意失败 `not_a_drill_run`（另加 rows/资源类） | 该检查器是**正常资源确认**的判据集；演练另用 §2.2 判据 |

### 2.2 U1/U2/U3 判据

| 项 | 期望值 | 说明 |
|---|---|---|
| `termination_trigger.json` 顶层 | `trigger_kind="threshold_crossed"`、`is_hard_stop=true`、**`enforced_by="drill_gate"`**、**`is_drill_run=true`** | 顶层回显是为了"一眼可辨"（本轮已实测，见 §4） |
| 同一记录的 `trigger.enforced_by` / `trigger.is_drill_run` | 同上（同源） | 内层也保留 |
| `threshold_evidence.thresholds.ws_hard_stop_mb` | **5000.0**（演练值，对比 `defaults.ws_hard_stop_mb=12288.0`） | `resolve_thresholds` 只在 `--drill` 下应用并**同时留痕默认值与演练值** |
| `threshold_evidence.consecutive_required` | 2 | `GateEngine.consecutive_samples` |
| `threshold_evidence.reasons` | 含形如 `ws_hard_stop(<实测> >= 5000.0 x≥2)` | 连续样本越线由 `rt_gate.GateEngine` 判定 |
| `termination_rec.enforced_by` | `drill_gate` | 与触发记录同源 |
| `termination_rec.steps` | **应依次出现**：`freeze_new_delivery` → `save_trigger_record` → `request_worker_end` → **`verify_ownership`(ok=true)** → **`terminate_server`** → **`post_termination_verification`(ok=true)**（可含 `worker_reclaimed`） | 与**无 COMSOL 回归不同**：真机里 server 仍在、worker 阻塞在 solve ⇒ 第 4 步的自退出检查（`port_open==False 且 worker 已死`）**不成立** ⇒ 必然走到 `terminate_server` |
| `ownership_checks` | `port_owner.ok=true`、`port_owner_actual_pid == expected_pid`、`identity_match=true`、`run_id` 正确 | 归属核验不过会走 `refused: REFUSED_identity_or_ownership_check_failed` 且**拒绝终止**（此时演练**不算成功**，见 §5） |
| 二次确认四项 | `expected_pid_absent=true`、`port_closed=true`、`no_new_unexpected_comsolmphserver=true`、`termination_command_exit=0`，`verified=true` | `deps.verify()`；`Stop-Process -Force` 的 rc 期望 0 |
| `signals/<child>.signal.json` | **应存在**：`request="graceful_worker_end"`、`trigger_kind="threshold_crossed"`、`is_hard_stop=true` | 演练=真终止要求 ⇒ 与"正常收尾**不写** signals"形成对照 |
| `worker_returncode` | 期望**整数**（**1**）：worker 因 server 被终止在 `study.run()` 抛异常 ⇒ 写 `worker_error.json` ⇒ `return 1` | enforce 路径先做 worker 回收（≤20 s）再做 **5 s 有界等待** ⇒ 通常能拿到真实码。**若为 null 必须在报告中解释，不得当作通过** |
| `worker_error.json` | 存在；`stage_at_error` = **`"solve"`**；`error_type` 为异常类名 | U3 的核心证据：证明"终止发生在 study 阻塞期间" |
| `cancel_record`（worker 侧，最终进 checkpoint；无 checkpoint 时看 worker_state） | `trigger` 为 worker 自己观察到的 action；`naming_note` 明确"终止由 supervisor 的 `verified_emergency_termination` 执行" | worker watchdog **不触碰 MPh client**（§7.1），因此**不会有** worker 侧的 graceful cancel |
| 命名纪律 | 任何地方**不得**出现"已验证的 COMSOL graceful cancel" | `naming_note`；历史踩坑第 6 条 |
| 时间线 | 全部样本 `drill=true`、`drill_thresholds` 为 dict；末段 `verdict=hard_stop`；`stop_line` 事件可出现 | `lt2_sampler.py` 的 drill 标记 |
| child kind | `enforcement_probe`（无 checkpoint）或 `solve_attempt`（若恰好写了 checkpoint） | `describe_child_dir`；`enforcement_probe` 的必需项 = `worker_state.json` + `termination_trigger.json` ⇒ `inventory_ok` 可为 true |
| `retry_classification` | **`{retry: false, class: "drill_hard_stop"}`** | 演练**绝不**自动重跑；且不得混入 `resource_hard_stop` |
| 演练后冻结复核 | `--verify` **MATCH**、`--verify-snapshot` **MATCH**（drift 0） | 演练期间冻结不得漂移 |
| 禁止项 | 产物中不得有任何"真实资源越线"的表述；本 run **不得**用于资源放行判断 | `DRILL_NOTE` 已在触发记录/时间线/manifest/README 四处留痕 |

---

## 3. 演练 vs 正常收尾：对照表（**当前版本上仍然成立**）

| 字段 | **演练**（预期，真机） | **正常收尾**（r3d **实测**） |
|---|---|---|
| `trigger_kind` | `threshold_crossed` | `normal_completion_sidecar_exit` |
| `is_hard_stop` | **true** | **false** |
| `enforced_by` | **`drill_gate`** | `null`（未 enforce） |
| `is_drill_run` | **true** | `null`（不适用） |
| `enforced` | （动作即终止） | `false` |
| `decided.action` | `hard_stop_enforce` | `observe_normal_completion` |
| signals 文件 | **有**（1 个） | **无**（目录都不存在） |
| `terminate_server` 步骤 | **有** | 无 |
| 二次确认 | `verified=true` | 无（`termination == null`） |
| `worker_returncode` | 1（求解被终止） | 0 |
| `worker_error.json` | 有（`stage_at_error=solve`） | 无 |
| 批次退出码 | 6 | 0 |
| 判据适用 | U1–U3（§2.2） | `check_r3_conditions.py` 23 条 + 六项额外核对 |

**当前版本上的既验部分**（本轮无 COMSOL 回归，见 §6）：`enforced_by=drill_gate` / `is_drill_run=true` 的**顶层回显**、
`classify_enforced_by` 9 标签表、`retry_class=drill_hard_stop` 且 `retry=false`、signals 写出、时间线 drill 标记、
演练阈值证据 5000、以及"无真实 server 时**绝不**声称终止成功"——**11/11 通过**（在冻结快照上）。

---

## 4. 失败与回退处置

### 4.1 "真终止" vs "又一次假触发"的判定规则（必须先定，再跑）

```text
U1/U2 **达成**的充分条件（全部满足）：
  (a) signals/<child>.signal.json 存在（= 真写了终止要求）
  (b) termination_rec.steps 含 terminate_server 且 command.rc == 0
  (c) termination_rec.ownership_checks.identity_match == true 且 port_owner.ok == true
  (d) post_verification.verified == true 且 expected_pid_absent == true 且 port_closed == true
判定为「**假触发**」（= r3c 那种形态，演练无效）：
  signals 缺失，或 termination_rec 为空/`termination == null`，
  或落盘 trigger_kind == normal_completion_sidecar_exit，或 enforced_by != drill_gate
判定为「**保护生效但 U2 未达成**」：
  termination_rec.refused != null（归属/身份核验不通过 ⇒ **拒绝终止**）
  ⇒ 这时**不得**放宽核验、不得手工 kill；保存 refused 记录 + ownership_checks 后停止并上报
判定为「**部分达成**」：
  走到了 grace_period_self_exit（说明 server/worker 在宽限期内已自行结束）
  ⇒ 需在报告中区分"谁终止的"，并说明为何未出现 terminate_server（例如 worker 先崩、端口先关）
```

### 4.2 非预期行为的处置（一律：保留现场 + 停止 + 上报）

```text
1) **不清理、不重跑、不改代码**：run 目录、日志、时间线、触发记录、signals 全部原地保留；
2) 立即停止后续动作（不启动生产批次、不接着跑第二次演练）；
3) 记录三件套：run_id / 退出码 / 期望 vs 实测逐条差异（用 §2.2 的表逐行填）；
4) 若怀疑冻结漂移：立刻 `--verify` + `--verify-snapshot`，drift≠0 则本 run 判 INVALIDATED；
5) 只有在报告与根因写明之后，才谈是否用**新 run-id** 重跑（演练不得复用 run-id）。
```

### 4.3 演练后的残留检查（必须全过才算收尾干净）

```text
1) 无残留 server：Get-Process comsolmphserver → 空
2) 端口 2036 closed：Test-NetConnection 127.0.0.1:2036 → False
3) 无意外 server：post_verification.no_new_unexpected_comsolmphserver == true 且
   remaining/unexpected pids 均为 []
4) signals 目录**恰好 1 个**文件（本次 child）；不存在 supervisor_signal.json 落在 child 目录内
5) 无原子写残留：run 目录及 child 目录内不得有 `*.tmp`（atomic_write_json 的临时文件）
6) 快照未被污染：`--verify-snapshot` MATCH（精确文件集 ⇒ 证明没有 __pycache__ 之类新增文件）
7) worker 进程已回收：termination_rec.worker_reclaimed 有记录（或 worker 在宽限期内自行退出）
8) 现场保留：不做任何清理（含 history `__pycache__`、临时 ns 目录）
```

---

## 5. 明确写死的前提与禁止项

```text
① **本演练会作废该次求解结果**：它只用于验证"触发 → 核验 → 终止 → 二次确认"机制；
   该 run 的 rows **不得**入库、**不得**用于任何性能/资源结论、**不得**混入数据集。
② **不得靠耗尽真实内存触发**：真实阈值（WS 12,288 MB / commit 4,096 MB / avail 4,096 MB）**不接近**；
   本演练用的是**人为压低**的 `--ws-hard-stop-mb 5000`，是"阈值穿越"的机制验证，不是资源事件。
   （r3d 实测 commit 最低 9,031 MB、avail 最低 7,373 MB ⇒ 与真实硬线相距甚远。）
③ 本 run 的 `DRILL_NOTE` 四处留痕（trigger/时间线/manifest/DRILL_README.txt），
   任何引用都必须带 "DRILL" 标识。
④ 不得自动重跑（`drill_hard_stop` ⇒ retry=false 已保证）；不得启动 LT2 生产批次。
⑤ 不得在演练中改阈值/改代码/放宽核验；`--drill` 与阈值覆盖是**唯一**允许的偏离。
⑥ 用户知情同意已取得（知晓"会主动终止测试 server、该次结果作废、不靠耗尽内存触发"）；
   执行时点由父 agent 与用户确认后另行放行。
```

---

## 6. 本轮已完成的**无 COMSOL** 前置回归（不启动 server）

| 检查 | 结果 |
|---|---|
| 演练接线回归（**从冻结快照**载入被测件，fake worker + `ramp_ws` + `--drill` + ws 5000） | **11/11 通过** → `work/runs/_evidence-drill-prep/drill_path_regression.json` |
| 同上：顶层 `enforced_by=drill_gate` / `is_drill_run=true` | 通过（含 `trigger` 内层与 `termination_rec` 一致） |
| 同上：`retry_class=drill_hard_stop` 且 `retry=false`（演练不自动重跑、不混入 resource） | 通过 |
| 同上：signals 写出、时间线 drill 标记、演练阈值证据 5000 | 通过 |
| 同上：**无真实 server 时绝不声称终止成功**（`performed=false` + `verified=false`，走 `self_exited_within_grace`） | 通过（T15g 属性保持） |
| 82 断言回归（含 **T15 演练接线** / **T16a `--drill` CLI 把关 exit 9**） | **82/82**，`ns-drill-prep-20260914-2100` |
| `enforced_by` 单位表（9 标签唯一、演练优先） | 通过 |
| 守卫两场景（持续抑制 / 有界升级）+ 灵敏度对照（2020/2000 旧码必失败） | 通过（见 r8d2 报告） |

**这些只验证"接线"，不能替代 U2**：真实 `comsolmphserver` 的终止只能在真机演练中证明。

---

## 7. 演练完成后要交付什么

```text
1) 命令原文 + 退出码 + 起止时间（真实墙钟）
2) §2.2 判据表**逐行**填实测值（期望 vs 实测）
3) 原始产物路径 + 哈希：termination_trigger.json / batch_manifest.json /
   child/worker_state.json / child/worker_error.json / signals/*.signal.json /
   resource_timeline.jsonl / DRILL_README.txt
4) `--verify` 与 `--verify-snapshot` 复核结果
5) §4.3 八项残留检查结果
6) 明确声明：该次求解结果作废、仅用于终止机制验证、不得用于资源放行
```
