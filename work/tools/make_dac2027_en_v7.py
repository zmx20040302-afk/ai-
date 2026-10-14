# -*- coding: utf-8 -*-
"""v7：由 **v6** 生成（正文改动 5 处 ＋ 补充材料新增 §S9/§S10）。

方法（沿用 v6 的纪律）：
  * **逐处字面替换**，每处在 v6 里**必须恰好命中 1 次**，否则报错退出（不猜、不模糊匹配）；
  * **不动任何既有数字**：本次只做 ① 计数更正（7/2 → 8/1）② 两口径分开写 ③ 表行改写 ④ S4 表述收紧
    ⑤ 场级 ROM 定量结论；**其余段落一字不改**；
  * **明细进补充材料**（§S9 净通量口径与逐面取向；§S10 场级 ROM），正文只留结论与指针 —— 保护 6 页限制；
  * 生成后做**自检**：字数、锚点、以及"v7 的其余部分与 v6 逐字节相同"（按替换点分段比对）。

产物：`docs/PAPER_DAC2027_EN_v7_20261012.md`、`docs/PAPER_DAC2027_EN_v7_PROVENANCE.md`、
      `docs/PAPER_DAC2027_EN_SUPPLEMENT_20261012.md`、
      `work/runs/eda64-20261010/n5_stage3/V7_GENERATION_REPORT.json`
"""
from __future__ import annotations

import difflib
import hashlib
import json
import pathlib
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
V6 = REPO / "docs/PAPER_DAC2027_EN_v6_20261011.md"
V7 = REPO / "docs/PAPER_DAC2027_EN_v7_20261012.md"
V7P = REPO / "docs/PAPER_DAC2027_EN_v7_PROVENANCE.md"
S6 = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261011.md"
S7 = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261012.md"
OUT = REPO / "work/runs/eda64-20261010/n5_stage3"

# ------------------------------------------------------------------ 正文替换（每处必须命中 1 次）
REPL = [
    # A. S3 计数更正（INDEX §192/§182）
    ("gives 7 passes, 2 failures and 0 inconclusive outcomes.",
     "gives 7 passes and 2 failures. Correcting the current-conservation check as described next makes "
     "the count **8 passes and 1 failure**, with 0 inconclusive outcomes; that corrected caliber was "
     "confirmed by the human reviewer on 2026-10-12."),
    # C. §6.5 诊断表第 4 行（INDEX §198/§202）
    ("| integration surface | two disjoint surfaces agree to 1.8 %, but **both exceed** the electrical "
     "input (3.996822e-06 W and 3.924776e-06 W versus 3.734359e-06 W) | refuted |",
     "| integration surface | the two patches are the **complementary halves of the one provably closed "
     "boundary** `∂(domain 1)` — an exhaustive search over all 65,535 domain subsets finds exactly one "
     "closed set — and their orientation is **measured per face**, not assumed; their flux difference is "
     "a genuine net outward flux (0.077 % at 5 MHz rising to 4.49 % at 35 MHz), not a surface "
     "disagreement | refuted |"),
    # D1. S4 表述收紧（INDEX §206/§207）
    ("under a post-hoc caliber, and must not be read as",
     "under a caliber **frozen before the 2026-10-12 re-analysis**, and must not be read as"),
    # D2. 非独立性的限制（紧接着上一句那一段）
    ("2.235 %, the finest-pair caliber the reviewer later approved passes, and both readings are reported.",
     "2.235 %, the finest-pair caliber the reviewer later approved passes, and both readings are reported. "
     "The 2026-10-12 re-analysis froze the caliber and every byte anchor *before* running and reproduced "
     "all twelve recorded values **bit-for-bit**; it nevertheless re-uses the **same solved fields**, so it "
     "is a procedural fix and **not** an independent confirmation, and the *choice* of spatial object is "
     "inherited from the earlier post-hoc ruling rather than cleansed by it."),
    # B. 两口径分开写（追加在 §6.5 末句之后）
    ("caliber must be named each time.",
     "caliber must be named each time.\n\n"
     "**Two calibers must be kept apart.** The table above is the *electrical-to-acoustic* caliber, whose "
     "non-vanishing limit (≈ −3.8 %) reflects an intentionally incomplete circuit model. On the *acoustic "
     "side alone* a circuit-free criterion exists — the net outward flux over the closed fluid boundary "
     "must vanish — and it behaves differently: **0.0769 %** at 5 MHz and **0.4660 %** at 10 MHz, but "
     "**1.07–4.49 %** from 15 to 35 MHz, converging with refinement as **1.770575 % → 0.953987 %** "
     "(λ/5 → λ/7 at 20 MHz, a ratio of 0.5388 against the 0.5102 of second order). It is therefore a "
     "**discretisation error of the acoustic mesh**, not a missing dissipation path (§S9); closing it "
     "needs mesh refinement, not a model change."),
    # E. 场级 ROM 定量结论（追加在 §6.4 末句之后）
    ("Per-check tables, the ladder history and the full caveat list are in §S2–§S5.",
     "Per-check tables, the ladder history and the full caveat list are in §S2–§S5.\n\n"
     "**The field-level obstruction is physical, not methodological.** Across eight representation "
     "families the worst held-out cell is always the same one (x = 0.63, f = 9.2 MHz); removing it drops "
     "the maximum from 17.7 % to 7.5 %, and that maximum is insensitive to representation, to x-rank "
     "(1 → 12) and to x-sampling density (12 → 32 nodes). The held-out fields reproduce to machine "
     "precision (1e-13…2e-11), so the residual is not a data defect; the field's correlation length along "
     "the design parameter is simply shorter than the sampling spacing (§S10)."),
]

