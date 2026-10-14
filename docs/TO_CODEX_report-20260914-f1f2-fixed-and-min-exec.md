# F1/F2 修复 + 最小执行（含灵敏度证明）—— 待建新 freeze

- 日期：2026-09-14
- 来源：硬停演练发现的两处"记录名与实际语义不一致"；父 agent 裁定 **b1 直接改名（不留别名）**
- 基线冻结：`freeze-20260914-2040-post-guard-persistent`（`lt2_production.py` = `81936aeb…`）
- 状态：**代码已改 + 最小执行已完成 + 82 断言回归通过**；**等父 agent 建新 freeze**，之后再跑 r3e 与演练重跑
- 未做：**未启动 LT2 生产批次**、未跑 r3e（需新冻结）、未重跑演练（需新冻结）

---

## 1. 裁定落实

| 裁定 | 落实 |
|---|---|
| ① `min_commit_gt_4096` → `min_commit_gt_hard_stop`，**同一批原子完成** | 生产点（`combo_pass_conditions`）与唯一消费者（`run_supervisor.aggregate_pass_conditions`）**同批改**；全仓库 grep 确认**无悬空引用**（除历史 `docs/` 记录与独立脚本 `lt2r0_v2.py` 的自有同名键——后者父 agent 早已裁定不改） |
| ① **不留过渡别名** | 未留任何 `_deprecated` 别名；`grep min_commit_gt_4096` 在 `lt2_production.py` 中只剩**注释里的历史说明** |
| ② `thresholds_*` **只放单源** | 采纳：`thresholds`（生效值，已有）+ `thresholds_provenance`（来源，新增）都只在 **checkpoint** 里；**撤销**我原方案里往 `pass_conditions` 塞 `thresholds_used`/`thresholds_source` 的复制（那是第二真相源） |
| ② F2 的 fail-closed 附加项**单列登记** | 见 §5（它改变的是**读失败**情形的行为，方向为 fail-closed） |

## 2. 改动清单（4 处 + 1 处 meta，逐条）

```text
(1) run_combo_worker：th = Thresholds()  →  th, th_rec = resolve_thresholds(args)
    （与 supervisor/sampler 同源；生产路径无 --drill ⇒ 返回默认值 ⇒ 数值不变）
(2) combo_pass_conditions：三键去数字改名，并加注释说明"名字不得内嵌数字"
      peak_ws_lt_12288      → peak_ws_lt_hard_stop
      min_avail_ge_4096     → min_avail_ge_hard_stop
      min_commit_gt_4096    → min_commit_gt_hard_stop
(3) run_supervisor.aggregate_pass_conditions：同步改名（唯一消费者）
(4) finalize_after_solve：
      · 时间线**只读一次**（同一份快照供两处使用）
      · F2：hard-stop verdict 行数**始终统计**（旧码只在 cancel_rec is None 时读）
      · 读失败 ⇒ None ⇒ no_hard_stop_verdict_samples 判 False（**fail-closed**）
      · 新增 hard_stop_verdict_sample_count
      · blocks_next_combination 的取值路径**保持旧语义**（取消时仍不看时间线）——见 §6 F3
(5) run_combo_worker → finalize_after_solve 的 meta：新增 thresholds_provenance = th_rec
      （drill_thresholds 直接复用 th_rec，不再二次调用 resolve_thresholds ⇒ 同源）
```

## 3. 最小执行 (a)–(d)：**7/7 通过**（`f1f2_new.json`）

| 检查 | 观测值 |
|---|---|
| **F1a 调用方使用生效阈值**（AST 层） | `uses_resolve_thresholds=true`、`bare_default_Thresholds=false` |
| **F1b 生产路径阈值=默认且来源自解释** | `thresholds.ws_hard_stop_mb=12288.0`、`thresholds_provenance.drill=false` |
| **F1c 生产路径三条件按新名存在且取值正确** | `peak_ws_lt_hard_stop=true`/`min_avail_ge_hard_stop=true`/`min_commit_gt_hard_stop=true`；`old_names_present=[]` |
| **F1d 演练路径用生效阈值并反映到摘要与判定** | `thresholds=5000.0`、`stop_line_event_count=5`、`peak_ws_lt_hard_stop=false`、`provenance.overrides={ws_hard_stop_mb:{default:12288.0, drill_value:5000.0}}` |
| **F2a 取消路径如实统计** | `no_hard_stop_verdict_samples=false`、`count=4` |
| **F2b 生产路径（0 行 hard_stop）** | `true`、`count=0` |
| **F2c 读失败 fail-closed** | `no_hard_stop_verdict_samples=false`、`count=None`（**不得为 True**） |

### 3.1 端到端（经真实 CLI）覆盖到层级必须说清

