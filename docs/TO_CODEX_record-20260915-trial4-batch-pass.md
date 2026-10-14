# 记录：小批试探 lt2-prod-trial4-combo-20260915 —— 4 组合 / 28 点全通过

- 时间：2026-09-15 12:02（START 11:22:05 → END 11:55:36，**2011 s = 33.5 min**）
- run_id：`lt2-prod-trial4-combo-20260915`
- 冻结点：`freeze-20260915-1055-post-f5-t1t2-abc-records`（15 文件；运行前后均 MATCH）
- 执行体：从**快照**执行，`script_sha256 = 9d42cdd7371661b4`
- 结果：**exit 0 / status PASS / children 4 / rows 28**

## 1. 为什么跑这一批

在投入 72 组合 × 7 频（504 点、按实测约 10 小时）之前，用**最小的可判定批量**验证：
批量编排、逐组合证据隔离、产物完整性、以及"每个组合都走正常收尾"这条新记录纪律。

组合取生产工具的默认值 `(0.6,4) (0.7,5) (0.45,6) (0.75,5)` —— 即 Codex 指定的 4 个精扫候选，
也都是合格 72 组内的点。4 × 7 = **28 点**。

## 2. 逐组合实测（4/4 全部 pass）

| child | combo | status | rows | `completion_record.json` | `termination_trigger.json` | pass_conditions | 阈值 | 时间线 | peak WS | commit 最低 | avail 最低 | 停止线事件 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 00 | `(0.6, 4)` | pass | 7 | ✅ | ❌ | 13/13 全布尔全 True | 12288 | 91 | 8034.0 | 14218.5 | 11205.0 | 0 |
| 01 | `(0.7, 5)` | pass | 7 | ✅ | ❌ | 13/13 全布尔全 True | 12288 | 121 | 9433.5 | 11157.1 | 8105.5 | 0 |
| 02 | `(0.45, 6)` | pass | 7 | ✅ | ❌ | 13/13 全布尔全 True | 12288 | 57 | 6232.0 | 16535.3 | 13636.7 | 0 |
| 03 | `(0.75, 5)` | pass | 7 | ✅ | ❌ | 13/13 全布尔全 True | 12288 | 120 | 9739.5 | 14625.1 | 10451.1 | 0 |

四者共同项：`pass_condition_shape_violations=[]`；两个计数**在 checkpoint 顶层**且为 0；
`thresholds_provenance{drill:false, overrides:{}}`；`worker_returncode=0`；`solve_error=None`；
`retry_classification{retry:false, class:normal_completion}`；时间线 >15 s 空档 0。

**资源上界**：峰值 WS 最高 9739.5（硬线 12288，余量 21%）；commit 最低 11157.1（硬线 4096）；
物理可用最低 8105.5（硬线 4096）⇒ 四个组合都在门禁内有充裕余量，**没有一次越线**。

## 3. 批量级核对

```text
status=PASS；children=4；blocked_reason=None
combos_requested == combos_delivered == [[0.6,4],[0.7,5],[0.45,6],[0.75,5]]
batch_size=4（在允许集合 [4,6,8] 内，不属禁止集合 12–16）
aggregate_pass_conditions = 11 项全布尔全 True
freeze_hash_pre_post_match / executed_from_frozen_snapshot / freeze_evidence_complete = 全 bool True
freeze pre=MATCH post=MATCH，drift 0/0，pre_post_files_identical=true，manifest sha256 e76538b7116b6faa…
retry_class=None / retry_reason=None / auto_retry_attempted=False（**独立字段**，未与 blocked_reason 混写）
合计 rows = 28（= 4 × 7，与期望一致）
证据隔离：4 个 child 目录各自 8 个文件，命名 child_00..03_attempt_1，无交叉、无复用
```

## 4. 交叉核对：与 LT1 反相基线**逐字节一致**（本轮最强的外部验证）

LT1 反相 15 点（`work\runs\lt1-reverse-sample\lt1_validated_results_v2.csv`）覆盖 5 个组合 × 3 频（5/20/35 MHz），
其中 4 个组合与本批**完全重叠**（`(0.6,4) (0.7,5) (0.45,6) (0.75,5)`）⇒ **12 个可比点**。

| 项 | LT1 基线 | 本次小批 |
|---|---|---|
| 产出时间 | 2026-09-14 | 2026-09-15 |
| 脚本 sha256 | `919eb3a84f1dfb0a…` | `9d42cdd7371661b4…` |
| 模型 sha256 | `cbe9ccc18e51005f…` | `cbe9ccc18e51005f…`（同） |
| 执行路径 | LT1 自算管线 | LT2 生产路径（冻结快照 + 三进程架构） |

逐字节比对 **10 个字段（Ptot_W / Vave_mps / Ptot_norm / Vave_norm / V_center_re / V_center_im /
V_outer_re / V_inner_re / V_ref_abs / Vdiff_abs）× 12 个点 = 120 个单元，0 处不一致**。

⇒ 新生产路径与更早、独立脚本、不同日期产出的反相基线**完全一致**：
既是求解可复现性的再一次证明，也说明本轮 A/B/C/F5 一系列改动**没有改变任何物理量**。

## 5. 与"全量 504 点"的关系（供决策）

- 实测节奏：2011 s / 4 组合 = **约 503 s ≈ 8.4 min/组合**（含建模、求解、收尾、端口关闭）。
- 全量 72 组合（合格 72 组 = 9 档 x_scale × N1 1..8）预计 **约 10.1 小时**（若含重试与波动，留 11–12 h）。
  比早先"15–17 h"的估计更乐观——该估计来自单组合 13–14 min 的旧样本，本批实测更快。
- 资源余量：本次 4 个组合峰值 WS 最高 9739.5 / commit 最低 11157.1 ⇒ 全程**无人值守**是可行的，
  但仍需机器在整段时间内不被其它重负载占用（否则会触发前置门禁拒启或运行期软线告警）。

## 6. 产物

| 文件 | 说明 |
|---|---|
| `work\runs\lt2-prod-trial4-combo-20260915\` | 4 个 child 目录（各 8 件）+ `batch_manifest.json` |
| `work\runs\_evidence-trial4\trial4_argv.txt` | 完整命令行 |
| `work\runs\_evidence-trial4\trial4_timing.txt` | START/END/exit/耗时 |
| `work\runs\_evidence-trial4\trial4_stdout.log` | 完整 stdout（含冻结核验与 RESULT） |
