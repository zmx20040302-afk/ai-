# 报告：T14 确定性化(A) + 正常收尾改名(B) + blocked_reason 分离(C) + F5 + T1 + T2

**日期**：2026-09-15
**依据**：父 agent 裁定 A/B/C（T14、改名、字段分离）＋ r3g 独立复核后新增的 F5 / T1 / T2
**被测件**：`work/tools` 下 5 个文件（哈希见 §8）。`rt_gate.py` 与其余 10 个冻结件**未改动**（逐个对照 1015 快照确认）。
**边界**：**未建 freeze**、**未跑 r3h**、**未启动 LT2 生产批次**、**未清理任何目录**。

---

## 0. r3g（已由你独立复核，此处只留接口）

你已独立复跑得到同一结论（23/23、all_pass、exit 0）。我这边同步记录的关键面：
child `status=pass`、`rows=7`、`pass_conditions` 13 项全布尔全 True、`pass_condition_shape_violations=[]`、
计数在 checkpoint 顶层（0/0；时间线 161 行 ⇒ 非空集）、`thresholds=12288` + `provenance{drill:false,overrides:{}}`、
`stop_line_event_count=0`、`signals/` 不存在、`termination=null`、`enforced_by=null`、
`normal_completion.trigger_kind=normal_completion_sidecar_exit`、三布尔 true（pre 10:09:25 / post 10:23:05）、
13 min 40 s。你给的 280 单元格对照（r3d/r3f/r3g）我未重复，直接引用你的记录。

⚠️ 记录一条现场事实：r3g 结束时无 COMSOL 进程；现在机器上有 **`ComsolUI`（pid 4808，约 2.1 GB）**——
那是"允许但记录"的图形界面（r3g 的 preflight 在 10:09 记录为无 GUI，说明它之后才出现）。我**没有**碰它。

---

## 1. 裁定 A：T14 确定性化 —— 结论比"摇摆"更严重

### 1.1 竞态根因（带行号）

```text
lt2_production.py::run_fake_combo_worker  旧代码：
    atomic_write_json(child_dir/"checkpoint.json", ck)
    set_state(stage="closed", stop=True, ...)
    return 0                       ← 立刻退出
supervise_child 的守卫判据（2222-2227 行）：
    _done_markers = stage=="closed" 或 checkpoint.json 存在；且 ss.verdict != "hard_stop"
    命中 ⇒ 写正常收尾记录
```

⇒ "已宣告收尾但进程仍在"的窗口只有**几毫秒**，而 supervisor 每 `gate_poll=0.3 s` 才轮询一次。
**写不写记录是纯粹的竞态。** 真 worker 因要拆 sampler / COMSOL server 天然驻留（r3f 的生产 child 目录确实留下了该记录），
所以**旧替身既不确定、又不保真**。

### 1.2 定量测量（新证据，`race_probe.py`，单变量：只差 `FAKE_CLOSED_LINGER_S` 1.5 vs 0.0）

| 组 | 落 `completion_record.json` | 守卫命中 | 重跑分类 |
|---|---|---|---|
| 修复版（1.5 s 驻留） | **15/15** | 15/15 | `normal_completion` 15/15 |
| 旧行为（0.0 s） | **0/15** | 0/15 | **`unclassified` 15/15** |

⇒ 两点新结论（比你原先的判断更强）：
1. **旧冒烟路径其实从未覆盖正常收尾守卫**（0/15 命中）——T14 一直是"两次都缺席 ⇒ 相等 ⇒ 通过"，**为错误的理由通过**；
2. 竞态还**连带改变分类**（`normal_completion` → `unclassified`），不只是少一个文件。

历史那次 T14 失败（81/82）正是负载让替身偶发驻留超过 0.3 s 的那一次。

### 1.3 修法（不是放宽断言）

```text
常量：FAKE_CLOSED_LINGER_S = 1.5（仅 fixed/确定性自测模式生效）
fake worker：原子写成功 ⇒ 宣告 closed 后 time.sleep(FAKE_CLOSED_LINGER_S) 再返回
```

T14 仍比对**全部**证据文件（含新名的收尾记录）⇒ 断言的证明力**没有**被削弱，反而第一次真正覆盖了守卫。
新增 **T14b**（命名纪律，见 §2）：正常路径必须有 `completion_record.json` 且**不得**有 `termination_trigger.json`。

### 1.4 稳定性（你要的 ≥5 次）

```text
套件 ×5（10:25:38–10:30:04，同一份代码 4E21A4C1）：83/83、83/83、83/83、83/83、83/83，各约 53 s
F5 之后重跑 ×5（10:33:26–10:37:51，代码 9D42CDD7）：83/83 ×5，各约 53 s
```

