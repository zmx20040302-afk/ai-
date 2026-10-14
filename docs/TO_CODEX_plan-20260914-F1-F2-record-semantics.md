# F1/F2 改动方案（**只写方案，未改任何代码**）

- 日期：2026-09-14
- 来源：LT2 硬停演练（`lt2-drill-hardstop-u1u3-20260914-2204`）发现的两处"记录名与实际语义不一致"
- 基线冻结：`freeze-20260914-2040-post-guard-persistent`（`lt2_production.py` = `81936aeb…`，153,287 B）
- 父 agent 裁定：**要修，但另开一轮**；不推翻 U1–U3

---

## 0. 先给结论：两处修法的**已核实前提**（决定改动范围）

我先把"谁能被改、谁不能被改"查清了（**未改代码**）：

| 事实 | 核实结果 | 含义 |
|---|---|---|
| 冻结测试 T17e 是否断言 `pass_conditions` 的**键数** | **不**。它只断言 `isinstance(dict)` 且 `"commit_hard_stop_samples_0" in pc`（第 948–951 行），键数只用于打印 | 增键/改键名**不会**破坏 82 断言 |
| 是否有测试/检查器引用 `peak_ws_lt_12288` / `min_avail_ge_4096` / `min_commit_gt_4096` | **无**（`tests_lt2_supervisor.py` 0 处；`check_r3_conditions.py` 0 处——它自己按时间线算 `min_commit_gt_6144`） | 键名可安全参数化 |
| 是否有测试/检查器引用 `no_hard_stop_verdict_samples` | **无**（整个 `work/tools` 只有生产代码第 1490 行） | F2 可安全改语义 |
| 批量聚合里谁**消费**了这些键 | `run_supervisor.aggregate_pass_conditions` 消费 `commit_hard_stop_samples_0` 与 **`min_commit_gt_4096`** | 改后者名字必须**同批改聚合键** |
| 演练阈值是否已下传到 worker | 是（`supervise_child` 在 `--drill` 下把 `--drill` + 三个覆盖一并传给 worker；本次实测 worker 侧 `args.ws_hard_stop_mb=5000`） | `resolve_thresholds(args)` 在 worker 内可用且会给出 5000 |

---

## 1. F1：worker 侧阈值/摘要/判定应使用**生效阈值**（而非默认值）

### 现状（三处耦合，都是同一个 `th`）
```text
run_combo_worker 第 1642 行：th = Thresholds()          ← 默认值，忽略 --drill 覆盖
   ↳ finalize_after_solve(..., th=th)
        ├─ ck["thresholds"] = th.to_dict()                        → 记成 12288（应为 5000）
        ├─ summarize_timeline(jsonl_f, th)                        → stop_line_event_count=0（应为 5）
        └─ combo_pass_conditions(rows, summary, lt2c, cancel_rec, th)
             ├─ "peak_ws_lt_12288": (peak) < th.ws_hard_stop_mb        ← **键名内嵌 12288，取值却来自 th**
             ├─ "min_avail_ge_4096": min_avail >= th.physical_avail_hard_stop_mb   ← 同上
             └─ "min_commit_gt_4096": cm.min > th.commit_hard_stop_mb               ← 同上
```

### 提议改动（3 处，逐字给出）
```python
# (1) run_combo_worker：改用**唯一**阈值裁定点（与 supervisor/sampler 同源）
-    th = Thresholds()
+    th, th_rec = resolve_thresholds(args)      # 默认=Codex 值；--drill 下应用覆盖并留痕

# (2) finalize_after_solve 的 checkpoint：把"用的是哪套阈值"写清（自解释，不靠命名）
     ck = {..., "thresholds": th.to_dict(),
+          "thresholds_provenance": th_rec,     # {drill, defaults, overrides{default,drill_value}, effective, note?}
           ...}

# (3) combo_pass_conditions：键名不再内嵌数字（数字随 th 变，名字不能写死）
-        "peak_ws_lt_12288": (summary.get("server_peak_ws_mb") or 0) < th.ws_hard_stop_mb,
-        "min_avail_ge_4096": (...).get("min") is not None and ... >= th.physical_avail_hard_stop_mb,
-        "min_commit_gt_4096": (cm.get("min") is not None and cm["min"] > th.commit_hard_stop_mb),
+        "peak_ws_lt_hard_stop": (summary.get("server_peak_ws_mb") or 0) < th.ws_hard_stop_mb,
+        "min_avail_ge_hard_stop": (...).get("min") is not None and ... >= th.physical_avail_hard_stop_mb,
+        "min_commit_gt_hard_stop": (cm.get("min") is not None and cm["min"] > th.commit_hard_stop_mb),
     # 并新增（自解释，避免"名字里的数字"再次成为唯一线索）
+        "thresholds_used": {"ws_hard_stop_mb": th.ws_hard_stop_mb,
+                            "physical_avail_hard_stop_mb": th.physical_avail_hard_stop_mb,
+                            "commit_hard_stop_mb": th.commit_hard_stop_mb},
+        "thresholds_source": ("drill_override" if getattr(th, "_drill", False) else "codex_default"),
```
```python
# (4) 同批更新唯一消费者：run_supervisor.aggregate_pass_conditions
-        "min_commit_gt_4096": all((c.get("pass_conditions") or {}).get("min_commit_gt_4096") is True ...),
+        "min_commit_gt_hard_stop": all((c.get("pass_conditions") or {}).get("min_commit_gt_hard_stop") is True ...),
```

