# -*- coding: utf-8 -*-
"""v12：由 **v11** 生成 —— 折入全频段实测关闭 + **基线更正**（同载体/不同网格）。

依据：用户 2026-10-13 裁定「现在就出 v12」（INDEX §222 之后的提问；§223 记录）。
改动**两处**（正文 1 + 补充材料 1），每处恰好命中 1 次；其余一字不动；**LF**；
报告哈希从磁盘算；往返自检可逐字节还原 v11（正文）与其 v11 时代版本（补充材料）。

产物：`PAPER_DAC2027_EN_v12_20261013.md`、`PAPER_DAC2027_EN_v12_PROVENANCE.md`、
      `PAPER_DAC2027_EN_SUPPLEMENT_20261013b.md`（**新名**；`…_20261013.md` 保留为 v11 时代版本）、
      `work/runs/eda64-20261010/n5_stage3/V12_GENERATION_REPORT.json`
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
V11 = REPO / "docs/PAPER_DAC2027_EN_v11_20261013.md"
V12 = REPO / "docs/PAPER_DAC2027_EN_v12_20261013.md"
V12P = REPO / "docs/PAPER_DAC2027_EN_v12_PROVENANCE.md"
SUP11 = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013.md"
SUP12 = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013b.md"
OUT = REPO / "work/runs/eda64-20261010/n5_stage3"

R1_OLD = ("Even λ/9 remains above the 0.5 % criterion (0.5632 %), but one further level of the same "
          "family — **λ/11, 862,410 elements** — measures **0.3862 %** at 20 MHz and is inside it. Only "
          "this single point has been brought to that resolution: the rest of the 5–35 MHz band has not, "
          "so the item as a whole still fails, and closing it would need a per-frequency mesh "
          "requirement rather than a model change.")
R1_NEW = ("Even λ/9 remains above the 0.5 % criterion (0.5632 %), but λ/11 (862,410 elements) brings "
          "20 MHz to **0.3862 %**, inside it. Extending the same treatment across the band with a "
          "per-frequency mesh measures **0.035, 0.137, 0.207, 0.365, 0.377, 0.354 and 0.383 %** at "
          "5–35 MHz — **all seven inside the inherited τ = 0.5 %**, the upper band by only ≈1.3×. This "
          "is a single-axis (`ftet1`) result on one carrier and one design point, not mesh independence; "
          "two operational deviations and two infrastructure aborts in the finest attempt travel with "
          "it (§S9).")

R2_OLD = ("⚠️ **Only the 20 MHz row shares the fit's caliber and carrier.** The other four residuals come "
          "from §S9's *17-face* caliber on a *different* carrier whose `ftet1` size is not recorded "
          "anywhere, so those rows are a cross-caliber, cross-carrier migration combined with the `h²` "
          "extrapolation — **not** measurements on this grid. And the 16-face caliber used for the fit is "
          "**not** the 17-face criterion of the main text (the ring face was not integrated at λ/5 and "
          "λ/7); the λ/9 value under the 17-face caliber is **0.539029 %**.")

R2_NEW = (
    "⚠️ **Only the 20 MHz row shares the fit's caliber and mesh.** The other four residuals are the "
    "*17-face* caliber on the **same carrier but a different mesh**: they come from an older solution of "
    "that model file whose degrees of freedom are **359,711**, whereas the carrier's current mesh solves "
    "to **900,431**. Re-measuring the band on the current mesh (same carrier, `ftet1` = λ/5, 17-face "
    "caliber, orientation re-derived per face) gives **0.0567 % (5 MHz), 0.4075 % (10), 0.9750 % (15), "
    "1.7286 % (20), 2.5965 % (25), 3.6645 % (30), 4.9503 % (35)**. The 20 MHz entry is verified from both "
    "directions: at the 16-face caliber **1.770575 %** against the independently recorded 1.770575 % "
    "(relative difference **3.9e-10**), and at the 17-face caliber 1.7286 %, matching the carrier's "
    "current-mesh solution. A single model file can therefore contain solutions computed on **different "
    "meshes**, so solutions must be compared by degrees of freedom, not by file name. Nor is the 16-face "
    "caliber used for the fit identical to the 17-face criterion of the main text (the ring face was not "
    "integrated at λ/5 and λ/7); the λ/9 value under the 17-face caliber is **0.539029 %**.\n\n"
    "**The band was then closed.** Choosing, per frequency, the mesh the same rule requires "
    "(`n = ceil(1.10·n_req(f))`) gives the 17-face residuals below; the 5 and 10 MHz points enter at λ/9 "
    "from the calibration above.\n\n"
    "| f (MHz) | 5 | 10 | 15 | 20 | 25 | 30 | 35 |\n|---:|---:|---:|---:|---:|---:|---:|---:|\n"
    "| criterion mesh | λ/9 | λ/9 | λ/11 | λ/11 | λ/13 | λ/16 | λ/18 |\n"
    "| 17-face resid | **0.0346 %** | **0.1368 %** | **0.2065 %** | **0.3653 %** | **0.3775 %** | "
    "**0.3537 %** | **0.3826 %** |\n\n"
    "All seven are inside the inherited τ = 0.5 %. Three constraints travel with this. (i) **The "
    "upper-band margin follows from the rule, not from a comfortable measurement**: the 1.10 factor on "
    "`n` targets ≈ τ/1.21 ≈ 0.413 %, and the measured 0.354–0.383 % sit exactly there, so the margin is "
    "about 1.3×; against a 0.3 % criterion most of the upper band would fail. (ii) **Two operational "
    "deviations and two infrastructure aborts** are declared and travel with the numbers: the "
    "pre-registered memory gate was overridden to `-np` = 8 on the basis of measured memory scaling, the "
    "single-mesh plan was replaced by per-frequency meshes, and the finest attempt (λ/19, DOF 5.13e6) "
    "failed twice — once aborted for slowness, once after the direct solver went out-of-core and returned "
    "no usable reading. **There is no λ/19 measurement at 35 MHz**; its criterion mesh is λ/18. "
    "(iii) **This is a single-axis (`ftet1`) statement** — the refinement selection set is the fluid "
    "domain only, and `ftri1` and the solid side are untouched — so it is neither whole-model mesh "
    "convergence nor a Richardson error bound. Cross-frequency residuals must not be compared with one "
    "another, since each frequency uses its own mesh; the criterion is per-frequency.")


def rep_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit("[FAIL] %s 锚点命中 %d 次（要求 1）" % (label, n))
    return text.replace(old, new)


def main() -> int:
    v11 = V11.read_text(encoding="utf-8")
    sup11 = SUP11.read_text(encoding="utf-8")
    for nm, t in (("v11", v11), ("sup11", sup11)):
        if "\r\n" in t:
            raise SystemExit("[FAIL] %s 含 CRLF" % nm)
    v11_sha = hashlib.sha256(V11.read_bytes()).hexdigest()
    sup11_sha = hashlib.sha256(SUP11.read_bytes()).hexdigest()

    body = rep_once(v11, R1_OLD, R1_NEW, "R1")
    sup = rep_once(sup11, R2_OLD, R2_NEW, "R2")

    V12.write_bytes(body.encode("utf-8"))
    SUP12.write_bytes(sup.encode("utf-8"))

    db, ds = V12.read_bytes(), SUP12.read_bytes()
    if b"\r\n" in db or b"\r\n" in ds:
        raise SystemExit("[FAIL] 输出出现 CRLF")
    dt, st = db.decode("utf-8"), ds.decode("utf-8")
    if dt.replace(R1_NEW, R1_OLD) != v11:
        raise SystemExit("[FAIL] 正文往返校验失败")
    if st.replace(R2_NEW, R2_OLD) != sup11:
        raise SystemExit("[FAIL] 补充材料往返校验失败")
    for must in ("359,711", "900,431", "0.0567", "4.9503", "0.3826", "0.413", "1.3×",
                 "no λ/19 measurement at 35 MHz",
                 "compared by degrees of freedom, not by file name"):
        if must not in st:
            raise SystemExit("[FAIL] 补充材料缺少必需项：%s" % must)
    if "all seven inside the inherited" not in dt:
        raise SystemExit("[FAIL] 正文缺少必需项")
    for pat in (r"work[/\\]runs", r"docs/", r"\bsha256\b", r"[0-9a-f]{32,}", r"\bnode0\d\b"):
        if re.search(pat, st) or re.search(pat, dt):
            raise SystemExit("[FAIL] 双盲泄漏：%s" % pat)

    wc = lambda s: len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-\./%]*",
                                  s[:s.find("## Content Generated by AI")]))
    w11, w12 = wc(v11), wc(dt)
    rep = {"kind": "dac2027_en_v12_generation", "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "source": V11.name, "source_sha256": v11_sha, "source_bytes": len(V11.read_bytes()),
           "output": V12.name, "output_sha256": hashlib.sha256(db).hexdigest(),
           "output_bytes": len(db), "output_eol": "LF",
           "supplement_source": SUP11.name, "supplement_source_sha256": sup11_sha,
           "supplement_output": SUP12.name, "supplement_output_sha256": hashlib.sha256(ds).hexdigest(),
           "supplement_output_bytes": len(ds), "supplement_output_eol": "LF",
           "replacements": {"body": 1, "supplement": 1},
           "body_words_v11": w11, "body_words_v12": w12, "body_words_delta": w12 - w11,
           "roundtrip_restores_v11_and_sup11": True, "double_blind_clean": True,
           "content_added": ["baseline correction: same carrier, different mesh (DOF 359,711 vs 900,431)",
                             "R1 same-mesh band series",
                             "full-band outcome: all seven ≤ τ, upper band margin ≈1.3× by construction",
                             "two declared deviations + two infrastructure aborts + no λ/19 value at 35 MHz",
                             "single-axis (ftet1) scope; not mesh independence, not a Richardson bound"]}
    if hashlib.sha256(V12.read_bytes()).hexdigest() != rep["output_sha256"]:
        raise SystemExit("[FAIL] 报告哈希与磁盘不一致")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "V12_GENERATION_REPORT.json").write_bytes(
        (json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    V12P.write_bytes(f"""# v12 出处说明（DAC 2027 英文稿）