```text
本 smokes 用 fake-combo-worker ⇒ 其 checkpoint 只有 2 项 pass_conditions、不经 finalize_after_solve，
故 **child 级三键不在本层出现**（renamed_keys_present 全 false 属预期，不是缺陷）。
本层能证明且已证明的是**批次聚合层**：aggregate 用 `min_commit_gt_hard_stop`，
旧键 `min_commit_gt_4096` **已不存在**（rename_end_to_end.json，含 scope_note）。
child 级端到端 = 由 **r3e**（生产路径，真 worker）与**演练重跑**（演练值）确认。
```

## 4. 灵敏度（(e) 项）：同一套断言跑在 **2040 旧码**上 —— **6/7 失败**（逐项）

| 检查 | 新码 | 旧码 | 旧码观测 | 失败类型 |
|---|---|---|---|---|
| F1a 调用方使用生效阈值 | ✔ | **✘** | `uses_resolve_thresholds=false`、`bare_default_Thresholds=true` | **取值级**（AST 实证：旧码裸建 `Thresholds()`） |
| F1b 生产路径阈值=默认+来源 | ✔ | ✔ | 与新码相同 | **不具鉴别力**（探针自己注入 provenance；已如实登记） |
| F1c 生产路径三条件按新名 | ✔ | **✘** | 新名全为 `null`；旧名 `[peak_ws_lt_12288, min_avail_ge_4096, min_commit_gt_4096]` 存在 | 键名级 |
| F1d 演练路径生效值 | ✔ | **✘** | `peak_ws_lt_hard_stop=null`（其余同：thresholds=5000、count=5） | 键名级 |
| **F2a 取消路径如实统计** | ✔ | **✘** | 旧码 `true`（应为 false）、`count=null` | **取值级（空集恒真）** |
| F2b 生产路径 0 行 | ✔ | **✘** | `true` 但 `count=null`（无该键） | 键名级 |
| **F2c 读失败 fail-closed** | ✔ | **✘** | 旧码 `true`（应为 false） | **取值级（空集判通过）** |

**结论**：F1 的**取值级**鉴别力来自 F1a（AST：调用方是否用生效阈值）——这正是 F1 缺陷的所在地
（`finalize_after_solve` 本身取参 `th`，故对旧码直接传 drill th 也会算出 5000，**不能**用来鉴别）；
F2 的**取值级**鉴别力来自 F2a/F2c（旧码把"空集"判成通过）。逐项明细见 `f1f2_sensitivity_detail.json`。

## 5. F2 的 fail-closed 附加项（单列登记）

```text
改动：时间线读失败时，旧码 `engine_verdicts=[]` ⇒ `len(hard)==0` ⇒ no_hard_stop_verdict_samples = **True**
      （空集判通过）；新码读到异常 ⇒ None ⇒ 判 **False**，并给出 count=None。
性质：**行为改变**（仅在"读失败"这一原本就异常的情形），方向 = fail-closed，与技能 §3「空集合判失败」一致。
证据：F2c（新码 false/None；旧码 true/None）。
```

## 6. F3（新登记，本轮**未改**，取舍由父 agent 定）

```text
现象：`blocks_next_combination = any(v.get("verdict")=="warning" for v in engine_verdicts)`，
      而 engine_verdicts 仍在 `cancel_rec is None` 门控下取值 ⇒ 取消的 child 恒为 False
      （即使时间线里有 warning 行）。
为何本轮不改：它在**批次流程里不可观测**——run_supervisor 先判 `child["status"] != "pass"`
      再判 `blocks_next_combination`，而非 pass 的 child 早已 break；
      且它不在父 agent 批准的改动清单内（"只碰方案里列出的那几处"）。
建议：若要与 F2 同口径，把 warning 判定也改为"始终统计"，并给 count；那属于**另一批**改动。
```

## 7. 回归与机械差异

```text
82 断言套件（新命名空间 ns-f1f2-20260914-2240）：**82/82**，failures=[]（键改名/增键未破坏冻结测试）
机械差异 vs 2040 快照：**5 hunks / +35 行 / −19 行**，touched_defs =
   [combo_pass_conditions, finalize_after_solve, run_combo_worker, run_supervisor]
   touched_defs_outside_declared_scope = []      （首次跑出 combo_pass_conditions 越界，
     原因是我探针的声明范围列表**过时**——F1 方案里明确列了它；补进声明范围后为 []）
patch 5,581 B  sha256 22766e511bfa6be7702570fa44b58df1d4c32c60c0b12a3a57bdc0c8a7b01058
冻结化最小执行：临时冻结 all_ok=true / window_drift=[]；frozen smoke A/B/B2 三布尔 true +
   确定性对照 new_fields_all_equal（exit 0）；guard 两场景（持续抑制 / 有界升级）exit 0；
   enforced_by 9 标签表 exit 0；临时冻结 --verify 与 --verify-snapshot 均 MATCH（drift 0）
```