# ------------------------------------------------------------------ 补充材料新增两节
S9 = """
## S9. Acoustic-side net-flux caliber and per-face orientation

**Criterion.** For a lossless, source-free fluid domain the divergence theorem gives
`∮_{∂Ω} I·n_outward dA = 0`, so the net outward flux over the closed fluid boundary must vanish. This
is circuit-free and is the measurable form of "two enclosing closed surfaces agree": with only one
provably closed boundary in this mesh, the net flux is the only available form of the same statement.

**There is exactly one closed boundary.** Enumerating the boundary of all 65,535 domain subsets
(closure test: every edge of the set belongs to exactly two faces of the set, using measured
`boundary_edges`) yields **one** closed set: `∂(domain 1)`, the acoustic-domain boundary, **17 faces**,
with **32/32** edges shared by exactly two faces. The older probe's `HEMI` (4 faces) and `ASI`
(12 faces) are each **not** closed (4 open edges each, on the same contact ring); they are the two
**complementary halves** of `∂(domain 1)`.

**Orientation is measured, not assumed.** With the measured fluid-domain centroid
`x_c = (0, 0, −37.499999e-06) m` and volume `V = 2.09439355675e-12 m³` (exactly (2/3)π(100 µm)³, so the
fluid is the z < 0 hemisphere), the per-face index `ρ_i = σ_i /(A_i |c_i − x_c|)` with
`σ_i = ∫ n·(x − x_c) dA` gives **+1.1315** (dome) and **+1.0** (ring) — outward — and
**−0.7218 / −0.7589 / −0.8807** for the twelve source-patch faces — inward. The translated divergence
identity `∮ n·(x − x_c) dA = 3V` decides this uniquely:

| orientation hypothesis | residual against 3V |
|---|---:|
| literal (no flip) | 6.61 % |
| flip outer patch | 200.0 % |
| **flip source patch** | **9.34e-08** |

**Two tempting identities have no discriminating power here** and must not be used: `∮ n dA = 0`
(because `|∫_outer n dA| / |∫_source n dA| = 0.99999716` — the dome's πR² minus the ring's π(R²−r_in²)
equals the ASI disk's πr_in², so flipping either patch zeroes it) and the untranslated `F = x` form
(because `∫_source n·x dA = 0` exactly). Only the translated form works.

**Measured net outward flux / outer flux**, at eight independent points (four solution tags carry two
independent solutions: `sol1 ≡ sol2 ≡ sol3` are bit-identical):

| f (MHz) | 5 | 10 | 15 | 20 | 25 | 30 | 35 | (2nd geometry) 20 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| net / outer | 0.0769 % | 0.4660 % | 1.0722 % | 1.7499 % | 2.4127 % | 3.4035 % | 4.4913 % | 1.7286 % |

**It converges with the acoustic mesh.** A same-machine pair differing **only** in `ftet1`
(λ/5, 342,886 elements versus λ/7, 424,591 elements; identical `ftri1` and solid scale) gives at 20 MHz
**1.770575 % → 0.953987 %**, a ratio of **0.5388** against the **0.5102** predicted by second-order
convergence (first order would give 0.7143).

**No dissipation path exists in the model settings.** `alpha1 = alpha2 = alpha3 = 0`;
`Im(∫ c dV) = Im(∫ ρ dV) = Im(∫ k dV) = 0` (measured mean c = 1481.44 m/s, ρ = 998.202 kg/m³); no
PML/absorbing layer/thermoviscous feature in the fluid domain; no impedance or absorbing boundary on
any of the 17 fluid faces; zero hits for loss keywords across all 26 features and 4 interfaces; the
only couplings are `asb1` (which sits exactly on the twelve source faces) and `pze1`; the fluid material
carries no attenuation property.

**What this does and does not settle.** The residual is a discretisation error of the acoustic mesh —
so closing the item requires **mesh refinement**, not a model change. It does **not** settle whether any
solver-level equivalent loss exists, the scan having covered model settings only; and the
frequency-scaling exponent alone cannot separate the two, which is why the mesh pair above is used
instead. Under the inherited 0.5 % criterion the item **fails** at 15–35 MHz.
"""

