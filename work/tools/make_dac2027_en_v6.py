# -*- coding: utf-8 -*-
"""v6：由 v5 **生成压缩投稿版**（正文 6,081 → ~4,400 词），明细移入补充材料。

方法（**逐节整段替换 + 逐句微调**，每处断言命中）：
  * §6.4 / §6.5 / §6.6 整节替换为压缩版（这三节共 2,826 词 → ~1,430）；
  * §1/§2/§3/§5/§7/§8 用**逐句**替换做小幅精简（每处命中 1 次）；
  * 正文新增一句指向补充材料 `docs/PAPER_DAC2027_EN_SUPPLEMENT_20261011.md`；
  * **不动任何数字**：压缩只删解释性文字，所有 headline 数字保留在正文。

产物：`docs/PAPER_DAC2027_EN_v6_20261011.md` + `docs/PAPER_DAC2027_EN_v6_PROVENANCE.md`
      + `work/runs/eda64-20261010/n5_stage3/V6_GENERATION_REPORT.json`
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
V5 = REPO / "docs/PAPER_DAC2027_EN_v5_20261011.md"
V6 = REPO / "docs/PAPER_DAC2027_EN_v6_20261011.md"
V5P = REPO / "docs/PAPER_DAC2027_EN_v5_PROVENANCE.md"
V6P = REPO / "docs/PAPER_DAC2027_EN_v6_PROVENANCE.md"
OUT = REPO / "work/runs/eda64-20261010/n5_stage3"

# ---------------------------------------------------------------- 压缩后的整节
S64 = """### 6.4 Physics-consistency gates

**S3 fails, and one of its two failures is a caliber artefact.** On the gate design point the
registered S3 report gives 7 passes, 2 failures and 0 inconclusive outcomes. The current-conservation
check compared a lumped circuit current with a field flux across an unclosed circuit using
post-processing normals; re-evaluated as a closed-surface flux with the physics normal it gives
6.469e-04…1.032e-03 on one carrier and 8.168e-04 on a second, inside the 0.5 % criterion. The
energy-closure check is *not* an artefact: the electrical input power is 6.177 % below the radiated
acoustic power against 0.5 %, and §6.5 shows that this survives refinement.

**S1/S2/S5 at the local level, and S4 under a declared scope.** On five held-out continuous values at
20 MHz a shape-preserving local model meets all three thresholds — key region **0.69999 %** (whole
domain 1.09097 %) for *N₁* = 4 and **0.95735 %** (1.13266 %) for *N₁* = 7, with an engineering maximum
of **0.739 %** — while a raw-POD variant fails the key region at 2.126 %; the coverage protocol
promoted by the human reviewer on 2026-10-10 yields 0.9259 / 0.9383. On the main mesh-sensitivity axis
(nine levels, 72 ordered pairs) the key region gives **0.6753 % < 2 %** and the whole-domain reference
1.5504 %; Richardson extrapolations under three caliper choices give 1.3446 %, 1.4300 % and 1.4963 %.
S4 therefore passes **only** on the levels tested, under a post-hoc caliber, and must not be read as
mesh independence. Strict convergence remains unestablished: the recorded strict check fails at
2.235 %, the finest-pair caliber the reviewer later approved passes, and both readings are reported.
No engineering absolute value is quoted anywhere in this paper.

**Field-level thresholds stay closed.** After correcting an object mismatch the field-level gate is
**0/7** folds at the key-region 2 % object, **0/7** at the 3 % engineering object and **2/7** at the
global 5 % object; two models have bit-identical maxima but different fold-pass counts and the
authoritative artifact names the less flattering one. A group of 405 combinations stays unexpanded.
Per-check tables, the ladder history and the full caveat list are in §S2–§S5."""

S65 = """### 6.5 Diagnosing the energy-closure residual

We probed S3's energy item directly, entirely by zero-solve post-processing on already-solved models
(full seven-row probe table in §S6).

