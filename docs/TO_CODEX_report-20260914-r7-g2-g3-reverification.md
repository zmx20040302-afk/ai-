# TO CODEX — G2 / G3 重验报告（同一 freeze-1810 既有证据，未新跑批次）

- 报告性质：**append-only**；不改写任何既有文件（含 §1 的 freeeze-1810 验收报告）
- 验收对象：`freeze-20260914-1810-post-atomic-retry`（`manifest_sha256 = 7ca99929906eb6d8015d8f961a85e56127e5348ff135a569c98b4c56dbe30d5d`）
- 证据来源限制：**只用**该 freeze 那一次的既有产物；**未重新跑批次**（遵守 Codex「G1 过后用同一批证据重验 G2/G3」）
- 落地方式：**独立成文**（未并入前一份报告），因为 G2/G3 是**另一组判据**，独立成文便于审阅方逐条复核

---

## 0. 证据基线（本报告全部判定所依据的产物文件）

| 产物 | bytes | SHA256 | 用途 |
|---|---|---|---|
| `work\runs\lt2-acceptance-20260914-1810-credit\acceptance_summary.json` | 121,883 | `b9a633e89894d8313cbfd41daf1e6877c2c5191f49b76611a935fc975d5dc8c2` | 顶层判定、确定性 manifest（含每文件 path/bytes/sha256）、证据文件登记 |
| `work\runs\acc-180754-run1\test_summary.json` | — | `b64514d0d473eed227d67e02819e4371b93b4b11e574c7d3d2ce7c5ff07c1271` | 第 1 轮 82 项断言原文 |
| `work\runs\acc-180754-run2\test_summary.json` | — | `56856b95b8bcaad4c05a8c37133416d54ae0bae5e27677e774e6a6c3704ab0bf` | 第 2 轮 82 项断言原文 |
| `work\runs\acc-180754-run1\lt2-supervisor-selftest\batch_manifest.json` | 18,344 | `d9b5841cd4123f5d49a40deb815f3477637b34f9be4bf7965a272351c235e4ec` | G2 主证据 |
| `work\runs\acc-180754-run2\lt2-supervisor-selftest\batch_manifest.json` | 18,344 | `d9b5841cd4123f5d49a40deb815f3477637b34f9be4bf7965a272351c235e4ec` | G2 主证据（**与 run1 逐字节相同**） |

---

## 1. G2（batch manifest）逐条判定

| # | 判据 | 取值 | 判定 | 依据产物 |
|---|---|---|---|---|
| G2-1 | manifest **真实生成** | `role=manifest-assembly`、`child_count=9`、`assembled_read_only=true`、`comsol_started=false`、`mph_imported=false`；两轮各 18,344 B | **PASS** | 两个 `batch_manifest.json`（各自 bytes/SHA256 见 §0） |
| G2-2 | **inventory 全部满足** | `children_satisfy_inventory = true`；套件侧对应断言 `T8 全部 child 满足其 kind 的清单规约（G3） — missing_required 的目录=无`（两轮均 PASS） | **PASS** | 两个 `batch_manifest.json` + 两个 `test_summary.json` |
| G2-3 | **控制通道脱敏可识别** | 每个 child 的 `worker_state.json` 项含：**文件名**（`files` 字典键）、`bytes=None`、`sha256=None`、`pid_redacted_for_determinism=true`、`redaction_reason="控制通道：含真实 PID/启动时间，bytes 与 sha256 均不参与确定性比对；文件名与原因仍保留以便审计"`；两轮各 **9 个**脱敏项（9 个 child × 1） | **PASS** | 两个 `batch_manifest.json`；套件断言 `T8 manifest 含每个 child 的文件级 sha256（脱敏项除外，且无无声缺失） — children=9, 脱敏文件=9, 缺 sha256 的目录=无` |
| G2-4 | **`child_dir` 已相对化** | 每个 child 的 `child_dir` = 其 `dir_name`（如 `child_00_attempt_1`），且 `child_dir_absolute_redacted=true`；**不再内嵌含 namespace 的绝对路径** | **PASS** | 两个 `batch_manifest.json` |
| G2-5 | **manifest 自身 bytes+SHA256 可给出** | 两轮均为 **18,344 B / `d9b5841cd4123f5d49a40deb815f3477637b34f9be4bf7965a272351c235e4ec`** ⇒ **两份逐字节相同**（这正是条件 5 `different_files=[]` 的直接体现） | **PASS** | §0 表 |

