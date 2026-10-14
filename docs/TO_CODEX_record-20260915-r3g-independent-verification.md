# 记录：r3g 独立复核（PASS 已确认 + 3 项非阻塞缺陷）

- 时间：2026-09-15 10:35
- 复核人：独立复核（**非**实现者；实现者正在做 T14 确定性修复）
- 对象：`lt2-resource-confirm-x080-n02-postpagefile-r3g`
- 冻结点：`freeze-20260915-1015-post-f2-counter-fix`（manifest sha256 `c653430ee2145378cdd9d8b6140432be075dc8b62f14291d3ecc76feb7767000`）
- 结论：**PASS_CONFIRMED**（r3g 的通过结论成立）；另发现 3 项缺陷，**均不影响 r3g 自身**，但必须在下一个 freeze 前修掉。

## 1. 已独立确认（逐项，均为我直接读字节/复跑所得）

| 检查项 | 期望 | 实测 | 结论 |
|---|---|---|---|
| child 状态 | `pass`（F4 修复目标） | `pass` | ✅ |
| rows | 7 | 7（5/10/15/20/25/30/35） | ✅ |
| `pass_conditions` | 全布尔、全 True | 13 项，非布尔 0 项，全 True | ✅ |
| `pass_condition_shape_violations` | 空 | `[]` | ✅ |
| 计数位置 | 顶层，**不在** `pass_conditions` | `hard_stop_verdict_sample_count=0`、`warning_verdict_sample_count=0` 均在顶层 | ✅ |
| 计数非空集 | 有真实采样 | 时间线 160 行 / sampler `sample_index=161` | ✅ |
| 生效阈值 | 12288 | `ws_hard_stop_mb=12288`（F1 修复） | ✅ |
| 阈值出处 | 单源 | `provenance{drill:false, overrides:{}}`，defaults == effective | ✅ |
| `stop_line_event_count` | 非演练应为 0 | 0 | ✅ |
| 资源裕度 | 远离硬线 | WS 峰 11377.2 < 12288；commit 最低 7372.5 > 4096；物理可用最低 6518.2 > 4096 | ✅ |
| `lt2c_quick_gate` | 全 True | 18 项全布尔全 True | ✅ |
| 收尾 | 干净 | sampler rc=0、port_open_at_end=false、30 s 内关端口、worker rc=0 且已记录 | ✅ |
| 正常收尾语义 | 未 enforce | `trigger_kind=normal_completion_sidecar_exit`、`enforced=false`、`termination=null`、`retry=false/normal_completion`、`blocks_next_combination=false` | ✅ |
| 三个冻结布尔 | 均为 `bool True` | 三项均为 `bool True`；pre/post 均 MATCH，drift 0 | ✅ |
| 前置门禁 | 18000/21500 连测两次 | 21252.6/26980.9 → 21235.0（间隔 5 s），两端口均空闲 | ✅ |
| 验收检查器复跑 | 23/23 | 我独立复跑：23/23、`all_pass=True`、exit=0（`checker_rerun_stdout.txt`） | ✅ |
| `V_ref_abs` | 不得回填 | 7 行全为 `null` | ✅ |

### 1.1 跨运行数值可复现 + F4 修复的三方对照（本轮最有价值的一条）

三个 run 是**三份不同 script_sha256** 的代码，跑同一组合 `(0.8, 2)` × 7 频：

| run | script sha256（前 16） | child 状态 | solve_s |
|---|---|---|---|
| r3d | `81936aeb0b5d42cb` | pass | 763.8 |
| r3f | `c3f4540749959c72` | **fail_or_limited**（F4 缺陷在场） | 744.5 |
| r3g | `f73549f4d816f11f` | **pass**（F4 已修） | 768.5 |

对 20 个物理字段 × 7 频 × 3 run = **280 个比对单元，逐字节（`repr`）全部一致，0 处不一致**；
唯一差异是 `solve_seconds`（墙钟量：763.8 / 744.5 / 768.5，本就不可复现）。`frozen_signature_sha256` 三者同为 `b26193fea3f56a6e`。

由此同时得到两件事：

1. **求解数值跨运行可复现**（不是"跑很多次没复现"，是逐字节相等）；
2. **r3f → r3g 的状态翻转可归因于记账修复**——物理量一字未动，状态却由 fail 变 pass ⇒ 该修复没有触碰物理/提取路径（天然的三方对照）。

## 2. 发现的缺陷（均不阻塞 r3g）

### F5（高）空集/缺证据仍判通过：4 个资源条件在「时间线为空」时返回 True

**实测**（冻结快照内纯函数探针 `vacuity_probe.py`，exit=0；探针前后快照三文件哈希仍等于 manifest、目录清单未变）：

```
### A_空时间线_key齐全
    monitoring_ok                    True     ← 空证据判通过
    peak_ws_lt_hard_stop             True     ← 空证据判通过
    commit_hard_stop_samples_0       True     ← 空证据判通过
    min_avail_ge_hard_stop           False    ← 对照：正确 fail-closed
    min_commit_gt_hard_stop          False    ← 对照：正确 fail-closed
### D_no_hard_stop_verdict_samples
    hard_stop_verdict_sample_count   0
    no_hard_stop_verdict_samples     True     ← 空列表 ⇒ 0 ⇒ True（只有读异常才是 None）
```

源码位置（`snapshot/lt2_production.py`）：`L1036-1037`（`monitoring_ok` 只看"没有 gap/missing 列"）、`L1041`（`or 0`）、`L1045`（`.get(..., 0)`）、`L1522-1531`（空列表 ⇒ 0）。

