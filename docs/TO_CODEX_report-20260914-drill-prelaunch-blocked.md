# 硬停演练：**执行前被阻塞，未启动**（append-only 记录）

- 日期：2026-09-14
- 授权：用户直接回复「**现在执行**」（范围＝真实 COMSOL 硬停演练 U1–U3；知情同意先前已取得）
- 方案：`docs/TO_CODEX_plan-20260914-hardstop-drill-U1U3.md`（本轮未偏离方案）
- 结果：**演练未启动**（`lt2-drill-hardstop-*` run 目录未创建；未起任何 server；**未杀任何进程**）
- 阻塞类型：**执行前前置条件不满足 + 存在会污染演练证据的并行负载**（不是代码/判定缺陷）

---

## 1. 我按方案先做的并行负载核查（父 agent 的硬性前置）

```text
COMSOL 进程：none
python 进程：仅 2 个 —— 均为**本会话自身的 MCP server**（13:02:55 启动；累计内核态 0.03 s / 0.92 s）
              ⇒ 属会话基础设施、几乎零占用，**不是**测试/求解负载
端口 2036：closed；无 server
但 4 秒 CPU delta 采样发现**非平凡后台负载**：
  League of Legends   4.23 CPU·s/4s ≈ 1.06 核
  LeagueClient        2.69 CPU·s/4s
  LeagueClientUx      1.56 CPU·s/4s
  LZTray              1.12 CPU·s/4s
  （另有 recorder / XLSmartUpdate / Memory Compression 1880 MB / node 499 MB / msedge 396 MB）
总 CPU：24 核，实测 17.5 % / 17.7 %（≈4.2 核当量）
```

## 2. 决定性数据：方案自己的启动前置门禁**当前不满足**

```text
                     现在（21:56–21:58）      r3d 启动时（20:19:44 实测）     差
avail physical        13,057.4 MB              18,370.1 MB                 −5,312.7 MB
commit available      15,940.1 MB              22,257.7 MB                 −6,317.6 MB
memory load           59 %                     42 %
门禁（方案要求照常）   16,384 / 16,384          gate_pass = true（r3d 记录）
现在门禁             avail ✗（13,057 < 16,384）  commit ✗（15,940 < 16,384）
```

⇒ 若照方案（不加 `--avail-gate/--commit-gate` 覆盖）原样执行，`run_supervisor` 会记
`blocked_reason=preflight_gate_failed(child_00)` 后**直接停止**：不会起 server、不会有演练，
只会留下一个 blocked 的 run 目录。**故我没有启动它。**

## 3. 更重要的第二重理由：**即使手工压低门禁也仍然无效**

拿 r3d 的 **commit 轨迹**（同一模型、同一 combo）做投影：

```text
r3d commit：preflight 22,257.7 → 首样本 21,461.3 → solve 前 8 个样本
            19,752.7 / 18,921.3 / 18,507.4 / **9,052.6** / 9,054.5 / 9,069.9 / 9,070.2 / 9,065.2
            solve 期最低 **9,031.3**
⇒ 模型加载本身消耗 commit ≈ **12,430 MB**（21,461.3 − 9,031.3）
⇒ 若现在（commit 15,940）开跑：solve 平台期 ≈ **3,510 MB**
⇒ 落在**真实** commit 硬停线（4,096 MB）**之下**
```

后果：采样器会同时报出 `commit_hard_stop(... <= 4096.0)` 与人为的 `ws_hard_stop(... >= 5000.0)`
⇒ **真实资源事件与人为演练触发混在一起**，触发记录不再能单独证明"演练机制"；
并且这正好违反方案 §5②的禁令「**不得靠耗尽真实内存触发**」（这里是"顺带真的越了 commit 线"，同样不可接受）。

## 4. 因此本轮**没有**做的事（可核查）

```text
✗ 未创建演练 run 目录（Get-ChildItem lt2-drill-hardstop* → 空）
✗ 未启动任何 comsolmphserver（当前 none、端口 closed）
✗ 未杀任何进程（League of Legends 仍在运行，未被触碰）
✗ 未压低任何门禁/阈值、未改任何代码、未偏离方案
✗ 未启动 LT2 生产批次
✓ 已保留现场（含 `_evidence-drill-prep/drill_prelaunch_blocker.json` 阻塞证据）
```

## 5. 建议（等父 agent / 用户决定）

**推荐 A：等后台负载回落到 r3d 量级再跑**（最干净，不引入未登记变量）

```text
释放目标：关掉 League of Legends + LeagueClient(+UxRender)（当前可见 WS ≈ 3.0 GB，
          实际 commit 占用通常更高），必要时再关 msedge/node 等非必需进程；
重新测量的**放行门槛**（我建议比 16,384 的硬门禁留出余量，使 solve 平台期远离 4,096）：
    avail_physical_mb ≥ 18,000  且  commit_available_mb ≥ 21,500
达标 ⇒ 立刻按方案原样开跑（命令一字不改）；未达标 ⇒ 继续等，我不会带负载开跑。
```

**备选 B（不推荐，但由你决定）**：明确接受"可能与真实 commit 硬停同时触发"，
并把这条写进演练报告作为**已知偏差**。我倾向不做——它会让 U1/U2/U3 的结论不再单纯。

**备选 C**：放开对"并行负载"的要求，但**仍然要求**门禁达标。技术上等价于 A（因为门禁是硬约束），
除非同时压低门禁 ⇒ 回到 B 的问题。

## 6. 一旦放行，我会原样执行并回报

```text
命令（一字不改，见方案 §1）：
  & $py -B "$snap\lt2_production.py" --run-id lt2-drill-hardstop-u1u3-<YYYYmmdd-HHMM> \
      --role supervisor --combos "[[0.8,2]]" --freqs "5" --expect-freq-count 1 \
      --drill --ws-hard-stop-mb 5000 --freeze-id freeze-20260914-2040-post-guard-persistent
回报：exit code / 四字段（含 termination_rec）/ 阈值证据 5000 vs 12288 / signals 存在性与个数 /
      steps（verify_ownership → terminate_server(rc=0) → post_termination_verification）/
      二次确认四项 + verified / worker_returncode / worker_error.json.stage_at_error /
      retry_class=drill_hard_stop 且 retry=false / DRILL_README.txt 与 DRILL_NOTE 四处 /
      三布尔 / 演练后 --verify 与 --verify-snapshot / 八项残留检查 / 逐项「期望 vs 实测」
```

阻塞证据文件：`work/runs/_evidence-drill-prep/drill_prelaunch_blocker.json`
（2,560 B；含当前三值、r3d 基线、差值、commit 投影、进程 WS 快照、`no_process_killed/no_run_dir_created`）。
