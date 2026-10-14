# -*- coding: utf-8 -*-
"""v13：由 **v12** 生成 —— 折入 ① **S0 事前预注册下的通过**（含**失败的旧口径**同现）与
② **S3 在两个人签口径下的通过**（并写明「改口径 ≠ 功率守恒」，6.177 % 读数保留）。

依据：用户 2026-10-13 选择「现在出 v13：补 S0 一节/一句 + 修 S3 口径叙述」；
证据：`work/runs/s0-rerun-20261013/S0_RESULT_V2.json`、`work/runs/s3-band-20261013/S3_ALIGNMENT_20261013_OPERATIVE.json`。

9 处替换，每处**恰好命中 1 次**；其余一字不动；**LF**；报告哈希从**磁盘**算；
往返自检可**逐字节还原 v12**；补充材料本版**未改**（沿用 `…_20261013b.md`，另记其 sha）。
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
V12 = REPO / "docs/PAPER_DAC2027_EN_v12_20261013.md"
V13 = REPO / "docs/PAPER_DAC2027_EN_v13_20261013.md"
V13P = REPO / "docs/PAPER_DAC2027_EN_v13_PROVENANCE.md"
SUP = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013b.md"
OUT = REPO / "work/runs/eda64-20261010/n5_stage3"

# ---- 1. 摘要：三负 → 两负 + 一「有条件通过」
A_OLD = ("splits with five seeds and eight methods none beats a persistence baseline on either formal target;\n"
         "the registered energy-closure gate fails every caliber correction we can test; and a multi-frequency\n"
         "reduced model misses the 2 % key-region threshold by 10×.")
A_NEW = ("splits with five seeds and eight methods none beats a persistence baseline on either formal target;\n"
         "a multi-frequency reduced model misses the 2 % key-region threshold by 10×; and the physics gate\n"
         "passes only under two calibers signed by the reviewer, one of which retires rather than resolves an\n"
         "electrical-to-acoustic deficit that survives refinement (≈ −3.8 % extrapolated).")

# ---- 2. 贡献 C4
C_OLD = ("4. **C4 — physics-consistency gates reported as experimental results, including the negative ones**:\n"
         "   S3 fails; S4 passes only under its declared scope and object; the strict mesh-convergence caliber\n"
         "   is not met; the solver state stays `draft`.")
C_NEW = ("4. **C4 — physics-consistency gates reported as experimental results, including the negative ones**:\n"
         "   limit consistency (S0) passes under a protocol pre-registered before its re-computation while the\n"
         "   spatial-isotropy caliber registered first still fails; S3 passes **only** after two signed caliber\n"
         "   rulings, not because the power budget balances; S4 passes only under its declared scope and object;\n"
         "   the strict mesh-convergence caliber is not met; the solver state stays `draft`.")

# ---- 3. 门禁语义：补 S0
G_OLD = ("S1 (key region < 2 %, global < 5 %), S2 (engineering quantities < 3 %), S3 (conservation < 0.5 %,\n"
         "boundary conditions < 1 %), S4 (mesh difference < 2 %) and S5 (interval coverage in [0.85, 0.95]).")
G_NEW = ("S0 (low-frequency limit consistency < 1 %), S1 (key region < 2 %, global < 5 %), S2 (engineering\n"
         "quantities < 3 %), S3 (conservation < 0.5 %, boundary conditions < 1 %), S4 (mesh difference < 2 %)\n"
         "and S5 (interval coverage in [0.85, 0.95]).")

# ---- 4. §6.4 首段：S3 改写；并新增 S0 段
S3_OLD = ("**S3 fails, and one of its two failures is a caliber artefact.** On the gate design point the\n"
          "registered S3 report gives 7 passes and 2 failures. Correcting the current-conservation check as described next makes the count **8 passes and 1 failure**, with 0 inconclusive outcomes; that corrected caliber was confirmed by the human reviewer on 2026-10-12. The current-conservation\n"
          "check compared a lumped circuit current with a field flux across an unclosed circuit using\n"
          "post-processing normals; re-evaluated as a closed-surface flux with the physics normal it gives\n"
          "6.469e-04…1.032e-03 on one carrier and 8.168e-04 on a second, inside the 0.5 % criterion. The\n"
          "energy-closure check is *not* an artefact: the electrical input power is 6.177 % below the radiated\n"
          "acoustic power against 0.5 %, and §6.5 shows that this survives refinement.")
S3_NEW = ("**S3 passes — but only under two calibers signed by the reviewer.** On the gate design point the\n"
          "registered S3 report gives 7 passes and 2 failures. Correcting the current-conservation check first\n"
          "makes the count **8 passes and 1 failure**, with 0 inconclusive outcomes (signed 2026-10-12): that\n"
          "check compared a lumped circuit current with a field flux across an unclosed circuit using\n"
          "post-processing normals, and re-evaluated as a closed-surface flux with the physics normal it gives\n"
          "6.469e-04…1.032e-03 on one carrier and 8.168e-04 on a second, inside the 0.5 % criterion. The\n"
          "remaining failure was then **re-scoped rather than re-solved** (signed 2026-10-13): the\n"
          "electrical-to-acoustic caliber under which it failed — the input power is 6.177 % below the radiated\n"
          "acoustic power, and §6.5 shows that this survives refinement — is retired as the gate's criterion\n"
          "while its reading is kept, and the operative criterion becomes the acoustic-side net outward flux of\n"
          "§6.5, which measures **0.035–0.383 %** across 5–35 MHz. With both rulings all nine registered checks\n"
          "pass. **The pass therefore records two ruled calibers, not a balanced power budget**: the\n"
          "electrical-to-acoustic deficit stands at 6.177 % and extrapolates to ≈ −3.8 %, about eight times the\n"
          "criterion, so any claim that the model's input and radiated powers agree would contradict §6.5.\n\n"
          "**S0 passes under a pre-registered protocol, and one registered caliber still fails.** The protocol\n"
          "was frozen before its zero-solve re-computation. On the solver's own material constants the\n"
          "low-frequency identity ρ_eff(f) = ∫|p|²dA / (2c·P_rad) must equal 998.2024166 kg/m³ exactly for a\n"
          "monopole; at 0.25 MHz it gives a relative error of **9.0380e-04**, 11.1× inside the 1 % criterion,\n"
          "and reproduces the recorded values bit-for-bit (**1.5230e-02** at 20 MHz is reported as well, that\n"
          "point having left the monopole asymptotics). The caliber registered *first* — spatial isotropy and an\n"
          "r⁻¹ law — **still fails** (0.0090833 and 0.0290035 against 0.01) and is reported alongside it. The\n"
          "residual does not fall monotonically to zero, so a systematic floor of ≈0.03–0.09 % remains; only the\n"
          "monopole component is covered; and the carrier is a λ/5 mesh whose binding to the solver instances is\n"
          "untested. The pre-registration covers the *evaluation protocol* only: the choice of ρ_eff itself was\n"
          "made after the isotropy caliber failed and is therefore still post-hoc.")

# ---- 5. §6.5 末句：补「人裁定采纳该口径」
T_OLD = ("two operational deviations and two infrastructure aborts in the finest attempt travel with it (§S9).")
T_NEW = ("two operational deviations and two infrastructure aborts in the finest attempt travel with it (§S9). "
         "On 2026-10-13 the reviewer adopted this acoustic-side caliber as the operative energy criterion of S3, "
         "retiring — without erasing — the electrical-to-acoustic reading of the table above; the two calibers "
         "must therefore always be named, because only one of them is now the gate.")

# ---- 6. 结论
K_OLD = ("and the physics-consistency gate fails on energy closure, a failure that survives every caliber\n"
         "correction and every refinement we could test. The flow is")
K_NEW = ("and the physics gate passes only under two calibers signed by the reviewer, one of which retires\n"
         "rather than resolves an electrical-to-acoustic deficit that survives refinement. The flow is")

# ---- 7. 限制 (iii)：两跳条件已满足但**状态未提升**
L_OLD = ("engineering absolute value may be quoted. (iii) The model's own status is `draft`; no state has been\n"
         "promoted.")
L_NEW = ("engineering absolute value may be quoted. (iii) S0 and S3 — the two first-hop conditions — are now\n"
         "met, yet **no state has been promoted**: promotion is a human act and no engineering absolute value\n"
         "follows from it. The model's own status remains `draft`.")

# ---- 8. 摘要首句：三负 → 两负 + 一「有条件通过」
H_OLD = "Three results are negative: under leakage-free grouped"
H_NEW = "Two results are negative and one is scoped: under leakage-free grouped"

# ---- 9. 限制 (vi) 末句：口径变更**已经发生**（不得再说「需要」）
I_OLD = "An engine-level caliber or model change — not more resolution — would be required to close it."
I_NEW = ("An engine-level caliber or model change — not more resolution — would be required to close it, and the\n"
         "ruling of 2026-10-13 is precisely such a caliber change: it retires the reading rather than removing\n"
         "the deficit.")

REPS = [("A_abstract", A_OLD, A_NEW), ("B_contributions_C4", C_OLD, C_NEW),
        ("C_gate_semantics", G_OLD, G_NEW), ("D_sec64_S3_and_S0", S3_OLD, S3_NEW),
        ("E_sec65_tail", T_OLD, T_NEW), ("F_conclusion", K_OLD, K_NEW), ("G_limitations_iii", L_OLD, L_NEW),
        ("H_abstract_count", H_OLD, H_NEW), ("I_limitations_vi", I_OLD, I_NEW)]


def main() -> int:
    t0 = time.time()
    src = V12.read_text(encoding="utf-8")
    if "\r\n" in src:
        raise SystemExit("[FAIL] v12 含 CRLF（本系列应为 LF）")
    sha12 = hashlib.sha256(V12.read_bytes()).hexdigest()

    body = src
    for label, old, new in REPS:
        n = body.count(old)
        if n != 1:
            raise SystemExit("[FAIL] %s 锚点命中 %d 次（要求 1）" % (label, n))
        body = body.replace(old, new)

    V13.write_bytes(body.encode("utf-8"))
    db = V13.read_bytes()
    if b"\r\n" in db:
        raise SystemExit("[FAIL] 输出出现 CRLF")
    dt = db.decode("utf-8")
    back = dt
    for _, old, new in REPS:
        back = back.replace(new, old)
    if back != src:
        raise SystemExit("[FAIL] 往返未逐字节还原 v12")

    # 必需项
    for must in ("S0 (low-frequency limit consistency < 1 %)", "9.0380e-04", "998.2024166",
                 "1.5230e-02", "0.0090833", "0.0290035", "still fails",
                 "S3 passes — but only under two calibers signed by the reviewer",
                 "not a balanced power budget", "6.177 %", "−3.8 %",
                 "two first-hop conditions", "no state has been promoted"):
        if must not in dt:
            raise SystemExit("[FAIL] 缺必需项：%s" % must)
    if dt.count("S0 (low-frequency limit consistency < 1 %)") != 1:
        raise SystemExit("[FAIL] 门禁语义行的 S0 命中数异常")
    # 双盲泄漏扫描
    for pat in (r"work[/\\]runs", r"docs/", r"\bsha256\b", r"[0-9a-f]{32,}", r"\bnode0\d\b",
                r"\bzhangmx\b", r"ubuntu-", r"\bINDEX\b"):
        if re.search(pat, dt):
            raise SystemExit("[FAIL] 双盲泄漏：%s" % pat)

    wc = lambda s: len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-\./%]*", s[:s.find("## Content Generated by AI")]))
    w12, w13 = wc(src), wc(dt)
    rep = {"kind": "dac2027_en_v13_generation", "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "source": V12.name, "source_sha256": sha12, "source_bytes": len(V12.read_bytes()),
           "output": V13.name, "output_sha256": hashlib.sha256(db).hexdigest(),
           "output_bytes": len(db), "output_eol": "LF",
           "supplement_unchanged": {"file": SUP.name, "sha256": hashlib.sha256(SUP.read_bytes()).hexdigest(),
                                    "bytes": SUP.stat().st_size,
                                    "note": "本版**未改**补充材料（无新数字需要补充材料承载）"},
           "replacements": {label: 1 for label, _, _ in REPS},
           "body_words_v12": w12, "body_words_v13": w13, "body_words_delta": w13 - w12,
           "roundtrip_restores_v12": True, "double_blind_clean": True,
           "evidence": {
               "S0": {"file": "work/runs/s0-rerun-20261013/S0_RESULT_V2.json",
                      "sha256": hashlib.sha256((REPO / "work/runs/s0-rerun-20261013/S0_RESULT_V2.json").read_bytes()).hexdigest(),
                      "verdict": "passed", "rel_err_at_0.25MHz": 9.037967e-04, "margin_ratio": 11.06,
                      "prereg": "work/runs/s0-rerun-20261013/PREREG_S0_V2.json"},
               "S3": {"file": "work/runs/s3-band-20261013/S3_ALIGNMENT_20261013_OPERATIVE.json",
                      "sha256": hashlib.sha256((REPO / "work/runs/s3-band-20261013/S3_ALIGNMENT_20261013_OPERATIVE.json").read_bytes()).hexdigest(),
                      "verdict": "passed", "n_checks": 9, "S3_complete": True,
                      "retired_item_reading_pct": 6.1767646903485025, "retired_limit_pct": -3.78}},
           "content_added": ["S0: pre-registered limit-consistency pass (9.0380e-04, 11.1x) with the registered isotropy caliber failing alongside",
                             "S0 added to the gate-semantics threshold list",
                             "S3 narrative: pass rests on two signed calibers; the 6.177 % / -3.8 % electrical-to-acoustic reading is retired, not erased",
                             "first-hop conditions met but no state promoted (promotion is a human act)",
                             "abstract and conclusion re-framed: two negative results + one scoped pass"]}
    if hashlib.sha256(V13.read_bytes()).hexdigest() != rep["output_sha256"]:
        raise SystemExit("[FAIL] 报告哈希与磁盘不一致")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "V13_GENERATION_REPORT.json").write_bytes(
        (json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    V13P.write_bytes(f"""# v13 出处说明（DAC 2027 英文稿）

