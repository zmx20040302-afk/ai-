# 裁定记录（append-only）— 2026-09-14 Codex 回复的接受、更正与执行

- 来源裁定：`TO_DEEPSEEK_HARNESS_LT2R0v2停止线裁定回复.md`（sha256 `12d0a191019a48e3f7911c220fcb910b3cdc3b3677c7c97f73133d42c735b544`）
- 性质：按 `AGENTS.md` §6「发现计划与现实不符时先记录实测事实，再改计划」的 append-only 记录。**不覆盖**任何既有文件。
- 本记录取代 `TO_CODEX_report-20260914-LT2R0v2-and-stopline-conflict.md` 中的第 1.1 节末段（跨求解不累积的推断）。

---

## 1. 状态更新

```text
LT1 numerical execution = PASS
LT1 delivery            = PASS_WITH_LIMITATIONS（v2 验收文件已生成，见 §3）
LT2-R0 v2 measurement   = PASS
LT2-R0 v2 safety gate   = FAIL
LT2 production          = BLOCKED_BEFORE_PRODUCTION
```

`PASS_CONDITIONAL` 这一含糊说法**废止**，改用上面两个正交状态。

---

## 2. 我接受的核心更正：R0 v2 的求解结构（并附我自己的复核证据）

裁定指出我把「一次含 7 频点的 `study.run()`」误述为「7 次独立求解、每次重划网格」。
**我复核后确认裁定正确**，我此前的陈述是错的。证据（`work\tools\lt2r0_v2.py` 行号）：

```text
L201  java.study("std1").feature("freq").set("plist", " ".join(f + "[MHz]" for f in FREQS))
L205  geom.run()
L207  mesh.run()
L214  java.study("std1").run()          <-- 只调用一次
L228  for i in range(len(FREQS)):       <-- 之后才用 inner=[i] 读 7 个频率的结果
```

即：几何与网格**只构建一次**，一次 study 覆盖 7 个频点。

**因此以下结论全部撤回**：

- ~~「7 个频点在同一 server 内依次求解，每次重划网格」~~ → 正确表述：一个组合只构建一次几何与网格，
  然后执行一次含 7 频点的频域 study；其资源时序中出现多次约 11 GB 的包络与回落。
- ~~「每次求解后 WS 回落至 2,630–3,566 MB，说明重划网格后内存被释放」~~ → 那些波峰可能对应
  COMSOL 内部逐频点处理，但**当前监控没有记录内部频点标签，不能把每个峰归属到某个频率**。
- ~~「漂移 +0.62% 证明跨求解不累积」~~ → 该数字只是**一次 study 内**多次包络的峰值离散度，
  不能外推到「不同参数组合之间不累积」。
- ~~「因此 4 组合共用一个 server 安全」~~ → **无效推断**。跨组合内存释放**没有任何证据**。

**接受的批大小裁定**：

```text
logical_batch_size    = 4 combinations
server_lifecycle_size = 1 combination
```

要升到 `server_lifecycle_size = 2`，必须先单独做一个「两组合共用同一 server」的生命周期试验。
在此之前我不得假设跨组合内存会被释放。

---

## 3. LT1 无重算修正的落地（修正 A / 修正 B）

**未重跑 COMSOL，未改写原始 CSV。** v1 文件哈希经复核未变
（`lt1_validated_results.csv` 仍为 `6cae2143…`，`lt1_validation_summary.json` 仍为 `f48242aa…`）。

新脚本：`work\tools\lt1_finalize_v2.py`。新产物（append-only）：

| 文件 | 字节 | sha256(前16) |
|---|---|---|
| `lt1_validated_results_v2.csv` | 11,971 | `43d5711cbb2d7141` |
| `lt1_validation_summary_v2.json` | 2,152 | `5bb36377a82d4442` |

**修正 A（判据哈希语义）**——先纠正一处事实：裁定说「报告把频率集合放进了 `invariant_criteria_hash`」。
复核实际代码：`INVARIANT` 里**本来就没有**频率，`freq_MHz` 一直在 `SWEEP_SPEC` 里；
**错的是我报告里的括号注释**（把「频率集合」写到了 invariant 名下）。代码实际拆分方向是对的。
在裁定给出的语义下仍做了实质性补强：

```text
INVARIANT  += vamp_V, Vdiff_V, units, acceptance_rules     （vamp_V 由 SWEEP_SPEC 迁入）
SWEEP_SPEC += expected_rows, server_lifecycle_size, resource_thresholds
两个 dict 都加 descriptor_revision = "v2_post_hoc_resplit_no_rerun"
```

新哈希：

```text
invariant_criteria_hash = a392cb28b22075877df140853ee018b8e8339cef7340c6cdd0fcafb0424e0b42
sweep_spec_hash         = 4f20ec678b20a6c622e361d0972cf116f55d370d890ffa55d077bd3cf34a4c6e
（v1 对照：a973de0d… / 5a036b53…）
```

哈希变化**只反映描述符重新拆分**，不代表 LT1 在旧哈希下未通过，也不触发任何重算。该事实已写入
v2 摘要的 `hash_split_change_log`。

