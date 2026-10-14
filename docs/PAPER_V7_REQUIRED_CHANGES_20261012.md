# DAC 2027 论文：v6 → v7 **所需改动清单**（只列不改；v6 仍是提交候选）

> 生成：2026-10-12。**本件不修改论文**。提交候选仍是 `PAPER_DAC2027_EN_v6_20261011.md` ＋ 补充材料。
> 每一项都给出：**v6 现文（含行号）｜为什么被超越｜出处｜建议替换文**。
> 是否出 v7、以及是否此刻出（会重开提交候选），**由你决定**。

## 0. 一句话

本轮（INDEX §189–§208）产生了 **4 处"数字/事实被超越"** 与 **1 处"表述需收紧"**，
以及 **1 处"可以新增的更强结果"**。**没有一处是 v6 写错了** —— 它们都是**当时正确、现在有更好口径或更多证据**。

---

## A. 【必须改】S3 的通过/失败计数：`7 通过 / 2 失败` → **`8 通过 / 1 失败`**

**v6 现文（L268–269）**：
> "On the gate design point the registered S3 report gives **7 passes, 2 failures** and 0 inconclusive outcomes."

**为什么被超越**：更正口径后（`conservation_current_circuit_vs_field_flux` 由**口径作废**改判通过：
物理场法向 6.469e-04…1.032e-03 / 8.168e-04），计数为 **8 通过 / 1 失败**；
**该更正口径已由人于 2026-10-12 逐项确认**（INDEX §192 第一条）。

**出处**：`work/runs/eda64-20261010/p5_cost/S3_GATE_CORRECTED_CALIBER.{json,md}`、INDEX §182/§192。

**建议替换文**：
> "On the gate design point the registered S3 report gives 7 passes and 2 failures; after the
> current-conservation check is re-evaluated under the physics normal (**6.469e-04…1.032e-03** on one
> carrier, **8.168e-04** on a second), the corrected count is **8 passes and 1 failure**, with 0
> inconclusive outcomes. This corrected caliber was confirmed by the human reviewer on 2026-10-12."

---

## B. 【必须改·且是**更强**的结果】能量项：把"电路缺口"与"声学侧网格"**分开**

**v6 现文（L273–274、L306、L308–311）**：
> L273–274: "The energy-closure check is *not* an artefact: the electrical input power is **6.177 %**
> below the radiated acoustic power against 0.5 %, and §6.5 shows that this survives refinement."
> L306（诊断表末行）: "unconverged discretisation | solid-side ×1 → ×0.75 → ×0.5: −4.852 % → −4.384 % →
> **−4.121 %** … acoustic mesh changes it by **0.0011 pp** | **refuted**"
> L308–311: "…this is a genuine discrete non-closure … and it **does not vanish with refinement** —
> the extrapolated limit, ≈ **−3.8 %**, is roughly eight times the 0.5 % criterion."

**为什么需要改**：以上**都正确**，但它们是**"电—声"口径**（`P_in` 对 `P_asi`）。本轮另立了一条
**与电路无关**的口径，并在它上面得到了**不同的收敛行为**：

| 口径 | 量 | 随加密的行为 |
|---|---|---|
| 电—声（v6 现口径） | `(P_in − P_asi)/P_asi` | **收敛到非零极限 ≈ −3.8 %**（≈8× 阈值）⇒ 是**电路模型不完整**，加密不关闭 |
| **声学侧净通量（新）** | `\|∮_{∂Ω} I·n_outward dA\| / \|Φ_outer\|` | **按 O(h²) 收敛**：20 MHz 下 λ/5 **1.770575 %** → λ/7 **0.953987 %**（残差比 0.5388 vs O(h²) 的 0.5102）⇒ 是**离散误差**，加密**可以**关闭 |

⇒ v6 的"does not vanish with refinement"对**前者**成立、对**后者不成立**；
不加区分地并列会让读者把两件事混为一谈。

**出处**：INDEX §202（(甲) 判定 + 逐面几何取向）、§203（O(h²) 扫描，**零新求解**）、§205（τ = 0.5 % 已签）。

