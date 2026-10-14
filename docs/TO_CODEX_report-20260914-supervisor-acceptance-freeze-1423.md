# LT2 supervisor 正式验收报告 — freeze-20260914-1423-post-flake-fix

- 日期：2026-09-14
- 依据：Codex R4 裁定 §6（T1–T12 验收清单与报告必填字段）、§7（可执行哈希锁）、§8
- 性质：**从冻结快照执行的正式验收**。本报告与 `docs\TO_CODEX_record-20260914-r6-*.md` 衔接。
- 结论：`all_pass = true`、exit 0。G1/G2/G3 对**本 freeze** 重新关闭。

---

## 1. 冻结标识与被测版本

```text
freeze_id   = freeze-20260914-1423-post-flake-fix
freeze 目录 = work\runs\lt2-supervisor-acceptance-freeze-20260914-1423-post-flake-fix\
manifest    = <上述>\freeze_manifest.json
快照        = <上述>\snapshot\   （7 个文件，均设只读）
```

**执行策略**：一切测试**从 `snapshot/` 运行**，不从持续被修改的 `work\tools` 运行。
已实测确认这一点成立——验收执行器的 `layout.tools` 字段指向快照目录：

```json
"layout": {"tools": "...\\lt2-supervisor-acceptance-freeze-20260914-1423-post-flake-fix\\snapshot",
           "repo": "C:\\Users\\zmx\\Desktop\\memsharness",
           "runs": "...\\work\\runs", "layout_ok": true}
```

被测脚本完整 SHA256：

| 文件 | 字节 | 完整 SHA256 |
|---|---|---|
| `lt2_production.py` | 119,412 | `1974a6075e4a3ca6d200feea6f6525ca9664c92b3237b3b436254efea287782d` |
| `lt2_sampler.py` | 15,668 | `7700e3eb4a56f49f1a57b3f07952fbe56de3acb25c78d6a7fe5a2f206d547abd` |
| `tests_lt2_supervisor.py` | 55,544 | `101b603482a1dd9956ff63e5224dc8425d15b3f7c1539489e7b6b28df38f7dd6` |
| `rt_gate.py`（依赖，冻结件） | 9,466 | `e99e76b76db1cd413ec5961c5dbca8379bd4a03ced4ddb24b2fd1c303cf3f5db` |
| `lt2_acceptance_r4.py`（验收执行器） | 13,670 | `050128fa59e08b9928b8a40769f56876bc118be57de2697aa239e02c8555843b` |
| `check_undefined_names.py` | 6,780 | `991671656d109032c19fe59a681531da7ada50a556278b874b13c33239e42a5e` |
| `lt2_flake_hunt.py`（flake 定位器） | 7,058 | `f9a290ded5643a1a4e8d46787d1a5cf8d69f5341523a3c6e974b6135974eaa4f` |

## 2. 命令与时间

```text
命令      : <venv>\python.exe <freeze>\snapshot\lt2_acceptance_r4.py
started_at: 2026-09-14T14:22:14
ended_at  : 2026-09-14T14:23:28   （约 74 s）
exit code : 0
通过/失败 : 套件两次均 82/82 通过、0 失败；T12 三项均 exit 0
```

## 3. 哈希锁：测试前 / 测试后双向校验（Codex §7 要求）

```text
测试前 --verify          : drift_count=0, verdict=MATCH
测试后 --verify          : drift_count=0, verdict=MATCH   （checked_at 14:23:36）
测试后 --verify-snapshot : drift_count=0, verdict=MATCH
```

即**冻结在全套验收期间未被破坏**。此前 R4 的「冻结候选失效」问题已由机制而非观察堵住。
（附：反向验证曾实测通过——故意篡改 `lt2_sampler.py` 一行即报
`INVALIDATED_BY_CODE_DRIFT`、`drift_count=1`、exit 1；按原字节还原后再次 MATCH。）

## 4. 确定性证据（**非空**，这是上一轮的缺陷所在）

```text
deterministic_files (两次)          = 55 / 55          ← 非空
nondeterministic_excluded (两次)    = 34 / 34
manifest_deterministic_sha256       = 8763e38a41ef1c4525ee1ed4d1498ddce91330ba2e199d5f3cda435fd1011df7
                                      （两次完全相同）
manifest_sha256_identical           = true
deterministic_manifest_empty        = false            ← 空集合判 FAIL 已生效
different_files / only_left / only_right = 0 / 0 / 0   ← Codex §8 明确要求的字段，已在 summary 中
full_tree_different_files           = 16（全部落在**声明的**不可复现集合内）
full_tree_only_left / only_right    = 0 / 0
child_count                         = 20
comsol_started = false ; mph_imported = false
all_pass = true
```