| candidate cause | measurement | verdict |
|---|---|---|
| port-voltage convention | drive −1.000000 V, ground 0, floating terminal ≤ 7.7 µV; including it changes `P_in` by +0.053 % | refuted |
| current post-expression | `∫es.JZ dA ≡ jω·∫es.Dz dA` on all four electrode sets, to all printed digits | refuted |
| plane-wave acoustic power | the model's `Ptot` equals the exact flux `Im(K)/(2ωρ)` at all six frequencies | refuted |
| integration surface | two disjoint surfaces agree to 1.8 %, but **both exceed** the electrical input (3.996822e-06 W and 3.924776e-06 W versus 3.734359e-06 W) | refuted |
| fixed systematic offset | a second geometry at the same 20 MHz gives +1.60 % / −0.34 % instead of −4.12 % / −5.82 %; within one geometry the sign flips across 5–35 MHz | refuted |
| unconverged discretisation | solid-side ×1 → ×0.75 → ×0.5: −4.852 % → −4.384 % → **−4.121 %** (decrement ratio 0.562 ⇒ limit ≈ **−3.8 %**); acoustic mesh changes it by 0.0011 pp | refuted |

The calibrated statement is therefore: **at this design point** the electrical input power is about
4.4 % below the acoustic flux, this is a genuine discrete non-closure rather than a post-processing
mistake, and it **does not vanish with refinement** — the extrapolated limit, ≈ −3.8 %, is roughly
eight times the 0.5 % criterion. The same caliber on a second, independently meshed carrier reproduces
the shortfall (−5.82 % and −4.12 % versus −6.57 % and −4.85 %) with the three powers agreeing between
carriers to within 0.81 %; that agreement is itself informative, since the second carrier's powers match
the ×0.5 solid-side refinement to 1.1e-10 relative. The residual is design-point- and
frequency-dependent (it changes sign), so a single figure such as "≈4.4 %" is valid for the reported
design point only and must never be presented as a property of the method. Three calibers travel with
every such statement: `P_in`-based energy statements are meaningful only above ≈2 MHz; post-processing
normals must not be used for closed-surface flux judges (they give ≈0.999 where the physics normal gives
8.2e-04); and because the sign depends on the integration surface at some frequencies, the surface
caliber must be named each time."""

S66 = """### 6.6 Closed-loop design-space exploration

**Closed loop (pre-registered, completed).** Four arms — random, greedy, Gaussian-process
expected improvement, and the same with an applicability gate — shared a pool of 1080 candidate designs
and five initial points under a fixed budget of 105 single-frequency evaluations of radiated acoustic
power per volt² at 20 MHz. The objective spans 574× across the 93 designs evaluated, the campaign
finished in 123 minutes with a 2 % failure rate, and the pre-registered primary endpoint is decisive:

| arm | calls | best objective (W/V²) | simple regret | best at k = 5 | top-10 % hit rate |
|---|---:|---:|---:|---:|---:|
| random (5 seeds × 5) | 25 | 2.1756e-05 | 18.8 % | 8.409e-06 (median) | 0.0 % |
| greedy | 25 | 2.2807e-05 | 14.9 % | 4.863e-06 | 4.0 % |
| GP + expected improvement | 25 | **2.6786e-05** | **0.00 %** | **2.640e-05** | **24.0 %** |
| GP + EI, gated | 23 | 2.6126e-05 | 2.46 % | 2.510e-05 | 17.4 % |

After five evaluations the GP arms exceed every one of the five random seeds (quantile 1.00) and both
beat the random arm's best value over its entire 25-call budget. A post-hoc replay shows that **24 of
the 25 ungated proposals would have landed outside the corpus-covered domain** (96 %), so abstention is
load-bearing rather than cosmetic. The claim is bounded: the oracle is single-frequency, so this is a
protocol-efficiency comparison and not a bandwidth result, and only the random arm has seed replication.

**Multi-frequency ROM (pre-registered, completed).** The third experiment asks whether single-frequency
evidence extends along the frequency axis; it fails, and the failure is diagnosed. The registered grid
placed eleven of thirteen frequencies inside 11.1–12.9 MHz and **none** between 6.3–11.1 or
12.9–18.0 MHz, while a coefficient-shape diagnosis showed the resonance phase swinging 2.8 rad across
the first of those empty intervals. On the nine cross cells per family the registered ROM's key-region
error is **27.76 %** (*N₁* = 4) and **32.19 %** (*N₁* = 7) against 2 %, with whole-domain values
27.77 % / 31.68 % against 5 %.