- 生成：{time.strftime("%Y-%m-%d")}；由 **v12**（`{V12.name}`，sha256 `{sha12[:24]}`，
  {len(V12.read_bytes())} B）经 **9 处**单命中字面替换生成（每处恰好 1 次）。
- 产物：`{V13.name}`（sha256 `{rep["output_sha256"][:24]}`，{rep["output_bytes"]} B，**LF**）。
- 补充材料本版**未改**：沿用 `{SUP.name}`（sha256 `{rep["supplement_unchanged"]["sha256"][:24]}`）。
- 正文词数：v12 **{w12}** → v13 **{w13}**（{w13 - w12:+d}）。
- **自检**：从磁盘回读；**反向替换逐字节还原 v12**；**双盲扫描干净**；无 CRLF。

## 折入了什么

1. **S0（极限一致性）通过了，且是事前预注册下的通过**：协议在零求解复算**之前**冻结；
   0.25 MHz 上 `ρ_eff = ∫|p|²dA/(2c·P_rad)` 与 998.2024166 kg/m³ 的相对误差 **9.0380e-04**（阈 1 %，**余量 11.1×**），
   与既有记录**逐位相同**；20 MHz 的 **1.5230e-02** 一并报出（该点已离开单极子渐近区）。
   **同现**：**先注册**的那条口径（空间各向同性 + r⁻¹ 律）**仍然失败**（0.0090833 / 0.0290035 > 0.01）。
   四条限制随行：残差**非单调**（≈0.03–0.09 % 系统底噪）、**只覆盖单极子成分**、载体为 λ/5 网格且与求解器实例的绑定**未做**、
   预注册**只覆盖评测协议**（ρ_eff 的选择本身仍是事后）。
