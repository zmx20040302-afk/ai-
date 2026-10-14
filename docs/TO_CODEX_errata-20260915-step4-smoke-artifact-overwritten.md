# 勘误：第 4 步交付目录被我（复核方）误覆盖一处产物

- 时间：2026-09-15 11:45
- 性质：**复核方的操作事故**（不是实现者的问题），append-only 登记
- 影响面：`work\ai-solver\step4\raw\smoke.json` 与 `work\ai-solver\step4\manifest.json` 两个文件的字节，
  以及报告正文里引用的这两个哈希
- 实质结论：**不受影响**（见 §4）

## 1. 发生了什么（按真实时序）

| 时刻 | 动作 | 结果 |
|---|---|---|
| ~11:30 | 我核对 `manifest.json` 的 32 件 | **32/32 全部匹配**（当时报告与磁盘一致） |
| ~11:35 | **我在交付目录内**直接跑了 `smoke_step4.py` 做独立复核 | 它把自己的输出写回 `raw\smoke.json` ⇒ 覆盖了实现者那一份 |
| ~11:40 | 我发现 `manifest.json` 与磁盘不符，遂**连跑两次** `assemble` 让 manifest 重新对齐 | manifest 更新为与磁盘一致；顺带证明 assemble 确定性 |
| ~11:45 | 全量核查并登记本勘误 | 见下 |

## 2. 具体哈希变化（实测）

| 文件 | 报告里引用的（= 实现者交付的） | 现在磁盘上的 |
|---|---|---|
| `work/ai-solver/step4/raw/smoke.json` | 8,436 B / `1d1701f3636a16180b1595b29ba98a2f64830e4973c58ec1604b42576edcb411` | 8,544 B / `57bca71166906b35094ddabeae0f2daf43d909f2d5b8c37b55464b197b9279b7` |
| `work/ai-solver/step4/manifest.json` | `9ac4855a7055247d41b876263c86b1b722c74ea3b4b3bd23cb36c772ee30d23c` | `b29b34972d2acc1ee1e84e1a17573f0d3323cb26a71fb64d81f995eb66e37cb0` |

报告里受影响的引用位置：`docs\TO_CODEX_record-20260915-ai-solver-step4-single-electrode.md`
**第 470 行**（§ 冒烟自测）与**第 577 行**（§6 产物表）、**第 552 行**（manifest 哈希）。
报告文件本身**未被改动**（48,866 B / `e7786aacf71954f7cb349f5a70b362633819f3837f49fefbe7029e53157b734f`），
其正文里**除这三处哈希外**的每个数字仍然有效。

**原字节不可恢复**：`smoke.json` 含墙钟耗时（"ALL PASSED = True (7.5s)" 之类），
按 `AGENTS.md` §3④ 这类产物本就**不可逐字节复现**；备份是在覆盖**之后**才做的，故不含有旧字节。
这是本次事故里唯一**真正丢失**的东西。

## 3. 为什么说实现者没有问题

- 事故前我已完成核对：**manifest 32/32 全部匹配**、报告哈希 `e7786aac…` 匹配、`step4_report.json` 等关键件匹配。
- 覆盖动作由我发起、且发生在**交付目录内**；实现者的产物在其交付时刻是自洽的。
- 由此新增一条通用纪律（已写入技能 `freeze-and-acceptance` §8 踩坑 11/12）：
  **不要在交付目录里运行交付物自带的测试脚本——要复跑先把整目录复制到 scratch。**

## 4. 实质结论为何不受影响

1. `smoke_step4.py` 的**通过数没变**：18 项全过、exit 0（我这次是**独立复跑**，7.5 s）。
   被覆盖的是**同一次冒烟测试的又一次运行结果**，检查项与判定逻辑完全一致。
2. 该文件**不参与**任何科学结论：误差表、保形覆盖率、拒答、S 级判定、`models_frozen.json`
   的哈希**均未变化**（见 §5 的复核）。
3. `manifest.json` 的新版本**对磁盘逐件核对通过（32/32）**，即"当前磁盘是自洽的"这一条仍然成立。

## 5. 事故后的完整复核（本轮独立验证的总账）

| 检查 | 结果 |
|---|---|
| `manifest.json` 逐件核对（路径+字节+sha256） | 事故前 **32/32**；事故后重新生成 **32/32** |
| 报告文件哈希 | 48,866 B / `e7786aac…` **与声明一致** |
| 保形认证计数（我自行统计 `raw\conformal_scores.csv` 167,328 行） | (场景×目标×模型×折) 实例 **328/328 全部 `certified=True`**，**0 个 False**；校准点数 64/72/153 均 ≥ 9 |
| `conformal_quantile` 门槛（我直接用平台函数复现，不看实现者结论） | m=4/6/8 ⇒ `inf`；**m=9 起**才有限 ⇒ 与技能 §4 的 9 点门槛一致；产物表 m≤8 认证 0/8、m≥9 认证 8/8 |
| 有效 OOD 切分 | `splits.csv` 9 行中**只有两条 `cross_family_holdout`** 的 `valid_cross_family_ood=True`，其余 6 条 False |
| 正定性守门扫描 | `domain_guard_scan.csv` 17 行自洽：V2 M1/V2/M3 = 7.84% / 16.20% / 9.38%（2142 点）；V1 为 6.30% / 3.89% / 7.04%（952 点）⇒ 报告头条用的是 **V2** 口径，报告已如实标注 |
| S3 | `s3_report.json`：`verdict=failed`、`n_checks=5 / n_failed=1 / n_inconclusive=4`、`release_allowed=false`、阈值**原样取自技能**（未改） |
| 拒答 API（我独立复跑 `smoke_step4.py` 的那次运行） | 前 7 类全部拒答、域内正常出解、`S3 release_allowed=False`、`surrogate.score` 可复用 ⇒ **ALL PASSED=True** |
| `assemble` 确定性（**新增证据**） | 同一代码连跑两次：**39/39 件逐字节相同** ⇒ 实现者的"连跑两次逐字节相同"**成立** |
| 越界写入 | `work\tools` / `src` / `work\models` 在 10:56 之后**新增写入 0 个** |

**一处必须同时登记的旁证（不是本次事故）**：`work\tools\__pycache__\*.pyc` 里有若干 10:32:41–10:32:53 的
文件（含 `lt2_production`、`check_r3_conditions`、`freeze_snapshot`、`tests_lt2_supervisor`），
时间落在**上一轮 LT2 实现者**的三向对照测试窗口（10:24–10:33）内 ⇒ 该轮存在未加 `-B` 的 import 残留。
它**不影响** `freeze-20260915-1055`（冻结只看 `work/tools` 源文件与快照目录内的文件集合，
且生产运行从快照执行、带 `-B` + `PYTHONPYCACHEPREFIX`），但应按卫生要求清理并注意归档规则。

## 6. 事后处置

1. 保留当前磁盘状态（`smoke.json` 新版 + 与之自洽的 `manifest.json`），**不回滚**：
   回滚 manifest 会让它与磁盘重新不一致，反而制造第二个错误。
2. 报告正文**不改**（append-only），本勘误即为其哈希引用的更正声明。
3. 技能 `freeze-and-acceptance` 新增踩坑 11/12（"别在交付目录里跑交付物的测试脚本"、"复跑 assemble 后必须重核 manifest"）。
4. 记录在 `docs\INDEX-records-and-rulings.md` §4 勘误表与 §13。
