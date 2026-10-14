# 报告：`hard_stop_verdict_sample_count` 落在布尔容器里 ⇒ 正常路径被误判失败（已修）

**日期**：2026-09-15
**触发**：父 agent 裁定「r3f 暴露了一个会作废整个 504 点生产批次的缺陷，请修它」
**结论**：缺陷**已定位、已修、已用最小执行证明**。新哈希在 §6，**未建 freeze、未跑 r3g、未启动生产批次**（等父 agent 冻结）。
**被修文件**：`work/tools/lt2_production.py`（生产件）、`work/tools/min_exec_r8b_evidence.py`（取证工具，AUX）

---

## 0. 先说一件必须先讲的事：恢复动作与我的修复**撞车**了

父 agent 从 2255 快照恢复 `work/tools/lt2_production.py` 时，我**正在同一文件上做修复**（两个写入者）。时间线（都有可复核痕迹）：

| 时刻 | 事件 | 痕迹 |
|---|---|---|
| 本轮开始 | 我读到的是 2255 版（`pc["hard_stop_verdict_sample_count"]` 在 `pass_conditions` 内、`all(pc.values())`） | 本轮第一次 `read` 的行号 1513/1538 |
| 之后 | 我施加 4 处修复 ⇒ 哈希 `f73549f4…` | `_evidence-f2status/diff_vs_2255.json`（current=f73549f4） |
| 之后 | 父 agent 的恢复把它覆盖回 `c3f45407…`（= 2255 快照，逐字节相同） | 本轮中段扫描又看到 `all(pc.values())` |
| 现在 | 我从父 agent 保全的 `_evidence-interrupted-20260915/*.interrupted` **逐字节恢复**了我的修复 | 两份哈希 MATCH（§6） |

**关键事实**：父 agent 保全的 `lt2_production.py.interrupted`（`f73549f4…`，164,242 B）与 `min_exec_r8b_evidence.py.interrupted`（`0fe3615d…`，58,149 B）**就是我这轮的修复版本**（内容标记已复核：`all_conditions_true` / `pass_condition_shape_violations` / `_rows7_ok` / `F2d_` / `F4_` / `system_memory_load_percent` 全在）。

⇒ 我按"逐字节等价"把它恢复回生产路径，**没有重写代码**（重写会引入无法与证据对齐的新字节）。
⇒ **请父 agent 冻结前先核一次哈希**（§6），避免再次出现"冻结的是旧字节"的情况。这不是追责，是 append-only 纪律在双写者场景下的必然要求：**哈希必须在报告时刻现场复核**。

---

## 1. 根因（与父 agent 的读法一致，补上行号与值）

`work/tools/lt2_production.py`（2255 版）：

```python
1511  pc = combo_pass_conditions(rows, summary, lt2c, cancel_rec, th)   # 返回**全布尔**
1512  pc["no_hard_stop_verdict_samples"] = (hard_stop_verdict_samples == 0)
1513  pc["hard_stop_verdict_sample_count"] = hard_stop_verdict_samples   # ← 整数！混进布尔容器
...
1538  "status": "pass" if all(pc.values()) else "fail_or_limited",      # ← 真值聚合
1539  "pass_conditions": pc,
```

- `hard_stop_verdict_samples` 在**正常路径**上是 `0`。
- `0` 在 Python 里为假 ⇒ `all(pc.values())` 为假 ⇒ `status = "fail_or_limited"`。
- 而 `0` 恰恰是**通过值**（"没有任何 hard-stop 样本"）。**正确的结果被当成失败。**
- `combo_pass_conditions` 本身返回的**全是布尔**（已在 §3.3 逐键确认）⇒ 唯一污染源就是这个计数器。
- 第二处同形聚合在收尾补写：`1925  d["status"] = "pass" if all(cp.values()) else "fail_or_limited"`（`cp` 含同一个计数器）。

**这是 F2 修复自身引入的缺陷**（`git`-like 追踪：2230 与 2255 两个冻结件都有此字段与聚合法，更早的 1940/2040 没有 F2 字段）——即"修掉空集判通过时，用值与真假的混同换来一个新的同类错误"。

### 为什么它必然作废整个批次（父 agent 判断成立，补一条机制）

- r3f 是 **F2 后的第一次正常生产运行**：演练那次 child 本就该 fail、r3e 那次被资源硬停 —— 两次都**掩盖**了它。
- 正常路径**每个组合**都会带 `hard_stop_verdict_sample_count = 0` ⇒ **504 个组合每一个都被判 `fail_or_limited`**。
- 批次级 `all_children_pass = all(c["status"] == "pass")`（2538 行）与 `no_blocked_reason`（2540 行）双双为假 ⇒ 跑 15–17 小时后**零个被接受的 child**。

