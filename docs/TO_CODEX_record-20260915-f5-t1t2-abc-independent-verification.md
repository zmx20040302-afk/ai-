# 记录：F5 / T1 / T2 / A / B / C 独立复核 + 新冻结点 freeze-20260915-1055

- 时间：2026-09-15 10:48
- 复核人：**独立复核**（非实现者；实现者已交回本轮改动并停止工作）
- 对象：`work/tools/` 本轮改动（A=T14 确定性化、B=记录改名、C=字段分离、F5=空集漏洞、T1=冻结器快照口径、T2=检查器入冻结）
- 结论：**六项全部独立确认**；新建冻结点 `freeze-20260915-1055-post-f5-t1t2-abc-records`（manifest sha256 `e76538b7116b6faa0fb80d7d6a6f8ae9b643151ac7748b09f84f0e7a7ccc74f0`），双向校验 MATCH。
- 当前阻塞：**r3h 被前置资源门禁挡住**（见 §5），需用户处置机器占用后才能跑。

## 1. 实现者声明的哈希：逐个实测，全部一致

| 文件 | 声明 sha256（前16） | 实测 | 字节数 |
|---|---|---|---|
| `lt2_production.py` | `9d42cdd7371661b4` | ✅ | 171,081 |
| `tests_lt2_supervisor.py` | `16bead4e0899ba65` | ✅ | 66,006 |
| `min_exec_r8b_evidence.py` | `53e3f8090772bc28` | ✅ | 63,161 |
| `freeze_snapshot.py` | `93d6c917fa2659ee` | ✅ | 15,768 |
| `check_r3_conditions.py` | `5ed0228ee1d031eb` | ✅ | 14,748 |
| `rt_gate.py`（声明未改） | `23ef7fdcac58e4f6` | ✅ | 11,140 |

## 2. diff 范围（以 1015 冻结快照为基线，AST 顶层定义级）

| 文件 | 变更的顶层定义 | 新增 | 删除 |
|---|---|---|---|
| `lt2_production.py` | `combo_pass_conditions`(F5)、`run_fake_combo_worker`(A)、`classify_trigger`/`finalize_after_solve`/`describe_child_dir`/`CHILD_FILE_SPEC`(B/C)、`run_supervisor`/`supervise_child`(B/C) | `COMPLETION_FILE_NAME`、`FAKE_CLOSED_LINGER_S`、`_set_blocked` | 0 |
| `tests_lt2_supervisor.py` | 仅 `t14_smoke_determinism` | 0 | 0 |
| `min_exec_r8b_evidence.py` | `DECLARED_SCOPE_FUNCS`、`mode_diff`、`mode_f1f2`、`mode_guard` | 0 | 0 |

⇒ 全部落在已声明的改动范围内，**函数外无越界改动**（与实现者 `outside=[]` 一致）。

## 3. F5：三向灵敏度实测（我自己写的探针，未复用实现者的测试）

探针：`work\runs\_evidence-f5-threeway\f5_threeway_probe.py`（exit 0 = 缺口已复现）；
对**空时间线**（用各版本自己的 `summarize_timeline` 生成，非手搓字典）比较三份代码：

| 版本 | `monitoring_ok` | `peak_ws_lt_hard_stop` | `commit_hard_stop_samples_0` | `min_avail`/`min_commit`（对照） |
|---|---|---|---|---|
| 1015（修复前，`f73549f4`） | **True** ❌ | **True** ❌ | **True** ❌ | False ✅ |
| 2255（更早，`c3f45407`） | **True** ❌ | **True** ❌ | **True** ❌ | False ✅ |
| work/tools（修复后，`9d42cdd7`） | False ✅ | False ✅ | False ✅ | False ✅ |

另三项独立结论：

- **未过度修复**：给「3 行正常样本」时，修复后 5 个资源条件**全为 True**（好运行不会被误杀）；
- **正对照**：给「commit 越线」的时间线时，`commit_hard_stop_samples_0` 正确判 **False**（真越线不会被放过）；
- **第 4 项也修了**：`no_hard_stop_verdict_samples` 现为 `bool(parsed_rows) and count==0`（`lt2_production.py` L1574）⇒ 空列表判 False；
  实现者还**同类补齐了两处**：`failed_frequency_points_0` / `drive_voltage_mismatch_0` 前置 `bool(rows)`（L1065-1066）。
- 探针运行前后，三个版本目录的文件哈希**未变**（只读取证）。

**实现者自陈「第一版修得不完整」经我复核成立**：`summarize_timeline` 对空时间线返回的是**整数 0**（不是 `None`），
所以「只判非 None」仍会漏；现版本用 `timeline_rows >= 1` 显式要求非空证据，与我的探针结论一致。

