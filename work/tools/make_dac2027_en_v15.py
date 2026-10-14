# -*- coding: utf-8 -*-
"""v15：由 **v14** 生成 —— 更正**拆分描述**（与实测不符）并折入 M1 证据。

背景（INDEX §234）：论文 §4.1 写「grouped, leakage-free splits in which an entire combination key
(geometry family) belongs either to training or to hold-out」，**与实测不符**：
  * 实际分组变量是**重复簇**（`dup_score ≥ 1`，541/2,255 = 24 %），不是 geometry family；
  * 精确重复泄漏**结构性为 0**（每个 (cell, x) 组合唯一）；
  * 但**不是 x 不相交**：C 批 x 步长 0.01，**91 %** 的 holdout 行在 train 里有相邻格邻居。

正文 5 处单命中替换 + 补充材料**另存新名**（`…_20261013c.md`）并追加 §S11。
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
V14 = REPO / "docs/PAPER_DAC2027_EN_v14_20261013.md"
V15 = REPO / "docs/PAPER_DAC2027_EN_v15_20261013.md"
V15P = REPO / "docs/PAPER_DAC2027_EN_v15_PROVENANCE.md"
SUP14 = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013b.md"
SUP15 = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013c.md"
OUT = REPO / "work/runs/eda64-20261010/n5_stage3"

A_OLD = ("under leakage-free grouped\n"
         "splits with five seeds and eight methods none beats a persistence baseline on either formal target;")
A_NEW = ("under duplicate-aware grouped\n"
         "splits with five seeds and eight methods none beats a persistence baseline on either formal target;")

C_OLD = ("compare eight methods against persistence under leakage-free grouped\n"
         "   splits with five seeds, reporting the channels that gain nothing instead of a pooled score.")
C_NEW = ("compare eight methods against persistence under duplicate-aware grouped\n"
         "   splits with five seeds, reporting the channels that gain nothing instead of a pooled score.")

S_OLD = ("**Splits.** All learned models use grouped, leakage-free splits in which an entire combination key\n"
         "(geometry family) belongs either to training or to hold-out; five split seeds are used. The split\n"
         "assignment is an external artifact whose training/test key sets are disjoint for every seed.")
S_NEW = ("**Splits.** All learned models share one external split artifact with five seeds. Its grouping variable\n"
         "is **duplicate clusters, not geometry families**: near-duplicate rows (541 of 2,255, 24 %) stay on one\n"
         "side, so contamination through *exactly repeated* design points is structurally zero (each geometry\n"
         "cell and continuous-coordinate combination occurs once). The split is **not** disjoint along the\n"
         "continuous axis: at the C batch's step of 0.01, **91 %** of held-out rows have a training neighbour\n"
         "one grid step away (87 % and 90 % in the two coarser batches, step 0.1). We state this because\n"
         "\"grouped\" must name what it groups — this split removes duplicate leakage, not interpolation\n"
         "leakage — and because a size-matched uniform random split is geometrically equivalent to it\n"
         "(adjacent-step fraction within 4 points) yet moves the median error of 9 of 63 C-batch cells by more\n"
         "than 10 % in both directions, so the residual spread is split-realization noise rather than an\n"
         "effect of the grouping rule (§S11).")

G_OLD = ("Under leakage-free grouped splits, per-batch training, and five seeds, 20 channel×batch cells are\n"
         "decidable. For the two formal targets the outcome is negative and consistent across seeds:")
G_NEW = ("Under duplicate-aware grouped splits (§4.1), per-batch training, and five seeds, 20 channel×batch\n"
         "cells are decidable. For the two formal targets the outcome is negative and consistent across seeds:")

P_OLD = ("but these are precisely the channels whose persistence baseline is weak because adjacent integer\n"
         "layers differ substantially.")
P_NEW = ("but these are precisely the channels whose persistence baseline is weak because adjacent integer\n"
         "layers differ substantially. Counting every channel, 8 of the 20 decidable cells admit no method that\n"
         "beats persistence in the median (three channels in each of A and C, two in V2), and the size-matched\n"
         "random split of §S11 gives 7: the two rules agree, so the negative result is not an artefact of the\n"
         "split rule.")

REPS = [("A_abstract", A_OLD, A_NEW), ("B_contributions_C3", C_OLD, C_NEW),
        ("C_splits_paragraph", S_OLD, S_NEW), ("D_sec63_opening", G_OLD, G_NEW),
        ("E_sec63_count", P_OLD, P_NEW)]

S11 = """

## S11. What the split actually groups, and how much the verdict moves

The registered split artifact groups **duplicate clusters**, not geometry families: near-duplicate rows
(541 of 2,255, 24 %; exact-key, rounded-key and last-place-unit duplicates) are kept on one side. Because
every (geometry cell, continuous-coordinate) combination occurs exactly once in the corpus, contamination
through exactly repeated design points is structurally zero — the *strict* leakage measure is 0 % for
**every** batch and both split rules. What is *not* removed is leakage along the continuous axis: a
held-out row can have a training neighbour one grid step away. Measured, relative to each batch's own grid
step (0.1 in the two coarser batches, 0.01 in batch C):

