# -*- coding: utf-8 -*-
"""English rendering of the frozen calibration strings.

WHY THIS FILE EXISTS
The task outputs were produced by an internal pipeline whose free-text fields (calibers, non-claims,
per-cell notes) were written in Chinese. This package is an English-language artifact for anonymous
review, so those strings are rendered in English by an explicit, auditable table — applied to **both**
the produced outputs (each task calls `to_en` before writing) and the expected values
(`build_expected_tasks.py` applies the same table). Numbers, key names and structure are untouched:
only the *values* of these free-text strings change, and they change identically on both sides, so the
deep comparison in `check_tasks.py` still passes and no number moves.

SCOPE AND HONESTY
* This is a **rendering**, not a retranslation of the science: each entry says the same thing the Chinese
  string said, including its hedging and its `**emphasis**`.
* Strings not in the table pass through unchanged. `unmapped_cjk()` reports any Chinese text that is
  still present, so a missed string is detectable rather than silent.
* The table is intentionally a *whole-string* map: partial substitution would be ambiguous.
"""
from __future__ import annotations

import re

CJK = re.compile(r"[\u4e00-\u9fff]")
# For the fail-closed check: ideographs **plus** CJK punctuation and fullwidth forms. A string can carry
# fullwidth parentheses or commas while containing no ideograph at all, and such text still has no place
# in an English artifact.
CJK_WIDE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")

