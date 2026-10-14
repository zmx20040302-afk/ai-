# r3c 结果是**未通过**（四项额外核对第 1 条失败）+ 守卫 v2 修复

- 日期：2026-09-14
- 上游：`freeze-20260914-2020-post-normal-completion-guard`（manifest `47b69e51…`）下的 r3c 资源确认
- 本轮结论先给最重要的：**r3c 的 23 条判据全过，但父 agent 指定的四项额外核对第 1 条失败** ⇒
  按"任何失败保留现场并停止"，**r3c 不作为"正常收尾零假触发"的证据**，未进入硬停演练。
- r3c 现场**完整保留**（`work/runs/lt2-resource-confirm-x080-n02-postpagefile-r3c/` 与 `_evidence-r3c/`）。

---

## 1. r3c 实测：修复意图**未达成**

```text
批次：exit 0 / status PASS / 检查器 23/23 all_pass=True
      （三布尔 true、rows=7、solve 763.3 s、网格 157,390、资源轴与 r3b 同量级）
但四项额外核对：
  1. 不存在 signals/ 目录，且 termination == null      → **FAIL**
     signals/child_00_attempt_1.signal.json 存在；termination 非 null
  2. normal_completion.trigger_kind == normal_completion_sidecar_exit
     且 is_hard_stop == false                          → PASS
  3. worker_returncode 非 null（真实退出码）            → PASS（= 0）
  4. 资源轴与 r3b 同口径                                → PASS
     （commit 最低 8,935.9 / WS 峰值 11,203.3 / avail 最低 7,403.1 / 160 行 / 无空档 / 硬停采样 0）
```

**关键时间线（同一 child，两个记录）**：

```text
20:12:30  守卫命中 → 记下 normal_completion（trigger_kind=normal_completion_sidecar_exit）  ← 正确
20:12:37  **仍然 enforce**（enforced_by=sidecar_health_gate，trigger_kind=unclassified_failure）
          → 写 signals + 覆盖落盘的 termination_trigger.json + 走 verified_emergency_termination
          （steps 里依然**没有** terminate_server；post_verification verified=true ⇒ 仍无害）
```

## 2. 根因（是我的实现缺陷，不是新问题）

```text
我把"记录只写一次"和"是否抑制 enforce"写进了**同一个条件**：
    if (_done_markers and normal_completion_rec is None and ss.verdict != "hard_stop"):
        ... 记一次 ...
        continue
⇒ 记录之后的**下一轮轮询**就不再满足该条件，落到旧判定路径；
  此时 sampler 早已退出（正常收尾），sidecar_health 报 sidecar_exited
  ⇒ decide_next_action = hard_stop_enforce(source=sidecar_health) ⇒ 照旧 enforce。
```

r3c 的 7 s 间隔（20:12:30 → 20:12:37）正是"记录一次"与"下一轮轮询"之间。

## 3. 守卫 v2（本次修复）

```text
(1) 抑制**持续**：守卫成立期间**每轮都跳过 enforce**（记录仍只写一次）；
(2) **有界**：新增 NORMAL_COMPLETION_GRACE_S = 60 s；超过即**升级处置**，
    action.source = "normal_completion_timeout"、enforced_by = "normal_completion_timeout_gate"
    —— 持续抑制必须封顶，否则 worker 收尾卡死会让 supervisor 永久阻塞（这是持续抑制必须付的代价）；
(3) 真实越线优先级不变：一旦 ss.verdict == "hard_stop"，守卫立即失效、照常 enforce（resource_gate）。
```
`enforced_by` 枚举由 8 个增至 **9 个**（新增 `normal_completion_timeout_gate`）。

## 4. 我上一轮的**测试保真度**缺陷（必须记下来）

```text
上一轮 guard 测试 12/12 全过，而真机 r3c 失败 —— 因为第一版替身**没有复现"sampler 已退出"**：
  · 替身写的 worker_state.sampler_pid = null
  · 于是旧代码走到 "not ws.get('sampler_pid') + in_startup" 分支 ⇒ 只是 sleep，从不 enforce
  · 测试因此**通过了错误的理由**
本次替身补齐 r3c 的**全部条件**：stage=closed + checkpoint.json + **sampler_pid 指向一个已结束的进程**
+ sampler_state 有正常样本（verdict=ok / sample_index=5 / last_sample_ts=now），并持有 3 s（≥15 轮轮询）。
```
**教训（已写入 `freeze-and-acceptance` 技能 §9）**：替身/复现器必须包含**真实故障的全部条件**，
否则"测试通过"只证明你构造的那个更弱场景被修好了 —— 与"跑很多次没复现"同属一类无效证据。