**G2 结论：PASS（5/5）**。强调一点方法论：`batch_manifest.json` **没有**被放进 allowlist ——
它是靠**修复**获得确定性的（控制通道 `bytes`+`sha256` 双脱敏、`child_dir` 相对化）。
allowlist 只用于「设计如此」的非确定性（真实 PID/墙钟/控制通道/探针目录），不得用来盖住应当修的缺陷。

---

## 2. G3（child 清单与隔离）逐条判定

| # | 判据 | 取值 | 判定 | 依据产物 |
|---|---|---|---|---|
| G3-1 | **每个 child/attempt 的文件清单与哈希** | `acceptance_summary.json` 内 `deterministic_manifest_run1/run2` 逐文件给出**规范化相对路径 + bytes + 完整 SHA256**（两侧各 **50** 项）；根级覆盖：`lt2-supervisor-selftest 26 / -smoke 5 / -postsolve 5 / -retry 6 / -atomic 1 / -drill 7`（`expected_inventory_bad_roots=[]`） | **PASS** | `acceptance_summary.json`（121,883 B / `b9a633e8…`） |
| G3-2 | **前序 child 未被改写（before == after）** | 两轮断言均为 PASS：`T9c 前序 child 未被后续 child 改写（before == after） — child_00_attempt_1:一致; child_01_attempt_1:一致; child_02_attempt_1:一致; child_03_attempt_1:一致`；另有 `T9d 前序 child 的 state 文件同样未被改写 — worker_state/sampler_state 哈希稳定` | **PASS** | 两个 `test_summary.json`（`b64514d0…` / `56856b95…`） |
| G3-3 | **attempt_1 / attempt_2 共存** | `T10c attempt_2 使用新目录并成功产出 checkpoint — status=pass, child_dir=child_00_attempt_2`；`T10d attempt_1 证据在 attempt_2 之后仍保留（未被覆盖） — attempt_1 目录仍在=True` | **PASS** | 两个 `test_summary.json` |
| G3-4 | **无 attempt_3** | `T10e 不存在 attempt_3 目录（禁止第三次自动重跑） — attempt_3 目录=无`；`T10f 源码中没有 attempt=3 调用路径 — False` | **PASS** | 两个 `test_summary.json` |
| G3-5 | **child 目录全覆盖（不藏形态不齐的目录）** | `T8 manifest 覆盖磁盘上全部 child 目录 — manifest=9 个, 磁盘=9 个`（两轮一致） | **PASS** | 两个 `test_summary.json` + 两个 `batch_manifest.json` |

**G3 结论：PASS（5/5）**。

---

## 3. 无法用既有证据判定的条目（如实登记，未用新跑补）

**无。** 本次 G2/G3 的 10 条判据**全部**可由 §0 所列既有产物直接判定，取值均已写出，且每条标注了
依据产物与该产物的 bytes/SHA256。**没有出现「现有证据不足以判定」的条目**，因此**不需要**新跑批次。

需注意的一处**口径边界**（非判定缺口）：G3-2 的 `before == after` 是**套件内断言**的结果（存于 `test_summary.json`），
而非由我重新计算时间线哈希 —— 我依据的是**该断言的两轮原文与 summary 哈希**，未对时间线做二次独立复算。
若审阅方要求「由第三方对同一批时间线独立复算 before/after」，那需要读取两个 namespace 内各 child 的
`resource_timeline.jsonl`（哈希已在 `acceptance_summary.json` 的确定性 manifest 中给出），
**可在不重跑任何求解的前提下完成**——请指示是否需要补这一步。

---

## 4. 声明与状态

```text
G1 = CLOSED_FOR_FREEZE_1810（父 agent 独立复核，本报告不改变它）
G2 = PASS_FOR_FREEZE_1810（本报告 §1，5/5，依据同一批既有证据）
G3 = PASS_FOR_FREEZE_1810（本报告 §2，5/5，依据同一批既有证据）
未新跑批次 ；comsol_started = false ；mph_imported = false
未运行 COMSOL / comsolbatch / mphserver ；未碰页面文件
未复用或清理任何既有 run 目录 ；rt_gate.py 保持「不改」
```

**后续（不跳步、不自行开跑）**：

```text
第 2 步 正常资源确认 r3（真实 COMSOL ≈十余分钟）= 等父 agent 取得用户放行后再开，我不自行启动
第 3 步 真实硬停演练 = 另行放行（Codex 本轮 DO_NOT_RUN；用户已给知情同意，时点待定）
第 4 步 LT2 生产 504 点 = 不得启动（U1–U3 未验；16 小时无人值守必须等硬停演练之后）
```

---