2. **S3 通过了 —— 但是「两个人签口径」下的通过，不是功率平衡**：登记口径 7 通过 / 2 失败；
   电流守恒项经 2026-10-12 签字改口径（闭合面 + 物理场法向，6.469e-04…1.032e-03 / 8.168e-04）⇒ 通过；
   能量项经 2026-10-13 签字**改口径**（采用声学侧 17 面净外通量，5–35 MHz 实测 **0.035–0.383 %**）⇒ 通过；
   九项全过。**电—声一致口径的 6.177 %（外推 ≈ −3.8 %）读数保留、不删**，论文 §6.5 已如实写出。
3. **两跳条件已满足但状态未提升**：`draft` 未动，放行权仍在人。

## 边界

- **不改任何图表**；除上述 9 处外**一字未动**；**不写「网格无关」、不写「能量守恒已验证」**、**不写「已放行」**；
- 页数：正文 **{w13}** 词（比 v6 的 4,463 长 {w13 - 4463:+d}）；**本机无 TeX，页数未编译验证**；
  本版相对 v12 **净增** {w13 - w12} 词 ⇒ 若编译超页，优先削减项见生成报告 `content_added` 与人裁定。

## 不主张

- 不主张 S0 通过会导致放行；不主张 ρ_eff 是**事前**选定的判据；
- 不主张「S3 通过」等价于功率守恒；不主张能量守恒已被证明或被否证；
- 不提升任何状态：`release_allowed` 仍 `false`、`solver_spec` 仍 `draft`。
""".encode("utf-8"))

    print("v12 %d B（sha %s）→ v13 %d B（sha %s）" % (rep["source_bytes"], sha12[:16],
                                                   rep["output_bytes"], rep["output_sha256"][:16]))
    print("正文词数 v12 %d → v13 %d（%+d）；9 处替换各命中 1 次" % (w12, w13, w13 - w12))
    print("自检：往返逐字节还原 v12 ✓；双盲干净 ✓；无 CRLF ✓（%.1f s）" % (time.time() - t0))
    print("写出:", V13.name, "|", V13P.name, "| V13_GENERATION_REPORT.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
