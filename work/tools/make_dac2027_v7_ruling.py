# -*- coding: utf-8 -*-
"""DAC 2027 论文 v7 生成器（fail-closed）。

本轮 = 把「用户 2026-10-09 最新裁定（S4 判定对象 = 关键区）+ A4 阈值适用对象定案
+ INDEX §126/§127」落进论文，并把 v6 里 S4 的**两条相反判定**收敛为**一条**。

守卫链（任一不满足即非零退出、不写任何文件）：
  1. v6 sha256 逐位校验（任务书给定值）；
  2. v6 行尾为**纯 CRLF**、无裸 LF / 裸 CR；
  3. 每条旧片段在**其所在行内恰好出现 1 次**（同时全稿恰好 1 次）；
  4. 同一行内的多条片段**互不重叠**；
  5. 每条新片段在结果中**恰好出现 1 次**；
  6. 产物行尾归一为**纯 CRLF**；
  7. **反向还原可逐字节还原 v6**（新增行按内容整行删除、替换按 new→old 回退）。

不改 v6 任何一字节：只读 v6，另写 v7。
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
V6 = ROOT / "docs" / "PMUT_DAC2027_初稿_v6_20261009.md"
V7 = ROOT / "docs" / "PMUT_DAC2027_初稿_v7_20261009.md"

V6_SHA256 = "07628a5814df1dc716f4e5628f7022ef7925ea3b72fc8dedad3b87b970f68ed0"
V6_BYTES = 102590
V6_LINES = 700  # 行数口径 = CRLF 条数（文件以 CRLF 结尾）


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --------------------------------------------------------------------------
# 替换表：(原行号, 旧片段, 新片段)
# --------------------------------------------------------------------------
REPL: list[tuple[int, str, str]] = []


def R(lineno: int, old: str, new: str) -> None:
    REPL.append((lineno, old, new))


# --- S4 判定收敛为一条 -----------------------------------------------------

R(11,
  "① S4 **收敛为单一结论 —— 口径 O（全体有序对）2.4223% > 2% ⇒ `failed`**",
  "① S4 当时**按全域**读数收敛为单一结论 —— **口径 O（全体有序对、判在**全域**）2.4223% > 2% ⇒ `failed`**"
  "（⚠️ **该读数的「空间对象」当时未指定；用户 2026-10-09 最新裁定把 `S4_mesh_diff_max = 0.02` 的对象钉在**关键区**，"
  "S4 因此改判 `passed` —— 见下方 v7 修订；本条为历史记录，不得再作判定依据**）")

R(12,
  "> **v6 修订（本轮；2026-10-09 第二批已确定事实，逐条依据 `INDEX §111–§116`）**："
  "① **S4 在「同批同机 6 档 `ftet1` 阶梯」这一新裁定集上，口径 O（30 个有序对 max 相对 L2）＝ 1.3847% < 2% ⇒ `passed`**",
  "> **v6 修订（2026-10-09 第二批已确定事实；其 ① 的 S4 判定已被 v7 取代，逐条依据 `INDEX §111–§116`）**："
  "① **S4 在「同批同机 6 档 `ftet1` 阶梯」（主敏感轴）上，口径 O（30 个有序对 max 相对 L2）＝ 1.3847%**")

R(12,
  "故该 `passed` **只覆盖所测 6 档之间的两两差",
  "故该档集的读数**只覆盖所测 6 档之间的两两差")

R(12,
  "**旧阶梯上已裁决采用的口径 O（2.4223% `failed`）判定未被推翻 —— 两个 2% 值取自不同的档集**",
  "**旧阶梯上判在**全域**的口径 O（2.4223%）现降为**参考口径**、不再作判定依据 —— 各 2% 值取自不同档集 / 不同空间对象**"
  "（S4 的权威判定见下方 v7 修订）")

R(12,
  "（压到 2% 以内约还需 λ/9、λ/10，**未做**）",
  "（压到 2% 以内约还需 λ/9、λ/10；**v7 现状：两档尚未跑完、正在排队**）")

R(20,
  "the physics-consistency gate S3 **fails** (0.0602 > 0.005, `S3_complete=false`) and mesh-independence S4 "
  "**fails** under the ruling-adopted criterion O (all ordered pairs, **2.4223% > 2%**), which — like the "
  "finer-pair caliber F (1.3553%, reported only as a secondary sensitivity caliber) — is a **post-hoc declared** "
  "caliber. On a **new, same-batch / same-machine six-level `ftet1` ladder**, the same caliber O over 30 ordered "
  "pairs is **1.3847% < 2%, i.e. `passed`** (worst pair λ/8 over λ/5; critical region 0.6507%); both axes pass "
  "individually (only-`ftet1` 1.3847%, dual-axis 0.8753%), so the pass does **not** rely on refining a single axis. "
  "This is **not** mesh independence: Richardson extrapolation still leaves an estimated **~2.6%** residual at h→0 "
  "(an extrapolation, not a measurement; λ/9 and λ/10 were **not** run), so the pass covers **only pairwise "
  "differences among the six measured levels**. The previously ruling-adopted caliber O over the older ladder "
  "remains **failed (2.4223%)** — the two 2% numbers come from **different level sets**.",
  "the physics-consistency gate S3 **fails** (0.0602 > 0.005, `S3_complete=false`); mesh-independence S4 is "
  "**`passed`**, the **ruled object** being the **critical region** (`R ≤ R_max/3`, 51/1369 points) under criterion "
  "O (all ordered pairs). The two ladders are reported **separately and never merged into one sentence**: on the "
  "**main sensitivity axis — the same-batch / same-machine six-level `ftet1` ladder (`INDEX §111`)** — the critical "
  "region is **0.6507% < 2%** (full domain 1.3847%, **reference only**; worst pair λ/8 over λ/5; both axes pass "
  "individually); the numbers **quoted in the ruling belong to the older ladder `s34-ladder-server-20261008`** "
  "(`h3um` over `h1um`, three same-machine levels), where the **critical region is 1.5191% < 2%** while the full "
  "domain **2.4161%** — together with the cross-machine 2.4223% and the finer-pair caliber F 1.3553% — is a "
  "**reference caliber only, no longer the basis of the verdict**; all of these are **post-hoc declared** calibers. "
  "Three limits travel with the verdict: (i) it covers **only pairwise differences among the measured levels** and "
  "must **not** be read as `mesh independence`; (ii) Richardson extrapolation still leaves an estimated **~2.6%** "
  "residual at h→0 (an **extrapolation, not a measurement**); (iii) the additional levels λ/9 and λ/10 **have not "
  "finished (queued)**, so the verdict covers only the existing levels and may be updated. **S4 turning `passed` "
  "does not authorise release**: the first state transition needs **S0 and S3**, which remain `inconclusive` / "
  "`failed`.")

R(22,
  "**必须保留**「按批分列」「2/8 通道未增值（含正式目标）」「S3 failed / S4 口径 O failed」"
  "「状态 = draft、无 L1、无实验」四项，**并在 v6 追加第五项「新 6 档 `ftet1` 阶梯口径 O 1.3847% `passed`，"
  "但只覆盖 6 档两两差、不等于网格无关」**。",
  "**必须保留**「按批分列」「2/8 通道未增值（含正式目标）」「S3 failed / **S4 口径 O ＋ 关键区 ⇒ `passed`**」"
  "「状态 = draft、无 L1、无实验」四项，**并在 v6 追加第五项、v7 收敛为**一条**判定**："
  "「S4 = `passed`，判定对象 = **关键区**（51/1369）；**两套阶梯的数字必须分开写、不得混用成一句** —— "
  "**`ftet1` 阶梯（§111）关键区 0.6507% / 全域 1.3847%；用户裁定书引用的旧阶梯 "
  "`s34-ladder-server-20261008`（`h3um` over `h1um`）关键区 1.5191% / 全域 2.4161%（参考口径）**；"
  "该 `passed` **只覆盖所测档两两差、不等于网格无关**（Richardson 外推仍 ~2.6%；λ/9、λ/10 未跑完）」。")

R(28,
  "物理一致性与网格无关性给出**明确的负结果**：S3 判 `failed`（守恒残差 0.0602114 > 0.005、`S3_complete=false`），"
  "S4 在**已裁决采用**的口径 O（全体有序对）下为 `failed`（**2.4223% > 2%**），"
  "最细一对的**口径 F（1.3553%）仅作次要敏感性口径**并列（两条口径**均为事后声明口径**，"
  "冻结三档口径仍 `inconclusive`）。**第二批已确定事实（`INDEX §111–§116`）**："
  "在**同批同机 6 档 `ftet1` 阶梯**这一新裁定集上，口径 O（30 个有序对 max）＝ **1.3847% < 2% ⇒ `passed`**"
  "（关键区 0.6507%；只动 `ftet1` 1.3847%、双轴 0.8753%，**两条轴单独都过**），"
  "但 Richardson 外推下最细档距 `h→0` 仍有 **~2.6% 估计残差（外推、非实测）** ⇒ "
  "**该 `passed` 只覆盖所测 6 档之间的两两差，不等于网格无关**；"
  "**旧阶梯上已裁决采用的口径 O（2.4223% `failed`）未被推翻**，两个 2% 值取自**不同档集**。",
  "物理一致性给出明确的负结果：S3 判 `failed`（守恒残差 0.0602114 > 0.005、`S3_complete=false`）。"
  "**S4 网格无关性按用户 2026-10-09 最新裁定 ＝ `passed`；判定对象 = 关键区**"
  "（`R = ‖(x,y,z)‖ ≤ R_max/3`，**51/1369** 点），口径 O = 全体有序对（阈值键 `S4_mesh_diff_max = 0.02` 未改）。"
  "**两套阶梯的数字必须分开写、不得混用成一句**："
  "**(a) 主敏感轴 `ftet1` 阶梯**（同批同机 6 档、30 个有序对；`INDEX §111`）⇒ "
  "**关键区 0.6507% < 2%**（全域 **1.3847%** 作**参考**；只动 `ftet1` 1.3847%、双轴 0.8753%，两条轴单独都过）；"
  "**(b) 用户裁定书引用的数字属旧阶梯** `work/runs/s34-ladder-server-20261008`"
  "（三档同机、`h3um` over `h1um`）⇒ **关键区 1.5191% < 2%**、**全域 2.4161% 作参考口径**"
  "（跨机登记的旧读数 2.4223%、最细一对的口径 F 1.3553% 同为参考；两条口径的性质仍为**事后声明**；"
  "冻结三档口径仍 `inconclusive`）。**三条限制随结论同现**：① 只报「**所测档之间的两两差**」、"
  "**不得声称「网格无关」**；② **Richardson 外推显示最细档距 `h→0` 仍有 ~2.6% 估计残差（外推、非实测）**；"
  "③ **新增 λ/9 与 λ/10 两档尚未跑完（正在排队）** ⇒ 本结论**只覆盖既有档**，新档结果落地后**可能再更新**。"
  "**S4 转 `passed` 不等于放行**（§6.4 第一跳要 S0 与 S3，二者仍 `inconclusive` / `failed`）。")

R(47,
  "、S4 网格无关性在**已裁决采用**的口径 O 下 `failed`（**2.4223% > 2%**；"
  "最细一对的口径 F 1.3553% 仅作**次要敏感性口径**，二者均为**事后声明口径**；"
  "冻结三档口径仍 `inconclusive`、场级三对象门禁为 0/7（关键区 2%）、0/7（S2 3%）与 2/7（全域 5%），"
  "**405 组不得展开**，模型状态保持 `draft`。**第二批已确定事实（`INDEX §111–§116`）**："
  "S4 在**同批同机 6 档 `ftet1` 阶梯**这一**独立档集**上口径 O ＝ **1.3847% < 2% ⇒ `passed`**"
  "（关键区 0.6507%；两条轴单独都过），但 **Richardson 外推仍有 ~2.6% 估计残差（外推、非实测）** ⇒ "
  "该 `passed` **只覆盖 6 档之间的两两差**、**不是**网格无关性；",
  "、**S4 网格无关性按用户 2026-10-09 最新裁定 ＝ `passed`，判定对象 = 关键区"
  "（`R = ‖(x,y,z)‖ ≤ R_max/3`，**51/1369** 点；口径 O = 全体有序对；阈值键 `S4_mesh_diff_max = 0.02` 未改）**："
  "**(a) `ftet1` 阶梯（§111）关键区 0.6507% < 2%**（全域 1.3847% 作参考）；"
  "**(b) 裁定书引用的数字属旧阶梯** `s34-ladder-server-20261008`（`h3um` over `h1um`）"
  "**关键区 1.5191% < 2%**、**全域 2.4161% 降为参考口径**（跨机 2.4223%、口径 F 1.3553% 同为参考；"
  "口径性质仍为**事后声明**；冻结三档口径仍 `inconclusive`）；**两套阶梯不得混用成一句**；"
  "**三条限制随结论同现**：只覆盖**所测档两两差**（**不得**称网格无关）、"
  "**Richardson 外推仍有 ~2.6% 估计残差（外推、非实测）**、**λ/9 与 λ/10 尚未跑完（正在排队）**；"
  "场级三对象门禁为 0/7（关键区 2%）、0/7（S2 3%）与 2/7（全域 5%），**405 组不得展开**，"
  "模型状态保持 `draft`（**S4 转 `passed` 不等于放行**：第一跳要 S0 与 S3，二者仍 `inconclusive` / `failed`）；")

# --- 阶段 3（te2_9）状态：正在跑（分块、尚未全完） -------------------------

R(243,
  "**te2_9 扩频重导（评审条目 B6：5–50 MHz / 648 组合）的状态 ＝ `【待产物】`"
  "（本轮实测未落地；不以估计值或旧值顶替）**：run 目录 `work/runs/te29-freq5-50-server-20261009/` 存在但"
  "**无** `Table_9.txt`，其 `TE29_REEXPORT_REPORT.json` 的 `new_export = null`；"
  "smoke 运行在 `solnum` 属性上报错（原文 `Invalid property value. - Property: solnum "
  "(Parameter values (freq (Hz)))`，留档 `srv_run_smoke.log`）。"
  "解析/盘点/回归/净值四件套在产物缺失时分别 `rc=3`",
  "**te2_9 扩频重导（评审条目 B6：5–50 MHz / 648 组合）的状态 ＝ `【待产物】`"
  "（导出**正在跑、分块、尚未全完**；不以估计值或旧值顶替）**：run 目录 "
  "`work/runs/te29-freq5-50-server-20261009/` 存在但**成品 `Table_9.txt` 未落地**"
  "（早期 `TE29_REEXPORT_REPORT.json` 的 `new_export` 为 `null`）；早期 smoke 运行曾在 `solnum` "
  "属性上报错（原文 `Invalid property value. - Property: solnum (Parameter values (freq (Hz)))`，"
  "留档 `srv_run_smoke.log`），该缺陷已由**分块可续跑导出**取代。"
  "**v7 现场只读实测（`_phase4`）**：分块口径 = 按 `N_w_te1` 切 **8 块**"
  "（外层解 `1:8:648`；每块 81 外层解 × 91 频点 = **7,371 行/表**；**串行**、每块独立 `mphserver`）；"
  "驱动 PID **55285 存活**，截至**远端钟 `2026-10-09T15:47:49`**：**`N_DONE = 2`**"
  "（`chunk_01.done` / `chunk_02.done`，各块 `rc=0`、`mrkvl1=81`、四张数值表各 7,371 行；"
  "`Bandwidth` 行数实测 **204 / 226** ≠ `2×81`，已如实登记）、**`CUR_CHUNK = chunk_03`** 进行中 ⇒ "
  "**新导出侧统计一律未落地**。解析/盘点/回归/净值四件套在**成品缺失**时分别 `rc=3`")

R(243,
  "⇒ **新导出侧的一切数字（组合 / 频点 / 峰值删失 / 带宽截断 / 可用 / Q 可判定 / Q 达标）一律标 `【待产物】`。**",
  "⇒ **新导出侧的一切统计数字（峰值删失 / 带宽截断 / 可用 / 「24 格」"
  "（`x ∈ {0.10, 0.20, 0.30}`）救回 / 净可用增量 / Q 可判定 / Q 达标分母）一律标 `【待产物】`**；"
  "其**规模**（组合 **648** × 频点 **91** = **58,968** 组合×频点）已由探针实测（648 外层解 × 91 内层频点），"
  "与**可比口径 4,392 点**（72 组合 × 61 频点 @ 1e-3 dB 回归靶）一样，"
  "**不得**用估计值或旧值顶替。")

# --- A4：三对象三阈值 + 点名退役「全域 2%」 --------------------------------

R(412,
  "**三对象门禁（同一 7 快照管线，逐折留一；v2 补齐，v1 稿整块缺失）**：",
  "**三对象门禁（同一 7 快照管线，逐折留一；v2 补齐，v1 稿整块缺失）—— A4 定案：三个对象、三个阈值（不新造阈值）**：")

R(416,
  "| 全域相对 L2 | 5% | `norm_shape_pchip` | 0.808890 | **2/7** |",
  "| 全域相对 L2（**1369** 点；键 `S1_global_rel_L2_max`） | **5%** | `norm_shape_pchip` | 0.808890 | **2/7** |")

R(417,
  "| **关键区相对 L2（51/1369 点）** | 2% | `norm_shape_pchip` | **0.858054** | **0/7** |",
  "| **关键区相对 L2（**51/1369** 点；键 `S1_key_region_rel_L2_max`）** | **2%** | `norm_shape_pchip` | "
  "**0.858054** | **0/7** |")

R(418,
  "| **S2 域内 `max\\|p\\|`** | 3% | `raw_linear` | **0.761833** | **0/7** |",
  "| **S2 域内 `max\\|p\\|`**（**工程量**对象；键 `S2_engineering_rel_err_max`） | **3%** | "
  "`raw_linear`（权威件 `best_model`） | **0.761833** | **0/7** |")

R(420,
  "⇒ **三个对象一致不通过**，`release_allowed = false`，且 **405 组不得展开**（2026-10-06 轮门禁结论）。"
  "⚠️ **更正一处对象错配**：最初那份「全域 2% ⇒ 0/7」是把**关键区的阈值套在全域指标上**；"
  "补算两个对象后，全域在 5% 下是 **2/7**（2% 下 0/7，最差折是阈值的 40.4 倍），"
  "关键区才是 **0/7**（且比全域更严）。",
  "⇒ **三个对象一致不通过**，`release_allowed = false`，且 **405 组不得展开**（2026-10-06 轮门禁结论）。"
  "⚠️ **A4 定案（`INDEX §126.6`；成文 `work/runs/field-expansion-20261009/A4_THRESHOLD_OBJECTS_RULING.md`）："
  "三个对象、三个阈值，不新造阈值** —— **2% → 关键区**（`R = ‖(x,y,z)‖ ≤ R_max/3`，**51/1369** 点）、"
  "**5% → 全域**（**1369** 点）、**S2 3% → 工程量**；"
  "**S1 = 前两者同时成立**（`WORKING_PLAN.md` §6.1.1 原文「关键区域 < 2%，全域 < 5%」），"
  "二者**不可互相替代、也不成加权**。⚠️ **点名退役「全域 2%」这一 spec 中不存在的判据**："
  "`work/runs/te2_8_pod_fields_20261005/pod_pipeline_x020_v2/gate_verdict_field_rel_L2.json` 的 "
  "`threshold_source` **原文**写「用户 2026-10-06 指示「先用 2%」；**与 WORKING_PLAN §6.1.1 关键区 <2% 同源**」，"
  "却把该阈值判在**全域**对象上 ⇒ **对象错配**；其姊妹件 `…_thr5pct.json`（阈值 0.05）与之"
  "**逐折数字完全相同**（`best_fold_value = 0.03733774968488022`、"
  "`worst_fold_value = 0.8088898085014998`，**只有阈值不同**）⇒ 实为**同一对象上的阈值敏感性实验**，"
  "**不是**规格的「关键区 / 全域」双对象规则。**两份文件字节不变（append-only）**，退役在**引用层**生效。"
  "⚠️ **改述后的正确读数（数字不变、只换对象）**：最初那份「全域 2% ⇒ 0/7」是把**关键区的阈值套在全域指标上**；"
  "正确读法是 **全域 5% ⇒ 2/7（`max 0.808890`）**、**关键区 2% ⇒ 0/7（`max 0.858054`）**、"
  "**S2 3% ⇒ 0/7（`max 0.761833`，`raw_linear`）** ⇒ **S1 仍 `failed`**（关键区 0/7）、"
  "`release_allowed = false`、**405 组不得展开** —— **原样有效**。"
  "⚠️ **报数纪律（`INDEX §127.6`）**：报折通过数**必须同时给模型名**、并先检查该对象 `max` 是否并列；"
  "**并列时以权威件 `best_model` 为准，并把并列模型一并报出，不得择优取数**"
  "（本表三行中只有 S2 行存在并列：`raw_linear` **0/7** 与 `raw_pchip` **3/7** 的 `max` 逐位相同；"
  "取后者会把 `0/7` 写成 `3/7`）。")

R(422,
  "**405 组不得展开**：在 2% 与 5% 两个阈值下 `expansion_to_405_allowed` 均为 `false`，"
  "`release_allowed` 均为 `false`。",
  "**405 组不得展开**：在 2% 与 5% 两个阈值下 `expansion_to_405_allowed` 均为 `false`，"
  "`release_allowed` 均为 `false`（按 A4：**2% 的对象是关键区、5% 的对象是全域**；"
  "历史上判在**全域**上的「2%」为**已退役**的对象错配读数）。")

# --- §6.8（二）/（二之二）：S4 -------------------------------------------

R(477,
  "**（二）S4 网格无关性 —— 旧（跨机混合）阶梯上 = `failed`（已裁决采用口径 O；口径 F 为次要口径，两条口径同现）；"
  "新 `ftet1` 阶梯见「（二之二）」**",
  "**（二）S4 网格无关性 —— 权威判定 = 口径 O（全体有序对）＋ 空间对象 = 关键区（51/1369 点）⇒ `passed`"
  "（用户 2026-10-09 最新裁定；**全域读数一律降为参考口径**；裁定集 = 旧阶梯 "
  "`s34-ladder-server-20261008`；`ftet1` 阶梯见「（二之二）」、同为参考）**")

R(480,
  "六对差 ≤ 0.05 pp、**同向且同量级超 2% 线** ⇒ `failed` 成立。",
  "六对差 ≤ 0.05 pp、**同向且同量级超 2% 线** ⇒ 该**全域**读数下 `failed` 成立（**参考口径**）。")

R(481,
  "- **两条服务器产物（工作区实测存在；其口径已由本裁决采用并随索引追加登记）**：",
  "- **两条服务器产物（工作区实测存在；旧阶梯即 v7 权威判定的裁定集，其口径与登记随索引追加）**：")

R(480,
  "- **替代阶梯口径（3e-6 / 2e-6 / 1.4e-6）＝ `failed`**：最差有序对全域 `rel_L2` = **0.0231361 > 0.02**"
  "（关键区 0.0143376）。",
  "- **替代阶梯口径（3e-6 / 2e-6 / 1.4e-6；Windows）：最差有序对**全域** `rel_L2` = **0.0231361**"
  "（关键区 **0.0143376**）。该读数**按全域**曾判 `failed`；**v7 起为参考口径**"
  "（同一批的**关键区**分量 1.4338% 一并列出，**仅为参考、不另立判定**）。")

R(482,
  "**口径 O（全体有序对的最大值 < 2%）= 2.4223% ⇒ `failed`**。",
  "**口径 O（全体有序对的最大值 < 2%）在**全域**上 = 2.4223%（跨机登记值）⇒ 按全域判 `failed`；"
  "v7 起该读数降为参考口径**。")

R(483,
  "- `work/runs/s34-ladder-server-20261008/`：三档**同机**重跑，口径 O = **2.4161%**（`h3um` over `h1um`）、"
  "口径 F = 1.3578% / 1.3527% ⇒ 与跨机阶梯结论**完全一致**"
  "（已登记 `val-pmut-s4-mesh-finest-pair-samemachine-20261008`）；"
  "跨机混用的实测影响为最大绝对差 **0.000145（0.0145 pp）** ⇒ 原判定对跨机混用不敏感。",
  "- `work/runs/s34-ladder-server-20261008/`：三档**同机**重跑，口径 O **全域** = **2.4161%**"
  "（`h3um` over `h1um`）／**关键区 = 1.5191%**（同一有序对；`S4_SAME_MACHINE_REPORT.json` 的 "
  "`pairs.1.key = 0.015190894692836621`）、口径 F = 1.3578% / 1.3527% ⇒ 与跨机阶梯结论**完全一致**"
  "（已登记 `val-pmut-s4-mesh-finest-pair-samemachine-20261008`）；"
  "跨机混用的实测影响为最大绝对差 **0.000145（0.0145 pp）** ⇒ 原判定对跨机混用不敏感。"
  "**v7：用户裁定书引用的 `1.5191% / 2.4161%` 即取自**本阶梯**（不是 §（二之二）的 `ftet1` 阶梯值）；"
  "据此 S4 = `passed`（对象 = 关键区），**全域 2.4161% 降为参考口径**。**")

R(484,
  "- **【已裁决（八项裁决第 1 项）：采用口径 O（全体有序对）】** S4 的正式判定**收敛为单一结论**："
  "**口径 O（全体有序对的最大值 < 2%）= 2.4223% > 2% ⇒ `failed`**。"
  "**口径 F（最细一对 `h2um` ↔ `h1um` < 2%）= 1.3553%（关键区 0.6110%）作为敏感性/次要口径并列给出**，"
  "沿用已有批准 id `fb-20261006-s4_criterion_finest_pair`（`validation` 记录 "
  "`val-pmut-s4-mesh-finest-pair-20261006`，`level = S4`、`passed = true`）；**本节不再表述为「待裁定」**。",
  "- **【v7 权威裁定（用户 2026-10-09 逐字：「关键区 1.5191% ⇒ passed」；只读依据 "
  "`work/runs/field-expansion-20261009/A4_THRESHOLD_OBJECTS_RULING.md` §4 ＋ `INDEX §126.6`）】** "
  "S4 的**唯一判定** = **口径 O（全体有序对）＋ 空间对象 = 关键区**"
  "（`R = ‖(x,y,z)‖ ≤ R_max/3`，**51/1369** 点；阈值键 `S4_mesh_diff_max = 0.02` 未改）。"
  "**两套阶梯的数字分开写、不得混用成一句**：**(a) 旧阶梯** `work/runs/s34-ladder-server-20261008`"
  "（三档同机，`h3um` over `h1um`）——**裁定书引用的就是它**：**关键区 1.5191% < 2% ⇒ `passed`**，"
  "**全域 2.4161% 作参考口径**；**(b) 主敏感轴 `ftet1` 阶梯**（`INDEX §111`，见「（二之二）」）："
  "**关键区 0.6507% < 2%**、全域 1.3847%（**参考**）。**两套阶梯同向、但数值不可互换。**")

R(485,
  "（数据先于文书、口径 O 已先判 `failed`）",
  "（数据先于文书；口径 O 最初按**全域**先判 `failed`，v7 把**对象**钉在关键区后改判 `passed` —— "
  "**口径本身仍是事后声明**，这一点不因改判而改变）")

R(485,
  "**正式 S4 判定 = 口径 O 的 `failed`**。冻结三档口径仍 `inconclusive`（**`inconclusive` ≠ 通过**）；"
  "`work/runs/s34-ladder-server-20261008/` 的同机重跑（口径 O = 2.4161%、口径 F = 1.3578% / 1.3527%）"
  "支持同一结论。",
  "**正式 S4 判定 = 口径 O ＋ 关键区 的 `passed`（v7）**。冻结三档口径仍 `inconclusive`"
  "（**`inconclusive` ≠ 通过**）；`work/runs/s34-ladder-server-20261008/` 的同机重跑"
  "（口径 O 全域 = 2.4161%、**关键区 = 1.5191%**、口径 F = 1.3578% / 1.3527%）**是该判定的裁定集**。")

R(487,
  "**（二之二）S4 主敏感轴（声学体网格 `ftet1`）阶梯实测（2026-10-09，服务器 `node01`；`INDEX §111`）**",
  "**（二之二）S4 主敏感轴（声学体网格 `ftet1`）阶梯实测（2026-10-09，服务器 `node01`；`INDEX §111`）"
  "—— 本档集**不替代** §（二）的裁定集；其**关键区 0.6507%** 与**全域 1.3847%**（参考）一并在下；"
  "⚠️ **裁定书引用的 `1.5191% / 2.4161%` 属旧阶梯 `s34-ladder-server-20261008`，不是本阶梯值**；"
  "**两套阶梯的数字不得混用成一句**。")

R(493,
  "| **口径 O（同批同机 6 档、30 个有序对 max 相对 L2）** | **1.3847%** | 2% | ✅ **`passed`** |",
  "| **口径 O（同批同机 6 档、30 个有序对 max 相对 L2）＝ 全域** | **1.3847%** | 2% | "
  "参考（**不是** S4 判定的取值对象） |")

R(495,
  "| 关键区（`R/R_max ≤ 1/3`）max | 0.6507% | 2% | ✅ passed |",
  "| **关键区（`R/R_max ≤ 1/3`）max —— 判定对象** | **0.6507%** | 2% | ✅ **`passed`** |")

R(500,
  "要把后者也压到 2% 以内，按该趋势大约还需 **λ/9 与 λ/10 两档**（**本轮未做**）。",
  "要把后者也压到 2% 以内，按该趋势大约还需 **λ/9 与 λ/10 两档**"
  "（**v7 现状：驱动/分析脚本已备好并部署（`work/runs/field-expansion-20261009/p3/`），"
  "但两档结果**尚未跑完（正在排队）**、本地无任何产物**）⇒ "
  "**本结论只覆盖既有档，新档结果落地后可能再更新**。")

R(502,
  "- **与（二）的关系**：**旧阶梯上的口径 O（2.4223% / 同机 2.4161%，`failed`）判定未被推翻** —— "
  "两个口径 O 的数值取自**不同的档集**（旧阶梯含 `h1um` 与跨机混用；本轮 6 档同批同机且以 `ftet1` 为主轴），"
  "**不可互相覆盖**。",
  "- **与（二）的关系（v7 重写）**：**S4 只有一条权威判定** —— 口径 O ＋ **关键区**，"
  "裁定集 = 旧阶梯 `s34-ladder-server-20261008`（三档同机）⇒ **关键区 1.5191% `passed`**（见 §（二））；"
  "**本条 6 档 `ftet1` 阶梯为参考档集**：**关键区 0.6507%**、全域 1.3847%（参考）。"
  "两套阶梯**不是同一批档**（旧阶梯含 `h1um` 与跨机混用；本轮 6 档同批同机且以 `ftet1` 为主轴）"
  "⇒ **不可互相替代、也不构成第二条判定**。（v6 曾把两条并列写成「两套说法」；v7 已收敛为单一判定。）")

R(514,
  "`21315173fd2732c7384c4a3d437bb7f7c297d5c3047b5ff01094ca3553b6bd3f`（本轮只读复核，逐位一致）。"
  "按放行状态机，需 **S0/S3 通过**才到 `physics_consistent`，而本轮 S0 为 `inconclusive`、S3 为 `failed` ⇒ "
  "**连第一次状态跃迁都还够不着**；`approved_solver` 另需人工签字。",
  "`21315173fd2732c7384c4a3d437bb7f7c297d5c3047b5ff01094ca3553b6bd3f`（v7 只读复核，逐位一致）。"
  "按放行状态机，需 **S0/S3 通过**才到 `physics_consistent`，而本轮 S0 为 `inconclusive`、S3 为 `failed` ⇒ "
  "**连第一次状态跃迁都还够不着**；`approved_solver` 另需人工签字。"
  "**v7 强调：S4 由 `failed` 改判为 `passed` 不改变本节任何一条 —— 第一跳要的是 S0 与 S3"
  "（二者仍 inconclusive / failed）⇒ 仍不得放行、仍不得提升任何状态。**")

# --- §7.4 对照表 / §8 / 内部清单 -----------------------------------------

R(539,
  "S3 `failed`、S4 **已裁决口径 O 判 `failed`（2.4223% > 2%；口径 F 1.3553% 为次要口径）**、"
  "冻结三档口径 `inconclusive`、S0 `inconclusive` ⇒ 连第一次状态跃迁都够不着；"
  "**v6 新增**：S3 在另一设计点上守恒残差 **0.1112**、且**三项仍为 `None`**（`S3_complete = False`）；"
  "S4 在新 6 档 `ftet1` 阶梯上口径 O **1.3847% `passed`**，但**只覆盖 6 档两两差**"
  "（Richardson 外推仍 **~2.6%**）⇒ **不得读成网格无关**",
  "S3 `failed`、**S4 权威判定 = 口径 O ＋ 关键区 ⇒ `passed`**（`ftet1` 阶梯 **0.6507%**；"
  "裁定书引用的旧阶梯 `s34-ladder-server-20261008` **1.5191%**；全域 2.4161% / 跨机 2.4223% / "
  "口径 F 1.3553% 一律降为**参考口径**）、冻结三档口径 `inconclusive`、S0 `inconclusive` ⇒ "
  "**S4 转 `passed` 不等于放行**：§6.4 第一跳要 **S0 与 S3**，二者仍 inconclusive / failed ⇒ "
  "**连第一次状态跃迁都够不着、仍不得放行**；**v6 新增**：S3 在另一设计点上守恒残差 **0.1112**、"
  "且**三项仍为 `None`**（`S3_complete = False`）；S4 的 `passed` **只覆盖所测档两两差**"
  "（Richardson 外推仍 **~2.6%**；λ/9、λ/10 未跑完）⇒ **不得读成网格无关**")

R(542,
  "| 从 7 个快照推断完整场级 ROM 已建立 | 三对象门禁：全域 5% ⇒ 2/7、关键区 2% ⇒ 0/7、S2 3% ⇒ 0/7"
  "（一致不通过）；`release_allowed = false`；**405 组不得展开**；且该管线落在声明范围之外 |",
  "| 从 7 个快照推断完整场级 ROM 已建立 | 三对象门禁（A4 定案：**2% → 关键区 51/1369 点、"
  "5% → 全域 1369 点、S2 3% → 工程量**；**「全域 2%」为已退役的对象错配读数**）：全域 5% ⇒ 2/7、"
  "关键区 2% ⇒ 0/7、S2 3% ⇒ 0/7（一致不通过）；`release_allowed = false`；**405 组不得展开**；"
  "且该管线落在声明范围之外 |")

R(550,
  "| 用旧值或估计值顶替未落地的 te2_9 扩频重导 | 新导出**未落地**（`new_export = null`、无 `Table_9.txt`、"
  "smoke 在 `solnum` 上报错）⇒ 新导出侧数字一律 `【待产物】`（§5.1） |",
  "| 用旧值或估计值顶替未落地的 te2_9 扩频重导 | 新导出**正在跑（分块、尚未全完）**：按 `N_w_te1` 切 8 块，"
  "截至远端钟 `2026-10-09T15:47:49` 完成 `chunk_01/02`（`N_DONE = 2`）、`chunk_03` 进行中；"
  "成品 `Table_9.txt` 未落地 ⇒ 新导出侧数字（含 **648×91 = 58,968**、**24 格**救回、净可用增量、"
  "Q 达标分母）一律 `【待产物】`（§5.1） |")

R(554,
  "物理一致性与网格无关性给出**明确的负结果**：S3 `failed`（0.0602114 > 0.005，`S3_complete = false`）、"
  "S4 在**已裁决采用**的口径 O（全体有序对）下 `failed`（**2.4223% > 2%**；"
  "最细一对的**口径 F 1.3553% 仅作次要敏感性口径**并列，二者均为**事后声明口径**；"
  "冻结三档口径仍 `inconclusive`）、场级三对象门禁 0/7 与 2/7 且 **405 组不得展开**；"
  "模型状态保持 `draft`，严格口径下 PMUT L1 未通过，且无实验与文献证据入库。"
  "**第二批已确定事实（`INDEX §111–§116`）**：S4 在**同批同机 6 档 `ftet1` 阶梯**上口径 O ＝ "
  "**1.3847% < 2% ⇒ `passed`**（关键区 0.6507%；只动 `ftet1` 1.3847%、双轴 0.8753%，两条轴单独都过），"
  "但 **Richardson 外推下最细档距 `h→0` 仍有 ~2.6% 估计残差（外推、非实测）** ⇒ "
  "该 `passed` **只覆盖所测 6 档之间的两两差、不等于网格无关**；"
  "**旧阶梯上已裁决采用的口径 O（2.4223% `failed`）未被推翻**；",
  "物理一致性给出明确的负结果：S3 `failed`（0.0602114 > 0.005，`S3_complete = false`）；"
  "**S4 网格无关性按用户 2026-10-09 最新裁定 ＝ `passed`，判定对象 = 关键区（51/1369 点；口径 O = 全体有序对）**："
  "**`ftet1` 阶梯（§111）关键区 0.6507% < 2%**（全域 1.3847% 作参考）；"
  "**裁定书引用的数字属旧阶梯 `s34-ladder-server-20261008`（`h3um` over `h1um`）—— 关键区 1.5191% < 2%**、"
  "**全域 2.4161% 降为参考口径**（跨机 2.4223%、最细一对**口径 F 1.3553%** 同为参考；"
  "口径性质仍为**事后声明**；冻结三档口径仍 `inconclusive`）；**两套阶梯不得混用成一句**；"
  "**三条限制随结论同现**：只覆盖**所测档两两差**（**不得**称网格无关）、"
  "**Richardson 外推仍有 ~2.6% 估计残差（外推、非实测）**、**λ/9 与 λ/10 尚未跑完（正在排队）⇒ "
  "结论只覆盖既有档、可能再更新**；场级三对象门禁 0/7 与 2/7 且 **405 组不得展开**；"
  "模型状态保持 `draft`（**S4 转 `passed` 不等于放行**：第一跳要 S0 与 S3，二者仍 `inconclusive` / `failed`），"
  "严格口径下 PMUT L1 未通过，且无实验与文献证据入库。")

R(684,
  "- 把 S4 的口径 F 通过写成「离散无关性已验证」（**已裁决采用口径 O，判 `failed`**；"
  "口径 F 仅为次要敏感性口径，且二者均为事后声明口径）；",
  "- 把 S4 的口径 F 通过写成「离散无关性已验证」（**权威判定 = 口径 O ＋ 关键区 ⇒ `passed`**；"
  "口径 F 仅为次要敏感性口径，且二者均为事后声明口径）；")

R(686,
  "- 把新 6 档 `ftet1` 阶梯的 `passed` 写成「该模型已网格无关」（**只覆盖 6 档两两差**，"
  "Richardson 外推仍 ~2.6%）；",
  "- 把 S4 的 `passed`（无论取值档集是 §（二）的旧三档还是 §（二之二）的 6 档）写成「该模型已网格无关」"
  "（**只覆盖所测档两两差**，Richardson 外推仍 ~2.6%；λ/9、λ/10 未跑完）；")

R(689,
  "- 用旧值或估计值顶替未落地的 te2_9 扩频重导（应标 `【待产物】`）。",
  "- 用旧值或估计值顶替**仍在跑（分块、尚未全完）**的 te2_9 扩频重导"
  "（应标 `【待产物】`；现场实测 `N_DONE = 2/8`）。")

R(699,
  "- S3 `failed`、S4 **已裁决采用口径 O 判 `failed`（2.4223% > 2%）**，口径 F（1.3553%）为**次要敏感性口径**，"
  "冻结三档口径 `inconclusive`；**v6 补**：新 6 档 `ftet1` 阶梯口径 O **1.3847% `passed`**，"
  "但**只覆盖 6 档两两差**（Richardson 外推仍 ~2.6%）⇒ **不等于网格无关**；"
  "S3 守恒残差随设计点变到 **0.1112**、**三项 `None`**、`S3_complete = False`；",
  "- S3 `failed`；**S4 ＝ 口径 O ＋ 关键区（51/1369）⇒ `passed`**："
  "**`ftet1` 阶梯（§111）关键区 0.6507%**（全域 1.3847% 参考）、"
  "**裁定书引用的旧阶梯 `s34-ladder-server-20261008` 关键区 1.5191%**（全域 2.4161% 参考）；"
  "口径 F（1.3553%）为**参考/次要敏感性口径**；冻结三档口径 `inconclusive`；"
  "**两套阶梯不得混用成一句**；该 `passed` **只覆盖所测档两两差**（Richardson 外推仍 ~2.6%；"
  "λ/9、λ/10 未跑完）⇒ **不等于网格无关**；**S4 转 `passed` 不等于放行**"
  "（§6.4 第一跳要 S0 与 S3，二者仍 inconclusive / failed）；"
  "S3 守恒残差随设计点变到 **0.1112**、**三项 `None`**、`S3_complete = False`；")

# --------------------------------------------------------------------------
# 插入表：(在原始行号之后插入的行)
# --------------------------------------------------------------------------

INSERT: list[tuple[int, list[str]]] = []

V7_NOTE = (
    "> **v7 修订（本轮；依据用户 2026-10-09 最新裁定 ＋ `INDEX §126` / `§127` ＋ A4 定案；"
    "**S4 的判定只有一条**）**："
    "① **S4 网格无关性 = `passed`；判定对象 = 关键区**（`R = ‖(x,y,z)‖ ≤ R_max/3`，**51/1369** 点；"
    "阈值键 `S4_mesh_diff_max = 0.02`，**不新造阈值**）。**口径 O（全体有序对）＋ 关键区**在两套档集上都不超线，"
    "但**两套阶梯的数字必须分开写、不得混用成一句**："
    "**(a) 主敏感轴 `ftet1` 阶梯**（同批同机 6 档、30 个有序对；`INDEX §111`）⇒ **关键区 0.6507% < 2%**"
    "（全域 **1.3847%** 作**参考**）；"
    "**(b) 用户裁定书引用的数字属旧阶梯** `work/runs/s34-ladder-server-20261008`"
    "（三档同机、`h3um` over `h1um`）⇒ **关键区 1.5191% < 2%**、**全域 2.4161% 作参考口径、不再作判定依据**"
    "（跨机登记的旧读数 **2.4223%** 与最细一对的口径 F **1.3553%** 同为参考）。"
    "**三条限制随结论同现**：① 只报「**所测档之间的两两差**」，**不得声称「网格无关」**；"
    "② **Richardson 外推显示最细档距 `h→0` 仍有 ~2.6% 估计残差（外推、非实测）**；"
    "③ **新增 λ/9 与 λ/10 两档尚未跑完（正在排队）** ⇒ 该结论**只覆盖既有档**，"
    "新档结果落地后**可能再更新**。"
    "**② S4 转 `passed` 不等于放行**：§6.4 第一跳要 **S0 与 S3**，二者仍 `inconclusive` / `failed` ⇒ "
    "**仍不得放行**，且**不得因 S4 变好而改 S3 的结论**。"
    "③ **A4 定案（三对象三阈值）**：**2% → 关键区（51/1369）**、**5% → 全域（1369）**、"
    "**S2 3% → 工程量**；**S1 = 前两者同时成立**；"
    "**点名退役「全域 2%」这一 spec 中不存在的判据**（对象错配，见 §6.6）。"
    "④ **报数纪律（`INDEX §127`）**：报「某对象的折通过数」**必须同时给模型名**，"
    "并**先检查该对象 `max` 是否并列**；**并列时以权威件 `best_model` 为准，并把并列一并报出，"
    "不得择优取数**（实例见 §5.2）。"
    "⑤ **x 族 `.mat` 校验为降级口径**（远端 `output_manifest.tsv` 不存在，见 §5.4），"
    "**不得**表述为「与 manifest 逐个相符」。"
    "⑥ **阶段 3（te2_9 扩频重导）＝【待产物】**：导出**正在跑（分块、尚未全完）**，"
    "**不得**用估计值或旧值顶替。"
    "⑦ **四条 `【待裁定】` 原样保留**（跨批同组合标签不一致 **137 组** ／ A∪C 池化 ／ v2 选带口径 **46 vs 43** ／ "
    "是否修 `scripts/verify_*.py` 的 2 处读写混用），**本轮不代裁定**。"
    "**本轮仍未提升任何状态**（`solver_spec.json` 仍 `state=draft`、sha256 `21315173…b6bd3f`；"
    "`multichannel_model.json` 仍 `status=draft`、sha256 `0d872fb1…444b1`）。"
)
INSERT.append((12, [V7_NOTE]))

TIE_NOTE = (
    "> **报数纪律（v7 新增；依据 `INDEX §127.6`）**：报「**某对象的折通过数**」**必须同时给模型名**，"
    "并**先检查该对象 `max` 是否并列**；**出现并列时，以权威件 `best_model` 为准，并把并列模型一并报出，"
    "不得择优取数**。实例（`INDEX §127` / `work/runs/field-expansion-20261009/S2_FOLD_RECHECK.md`）："
    "S2 对象上 `raw_linear` 与 `raw_pchip` 的 `max` **完全并列**（都是 `0.7618331854270892`，"
    "因 N1=1 端点外推折在两者间**逐位相同**），但**折通过数不同**（`raw_linear` **0/7**、`raw_pchip` **3/7**）；"
    "权威件 `pod_objects_x020_three_objects.json` 的 `per_object_ranking.S2_max_abs_p_rel_err` 明写 "
    "`best_model = 'raw_linear'`、`best_n_folds_pass = 0` ⇒ **规范读数 = `0/7`（`raw_linear`）**；"
    "把 `raw_pchip` 的 `3/7` 挂在「最优」上属**静默换模型**，且方向是**把数字变得好看**"
    "（`0/7` → `3/7`）—— 这是一处**必须点名的缺陷**。该件 `_note` 原文："
    "**禁止用某个对象的最优模型去代表另一个对象**。"
)
INSERT.append((258, [TIE_NOTE]))

MANIFEST_NOTE = (
    "> **x 族 `.mat` 校验的「口径降级」声明（v7 新增，照抄不弱化；`INDEX §126.2`）**："
    "远端 `output_manifest.tsv` **不存在**（现场 `find … -maxdepth 1 -name output_manifest.tsv | wc -l` = **0**；"
    "顶层只有 `pod_20MHz/`、`representative_full/`、`snapshot_index.tsv`）"
    "⇒ x 族 `.mat` 的校验**只能用降级口径**：**远端现算 `sha256sum` → 本地复算比对** ＋ "
    "index 的 `n_points` 与参数**三路一致**（文件名 / index 行 / 计划行）＋ "
    "**掩膜计数一致**（`p_finite_mask` 非零计数 == `p_total_Pa` 有限元素数）。"
    "**不得**表述为「与 manifest 逐个相符」。"
    "本轮 A1 取回的 **400 件 / 632,468,318 B**、**5/5 块六条全过**、**豁免清单为空**，"
    "均为该降级口径下的实测（`INDEX §126.1`–`§126.3`）。"
)
INSERT.append((298, [MANIFEST_NOTE]))

V5_HISTORY_BULLET = (
    "- **v5 的旧读数（历史，已被上行取代、不隐藏）**：八项裁决第 1 项当时只钉了**口径 O**、"
    "**未指定空间对象**，且判在**全域** ⇒ `2.4223% > 2% ⇒ failed`。"
    "**口径 F（最细一对 `h2um` ↔ `h1um` < 2%）= 1.3553%（关键区 0.6110%）仍为敏感性/次要口径**，"
    "沿用已有批准 id `fb-20261006-s4_criterion_finest_pair`（`validation` 记录 "
    "`val-pmut-s4-mesh-finest-pair-20261006`，`level = S4`、`passed = true`）。"
)
INSERT.append((484, [V5_HISTORY_BULLET]))

S4_ONLY_ONE_BULLET = (
    "- 把 S4 写成**两条相反的判定**（例如「口径 O `failed`」与「口径 O `passed`」并列）"
    "—— **v7 起 S4 只有一条判定**（口径 O ＋ 关键区 ⇒ `passed`），其余读数一律为**参考口径**；"
)
INSERT.append((686, [S4_ONLY_ONE_BULLET]))


def main() -> int:
    raw = V6.read_bytes()
    got = sha256(raw)
    if got != V6_SHA256 or len(raw) != V6_BYTES:
        print(f"FATAL v6 sha256/bytes mismatch: {got} / {len(raw)}")
        return 2
    if raw.count(b"\r\n") != V6_LINES or raw.count(b"\n") != V6_LINES:
        print("FATAL v6 not pure CRLF")
        return 2
    if raw.count(b"\r") != V6_LINES:
        print("FATAL v6 has lone CR")
        return 2

    text = raw.decode("utf-8")
    lines = text.split("\r\n")
    if len(lines) != V6_LINES + 1 or lines[-1] != "":
        print(f"FATAL v6 line split unexpected: {len(lines)}")
        return 2

    # --- 校验：每条旧片段在其所在行恰好 1 次、全稿恰好 1 次 ---
    per_line: dict[int, list[tuple[str, str]]] = {}
    for lineno, old, new in REPL:
        if not (1 <= lineno <= V6_LINES):
            print(f"FATAL lineno out of range: {lineno}")
            return 2
        line = lines[lineno - 1]
        if line.count(old) != 1:
            print(f"FATAL old not unique in line {lineno}: count={line.count(old)}")
            print("  OLD:", old[:120])
            return 2
        if text.count(old) != 1:
            print(f"FATAL old not unique in document: line={lineno} count={text.count(old)}")
            return 2
        if new in text:
            print(f"FATAL new already present in v6 (line {lineno}): {new[:120]}")
            return 2
        per_line.setdefault(lineno, []).append((old, new))

    # --- 校验：同一行内片段互不重叠 ---
    for lineno, items in per_line.items():
        line = lines[lineno - 1]
        spans = []
        for old, _ in items:
            i = line.index(old)
            spans.append((i, i + len(old)))
        spans.sort()
        for a, b in zip(spans, spans[1:]):
            if b[0] < a[1]:
                print(f"FATAL overlapping snippets in line {lineno}: {spans}")
                return 2

    # --- 应用替换 + 插入 ---
    ins_after: dict[int, list[str]] = {}
    for lineno, newlines in INSERT:
        if not (1 <= lineno <= V6_LINES):
            print(f"FATAL insert lineno out of range: {lineno}")
            return 2
        ins_after.setdefault(lineno, []).extend(newlines)

    out_lines: list[str] = []
    for idx, line in enumerate(lines[:-1], start=1):
        for old, new in per_line.get(idx, []):
            line = line.replace(old, new)
        out_lines.append(line)
        out_lines.extend(ins_after.get(idx, []))
    out_lines.append("")  # 结尾 CRLF

    v7_bytes = "\r\n".join(out_lines).encode("utf-8")

    # --- 校验：每条新片段在结果中恰好 1 次 ---
    v7_text = v7_bytes.decode("utf-8")
    for lineno, old, new in REPL:
        c = v7_text.count(new)
        if c != 1:
            print(f"FATAL new count != 1 (line {lineno}): {c}")
            print("  NEW:", new[:160])
            return 2
    for _, newlines in INSERT:
        for nl in newlines:
            if v7_text.count(nl) != 1:
                print(f"FATAL inserted line count != 1: {v7_text.count(nl)}")
                return 2

    # --- 校验：纯 CRLF ---
    n_lf = v7_bytes.count(b"\n")
    n_crlf = v7_bytes.count(b"\r\n")
    n_cr = v7_bytes.count(b"\r")
    if n_lf != n_crlf or n_cr != n_crlf:
        print(f"FATAL v7 not pure CRLF: LF={n_lf} CRLF={n_crlf} CR={n_cr}")
        return 2

    # --- 校验：反向还原可逐字节还原 v6 ---
    r_lines = v7_text.split("\r\n")
    ins_multiset = []
    for _, newlines in INSERT:
        ins_multiset.extend(newlines)
    kept = []
    removed = 0
    for ln in r_lines[:-1]:
        if ln in ins_multiset:
            ins_multiset.remove(ln)
            removed += 1
            continue
        kept.append(ln)
    if ins_multiset:
        print(f"FATAL reverse: {len(ins_multiset)} inserted lines not found")
        return 2
    if removed != sum(len(v) for _, v in INSERT):
        print(f"FATAL reverse: removed {removed} != expected")
        return 2
    back: list[str] = []
    for idx, line in enumerate(kept, start=1):
        for old, new in per_line.get(idx, []):
            if line.count(new) != 1:
                print(f"FATAL reverse: new not unique in line {idx}")
                return 2
            line = line.replace(new, old)
        back.append(line)
    back.append("")
    restored = "\r\n".join(back).encode("utf-8")
    if restored != raw:
        print("FATAL reverse restore != v6 (byte-level)")
        return 2

    # --- 写盘 ---
    V7.write_bytes(v7_bytes)

    # --- 公共前缀（v6 是就地修订、不是 v7 的字节前缀） ---
    cp = 0
    for a, b in zip(raw, v7_bytes):
        if a != b:
            break
        cp += 1

    print("V7_OK")
    print(f"v6: {len(raw)} B / {V6_LINES} 行(CRLF) / {sha256(raw)}")
    print(f"v7: {len(v7_bytes)} B / {v7_bytes.count(chr(13).encode()+chr(10).encode())} CRLF / {sha256(v7_bytes)}")
    print(f"path: {V7}")
    print(f"replacements: {len(REPL)}  inserts: {sum(len(v) for _, v in INSERT)}")
    print(f"common_prefix_bytes: {cp} (v6 不是 v7 的字节前缀)")
    print("reverse_restore == v6: True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
