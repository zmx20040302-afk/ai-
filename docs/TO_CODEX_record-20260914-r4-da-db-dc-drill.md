# TO CODEX — D-A / D-B / D-C 修复 + `--drill` 演练模式 + 接线冒烟测试（2026-09-14 第四轮）

- 依据：父 agent 现场实测（run-id `lt2-resource-confirm-x080-n02-postpagefile` 启动失败）+ 追加的演练需求
- 约束遵守：**未运行任何 COMSOL / comsolbatch / mphserver**（末次核验 2036=0、comsolmphserver=0、comsolbatch=0）；
  **未碰页面文件**；未改 `AGENTS.md`/`WORKING_PLAN.md`/`rt_gate.py`/`tests_rt_gate.py`/`lt2r0_v2.py`
- 本文 append-only；取代 `docs\TO_CODEX_record-20260914-supervisor-p0-fixes.md` §1 的哈希表

---

## 1. 交付物与哈希（引用时刻：2026-09-14 13:23:52）

| 文件 | 字节 | sha256 |
|---|---|---|
| `work\tools\lt2_production.py` | 114,697 | `dac8270dec1f983f700e4ad0e5a97caee330912b0eda34814e61d5294030e0ca` |
| `work\tools\lt2_sampler.py` | 15,668 | `7700e3eb4a56f49f1a57b3f07952fbe56de3acb25c78d6a7fe5a2f206d547abd` |
| `work\tools\tests_lt2_supervisor.py` | 42,598 | `1108c01892bb705e0e4110166fd67158255fb17d349984ac55fd24d8f5481d0f` |
| `work\tools\rt_gate.py`（未改） | 9,466 | `e99e76b76db1cd413ec5961c5dbca8379bd4a03ced4ddb24b2fd1c303cf3f5db` |
| `work\tools\tests_rt_gate.py`（未改） | 9,455 | `d15dddc0d9c33c3e52c7a76542927607ccd80476f749caade2f56f849ae6febc` |

---

## 2. D-A（阻断级）：supervisor 预写 child 目录 与 worker 守卫互斥 —— 已修

### 2.1 真实根因（比"两机制矛盾"更深一层）

父 agent 观察到的现象（`*_refused.json` + `sampler_state` 四项全 null + `decided.source=sidecar_health` +
同一秒写信号）由**启动竞态**触发，逐轮推演如下：

1. `supervise_child` 先 `child_dir.mkdir()`（空目录），随后 `Popen(worker)`；
2. supervisor 的监督循环**立刻**开始：此时 worker 还在 `import numpy/mph`，`worker_state.json` 还不存在；
3. 旧代码 `proc_exists(ws.get("sampler_pid"))` → `proc_exists(None)` → `False`
   → `sidecar_health(now, None, False)` 直接返回 **`sidecar_exited`**（rt_gate 里 `not proc_alive` 优先于一切）；
4. ⇒ **第一节拍就判 hard_stop**，`verified_emergency_termination` 立即往 child 目录写
   `hard_stop_trigger.json` + `supervisor_signal.json`；
5. worker 这时才起来，执行 append-only 守卫，看到目录非空 → **拒绝并退出**。

所以 D-A 是「启动竞态 → 立刻误判 sidecar 失效 → 往 child 目录写信号 → 撞上守卫」的连锁，而不是单纯两机制冲突。

### 2.2 修复（唯一规则，且只在一处声明）

1. **信号文件移出 child 目录**（首选方案）：`<run_id>/signals/<child_dir_name>.signal.json`。
   child 目录**只放证据**。规则写在 `CHILD_FILE_SPEC_NOTE` 与 `batch_manifest.child_file_spec` 里，
   不再有第二套白名单。
2. **启动宽限** `STARTUP_GRACE_S = 180 s`：宽限期内「还没有 `sampler_pid`」「还没有首个样本」
   **不得**判为 sidecar 失效；宽限期满仍未登记 `sampler_pid` ⇒ 归 `worker_startup_failure`（**不是** resource_hard_stop）。
3. `sidecar_health` 在 `rt_gate.py` 内**未改动**（该文件禁止修改）；竞态与宽限逻辑放在我自己的
   `supervise_child` 里，先判 `worker_state` 是否已登记 sampler，再决定是否调 `sidecar_health`。

---

## 3. D-B（严重）：失败被误分类为 `resource_hard_stop` —— 已修

旧 `classify_retry()` 只要存在触发记录就判 `resource_hard_stop`。现在改为按 `trigger_kind` 分流：

