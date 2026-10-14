# r3b 正常资源确认：**PASS（23/23）**

- run_id：`lt2-resource-confirm-x080-n02-postpagefile-r3b`（新 id，未复用 r3）
- 执行：**从冻结快照执行**（`work/runs/lt2-supervisor-acceptance-freeze-20260914-2000-post-three-booleans/snapshot/lt2_production.py`）
- 冻结：`freeze-20260914-2000-post-three-booleans`，manifest `a48b15499246b4468b14271089b28e904725ba59b5c1fb90517fcc86831148ab`
- 时间：起 2026-09-14T19:34:06 → 止 19:47:41/42（约 13.6 min）；`solve_seconds=765.2`
- 参数：`--combos [[0.8,2]]`、`--freqs 5,10,15,20,25,30,35`（逗号形式，已留痕）、`--freeze-id` 显式给出；
  **未加 `--drill`、未压低任何阈值、前置门禁用默认 16,384/16,384、单实例串行、后台作业**
- 退出码 **0**，`status=PASS`，`blocked_reason=null`
- 期间**无第三方并行负载**（我只做了只读的采样行数/日志解码），故本轮资源数值是**干净基线**，
  与 r3（存在并行负载登记）不构成同口径对比。

---

## 1. 判据逐条取值（`check_r3_conditions.py` 全 23 条）

```text
python work/tools/check_r3_conditions.py --run-id lt2-resource-confirm-x080-n02-postpagefile-r3b \
       --json-out work/runs/_evidence-r3b/r3b_checker.json
→ [结论] 23/23 通过；all_pass=True；失败项=[]
（父 agent 本轮把检查器从 21 条扩到 23 条：三个冻结布尔各占一条。r3 时是 20/21。）
```

| # | 条件 | pass | detail |
|---|---|---|---|
| 1 | `child_dir_exists` | true | `child_00_attempt_1` |
| 2 | `rows_eq_7` | true | 7 rows |
| 3 | `unique_freqs_eq_7` | true | 7 unique: 5/10/15/20/25/30/35 |
| 4 | `drive_mismatch_0` | true | 0 mismatched |
| 5 | `solve_error_is_null` | true | `solve_error=None` |
| 6 | `ws_hard_stop_samples_0` | true | 0 |
| 7 | `physical_hard_stop_samples_0` | true | 0 |
| 8 | `commit_hard_stop_samples_0` | true | 0 |
| 9 | `commit_warning_samples_0` | true | 0（若非 0 须暂停解释，非直接放宽） |
| 10 | `min_commit_gt_6144` | true | **min=8,724.3** |
| 11 | `missing_system_columns_0` | true | solve_rows=153 missing=[] |
| 12 | `monitoring_gaps_gt_15s_0` | true | gaps=0 unparsable_ts=0 |
| 13 | `checkpoint_valid` | true | 存在且可解析 |
| 14 | `lt2c_quick_gate_pass` | true | `shape=nested:checks.pass value=True` |
| 15 | `pid_source_is_port_owner` | true | `port_owner` |
| 16 | `identity_complete` | true | keys=[name, parent_is_worker, parent_pid, pid, start_filetime, worker_pid] |
| 17 | `port_closed_within_30s` | true | True |
| 18 | `server_process_absent` | true | `stop=True stage=closed` |
| 19 | `no_blocked_reason` | true | None |
| 20 | **`freeze_hashes_pre_post_match`** | **true** | `artifact key freeze_hash_pre_post_match=True` |
| 21 | **`executed_from_frozen_snapshot`** | **true** | `True（防从非冻结副本执行）` |
| 22 | **`freeze_evidence_complete`** | **true** | `True reason=None` |
| 23 | `not_a_drill_run` | true | `drill_flag_seen=False` |

`evidence` 段（检查器读到的原始值）：`timeline_rows=160`、`solve_seconds=765.2`、`commit_min=8724.3`、
`commit_max=21205.4`、`ws_max=11177.7`、`physical_min=6783.1`、`batch_manifest_present=true`。

---

## 2. 三布尔取值（裁定 2 的产物字段）

```json
"freeze_id": "freeze-20260914-2000-post-three-booleans",
"freeze_hash_pre_post_match": true,
"executed_from_frozen_snapshot": true,
"freeze_evidence_complete": true
```

配套证据（`batch_manifest.json` → `freeze_evidence`）：

