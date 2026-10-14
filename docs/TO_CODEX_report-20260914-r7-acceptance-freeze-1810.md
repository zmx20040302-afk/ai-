# TO CODEX — R7 无 COMSOL 正式验收报告（freeze-1810）

- 报告性质：**append-only**；本文件不改写任何既有文件（1423 报告、R6/R7 记录、历史 run 目录均原样保留）
- 验收对象冻结：`freeze-20260914-1810-post-atomic-retry`
- 验收性质：**无 COMSOL**（`comsol_started=false`、`mph_imported=false`，测试前后均无 `comsolmphserver`）
- 父 agent 已独立复核并据此关闭 `G1 = CLOSED_FOR_FREEZE_1810`

---

## 1. 冻结标识

```text
freeze_id        = freeze-20260914-1810-post-atomic-retry
freeze 目录      = work\runs\lt2-supervisor-acceptance-freeze-20260914-1810-post-atomic-retry\
manifest_sha256  = 7ca99929906eb6d8015d8f961a85e56127e5348ff135a569c98b4c56dbe30d5d
three_way.all_ok = true
window_drift     = []          status = ACTIVE
只读快照         = 12 个文件（3 targets + rt_gate 依赖 + 8 acceptance_aux）
```

被验收文件（完整 SHA256）：

| 文件 | bytes | SHA256 |
|---|---|---|
| `lt2_production.py` | 122,900 | `cf599afd540f627989e39743dd6c062dacb13fcc5784c543ce7412097bb7fc83` |
| `lt2_sampler.py` | 15,668 | `7700e3eb4a56f49f1a57b3f07952fbe56de3acb25c78d6a7fe5a2f206d547abd` |
| `tests_lt2_supervisor.py` | 64,765 | `d85622df5d0b58e86028c8845421705a70717cf24389cc89bac63732d206cc38` |
| `rt_gate.py` | 11,140 | `23ef7fdcac58e4f6db675f6f8fb2ea6cdd2d63b007dc0175a5e5e0ae94844b40` |
| `lt2_acceptance_r4.py` | 29,767 | `89030f7975ef48d4e9ec672a93f7501965adfffc1cb2a3781af4a4a94b533f62` |
| `check_undefined_names.py` | 6,780 | `991671656d109032c19fe59a681531da7ada50a556278b874b13c33239e42a5e` |
| `lt2_flake_hunt.py` | 7,700 | `029e8addd25a4aa1755d0a69e7dc0f31840ac02ca65d08288e4d6aadb89c598a` |
| `lt2_expected_inventory.json` | 4,340 | `4efbbf93c92f055c88f4b212ca21c9cbeb287df4da7bb0ebb686b00be33b6364` |
| `lt2_conc_tests.py` | 8,583 | `d563ebbc8bc2b03a7fe00d4ed96ff2c66ad768b97c1d24b545ad44e0cdc7e32f` |
| `tests_rt_gate.py` | 9,455 | `d15dddc0d9c33c3e52c7a76542927607ccd80476f749caade2f56f849ae6febc` |
| `repro_b_sampler.py` | 6,398 | `f1311d7f7e1016a7bfd1bc8f2f5483cf48aa9cb4f174f8004a542c77addcd1cb` |
| `test_atomic_retry.py` | 4,252 | `ce9b7f57fd1bb295380ad2a8fb804dd4ffd0fc1563adc5f02ef5f97d2b2e1331` |

---

## 2. 跑前/跑后四项冻结校验

```text
--verify freeze-20260914-1810-post-atomic-retry          mode=source-vs-manifest,
        drift=[], drift_count=0, verdict=MATCH           checked_at=2026-09-14T18:29:41
--verify-snapshot freeze-20260914-1810-post-atomic-retry mode=snapshot-vs-manifest,
        drift=[], drift_count=0, verdict=MATCH           checked_at=2026-09-14T18:29:41
        snapshot_added_untracked 为空、无被跟踪文件缺失
```
（父 agent 于 18:30:00 独立复跑，结果同为 MATCH、drift_count=0。）

**跑前自检（字段原文）**：