---

## 2. 修复（逐条对应父 agent 的 1–4 条）

### 2.1 计数移出布尔容器（第 1 条）

```python
    pc = combo_pass_conditions(rows, summary, lt2c, cancel_rec, th)
    pc["no_hard_stop_verdict_samples"] = (hard_stop_verdict_samples == 0)
    # F2 计数**不进** pass_conditions（只放布尔条件）：计数器 0 是"通过值"，一旦混进
    # 条件字典，任何真值聚合都会把它读成假（r3f 实测缺陷）。
    conditions_ok, condition_shape_violations = all_conditions_true(pc)
    ...
    ck = {..., "warning_verdict_sample_count": warning_verdict_samples,
          "hard_stop_verdict_sample_count": hard_stop_verdict_samples,   # ← 顶层，与 F3 对称
          "pass_condition_shape_violations": condition_shape_violations,  # ← 始终落盘（正常为空）
          "status": "pass" if conditions_ok else "fail_or_limited",
          "pass_conditions": pc, ...}
```

**位置选择理由（单一真源、无别名）**：F3 的计数已经在**顶层** `warning_verdict_sample_count`。把 F2 计数也放顶层 ⇒ 两者对称、一个字段只有一处；**没有**新建 `verdict_counts` 之类的第二容器（那会产生"同一事实两个位置"的别名风险）。布尔判定仍在 `pass_conditions` 内（`no_hard_stop_verdict_samples`），语义不变。

### 2.2 结构性守卫（第 2 条）：`all_conditions_true`

```python
def all_conditions_true(conditions: dict) -> tuple[bool, list[str]]:
    violations = [k for k, v in conditions.items() if not isinstance(v, bool)]
    ok = bool(conditions) and not violations and all(v is True for v in conditions.values())
    return ok, violations
```

- **身份比较 `v is True`**（不是真值判断）⇒ `1` / `0` / `None` / 字符串**一律不算通过**。
- **非空** ⇒ 空集合判失败（保留"空集不得冒充通过"的既有教训）。
- **非布尔 ⇒ 登记字段名**并判失败：写入 `pass_condition_shape_violations: ["hard_stop_verdict_sample_count"]`。
- **两处状态写入都只走这一个函数**（1538 与 1925）⇒ 聚合口径单源，不存在第二条推导路径。

**为什么是"记账 + 判失败"而不是抛异常**：`finalize_after_solve` 抛异常会让 **checkpoint 都写不出来**（证据丢失、run 变成无 checkpoint，比"明确判失败"更糟）。这里的 fail-closed 是端到端成立的：形状违规 ⇒ `status=fail_or_limited` ⇒ 批次 `all_children_pass=False` ⇒ `blocked_reason` 落盘 ⇒ 退出码 6；同时**字段名**留在 checkpoint 里。**不静默、不放过**。

### 2.3 系统性排查（第 3 条）——不是只修一处

| 排查项 | 结果 |
|---|---|
| 全库 checkpoint 扫描（`**/checkpoint.json`） | 扫 **745** 个；**69** 个含非布尔条件；命中字段**全部且仅为** `hard_stop_verdict_sample_count`（**一个字段族**，无第二个） |
| 代码层"对条件字典做真值聚合"的表达式 | 命中 2 处，都在 `lt2_production.py`（1538 / 1925），**均已改为 `all_conditions_true`**；其余命中为 `tests_lt2_supervisor.py`（`T9`/汇总局部变量，非条件字典）与 `min_exec_r8b_evidence.py:538`（guard 模式自己的 checks，全布尔，另行确认） |
| 独立工具 `lt2r0_v2.py:334` 的 `all(res["pass_conditions"].values())` | **复核为安全**：该字典 8 个值全为布尔（唯一非常量 `monitoring_ok = (not gaps) and (not missing_cols) and sampler_rc == 0` ⇒ bool）。**未改动**（不在本次范围） |
| sampler 路径的 `pass_conditions`（1648 行） | 两个值都是布尔表达式（`sampler_rc == 0` / `.is_file()`）⇒ 安全 |
| 批次级 `aggregate_pass_conditions`（2536–2562） | 11 项全为布尔，且子项读取用 `is True` 身份比较 ⇒ 安全 |
| 消费方清单 | 全仓 `pass_conditions` 消费者：`lt2_production`（已修）、`min_exec_r8b_evidence`（已修）、`check_r3_conditions`（只读批次级聚合，父 agent 自补）、`tests_lt2_supervisor`（T17e 只查键存在性，无真值聚合）、`lt2r0_v2`（如上） |

