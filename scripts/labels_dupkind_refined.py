# -*- coding: utf-8 -*-
"""为并集表 **v3** 追加**一个派生标记列** `dup_kind_refined`（**只追加列，不改行、不改已有列**）。

背景（§94 / §94.4 已登记）：
* v3（`work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv`，2255 行 × 30 列）
  已按 **O-A（不去重、一行不删）** 落表，并带 `dup_score` / `dup_of` / `dup_kind` 三个标记列。
* `dup_kind` 只编码「逐对内容差异类型（`exact_duplicate_row` / `marker_columns_only` /
  `measurement_differs`）＋ 对方批次」，**区分不了**下列两类跨批同组合：
  ① 同栅格同组合 vs 不同栅格同组合；② 身份键**原样相同** vs **仅 ulp 归一化后相同**。
  ⇒ 本脚本追加 `dup_kind_refined` 补齐这两维（第三维沿用 `dup_kind` 的既有判据）。

## `dup_kind_refined` 判据（逐行、逐对；非重复行留空）

对每一行 `i`，取本表内与它共享同一 **ulp 归一化（round 6）** 组合键的**其他行** `j`，
每对产出一个 token（`;` 连接、排序后写入本行）：

```text
<grid_rel>|<key_rel>|<content_rel>@<other_batch>
```

| 位置 | 取值 | 判据 |
|---|---|---|
| `grid_rel` | `grid_same` | `freq_grid_MHz` **原样字符串**相等且非空 |
| | `grid_same_empty` | 两侧都为空（本表实测 0 对，登记为边界） |
| | `grid_diff` | 上述不成立 |
| `key_rel` | `key_str_same` | `x_scale` / `N_w_te1` / `N_w_te2` 三列**原样字符串**逐字相等 |
| | `key_repr_same` | 字符串不同，但门禁 `n_overlap_raw` 口径相等（`repr(_num(·))` 相同，**表示差**，如 `0.20` vs `0.2`） |
| | `key_ulp_only` | 上述都不成立，但 `round(_num(·), 6)` 相等（**真 ulp 差**） |
| `content_rel` | `exact_duplicate_row` | `labels_two_batch.COMPARE_COLUMNS` 全部逐字相等 |
| | `marker_columns_only` | 差异列 ⊆ `labels_two_batch.MARKER_COLUMNS` |
| | `measurement_differs` | 其余（差异落到测量类列） |
| `other_batch` | 对方行的 `batch` | — |

* **`key_rel` 的三级不可合并**：门禁 `check_batch_isolation` 的 `n_overlap_raw`（`repr(_num(·))`）
  与「字符串逐字相同」**不是一回事**；把两者混称「原样」会把**表示差**（`0.20` vs `0.2`）
  误报成 **1 ulp 差**。三级口径恰好可与门禁 `446 / 386 / 162` 逐级对上（见 `dup_kind_refined.md`）。
* 判据里的 `COMPARE_COLUMNS` / `MARKER_COLUMNS` / `_identity` / `_identity_key` / `_num`
  **直接 import 原脚本**，不另写一套（避免口径漂移）。
* **不删行、不改任何既有列的取值、不重排行序**；输出写到**新目录**，v3 原表**只读**。

## fail-closed 守卫

1. 输入 v3 的 sha256 必须等于登记值 `20e28ba1…`，否则退出码 2、**不出表**；
2. 输出行数必须等于输入行数、前 30 列逐行逐字相等，否则退出码 2、**不出表**；
3. 输出目录若已存在同名产物，**拒绝覆盖**（append-only）。
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as _dt
import hashlib
import importlib.util
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
V3 = REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv"
V3_SHA256 = "20e28ba12457ce5b553fce3d02c0e4f59e7861370775ecf4cf68b0dff6a3a590"
V3_ROWS = 2255
V3_COLS = 30
NEW_COLUMN = "dup_kind_refined"
EXIT_PASS, EXIT_INPUT = 0, 2


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def load_labels_two_batch():
    """import `scripts/labels_two_batch.py`（复用其常量与 `_identity`，不复制口径）。"""
    sys.path.insert(0, str(REPO / "src"))
    spec = importlib.util.spec_from_file_location(
        "_l2_for_dupkind", REPO / "scripts/labels_two_batch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # 该模块 main() 有 __main__ 守卫，import 无副作用
    return mod


def classify_pair(a: dict, b: dict, l2, sa) -> tuple[str, str, str]:
    """返回 (grid_rel, key_rel, content_rel)。"""
    ga, gb = str(a.get("freq_grid_MHz", "")), str(b.get("freq_grid_MHz", ""))
    if not ga and not gb:
        grid_rel = "grid_same_empty"
    elif ga == gb:
        grid_rel = "grid_same"
    else:
        grid_rel = "grid_diff"
    keys = ("x_scale", "N_w_te1", "N_w_te2")
    if all(str(a.get(k, "")) == str(b.get(k, "")) for k in keys):
        key_rel = "key_str_same"
    elif sa._identity_key(a, keys, None) == sa._identity_key(b, keys, None):
        key_rel = "key_repr_same"          # 门禁 n_overlap_raw 口径相等 ⇒ 表示差
    else:
        key_rel = "key_ulp_only"           # 已同组（round 6 归一化相等）⇒ 真 ulp 差
    if all(str(a.get(c, "")) == str(b.get(c, "")) for c in l2.COMPARE_COLUMNS):
        content = "exact_duplicate_row"
    else:
        dcols = [c for c in l2.COMPARE_COLUMNS if str(a.get(c, "")) != str(b.get(c, ""))]
        content = ("marker_columns_only" if set(dcols) <= set(l2.MARKER_COLUMNS)
                   else "measurement_differs")
    return grid_rel, key_rel, content


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v3", default=str(V3))
    ap.add_argument("--out-dir", default=None,
                    help="缺省 work/runs/labels-dupkind-refined/<ts>/")
    a = ap.parse_args(argv)

    v3p = pathlib.Path(a.v3)
    if not v3p.is_absolute():
        v3p = REPO / v3p
    if not v3p.exists():
        print("[FAIL] 输入 v3 表不存在：%s" % v3p)
        return EXIT_INPUT
    sha_in = sha256_file(v3p)
    if sha_in != V3_SHA256:
        print("[FAIL] v3 sha256 与登记值不符：实测 %s ≠ 登记 %s ⇒ 不出表（不猜）"
              % (sha_in, V3_SHA256))
        return EXIT_INPUT

    with v3p.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    cols = list(rows[0].keys())
    if len(rows) != V3_ROWS or len(cols) != V3_COLS:
        print("[FAIL] 输入形状与登记不符：%d 行 / %d 列（登记 %d / %d）"
              % (len(rows), len(cols), V3_ROWS, V3_COLS))
        return EXIT_INPUT
    if NEW_COLUMN in cols:
        print("[FAIL] 输入表已含 %r —— 拒绝重复追加" % NEW_COLUMN)
        return EXIT_INPUT

    l2 = load_labels_two_batch()
    from memsharness import sweep_analysis as sa

    # ---- 分组（口径与 v3 的 dup_* 完全同源：L2._identity，round 6）----
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(rows):
        groups.setdefault(l2._identity(r), []).append(i)

    n_groups = n_rows_in_groups = 0
    key_level_pairs: collections.Counter = collections.Counter()
    examples: dict[str, list] = collections.defaultdict(list)
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        n_groups += 1
        n_rows_in_groups += len(idxs)
        for i in idxs:
            toks = []
            for j in idxs:
                if j == i:
                    continue
                g, k, c = classify_pair(rows[i], rows[j], l2, sa)
                toks.append("%s|%s|%s@%s" % (g, k, c, rows[j]["batch"]))
                if i < j:            # 每对只计一次
                    key_level_pairs[k] += 1
                    if len(examples[k]) < 3:
                        examples[k].append({
                            "batch_a": rows[i]["batch"], "batch_b": rows[j]["batch"],
                            "key_a": [rows[i][x] for x in ("x_scale", "N_w_te1", "N_w_te2")],
                            "key_b": [rows[j][x] for x in ("x_scale", "N_w_te1", "N_w_te2")],
                        })
            rows[i][NEW_COLUMN] = ";".join(sorted(toks))
    for i, r in enumerate(rows):
        r.setdefault(NEW_COLUMN, "")

    # ---- 回读自校验：前 30 列必须逐行逐字等于 v3 ----
    with v3p.open(encoding="utf-8", newline="") as fh:
        orig = list(csv.DictReader(fh))
    bad = [i for i, (x, y) in enumerate(zip(orig, rows))
           if any(str(x[c]) != str(y[c]) for c in cols)]
    if bad or len(orig) != len(rows):
        print("[FAIL] 前 %d 列出现差异行（%d 行）⇒ 拒绝出表" % (len(cols), len(bad)))
        return EXIT_INPUT

    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    outdir = (pathlib.Path(a.out_dir) if a.out_dir
              else REPO / "work/runs/labels-dupkind-refined" / ts)
    if not outdir.is_absolute():
        outdir = REPO / outdir
    outdir.mkdir(parents=True, exist_ok=True)
    csvp = outdir / "labels_two_batch_dupkind_refined.csv"
    if csvp.exists():
        print("[FAIL] 产物已存在，拒绝覆盖（append-only）：%s" % csvp)
        return EXIT_INPUT

    out_cols = cols + [NEW_COLUMN]
    with csvp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=out_cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in out_cols})

    # ---- 分布 ----
    vc = collections.Counter(r[NEW_COLUMN] or "<empty>" for r in rows)
    tok_ct: collections.Counter = collections.Counter()
    for r in rows:
        for t in (r[NEW_COLUMN].split(";") if r[NEW_COLUMN] else []):
            tok_ct[t] += 1
    dim = collections.Counter()
    for r in rows:
        for t in (r[NEW_COLUMN].split(";") if r[NEW_COLUMN] else []):
            g, k, c = t.split("@")[0].split("|")
            dim["grid_rel=" + g] += 1
            dim["key_rel=" + k] += 1
            dim["content_rel=" + c] += 1

    rep = {
        "kind": "dup_kind_refined_view",
        "note": "**派生标记视图**：v3 的 30 列逐字原样 ＋ 追加 1 列 %s。"
                "本文件**不是**新的并集表/标签表 —— O-A 的载体仍是 v3；本视图**一行未删、"
                "未改任何既有列取值、未重排行序**（已逐行逐字回读校验）。" % NEW_COLUMN,
        "input": {"path": str(v3p.relative_to(REPO)) if v3p.is_relative_to(REPO) else str(v3p),
                  "sha256": sha_in, "n_rows": len(orig), "n_cols": len(cols)},
        "output": {"path": str(csvp.relative_to(REPO)), "sha256": sha256_file(csvp),
                   "bytes": csvp.stat().st_size,
                   "n_rows": len(rows), "n_cols": len(out_cols)},
        "identity_key": {"param_keys": ["x_scale", "N_w_te1", "N_w_te2"],
                         "ulp_decimals": l2.IDENTITY_ROUND_DECIMALS,
                         "note": "与 v3 的 dup_* 同源：直接 import scripts/labels_two_batch.py；"
                                 "key_rel 的中间级复用门禁 sweep_analysis._identity_key(·, None)"},
        "rule": "<grid_rel>|<key_rel>|<content_rel>@<other_batch>；逐对、`;` 连接、排序；"
                "非重复行留空。grid_rel ∈ {grid_same, grid_same_empty, grid_diff}；"
                "key_rel ∈ {key_str_same, key_repr_same, key_ulp_only}；content_rel ∈ "
                "{exact_duplicate_row, marker_columns_only, measurement_differs}。",
        "counts": {"n_rows": len(rows), "n_rows_empty": vc.get("<empty>", 0),
                   "n_dup_groups": n_groups, "n_rows_in_dup_groups": n_rows_in_groups},
        "key_level_pairs": {"note": "每对只计一次；应与门禁的两两重叠 446 对上："
                                    "str_same=162、str+repr=386、三者合计=446",
                            "counts": dict(sorted(key_level_pairs.items())),
                            "str_same": key_level_pairs.get("key_str_same", 0),
                            "str_or_repr_same": (key_level_pairs.get("key_str_same", 0)
                                                 + key_level_pairs.get("key_repr_same", 0)),
                            "total_pairs": sum(key_level_pairs.values()),
                            "matches_gate_446": sum(key_level_pairs.values()) == 446,
                            "matches_gate_386": (key_level_pairs.get("key_str_same", 0)
                                                 + key_level_pairs.get("key_repr_same", 0)) == 386,
                            "matches_gate_str162": key_level_pairs.get("key_str_same", 0) == 162},
        "examples": {k: v for k, v in sorted(examples.items())},
        "value_counts": dict(sorted(vc.items(), key=lambda kv: (-kv[1], kv[0]))),
        "token_counts": dict(sorted(tok_ct.items(), key=lambda kv: (-kv[1], kv[0]))),
        "dimension_counts": dict(sorted(dim.items())),
        "verification": {
            "input_sha256_matches_registry": sha_in == V3_SHA256,
            "rows_unchanged": len(orig) == len(rows),
            "first_n_columns_byte_identical": not bad,
            "v3_untouched": sha256_file(v3p) == V3_SHA256,
            "deduplicated": False, "rows_dropped": 0,
        },
    }
    (outdir / "dup_kind_refined.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- 判据说明（markdown，与本 JSON 同源）----
    kl = rep["key_level_pairs"]
    lines = [
        "# `dup_kind_refined` 判据（v3 派生标记视图）",
        "",
        "> 输入（只读）：`%s`" % rep["input"]["path"],
        "> sha256 `%s`（**生成后复核仍为此值**：%s）"
        % (rep["input"]["sha256"], str(rep["verification"]["v3_untouched"]).lower()),
        "> 输出：`%s`（%d 行 × %d 列，sha256 `%s`）"
        % (rep["output"]["path"], rep["output"]["n_rows"], rep["output"]["n_cols"],
           rep["output"]["sha256"]),
        "",
        "**本视图只追加 1 列**: v3 的 30 列**逐字原样**、行序与行数不变（已逐行回读校验；"
        "**一行未删、未去重**）。O-A 的载体仍是 v3，本文件**不是**新的并集表/标签表。",
        "",
        "## 1. 为什么 `dup_kind` 不够",
        "",
        "`dup_kind` 的取值只有 `<content_rel>@<other_batch>`（`content_rel` ∈ "
        "`exact_duplicate_row` / `marker_columns_only` / `measurement_differs`）"
        "＋ `;` 连接、排序。它**区分不了**同一「跨批同组合」的另外两维：",
        "",
        "1. **栅格关系**：同栅格同组合（A 与 V2 同为 `5-35/61`）vs 不同栅格同组合"
        "（C 的 `5-50/91` 对上 A/V2 的 `5-35/61`）；",
        "2. **身份键表示差**：三列**原样字符串**是否逐字相同 —— `dup_kind` 完全不含这一信息；"
        "而它决定了「同一组合」是靠**字面**还是靠**归一化**才成立的。",
        "",
        "实测：跨批重复对共 **%d** 对，其中字面逐字相同只有 **%d** 对，"
        "另有 **%d** 对是**表示差**（`repr(_num(·))` 相同的 raw 口径）、**%d** 对是**真 ulp 差**。"
        "后两类在 `dup_kind` 里**长得一模一样**。"
        % (kl["total_pairs"], kl["str_same"], kl["counts"].get("key_repr_same", 0),
           kl["counts"].get("key_ulp_only", 0)),
        "",
        "## 2. 判据（逐行逐对；非重复行留空）",
        "",
        "```text",
        "<grid_rel>|<key_rel>|<content_rel>@<other_batch>",
        "```",
        "",
        "| 位置 | 取值 | 判据 |",
        "|---|---|---|",
        "| `grid_rel` | `grid_same` | `freq_grid_MHz` 原样字符串相等且非空 |",
        "| | `grid_same_empty` | 两侧都为空（本表 0 对） |",
        "| | `grid_diff` | 其余 |",
        "| `key_rel` | `key_str_same` | `x_scale`/`N_w_te1`/`N_w_te2` 三列**原样字符串**逐字相等 |",
        "| | `key_repr_same` | 字符串不同，但 `sweep_analysis._identity_key(·, None)` 相等"
        "（= 门禁 `n_overlap_raw` 口径，**表示差**） |",
        "| | `key_ulp_only` | 上述都不成立，但 `round(·, 6)` 相等（**真 ulp 差**） |",
        "| `content_rel` | `exact_duplicate_row` / `marker_columns_only` / "
        "`measurement_differs` | **沿用** `dup_kind` 的既有判据"
        "（`labels_two_batch.COMPARE_COLUMNS` / `MARKER_COLUMNS`） |",
        "| `other_batch` | 对方行的 `batch` | — |",
        "",
        "## 3. 与门禁数字的对账（独立口径，人工可复核）",
        "",
        "| 口径 | 本视图（逐对计一次） | 门禁 `batch_no_cross_batch_combo.detail` | 对上 |",
        "|---|---|---|---|",
        "| 字符串逐字相同 | **%d** | （门禁无此项） | — |" % kl["str_same"],
        "| `repr(_num())` 相同 | **%d** | `n_overlap_raw` **386** | **%s** |"
        % (kl["str_or_repr_same"], str(kl["matches_gate_386"]).lower()),
        "| round-6 归一化后相同 | **%d** | `n_overlap_normalized` **446** | **%s** |"
        % (kl["total_pairs"], str(kl["matches_gate_446"]).lower()),
        "",
        "门禁取数位置（只读复核）：`work/runs/labels-two-batch-v3/20261008T170618/"
        "VERSION_LTB3_v20261008T170618.json` → `gate.runs.{declared,row_grid}."
        "verdict.checks[batch_no_cross_batch_combo].detail`（两口径取值相同）。",
        "",
        "⇒ 「不做 ulp 归一化时新增数会虚高」那句话里的**raw 口径是 `repr` 口径**，"
        "**不是**字符串口径；两者相差 **%d** 对（表示差）。引用时必须写明。"
        % (kl["str_or_repr_same"] - kl["str_same"]),
        "",
        "## 4. 取值分布（行级，含空）",
        "",
    ]
    for k, v in rep["value_counts"].items():
        lines.append("- `%s`：**%d** 行" % (k, v))
    lines += ["", "## 5. 维度计数（token 级）", ""]
    for k, v in rep["dimension_counts"].items():
        lines.append("- `%s`：**%d** 个 token" % (k, v))
    lines += ["", "## 6. 各 `key_rel` 级样例（身份键三列原样）", ""]
    for k, exs in rep["examples"].items():
        lines.append("- **`%s`**：" % k)
        for e in exs:
            lines.append("  - `%s` %s vs `%s` %s"
                         % (e["batch_a"], e["key_a"], e["batch_b"], e["key_b"]))
    lines += [
        "",
        "## 7. 自校验",
        "",
        "```json",
        json.dumps(rep["verification"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 8. 未做",
        "",
        "- **未去重、未删行、未过滤、未提升任何状态、未放宽任何门禁**；",
        "- **未改 v3**（原表只读；生成后 sha256 复核仍为输入值）；",
        "- 本列**只是标记**：既不改变任何统计口径，也不构成「切分键」；"
        "`batch` **仍不得**当防泄漏整组切分键（§94.2 / §95）。",
        "",
    ]
    (outdir / "dup_kind_refined.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({"out_dir": str(outdir.relative_to(REPO)),
                      "csv": rep["output"], "counts": rep["counts"],
                      "key_level_pairs": rep["key_level_pairs"],
                      "value_counts": rep["value_counts"],
                      "v3_sha256_after": sha256_file(v3p)},
                     ensure_ascii=False, indent=2))
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
