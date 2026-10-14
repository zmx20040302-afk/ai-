# -*- coding: utf-8 -*-
"""生成 `docs/WORK_REPORT_20261013.md`：本轮（2026-10-12 → 13）全部工作的**详细汇报**。

所有文件哈希由本脚本在运行时**从磁盘现算**；结论一律挂证据件；自查错误与不主张单列。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "docs/WORK_REPORT_20261013.md"


def sha(rel: str) -> str:
    p = REPO / rel
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "MISSING"


def meta(rel: str) -> tuple[int, str]:
    p = REPO / rel
    if not p.is_file():
        return (-1, "MISSING")
    return (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())


L: list[str] = []


def w(s: str = "") -> None:
    L.append(s)


# ---------------------------------------------------------------- 数据
F = {
    "s0_pre": "work/runs/s0-rerun-20261013/PREREG_S0_V2.json",
    "s0_res": "work/runs/s0-rerun-20261013/S0_RESULT_V2.json",
    "s0_rep": "work/runs/s0-rerun-20261013/S0_REPORT_V2.md",
    "s3_pair": "work/runs/s3-band-20261013/S3_ALIGNMENT_20261013.json",
    "s3_op": "work/runs/s3-band-20261013/S3_ALIGNMENT_20261013_OPERATIVE.json",
    "s3_band": "work/runs/s3-band-20261013/S3_BAND_RESULT.json",
    "spec": "work/runs/solver/pmut-f1/solver_spec.json",
    "ledger": "work/runs/solver/pmut-f1/release_log.jsonl",
    "promo": "work/runs/solver/pmut-f1/STATE_PROMOTION_20261013.json",
    "gate_f": "work/runs/eda64-20261010/EDA65_RELEASE_GATE_AMENDED_20261013F.json",
    "gate_g": "work/runs/eda64-20261010/EDA65_RELEASE_GATE_AMENDED_20261013G.json",
    "i3_pre": "work/runs/eda64-20261010/item3-prereg-20261013/PREREG_ITEM3_FREQUENCY_DESIGN.json",
    "i3_cost": "work/runs/eda64-20261010/item3-prereg-20261013/COST_ESTIMATE.md",
    "n4_reex": "work/runs/eda64-20261010/item3-prereg-20261013/N4_REEXAMINATION_OF_ITEM3.md",
    "v13": "docs/PAPER_DAC2027_EN_v13_20261013.md",
    "v14": "docs/PAPER_DAC2027_EN_v14_20261013.md",
    "v15": "docs/PAPER_DAC2027_EN_v15_20261013.md",
    "v16": "docs/PAPER_DAC2027_EN_v16_20261013.md",
    "supc": "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013c.md",
    "v17": "docs/PAPER_DAC2027_EN_v17_20261013.md",
    "supd": "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013d.md",
    "track": "docs/TRACK_CHOICE_ASSESSMENT_20261013.md",
    "codex": "docs/CODEX_REVIEW_20261013.md",
    "m_pre": "work/runs/ai11-m1m3-20261013/PREREG_M1_M3.json",
    "m1v2": "work/runs/ai11-m1m3-20261013/M1_RESULT_V2.json",
    "m2": "work/runs/ai11-m1m3-20261013/M2_RESULT.json",
    "m3": "work/runs/ai11-m1m3-20261013/M3_RESULT.json",
    "m4man": "work/dist/peakguard-bench-v1-20261013/MANIFEST.json",
    "m4rep": "work/runs/ai11-m4-20261013/M4_PACKAGE_REPORT.json",
    "index": "docs/INDEX-records-and-rulings.md",
}
H = {k: meta(v) for k, v in F.items()}
man = json.loads((REPO / F["m4man"]).read_text(encoding="utf-8"))
gate = json.loads((REPO / F["gate_g"]).read_text(encoding="utf-8"))
spec = json.loads((REPO / F["spec"]).read_text(encoding="utf-8"))
led = [l for l in (REPO / F["ledger"]).read_text(encoding="utf-8").splitlines() if l.strip()][-1]


def row(label: str, key: str) -> str:
    b, h = H[key]
    return f"| {label} | `{F[key]}` | {b:,} | `{h[:16]}…` |"


w("# 工作汇报 · 2026-10-13（覆盖 2026-10-12 夜 → 10-13 全日）")
w()
w("**汇报范围**：从你裁定「不接受事后口径 ⇒ 补事前预注册并重跑」开始，到论文 v16 与 AI1.1 匿名 benchmark 包为止的全部工作。")
w("**纪律**：本文每个数字都挂证据件；`None`/`inconclusive` 一律不写成通过；**人保留放行权**；未提升任何超出你裁定的状态。")
w()
w("---")
w()
w("## 0. 一页速览")
w()
w("| 维度 | 当前状态 |")
w("|---|---|")
w(f"| 门禁链 | 第 7 轮（F/G 两次修订），**{gate['n_satisfied']} `satisfied` / {gate['n_partial']} `partial` / {gate['n_not_satisfied']} `not_satisfied`**，`release_allowed = {str(gate['release_allowed']).lower()}` |")
w(f"| 唯一硬缺口 | **`#3`**（完整一阶谐振频响）：覆盖名义存在，但被判据拒绝（13.9–16.1×）+ 端口频响未导出 |")
w(f"| 模型状态 | `solver_spec.state = {spec['state']}`（由仓库状态机提升，**非**代码自我放行）；`solve()` 实测仍拒答 |")
w("| 论文 | **v17**（最新候选，M5 重定位为 reliability benchmark，未编译）；v6–v16 与四份补充材料快照全部保留 |")
w("| 补充材料 | `…_SUPPLEMENT_20261013d.md`（＝v16 时代件 + **§S12 任务规格**；c 档含 §S11） |")
w("| AI1.1 交付 | M1（拆分消融＋机制更正）、M2（risk–coverage）、M3（跨批迁移）、**M4 匿名可复现包** |")
w("| 包内一键复现 | **PASS**：800 格逐格一致、最大相对偏差 **0.000e+00**、含 6 项消融、407 s |")
w(f"| INDEX 台账 | §1–§236，{(REPO / F['index']).stat().st_size:,} B，append-only（**本汇报另记于 §237**） |")
w("| 本机 COMSOL | **本轮全程零求解**（所有结论来自既有冻结件） |")
w()
w("---")
w()
w("## 1. 你给的裁定链（本文按此组织）")
w()
w("1. 「**不接受事后口径** ⇒ 补事前预注册并重跑」→ §2.1 S0；")
w("2. 「**S3 现在就对齐**」→ §2.2；")
w("3. 选择题：`#4` 处置、FOM 载体口径、第一跳状态、`#3` 启动方式 → §2.3 / §2.4；")
w("4. 「**现在就出 v13/v14**」→ §2.6；")
w("5. 「`#3` 重审」→ §2.5；")
w("6. 「**AI1.1 主投、保留 EDA6.4**」＋「按 M1→M3 做起来」→ §2.8；")
w("7. 「**继续 M4**」→ §2.9；")
w("8. 「**先做 v16**」＋「给我一个详细的汇报」→ 本文。")
w()
w("---")
w()
w("## 2. 逐件工作")
w()
w("### 2.1 S0（极限一致性）：补**事前预注册**后零求解复算 ⇒ `passed`")
w()
w("**诉求**：你裁定不接受事后口径。**做法**：先冻结协议，再从冻结原始件复算；两个输入件 sha256 实测相符才继续。")
w()
w("| 频点 (MHz) | `rho_eff` (kg/m³) | `rel_err` | 判定 |")
w("|---:|---:|---:|---|")
for f, r, e in ((0.25, 999.1045887373, 9.0380e-4), (0.5, 999.0953844349, 8.9458e-4),
                (1.0, 999.0585804148, 8.5771e-4), (2.0, 998.9115817822, 7.1044e-4),
                (5.0, 997.8927765554, 3.1020e-4), (20.0, 982.9993227127, 1.5230e-2)):
    w(f"| {f:g} | {r:.10f} | {e:.4e} | {'**超 1 %**' if e > 0.01 else '阈内'} |")
w()
w("**结论**：判据频点 0.25 MHz 上 `rel_err = 9.0380e-04 ≤ 1 %`，**余量 11.1×** ⇒ `passed`；")
w("与既有分析件 **6/6 频点逐位相同（diff = 0.000e+00）** ⇒ 是复现、不是重新拟合。")
w()
w("**必须同现**：**先注册**的那条口径（空间各向同性 / r⁻¹ 律）**仍 `failed`**（0.0083 / 0.0290 > 0.01，且非单调）。")
w("**四条限制**：① 口径选择本身**仍事后**（预注册只覆盖*评测协议*）；② 残差非单调 ⇒ ≈0.03–0.09 % 系统底噪；")
w("③ 只覆盖单极子成分；④ 载体 λ/5 网格与 x 族求解器实例的绑定未做。")
w()
w("**附**：本轮实测 S0 的载体 `input.mph` sha256 = `0f75ca1df9262f27…` = **冻结 FOM M-base 本身** ⇒ S0 证据就落在冻结 FOM 上。")
w()
w("| 证据件 | 路径 | 字节 | sha256 |")
w("|---|---|---:|---|")
for lab, k in (("S0 预注册", "s0_pre"), ("S0 结果", "s0_res"), ("S0 报告", "s0_rep")):
    w(row(lab, k))
w()
w("### 2.2 S3：口径对齐（两分支并置 → 你签字选 B）⇒ 9/9、`S3_complete = true`")
w()
w("**要对齐的不一致**：你已裁定「能量项关闭」，但 S3 证据件里 `S3_complete` 仍是 `false`。")
w("**为什么不能裸翻字段**：仓库自己的审计器 `src/memsharness/s3_gate_audit.py` 第 69 行写死")
w("「判定非 `passed` 却置 `S3_complete=True`」为不自洽；判据本体 `verdict_from_checks()` 是 fail-closed。")
w()
w("**权威基线**（我第一版选错了，见 §5-3）：`c-batch-20261010/s3_gate_c_batch.json`，9 项 **7 通过 / 2 失败 / 0 未决**。")
w()
w("**两处口径**：① 电流守恒（登记口径 VOID）⇒ 改「闭合 28 面 + 物理场法向」（人签 2026-10-12）；")
w("② 能量项（登记 `False` 6.1768 %、外推 ≈ −3.78 %）⇒ 你在三选一中**选改口径**，采用**条文①′**（声学侧 17 面净外通量，τ = 0.5 %，取向逐面实测）。")
w()
w("| f (MHz) | 判据网格 | 17 面残差 | 余量 |")
w("|---:|---|---:|---:|")
for f, g, r, m in ((5, "λ/9", 0.034639, 14.43), (10, "λ/9", 0.136818, 3.65), (15, "λ/11", 0.206549, 2.42),
                   (20, "λ/11", 0.365297, 1.37), (25, "λ/13", 0.377494, 1.32), (30, "λ/16", 0.353731, 1.41),
                   (35, "**λ/18**", 0.382620, 1.31)):
    w(f"| {f} | {g} | {r:.6f} % | {m:.2f}× |")
w()
w("**生效件**：判定由仓库判据本体**现算** ⇒ `verdict = passed`、**9/9**、**`S3_complete = true`**；审计 `ok = true`。")
w("**负对照（已跑）**：换回分支 A 的 checks 而 `S3_complete` 仍为 `true` ⇒ 审计器报 4 项问题 ⇒ 证明该字段**由 checks 推出**、非手填。")
w("**退役 ≠ 抹除**：电—声一致口径 **6.1768 %**、趋势 −4.8517/−4.3837/−4.1205、**外推 ≈ −3.78 %** 逐字保留在 `retired_items`。")
w()
w("**随「关闭」同行的限制**：两条声明偏离（`-np` 门禁被覆盖为 8；**逐频点各自网格 ⇒ 35 MHz 判据网格 λ/18、λ/19 无 35 MHz 实测值**）；")
w("两次基建失败（λ/19/np=8 中止 36 min；λ/19/35 MHz/np=16 MUMPS out-of-core）；**上边界余量 ≈1.3× 是规则算出来的**（判据若改 0.3 % 上边界多数不过）；")
w("**只动 `ftet1` 一条轴**（非全模型网格收敛、非 Richardson 误差界）；**跨频点残差不得互比**。")
w()
w("| 证据件 | 路径 | 字节 | sha256 |")
w("|---|---|---:|---|")
for lab, k in (("S3 两分支并置件", "s3_pair"), ("S3 生效件（分支 B）", "s3_op"), ("S3 全频段实测", "s3_band")):
    w(row(lab, k))
w()
w("### 2.3 模型状态提升：`draft → physics_consistent`（走仓库自己的状态机）")
w()
w("**做法**：`src/memsharness/solver.py::apply_state(write=True)` —— **未手写任何状态**；证据**现算**")
w("（S0 取判据频点值；S3 由 9 项 checks 经 `verdict_from_checks()` 重推 `passed`）。")
w()
w(f"- `solver_spec.json`：2,559 B（sha `21315173fd2732c7…`）→ **{H['spec'][0]:,} B（sha `{H['spec'][1][:16]}…`）**，`state = physics_consistent`；")
w("  **变动的顶层键只有 `['release', 'state']`**（脚本断言）；`validate_spec()` 通过；**提升前字节逐字节另存**（本仓库无 git）。")
w(f"- **放行台账**（append-only）追加 1 条：`{led[:200]}`")
w("- **运行时强制已实测**：`solve()` 仍 `refused=True`、`fallback=comsol`（只有 `approved_solver` 才能出解）。")
w()
w("| 证据件 | 路径 | 字节 | sha256 |")
w("|---|---|---:|---|")
for lab, k in (("solver_spec（提升后）", "spec"), ("放行台账", "ledger"), ("状态提升记录", "promo")):
    w(row(lab, k))
w()
w("### 2.4 门禁第 6 轮（F）：`#4` ⇒ `satisfied` ＋ 两处过时文本更正")
w()
w("E 轮把 `#4` 的改判条件**自己写死**为「待 ① S0、② 签字」；两件均已就位 ⇒ 依你选的 **F1** 改判。")
w("同时更正两处**过时** gap：`#5` 删「FOM 未裁定」（FOM 已于 10-12 冻为 **M-base**），改写为「S4 载体 **M-h1um** ≠ 冻结 FOM ⇒ 『在最终 FOM 上』字面未满足」；")
w("`#7` 改写为「电—声功率平衡仍未闭合（6.1768 %、外推 ≈ −3.78 %），但**不再是** `#4` 的 S3 失败项」。")
w()
w("### 2.5 `#3` 重审 ⇒ 门禁第 7 轮（G）")
w()
w("**发现**：`n4_multifreq/` 是一份**已执行完毕**的多频场 campaign（预注册 `FROZEN_BEFORE_ANY_N4_SOLVE`、载体＝**冻结 FOM M-base**、")
w("13 频点 × 30 设计点、台账 34 条全 ok、`aligned/` 35 npz），而 `#3` 原文本写「场快照语料 = 仅 20 MHz」——**过时**。")
w()
w("**它产出的结论**：20 MHz 回归靶量级对拍通过（全域 1.2263 / 1.2997 %，关键区 0.5019 / 0.5632 %）；")
w("**交叉格 S1 失败**：注册口径 `linear`/k=4 关键区 max —— 3/9 格 27.0794 / 30.8683 %，**9/9 格更正后 27.7575 / 32.1885 %** ⇒ 最差 **16.1×**。")
w("**定因**：k=4 → k=120 自重构 → 0.000 % 而交叉格不变 ⇒ **非基截断**；预注册 stage-3「只改频率轴」重设计后最好 `cubic` 仍 **26.46 %**，")
w("单极点谐振**在自身训练数据上**就失败（68.56 / 76.13 %）⇒ **瓶颈在表示**。")
w()
w("**你选 ③**：`#3` 维持 `not_satisfied`，gap 重写为「覆盖名义存在但被判据拒绝（13.9–16.1×）」+「端口频响未导出」+「修法在表示层、不是再加密采样」。")
w()
w("### 2.6 `#3` 预注册草案 + **实测**成本模型（你选 T1：先出件、不跑）")
w()
w("**O1–O4 已裁定**：载体 = **M-base**；场变量用 `p` / `acpr.p_t` 并在同变量上重导 20 MHz 靶；主批 x 用协议默认（`N1 ∈ {{4,7}}` × 12 x）；网格固定 λ/5。")
w()
w("| 网格 | 单元数 | DOF | 每频点求解 (s) |")
w("|---|---:|---:|---:|")
for g, e, d, t in (("λ/5", 342886, 900431, 74.6), ("λ/9", 592560, 1239686, 91.9), ("λ/11", 862410, 1603812, 156.4),
                   ("λ/13", 1263824, 2144396, 278.1), ("λ/16", 2172398, 3366598, 578.5), ("λ/18", 2999251, 4476473, 1575.5),
                   ("λ/19", 3489637, 5134258, None)):
    w(f"| {g} | {e:,} | {d:,} | {'**失败**（MUMPS out-of-core）' if t is None else f'{t:.1f}'} |")
w()
w("**工作量 329 次频域解**（312 主批 + 9 交叉留出 + 8 先导）⇒ **λ/5 约 6.81 h**。")
w("**两处更正**：协议旧估计「35–50 s/点」偏乐观 1.5–2.3×；**我先前说的「~17 s/频点」是错的**——")
w("那来自 S0 的 `s0_close3`，而该件 `study.run(` 出现 **0** 次（**纯后处理**，6 频点共 12.7 s）。")
w()
w("### 2.7 论文 v13 → v14 → v15 → v16")
w()
w("| 版本 | 关键改动 | 词数 | 验证 |")
w("|---|---|---:|---|")
w(f"| **v13** | 补 **S0 段**与门禁语义 S0 行；S3 改三段式（7/2 → 8/1 → 9/9）并写明「通过记录的是两个人签口径，不是功率平衡」；摘要/结论/限制同步 | 5,225 | `verify_v7.py` pass |")
w(f"| **v14** | 摘要「by 10×」→ 实测 **27.76 % / 32.19 %（13.9× / 16.1×）**（正文本来写对，只对齐） | 5,234 | pass |")
w(f"| **v15** | **拆分描述事实更正**：分组变量 = **重复簇**（541/2,255 = 24 %）；精确重复泄漏 0；**x 邻接泄漏 C 批 91 %** 披露；摘要/贡献/§6.3 改 duplicate-aware；§6.3 补 8/20 vs 7/20 一致性；补充材料新增 **§S11** | 5,402 | pass |")
w(f"| **v16** | 把「**自包含 benchmark 包 + 一条命令复现全表与 6 项消融**」写进贡献 C3 与 §6.3（并如实注明**尚无第三方运行过**） | **5,484** | pass |")
w(f"| **v17（= M5 重定位）** | 标题 → **PeakGuard-Bench: A Reliability Benchmark…**；摘要以「一个谐振多物理场设计任务的代理模型应该怎样被评测？」开篇；贡献 **C1–C4 → B1–B4**（冻结语料／参考实现／任务规格／门禁即结果）；第 4 节标题改「The benchmark and its reference implementation」；引言补一句关于「问题」而非「数字」的泛化；补充材料新增 **§S12 七项任务规格（T1–T7）** | **5,604** | pass |")
w()
w("**共同自检**：往返逐字节还原上一版、双盲扫描干净、无 CRLF、报告哈希从磁盘算、补充材料结构逐字节校验。")
w()
w("| 论文/补充材料 | 字节 | sha256 |")
w("|---|---:|---|")
for lab, k in (("v13", "v13"), ("v14", "v14"), ("v15", "v15"), ("v16", "v16"), ("v17（M5 重定位）", "v17"),
               ("补充材料 c（含 §S11）", "supc"), ("补充材料 d（含 §S12）", "supd")):
    w(f"| `{pathlib.Path(F[k]).name}` | {H[k][0]:,} | `{H[k][1][:16]}…` |")
w()
w("### 2.8 AI1.1：方向评估 + M1/M2/M3")
w()
w("**方向评估**（`docs/TRACK_CHOICE_ASSESSMENT_20261013.md`）：AI1.1 主投（缺口几乎全在零求解侧）、")
w("EDA6.4 保留（补 5 种子 ≈ 6–7 h 求解即可）、**EDA6.5 本轮不投**（核心结果硬失败，且外部建议的 vector fitting 已在仓库里试过并爆掉 3–4 个数量级）。")
w()
w("**M1（random vs grouped split 消融，零求解）**：")
w("- V1 按**预注册三条规则**全部触发（D1 46 格、D2、D3）；")
w("- **V2 机制核对推翻了 V1 的解读**：两臂在**三个批**上几何等价（相邻格比例 Δ ≤ 4.2 pp）⇒ 差异是**拆分实现噪声**；")
w("- **采纳的结论**：① 评测结论对拆分实现**不稳定**（同一批只换留出行，C 批 9/63 格中位误差变动 >10 %，双向）；")
w("  ② 「随机拆分系统性改变结论」**未获支持**；③ **新发现**：注册的「grouped」拆分挡的是**重复簇/跨批重复**泄漏，")
w("  **没有**挡 x 邻接插值泄漏（C 批 **91 %**）；④ 「无方法胜过 persistence」的通道级计数 **grouped 8 / 20、random 7 / 20**（与论文 §6.3 逐个一致）。")
w()
w("**M2（risk–coverage）**：预注册 score = 模型与强基线的归一化分歧；700 格 / 140 聚合。")
w("风险随覆盖率下降**只小幅下降**（典型 5–15 % 相对），**没有任何格子在 cov 0.85 处进到 2 % 以内**。")
w()
w("**M3（跨批迁移）**：迁移差（跨批 median − 同批 median）**中位 ≈ 0**（C→A −0.0041、A→C +0.0020、A∪C→V2 +0.0007），分布很宽（−0.269 … +0.211）；**预注册不设阈值**，只作描述。")
w()
w("### 2.9 M4：匿名可复现 benchmark 包")
w()
w(f"**包**：`work/dist/peakguard-bench-v1-20261013/`（**{man['n_files']} 个文件**，逐件 sha256 见包内 `MANIFEST.json`，sha `{H['m4man'][1][:16]}…`）。")
w("数据**逐字节复制**（4 个 CSV 的 sha 与源件相同）；代码 vendored 并**路径脱敏**（19 处单命中替换 + 内联 `_identity_key`）；")
w("期望值**从注册件提取**（160 个 (批×通道×方法) × 5 种子）。")
w()
w("**包内一键复现（实测）**：`python run_benchmark.py --check` ⇒ **PASS**：")
w("逐格 OK **800**、超容差 0、缺失 0、**最大相对偏差 0.000e+00**（容差 1e-6）、同时跑通 **6 项消融**、墙钟 **407.4 s**；")
w(f"环境记录：Python {man['environment_recorded']['python']} / numpy {man['environment_recorded']['numpy']} / scipy {man['environment_recorded']['scipy']} / sklearn {man['environment_recorded']['sklearn']}。")
w()
w("**身份/双盲审计（两轮）**：构建时 13 个文件 **0 风险串**；冒烟后发现 **3 个 `.pyc` 内嵌绝对路径与用户名**，已删除并复核（14 文件、0 风险串、清单一致性 True）。")
w()
w("**留给人**：许可证（包内 `NOTE_on_license.md` 故意未定）、公开时机与补充材料提交规则。")
w()
w("### 2.10 M5：重定位与写作（论文 v17）")
w()
w("**目标**：把论文从「一个代理流程」改写成 **AI1.1 的 reliability benchmark**（外部评估指出的最大风险是「被评成 PMUT 数据整理」），")
w("**只重述既有证据、不新增技术结论、不改任何阈值**。12 处正文单命中替换 + 补充材料新增 §S12：")
w()
w("| 改动 | 内容 |")
w("|---|---|")
w("| 标题 | `PeakGuard-Bench: A Reliability Benchmark for Surrogate-Assisted Multiphysics Design Automation` |")
w("| 摘要定调 | 以「**一个谐振多物理场设计任务的代理模型应该怎样被评测？**」开篇，再给载体（PMUT）与「七个指定评测任务」；结尾补「语料/冻结拆分/参考实现以自包含包发布」 |")
w("| 贡献表 | **C1–C4 → B1–B4**：冻结语料与标注协议／分层参考实现／**任务规格＋评测协议**／门禁即结果；B3 指向 §S12 |")
w("| 第 4 节 | `## 4. PeakGuard` → `## 4. The benchmark and its reference implementation` |")
w("| 引言 | 补一句**关于「问题」而非「数字」**的泛化：哪些标签可比、哪种拆分泄漏、是否胜过强基线、何时该拒答——不只 PMUT |")
w("| 补充材料 §S12 | **七项任务规格（T1–T7）**：输入／主指标／拒答规则／证据位置；＋「包覆盖什么」＋「**刻意不主张什么**」 |")
w()
w("**自检**：反向替换逐字节还原 v16；补充材料按「原文 + §S12」逐字节校验；额外禁词扫描（含 `work/dist`、`peakguard-bench-v1`、长 hex）；`verify_v7.py` ⇒ **pass**。")
w(f"**词数影响**：v16 5,484 → **v17 5,604（+120）**；含 AI 与参考 **6,192**。⇒ **编译与削减更紧迫**（候选块见 INDEX §228；本轮的标题/摘要/B1–B4/§S12 指针属**重定位必需**，不宜削）。")
w()
w("---")
w()
w("## 3. 交付物清单（哈希现算）")
w()
w("| 件 | 路径 | 字节 | sha256 |")
w("|---|---|---:|---|")
for lab, k in (("S0 预注册", "s0_pre"), ("S0 结果", "s0_res"), ("S0 报告", "s0_rep"),
               ("S3 两分支并置", "s3_pair"), ("S3 生效件", "s3_op"), ("S3 全频段实测", "s3_band"),
               ("solver_spec（提升后）", "spec"), ("放行台账", "ledger"), ("状态提升记录", "promo"),
               ("门禁 F 轮", "gate_f"), ("门禁 G 轮（最新）", "gate_g"),
               ("#3 预注册草案", "i3_pre"), ("#3 成本估算", "i3_cost"), ("#3 重审发现件", "n4_reex"),
               ("论文 v13", "v13"), ("论文 v14", "v14"), ("论文 v15", "v15"), ("论文 v16", "v16"),
               ("论文 v17（M5 重定位）", "v17"),
               ("补充材料 c", "supc"), ("补充材料 d", "supd"), ("方向评估", "track"), ("Codex 交接件", "codex"),
               ("M1–M3 预注册", "m_pre"), ("M1 结果 V2", "m1v2"), ("M2 结果", "m2"), ("M3 结果", "m3"),
               ("包 MANIFEST", "m4man"), ("M4 报告", "m4rep"), ("INDEX 台账", "index")):
    w(row(lab, k))
w()
w("---")
w()
w("## 4. 本轮我自查出的自身缺陷（全部已修并留痕）")
w()
w("| # | 缺陷 | 类别 | 固化规则 |")
w("|---:|---|---|---|")
w("| 1 | 预注册 JSON 混入 ASCII 双引号 ⇒ `json.loads` 报错 | **同类第 6 次** | 中文语境一律用「」；禁止在双引号串内用 ASCII `\"` |")
w("| 2 | 运行产物行尾 LF/CRLF 不一致 | 惯例 | 统一并**用归一化字节相等自证「只动行尾」** |")
w("| 3 | S3 对齐**基线选错**（用 `p2/s3_gate_expand.json` 而非登记件） | 证据选取 | 只认 `registered_gate` 指向的件 + 已签更正，**不得按时间戳挑基线** |")
w("| 4 | v13 首版删掉被验证器锁定的「8 passes and 1 failure」 | 叙事编辑 | 修叙事**不得删**已被验证器锁定的历史数字 |")
w("| 5 | 生成器漏一个右花括号 ⇒ `SyntaxError` | 代码 | 长嵌套字面量出错**先用工具定位**（写了 `scan_brackets.py`） |")
w("| 6 | 把**后处理耗时**当求解耗时（「~17 s/频点」） | 数字口径 | 引用耗时前**先确认该运行是否真的求解**（判据 = java 里 `study.run(` 次数） |")
w("| 7 | 脚本用 `%` 格式化中文文本 ⇒ `TypeError` | **同类第 7 次** | 中文文本一律哨兵 `@X@` + `.replace()` |")
w("| 8 | §231 的哈希写在**改件之前** | 记录纪律 | **先定稿、再算哈希、再写记录** |")
w("| 9 | 我推测「逐设计点开窗可修 `#3`」——**被仓库已有预注册实验否证** | 推测当结论 | 报机制前**先检索仓库是否已有针对它的预注册实验** |")
w("| 10 | M1 通道级计数把「**无数据**」当成「输给 persistence」 | 分母纪律 | **无数据 ≠ 输**；先算**可判定基数** |")
w("| 11 | M1 邻接度量用绝对阈值 0.01，把**网格步长**与拆分结构混在一起 | 度量口径 | 度量必须**按尺度相对化**，并同时报一个不依赖尺度的量 |")
w("| 12 | 打包护栏按「我以为的形态」写 ⇒ 漏过 `str(REPO / \"src\")` 与 `relative_to(REPO)` | 护栏 | 护栏按**禁止集合**写（任何残留内部字样一律 fail-closed） |")
w("| 13 | `parents[]` off-by-one（`work/runs/<batch>/` 的**文件**常量是 `[3]`） | 路径 | **同类第 7 次** ⇒ 文件/目录常量分开记，且加「目标必须存在」断言 |")
w("| 14 | 审计扫不存在的目录却**静默返回 0 文件** | 静默失败 | 任何扫描/审计先断言目标存在 |")
w("| 15 | `.pyc` 内嵌绝对路径与用户名 | 双盲 | 投稿包末步**必删 `__pycache__`/`*.pyc`** 并复核 |")
w("| 16 | 内联 Python 被 PowerShell 吃掉引号/反引号（多次） | 环境 | 复杂 Python **一律写 `.py` 文件**再跑 |")
w("| 17 | `med(None)` 缺护栏、`reg[\"agg\"]` 键名写错 | 代码 | **先看返回结构/键名再写消费代码** |")
w()
w("---")
w()
w("## 5. 未完成 / 待你裁定 / 阻塞点")
w()
w("| 项 | 状态 | 需要谁 |")
w("|---|---|---|")
w("| **论文 v17 编译** | **未编译**（本机无 TeX）；正文 5,604 词、含 AI 与参考 6,192 词 | 你（Overleaf/本地）；削减候选块见 INDEX §228 |")
w("| **门禁 `#3`** | 唯一 `not_satisfied`；修法在**表示层**（须新预注册） | 你决定是否启动 |")
w("| 其余 5 项 `partial` | `#1` 契约签字与标签映射；`#2` 未见频率；`#5` S4 载体与独立确认；`#7` 端口契约与功率平衡；`#9` POD 在线耗时与 break-even | 你裁定优先级 |")
w("| 状态再提升 | 需 `solver_certified`（S1/S2 + S5 + 独立留出）⇒ 当前 S1/S2 在多频上未过 | 不改变现状 |")
w("| 包许可证 / 公开时机 | 包内已写明「故意未定」；双盲期内不得公开 | **你**（我不擅自决定） |")
w("| `N4_REPORT.md` 数字不一致 | 限制段 k=120 写 18.52 / 27.61 %，而 `N4_ROM_DIAG.json` k 扫描平台值是 27.64 / 31.79 %（与论文一致） | 你决定是否出 append-only 更正 |")
w("| 补充材料提交规则 | 需在投稿系统确认 | 你 |")
w()
w("---")
w()
w("## 6. 不主张")
w()
w("- 不主张放行、不主张状态再升级：`release_allowed = false`，`solver_spec = physics_consistent`（**非** `solver_certified`/`approved_solver`）；")
w("- 不主张「S3 通过 = 功率平衡/能量守恒已证明」；不主张「S0 通过 = 可免 COMSOL 出解或网格无关」；")
w("- 不主张 `#3` 已满足；不主张「grouped 拆分已无泄漏」（**恰恰相反**，已在正文与 §S11 明示）；")
w("- 不主张包已经第三方验证；不主张跨机器逐位一致；不主张任何工程绝对值；")
w("- 不主张 AI1.1/EDA6.4 会被接收。")
w()
w("---")
w()
w(f"*本文由 `work/tools/make_work_report_20261013.py` 生成；全部哈希在生成时从磁盘读取后计算。*")

txt = "\n".join(L) + "\n"
if "\r\n" in txt:
    raise SystemExit("[FAIL] 生成文本含 CRLF")
OUT.write_bytes(txt.encode("utf-8"))
back = OUT.read_bytes()
print("写出 %s：%d B，sha256 %s" % (OUT.name, len(back), hashlib.sha256(back).hexdigest()))
print("引用交付物 %d 件；其中 MISSING %d 件" % (len(H), sum(1 for v in H.values() if v[0] < 0)))
