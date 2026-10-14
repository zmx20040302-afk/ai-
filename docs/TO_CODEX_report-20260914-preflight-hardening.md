# ② preflight 补强（COMSOL 家族显式检查 + 统一门禁 18000/21500 + 双采样）—— 待建新 freeze

- 日期：2026-09-14
- 来源：父 agent 2026-09-14 ② 裁定（依据 r3e 真实硬停：旧门禁 16,384 不足以保平台期安全）
- 基线冻结：`freeze-20260914-2230-post-f1f2f3-record-semantics`（`5e7e84e3…`）
- 状态：**代码已改 + 最小执行已完成 + 灵敏度成立 + 82 断言回归通过**；等父 agent 建新 freeze

---

## 1. 改动清单（只碰这几处，`rt_gate.py` 未动）

```text
(1) 门禁默认值：PREFLIGHT_AVAIL_MB 16384.0 → **18000.0**；PREFLIGHT_COMMIT_MB 16384.0 → **21500.0**
    （CLI 仍可 --avail-gate/--commit-gate 覆盖；覆盖值照旧写入产物 gates/gate_overridden）
(2) 新增 PREFLIGHT_DOUBLE_SAMPLE_GAP_S = 5.0（开跑前连测两次的间隔）
(3) 新增 COMSOL_BLOCKING_PROCS = ("comsolmphserver","comsolbatch","comsolcompile")  ← 在场即拒绝启动
    新增 COMSOL_GUI_ALLOWED  = ("ComsolUI",)                                        ← 在场允许，但必须记录
(4) 新增 classify_comsol_processes(procs)  —— **纯函数**（阻断项 / 允许的 GUI / 其它含 comsol 名者）
(5) 新增 comsol_process_scan()             —— 只读扫描，记录 method + 逐项 pid/name/start
(6) 重写 preflight()：两次内存采样 + 两次进程扫描；`gate_pass` = **两次都满足**
    （端口空闲 ∧ 无阻断进程 ∧ avail≥门禁 ∧ commit≥门禁）；新增 `blocked_by` 逐项原因
```
**单源说明**：`double_sample.sample1/sample2` 是两次采样的**唯一事实来源**；顶层
`system_available_physical_mb`/`commit_available_mb`/`port_free` 保留为 **sample1** 的值（兼容既有读者，
并在注释与字段名里写明）；`comsol_process_scan` 与其 `_second_sample` 各自独立（两次扫描本就不同）。

**明确未动**：`rt_gate.py`（`23ef7fdcac58e4f6…`，与 2230 冻结一致）、`Thresholds`、判定逻辑、F1/F2/F3 字段。

## 2. 最小执行：**14/14 通过**（`preflight_new.json`）

| 组 | 检查 | 结果 |
|---|---|---|
| 纯函数（合成清单，不依赖真机） | 阻断项识别（mphserver/batch/compile） | ✔ |
| | ComsolUI 不在阻断项里（单列为允许） | ✔ |
| | 其它含 comsol 名的进程如实登记（不隐藏） | ✔ |
| | 有阻断项 ⇒ `clean=False` | ✔ |
| | **仅 ComsolUI ⇒ `clean=True` 且被记录（不拒绝启动）** | ✔ |
| | 无 COMSOL 进程 ⇒ `clean=True` | ✔ |
| 活体 preflight | 可调用（位置参数兼容旧签名） | ✔（`gate_pass=true`） |
| | **门禁默认值 = 18000 / 21500** | ✔ |
| | 双采样记录（两次 + 间隔 + 差值） | ✔ |
| | COMSOL 家族扫描已记录（方法 + 清单 + 阻断名单） | ✔ |
| | 扫描覆盖两次采样 | ✔ |
| | GUI 允许名单被记录 | ✔ |
| | `blocked_by` 逐项原因已记录 | ✔ |
| | **`gate_pass` == 两次采样判据的合取（判定语义未变）** | ✔ |

活体实测（22:44 前后）：COMSOL 家族 = 空、端口 closed、avail/commit 均过 18000/21500 ⇒ `gate_pass=true`。

## 3. 灵敏度：同一套断言在**改前代码**上 **8/14 失败**