## 5. 灵敏度证明（同一套断言，在旧代码上**必然失败**）

| 被测版本 | 结果 | 失败项 | 关键观测 |
|---|---|---|---|
| **当前 work/tools** | **ok**（全部通过） | — | `enforcement_source=null`、signals 无、落盘 kind=`normal_completion_sidecar_exit` |
| **2020 快照**（只抑制一次 = r3c 缺陷） | **FAIL 7/14** | `enforced_by 为 null`、`没有 termination`、`没有 enforcement_source`、`**没有**写 signals`、`重跑分类为 normal_completion`、`落盘 kind 一致`、`多轮轮询后仍持续抑制` | `enforcement_source=sidecar_health`、signals **有**、落盘 kind=`unclassified_failure` —— **与 r3c 逐条吻合** |
| **2000 快照**（完全没有守卫） | **FAIL 12/14** | 含上面全部 + `守卫命中`/`is_hard_stop=false`/`decided`/`markers` | `worker_returncode=null`、signals 有 |

⇒ 该测试**不是空断言**：它能在旧代码上确定性地复现 r3c 的失败形态。

**有界升级路径也单独验了**（`--grace-s 1.5` + 替身活 6 s）：`enforcement_source=normal_completion_timeout`、
`enforced_by=normal_completion_timeout_gate`、signals **有**、`worker_returncode=0` 且**未挂死** ⇒ 封顶有效。

## 6. 其余回归（本轮最终字节上）

```text
enforced_by 单位表：9 个标签各自唯一、演练优先、无未声明值 → ok
演练路径（套件 T15 真跑产物）：顶层 trigger_kind=threshold_crossed / is_hard_stop=true /
                              **enforced_by=drill_gate** / is_drill_run=true → 一眼可辨
82 断言回归：82/82（新命名空间 ns-r8d2-final-20260914-2050），failures=[]
frozen smoke A/B/B2：三布尔 true、worker_returncode=0 已记录、enforcement_source=null、**无 signals 目录**
确定性：new_fields_all_equal=true + child 级字段全等
机械差异基线（对 2020 快照）：7 hunks / +44 / −18；touched_defs =
   [<module>, classify_enforced_by, supervise_child]；touched_defs_outside_declared_scope = []
```

## 7. 新哈希（请据此建新 freeze）

```text
被测件 work/tools/lt2_production.py
  bytes  = 153,287
  sha256 = 81936aeb0b5d42cbfdef5f973ba67c0abc9c21706d83dbd6cd1fe49cbf084f8a
AUX 取证工具 work/tools/min_exec_r8b_evidence.py（guard 模式：忠实替身 + 两种场景 + 灵敏度 --source）
  bytes  = 35,523
  sha256 = bb1fd1cba294be55516f1ebe242b37a609beb58ef107b5d4b78cc443312aa30f
其余 11 个冻结件与 2020 manifest 逐项相同（未改）
临时冻结（**非验收**，保留勿用）：
  freeze-20260914-min-exec-r8d2-provisional-not-for-acceptance  manifest 48c5bd1f…
  --verify / --verify-snapshot 均 MATCH / drift 0
证据汇总：work/runs/_evidence-r8d2/r8d2_final_summary.json
  b60925f54e9cad5b8fa1e83ae58c360222333bc641143260bcec238cfcd2b609
```

## 8. 建议

```text
1) 按 §7 建新 freeze（lt2_production.py = 81936aeb…）
2) 跑 **r3d**（新 run-id，从新快照执行，显式 --freeze-id），复核同一组 23 条 + 四项额外核对；
   预期：signals/ **不存在**、termination == null、normal_completion 记录在 manifest 里、rc=0
3) r3d 通过后才谈硬停演练；LT2 生产批次仍未启动
（r3c 现场不清理；r3c 的资源轴结论可复用，但"零假触发"这一条**必须**由 r3d 重新取得）
```