**建议**:在 §6.5 末尾新增一段（不改动原表）：
> "**Two calibers must be kept apart.** The table above is the *electrical-to-acoustic* caliber, and its
> non-vanishing limit (**≈ −3.8 %**) is a property of an intentionally incomplete circuit model. On the
> *acoustic side alone* there is a circuit-free criterion: the net outward flux over the closed fluid
> boundary must vanish for a lossless source-free domain. Measured on eight independent points it is
> **0.0769 %** at 5 MHz and **0.4660 %** at 10 MHz (inside the 0.5 % criterion) but **1.07–4.49 %** from
> 15 to 35 MHz. Unlike the electrical gap, **this residual does converge with mesh refinement**: at
> 20 MHz it falls from **1.770575 %** (λ/5) to **0.953987 %** (λ/7), a ratio of **0.5388** against the
> 0.5102 predicted by second-order convergence. The residual is therefore a discretisation error of the
> acoustic mesh, not a missing dissipation path: an exhaustive inventory of the model's settings
> (attenuation coefficients, complex sound speed, PML/absorbing/impedance features, thermoviscous
> couplings, lossy material properties) found **no dissipation term at all**. Closing this item requires
> acoustic-mesh refinement, not a model change."

---

## C. 【必须改·§6.5 诊断表第 4 行】"two disjoint surfaces" 的说法被推翻

**v6 现文（L304）**：
> "integration surface | two disjoint surfaces agree to 1.8 %, but **both exceed** the electrical input
> (3.996822e-06 W and 3.924776e-06 W versus 3.734359e-06 W) | refuted"

**为什么被超越**：**穷举该网格全部 65,535 个 domain 子集后，唯一可证闭合的边界集合只有一个**
（`∂(domain 1)`，17 个面，32/32 条边恰共享 2 次）。旧探针的 `HEMI`(4 面) 与 `ASI`(12 面)
**各自都不闭合**（各 4 条开边，落在同一条接触环上），二者只是 `∂(domain1)` 的**两片互补剖分**。
并且**取向已由逐面几何实测判定**：外片（穹顶 4 + 环面 1）**外向**，源片 12 面**内向**
（由平移形式散度恒等式 `∮n·(x−x_c)dA = 3V` **唯一**判出：残差 literal **6.61 %** / flip_outer **200 %** /
**flip_source 9.34e−8**）。

**出处**：`p5_cost/P5_4_ENERGY_SURFACE_CHECK.json`（边界普查 + 子集穷举）、
`P5_4_NORMAL_ORIENTATION_CHECK.json`（17 面逐面 ρ）、INDEX §198/§202。

**建议替换该行的 measurement 列**：
> "the two patches are the **complementary halves of the single provably closed boundary** `∂(domain 1)`
> (exhaustive search over all 65,535 domain subsets finds exactly one closed set); their orientation is
> **measured** per face, not assumed (outer patch outward ρ ≈ +1.0…+1.13; source patch inward
> ρ ≈ −0.72…−0.88), so their flux difference **is** the net outward flux, 0.077 % at 5 MHz rising to
> 4.49 % at 35 MHz"

---

## D. 【应改·表述收紧】S4 的 "post-hoc caliber"

**v6 现文（L283–285）**：
> "S4 therefore passes **only** on the levels tested, **under a post-hoc caliber**, and must not be read
> as mesh independence."
> "the finest-pair caliber the reviewer later approved passes, and both readings are reported"

**为什么需要改（不是错，是要更准）**：2026-10-12 已对 S4 补做**事前预注册并重跑分析**（零新求解）：
口径（**口径 O ＋ 关键区 ＋ 2 %**）与全部字节锚点在**跑之前**冻结，operative = **0.015190895 ≤ 0.02 ⇒ passed**，
且 12 个判定数字与既有登记**逐位一致（差 0.00e+00）**。
**但**判定**对象（关键区）继承自 v7 的事后裁定** ⇒ 「口径为事后声明」**并未被修掉**。