---

## 2. 裁定 B：正常收尾产物改名

### 2.1 改了什么

```text
· 新常量 COMPLETION_FILE_NAME = "completion_record.json"；正常收尾写它
  （TRIGGER_FILE_NAME = "termination_trigger.json" 从此**只**表示"发生过终止动作"）
· 记录内明示：termination_performed=false、enforcement_requested=false
  （连同既有 trigger_kind=normal_completion_sidecar_exit / is_hard_stop=false / enforced=false）
· CHILD_FILE_SPEC 增加该文件的语义说明（否则会被 describe_child_dir 记为 unexpected_files）
· describe_child_dir 的 kind 判定**只看** TRIGGER_FILE_NAME（正常收尾记录不得把目录判成 enforcement_probe）
```

### 2.2 读者清单（按你的要求：先查再改，不让名字好看而破坏断言）

| 读者 | 位置 | 处置 |
|---|---|---|
| enforce/drill 路径写触发记录 | `lt2_production.py`（termination 流程） | **不变** |
| `CHILD_REQUIRED_BY_KIND["enforcement_probe"]` | 同上 | **不变**（仍要求 trigger 文件） |
| `CHILD_FILE_SPEC` / `unexpected_files` | 同上 | 增加新文件名（r3g 的 inventory `unexpected_files=[]` 已验证） |
| `describe_child_dir` 的 kind 分支 | 同上 | **仅注释**（已用逻辑行逐行比对证明：37=37 行一致，去注释后完全相同） |
| T1/T7/T15（enforce/drill 断言） | `tests_lt2_supervisor.py` | **不变**（它们读的是终止路径） |
| T14（rglob 比对） | 同上 | 名称无关，继续比对（改名后比对的是新文件）；新增 T14b |
| guard 模式读者 | `min_exec_r8b_evidence.py` | 用 `getattr(P,"COMPLETION_FILE_NAME", P.TRIGGER_FILE_NAME)` 回退 ⇒ **同一套断言**也能跑历史快照（灵敏度需要） |
| `check_r3_conditions.py` | 你的检查器 | **零引用**（grep 确认，无需改） |
| `lt2_expected_inventory.json` | 冻结 AUX | 列的是 **drill** 的 trigger ⇒ 不受影响 |
| 历史文档 | `docs/*` | **不改**（它们是旧运行的历史记录；索引更新见 §2.4） |

### 2.3 灵敏度（`guard` 模式三向）

```text
修复版 exit=0 ｜ 1015 冻结件 exit=1 ｜ 2255 冻结件 exit=1
（1015 失败项含"落在 completion_record.json 且无 termination_trigger.json"与"termination_performed=false"
  —— 正是改名要保证的两条）
```

### 2.4 字段位置索引 v2（**取代** 2239 报告 §5 的对应两行，供后续运行使用）

| 事实 | 位置 |
|---|---|
| **正常收尾**记录 | `child_*/completion_record.json`（`trigger_kind=normal_completion_sidecar_exit`、`termination_performed=false`） |
| **终止动作**触发记录（enforce/drill） | `child_*/termination_trigger.json` |
| F2/F3 计数 | checkpoint **顶层** `hard_stop_verdict_sample_count` / `warning_verdict_sample_count` |
| 条件字典形状违规 | checkpoint 顶层 `pass_condition_shape_violations`（正常为 `[]`） |
| 批次阻塞 = 什么失败了 | `batch_manifest.blocked_reason` |
| 为何不重跑 | `batch_manifest.retry_class` / `retry_reason` / `auto_retry_attempted` |
| 冒烟/正常收尾守卫分类 | `child.normal_completion.trigger_kind`（`termination_trigger` 字段在正常路径为 null） |
| 检查器自证 | 检查器产物顶层 `checker_sha256` / `checker_path` / `checker_argv` / `checker_exited` |

> 历史运行仍按旧名（`termination_trigger.json`）存在，且**不追溯改名**——r3g 的目录保持原样。

---

## 3. 裁定 C：`blocked_reason` 与重跑分类分离

```text
新增 _set_blocked(result, reason, retry_class, retry_reason, auto_retry_attempted) —— 唯一写入口
· blocked_reason          ：**什么失败了**（如 `child_00_not_pass:status=fail_or_limited`）
· retry_class/retry_reason：**为何不重跑**（分类器给出的分类与理由）
· auto_retry_attempted    ：本次是否真的重跑过（与"分类器建议重跑"是两件事）
```

