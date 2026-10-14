# 裁定记录（append-only）第三轮 — 页面文件生效证实、G1–G3 关闭、资源确认启动

- 日期：2026-09-14
- 前置：`docs\TO_CODEX_record-20260914-r2-p0-and-pagefile-not-effective.md`（本文件为 append-only 续篇，不覆盖）
- 来源裁定：`TO_DEEPSEEK_HARNESS_页面文件授权与实时门禁复核回复.md`
  sha256 `0c5181a6d9e1f5be6eebf467b6b05ed08ebc529e726cd8410a5c2274bf9c322b`

---

## 1. 页面文件变更**已生效**（含一次失败尝试的诊断）

### 1.1 第一次「重启」未生效的诊断（已定位并在 §1.2 证实）

用户第一次告知「已完成重启」后，我按承诺复核，发现**未生效**：

```text
LastBootUpTime = 2026-09-12 15:02:59（已运行 45.6 小时）
近 24h 内核启动事件 = 0 条
设置侧已登记：AutomaticManagedPagefile=False、初始/最大 12288/12288
但 AllocatedBaseSize = 4,873 MB、commit limit = 37,063.0 MB（均未变）
HiberbootEnabled = 1   ← 快速启动开启
```

**根因**：快速启动开启时，**「关机」再开机是从休眠恢复内核会话**，`LastBootUpTime` 不变，
页面文件的重新分配也不会发生。→ 需要的是**「重启」**（开始 → 电源 → 重新启动），
即使开着快速启动也会走完整引导。我把该诊断回报用户后，用户执行了真正的重启。

### 1.2 第二次重启后实测（生效）

```text
LastBootUpTime = 2026-09-14 13:01:54（已运行 0.0 小时）→ 确为真实重启
AutomaticManagedPagefile = False        ✓
Win32_PageFileUsage.AllocatedBaseSize = 12,288 MB（变更前 4,873）✓
Win32_PageFileSetting 初始/最大 = 12288 / 12288 MB  ✓
C 盘可用 = 188.6 GB（变更前 195.2；减少约 6.6 GB，与页面文件扩张一致）✓
```

**提交限制（核心判据）——我的预测被精确证实**：

| 项 | 变更前 | 我的预测 | 实测 |
|---|---|---|---|
| commit limit | 37,063.0 MB | **44,478 MB** | **44,477.4 MB** |

预测依据在被验证前是推导而非事实：变更前实测 `limit 37,063 = RAM 32,190 + 页面文件 4,873`，
故预测 `32,190 + 12,288 = 44,478`。**实测 44,477.4 MB，与预测差 0.6 MB（相对误差 1.4e-5）**
→ 该测量模型（commit limit = 物理内存 + 页面文件分配）成立，后续可据此推算。

### 1.3 干净启动下的资源余量（与变更前对比）

| 指标 | 变更前（负载中） | 本次（刚重启） |
|---|---|---|
| committed bytes | 25,296 → 31,899.7 MB | **10,721.7 MB** |
| commit 可用 | 11,759.6 → 5,163 MB | **33,755.6 MB** |
| 物理可用 | 16,948 → 9,793 MB | **22,356.0 MB** |

→ Codex §3.3 的回退前置门禁（commit ≥16,384 **且** 物理可用 ≥16,384）在**当前干净状态下达标**
（33,755.6 / 22,356.0）。这也说明该门禁能否通过**强依赖背景负载**，与 §3.2 的更正一致
（「当前负载下的可用量」不是不变上限）。

---

## 2. G1–G3 关闭（我逐项复核）

实现方在收到我的缺口清单后于 12:54–13:00 更新了三个脚本。**我的独立复核**：

| 脚本 | 字节 | sha256(前16) |
|---|---|---|
| `work\tools\lt2_production.py` | 93,747 | `e1385e4e6e39c688` |
| `work\tools\lt2_sampler.py` | 12,119 | `9b772568d0e90fa2` |
| `work\tools\tests_lt2_supervisor.py` | 29,186 | `a5de4f2885ea64b9` |

