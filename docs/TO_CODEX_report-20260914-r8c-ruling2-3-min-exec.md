# TO_CODEX / 父 agent：裁定 2（三布尔拆分）+ 裁定 3（重建件显式声明）——最小执行取证（r8c）

- 日期：2026-09-14
- 上一轮（r8b）报告：`docs/TO_CODEX_report-20260914-r8b-freqs-freeze-evidence-min-exec.md`
  （②③ 的完整实现与取证仍以那份为准；本文只覆盖**本轮改动**）
- 本轮改动**仅两处**：裁定 2 的布尔拆分、裁定 3 的重建件显式声明（+ 裁定 1 要求的 reason 串措辞）。
- 未做（不变）：未跑硬停演练（U1–U3）、未启动 LT2 生产批次、未动 `rt_gate.py`、未动阈值/判定逻辑、
  未清理或复用任何既有 run 目录。③ 的 `parse_freqs` 本轮**一行未动**。

---

## 1. 裁定落实情况

| 裁定 | 要求 | 落实 |
|---|---|---|
| **1** `--freeze-id` 保持可选 | 强制放在**判定**层；reason 串要让人一眼看懂「缺的是冻结证据 + 补它的命令」 | **CLI 行为未改**；`reason` 已改写为「未提供 --freeze-id ⇒ 本次运行**没有冻结证据**…补齐方式：启动时加 `--freeze-id <freeze_id>`（例如 `--freeze-id freeze-20260914-1940-post-freqs-freeze-evidence`）；该 id 须已由 `freeze_snapshot.py --create` 建立且 `--verify` 为 MATCH…」（全文见 §3） |
| **2** 拆成三个单义布尔 | `freeze_hash_pre_post_match` / `executed_from_frozen_snapshot` / `freeze_evidence_complete` + `definition` | 已拆；**判定逻辑与阈值不变**，只是把多义布尔拆开（§2） |
| **3** 重建件不造假字段但显式说明 | `freeze_evidence_complete=false` + `freeze_evidence_absent_reason="assembled_read_only_rebuild_not_a_run"` | 已加；**未改重建函数的任何计算逻辑**（§4） |

---

## 2. 裁定 2：三个单义布尔

```json
"freeze_hash_pre_post_match": true,        // 只回答「冻结哈希前后是否对得上」
                                           //   = (pre ok) AND (post ok) AND (两次逐文件哈希集合完全一致)
"executed_from_frozen_snapshot": true,     // 只回答「是否从冻结副本执行」
                                           //   = 运行中的 lt2_production.py 逐字节 == 冻结件
"freeze_evidence_complete": true,          // 只回答「本次运行的冻结证据是否完整可用」
                                           //   = 前两者皆 true
"definition": "三个布尔各自只有一个含义：freeze_hash_pre_post_match = (运行前核验 ok) AND (运行后核验 ok) AND (两次逐文件哈希集合完全一致) —— 只回答「冻结哈希前后是否对得上」；executed_from_frozen_snapshot = (运行中的脚本逐字节 == 冻结件) —— 只回答「是否从冻结副本执行」；freeze_evidence_complete = 前两者皆 true —— 只回答「本次运行的冻结证据是否完整可用」。"
```

实现要点（防止两处各算一遍而分叉）：三个布尔只在 `freeze_evidence()` 里算**一次**，
`run_supervisor` 把同一份结果写到顶层（检查器读的那一层）与 `freeze_evidence` 内，二者同源。

保留未动：`pre`/`post` 两次核验的 `at` / `clock_mode` / `verdict` / `drift_count` / 逐文件
`frozen_sha256` vs `current_sha256` / `files_digest`，以及 `running_script_is_frozen_target` 细节块。
`pre_post_files_identical` 保留为**分量细节**（不是放行判据），并在注释中写明这一点。

---

## 3. 裁定 1：无 freeze-id 时的 reason 串（实测原文）

```text
文件：work/runs/_evidence-r8c/nofreeze_path_evidence.json（1,334 B，5b07553893bea57f…）
{
  "freeze_id": null,
  "freeze_hash_pre_post_match": false,
  "executed_from_frozen_snapshot": false,
  "freeze_evidence_complete": false,
  "requested": false,
  "reason": "未提供 --freeze-id ⇒ 本次运行**没有冻结证据**：运行自身无法证明冻结未漂移，也无法证明跑的是冻结件。补齐方式：启动时加 `--freeze-id <freeze_id>`（例如 `--freeze-id freeze-20260914-1940-post-freqs-freeze-evidence`）；该 id 须已由 `python work/tools/freeze_snapshot.py --create` 建立，且 `python work/tools/freeze_snapshot.py --verify <freeze_id>` 为 MATCH。在补齐之前，以下三个布尔一律 false（fail-closed），检查器必须判失败。"
}
```

对应 run：`lt2-min-exec-r8c-nofreeze`，exit 6（fake 场景），manifest 12,244 B
`aa14f7841fe74e01e81047ff1593c4ee156cea35eb4db81af573661d54326455`。

---

## 4. 裁定 3：只读重建件显式声明「没跑过」

