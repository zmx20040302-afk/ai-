# r3e：**真实资源硬停**（非演练、非代码缺陷）—— append-only 记录

- 日期：2026-09-14
- run_id：`lt2-resource-confirm-x080-n02-postpagefile-r3e`
- 冻结：`freeze-20260914-2230-post-f1f2f3-record-semantics`（`5e7e84e3…`）；pre 22:19:22 MATCH / post 22:32:21 MATCH
- 执行：从快照执行、`--combos [[0.8,2]]`、7 频点、不加 `--drill`、门禁照常（16,384/16,384）
- **结果：exit 6 / `BLOCKED_OR_LIMITED` / checker 14/23** ⇒ **未复现 r3d 的 23 条**（期望未达成）

---

## 1. 发生了什么：机器真实耗尽 commit（0.5 MB）

```text
22:19:25  采样 1    avail 18,726.2   commit 23,600.8   stage=startup
22:19:40  采样 4    avail 17,691.6   commit 22,145.5   stage=solve（求解开始）
   …（求解推进 12 分钟，commit 平台期约 8,000–8,400，WS 稳步上升到 ~7,800）
22:31:46  采样149   avail  8,513.3   commit  8,036.5   ws 7,838.6   verdict=ok
22:31:51  采样150   avail  1,960.1   commit  2,005.1   ws 8,125.6   verdict=**warning**
22:31:57  采样151   avail  1,841.4   commit      **0.5**   ws 8,343.6   verdict=**hard_stop**
          reasons = ["physical_avail_hard_stop(1841.4 <= 4096.0 x2)", "commit_hard_stop(0.5 <= 4096.0 x2)"]
22:32:02  采样152   commit 917.0 / 22:32:07 commit 1,112.9（仍 hard_stop）
22:32:12  采样154   avail 8,676.2   commit 9,253.3   verdict=ok      ← server 已被终止后**内存恢复**
峰值：WS 11,086.1（**未触 WS 硬线 12,288**）；最低 commit **0.5**、最低 avail **1,020.5**
```

**关键分解（判断"是不是我们这个作业自己吃掉的"）**：

```text
22:31:46 → 22:31:51 的 5 秒内：
  commit  8,036.5 → 2,005.1   （−6,031.4 MB）
  avail   8,513.3 → 1,960.1   （−6,553.2 MB）
  而**本任务 server 的 WS 只涨了 +287.0 MB**（7,838.6 → 8,125.6）
终止后（22:32:12）内存立刻回到 commit 9,253 / avail 8,676
⇒ 这是**外部消费者**的阶跃式占用（不是 COMSOL 作业的渐进增长），且占用在 server 终止后释放。
   本记录**只陈述这一可确证事实**，不推断具体是哪个进程（时间线不含其它进程信息）。
```

**我的自查**：本会话在该时间窗内只做过 ≤140 MB 的模型哈希与 141 KB 的 xlsx 解析，
**未**读入任何 GB 级文件；`probe_legacy_drive_api.py` 只是写文件、未运行。

---

## 2. 管线行为：**正确**（这是本次最有价值的结论）

```text
分类：trigger_kind=threshold_crossed、is_hard_stop=true、**enforced_by=resource_gate**、is_drill_run=false
      ⇒ 真实资源事件被**如实标注**，没有被误标成演练、也没有被误标成基础设施故障
动作：steps = freeze_new_delivery → save_trigger_record → request_worker_end → **verify_ownership**
      → **terminate_server**（`Stop-Process -Id 26820 -Force`，rc=0）→ post_termination_verification
二次确认：termination_command_exit=0 / expected_pid_absent=true(0.0s) / port_closed=true(1.5s) /
      no_new_unexpected_comsolmphserver=true / **verified=true**
重跑分类：{retry: **false**, class: **resource_hard_stop**} ⇒ 资源硬停**不自动重跑**（§6）
signals：恰好 1 个；worker_state.solve_error = Java NPE（server 被切断后 study.run 的异常）
```
⇒ **这是本项目第一次"真实（非人为压低阈值）的硬停事件"被端到端正确处理**：
真实越线 → 归属核验 → 终止真实 server → 二次确认 → 阻断批次 → 不自动重跑 → 全部留痕。
它**独立于演练**地验证了 §7.1 的终止路径（U2 的语义在真实资源事件上同样成立）。

## 3. F1/F2/F3 修好的字段：在真实事件上如实工作

```text
checkpoint.thresholds.ws_hard_stop_mb = 12288.0（生效值）
checkpoint.thresholds_provenance = {drill: false, overrides: {}, effective: <默认>}   ← F1：来源自解释
hard_stop_verdict_sample_count = 3,  no_hard_stop_verdict_samples = false              ← F2：如实（旧码会恒真）
warning_verdict_sample_count = 1,    blocks_next_combination = true                    ← F3：如实（旧码取消场景恒假）
child pass_conditions 三键均为**新名**（peak_ws_lt_hard_stop=true / min_avail_ge_hard_stop=false /
   min_commit_gt_hard_stop=false）                                                      ← F1：改名生效且取值正确
batch aggregate 用 min_commit_gt_hard_stop（旧键不存在）                                ← 改名原子生效
```
⚠️ 注意：这些只证明**新字段在真实路径上如实工作**；**不**证明"生产路径数值逐一不变"——
r3e 因被终止而 `rows=0`，该项仍**未取得**。

## 4. 检查器 14/23 的失败项（全部由"真实硬停"派生，非新缺陷）

```text
rows_eq_7 / unique_freqs_eq_7 / drive_mismatch_0 / solve_error_is_null        ← 求解被终止，无 7 行
physical_hard_stop_samples_0 / commit_hard_stop_samples_0 / commit_warning_samples_0
min_commit_gt_6144 / no_blocked_reason                                        ← 真实越线所致
（trio 三布尔 = true；冻结 pre/post 均 MATCH；身份 pid_source=port_owner；端口 30 s 内关闭）
```

## 5. 结论与建议

```text
① r3e **不作为**"生产路径数值不变 / 23 条复现"的证据（rows=0）——该目标需在**干净条件下**重跑。
② r3e 作为**真实硬停事件**的记录**成立且有价值**：真实 resource_gate 路径端到端正确、不自动重跑。
③ **标准前置门禁不足**：r3e 启动时 avail 18,754 / commit 24,347（均**高于** 16,384 门禁），
   仍在 5 秒内被外部阶跃吃掉 6 GB commit ⇒ 建议生产运行也采用**更严**的前置门槛
   （例如 avail ≥ 18,000 且 commit ≥ 21,500，并在运行前连测两次确认无外部消费者在活动）。
④ 外部消费者**未归因**（无可确证证据）；任何后续资源敏感运行都应先做"两次采样 + 进程清单"。
⑤ 现场保留：`work/runs/lt2-resource-confirm-x080-n02-postpagefile-r3e/` 与 `_evidence-r3e/` 均未清理。
```