## 4. T1 / T2 / A / B / C

### 4.1 T1（冻结器快照口径）已修，实测不再误报

```
--verify-snapshot freeze-1015 : MATCH / drift_count=0 / source_drift_count=3 / exit=0   ← 源漂移独立字段，不并入 verdict
--verify          freeze-1015 : INVALIDATED_BY_CODE_DRIFT / drift_count=3 / exit=1      ← 仍是"不可用于新运行"的正当判据
```
且 `freeze_snapshot.py` 已把自己纳入 AUX（冻结器自证版本）。

### 4.2 T2（检查器入冻结 + 自证哈希）已做，且**在旧缺陷产物上真的会失败**

| 对象 | 结果 | 失败项 |
|---|---|---|
| r3g（修复后产物） | **25/25**，exit 0 | — |
| r3f（F4 缺陷产物） | **22/25**，exit 1 | `no_blocked_reason`、`pass_conditions_all_bool`、`child_status_pass` |

三条失败**都是真阳性**（我逐个回查了 r3f 的产物）：
`r3f.pass_conditions` 里确实混着 `('hard_stop_verdict_sample_count', 'int', 0)`；
r3f 的 `blocked_reason` 确实非空；r3f 的 `status` 确实是 `fail_or_limited`。
⇒ 新检查器能直接点出历史上那次「全绿却失败」的根因，而不是靠批次级兜底。

新增的两条正是我指定的语义检查（`pass_conditions_all_bool` 会打印非布尔字段名；`child_status_pass` 同时要求
`batch_manifest.children[0].status == "pass"` 且 `checkpoint.status == "pass"`），另三条冻结布尔（单义）也已在查。
检查器产物顶层已带 `checker_sha256` / `checker_argv` / `checker_exited`。

### 4.3 A（T14 确定性化）：机制成立，且**我把它量化了**

我在 scratch 目录做了受控 A/B（除一个常量外逐字节相同，CRLF 保留，diff 仅 1 行）：

| 变体 | `FAKE_CLOSED_LINGER_S` | 正常收尾记录 | T14（逐字节一致性） | T14b（命名纪律） | 套件 |
|---|---|---|---|---|---|
| N（新代码） | 1.5 | **写出** `completion_record.json` | PASS（7 个证据文件） | PASS | **83/83**，连跑 **3/3** |
| L0（只改该常量为 0.0） | 0.0 | **不写** | PASS（6 个证据文件） | **FAIL** | 82/83，**3/3 完全一致** |
| O1015（新测试 + 旧生产 `f73549f4`） | 1.5 | **不写** | PASS（6 个文件） | **FAIL** | 82/83 |

由此三条独立结论：

1. **A 的机制确认**：驻留是「守卫是否被命中 / 记录是否写出」的**唯一**变量（其余字节全同）。
2. **敏感性的载体是 T14b，不是 T14**：T14 在三种变体下**都通过**——因为两次运行「同样缺席」也满足「逐字节一致」。
   即实现者所述「两次都缺席 ⇒ 相等 ⇒ 通过，为错误的理由通过」这一形态**在旧生产件上依然存在**，
   真正把它逼出来的是 T14b。这一点实现者的报告里没有单独点明，建议在验收报告里写明（否则后人会以为 T14 就是该修复的判据）。
3. **不是靠相位运气**：测试路径的轮询周期 `_smoke_args(gate_poll=0.3)`，驻留 1.5 s ⇒ **5 倍裕度**。
   生产路径 `GATE_POLL_S=2.5`，而真 worker 的「可被观察到」窗口**结构性地很宽**：`checkpoint.json` 在 postprocess 就落盘并长期存在，
   worker 之后还要走 cleanup→等端口关闭（≤30 s 循环）→`sampler.wait(timeout=20)`→补写 checkpoint（`lt2_production.py` L1958-2007）
   ⇒ 窗口远大于 2.5 s。r3d/r3g 两次真机正常收尾都记到了，与此一致。
4. 顺带确认：L0 与 O1015 的失败**只有** T14b 一项，其余 82 项照常通过 ⇒ 改动没有掩盖别的信号。

> 一处诚实的边界：**我没有**独立测出生产路径「`stage=closed` → worker 退出」的实际秒数（产物里没有这个量）。
> 上面的「窗口很宽」是**由代码结构推出**的（checkpoint 早于 cleanup 落盘 + 端口关闭循环 + sampler.wait），不是实测值。
> 若要把它变成实测，可在 worker 收尾处记录 `closed_at` 与进程退出时刻的差。

### 4.4 B（记录改名）与 C（字段分离）

