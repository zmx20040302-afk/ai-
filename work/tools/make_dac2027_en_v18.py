# -*- coding: utf-8 -*-
"""v18：由 **v17** 生成 —— 把本轮最硬的发现「**按解身份比较**」写进正文与规格。

依据：INDEX §241（撤回 1.82×）、§243（零求解解身份探针：几何相同、单网格同名，但硬编码选择集跨解失效）。

正文 1 处插入（§5 新增 **Solution identity** 段）＋补充材料 3 处（§S9 句升级、§S12 的 T3/T5 行）
＋补充材料**另存新名**并追加 **§S13**。
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
V17 = REPO / "docs/PAPER_DAC2027_EN_v17_20261013.md"
V18 = REPO / "docs/PAPER_DAC2027_EN_v18_20261013.md"
V18P = REPO / "docs/PAPER_DAC2027_EN_v18_PROVENANCE.md"
SUPD = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013d.md"
SUPE = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013e.md"
OUT = REPO / "work/runs/eda64-20261010/n5_stage3"

B_OLD = ("**not** change with the solved frequency.")
B_NEW = ("**not** change with the solved frequency.\n"
         "\n"
         "**Solution identity.** Every comparison in this paper is made on an identified solution: its\n"
         "solution tag, the mesh that solution stored, and a parameter read-back at the design point. This is\n"
         "stricter than matching element counts, because one model file can carry solutions whose stored\n"
         "meshes number their entities differently, so a post-processing selection that is valid for one\n"
         "solution can silently address different faces on another. We verified this on a four-solution file\n"
         "whose solutions share an identical geometry (fluid volume equal to ten digits) and an identical\n"
         "parameter read-back, yet disagree by a factor **6.7** in an electrode-area probe evaluated from a\n"
         "hard-coded entity list (§S13). Where a comparison spans two model files, both are named by content\n"
         "hash, not by file name.")

S_OLD = ("A single model file can therefore contain solutions computed on **different meshes**, so solutions "
         "must be compared by degrees of freedom, not by file name.")
S_NEW = ("A single model file can therefore contain solutions computed on **different meshes**, so solutions "
         "must be compared by degrees of freedom, not by file name. §S13 sharpens this further: the same file "
         "can also carry solutions whose **stored meshes number their entities differently**, so a "
         "post-processing selection that is valid for one solution can silently address different faces on "
         "another. Comparisons must therefore be made on **solution identity** — tag, stored mesh, and a "
         "re-resolved selection — not merely on a matched element count.")

T3_OLD = ("| T3 | conditional regression on the two formal targets | (x, N1, N2) | median relative error with the "
          "count of defined rows, plus `lift_paired` against persistence | abstain outside the measured grid | §6.3 |")
T3_NEW = ("| T3 | conditional regression on the two formal targets | (x, N1, N2) **plus a solution identity** "
          "(tag, stored mesh, parameter read-back) | median relative error with the count of defined rows, plus "
          "`lift_paired` against persistence | abstain outside the measured grid, and refuse any comparison whose "
          "solutions fail the identity check (§S13) | §6.3, §S13 |")

T5_OLD = ("| T5 | refusal behaviour | a proposal set | accepted and refused counts with reasons, and the "
          "false-accept rate at three tolerances | refuse when the applicability test fails | §6.2, §6.6 |")
T5_NEW = ("| T5 | refusal behaviour | a proposal set, plus each solution's identity (§S13) | accepted and refused "
          "counts with reasons, and the false-accept rate at three tolerances | refuse when the applicability test "
          "fails, or when a solution identity check fails | §6.2, §6.6, §S13 |")

S13 = """## S13. Solution identity: why matching element counts is not enough

One model file can hold several solutions. Across this work we met that three times, and each time the
comparison caliber had to be tightened:

| occasion | what differed between the solutions | how it showed up |
|---|---|---|
| S4 ladder history | the **mesh** (359,711 vs 900,431 degrees of freedom) | residual rows that look comparable but are not |
| closed-loop review | the **design state** (two drive-electrode areas) | an apparent 1.8× discrepancy between two carriers |
| this section | the **stored mesh's entity numbering** | a probe that is valid for one solution silently addresses different faces on another |

The first two are reported in §S9 and §S11. The third was isolated with a zero-solve probe on a file that
carries four solutions, all at the same design point and the same frequency (20 MHz):

| solution | frequencies in the solution | fluid-domain volume (m³) | electrode-area probe from a hard-coded entity list | mean electrode potential (V) |
|---|---:|---:|---:|---:|
| 1 | 7 (5–35 MHz) | 2.094393557e−12 | 3.5467e−09 | 8.2248e−03 |
| 2 | 7 (5–35 MHz) | 2.094393557e−12 | 3.5467e−09 | 8.0439e−02 |
| 3 | 7 (5–35 MHz) | 2.094393557e−12 | 3.5467e−09 | 8.2248e−03 |
| 4 | 1 (20 MHz) | 2.094393557e−12 | **5.3201e-10** | **2.9744e−02** |

All four solutions share an **identical geometry** — the fluid-domain volume agrees to ten digits — and the
file contains a **single mesh object** whose current state is the one the paper's calibers specify. The
parameters read back at the design point (`x_scale` 0.6, two integer layer counts) are the same for all
four. Yet an integral taken over a **hard-coded list of boundary entities** differs by a factor **6.667**
between solution 1 and solution 4, and the mean electrode potential by a factor 3.6. With geometry, mesh
object and parameters identical, the only consistent explanation is that the same entity numbers address
**different physical faces** on the two solutions' stored meshes — solutions created by different studies
before and after a re-mesh. Any quantity evaluated through such a list is therefore comparable only within
one stored mesh.

**The rule we adopt.** A comparison is admissible only if it is made on an identified solution, and
identity requires all four of: (i) the solution tag; (ii) the mesh that solution stored; (iii) a
parameter read-back at the design point; (iv) a **geometric invariant** — an integral that depends only on
the geometry, such as the fluid-domain volume — that must agree across the objects being compared. Where a
quantity must be read from stored solutions, the selections are re-resolved on the target solution's mesh
rather than copied from another; where that is impossible, the quantity is re-solved instead of re-used.

**Reproduction.** The probe is read-only: it loads the model, enumerates the solutions and studies, creates
one result dataset per solution, and evaluates only integrals. It performs no solve and writes no model.
Running it costs under a minute on a 96-core node, and it is the check we now apply before quoting any
cross-solution or cross-file number.

