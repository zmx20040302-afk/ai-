# -*- coding: utf-8 -*-
"""v17 = **M5 重定位**：由 v16 生成，把论文从「一个代理流程」改写为「**AI1.1 的可靠性 benchmark**」。

改动集中在标题 / 摘要定调 / 贡献表（C→B 并补基准语义）/ 引言一句泛化 / 第 4 节标题 /
补充材料新增 **§S12 任务规格**（七项任务 × 指标 × 拒答规则 × 证据位置）。
**不新增技术结论**，只重述既有证据与已发布的包。
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
V16 = REPO / "docs/PAPER_DAC2027_EN_v16_20261013.md"
V17 = REPO / "docs/PAPER_DAC2027_EN_v17_20261013.md"
V17P = REPO / "docs/PAPER_DAC2027_EN_v17_PROVENANCE.md"
SUPC = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013c.md"
SUPD = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013d.md"
OUT = REPO / "work/runs/eda64-20261010/n5_stage3"

R = []
R.append(("A_title",
          "# PeakGuard: An Abstention-Aware Surrogate Flow for Reliable Multi-Physics PMUT Design-Space Exploration",
          "# PeakGuard-Bench: A Reliability Benchmark for Surrogate-Assisted Multiphysics Design Automation"))
R.append(("B_abstract_open",
          "Design-space exploration for piezoelectric micromachined ultrasonic transducers is expensive and\n"
          "vulnerable to labels that are numerically present but physically incomparable: resonance order can\n"
          "switch, and a −3 dB bandwidth is undefined when a crossing leaves the scan window.\n"
          "We present **PeakGuard**, an abstention-aware surrogate flow coupling resonance-semantic labelling,\n"
          "mixed continuous–discrete modelling, calibrated intervals and fail-closed validity checks, with\n"
          "evidence reported per corpus, never pooled.",
          "How should a surrogate model of a resonant multiphysics design task be evaluated? We answer with a\n"
          "frozen, released benchmark built on a piezoelectric micromachined ultrasonic transducer (PMUT)\n"
          "parameter sweep, in which labels are numerically present but often physically incomparable: the\n"
          "resonance order can switch, and a −3 dB bandwidth is undefined once a crossing leaves the scan\n"
          "window. **PeakGuard-Bench** couples resonance-semantic labelling, mixed continuous–discrete\n"
          "modelling, calibrated intervals and fail-closed abstention into seven specified evaluation tasks,\n"
          "and reports every result per corpus, never pooled."))
R.append(("C_abstract_close",
          "PeakGuard is a screening and scheduling layer, not a\nsolver replacement.",
          "The corpus, the frozen split and the reference implementation are released as a self-contained\n"
          "package; the flow is a screening and scheduling layer, not a solver replacement."))
R.append(("D_contrib_lead", "This paper contributes:",
          "This paper contributes a **benchmark** rather than a new predictor:"))
R.append(("E_B1",
          "1. **C1 — a semantically consistent first-peak labelling protocol.** Complete peak, no interior peak,",
          "1. **B1 — a frozen corpus and a semantically consistent first-peak labelling protocol.** The corpus is\n"
          "   two scan grids (2,005 rows) plus a frozen 250-row batch. Complete peak, no interior peak,"))
R.append(("F_B2",
          "2. **C2 — a layered surrogate for mixed continuous–discrete inputs with fail-closed abstention**",
          "2. **B2 — a layered reference implementation for mixed continuous–discrete inputs, with fail-closed\n"
          "   abstention**"))
R.append(("G_B3",
          "3. **C3 — an evaluation protocol that names what fails.** We audit the bandwidth caliber, check",
          "3. **B3 — a task specification and an evaluation protocol that names what fails.** Seven tasks, from\n"
          "   peak identity to closed-loop scheduling, are specified in §S12. We audit the bandwidth caliber, check"))
R.append(("H_B4",
          "4. **C4 — physics-consistency gates reported as experimental results, including the negative ones**:",
          "4. **B4 — physics-consistency gates reported as experimental results, including the negative ones**:"))
R.append(("I_sec4_title", "## 4. PeakGuard",
          "## 4. The benchmark and its reference implementation"))
R.append(("J_41_ref", "**4.1 Semantic labelling (C1).**", "**4.1 Semantic labelling (B1).**"))
R.append(("K_42_ref", "**4.2 Layered surrogate (C2).**", "**4.2 Layered surrogate (B2).**"))
R.append(("L_intro_generality",
          "The physics is well understood, but sweeping continuous and discrete parameters with a full\n"
          "multi-physics model remains expensive.",
          "The physics is well understood, but sweeping continuous and discrete parameters with a full\n"
          "multi-physics model remains expensive. The evaluation questions this raises — which labels are\n"
          "comparable, which splits leak, whether a model beats a strong baseline, when it should refuse —\n"
          "recur wherever a resonant design space is swept with a full-wave solver, not only in PMUTs."))

S12 = """

## S12. Benchmark task specification