- `COMPLETION_FILE_NAME = "completion_record.json"`（L147）、`TRIGGER_FILE_NAME = "termination_trigger.json"`（L141）；
  正常收尾只写前者（L2309），**不写**后者（L2308 注释 + `CHILD_FILE_SPEC` L2449-2455 明写语义）；
  `termination_performed: false` 在 L1251。**读者已枚举**：`describe_child_dir`(L2508)、`enforcement_probe`(L2436)、
  `classify_trigger`(L2172) —— 前两处语义未变。
- C：`_set_blocked(result, reason, *, retry_class, retry_reason, auto_retry_attempted)`（L2125），
  四个调用点收敛到它（L2616/2632/2640/2647）；批次级顶层新增 `retry_class`/`retry_reason`/`auto_retry_attempted`（L2608-2609）。
  对照：**旧产物 r3f 的 `blocked_reason` 正是混写的** —— `'child_00_not_pass:fail_or_limited（不可自动重跑：normal_completion）'`
  ⇒ C 修的是一个真实存在的混写形态。

## 5. 新冻结点与当前阻塞

```
freeze_id       = freeze-20260915-1055-post-f5-t1t2-abc-records
manifest sha256 = e76538b7116b6faa0fb80d7d6a6f8ae9b643151ac7748b09f84f0e7a7ccc74f0
文件数          = 15（targets 3 + deps 1 + aux 11，已含 check_r3_conditions.py 与 freeze_snapshot.py 自身）
三方回读        = source_ok / snapshot_ok / manifest_ok 全 true；window_drift = []
--verify          = MATCH / drift 0 / exit 0
--verify-snapshot = MATCH / drift 0 / source_drift 0 / exit 0
调用时间        = 2026-09-15T10:48:33（窗口内 COMSOL 家族进程为空）
```

**r3h 现在跑不了**（门禁按设计拒绝启动），实测：

```
采样1: avail=15268.2 MB（门禁 18000）❌   commit=19505.8 MB（门禁 21500）❌   load=52%
采样2: avail=15107.5 MB ❌                commit=19366.1 MB ❌                load=53%（间隔 5 s）
端口 2036 = CLOSED ✅（可直接用）
COMSOL 家族进程 = 无 ✅；但用户的 ComsolUI.exe（pid 4808）开着：Private 2570.4 MB / WS 2046.6 MB
系统：RAM 32189.4 MB；提交上限 44477.4 MB；已提交 ≈ 25105.2 MB
```

对比：r3g 启动前（10:09:26）同一门禁读数为 avail 21252.6 / commit 26980.9 ⇒ 40 分钟内提交量涨了约 7.6 GB。
占用前列：ComsolUI 2570 MB、`python` pid 23088 867 MB（**2026-09-14 13:02:55 启动的旧遗留进程**）、
node 767 MB（DSH Web GUI，勿动）、dwm 645 MB、LZTray 537 MB、ChatGPT/Chrome/PPT/Excel/Weixin 各 330–380 MB。

⇒ 要让 r3h 过门禁，需要腾出约 **2.9 GB avail / 2.1 GB commit**。这属于**用户机器占用**，我不擅自关用户的 COMSOL GUI 或其它程序。

## 6. 未做 / 边界

- **未**跑 COMSOL（r3h 未启动，被门禁正确挡住）；**未**启动 504 点生产批次；**未**清理任何目录。
- **未**触碰用户的 `ComsolUI.exe`（pid 4808）。
- 本轮所有 scratch 与探针产物只写在 `work\runs\_evidence-f5-threeway\`（含 `A_threeway\{N,L0,P10,O1015}`）。
  注意：`P10` 变体因我的补丁脚本长度校验失败**未真正改成功**，等价于 N 的副本，其运行结果不作为证据（已剔除）。
- `check_r3_conditions.py` 里 `min_commit_gt_6144` 的**键名内嵌数字**与 F1「键名不得内嵌数字」的原则不一致；
  但该检查器的判据是**固定验收口径**（不随 `--drill` 变化有效值），故仅登记为一致性瑕疵，不要求本轮修改。

## 7. 产物

| 文件 | 说明 |
|---|---|
| `work\runs\_evidence-f5-threeway\f5_threeway_probe.py` | F5 三向探针（可重跑，exit 0 = 缺口复现） |
| `work\runs\_evidence-f5-threeway\f5_threeway_report.json` | 三向结构化结果 |
| `work\runs\_evidence-f5-threeway\A_threeway\{N,L0,O1015}\` | A 的受控 A/B 三份代码副本 + 运行日志 |
| `work\runs\_evidence-f5-threeway\checker_new_r3g.txt` / `checker_new_r3f.txt` | 新检查器 25/25 与 22/25 的原始输出 |
