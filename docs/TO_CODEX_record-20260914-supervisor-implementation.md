# TO CODEX — LT2 生产 runner（含实时 supervisor）实现记录

> ⚠️ **本文第 1 节的哈希与第 2/3 节的部分结论已被取代**（append-only，不覆盖原文）：
> Codex 二审提出 2 个 P0 + 2 个 P1，修复与新证据见
> `docs\TO_CODEX_record-20260914-supervisor-p0-fixes.md`。
> 本文保留为第一轮实现的历史记录；**U1 的措辞应以新文档为准**（`verified_emergency_termination` 路径）。

- 日期：2026-09-14
- 范围：**只写代码 + 静态/干跑验证**。本次**未运行任何 COMSOL 求解**（现场核验：2036 端口监听 0 个、`comsolmphserver` 进程 0 个、`comsolbatch` 进程 0 个）。
- 性质：交实现，并**上报一个会阻塞 LT2 开跑的裁定冲突**（见第 5 节）。

---

## 1. 实现清单

| 交付物 | 路径 | 字节 | sha256 |
|---|---|---|---|
| sidecar 采样器（运行期实时判定） | `work\tools\lt2_sampler.py` | 10,594 | `cf4b0690b26504a34dc29942c98936da61ed5055d72c9ef2d4e47bc09dfa8868` |
| 生产 runner（supervisor + combo-worker） | `work\tools\lt2_production.py` | 62,503 | `5b311deb1ade1ea4754e161c7cf541f35261f23f1e6179c195a778cc8149192f` |
| 复用的门禁引擎（**未改动**） | `work\tools\rt_gate.py` | 9,466 | `e99e76b76db1cd413ec5961c5dbca8379bd4a03ced4ddb24b2fd1c303cf3f5db` |
| 复用的门禁测试（**未改动**） | `work\tools\tests_rt_gate.py` | 9,455 | `d15dddc0d9c33c3e52c7a76542927607ccd80476f749caade2f56f849ae6febc` |

未改动：`AGENTS.md`、`WORKING_PLAN.md`、`lt2r0_v2.py`、`rt_gate.py`、`tests_rt_gate.py`（`lt2r0_v2.py` mtime 仍为 2026-09-14 09:16:32）。

### 1.1 架构：为什么是三个进程

实测已知约束：**MPh 一个 Python 会话只能有一个 `mph.Client`**（`disconnect()` 后再 `mph.Client()` 报
`Not connected to a server`）。而授权要求「**每个组合一个全新 server**」（`server_lifecycle_size = 1`）。
二者无法在同一进程内同时满足，故：

```text
supervisor（--role supervisor，不 import mph，只编排与核验）
  └─ combo-worker（--role combo-worker，每组合一个全新进程 → 一个全新 client/server）
       └─ sampler（lt2_sampler.py，独立 sidecar，运行期实时判定）
```

这是**被实测约束逼出来的**结构，不是设计偏好；如 Codex 认为可以放宽「每组合新 server」，则可退回单进程。

### 1.2 取消路径的归属（D2 的修正）

求解期主线程阻塞在 `study.run()`，无法轮询。因此：

1. **worker 进程内 watchdog 线程**每 `--gate-poll`（默认 2.5 s）读 `sampler_state.json`
   + `sidecar_health`，判定 `cancel_current` 即动作；
2. 取消顺序：`client.clear()`/`disconnect()` **优雅取消优先**；
3. 优雅取消宽限 10 s 后端口仍开 → 才终止 server，且**必须通过三重核验**：
   PID 一致 + 启动时间（`StartTime.ToFileTime()`）一致 + 端口归属（`port_owner_ok`）；
4. 核验不过 → **拒绝终止**并在 `cancel_record.terminated` 写 `REFUSED_identity_or_ownership_check_failed`；
5. supervisor 只在 worker 失联（硬线持续 >20 s 且进程仍在）时**升级**处置，同一套核验后才动手；
   worker 仍存活 30 s → 终止该 worker 进程（由本 supervisor 拉起，PID 无歧义）。

软线只阻止**下一组合**（`GateEngine.blocks_next_combination()`），不取消当前组合。

### 1.3 缺陷 D1 / D3 的落实

- **D1（commit 项被漏）**：`combo_pass_conditions()` 与批次级 `aggregate_pass_conditions` **都含 commit 项**：
  `commit_hard_stop_samples_0`、`min_commit_gt_4096`（阈值取自 `rt_gate.Thresholds`，未自行放宽）。
  另有 `commit_hard_stop_samples` / `commit_warning_samples` 计数入时序摘要。
