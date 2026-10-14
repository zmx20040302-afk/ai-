# 裁定记录（append-only）R6 — 哈希锁落地验证、flake 复现、G1 空证据

- 日期：2026-09-14
- 前置：`docs\TO_CODEX_record-20260914-r5-hash-lock-and-drill-consent.md`（本文件为 append-only 续篇）
- 性质：执行进展 + 两处新发现（一处对我方是阻塞项，一处是**证据质量缺陷**）

---

## 1. 可执行哈希锁：已落地并端到端验证

Codex R4 §7 要求的机制已实现为 `work\tools\freeze_snapshot.py` 并**实测通过**：

```text
freeze_id  = freeze-20260914-1402-pre-flake-fix
目录       = work\runs\lt2-supervisor-acceptance-freeze-20260914-1402-pre-flake-fix\
快照       = <上述>\snapshot\   （6 个文件，均设只读）
```

快照文件（采纳实现方建议，**把验收执行器与静态检查器一并纳入**，否则验收证据不可第三方复算）：

| 文件 | 字节 | sha256(前16) | 角色 |
|---|---|---|---|
| `lt2_production.py` | 119,412 | `1974a6075e4a3ca6` | target |
| `lt2_sampler.py` | 15,668 | `7700e3eb4a56f49f` | target |
| `tests_lt2_supervisor.py` | 53,368 | `60a073d3cd4f6a1a` | target |
| `rt_gate.py` | 9,466 | `e99e76b76db1cd41` | dependency（冻结件） |
| `lt2_acceptance_r4.py` | 8,596 | `664e13c6e85fdac6` | acceptance_aux |
| `check_undefined_names.py` | 6,518 | `e053d9df7310e02e` | acceptance_aux |

`freeze_manifest.json` 含 Codex §7 要求字段：freeze_id / created_at / 各脚本 path+sha256 /
model path+sha256 / criteria_hashes（从 `lt1_validation_summary_v2.json` 读取，不自行重算）/ python executable+version+platform。

**三种模式实测**：

```text
--create          -> 生成 manifest 并设只读（readonly_set 6 个文件）      exit 0
--verify          -> source-vs-manifest: drift_count=0, verdict=MATCH     exit 0
--verify-snapshot -> snapshot-vs-manifest: drift_count=0, verdict=MATCH
--verify（反向）   -> 我故意给 lt2_sampler.py 追加一行：
                     drift=[{frozen:"7700e3eb4a56f49f", current:"452978a7a9d488c9"}]
                     verdict=INVALIDATED_BY_CODE_DRIFT, drift_count=1      exit 1
--verify（还原后） -> 按原字节还原 -> verdict=MATCH（证明还原逐字节精确）
```

即：**漂移现在会被机制拦住，而不只是靠我读两次文件**。这是对 R4 裁定 §6「冻结候选失效」的正面补救。

## 2. 新发现一（阻塞项）：1/7 间歇失败**已复现**，但失败断言未知

从**冻结快照**运行 `lt2_acceptance_r4.py`：

```text
suite run1 = 合计 82 项，通过 82，失败 0    rc=0
suite run2 = 合计 82 项，通过 81，失败 1    rc=1   ← 复现
两次均: 测试期间 comsolmphserver 进程 = []（必须为空）
```

上一次实现方的运行是 **run1 失败、run2 通过**；我这次是 **run1 通过、run2 失败**。
两次都落在同一概率量级（约 1/7），且**失败位置不固定** ⇒ 更像**竞态**而非确定性缺陷。
考虑到我们此前已抓到一处启动竞态（D-A：supervisor 在 worker 未就绪时首拍判 `sidecar_exited`），
此处**不能按噪声处理**。

**为什么仍未定位**：验收执行器只保存 `stdout_tail`，**失败断言那一行被截断**掉了。
已要求它用 12× 循环把完整 stdout 落到 `work/runs/lt2-acceptance-flake/run_NN.log`，
给出失败断言原文与根因判断（测试自身竞态 vs 生产代码竞态）。

## 3. 新发现二（证据质量缺陷）：G1 的「确定性」证据目前是**空洞的**