| trigger_kind | is_hard_stop | 重跑类别 | 可重跑 |
|---|---|---|---|
| `threshold_crossed`（真实） | true | `resource_hard_stop` | 否 |
| `threshold_crossed`（drill） | true | **`drill_hard_stop`** | 否 |
| `worker_startup_failure` | false | `server_startup_transient` | **是（一次）** |
| `integrity_failure` / `sample_gap_or_health` / `unclassified_failure` | false | `sampler_supervisor_integrity` | 否 |
| （目录复用被拒，独立标志） | — | `child_dir_reuse_refused` | 否（fail-closed） |

`resource_hard_stop` **只在** `ss.verdict == "hard_stop"` **且** `reasons` 含阈值穿越词
（`ws_hard_stop(` / `physical_avail_hard_stop(` / `commit_hard_stop(`）**且** `sample_index >= 2` 时成立。
`sidecar_exited`、无样本、worker 启动失败**永远不会**推导出 `resource_hard_stop`。

## 4. D-C：没有越线样本不得称 hard stop —— 已修

- 触发记录改名 `termination_trigger.json`（不再叫 `hard_stop_trigger.json`），**必带**
  `trigger_kind` 与 `is_hard_stop`，并带 `wording_note`：
  > 仅当 `trigger_kind == 'threshold_crossed'` 时本记录才是资源硬停；其余均为基础设施/完整性故障，不得称 hard stop
- `threshold_evidence` 只在真越线时写出，且阈值取**生效阈值**（演练时为覆盖值），
  不再记成默认值（这一条是自测中发现的真实 bug：演练阈值 5000 曾被记成默认 12288）。
- `child_dir` 清单规约同步更新（`enforcement_probe` 要求 `worker_state.json` + `termination_trigger.json`）。

---

## 5. `--drill` 演练模式（仅演练，绝不可用于生产）

1. **显式开关 + 把关**：阈值覆盖 `--ws-hard-stop-mb` / `--commit-hard-stop-mb` /
   `--physical-hard-stop-mb` **只在同时给 `--drill` 时接受**；否则直接拒绝、退出码 **9**：
   ```
   [STOP] 阈值覆盖 ['commit_hard_stop_mb'] 只在 --drill 演练模式下允许；生产运行必须使用 Codex 裁定阈值
   ```
2. **走真实门禁路径**：真样本、真 `GateEngine`、真「连续 2 个 5 s 采样」判定；未注入任何假样本。
   压低阈值后「启动阶段低、进入 solve 才越线」由 sampler 的 `ramp_ws` 剖面保证。
3. **产物自我标识**：`drill: true` + `drill_thresholds`（原值/演练值）+ `drill_note` 写入
   **每个时间线样本**、`sampler_state.json`、`checkpoint.json`、`batch_manifest.json`、
   `termination_trigger.json`；批次根另写 **`DRILL_README.txt`**。
4. **分类隔离**：演练硬停分类为 `drill_hard_stop`，不混入 `resource_hard_stop`。
5. **前置门禁照常执行**：演练不跳过 `--avail-gate` / `--commit-gate`（已用强制失败门禁验证，见 §7）。

### 5.1 你要的调用式（已按你的参数逐项核对，可直接照抄）

```powershell
python work/tools/lt2_production.py --run-id <新的唯一id> --combos '[[0.8,2]]' --freqs '5' --max-combos 1 `
       --drill --ws-hard-stop-mb 5000 --interval 5 --gate-poll 3
