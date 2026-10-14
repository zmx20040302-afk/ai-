# 硬停演练**重跑**（2239）：U1/U2/U3 达成 + **F1/F2/F3 四项修复实证**

- 日期：2026-09-14
- run_id：`lt2-drill-hardstop-u1u3-20260914-2239`（新 id，未复用 2204）
- 冻结：`freeze-20260914-2230-post-f1f2f3-record-semantics`（`lt2_production.py` = `5e7e84e3…`）
- 执行：22:38:32 → 22:39:58（86 s）；**从快照执行**；`-B` + `PYTHONDONTWRITEBYTECODE=1`
- 命令（与父 agent 给定逐字一致）：
  `--role supervisor --combos "[[0.8,2]]" --freqs 5 --expect-freq-count 1 --drill --ws-hard-stop-mb 5000 --freeze-id …2230…`
- **exit code = 6**（期望 6 ✔）

## 前置（只读，开跑前）

```text
COMSOL 家族进程：**一个都没有**（comsolmphserver / comsolbatch / comsolcompile / ComsolUI 均不在场）
  ⇒ 上轮阻塞演练的两个探针（comsolbatch -h pid 9676、comsolcompile pid 44736）与用户 GUI 都已消失
端口 2036：closed
内存两次采样（门槛 18000 / 21500）：
  22:38:09  avail 19,856.0  commit 26,667.7  load 38%
  22:38:14  avail 19,974.2  commit 26,825.3  load 37%     ⇒ **两次都过**
源码状态：为使 `--freeze-id 2230` 的运行前核验通过，已把 `work/tools/lt2_production.py`
  **逐字节恢复**为该冻结值（`5e7e84e3…`），`--verify` / `--verify-snapshot` 均 MATCH
  （我的 preflight 补强暂存于 `_evidence-preflight/preflight_hardened_lt2_production.py`，`c3f45407…`，演练后重新应用）
```

---

## 1. 逐项「期望 vs 实测」

### 1.1 同构部分（与 2204 那次一致，全部达成）

| 项 | 期望 | 实测 | |
|---|---|---|---|
| exit code | 6 | **6** | ✔ |
| `trigger_kind` | threshold_crossed | **threshold_crossed**（顶层 + 内层） | ✔ |
| `is_hard_stop` | true | **true** | ✔ |
| `enforced_by` | drill_gate | **drill_gate**（顶层 + 内层 + `termination_rec`） | ✔ |
| `is_drill_run` | true | **true** | ✔ |
| signals | 恰 1 | **1**（`child_00_attempt_1.signal.json`，`request=graceful_worker_end`） | ✔ |
| steps | verify_ownership → terminate_server(rc=0) → post_termination_verification | **六步全中**：`freeze_new_delivery → save_trigger_record → request_worker_end → verify_ownership(identity_match=true) → terminate_server(Stop-Process -Id 51492 -Force, **rc=0**) → post_termination_verification`；`refused=null` | ✔ |
| 二次确认 | 四项 + verified | `termination_command_exit=0`、`expected_pid_absent=true(0.0 s)`、`port_closed=true(1.5 s)`、`no_new_unexpected_comsolmphserver=true`、**`verified=true`** | ✔ |
| U3 载体 | solve_error = Java NPE | **Java NPE**（`aPIReturnValue … is null`）；`solve_started 22:38:50 → cancel_requested_at 22:39:31`（solve 内 **41 s**）`→ solve_returned 22:39:48`，`solve_seconds=58.3` | ✔ |
| 演练阈值证据 | 5000 vs 默认 12288 | `ws_hard_stop(6431.4 >= 5000.0 x2)`（首个越线样本 index 12 @22:39:29） | ✔ |
| 未接近真实线 | — | WS 峰值 **7,405.5**（< 12,288）、commit 最低 **13,456.8**（> 4,096）、avail 最低 **12,348.9**（> 4,096） | ✔ |
| 重跑分类 | drill_hard_stop / retry=false | `{retry: false, class: "drill_hard_stop"}` | ✔ |
| `DRILL_README.txt` | 存在 | 存在（1,330 B） | ✔ |
| 三布尔 | 全 true | 全 **true**；窗口 pre 22:38:32 MATCH / post 22:39:57 MATCH | ✔ |

### 1.2 **F1/F2/F3 四项**（上一轮全错，这次全部对上）

| 项 | 期望 | 实测 | 2204（未修）对照 |
|---|---|---|---|
| **F1** `stop_line_event_count` | **5** | **5** | 0 ❌ |
| **F1** `peak_ws_lt_hard_stop` | **false** | **false** | 键名还是 `peak_ws_lt_12288` 且值 `true` ❌ |
| **F2** `hard_stop_verdict_sample_count` / `no_hard_stop_verdict_samples` | **4 / false** | **4 / false** | 无计数字段 / `true`（空集恒真）❌ |
| **F3** `warning_verdict_sample_count` / `blocks_next_combination` | 与时间线自洽 | **0 / false**（时间线 warning 行 **0**、hard_stop 行 **4** ⇒ 自洽） | 无字段 / 旧门控逻辑 ❌ |
| 附：`thresholds.ws_hard_stop_mb` | 生效值 5000 | **5000.0** + `thresholds_provenance{drill:true, overrides:{ws_hard_stop_mb:{default:12288.0, drill_value:5000.0}}}` | 记 12288（默认，非生效值）❌ |

**这四项就是 F1/F2/F3 修好的实证**：2204 与 2239 的命令、模型、阈值、组合**完全相同**，
唯一差别是代码（冻结 2000 → 冻结 2230），因而构成一次干净的 **A/B 对照**。

