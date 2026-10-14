# r8d：正常完成守卫 + 真实退出码 + `enforced_by`（硬停演练前必修项）

- 日期：2026-09-14
- 授权：父 agent 裁定「r3b 报的既有现象**必须在硬停演练之前修**」；本文覆盖该修复与最小执行。
- 上一轮：`docs/TO_CODEX_report-20260914-r3b-resource-confirm-pass.md`（r3b 结果）。
- **我同意多跑一次 r3c**：本次改的正是**收尾路径**（何时 enforce、如何记退出码），
  而 r3b 验证的恰恰是收尾路径（server 清理、端口关闭、stage=closed）——
  改了被验证的那段，验证就得重做；十余分钟成本换掉「验证对象已变却仍引用旧结论」的风险，值。

---

## 0. 一句话结论

四项要求全部落实并已真跑取证：**正常收尾不再 enforce**（并记为
`trigger_kind=normal_completion_sidecar_exit`）、**真实 worker 退出码不再为 null**、
**演练与正常收尾在记录里一眼可辨**（`enforced_by=drill_gate` / `is_drill_run=true`），
**阈值与判定逻辑未动**（除"正常完成不走 enforce"这条本身）。82 断言 **82/82**。

---

## 1. 修了什么（逐条对上父 agent 的要求）

### ① 轮询加「正常完成守卫」

```text
命中判据（只用**正常完成的正面证据**，两者都只在求解收尾之后才可能出现）：
    stage == "closed"  或  checkpoint.json 已存在
附加条件：ss.verdict != "hard_stop"     ← 真实越线**永远优先**，绝不被降级为「正常收尾」
命中后：不 enforce、不写 signals（没有终止要求）、等 worker 自然退出 → 记**真实**退出码
记录：  trigger_kind = normal_completion_sidecar_exit，is_hard_stop = false，enforced = false
```
未命中时行为**完全不变**：真硬停发生在 solve 期间（`stage` 为 solve/loading，且无 checkpoint）⇒ 照常 enforce。

### ② `worker_returncode` 不得因 `enforced` 而为 null

```text
正常路径：守卫使其不再走 enforce ⇒ 回到 `proc.wait(30)` ⇒ 真实退出码（实测 0）
enforce 路径：原本 break 后立即读 proc.returncode（可能仍为 None）⇒ 新增**有界**等待
    ENFORCE_WORKER_WAIT_S = 5，`proc.wait(timeout=5)`；拿不到就**如实留 null**（不编造）
    rc 只用于 status 兜底字符串，**不参与任何判定**
```

### ③ 演练路径可判读：`enforced_by`（+ `is_drill_run`）

```text
classify_enforced_by(action_source, trigger_kind, drill) → 8 个**单一含义**标签：
  drill_gate（演练优先）/ resource_gate / integrity_gate / worker_startup_gate /
  worker_requested_gate / sampler_verdict_gate / sidecar_health_gate / unclassified_gate
落点三处，值同源：触发记录顶层 + 触发记录 trigger 子对象 + termination_rec
```

### ④ 阈值 / 判定逻辑未动

机械证据见 §3：改动只落在 `classify_enforced_by`（新增）、`classify_trigger`（新增分支）、
`classify_retry`（新增分支）、`verified_emergency_termination`（新增字段）、`supervise_child`（守卫+字段）。
`decide_next_action`、`combo_pass_conditions`、`Thresholds`、`rt_gate.py` **一行未动**。

---

## 2. 最小执行：命令 / exit code / 条件表

前置：本轮临时冻结（**非验收**）`freeze-20260914-min-exec-r8d-final-provisional-not-for-acceptance`
manifest `657f372413a250b401b1a13f08f82d6fdd829e3ad669e39463d586203ebc66c0`，`all_ok=true`、`window_drift=[]`。