**修正 B（selection 状态措辞）**——已完成：

```text
selection_status              = externally_supported        （不再沿用预检的 verified）
selection_verification_scope  = external_precheck_not_same_solve_run
selection_evidence_source_value = <原预检值，仅作留痕>
```

---

## 4. 原 2.5 GB 条款 → superseded

`docs\TO_CODEX_order-20260913-LT0-LT3.md` §LT2-D 的

```text
单批次峰值 server WS >= 2.5 GB -> stop
```

**已被 2026-09-14 后续裁定正式废止**，不得再据此阻塞单个正常求解；`PeakWorkingSet` 单调不减，
**只作批后审计**，不作实时信号。新实时规则以 `work\tools\rt_gate.py` 的 `Thresholds` 默认值为唯一权威：

> **落地方式说明**：该工单文件在本机带**只读冻结**属性（`IsReadOnly=True`，写入报 `ReplaceFileW EACCES`）。
> 我**没有**清除该属性去就地改写它——冻结的授权文件不应被静默修改。
> 按裁定允许的「或其正式后继版本」路线，改为新建
> `docs\TO_CODEX_order-20260914-LT2-superseding-LT2B-LT2D.md`，其中显式声明取代 §LT2-B 与 §LT2-D，
> 并保留 §LT2-A/§LT2-C/§LT2-E 继续有效。

```text
ws_warning_mb                 = 11500      （预警，不中断正常波峰）
ws_hard_stop_mb               = 12288      （连续 2 个 5 s 采样）
physical_avail_hard_stop_mb   = 4096       （连续 2 个采样）
commit_warning_mb             = 6144
commit_hard_stop_mb           = 4096       （连续 2 个采样）
physical_avail_warning_mb     = None       （Codex 未指定，显式留空，不自行发明）
```

LT2-B 的「每批 8–16 个组合」同样被后续裁定覆盖，禁止 12–16。

---

## 5. 实时中止机制（已实现并测试的部分）

| 文件 | 作用 | 状态 |
|---|---|---|
| `work\tools\rt_gate.py` | 纯逻辑实时门禁引擎（判定，不做动作） | **已实现，30/30 故障注入测试通过** |
| `work\tools\tests_rt_gate.py` | 故障注入测试（全部用模拟值，未压垮真实内存） | **已实现，退出码 0** |
| `work\tools\lt2_sampler.py` | 独立 sidecar（5 s 采样、运行期判定、完整 JSONL） | 由子代理实现中，见 §6 |
| `work\tools\lt2_production.py` | 外层 supervisor（每组合全新 server、取消/终止路径、原子 checkpoint） | 由子代理实现中，见 §6 |

故障注入测试覆盖裁定 §8 要求的全部 5 项，另加边界与语义项：

```text
T1  sampler 退出 / 尚无采样        -> hard_stop
T2  时间线停更 > 15 s（引擎 + 外层）-> hard_stop，且空档事件落盘
T3  端口被无关 PID 占用             -> 拒绝（含归属未知/期望未知两类）
T4  checkpoint 写失败               -> 可检出，且不留半写 .tmp
T5  WS 硬线必须连续 2 次；中间回落清零；11500 以下不预警
T6  commit 硬线同规则；≤6144 预警；物理可用 5000 不触发、4000 连续两次触发
T7  软线只阻止下一组合，不取消当前组合
T8  Peak WS 极高但当前 WS 正常 -> 不触发任何门禁（只审计）
```

**测试过程中的一次自纠**：T6c 初版断言「物理可用 5000 连续两次应硬停」是**测试写错**
（硬线是 ≤4096），修正为 4000 触发 + 新增 5000 不触发的边界断言后 30/30 通过。代码本身未改。

### 5.1 用真实时间线回放新门禁（新增证据）

把 R0 v2 的 **159 个真实采样**灌进新门禁引擎（不是模拟值），结果：

```text
样本数            = 159
硬停采样数        = 147
首次硬停          = 2026-09-14T09:17:30
首次硬停原因      = commit_hard_stop(747.1 <= 4096.0 x2)
去重后预警        = ['commit_warning(745.7 <= 6144.0)']
预警计数          = {commit_warning: 148}
硬停计数          = {commit_hard_stop: 147}
```

**含义（这是先改页面文件的直接理由）**：在**当前 4.9 GB 页面文件**下，采用新实时门禁后，
R0 v2 那次运行会在**求解开始约 35 秒后**（09:17:25 起求解，09:17:30 触发）就被正常取消，
159 个采样里 147 个命中 commit 硬线。也就是说：**门禁一上线，LT2 在当前配置下必然跑不动**——
不是门禁太严，而是 commit 余量真的不够。这与用户已批准的页面文件调整方向一致。

### 5.2 回放暴露并已修复的自身缺陷（T9）

首轮回放时 `warnings_seen` 累积了 **139 条同类条目**（因为预警字符串里带了具体数值，
去重按整串比较 → 每来一个新数值就新增一条）。这会让 state JSON 与报告膨胀且不可读。
已修为「**按类型去重 + 计数**」：`warnings_seen`/`hard_stops` 各只留首次出现的具体证据，
另加 `warning_counts`/`hard_stop_counts` 给出次数。新增 T9 三项断言覆盖该行为。
测试计数由 30 项升至 **33 项，全部通过**。