四处写入点全部改走该函数：preflight 门禁失败（无分类器意见 ⇒ `retry_*` 保持 None）、attempt_1 判失败、
attempt_2 仍失败（`auto_retry_attempted=true`）、软线阻塞下一组合。
三个字段在 manifest 里**始终存在**（未阻塞时为 None/False），避免"字段缺席 = 无从审计"。
`aggregate_pass_conditions.no_blocked_reason` 语义**不变**（`blocked_reason is None`）。

---

## 4. F5：空集/缺证据不得判通过

### 4.1 你点出的四项（全部确认）+ 一项同类

```text
· monitoring_ok                ← `not []` ⇒ True
· peak_ws_lt_hard_stop         ← `or 0` ⇒ 0 < 12288 ⇒ True
· commit_hard_stop_samples_0   ← `.get(...,0)==0` ⇒ True
· no_hard_stop_verdict_samples ← 空列表 ⇒ 计数 0 ⇒ True
```

修法一律是「**显式非空证据 + 阈值判定**」。**我另外把两处同类也修了并请你复核**：
- `failed_frequency_points_0` / `drive_voltage_mismatch_0`：`all()` 在空集上为真（虽被 `frequency_rows_7` 兜住，
  但报告里会出现"0 行却全称合格"的假陈述）⇒ 加 `bool(rows)` 前置；且 `Vdiff` 缺失/非数值不再被 `all()` 静默跳过。
- `blocks_next_combination`（F3）：空时间线同样**无法证明**"没有软线告警" ⇒ 现在判**阻塞**（fail-closed，同一原则）。

**并在实现中发现自己第一版修得不完整**：`commit_hard_stop_samples_0` 只判"非 None"仍然漏 —— 实测
`summarize_timeline` 对空时间线返回的是**整数 0**（不是 None），所以必须显式要求 `timeline_rows >= 1`。
这条已修（负向测试当场把它逼出来了，见 4.2）。

### 4.2 负向测试 + 三向灵敏度（你要求的"必须在旧代码上失败"）

新增 `F5a`：构造**空时间线**（keys 齐全、0 行）⇒ 断言 `status != "pass"`、四项必须为 False、
且 `blocks_next_combination is True`；另有 `F5b` 作为非空对照（仍须 `pass`，证明没把正常路径改坏）。

```text
修复版     exit=0   F5a/F5b 通过；F2b/F2d/F4 同时通过（F2 修复未被破坏）
1015 冻结件 exit=1   **只**失败 F5a，且空集通过项 = 四项全中 [monitoring_ok, peak_ws_lt_hard_stop,
                     commit_hard_stop_samples_0, no_hard_stop_verdict_samples]   ← 与你的探针结论一致
2255 冻结件 exit=1   失败 F5a + F2*/F4（两代缺陷叠加）
```

F5 之后**套件 ×5 仍 83/83**（说明更严的 `drive_voltage_mismatch_0`/空集判据没有误伤既有路径）。

---

## 5. T1：`--verify-snapshot` 不再把源漂移误报成快照损坏

`_compare` 现在返回 `(判定用 drift, rc, source_drift)`：快照模式的 **verdict 只看快照**，
源漂移进 `source_drift`/`source_drift_count` 独立字段，并附说明「源漂移不影响本次快照判定；
但该 freeze_id 不可再用于新运行」。两个调用点（`--verify` / `--verify-snapshot`）已同步。

**现场验证（就在当前工作区）**：

```text
--verify-snapshot freeze-20260915-1015-post-f2-counter-fix
    mode=snapshot-vs-manifest  drift_count=0  verdict=MATCH  source_drift_count=3  exit=0
--verify freeze-20260915-1015-post-f2-counter-fix
    mode=source-vs-manifest    drift_count=3  verdict=INVALIDATED_BY_CODE_DRIFT  exit=1
```

⇒ 与你的判断一致：**快照完好**（3 条漂移全来自源文件、mtime 晚于 r3g 结束），旧实现却把它报成 `SNAPSHOT_CORRUPTED`。

---

## 6. T2：检查器进入冻结集合 + 产物自证

```text
(a) freeze_snapshot.py 的 AUX 增加 "check_r3_conditions.py"
(b) check_r3_conditions.py 产物顶层新增：checker_sha256 / checker_path / checker_argv / checker_exited
    （写入之后只剩一次 print，没有可失败步骤 ⇒ 该字段与真实退出码一致）
```

**并按你在上一条消息里指定的两条语义检查一并落实**（因为你要求把检查器纳入本轮冻结，
否则冻结后它立刻被新版取代；若你已有并行版本，以你的为准并重跑一次即可）：

```text
· pass_conditions_all_bool  —— 非布尔即判失败并**打印字段名**
· child_status_pass         —— batch_manifest.children[0].status 与 checkpoint.status 都必须是 "pass"
```

