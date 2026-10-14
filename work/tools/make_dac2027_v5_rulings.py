# -*- coding: utf-8 -*-
"""生成 `docs/PMUT_DAC2027_初稿_v5_20261009.md`：把 2026-10-09「八项裁决」逐条外科式落进论文。

纪律（fail-closed）：
* 基线 v4 的 sha256 必须逐位相符，否则拒绝；
* 每条替换的 `old` 片段在 v4 中必须**恰好出现 1 次**，否则拒绝；
* 按**二进制**读写，保持 CRLF，不做任何其它改动；
* 逐字节最强守卫：把每条新片段换回旧片段应能**逐字节还原 v4**。

不改任何既有版本、不改代码、不改数据。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

from memsharness.guards_inplace import backup_before_edit

REPO = pathlib.Path(__file__).resolve().parents[2]
V4 = REPO / "docs/PMUT_DAC2027_初稿_v4_20261009.md"
V5 = REPO / "docs/PMUT_DAC2027_初稿_v5_20261009.md"
V4_SHA = "4472aa5b7e86528d2bc05d6f68c284cc45bc96b9eb1ec29b674c4e48374dce55"

# ---------------------------------------------------------------- 替换表
R: list[tuple[str, str]] = []          # (label, old, new)


def add(label: str, old: str, new: str) -> None:
    R.append((label, old, new))


# A — 版本头：附加 v5 裁决行（既有行一字未改）
add(
    "A-v5头",
    "> **状态纪律（本轮新增）**：`work/runs/solver/pmut-f1/solver_spec.json` 仍 `state=draft`；多通道代理仍 `status=draft`。**本轮未提升任何模型或 S 级状态，放行权在人。**",
    "> **状态纪律（本轮新增）**：`work/runs/solver/pmut-f1/solver_spec.json` 仍 `state=draft`；多通道代理仍 `status=draft`。**本轮未提升任何模型或 S 级状态，放行权在人。**\n"
    "> **v5 修订（本轮；依据用户 2026-10-09 八项裁决）**：① S4 **收敛为单一结论 —— 口径 O（全体有序对）2.4223% > 2% ⇒ `failed`**，口径 F（最细一对）1.3553% **降为敏感性/次要口径**，二者**均为事后声明口径**；② 分类碰撞缺陷**已按裁决修复**（另一执行者完成；本稿交付前实测归类已纠正为 `layer_does_not_exist`），而隔离清单在 `predict()` 路径**仍未**被读取（\\(I_{iso}\\) = 披露项、未生效）；③ U3 **已由人裁定确认覆盖并点名** `b_GE_task3_2new_currentdrive_fmax45_v1.mph`；④ 防泄漏分组规则 = **按 ulp 归一化组合键整组切分**；⑤ Q **按批分列、不报单一中位数**；⑥ **405 组维持不展开**；⑦ v2 批**纳入、按批分组、带删失/截断标志**；⑧ 跨管线 −3 dB **只登记差异、暂不裁定谁对**。逐条对照见 `docs/PAPER_REVISION_LOG_20261009.md` §L（代码状态变化见 §L.5 / `INDEX §105`）。**八项裁决均未提升任何状态。**",
)

# B — 英文摘要
add(
    "B-en摘要",
    "and mesh-independence S4 is `inconclusive` under the frozen criterion.",
    "and mesh-independence S4 **fails** under the ruling-adopted criterion O (all ordered pairs, **2.4223% > 2%**), which — like the finer-pair caliber F (1.3553%, reported only as a secondary sensitivity caliber) — is a **post-hoc declared** caliber.",
)

# C — 摘要字数注
add(
    "C-摘要注",
    "「S3 failed / S4 inconclusive」",
    "「S3 failed / S4 口径 O failed」",
)

# D — 中文摘要
add(
    "D-zh摘要",
    "S4 在冻结口径下为 `inconclusive`、在替代阶梯口径下为 `failed`（2.3136% > 2%）",
    "S4 在**已裁决采用**的口径 O（全体有序对）下为 `failed`（**2.4223% > 2%**），最细一对的**口径 F（1.3553%）仅作次要敏感性口径**并列（两条口径**均为事后声明口径**，冻结三档口径仍 `inconclusive`）",
)

# E — §1 贡献 4
add(
    "E-贡献4",
    "、S4 网格无关性在冻结口径下 `inconclusive`、在替代阶梯口径下 `failed`（2.3136% > 2%）",
    "、S4 网格无关性在**已裁决采用**的口径 O 下 `failed`（**2.4223% > 2%**；最细一对的口径 F 1.3553% 仅作**次要敏感性口径**，二者均为**事后声明口径**；冻结三档口径仍 `inconclusive`）",
)

# F — §3.1 N2=9 / v2 地位
add(
    "F-v2地位",
    "**【待裁定】**「是否把 v2 批纳入本文的『当前数据』口径」须人选定（两种口径都不支持「N2=9 泛化已验证」这一说法）。",
    "**已裁决（八项裁决第 7 项）：v2 批纳入本文「当前数据」口径，但必须按批分组、并携带删失/截断标志** —— v2 只与 A 批**并置**、不池化，其 `peak_at_scan_endpoint`（峰频右删失）与 `bw_upper_cutoff_at_endpoint`（带宽截断）组合**不得**当作正常测量值参与排名、比较或统计（删失 92/250 = 36.8%、截断 103/250 = 41.2%）。**纳入 ≠ 「N2=9 泛化已验证」**：C 批根本没有 N2=9 行、A 批只有 1 行，净可用增量 **46**、叠加 Q 门禁后 **11**（分母 **32**），该说法**仍不成立**。",
)

# G — §5.1 v2 与 A 批的关系
add(
    "G-v2并置",
    "因此两者**只能并置、不能合并统计**，v2 的价值主要在 N2=9 与删失/截断口径。",
    "因此两者**只能并置、不能合并统计**。**已裁决（八项裁决第 7 项）：v2 批纳入本文「当前数据」口径，按批分组、携带删失/截断标志**（见下方缺陷 1–3），v2 的价值主要在 N2=9 与删失/截断口径。",
)

# H — §5.1 缺陷 4：跨管线 −3 dB
add(
    "H-跨管线",
    "（「31/100 超 5%」与「30/100 超 100%」是两个不同的数，引用时不得混用。）",
    "（「31/100 超 5%」与「30/100 超 100%」是两个不同的数，引用时不得混用。）**已裁决（八项裁决第 8 项）：跨管线 −3 dB 差异只登记、暂不裁定谁对** —— 本条只登记差异（峰频 **69/100 逐位相等**、**31/100 超 5%**（其中 **30 组超 100%**，最大 3.467×）、带宽中位差 **30%**、Q 中位差 **19%**），依据 `INDEX §92.3 更正二` 与 `scripts/cross_pipeline_label_check.py`（该对账本身是**描述性**的），**不得**据此声称「已验证一致」，也**不得**裁定哪条管线更接近真值（须各自原始频谱与提取定义原文）。",
)

# I — §5.2 防泄漏分组规则
add(
    "I-切分键",
    "建议口径为**按 ulp 归一化组合键或 `dup_of` 族整组切分**；**【待裁定】** 该建议未经用户拍板（须人裁定训练/留出分组规则），本轮**不执行**。",
    "**已裁决（八项裁决第 4 项）：防泄漏分组规则 = 按 ulp 归一化组合键整组切分**（先对组合键做 ulp 归一化，同一组合键的全部记录必须落在同一折，**不得**跨折）。定此规则的原因即上行实测：`batch` 不是有效切分键（跨批重叠 **446 = 162 字面 ＋ 224 表示差 ＋ 60 真 ulp**）；且**不做 ulp 归一化会把新增数虚高**（实测 1 ulp 表示差把 **83** 误报成 **117**，见 `work/runs/paper-evidence-20261009/E8_batch_isolation_numbers.md`）。**本轮只落实口径表述、不执行实际切分**（集合级组合数/种子/内容哈希仍【待补】）。",
)

# J — §6.1 Q 中位数
add(
    "J-Q中位数",
    "**【待裁定】** 若正文必须给出**单一** Q 中位数，用哪个分母（C 批 3.6648 vs 池化 3.6861）须人选定并显式标注分母。",
    "**已裁决（八项裁决第 5 项）：Q 按批分列、不报单一中位数** —— 正文**不给出任何单一 Q 中位数**，只并列 C 批 **3.6648**（n = 1,523）与 A 批 **3.9433**（n = 154）；池化值 3.6861 仅作规模参考、**显式标注「池化、不作结论」**。",
)

# K — §6.5 限定段：分类逻辑与隔离读取
add(
    "K-分类缺陷",
    "以下两点属**已知缺陷、待处置**，本轮**只登记、不修代码**（修改分类逻辑属变更判定语义，须人拍板）：① 分类函数按顺序匹配子串，而 `该层不存在：要求 N_w_te1 < N_w_te2` 这句本身含 `N_w_te2` ⇒ **先命中 `n2_out_of_domain`（标签碰撞）**，本应判 `layer_does_not_exist`；② 隔离组合 `excluded_quarantine` 未被 `predict()` 读取（§4.3 的 \\(I_{iso}\\) 门在实际预测路径上不生效）。**在其修复并重新冻结之前，任何沿用自报标签的拒答统计都必须按本节实测口径重述。**",
    "以下两条缺陷的处置**已裁决（八项裁决第 2 项）：分类逻辑（低风险）先修，隔离读取另议**。① **分类碰撞 —— 已按裁决修复**：原缺陷是分类函数按顺序匹配子串，而 `该层不存在：要求 N_w_te1 < N_w_te2` 这句本身含 `N_w_te2` ⇒ **先命中 `n2_out_of_domain`（标签碰撞）**，本应判 `layer_does_not_exist`。**修复已由另一执行者完成**（把 `layer_does_not_exist` 提到 `n2_out_of_domain` 之前，**只调次序、不动模式与阈值**）；**本稿交付前实测**：`_classify_refusal('该层不存在：要求 N_w_te1 < N_w_te2')` → `layer_does_not_exist`，而真 `N_w_te2` 越域仍判 `n2_out_of_domain`；`src/memsharness/multichannel_surrogate.py` sha256 `7ec83d3d83c58004aaa1a9f6fbf0d70ed9bd3e1b67c89db3c581665a0d063ff4`（mtime `2026-10-09 09:52:18`），并新增回归用例 `tests/test_mc_refusal_classification.py`（**9 passed**，本轮以只读方式实跑）。② **隔离读取（另议；仍未修）**：隔离组合 `excluded_quarantine` 未被 `predict()` 读取 —— 该字段全文**仅出现在 `model_card()`**，`predict()` / `check_domain()` 均无该分支 ⇒ §4.3 的 \\(I_{iso}\\) 门在实际预测路径上**仍不生效**，**该项仍为未生效的披露项**。**① 落地后该网格的聚合账不变、只有标签归属迁移**：修复后实测 `layer_does_not_exist` **102** ＋ `x_outside_layer_range` **51** = 153、`n2_out_of_domain` **0**、接受 **323**、网格 **476**（回归用例 ③ 以冻结 CSV 逐点比对「接受/拒答判定」）。**E3 逐点明细与 `E3_refusal_screen.json` 已按修复后的代码重生成，故本节分桶表以「当前自报标签 = `layer_does_not_exist`」列出；修复前的 `n2_out_of_domain` 标签作为历史事实在同表下方注明（见 `INDEX §101.5 / §102 / §104 / §105`）。**",
)

# L — §4.3 限定段末句
add(
    "L-4.3缺陷处置",
    "修复该缺陷属变更判定语义、须人拍板 —— 本轮**只登记、不修代码**。",
    "**已裁决（八项裁决第 2 项）：分类逻辑（低风险）先修、由另一执行者执行（已完成）；本项（隔离读取）另议 —— 仍未读取** ⇒ \\(I_{iso}\\) **仍为未生效的披露项**，`predict()` 的读取行为**未改**（分类问题的处置见 §6.5 限定段 ①）。",
)

# M — §6.6 405 组
add(
    "M-405",
    "**【待裁定】** 是否改变该门禁结论（即 405 组是否展开）须人裁定；若展开须先过阈值或改口径并留痕。",
    "**已裁决（八项裁决第 6 项）：405 组维持不展开**（维持当前门禁结论），依据为 `expansion_to_405_allowed=false`、`release_allowed=false`，且 7 折留一在**关键区 2% 门禁下 0/7** 通过。若将来要展开，须先过阈值或改口径并留痕；**不得**以趋势结果直接展开。",
)

# N — §6.8（二）标题
add(
    "N-S4标题",
    "**（二）S4 网格无关性 = 两条口径必须同现**",
    "**（二）S4 网格无关性 = `failed`（已裁决采用口径 O；口径 F 为次要口径，两条口径同现）**",
)

# O — §6.8（二）原「待裁定采用哪条口径」整条
add(
    "O-S4收敛",
    "- **【待裁定：采用哪条口径】** S4 的正式判定以**口径 F（最细一对）**还是**口径 O（全体有序对）**为准，**须人裁定并在索引补登记**（`INDEX §92.4 / §98` 目前只登记「冻结 `inconclusive` / 替代 `failed`」，未登记上述服务器产物）。**本文不自行选定一条**：两条口径的数字与相反结论**必须同现**；且二者都是**事后声明**的判据解释变更（数据先于文书、口径 O 已先判 `failed`），只能表述为「在一条事后声明的最细一对口径下通过」，**不得**表述为独立确认或「预注册判据已满足」。",
    "- **【已裁决（八项裁决第 1 项）：采用口径 O（全体有序对）】** S4 的正式判定**收敛为单一结论**：**口径 O（全体有序对的最大值 < 2%）= 2.4223% > 2% ⇒ `failed`**。**口径 F（最细一对 `h2um` ↔ `h1um` < 2%）= 1.3553%（关键区 0.6110%）作为敏感性/次要口径并列给出**，沿用已有批准 id `fb-20261006-s4_criterion_finest_pair`（`validation` 记录 `val-pmut-s4-mesh-finest-pair-20261006`，`level = S4`、`passed = true`）；**本节不再表述为「待裁定」**。\n"
    "- **两条口径均为事后声明口径**（数据先于文书、口径 O 已先判 `failed`）：口径 F 只能表述为「在一条事后声明的最细一对口径下通过」，**不得**表述为独立确认或「预注册判据已满足」；**正式 S4 判定 = 口径 O 的 `failed`**。冻结三档口径仍 `inconclusive`（**`inconclusive` ≠ 通过**）；`work/runs/s34-ladder-server-20261008/` 的同机重跑（口径 O = 2.4161%、口径 F = 1.3578% / 1.3527%）支持同一结论。",
)

# P — §6.8（三）1：U3 点名裁定
add(
    "P-U3",
    "既有用户裁定（`INDEX §51`）另有「结构同源」口径，但其 `target_id` **未点名**该文件，且自陈**不覆盖**输出列定义 / 测点取样面 / 驱动电压 / 网格与 L1 ⇒ 「结构同源」不能自动从 x 族外推到 S3/S4 那一份。**【待裁定：U3】** 一条**点名**该 `.mph` 的裁定（人 + `feedback` 登记）仍缺，须人裁定。",
    "既有用户裁定（`INDEX §51`）另有「结构同源」口径，但其 `target_id` **未点名**该文件，且自陈**不覆盖**输出列定义 / 测点取样面 / 驱动电压 / 网格与 L1。**【已裁决（八项裁决第 3 项）：U3 点名裁定成立】** 用户已裁定**确认覆盖**，并**点名** `b_GE_task3_2new_currentdrive_fmax45_v1.mph` ⇒ 据此，**S3/S4 的结论可以挂到路线甲求解器名下**，但**必须同时写清两点边界**：① 该同源是**人裁定**（不是复算证明）—— 两份 `.mph` 的 sha256 仍逐位不同、体量仍差 2,472 倍；② **变量语义可比性由 U1 实测支撑**（见下条），**不是**由同源裁定推出。",
)

# Q — §6.8（三）2：U1 只证语义可比
add(
    "Q-U1边界",
    "**但这不提供任何模型同源性证据**：U1 只在模型自带 7 频点、`x_scale = 1.0 / N_w_te1 = 8` **一个参数组合**上求值，**x 族 20 MHz 的 `p` 列仍未导出**；**U3 与 U4（x 族模型 feature 表 / `.m` 导出）均未做**。",
    "**同源性本身由人裁定给出（八项裁决第 3 项），U1 提供的是变量语义可比性**：U1 只在模型自带 7 频点、`x_scale = 1.0 / N_w_te1 = 8` **一个参数组合**上求值，**x 族 20 MHz 的 `p` 列仍未导出**；**U4（x 族模型 feature 表 / `.m` 导出）未做**。⇒ 把 S3/S4 挂到路线甲求解器名下的**依据 = 人裁定 ＋ U1 的变量语义实测**，**不得**据此声称模型同源已被复算证明。",
)

# R — §7.4 表格：替代 COMSOL 行
add(
    "R-74替代",
    "| 替代 COMSOL | 代理 `status = draft` 且带 `NOT_a_solver` 声明；S3 `failed`、S4 冻结口径 `inconclusive`、S0 `inconclusive` ⇒ 连第一次状态跃迁都够不着 |",
    "| 替代 COMSOL | 代理 `status = draft` 且带 `NOT_a_solver` 声明；S3 `failed`、S4 **已裁决口径 O 判 `failed`（2.4223% > 2%；口径 F 1.3553% 为次要口径）**、冻结三档口径 `inconclusive`、S0 `inconclusive` ⇒ 连第一次状态跃迁都够不着 |",
)

# S — §7.4 表格：N2=9 行（补 v2 地位）
add(
    "S-74N29",
    "| 声称 N2=9 泛化已经验证 | N2=9 的全部可用数据只能来自 v2（C 批**根本没有** N2=9 行，A 批仅 1 行）；",
    "| 声称 N2=9 泛化已经验证 | **（v2 已按八项裁决第 7 项纳入「当前数据」，但按批分组、带删失/截断标志）** N2=9 的全部可用数据只能来自 v2（C 批**根本没有** N2=9 行，A 批仅 1 行）；",
)

# T — §7.4 表格：批次合并行（切分规则）
add(
    "T-74切分",
    "⇒ 只能并置；跨批同组合 446 对 ⇒ `batch` 不得当防泄漏切分键 |",
    "⇒ 只能并置；跨批同组合 446 对 ⇒ `batch` 不得当防泄漏切分键，**已裁决改用「按 ulp 归一化组合键整组切分」** |",
)

# U — §8 结论
add(
    "U-结论",
    "、S4 冻结口径 `inconclusive` / 替代阶梯 `failed`（2.3136% > 2%；服务器产物另给出口径 F 1.3553% 与口径 O 2.4223% 两条相反结论，**采用哪条须人裁定**）",
    "、S4 在**已裁决采用**的口径 O（全体有序对）下 `failed`（**2.4223% > 2%**；最细一对的**口径 F 1.3553% 仅作次要敏感性口径**并列，二者均为**事后声明口径**；冻结三档口径仍 `inconclusive`）",
)

# V — 内部清单 F
add(
    "V-清单F",
    "- 把 S4 的口径 F 通过写成「离散无关性已验证」（口径 O 仍 `failed`，且为事后声明口径）；",
    "- 把 S4 的口径 F 通过写成「离散无关性已验证」（**已裁决采用口径 O，判 `failed`**；口径 F 仅为次要敏感性口径，且二者均为事后声明口径）；",
)

# W — 内部清单 G
add(
    "W-清单G",
    "- S3 `failed`、S4 冻结口径 `inconclusive` / 替代阶梯 `failed`（服务器产物另给两条相反口径，**待裁定**）；",
    "- S3 `failed`、S4 **已裁决采用口径 O 判 `failed`（2.4223% > 2%）**，口径 F（1.3553%）为**次要敏感性口径**，冻结三档口径 `inconclusive`；",
)

# X — §6.8（二）服务器产物引导句（原文写「索引未登记、正在整理」）
add(
    "X-S4产物",
    "- **另有一条索引未登记、正在整理的服务器产物（工作区实测存在）**：",
    "- **两条服务器产物（工作区实测存在；其口径已由本裁决采用并随索引追加登记）**：",
)

# Y — §6.5 分桶表与「独立桶」句：改为**修复后**的 E3 口径（E3 已由另一执行者按修复后代码重生成）
add(
    "Y1-独立桶",
    "- 原句列出的「结构整数约束不成立」与「命中隔离记录」**不是两类之外的独立桶**：前者正是那 102 条的真实触发（只是被自报标签写错），后者实测 0 次。",
    "- 原句列出的「结构整数约束不成立」与「命中隔离记录」**不是两类之外的独立桶**：前者正是那 102 条的**真实触发**（修复前曾被**标签碰撞**误报为 `n2_out_of_domain`，该碰撞**已按裁决修复**，见下方限定段 ①），后者实测 0 次。",
)

_OLD_TABLE = "\r\n".join([
    "**E3 实测直方图**（来源 `work/runs/paper-evidence-20261009/E3_refusal_histogram.csv`；逐点明细见同目录 `E3_refusal_grid_points.csv`，476 行）：",
    "",
    "| 桶 | 计数 |",
    "|---|---:|",
    "| refused｜`n2_out_of_domain`（**模型自报标签，归类有误，见下方限定**） | 102 |",
    "| refused｜`x_outside_layer_range` | 51 |",
    "| refused｜（**实测触发**）层不存在 `N1 ≥ N2` | 102 |",
    "| refused｜（**实测触发**）`N2 ∉ [5,9]` | 0 |",
    "| accepted｜`in_layer` | 323 |",
    "| accepted｜`n2_extrap` | 0 |",
    "| 合计 | 476 |",
    "",
    "被拒答的网格点**单独计数并给出原因直方图，不混进排名**。",
])
_NEW_TABLE = "\r\n".join([
    "**E3 实测分桶（以逐点明细为准）**（来源 `work/runs/paper-evidence-20261009/E3_refusal_grid_points.csv`，**476 行**，sha256 `0248bd74ee912d9c968b27d5de68ac0fa3b7678d53f26079d785b8170871dec0`；同目录 `E3_refusal_screen.json` 的 `counts.refusal_reasons_as_reported` 与本表逐项一致）：",
    "",
    "| 桶 | 计数 |",
    "|---|---:|",
    "| refused｜`layer_does_not_exist`（**当前自报标签 = 实测触发**：层不存在 `N1 ≥ N2`） | 102 |",
    "| refused｜`x_outside_layer_range` | 51 |",
    "| refused｜`n2_out_of_domain`（`N2 ∉ [5,9]`） | **0** |",
    "| accepted｜`in_layer` | 323 |",
    "| accepted｜`n2_extrap` | 0 |",
    "| 合计（逐点 CSV 逐行核对） | 476 |",
    "",
    "> **修复前的自报标签（历史事实，已登记）**：分类碰撞未修时，同一 476 点网格的自报标签是 `n2_out_of_domain` **102**（**归类有误**）＋ `x_outside_layer_range` 51 —— 见 `INDEX §101.5 / §102 / §104 / §105`。修复后自报标签变为 `layer_does_not_exist` 102，而**拒答/接受判定与三个总数（153 / 323 / 476）一个都没变**。",
    ">",
    "> **⚠️ 证据包的生成时间与稳定性（如实登记；本轮只登记、不改 `work/runs/`）**：`work/runs/paper-evidence-20261009/` 在本稿写作期间被**数据侧就地重生成多次**（观察到**两版不同内容**：`2026-10-09 09:54:53` 与 `09:57:57`；其后 `09:58:57` 的重生成与 `09:57:57` 版**逐字节相同**；均**非 append-only**）。两次重生成中，**本表引用的四个数（`layer_does_not_exist` 102 ／ `x_outside_layer_range` 51 ／ `in_layer` 323 ／ 合计 476）与「拒答 153」全部不变**，逐点 CSV（sha256 `0248bd74ee912d9c968b27d5de68ac0fa3b7678d53f26079d785b8170871dec0`）在两次重生成之间**逐字节相同**。09:54:53 版的 `E3_refusal_histogram.csv` 曾是**半更新状态**（各桶之和 **374 ≠ 合计 476**）；该问题在 **09:57:57 版已由数据侧修正**（报出标签桶 `n2_out_of_domain` **0**；实际触发桶 51 ＋ 102 ＋ 0 = **153**；`in_layer` 323；合计 476）。⇒ **本节以逐点 CSV 与 `E3_refusal_screen.json` 的 `counts.refusal_reasons_as_reported` 为准**；分桶文件 / JSON / md 的**逐次 sha256 与时间戳**登记在 `docs/PAPER_REVISION_LOG_20261009.md` §L.7 与 `docs/INDEX-records-and-rulings.md` §107（**本轮不改 `work/runs/` 任何文件**）。",
    "",
    "被拒答的网格点**单独计数并给出原因直方图，不混进排名**。",
])
add("Y2-直方图表", _OLD_TABLE, _NEW_TABLE)

# Z — §6.5 限定段首句：点明那是「修复前」的自报标签
add(
    "Z-自报标签",
    "自报标签 `x_outside_layer_range` **51** ＋ `n2_out_of_domain` **102** 的总数（153）与实测一致，但**后 102 条的归类是错的**。",
    "**修复前的**自报标签 `x_outside_layer_range` **51** ＋ `n2_out_of_domain` **102** 的总数（153）与实测一致，但**后 102 条的归类是错的**（该碰撞**已按裁决修复**，见 ①）。",
)


def main() -> int:
    raw_v4 = V4.read_bytes()
    got = hashlib.sha256(raw_v4).hexdigest()
    if got != V4_SHA:
        print("[FAIL] v4 基线 sha256 不符：%s != %s" % (got, V4_SHA))
        return 2
    text = raw_v4.decode("utf-8")
    if "\r\n" not in text:
        print("[FAIL] v4 非 CRLF，拒绝改写")
        return 2
    bare = text.count("\n") - text.count("\r\n")
    if bare != 0:
        print("[FAIL] v4 含 %d 个裸 LF，拒绝（本脚本按纯 CRLF 处理）" % bare)
        return 2

    # 唯一性守卫
    for label, old, _new in R:
        n = text.count(old)
        if n != 1:
            print("[FAIL] %s：旧片段出现 %d 次（要求恰好 1 次）" % (label, n))
            return 2
    # 互不重叠守卫（按出现位置排序，避免替换串互相嵌套）
    spans = []
    for label, old, _new in R:
        i = text.index(old)
        spans.append((i, i + len(old), label))
    spans.sort()
    for a, b in zip(spans, spans[1:]):
        if b[0] < a[1]:
            print("[FAIL] 片段重叠：%s 与 %s" % (a[2], b[2]))
            return 2

    new_text = text
    for _label, old, new in R:
        new_text = new_text.replace(old, new, 1)

    # 行尾归一：新增片段里的 `\n` 一律转成 CRLF，保持全文纯 CRLF（与 v4 一致）
    new_text = new_text.replace("\r\n", "\n").replace("\n", "\r\n")
    if new_text.count("\n") != new_text.count("\r\n"):
        print("[FAIL] 归一后仍有裸 LF")
        return 2

    # 逐字节最强守卫：换回旧片段应还原 v4
    back = new_text
    for _label, old, new in R:
        new_crlf = new.replace("\r\n", "\n").replace("\n", "\r\n")
        back = back.replace(new_crlf, old, 1)
    if back != text:
        print("[FAIL] 反向还原失败 —— 除登记改动外还有其它差异")
        return 2

    if V5.is_file():
        # 就地改守卫（`INDEX §131.2`）：重跑时 V5 已存在 ⇒ 先备份改前字节。
        backup_before_edit(V5)
    V5.write_bytes(new_text.encode("utf-8"))
    out = V5.read_bytes()
    print("v4 sha256 = %s（%d B / %d 行）" % (got, len(raw_v4), raw_v4.decode("utf-8").count("\n") + 1))
    print("v5 写入   = %s（%d B / %d 行）" % (hashlib.sha256(out).hexdigest(), len(out),
                                        out.decode("utf-8").count("\n") + 1))
    print("改动条数 = %d" % len(R))
    return 0


if __name__ == "__main__":
    sys.exit(main())