`assemble_manifest_from_child_dirs()` 新增（**不动任何计算逻辑**）：

```json
"freeze_evidence_complete": false,
"freeze_evidence_absent_reason": "assembled_read_only_rebuild_not_a_run",
"freeze_evidence_note": "本 manifest 由 `--assemble-manifest-only` **只读重建**：未执行任何冻结核验，故 freeze_evidence_complete=false。两个分量 `freeze_hash_pre_post_match` 与 `executed_from_frozen_snapshot` **故意不写**（不写 ≠ 判假：它们是「没跑过」，不是「跑过但哈希不符/不是冻结件」）。要得到这三个布尔，必须真跑一次 supervisor 并显式带 `--freeze-id`。"
```

**对照实测**（同一次 r8c 轮次内的两个真实产物）：

| 键 | supervisor **真跑件**（`lt2-min-exec-r8c-comma-b`） | **只读重建件**（套件 T8 产出，9 个 child） |
|---|---|---|
| `freeze_id` | `freeze-20260914-min-exec-r8c-provisional-not-for-acceptance` | **不写**（重建不是一次运行） |
| `freeze_hash_pre_post_match` | `true` | **不写** |
| `executed_from_frozen_snapshot` | `true` | **不写** |
| `freeze_evidence_complete` | `true` | **`false`** |
| `freeze_evidence_absent_reason` | — | **`"assembled_read_only_rebuild_not_a_run"`** |
| `assembled_read_only` / `comsol_started` | — / — | `true` / `false` |
| `child_count` | 1 | 9 |

⇒「**没跑过**」（重建件：显式 reason、分量不写）与「**跑过但证据缺失**」（真跑件：分量写出、缺哪项就哪项 false）
在产物层**已可区分**。对照文件：`_evidence-r8c/compare_supervisor_vs_rebuilt.json`、
`_evidence-r8c/rebuild_declaration_evidence.json`。

---

## 5. 机械差异基线（对**上一个冻结快照** 1940）

```text
快照 = work/runs/lt2-supervisor-acceptance-freeze-20260914-1940-post-freqs-freeze-evidence/snapshot/lt2_production.py
       63a36ca5411df41f6b881212e210cc29034d031ad3bb07b06e10a13b33c53bf5  (138,923 B)
当前 = 8f49ab4e6f85749d7a9b46e511ebf5b471c58917c62e7f4b7dcd907746e80c91  (141,673 B)
差异 = 6 hunks / +47 行 / −12 行；patch 6,975 B
       6d8eabbd379cc0458dd88920a902796902ccf05a62634d27ad60808af530df9f
touched_defs = [<module>, freeze_evidence, assemble_manifest_from_child_dirs, run_supervisor]
touched_defs_outside_declared_scope = []          ← 无越界改动
删除行（12 条）全部落在 freeze_evidence / run_supervisor 的 ② 字段区，逐条已列在 JSON 里
```

断言：与裁定 2/3 无关的 `parse_freqs`、`freeze_verify`、`supervise_child`、`main`、`finalize_after_solve`
**本轮 0 改动**（未出现在 touched_defs 中）。

---

## 6. 最小执行：命令 / exit code / 条件表

前置：本轮**临时冻结**（非验收）`freeze-20260914-min-exec-r8c-provisional-not-for-acceptance`
manifest `815a96b0615ad2d84d21c82db795adc2caf1d6398d65697a708874d15c60afb0`
`three_way.all_ok=true`、`window_drift=[]`、13 个只读快照文件（含 `min_exec_r8b_evidence.py`）。

| 用例 | 命令要点 | exit | 判据 | 结果 |
|---|---|---|---|---|
| A2（空格字面量 + r8c freeze） | `min_exec_r8b_evidence.py smoke --run-id lt2-min-exec-r8c-space-a --freqs-raw "5 10 15 20 25 30 35" --freeze-id <r8c>` | 6 | `hash_pre_post=true`、`executed_from_frozen_snapshot=true`、`freeze_evidence_complete=true`、freqs count=7 | **PASS** |
| B3（逗号 + r8c freeze） | 同上 `--run-id lt2-min-exec-r8c-comma-b --freqs-raw "5,10,...,35"` | 6 | 同上三项皆 true | **PASS** |
| B4（与 B3 同输入，仅 run-id 不同） | `--run-id lt2-min-exec-r8c-comma-b2` | 6 | 同上 | **PASS** |
| N2（旧 freeze 1940） | `--freeze-id freeze-20260914-1940-post-freqs-freeze-evidence` | **11** | 运行前判 `INVALIDATED_BY_CODE_DRIFT`、`drift_count=2`（本轮改动的两个文件）、**拒绝启动、未建 run 目录** | **PASS** |
| 无 freeze-id | 不给 `--freeze-id` | 6 | 三布尔皆 false + §3 的 reason | **PASS** |
| 确定性（B3 vs B4） | `compare --manifest-a …comma-b --manifest-b …comma-b2` | 0 | `new_fields_all_equal=true`（6 个字段：`freqs_parse`/`freeze_evidence`/`freeze_id`/三个布尔，两侧 sha256 全等） | **PASS** |
| 裁定 3 对照 | `compare --manifest-a <supervisor件> --manifest-b <重建件>` | 1 | 差异**只**来自「重建件按设计不写这些字段」（§4 表） | **PASS** |
| 82 断言回归 | `tests_lt2_supervisor.py --namespace ns-r8c-regress-20260914-2010` | 0 | **82/82**，`failures=[]`；其中 T8 正是重建路径（4 条断言全过） | **PASS** |
| 检查器复读 | `check_r3_conditions.py --run-id lt2-min-exec-r8c-comma-b` | 1 | 15/21；`freeze_hashes_pre_post_match: pass=true`；6 项失败仍是 fake 场景固有缺失（`rows_eq_7`/`unique_freqs_eq_7`/`solve_error_is_null`/`lt2c_quick_gate_pass`/`pid_source_is_port_owner`/`identity_complete`） | **接口对齐** |