> 哈希按**引用时刻 2026-09-14 13:05** 标注，不当作稳定常量。

### 2.1 G1 关闭：固定时间戳模式**逐字节可复现**（我亲自验证）

我执行了此前要求的关键验证——**同一命令连跑两次，产物是否逐字节一致**：

```text
命令: python work/tools/tests_lt2_supervisor.py --fixed-timestamps
第 1 次: exit=0 | 快照 35 个文件
第 2 次: exit=0 | 快照 35 个文件
比对: 相同 35 项 | 不同 0 项 | 仅单侧存在 0 项
结论: 固定模式下可复现（逐字节一致）
```

`batch_manifest.json` 中 `clock_mode: "fixed"`、`at: "2026-09-14T04:00:00"` 佐证固定时钟生效。
→ Codex §10.B 要求的「目录树 + 各时间线 SHA256」现在**第三方可复算**，G1 关闭。
（默认模式仍用墙钟，属不可复现，已按我的要求在证据中标注 `clock_mode`。）

### 2.2 G2 关闭：`batch_manifest.json` 已真实产出

`work\runs\lt2-supervisor-selftest\batch_manifest.json` 现存在，顶层键含：

```text
run_id, role=manifest-assembly, at, clock_mode=fixed, assembled_read_only=true,
mph_imported=false, comsol_started=false,
child_file_spec, child_file_spec_note, child_required_by_kind,
child_count, children_satisfy_inventory
```

并新增 `--assemble-manifest-only` 子命令（只读扫描 `child_*_attempt_*` 并写批次根 manifest，
不启动 server、不 import mph）→ 该写入路径**已被真实触发**，G2 关闭。

### 2.3 G3 关闭：child 文件规格与「按类型必需」已显式声明

manifest 现在自带 `child_file_spec`（逐文件说明哪个角色独占写、内容是什么）、
`child_required_by_kind`（按 child 类型声明必需文件）与 `children_satisfy_inventory`（是否满足清单）。
→ 「哪些文件应当存在、缺失是否合法」从隐含约定变成**产物内的可核验声明**，G3 关闭。
`child_03_attempt_2` 也已补齐 `worker_state.json`（此前缺该文件）。

---

## 3. 已启动：`(0.8,2)` 页面文件后资源确认（裁定 §9 步骤 10）

```text
命令: python work/tools/lt2_production.py
        --run-id lt2-resource-confirm-x080-n02-postpagefile
        --combos '[[0.8,2]]' --freqs '5 10 15 20 25 30 35' --max-combos 1
前置门禁: avail >= 16,384 MB 且 commit >= 16,384 MB（当前 22,356 / 33,755.6 → 通过）
性质: 真实 COMSOL 求解（后台作业 pwsh-1），单组合 7 频点，单 server 生命周期
```

该次预期同时验证：

- **U5（架构关键假设）**：每组合一个全新 combo-worker 进程 ⇒ 全新 `mph.Client`
  是否真绕开「MPh 单会话单 client」约束；
- **U7**：`server_pid_from_port()` 对真实 `comsolmphserver` 的端口归属取值、
  `parent_is_worker` 在真实 MPh 启动链上的取值；
- **commit 余量**：页面文件生效后运行期最低 commit 是否显著高于 4,096 MB 硬线
  （变更前运行期为 647–1,300 MB，必须触发硬停）；
- **U4 部分**：LT2-C 快速门禁与 `tolerance_evidence` 首次在真实 `fin` 几何上取值。

**尚未启动、需用户放行**：

```text
真实 COMSOL 硬停演练（U1/U2/U3）
  —— 必须用「安全、早触发的模拟门禁」或「可快速取消的小模型」，
     禁止通过把真实机器内存压到危险水平来触发（裁定 §8）
  —— 该演练不在本次资源确认内，需单独放行
```

---

## 4. 状态