MAP = {
    # ---- M1 (split ablation, V2 mechanism check) ----
    "**评测结论对拆分实现不稳定**（该结论有证据，逐批方向见下表）；但「随机拆分系统性改变结论」**未获支持**：两臂在 A_5-35MHz、C_5-50MHz、V2_5-35MHz 上的 x 邻接比例几乎相同，差异方向双向，不能排除拆分实现噪声。 **另有一条对我们自己协议的新发现**：主批 C 的 x 网格步长是 **0.01**，而注册拆分的 holdout 中有 **91.1 %** 的行在 train 里有**相邻格**邻居（两臂皆然）⇒ 该「grouped」拆分只挡住**重复簇/跨批重复**泄漏，**没有**挡住 x 邻接插值泄漏。":
        "**The evaluation verdict is unstable across split realisations** (that finding has evidence; the "
        "per-batch direction is in the table below). But \"a random split systematically changes the "
        "verdict\" is **not supported**: the two arms' x-adjacency fractions are almost identical on "
        "A_5-35MHz, C_5-50MHz and V2_5-35MHz, the differences run in both directions, and split-"
        "implementation noise cannot be excluded. **One further finding about our own protocol**: the C "
        "batch's x grid step is **0.01**, yet **91.1 %** of the registered split's held-out rows have a "
        "**one-step** training neighbour (true for both arms) => the \"grouped\" split blocks only "
        "**duplicate-cluster / cross-batch duplicate** leakage; it does **not** block x-adjacency "
        "interpolation leakage.",

    "V1 按**预注册规则**触发；V2 追加**事后**机制核对后发现：两臂在**三个批**上的「x 相邻格」比例几乎相同（Δ ≤ 4.2 pp）⇒ 差异**不能归因于分组规则**。并且查明注册的「grouped」拆分实际按**重复簇**分组（`dup_score ≥ 1`，541 行 / 24 %），并不阻断主批 C 的 **x 邻接插值泄漏（约 91 %）**——原描述「an entire combination key (geometry family)」与实测不符。":
        "V1 triggered under the **pre-registered rule**. V2 added a **post-hoc** mechanism check and found "
        "that the two arms' x-adjacent fractions are almost identical on **all three batches** "
        "(delta <= 4.2 pp) => the difference **cannot be attributed to the grouping rule**. V2 also "
        "established that the registered \"grouped\" split actually groups by **duplicate clusters** "
        "(`dup_score >= 1`, 541 rows / 24 %) and does not block the C batch's **x-adjacency interpolation "
        "leakage (~91 %)** — the earlier description \"an entire combination key (geometry family)\" does "
        "not match the measurement.",

    "V1 的**预注册判定不被改写**：它按规则触发了，这一点保留在原件里；":
        "The V1 **pre-registered verdict is not rewritten**: it triggered by rule, and that stands in the "
        "original record;",

    "V2 的机制核对是**事后**的，故 V2 的结论标为更正结论而非新预注册；":
        "The V2 mechanism check is **post-hoc**, so the V2 conclusion is labelled a correction rather "
        "than a new pre-registration;",

    "不主张「随机拆分一定更乐观」；不主张「grouped 拆分已无泄漏」（恰恰相反，见 geometry）；":
        "No claim that \"a random split is necessarily more optimistic\"; no claim that \"the grouped "
        "split is free of leakage\" (the opposite holds — see geometry);",

    "两臂在该批的 x 邻接（按网格步长相对化）几乎相同 ⇒ 该批差异**不能归因于分组规则**":
        "The two arms' x-adjacency on this batch (relativised by the grid step) is almost identical "
        "=> this batch's difference **cannot be attributed to the grouping rule**",

    "随机指派按预注册 RNG 配方复现，15/15 逐批行数与注册件一致 ✓":
        "Random assignment reproduced under the pre-registered RNG recipe; per-batch row counts match "
        "the registered artifact 15/15 ✓",

    "常规随机评测会给出不同结论":
        "a conventional random evaluation would reach a different conclusion",

    # ---- M2 (risk-coverage) ----
    "s_i = |pred_i − pers_i| / truth_i（模型与强基线的分歧，归一化）":
        "s_i = |pred_i - pers_i| / truth_i (normalised disagreement between the model and the strong "
        "baseline)",

    "arm G（注册 grouped split）":
        "arm G (the registered grouped split)",

    "只报**预注册的那一个** score，不主张已找到最优评分函数；":
        "Reports **only the one pre-registered** score; no claim that the optimal scoring function has "
        "been found;",

    "**不**主张这是区间校准：S5 的区间覆盖率是**另一口径**，本节的 score-coverage 不得与 S5 混称；":
        "**Not** claimed to be interval calibration: S5's interval coverage is a **different caliber**, "
        "and the score-coverage here must not be conflated with S5;",

    # ---- M3 (cross-batch transfer) ----
    "within-batch 参照取自注册件（arm G），未重跑":
        "the within-batch reference is taken from the registered artifact (arm G) and was not re-run",

    "**不设通过/失败阈值**（预注册写死为描述性证据）；":
        "**No pass/fail threshold is set** (the pre-registration fixes this as descriptive evidence);",

    "不得据此声称泛化能力或 OOD 检测性能；":
        "must not be used to claim generalisation ability or OOD-detection performance;",

    "测试侧用**整批**未 quarantine 行（跨批语义下该批整体未见）；train 侧用该批**全部**行；":
        "The test side uses the **whole** non-quarantined batch (under cross-batch semantics that batch is "
        "entirely unseen); the train side uses **all** rows of that batch;",

    "零求解、未改任何既有件；逐批逐通道陈述，不池化。":
        "Zero solves and no existing artifact modified; stated per batch and per channel, with no pooling.",

    # ---- T1/T2 (classification) ----
    "V2_5-35MHz（代理标志）":
        "V2_5-35MHz (proxy flags)",

    "hgb 的平衡精度高于多数类基线（但仍须看逐状态 recall）":
        "hgb balanced accuracy exceeds the majority-class baseline (per-state recall must still be read)",

    "未检出显著抬高（降幅 ≤ 0.03）":
        "no significant inflation detected (reduction <= 0.03)",

    # ---- T5 (refusal behaviour) ----
    "本件**描述性**、不设通过/失败阈值；逐批逐通道、不池化；":
        "This artifact is **descriptive** and sets no pass/fail threshold; per batch and per channel, "
        "with no pooling;",

    "**未预测 ≠ 正确**：拒答覆盖率与被接受子集上的精度/容差必须并置读；":
        "**Unpredicted is not correct**: refusal coverage and the accuracy/tolerance on the accepted "
        "subset must be read side by side;",

    "不主张拒答机制已最优（只评已注册机制）；零 COMSOL 求解。":
        "No claim that the refusal mechanism is optimal (only the registered mechanism is evaluated); "
        "zero COMSOL solves.",

    "逐批逐通道陈述，不池化、不给加权总分；零求解、未改任何既有件。":
        "Stated per batch and per channel; no pooling and no weighted total; zero solves and no existing "
        "artifact modified.",

    "零求解、未改任何既有件。":
        "Zero solves and no existing artifact modified.",

    # ---- corpus / channel labels ----
    "无数据（某侧缺该通道）":
        "no data (this channel is absent on that side)",

    # ---- T7 replay: fields the port adds (not present in the registered artifact) ----
    "n_solves 恒为 0：本件不含任何求解器调用路径（无外部进程 / 专有求解器 / 模型文件）。":
        "n_solves is always 0: this artifact contains no solver invocation path (no external process, "
        "no proprietary solver, no model file).",

    "DOE 5 次 + A1 5 种子×5 次 + A2/A3/A4 种子 0 各 25 次 + A2/A3/A4 种子 1-4 各 5 次 = 165 次调用":
        "DOE 5 calls + A1 5 seeds x 5 calls + A2/A3/A4 seed 0 x 25 calls each + A2/A3/A4 seeds 1-4 x 5 "
        "calls each = 165 calls",

    "注册 LEDGER 投影的 (arm,seed,k) 覆盖实测反推（PREREG.calls_per_seed 不足以表达）":
        "reverse-engineered from the observed (arm,seed,k) coverage of the registered ledger projection "
        "(the pre-registration's calls_per_seed cannot express it)",

    "batch C_5-50MHz 语料覆盖的 (N_w_te1, N_w_te2) 对（冻结常量）":
        "the (N_w_te1, N_w_te2) pairs covered by the C_5-50MHz corpus (frozen constants)",
}