```text
pre  = { at: 2026-09-14T19:34:06, verdict: MATCH, drift_count: 0, frozen_file_count: 13 }
post = { at: 2026-09-14T19:47:41, verdict: MATCH, drift_count: 0, frozen_file_count: 13 }
freeze_manifest_sha256              = a48b15499246b4468b14271089b28e904725ba59b5c1fb90517fcc86831148ab
pre_post_files_identical            = true
running_script_is_frozen_target     = { file: lt2_production.py,
    self_path: <snapshot>\lt2_production.py,
    self_sha256: 8f49ab4e6f85749d7a9b46e511ebf5b471c58917c62e7f4b7dcd907746e80c91,
    frozen_target_sha256: 8f49ab4e…（同值）, match: true }
```

⇒ **两次 `at` 是真实墙钟**（19:34:06 / 19:47:41），构成批次窗口上下界（未加 `--fixed-timestamps`，
这正是当初说明的设计取舍）；`running_script_is_frozen_target.self_path` 落在 **snapshot 目录**，
即「从冻结副本执行」这一条不是声明而是产物自证。

---

## 3. `--verify` / `--verify-snapshot` 运行后复核

```text
python work/tools/freeze_snapshot.py --verify          freeze-20260914-2000-post-three-booleans
  → drift_count = 0 ; verdict = MATCH ; checked_at = 2026-09-14T19:48:01 ; exit 0
python work/tools/freeze_snapshot.py --verify-snapshot freeze-20260914-2000-post-three-booleans
  → drift_count = 0 ; verdict = MATCH ; checked_at = 2026-09-14T19:48:01 ; exit 0
```

`--verify-snapshot` 同时做**精确文件集合**校验（新增未跟踪文件即判失败）：MATCH ⇒ 运行期间
snapshot 目录**没有**多出 `__pycache__` 之类文件（执行时带了 `-B` + `PYTHONDONTWRITEBYTECODE=1`）。

---

## 4. 运行实质（不是只看判决）

| 项 | 值 |
|---|---|
| 组合 / 驱动 | `(0.8, 2)`；`dual_electrode_antiphase_voltage_drive`（pot1=+1V cyl8 / pot2=−1V cyl9 / gnd1=0V cyl7） |
| 频率 | 7 点 5/10/15/20/25/30/35 MHz（`freqs_parse.count=7`，canonical `5[MHz] … 35[MHz]`） |
| 结果行 | `rows=7`、唯一频率 7、`Vdiff_abs=1.9999999999999998`、`drive_mismatch=0` |
| 网格 | `mesh_element_count=157,390`（r3 同值） |
| 求解 | `solve_seconds=765.2`（r3=749.5）、`solve_error=null`、worker `stage=closed` |
| 电流指标 | `electrical_current_metrics_excluded=true`，reason `LT0_C_KCL_relative_gt_1pct`（口径同前） |
| LT2-C | `checks.pass=true`；18 项子检查全 true（含 `intop5_eq_swr1_eq_efc1`、`term1_active_false`、`cir_inactive_verified`） |
| 容差证据（U4/U8） | frozen=current=`6.266153558917681e-08`，相对差 `0.0`，tol `1e-6`；`frozen_evidence_run_id=precheck-b2-phase2-v5-aggregate`，sha `b26193fe…` |
| 资源 | commit 最低 **8,724.3**（>6144）、commit 最高 21,205.4；WS 峰值 **11,177.7**；avail 最低 **6,783.1**；三类硬停采样 0、commit 预警采样 0、空档>15s 0、缺列 0、`stop_line` 事件 0；时间线 160 行 |
| 身份 | `pid_source=port_owner`；`{pid:21548, start_filetime:134338592490176273, parent_pid:18260, worker_pid:18260, parent_is_worker:true}` |
| 收尾 | `port_closed_within_30s=true`、`server_process_absent=true`、sampler `verdict=ok`、`no_cancel_triggered`、`no_hard_stop_verdict_samples` |
| 批次 | 11 项 aggregate 全 true；child 13 项 pass_conditions 全 true |
| 产物哈希 | `rows.csv` `1ed3425bce92bb5e98f8990fc43aa46d1804acd5bbb973dadb922ffbaef8cb36`；`batch_manifest.json` `4289a16d…`；`checkpoint.json` `d87c9ca1…`；`resource_timeline.jsonl` `91102c50…` |

收尾进程核查：`comsolmphserver_pids=none`、端口 2036 `closed`（19:48 实测）。

---

## 5. 一处**既有**现象，如实登记（不是本轮 ②③ 引入，且**不构成本轮失败**）

r3b 的 child 目录里有 `termination_trigger.json`、run 目录里有 `signals/child_00_attempt_1.signal.json`。
**r3 有完全相同的两个文件**（逐字段同形态），故属既有行为。已追到代码与实测事实：