## 8. 新哈希（请据此建新 freeze）

```text
work/tools/lt2_production.py
  155,022 B   0b6ee62a29fa2b000300ef4753401551982aba18ec2eab95b75e818ec9ee6b62
work/tools/min_exec_r8b_evidence.py（新增 f1f2 模式：AST 调用方检查 + (a)-(d) + 灵敏度 --source）
   46,010 B   85c0cd0dd382adc3529f…（全文见 evidence_hashes.json）
临时冻结（非验收，保留勿用）：
  freeze-20260914-min-exec-f1f2-provisional-not-for-acceptance   manifest 61c7e15dd3a7264880720e404ba6735178f6edcef41711ce47bec1f33b81b00b
全部证据哈希：work/runs/_evidence-f1f2/evidence_hashes.json  c2ae33302526a72d…（重写 rename_end_to_end 后以文件内实际值为准）
```

## 9. 历史产物声明（父 agent 要求，必须写明）

```text
**历史产物（如 r3d 的 child/checkpoint.json、以及所有 2040 及更早的 run）携带旧键名**
（`peak_ws_lt_12288` / `min_avail_ge_4096` / `min_commit_gt_4096`，批次级同理）。
它们是**只读证据**：**不得**按新语义重新解读，也**不得**用新键名去检索旧产物
（会得到"键不存在"而误判为缺失）。新旧对应关系：
  peak_ws_lt_12288   ↔ peak_ws_lt_hard_stop
  min_avail_ge_4096  ↔ min_avail_ge_hard_stop
  min_commit_gt_4096 ↔ min_commit_gt_hard_stop
（旧产物中三键的**数值**仍有效，因为当时生效阈值即默认值。）
```

## 10. 下一步（等你建新 freeze）

```text
1) 你按 §8 建新 freeze（lt2_production.py = 0b6ee62a…；建议继续把 min_exec_r8b_evidence.py 纳入 AUX）
2) **r3e**（生产路径资源确认）：新 run-id、显式 --freeze-id、不加 --drill、不压阈值、
   前置门禁照常、无并行负载。期望：r3d 的 23 条判据**全部复现**（数值不变），
   且 child checkpoint 在新代码下自洽：三键为新名、`thresholds_provenance.drill=false`、
   `hard_stop_verdict_sample_count=0`、`no_hard_stop_verdict_samples=true`
3) **演练重跑**：重跑前仍需 avail ≥ 18,000 且 commit ≥ 21,500、无并行负载。
   期望（F1/F2 修好的实证）：`stop_line_event_count=5`、`peak_ws_lt_hard_stop=false`、
   `hard_stop_verdict_sample_count=4`、`no_hard_stop_verdict_samples=false`，
   其余 U1/U2/U3 证据与本次一致（steps 六步 / rc=0 / verified=true / signals 恰 1）
4) **不启动 LT2 生产批次**（另一道门）
```

---

## 11.（append-only）F3 同批修复 —— **取代 §8 的哈希**

父 agent 裁定：**F3 与 F1/F2 是同一关注点（取消/覆盖阈值路径下的"记录名与实际语义不一致"），同批修**；
理由含"我们正要重跑演练，而演练正是取消路径——明知某字段错还让它进新证据比扩大几行 diff 更糟"。

### 11.1 改动（单源、无别名、不引入第二真相源）

```text
旧：engine_verdicts: list[dict] = (timeline_parsed or []) if cancel_rec is None else []
    "blocks_next_combination": any(v.get("verdict") == "warning" for v in engine_verdicts)
    ⇒ **第二条按 cancel_rec 门控的取值路径**；取消场景恒 False（"取消的 child 一律声称无软线告警"）
新：删掉 engine_verdicts 与门控；warning 计数与 hard-stop 计数**同源于同一份 timeline_parsed**：
    warning_verdict_samples = None if timeline_parsed is None else
                              sum(1 for v in timeline_parsed if v.get("verdict") == "warning")
    "blocks_next_combination": (True if warning_verdict_samples is None
                                else warning_verdict_samples > 0)      ← 键名不变（无别名）
    "warning_verdict_sample_count": warning_verdict_samples            ← 与 F2 的 count 同规
读失败处置与 F2 **同规**：None ⇒ 判**阻塞下一组合**（fail-closed：无法证明"没有软线告警"就不投递下一组合）
```
> `blocks_next_combination` 仍是 checkpoint **顶层**键（消费者 `run_supervisor` 第 2420 行不变）；
> `rt_gate.GateEngine.blocks_next_combination()` 是另一件事（引擎级，未触碰）。

### 11.2 最小执行：**10/10 通过**（F1a–F1d + F2a–F2c + F3a–F3c）

