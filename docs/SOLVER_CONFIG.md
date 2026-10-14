# AI 求解器底层配置（**尚未放行**）：solver_spec

> 用户 2026-09-30 指示：「先完成求解器的底层配置，场级解我正在导出」。
> 本文件说明**场数据到达之前**已经配好、并用可离线检验的方式锁死的那一层。
> 权威口径：`WORKING_PLAN.md` §6.1.1（S0–S5）与 §6.4（放行门禁）；
> 技能 `ai-solver-verification`、`field-io-contract`。本层**不新增第四套口径**。

## 1 这一层是什么 / 不是什么

* **是**：求解器的**声明式规格**（`solver_spec`）+ **S 级评估** + **放行状态机** + **出解门禁与盖章**。
* **不是**：预测器本身。预测由降阶模型承担（`src/memsharness/pod.py` 的 `PodModel`），
  本层负责"**什么时候允许出解、出解必须带什么**"。
* **不是**：代理层（`surrogate.py` / `multichannel_surrogate.py`）的扩展。
  两类模型**两套放行口径**（§6.4 原文）：代理层用 L 级，求解器用 S 级，**不得互相冒充**。

| 文件 | 作用 |
|---|---|
| `schemas/solver_spec.schema.json` | 规格契约（机器可校验） |
| `src/memsharness/solver.py` | 校验 / S 级评估 / 状态机 / 适用范围 / 出解盖章 |
| `scripts/solver_config.py` | CLI：`init` / `validate` / `summary` / `state` / `solve` |
| `work/runs/solver/<solver_id>/solver_spec.json` | **实例**（模板路径；`pmut-f1` 实例已写出，其它 id 现在**不存在**） |
| `work/runs/solver/<solver_id>/release_log.jsonl` | **放行台账**（首次跃迁才创建 ⇒ 现在**不存在**；append-only） |
| `tests/test_solver.py` | 30 条契约用例 |

## 2 放行状态机（§6.4，代码不得自我放行）

```
draft ──(S0 与 S3 全过)──▶ physics_consistent ──(S1/S2 达标 + S5 已认证 + 独立留出集)──▶ solver_certified
                                                                                        │
                                                              （**人工签字** + 适用范围）▼
                                                                                 approved_solver
任一阶段漂移复检失败 ─────────────────────────────────────────────────────────▶ suspended
suspended ──（**只能由人**恢复）──▶ physics_consistent
```

* 代码可自动完成的跃迁与**必须人工签字**的跃迁分别写在 `AUTO_TRANSITIONS` / `HUMAN_TRANSITIONS`
  两张表里：用例断言**放行那条边不允许由代码自行走通**（它只在人工签字表里）。
* 人工签字的 CLI 形状：
  ```powershell
  python -B scripts\solver_config.py state --spec work\runs\solver\pmut-f1\solver_spec.json `
      --evidence work\runs\solver\pmut-f1\evidence.json --apply `
      --sign-by "你的名字" --scope "只覆盖 N2∈[5,8]、x∈[0.2,1.0]、5–50 MHz"
  ```
  **不给 `--sign-by` 或 `--scope` 就会被拒**——这是红线 5（放行权在人）的代码形态。

## 3 `None ≠ 通过`（S3 硬门禁的原文语义）

* 任一 S3 检查为 `None`（无法判定）⇒ 整体 `inconclusive` ⇒ **状态不许推进**；
* S5 未认证（校准点不足）时 `s5_passed = **null**`，**不是 True**（SOP §4 原文）；
  `certified=false` 记作"无法判定"，而不是"检查失败"——它的含义是"样本还不够，先别放行"。

## 4 出解门禁（顺序固定，逐条 fail-closed）

```
① 状态必须是 approved_solver        否则 refused + fallback=comsol
② 参数必须命中适用范围（逐条判）    否则 refused + fallback=comsol（写明每一条 miss）
③ 必须有场级误差界                  否则 refused（红线 7）
④ 才调用预测器，并盖 5 个必备元数据
```

出解必带（缺一项即报错，不静默省略）：

| 元数据 | 取值 |
|---|---|
| `source_type` | 恒为 `ai_solver`（红线 8：与 `simulation` 严格区分） |
| `model_id` | 非空（红线 8：挂到具体模型版本） |
| `uncertainty` | 场级误差界（红线 7） |
| `verification_level` | 当前放行状态 |
| `applicability_hit` | 适用范围命中判定（§6.4 运行时规则） |

## 5 公共点集与掩膜（field-io-contract）

* `point_set.points_file` **必须**给（显式坐标文件），`point_set.spec` 记每轴 start/stop/n；
* `mask_policy` **只允许** `common_mask_all_finite`：公共掩膜 = 在**所有**快照中都有限的点，
  **绝不允许把 NaN 当 0 填充**（那会污染基与误差）；
* 场级误差一律用 `rel_L2 = ‖pred−true‖₂/‖true‖₂`（只在掩膜点上、双方都有限），
  **逐留出快照给 max**，不用平均值掩盖最差点。

## 6 场级解到位后怎么接（用户正在导出）

```powershell
# ① 用真实导出目录**推导**公共点集（推导不出来会如实说，不猜）
python -B scripts\solver_config.py init --solver-id pmut-f1 --export-dir work\exports --force

# ② 人逐项补齐四件事（缺一项 validate 就不通过）
#    model_id（降阶模型版本）、point_set、applicability.param_bounds、thresholds
python -B scripts\solver_config.py validate --spec work\runs\solver\pmut-f1\solver_spec.json

# ③ 训练降阶模型（POD）+ 在**独立 COMSOL 留出集**上算场级相对 L2（S1）
# ④ 把 S0–S5 证据写成 evidence.json，再跑 state（决定能否推进）
python -B scripts\solver_config.py state --spec ... --evidence evidence.json
```

**当前实例的真实状态**（不粉饰）：`work/runs/solver/pmut-f1/solver_spec.json` 是 **draft**，
且 `validate` **故意不通过**——因为 `applicability.param_bounds` 还空着。
在拿到导出前，任何"合适范围"都是我编的，所以**留空等人填**。
它现在能做的、也是唯一该做的：**拒答**（`solve` 返回 `refused` + `fallback=comsol`）。

## 7 还没做（下一批）

1. **接入 MCP / 控制台**：现在只能用 CLI 与人读 JSON；下一步给一个只读工具
   （`solver_spec` / `solver_state`），并在页面上显示状态与"缺什么"。
2. **POD 训练脚本的封装**：`pod.fit(...)` 已有，但"从导出目录 → 公共点集 → POD → S1 报告"
   这条流水线还没有一键入口；等导出到位后做。
3. **S0/S4 的证据生成**：S0 需要闭式解对照（`analytic.py` 已有部分模型），
   S4 需要 2–3 套网格的结果（依赖 COMSOL 侧网格扫描）。