S10 = """
## S10. Field-level ROM: representation families and the obstruction

**What was tried.** Eight representation families, all on the same frozen 1,373-point set, the same
held-out design (3 unseen x × 3 unseen f, thresholds 2 % key region / 5 % global) and with every
selection made on training cells only: (1) global POD coefficients with linear/cubic/rbf interpolation;
(2) key-region-weighted POD; (3) multi-pole vector fitting; (4) phase-explicit resonance fitting;
(5) a small MLP on POD coefficients; (6) implicit coordinate networks (two versions); (7) a physics
basis of outgoing spherical waves `h_l^(2)(kr)·Y_lm` with interpolated modal amplitudes; (8) factorised
models `p(x,f) ≈ Φ(r;f)·α(x,f)` at x-rank 1…12.

**Medians improve; maxima do not.**

| representation | key region, median | key region, max |
|---|---:|---:|
| global POD, cubic (12 x-nodes) | 13.4 % | 26.5 % |
| global POD, cubic (32 x-nodes) | **0.94 %** | 15.6 % |
| factorised, x-rank 3 (32 x-nodes) | **1.05 %** | 17.7 % |
| physics basis + amplitude interpolation | 4.98 % | 24.3 % |
| implicit coordinate network | 5.8 % | 76.4 % |

(second family: 14.1 % → 1.13 % for POD, max 18.3 %.)

**The maximum is always the same cell.** For every representation and every x-rank, the worst held-out
cell is `x = 0.63, f = 9.2 MHz`; the next two are `x = 0.93, f = 6.6` (7.5 %) and `x = 0.93, f = 9.2`
(5.3 %), and all six remaining cells are ≤ 5.3 %. Raising the factorised x-rank from 1 to 12 moves the
median from 11.8 % to 1.1 % but the maximum only from 20.2 % to 17.7 %. The maximum is likewise
insensitive to x-sampling density (12 → 32 nodes) and to the representation itself.

**The obstruction is not the data.** The held-out fields at `x = 0.63` and `x = 0.93` were re-solved on
the remote node and compared with the recorded ones: `K` relative differences are 0.0 (two cases) and
≤ 5.5e-11, `p_max` relative differences are 0.0, and the aligned field differs by 1e-13…2e-11 in the key
region — floating-point round-off. The validation data is correct to machine precision.

**It is not a spacing threshold either.** A leave-one-out scan over the 32 training x-nodes (holding out
one x, keeping all 21 training frequencies) finds **no** monotone rule in the distance to the nearest
remaining node: at the same 0.023 spacing the error ranges from **1.12 %** (`x = 0.863`) to **35.70 %**
(`x = 0.200`), and the worst case overall is `x = 0.269` at **60.0 %** for the second family. The hard
regions are the low-x band (≤ 0.29) and `x ≈ 0.46 / 0.59 / 0.65`; the smooth band is 0.73–0.91.

**Consequence for a declared domain.** Because no spacing threshold exists, a certified domain cannot be
stated as "x within δ". An explicit interval list, pre-registered with the rule "only adjacent measured
nodes, never extrapolated", leaves a cross-family, cross-rank common band of a single narrow interval,
**x ∈ [0.78, 0.886]**. In the frequency direction the same rule yields an **empty** set: the training
frequency grid contains gaps of 1.34/1.59 MHz (7.07→8.41→10) and 2.68 MHz (14.14→16.82) across which a
whole frequency plane cannot be reconstructed to 2 %. (The lowest frequency, 5 MHz, is a grid boundary,
so its leave-one-out value of ≈1400 % is an extrapolation artefact and is not read as an interpolation
error.) The three held-out frequencies (6.6, 9.2, 15.5 MHz) all sit in **small** gaps, which is why they
are reconstructible while the large-gap nodes are not.

**What was not done.** No domain-densification campaign was run (an estimate based on the measured
smoothness scale puts a full-domain 2 % maximum at roughly 300–400 x-nodes, ≈20–60 h, and this is an
extrapolation, not a measurement), and no operator-learning architecture was trained.
"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit("[FAIL] 锚点 %s 命中 %d 次（要求恰好 1 次）：%r" % (label, n, old[:60]))
    return text.replace(old, new)


def words(md: str) -> int:
    """正文词数：去掉标题/表格/代码/引用块后的英文词数（与 v6 同口径的近似）。"""
    body = md.split("## References")[0]
    body = re.sub(r"(?m)^\s*\|.*$", " ", body)
    body = re.sub(r"(?m)^#{1,6} .*$", " ", body)
    body = re.sub(r"[`*_>#]", " ", body)
    return len([w for w in re.findall(r"[A-Za-z][A-Za-z'’\-\./0-9]*", body)])


def main() -> int:
    t0 = time.time()
    v6 = V6.read_text(encoding="utf-8")
    v6_sha = hashlib.sha256(v6.encode("utf-8")).hexdigest()
    s6 = S6.read_text(encoding="utf-8")
    s6_sha = hashlib.sha256(s6.encode("utf-8")).hexdigest()

    v7 = v6
    for i, (old, new) in enumerate(REPL):
        v7 = replace_once(v7, old, new, "REPL[%d]" % i)

    # **先写盘**，再做"从磁盘回读"的自检（否则回读到的是旧文件）。
    # ⚠️ **必须写字节**：`Path.write_text` 在 Windows 上把 `\n` 翻成 `\r\n`，
    #    而 v6 与旧补充材料**全是 LF** ⇒ 用 write_text 会让 v6→v7 的**每一行 diff 都变**，
    #    且报告里按 LF 算的 sha 与磁盘不符（**实测踩过**，见 INDEX §211）。
    v7_bytes = v7.encode("utf-8")
    V7.write_bytes(v7_bytes)

    # 自检（**真实的**，且**从磁盘回读**，不是对内存对象复述构造过程）：
    #   ① 每处 `new` 在写出的 v7 里**恰好出现 1 次**；
    #   ② 把每个 `new` 反向换回 `old` ⇒ 必须**逐字节还原 v6**（证明除这 6 处外一字未动）；
    #   ③ 若干"本轮不该动"的句子原样仍在。
    # 说明：difflib 的字符级差异块数会**高估**（新旧文共享片段会把一处替换拆成多块），
    #       故只作**信息量**输出，**不作断言**。
    disk = V7.read_text(encoding="utf-8")
    disk_bytes = V7.read_bytes()
    if b"\r\n" in disk_bytes:
        raise SystemExit("[FAIL] v7 出现 CRLF —— 与 v6（纯 LF）不一致，diff 会全行变")
    if v6.count("\r\n") or s6.count("\r\n"):
        raise SystemExit("[FAIL] 源件含 CRLF（预期纯 LF）")
    for i, (old, new) in enumerate(REPL):
        c = disk.count(new)
        if c != 1:
            raise SystemExit("[FAIL] 回读后 REPL[%d] 的新文出现 %d 次（要求 1 次）" % (i, c))
    back = disk
    for old, new in REPL:
        back = back.replace(new, old)
    if back != v6:
        raise SystemExit("[FAIL] 往返校验失败：反向替换后与 v6 不一致")
    sm = difflib.SequenceMatcher(None, v6, disk, autojunk=False)
    n_diff_blocks = len(sm.get_matching_blocks()) - 1
    UNTOUCHED = [
        "**Field-level thresholds stay closed.**",
        "| fixed systematic offset | a second geometry at the same 20 MHz gives",
        "surrogate modelling is useless",
        "No engineering absolute value is quoted anywhere in this paper.",
        "A group of 405 combinations stays unexpanded.",
    ]
    for u in UNTOUCHED:
        if u not in disk:
            raise SystemExit("[FAIL] 本应保持不变的句子在 v7 中丢失：%r" % u[:60])
    print("自检：回读 6/6 新文各 1 次；**往返校验通过（反向替换逐字节还原 v6）**；"
          "5 句不该动的原样仍在")
    print("  （difflib 字符级差异块数 = %d，仅信息量、不作断言：新旧文共享片段会把一处替换拆成多块）"
          % n_diff_blocks)
    # 段数（空行分段）变化 = 新增 2 段
    if len(v6.split("\n\n")) + 2 != len(v7.split("\n\n")):
        print("[warn] 段数变化 = %d（预期 +2）" % (len(v7.split("\n\n")) - len(v6.split("\n\n"))))

    s7 = s6.rstrip("\n") + "\n" + S9 + S10
    S7.write_bytes(s7.encode("utf-8"))          # 同 v7：写字节，保持 **LF**

    w6, w7 = words(v6), words(v7)
    s7_bytes = S7.read_bytes()
    rep = {"kind": "dac2027_en_v7_generation", "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "source": V6.name, "source_sha256": v6_sha, "source_bytes": len(v6.encode("utf-8")),
           # ⚠️ 一律按**磁盘字节**记（不是内存字符串）—— 否则 EOL 一翻，哈希就对不上（实测踩过）
           "output": V7.name, "output_sha256": hashlib.sha256(disk_bytes).hexdigest(),
           "output_bytes": len(disk_bytes), "output_eol": "LF",
           "supplement_source": S6.name, "supplement_source_sha256": s6_sha,
           "supplement_output": S7.name,
           "supplement_output_sha256": hashlib.sha256(s7_bytes).hexdigest(),
           "supplement_output_bytes": len(s7_bytes), "supplement_output_eol": "LF",
           "n_replacements": len(REPL), "all_anchors_hit_once": True,
           "body_words_v6": w6, "body_words_v7": w7, "body_words_delta": w7 - w6,
           "page_limit_note": "DAC 限 **6 页 + 1 页仅参考文献**；本机**无 TeX**，页数**未编译验证**。"
                              "若编译溢出，**指定删减顺序**：① §6.4 末段（场级 ROM）② §6.5 末段（两口径）"
                              "③ §6.5 末句的非独立性说明。",
           "elapsed_s": round(time.time() - t0, 2)}
    if hashlib.sha256(V7.read_bytes()).hexdigest() != rep["output_sha256"]:
        raise SystemExit("[FAIL] 报告里的 output_sha256 与磁盘不一致")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "V7_GENERATION_REPORT.json").write_bytes(
        (json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    gen = time.strftime("%Y-%m-%d")
    V7P.write_bytes(f"""# v7 出处说明（DAC 2027 英文稿）

