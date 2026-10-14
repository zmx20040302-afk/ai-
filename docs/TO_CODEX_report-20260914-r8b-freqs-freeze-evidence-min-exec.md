# TO_CODEX / 父 agent：②③ 修复 + 最小执行取证（r8b）

- 日期：2026-09-14
- 范围：**只碰两处**（② `batch_manifest.json` 缺冻结证据字段；③ `--freqs` 解析加固），
  **不动判定逻辑与阈值**。
- 流程遵守：父 agent 规则「修复不得只靠静态检查宣布」⇒ 本文件只登记**真跑过**的结果。
- 未做（明确声明）：未跑硬停演练（U1–U3）、未启动 LT2 生产批次、未动 `rt_gate.py`、
  未动任何阈值、未清理/复用任何既有 run 目录。

---

## 0. 一句话结论

**②③ 已实现并已真跑验证**：`--freqs '5 10 15 20 25 30 35'`（父 agent 实际发过的字面量）
现在解析为 **7 个频率**且写入产物；`batch_manifest.json` 现在写入
`freeze_id` + 运行前后**各一次**只读冻结核验（含时间戳、逐文件哈希、drift）
+ `freeze_hash_pre_post_match`；父 agent 的检查器对该字段**已能判真**（实测 `pass: true`）。
全套 82 断言在本轮源码上 **82/82 通过**，且与「上一个冻结快照的旧代码」逐字段对照
**批次判定字段完全一致** ⇒ 判定未变。

**需要父 agent 做**：建新 freeze（`lt2_production.py` 新哈希见 §5），然后从新快照重跑 r3（新 run-id）。

---

## 1. 对父 agent 两处认定的处置

| 父 agent 认定 | 我的处置 | 证据 |
|---|---|---|
| ① `lt2c_quick_gate` 是**消费者**错，不得为消费者方便污染产物 | **未改生产件**（一个字节都没动这块） | §4 机械差异只触及 12 个冻结件中的 `lt2_production.py`；`lt2c_quick_gate` 的写入形状未变 |
| ② `freeze_hash_pre_post_match` 是**真缺字段**，要改生产件 | **改生产件**（`run_supervisor` 写批次根 manifest） | §4、§6.2 |
| ③ `--freqs` 解析要加固（生产件，与②同批） | **改生产件**（`parse_freqs` + CLI + worker 下传） | §4、§6.1 |

---

## 2. ③ `--freqs` 解析加固（实现口径）

```text
a) 分隔符：先做「全角逗号 → 半角」，再按正则 [,\s]+ 切分
   ⇒ 逗号（半角/全角）与空白（空格/制表/换行）**等价**
   （父 agent 那条字面量 `5 10 15 20 25 30 35` 旧实现按逗号切分只得 1 个频率：
     实测 old=1 / new=7，见 §6.1）
b) 解析结果写入产物：parsed_freq_list_MHz（浮点表）+ parsed_freq_list_MHz_count
   + canonical_plist（真正交给 COMSOL 的 plist 字符串）+ tokens/raw/expected_count_source
   落点两处：批次根 batch_manifest.json.freqs_parse 与 **child** checkpoint.json.freqs_parse
c) fail-closed：结果为空 / 含重复 / 含非法 token（非有限正浮点数）/ 数量与期望不符
   ⇒ 打印 STOP + 完整 parse_record，**拒绝启动**，退出码 **10**（FREQ_PARSE_REFUSAL_EXIT）
```

### 「期望数量」的来源（父 agent 要求写明）

```text
默认 = 本模块声明的**生产授权口径** EXPECTED_FREQ_COUNT = len(DEFAULT_FREQS) = 7
       （Codex 裁定：5/10/15/20/25/30/35 MHz，每组合 7 点）
覆盖 = CLI 显式 --expect-freq-count N（非生产点数必须显式给；覆盖本身也写入产物：
       parse_record.expected_count_source = "CLI 显式 --expect-freq-count=N"）
下传 = supervisor 拉起 worker 时**一并下传**期望条数
       （否则 worker 会用默认 7 重判，`--expect-freq-count 3` 会在 worker 侧被误拒）
```

### 我额外加严的 3 点（超出父 agent 明确要求，供审阅可否决）

1. 重复判定按**数值**（`float` 规范化）：`5` 与 `5.0` 视为同一频率重复 ⇒ 拒绝（否则会出现两行同一频率，仍属静默变形）。
2. 非法判定含 `<= 0` 与非有限值（`-15`、`0` 均拒绝）。
3. 全角逗号归一（中文输入法下的常见静默变形）。