**Not claimed.** That the discarded readings were physically wrong: they are simply not comparable to the
retained ones. Nor that the first three solutions' originating setup can be reconstructed from the file —
it cannot, which is exactly why the identity has to be recorded alongside the result rather than recovered
later. This section adds no physics; it is a bookkeeping rule that the earlier discrepancy shows is
load-bearing.
"""


def main() -> int:
    src = V17.read_text(encoding="utf-8")
    sup = SUPD.read_text(encoding="utf-8")
    for nm, t in (("v17", src), ("supd", sup)):
        if "\r\n" in t:
            raise SystemExit("[FAIL] %s 含 CRLF" % nm)
    sha17 = hashlib.sha256(V17.read_bytes()).hexdigest()
    sha_d = hashlib.sha256(SUPD.read_bytes()).hexdigest()

    body = src
    n = body.count(B_OLD)
    if n != 1:
        raise SystemExit("[FAIL] 正文锚点命中 %d 次" % n)
    body = body.replace(B_OLD, B_NEW)
    sup_new = sup
    for label, old, new in (("S9", S_OLD, S_NEW), ("T3", T3_OLD, T3_NEW), ("T5", T5_OLD, T5_NEW)):
        c = sup_new.count(old)
        if c != 1:
            raise SystemExit("[FAIL] 补充材料 %s 锚点命中 %d 次" % (label, c))
        sup_new = sup_new.replace(old, new)
    sup_new = sup_new + "\n\n" + S13

    V18.write_bytes(body.encode("utf-8"))
    SUPE.write_bytes(sup_new.encode("utf-8"))
    db, ds = V18.read_bytes(), SUPE.read_bytes()
    if b"\r\n" in db or b"\r\n" in ds:
        raise SystemExit("[FAIL] 输出出现 CRLF")
    dt, st = db.decode("utf-8"), ds.decode("utf-8")
    if dt.replace(B_NEW, B_OLD) != src:
        raise SystemExit("[FAIL] 正文往返未还原 v17")
    tail = "\n\n" + S13
    if not st.endswith(tail):
        raise SystemExit("[FAIL] 补充材料尾部不是 §S13")
    head = st[:-len(tail)]
    for label, old, new in (("S9", S_OLD, S_NEW), ("T3", T3_OLD, T3_NEW), ("T5", T5_OLD, T5_NEW)):
        if head.count(new) != 1:
            raise SystemExit("[FAIL] 头部新锚点 %s 计数 %d" % (label, head.count(new)))
    back = head.replace(S_NEW, S_OLD).replace(T3_NEW, T3_OLD).replace(T5_NEW, T5_OLD)
    if back != sup:
        raise SystemExit("[FAIL] 头部逆替换未逐字节还原 v17 时代件（有未登记的改动）")
    delta = sum(len(new) - len(old) for old, new in ((S_OLD, S_NEW), (T3_OLD, T3_NEW), (T5_OLD, T5_NEW)))
    if len(head) - len(sup) != delta:
        raise SystemExit("[FAIL] 头部长度差 %d ≠ 替换增量 %d" % (len(head) - len(sup), delta))
    print("补充材料结构：尾部 §S13 ✓；头部逆替换逐字节还原 ✓（长度差 %+d）" % delta)
    for must in ("**Solution identity.**", "factor **6.7**", "(§S13)",
                 "both are named by content\nhash, not by file name."):
        if must not in dt:
            raise SystemExit("[FAIL] 正文缺必需项：%s" % must)
    for must in ("§S13 sharpens this further", "**plus a solution identity**",
                 "or when a solution identity check fails", "## S13. Solution identity",
                 "6.667", "geometric invariant", "**Not claimed.**"):
        if must not in st:
            raise SystemExit("[FAIL] 补充材料缺必需项：%s" % must)
    for pat in (r"work[/\\]runs", r"work/dist", r"docs/", r"\bsha256\b", r"[0-9a-f]{32,}",
                r"\bnode0\d\b", r"\bINDEX\b", r"peakguard-bench"):
        if re.search(pat, dt) or re.search(pat, st):
            raise SystemExit("[FAIL] 双盲泄漏：%s" % pat)

    wc = lambda s: len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-\./%]*", s[:s.find("## Content Generated by AI")]))
    w17, w18 = wc(src), wc(dt)
    rep = {"kind": "dac2027_en_v18_generation", "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "source": V17.name, "source_sha256": sha17, "source_bytes": len(V17.read_bytes()),
           "output": V18.name, "output_sha256": hashlib.sha256(db).hexdigest(),
           "output_bytes": len(db), "output_eol": "LF",
           "supplement_source": SUPD.name, "supplement_source_sha256": sha_d,
           "supplement_output": SUPE.name, "supplement_output_sha256": hashlib.sha256(ds).hexdigest(),
           "supplement_output_bytes": len(ds), "supplement_output_eol": "LF",
           "replacements": {"body_solution_identity_paragraph": 1, "supplement_S9_sentence": 1,
                            "supplement_T3_row": 1, "supplement_T5_row": 1},
           "body_words_v17": w17, "body_words_v18": w18, "body_words_delta": w18 - w17,
           "roundtrip_restores_v17": True, "supplement_is_v17_text_plus_S13": True,
           "double_blind_clean": True,
           "content_added": ["body §5: Solution identity paragraph (tag + stored mesh + parameter read-back + geometric invariant)",
                             "supplement §S9: sharpened statement pointing to §S13",
                             "supplement §S12: T3/T5 now require a solution identity",
                             "supplement §S13: four-solution table, the 6.667x probe, the adopted rule, reproduction and non-claims"],
           "not_added": "no new physics, no threshold change, no new measurement"}
    if hashlib.sha256(V18.read_bytes()).hexdigest() != rep["output_sha256"]:
        raise SystemExit("[FAIL] 报告哈希与磁盘不一致")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "V18_GENERATION_REPORT.json").write_bytes(
        (json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    V18P.write_bytes(f"""# v18 出处说明（DAC 2027 英文稿）