# Second level: substring rendering, for **composed** strings that embed data (a whole-string table
# cannot hold them, because they change when the data changes). Applied only to strings with no exact
# entry. Order matters: longer, more specific fragments first.
SEGMENTS = {
    "（原生标志只含 A/C）": " (native flags cover A/C only)",
    "（V2 代理标志不参与）": " (V2 proxy flags excluded)",
    "（唯一 x 步长 0.01 的批）": " (the only batch with x step 0.01)",
    "，": ", ",
}


def _render(s: str) -> str:
    if s in MAP:
        return MAP[s]
    out = s
    for zh, en in SEGMENTS.items():
        if zh in out:
            out = out.replace(zh, en)
    return out


def to_en(o):
    """Recursively replace mapped strings. Values only; keys and numbers are untouched."""
    if isinstance(o, str):
        return _render(o)
    if isinstance(o, dict):
        return {k: to_en(v) for k, v in o.items()}
    if isinstance(o, list):
        return [to_en(v) for v in o]
    if isinstance(o, tuple):
        return tuple(to_en(v) for v in o)
    return o


def unmapped_cjk(o, path="", out=None):
    """Every string still containing Chinese after `to_en`, with its path. Empty list == fully English."""
    out = [] if out is None else out
    if isinstance(o, dict):
        for k, v in o.items():
            unmapped_cjk(v, path + "." + str(k), out)
    elif isinstance(o, (list, tuple)):
        for i, v in enumerate(o):
            unmapped_cjk(v, path + "[]", out)
    elif isinstance(o, str) and CJK.search(o):
        out.append((path, o))
    return out


if __name__ == "__main__":
    import json
    import sys
    print("entries:", len(MAP), "| segments:", len(SEGMENTS))
    print("self-check: no Chinese left in any mapped value:",
          not any(CJK_WIDE.search(v) for v in MAP.values()))
    print("self-check: no Chinese left in any segment rendering:",
          not any(CJK_WIDE.search(v) for v in SEGMENTS.values()))
    print("self-check: no duplicate English renderings:",
          len(set(MAP.values())) == len(MAP))
    if len(sys.argv) > 1:                      # 传入一个结果 JSON 即可体检
        d = json.loads(open(sys.argv[1], encoding="utf-8").read())
        left = unmapped_cjk(to_en(d))
        print("unmapped CJK strings:", len(left))
        for p, s in left[:20]:
            print("   ", p, "->", s[:90])