```text
pagefile_change                     = EFFECTIVE（commit limit 44,477.4 MB，实测已证实）
LT2-P0-1                            = IMPLEMENTED_AND_FAULT_INJECTION_TESTED（真机路径本次资源确认开始覆盖）
LT2-P0-2 / P1-a / P1-b              = DONE
G1 / G2 / G3                        = CLOSED（G1 由我连跑两次逐字节一致证实）
§8 七项测试                          = 29/29 exit 0，且产物在固定模式下可第三方复算
(0.8,2) 页面文件后资源确认           = RUNNING（run-id lt2-resource-confirm-x080-n02-postpagefile）
真实 COMSOL 硬停演练（U1/U2/U3）     = NOT_STARTED（待用户放行）
LT2 production                      = BLOCKED_BEFORE_PRODUCTION（首个逻辑批仍未启动）
```

---

## 5. 资源确认**失败**：P0-2/G3 修复引入阻断级回归（2026-09-14 13:04，实测）

上述资源确认作业以 **exit code 1** 结束。**它失败的原因不是资源不足**，必须如实区分——
否则会被误读成「页面文件改了还是不够」。

### 5.1 现场证据

```text
supervisor 最终输出:
  status = BLOCKED_OR_LIMITED
  blocked_reason = child_00_not_pass:worker_failed（不可自动重跑：resource_hard_stop）
  aggregate_pass_conditions: commit_hard_stop_samples_0 = false, min_commit_gt_4096 = false,
                             no_cancel_triggered = false, all_timelines_preserved = false

child_00_attempt_1/ 实际内容: 仅 hard_stop_trigger.json + supervisor_signal.json
                              （无 resource_timeline.*、无 sampler_state、无 checkpoint）
child_00_attempt_1_refused.json:
  {"reason": "child_dir_exists_nonempty", "note": "拒绝复用非空 child 目录（append-only）"}
hard_stop_trigger.json:
  decided.action = hard_stop_enforce, decided.source = sidecar_health,
  decided.reason = ["sidecar_exited"], sampler_state = {verdict:null, reasons:null,
  sample_index:null, last_sample_ts:null}   ← 全为 null
supervisor_signal.json: writer = lt2_supervisor, request = graceful_worker_end,
  时间戳 2026-09-14T13:04:51（与拒绝时刻同一秒）
```

### 5.2 因果链

1. supervisor 在拉起 worker **之前/同时**把 `supervisor_signal.json` 写进了 `child_00_attempt_1/`；
2. worker 启动后执行新加的 append-only 守卫「child 目录非空则拒绝复用」→ **拒绝并立即退出**
   （`child_dir_exists_nonempty`）；
3. 因此**从未启动 COMSOL server**，采样器也没产出任何样本，时间线为空；
4. supervisor 见 sidecar 无样本/已退出 → 判 `sidecar_exited` → `hard_stop_enforce`；
5. `classify_retry()` 把它归为 `resource_hard_stop`（不可重跑）→ 批次 BLOCKED。

### 5.3 三个缺陷

- **D-A（阻断级）**：supervisor 预写 child 目录 与 worker 的「非空即拒绝」守卫**互斥**，
  worker 永远起不来。两个机制自相矛盾。修法：把 supervisor 信号移出 child 目录
  （child 目录只放证据），或守卫改白名单，或显式 fresh 令牌；规则必须唯一并写进 manifest。
- **D-B（严重）**：**基础设施故障被误分类为 `resource_hard_stop`**。
  `resource_hard_stop` 只应在「活的 sidecar 真的产出连续 2 个越线样本」时成立；
  「sidecar 在首个样本之前退出」不得推导为资源硬停。否则基础设施 bug 会被伪装成资源问题，
  在真实生产中**掩盖**同类 bug。
- **D-C（重要）**：`hard_stop_trigger.json` 允许在 `sampler_state` 全为 null 时记为硬停；
  触发记录必须区分 `threshold_crossed`（含越线样本/阈值/连续次数）与
  `no_samples_observed` / `integrity_failure`。**没有越线样本时不得称 hard stop。**