### 2.4 retry 分类核查（第 4 条）——**未被污染**，但 blocked_reason 的措辞有误导性

- `classify_retry` 读 `pc = child.get("pass_conditions")`（2050 行），但**只在一处**用它：
  `2119  if err and pc.get("commit_hard_stop_samples_0") is not False:` —— 用的是**身份比较**，非布尔值不会冒充结论；且 r3f 的 `err` 为空（`solve_error=None`）⇒ 该分支根本没走到。
- r3f 的 `class = "normal_completion"` 来自 `tk == TRIGGER_KIND_NORMAL_COMPLETION`（2101 行分支）：
  `tk = trig.get("trigger_kind") or nc.get("trigger_kind")`（2057 行）——**完全由正常收尾守卫的 sidecar 记录决定，与 `pass_conditions` 无关**。
- ⇒ **分类输入正确**：r3f 确实没取消、没强杀，`normal_completion` 是**如实**标签（这正是③轮修好的守卫在正常工作）。
- ⚠️ 但 `blocked_reason` 的拼装 `f"child_{idx:02d}_not_pass:{child['status']}" + f"（不可自动重跑：{rc1.get('class')}）"`（2526–2528 行）把**状态**与**重跑分类**粘在一句里，于是"状态推导 bug"读起来像"因为正常完成所以失败"——**建议**（不擅自改）未来把二者分开表述，例如 `child_00 status=fail_or_limited; retry_class=normal_completion(不涉及重跑)`。

---

## 3. 证据

### 3.1 三向灵敏度（同一条命令、同一套断言，只换被测件）

命令（对每个 `--source` 完全相同，只有被测件不同 ⇒ 严格单变量 A/B）：

```
python work/tools/min_exec_r8b_evidence.py f1f2 --out <json> --run-id <rid> [--source <历史冻结快照>]
```

| 被测件 | sha256（前 16） | 退出码 | 断言 |
|---|---|---|---|
| **本修复** `work/tools/lt2_production.py` | `f73549f4d816f11f` | **0** | 12/12 通过 |
| 冻结 2255（r3f 实际跑的版本，含缺陷） | `c3f4540749959c72` | **1** | F2a/F2b/F2d/F4 失败 |
| 冻结 2230（F2 记录语义首次引入） | `5e7e84e304b8b767` | **1** | 同上 |

**2255 上的决定性与观测**（这就是 r3f 生产失败的**最小复现**，无需 COMSOL）：

```text
F2b 观测：no_hard_stop_verdict_samples = true   ← 实质条件为真
          hard_stop_verdict_sample_count = 0    ← 正确值（在 pass_conditions 内）
          status = "fail_or_limited"            ← 却判失败
          false_keys = ["hard_stop_verdict_sample_count"]   ← 唯一"假"键＝那个计数器
```

即：**全绿 + 唯一假键是计数器 + 状态失败** —— 与 r3f 生产现场同形。
复跑（恢复后、在最终字节上）：`_evidence-f2status/f1f2_v3_final_new.json`（exit 0）/ `…_v3_final_2255.json`（exit 1）。

### 3.2 最小执行里的"正常完成生产路径"用例（第 5 条）

新增/加强的断言（`min_exec_r8b_evidence.py` f1f2 模式）：

- **F2b（缺陷回归点）**：**7 行真实合格行** + 无取消 + 无 hard_stop 行 ⇒ 断言
  `no_hard_stop_verdict_samples is True` **且** 顶层计数 `== 0` **且** `status == "pass"` **且** 所有布尔条件 `is True`。
  7 行是**必须**的：旧探针用 `rows=[]` 会让 `frequency_rows_7=False`，于是"全绿"根本达不到、**复现不了该缺陷**（测试保真度）。
- **F2d（形状不变量）**：计数**不得**出现在 `pass_conditions` 里；`pass_condition_shape_violations == []`；`pass_conditions` 的值必须全是 bool。
- **F4（聚合器本身，纯函数）**：`{T,T}→(True,[])`；`{T, count:0}→(False,["hard_stop_verdict_sample_count"])`；`{}→(False,[])`；`{T,F}→(False,[])`；`{1}→(False,["a"])`。
- **F2a/F2c、F3a/F3b/F3c** 全部按新位置（顶层计数）读取，语义不变（取消路径 count=4；读失败 ⇒ count=None + 判阻塞）。