```json
"layout": {"tools": "…\\work\\runs\\lt2-supervisor-acceptance-freeze-20260914-1810-post-atomic-retry\\snapshot",
           "repo": "…\\memsharness", "runs": "…\\work\\runs",
           "out": "…\\work\\runs\\lt2-acceptance-20260914-1810-credit",
           "snapshot_dir": "…\\lt2-supervisor-acceptance-freeze-20260914-1810-post-atomic-retry\\snapshot",
           "executed_from_snapshot": true, "layout_ok": true}
```
⇒ `layout.tools` 指向本 freeze 快照、`executed_from_snapshot=true`（**不是**从旧快照执行）。

---

## 3. Codex R6 §4 十项逐条判定

| # | 条件 | 判定 | 证据 |
|---|---|---|---|
| 1 | 两轮 suite 结构化 82/82 | **true** | `total=82, pass=82, fail=0, exception=null`（两轮），`T12={compile_rc:0, import_rc:0, dry_run_rc:0, import_ok_token:true}` |
| 2 | deterministic manifest 两侧非空 | **true** | `deterministic_files=[50,50]` |
| 3 | 六个确定性根全覆盖 + inventory 校验 | **true** | `expected_inventory_bad_roots=[]` |
| 4 | 每项含规范化相对路径+bytes+完整 SHA256 | **true** | 归一化实现 `Path(x.replace("\\","/")).as_posix()`，compare 前两侧同过 |
| 5 | `different_files`/`only_left`/`only_right` 全空 | **true** | `[] / [] / []` |
| 6 | 排除项只来自固定 allowlist 且逐文件附原因 | **true** | 41/41 条带 `allowlist_rule`（见 §5） |
| 7 | full-tree 差异全部可映射到 allowlist | **true** | 无 `allowlist_rule=None` 项 |
| 8 | `comsol_started=false`、`mph_imported=false`、前后无 COMSOL server | **true** | 两轮 structured 均为 false；`comsol_servers_before=[]`、`after=[]` |
| 9 | 每轮完整 stdout/stderr 落盘并记 bytes+SHA256 | **true** | 见 §4；`evidence_files_complete=true` |
| 10 | 前后 source/snapshot 四项校验 MATCH | **true** | §2 |

**批次结论**：`all_conditions_met = true`，执行器 exit code = **0**。

---

## 4. 八个具名证据文件（C9 §3.6）

| 文件 | bytes | SHA256（完整） | rc |
|---|---|---|---|
| `verify_source_pre.json` | 5,155 | `e682ecb3846e48e4eb8f9073722382a4…`（完整值见 summary） | 0 |
| `verify_snapshot_pre.json` | 5,159 | `318e1b9e9733d524820011403f51e77d…` | 0 |
| `suite_run1.stdout.log` | 20,346 | `9f1f7c40b603c102b30386241c763f23b8379c9e48c94ec924953d30b75b47fa` | 0 |
| `suite_run1.stderr.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 0 |
| `suite_run2.stdout.log` | 20,347 | `34edc65079030e980e2fc86e388871db00331d874cb805655cf4c06e14003b79` | 0 |
| `suite_run2.stderr.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 0 |
| `verify_source_post.json` | 5,156 | `721b0fec856a51fb07ac50f1b49b40d8…` | 0 |
| `verify_snapshot_post.json` | 5,160 | `390f9f1d3cb5f7971a1c8761afcd9095…` | 0 |

`evidence_files_complete = true`（bytes/SHA256/returncode 三者齐备，含两个 0 B 的 stderr）。

**`acceptance_summary.json` 自身**：`121,883 B`，SHA256
`b9a633e89894d8313cbfd41daf1e6877c2c5191f49b76611a935fc975d5dc8c2`
（父 agent 独立读数一致 ⇒ 整条证据链闭合。）

**30 次隔离运行**：`isolated_summary = {n:30, passed:30, failed:[], all_pass:true}`（父 agent 逐条复核 30/30）。

---

## 5. allowlist 逐条规则 + 命中文件数（本报告新增，回应审阅）