- **D3（事件被截断藏量级）**：`resource_timeline.jsonl` 写**完整**事件流；
  报告侧同时给出 `stop_line_event_count`（总数）、`stop_line_events_head40`（前 40 条）、
  `stop_line_events_truncated_in_report`（被摘要省略的条数）与
  `stop_line_events_file_sha256`（完整文件哈希）。

### 1.4 溯源字段

- 判据哈希**只从** `work\runs\lt1-reverse-sample\lt1_validation_summary_v2.json` 读
  （`invariant_criteria_hash` = `a392cb28…`、`sweep_spec_hash` = `4f20ec67…`，并记录来源文件 sha256）；
  文件缺失或字段为空 ⇒ 抛异常拒跑，**不自行重算一套**。
- 控制面冻结签名**只从** `work\runs\precheck-b2-phase2-v5-aggregate\geometry_selection_precheck.json`
  按 `(x_scale, N_w_te1)` 取值（面积 + bbox + `intop5/swr1/efc1` 实体），并记录来源 sha256。
- 每行含 `source_run_id` 与 `source_artifact_sha256`（= 该组合 `<combo>_raw_rows.csv` 的 sha256，
  避免"文件哈希含自身"的自指问题）；每个 child checkpoint 含模型/脚本/sampler/判据/冻结签名哈希。
- checkpoint **先原子写、再关 server**；写失败抛异常（不允许静默）。

### 1.5 run-id 防呆（append-only 的硬保护，不再靠君子协定）

`--run-id` 现在有两道守卫（`run_id_reuse_guard()` / `validate_run_id()`，退出码 **4**）：

1. **路径合法性**：拒绝空值、`/` `\` `:` `*` `?` `"` `<` `>` `|`、`..`、首尾空白、超长，
   并校验 `resolve()` 后仍落在 `work\runs\` 之内（防止产物写到运行区之外）。
2. **复用防护（默认拒绝）**：若 `work\runs\<run-id>\` **已存在且非空**，**拒绝启动**并打印既有条目及其数量；
   仅显式传 `--force-reuse-run-id` 才放行，且放行时打印 `[WARN]` 并把
   `action = forced_reuse_nonempty` 写进产物（`run_id_guard` 字段）。

   *理由*：既有产物代表已经发生过的运行，覆盖即违反 append-only 红线；此前"换新 run-id"只写在文档里。

3. **`--dry-run` 的 run-id 唯一化**：省略 `--run-id` 时自动生成
   `lt2-dryrun-<YYYYmmdd-HHMMSS>-pid<pid>`（时间戳 + pid），使连续两次干跑不会互相踩。
   非 `--dry-run` 场景仍**必须**显式给 `--run-id`（否则 exit 3）。

   注意：`combo-worker` 角色**跳过**该守卫——它的 run 目录由 supervisor 先建成，
   否则 worker 会被自己刚建好的目录拦下。

---

## 2. 静态与干跑验证（实测输出）

### 2.1 `py_compile`

`lt2_sampler.py`、`lt2_production.py` → exit 0。

### 2.2 `rt_gate` 测试

```text
python work/tools/tests_rt_gate.py   → exit 0
合计 33 项，通过 33，失败 0
```

⚠️ **`rt_gate.py` / `tests_rt_gate.py` 的哈希不是稳定常量**：这两个文件由**父 agent 维护**。
本次会话中父 agent 于 12:24:18 / 12:24:21 改写了它们（把 `warnings_seen` 由「按数值累积」改为
「按类型去重 + 计数」，并新增 T9 三项断言），测试数由 **30 → 33**。
改写前我跑出 30/30，改写后复跑 33/33。

📌 **更正**：早前我把这次改写描述成「工作区存在第三方并发写入者」。**该判断错误**——
父 agent 已澄清那两次改写是**其本人**所为。不存在第三方写入者，此更正据此记录。
本文 sha256 对应改写后的内容，并在 12:24:52 与 12:24:58 两次采样一致。
`rt_gate.Thresholds` 的 5 个默认值经核对未变（11500 / 12288 / 4096 / 6144 / 4096）。
→ 引用这两个文件的哈希时请标注「引用时刻」，不要当作稳定常量；详见第 7 节。

### 2.3 `--preflight-only`（只读探测，不启动 COMSOL）

```json
{"at": "2026-09-14T12:24:15", "port_free": true, "other_server_pid": null,
 "system_available_physical_mb": 9439.2, "system_memory_load_percent": 70,
 "commit_available_mb": 3154.8,
 "gates": {"physical_avail_gate_mb": 16384.0, "commit_gate_mb": 13500.0},
 "gate_overridden": false, "gate_pass": false}