- 生成：{time.strftime("%Y-%m-%d")}；由 **v11**（`{V11.name}`，sha256 `{v11_sha[:24]}`，
  {len(V11.read_bytes())} B）经 **正文 1 处 + 补充材料 1 处**字面替换生成。
- 产物：`{V12.name}`（sha256 `{rep["output_sha256"][:24]}`，{rep["output_bytes"]} B，**LF**）。
- 补充材料**另存新名**：`{SUP12.name}`（sha256 `{rep["supplement_output_sha256"][:24]}`）；
  **v11 时代版本保留**为 `{SUP11.name}`（`{sup11_sha[:24]}`）—— 保持"一个版本一个文件名"。
- 正文词数：v11 **{w11}** → v12 **{w12}**（{w12 - w11:+d}）。
- **自检**：从磁盘回读；正文反向替换**逐字节还原 v11**、补充材料反向替换**逐字节还原 v11 时代版本**；
  **双盲扫描干净**。

## 折入了什么（依据 INDEX §220/§222；用户 2026-10-13 裁定）

1. **基线更正**：§S9 原先写那 4 行来自"a *different* carrier whose `ftet1` size is **not recorded**"
   —— **两半都错**。实测：那是**同一载体**（`s34_h1um_out_Model.mph`）的**另一张网格**，
   `sol1` DOF **359,711** vs 载体当前网格 `sol4` DOF **900,431**；该载体的 `ftet1` 现在是 **λ/5**（已登记）。
   并加入数据卫生结论：**同一模型文件可含不同网格上的解，须按自由度比较、不能按文件名**。