### 影响范围（逐项）
| 面 | 影响 |
|---|---|
| **生产运行（无 `--drill`）** | `resolve_thresholds(args)[0]` 返回的就是 `Thresholds()` 默认值 ⇒ **数值与今天逐一相同**（`thresholds`/`stop_line_event_count`/三条件全部不变）；**仅新增两个键**（`thresholds_provenance`、`thresholds_used`/`thresholds_source`）与**三个键改名** |
| 演练/阈值覆盖 | checkpoint 阈值变为 **5000**、`stop_line_event_count` 变为 **5**（本例）、`peak_ws_lt_hard_stop` 变为 **False**（峰值 7,334 > 5,000）——**这正是"生效值"应有的样子** |
| 子件 `pass_conditions` 键数 | 11 → **13**（T17e 不断言键数，安全） |
| 批量聚合 | 键 `min_commit_gt_4096` → `min_commit_gt_hard_stop`（同批改）；`commit_hard_stop_samples_0` 等不变 |
| 检查器 `check_r3_conditions.py` | 不读这些子键，自算 `min_commit_gt_6144` ⇒ 不受影响；它把 `aggregate_pass_conditions` 整块当 evidence 记录 ⇒ 需在报告中说明键名变化 |
| 外部读取者（若有） | 若有人在读 `min_commit_gt_4096`，会读不到。**备选 b2**：保留该键作为一条 `deprecated_alias`（同值 + 显式 `_deprecated` 说明）过渡一轮。**我推荐 b1 直接改名**（不留双源），请裁定 |
| 产物字节 | 生产路径的 **checkpoint 字节会变**（键改名 + 新增键）⇒ r3d 的 checkpoint 在新代码下**不可逐字节复现**（数值判据仍全部可复现） |

---

## 2. F2：`no_hard_stop_verdict_samples` 在取消场景下**空集恒真**

### 现状
```python
# finalize_after_solve 第 1480–1490 行
    engine_verdicts: list[dict] = []
    if cancel_rec is None:                     # ← 有取消记录时**根本不读时间线**
        try: engine_verdicts = [json.loads(l) for l in jsonl_f.read_text(...).splitlines() if l.strip()]
        except Exception: engine_verdicts = []
    hard = [v for v in engine_verdicts if v.get("verdict") == "hard_stop"]
    pc = combo_pass_conditions(...)
    pc["no_hard_stop_verdict_samples"] = len(hard) == 0     # ← 取消时 hard=[] ⇒ 恒 True
```
实测后果：`true`，而时间线有 **4 行** `verdict=hard_stop`。
另有同类隐患：**时间线读失败**时 `engine_verdicts=[]` ⇒ 也恒 True（**空集判通过**，违反"空集合判失败"）。

### 提议改动
```python
    # 始终统计（取消与否都统计）；**读失败 ⇒ None ⇒ 判 False（fail-closed）**
    hard_stop_verdict_samples: int | None = None
    try:
        hard_stop_verdict_samples = sum(
            1 for l in jsonl_f.read_text(encoding="utf-8", errors="replace").splitlines()
            if l.strip() and json.loads(l).get("verdict") == "hard_stop")
    except Exception:
        hard_stop_verdict_samples = None            # 不得当 0
    pc["no_hard_stop_verdict_samples"] = (hard_stop_verdict_samples == 0)   # None==0 → False ✓
    pc["hard_stop_verdict_sample_count"] = hard_stop_verdict_samples        # 给出数字，误读不了
```