## 附录 A（后补，append-only）—— G3-2 的**第三方独立复算**

本节为**附录**（父 agent 放行后补做）；§0–§4 已发布内容**未作任何改写**。

**为什么补**：G3-2 断言「前序 child 未被改写」，原依据是**套件自身**的两轮输出。
「被测套件自己声明没改过」强度不足，需由独立方对**磁盘上的实际文件**复算。**只读，未重跑任何求解。**

**执行**：`work\tools\g3_2_independent_recheck.py`（新增；只读扫描 + 双哈希），
产物 `work\runs\lt2-acceptance-20260914-1810-credit\g3_2_independent_recheck.json`
= **4,980 B / `89db610da4d14a4256962d89b8a82679ecd833408a1d34bb84bd5ccc18e9cc7c`**

**读取时刻**：`read_at = 2026-09-14T18:32:38`，`read_again_at = 18:32:39`（读前/读后各一次全量 sweep）。

| 比对 | 结果 |
|---|---|
| run1 manifest vs run1 **当前**磁盘 | 50 项，`diff = []`，`all_equal = true` |
| run2 manifest vs run2 **当前**磁盘 | 50 项，`diff = []`，`all_equal = true` |
| run1 manifest vs run2 manifest（**跨轮**） | `diff = []` ⇒ **run2 的创建/写入没有改动 run1 的内容**（即 before == after） |
| 两次 sweep 是否一致 | `second_sweep_stable = true` ⇒ 本次复算**读取期间无第三方写入** |
| `resource_timeline.jsonl` 条数 | run1 14 条 / run2 14 条（哈希数组已写入产物） |

**判定**：

```text
G3-2 = INDEPENDENTLY_RECONFIRMED
```

**一处必须写清的口径（避免误读为异常）**：产物中 `resource_timeline_run1_vs_run2_equal = false`，
那是**原始 14 条 timeline 的全量**比较结果，其中**包含按设计本就不同的根**
（`-wallclock/` 是 T9 的墙钟反例、`-liveproc/` 含真实 PID），这些已在 allowlist 中逐条声明。
**在确定性集合内**逐项比较为 `diff = []`（上表第 1–3 行），故「前序 child 未被改写」成立。
如需把这 14 条的差异逐条归属到具体根（只读、不需重跑），可再补一节。

**依据产物哈希**：`acceptance_summary.json` = 121,883 B / `b9a633e89894d8313cbfd41daf1e6877c2c5191f49b76611a935fc975d5dc8c2`；
run1 `test_summary.json` = `b64514d0d473eed227d67e02819e4371b93b4b11e574c7d3d2ce7c5ff07c1271`；
run2 `test_summary.json` = `56856b95b8bcaad4c05a8c37133416d54ae0bae5e27677e774e6a6c3704ab0bf`；
两个 `batch_manifest.json` 均 = `d9b5841cd4123f5d49a40deb815f3477637b34f9be4bf7965a272351c235e4ec`。
本附录**未启动 COMSOL**（现场核验 2036 = 0、`comsolmphserver` = 0），未改任何既冻结文件。

**附录 A 修订（append-only；字段重命名，判定不变）**：原产物中的 `resource_timeline_run1_vs_run2_equal`
（一个 `false` 布尔）**易被误读为「G3-2 未通过」**，已改为自解释字段，**判定逻辑与结论均未改动**：

```text
full_set_including_by_design_differences_equal : false   （全量集合含按设计本就不同的根）
deterministic_set_equal                        : true    （G3-2 的判据就是这个集合）
by_design_differing_roots                      : 9 个根 → 各自 allowlist 规则（null 规则数 = 0）
g3_2_verdict                                   : INDEPENDENTLY_RECONFIRMED
field_note                                     : 已写入产物，显式说明 false ≠ 判定失败
```
重生成产物：`work\runs\lt2-acceptance-20260914-1810-credit\g3_2_independent_recheck.json`
= **5,988 B / `bb6ef96daaca9784dde55ef72498d8f1ff99b1541eb71a2ec6e52bcdd227b0dd`**
（旧产物 4,980 B / `89db610d…` 被本次重跑覆盖，按 append-only 精神在此登记旧值以便追溯）；
**已做 UTF-8 回读校验：解析 OK**。


（父 agent 的两个字面探针按「未由第三方」「before==after」匹配返回 False 属**措辞差异**：
原边界写在 **§3「无法用既有证据判定的条目」小节末段**——原文为「G3-2 的 before == after 是套件内断言的结果…
未对时间线做二次独立复算」；本附录即该边界的补做结果。）