2. **同网格频段序列**（R1，λ/5，17 面）：0.0567 / 0.4075 / 0.9750 / 1.7286 / 2.5965 / 3.6645 / 4.9503 %。
3. **全频段实测结局**：逐频点按同一条规则选网格 ⇒ 17 面残差
   **0.0346 / 0.1368 / 0.2065 / 0.3653 / 0.3775 / 0.3537 / 0.3826 %**，**7/7 ≤ τ = 0.5 %**。
4. **三条必随限制**：① 上频段余量 ≈1.3× **是规则设计出来的**（目标 ≈ τ/1.21 ≈ 0.413 %），
   0.3 % 口径下上频段多数会不过；② **两条运维偏离 + 两次基础设施中止**，且 **35 MHz 没有 λ/19 实测值**
   （判据网格 = λ/18）；③ **单轴（`ftet1`）**，非全模型网格收敛、非 Richardson 误差界。

## 边界

- **不改任何图表**；除上述两处外**一字未动**；**不写"网格无关"、不写"能量守恒已验证"**；
- 页数：正文 **{w12}** 词（比 v6 的 4,463 长 {w12 - 4463:+d}）；**本机无 TeX，页数未编译验证**。

## 不主张

- 本件**不出裁定**（能量项是否关闭由人裁定，已由用户 2026-10-13 裁定为"关闭，带完整限定"）；
- **不主张** S3 通过、**不主张**放行；不提升任何状态（`release_allowed` 仍 `false`、`solver_spec` 仍 `draft`）。
""".encode("utf-8"))

    print("v11 %d B（sha %s）→ v12 %d B（sha %s）" % (rep["source_bytes"], v11_sha[:16],
                                                   rep["output_bytes"], rep["output_sha256"][:16]))
    print("补充材料另存 %s（%d B，sha %s）；v11 时代版本保留 %s"
          % (SUP12.name, len(SUP12.read_bytes()), rep["supplement_output_sha256"][:16], SUP11.name))
    print("正文词数 v11 %d → v12 %d（%+d）" % (w11, w12, w12 - w11))
    print("自检：正文往返还原 v11 ✓；补充材料往返还原 v11 时代版本 ✓；双盲干净 ✓；无 CRLF ✓")
    print("写出:", V12.name, "|", V12P.name, "|", SUP12.name, "| V12_GENERATION_REPORT.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