---

## 3. ② 冻结证据（实现口径）

`batch_manifest.json` 新增（顶层，检查器直接读的一层）：

```json
"freeze_id": "freeze-<...>",
"freeze_hash_pre_post_match": true,
"freeze_evidence": {
  "requested": true, "freeze_id": "freeze-<...>",
  "verifier": "lt2_production.freeze_verify（只读；口径同 freeze_snapshot.py --verify：source-vs-manifest，三个分组全查）",
  "manifest_path": "...\\freeze_manifest.json",
  "freeze_manifest_sha256": "...",
  "mode": "source-vs-manifest（targets / dependencies / acceptance_aux 三个分组全查）；pre = 批次开始前，post = 批次结束后",
  "pre":  { "at": "...", "clock_mode": "fixed|wallclock", "ok": true, "verdict": "MATCH",
            "drift_count": 0, "frozen_file_count": 12, "files": [ {"group","file","path",
            "exists","frozen_sha256","current_sha256"} ... ], "files_digest": "..." },
  "post": { ... 同上，批次结束后的**第二次**核验 ... },
  "pre_verdict": "MATCH", "post_verdict": "MATCH",
  "pre_drift_count": 0, "post_drift_count": 0,
  "pre_post_files_identical": true,
  "running_script_is_frozen_target": { "file": "lt2_production.py", "self_path": "...",
      "self_sha256": "...", "frozen_target_sha256": "...", "match": true,
      "note": "运行中的 lt2_production.py 是否与冻结值逐字节一致（防从非冻结副本执行）" },
  "definition": "freeze_hash_pre_post_match = (运行前核验 ok) AND (运行后核验 ok) AND (两次逐文件哈希集合完全一致) AND (运行中的脚本 == 冻结件)",
  "freeze_hash_pre_post_match": true
}
```

设计说明（供拍板，见 §8）：

- **只读**：`freeze_verify()` 不写任何文件、不改状态，因此可在运行前后各执行一次；
  不 import `freeze_snapshot.py`（它是冻结窗口的守护者，不应成为被测运行期依赖）。
- 形状自带 `definition`，无需读代码即可理解布尔含义。
- `--fixed-timestamps` 下两次 `at` 都走固定时钟 ⇒ **pre.at == post.at 是设计使然**（保证产物可复算）；
  **真机 r3 不带 `--fixed-timestamps`**，两次 `at` 是真实墙钟，构成批次窗口的上下界。

---

## 4. 机械差异基线（父 agent 规则：与**上一个冻结快照**逐行对照）

```text
快照 = work/runs/lt2-supervisor-acceptance-freeze-20260914-1810-post-atomic-retry/snapshot/lt2_production.py
       sha256 cf599afd540f627989e39743dd6c062dacb13fcc5784c543ce7412097bb7fc83  (122,900 B)
当前 = work/tools/lt2_production.py
       sha256 63a36ca5411df41f6b881212e210cc29034d031ad3bb07b06e10a13b33c53bf5  (138,923 B)
差异 = 9 hunks / +286 行 / -2 行；patch 19,013 B
       sha256 15fb893d940daa19c17c1775703fe575e6705ea0e80791da1cdf0d4f62010f6e
机械判据（不靠关键词猜测）：把每个 hunk 的改动行映射到**新文件里所属的顶层 def**，
要求 ∈ 声明范围。结果：
  touched_defs = [<module>, parse_freqs, freeze_dir, _files_digest, freeze_verify, freeze_evidence,
                  run_combo_worker, run_fake_combo_worker, supervise_child, run_supervisor, main]
  touched_defs_outside_declared_scope = []      ← 无越界改动
删除的 2 行（均在声明范围内）：
  - "--freqs", ",".join(args.freqs), "--interval", str(args.interval),   （supervise_child：改为下传期望条数）
  - args.freqs = tuple(f.strip() for f in str(args.freqs).split(",") if f.strip())  （main：③ 取代）
```

`freeze_snapshot.py --create` 的清单比对（1810 vs 本轮临时冻结，12 个文件）：

```text
files_compared = 12 ; changed = ["lt2_production.py"] ; unchanged = 其余 11 个
only_one_file_changed = true
```

---

## 5. 新哈希（父 agent 建新 freeze 用）