The benchmark is seven tasks over the frozen corpus of §4.1 and the split of §S11. Each task names its
inputs, its primary metric, its refusal rule and where its evidence appears. Every metric is reported per
batch and per channel; nothing is pooled and no weighted total is computed.

| # | task | inputs | primary metric | refusal rule | evidence |
|---|---|---|---|---|---|
| T1 | first-peak identity | (x, N1, N2) | accuracy over the four peak states, per state | abstain when the state is right-censored or truncated | §6.1 |
| T2 | bandwidth closure | (x, N1, N2) | accuracy of `bandwidth_closed`, with the caliber named | abstain when the extraction caliber is undefined | §6.1, §6.2 |
| T3 | conditional regression on the two formal targets | (x, N1, N2) | median relative error with the count of defined rows, plus `lift_paired` against persistence | abstain outside the measured grid | §6.3 |
| T4 | split comparison | (x, N1, N2) with the frozen assignment | per-cell median-error ratio between two split rules, reported with the adjacent-step leakage fraction | not applicable (both arms are evaluated) | §S11 |
| T5 | refusal behaviour | a proposal set | accepted and refused counts with reasons, and the false-accept rate at three tolerances | refuse when the applicability test fails | §6.2, §6.6 |
| T6 | cross-batch transfer | train batch → test batch | median relative error, its difference from the within-batch reference, and the acceptance fraction | refuse outside the training batch's measured range | §S11 |
| T7 | closed-loop scheduling | a budget of oracle calls | simple regret at k = 5 calls, and the fraction of un-gated proposals outside the supported domain | refuse un-gated proposals | §6.6 |

**What the released package covers.** The package of §6.3 ships the corpus, the frozen split, the
thresholds and a reference implementation that reproduces the regression and ablation parts of T3 and the
refusal counting of T5 by one command; T4 is reproduced by the counterfactual split described in §S11,
whose generator recipe is fixed and recorded; the full per-arm table behind T7 is in §S7. Nothing in the
package asserts an engineering absolute value, and no threshold in it was adjusted after any run.

**What is deliberately not claimed.** That these seven tasks exhaust the failure modes of surrogate
modelling for resonant design; that the corpus is representative of PMUT design, of RF filters or of
analog circuits at large; or that any task's metric is comparable across batches. The generality claim is
about the *questions*, not about the numbers: they recur wherever a resonant design space is swept with a
full-wave solver.
"""


def main() -> int:
    src = V16.read_text(encoding="utf-8")
    sup = SUPC.read_text(encoding="utf-8")
    for nm, t in (("v16", src), ("supc", sup)):
        if "\r\n" in t:
            raise SystemExit("[FAIL] %s 含 CRLF" % nm)
    sha16 = hashlib.sha256(V16.read_bytes()).hexdigest()
    sha_c = hashlib.sha256(SUPC.read_bytes()).hexdigest()

    body = src
    for label, old, new in R:
        n = body.count(old)
        if n != 1:
            raise SystemExit("[FAIL] %s 命中 %d 次（要求 1）" % (label, n))
        body = body.replace(old, new)
    sup_new = sup + S12

    V17.write_bytes(body.encode("utf-8"))
    SUPD.write_bytes(sup_new.encode("utf-8"))
    db, ds = V17.read_bytes(), SUPD.read_bytes()
    if b"\r\n" in db or b"\r\n" in ds:
        raise SystemExit("[FAIL] 输出出现 CRLF")
    dt, st = db.decode("utf-8"), ds.decode("utf-8")
    back = dt
    for _, old, new in R:
        back = back.replace(new, old)
    if back != src:
        raise SystemExit("[FAIL] 往返未逐字节还原 v16")
    if st[:len(sup)] != sup or st[len(sup):] != S12:
        raise SystemExit("[FAIL] 补充材料不是「原文 + §S12」")
    for must in ("# PeakGuard-Bench: A Reliability Benchmark",
                 "How should a surrogate model of a resonant multiphysics design task be evaluated?",
                 "seven specified evaluation tasks",
                 "contributes a **benchmark** rather than a new predictor",
                 "**B1 —", "**B2 —", "**B3 —", "**B4 —", "are specified in §S12",
                 "## 4. The benchmark and its reference implementation",
                 "(B1).", "(B2).", "not only in PMUTs"):
        if must not in dt:
            raise SystemExit("[FAIL] 正文缺必需项：%s" % must)
    if re.search(r"\*\*C[1-4] —", dt):
        raise SystemExit("[FAIL] 正文仍含旧贡献编号 C1–C4")
    for must in ("## S12. Benchmark task specification", "| T7 | closed-loop scheduling",
                 "What is deliberately not claimed."):
        if must not in st:
            raise SystemExit("[FAIL] 补充材料缺必需项：%s" % must)
    for pat in (r"work[/\\]runs", r"work/dist", r"docs/", r"\bsha256\b", r"[0-9a-f]{32,}", r"\bnode0\d\b",
                r"\bINDEX\b", r"peakguard-bench-v1"):
        if re.search(pat, dt) or re.search(pat, st):
            raise SystemExit("[FAIL] 双盲泄漏：%s" % pat)

    wc = lambda s: len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-\./%]*", s[:s.find("## Content Generated by AI")]))
    w16, w17 = wc(src), wc(dt)
    rep = {"kind": "dac2027_en_v17_generation_repositioned", "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "source": V16.name, "source_sha256": sha16, "source_bytes": len(V16.read_bytes()),
           "output": V17.name, "output_sha256": hashlib.sha256(db).hexdigest(),
           "output_bytes": len(db), "output_eol": "LF",
           "supplement_source": SUPC.name, "supplement_source_sha256": sha_c,
           "supplement_output": SUPD.name, "supplement_output_sha256": hashlib.sha256(ds).hexdigest(),
           "supplement_output_bytes": len(ds), "supplement_output_eol": "LF",
           "replacements": {label: 1 for label, _, _ in R},
           "body_words_v16": w16, "body_words_v17": w17, "body_words_delta": w17 - w16,
           "roundtrip_restores_v16": True, "supplement_is_v16_text_plus_S12": True,
           "double_blind_clean": True,
           "repositioning": ["title -> PeakGuard-Bench: a reliability benchmark",
                             "abstract opens with the evaluation question, not with the device",
                             "contributions relabelled B1-B4 as benchmark artifacts",
                             "section 4 retitled; intro claims generality about the questions, not the numbers",
                             "supplement: new S12 benchmark task specification (T1-T7)"],
           "not_added": "no new technical result, no threshold change, no new number"}
    if hashlib.sha256(V17.read_bytes()).hexdigest() != rep["output_sha256"]:
        raise SystemExit("[FAIL] 报告哈希与磁盘不一致")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "V17_GENERATION_REPORT.json").write_bytes(
        (json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    V17P.write_bytes(f"""# v17 出处说明（DAC 2027 英文稿）· **M5 重定位**

