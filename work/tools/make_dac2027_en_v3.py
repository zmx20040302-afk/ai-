# -*- coding: utf-8 -*-
"""P5→论文：由英文稿 v2 **生成** v3（把「能量缺口随频率/设计点变号」回填，并修掉 v2 的重复标题）。

纪律同前：每处替换**断言恰好命中 N 次**，否则整体失败；**不改任何既有数字**，只**新增**本轮实测事实。

v3 相对 v2 的改动：
  T1 **修掉重复标题**（v2 因头部替换保留了原第 1 行标题 + 新头部的标题，标题出现两次）
  T2 头部块加一行「v3 相对 v2 改了什么」
  T3 §6.5 探测表**新增一行**：「缺口是一个固定的系统性偏移」→ **refuted**（同几何内随频率变号 + 同频换几何变号）
  T4 §6.5 结论段：保留原「该设计点上 −4.4 %」的校准表述，**追加** ① 两载体同口径复现（−4.85 % / −4.12 %）
     ② **缺口随频率/设计点变号**（实测区间与端点，含落在 0.5 % 带内的那一例）；并**明确写出**
     「不得把 ≈4.4 % 当成全局常数」
  T5 §6.5 口径限制由 (i)(ii) 增补为 (i)(ii)(iii)
  T6 §8 限制新增 (vi)：能量缺口是**逐点量**，且本轮新证据是**零求解**后处理
  T7 内部溯源件：v3 版 = v2 版 + `[P5-1]`/`[P5-3]` 两行

产物：`docs/PAPER_DAC2027_EN_v3_20261011.md`、`docs/PAPER_DAC2027_EN_v3_PROVENANCE.md`、
      `work/runs/eda64-20261010/p5_cost/V3_GENERATION_REPORT.json`
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
V2 = REPO / "docs/PAPER_DAC2027_EN_v2_20261011.md"
V2P = REPO / "docs/PAPER_DAC2027_EN_v2_PROVENANCE.md"
V3 = REPO / "docs/PAPER_DAC2027_EN_v3_20261011.md"
V3P = REPO / "docs/PAPER_DAC2027_EN_v3_PROVENANCE.md"
OUT = REPO / "work/runs/eda64-20261010/p5_cost"

HDR_EXTRA = ("> **v3 change (this revision).** §6.5 now reports the energy-closure residual **per point**:\n"
             "> the same caliber on a second, independently meshed carrier of the same design point reproduces\n"
             "> the shortfall (−4.85 % vs −4.12 %), while the residual is shown to **change sign** both across\n"
             "> frequency within one geometry and across geometries at one frequency — so the single number\n"
             "> \"≈4.4 %\" is design-point-specific and must not be quoted as a global constant.")

ROW_NEW = ("| the residual is a fixed systematic offset | same caliber on a second geometry at the same 20 MHz: "
           "+1.60 % (coupling surface) and −0.34 % (outer hemisphere) instead of −4.12 % / −5.82 %; within one "
           "geometry, 5–15 MHz gives +3.14…+3.97 % and 25–35 MHz gives −1.52…−0.82 % (coupling surface) | "
           "**refuted** |")

OLD_CONCL = """The calibrated statement is therefore: at this design point the *electrical* input power is about
4.4 % below the acoustic flux measured on two mutually independent surfaces, and this is a genuine
discrete non-closure rather than a post-processing mistake. Two caliber limits must be quoted with
it: (i) energy statements whose numerator is `P_in` are only meaningful above ≈2 MHz, because at
lower frequencies the real part of the terminal current is at the level of the linear solver's
resolution (5e-08 of the apparent power); (ii) post-processing normals (`nX/nY/nZ`) must not be used
for closed-surface flux judges — on the 28-face electrode surface they give
`∫nz dA = −6.65e-09 ≠ 0` and a spurious non-conservation ratio of 2.16, whereas the physics normal
`es.nx/ny/nz` gives 1.03e-03, inside the 0.5 % criterion. The refinement that would settle the
question (halving the solid-side mesh) failed on local memory at 900,182 degrees of freedom with a
peak physical memory of 19.14 GB; this is recorded as an infrastructure limit, not as divergence."""

NEW_CONCL = """The calibrated statement is therefore: **at this design point** the *electrical* input power is
about 4.4 % below the acoustic flux measured on two mutually independent surfaces, and this is a
genuine discrete non-closure rather than a post-processing mistake.