```text
被测件（唯一改动）：work/tools/lt2_production.py
  bytes  = 138,923
  sha256 = 63a36ca5411df41f6b881212e210cc29034d031ad3bb07b06e10a13b33c53bf5
其余 11 个冻结件：与 1810 manifest 逐项相同（未改）
本轮新增的**取证工具**（非被测件，是否纳入 AUX 由父 agent 定）：
  work/tools/min_exec_r8b_evidence.py  19,308 B
  sha256 = 21fcfe1f7e4633ef94fac95103a0fb9d5ad702e9e84ba16cfe2070606617430e
临时冻结（**仅供本轮最小执行使用，非验收冻结，请勿当作放行依据**）：
  freeze_id = freeze-20260914-min-exec-r8b-provisional-not-for-acceptance
  manifest  = 9d5f56e720561dca91d4b92974d77eed4af34eb8f8dbd87cfe6e93a456d2f1d8
  --verify / --verify-snapshot 均 MATCH, drift_count=0, three_way.all_ok=true, window_drift=[]
1810 冻结现状：--verify = INVALIDATED_BY_CODE_DRIFT, drift_count=1（file=lt2_production.py）
  ⇒ 符合预期：被测件已改，1810 不再可用于放行；必须新建 freeze
```

---

## 6. 最小执行：命令 / exit code / 条件表 / layout 原文

### 6.1 ③ 解析：拒绝用例与正常用例

命令：`python -B work/tools/min_exec_r8b_evidence.py refusals --out work/runs/_evidence-r8b/freqs_refusals.json`

| 用例 | `--freqs` 取值 | exit | 期望 | 结果 |
|---|---|---|---|---|
| empty_string | `""` | 10 | 拒绝、不建目录 | PASS |
| missing_value | （无取值） | 2 | argparse 层拒绝（另一层 fail-closed） | PASS |
| whitespace_only | `" "` | 10 | 拒绝 | PASS |
| comma_only | `","` | 10 | 拒绝 | PASS |
| duplicate_exact | `5,10,10,20,25,30,35` | 10 | 拒绝（重复） | PASS |
| duplicate_numeric_alias | `5,5.0,15,20,25,30,35` | 10 | 拒绝（数值重复） | PASS |
| count_6_not_7 | `5 10 15 20 25 30` | 10 | 拒绝（数量不符） | PASS |
| invalid_token | `5,10,abc,20,25,30,35` | 10 | 拒绝 | PASS |
| negative_freq | `5,10,-15,20,25,30,35` | 10 | 拒绝 | PASS |
| zero_freq | `5,10,0,20,25,30,35` | 10 | 拒绝 | PASS |

```text
all_ok = true ; new_run_dirs = []      ← 10 个拒绝用例**都没有**创建 run 目录
```

命令：`python -B work/tools/min_exec_r8b_evidence.py valid --out work/runs/_evidence-r8b/freqs_valid.json`

| 字面量 | 旧实现（按逗号切分） | 新实现 | canonical_plist |
|---|---|---|---|
| `5 10 15 20 25 30 35` | **1** | **7** | `5[MHz] 10[MHz] 15[MHz] 20[MHz] 25[MHz] 30[MHz] 35[MHz]` |
| `5,10,15,20,25,30,35` | 7 | 7 | 同上（两者 canonical plist 完全一致） |

```text
expected_count = 7 ; expected_count_source = "默认生产授权口径 EXPECTED_FREQ_COUNT=7（= len(DEFAULT_FREQS)）"
freq_parse_refusal_exit = 10 ; freeze_unresolved_exit = 11 ; all_ok = true
```

### 6.2 ② 冻结证据：真跑 supervisor（`fake-combo-worker`，**不启动 COMSOL**）

命令（由取证器记录进 `smoke_*.json` 的 `argv`，下同）：

```text
python -B work/tools/lt2_production.py --run-id <RUN> --role supervisor
       --worker-role fake-combo-worker --combos [[0.6,4]] --max-combos 1 --batch-size 4
       --freqs <RAW> --interval 1 --gate-poll 0.3 --fixed-timestamps
       [--freeze-id <FID>]
```