> 该缺陷是**用真实数据回放才发现的**，纯模拟值单测（每类只喂一个值）不会暴露它。

---

## 6. 待验证 / 已知风险（不掩盖）

1. **真实 COMSOL 下的硬线取消路径尚未实测**：`rt_gate` 的判定已测，但「硬线触发 → `client.clear()`/`disconnect()`
   → 必要时按 PID+启动时间+端口+run-id 终止 server」这条动作链**只在干跑下走过**，未在真实求解中触发过。
2. **sidecar 与 server 的 PID 归属**：`find_pid()` 用「最新启动的 `comsolmphserver`」启发式，
   `port_owner_ok` 只能校验「端口可用且 PID 等于期望值」，**不能独立证明**端口占用者就是该 PID
   （未查到可靠的 Windows 端口→PID 映射手段时不得声称已证明）。
3. **页面文件调整属系统级变更**：须用户单独明确授权，我不得自行修改或重启（见 §7）。
4. **LT2 总墙钟未实测**：15.1 h 只是同模型同环境下的线性估算；72 次独立 server 启停开销、
   不同组合耗时分布、门禁触发率都还没有数据。首批 4 组合完成后才能给出更可靠的估算。

---

## 7. 需要用户单独授权的事项

```text
pagefile_initial_size >= 12 GB   -> 系统级变更，需用户明确批准 + 可能重启
```

**若用户不批准**：不允许 16–17 h 无人值守常规批次；只能走有人值守、严格 `1 组合 / 1 server` 的保守路线，
且每次启动前实测 `commit_available_mb >= 13500` 与 `available_physical_mb >= 16384`，任一门禁不满足即不启动。

---

## 8. 执行顺序（按裁定 §9）

```text
[x] 1. 无重算修正 LT1 判据哈希语义 + selection_status        （§3 已完成）
[x] 2. 修复 pass_conditions、实时 supervisor、完整事件落盘     （已完成：rt_gate + lt2_sampler + lt2_production；
                                                              commit 项已进 combo 级与批次级验收）
[x] 3. supervisor 故障注入测试                                （rt_gate 33/33 通过 + 四场景干跑 all_scenarios_passed）
[~] 4. 页面文件系统级调整授权                                  （用户已批准；但本进程非管理员，尚未执行/重启）
[ ] 5A/5B. 批准 -> 调整重启 + (0.8,2) 资源确认 / 拒绝 -> 有人值守保守路线
[ ] 6. 满足门禁后运行首个 4 组合逻辑批
[ ] 7. 提交 4 个独立 server 生命周期的结果、资源、清理与哈希
[ ] 8. 再决定是否做「两组合 / 一 server」试验
```

### 8.1 实现交付与独立核验（2026-09-14）

| 文件 | 字节 | sha256(前16) | 引用时刻 |
|---|---|---|---|
| `work\tools\lt2_sampler.py` | 10,594 | `cf4b0690b26504a3` | 2026-09-14 12:35 |
| `work\tools\lt2_production.py` | 62,503 | `5b311deb1ade1ea4` | 2026-09-14 12:35（含 run-id 复用防呆；旧版 57,323 B / `98b64c2e…` 已作废） |

> 哈希按「引用时刻」标注，不当作稳定常量（见 `TO_CODEX_record-20260914-supervisor-implementation.md` §7）。

由子代理实现；**父代理已独立复核**：哈希自算一致；现场 `comsolmphserver 0 / comsolbatch 0 / 端口 2036 CLOSED`；
`--dry-run` 由父代理**自己重跑**得 exit 0 与相同四场景计数；缺陷 D1 由父代理**读代码**确认
（`combo_pass_conditions` L504 `commit_hard_stop_samples_0`、L505 `min_commit_gt_4096`；批次级 L1009/L1012）。

架构：三进程（supervisor → 每组合一个 combo-worker 全新进程 → sampler sidecar），
起因是「MPh 单会话单 client」约束与「每组合一个全新 server」授权无法在单进程内共存。
`import mph` 只在 worker 分支（L609），模块加载时不 import。

### 8.2 升级给 Codex 的阻塞项

两个 commit 门禁在当前配置下**互斥**：前置 `≥13,500` 高于本机 commit 理论上限 **11,759.6 MB**
（0/159 采样满足），运行期 `≤4,096 硬停` 又必然触发（147/159）。
详情与推导见 `docs\TO_CODEX_escalation-20260914-commit-gates-mutually-exclusive.md`。

### 8.3 不存在的「并发写入者」（更正子代理误报）

子代理曾报工作区有第三方并发改写 `rt_gate.py`。经查**是父代理自己的编辑**
（创建 12:20:28 → 编辑 12:24:18，内容为 `warnings_seen` 去重 + T9，测试 30→33）。
无第三方写入者，不需追查。

第 6 步之前保持 `LT2 = BLOCKED_BEFORE_PRODUCTION`。