```

逐条确认：

- (a) **会真实启动 server 并进入 solve**：`--drill` 不改变 worker 的真实路径（仍 `mph.start(cores=1, port=2036)`
  → 载入模型 → `geom.run` → `mesh.run` → LT2-C → `study("std1").run()`）。
- (b) **会在 study 阻塞期间因 verdict 动作**：supervisor 每 `--gate-poll 3` 秒读
  `sampler_state.verdict` / `worker_state.cancel_requested`；WS 一旦连续 2 个 5 s 采样 ≥ 5000 MB
  即 `hard_stop_enforce`（**先判 verdict，再判 cancel_requested，最后才判 sidecar 健康**）。
  注意：若本机 solve 阶段 WS 上升很快，可能在 LT2-C 之后约 10–15 s 触发；
  若你希望**更早**触发，把 `--ws-hard-stop-mb` 再压低（例如 3000），或在**启动阶段**就压低
  ——当前实现是在 `study.run()` 期间触发，正合 U1 场景。
- (c) **会执行 `verified_emergency_termination` 并做四项二次确认**：终止命令退出码、expected PID 消失、
  端口 2036 关闭、无意外 `comsolmphserver`；PID/端口均**带超时轮询**后才判。
- (d) **证据留在 `child_00_attempt_1/`**：`resource_timeline.jsonl`（每行带 `drill:true`）、
  `resource_timeline.csv`、`sampler_state.json`、`worker_state.json`、`termination_trigger.json`；
  退出请求在 `<run_id>/signals/child_00_attempt_1.signal.json`；批次根有 `batch_manifest.json` + `DRILL_README.txt`。
- **退出码约定**：演练触发硬停 ⇒ 该 child 不是 `pass` ⇒ 批次 `BLOCKED_OR_LIMITED` ⇒ 退出码 **6**。
  这是**预期结果**（演练本来就要触发硬停），不是失败。`--preflight-only` 才是 5。
- **参数名/语义无误**：`--drill`、`--ws-hard-stop-mb`、`--freqs`、`--combos`、`--max-combos`、
  `--interval`、`--gate-poll`、`--run-id` 均为实际参数；`--combos` 是 JSON 数组，
  Windows 下建议用单引号包住（PowerShell 里 `'[[0.8,2]]'` 可用）。

---

## 6. 5 项接线冒烟测试（D-A 回归的漏测链路）+ 演练/把关测试

`python work/tools/tests_lt2_supervisor.py` → **exit 0，合计 59 项断言，通过 59，失败 0**
（`comsolmphserver 进程 = []`）。新增项：

| # | 要求 | 结果 |
|---|---|---|
| T10 | 正常路径：supervisor 启动 1 个 child，worker **不得拒绝**，child 内含 5 件套 | PASS：`child_00_attempt_1/` = `checkpoint.json, raw_rows.csv, resource_timeline.csv, resource_timeline.jsonl, rows.csv, sampler_state.json, worker_state.json`；timeline sha256 非空 |
| T11 | supervisor 信号**不在** child 目录内 | PASS：child 内无 `supervisor_signal.json`；正常路径也不产生信号（只在硬停时写到 `signals/`） |
| T12 | 正常路径无 `*_refused.json` 且分类**不是** `resource_hard_stop` | PASS：`refused 文件=无`、`child_dir_reuse_refused=False`、`class=unclassified`、`trigger=None` |
| T13 | `resource_hard_stop` **只在**注入越线样本时出现（含反向） | PASS 5/5：越线→`resource_hard_stop`；越线+drill→`drill_hard_stop`；无 worker_state→`server_startup_transient`；首样本前退出→`sampler_supervisor_integrity`；目录复用被拒→`child_dir_reuse_refused` |
| T14 | `--fixed-timestamps` 下连跑两次哈希逐字节一致 | PASS：6 个证据文件 0 不一致（排除控制通道 `worker_state.json`，理由见 §7） |
| T15 | 演练接线（无 COMSOL）：压低阈值 → 运行期硬停 → drill 标记 + `drill_hard_stop` | PASS 7/7：`threshold_crossed`+`is_hard_stop=true`、`drill_hard_stop`、阈值证据含 `ws_hard_stop_mb=5000`、信号在 `signals/`、时间线 `drill=true`、无真实 server 时**绝不声称终止成功** |
| T16 | `--drill` 把关 | PASS：无 `--drill` 传阈值 ⇒ exit **9**；前置门禁路径有明确 gate 结论 |

### 6.1 冒烟测试又抓出**两个**真实缺陷（都已修）

1. **run-id 复用防护漏了新的 worker 角色**：守卫条件原为 `args.role != "combo-worker"`，
   新增的 `fake-combo-worker` 未被豁免 ⇒ worker 被自己拦下、exit 4、child 目录全空。
   已改为**只对 `role == "supervisor"` 生效**（worker 角色由 supervisor 拉起，必须跳过）。
   若没有这条冒烟测试，真实演练会用同样方式失败（我会以为代码没问题）。
2. **演练阈值没有传到 worker→sampler**：`supervise_child` 只传了 `--drill` 没传三个阈值，
   sampler 退回默认值 ⇒ 演练不会触发。已修为一并透传，并让 `threshold_evidence` 记录**生效阈值**。
   另外 sampler 的模拟剖面原先**只有会越线的一种**，「正常路径」其实一直在触发 commit 硬停——
   现新增 `safe` / `ramp_ws` 两个剖面，正常冒烟用 `safe`、演练用 `ramp_ws`。

---

## 7. 连跑两次哈希一致证据（G1）

同一命令连跑两次 `tests_lt2_supervisor.py`，逐文件 sha256 对照：

```text
=== 连跑两次逐字节复算 ===
  core      文件数=34 不一致=0
  smoke     文件数=6  不一致=0
  manifest  文件数=35 不一致=0
  batch_manifest.json 两次一致 = True
