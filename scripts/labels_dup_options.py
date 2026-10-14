# -*- coding: utf-8 -*-
"""去重规则的**选项评估**：只算影响，**不执行任何一条**。

输入 = v3 并集表（`batch` 已改为一批一栅格），**只读**。
输出 = `dedup_options.md` ＋ `dedup_options.json`（落在 `--out-dir`，缺省与输入表同目录）。

纪律：

* **不写任何表**：本脚本只做假想规则下的**计数**（在内存里算），
  绝不删除/改写并集表、冻结副本或 C 批原表（红线：去重规则待用户拍板）；
* 每个选项都给**具体数字**：行数、组合数、逐批保留/丢弃行数、下游 Q 门槛计数；
* 每个选项都给**风险**，尤其「是否可能静默丢掉 A 的 162 行那类已登记数据」——
  该 162 在建表时已登记（`multichannel_coverage.json`：
  「同参数不同批**各占一行**，**禁止**字典合并（会静默丢掉 A 的 162 行）」）。
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import labels_two_batch as L2                                          # noqa: E402

DEFAULT_TABLE = (REPO / "work/runs/labels-two-batch-v3/20261008T170435"
                 / "labels_two_batch.csv")
A_LABEL, C_LABEL, V2_LABEL = "A_5-35MHz", "C_5-50MHz", "V2_5-35MHz"

RULES = [
    {"id": "O-A", "kind": "none",
     "name": "不去重（现状）＋ `dup_of` 标记 ＋ **统计一律按批分组**",
     "rule": "保留全部 2255 行；用已有的 `dup_score` / `dup_of` / `dup_kind` 标记重叠；"
             "任何统计/排名按 `batch` 分列，禁止池化。"},
    {"id": "O-B", "kind": "priority", "order": [C_LABEL, A_LABEL, V2_LABEL],
     "name": "每组合留一行；优先级 **C > A > V2**（即「重叠归 C/A 优先、V2 只留新增」）",
     "rule": "同一（ulp 归一化）组合只保留**一行**，优先级 `C_5-50MHz` > `A_5-35MHz` "
             "> `V2_5-35MHz`。"},
    {"id": "O-C", "kind": "priority", "order": [A_LABEL, C_LABEL, V2_LABEL],
     "name": "每组合留一行；优先级 **A > C > V2**（保 5–35 同栅格可比、保 A 全部已登记行）",
     "rule": "同一组合只保留一行，优先级 `A_5-35MHz` > `C_5-50MHz` > `V2_5-35MHz`。"},
    {"id": "O-D", "kind": "exact_only",
     "name": "只删**完全重复行**（所有列逐位相同）",
     "rule": "仅当同一组合内两行**所有列逐位相同**时删去后来的那一行；"
             "任何一列不同即保留。"},
]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def evaluate(rows: list[dict], rule: dict, decimals: int) -> dict:
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(rows):
        groups.setdefault(L2._identity(r, decimals), []).append(i)
    keep: set[int] = set()
    if rule["kind"] == "none":
        keep = set(range(len(rows)))
    elif rule["kind"] == "priority":
        rank = {b: i for i, b in enumerate(rule["order"])}
        for _, idxs in groups.items():
            keep.add(min(idxs, key=lambda j: (rank.get(rows[j]["batch"], 99), j)))
    elif rule["kind"] == "exact_only":
        for _, idxs in groups.items():
            seen: list[int] = []
            for j in idxs:
                if any(all(str(rows[j].get(c, "")) == str(rows[k].get(c, ""))
                           for c in rows[j]) for k in seen):
                    continue
                seen.append(j)
            keep.update(seen)
    else:  # pragma: no cover
        raise ValueError(rule["kind"])

    kept = [rows[i] for i in range(len(rows)) if i in keep]
    dropped = [rows[i] for i in range(len(rows)) if i not in keep]
    batches = sorted({r["batch"] for r in rows})

    def cnt(rs, b):
        return sum(1 for r in rs if r["batch"] == b)

    def qgate(rs, b):
        return sum(1 for r in rs if r["batch"] == b and _f(r["Q"]) is not None
                   and L2.Q_LO <= _f(r["Q"]) <= L2.Q_HI)

    survivor_mix = {}
    if rule["kind"] == "priority":
        for _, idxs in groups.items():
            b = rows[min(idxs, key=lambda j: (
                {x: i for i, x in enumerate(rule["order"])}.get(rows[j]["batch"], 99), j))]["batch"]
            survivor_mix[b] = survivor_mix.get(b, 0) + 1
    return {
        "rule_id": rule["id"],
        "n_kept_rows": len(kept),
        "n_dropped_rows": len(dropped),
        "n_unique_combos": len({L2._identity(r, decimals) for r in kept}),
        "kept_rows_by_batch": {b: cnt(kept, b) for b in batches},
        "dropped_rows_by_batch": {b: cnt(dropped, b) for b in batches},
        "Q_in_gate_by_batch_after_rule": {b: qgate(kept, b) for b in batches},
        "Q_in_gate_by_batch_before_rule": {b: qgate(rows, b) for b in batches},
        "survivor_batch_mix": survivor_mix,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default=str(DEFAULT_TABLE))
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--decimals", type=int, default=L2.IDENTITY_ROUND_DECIMALS)
    a = ap.parse_args(argv)
    t = pathlib.Path(a.table)
    if not t.exists():
        print("[FAIL] 未找到 v3 并集表：%s" % t)
        return 2
    rows = list(csv.DictReader(t.open("r", encoding="utf-8", newline="")))
    if not rows:
        print("[FAIL] 输入为 0 行 ⇒ 空集判失败")
        return 2
    outdir = pathlib.Path(a.out_dir) if a.out_dir else t.parent
    if not outdir.is_absolute():
        outdir = REPO / outdir
    outdir.mkdir(parents=True, exist_ok=True)

    batches = sorted({r["batch"] for r in rows})
    base = {"n_rows": len(rows),
            "n_unique_combos": len({L2._identity(r, a.decimals) for r in rows}),
            "rows_by_batch": {b: sum(1 for r in rows if r["batch"] == b) for b in batches}}
    evals = [evaluate(rows, r, a.decimals) for r in RULES]
    for r, e in zip(RULES, evals):
        e["name"] = r["name"]
        e["rule"] = r["rule"]

    payload = {
        "kind": "dedup_options_analysis",
        "input_table": L2._rel(t),
        "input_sha256": L2.sha256_file(t),
        "executed": False,
        "executed_note": "**本文件只是选项评估，未执行任何去重**；并集表一行未删、一字节未改。",
        "identity_key": {"param_keys": ["x_scale", "N_w_te1", "N_w_te2"],
                         "ulp_decimals": a.decimals},
        "baseline": base,
        "options": evals,
        "registered_constraint": {
            "source": "work/runs/first-peak-20260929/multichannel_coverage.json",
            "text": "同参数不同批**各占一行**，**禁止**字典合并（会静默丢掉 A 的 162 行）",
            "implication": "任何把同一组合并成一行的选项，只要丢弃的是 A 行，"
                           "就**与已登记的建表规则冲突**，必须先由人明确推翻该登记；"
                           "本脚本不做该判断。",
        },
    }
    (outdir / "dedup_options.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        "# 去重规则**选项评估**（只出选项，**不执行**）",
        "",
        "> 输入（只读）：`%s`" % L2._rel(t),
        "> sha256 `%s`" % payload["input_sha256"],
        "> 身份键 = (`x_scale`, `N_w_te1`, `N_w_te2`)，先做 ulp 归一化（round 6）。",
        "> **本文不执行任何去重**：下表数字都是在内存里假想规则算出来的；并集表一行未删。",
        "",
        "## 0. 基线（不去重）",
        "",
        "| 项 | 值 |",
        "|---|---|",
        "| 总行数 | **%d** |" % base["n_rows"],
        "| 唯一组合数 | **%d** |" % base["n_unique_combos"],
        "| 重复行余量（行数 − 组合数） | **%d** |"
        % (base["n_rows"] - base["n_unique_combos"]),
    ]
    for b in batches:
        md.append("| `%s` 行数 | %d |" % (b, base["rows_by_batch"][b]))
    md += [
        "",
        "## 1. 选项一览（每个选项的具体数字影响）",
        "",
        "| 选项 | 保留行数 | 丢弃行数 | 组合数 | A 保留/丢弃 | C 保留/丢弃 | V2 保留/丢弃 |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in evals:
        k, d = e["kept_rows_by_batch"], e["dropped_rows_by_batch"]
        md.append("| **%s** %s | %d | **%d** | %d | %d / **%d** | %d / **%d** | %d / **%d** |"
                  % (e["rule_id"], e["name"], e["n_kept_rows"], e["n_dropped_rows"],
                     e["n_unique_combos"], k[A_LABEL], d[A_LABEL], k[C_LABEL], d[C_LABEL],
                     k[V2_LABEL], d[V2_LABEL]))
    md += ["", "### 1.1 各选项的规则原文", ""]
    for e in evals:
        md += ["- **%s**：%s" % (e["rule_id"], e["rule"])]
    md += [
        "",
        "### 1.2 每个组合由哪一批的行代表（O-B / O-C 的差别就在这 162 个组合上）",
        "",
        "| 选项 | 代表行来自 A | 来自 C | 来自 V2 |",
        "|---|---|---|---|",
    ]
    for e in evals:
        if e["survivor_batch_mix"]:
            m = e["survivor_batch_mix"]
            md.append("| **%s** | %d | %d | %d |"
                      % (e["rule_id"], m.get(A_LABEL, 0), m.get(C_LABEL, 0),
                         m.get(V2_LABEL, 0)))
    md += [
        "",
        "## 2. 对下游统计的影响（Q∈[2.5,3.5] 计数，**按批分列、不给合成数**）",
        "",
        "| 选项 | A 达标 | C 达标 | V2 达标 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for e in evals:
        q = e["Q_in_gate_by_batch_after_rule"]
        q0 = e["Q_in_gate_by_batch_before_rule"]
        delta = {b: q[b] - q0[b] for b in batches}
        md.append("| **%s** | %d（%+d） | %d（%+d） | %d（%+d） | 括号 = 相对不去重的变化 |"
                  % (e["rule_id"], q[A_LABEL], delta[A_LABEL], q[C_LABEL], delta[C_LABEL],
                     q[V2_LABEL], delta[V2_LABEL]))
    md += [
        "",
        "## 3. 风险（逐条写清，尤其**静默丢掉已登记数据**的风险）",
        "",
        "- **O-A（不去重）**：风险最低、信息最全，但 **`batch` 不能当防泄漏的整组切分键**"
        "（329 行的组合跨批）；下游必须按 `dup_of` 分组，否则同组合同时进训练/留出集。"
        "无任何行被丢弃。",
        "- **O-B（C > A > V2）**：丢弃 **329** 行，其中 **A 丢 162 行**（A 只剩 61 行）。"
        "这 162 行正是 `multichannel_coverage.json` 已登记为「同参数不同批各占一行」的数据 ⇒"
        "**该选项与已登记规则冲突**，执行前必须由人明确推翻登记，否则就是**静默丢掉已登记数据**。"
        "另：这 162 个组合的代表行将由 **C 的 5–50/91** 承担，其 Q 与 A 侧的 Q 并非同一管线"
        "（§92.3 更正二：Q 中位相对差 19%、89.5% 的组合差超 5%）⇒ **排名会随选项变化**。",
        "- **O-C（A > C > V2）**：同样丢弃 **329** 行，但丢的是 **C 的 162 行**；"
        "A 的 223 行**全部保留**（不违反上述登记）。代价：这 162 个组合的代表行变成"
        "**A 的 5–35/61 粗栅格**，而 C 侧原表带 **`q_gate_pass` 权威列**（§92.2 逐行对账 728）——"
        "该权威列在这 162 个组合上**失去代表行**；且 35 MHz 上限会**高估宽度、压低 Q**"
        "（§92.2），使这 162 个组合的 Q 门槛结果偏向不可比。",
        "- **O-D（只删完全重复行）**：丢弃 **%d** 行 ⇒ **实际上什么都没做**。"
        "它的价值是**量化**：按最严判据「全列逐位相同」在 v3 表里**没有可删的行**"
        "（§93.1：完全重复行 0），所以「安全去重」在本数据上**买不到任何行数下降**。"
        "风险：若把它当成「已去重」，会误以为 `batch` 恢复成合法切分键 —— **并非如此**。"
        % [e for e in evals if e["rule_id"] == "O-D"][0]["n_dropped_rows"],
        "",
        "## 4. 结论（**不替用户拍板**）",
        "",
        "- 若目标是「**不丢任何已登记数据**」：只有 **O-A** 与 **O-C** 满足（O-C 丢的是 C 侧行，"
        "但那 162 个组合的 C 侧 `q_gate_pass` 权威列随之失去代表 ⇒ 仍需人判断）。",
        "- 若目标是「**尽可能少丢**」：**O-D** 丢 0 行，但没有解决跨批重叠 ⇒ `batch` 仍不能作切分键。",
        "- 若目标是「**让每个组合只有一行、且优先保留宽窗口**」：**O-B**，代价是丢 A 的 162 行。",
        "- **任何一条都不得由智能体自行执行**：本文件只登记选项与数字；"
        "去重与切分规则须用户拍板（§92.7 待办 2 / §93.7 第 1 条）。",
        "",
    ]
    (outdir / "dedup_options.md").write_text("\n".join(md), encoding="utf-8")

    print("== 去重选项评估（**未执行任何去重**）==")
    print("  基线：%d 行 / %d 组合（余量 %d）"
          % (base["n_rows"], base["n_unique_combos"],
             base["n_rows"] - base["n_unique_combos"]))
    for e in evals:
        print("  %s：保留 %d 行（丢 %d）｜ A 保留 %d 丢 %d ｜ C 保留 %d 丢 %d ｜ V2 保留 %d 丢 %d"
              % (e["rule_id"], e["n_kept_rows"], e["n_dropped_rows"],
                 e["kept_rows_by_batch"][A_LABEL], e["dropped_rows_by_batch"][A_LABEL],
                 e["kept_rows_by_batch"][C_LABEL], e["dropped_rows_by_batch"][C_LABEL],
                 e["kept_rows_by_batch"][V2_LABEL], e["dropped_rows_by_batch"][V2_LABEL]))
    print("选项清单：%s" % L2._rel(outdir / "dedup_options.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
