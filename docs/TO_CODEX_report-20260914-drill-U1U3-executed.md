# LT2 硬停演练（U1–U3）：**已执行，U1/U2/U3 全部达成**

- 日期：2026-09-14
- 授权：用户直接回复「**现在执行**」（范围＝真实 COMSOL 硬停演练 U1–U3；知情同意先前已取得）
- 方案：`docs/TO_CODEX_plan-20260914-hardstop-drill-U1U3.md`（**原样执行，命令一字未改**）
- 冻结：`freeze-20260914-2040-post-guard-persistent`（`lt2_production.py` = `81936aeb…`，153,287 B）
- run_id：`lt2-drill-hardstop-u1u3-20260914-2204`；**launch 22:04:00 → end 22:05:27（87 s）**
- **exit code = 6**（期望 6 ✔）；`status = BLOCKED_OR_LIMITED`（演练预期）
- 执行前门禁（只读复测 22:03:37）：avail **20,318.5** ≥ 18,000 / commit **26,553.1** ≥ 21,500 / load 36 %；
  无 `comsolmphserver`、端口 2036 closed、无求解/测试探针进程、总 CPU 5.5 %（top delta 0.3 CPU·s/4s）

```text
命令（与方案逐字一致）：
& $py -B "<snapshot>\lt2_production.py" --run-id lt2-drill-hardstop-u1u3-20260914-2204 \
    --role supervisor --combos "[[0.8,2]]" --freqs "5" --expect-freq-count 1 \
    --drill --ws-hard-stop-mb 5000 --freeze-id freeze-20260914-2040-post-guard-persistent
（-B + PYTHONDONTWRITEBYTECODE=1；后台作业；单实例串行）
```

---

## 1. 逐项「期望 vs 实测」

| # | 项 | 期望 | **实测** | 结论 |
|---|---|---|---|---|
| 1 | exit code | 6 | **6** | ✔ |
| 2 | `trigger_kind` | `threshold_crossed` | **`threshold_crossed`**（顶层 + `trigger` 内层） | ✔ |
| 3 | `is_hard_stop` | true | **true** | ✔ |
| 4 | `enforced_by` | `drill_gate` | **`drill_gate`**（顶层 + 内层 + `termination_rec`） | ✔ |
| 5 | `is_drill_run` | true | **true**（顶层 + 内层） | ✔ |
| 6 | 阈值证据 | `ws_hard_stop_mb=5000.0`（对比默认 12288） | **5000.0**；`overrides={ws_hard_stop_mb:{default:12288.0, drill_value:5000.0}}`；`effective.ws_hard_stop_mb=5000.0` | ✔ |
| 7 | signals | 存在且**恰 1 个** | **1 个**：`signals/child_00_attempt_1.signal.json`（240 B，`request=graceful_worker_end`） | ✔ |
| 8 | steps | `verify_ownership(ok)` → `terminate_server(rc=0)` → `post_termination_verification(ok)` | **`freeze_new_delivery → save_trigger_record → request_worker_end → verify_ownership → terminate_server → post_termination_verification`**（`identity_match=true`；`Stop-Process -Id 5084 -Force` **rc=0**；末步 `ok`） | ✔ |
| 9 | 二次确认 | 四项 + `verified=true` | `termination_command_exit=**0**`、`expected_pid_absent=**true**(0.0 s)`、`port_closed=**true**(1.5 s)`、`no_new_unexpected_comsolmphserver=**true**`（`remaining/unexpected pids=[]`）、**`verified=true`** | ✔ |
| 10 | `worker_returncode` | 整数 1 | **0**（**与预测不同**，见 §3①；`worker_returncode_recorded=true`，非 null） | ⚠ 有解释 |
| 11 | `worker_error.json.stage_at_error` | `"solve"` | **该文件不存在**（**与预测不同**，见 §3②）；U3 证据改由 `worker_state.solve_error` + `cancel_record` + 时间线承担 | ⚠ 有解释 |
| 12 | 重跑分类 | `drill_hard_stop` 且 `retry=false` | **`{retry: false, class: "drill_hard_stop"}`** | ✔ |
| 13 | `DRILL_README.txt` | 存在 | **存在**（1,330 B，含 run_id / drill_thresholds / DRILL_NOTE / U1-U3 用途） | ✔ |
| 14 | `DRILL_NOTE` 四处留痕 | 四处 | **四处**：`batch_manifest.drill_note`、`child/checkpoint.json.drill_note`、`resource_timeline.jsonl[].drill_note`、`DRILL_README.txt` | ✔ |
| 15 | 三布尔 | 全 true | `freeze_hash_pre_post_match` / `executed_from_frozen_snapshot` / `freeze_evidence_complete` **全 true** | ✔ |
| 16 | 演练后复核 | 两次 MATCH | `--verify` **MATCH**（drift 0）、`--verify-snapshot` **MATCH**（drift 0，精确文件集） | ✔ |
| 17 | 冻结窗口 | 真实墙钟 | pre **22:04:00** MATCH / post **22:05:27** MATCH | ✔ |
| 18 | 归属核验 | `identity_match=true`、不触发 `refused` | `identity_match=true`、`port_owner.ok=true`、**`refused=null`** | ✔ |