必须如实登记的两点（与上一轮相同）：

- exit 6 = `BLOCKED_OR_LIMITED` 是 **fake-combo-worker 的既有语义**（其 `pass_conditions` 只有 2 项），
  上一轮已用 1810 快照旧代码做 `behaviour_equal=true` 的机械对照；本轮未改判定逻辑（§5 未触及判定函数）。
- `--fixed-timestamps` 下 `pre.at == post.at` 是设计使然（产物可复算）；真机 r3 不带该开关，
  两次 `at` 是真实墙钟，构成批次窗口上下界。

---

## 7. 新哈希（请据此建新 freeze）

```text
被测件 work/tools/lt2_production.py
  bytes  = 141,673
  sha256 = 8f49ab4e6f85749d7a9b46e511ebf5b471c58917c62e7f4b7dcd907746e80c91
AUX 取证工具 work/tools/min_exec_r8b_evidence.py（本轮同步更新：报告三布尔/加 absent_reason 对照）
  bytes  = 20,192
  sha256 = 58296b5c2bf65620164d268a6d78337003e755205907f518800b2e90c9267c36
其余 11 个冻结件：与 1940 manifest 逐项相同（未改）
临时冻结（**非验收**，仅供本轮最小执行）：
  freeze-20260914-min-exec-r8c-provisional-not-for-acceptance   manifest 815a96b0…
1940 冻结现状：--verify = INVALIDATED_BY_CODE_DRIFT, drift_count=2
  （lt2_production.py + min_exec_r8b_evidence.py，均为本轮有意改动）⇒ 需按本哈希新建 freeze
全部证据文件哈希清单：work/runs/_evidence-r8c/evidence_hashes.json
  3,379 B  774e28d1cc27e76dbea2af9a4377414712f0907fff45565aa66de77eaa340871
```

---

## 8. 本轮的 layout 原文

```text
[C:\Users\zmx\Desktop\memsharness\work\runs\_evidence-r8c]
checker_on_r8c_B3.json
compare_B3_vs_B4.json
compare_supervisor_vs_rebuilt.json
diff-vs-freeze-1940.patch
diff_vs_freeze_1940.json
evidence_hashes.json
nofreeze_path_evidence.json
rebuild_declaration_evidence.json
smoke_A2_space_frozen.json
smoke_B3_comma_frozen.json
smoke_B4_comma_frozen.json
smoke_N2_old1940_refused.json
smoke_nofreeze_r8c.json

[runs/lt2-min-exec-r8c-comma-b]        batch_manifest.json + child_00_attempt_1（7 件套）
[runs/lt2-min-exec-r8c-space-a]        batch_manifest.json + child_00_attempt_1
[runs/lt2-min-exec-r8c-comma-b2]       batch_manifest.json + child_00_attempt_1
[runs/lt2-min-exec-r8c-nofreeze]       batch_manifest.json + child_00_attempt_1
[runs/ns-r8c-regress-20260914-2010]    82 断言套件命名空间（含 lt2-supervisor-selftest/batch_manifest.json = 重建件）
  test_summary.json                    14,497 B  b1a6dc3e54b7b0fe…（total 82 / pass 82 / fail 0）
  lt2-supervisor-selftest/batch_manifest.json  18,905 B  2aa7ce6618728529…（裁定 3 的重建件）
[runs/lt2-supervisor-acceptance-freeze-20260914-min-exec-r8c-provisional-not-for-acceptance]
  非验收临时冻结（保留，勿用于放行）
反向用例目录 lt2-min-exec-r8c-negative-old1940 不存在
```

---

## 9. 建议的下一步（不变）

```text
1) 父 agent 按 §7 的 lt2_production.py = 8f49ab4e… 与 min_exec_r8b_evidence.py = 58296b5c… 建新 freeze。
2) 从**新快照**重跑 r3（新 run-id，显式带 --freeze-id <新 freeze>）；届时检查器的
   freeze_hashes_pre_post_match 应为 true（本轮已用 fake 路径证明该条能判真）。
   注：r3 是真机 run，`executed_from_frozen_snapshot` 亦应为 true（脚本须从冻结快照执行）。
3) 硬停演练（U1–U3）与 LT2 生产批次仍等父 agent 单独放行。
```