```

- **可复算集合**：`lt2-supervisor-selftest/`（34 个文件）+ `lt2-supervisor-selftest-smoke/`
  的 6 个证据文件 + 含 `batch_manifest.json` 的 35 个文件，全部逐字节一致。
- **明确不可复算**（已在报告与代码注释中标注，不再混入证据）：
  - `lt2-supervisor-selftest-liveproc/`：T1/T6/T7 做**真实进程终止**，必然写入真实 PID/启动时间；
  - `lt2-supervisor-selftest-wallclock/`：wallclock 反例专用；
  - `worker_state.json`：**控制通道**，必须携带真实 `sampler_pid` 供 supervisor 判活 ⇒ 天然不可复算；
    证据文件（时间线 / `sampler_state.json` / `checkpoint.json` / `rows.csv`）才是可复算对象，
    且 `checkpoint.json` 在确定性模式下把 PID 置空（`pid_redacted_for_determinism`）。
- 确定性来源：`--fixed-timestamps`（sampler 时间戳由固定基准派生，`gmtime` 与本地时区无关）+
  `write_own_state` 的 `updated_at` 改为 `setdefault`（调用方可给固定值）+
  `verified_emergency_termination(clock=…)` 可注入 +
  `--assemble-manifest-only --fixed-timestamps` 固定 manifest 的 `at`。

---

## 8. 仍未验证清单（U1–U8 更新）

| # | 状态 | 说明 |
|---|---|---|
| **U1** | 机制已就绪、**仍未见真机** | `verified_emergency_termination` 现在**有演练入口**（`--drill --ws-hard-stop-mb`），且该路径已被 T15 在无 COMSOL 条件下走通（含触发分类、drill 标记、信号落点、拒绝/自退分支）。**真实 COMSOL 下的全路径仍未实测**（由父 agent 跑演练） |
| U2 | 仍未见真机 | 对**真实 `comsolmphserver`** 的 `Stop-Process` 未执行（对自建替身已实测通过，T1/T7）；是否需要 `/T` 树状终止仍未验证 |
| U3 | 仍未见真机 | 真实 `study.run()` 阻塞期间被终止后 COMSOL 的行为（报什么错、worker 如何退出、端口是否释放）未实测 |
| U4 | 仍未见真机 | LT2-C 从未在真实 `fin` 几何上跑过；`tolerance_evidence` 从未用真实面积/bbox 填过 |
| U5 | 仍未见真机 | 「每组合一个全新进程 ⇒ 全新 `mph.Client`」未在真机证实（演练会顺带验证） |
| U6 | 部分覆盖 | 真实 5 s 计时下的停更仍未实测；`--gate-poll 3` 与 `--interval 5` 的真实配合由演练检验 |
| **U7** | 仍未见真机 | `server_pid_from_port()` 对真实 `comsolmphserver` 的端口归属取值、`parent_is_worker` 父子关系判断——**演练会首次验证** |
| **U8** | 仍未见真机 | 真实 `checkpoint.json` 的 `tolerance_evidence` 数值——仍为空 |
| **U9（新）** | 已测但需真机确认 | 演练中 `hard_stop` 触发时 `study.run()` 抛什么异常、worker 是否走 `finally` 正常收尾、`sampler_returncode` 是否为 0 |
| **U10（新）** | 未测 | 演练阈值取多少才能**稳定**在 solve 期间触发（取决于本机真实 WS 曲线）；建议先用 5000，若过晚再降到 3000 |

## 9. 已知风险

| # | 风险 |
|---|---|
| R1 | `LT2 生产` 仍 **BLOCKED**：双 16,384 MB 前置门禁 + 页面文件授权状态由父 agent 维护；本轮未碰页面文件 |
| R2 | `rt_gate.py`/`tests_rt_gate.py` 由父 agent 维护，本文哈希须标注引用时刻（13:23:52） |
| R3 | 演练 run 的产物带 `drill: true`，但**必须靠人/脚本过滤**——分析脚本若忽略该字段仍可能误用。`DRILL_README.txt` 是显式告警，但不构成技术阻断 |
| R4 | `resource_hard_stop` 的正向判据依赖 `reasons` 文本模式匹配（`ws_hard_stop(` 等）。若 `rt_gate` 改了 reason 文案，该匹配会失配 ⇒ 退化为 `unclassified_failure`（fail-closed，不会误判为资源硬停）。**建议 Codex 考虑把 reason 结构化为字段** |
| R5 | 自动重跑分类仍是启发式（阶段/错误串）；`unclassified` 一律 fail-closed 不重跑 |
| R6 | 冒烟测试的「正常路径」用 `safe` 剖面，只验证**接线**，不代表真实资源的判据行为 |