`--source` = 2230 快照（改前）。失败项（即新增能力）：`纯函数 classify_comsol_processes 存在`、
`门禁默认值 = 18000/21500`（旧为 16384/16384）、`双采样记录`、`COMSOL 家族扫描已记录`、
`扫描覆盖两次采样`、`GUI 允许名单被记录`、`blocked_by 已记录`、`gate_pass 语义可复算`。
⇒ 断言不是空断言：它能检出"这个补强没做"。

## 4. 行为不变：**判定字段逐字相同**（机械证据）

对照 = 上一轮（F1/F2/F3）的 fake-worker smoke B vs 本轮 smoke B：

```text
behaviour_equal = **true**
  status / blocked_reason / aggregate_pass_conditions / batch_size / server_lifecycle_size  全部 equal
child_record_new_fields.equal = **true**
  （worker_returncode / enforced_by / normal_completion / retry_class 等 6 项）
唯一差异：freeze_evidence / freeze_id —— 因两次用的**临时冻结 id 不同**，属预期，与判定无关。
```
⇒ preflight 补强**只加证据、不改判定**。

## 5. 回归与机械差异

```text
82 断言套件（ns-preflight-20260914-2245）：**82/82**（含 T16b --preflight-only：仍断言 rc ∈ (0,5) 且产物含 gate_pass）
机械差异 vs 2230 快照：**2 hunks / +118 行 / −16 行**
  touched_defs = [<module>, classify_comsol_processes, comsol_process_scan, preflight]
  touched_defs_outside_declared_scope = **[]**
  （首跑报越界 = 我取证器的声明范围列表没把这三个新函数算进去；补入后为 []）
  删除的 16 行 = 旧门禁两条常量 + 旧 preflight 函数体（全在声明范围内）
  patch 9,199 B  sha256 f6273c485c7b25fc43905f4cd4fc1d7556962d27d14285f79b094585b27dea18
冻结化最小执行：临时冻结 v2 `all_ok=true`、`--verify` 与 `--verify-snapshot` 均 **MATCH**（drift 0）；
  frozen smoke A/B/B2 三布尔 true + 确定性对照 exit 0；guard 两场景 exit 0；enforced_by 表 exit 0
```

## 6. 新哈希（请据此建新 freeze）

```text
work/tools/lt2_production.py
  162,186 B   c3f4540749959c72ddac424051f9795169e3f20f204827a1788dfc9e1e1ad9ad
work/tools/min_exec_r8b_evidence.py（新增 preflight 模式）
   54,247 B   41a6572606f21c7da692…（全文见 evidence_hashes.json）
work/tools/rt_gate.py  未改   11,140 B  23ef7fdcac58e4f6db675f6f8fb2ea6cdd2d63b007dc0175a5e5e0ae94844b40
临时冻结（非验收，保留勿用）：
  freeze-20260914-min-exec-preflight-v2-provisional-not-for-acceptance
  manifest 665b2042f4bdb916704bc3ab3dcc0570c21fd175830a29f9f48a165f533cebca  （source/snapshot 均 MATCH）
  注：先前那个 `…-preflight-provisional-…`（manifest 4a61819c…）在我冻结后又被编辑了取证器
      （补声明范围列表），故其 `--verify-snapshot` 报 1 项漂移；**被测件 lt2_production.py 两次相同**
      （都是 c3f45407…）。已用 v2 取代，避免留下可被误读的漂移。两者均为非验收临时冻结。
```

## 7. 文档同步（我主动做的一处，请确认）

`.dsh/skills/comsol-batch-production/SKILL.md` §3「门禁与停止线」原写
「前置 16384/16384；演练类更严 18000/21500」——与本裁定冲突，已改为**统一 18000/21500** +
「无 COMSOL 家族进程（ComsolUI 允许但需记录）+ 开跑前连测两次 + 命中清单写入产物」，
并注明废弃 16384 的**实测依据**（r3e）。若你希望技能保持原样，我回退这一处。

## 8. 下一步（按父 agent 顺序，不跳步）

```text
③ 干净条件下跑 r3e（新 run-id、显式 --freeze-id、不加 --drill、不压阈值、无并行负载、
   内存两次达标）⇒ 期望复现 r3d 的 23 条 + `warning_verdict_sample_count=0` + `blocks_next_combination=false`
④ 之后才做 `--model` 最小改动 + legacy 对拍
**不启动 LT2 生产批次**
```
