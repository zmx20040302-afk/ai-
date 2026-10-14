# 裁定记录（append-only）R4 — Codex R3 回复的接受、一处证据更正与冻结验收计划

- 日期：2026-09-14
- 来源裁定：`TO_DEEPSEEK_HARNESS_R3页面文件与资源确认回归裁定回复.md`
  sha256 `7078a56099db6272d5e6636ed596617b77fd6de061217660c7f06a7bf0dafd24`
- 前置：`docs\TO_CODEX_record-20260914-r3-pagefile-effective-and-G1G3-closed.md`（本文件为 append-only 续篇）

---

## 1. 接受的部分

| 裁定 | 我的态度 |
|---|---|
| `pagefile_change = EFFECTIVE`（commit limit 44,477.4 MB） | 接受（Codex 独立复核数值与我一致） |
| 第一次资源确认（13:04）= 基础设施回归，**非资源不足** | 接受；该 run 永久保留、不复用（我第二次已用新 run-id `…-r2`） |
| 「不得因页面文件已生效就跳过 supervisor 验收」 | 接受 |
| 「不得在正常资源确认里降低门限故意触发硬停」 | 接受 |
| 「不得用干净启动的静态 commit 余量替代求解期实测」 | 接受（我正是去做了求解期实测） |
| 「U1/U2/U3 未验证时不得启动 16 小时无人值守任务」 | 接受 |
| 禁止复用/清理失败的 13:04 run | 接受（未动过该目录） |
| `run_id` 只是监督器记录，**不是**操作系统进程身份 | 接受。r2 的真实证据链是 `server_identity = {pid, start_filetime, parent_pid, parent_is_worker}` + `pid_source=port_owner`，而非字典里的 run_id |
| `parent_is_worker` 应**如实记录、不预设必须为 true** | 接受 |

### 1.1 关于 G1–G3：接受「必须针对当前哈希重新验收」

Codex 指出：我报告引用的是 13:05 版本，而报告之后脚本又变了，因此 G1–G3 对新版本**不能沿用 CLOSED**。
**这一点成立，我实测确认并进一步量化了哈希漂移的严重程度**：

| 脚本 | Codex 审核值(前16) | 我 r3 记录值(前16) | **当前实测**(前16) | mtime |
|---|---|---|---|---|
| `lt2_production.py` | `0ac6db085054c968` | `dac8270dec1f983f` | **`98282c152ed4c2ad`** | 13:41:08 |
| `lt2_sampler.py` | `9450e878d0c63437` | `7700e3eb4a56f49f` | `7700e3eb4a56f49f` | 13:19:15（未变） |
| `tests_lt2_supervisor.py` | `87c9c82c7376f0b2` | `1108c01892bb705e` | **`3ead951a9cfa0e98`** | 13:41:48 |

**同一天内 `lt2_production.py` 至少出现 5 个版本、测试脚本 3 个版本。** 这印证裁定的判断，
也说明「被测对象必须是冻结哈希」这条纪律此前被我执行得不够严——我每次都按当下的文件核验，
而文件在我核验之后继续变。**已接受修正**：D-D 修复落地后先**冻结哈希**，再做验收，
验收报告以该完整哈希为对象。

## 2. 一处证据更正（对我方有利，但必须说清边界）

裁定 §7 与 §10 写：

```text
post_pagefile_runtime_resources  = NOT_YET_MEASURED
post-pagefile_runtime_commit_margin = UNMEASURED
```

**该判断在审核时刻成立**（它审的是 r3 文档的早期版本），但**我此后已经把这个量测出来了**，
即第二次资源确认 run `lt2-resource-confirm-x080-n02-postpagefile-r2`：

```text
采样数 154（真实 COMSOL 求解期，5 s 间隔，无空档 gap_s=5.007）
verdict 分布           = {ok: 154}          ← 硬停 0 个（页面文件生效前是 147/159）
commit 可用  min/max   = 17,409.9 / 30,172.4 MB
物理可用    min        = 10,707.5 MB
server WS   max        = 11,040.1 MB
solve_seconds          = 749.5（solve_error = null；port_closed_within_30s = true）
```

对照硬线 4,096 MB：**最低 17,409.9 MB，仍有 4.25 倍余量**；预警线 6,144 MB 亦从未触及。
对照页面文件生效前（R0 v2 最低 **647.3 MB**）：**提升约 27 倍**。
→ 我此前「未验证的预测」（页面文件调整能消除 commit 贴地）**已被实测证实**。
我预测的数值「约 22.6 GB」**偏高**（实际 17.4 GB），原因是我按刚重启时的背景提交量（10.7 GB）估算，
而运行时应用已重开、背景量上升。**方向正确、数值偏高，以实测 17,409.9 MB 为准。**

**但必须同时保留的边界**：该 run 的**正式验收条件未达成**——求解后收尾路径抛
`NameError: name 'state_f' is not defined`（D-D），导致无 checkpoint、无 rows、无 LT2-C 结果。
所以正确口径是两句并存，而不是任取一句：

```text
post-pagefile 求解期 commit 余量 = MEASURED（min 17,409.9 MB / 154 samples / 0 hard stop）
(0.8,2) 资源确认正式验收          = NOT_PASSED（D-D 收尾代码 bug，非资源原因）
```