### 5.4 对结论的影响（重要）

- 本次运行**没有产生任何 post-pagefile 资源数据**（连 server 都没启动），
  因此 §1.3 之后关于「调整后运行期 commit 最低值」的预测**既未被证实、也未被推翻**，
  目前仍是**未验证的预测**。不得据此声称「页面文件调整无效」或「资源仍不够」。
- §8 的 29 项故障注入测试**没有覆盖**「supervisor 拉起 worker → worker 接受自己的 child 目录 →
  sampler 产出时间线」这条最基本链路，所以该回归漏网。已要求补 5 项无 COMSOL 的接线冒烟测试
  （正常路径产物齐备、信号文件不在 child 目录、正常路径不得被分类为 resource_hard_stop、
  反向用例：无样本退出不得是 resource_hard_stop、固定模式下连跑两次哈希一致）。
- 修复后需**重跑**资源确认（换新 run-id）。当前机器刚重启、内存干净，宜尽快重跑。

### 5.5 状态更新

```text
(0.8,2) 页面文件后资源确认 = FAILED_DUE_TO_INFRA_REGRESSION（非资源原因；无资源数据）
post-pagefile 运行期 commit 余量 = UNTESTED_PREDICTION（预测：干净启动下最低约 22.6 GB）
G1/G2/G3                  = CLOSED（但 G3 的守卫实现引入了 D-A，需修正后重新关闭）
真实 COMSOL 硬停演练        = NOT_STARTED（待用户放行）
LT2 production            = BLOCKED_BEFORE_PRODUCTION
```

---

## 6. D-A/D-B/D-C 修复与 `--drill` 就绪（2026-09-14 13:24，父代理核验）

### 6.1 D-A 的真实根因比我诊断的更深一层（接受实现方的更准确诊断）

我先前诊断为「supervisor 预写 child 目录 与 worker 非空守卫互斥」。实现方进一步定位到
**启动竞态**，我核验其逻辑成立且能完整解释我观测到的现象：

```text
supervisor Popen(worker) 后立刻开始监督
  -> worker 尚在 import numpy/mph，worker_state.json 尚不存在
  -> proc_exists(None) = False
  -> rt_gate.sidecar_health 因 not proc_alive 优先，直接返回 sidecar_exited
  -> 第一节拍即判 hard_stop
  -> 往 child 目录写 termination_trigger + signal
  -> worker 这时才启动，撞上 append-only 守卫 -> 拒绝退出
```

这正是我看到的「`sampler_state` 四项全 null + `source=sidecar_health` + 拒绝与信号同一秒」。
**我的诊断只到「互斥」，未到「竞态」这一步**，接受更正。

修法（唯一规则、一处声明）：信号移到 `<run_id>/signals/<child_dir_name>.signal.json`，
child 目录只放证据；新增 `STARTUP_GRACE_S = 180 s`——宽限期内「尚无 sampler_pid / 尚无首个样本」
不得判 sidecar 失效；超时归 `worker_startup_failure`（可重跑一次）。`rt_gate.py` 未改（正确，它属冻结件）。

### 6.2 D-B / D-C 修复

- **D-B**：`classify_retry` 按 `trigger_kind` 分流；`resource_hard_stop` **只在**
  「`verdict==hard_stop` + reasons 含阈值穿越词 + `sample_index>=2`」时成立；
  `sidecar_exited`/无样本/worker 启动失败永不推导为资源硬停。
  目录复用被拒 → 独立类别 `child_dir_reuse_refused`（fail-closed）。
- **D-C**：触发记录改名 `termination_trigger.json`，必带 `trigger_kind`/`is_hard_stop`/`wording_note`；
  `threshold_evidence` 只在真越线时写出，且取**生效阈值**（此处又发现一个真实 bug：
  演练阈值 5000 曾被记成默认 12288，已修）。

### 6.3 我的独立核验（本次）