| 用例 | RUN | freqs 字面量 | freeze-id | exit | `freeze_hash_pre_post_match` | pre/post verdict | files_identical | running_script match | manifest |
|---|---|---|---|---|---|---|---|---|---|
| A | lt2-min-exec-r8b-frozen-space-a | `5 10 15 20 25 30 35` | 临时冻结 | 6 | **true** | MATCH / MATCH | true | true | 24,029 B |
| B | lt2-min-exec-r8b-frozen-comma-b | `5,10,15,20,25,30,35` | 临时冻结 | 6 | **true** | MATCH / MATCH | true | true | 24,028 B |
| B2 | lt2-min-exec-r8b-frozen-comma-b2 | 同 B（仅 run-id 不同） | 临时冻结 | 6 | **true** | MATCH / MATCH | true | true | 24,034 B |
| N | lt2-min-exec-r8b-negative-oldfreeze | `5,10,15,20,25,30,35` | **旧冻结 1810** | **11** | —（未启动） | — | — | — | **未产出** |

说明（必须如实登记，避免误读）：

- **exit 6 = `BLOCKED_OR_LIMITED`，是 `fake-combo-worker` 的既有语义**，不是 ②③ 引起的回归：
  假 worker 的 `pass_conditions` 只含 2 项，故批次级 4 项（commit 硬停/commit 下限/LT2-C/取消）判 False。
  机械对照见 6.3：**用 1810 快照里的旧代码跑同一条路径，`aggregate_pass_conditions` 与 `status` 逐字相同**。
- 用例 N：`--freeze-id` 指向旧冻结（源码已变）⇒ **运行前**核验即判定
  `INVALIDATED_BY_CODE_DRIFT, drift_count=1`，**拒绝启动**（exit 11），
  **没有创建 run 目录、没有写 manifest**（`Test-Path ... = False`）⇒ 不会白跑一整批才发现拿不到证据。
- 确定性与输入无关的部分已单独证明（6.3）。

### 6.3 对照与确定性（机械）

| 对照 | 命令 | exit | 结论字段 |
|---|---|---|---|
| 新增字段确定性（B vs B2，输入完全相同） | `... compare --manifest-a ...comma-b --manifest-b ...comma-b2` | 0 | `new_fields_all_equal = true`（`freqs_parse` 754 B / `freeze_evidence` 10,816 B / `freeze_id` / `freeze_hash_pre_post_match` 四项 sha256 两侧全等） |
| 判定未变（旧代码 C vs 新代码 B） | `... compare --manifest-a ...control-old1810 --manifest-b ...comma-b` | 1（因旧代码**没有**新字段，`new_fields_all_equal=false`，属预期） | **`behaviour_equal = true`**：`status / blocked_reason / aggregate_pass_conditions / batch_size / server_lifecycle_size` 逐字相同 |

```text
整份 manifest 逐字节比较（B vs B2）= false  ⇒ 如实登记：
  整份含 run_id / 绝对 child_dir / 顶格 "at"（wallclock，非固定时钟）⇒ 本来就不同（**改动前亦然**）。
  故确定性结论只对**本轮新增字段**成立，这也是本轮唯一需要成立的确定性。
```

### 6.4 全套 82 断言（回归）

```text
命令：python -B work/tools/tests_lt2_supervisor.py --namespace ns-r8b-regress-20260914-1930
exit = 0 ; total 82 / pass 82 / fail 0 ; failures = [] ; exception = null
tests_sha256 = d85622df5d0b58e86028c8845421705a70717cf24389cc89bac63732d206cc38（测试件未改）
comsol_started = false ; mph_imported = false ; comsol_servers_seen = [] ; lock.ok = true
命名空间根 = work/runs/ns-r8b-regress-20260914-1930（独立命名空间，未触碰既有证据目录）
```

重点核对的条目：**T10 supervisor→worker→sampler 接线跑通（worker 未拒绝）= true**
——这正是 ③「supervisor 向 worker 下传 `--expect-freq-count`」改动所触及的路径。

### 6.5 用父 agent 的检查器读本轮产物（接口是否已对齐）

```text
命令：python -B work/tools/check_r3_conditions.py --run-id lt2-min-exec-r8b-frozen-comma-b
结果：15/21；其中
  "freeze_hashes_pre_post_match": { "pass": true, "detail": "True（缺字段即判 False）" }   ← ② 已对齐
其余 6 项失败项全是「fake 场景的固有缺失」，与 ②③ 无关：
  rows_eq_7 / unique_freqs_eq_7 / solve_error_is_null / lt2c_quick_gate_pass /
  pid_source_is_port_owner / identity_complete
  （该 run 是 1 行模拟数据、未起 COMSOL、无真实 server ⇒ 这些字段本就不存在）
```

### 6.6 layout 原文

