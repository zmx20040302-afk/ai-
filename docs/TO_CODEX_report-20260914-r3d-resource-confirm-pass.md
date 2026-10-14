# r3d 正常资源确认：**PASS（23/23 + 六项额外核对全过）**，真机首次「正常收尾零假触发」

- run_id：`lt2-resource-confirm-x080-n02-postpagefile-r3d`（新 id，未复用 r3/r3b/r3c）
- 冻结：`freeze-20260914-2040-post-guard-persistent`
  manifest `1c87385b1cab54188c5d7d46075074d323d9442dc2a4874c8df5568cb74f9ce2`
- 执行：**从冻结快照执行**（`.../freeze-20260914-2040-post-guard-persistent/snapshot/lt2_production.py`）
- 时间：20:19:44 → 20:33:12（约 13.5 min）；`solve_seconds = 763.8`
- 参数：`--combos [[0.8,2]]`、`--freqs 5,10,15,20,25,30,35`、显式 `--freeze-id`；
  **未加 `--drill`、未压低阈值、前置门禁默认、单实例串行、后台作业**；退出码 **0**，`status=PASS`

---

## 0. 结论

| 项 | 结果 |
|---|---|
| `check_r3_conditions.py` | **23/23**，`all_pass=True`，失败项 `[]`，exit 0 |
| 三布尔 | `freeze_hash_pre_post_match` / `executed_from_frozen_snapshot` / `freeze_evidence_complete` **全 true** |
| 额外核对 1 无 signals + `termination==null` | **PASS**（`signals/` **不存在**，`termination == null`） |
| 额外核对 2 `normal_completion` 记录 | **PASS**（`normal_completion_sidecar_exit` / `is_hard_stop=false` / `decided=observe_normal_completion`） |
| 额外核对 3 真实退出码 | **PASS**（`worker_returncode = 0`，`worker_returncode_recorded = true`） |
| 额外核对 4 资源轴同口径 | **PASS**（见 §2） |
| 额外核对 5 `enforced_by` 恒为 null | **PASS**（`enforced_by=null`、`enforcement_source=null`、**未**出现 `normal_completion_timeout_gate`、`termination_trigger=null`） |
| 额外核对 6 落盘记录**未被后续轮次改写** | **PASS**（三重证据，见 §3） |
| 运行期冻结未漂移 | `--verify` **MATCH**（drift 0，20:33:27）、`--verify-snapshot` **MATCH**（含精确文件集校验） |

---

## 1. 判据与产物

```text
python work/tools/check_r3_conditions.py --run-id lt2-resource-confirm-x080-n02-postpagefile-r3d \
       --json-out work/runs/_evidence-r3d/r3d_checker.json
→ [结论] 23/23 通过；all_pass=True；失败项=[]
   （含 freeze_hashes_pre_post_match / executed_from_frozen_snapshot / freeze_evidence_complete 三条）
```

| 项 | 值 |
|---|---|
| 结果行 | `rows=7`、唯一频率 7（5/10/15/20/25/30/35 MHz）、`drive_mismatch=0` |
| 网格 / 求解 | `mesh_element_count=157,390`、`solve_seconds=763.8`、`solve_error=null`、`stage=closed` |
| 频率解析 | `freqs_parse.count=7`，canonical `5[MHz] … 35[MHz]`（逗号形式，已留痕） |
| LT2-C | `checks.pass=true`；容差证据 frozen=current（`area_relative_difference=0.0`） |
| 身份 / 收尾 | `pid_source=port_owner`、`parent_is_worker=true`、`port_closed_within_30s=true` |
| 冻结窗口 | pre `20:19:44` MATCH / post `20:33:12` MATCH（**真实墙钟**，构成批次窗口上下界） |
| `running_script_is_frozen_target` | `match=true`（`self_path` 落在 snapshot 目录） |
| 无 drill | `drill_anywhere=false`、`stop_line` 事件 0 |
| child 目录 | `checkpoint.json` / `rows.csv` / `raw_rows.csv` / `resource_timeline.jsonl`+`csv` / `sampler_state.json` / `worker_state.json` / **`termination_trigger.json`（= 正常收尾记录）**；**没有 `signals/`** |

## 2. 资源轴（与 r3b 同口径）

| 指标 | r3d | r3b（对照） | 判据 |
|---|---|---|---|
| commit 最低 | **9,031.3** | 8,724.3 | > 6144 ✔ |
| commit 最高 | 21,525.6 | 21,205.4 | — |
| WS 峰值 | **11,149.5** | 11,177.7 | < 12,288 ✔ |
| avail 最低 | **7,373.8** | 6,783.1 | ≥ 4096 ✔ |
| 时间线行数 | 160 | 160 | 无空档 ✔ |
| >15 s 空档 / 不可解析时间戳 | 0 / 0 | 0 / 0 | ✔ |
| 三类硬停采样 / commit 预警采样 | 0 / 0 | 0 / 0 | ✔ |
| 缺列（solve 阶段） | 无 | 无 | ✔ |

两次均为**无第三方并行负载**的干净基线。

## 3. 额外核对 6：落盘记录「写完不再被改写」的三重证据

r3c 的缺陷形态是「20:12:30 记了正常收尾 → 20:12:37 被 enforce 覆盖」。
r3d 用**独立看门狗**（10 s 轮询，共 **83 次**）全程记录该文件的哈希：

