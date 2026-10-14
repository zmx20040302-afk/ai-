# 用户授权记录 — 真实 COMSOL 硬停演练（2026-09-14）

> 本文件按 `docs\TO_CODEX_record-20260914-r2-*.md` §2 定下的规矩建立：
> **任何授权类事实必须同时记录「授权来源、原话摘要、时间」**，不得只写「已批准」。

---

## 1. 授权事实

| 项 | 内容 |
|---|---|
| 授权来源 | 用户在本会话中的直接回复 |
| 原话摘要 | **「放行」**（回应我提出的「仍需你放行的：真实 COMSOL 硬停演练（U1/U2/U3）」） |
| 时间 | 2026-09-14（本会话，页面文件生效核验之后） |
| 授权范围 | 执行**真实 COMSOL 硬停演练**，以验证 U1 / U2 / U3 |
| 前置授权（早前） | 页面文件调整至 ≥12 GB：用户以结构化选择明确批准；**现已生效**（commit limit 44,477.4 MB） |

## 2. 授权覆盖的内容

```text
U1  真实 COMSOL 下 verified_emergency_termination 全路径
    （硬线触发 -> 冻结投递 -> 保存触发样本 -> 请求 worker 结束 -> 宽限期
     -> 归属核验 -> 终止 server -> 终止后二次确认 -> 回收 worker）
U2  对真实 comsolmphserver 执行终止（此前只在自建替身上验证过）
U3  真实 worker 阻塞在 study.run() 期间被终止 / worker 回收行为
U5  每组合一个全新 combo-worker 进程 => 全新 mph.Client 是否真绕开「单会话单 client」约束
U7  server_pid_from_port() 端口归属与 parent_is_worker 在真实 MPh 启动链上的取值
```

顺带一并执行：`(0.8,2)` **页面文件后资源确认**（上一次因 D-A 回归失败，未取得任何资源数据）。

## 3. 约束（来自 Codex 裁定 §8，不得放宽）

```text
演练触发方式：必须用「安全的、早触发的模拟门禁」或「可快速取消的小模型」
禁止          ：通过把真实机器内存压到危险水平来触发
禁止          ：把演练产物混入生产资源口径（需显式 drill 标识）
禁止          ：由我自行修改页面文件或重启系统（该变更已由用户完成）
```

## 4. 本次授权**不**覆盖的内容

```text
LT2 首个生产逻辑批（4 组合）= 仍需等前置门禁全部满足，不在本次授权内
提升 server_lifecycle_size 到 2  = 需先单独做「两组合共用一 server」试验，不在本次授权内
模型/结果状态晋升                = 人工门禁保留，智能体不得自行晋升
```

## 5. 当前阻塞

```text
D-A（阻断级回归）：supervisor 在拉起 worker 前把 supervisor_signal.json 写进 child 目录，
                 与 worker 的「child 目录非空即拒绝复用」守卫互斥 => worker 永远起不来。
                 任何真实运行（含演练）都会立刻失败 => 必须等该修复落地。
```

实测证据：run-id `lt2-resource-confirm-x080-n02-postpagefile`，
`child_00_attempt_1_refused.json` 的 `reason = child_dir_exists_nonempty`。
详见 `docs\TO_CODEX_record-20260914-r3-pagefile-effective-and-G1G3-closed.md` §5。

另：现有代码**没有演练机制**（`Thresholds()` 三处均用默认值构造，无 CLI 覆盖/环境变量/注入开关），
已要求实现 `--drill` 模式（含阈值覆盖 + 产物自我标识 + 独立分类），修好后方可执行本次授权。

---

## 6. 知情同意补充（2026-09-14，第二次确认）

Codex R3 裁定 §8 判定 `real_COMSOL_hard_stop_drill = NOT_AUTHORIZED_IN_THIS_TURN`，
并要求授权时明确告知**破坏性后果**。经查：我第一次征询时**漏说了两条**——
「会故意结束本次测试 server」与「该次结果预计作废」。因此我**未**把用户原先那句「放行」
当作完整知情同意，而是按裁定 §8 清单补全后重新征询。

| 项 | 内容 |
|---|---|
| 授权来源 | 用户在本会话中对补全后问题的结构化选择 |
| 选择结果 | **「确认放行（知情后仍同意）」** |
| 时间 | 2026-09-14（本会话） |
| 已告知的破坏性后果 | ① 会**故意终止本次测试 server 进程**以验证 `verified_emergency_termination` 全路径；② **该次运行的求解结果预计作废**（只用于验证终止机制，不是有效数据） |
| 已告知的执行约束 | 使用现有模型**副本**、早触发 drill 阈值（**不靠耗尽内存触发**）；演练前确认无其他 COMSOL 作业；演练后验证 PID / 端口 / 临时文件清理；**不重启电脑、不改页面文件** |
| 生效前置 | D-D 修复落地 → 冻结哈希 → 裁定 §6 的 T1–T12 无 COMSOL 验收全过 → 正常资源确认（新 run-id）通过 → 才执行演练 |

**结论**：`real_COMSOL_hard_stop_drill = AUTHORIZED_WITH_INFORMED_CONSENT`，
但**受前置条件约束**，未满足前置前不得启动。
