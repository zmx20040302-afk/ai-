# -*- coding: utf-8 -*-
"""A1→论文：由英文稿 v3 **生成** v4（把过时的「the gap stays at −4.39 %」换成 A1 的加密趋势结论）。

纪律同前：每处替换**断言恰好命中 1 次**；**不改既有数字**，只**新增**本轮实测事实；
生成器可重放，v1/v2/v3 一字未改。

v4 相对 v3 的改动：
  T1 头部加 v4 change 说明
  T2 §6.5 探测表那一行：「the residual is unconverged discretisation」的**判定由 `not confirmed` 改为 `refuted`**，
     证据换成 A1 的三档趋势（−4.852 / −4.384 / −4.121 %）+ 声学轴不敏感（0.0011 pp）
  T3 §6.5 末段：把「halving the solid-side mesh failed on local memory ... infrastructure limit」
     改为「该加密已在 96 核服务器上跑成（342,886 单元 / 126.8 s），**问题已定案**：缺口收敛到 ≈ −3.8 %」，
     本地失败记录**保留为历史**
  T4 §6.5 两载体段：补一句**交叉核对**（h1um 载体与 ×0.5 固体侧在 P_in/P_asi 上一致到 1.1e-10
     ⇒ 「两载体复现」实质是加密一致性）
  T5 §8 限制 (vi) 追加：该缺口**在固体侧加密下依然存在**（收敛 ≈ −3.8 %，约为 0.5 % 阈值的 8 倍）
  T6 内部溯源件 v4 = v3 + `[A1]` 行

产物：`docs/PAPER_DAC2027_EN_v4_20261011.md`、`docs/PAPER_DAC2027_EN_v4_PROVENANCE.md`、
      `work/runs/eda64-20261010/p5_a1/V4_GENERATION_REPORT.json`
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
V3 = REPO / "docs/PAPER_DAC2027_EN_v3_20261011.md"
V3P = REPO / "docs/PAPER_DAC2027_EN_v3_PROVENANCE.md"
V4 = REPO / "docs/PAPER_DAC2027_EN_v4_20261011.md"
V4P = REPO / "docs/PAPER_DAC2027_EN_v4_PROVENANCE.md"
OUT = REPO / "work/runs/eda64-20261010/p5_a1"

HDR_EXTRA = ("> **v4 change (this revision).** The mesh-refinement question raised in §6.5 is now **settled**:\n"
             "> the solid-side refinement that previously failed locally has been run on a 96-core server, and the\n"
             "> energy-closure residual falls monotonically with refinement (−4.852 % → −4.384 % → −4.121 %)\n"
             "> but extrapolates to a **non-zero limit of ≈ −3.8 %** — roughly eight times the 0.5 % criterion, and\n"
             "> insensitive to the acoustic mesh. The residual is therefore *not* under-resolution.")

OLD_ROW = ("| the residual is unconverged discretisation | under the refinement we can afford, "
           "`P_asi` changes by 1e-06 relative and `P_in` by 1.4e-05; the solid-side mechanical "
           "power independently reproduces the acoustic side to 0.02 %; the gap stays at "
           "**−4.39 %** | **not confirmed** |")
NEW_ROW = ("| the residual is unconverged discretisation | solid-side refinement on a 96-core server "
           "(×1 → ×0.75 → ×0.5 mesh, 136,250 → 342,886 elements): the gap falls monotonically "
           "−4.852 % → −4.384 % → **−4.121 %**, with decrement ratio 0.562, so a geometric fit puts the "
           "converged limit at **≈ −3.8 %**; refining the acoustic mesh from λ/5 to λ/7 at ×0.5 moves the gap "
           "by only 0.0011 pp | **refuted** |")

OLD_TAIL = """The refinement that would settle the question (halving the solid-side mesh) failed on local memory at
900,182 degrees of freedom with a peak physical memory of 19.14 GB; this is recorded as an
infrastructure limit, not as divergence."""
NEW_TAIL = """The refinement that settles the question — halving the solid-side mesh — failed on local memory
(900,182 degrees of freedom, peak physical memory 19.14 GB), and is recorded as an infrastructure
limit; it has since been **run to completion on a 96-core server** (342,886 elements, 126.8 s solve,
zero failures), with the outcome given in the table above: the residual converges to ≈ −3.8 %, i.e.
the energy item is a **converged discrete non-closure at this caliber**, not an under-resolution
artefact. Whether the caliber or the model must change to satisfy the 0.5 % criterion is left open and
is explicitly *not* claimed here (see §8)."""

OLD_CARRIER = ("versus −4.85 % and −6.57 % on the first carrier, with the three powers agreeing between\n"
               "carriers to within 0.81 %.")
NEW_CARRIER = ("versus −4.85 % and −6.57 % on the first carrier, with the three powers agreeing between\n"
               "carriers to within 0.81 %. That agreement is itself informative: the second carrier's port and\n"
               "acoustic powers match the ×0.5 solid-side refinement above to 1.1e-10 relative, so the two\n"
               "carriers differ by a *refinement step*, not by machine or implementation.")

OLD_LIM6 = ("""§6.5 is a *per-point* quantity that changes sign with frequency and design point; the value quoted for
the reported design point is not a global constant, and the supporting measurements were obtained by
zero-solve post-processing of already-solved models rather than by new solves.""")
NEW_LIM6 = ("""§6.5 is a *per-point* quantity that changes sign with frequency and design point; the value quoted for
the reported design point is not a global constant, and the supporting measurements were obtained by
zero-solve post-processing of already-solved models rather than by new solves. It also does **not**
vanish under mesh refinement: on the reporting design point it falls from −4.85 % to −4.12 % as the
solid-side mesh is halved twice, and extrapolates to ≈ −3.8 %, about eight times the 0.5 % criterion.
An engine-level caliber or model change — not more resolution — would be required to close it.""")

EDITS = [("T2_probe_row_discretisation", OLD_ROW, NEW_ROW),
         ("T3_refinement_settled", OLD_TAIL, NEW_TAIL),
         ("T4_two_carrier_refinement_step", OLD_CARRIER, NEW_CARRIER),
         ("T5_limitation_vi_converged", OLD_LIM6, NEW_LIM6)]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    text = V3.read_text(encoding="utf-8")
    report: dict = {"kind": "p5_a1_v4_generation", "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "source": str(V3.relative_to(REPO)),
                    "source_sha256": hashlib.sha256(V3.read_bytes()).hexdigest(), "edits": []}

    anchor = "> paths and artifact hashes). **No model state has been promoted**: the surrogate"
    assert text.count(anchor) == 1
    text = text.replace(anchor, HDR_EXTRA + "\n" + anchor)
    report["edits"].append({"id": "T1_header_v4_note", "hits": 1})

    for eid, old, new in EDITS:
        got = text.count(old)
        if got != 1:
            raise SystemExit("%s 命中 %d 次（期望 1）⇒ 拒绝生成" % (eid, got))
        text = text.replace(old, new)
        report["edits"].append({"id": eid, "hits": got, "old_chars": len(old), "new_chars": len(new)})

    V4.write_text(text, encoding="utf-8", newline="\n")
    report["outputs"] = {str(V4.relative_to(REPO)): {
        "lines": text.count("\n") + 1, "bytes": V4.stat().st_size,
        "sha256": hashlib.sha256(V4.read_bytes()).hexdigest(),
        "words": len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-\./%]*", text)),
        "stale_phrase_remaining": ("the gap stays at" in text)}}

    prov = V3P.read_text(encoding="utf-8")
    prov = prov.replace("英文稿 **v3** 的数字溯源", "英文稿 **v4** 的数字溯源")
    prov = prov.replace("- 投稿候选：`docs/PAPER_DAC2027_EN_v3_20261011.md`（v3 由 v2 生成；",
                        "- 投稿候选：`docs/PAPER_DAC2027_EN_v4_20261011.md`（v4 由 v3 生成；")
    prov = prov.rstrip() + "\n" + (
        "\n## D. v4 新增数字的溯源（A1，服务器零/一次求解均可核算）\n\n"
        "| 标签 | 量 | 来源产物 |\n|---|---|---|\n"
        "| [A1] | 固体侧加密三档缺口 −4.852 / −4.384 / −4.121 %；几何外推极限 ≈ −3.8 %（递减比 0.562）；"
        "声学轴 λ/5→λ/7 仅 0.0011 pp；×0.5 档 342,886 单元 / 126.8 s；×0.5+λ/7 = 424,591 单元 / 112.5 s；"
        "闭合 28 面 `es` 法向 8.17e-04；h1um 载体与 ×0.5 一致到 1.1e-10 | "
        "`work/runs/eda64-20261010/p5_a1/P5_A1_REFINEMENT_TREND.json`、`P5_A1_SOLID_HALF_RAW.json`、"
        "`P5_A1_SOLID_HALF_L7_RAW.json`；本地三档见 `n1c_mesh_study/N1C_MESH_STUDY.json` |\n")
    V4P.write_text(prov, encoding="utf-8", newline="\n")
    report["outputs"][str(V4P.relative_to(REPO))] = {
        "bytes": V4P.stat().st_size, "sha256": hashlib.sha256(V4P.read_bytes()).hexdigest()}
    (OUT / "V4_GENERATION_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8")
    for e in report["edits"]:
        print("   %-40s hits=%s" % (e["id"], e.get("hits")))
    for k, v in report["outputs"].items():
        print("== 写出 %s %s" % (k, json.dumps(v, ensure_ascii=False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