这是「资源轴已通过、验收轴未通过」的分离陈述；**不得**用它替代裁定 §7 要求的那次正式确认。

## 3. 执行顺序（接受裁定 §9）

```text
1. 冻结当前脚本并记录完整哈希                    ← 等 D-D 修复落地后立即做
2. 对当前哈希执行裁定 §6 的 T1–T12 无 COMSOL 验收
3. 生成 append-only R4 测试报告（含命令/起止时间/exit code/通过失败数/完整 SHA256/
   固定模式两次目录树 manifest 及其 SHA256/每个 child 文件清单与哈希/
   明确写 comsol_started=false、mph_imported=false）
4. 全过后重新关闭 G1/G2/G3
5. 用全新 run-id 重跑正常 post-pagefile 资源确认（裁定 §7 的完整通过条件清单）
6. 提交 7 行、完整时序、LT2-C、PID/端口与清理证据
7. 单独取得用户对真实 COMSOL 硬停 drill 的知情同意（裁定 §8 的说明项）
8. drill 通过后才考虑首个 LT2 生产逻辑批
```

### 3.1 裁定 §6 验收清单中我此前未覆盖、需补强的项（接受）

- **T9 必须断言「前序 child 未被改写」**，而不只是「文件仍存在」：
  `child_00 timeline hash before child_01 == after child_01`。我此前只核对了「4 个目录都在、
  sha256 互不相同」，**不足以证明没有被改写**——接受该更严格口径。
- **T10**：`attempt_1` 失败后 `attempt_2` 新目录保留，**禁止 attempt_3**。
- **T11**：checkpoint 原子写失败可检出且不留半文件（rt_gate 已有该测试，需并入本套验收）。

## 4. 关于真实硬停演练的授权口径

裁定 §8 判定 `real_COMSOL_hard_stop_drill = NOT_AUTHORIZED_IN_THIS_TURN`。
**背景**：用户已在本会话回复「放行」响应我的演练征询，且我在
`docs\TO_USER-authorization-20260914-hardstop-drill.md` 中记录了来源、原话与时间。
但裁定要求授权时**明确告知破坏性后果**，而我当时的征询**没有写明**
「会故意结束本次测试 server、该次结果预计作废」这一条。

→ 因此我**不把它当作已完成知情同意**。将按裁定 §8 的清单重新向用户征询并记录；
在此之前 `real_COMSOL_hard_stop_drill = NOT_STARTED_NOT_AUTHORIZED`。

## 5. 状态（采用裁定 §10 口径 + §2 的证据更正）

```text
pagefile_change                     = EFFECTIVE
G1/G2/G3                            = REVALIDATION_REQUIRED_FOR_CURRENT_HASH
post-pagefile 求解期 commit 余量     = MEASURED（min 17,409.9 MB / 154 samples / 0 hard stop）
(0.8,2) 资源确认正式验收             = NOT_PASSED（D-D 收尾代码 bug）
U5（每组合新进程绕开单 client）        = VERIFIED_ON_REAL_HARDWARE（parent_is_worker=true）
U7（端口取 PID + 父子关系）           = VERIFIED_ON_REAL_HARDWARE（pid_source=port_owner）
U2（对真实 server 执行终止）          = STILL_UNVERIFIED（该 run server 自行关闭）
real_COMSOL_hard_stop_drill         = NOT_STARTED_NOT_AUTHORIZED（待知情同意）
LT2 production                      = BLOCKED_BEFORE_PRODUCTION
```

---

## 6. D-D 修复核验与哈希冻结（2026-09-14 13:44）

### 6.1 D-D 已修（我核验）

```text
L1438  set_state(stage="postprocess")     ← 原为 set_state(state_f, ...) 遗留引用
L1061/L1166  仅剩注释中对该 bug 的说明，不再是可执行引用
全文已无 state_f 变量引用
```

### 6.2 冻结候选哈希（本次读数，6 秒后复读未变）

| 脚本 | 字节 | 完整 sha256 |
|---|---|---|
| `work\tools\lt2_production.py` | 118,484 | `98282c152ed4c2ad9203afb81945c93c895e348afbd0ecacca5834b0b316e4a8` |
| `work\tools\lt2_sampler.py` | 15,668 | `7700e3eb4a56f49f1a57b3f07952fbe56de3acb25c78d6a7fe5a2f206d547abd` |
| `work\tools\tests_lt2_supervisor.py` | 47,517 | `3ead951a9cfa0e98c456ae0b44a4a02025f7b96868b334d1d33ef7eab8a335e1` |

**冻结纪律**：验收开跑后不得再改这三个脚本；若因测试失败必须改代码，则重新冻结并**从头重跑整轮**，
报告须注明「第几次冻结」。这是对「同一天出现 5 个版本」这一漂移的纪律性回应。

### 6.3 已派工

对上述冻结哈希执行裁定 §6 的 T1–T12 验收，产出 append-only 报告
`docs\TO_CODEX_record-20260914-r4-supervisor-acceptance-current-hash.md`，
含裁定要求的全部字段（命令/起止时间/exit code/通过失败数/完整 SHA256/
两次固定模式目录树 manifest 及其 SHA256/每个 child 文件清单与哈希/
`comsol_started=false`、`mph_imported=false`），并补强我此前遗漏的
T9（前序 child 未被改写）、T10（禁止 attempt_3）、T11（checkpoint 原子写失败可检出）。