exit = 5
```

（当刻机器负载 70%，两个门禁都不满足。这不是代码问题，是**门禁值与机器实际能力的关系问题**，见第 5 节。）

### 2.4 `--dry-run`（模拟样本驱动**同一份**门禁与状态机，不启动 server）

```text
DRY-RUN: all_scenarios_passed = true, exit = 0
normal_headroom        ok=8  warning=0 hard_stop=0  首次取消=None      投递下一组合=true
ws_hard_stop           ok=6  warning=1 hard_stop=1  首次取消=gate_engine 投递下一组合=false
soft_only              ok=0  warning=8 hard_stop=0  首次取消=None      投递下一组合=false
r0_v2_measured_replay  ok=6  warning=1 hard_stop=33 首次取消=gate_engine 投递下一组合=false
```

四个场景各自验证了一条规则：正常放行 / 硬线取消当前组合 / 软线只阻止下一组合 /
**用真实实测样本回放**。干跑同时走了 `atomic_write_json` checkpoint 写盘路径（全部 `ok`）。

`r0_v2_measured_replay` 读的是 `lt2-resource-calibration-x080-n02-v2\resource_timeline.csv`
（**真实实测**，只读，不跑 COMSOL），首次取消原因为：

```json
{"sample_index": 8, "reason": ["commit_hard_stop(747.1 <= 4096.0 x2)"], "source": "gate_engine"}
```

即 **commit 硬线**（不是 WS、不是可用物理内存）触发了取消。这条不是合成数据，是 R0 v2 的真实测量值。

### 2.5 `lt2_sampler.py --simulate`（走同一套判定与写盘路径）

```text
exit = 0
resource_timeline.jsonl 行数 = 12（完整事件流，未截断）
resource_timeline.csv  行数 = 12，列 = R0 的 COLS（逐列一致）
sampler_state.json 键 = combo, counters, last_sample_ts, pid, reasons,
                       sample_index, stage, stop, verdict, warnings