| batch | x grid step | exact-key overlap | adjacent-step train neighbour, registered / random |
|---|---:|---:|---:|
| A | 0.100 | 0 % | 87.3 % / 83.1 % |
| C | 0.010 | 0 % | 91.1 % / 92.2 % |
| V2 | 0.100 | 0 % | 89.7 % / 89.0 % |

**Counterfactual split.** We rebuilt the split as a uniform random assignment per batch and per seed,
holding the per-batch training/holdout sizes, the code, the hyper-parameters, the metric and the row set
fixed, so that *only which rows are held out* changes. The two arms are geometrically equivalent (the
adjacent-step fraction differs by at most 4 points, above), and the per-cell comparison is:

| batch | cells | random improves >10 % | random worsens >10 % | median ratio | across-seed s.d., registered / random |
|---|---:|---:|---:|---:|---:|
| A | 63 | 14 | 6 | 0.979 | 0.0038 / 0.0042 |
| C | 63 | 5 | 4 | 0.992 | 0.0010 / 0.0010 |
| V2 | 31 | 10 | 7 | 0.963 | 0.0169 / 0.0192 |

The movement is two-sided and the across-seed spread is the same size in both arms, so the differences are
**split-realization noise, not an effect of the grouping rule**. This matters for how the negative
persistence result is read: it is *not* an artefact of having chosen a grouped split, because the
size-matched random split reproduces it — 8 of the 20 decidable channel×batch cells admit no method that
beats persistence under the registered split and 7 of 20 under the random one (three channels in each of A
and C, two in V2, under the registered split). Conversely, no result in this paper may be read as
"x-adjacency leakage was excluded": it was not, and the batch-C fraction above is the honest measure of what
the split does and does not remove. The full per-cell table, the split-reproduction check (all fifteen
per-batch/per-seed sizes reproduce the registered artifact exactly) and the random assignment's fixed
generator recipe are recorded in the internal evidence companion.
"""


def rep_once(t: str, old: str, new: str, label: str) -> str:
    n = t.count(old)
    if n != 1:
        raise SystemExit("[FAIL] %s 锚点命中 %d 次（要求 1）" % (label, n))
    return t.replace(old, new)


def main() -> int:
    src = V14.read_text(encoding="utf-8")
    sup = SUP14.read_text(encoding="utf-8")
    for nm, t in (("v14", src), ("sup14", sup)):
        if "\r\n" in t:
            raise SystemExit("[FAIL] %s 含 CRLF" % nm)
    sha14 = hashlib.sha256(V14.read_bytes()).hexdigest()
    sha_sup14 = hashlib.sha256(SUP14.read_bytes()).hexdigest()

    body = src
    for label, old, new in REPS:
        body = rep_once(body, old, new, label)
    sup_new = sup + S11

    V15.write_bytes(body.encode("utf-8"))
    SUP15.write_bytes(sup_new.encode("utf-8"))
    db, ds = V15.read_bytes(), SUP15.read_bytes()
    if b"\r\n" in db or b"\r\n" in ds:
        raise SystemExit("[FAIL] 输出出现 CRLF")
    dt, st = db.decode("utf-8"), ds.decode("utf-8")
    back = dt
    for _, old, new in REPS:
        back = back.replace(new, old)
    if back != src:
        raise SystemExit("[FAIL] 正文往返未还原 v14")
    if st[:len(sup)] != sup or st[len(sup):] != S11:
        raise SystemExit("[FAIL] 补充材料不是「原文 + §S11」")
    for must in ("duplicate-aware grouped splits", "duplicate clusters, not geometry families",
                 "91 %", "87 % and 90 %", "split-realization noise", "8 of the 20 decidable cells",
                 "the size-matched\nrandom split of §S11 gives 7", "(§S11)"):
        if must not in dt:
            raise SystemExit("[FAIL] 正文缺必需项：%s" % must)
    if "leakage-free grouped" in dt:
        raise SystemExit("[FAIL] 正文仍含「leakage-free grouped」")
    for must in ("## S11.", "91.1 % / 92.2 %", "split-realization noise"):
        if must not in st:
            raise SystemExit("[FAIL] 补充材料缺必需项：%s" % must)
    for pat in (r"work[/\\]runs", r"docs/", r"\bsha256\b", r"[0-9a-f]{32,}", r"\bnode0\d\b", r"\bINDEX\b"):
        if re.search(pat, dt) or re.search(pat, st):
            raise SystemExit("[FAIL] 双盲泄漏：%s" % pat)

    wc = lambda s: len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-\./%]*", s[:s.find("## Content Generated by AI")]))
    w14, w15 = wc(src), wc(dt)
    rep = {"kind": "dac2027_en_v15_generation", "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "source": V14.name, "source_sha256": sha14, "source_bytes": len(V14.read_bytes()),
           "output": V15.name, "output_sha256": hashlib.sha256(db).hexdigest(),
           "output_bytes": len(db), "output_eol": "LF",
           "supplement_source": SUP14.name, "supplement_source_sha256": sha_sup14,
           "supplement_output": SUP15.name, "supplement_output_sha256": hashlib.sha256(ds).hexdigest(),
           "supplement_output_bytes": len(ds), "supplement_output_eol": "LF",
           "replacements": {label: 1 for label, _, _ in REPS},
           "body_words_v14": w14, "body_words_v15": w15, "body_words_delta": w15 - w14,
           "roundtrip_restores_v14": True, "supplement_is_v14_text_plus_S11": True,
           "double_blind_clean": True,
           "content_changed": ["split description corrected: grouping variable = duplicate clusters (not geometry families)",
                               "disclosed: exact-key leakage 0 %; x-adjacent leakage 91 % in batch C (87/90 % in A/V2)",
                               "added: size-matched random split is geometrically equivalent; 9/63 C cells move >10 % both ways; 8 vs 7 of 20 persistence cells",
                               "abstract / contributions / §6.3 wording: 'leakage-free grouped' -> 'duplicate-aware grouped'",
                               "supplement: new §S11 with the geometry and counterfactual tables"]}
    if hashlib.sha256(V15.read_bytes()).hexdigest() != rep["output_sha256"]:
        raise SystemExit("[FAIL] 报告哈希与磁盘不一致")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "V15_GENERATION_REPORT.json").write_bytes(
        (json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    V15P.write_bytes(f"""# v15 出处说明（DAC 2027 英文稿）

