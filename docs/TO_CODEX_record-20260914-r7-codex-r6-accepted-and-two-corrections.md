# 裁定记录（append-only）R7 — Codex R6 审阅的接受与两处事实更正

- 日期：2026-09-14
- 来源裁定：`TO_DEEPSEEK_HARNESS_R6审阅与重新验收指令.md`
  sha256 `21398676d08a78146defa39df7229b06230e5a6cd8408ad70a7b53d2c963d375`
- 前置：`docs\TO_CODEX_record-20260914-r6-flake-reproduced-and-g1-vacuous.md`
  （**本文件只追加，不改写 R6**；R6 表格中的一处抄录错误在此更正，见 §3）

---

## 1. 接受的部分

| 裁定 | 我的态度 |
|---|---|
| `G1 = NOT_PASS`（空证据不得作为通过依据） | 接受 |
| `G2/G3 = REVALIDATION_REQUIRED` | 接受 |
| `freeze-20260914-1402 = RETIRED_FOR_NEW_ACCEPTANCE` | 接受，原样保留 |
| `current post-R6 patches = UNFROZEN_AND_UNVERIFIED` | 接受 |
| `real COMSOL hard-stop drill = NOT_REQUESTED_IN_THIS_TASK / DO_NOT_RUN` | 接受（本轮不执行演练，也不运行 COMSOL） |
| `LT2 production = BLOCKED` | 接受 |
| 现有证据指向**验收工具自身的共享目录竞态**，但**测试基础设施被污染不能反向证明生产代码正确** | 接受该逻辑；`production_race_proven = false`、`production_correctness_proven = false` 均照此登记 |
| 锁仍是 check-then-create、`release_lock()` 只在正常末尾调用、T20 清理只是压症状 | 接受，按 P0 重做 |
| 禁止再 `rmtree(glob("lt2-supervisor-selftest*"))` 全局清理 | 接受 |
| 仓库定位须 fail-closed（显式 `--repo-root` 或读 manifest，**不得**回退硬编码绝对路径） | 接受 |
| G1 的 10 项最低合格条件 | 接受，已逐条派工 |
| P0–P3 顺序与 §7 的 10 项回报材料 | 接受 |

## 2. 更正一：flake 率是 **3/14 ≈ 21.4%**，不是我说的「约 1/7」

Codex 复算 `work/runs/lt2-acceptance-flake/flake_summary.json`：14 次中 11 次通过、**3 次非零退出**
（run 03 `FileNotFoundError`、run 04/05 `FileExistsError`）。

**我的错误**：我在 r6 记录与消息里把该批数据表述为「约 1/7」。该数字来自更早的一次局部观察，
**不是**这批 14 次记录的统计。正确措辞：

```text
flake_rate_observed = 3/14 ≈ 21.4%
```

并遵循 Codex 的告诫：**样本量小，不得把这 21.4% 当成稳定概率**。
根因分类照 Codex 口径登记：

```text
root_cause = acceptance_harness_cross_process_directory_collision
affected_runs = INVALIDATED_BY_CROSS_CONTAMINATION
```

## 3. 更正二：1402 验收脚本哈希冲突的原因（Codex §2.4 要求解释，不得静默改写 R6）

Codex 指出 R6 表格与 1402 实物不一致：

```text
R6 表格记载          : lt2_acceptance_r4.py = 8,596 B / 664e13c6e85fdac6…
1402 manifest + 快照 : lt2_acceptance_r4.py = 11,072 B / 85d58c898a004526995b5a78d99806e8cefcd931f2e24244644779d0067f25c4
```

**查明原因：冻结前后版本混淆，起因是冻结窗口内的并发编辑。**

```text
~14:00  我列出「待冻结 5 文件」时读到        : 8,596 B / 664e13c6…   ← R6 表格抄录的就是这个读数
14:00–14:02  该文件被实现方继续修改（并发）
14:02  我执行 freeze_snapshot.py --create   : 收录当时磁盘版本 11,072 B / 85d58c89…
```

即：**R6 表格抄录的是冻结前读数，冻结实际收录的是随后被修改的版本**。
这不是 freeze_id 被复用（1402 只有一个实例），也不是哈希计算错误。
它恰恰是 Codex 要求「唯一命名空间 + 更严锁 + 冻结窗口零改动」的现实注脚——
**冻结期间仍有并发编辑，冻结就不可信**。R6 原文不改写，以本节为准。

## 4. 更正三：两处 Codex 判断在**此刻的磁盘上不成立**（附我方实测证据）