---

## 2. U1 / U2 / U3 结论

### U1 全路径 —— **达成**
触发记录 → 归属核验 → 终止 → 二次确认 → worker 回收，六步全部落痕且顺序与设计一致（第 8 项）。
触发时刻 `cancel_requested_at = 22:05:00`，触发记录 `saved_at = 22:05:00`，终止命令 rc=0。

### U2 对真实 `comsolmphserver` 的终止 —— **达成**
```text
expected_pid = 5084（来自 2036 端口持有者，非启发式）
terminate_server: cmd = "Stop-Process -Id 5084 -Force", rc = 0
post_verification: expected_pid_absent=true(0.0s) / port_closed=true(1.5s) /
                   no_new_unexpected_comsolmphserver=true / termination_command_exit=0 / verified=true
ownership_checks: port_owner.ok=true, port_owner_actual_pid=5084, identity_match=true
```
且**未误伤**：用户的 `ComsolUI.exe`（pid 34700）全程在运行、未被触碰；演练后实时枚举仍只有它，无新 server。

### U3 study 阻塞期间被终止后的行为 —— **达成**
```text
solve_started_at      = 22:04:18
cancel_requested_at   = 22:05:00   ← 终止发生在 solve 开始后 **42 s**
solve_returned_at     = 22:05:17   ← 被终止后 17 s 返回；solve_seconds = 58.1
worker_state.solve_error = "java.lang.NullPointerException: ... Cannot read field
                            \"aPIReturnValue\" because \"<local6>\" is null"
                            （= COMSOL/MPh 客户端在 server 被切断后的异常，证明终止打在 study 运行中）
cancel_record = { trigger: {action: hard_stop_enforce, source: sampler_state.verdict},
                  naming_note: "worker 侧只记录触发；终止由 supervisor 的
                                verified_emergency_termination 执行" }
                ⇒ worker **没有**声称 graceful cancel（命名纪律保持）
时间线：16 个样本全部 drill=true；首个越线样本 sample_index=12 @22:04:58、
        reasons=["ws_hard_stop(6363.9 >= 5000.0 x2)"]、stage=solve、verdict=hard_stop（共 4 行 hard_stop）
worker_reclaimed = {pid: 11032, terminated: false, waited_s: 7.0, note: "worker 在宽限期内自行退出"}
```

**未接近真实资源线**（证明触发纯属人为阈值，符合"不得靠耗尽真实内存触发"）：
WS 峰值 **7,334.9**（< 12,288）、commit 最低 **13,065.7**（> 4,096）、avail 最低 **12,427.8**（> 4,096）、
`commit_warning_samples=0`、`commit_hard_stop_samples=0`；`ws_samples_ge_12288 = 0`。

---

## 3. 两处**与我预测不同**的地方（如实登记，均为我的预测误差）

**① `worker_returncode` 实测 0（我预测 1）。**
原因：worker 把求解失败当成**受控路径**处理（`solve_error` 捕获后仍走 `finalize_after_solve` 写 checkpoint），
因此正常退出并返回 0；`worker_reclaimed.terminated=false` + `waited_s=7.0` 即"worker 在宽限期内自行退出"。
⇒ 我的预测错在"以为求解异常必然走 `except` 分支返回 1"。**非实现缺陷**：child 的判定不依赖 rc，
`status` 取自 checkpoint（`fail_or_limited`），rc=0 不会被误读为成功。