`exclusions` 放在 **run 级**（`runs[i].exclusions`）而非顶层，原因：排除清单是**每一轮各自的现场**
（run1 与 run2 的 namespace 不同、文件集合可能不同），放 run 级才能保留"哪一轮排除了什么"；
顶层只放**跨轮比较结果**（`different_files/only_left/only_right/exclusions_run1/exclusions_run2` 摘要）。
为便于审阅，本报告把去重规则与命中数列出如下（run1 与 run2 **完全相同**，各 41 条）：

| # | allowlist_rule | 命中数 | 原因 |
|---|---|---|---|
| 1 | `basename:worker_state.json` | 20 | 控制通道：必须携带真实 sampler_pid/worker pid 供 supervisor 判活（设计如此） |
| 2 | `prefix:lt2-supervisor-selftest-liveproc/` | 8 | 真实终止探针 T7/T8 真杀自建进程 ⇒ 含真实 PID/启动时间（设计如此） |
| 3 | `prefix:lt2-supervisor-selftest-wallclock/` | 6 | T9 的 wall-clock 反例：故意不使用固定时间戳（设计如此） |
| 4 | `exact:…-smoke/child_00_attempt_1/checkpoint.json` | 1 | test-double checkpoint：摘要含被排除控制通道信息 |
| 5 | `exact:…-drill/child_00_attempt_1/checkpoint.json` | 1 | test-double checkpoint：演练期与 supervisor 动作时序耦合 |
| 6 | `exact:…-postsolve/child_00_attempt_1/checkpoint.json` | 1 | test-double checkpoint：摘要含被排除控制通道信息 |
| 7 | `exact:…-retry/child_00_attempt_2/checkpoint.json` | 1 | test-double checkpoint：摘要含被排除控制通道信息 |
| 8 | `exact:…-retry/child_00_attempt_1_refused.json` | 1 | 拒绝记录含 worker pid |
| 9 | `regex:^lt2-drill-guard-probe-[^/]+/.*$` | 1 | T16b 的 preflight-only 探针目录（只读门禁探测） |
| 10 | `basename:test_summary.json` | 1 | 结构化 summary 自身 |

合计 41 = 20+8+6+1×5+1+1。规则全部**精确到具体文件或唯一前缀**，**无通配整类**；未命中规则的根外文件⇒`allowlist_rule=None`⇒条件 6/7 判假（fail-closed 保留）。
`batch_manifest.json` **不在** allowlist 内：它是靠**修复**变确定性的（控制通道 `bytes`+`sha256` 双脱敏、`child_dir` 相对化），属"修文件"而非"开豁免"。

---

## 6. 两处口径澄清（回应审阅提问）

**澄清 1（两套日志的关系）**：`runs[i].log_path` 指向的 `suite_run{1,2}.log` 是**合并/带横幅**的流
（命令行 + returncode + seconds + 两个分离日志的 path/bytes/SHA256 + stdout 段 + stderr 段），
八个具名文件是**原始分离流**。两者字节差恒为 **723 B**（=横幅与分段标记），且 `stderr` 为 0 B：

```text
suite_run1.log        21,069 B  685679383e1cce0580f87ab127c0b214b67b6c3f3dcc20770c08b5fe33ece20c
suite_run2.log        21,070 B  956a84bced4a8171d432eb1dfa6947145570530676530df9290f7ba12ccc9cb9
（对照：stdout 20,346 / 20,347 B；stderr 0 / 0 B；差 723 / 723 B）
前两行示例：'# cmd: …snapshot\\tests_lt2_supervisor.py --namespace acc-180754-run1', '# returncode: 0'
```
⇒ 两套日志**互补而非矛盾**：具名文件满足 C9 §3.6，合并日志便于人读；`log_path` 指向合并流。

**澄清 2（exclusions 位置）**：见 §5 首段——run 级是**设计选择**（保留每轮各自现场），
本报告额外给出顶层可读的去重规则与命中数，避免审阅方翻两层。

---

## 7. B（sampler `rc=2`）的根因与修复证据