- 生成：{time.strftime("%Y-%m-%d")}；由 **v16**（`{V16.name}`，sha256 `{sha16[:24]}`，{len(V16.read_bytes())} B）
  经 **12 处**单命中字面替换生成。
- 产物：`{V17.name}`（sha256 `{rep["output_sha256"][:24]}`，{rep["output_bytes"]} B，**LF**）。
- 补充材料**另存新名**：`{SUPD.name}`（sha256 `{rep["supplement_output_sha256"][:24]}`）
  ＝ **v16 时代件原文 + §S12**；`{SUPC.name}`（`{sha_c[:24]}`）保留。
- 正文词数：v16 **{w16}** → v17 **{w17}**（{w17 - w16:+d}）。
- **自检**：从磁盘回读；反向替换**逐字节还原 v16**；补充材料按「原文 + §S12」逐字节校验；双盲扫描干净。

## 改了什么（**只重述，不新增**）

1. **标题**：`PeakGuard: An Abstention-Aware Surrogate Flow …` → **`PeakGuard-Bench: A Reliability Benchmark
   for Surrogate-Assisted Multiphysics Design Automation`**；
2. **摘要定调**：开头改为「**一个谐振多物理场设计任务的代理模型应该怎样被评测？**」，再给载体（PMUT）与
   「七个指定评测任务」；结尾补「语料、冻结拆分与参考实现以自包含包发布」；
3. **贡献表**：`C1–C4` → **`B1–B4`**，并把基准语义写进标题行（冻结语料 / 参考实现 / 任务规格 / 门禁即结果）；
   **B3** 指向新 §S12；
4. **引言**：加一句**关于「问题」而非「数字」**的泛化（哪些标签可比、哪种拆分泄漏、是否胜过强基线、何时该拒答）；
5. **第 4 节标题**：`## 4. PeakGuard` → **`## 4. The benchmark and its reference implementation`**；
6. **补充材料 §S12**：**七项任务规格表**（T1–T7：输入 / 主指标 / 拒答规则 / 证据位置）＋「包覆盖什么」
   ＋「**刻意不主张什么**」（七项任务并非穷尽失败模式、语料不代表性、跨批指标不可比）。

## 边界与不主张

- **不新增任何技术结论、不改任何阈值、不新增任何数字**；除上述 12 处与 §S12 外**一字未动**；
- 页数：正文 **{w17}** 词（比 v6 的 4,463 长 {w17 - 4463:+d}）；**本机无 TeX，页数未编译验证**（削减块见 INDEX §228）；
- 不主张改名本身能提升接收概率；不主张这些任务已被第三方按规格跑过。
""".encode("utf-8"))

    print("v16 %d B（sha %s）→ v17 %d B（sha %s）" % (len(V16.read_bytes()), sha16[:16],
                                                   len(db), rep["output_sha256"][:16]))
    print("补充材料：%s（%d B，sha %s）＝ v16 时代件 + §S12" % (SUPD.name, len(ds), rep["supplement_output_sha256"][:16]))
    print("正文词数 v16 %d → v17 %d（%+d）；12 处替换各命中 1 次" % (w16, w17, w17 - w16))
    print("自检：往返还原 v16 ✓；补充材料结构 ✓；双盲干净 ✓；无 CRLF ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
