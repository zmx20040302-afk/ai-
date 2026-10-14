# -*- coding: utf-8 -*-
"""核验并集表 v3 是否满足 O-A，并检查 dup_kind 的区分能力（只读）。

用法：
  work\\.venv\\Scripts\\python.exe -X utf8 work\\tools\\verify_v3_oa.py

只读：不写任何表、不改任何行。
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
V3 = REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv"


def sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def norm(v: str) -> str:
    """身份键的 ulp 归一化：round 6。"""
    try:
        return repr(round(float(v), 6))
    except (TypeError, ValueError):
        return "?" + str(v)


def main() -> int:
    out: dict = {}
    out["v3_path"] = str(V3.relative_to(REPO))
    out["v3_sha256"] = sha256(V3)

    with V3.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    hdr = list(rows[0].keys())
    out["n_rows"] = len(rows)
    out["n_cols"] = len(hdr)
    out["columns"] = hdr

    # --- 批行数
    batch_ct = collections.Counter(r["batch"] for r in rows)
    out["batch_counts"] = dict(sorted(batch_ct.items()))
    out["batch_counts_sum"] = sum(batch_ct.values())

    # --- 标记列非空计数
    for col in ("dup_of", "dup_kind", "dup_score"):
        if col not in hdr:
            out.setdefault("missing_columns", []).append(col)
            continue
        ne = sum(1 for r in rows if str(r[col]).strip() != "")
        out["nonempty_" + col] = ne
    # dup_score 的取值分布（它可能用 0 表示无重复）
    if "dup_score" in hdr:
        out["dup_score_value_counts"] = dict(
            sorted(collections.Counter(str(r["dup_score"]).strip() or "<empty>"
                                       for r in rows).items(),
                   key=lambda kv: (-kv[1], kv[0])))
    if "dup_kind" in hdr:
        vc = collections.Counter(str(r["dup_kind"]).strip() or "<empty>" for r in rows)
        out["dup_kind_value_counts"] = dict(sorted(vc.items(), key=lambda kv: (-kv[1], kv[0])))

    # --- 身份键与组合
    key = lambda r: (norm(r["x_scale"]), norm(r["N_w_te1"]), norm(r["N_w_te2"]))  # noqa: E731
    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    out["n_unique_combos"] = len(groups)
    out["rows_minus_combos"] = len(rows) - len(groups)

    # --- 跨批组合：同一组合的行来自 >1 个批
    cross = {k: v for k, v in groups.items() if len({r["batch"] for r in v}) > 1}
    out["n_cross_batch_combos"] = len(cross)
    cross_rows = sum(len(v) for v in cross.values())
    out["n_rows_in_cross_batch_combos"] = cross_rows
    out["overlap_rows_normalized"] = cross_rows - len(cross)

    # --- 每批恰一栅格？
    grid_by_batch: dict[str, set] = collections.defaultdict(set)
    for r in rows:
        grid_by_batch[r["batch"]].add(norm(r["freq_grid_MHz"]))
    out["freq_grid_by_batch"] = {k: sorted(v) for k, v in sorted(grid_by_batch.items())}

    # --- dup_of 指向性：dup_of 非空的行数与「组内非首位」关系
    #     dup_of 取值形如 "batch|x|N1|N2" 还是行号？先看样例与取值形态
    sample = [r["dup_of"] for r in rows if str(r["dup_of"]).strip() != ""][:5]
    out["dup_of_samples"] = sample
    sample_k = [r["dup_kind"] for r in rows if str(r["dup_kind"]).strip() != ""][:5]
    out["dup_kind_samples"] = sample_k

    # --- dup_kind 的区分能力：对每个跨批组合，看组内各行 dup_kind 的组合
    same_grid_same_combo = 0
    diff_grid_same_combo = 0
    kinds_for_cross: collections.Counter = collections.Counter()
    for k, v in cross.items():
        grids = {norm(r["freq_grid_MHz"]) for r in v}
        kinds = tuple(sorted({str(r["dup_kind"]).strip() or "<empty>" for r in v}))
        kinds_for_cross[kinds] += 1
        if len(grids) == 1:
            same_grid_same_combo += 1
        else:
            diff_grid_same_combo += 1
    out["cross_same_grid_combos"] = same_grid_same_combo
    out["cross_diff_grid_combos"] = diff_grid_same_combo
    out["cross_batch_dup_kind_kindsets"] = {
        " | ".join(k): n for k, n in kinds_for_cross.most_common()}

    # --- 「仅 ulp 差」与「原样重复」：看同一组合内非归一化键是否相同
    exact_dup_rows = 0
    for k, v in groups.items():
        raw = collections.Counter(
            (r["x_scale"], r["N_w_te1"], r["N_w_te2"]) for r in v)
        exact_dup_rows += sum(c - 1 for c in raw.values() if c > 1)
    out["rows_exact_key_dup"] = exact_dup_rows

    # --- 完全重复行（所有列逐位相同）
    seen = collections.Counter(tuple(r[c] for c in hdr) for r in rows)
    out["fully_identical_row_dups"] = sum(c - 1 for c in seen.values() if c > 1)

    # --- Q 达标（Q in [2.5, 3.5]）按批分组
    qgate: dict[str, dict] = {}
    for b in sorted(batch_ct):
        sub = [r for r in rows if r["batch"] == b]
        ok = 0
        invalid = 0
        for r in sub:
            try:
                q = float(r["Q"])
            except (TypeError, ValueError):
                invalid += 1
                continue
            if 2.5 <= q <= 3.5:
                ok += 1
        qgate[b] = {"rows": len(sub), "q_in_2.5_3.5": ok, "q_unparsable": invalid}
    out["q_gate_by_batch"] = qgate

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