**② `worker_error.json` 不存在（我预测存在且 `stage_at_error="solve"`）。**
原因：`worker_error.json` 只在 worker **自身流程抛出未处理异常**时写；本次求解失败是受控路径，
证据落在 `worker_state.solve_error`（Java NPE 原文）+ `checkpoint.status=fail_or_limited` + `rows=0` +
`cancel_record` + 时间线 4 行 hard_stop。⇒ **U3 依然成立**，只是证据载体与我预测的不同。

（附：child `pass_conditions` 里 `frequency_rows_7=false` 是**单频点设计的必然**——`--freqs 5` 只解 1 点；
`no_cancel_triggered=false` 是演练的必然。两者都不是缺陷。）

---

## 4. 两处**发现**（不是演练失败；均属既有行为，建议另行开一轮修，需新 freeze）

### F1 worker 侧 checkpoint 用**默认阈值**计算（演练下与实际生效的 5000 不一致）

```text
事实：child/checkpoint.json.thresholds.ws_hard_stop_mb = 12288.0（默认），而本次**实际生效**的是 5000.0
    （sampler 侧按 drill 阈值判定；supervisor 的 batch_manifest.drill_thresholds 与时间线 drill_thresholds 都正确）
后果（可量化）：resource_summary.stop_line_event_count = **0**，而按生效阈值统计应有 **5** 个样本越 5000
    （5,367.7 / 6,363.9 / 6,852.5 / 6,857.3 / 7,334.9；≥12288 为 0 个）
根因：run_combo_worker 里 `th = Thresholds()`（第 1642 行）而非 `resolve_thresholds(args)[0]`；
    checkpoint 的 thresholds / summarize_timeline / combo_pass_conditions 都用这个默认 th。
影响面：**生产运行不受影响**（无 --drill 时默认即生效值）；仅演练/阈值覆盖时标签不一致。
建议：worker 改用 `resolve_thresholds(args)[0]`，使 checkpoint 的阈值与摘要反映**生效阈值**并带演练来源。
```

### F2 `no_hard_stop_verdict_samples` 在"有取消记录"时**恒真**（空集冒充"没有越线样本"）

```text
事实：checkpoint.pass_conditions.no_hard_stop_verdict_samples = **true**，而时间线里有 **4 行** verdict=hard_stop
根因（第 1480–1490 行）：engine_verdicts 只在 `if cancel_rec is None` 时读取；取消时为空集
      ⇒ `len(hard)==0` 恒真（与我早前报告的同类命名/语义问题一致）
影响面：仅取消/演练路径；生产正常路径 cancel_rec 为 None ⇒ 该判据有效。
建议：改为始终统计（并给出计数），或在命名上明确"此判据在取消场景不适用"。
```

> 两项都**未修改**（改代码会使 2040 冻结失效，且本轮只授权执行演练）。

---

## 5. 八项残留检查（逐项）

| # | 检查 | 结果 |
|---|---|---|
| 1 | 无残留 server | **PASS** `comsolmphserver` none |
| 2 | 端口 2036 closed | **PASS** |
| 3 | 无意外 server | **PASS** 仅 `ComsolUI`（pid 34700，用户 GUI，全程未触碰）；`no_new_unexpected_comsolmphserver=true`、remaining/unexpected `pids=[]` |
| 4 | signals 恰 1 个 | **PASS** `child_00_attempt_1.signal.json` |
| 5 | 无 `*.tmp` | **PASS**（run 与 child 递归） |
| 6 | 快照未污染 | **PASS** `--verify-snapshot` MATCH（drift 0，精确文件集） |
| 7 | worker 已回收 | **PASS** `worker_reclaimed`：宽限期内自行退出（waited 7.0 s） |
| 8 | 现场保留 | **PASS** 未做任何清理；run 根 = `DRILL_README.txt` + `batch_manifest.json` + `child_00_attempt_1/` + `signals/` |

---

## 6. 声明（与方案一致）

```text
① **本演练作废该次求解结果**：rows = 0（未产出任何频率点结果），本 run 不得入库、
   不得用于任何性能/资源结论、不得混入数据集。
② **不得靠耗尽真实内存触发**：已遵守并可证——真实阈值（WS 12,288 / commit 4,096 / avail 4,096）
   全程未接近（峰值 7,334.9、最低 13,065.7 / 12,427.8），触发完全来自人为的 5000。
③ `DRILL_NOTE` 四处留痕（manifest / checkpoint / 时间线 / DRILL_README.txt）。
④ `check_r3_conditions.py` **不适用于本 run**（会故意失败 not_a_drill_run 与 rows/资源类条件）。
⑤ 未启动 LT2 生产批次；未改任何被测件/阈值/判定逻辑；未清理现场。
```