现场验证：

```text
r3g：25/25 全通过（原 23 + 2），顶层含 checker_sha256=5ed0228e…、checker_argv、checker_exited=0
r3f：22/25，失败项 = [no_blocked_reason, pass_conditions_all_bool, child_status_pass]
     ⇒ 检查器现在能**自己**抓住 r3f 那一类缺陷，而不再只靠批次级 blocked_reason 兜住
```

**同类补齐（同一原则，我主动加的，请复核）**：`freeze_snapshot.py`（**冻结器自身**）原先也不在 AUX 里
⇒ 改它不会让任何 freeze 失效，而它决定"怎么判定冻结"。现已纳入 AUX。

---

## 7. 机械差异与声明范围

```text
diff(1015 snapshot → 现在) 只有 lt2_production.py 可比（其余为本轮新增/未入冻文件）
touched_defs = [<module>, _set_blocked, classify_trigger, combo_pass_conditions,
                describe_child_dir, finalize_after_solve, run_fake_combo_worker,
                run_supervisor, supervise_child]
touched_defs_outside_declared_scope = []          ← 无越界（声明范围已同步更新到 A/B/C/F5）
hunks=14  added=108  deleted=20
```

`tests_lt2_supervisor.py` 断言数 **82 → 83**（新增 T14b）；`check_r3_conditions.py` 条件数 **23 → 25**（新增 2 条）。
两处都是**有意增加**，请按新计数冻结。

---

## 8. 新哈希（请冻结这五个字节）

| 文件 | sha256 | 字节 |
|---|---|---|
| `work/tools/lt2_production.py` | `9d42cdd7371661b4cbe9cb3d8cd3808958007d5e5da850dcb5e38171bb529844` | 171,081 |
| `work/tools/min_exec_r8b_evidence.py` | `53e3f8090772bc2837a7f178c1424ce49da78414f08042a8f292861d794150c5` | 63,161 |
| `work/tools/tests_lt2_supervisor.py` | `16bead4e0899ba653afcbf6a5e07f26480aed0a2fe743a417fdc4f387328b966` | 66,006 |
| `work/tools/freeze_snapshot.py` | `93d6c917fa2659ee10ca90c23a8b33652266c2e82716b306a1f73375159b4e33` | 15,768 |
| `work/tools/check_r3_conditions.py` | `5ed0228ee1d031eb70ea60d9ba6e39368b9da2bad6b8f027def4f9c176d77ba8` | 14,748 |
| （未改动）`work/tools/rt_gate.py` | `23ef7fdcac58e4f6db675f6f8fb2ea6cdd2d63b007dc0175a5e5e0ae94844b40` | 11,140 |

对照：1015 快照 `lt2_production.py = f73549f4…`；本轮**未改动**的 10 个冻结件已逐个核过哈希相同。

---

## 9. 未做 / 待你决定

- **未建 freeze**；**未跑 r3h**。本轮改了 `lt2_production.py`（F5 + 记录形状），
  按既有纪律「旧批不能替新代码背书」，**新冻结建好后若要让这些字节被生产路径背书，需要一次新的资源确认运行**
  （建议 `r3h`，同组合、从新快照执行）。r3g 的结论仍然有效（它由 1015 快照背书、pre/post 完整夹住）。
- **未启动 LT2 生产批次**（明确禁止）。
- 请你复核两处"我主动多做一步"的地方：F3 空集判阻塞、`freeze_snapshot.py` 纳入 AUX。
- 你上一条指定的两条 checker 语义检查我已实现（§6）；若你已有并行版本，请以你的为准并让我重跑一次三向。

## 10. 证据索引

```text
work/runs/_evidence-abc-20260915/
  race_probe.py / race_probe.log / race_probe_result.json       A 的定量竞态证据（15/15 vs 0/15）
  t14_stability_summary.txt / t14_run{1..5}.log                 T14 稳定性 ×5（83/83）
  suite5_v2_summary.txt / suite5_v2_run{1..5}.log               F5 之后套件 ×5（83/83）
  f1f2_v6_new|s1015|s2255.json                                  F1/F2/F3/F4/F5 三向灵敏度
  guard_v2_new|s1015|s2255.json                                 B 改名 + 守卫语义三向灵敏度
  diff_vs_1015_v2.json / abc2.patch                             机械差异（outside=[]）
  linger0/lt2_production.py                                     B 组副本（仅 LINGER 常量不同，可逐字节复核）
work/runs/_evidence-r3g/r3g_checker_v2.json                     检查器 25/25 + 自证字段
work/runs/_evidence-r3f/r3f_checker_v2.json                     检查器 22/25（旧缺陷被抓）
```