- 生成：{gen}；由 **v6**（`{V6.name}`，sha256 `{v6_sha[:24]}`，{len(v6.encode("utf-8"))} B）
  经 **{len(REPL)} 处字面替换**生成；每处在 v6 中**恰好命中 1 次**。
- 产物：`{V7.name}`（sha256 `{rep["output_sha256"][:24]}`，{rep["output_bytes"]} B，**LF**）；
  补充材料：`{S7.name}`（在 §S1–§S8 之后新增 **§S9** 净通量口径与逐面取向、**§S10** 场级 ROM）。
- 正文词数：v6 **{w6}** → v7 **{w7}**（{w7 - w6:+d}）。
- **生成自检**：从磁盘回读 ⇒ 6/6 新文各出现 1 次；**把每个新文反向替换回旧文后可逐字节还原 v6**
  （证明除这 6 处外一字未动）；5 句"本轮不该动"的句子原样仍在。

## 改动逐条（每处都指向可核产物）

| # | 位置 | 改动 | 出处 |
|---|---|---|---|
| A | §6.4 首段 | S3 计数 `7 通过 / 2 失败` → **`8 通过 / 1 失败`**（更正口径经人 2026-10-12 确认） | INDEX §182/§192；`p5_cost/S3_GATE_CORRECTED_CALIBER.*` |
| B | §6.5 末 | 新增一段：**电—声口径**（≈ −3.8 %，电路不完整）与**声学侧净通量**（O(h²) 收敛，1.770575 %→0.953987 %）**分开写** | INDEX §202/§203/§205；`NETFLUX_REFINEMENT.json` |
| C | §6.5 诊断表第 4 行 | 「两个不相交面」→ **唯一可证闭合面的两片互补剖分、取向逐面实测** | INDEX §198/§202；`P5_4_ENERGY_SURFACE_CHECK.json`、`P5_4_NORMAL_ORIENTATION_CHECK.json` |
| D | §6.4 S4 段 | 「post-hoc caliber」→ **跑前冻结**；并补明**重跑用同一批既有解、不是独立确认、对象继承事后裁定** | INDEX §206/§207；`s4-prereg-20261012/` |
| E | §6.4 末 | 新增一段：场级 ROM 的**定量**结论（最差格恒为 `x=0.63, f=9.2`；对表示/秩/密度不敏感） | INDEX §189–§194、§197 |