验收执行器 stdout 报告：

```json
"deterministic_files": [0, 0],
"manifest_deterministic_sha256": ["44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
                                  "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"],
"manifest_sha256_identical": true
```

**我实测验证**：

```text
sha256("{}") = 44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a   ← 完全一致
```

即两次运行的「确定性 manifest」**都是空对象**；我读 `work\runs\lt2-acceptance-r4\acceptance_summary.json`
确认每个 run 的 **manifest 条目数 = 0**。于是：

```text
两边都是空 => 必然相等 => manifest_sha256_identical: true 不携带任何信息
```

**后果（严重）**：G1（确定性可复现）会在一份**空证据**上被判定通过。这正是最该拦住的一类过度声称。
**不接受**该字段作为 G1 通过依据。

要求（已派工）：

```text
1. 确定性 manifest 必须真正枚举被比对文件（路径 + sha256 + 字节数），并完整写入 acceptance_summary.json
2. 空集合必须判 FAIL：被比对文件数为 0 时禁止输出 identical: true
   -> 应报 deterministic_manifest_empty => FAIL（空比较永远不能算通过）
3. acceptance_summary.json 必须直接包含 Codex R4 §8 要求的
   different_files / only_left / only_right（现仅存在于 stdout，summary 里为 None ⇒ 报告缺字段）
```

### 3.1 附带发现：一处未解释的非确定性

```text
resource_timeline.jsonl : run1 dd8d82ae6f2ad8bd…  vs  run2 7d5f7c2ef6449a4d…   ← 不同
worker_state.json       : run1 d27290c76cf7295c…  vs  run2 d27290c76cf7295c…   ← 相同
```

已要求说明：在 `--fixed-timestamps` 下 `resource_timeline.jsonl` / `sampler_state.json`
**是否本应逐字节一致**；若本应一致，则是第三处非确定性来源，须一并定位。
（可能解释：run 失败那次本身多/少了内容；但必须证实，不能默认。）

## 4. 必须记录的交叉污染风险

我从冻结快照运行验收执行器时，与该实现方正在进行的 12× 循环**写同一个
`work\runs\lt2-supervisor-selftest*` 目录**。二者可能互相污染。
已明确：以**它带完整日志**的那几轮为准；若发现有污染迹象须如实说明。
**本轮之后我暂停自行运行测试套件**，直到它完成 flake 定位，避免再次叠加污染。

## 5. 状态

```text
hash_lock_mechanism            = IMPLEMENTED_AND_VALIDATED（含反向漂移测试）
freeze-20260914-1402           = MATCH（源文件与快照一致）
flake_1_of_7                   = REPRODUCED_NOT_ROOT_CAUSED（失败断言被 tail 截断）
G1_deterministic_evidence      = VACUOUS（hash of {}；不得作为通过依据）
acceptance_summary_fields      = INCOMPLETE（缺 different_files/only_left/only_right）
post_pagefile_runtime_resource_axis = PASS（commit 最低 17,409.9 MB）
post_pagefile_formal_confirmation   = NOT_PASS（state_f 收尾 bug；D-D 静态已修，运行未验）
G1/G2/G3                       = REVALIDATION_REQUIRED
real_COMSOL_hard_stop_drill    = AUTHORIZED_WITH_INFORMED_CONSENT（受前置约束，暂不执行）
LT2 production                 = BLOCKED_BEFORE_PRODUCTION
```

## 6. 下一步（顺序不变）

```text
1. flake 根因 + G1 空证据修复 + summary 字段补全（实现方，进行中）
2. 报回最终哈希 -> 我新建 freeze_id（1402 保留，append-only）
3. 从新快照跑完整 T1–T12（测试前/后各校验一次）
4. 正式验收报告（含 Codex §8 全部字段，且确定性 manifest 非空）
5. G1–G3 关闭
6. 新 run-id 跑正常资源确认 r3（不故意触发硬线）
7. 提交 7 行/时序/LT2-C/checkpoint/身份/清理证据
8. 硬停 drill（知情同意已取得）
9. 才谈首个 LT2 生产逻辑批
```