```text
[C:\Users\zmx\Desktop\memsharness\work\runs\_evidence-r3d\trigger_write_watch.jsonl]
{"ts": "2026-09-14T20:33:07", "polls": 82,
 "sha256": "79014cb31b14b1e4fd521c5557b6aee1a1b7e2f47028d8485dc027c49d967124",
 "bytes": 1277, "mtime": 1789389182.23, "kind": "normal_completion_sidecar_exit"}
→ distinct_hashes = **1**（83 次轮询只出现过**一个**哈希）
```

| 证据 | 观测 |
|---|---|
| ① 看门狗时间序列 | 83 次轮询、**1 个不同哈希**；首次出现 `20:33:07`（kind 即 `normal_completion_sidecar_exit`）；运行结束后重读哈希**完全相同**、mtime **未变**（`20:33:02`） |
| ② 结构一致性 | 落盘记录与 `batch_manifest.json` 里 `children[0].normal_completion` 是**同一份**（`at` 均为 `20:33:02`、kind 相同）；而 `children[0].termination_trigger is None`、`termination is None`（= 该 child **没有**任何 enforce 触发记录） |
| ③ 目录级 | `<run_id>/signals/` **不存在**（enforce 才会写）；child 目录里的 `termination_trigger.json` 内容 = 正常收尾记录本身 |

落盘记录原文（`/child_00_attempt_1/termination_trigger.json`）：

```json
{ "trigger_kind": "normal_completion_sidecar_exit", "is_hard_stop": false,
  "enforced": false, "enforced_by": null,
  "decided": {"action": "observe_normal_completion", "source": "normal_completion_guard",
              "reason": ["checkpoint_present"], "note": "正常收尾：不 enforce、不写 signals（没有终止要求）；等 worker 自然退出以取得**真实** worker_returncode"},
  "normal_completion_markers": ["checkpoint_present"],
  "wording_note": "本记录**不是**终止要求、**不是**资源事件：trigger_kind=normal_completion_sidecar_exit；只有 threshold_crossed 才是资源硬停",
  "at": "2026-09-14T20:33:02" }
```

> 细节值得记一笔：本次 markers 只有 `checkpoint_present`，没有 `worker_stage_closed` ——
> 因为 worker 是**先写 checkpoint 再置 stage=closed**，守卫在**最早**的正面证据上就命中了。
> 这也说明"checkpoint 存在"这条判据是**必要且充分**的早期信号（两个 marker 任一即可）。

---

## 4. 本轮修复链条（r3c 失败 → r8d2 修复 → r3d 通过）

```text
r3c（freeze-2020）：23/23 但额外核对 1 失败 —— 守卫只抑制**一次**，
                    记录后下一轮落回旧路径 ⇒ sidecar_exited ⇒ 20:12:37 仍 enforce
r8d2（修复）：持续抑制 + 有界升级（60 s → normal_completion_timeout_gate）+ 真实越线仍优先
r3d（本轮）：23/23 + 六项全过；signals 不存在；记录只写一次且不再被改写
```

## 5. 两条固化的教训（父 agent 已确认采纳，一并转 Codex）

```text
(A) **替身/复现器必须包含真实故障的全部条件，否则测试会"以错误的理由通过"。**
    实测：r8d 第一版替身复现了 stage=closed + checkpoint，却把 sampler_pid 写成 null
    ⇒ 旧代码落进"启动期"分支、从不 enforce ⇒ 测试 12/12 全绿而真机 r3c 依然失败。
    补救：替身补齐 r3c 的全部条件（含 sampler_pid 指向**已结束**进程 + 正常样本）并多轮驻留；
    并**证明测试灵敏度**——把同一套断言跑在历史冻结快照上必须失败
    （2020 快照 FAIL 7 项、2000 快照 FAIL 12 项，均为该缺陷的真实形态）。
(B) **抑制/守卫类修复必须"持续生效"且"有界"。**
    把"只记一次"写进守卫条件 ⇒ 下一轮落回旧路径（r3c 实测）；
    持续抑制不设上界 ⇒ worker 收尾卡死时 supervisor 永久挂住。
    正确形式：守卫成立期间**每轮**都抑制 + 上界（本例 60 s）超时**升级处置**，
    且升级标签自解释（`normal_completion_timeout_gate` = "正常收尾已判定但 worker 超 60 s 未退出"），
    不会被读成资源硬停。
```
两条已写入技能 `.dsh/skills/freeze-and-acceptance/SKILL.md` §8（踩坑 9/10）与 §9。

## 6. 证据与哈希

```text
work/runs/_evidence-r3d/
  r3d_checker.json                       23/23 判据 + evidence 段
  r3d_artifact_summary.json              运行实质 + 六项额外核对取值 + 产物哈希
  r3d_record_not_overwritten_evidence.json   额外核对 6 的三重证据
  trigger_write_watch.jsonl              看门狗原始记录（83 次轮询 / 1 个哈希）
  r3d_stdout.log / r3d_stdout_utf8.log   supervisor 原始输出（GBK 原样 + UTF-8 副本）
  evidence_hashes.json                   本目录全部哈希清单
被测件（本轮未改动，与冻结值一致）：work/tools/lt2_production.py
  153,287 B  81936aeb0b5d42cbfdef5f973ba67c0abc9c21706d83dbd6cd1fe49cbf084f8a
```

## 7. 未做

```text
未执行硬停演练（U1–U3）    未启动 LT2 生产批次    未改任何被测件/阈值/判定逻辑
未复用任何既有 run-id      未清理任何现场（r3/r3b/r3c/r3d 全部保留）
```