## 页数与删减顺序（**必须先说清**）

DAC 限 **6 页 + 1 页仅参考文献**；本机**无 TeX**，页数**未编译验证**。若编译溢出，
**指定删减顺序**：① §6.4 末段（E）② §6.5 末段（B）③ §6.5 末句的非独立性说明（D2）——
**A/C/D1 三处不得删**（它们是正确性更正）。

## 不主张

- **不动任何既有数字**（除 A 的计数更正）；**未改任何图表**；
- **不主张**页数已满足；**不主张** S1/S3 有任何可放行结论；**不主张**本版已可提交（仍缺 TeX 页数、
  补充材料规则、图与 caption、LLM 标识）；
- 不提升任何状态；`release_allowed` 仍 `false`；`solver_spec` 仍 `draft`。
""".encode("utf-8"))

    print("v6 %d B（sha %s）→ v7 %d B（sha %s）" % (len(v6.encode("utf-8")), v6_sha[:16],
                                                  rep["output_bytes"], rep["output_sha256"][:16]))
    print("替换 %d 处，全部恰好命中 1 次" % len(REPL))
    print("正文词数 v6 %d → v7 %d（%+d）" % (w6, w7, w7 - w6))
    print("补充材料 %d B → %d B（新增 §S9/§S10）" % (len(s6.encode("utf-8")),
                                                len(s7.encode("utf-8"))))
    print("写出: %s | %s | %s | V7_GENERATION_REPORT.json" % (V7.name, V7P.name, S7.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