**The residual is design-point- and frequency-dependent, and must be quoted per point.** Two further
zero-solve measurements were made with the *same* caliber. First, the identical post-processing applied
to a second, independently meshed carrier of the *same* design point reproduces the shortfall: input
power 3.7338 µW against 3.8943 µW (coupling surface) and 3.9645 µW (outer hemisphere), i.e. −4.12 %
and −5.82 %, versus −4.85 % and −6.57 % on the first carrier, with the three powers agreeing between
carriers to within 0.81 %. The direction of the residual, however, is *not* universal: at the same
20 MHz on a second geometry the same caliber yields **+1.60 %** against the coupling surface and
**−0.34 %** against the outer hemisphere — the latter comfortably inside the 0.5 % criterion — and
within a single geometry the sign flips across the band (5–15 MHz: +3.14…+3.97 %; 25–35 MHz:
−1.52…−0.82 % against the coupling surface, −4.08…−5.34 % against the outer hemisphere). A single
figure such as "≈4.4 %" is therefore valid for the reported design point only and must never be
presented as a property of the method.

Three caliber limits must be quoted with it: (i) energy statements whose numerator is `P_in` are only
meaningful above ≈2 MHz, because at lower frequencies the real part of the terminal current is at the
level of the linear solver's resolution (5e-08 of the apparent power); (ii) post-processing normals
(`nX/nY/nZ`) must not be used for closed-surface flux judges — on the 28-face electrode surface they
give `∫nz dA = −6.65e-09 ≠ 0` and a spurious non-conservation ratio of 2.16, whereas the physics
normal `es.nx/ny/nz` gives 1.03e-03, inside the 0.5 % criterion (reproduced independently on the
second carrier: 8.2e-04 versus 0.999); (iii) because the sign of the residual depends on the
integration surface at some frequencies, the surface caliber must be named in every such statement.
The refinement that would settle the question (halving the solid-side mesh) failed on local memory at
900,182 degrees of freedom with a peak physical memory of 19.14 GB; this is recorded as an
infrastructure limit, not as divergence."""

OLD_LIM = """(v) Both pre-registered experiments of §6.6 are complete; their
narrow or negative outcomes are reported as results, not withheld."""
NEW_LIM = """(v) Both pre-registered experiments of §6.6 are complete; their
narrow or negative outcomes are reported as results, not withheld. (vi) The energy-closure residual of
§6.5 is a *per-point* quantity that changes sign with frequency and design point; the value quoted for
the reported design point is not a global constant, and the supporting measurements were obtained by
zero-solve post-processing of already-solved models rather than by new solves."""

def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    text = V2.read_text(encoding="utf-8")
    report: dict = {"kind": "p5_v3_generation", "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "source": str(V2.relative_to(REPO)),
                    "source_sha256": hashlib.sha256(V2.read_bytes()).hexdigest(),
                    "edits": []}

    # ---- T1 修掉重复标题 ----
    lines = text.split("\n")
    assert lines[0].startswith("# PeakGuard"), lines[0][:60]
    assert lines[2].startswith("# PeakGuard"), lines[2][:60]
    lines = lines[:2] + lines[3:]
    report["edits"].append({"id": "T1_duplicate_title", "removed": "v2 的第 3 行（重复标题）"})
    text = "\n".join(lines)

    # ---- T2 头部加一行 v3 说明 ----
    anchor = "> paths and artifact hashes). **No model state has been promoted**: the surrogate"
    assert text.count(anchor) == 1, text.count(anchor)
    text = text.replace(anchor, HDR_EXTRA + "\n" + anchor)
    report["edits"].append({"id": "T2_header_v3_note", "hits": 1})

    # ---- T4 探测表新增一行（放在最后一行「unconverged discretisation」之后）----
    last_row = ("| the residual is unconverged discretisation | under the refinement we can afford, "
                "`P_asi` changes by 1e-06 relative and `P_in` by 1.4e-05; the solid-side mechanical "
                "power independently reproduces the acoustic side to 0.02 %; the gap stays at "
                "**−4.39 %** | **not confirmed** |")
    assert text.count(last_row) == 1, "未找到探测表最后一行"
    text = text.replace(last_row, last_row + "\n" + ROW_NEW)
    report["edits"].append({"id": "T4_probe_table_row", "hits": 1})

    # ---- T5 结论段替换 ----
    assert text.count(OLD_CONCL) == 1, "结论段未唯一命中（%d）" % text.count(OLD_CONCL)
    text = text.replace(OLD_CONCL, NEW_CONCL)
    report["edits"].append({"id": "T5_conclusion_two_carrier_and_sign_change", "hits": 1,
                            "old_chars": len(OLD_CONCL), "new_chars": len(NEW_CONCL)})

    # ---- T6 §8 限制新增 (vi) ----
    assert text.count(OLD_LIM) == 1, "限制段未唯一命中"
    text = text.replace(OLD_LIM, NEW_LIM)
    report["edits"].append({"id": "T6_limitations_vi", "hits": 1})

    V3.write_text(text, encoding="utf-8", newline="\n")
    report["outputs"] = {str(V3.relative_to(REPO)): {
        "lines": text.count("\n") + 1, "bytes": V3.stat().st_size,
        "sha256": hashlib.sha256(V3.read_bytes()).hexdigest(),
        "words": len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-\./%]*", text)),
        "titles_at_top": len([l for l in text.split("\n")[:4] if l.startswith("# PeakGuard")])}}

    # ---- T7 溯源件 ----
    prov = V2P.read_text(encoding="utf-8")
    prov = prov.replace("# 内部溯源件（**不进投稿**）：英文稿 v2 的数字溯源与注册用摘要",
                        "# 内部溯源件（**不进投稿**）：英文稿 **v3** 的数字溯源与注册用摘要")
    prov = prov.replace("- 投稿候选：`docs/PAPER_DAC2027_EN_v2_20261011.md`（正文不含本文件内容）。",
                        "- 投稿候选：`docs/PAPER_DAC2027_EN_v3_20261011.md`（v3 由 v2 生成；"
                        "改动见 `work/runs/eda64-20261010/p5_cost/V3_GENERATION_REPORT.json`）。")
    add = ("\n## C. v3 新增数字的溯源（P5-1 / P5-3，全部零求解）\n\n"
           "| 标签 | 量 | 来源产物 |\n|---|---|---|\n"
           "| [P5-1] | 两载体同口径能量并置：P_in/P_asi/P_hemi、缺口 −4.85 % / −4.12 %、跨载体 ≤0.81 % | "
           "`work/runs/eda64-20261010/p5_h1um/P5_H1UM_RECALIBER.json`；原始 "
           "`P5_H1UM_REMEASURE_RAW.json`；载体 sha256 `6005ca65…`（185,349,336 B） |\n"
           "| [P5-3] | 逐频点功率平衡（缺口随频率变号：+3.14…+3.97 % / −1.52…−0.82 %；另一几何 +1.60 % / −0.34 %）；"
           "Z(f) 无源必要条件逐点通过；后处理法向缺陷在载体 B 复现（8.2e-04 vs 0.999） | "
           "`work/runs/eda64-20261010/p5_port/P5_PORT_CONTRACT_AND_PASSIVITY.json`、`P5_PORT_PROBE_RAW.json` |\n"
           "| [P5-3c] | 成本/break-even（在线 0.0011 ms、内存 20.14 MB、N* ≈ 150 / 37） | "
           "`work/runs/eda64-20261010/p5_cost/SIX_CARRIER_COST_AND_BREAKEVEN.json`、`ONLINE_LATENCY.json` |\n")
    V3P.write_text(prov.rstrip() + "\n" + add, encoding="utf-8", newline="\n")
    report["outputs"][str(V3P.relative_to(REPO))] = {
        "bytes": V3P.stat().st_size, "sha256": hashlib.sha256(V3P.read_bytes()).hexdigest()}
    (OUT / "V3_GENERATION_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for e in report["edits"]:
        print("   %-46s %s" % (e["id"], e.get("hits", e.get("removed", ""))))
    for k, v in report["outputs"].items():
        print("== 写出 %s (%s)" % (k, json.dumps(v, ensure_ascii=False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