```text
[C:\Users\zmx\Desktop\memsharness\work\runs\_evidence-r8b]
compare_B_vs_B2.json
compare_C_old_vs_B_new.json
checker_on_smoke_B.json
diff_vs_freeze_1810.json
diff-vs-freeze-1810.patch
freqs_refusals.json
freqs_valid.json
nofreeze_path_evidence.json
smoke_A_space_frozen.json
smoke_B_comma_frozen.json
smoke_B2_comma_frozen.json
smoke_N_oldfreeze_refused.json

[C:\Users\zmx\Desktop\memsharness\work\runs\lt2-min-exec-r8b-frozen-comma-b]
batch_manifest.json
child_00_attempt_1

[child_00_attempt_1 of run B]
checkpoint.json          ← 内含 freqs_parse（line 20）与 freeze_id（line 59）
raw_rows.csv
resource_timeline.csv
resource_timeline.jsonl
rows.csv
sampler_state.json
worker_state.json

[全部新增 run 目录]
lt2-min-exec-r8b-control-old1810          （旧代码对照）
lt2-min-exec-r8b-frozen-comma-b
lt2-min-exec-r8b-frozen-comma-b2
lt2-min-exec-r8b-frozen-space-a
lt2-min-exec-r8b-nofreeze-a               （未给 --freeze-id 的路径：requested=false）
lt2-supervisor-acceptance-freeze-20260914-min-exec-r8b-provisional-not-for-acceptance
work/runs/ns-r8b-regress-20260914-1930    （82 断言套件命名空间）
反向用例目录 lt2-min-exec-r8b-negative-oldfreeze 不存在（Test-Path = False）
```

### 6.7 证据文件哈希

| 文件 | bytes | sha256 |
|---|---|---|
| `work/tools/lt2_production.py` | 138,923 | `63a36ca5411df41f6b881212e210cc29034d031ad3bb07b06e10a13b33c53bf5` |
| `work/tools/min_exec_r8b_evidence.py` | 19,308 | `21fcfe1f7e4633ef94fac95103a0fb9d5ad702e9e84ba16cfe2070606617430e` |
| `_evidence-r8b/freqs_refusals.json` | 45,999 | `7ba7170568f99a4f08aec14ea344cc18bc2b2c5b6748cd742f90d8f2319cd076` |
| `_evidence-r8b/freqs_valid.json` | 1,877 | `18394713fd820cee0de66c64fb53c7de008f013204ff56bd3a302423baf4d9e1` |
| `_evidence-r8b/smoke_A_space_frozen.json` | 17,733 | `374344642eca2e656cb5ae76e808850929ccffc038c2fef0581940cba473f13c` |
| `_evidence-r8b/smoke_B_comma_frozen.json` | 17,733 | `672e11eb6a2b22e00d676ee00d5536ce81f06b6a39b54fa8615c59a49bb081c1` |
| `_evidence-r8b/smoke_B2_comma_frozen.json` | 17,737 | `e9d3f8db6d8ec57d271c021fef30e9e618c209f8edfe0d8f5e319bf43a491419` |
| `_evidence-r8b/smoke_N_oldfreeze_refused.json` | 2,626 | `d5df8c0c86f7655d7a7a94121f35da09d33521ef00d74f926609750460e5690c` |
| `_evidence-r8b/compare_B_vs_B2.json` | 3,590 | `a078216070b5bc943e1f7821464f40d350e1fe42250db3d2d7acfaa1e4d5d7c6` |
| `_evidence-r8b/compare_C_old_vs_B_new.json` | 3,530 | `02d0b9b33b87ca29047691b5ca7e789b61bcb1729fce743ffab59ede0c1312ff` |
| `_evidence-r8b/diff_vs_freeze_1810.json` | 5,035 | `474461f662993aa4745835098613a691d6298926d6ac355aac689f30a6fd1fb0` |
| `_evidence-r8b/diff-vs-freeze-1810.patch` | 19,013 | `15fb893d940daa19c17c1775703fe575e6705ea0e80791da1cdf0d4f62010f6e` |
| `_evidence-r8b/checker_on_smoke_B.json` | 3,850 | `9d1de8e3722282ee9d2019846dcf53a680e6ea1b376ca0000149473ca5107485` |
| `_evidence-r8b/nofreeze_path_evidence.json` | 461 | `3351046dfe30f687f50e50ba1bd6abc0dfd5dab0a0f5ac8b64b23bcf4c0e51f8` |
| `runs/lt2-min-exec-r8b-frozen-space-a/batch_manifest.json` | 24,029 | `4362f915671438651edc66df7eaeb7f8d5081c991541b160d1e4bfa99410ff9f` |
| `runs/lt2-min-exec-r8b-frozen-comma-b/batch_manifest.json` | 24,028 | `e3c28dd752a3996d46647916f82081c8d3d5b3f237efcd9a2b9a2872412b1056` |
| `runs/lt2-min-exec-r8b-frozen-comma-b2/batch_manifest.json` | 24,034 | `0aa883b1bd5257562965a368d41aba92ca185f2d54ce1b8ceb772df0007e6771` |
| `runs/lt2-min-exec-r8b-frozen-comma-b/child_00_attempt_1/checkpoint.json` | 3,565 | `f7fed542de8425604be9abd433bbe75fe3d45b3810103367e8859abfecad790e` |
| `runs/ns-r8b-regress-20260914-1930/test_summary.json` | — | 82/82，见 §6.4 |

