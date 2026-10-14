# -*- coding: utf-8 -*-
"""跨批重叠的**逐 cell / 逐 x 分解**：把「重叠由参数栅格重合造成」从推断变成**可复算的计数**。

只读 v3 并集表（`batch` 已一批一栅格），输出 `overlap_by_cell.{json,md}` 到 `--out-dir`
（缺省与输入表同目录）。**不写表、不去重、不改任何既有产物。**

口径：组合身份键 = (`x_scale`, `N_w_te1`, `N_w_te2`)；三列**一律按数值**归一化
（`N_w_*` 取整数、`x_scale` 取 `round(x, decimals)`），与
`memsharness.sweep_analysis.check_batch_isolation` 的 `_num` 口径一致；
**不这样做会把 C 侧字面 `1.0` 与 v2 侧字面 `1` 判成两个组合**（实测）。
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import labels_two_batch as L2                                          # noqa: E402

DEFAULT_TABLE = (REPO / "work/runs/labels-two-batch-v3/20261008T170618"
                 / "labels_two_batch.csv")


def key_of(r: dict, decimals: int) -> tuple:
    def num(v):
        f = float(str(v).strip())
        return int(f) if f.is_integer() else round(f, decimals)
    return (num(r["x_scale"]), num(r["N_w_te1"]), num(r["N_w_te2"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default=str(DEFAULT_TABLE))
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--decimals", type=int, default=L2.IDENTITY_ROUND_DECIMALS)
    a = ap.parse_args(argv)
    t = pathlib.Path(a.table)
    if not t.exists():
        print("[FAIL] 未找到并集表：%s" % t)
        return 2
    rows = list(csv.DictReader(t.open("r", encoding="utf-8", newline="")))
    if not rows:
        print("[FAIL] 输入为 0 行 ⇒ 空集判失败")
        return 2
    outdir = pathlib.Path(a.out_dir) if a.out_dir else t.parent
    if not outdir.is_absolute():
        outdir = REPO / outdir
    outdir.mkdir(parents=True, exist_ok=True)

    sets: dict[str, set] = {}
    for r in rows:
        sets.setdefault(r["batch"], set()).add(key_of(r, a.decimals))
    labels = sorted(sets)
    overlap = {k for k in set().union(*sets.values())
               if sum(1 for b in labels if k in sets[b]) > 1}

    per_cell: dict[str, dict[str, int]] = {}
    x_values: dict[str, list] = {}
    for k in sorted(overlap):
        cell = "%s|%s" % (k[1], k[2])
        cls = "+".join(b for b in labels if k in sets[b])
        per_cell.setdefault(cell, collections.Counter())[cls] += 1
        x_values.setdefault(cls, [])
        x_values[cls].append(k[0])

    payload = {
        "kind": "overlap_by_cell",
        "input_table": L2._rel(t),
        "input_sha256": L2.sha256_file(t),
        "identity_key": {"param_keys": ["x_scale", "N_w_te1", "N_w_te2"],
                         "numeric_normalization": True,
                         "ulp_decimals": a.decimals},
        "n_overlapping_combos": len(overlap),
        "per_cell_counts": {c: dict(sorted(v.items())) for c, v in sorted(per_cell.items())},
        "classes": {c: len(v) for c, v in sorted(x_values.items())},
        "unique_x_per_class": {c: sorted(set(v)) for c, v in sorted(x_values.items())},
        "x_count_per_class": {c: len(sorted(set(v))) for c, v in sorted(x_values.items())},
        "multiplicity_per_class": {
            c: collections.Counter(v) and dict(sorted(collections.Counter(v).items()))
            for c, v in sorted(x_values.items())},
        "note": "每类的组合数 = Σ_cell (该 cell 上该类组合数)；"
                "「x 值个数」是**参与该类的唯一 x 取值个数**（同一 cell 上每个 x 记一次）。",
    }
    (outdir / "overlap_by_cell.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        "# 跨批重叠的**逐 (te1,te2) cell / 逐 x 分解**（只读）",
        "",
        "> 输入（只读）：`%s`" % payload["input_table"],
        "> sha256 `%s`" % payload["input_sha256"],
        "> 身份键三列**一律按数值**归一化（否则 C 侧 `1.0` 与 v2 侧 `1` 会被判成两个组合）。",
        "",
        "| 类别（涉及的批） | 组合数 | 唯一 x 取值个数 | 说明 |",
        "|---|---|---|---|",
    ]
    for c, n in sorted(payload["classes"].items(), key=lambda kv: -kv[1]):
        md.append("| `%s` | **%d** | %d | 见 `per_cell_counts` |"
                  % (c, n, payload["x_count_per_class"][c]))
    md += ["", "## 逐 cell 明细（每类在该 cell 上的组合数）", "",
           "| (te1,te2) | " + " | ".join("`%s`" % c for c in
                                         sorted(payload["classes"])) + " |",
           "|---" * (len(payload["classes"]) + 1) + "|"]
    for cell, cnt in sorted(payload["per_cell_counts"].items(),
                            key=lambda kv: (float(kv[0].split("|")[0]),
                                            float(kv[0].split("|")[1]))):
        md.append("| %s | %s |" % (cell.replace("|", ", "),
                                   " | ".join(str(cnt.get(c, 0))
                                              for c in sorted(payload["classes"]))))
    md += ["", "合计 **%d** 个组合出现在 ≥2 个批。" % payload["n_overlapping_combos"], ""]
    (outdir / "overlap_by_cell.md").write_text("\n".join(md), encoding="utf-8")

    print("== 跨批重叠逐 cell 分解（只读）==")
    for c, n in sorted(payload["classes"].items(), key=lambda kv: -kv[1]):
        print("  %-40s %4d 组合 ｜ 唯一 x %d 个"
              % (c, n, payload["x_count_per_class"][c]))
    print("  合计 %d" % payload["n_overlapping_combos"])
    print("产物：%s ／ %s" % (L2._rel(outdir / "overlap_by_cell.json"),
                            L2._rel(outdir / "overlap_by_cell.md")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
