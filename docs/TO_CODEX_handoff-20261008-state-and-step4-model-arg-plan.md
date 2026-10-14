# 状态交接 + 已登记小改动（step ④ `--model`）的可裁决方案

**时间**：2026-10-08（本会话在 2026-09-15 之后被挂起，本次"继续任务"先做现场重定位）
**性质**：**只读核验 + 方案**。本轮**未改任何代码、未跑 COMSOL、未写入任何 run 目录、未动任何冻结**。
**为什么需要人裁决**：本会话由上级 agent 持有，工具层明确拒绝人类交互（`human interaction is unavailable while the calling agent is owned by another live agent`），故未决项写在 §4。

---

## 1. 现场重定位（每条都有可复核出处）

| 事项 | 实测结论 | 出处 |
|---|---|---|
| **r3h**（我上一轮改动后的生产路径资源确认） | **PASS**，`blocked_reason=None` | `work/runs/lt2-resource-confirm-x080-n02-r3h-post-f5-t1t2/` + `work/runs/_evidence-r3h/` |
| **我的 A/B/C/F5/T1/T2 改动是否被生产路径背书** | **是**：09-15 11:22–11:55 用冻结 `freeze-20260915-1055-post-f5-t1t2-abc-records` 跑了 **4 组合生产试用**，4/4 `pass`、`rows=7`、`unexpected_files=[]`、三布尔 true | `work/runs/lt2-prod-trial4-combo-20260915/batch_manifest.json` |
| 冻结 1055 现状 | `--verify` = **MATCH**（`drift_count=0`）⇒ 我报告的 5 个哈希仍是冻结值 | `freeze_snapshot.py --verify freeze-20260915-1055-...` |
| **504 点整批** | **已出局**：用户提问后已选"**暂不跑全量**"；504 = 72 组合 × 7 频点且**全部是反相驱动** | `docs/DECISION-MEMO-20260915-legacy-vs-reverse-drive.md` §1/§7 |
| `lt2-prod-b2-r1` | 只是 **dryrun + `preflight_only.json`**（09-14 12:24，用**旧门禁** 16384/13500，当场 `gate_pass=false`：avail 9439 / commit 3155）⇒ **整批从未启动** | 该目录内容 |
| 单组合真实成本（用于任何未来预算） | trial4 实测 `solve_seconds` 254.9 / 424.4 / 568.5 / 576.4；**壁钟 ≈8.4 min/组合**；峰值 WS 6.2–9.7 GB | trial4 各 child `worker_state.json` / `resource_timeline` |
| solver 线最新要求 R1–R14 | **技能侧已落点**（`comsol-batch-production` §9.1–9.10；R4→`field-io-contract` §8、R5→`dataset-contract` §10 与 `sweep-analysis` §8、R3/R8→`freeze-and-acceptance`、R12→`report-and-evidence` §8）；**代码侧标记亦命中**（stage1 驱动/launcher/判读/回传校验/watch） | 各 `SKILL.md`；`work/runs/stage1-20261008/` |
| INDEX | **没有 2026-10-08 的条目**（最后一节为 §91，2026-10-06）⇒ 10-08 三轮尚未登记 | `docs/INDEX-records-and-rulings.md` |

---

## 2. 我这线唯一登记的未做项：step ④「生产路径的模型可配置」

`docs/DECISION-MEMO-…` §5 明确：「走**生产路径**需给 `lt2_production.py` 加 `--model` 参数（现在写死反相模型）；属**已登记的小改动**，改完须**新建冻结**」。

### 2.1 实测耦合面（这是方案的要点）

```text
L85   MODEL = MODELS / "b_GE_task3_2new_reverse_voltage_drive_v1.mph"     ← 写死（sha256 cbe9ccc18e51005f…，138,959,575 B）
L96   DRIVE_MODE = "dual_electrode_antiphase_voltage_drive"               ← 另一个写死常量
L1838 client.load(str(MODEL))                        ← 唯一实际加载点
L1584 / L1711 / L2606 "model_sha256": sha256_file(MODEL)   ← 三处哈希记录（同一常量，单一真源）
L1508 / L1583 / L1684 / L1704 / L2586 "drive_mode": DRIVE_MODE  ← 五处记录
```

**⇒ 只加 `--model` 是不够的，而且危险**：换模型后 `drive_mode` 仍写 `dual_electrode_antiphase_voltage_drive`，
checkpoint 就会**谎报驱动**——正是本仓反复处理的「记录名与实际语义不一致」同一族
（其后果不只是难看：旧参数模型是 `legacy_1ohm_to_reference`、`|Vdiff|≈1 V`，与反相的 2 V 差一倍，
下游任何按驱动做的归一化都会算错）。