| 用例 | 命令要点 | exit | 判据 | 结果 |
|---|---|---|---|---|
| **守卫（确定性）** | `min_exec_r8b_evidence.py guard --run-id lt2-min-exec-r8d-final-guard` | 0 | 12 项检查全 true（见 §2.1） | **PASS** |
| `enforced_by` 单位表 | `... enforced-by` | 0 | 8 个标签各自唯一、演练优先、无未声明值 | **PASS** |
| **演练路径** | 直接驱动 `supervise_child(drill=True, ws_hard_stop_mb=5000)`（新命名空间） | — | 6/6：顶层 `enforced_by=drill_gate`、`is_drill_run=true`、`is_hard_stop=true`、分类仍 `drill_hard_stop`、`worker_returncode=0` | **PASS** |
| frozen smoke A（空格字面量 + freeze-id） | `... smoke --freqs-raw "5 10 15 20 25 30 35"` | 6 | 三布尔 true；`worker_returncode=0` 已记录；**无 signals 目录**；`enforcement_source=null` | **PASS** |
| frozen smoke B / B2（逗号，同输入两次） | `... smoke --freqs-raw "5,10,...,35"` | 6 / 6 | 同上；`new_fields_all_equal=true` + child 级字段相等 | **PASS** |
| 82 断言回归 | `tests_lt2_supervisor.py --namespace ns-r8d-final-20260914-2115` | 0 | **82/82**，`failures=[]` | **PASS** |

> exit 6 = `BLOCKED_OR_LIMITED` 是 `fake-combo-worker` 的既有语义（其 `pass_conditions` 只有 2 项，
> 故批次级 4 项判 false）——与 ②③/r8d 无关，前几轮已用旧快照旧代码做 `behaviour_equal=true` 对照。

### 2.1 守卫测试的 12 项检查（确定性复现 r3/r3b 收尾竞态）

做法：把 `P.SELF` 换成替身脚本（`supervise_child` 用它拼 worker 命令），替身写上
`stage=closed` + checkpoint 后**再活 3 秒** ⇒ 轮询**必然**命中竞态窗口（不是靠碰运气）。

```text
[✓] 守卫命中并记为正常收尾        [✓] 不是资源硬停（is_hard_stop=false）
[✓] decided 不是 hard_stop_enforce（= observe_normal_completion）
[✓] 记录含正面证据 markers（["worker_stage_closed","checkpoint_present"]）
[✓] enforced_by 为 null（未 enforce）  [✓] 没有 termination 记录  [✓] 没有 enforcement_source
[✓] **没有**写 signals 文件         [✓] worker_returncode 已记录且为 0
[✓] worker_returncode 非 null（① 已修） [✓] 重跑分类为 normal_completion
[✓] 落盘记录 trigger_kind 一致
```

落盘的正常收尾记录（`normal_completion_record_final.json`，原文）：

```json
{ "trigger_kind": "normal_completion_sidecar_exit", "is_hard_stop": false,
  "enforced": false, "enforced_by": null,
  "decided": {"action": "observe_normal_completion", "source": "normal_completion_guard",
              "reason": ["worker_stage_closed", "checkpoint_present"], "note": "正常收尾：不 enforce、不写 signals（没有终止要求）；等 worker 自然退出以取得**真实** worker_returncode"},
  "normal_completion_markers": ["worker_stage_closed", "checkpoint_present"],
  "wording_note": "本记录**不是**终止要求、**不是**资源事件：trigger_kind=normal_completion_sidecar_exit；只有 threshold_crossed 才是资源硬停",
  "reason": "worker 已产出 checkpoint / 已宣告 stage=closed ⇒ 这是**正常收尾**：sidecar 退出是 worker 自己停的，不得据此 enforce",
  "at": "2026-09-14T04:00:00" }
```

### 2.2 演练 vs 正常收尾：一眼可辨（裁定 ③ 的核心交付）

| 字段 | **演练**终止记录 | **正常收尾**记录 |
|---|---|---|
| `trigger_kind` | `threshold_crossed` | `normal_completion_sidecar_exit` |
| `is_hard_stop` | **true** | **false** |
| `enforced_by` | **`drill_gate`** | **`null`**（未 enforce） |
| `is_drill_run` | **true** | 不适用（无终止） |
| `enforced` | （无此字段，动作即终止） | **false** |
| `decided.action` | `hard_stop_enforce` | `observe_normal_completion` |
| 有没有 signals 文件 | 有（`<run_id>/signals/<child>.signal.json`） | **没有** |
| `worker_returncode` | 真实值（实测 0） | 真实值（实测 0） |

⇒ 演练之后**不可能**再把"正常收尾的假触发"误读成"演练的真终止"，
因为两者在 `trigger_kind` / `enforced_by` / `is_drill_run` / `enforced` / signals 有无 上全部不同。