- 生成：{time.strftime("%Y-%m-%d")}；由 **v14**（`{V14.name}`，sha256 `{sha14[:24]}`，{len(V14.read_bytes())} B）
  经 **5 处**单命中字面替换生成。
- 产物：`{V15.name}`（sha256 `{rep["output_sha256"][:24]}`，{rep["output_bytes"]} B，**LF**）。
- 补充材料**另存新名**：`{SUP15.name}`（sha256 `{rep["supplement_output_sha256"][:24]}`，{len(ds)} B）——
  **v14 时代版本保留**为 `{SUP14.name}`（`{sha_sup14[:24]}`）；新件 = 该件原文 + **§S11**。
- 正文词数：v14 **{w14}** → v15 **{w15}**（{w15 - w14:+d}）。
- **自检**：从磁盘回读；反向替换**逐字节还原 v14**；补充材料按「原文 + §S11」逐字节校验；**双盲扫描干净**。

## 改了什么，为什么

**这是一个事实更正**：论文原写「grouped, leakage-free splits in which an entire combination key
(geometry family) belongs either to training or to hold-out」——**与实测不符**（依据 INDEX §234 / M1）：

1. 分组变量实际是**重复簇**（`dup_score ≥ 1`，**541/2,255 = 24 %**），不是 geometry family；
2. **精确重复泄漏结构性为 0**（每个 (cell, x) 组合唯一）—— 这点协议是干净的，保留主张；
3. 但**不是 x 不相交**：C 批 x 步长 **0.01**，**91 %** 的留出行在 train 里有相邻格邻居（A/V2 步长 0.1，为 87 %/90 %）；
4. **规模对齐的随机拆分与注册拆分几何等价**（相邻格比例差 ≤4 pp），却使 C 批 **9/63** 个格子的中位误差变动 >10 %（双向），
   两臂种子间波动同量级 ⇒ 残差是**拆分实现噪声**，不是分组规则效应；
5. 因此「无方法胜过 persistence」的负结果**不是拆分规则造成的**：注册拆分 **8/20** 格、随机拆分 **7/20** 格。

## 边界与不主张

- **不改任何图表**；除上述 5 处与 §S11 外**一字未动**；**不新增结论**；**不改任何阈值**；
- **不主张**「x 邻接泄漏已排除」（恰恰相反，已在正文与 §S11 披露）；
- 页数：正文 **{w15}** 词（比 v6 的 4,463 长 {w15 - 4463:+d}）；**本机无 TeX，页数未编译验证**（削减块见 INDEX §228）。
""".encode("utf-8"))

    print("v14 %d B（sha %s）→ v15 %d B（sha %s）" % (len(V14.read_bytes()), sha14[:16],
                                                   len(db), rep["output_sha256"][:16]))
    print("补充材料：%s（%d B，sha %s）＝ v14 时代件 + §S11" % (SUP15.name, len(ds), rep["supplement_output_sha256"][:16]))
    print("正文词数 v14 %d → v15 %d（%+d）；5 处替换各命中 1 次" % (w14, w15, w15 - w14))
    print("自检：往返还原 v14 ✓；补充材料结构 ✓；双盲干净 ✓；无 CRLF ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