| F3 检查 | 新码观测 |
|---|---|
| F3a 取消场景也如实统计 warning | `blocks_next_combination=true`、`count=2` |
| F3b 无 warning 时不阻塞 | `false`、`count=0` |
| F3c 读失败 fail-closed | **`true`**、`count=None` |

### 11.3 灵敏度：**三方对照**（比两方更强）

| 被测版本 | 结果 | 失败项 |
|---|---|---|
| **当前代码**（F1+F2+F3） | **10/10 通过** | — |
| **f1f2 中间态**（F1/F2 已修、**F3 未修**） | **恰好 3 项失败** | F3a、F3b、F3c —— **F1/F2 七项全部仍通过** ⇒ **精确隔离出 F3 的断言力** |
| **2040 旧码** | 9/10 失败 | F1a/F1c/F1d + F2a/F2b/F2c + F3a/F3b/F3c（F1b 仍不具鉴别力，已登记） |

中间态上 F3 的观测：三项都是 `blocks_next_combination=false`、`count=null`
（即"取消 ⇒ 恒 False"与"没有计数字段"），与 F3 的缺陷描述逐条吻合。

### 11.4 机械差异：双基线（累计 + 仅 F3 增量）

| 基线 | hunks | 行数 | `touched_defs` | 越界 |
|---|---|---|---|---|
| **2040**（F1+F2+F3 累计，即上一个冻结） | 6 | +45 / −21 | `[combo_pass_conditions, finalize_after_solve, run_combo_worker, run_supervisor]` | **[]** |
| **f1f2 中间态**（仅 F3 增量） | 3 | +14 / −6 | **`[finalize_after_solve]`** | **[]** |

（F3 只动了 `finalize_after_solve` 一处，其余三个函数的改动全部来自 F1/F2 —— 这正是双基线要证明的。）

### 11.5 回归与冻结化最小执行

```text
82 断言套件（ns-f3-20260914-2300）：**82/82**，failures=[]
临时冻结 all_ok=true / window_drift=[]；frozen smoke A/B/B2 三布尔 true + 确定性对照相等；
guard 两场景（持续抑制 / 有界升级）ok；enforced_by 9 标签表 ok；
临时冻结 --verify 与 --verify-snapshot 均 **MATCH**（drift 0）
```

### 11.6 **新哈希（取代 §8；§8 的 F1/F2 哈希作废）**

```text
work/tools/lt2_production.py
  155,778 B   5e7e84e304b8b76712a79ca68544e488fb2c28afe7820af423e63a6bad4c7a45
work/tools/min_exec_r8b_evidence.py（新增 F3a–F3c 检查）
   48,132 B   a3af5869dda46fe0586304fa5353c5ab051fa1e1113787466cb5a7e2478e70c9
临时冻结（非验收，保留勿用）：
  freeze-20260914-min-exec-f3-provisional-not-for-acceptance
  manifest 51ebcd142a5c71d4b7c6904deca8aa764025794c8d123e94d1b00727e5cb5c38
全部证据：work/runs/_evidence-f3/f3_final_summary.json  ed57e430ac9d17c0a891e7c93f12480240303e81ed028426d596ee499c8bb70c
```
> §8 里 `0b6ee62a…`（F1/F2 中间态）**从未被冻结**（父 agent 当时说"先不建冻结"）⇒ 直接作废，无需废弃任何冻结。

### 11.7 历史产物声明（不变，含 F3 的旧行为）

```text
2040 及更早的 run：child checkpoint 携带**旧键名**（peak_ws_lt_12288 / min_avail_ge_4096 /
min_commit_gt_4096），且 `blocks_next_combination` 在取消场景为**旧语义的恒 False**。
它们都是**只读证据**：既不得按新语义重解读，也不得用新键名去检索（会误判为缺失）。
其数值在当时有效；F3 那段旧行为**不构成对 U1–U3 结论的影响**（演练结论不读该字段）。
```

### 11.8 下一步（与 §10 相同，仅哈希更新）

```text
1) 按 §11.6 建新 freeze（lt2_production.py = 5e7e84e3…；建议 min_exec_r8b_evidence.py 继续入 AUX）
2) r3e（生产路径资源确认）→ 期望 23 条全复现 + child checkpoint 自洽（新键名、provenance、
   hard_stop_verdict_sample_count=0、no_hard_stop_verdict_samples=true、
   **warning_verdict_sample_count=0 且 blocks_next_combination=false**）
3) 演练重跑（前置 avail ≥ 18,000 / commit ≥ 21,500、无并行负载）→ 期望
   stop_line_event_count=5、peak_ws_lt_hard_stop=false、hard_stop_verdict_sample_count=4、
   no_hard_stop_verdict_samples=false，其余 U1/U2/U3 证据一致
4) 停下报告；**不启动 LT2 生产批次**
```