**为什么要紧**：项目不变量明列「空集必须判失败」。这 4 项是"资源有没有越线"的唯一布尔证据；一旦采样器写出空/截断时间线，它们会**集体判通过**，把"没测到"当成"没越线"。同函数的 `min_avail_ge_hard_stop` / `min_commit_gt_hard_stop` 已显式要求 `is not None` ⇒ 标准是清楚的，只是这 4 项漏了。

**r3g 不受影响**：时间线 160 行、键齐全、数值远离硬线。

**修法**：四项一律改成"显式非空证据 + 阈值判定"（如要求 `timeline_rows >= 1`、`server_peak_ws_mb is not None`、`commit_hard_stop_samples is not None`），并补**负向测试**：构造空时间线断言 `status != pass`，且该断言必须在旧代码上**失败**（否则是无敏感性测试）。

### T1（中）`--verify-snapshot` 把「源文件漂移」误报为 `SNAPSHOT_CORRUPTED`

`work/tools/freeze_snapshot.py` 的 `_compare()` 第一个循环（L198-206）**无条件**比较 `e["path"]`（即 `work/tools` 源文件），不看 `mode`；快照比对在 `mode=="snapshot"` 分支内（L207+）。于是：

```
--verify          → INVALIDATED_BY_CODE_DRIFT, drift 3, exit 1
--verify-snapshot → SNAPSHOT_CORRUPTED,        drift 3, exit 1   ← verdict 名是错的
```

而**直接量测**证明快照完好：`lt2_production.py=f73549f4…`、`tests_lt2_supervisor.py=d85622df…`、`min_exec_r8b_evidence.py=0fe3615d…`，三者**均等于 manifest**，且 mode `0o444`；源文件 mtime 为 10:24:04 / 10:24:17 / 10:25:29，**全部晚于 r3g 结束时间 10:23:05**（后续修复所改）。

**为什么要紧**：只要源文件有后续编辑，`--verify-snapshot` 就永远失败，还给出"快照已损坏"这一**错误**结论，会诱导放弃本来有效的运行。

**修法**：`mode=="snapshot"` 时第一循环改用 `snapshot_path`/`snapshot_sha256`；源漂移在快照模式下作为独立字段报告，不并入同一 verdict。

### T2（中）验收检查器不在冻结集合内，产物也不自证用了哪一版

- 快照 13 个文件中**没有** `check_r3_conditions.py`（它不在 `freeze_snapshot.py` 的 AUX 组里）；
- 检查器产物顶层键 `["conditions","evidence","missing","run_dir","run_id","summary"]`，**不含**自身 sha256。

即：冻结点把"被测版本"钉死了，却把"判据的执行者"留活了。同一份 r3g 产物换一版检查器就能得到不同结论，而证据无法自证。

**修法**：(a) 把 `check_r3_conditions.py` 加入 AUX；(b) 证据顶层加 `checker_sha256`/`checker_argv`/`checker_exited`。
（本次我复跑用的检查器 sha256 = `01e4dbb088e18f6d41d75f770f9de0bed6e77038dea012415abc8b379b39a0a3`。）

### T3（信息）freeze-1015 已被源漂移作废，不可再用于新运行

r3g 自身的冻结证据**有效**：pre 10:09:25 MATCH、post 10:23:05 MATCH，把整个运行夹住了。但源文件在运行**之后**（10:24 起）被改 ⇒ 按 manifest 自带规则，该 freeze_id 不能再用作新运行的依据；后续（T14 等）必须新建 freeze_id 并从 snapshot 执行。

## 3. 本轮我做了什么 / 没做什么

- 只读复核：直接读 r3g 产物字节、batch_manifest、checkpoint、resource_timeline；独立复跑验收检查器；在冻结快照内以 importlib 调用纯函数做空集探针（**未修改快照**，探针后三文件哈希仍等于 manifest、目录清单不变）。
- **未**修改 `work/tools` 下任何文件；**未**跑 COMSOL；**未**写入或覆盖 r3g 与实现者的任何产物目录；**未**复用任何既有 run_id。

## 4. 产物

| 文件 | sha256 |
|---|---|
| `work/runs/_evidence-r3g-independent-verify/independent_verify.json` | `3b35dfc003a270d10670cc79d7c45b5d15bc6fe2c60e732ddff5382db5cf44b8` |
| `work/runs/_evidence-r3g-independent-verify/vacuity_probe.py` | `cce9f12a5281cc138594d73926aeee858fea8d83ab6bfc15e44cf2ed98528d7e` |
| `work/runs/_evidence-r3g-independent-verify/checker_rerun_stdout.txt` | `fe6364bfb7b70fec1cba2984586acc44a4aa8e8adf248d3cdfc3360e6283524b` |
| `work/runs/_evidence-r3g-independent-verify/freeze_verify_stdout.txt` | `e8a8ace51f155b50f4e5a1d7b21f0efd0edf63cf034078dc5108a000764baf02` |

## 5. 建议的下一个 freeze 需要包含

1. F5 四项的空集防护 + 负向测试（必须在旧代码上失败）；
2. T1 快照模式比对口径修正（或 verdict 拆分）；
3. T2 把 `check_r3_conditions.py` 纳入 AUX 并在证据里自证哈希；
4. 实现者已承诺的 T14 确定性修复（`termination_trigger.json` 命名/`blocked_reason` 拆分）——注意 T14 改动本身就会再次漂移 `lt2_production.py`，属预期。
