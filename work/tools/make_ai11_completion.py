# -*- coding: utf-8 -*-
"""生成 `docs/AI11_COMPLETION_20261013.md`：**AI1.1 任务完成报告**（哈希从磁盘现算）。"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "docs/AI11_COMPLETION_20261013.md"
F = {
    "m_pre": "work/runs/ai11-m1m3-20261013/PREREG_M1_M3.json",
    "m1": "work/runs/ai11-m1m3-20261013/M1_RESULT_V2.json",
    "m1r": "work/runs/ai11-m1m3-20261013/M1_REPORT_V2.md",
    "m2": "work/runs/ai11-m1m3-20261013/M2_RESULT.json",
    "m3": "work/runs/ai11-m1m3-20261013/M3_RESULT.json",
    "man": "work/dist/peakguard-bench-v1-20261013/MANIFEST.json",
    "m4": "work/runs/ai11-m4-20261013/M4_PACKAGE_REPORT.json",
    "t7pre": "work/runs/ai11-t7-multiseed-20261013/dse/PREREG.json",
    "t7res": "work/runs/ai11-t7-multiseed-20261013/T7_MULTISEED_RESULT.json",
    "t7rep": "work/runs/ai11-t7-multiseed-20261013/T7_MULTISEED_REPORT.md",
    "tpre": "work/runs/ai11-t1t2t5-20261013/PREREG_T1_T2_T5.json",
    "t12": "work/runs/ai11-t1t2t5-20261013/T1_T2_RESULT.json",
    "t12r": "work/runs/ai11-t1t2t5-20261013/T1_T2_REPORT.md",
    "spre": "work/runs/ai11-t1t2t5-20261013/PREREG_T1_T2_SPACING_ADDENDUM.json",
    "sp": "work/runs/ai11-t1t2t5-20261013/T1_T2_SPACING_RESULT.json",
    "spr": "work/runs/ai11-t1t2t5-20261013/T1_T2_SPACING_REPORT.md",
    "t5": "work/runs/ai11-t1t2t5-20261013/T5_RESULT.json",
    "t5r": "work/runs/ai11-t1t2t5-20261013/T5_REPORT.md",
    "v17": "docs/PAPER_DAC2027_EN_v17_20261013.md",
    "supd": "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013d.md",
    "index": "docs/INDEX-records-and-rulings.md",
}
H = {k: (lambda p: (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()) if p.is_file() else (-1, "MISSING"))(REPO / v)
     for k, v in F.items()}
t7 = json.loads((REPO / F["t7res"]).read_text(encoding="utf-8"))
t12 = json.loads((REPO / F["t12"]).read_text(encoding="utf-8"))
sp = json.loads((REPO / F["sp"]).read_text(encoding="utf-8"))
t5 = json.loads((REPO / F["t5"]).read_text(encoding="utf-8"))
m4 = json.loads((REPO / F["m4"]).read_text(encoding="utf-8"))
m2 = json.loads((REPO / F["m2"]).read_text(encoding="utf-8"))
m3 = json.loads((REPO / F["m3"]).read_text(encoding="utf-8"))
man = json.loads((REPO / F["man"]).read_text(encoding="utf-8"))

L = []
def w(s: str = "") -> None:
    L.append(s)
w("# AI1.1 任务完成报告 · 2026-10-13")
w()
w("**目标**（用户裁定）：「不用考虑页数，现在就是要把 AI1.1 方向的任务做完」。")
w("**口径**：每一项都事后可追溯（预注册在前、结果在后、哈希现算）；`None`/未预测一律不写成通过；**人保留放行权**。")
w()
w("---")
w()
w("## 0. 七项基准任务（论文 §S12 的 T1–T7）——现状矩阵")
w()
w("| 任务 | 证据 | 关键读数 | 状态 |")
w("|---|---|---|---|")
w("| **T1** 峰身份 | `T1_T2_RESULT.json` | 5 类定义中 A/C 只有 3 类非空；hgb 平衡精度 **0.889（A）/ 0.956（C）** vs 多数类 0.333 | **已评** |")
w("| **T2** 带宽闭合 | 同上 | hgb 平衡精度 **0.978 / 0.977** vs 多数类 0.500 | **已评** |")
w("| **T3** 条件回归（两个正式目标） | 注册 N2 基线件 | 无一方法胜过 persistence（通道级 **8/20** 格） | **已评**（论文 §6.3） |")
w("| **T4** 拆分比较 | `M1_RESULT_V2.json` + §S11 | 两臂几何等价 ⇒ 差异是**拆分实现噪声**；注册拆分**未阻断** C 批 91 % 相邻格泄漏 | **已评** |")
w("| **T5** 拒答行为 | `T5_RESULT.json` | **160 格**（批×通道×方法）× 三档容差的 false-accept + pchip 结构性拒答模式 + 跨批接受率 | **已评** |")
w("| **T6** 跨批迁移 | `M3_RESULT.json` | 140 格有读数；迁移差中位 **≈ 0**（−0.0041 / +0.0020 / +0.0007） | **已评** |")
w("| **T7** 闭环调度 | `T7_MULTISEED_RESULT.json` + 原 N3 | k=5 主终点；A1 有 5 种子分布；**A2/A3/A4 补种子后逐 k 逐位相同（方差恰为 0）**；补齐**零新求解**（60 条全为缓存命中） | **已评（含多种子补齐）** |")
w()
w("---")
w()
w("## 1. 本轮新增的四件（把缺口逐个关掉）")
w()
w("### 1.1 T7 多种子补齐（**零新求解**：60 次记录全部命中既有逐点缓存）")
w()
w("- **原缺口**：注册设计里 `A1_random` 有 5 种子，而 `A2_greedy`/`A3_gp_ei`/`A4_gp_ei_gated` **各只有 1 条轨迹**（原 `design.seed_policy` 自述）。")
w("- **做法**：**匹配式补种子**（不是每种子 25 次），即 A2/A3/A4 各补种子 1–4、**每种子 5 次调用** ⇒ 每臂 = 5 种子 × 5 次调用，与 A1 完全对齐；")
w("  复用旧台账 **105 条**与旧逐点缓存 **94 个**。")
w("  ⚠️ **成本更正（INDEX §240）**：这 60 条记录**全部是缓存命中**（`cached: true`，且该目录内**没有** `dse_point.java`/`.java`/`.class` 产物）")
w("  ⇒ **实际新求解 = 0**；此前的「60 次新求解」说法**作废**。这与结论自洽：三臂的提议对种子不敏感，故提议点恰为种子 0 已求值过的点。")
w("- **结果（关键）**：")
w()
w("| 臂 | 种子数 | k≤5 的 best y（逐种子） | 跨种子逐 k 相同？ | 极差 |")
w("|---|---:|---|---|---:|")
for a in ("A1_random", "A2_greedy", "A3_gp_ei", "A4_gp_ei_gated"):
    blk = t7["per_arm"][a]
    ac = blk["_across_seeds"]
    same = "**是（y 与提议都相同）**" if (ac["y_identical_at_every_k"] and ac["proposal_identical_at_every_k"]) else "否"
    w("| `%s` | %d | %s | %s | %.3e |" % (a, ac["n_seeds"],
                                          ", ".join("%.4e" % x for x in ac["best_at_k5_list"]), same,
                                          ac["best_at_k5_spread"]))
w()
w("⇒ **补种子没有给出「分布」，而是给出一个更强的事实**：在这套注册设计下（固定 DOE、离散候选池、EI 在池上取 argmax、greedy 无随机性），")
w("**A2/A3/A4 对种子完全不敏感**。因此原限制「另三臂无种子复制」被**实测消解**：不是样本不足，而是这几个臂**没有可复现的种子方差**；")
w("同时确认 **A1_random 是本设计里唯一的随机来源**，论文 §6.3 的秩/分位口径**不变**。")
w()
w("### 1.2 T1/T2 状态预测任务（零求解）")
w()
w("- **语料事实（如实）**：A/C 原生标志里 `censored` 与 `truncated` **为空**（这两个标志只在 V2 上作为代理存在）⇒ 预注册的 5 类状态在本语料上**实为 3 类**（`complete` 1,677 / `no_peak` 232 / `unclosed` 96）；V2 因是代理标志被排除。")
w("- **结果**：hgb 的平衡精度 **T1 0.889（A）/ 0.956（C）**、**T2 0.978 / 0.977**，均远超多数类基线（0.333 / 0.500）；逐状态 recall 无 0。")
w("- **泄漏敏感性对照（追加预注册）**：注册拆分在 C 批有 91 % 相邻格泄漏，故另做**块留出**（连续 5 个 x 为一块，留出第 1/4/7 块）")
w("  ⇒ 留出与 train 的最近间隔中位 **0.0200**（仅 **%d** 行仍 ≤1 步）；" % sp["spacing_check"]["n_adjacent_or_less"])
w("  **T1 0.9555 → 0.9325（降 0.023）**、**T2 0.9769 → 0.9955（升 0.019）** ⇒ 按预注册判定 **「未检出显著抬高」**。")
w("  ⇒ **结论**：标签有效性（是否闭合、峰是否存在）**可由设计点 (x, N1, N2) 预测**，且这一结论**不是** x 邻接泄漏造成的。")
w()
w("### 1.3 T5 拒答行为合并评测（纯提取）")
w()
w("- **160 格**（3 批 × 通道 × 方法）的拒答覆盖率与三档容差下的 false-accept 并置；")
w("- pchip 的**结构性拒答模式**（跨种子合计）+ **跨批适用域接受率**（来自 M3）作为第二类拒答来源；")
w("- 明确区分两套弃权口径：**T5 = 结构性拒答**（定义域/口径），**M2 = 评分式弃权**（预注册的模型—基线分歧分），**不得混称**。")
w()
w("### 1.4 「标签策略消融」为什么两组数字完全相同（**不是缺陷**）")
w()
w("- N2 的 `A1_peak_semantics` 两臂（「按状态过滤」vs「当作普通值」）在每一格的中位数**逐位相同**。")
w("- **查明原因（语料事实）**：`bandwidth_Hz` **有值 ⟺ `bandwidth_closed` 为真** —— A 批 154/154、C 批 1523/1523，")
w("  反例（有值但未闭合）**= 0 行**；`Q` 同理随状态缺失。⇒ **数据本身已把过滤条件编码进去**，两臂在任何实现下都不可能不同。")
w("- ⇒ 结论：该消融**结构性无差异**（不是实现 bug，也不是「标签策略不重要」）。")
w("  **可发表含义**：一个看起来合理的消融，如果它切换的过滤条件已被数据编码，就是**空洞的**；")
w("  真正有意义的对照不是「过滤 vs 不过滤」，而是「**把 NaN 当缺失 vs 把它插补成值**」。")
w()
w("---")
w()
w("## 2. 外部评阅列出的 7 项 AI1.1 缺口 —— 逐项结清")
w()
w("| 缺口（外部评阅原文） | 状态 | 证据 |")
w("|---|---|---|")
w("| 标签策略消融 | **已存在**（N2 六项消融）＋ 本轮**查明其标签那项结构性无差异** | `n2_baselines/ablations.json`；本件 §1.4 |")
w("| random split 与 grouped split 消融 | **已完成**（M1，含机制核对后的更正） | `M1_RESULT_V2.json` |")
w("| 至少 5 个共同种子的闭环实验 | **已完成**（T7 匹配式补齐 60 次调用）⇒ 三臂种子方差**恰为 0** | `T7_MULTISEED_RESULT.json` |")
w("| risk–coverage 评测 | **已完成**（M2，700 格 / 140 聚合） | `M2_RESULT.json` |")
w("| 匿名 benchmark 发布包 | **已完成**（M4，13 文件、身份审计 0 风险串） | 包内 `MANIFEST.json` |")
w("| 一键复现脚本 | **已完成**（`python run_benchmark.py --check` ⇒ PASS，800 格逐格一致、最大偏差 0.0） | `M4_PACKAGE_REPORT.json` |")
w("| 跨批次或跨 FOM 测试 | **跨批已完成**（M3，三臂 140 格）；**跨 FOM 未做**（见 §3） | `M3_RESULT.json` |")
w()
w("---")
w()
w("## 3. 仍未做的一项（如实）")
w()
w("**跨 FOM（模型域）测试**：把 M-base 与 M-h1um 两套模型上的读数做同口径对照。")
w("- 现有证据**不足以**支撑：S0 的低频六频点标量在 **M-base** 上，而 S3/S4 的场/通量证据在 **M-h1um** 上；两者**不是同一份解的同一口径**。")
w("- 要做需要在该模型上重跑（新求解）；成本量级与 `#3` 的预注册同族（视频点数与网格而定）。")
w("- **本件不启动**：这属于「新 campaign + 新预注册」，按项目纪律须先出预注册与人裁定。")
w()
w("---")
w()
w("## 4. 交付物（哈希现算）")
w()
w("| 件 | 路径 | 字节 | sha256 |")
w("|---|---|---:|---|")
for lab, k in (("M1–M3 预注册", "m_pre"), ("M1 结果 V2", "m1"), ("M1 报告 V2", "m1r"),
               ("M2 结果（risk–coverage）", "m2"), ("M3 结果（跨批迁移）", "m3"),
               ("包 MANIFEST", "man"), ("M4 报告", "m4"),
               ("T7 扩展预注册", "t7pre"), ("T7 结果", "t7res"), ("T7 报告", "t7rep"),
               ("T1/T2/T5 预注册", "tpre"), ("T1/T2 结果", "t12"), ("T1/T2 报告", "t12r"),
               ("T1/T2 泄漏对照预注册", "spre"), ("T1/T2 泄漏对照结果", "sp"), ("T1/T2 泄漏对照报告", "spr"),
               ("T5 结果", "t5"), ("T5 报告", "t5r"),
               ("论文 v17", "v17"), ("补充材料 d", "supd"), ("INDEX 台账", "index")):
    b, h = H[k]
    w("| %s | `%s` | %s | `%s` |" % (lab, F[k], ("MISSING" if b < 0 else format(b, ",")), h[:16]))
w()
w("---")
w()
w("## 5. 不主张")
w()
w("- 不主张「AI1.1 会被接收」；不主张七项任务穷尽了失败模式；")
w("- 不主张 T1/T2 的状态分类有工程用途（状态是**语料定义量**）；不主张块留出等于「正确」口径；")
w("- 不主张 T7 的种子方差为 0 对**连续**候选空间或其它采集函数成立（离散池 + 确定性 argmax 是前提）；")
w("- 不主张跨批可比性、不主张任何工程绝对值；不提升任何模型状态；")
w("- 门禁与状态**未变**：`release_allowed = false`、`solver_spec = physics_consistent`。")
w()
w("---")
w()
w(f"*本件由 `work/tools/make_ai11_completion.py` 生成；全部哈希在生成时从磁盘读取后计算。*")

txt = "\n".join(L) + "\n"
if "\r\n" in txt:
    raise SystemExit("[FAIL] 生成文本含 CRLF")
OUT.write_bytes(txt.encode("utf-8"))
back = OUT.read_bytes()
print("写出 %s：%d B，sha256 %s" % (OUT.name, len(back), hashlib.sha256(back).hexdigest()))
print("引用 %d 件；MISSING %d 件" % (len(H), sum(1 for v in H.values() if v[0] < 0)))