---

## 7. 证据文件与哈希（`work/runs/_evidence-drill/`）

```text
drill_result.json      9,871 B  dba5843579135ac94ae65a5679a25aed980a24a076a7d3ef42e2816d2aa7867a
drill_u3_detail.json   4,835 B  1417a513e885799abb3e5bf5e5c0aa5b16031b2eafaf9ca28caf73c2605eae87
drill_findings.json    1,371 B  fdd9a993fab2f5ae443a…（F1/F2 量化）
drill_argv.txt           364 B  773f61ada4e3b2b689f0…
drill_stdout.log       1,313 B  ba4c084149dfee018702…
evidence_hashes.json   2,857 B  8fd7a6bac0c81ac1a2b727ad4e673177ee3d66777fb3b63ae8d68ca706ef63d4
run 产物：
  batch_manifest.json                 44,875 B  6edb7368cfa4c82bcbf5…
  DRILL_README.txt                     1,330 B  e149e22b88800f19da1f…
  signals/child_00_attempt_1.signal.json  240 B  a93bf1d5b5d82e56a0f1…
  child/termination_trigger.json       3,284 B  c50365efb83a0008bb8e…
  child/worker_state.json              1,141 B  44f862f48d15742c7e7b…
  child/checkpoint.json               11,965 B  1657e54633ec49df78ec…
  child/resource_timeline.jsonl       11,040 B  ab3856b51172fd7b3f84…
  child/sampler_state.json             1,030 B  7015799378fdb095e787…
```

## 8. 未做

```text
未启动 LT2 生产批次（另一道门）    未改任何代码/阈值/判定逻辑
未清理任何现场                    未手工 kill 任何进程（演练的终止走的是产品代码路径）
```

---

## 9.（补充登记，append-only）F1/F2 的处置裁定，与"什么支撑了 U1–U3"

**父 agent 裁定（2026-09-14）**：F1/F2 **要修，但另开一轮**；两者**不推翻**本次 U1–U3 结论。

### 9.1 为什么 F1/F2 不推翻 U1–U3

```text
本次 U1/U2/U3 的结论建立在**四类证据**上，与 F1/F2 涉及的两个字段无关：
  · 触发记录 termination_trigger.json（顶层 trigger_kind / is_hard_stop / enforced_by / is_drill_run
    + threshold_evidence + wording_note）
  · termination_rec.steps 六步序列 + ownership_checks.identity_match + terminate_server rc=0
  · post_verification 四项 + verified=true
  · U3 载体：worker_state.solve_error（Java NPE）+ cancel_record.naming_note + 时间线 4 行 hard_stop
F1 涉及 checkpoint.resource_summary.stop_line_event_count；F2 涉及
checkpoint.pass_conditions.no_hard_stop_verdict_samples —— 两者都**不在** U1–U3 的证据链上
（演练结论不读这两个字段）。
「未接近真实线」的实证同样独立于 F1/F2：WS 峰值 7,334.9 < 12,288、commit 最低 13,065.7、
avail 最低 12,427.8、commit 预警/硬停采样 0、ws_samples>=12288 = 0。
```

### 9.2 登记状态

```text
F1  worker 侧 checkpoint 用默认阈值计算（12288）而实际生效 5000
    => resource_summary.stop_line_event_count = 0（按生效阈值应为 5）
    影响面：生产不受影响（无 --drill 时默认即生效值）；仅演练/阈值覆盖时标签不一致
    状态：**已发现、待修**（方案见 docs/TO_CODEX_plan-20260914-F1-F2-record-semantics.md）
F2  no_hard_stop_verdict_samples 在 cancel_rec 非空时恒真（空集冒充「没有越线样本」）
    => true 与时间线 4 行 hard_stop 并存
    影响面：仅取消/演练路径；生产正常路径该判据有效
    状态：**已发现、待修**（同上方案文档）
```

### 9.3 本次演练结论的有效性边界

```text
有效：U1（触发 -> 核验 -> 终止 -> 二次确认 全路径）、U2（对真实 comsolmphserver 的归属核验式终止，
      未误伤用户 ComsolUI.exe）、U3（study 阻塞期间被外部终止后的行为与留痕）
作废：该次求解结果（rows=0）—— 不得入库、不得用于任何性能或资源结论
未覆盖：LT2 生产批次（504 点）—— 仍未启动
```