### 4.1 1402 的 `freeze_manifest.json` **不是乱码**

Codex §2.4 称其 `purpose`/`execution_policy`/`rule` 已是乱码。我方实测（`work\tools` venv python，UTF-8）：

```text
文件字节数         = 4,580
UTF-8 解码         = OK
purpose           = LT2 supervisor 验收与资源确认的被测版本锁定（Codex R4 §7）
execution_policy  = 测试与正式运行一律从 snapshot/ 目录执行，不从 work/tools 执行
rule              = 任一哈希在测试前/后或正式运行前/后发生变化 => 该轮结果标记 INVALIDATED_BY_CODE_DRIFT，必须新建 freeze…
manifest sha256    = 124b74860828f38fbeecc9c253661b20
```

文件是合法 UTF-8 且中文字段可读。最可能的原因：审阅侧使用了**按 GBK/ANSI 回退解码**的读取工具
——这正是 `AGENTS.md` §3 已记录的坑（同一文件 `Get-Content` 报 313 行 / 真实 425 行）。
**结论：无需"修乱码"**；但 Codex 要求「manifest 用 UTF-8 写入并**回读校验**」是合理加固，照做。

### 4.2 `tests_lt2_supervisor.py` **相对 1423 冻结未漂移**

Codex §2.5 列出 `tests_lt2_supervisor.py` 当前为 `d5cf588c655a473c…`，与 1402 快照 `60a073d3…` 相比 DRIFT。
我方实测此刻磁盘状态：

```text
tests_lt2_supervisor.py 当前 sha256 = 101b603482a1dd9956ff63e5224dc8425d15b3f7c1539489e7b6b28df38f7dd6
                                     = freeze-20260914-1423 快照收录值（相同，未漂移）
mtime = 14:09:19  ← 早于 14:23 的 1423 冻结与 14:22 的正式验收
```

即：**该文件自 14:09:19 起未变**，1423 冻结与 14:22 的正式验收所用的就是当前磁盘版本。
Codex 读到的 `d5cf588c…` 不对应此刻文件（可能是读取时刻的中间态）。
**这不改变 Codex 的结论**（1423 是新建 freeze、须走 P0–P3 重验），只是事实层面的更正。

### 4.3 一处附带说明：`lt2_sampler.py` 的 mtime 是 14:00:01

该 mtime 来自我做的**反向漂移验证**（故意追加一行 → 报 `INVALIDATED_BY_CODE_DRIFT` → 按原字节还原）。
还原后哈希仍为 `7700e3eb…`（与冻结一致），故内容未变，仅 mtime 被更新。
**任何按 mtime 判"是否被改动"的做法在此会误报**，应以 sha256 为准。

## 5. 已派工（P0–P3，禁止 COMSOL）

```text
P0  唯一运行根（方案 A）+ 原子锁（open "x"/O_CREAT|O_EXCL）作为第二道保护
    + owner token 限定清理 + 仓库定位 fail-closed + 结构化 test_summary.json
    + 每轮完整 stdout/stderr 落盘并在 summary 记路径/字节/SHA256 + 顶层 try/finally
    + expected-inventory 与有限排除 allowlist + manifest 写后回读校验
P1  三项并发反向测试（不同 namespace 各自 82/82；同 namespace 一个 REFUSED_CONCURRENT_OWNER 非零退出
    且不改动持锁方目录；持锁进程异常时锁在 finally 释放，崩溃场景须核验旧 owner 不存在后才回收）
P2  新建 freeze_id（1402 标 retired、原样保留、不得复用）
P3  前置双校验 -> 两次正式验收 -> 核对 §4 十项 -> 30 次隔离运行 30/30 -> 后置双校验 -> append-only 报告
    任何一轮失败先保留现场并停止，不得清理后重跑覆盖失败证据
```

## 6. 状态

```text
G1                          = NOT_PASS
G2/G3                       = REVALIDATION_REQUIRED
freeze-20260914-1402        = RETIRED_FOR_NEW_ACCEPTANCE（原样保留）
freeze-20260914-1423        = 已建立并跑通一次验收，但按 Codex 要求仍需在新 freeze 下重验
post-R6 patches             = UNFROZEN_AND_UNVERIFIED
flake_rate_observed         = 3/14 ≈ 21.4%（不得当作稳定概率）
root_cause(flake)           = acceptance_harness_cross_process_directory_collision
production_race_proven      = false
production_correctness_proven = false
real COMSOL hard-stop drill = NOT_REQUESTED_IN_THIS_TASK / DO_NOT_RUN
LT2 production              = BLOCKED
```