---

## 3. 机械差异基线（对**上一个冻结快照** 2000）

```text
快照 = .../freeze-20260914-2000-post-three-booleans/snapshot/lt2_production.py  8f49ab4e… 141,673 B
当前 = work/tools/lt2_production.py                                            5c3550d2… 150,973 B
差异 = 12 hunks / +130 行 / −1 行
  patch 12,415 B  d6ec7dee810a1eeead8a36a5aa6c49d85d68258bd5b139e814d883965c6edf15
唯一的删除行（在声明范围内，被下面一行取代）：
  -    tk = trig.get("trigger_kind")
  +    tk = trig.get("trigger_kind") or nc.get("trigger_kind")      ← 见 §4 的说明
touched_defs = [<module>, classify_enforced_by, classify_trigger, classify_retry,
                verified_emergency_termination, supervise_child]
touched_defs_outside_declared_scope = []
```

---

## 4. 两处必须说明的实现取舍（不是自作主张，是被既有冻结件约束）

**① 正常收尾记录**不塞进 `res["termination_trigger"]`**，单独放 `normal_completion`。**
原因：`tests_lt2_supervisor.py` 的 **T12 明确断言正常路径 `termination_trigger is None`**
（冻结件，不得改）。因此 `classify_retry` 改为两处合看 trigger_kind
（`trig.get("trigger_kind") or nc.get("trigger_kind")`）——这就是 §3 里那 1 行删除的来源。
落盘的 `child/termination_trigger.json` 仍然按父 agent 要求写正常收尾记录（文件名不变）。

**② `verified_emergency_termination` 的 saved-record 顶层**也回显 `enforced_by` / `is_drill_run`。
第一版只写在 `trigger` 子对象里（值正确），但"一眼可辨"要求不该下钻一层 ⇒ 已在顶层回显
（`trigger` 内仍保留，值同源）。这一改动只影响 enforce 路径。

---

## 5. 新哈希（请据此建新 freeze）

```text
被测件 work/tools/lt2_production.py
  bytes  = 150,973
  sha256 = 5c3550d27a13359567a27536280a60930f75c89b4323737d798931aee153b398
AUX 取证工具 work/tools/min_exec_r8b_evidence.py（新增 guard / enforced-by 两个模式）
  bytes  = 30,996
  sha256 = a0e0b456eb5facda772d6606c8e1eef3d3de4fe98d141493d8cc83ea21d22ddd
其余 11 个冻结件与 2000 manifest 逐项相同（未改；含 rt_gate.py / lt2_sampler.py / tests_*.py）
临时冻结（**非验收**，保留勿用）：
  freeze-20260914-min-exec-r8d-final-provisional-not-for-acceptance  manifest 657f3724…
  --verify / --verify-snapshot 均 MATCH / drift_count=0（源码自建冻后未再改动）
全部证据哈希：work/runs/_evidence-r8d/evidence_hashes.json
  fe9affc7cc9297390403f6c5e4defa202075ad6b81b9bd46e54aa3024535c891
```

---

## 6. r3c 我建议这样跑（等你建新 freeze）

```text
--run-id lt2-resource-confirm-x080-n02-postpagefile-r3c（新 id，不复用 r3/r3b）
--combos '[[0.8,2]]'  --freqs '5,10,15,20,25,30,35'
--freeze-id <新 freeze>                 ← 显式带，三布尔应为 true
从**新快照**执行；不加 --drill、不压低阈值、前置门禁默认、单实例串行、后台作业
```

r3c 完成后我会额外核对三件事（都是本次修复的**真机**落点）：

```text
1) worker_returncode 非 null（应为 0）
2) normal_completion.trigger_kind == normal_completion_sidecar_exit
   （真机 teardown 窗口比 fake 长，r3/r3b 都命中了这个窗口 ⇒ 预期本次会命中）
3) **不存在** signals/ 目录，且 termination == null（真机首次做到"正常收尾零假触发"）
4) 资源轴判据与 r3b 同口径复现（commit/WS/avail/160 行量级）
```

---

## 7. 未做

```text
未执行硬停演练（U1–U3）        未启动 LT2 生产批次
未改阈值 / 判定逻辑 / rt_gate.py    未复用任何既有 run-id，未清理任何现场
```