### 2.2 最小且诚实的设计（待批准后再动手）

```text
① CLI 增加两个参数，**缺省值与现常量逐字节一致**：
     --model PATH         缺省 = 当前反相模型（不传则行为完全不变）
     --drive-mode NAME    缺省 = 当前 DRIVE_MODE
② 启动时**解析一次**，之后全部读解析结果（禁止第二真源）：
     model_path / model_sha256 / drive_mode 三件由同一个 resolve 入口产出；
     L1838 的 load 与四处记录全部改读该入口（含 sampler/dry-run 路径）。
③ fail-closed 校验：
     · PATH 必须存在且是文件，否则非零退出（不静默回退到缺省模型）；
     · **给了 --model 却没给 --drive-mode ⇒ 拒绝启动**（不得按文件名推断驱动 —— 那是"猜测模型内部"）。
     · （建议）声明式登记表 {model_sha256 → 允许的 drive_mode}，不匹配即拒绝；
       登记表入冻结，使"模型↔驱动"这对事实可第三方复核。
④ 产物里保留既有字段名 `model_sha256` / `drive_mode`（不新造别名），并新增 `drive_mode_source`
   说明它来自 CLI 还是缺省 —— 让"这次跑的是哪个模型、什么驱动"单源可读。
```

### 2.3 验证计划（不启动 COMSOL 的部分先做，COMSOL 部分需放行）

```text
(a) 不传参 ⇒ 与当前代码在**同一输入**下记录字段逐一相同（行为不变的第一性证明）
(b) --model <legacy 0f75ca1d…> + --drive-mode legacy_1ohm_to_reference ⇒ 记录值正确
(c) --model <legacy> 而**不传** --drive-mode ⇒ 非零退出 + 拒绝记录（负向测试）
(d) 旧码灵敏度：同一探针在冻结 1055 快照上必须失败（否则是无敏感性测试）
(e) 现有套件 83 断言全通过 + 机械差异 touched_defs_outside_declared_scope=[]
(f) 代码改动 ⇒ **新建冻结**（1055 会立刻 `INVALIDATED_BY_CODE_DRIFT`）
(g) 真跑 COMSOL 的只有"换模型后的最小执行"，且需人放行（单组合 7 频点 ≈ 8.4 min）
```

### 2.4 优先级诚实说明

`--model` 本身**不产出任何用户当前想要的数字**：旧参数侧真正缺的是
① **电气量**（旧数据 `Zin1 ≡ Zin2` 逐位相同 = 公式复制错误；电流因 KCL 相对误差 >1% 被排除）
② **带宽口径**（7 点/5 MHz 太粗，需在选定组合上加密到 0.25–0.5 MHz）。
二者都要**先在模型上改公式/改频率计划**，不在算力侧，也不是 `--model` 能解决的。
⇒ 若近期目标是"旧参数 + AI 求解器"，则 `--model` **不是**关键路径（AI 侧缺的是**场级留出集**，已由 x 族/POD 线在补）。
它的价值是：让**任何**未来的生产路径运行不再被写死的模型绑死。

---

## 3. 我没有做的事（边界）

- 没有改任何 `work/tools/*`（1055 仍 MATCH）；没有跑 COMSOL；没有新建/修改任何 run 目录或冻结；
- **没有**准备或启动 504 整批（备忘 §7 已记录用户选择"暂不跑全量"）；
- 没有动 solver 线的任何文件（R1–R14 已落点，§7 待裁决项**按文档要求不自行执行**）；
- 没有往 `INDEX-records-and-rulings.md` 追加 10-08 条目（那属另一条线的记录，双写者有前车之鉴）。

---

## 4. 未决项（需要人或上级 agent 裁决）

1. **方向**：本会话的线（LT2 监管器）已闭合到"试用 PASS + 504 由用户取消"。
   接下来是 (a) 做 step ④ `--model`（需新冻结 + 一小段 COMSOL），
   (b) 转 solver 线的 §7 裁决项（`p`/`p_total` 口径对齐、S4 空间对象、S3 补导出、Stage-2），
   还是 (c) 做维护（把 10-08 三轮补进 INDEX）？
   —— 我倾向 **(b) 的 §7.6 口径对齐取证**（它是文档自认的"不解决则 S3/S4 数字挂不上求解器"的头号阻塞，
   且取证属只读工作）；但该线可能由另一会话在推进，故不擅自介入。
2. **10-08 三轮未入 INDEX**：是否要我补登记（append-only，按 `scripts/append_record_section.py`）？
   若另一会话正在写 INDEX，请指定谁写，避免双写。
3. step ④ 若要动手，请给**放行**（我会：先做 §2.3 的 (a)–(f)，再报哈希等你建冻结；COMSOL 那一步另行申请）。