- 生成：{time.strftime("%Y-%m-%d")}；由 **v17**（`{V17.name}`，sha256 `{sha17[:24]}`，{len(V17.read_bytes())} B）
  经 **1 处正文插入 + 3 处补充材料替换**生成。
- 产物：`{V18.name}`（sha256 `{rep["output_sha256"][:24]}`，{rep["output_bytes"]} B，**LF**）。
- 补充材料**另存新名**：`{SUPE.name}`（sha256 `{rep["supplement_output_sha256"][:24]}`，{len(ds)} B）
  ＝ **v17 时代件原文 + §S13**；`{SUPD.name}`（`{sha_d[:24]}`）保留。
- 正文词数：v17 **{w17}** → v18 **{w18}**（{w18 - w17:+d}）。
- **自检**：从磁盘回读；正文反向替换**逐字节还原 v17**；补充材料按「原文 + §S13」逐字节校验；**双盲扫描干净**。

## 折入了什么

本轮最硬的一条发现（INDEX §241 撤回、§243 探针）：**同一 `.mph` 内可以有多个解，其存储网格的实体编号不同**
⇒ 用**硬编码实体号**做的后处理在解之间不可比（实测电极面积探针差 **6.667×**、电位差 3.6×，而四解的
**流体域体积逐位相同**、**只有一个网格对象**、参数读回一致）。

1. **正文 §5 新增「Solution identity」段**：一切对照都在**已识别的解**上进行（sol tag + 该解存储的网格 +
   设计点参数读回），并给出那 6.7× 的实测；跨文件对照一律按**内容哈希**指名，不按文件名。
2. **补充材料 §S9**：原句「按自由度比较、不按文件名」**升级**并指向 §S13。
3. **§S12 的 T3/T5**：任务输入与拒答规则**加入解身份要求**（身份核不过 ⇒ 拒答）。
4. **补充材料新增 §S13**：四解对照表 + 探针 + **采纳的规则**（四项身份 + 几何不变量）+ 复现方式 + 不主张。

## 边界与不主张

- **不新增任何物理结论、不改任何阈值、不新增任何测量**；除上述四处外**一字未动**；
- 不主张被丢弃的读数在物理上是错的（只主张**不可比**）；不主张能从文件重建那三个解的来源设置（**不能**）；
- 页数：正文 **{w18}** 词（比 v6 的 4,463 长 {w18 - 4463:+d}）；**本机无 TeX，页数未编译验证**。
""".encode("utf-8"))

    print("v17 %d B（sha %s）→ v18 %d B（sha %s）" % (len(V17.read_bytes()), sha17[:16],
                                                   len(db), rep["output_sha256"][:16]))
    print("补充材料：%s（%d B，sha %s）＝ v17 时代件 + §S13" % (SUPE.name, len(ds), rep["supplement_output_sha256"][:16]))
    print("正文词数 v17 %d → v18 %d（%+d）" % (w17, w18, w18 - w17))
    print("自检：往返还原 v17 ✓；补充材料结构 ✓；双盲干净 ✓；无 CRLF ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