⚠️ **探针保真度缺口（已修，记录在案）**：合成时间线原本漏了 `system_memory_load_percent` 列，导致 `monitoring_ok=False`，我第一次跑 F2b 时"新代码也失败"——那是**探针缺陷**不是生产缺陷。补列后 F2b 通过，缺陷复现与修复证明才成立。（这与"先证明复现器的条件完整"是同一条纪律。）

### 3.3 机械差异（范围证明）

```text
snapshot(freeze2255) c3f4540749959c72  →  current f73549f4d816f11f
hunks=4  added=31  deleted=3
touched_defs = ['all_conditions_true', 'finalize_after_solve', 'run_combo_worker']
touched_defs_outside_declared_scope = []          ← 无越界
```

`_evidence-f2status/diff_vs_2255.json` + `f2status.patch`。**`supervise_child`（正常收尾守卫所在函数）不在 diff 内** —— 这一点在 §4 的 T14 判定里要用。

### 3.4 r3f 原始取证（保留，不清理）

- 目录保留：`work/runs/lt2-resource-confirm-x080-n02-postpagefile-r3f/`（append-only 守卫有效：父 agent 判定它"被中途失败遗弃"，实际它正常跑完了）。
- `_evidence-r3f/r3f_checker.json`：**22/23**，唯一失败项 `no_blocked_reason`。
- 实质条件 **14/14 全为 true**（含 `peak_ws_lt_hard_stop` / `min_avail_ge_hard_stop` / `commit_hard_stop_samples_0` / `no_hard_stop_verdict_samples` / `server_cleanup_ok` / `sampler_exit_ok`），其中唯一的非布尔项就是计数器。
- **F1 在生产路径上是对的**：`thresholds.ws_hard_stop_mb = 12288`、`thresholds_provenance = {drill: false, overrides: {}}`。
- **F2/F3 记录语义正确**：`stop_line_event_count = 0`、`warning_verdict_sample_count = 0`、`blocks_next_combination = false`、`hard_stop_verdict_sample_count = 0`、`no_hard_stop_verdict_samples = true`。
- **② preflight 加固按预期落盘**：`gate_pass=true`、`blocked_by=[]`、双采样 gap 5 s（Δavail 41.9 / Δcommit 62.9 MB）、`comsol_process_scan.clean=true`、无阻断进程、无允许 GUI 进程；顶层键为 sample1 投影。
- **冻结三件套全 true**：`freeze_hash_pre_post_match` / `executed_from_frozen_snapshot` / `freeze_evidence_complete`。
- 运行事实：155 行时间线、`rows=7`、`solve_seconds=744.5`、`stage=closed`、`solve_error=None`、`worker_returncode=0`、`retry=false / class=normal_completion`；时间线最大值：WS 11,058.6 MB、commit 最小 13,900.5 MB、avail 最小 10,256.0 MB（**均未越线**，无 warn/hard_stop 行）。
- 批次聚合 11 项中**只有** `all_children_pass` 与 `no_blocked_reason` 为假 —— 二者都由那个状态推导直接导致。

---

## 4. 82 断言回归：**同码两次 82/82 与 81/82** —— T14 是既有脆弱断言，不是本次回归

| 运行 | 命名空间 | 结果 |
|---|---|---|
| 第 1 次 | `ns-51224-1789437802` | **81/82**，失败 `T14 冒烟证据连跑两次逐字节一致`，差异文件 = `child_00_attempt_1\termination_trigger.json` |
| 第 2 次（同字节代码） | `ns-f2status-rerun-20260915` | **82/82，exit 0** |

**判定：T14 与我这次修复无关，且本身在"同一份代码"上就会摇摆。** 依据三条，逐条可复核：

1. **差异文件写在我的 diff 之外**：`termination_trigger.json` 由 `supervise_child` 的正常收尾守卫写（`2236  atomic_write_json(child_dir / TRIGGER_FILE_NAME, normal_completion_rec)`），而机械差异证明 `supervise_child` **不在 touched_defs 内**（§3.3）。该写入的判据是
   `2222-2227  (_done_markers: stage=="closed" / checkpoint.json 存在) and ss.get("verdict") != "hard_stop"` —— **完全不读 `pass_conditions` 或 `status`**。
2. **同一版本内自相矛盾**：T10 那次冒烟**写出了**该文件（T10 的 child 文件清单含 `termination_trigger.json`），T14 删目录重跑后**没写出**（最终清单 7 个文件、无该文件）。同码、同参数、两次运行 ⇒ 差异来自**竞态**：守卫只在"worker 已宣告收尾但进程尚未退出"的窗口被轮询到时才写记录；worker 退出快过 supervisor 首轮轮询就不写。
3. **历史一致性**：全部 `ns-*` 命名空间里，`termination_trigger.json` 只出现在 `liveproc` / `drill` 目录，**没有任何一个 smoke 目录**留下它 ⇒ 历史上 T14 之所以通过，只是因为守卫**通常**输掉这个竞态。