**关于上一轮的缺陷（已改正并留档）**：上一版执行器用 `TOOLS.parent.parent` 推仓库根，
从快照运行时 `RUNS` 变成不存在的嵌套路径 ⇒ 两次 glob 均空 ⇒ 两份 manifest 都是 `{}` ⇒
`sha256("{}") = 44136fa3…` 相同 ⇒ 误判 `identical = true`。
该「空洞证据」产物已按 append-only 保全在 `work\runs\lt2-acceptance-r4-vacuous-bug\`。
现版本已修：向上查找仓库根 + `layout_ok` 校验 + **空集合一律 FAIL** + manifest 完整内联 + §8 字段进 summary。

## 5. 不可复现项的声明（16 处全量差异的来源）

```text
worker_state.json        控制通道，必须带真实 sampler_pid 供判活 → 不参与逐字节比对
*-liveproc\              真实 PID
*-wallclock\             T9 的反例根，**故意不启用** --fixed-timestamps（故其 timeline 必然不同）
```

确定性集合内 `resource_timeline.jsonl` / `sampler_state.json` 的差异数 = **0**
（上一轮我发现的「两次 timeline 哈希不同」全部且仅仅来自 `wallclock` 反例根，已解释）。

## 6. 产物与哈希（引用时刻 2026-09-14T14:23:36）

| 产物 | 字节 | sha256(前16) |
|---|---|---|
| `acceptance_summary.json` | 31,752 | `d6fa59384111d430` |
| `child_inventory.json` | 11,930 | `bca2fee476ab0ced`（summary 记录 `child_inventory_sha256 = bca2fee476ab0ced9414e4e7cc6f7a02`） |
| `manifest_deterministic_run1.json` | 9,718 | `8763e38a41ef1c45` |
| `manifest_deterministic_run2.json` | 9,718 | `8763e38a41ef1c45`（与 run1 相同） |
| `manifest_full_run1.json` | 15,848 | `06bfd9183635d916` |
| `manifest_full_run2.json` | 15,848 | `6ff431cf8d464b5e`（含不可复现项，按设计不同） |
| `nondeterministic_excluded_run1.json` | 6,095 | `3f5e8e79308ffae5` |
| `nondeterministic_excluded_run2.json` | 6,095 | `3f5e8e79308ffae5` |
| `tree_manifest_run1.json` / `run2.json` | 15,848 | `01ca7ef95baef945` / `783440745e28116b` |

每个 child/attempt 的文件清单与哈希见 `child_inventory.json`（`child_count = 20`），
其 sha256 已记入 `acceptance_summary.json`，未截断。

## 7. T1–T12 结果

| # | 项 | 结果 |
|---|---|---|
| T1 | 固定时间戳连跑两次，完整目录树逐字节一致 | PASS（确定性集合 `different_files=0`、`only_left=0`、`only_right=0`） |
| T2 | `batch_manifest` 真实生成且 inventory 满足 | PASS（`child_count=20`，inventory sha 记入 summary） |
| T3 | 正常 fake worker 接受空 child 目录并产出完整文件 | PASS |
| T4 | supervisor signal 只出现在 `<run>/signals/` | PASS |
| T5 | 首样本前 sidecar 退出 = integrity/startup failure，非 resource hard stop | PASS |
| T6 | 连续两次模拟越线时 supervisor 因 **verdict** 动作而非等 stale | PASS |
| T7 | 错误 port owner / PID / start time 时拒绝终止 | PASS |
| T8 | 模拟终止后执行 PID/端口二次验证 | PASS |
| T9 | `child_00..03` 时间线同时存在且**前序哈希不变**（before==after） | PASS（含 wallclock 反例根对照） |
| T10 | `attempt_1` 失败后 `attempt_2` 新目录保留，禁止 `attempt_3` | PASS |
| T11 | checkpoint 原子写失败可检出且不留半文件 | PASS（`rt_gate` 用例并入） |
| T12 | 语法 / import / dry-run | PASS（compile=0, import=0, dry_run=0） |

## 8. flake 的处置与如实措辞

**根因（测试侧，非生产竞态）**：套件两个实例共享 `work\runs\lt2-supervisor-selftest*` 目录，互相删/建。
两个具体崩溃点已定位并修复：

```text
T1  (child/"termination_trigger.json").read_text() 未保护 → 文件被并发删 → 未捕获异常 ⇒ 整套件中止（5.1 s，无「合计」行）
T20 bad_target.mkdir() 未保护 → 目录已存在 ⇒ FileExistsError ⇒ 套件中止
```

**根治**：套件加**独占运行锁**（`work\runs\lt2-supervisor-selftest.LOCK`，陈旧锁可抢占）。
实测并发第二个实例输出 `[SKIP] 另一个测试实例正在运行（pid=…）⇒ 拒绝并发执行`、exit 3。
⇒ 「两个套件实例互删共享目录」这一向量被**从结构上关闭**，而非事后解释。

**如实措辞**：修复后 14/14 全绿（`flake_count=0`），本次正式验收两次 82/82。
那一次 `81/82` 的**具体断言未被捕获**（当轮只存了 stdout_tail，是记录失误），
因此**不写成「已完整解释」**，只写「两个已定位崩溃点已修 + 并发向量已关闭 + 14 次及本次两次均未复现」。

**交叉污染披露**：我在 r6 阶段从旧快照跑过验收，与该循环时间重叠（run 03/04/05 失败恰在重叠窗口），
是本次 flake 得以复现的原因之一；该重叠已在报告与 r6 记录中如实说明。

## 9. 结论与边界

```text
G1 确定性可复现      = CLOSED_FOR_THIS_FREEZE（非空 55/55，两次 manifest 逐字节相同）
G2 batch manifest    = CLOSED_FOR_THIS_FREEZE
G3 child 清单/隔离    = CLOSED_FOR_THIS_FREEZE（含 T9 前序哈希不变、T10 禁止 attempt_3）
哈希锁机制            = IMPLEMENTED_AND_VALIDATED（测试前/后 + 反向漂移均实测）
```

**边界（不得超出）**：

- 本验收**不含任何真实 COMSOL**（`comsol_started=false`、`mph_imported=false`）；
  它证明的是接线、确定性、目录保留、终止拒绝与分类逻辑，**不证明**真实 server 的终止路径（U2/U3）。
- 7 个文件一旦再变更，本 freeze 即失效，须新建 freeze_id 并从 T1 整轮重跑。
- 下一步仍须：新 run-id 跑正常资源确认 r3 → 提交 7 行/LT2-C/checkpoint/身份/清理证据 →
  用户已授权的硬停 drill → 才谈首个 LT2 生产逻辑批。