**根因（由 traceback 判定）**：Windows 上 `os.replace` 覆盖**正被其它进程读取**的目标文件会抛
`PermissionError: [WinError 5]`（同类 WinError 32）。`atomic_write_json` 原**无重试**，异常冒泡 ⇒
sampler 致命 `rc=2` ⇒ supervisor 见 `sidecar_exited` ⇒ `sampler_supervisor_integrity` ⇒ **整批 blocked**。
唯一必要条件是「有人同时读 state」，而**该条件在生产天然成立**（supervisor 每 2.5–3 s 轮询 vs sampler 每 5 s 写）。

**修复**：仅 `rt_gate.atomic_write_json` 一处 —— WinError 5/32 有界重试 **5×50 ms**，
**fail-closed 未软化**（耗尽仍 `ok:False`），返回 dict 增 `attempts/retries`。
**diff 收敛性**：父 agent 以 1750 快照旧 `rt_gate.py`（`e99e76b7…`）为基线做行级 diff ⇒
`atomic_write_json` 外改动行 = **0**（可机械复算，非自述）。

**A/B 受控对比（同一复现器与负载，只差修复）**：

```text
旧（1750 冻结 rt_gate）  n=80 bad=7  rc={'0':73,'2':7}  summary sha256 af23afa47f03fee8…
新（已修复 rt_gate）     n=80 bad=0  rc={'0':80}         summary sha256 d38912c91d48a242…
重试触发证据 = atomic_retry_test.json: ok=615, retried=204, max_retries=4, attempts_sum=940
```

---

## 8. 已知限制与比率纪律

- `extreme_stress_residual = 15/615 ≈ 2.4%`（4 写 4 读、≈2500× 生产读频率）——**非生产工况**；
  保持 5×50 ms 的依据：生产最热文件 ≈0.4 Hz 读写、读者持有时长约毫秒级 ⇒ 250 ms 有约两个数量级余量；
  且提高上限无法消除压测内在争用，只会拉长写者最坏阻塞（worker 的 checkpoint 正处于「先原子写再关 server」）。
  **关键是 fail-closed 已保住**：生产残留风险表现为「停下来」而非「静默写坏」。
- `read_json_safe = REPORTED_NOT_FIXED`：读失败返回 `{}`。最坏后果是**把健康 worker 误判为启动失败并重跑一次**
  （宽限期后 `worker_startup_failure` → `server_startup_transient`），**不是**"把坏结果当通过"
  （`ss={}` ⇒ verdict `ok` ⇒ 不动作；`os.replace` 原子 ⇒ 读侧看不到半写）。属**稳健性缺陷、非正确性缺陷**，与 R4 同窗口处理。
- **三条比率（12.5% 压测 / 7.7% 单批 / 2.4% 极端压测）均不得当作生产故障率。**
- 历史 `81/82`：**原始日志已因复用丢失，不声称有原始日志支撑**；本会话抓到的那次是 `T8`（由我自己的脱敏改动触发），
  **历史那次是否同一断言未被证明**。

---

## 9. 声明与后续（不跳步、不自行升级）

```text
comsol_started = false ; mph_imported = false ; real_COMSOL_hard_stop_drill = NOT_RUN
未运行 COMSOL / comsolbatch / mphserver ；未碰页面文件
未复用或清理任何既有 run 目录（1402/1423/165357/165457/170522/1722/1725/1745/1747/1750 全部原样保留）
rt_gate.py 自本轮起恢复「不改」（唯一例外已用完）
G1 = CLOSED_FOR_FREEZE_1810（父 agent 独立复核）
下一步顺序：① 用同一 freeze 同一批证据重验 G2/G3 → ② 新 run-id 跑正常资源确认 r3
（work\tools\check_r3_conditions.py，21 项 fail-closed）→ ③ 真实硬停演练（需另行放行）
LT2 生产 = BLOCKED（U1–U3 未验证；16 小时无人值守须待硬停演练之后）
```

失败与被取代的冻结谱系（原样保留、不清理）：`1402 / 1423 / 165357 / 165457 / 170522 / 1722 / 1725 / 1745 / 1747 / 1750`；
其中 `credit 批次 lt2-acceptance-20260914-1750-credit = ABORTED_WITHOUT_SUMMARY`（中止原因无法判定，丢失剩余 17 轮分布）。