**出处**：`work/runs/s4-prereg-20261012/PREREG_S4.{json,md}`、`S4_RERUN_REPORT.{json,md}`；INDEX §206/§207。

**建议**：把"under a post-hoc caliber"改为
> "under a caliber **frozen before the present re-analysis** — a re-analysis that reproduces the recorded
> values **bit-for-bit** — while the *choice of the spatial object* (key region) is **inherited** from an
> earlier post-hoc ruling and is therefore **not** cleansed by that re-analysis; the re-analysis uses the
> **same solved fields** and is **not** an independent confirmation"

**并且**：v6 的九档/72 有序对读数与本次三档/6 有序对读数**属不同档集，不得混用成一句**（沿用 v7 的纪律）。

---

## E. 【可选·新增】场级 ROM：从"7 个快照不足"升级为一条**定量**结论

**v6 现状**：§6.4 只写"local level"的 S1（shape-preserving local model 通过）；本轮
**场级 ROM** 的九轮实验（§187–§193）与**分区图**（§197）**未进 v6**。

**可以新增的更强结果**（若你愿意扩稿；不给工程绝对值）：
> "For a *field-level* ROM the obstruction is not representation, rank or sampling. Across **eight**
> distinct representation families — global POD, key-region-weighted POD, a physics basis of 25–36 outgoing
> spherical waves, implicit coordinate networks, and factorised rank-1…12 models — the **worst held-out
> cell is the same one** (x = 0.63, f = 9.2 MHz); removing it drops the maximum from 17.7 % to 7.5 %,
> while the maximum is **insensitive** to representation, to x-rank (1 → 12) and to x-sampling density
> (12 → 32 nodes). Median errors do fall as sampling is refined (13.4 % → 0.94 %), and the held-out
> fields reproduce to machine precision (relative differences 1e-13…2e-11), so the residual is neither a
> data defect nor a modelling artefact: **the field's correlation length along the design parameter is
> shorter than the sampling spacing (≈0.01 against 0.02–0.05)**. A leave-one-out scan finds no
> spacing threshold — at the *same* 0.023 spacing the error ranges from 1.12 % to 35.70 % — so the
> certified domain is not expressible as 'x within δ' but only as an explicit interval list, whose
> cross-family common part is a single narrow band (x ∈ [0.78, 0.886])."

**出处**：§189–§194、§197（含 `XDENSE_SHAPE_VS_GAIN.json`、`RECHECK_HOLDOUT_COMPARE.json`、`PARTITION_MAP.json`）。

**提醒**：本节若加入，页数会涨（当前正文 4,463 词），而 DAC 限 **6 页 + 1 页仅参考文献**；
**是否加、加多少，取决于版面预算** —— 这也是我把它列为"可选"的原因。

---

## F. 不需要改的（核对过，仍然正确）

- S4 的"只覆盖所测档两两差、不得读成网格无关"；
- Richardson 外推的三种口径并报；
- 场级门禁 `0/7`、`0/7`、`2/7` 与 405 组不展开；
- "No engineering absolute value is quoted anywhere in this paper."；
- L301–L303 三行（端口电压约定 / 电流后处理表达式 / 平面波声功率）——**本轮没有推翻它们**。

## G. 提交候选的状态（**未变**）

- 提交候选**仍是 v6 ＋ 补充材料**；**本件不改论文**；
- 仍悬空的提交项（与 `docs/DAC2027_SUBMISSION_CHECKLIST.md` 一致）：TeX 页数编译、
  补充材料投稿规则、图与 caption、LLM 标识；
- 摘要 2026-11-11、正文 2026-11-18（AoE 换算见清单）。

## H. 不主张

- **不主张** v6 有错 —— 上述 A–E 都是"当时正确、现在有更好口径或更多证据"；
- **不主张**必须现在出 v7（会重开提交候选，且涉及版面，**由你定**）；
- **不主张** B 段的新口径已"关闭能量项" —— 按 τ = 0.5 %，**该项判定为失败**（8 点里 2 点通过）；
- 不提升任何状态；`release_allowed` 仍 `false`；`solver_spec` 仍 `draft`。