首个 hard_stop 样本 = #4，原因 ['commit_hard_stop(2000.0 <= 4096.0 x2)']（验证"连续两个采样"规则）
```

### 2.6 CLI 防呆

```text
--batch-size 12 → [STOP] 批大小 12 被授权明令禁止（禁止 12–16），exit 3
--batch-size 5  → [STOP] 批大小 5 不在授权集合 (4, 6, 8)，exit 3
```

### 2.7 验收条件的功能校验（证明 D1 是**功能**修复，不是只加了个键）

直接调用 `combo_pass_conditions()` 做四个场景（临时脚本跑完即删）：

| 场景 | 输入 | 结果 |
|---|---|---|
| A 全达标 | commit min 12,000 | 10 项全 True，`all_pass = True` → 条件**不是**恒假 |
| B 代入 R0 v2 真实实测 | commit min 647.3，硬线样本 145 | **只有** `commit_hard_stop_samples_0` 与 `min_commit_gt_4096` 为 False，其余 8 项全 True → `all_pass = False` |
| C watchdog 取消过 | `cancel_record` 非空 | `no_cancel_triggered = False` → 不通过 |
| D LT2-C 未过 | `checks.pass = False` | `lt2c_quick_gate_pass = False` → 不通过 |

场景 B 是关键：用**真实实测值**代入时，唯一拦住验收的就是 commit 两项——
即 R0 那次"自报 PASS"的情形在本实现下**不会再被判通过**（缺陷 D1 已闭环）。
combo 级与批次级验收条件中均含这两个 commit 键（已核验）。

### 2.8 run-id 复用防护自测（第 1.5 节的守卫）

| 用例 | 命令要点 | 期望 | 实测 |
|---|---|---|---|
| C1 新 run-id | `--dry-run`（省略 `--run-id`） | 自动唯一值 + exit 0 | 生成 `lt2-dryrun-20260914-122735-pid44648`，四场景全过，**exit 0** |
| C2 已存在且非空 | `--run-id lt2-prod-b2-r1 --dry-run` | **拒启，非零** | 打印既有条目 `['dryrun','preflight_only.json']`（2 个），**exit 4** |
| C3 强制复用 | 同行 + `--force-reuse-run-id` | 放行 | 打印 `[WARN]`，**exit 0**，报告 `run_id_guard.action = forced_reuse_nonempty` |
| C4 非法 run-id | `--run-id '..\evil'` / `'a/b'` | 拒启，非零 | 列出非法原因，**exit 4** |
| C5 已存在但为空 | 先建空目录再 `--dry-run` | 放行 | **exit 0**（`action = use_existing_empty`） |
| C6 非 dry-run 缺 run-id | `--preflight-only`（无 `--run-id`） | 拒启，非零 | **exit 3** |

守卫判定同时写入产物 `run_id_guard` 字段（dry-run 报告与 supervisor 结果均有），
因此"这次是否复用了旧目录"事后可查。

**本轮自测的 COMSOL 现场核验**：2036 监听 = 0、`comsolmphserver` = 0、`comsolbatch` = 0；
dry-run 报告 `mph_imported = False`、`server_started = False`。

---

## 3. 未验证（诚实清单）

| # | 未验证项 | 为什么没验证 | 影响 |
|---|---|---|---|
| U1 | **真实 COMSOL 下的硬线取消路径**（watchdog → `client.clear()`/`disconnect()` → 端口关闭） | 本次禁止运行 COMSOL | 未知 MPh 在 `study.run()` 阻塞期间被另一线程调 `clear()` 的实际行为；不排除需要走到"终止 server"这一档 |
| U2 | 终止 server 的 `Stop-Process` 分支 | 同上（且会真杀进程） | 三重核验逻辑本身是纯函数、已被覆盖；但真机终止未执行 |
| U3 | supervisor 升级路径（worker 失联 → 核验 → 终止） | 同上 | 同上 |
| U4 | `LT2-C 快速门禁`在真实模型上的取值（`pot1/pot2/gnd1` 非空、交集 0、`intop5==swr1==efc1`、area/bbox 对冻结值） | 同上 | 已按授权写法实现并复用 `geometry_selection_precheck` 的函数；但**未在真实 `fin` 几何上跑过一次**。门禁是 **fail-closed**：任何一项取不到证据（None）即判不通过 |
| U5 | 「每组合一个全新进程 ⇒ 全新 `mph.Client`」是否真的绕开单 client 约束 | 同上 | 这是架构的关键假设，只有真机能证 |
| U6 | `--simulate` 不是真实计时下的采样节奏（真实为 5 s/样本、15 s 停更判定） | 模拟样本瞬时产出 | 停更检测靠 `tests_rt_gate.py` 的 T2 覆盖 |

## 4. 已知风险

| # | 风险 | 说明 |
|---|---|---|
| R1 | **两个 commit 门禁数字互斥，LT2 实际无法开跑** | 详见第 5 节。这是**阻塞项**，不是实现缺陷 |
| R2 | **`rt_gate.py`/`tests_rt_gate.py` 由父 agent 维护，哈希随时可变更** | 12:24 父 agent 本人改写了这两个文件（30→33 项测试）。**不存在第三方写入者**（早前的"并发写入者"判断已更正）。引用这两个文件的哈希必须标注引用时刻，见第 7 节 |
| R3 | 控制面比对容差是本文件自定 | `AREA_REL_TOL = BBOX_REL_TOL = 1e-6`，**不是授权给的数字**；我选择它的理由是几何是确定性的、期望重合到浮点噪声级。已在 checkpoint 的 `lt2c_quick_gate.area_rel_tol/bbox_rel_tol` 里留痕 |
| R4 | `work\runs\lt2-prod-b2-r1\` 当前只有模拟/预检产物 | 已由新的 run-id 复用防护**硬拦截**（默认拒绝写入非空 run 目录，exit 4）；真实生产换新 `--run-id` 即可。所有模拟产物带 `simulated: true` + `dryrun\README.txt` 警示 |
| R5 | 求解失败的组合不会自动重跑 | 当前实现是"失败即 blocked 并停止投递"（比授权更保守）。授权说"失败只重跑失败组合"——重跑策略需 Codex 确认由谁触发 |
| R6 | `--force-reuse-run-id` 会放行覆盖既有产物 | 这是**显式**逃生阀，会打印 `[WARN]` 并在产物 `run_id_guard` 里留痕（`action = forced_reuse_nonempty`）。不是静默行为，但用之前应确认既有产物已归档 |

---

## 5. 阻塞项：两个 commit 门禁数字互斥（需 Codex 裁定）

授权给了两个 commit 相关数字，实测显示**它们同时成立时 LT2 一个组合都跑不完**：

**（a）前置门禁 `commit ≥ 13,500 MB` —— 本机从未达到过。**

| 证据 | 值 |
|---|---|
| R0 v2 前置门禁实测 | `commit_available_mb = 10,825.1`（< 13,500）→ **该门禁当时就会失败** |
| R0 v2 全程 159 个采样 | `commit_available_mb` min 647.3 / **max 11,294.9**；**> 13,500 的采样数 = 0** |
| 本次 `--preflight-only`（12:24:15） | 3,154.8 |
| 本机 commit limit 与空闲已提交量 | 37,055.6 MB − 25,296 MB = 11,760 MB（**理论上限**，仍 < 13,500） |

同理可用物理内存门禁 `≥16,384 MB`：R0 v2 全程 159 个采样中**只有 2 个**满足（都在 server 起来之前的启动段）。

**（b）运行期硬线 `commit ≤ 4,096 MB`（连续 2 个采样）—— 本机几乎全程满足。**

R0 v2 实测运行期 commit 在 **647.3 – 1,300 MB** 区间（159 个采样中 145 个 ≤1,024 MB）。
真实样本回放干跑给出 **33/40 个 hard_stop**，首次取消发生在第 8 个采样：

```text
commit_hard_stop(747.1 <= 4096.0 x2)
```

**结论**：commit 的**下限要求达不到**（前置永远失败），**上限又在运行期必然被穿越**（每组合都会被取消）。
两个数字都来自授权，我**没有改动任何一个**（`rt_gate.Thresholds` 原样复用；前置门禁走 CLI 默认值）。
但按现状 LT2 无法产出任何一行合格数据。这与本会话早前已上报的机制一致：
本机 commit 的天花板由**页面文件只分配 4,873 MB** 决定，空闲提交量已达 25.3 GB。

### 需要 Codex 裁定

- **Q1** `commit ≥ 13,500 MB` 这个前置门禁值从何而来？是否应改（或删除）？（本机观测上限 11,294.9 / 理论 11,760）
- **Q2** 运行期 `commit ≤ 4,096 MB` 硬线是否应按本机实测重新标定？否则每个组合都会在求解开始后约 10 s 被取消。
- **Q3** 是否采纳「先调大页面文件抬高 commit limit」（系统级改动，需用户同意，可能要重启）——这是让两个门禁都变得**有意义**的唯一廉价办法。
- **Q4** R5 的重跑策略由谁触发？

---

## 6. 状态用词

```text
LT2 runner 实现        = DONE_CODE_ONLY（静态 + 干跑通过；真实 COMSOL 未跑）
LT2 实时中止机制        = IMPLEMENTED_NOT_LIVE_TESTED（U1–U3）
LT2 生产开跑            = BLOCKED（第 5 节：commit 两个门禁互斥）
```

---

## 7. 本文件哈希失效条件

本文引用的 sha256 **不是永久常量**。引用前请按下列条件判断是否仍然有效：

| 文件 | 维护者 | 失效条件 | 建议标注方式 |
|---|---|---|---|
| `work\tools\lt2_sampler.py` | 本 agent（子 agent） | 任何后续编辑 | 「截至 2026-09-14 12:2x，sha256 = …」 |
| `work\tools\lt2_production.py` | 本 agent（子 agent） | 任何后续编辑（含第 1.5 节守卫的后续调整） | 同上 |
| `work\tools\rt_gate.py` | **父 agent** | 父 agent 任何编辑 | **必须标注引用时刻**；不要当作稳定常量 |
| `work\tools\tests_rt_gate.py` | **父 agent** | 父 agent 任何编辑（测试数量会随之变化） | 同上，并同时标注当时的用例数 |

**已发生的一次失效**：本会话 12:24:18 / 12:24:21 父 agent 改写了 `rt_gate.py` / `tests_rt_gate.py`
（`warnings_seen` 语义由「按数值累积」改为「按类型去重 + 计数」+ 新增 T9），
测试数 30 → 33。**本文第 1 节表格中的哈希与第 2.2 节的 33/33 均为改写后取值**
（12:24:52 与 12:24:58 两次采样一致）。

**复算方法**（任何人可独立核验）：

```powershell
python -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path(r'work\tools\rt_gate.py').read_bytes()).hexdigest())"
```

**另需注意**：`rt_gate.Thresholds` 的默认阈值若被改动，LT2 的门禁口径即改变。
本文记录核对时刻的值为 `ws_warning 11500 / ws_hard_stop 12288 / physical_avail_hard_stop 4096 /
commit_warning 6144 / commit_hard_stop 4096 / consecutive_samples 2 / gap_limit_s 15`。
运行期写入的每个 checkpoint 都带 `thresholds` 快照（`GateEngine.th.to_dict()`），
因此**即使阈值后来被改，历史产物的口径仍可追溯**。