---

## 2. 演练后复核与八项残留检查

```text
--verify              MATCH（drift 0，checked_at 22:40:21）
--verify-snapshot     MATCH（drift 0，含精确文件集校验）
1) 无残留 server          PASS（comsolmphserver none）
2) 端口 2036 closed       PASS
3) 无意外 server          PASS（实时枚举 comsol 家族 = 空）
4) signals 恰 1 个        PASS（child_00_attempt_1.signal.json）
5) 无 *.tmp               PASS
6) 快照未污染             PASS（--verify-snapshot MATCH）
7) worker 已回收          PASS（worker_reclaimed: pid 23812, terminated=false, waited_s=6.0,
                               note=worker 在宽限期内自行退出）
8) 现场保留               PASS（run 根 = DRILL_README.txt + batch_manifest.json + child_00_attempt_1/ + signals/）
```

## 3. 声明

```text
① 本演练**作废该次求解结果**（rows=0）：不得入库、不得用于任何性能或资源结论。
② **不得靠耗尽真实内存触发**：已遵守并可证——真实阈值全程未接近（WS 7,405.5 < 12,288；
   commit 13,456.8 / avail 12,348.9 远高于 4,096），触发完全来自人为的 5000。
③ `check_r3_conditions.py` **不适用于本 run**（会故意失败 not_a_drill_run 与 rows/资源类）。
④ DRILL_NOTE 四处留痕（manifest / checkpoint / 时间线 / DRILL_README.txt）。
⑤ 未改任何被测件（跑的是冻结快照）；未启动 LT2 生产批次；现场未清理。
```

## 4. 证据与哈希（`work/runs/_evidence-drill2/`）

```text
drill2_result.json        6,464 B  32ffa26a68e1678385669e9cc05e923c6e6e1a387a064adb0f2bedf973269795
predrill_env_scan.json      136 B  3a36c9aa388a0d05cedb…（开跑前 COMSOL 家族 = 空）
run 产物：
  batch_manifest.json                      45,011 B  2b0be31a41b6cc7691eb…
  DRILL_README.txt                          1,330 B  6c751b73f10aa4115be6…
  signals/child_00_attempt_1.signal.json      240 B  e99e9f1856ac58b8e51b…
  child/termination_trigger.json            3,288 B  29da0f307b599e0d5c8e…
  child/worker_state.json                   1,144 B  4b7402ee0bda82504db8…
  child/checkpoint.json                    13,824 B  245dd0e0d45e1e782e70…
  child/resource_timeline.jsonl            11,054 B  49cdedf7c19ad6d85d2a…
  child/sampler_state.json                  1,031 B  bc88f0928efff11f8d00…
被测件（= 冻结值，本轮未改）：work/tools/lt2_production.py  155,778 B  5e7e84e304b8b76712a7…
```

## 5. 字段位置索引（供后续复核：这几项**不在** `termination_trigger.json` 里）

```text
你猜的两个路径为空，是因为它们不在 `child/termination_trigger.json`（那只是触发记录）：

termination_rec（steps / post_verification / ownership_checks / termination / worker_reclaimed）
    → **`batch_manifest.json` → `children[0].termination`**
      · steps     = children[0].termination.steps = [freeze_new_delivery, save_trigger_record,
                    request_worker_end, verify_ownership, terminate_server, post_termination_verification]
      · verified  = children[0].termination.post_verification.verified = true
      · 二次确认四项 = children[0].termination.post_verification.{termination_command_exit,
                    expected_pid_absent, port_closed, no_new_unexpected_comsolmphserver}
      · 归属核验  = children[0].termination.ownership_checks.identity_match = true
      · 终止命令  = children[0].termination.termination.command = {cmd: Stop-Process -Id 51492 -Force, rc: 0}
      · worker 回收 = children[0].termination.worker_reclaimed
stop_line_event_count（F1 那一项）
    → **`child/checkpoint.json` → `resource_summary.stop_line_event_count`** = 5
      （同层：commit_hard_stop_samples / commit_warning_samples / server_ws_mb /
        system_available_physical_mb / commit_available_mb / timeline_gaps_over_15s /
        solve_stage_missing_system_columns / stop_line_events_file(_sha256)/_head40）
其余本次引用的字段：
    F1/F2/F3 的其余字段   → `child/checkpoint.json`：thresholds / thresholds_provenance /
        blocks_next_combination / warning_verdict_sample_count /
        pass_conditions.peak_ws_lt_hard_stop / pass_conditions.no_hard_stop_verdict_samples /
        pass_conditions.hard_stop_verdict_sample_count
    触发记录顶层（kind/is_hard_stop/enforced_by/is_drill_run/wording_note）→
        `child/termination_trigger.json` 顶层，及同源的 `trigger` 子对象
    U3 载体 → `child/worker_state.json`：solve_error / solve_started_at / solve_returned_at /
        cancel_requested / cancel_source / cancel_requested_at
```

## 6. 下一步（按父 agent 顺序，**不连做**）

```text
② preflight 补强（COMSOL 家族显式检查 + ComsolUI 单列记录 + 门禁默认 18000/21500 + 双采样）
   —— 我的改动已写好并暂存（`c3f45407…`），演练后重新应用到 `work/tools/lt2_production.py`，
   然后做最小执行 + 灵敏度 + 82 断言 + 机械差异，报新哈希
③ 干净条件下跑 r3e（取得「生产路径数值逐一不变」）
④ 之后才做 `--model` 与 legacy 对拍
**不启动 LT2 生产批次**
```
