# 记录：r3h —— 新代码在**真实生产路径**上的背书（A/B/C/F5 全部首次生效）

- 时间：2026-09-15 11:21
- run_id：`lt2-resource-confirm-x080-n02-r3h-post-f5-t1t2`
- 冻结点：`freeze-20260915-1055-post-f5-t1t2-abc-records`（manifest sha256 `e76538b7116b6faa0fb80d7d6a6f8ae9b643151ac7748b09f84f0e7a7ccc74f0`，15 文件）
- 执行体：从**快照**执行 `…\snapshot\lt2_production.py`（`script_sha256 = 9d42cdd7371661b4`）
- 结果：**exit 0 / status PASS / 816.9 s**；检查器（冻结版，sha256 `5ed0228ee1d031eb…`）**25/25**

## 1. 启动前门禁（与 r3g 同口径）

| 项 | r3h | 门禁 | r3g（对照） |
|---|---|---|---|
| 可用物理内存（双采样 5 s） | 19561.6 → 19434.4 MB | ≥ 18000 | 21252.6 MB |
| 可提交（双采样 5 s） | 26040.4 → 25975.8 MB | ≥ 21500 | 26980.9 MB |
| COMSOL 家族进程 | 无 | 必须无 | 无 |
| 端口 2036 | CLOSED | 必须关 | 关 |

## 2. 本轮新代码独有的四项，**首次在真机上生效**

| 项 | 期望 | r3h 实测 |
|---|---|---|
| **B 改名**：正常收尾记录落哪个文件 | 只有 `completion_record.json`，**不得**有 `termination_trigger.json` | child 目录 8 个文件：`checkpoint.json`、**`completion_record.json`**、`raw_rows.csv`、`resource_timeline.csv/.jsonl`、`rows.csv`、`sampler_state.json`、`worker_state.json`；`termination_trigger.json` **不存在** ✅ |
| B 记录内容 | `termination_performed=false`、`enforced=false`、`trigger_kind=normal_completion_sidecar_exit` | 三者全部符合 ✅ |
| **C 字段分离** | `blocked_reason` 与重跑字段分列 | `blocked_reason=None`；`retry_class=None`、`retry_reason=None`、`auto_retry_attempted=False`（**独立字段**）✅ |
| **F5 形状** | 计数在 checkpoint 顶层、`pass_conditions` 只放布尔 | `hard_stop_verdict_sample_count=0`、`warning_verdict_sample_count=0` **在顶层**；`pass_conditions` 13 项**全布尔全 True**；`pass_condition_shape_violations=[]` ✅ |

## 3. 其余逐项（全部符合）

```text
child status = pass ; rows = 7 ; attempt = 1 ; worker_returncode = 0 ; solve_error = None
生效阈值 = ws_hard 12288.0 / commit_hard 4096.0；provenance{drill:false, overrides:{}}，defaults == effective
资源 = peak WS 11328.4 < 12288；commit 最低 9904.2 > 4096；物理可用最低 8151.4 > 4096
      时间线 159 行；>15 s 空档 0；stop_line_event_count = 0
收尾 = port_open_at_end=false；port_closed_within_30s=true；sampler_returncode=0；blocks_next_combination=false
失败分类 = retry_classification{retry:false, class:normal_completion}；enforced_by=null；failure_stage=closed
三个冻结布尔 = 全部 bool True；pre MATCH / post MATCH，drift 0/0，pre_post_files_identical=true
aggregate_pass_conditions = 11 项全布尔全 True
V_ref_abs = null（7/7，未回填）
```

## 4. 第四个重复点：**四份不同代码，物理数值逐字节相同**

r3d / r3f / r3g / r3h 跑的是**同一组合 `(0.8, 2)` × 7 频点**，但 `script_sha256` 四个都不同：

| run | script_sha256（前16） | status | solve_s |
|---|---|---|---|
| r3d | `81936aeb0b5d42cb` | pass | 763.8 |
| r3f | `c3f4540749959c72` | fail_or_limited | 744.5 |
| r3g | `f73549f4d816f11f` | pass | 768.5 |
| **r3h** | **`9d42cdd7371661b4`** | **pass** | **762.9** |

20 个物理字段 × 7 频点 × 3 个对照组 = **420 个比对单元，逐字节（`repr`）0 处不一致**；
唯一差异仍是 `solve_seconds`（墙钟量）。`frozen_signature_sha256` 四者同为 `b26193fea3f56a6e`。

⇒ ① 求解数值跨 4 次独立运行可复现；② 本轮 F5 / A / B / C 四类改动**没有触碰物理与提取路径**
（这是一次天然的四方对照，无需另造受控实验）。

## 5. 冻结点在运行后仍然干净

```
--verify          freeze-1055 : MATCH / drift_count 0 / exit 0
--verify-snapshot freeze-1055 : MATCH / drift_count 0 / source_drift_count 0 / exit 0
```

⇒ r3h 之后 `work/tools` 与快照**都没有漂移**，该冻结点是干净的，可直接用于后续批次
（这与 freeze-1015 形成对比：1015 在 r3g 之后被后续修复改动而作废）。

## 6. 之后做了什么

r3h 通过后，按用户选择启动**小批试探**：`lt2-prod-trial4-combo-20260915`，
组合 = `(0.6,4) (0.7,5) (0.45,6) (0.75,5)`（= Codex 指定的 4 个精扫候选，也是生产工具默认值），
4 × 7 = **28 点**，同一冻结点、同样从快照执行。目的：在投入 72 组合 × 7 频（约 15–17 h）
之前验证批量编排、逐组合隔离与产物完整性。

## 7. 产物

| 文件 | 说明 |
|---|---|
| `work\runs\lt2-resource-confirm-x080-n02-r3h-post-f5-t1t2\` | r3h 运行产物（child_00_attempt_1 + batch_manifest.json） |
| `work\runs\_evidence-r3h\r3h_argv.txt` / `r3h_timing.txt` / `r3h_stdout.log` | 命令、时序、完整 stdout |
| `work\runs\_evidence-r3h\r3h_checker.json.txt` | 冻结版检查器 25/25 原始输出 |
| `work\runs\_evidence-r3h\freeze_verify_after.txt` | 运行后冻结点双向校验原始输出 |