*Disclosure.* The first run of this analysis covered **3 of those 9 cells**: the registration stored the
held-out frequencies as `[11.399999999999999, 12, 12.600000000000001]` while the field dictionary is
keyed by exact values, and an exact-equality cell filter silently dropped the columns `11.4` and
`12.6`; the first-reported figures (27.1 % / 30.9 %) were therefore computed on `f = 12.0` alone. The
defect is in the analysis script, not in the data or the model, and it is disclosed because the earlier
numbers appear in this paper's revision history; §S1 gives the corrected per-variant values and the
affected artifacts are retained unchanged.

Raising the basis order from the registered k = 4 to the full rank k = 120 drives the training
reconstruction error to 0.000 % while the cross-cell error stays at **27.64 % / 31.79 %**, so the
reduced basis is *not* the limiting factor — the corrected numbers make that conclusion stronger.
A pre-registered re-design then changed **only** the frequency axis (a quarter-octave grid covering both
flanks, with the three held-out frequencies placed **on the flanks**; 360 further solves, zero failures,
102 minutes). No reconstruction reaches the criterion: the best is `cubic` at **26.46 %** / 44.84 %,
and the single-pole resonance parameterisation fails **on its own training data** (training control
68.56 % / 76.13 %, per-mode fit residual 27.22 % / 23.98 %). Two things follow. First, frequency
sampling was *not* the binding constraint, so densifying the axis the diagnosis identified does not
rescue this ROM. Second, a single-pole Lorentzian plus a complex baseline cannot represent these
coefficient curves at all. The pre-registered fallback therefore applies: change the *representation*
rather than the threshold — a multi-pole or complex-pole (vector-fitting) form, an explicit per-mode
propagation phase, or an operator-learning surrogate — and S5 is deliberately left unevaluated because
its (*x*, *f*) protocol has not been pre-registered."""

# ---------------------------------------------------------------- 逐句微调
TRIMS = [
    # §1 引言：三处收紧（删解释性从句，不动任何数字/主张）
    ("The physics is therefore well understood, but\nsweeping several continuous and discrete parameters with a full multi-physics model remains\nexpensive.",
     "The physics is well understood, but sweeping continuous and discrete parameters with a full\nmulti-physics model remains expensive."),
    ("Two-stage surrogates [9] and comparative surrogate studies [10]\nlikewise target sample efficiency. The shared objective is not a small average prediction error but\nfinding feasible, high-quality designs under a fixed simulation budget.",
     "Two-stage surrogates [9] and comparative studies [10] likewise target sample efficiency. The shared\nobjective is not a small average error but finding high-quality designs under a fixed budget."),
    ("The present evidence supports trend screening and scheduling of high-fidelity re-checks. It does not\nsupport replacing the FE solver, and it does not support any engineering absolute value.",
     "The evidence supports trend screening and scheduling of high-fidelity re-checks; it does not support\nreplacing the FE solver or quoting any engineering absolute value."),
    # §3：状态列表收紧
    ("A channel value is *defined* for fitting only when the value exists,\nis positive, and its state condition is satisfied; ratios in this paper always report the count of\nrows that are defined in this sense, never a flag-based denominator.",
     "A channel value is *defined* for fitting only when it exists, is positive, and its state condition\nholds; ratios always report that count, never a flag-based denominator."),
    # §5：实验设置收紧
    ("The mesh used\nfor all physics-gate numbers below is the pre-registered caliber: a boundary mesh on the\nsolid/electrode side plus a tetrahedral acoustic mesh of `lamda/5` referenced to\n`fmax = 35 MHz`, so that the mesh does **not** change with the solved frequency — a requirement for\nany limit or comparison argument.",
     "All physics-gate numbers below use the pre-registered caliber: a boundary mesh on the solid/electrode\nside plus a tetrahedral acoustic mesh of `lamda/5` referenced to `fmax = 35 MHz`, so the mesh does\n**not** change with the solved frequency."),
    # §6.3：结论段收紧
    ("These numbers were re-derived by an independent implementation that does not import the main\nevaluation code: the artifact manifest (12 files) verifies hash-for-hash, the training/test key sets\nare disjoint for all five seeds, and the persistence median 0.007726751204325416 and its\ndefined-row count (416) reproduce exactly.",
     "An independent implementation that does not import the evaluation code re-derived these numbers: the\nmanifest (12 files) verifies hash-for-hash, the training/test key sets are disjoint for all five seeds,\nand the persistence median 0.007726751204325416 and its defined-row count (416) reproduce exactly."),
    # §7：讨论收紧两处
    ("**Abstention is a feature with a price.** Refusing out-of-domain queries prevents silent\nextrapolation, but it also removes coverage: in the ablation, disabling abstention raises coverage to\n1 while the fallback-filled subset frequently has *lower* median error than the abstaining arm,\ni.e. \"abstention blocks the hard cases, therefore it is more accurate\" does not follow. Any gate must\nbe reported together with the coverage it costs.",
     "**Abstention is a feature with a price.** Refusing out-of-domain queries prevents silent extrapolation\nbut removes coverage: disabling abstention raises coverage to 1 while the fallback-filled subset often\nhas *lower* median error, so \"abstention blocks the hard cases, therefore it is more accurate\" does not\nfollow. Any gate must be reported with the coverage it costs."),
    ("**Gates are results.** Three of the four physics checks reported here are negative or\nnarrowly-scoped. Reporting them as results rather than as internal diagnostics is what makes the\nrefusal mechanism auditable — and it is also what forbids the engineering claims that a\nsmaller-error surrogate would tempt one to make.",
     "**Gates are results.** Three of the four physics checks here are negative or narrowly scoped.\nReporting them as results rather than as diagnostics is what makes the refusal mechanism auditable —\nand what forbids the engineering claims a smaller-error surrogate would tempt one to make."),
    # §8：结论段收紧
    ("PeakGuard couples resonance-semantic labelling, a layered mixed-input surrogate, calibrated\nintervals, and fail-closed abstention for PMUT design-space exploration. On the present corpus its\nhonest summary is: label validity and gate status, not prediction accuracy, dominate usefulness; no\ntested method beats persistence on the two formal targets; the physics-consistency gate fails on\nenergy closure, and that failure survives every caliber correction we could test.",
     "PeakGuard couples resonance-semantic labelling, a layered mixed-input surrogate, calibrated intervals\nand fail-closed abstention. On this corpus the honest summary is: label validity and gate status, not\nprediction accuracy, dominate usefulness; no tested method beats persistence on the two formal targets;\nand the physics-consistency gate fails on energy closure, a failure that survives every caliber\ncorrection and every refinement we could test."),
    ("Experimental\nanchoring, a validated field-level solver, and a frequency-axis reduced model that meets the\nkey-region criterion remain future work; the fixed-budget closed loop and the first multi-frequency\nprotocol are reported here, the latter as a diagnosed failure.",
     "Experimental anchoring, a validated field-level solver, and a frequency-axis reduced model that meets\nthe key-region criterion remain future work; the closed loop and the first multi-frequency protocol are\nreported here, the latter as a diagnosed failure."),
]


def wc(s: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-\./%]*", s))


def replace_section(text: str, h_start: str, h_next: str, new: str, eid: str, rep: dict) -> str:
    i = text.index(h_start)
    j = text.index(h_next, i)
    old = text[i:j]
    text = text[:i] + new + "\n\n" + text[j:]
    rep["edits"].append({"id": eid, "old_words": wc(old), "new_words": wc(new),
                         "saved": wc(old) - wc(new)})
    return text


def main() -> int:
    DRY = "--dry" in sys.argv
    text = V5.read_text(encoding="utf-8")
    rep: dict = {"kind": "v6_compression", "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                 "source": str(V5.relative_to(REPO)),
                 "source_sha256": hashlib.sha256(V5.read_bytes()).hexdigest(),
                 "body_words_v5": wc(text[:text.find("## Content Generated by AI")]), "edits": []}

    # 指向补充材料的一句（放在 §5 末尾之后、§6 之前）
    anchor = "## 6. Results"
    assert text.count(anchor) == 1
    text = text.replace(anchor,
                        "*Supplementary material (§S1–§S8) carries the per-cell, per-variant and historical\n"
                        "detail; every headline number appears in this body.*\n\n" + anchor)
    rep["edits"].append({"id": "T0_supplement_pointer", "hits": 1})

    text = replace_section(text, "### 6.4 Physics-consistency gates", "### 6.5 ", S64, "T1_s64", rep)
    text = replace_section(text, "### 6.5 Diagnosing", "### 6.6 ", S65, "T2_s65", rep)
    text = replace_section(text, "### 6.6 Closed-loop", "## 7. Discussion", S66, "T3_s66", rep)

    for old, new in TRIMS:
        got = text.count(old)
        if got != 1:
            raise SystemExit("逐句微调命中 %d 次（期望 1）：%r" % (got, old[:70]))
        text = text.replace(old, new)
        rep["edits"].append({"id": "T4_trim", "old_words": wc(old), "new_words": wc(new),
                             "saved": wc(old) - wc(new)})

    body = text[:text.find("## Content Generated by AI")]
    rep["body_words_v6"] = wc(body)
    rep["saved_total"] = rep["body_words_v5"] - rep["body_words_v6"]
    rep["target_body_words"] = 4500
    if DRY:
        print("== DRY：正文 %d → %d 词（省 %d）" % (rep["body_words_v5"], rep["body_words_v6"],
                                                rep["saved_total"]))
        for e in rep["edits"]:
            print("   %-22s %s" % (e["id"], e.get("saved", e.get("hits"))))
        return 0

    V6.write_text(text, encoding="utf-8", newline="\n")
    rep["outputs"] = {str(V6.relative_to(REPO)): {
        "lines": text.count("\n") + 1, "bytes": V6.stat().st_size,
        "sha256": hashlib.sha256(V6.read_bytes()).hexdigest(),
        "words_total": wc(text)}}
    prov = V5P.read_text(encoding="utf-8")
    prov = prov.replace("英文稿 **v5** 的数字溯源", "英文稿 **v6** 的数字溯源")
    prov = prov.replace("- 投稿候选：`docs/PAPER_DAC2027_EN_v5_20261011.md`（v5 由 v4 生成；",
                        "- 投稿候选：`docs/PAPER_DAC2027_EN_v6_20261011.md`（v6 由 v5 压缩生成；")
    prov = prov.rstrip() + ("\n\n## F. v6 压缩说明\n\n"
                            "- v6 = v5 的**压缩投稿版**：正文 %d → **%d** 词；§6.4/§6.5/§6.6 整节重写，"
                            "§1/§3/§5/§6.3/§7/§8 逐句微调；**未增删任何数字或主张**。\n"
                            "- 明细（逐格/逐变体表、S3 九项表、S4 阶梯、L1 历史、场级折数、能量探针七行表、"
                            "闭环全表、带宽口径）移入 `docs/PAPER_DAC2027_EN_SUPPLEMENT_20261011.md`（§S1–§S8）。\n"
                            % (rep["body_words_v5"], rep["body_words_v6"]))
    V6P.write_text(prov, encoding="utf-8", newline="\n")
    rep["outputs"][str(V6P.relative_to(REPO))] = {
        "bytes": V6P.stat().st_size, "sha256": hashlib.sha256(V6P.read_bytes()).hexdigest()}
    (OUT / "V6_GENERATION_REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
    print("== 正文 %d → %d 词（省 %d，目标 ≤%d）"
          % (rep["body_words_v5"], rep["body_words_v6"], rep["saved_total"], rep["target_body_words"]))
    for e in rep["edits"]:
        print("   %-22s %s" % (e["id"], e.get("saved", e.get("hits"))))
    for k, v in rep["outputs"].items():
        print("== 写出 %s %s" % (k, json.dumps(v, ensure_ascii=False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