| 项 | 方式 | 结果 |
|---|---|---|
| 三个脚本哈希 | 自算 | 全部一致（见 6.4） |
| `rt_gate.py` 未被改动 | 自算 | `e99e76b7…` 不变 ✓（冻结件确实未被碰） |
| `STARTUP_GRACE_S` / signals 约定 / drill / `drill_hard_stop` / `child_dir_reuse_refused` | 读代码 | 均存在 ✓ |
| **`--drill` 把关** | 实跑 | 不给 `--drill` 却传 `--ws-hard-stop-mb` → **exit 9**，并打印「阈值覆盖只在 --drill 演练模式下允许；生产运行必须使用 Codex 裁定阈值」✓ |

### 6.4 哈希更正（此前记录已失效）

§2 表中的 93,747 / 12,119 / 29,186 是上一轮值，**已作废**。当前值（引用时刻 2026-09-14 13:24）：

| 脚本 | 字节 | sha256(前16) |
|---|---|---|
| `work\tools\lt2_production.py` | 114,697 | `dac8270dec1f983f` |
| `work\tools\lt2_sampler.py` | 15,668 | `7700e3eb4a56f49f` |
| `work\tools\tests_lt2_supervisor.py` | 42,598 | `1108c01892bb705e` |

> 这已是同一天内第三次哈希变更。再次印证「脚本哈希必须带引用时刻」这条约定。

### 6.5 值得 Codex 关注的两点

- **R4（实现方提出，我认同）**：`resource_hard_stop` 的正向判据依赖 `reasons` 的**文本模式匹配**
  （`ws_hard_stop(` 等）。若 `rt_gate` 日后改动 reason 文案，匹配会失配 → 退化为
  `unclassified_failure`（**fail-closed，不会误判为资源硬停**，这点是安全的），
  但会失去「可重跑一次」的机会。建议把 reason 结构化为字段——**这需要改 `rt_gate.py`**，
  而它当前是冻结件，故未动，待 Codex 裁定。
- **U10**：演练阈值取多少能**稳定**在 solve 期触发，取决于真实 WS 曲线；建议先 5000，过晚则降 3000。
  这一点只有真实演练能定。

### 6.6 已重新启动的真实运行

```text
(0.8,2) 页面文件后资源确认（重跑）
  run-id: lt2-resource-confirm-x080-n02-postpagefile-r2
  命令: --combos '[[0.8,2]]' --freqs '5 10 15 20 25 30 35' --max-combos 1
  性质: 真实 COMSOL，后台作业 pwsh-2；单实例串行（演练在其完成后才启动）
```

真实硬停演练（用户已授权）将使用：`--drill --ws-hard-stop-mb 5000 --freqs '5'`，
预期退出码 **6**（演练触发硬停 ⇒ `BLOCKED_OR_LIMITED`，是**预期结果而非失败**）。

---

## 7. 资源确认第 2 次：**资源层面成功、求解成功，收尾代码 bug 致批次失败**

run-id `lt2-resource-confirm-x080-n02-postpagefile-r2`（真实 COMSOL，`--combos '[[0.8,2]]'`，
7 频点）。批次结果 `BLOCKED_OR_LIMITED`，但**失败发生在求解成功之后**，必须分开陈述。

### 7.1 资源层面：页面文件变更**解决了问题**（这是本次最关键的数据）

| 指标 | 页面文件生效前（R0 v2） | 本次（生效后） | 变化 |
|---|---|---|---|
| 采样数 | 159 | 154 | — |
| `verdict` 分布 | 147 个 `hard_stop` | **154 个全部 `ok`** | 硬停归零 |
| commit 可用最低 | **647.3 MB** | **17,409.9 MB** | **约 27 倍** |
| commit 可用最高 | 11,294.9 MB | 30,172.4 MB | — |
| 物理可用最低 | 5,680.7 MB | **10,707.5 MB** | 约 1.9 倍 |
| server WS 峰值 | 11,236.3 MB | 11,040.1 MB | 同量级（符合预期） |
| 采样空档 | 无 | 无（`gap_s = 5.007`） | — |