⇒ 由此得到**给父 agent 的裁定请求**（不在本次声明范围内，所以我没有擅自改）：
- 选项 A：把 T14 的比对改成"**同一运行内**两次采样"或用**确定性的收尾替身**（让守卫的竞态可控），使断言不再依赖 worker 退出时序；
- 选项 B：把正常路径的 `termination_trigger.json` 从"证据文件"里显式排除（它是**控制/审计记录**，与 `worker_state.json` 同类，天然带墙钟）；
- 选项 C：接受 T14 的偶发性并在验收记录里显式声明"该断言非确定"（最弱，不推荐）。
> 我的建议：**A**（保住断言的证明力）**＋ B 的说明**（明确该文件是审计记录、非资源事件）。理由：r3/r3b 的教训正是"正常路径不得留下看起来像硬停的终止记录"——现在这个文件虽然 `trigger_kind=normal_completion_sidecar_exit` / `is_hard_stop=False`（不会误导分类），但它出现在 child 目录里，仍会被"按文件名看证据"的审计误读。

---

## 5. 未做的事（保持边界）

- **未建 freeze**（父 agent 说"我建新 freeze"）。冻结前请复核 §6 的两份哈希；`work/tools` 任何一处被改，`--freeze-id` 运行都会按既有纪律退出 11。
- **未跑 r3g**（等父 agent 冻结后，用新 run-id `lt2-resource-confirm-x080-n02-postpagefile-r3g`、`--freeze-id <新冻结>`）。
- **未启动 LT2 生产批次**（明确禁止）。
- **未改** `check_r3_conditions.py`（父 agent 自补两条）、`tests_lt2_supervisor.py`（保持 82 断言的既有口径，便于冻结后回归）、`lt2r0_v2.py`（复核为安全）。
- **未清理**任何 run 目录 / 命名空间（含 r3f、被中断的 `ns-50128-…`、以及本次新增的 `_evidence-f2status` 与两次套件命名空间）。

---

## 6. 新哈希（请冻结这两个字节）

| 文件 | sha256 | 字节 |
|---|---|---|
| `work/tools/lt2_production.py` | `f73549f4d816f11fa5f631b0e13b886435b649f9fff24f441f4439e7a5a12c70` | 164,242 |
| `work/tools/min_exec_r8b_evidence.py` | `0fe3615dce6039fe83437ffecf59b1f258bd9a03bec8977554d7442586dbb557` | 58,149 |

（对照：2255 快照的 `lt2_production.py` = `c3f4540749959c72ddac424051f9795169e3f20f204827a1788dfc9e1e1ad9ad`，162,186 B；本次 `work/tools/rt_gate.py` **未改动**。）

**本次修复的两个字节来源**：`work/runs/_evidence-interrupted-20260915/lt2_production.py.interrupted` 与 `…/min_exec_r8b_evidence.py.interrupted`（父 agent 保全），我用 `shutil.copyfile`（**不是** `copy2`，避免 0o444 只读属性传染）恢复，并逐字节核对哈希一致。

---

## 7. 证据文件索引

```text
work/runs/_evidence-r3f/r3f_checker.json             r3f 检查器 22/23（唯一失败 no_blocked_reason）
work/runs/_evidence-r3f/r3f_argv.txt                 r3f 的完整调用参数（r3g 照此改 run-id/freeze-id）
work/runs/_evidence-r3f/r3f_stdout.log               r3f RESULT 行（blocked_reason）
work/runs/_evidence-f2status/f1f2_v3_final_new.json  修复版：12/12 通过（exit 0）
work/runs/_evidence-f2status/f1f2_v3_final_2255.json 2255 版：F2a/F2b/F2d/F4 失败（缺陷复现）
work/runs/_evidence-f2status/f1f2_v2_2230.json       2230 版：同样失败（缺陷族谱）
work/runs/_evidence-f2status/diff_vs_2255.json       机械差异：outside=[]、touched_defs=3 个
work/runs/_evidence-f2status/f2status.patch          补丁原文
work/runs/_evidence-f2status/tests_lt2_supervisor.log 第 1 次套件（81/82，T14 失败）
work/runs/_evidence-f2status/tests_rerun.log          第 2 次套件（82/82，同字节代码）
```