### 影响范围
| 面 | 影响 |
|---|---|
| 生产正常路径 | 原来 `cancel_rec is None` ⇒ 已在读时间线 ⇒ **数值不变**（仍 True 当且仅当 0 行 hard_stop）；额外做一次同样的读（16–160 行，成本可忽略） |
| 取消/演练路径 | 由"恒真"变为**真实值**（本例 **False** + count=4）⇒ 子件 `pass_conditions` 会更"红"，但**child status 已是 `fail_or_limited`**（`frequency_rows_7=false` 等）⇒ **状态不变** |
| 批量聚合 | 该键不进 `aggregate_pass_conditions` ⇒ 不影响批次判定 |
| 键数 | 11(或 13) → +1（T17e 不断言键数，安全） |
| 命名 | 键名保持 `no_hard_stop_verdict_samples`（语义修正后名副其实）；新增计数字段便于读数 |

---

## 3. 最小执行（改完之后、报哈希之前）

按既定流程，**只做受影响路径的最小执行**（不启动真实 COMSOL）：

```text
1) 静态：py_compile + check_undefined_names.py（两个文件）
2) 机械差异基线：对**当前冻结 2040 快照**做 diff，要求 touched_defs ⊆ 声明范围
   （预计：<module>/resolve 相关常量、combo_pass_conditions、finalize_after_solve、
     run_combo_worker、run_supervisor）
3) 单元/最小执行（无 COMSOL）：
   a) **生产路径不变**：构造一次 finalize_after_solve（无 --drill）⇒ 断言
      thresholds == codex 默认、thresholds_provenance.drill == false、
      stop_line_event_count / 三条件**与旧代码同值**
   b) **演练路径生效值**：同一输入 + drill 覆盖 5000 ⇒ 断言 thresholds.ws_hard_stop_mb == 5000、
      stop_line_event_count == 5（本例时间线）、peak_ws_lt_hard_stop == False、
      thresholds_provenance.overrides == {ws_hard_stop_mb:{default:12288.0, drill_value:5000.0}}
   c) **F2 正确值**：注入 4 行 hard_stop 的时间线 + cancel_rec ⇒ 断言
      no_hard_stop_verdict_samples == False 且 count == 4
   d) **F2 fail-closed**：把 jsonl_f 指到不存在路径 ⇒ 断言
      no_hard_stop_verdict_samples == False 且 count is None（**不得为 True**）
   e) **灵敏度**：把 (a)–(d) 同一套断言跑在 2040 快照旧代码上 ⇒ 必须失败（证明测试不是空断言）
4) 冻结件回归：82 断言套件（新命名空间）应仍 **82/82**
5) 冻结化最小执行：建临时冻结 → frozen smoke A/B/B2（三布尔 true + 确定性对照）+ guard 两场景
6) 报新哈希 → 父 agent 建新 freeze
```

## 4. 冻结与重跑影响（请裁定）

```text
① 代码一改，2040 冻结立即 drift ⇒ 必须新建 freeze（流程同前）。
② **演练必须重跑**（我同意父 agent 的倾向）：本次改的正是**取消路径的记录逻辑**
   （worker 的 th、取消时的 verdict 统计），而演练是**唯一**能端到端验证它的手段。
   重跑前仍需满足：avail ≥ 18,000 且 commit ≥ 21,500、无并行负载、命令原样。
③ **资源确认（r3d）是否需要重跑？** 这是需要你判定的点，我的分析：
   - 判据层面：改动不改变生产路径的**数值**，r3d 的 23 条判据在三布尔/资源轴/容差/身份上都会复现；
   - 产物层面：生产路径的 **checkpoint 字节会变**（三键改名 + 新增键）⇒ r3d 的 checkpoint
     在新代码下**不可逐字节复现**（数值仍可复现）。
   ⇒ 若坚持"被接受的那次运行必须与冻结代码逐字节对齐"，则应补跑一次 **r3e**（约 14 min）；
     若接受"数值判据可复现即算通过"，则 r3d 可保留、只重跑演练。
   **我的建议：补跑 r3e**——成本一次求解，换掉"被接受产物与冻结代码不一致"的隐患。
```

## 5. 明确不做

```text
本轮**未改任何代码**、未改阈值、未改判定逻辑、未启动 LT2 生产批次、未清理现场。
F1/F2 的修与重跑，等你建完新 freeze 并放行后再动手。
```