```text
commit 硬线 4,096 MB：本次最低 17,409.9 MB，仍有 4.25 倍余量 → 不再触发
commit 预警线 6,144 MB：同样从未触及
WS 硬线 12,288 MB：峰值 11,040.1 MB（< 11,500 预警线）→ 未触发
```

→ **§5.4 中「未验证的预测」现已被实测证实**：页面文件调整确实消除了 commit 贴地问题。
我先前预测的最低余量「约 22.6 GB」**偏高**（实际 17.4 GB），原因是我按刚重启时的背景提交量
（10.7 GB）估算，而运行时应用已重新打开、背景提交量上升。**预测方向正确、具体数值偏高**，
以实测 17,409.9 MB 为准。

### 7.2 求解本身成功

```text
solve_started_at = 13:26:03，solve_returned_at = 13:38:33
solve_seconds = 749.5（与 R0 v2 的 754.4 s 吻合）
solve_error = null
port_closed_within_30s = true（server 自行正常关闭）
末行采样 WS 掉至 1,691.4 MB（收尾特征）
```

### 7.3 真机首次证实的两项（长期未验证）

- **U5**：`server_identity.parent_is_worker = true` → **每组合一个全新 combo-worker 进程
  确实绕开了「MPh 单会话单 client」约束**。这是整个三进程架构的关键假设，现已真机成立。
- **U7**：`pid_source = "port_owner"`、`pid_source_waited_s = 0.6` →
  `server_pid_from_port()` 端口取 PID 与父子关系在**真实 MPh 启动链**上可用（不再是启发式）。
- 附带 **U6 部分覆盖**：真实 5 s 节奏下 154 个采样无空档（`gap_s = 5.007`）。

### 7.4 失败点：D-D 遗留变量引用（普通代码 bug）

```json
worker_error.json: {"error": "NameError: name 'state_f' is not defined",
                    "combo": [0.8, 2], "child_index": 0, "attempt": 1}
时刻 13:38:33（与 solve_returned_at 同一秒）→ 发生在求解之后的收尾路径
后果: checkpoint_present = false、无 rows.csv、lt2c_quick_gate = null、
      pass_conditions = null、worker_returncode = 1
```

`state_f` 是 **P1-a 单写者拆分时留下的旧变量**（原先只有一个 state 文件，
现拆为 `worker_state.json`/`sampler_state.json`/`supervisor_signal.json`）。
**已要求系统性排查全部同类遗留引用**，而非只修这一处；
并要求补一项覆盖「求解返回 → 写 checkpoint → LT2-C → 抽取 rows.csv」的收尾路径测试
（此前 T10 的 `fake-combo-worker` 显然没走这条路径，所以漏网）。

### 7.5 分类仍算正确（D-B 生效）

失败**没有**被误标为 `resource_hard_stop`，而是 `sampler_supervisor_integrity`（fail-closed）。
不过一个 worker 自身抛异常归到「监控完整性」并不贴切，已要求改为独立类别
（如 `worker_exception_postsolve`），以免指向错误子系统。

### 7.6 状态

```text
pagefile 后的资源行为        = VERIFIED（commit 最低 17,409.9 MB，硬停 0/154）
(0.8,2) 资源确认             = RESOURCE_PASS / BATCH_FAIL（收尾代码 bug，非资源原因）
U5 / U7                      = VERIFIED_ON_REAL_HARDWARE
U6                           = PARTIALLY_VERIFIED（真实 5 s 节奏无空档）
U2（真实 server 终止）        = STILL_UNVERIFIED（本次 server 自行关闭，cancel_record=null）
U3 / U4 / U8 / U9 / U10      = STILL_UNVERIFIED
D-D（遗留 state_f 引用）      = 已派修
真实 COMSOL 硬停演练          = NOT_STARTED（用户已授权，待 D-D 修好后执行）
LT2 production               = BLOCKED_BEFORE_PRODUCTION
```