```text
发生时刻 = 19:47:31（求解已完成、worker 已写完 checkpoint 并置 stage=closed/stop=true，
            但 worker 进程尚未退出）
链路     = supervise_child 轮询 → sampler_pid 已不在（**正常收尾**：worker 结束时停 sidecar）
           → sidecar_health = sidecar_exited → decide_next_action = hard_stop_enforce(source=sidecar_health)
           → verified_emergency_termination(...)
实测动作 = steps = [freeze_new_delivery, save_trigger_record, request_worker_end, **grace_period_self_exit(ok=true)**]
           —— **没有 terminate_server 步骤**
实测二次确认 = { termination_command_exit: null, expected_pid_absent: true(0.0s), port_closed: true(1.5s),
                no_new_unexpected_comsolmphserver: true, remaining/unexpected pids: [], verified: true }
            ⇒ **没有对任何存活 server 执行终止命令**；server 早已由 worker 正常关闭
自标注   = trigger_kind = "unclassified_failure"、is_hard_stop = **false**、
           wording_note = "仅当 trigger_kind == 'threshold_crossed' 时本记录才是资源硬停…"（D-C 修复在起作用）
```

**影响评估（可证伪的只有两条，均为证据卫生，不影响物理/资源安全）**：

1. `batch_manifest.json` 里该 child 的 `worker_returncode = **null**`（r3 亦然）。
   原因：`enforced=True` 时 supervisor **跳过**了 `proc.wait(30)`，随后立即读 `proc.returncode`，
   而此刻 worker 进程尚未退出完 ⇒ 退出码没被记录。**7 行结果、checkpoint、时间线、资源判据全部完好**。
2. 一次**正常收尾**的 run 里留下了 `decided.action=hard_stop_enforce` 的触发记录与信号文件
   （记录自带 `is_hard_stop=false` + 措辞说明，读完可正确解读；但"PASS 的 run 里为什么有 hard_stop_enforce"
   仍会让人多问一句）。

**建议的修法（本轮未改，原因见下）**：在 `supervise_child` 轮询里加一条**正常完成守卫**——
若 `worker_state.stage == "closed"` 或 `checkpoint.json` 已存在，则**不**走 enforce 分支，
而是等 worker 自然退出、记录真实 `worker_returncode`，并把该情形记为
`trigger_kind = "normal_completion_sidecar_exit"`（`is_hard_stop=false`）。

**为什么本轮不动手**：任何对 `lt2_production.py` 的改动都会使 `freeze-20260914-2000-post-three-booleans`
立即失效（本轮三布尔判真正是靠它），且父 agent 本轮只授权"从新快照重跑 r3"。是否修由父 agent 决定；
若要修，我按同一流程走（改 → 最小执行 → 报哈希 → 新 freeze → 重跑）。

---

## 6. 证据文件（`work/runs/_evidence-r3b/`）

```text
r3b_checker.json              9,177 B  0094a71519ac7c78da7f0f38df5cf9310d824f5ff876ab0ceb4e87121e65cdb8
r3b_artifact_summary.json     5,293 B  7386c60a7215027c57c429112b83c2b1c12c865842bdae3ac878fc654a27bae0
r3b_termination_record.json   1,275 B  42e71c071afeedabd9e302a185656105b3628963d2bd9cd0ee004dba2f10cb7d
r3b_stdout.log                1,167 B  f05046ee41693a9bff02a5c0999271de016b775078581a715457ed8f81187177（GBK 原样）
r3b_stdout_utf8.log           1,192 B  18cd7620ae165fc0877d2a2733f9b1a9cc4257fed291e62ea311caf422d242b2（同内容 UTF-8 副本）
r3b_stderr.log                    0 B  e3b0c44298fc1c149afbf4c8c99...（空）
evidence_hashes.json          2,459 B  0d9dc16ecfc0b45be031932940c8780001aeafb733d56eb234163fff1a9545e7
```

运行目录 `work/runs/lt2-resource-confirm-x080-n02-postpagefile-r3b/`：
`batch_manifest.json`(37,327 B) + `child_00_attempt_1/`{checkpoint, rows.csv, raw_rows.csv,
resource_timeline.jsonl/csv, sampler_state.json, worker_state.json, termination_trigger.json} + `signals/`。
**现场保留，未清理。**

---

## 7. 未做

```text
未执行硬停演练（U1–U3）          未启动 LT2 生产批次
未修改任何被测件/阈值/判定逻辑    未加 --drill、未压低阈值
未复用 r3 的 run-id / 未清理既有现场
```
