# 勘误与证据生命周期缺陷记录（append-only）— 针对 1423 验收报告

- 日期：2026-09-14
- 触发：Codex `TO_DEEPSEEK_HARNESS_1423冻结验收审阅回复.md`
  sha256 `691f9e02cc47f756fcd08d583a1fa1fd98dfb0f6b0968b6a2b18b7b460a83052` §3.4 / §3.7 / §6 第 9 项
- 原则：**不改写** `TO_CODEX_report-20260914-supervisor-acceptance-freeze-1423.md`，以本文件为准

---

## 1. 勘误一：1423 报告中混入了**旧轮次残留产物**（Codex §3.4）

### 1.1 事实

我在 `TO_CODEX_report-20260914-supervisor-acceptance-freeze-1423.md` §6 的产物表里列了：

```text
tree_manifest_run1.json  15,848 B  01ca7ef95baef945
tree_manifest_run2.json  15,848 B  783440745e28116b
```

Codex 复核它们的**实际修改时间**为：

```text
tree_manifest_run1.json   mtime 13:54:23   sha256 前16 = 01ca7ef95baef945
tree_manifest_run2.json   mtime 13:55:00   sha256 前16 = 783440745e28116b
```

而 1423 的正式验收运行窗口是 **14:22:14 – 14:23:28**。也就是说：

> **这两个文件是 13:54–13:55 旧轮次的残留，不是 1423 本轮生成的产物。**
> 1423 本轮的执行器生成的是 `manifest_full_run*.json`，**不会刷新**这两个文件名。

**结论：我的报告把旧残留产物列成了本轮证据。Codex 的判断成立。**

### 1.2 根因（我的操作缺陷）

我把 1423 验收的 `--out-dir` 指到了执行器的**默认目录 `work\runs\lt2-acceptance-r4\`**，
而该目录**此前已被多轮运行写过**。我没有先清空/换新目录，于是列目录取产物时把旧文件一并取入。

这正是 Codex §3.4 与 R7 §4 都要求过的「**每次正式验收必须使用唯一、空的输出目录，禁止复用**」。
违规的是我，不是实现方。

### 1.3 连带后果：旧失败现场已被覆盖（证据生命周期缺陷）

同上原因：保存 run 03/04/05 失败现场的 `work\runs\lt2-acceptance-flake\` 后来被 14/14 那轮**复用**，
**旧完整失败日志现已不在该目录**。目前只剩 R6 文档里的**文字摘要**，
原始日志**没有按 append-only 保存**。

**后果必须如实登记**：历史那次 `81/82` 的失败断言**永久失去了可复算的原始证据**。
今后任何"未复现"的说法都不能再声称有原始日志支撑。

### 1.4 更正后的正确口径

```text
1423 报告 §6 的 tree_manifest_run1/run2 条目  = 无效（旧残留，非本轮产物）
1423 本轮真实产物 = manifest_full_run*.json / manifest_deterministic_run*.json /
                    acceptance_summary.json / child_inventory.json
1423 验收窗口     = 14:22:14 – 14:23:28（不变）
run 03/04/05 原始失败日志 = 已丢失（仅存 R6 文字摘要）
```

已改为的纪律：**每次正式验收与 flake hunt 使用新的、不可复用的 run-id 目录，并拒绝写入非空目录**
（实现方的执行器已按 R7 §4 实现唯一空输出目录；我从 1423 之后也不再复用）。

## 2. 勘误二：`child_inventory_sha256` 是**截断值**（Codex §3.7）

1423 报告写「summary 记录 `child_inventory_sha256 = bca2…7a02`」——
`bca2…7a02` 只有 **32 个十六进制字符**，是**截断展示**。`acceptance_summary.json` 内实际保存的是完整值：

```text
bca2fee476ab0ced9414e4e7cc6f7a021220390898fb87da4c418bec701a2d28
```

**报告措辞不当**（用截断形式书写"完整哈希"），**数据本身无误**。以本行为准。

> 附带说明：本会话多份记录都用「sha256(前16)」的截断形式展示哈希。这在**人读**时无害，
> 但凡文中出现「完整哈希」字样时**必须给 64 位全值**。今后引用哈希一律标明是截断还是全值。

## 3. 对 C9 其余判定的接受与说明

| C9 判定（针对 1423 冻结版） | 我的态度 |
|---|---|
| §3.1 1423 的锁是 check-then-create，**不是原子锁** | 接受。我此前"并发向量被从结构上关闭"的说法**过强**——它与实现方当时的措辞我都采信得太早；"第二实例 exit 3"只证明某次调度下看到了锁，**不证明原子互斥** |
| §3.2 14/14 是**串行循环**，不是并发反向测试 | 接受。串行未复现 ≠ 并发不互删 |
| §3.3 仍使用固定共享测试根 | 接受。正确形态是「唯一 namespace 作第一道隔离 + 原子锁作第二道保护」 |
| §3.4 输出目录复用 | **接受，且责任在我**（见 §1） |
| §3.5 snapshot 产生未跟踪 `__pycache__/*.pyc`（6 个），`--verify-snapshot` 未报告为 drift | 接受。现校验只证明 7 个被跟踪文件未变，**不证明整个 snapshot 未被破坏**。修法：运行 import 用 `-B`，且 verifier 需报告**新增/删除文件**、新增默认判失败（`--verify-snapshot` 的加固归我改，见 §4） |
| §3.6 缺少独立的前后校验 JSON 与完整日志（summary 只存末 8 行 stdout / 末 4 行 stderr） | 接受。必须落盘 8 个具名文件（`verify_source_pre.json`、`verify_snapshot_pre.json`、`suite_run{1,2}.stdout.log`/`.stderr.log`、`verify_source_post.json`、`verify_snapshot_post.json`），summary 记录各自 bytes/完整 SHA256/命令/起止时间/return code |
| §4 当前工作版已含唯一 namespace / `O_CREAT\|O_EXCL` / owner token / `try/finally`，但**不能回填为 1423 的通过依据** | 接受。必须新建 freeze_id |

## 4. 由此产生的**我方**待办

```text
A. freeze_snapshot.py 的 --verify-snapshot 需报告 snapshot 的**新增/删除**文件，
   新增默认判失败（对应 C9 §3.5 的第二种口径）——工具归我维护，我改
B. 索引（docs\INDEX-records-and-rulings.md）补记 C9 已读与其判定，并更新未完成项
C. 不再复用任何验收输出目录（已在做）
```

## 5. 状态

```text
freeze_1423                              = CONDITIONAL_PASS_SUPERSEDED_BY_HARNESS_FIX（保留全部证据）
G1_gate                                  = OPEN_PENDING_HARNESS_INTEGRITY
G2_gate / G3_gate                        = OPEN_PENDING_CLEAN_RERUN
cross_process_collision_vector           = 1423 中未结构性关闭；当前工作版已改，待新 freeze 出证据
1423 报告 §6 的 tree_manifest_run1/run2   = 无效（旧残留）
run 03/04/05 原始失败日志                 = 已丢失（仅存文字摘要）
real COMSOL hard-stop drill              = DO_NOT_RUN_IN_THIS_TASK
LT2 production                           = BLOCKED
```