---

## 7. 未改动清单（防止「顺手改了别处」）

```text
rt_gate.py            未改（sha256 23ef7fdcac58e4f6… 与 1810 相同）
lt2_sampler.py        未改（7700e3eb4a56f49f…）
tests_lt2_supervisor.py 未改（d85622df5d0b58e8…）
lt2_acceptance_r4.py  未改（89030f7975ef48d4…）
其余 AUX（check_undefined_names / lt2_flake_hunt / lt2_expected_inventory / lt2_conc_tests /
         tests_rt_gate / repro_b_sampler / test_atomic_retry）均未改
阈值 / 判定逻辑：未改（§6.3 behaviour_equal = true 为机械证据）
assemble_manifest_from_child_dirs()：**故意未改**（见 §8-③）
硬停演练（U1–U3）：未执行；LT2 生产批次：未启动
```

---

## 8. 需要父 agent 拍板的 3 处设计选择

**① `--freeze-id` 是不是必需？**
现状：可选。给了但核验不过/无法核验 ⇒ **拒绝启动**（exit 11，避免白跑 16 h 才发现拿不到证据）；
**没给** ⇒ 不拒绝，但 `freeze_hash_pre_post_match` 恒为 `false` 且带显式
`reason = "未提供 --freeze-id ⇒ 运行自身无法证明冻结未漂移；该字段一律 false（fail-closed）"`。
实测（`lt2-min-exec-r8b-nofreeze-a`，manifest 11,403 B
`9631f83754d35e93b8b5170517af7a9cef9c3ed22dac10650f013dad6e549d96`）：
`requested=false / freeze_id=null / pre=post=null / freeze_hash_pre_post_match=false`，
同一次运行里 `freqs_parse` 仍正常写出（count=7）。
理由：把「拒绝启动」做成必需项会连带改掉自测路径（`tests_lt2_supervisor.py` 不传 freeze-id），
那就超出「只碰两处」。若父 agent 要求生产运行必须显式给 freeze-id，请明示，我另开一轮改。

**② `freeze_hash_pre_post_match` 的合取项多了一项。**
我定义为 4 项合取：pre ok ∧ post ok ∧ 两次逐文件哈希集合一致 ∧ **运行中的脚本 == 冻结件**
（最后一项为新增，用于防「从非冻结副本执行」）。若父 agent 认为应按字面口径只取前 3 项，请明示。

**③ `--assemble-manifest-only` 产出的 manifest 仍**不含**该字段（检查器会判 false）。**
我故意没动 `assemble_manifest_from_child_dirs()`：它是**只读重建**（不是一次运行），
按 fail-closed 判 false 是正确的。若父 agent 希望「任何 `batch_manifest.json` 都显式写出该字段
（重建件写 false + reason）」，我可以在下一轮补——但那会再动一处代码，需新 freeze。

---

## 9. 建议的下一步

```text
1) 父 agent 建新 freeze（lt2_production.py = 63a36ca5…）
   —— 建议把 work/tools/min_exec_r8b_evidence.py（21fcfe1f…）也纳入 AUX，
      否则本轮 §6 的最小执行证据不可第三方复算。
2) 从**新快照**重跑 r3（新 run-id），沿用既有 r3 命令，并显式加 --freeze-id <新 freeze>；
   届时 batch_manifest.json.freeze_hash_pre_post_match 应为 true，检查器第 ② 项判真。
3) 硬停演练（U1–U3）与 LT2 生产批次仍等父 agent 单独放行。
```
