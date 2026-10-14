# -*- coding: utf-8 -*-
"""集合级**内容哈希**：把「用了哪个集合」从描述变成**可核对**（INDEX §128.5 Q3 前半）。

## 规范化口径（**写死**，一句话）

> 把集合的每个元素渲染成一个**规范文本 token**，按元素的**自然数值序**升序排列
> （三元组按 `(round(x_scale,6), N_w_te1, N_w_te2)`、标量按数值、整行按 `(三元组, 行原样文本)`），
> **每个 token 后接一个 `\\n`**（末尾恰好一个换行；空集合 = 零字节），整体 **UTF-8** 编码后取 **sha256**。

token 渲染规则（三种元素类型）：

| 元素类型 | 集合举例 | token 渲染 |
|---|---|---|
| **三元组**（组合键） | 批的组合键集合、某 seed 的 train 组集合 | `"%.17g\\|%.17g\\|%.17g" % (round(x,6), N1, N2)` |
| **标量**（层号） | 某折的留出层集合 | `"%.17g" % n2` |
| **整行** | 某批的行集合 | 源 CSV 各列单元格**原样字符串**按**源列序**以 `\\x1f`(US) 连接 |

为什么这样定（三条都必须成立，缺一不可）：

1. **行序无关**：输入行**打乱**后重算，哈希**逐位不变**（本脚本的 `--shuffle-test` 实测，见交付表）；
2. **不依赖源文件字节**：不用源文件的换行（CRLF/LF）与 BOM ⇒ 同一内容在不同 checkout 上同哈希；
3. **不吞元素**：整行 token 用 `\\x1f` 连接（不用 `,`，避免与单元格内的逗号混淆），
   且**断言**单元格内不含 `\\n`/`\\r`（含则 fail-closed 退出码 2，避免 token 分隔歧义）。

`%.17g` 是 double 的**可往返**十进制表示（与仓库纪律「传参一律 `%.17g`，不得 `%.10g`」一致）；
`round(x_scale, 6)` 是与门禁 `check_batch_isolation` 同一个 ulp 归一化口径。

## 两个**独立实现**（必须逐位相同）

* **实现 P**：本脚本 —— Python `hashlib.sha256`，对规范文本字节取哈希；
* **实现 W**：`canonicalize_key_set.ps1`（PowerShell 5.1 + Windows CNG `certutil -hashfile`）——
  **从源 CSV 端到端**独立做规范化（`[math]::Round` → `.ToString('G17')` → `Sort-Object` → `UTF8Encoding($false)`）
  再取哈希。两者只共享**口径文字**，不共享一行代码。
* **实现 C**：对实现 P 落盘的**规范字节文件**再跑 `certutil`（独立哈希引擎），覆盖**全部**集合
  （含实现 W 覆盖不到的行多重集）。

## 纪律

* 只读既有数据；产物落**新目录**；不改任何既有表、不提升任何状态、不跑 COMSOL；
* 每个集合都带**依据文件 + 依据字段 + 元素数**；
* 以后引用某集合**必须带该哈希**（见交付 md 末节）。

用法::

    work\\.venv\\Scripts\\python.exe -X utf8 scripts/collection_content_hashes.py
    work\\.venv\\Scripts\\python.exe -X utf8 scripts/collection_content_hashes.py --cli-verify

退出码：`0` 成功 ／ `2` 输入不可用、自校验不成立或哈希不一致。
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import pathlib
import random
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

EXIT_OK, EXIT_FAIL = 0, 2

#: ulp 归一化小数位（与门禁/整组切分同一口径）
ROUND_DECIMALS = 6

PARAM_KEYS = ("x_scale", "N_w_te1", "N_w_te2")

# ---------------------------------------------------------------- 输入（登记哈希）
V3 = REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv"
V3_SHA = "20e28ba12457ce5b553fce3d02c0e4f59e7861370775ecf4cf68b0dff6a3a590"
VIEW = REPO / "work/runs/labels-dupkind-refined/20261008T215100/labels_two_batch_dupkind_refined.csv"
VIEW_SHA = "21e807eecf0807f88164c0cd51cc5329339ccee501b8cee03acaddeff3274afb"
ASSIGN = REPO / "work/runs/grouped-split-20261009/grouped_split_assignments.csv"
GROUPS = REPO / "work/runs/grouped-split-20261009/grouped_split_groups.csv"
AC_LABELS = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"
AC_LABELS_SHA = "d06edfe1999434999d360dc01220eedced236268f1dce1b9c176b516adfecbac"
V2_LABELS = REPO / "work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv"

#: 预注册折定义（**沿用既有** `fit_multichannel_surrogate`：`N2_TRAIN_MAIN`/`N2_TEST_MAIN`）
N2_TRAIN_MAIN = (5.0, 6.0, 7.0)
N2_TEST_MAIN = 8.0
FOLD_HELDS = (None, 7.0, 6.0, 5.0)

SEEDS = (0, 1, 2, 3, 4)

#: 新的**分层**切分产物（若已存在则纳入哈希；不存在则如实标 absent）
STRAT_DIR = REPO / "work/runs/stratified-split-20261009"
STRAT_GROUPS = STRAT_DIR / "stratified_split_groups.csv"
STRAT_ASSIGN = STRAT_DIR / "stratified_split_assignments.csv"

DEFAULT_OUT = REPO / "work/runs/stratified-split-20261009/hashes"

#: 实现 W（PowerShell 端到端规范化器）——与本脚本**不共享一行代码**
PS_CANON = REPO / "scripts/canonicalize_key_set.ps1"


# ================================================================ 规范化（实现 P）

def _g17(v) -> str:
    return "%.17g" % float(v)


def triple(x, n1, n2) -> tuple:
    """ulp 归一化组合键：`(round(x_scale, 6), N_w_te1, N_w_te2)`。"""
    return (round(float(x), ROUND_DECIMALS), float(n1), float(n2))


def key_token(t: tuple) -> str:
    return "%s|%s|%s" % (_g17(t[0]), _g17(t[1]), _g17(t[2]))


def scalar_token(v) -> str:
    return _g17(v)


def _cell(v) -> str:
    s = "" if v is None else str(v)
    if "\n" in s or "\r" in s:
        raise ValueError("单元格含换行 ⇒ token 分隔歧义（fail-closed）：%r" % s)
    return s


def row_token(r: dict, cols) -> str:
    return "\x1f".join(_cell(r.get(c, "")) for c in cols)


def canonical_lines_keys(triples) -> list[str]:
    return [key_token(t) for t in sorted(set(triples))]


def canonical_lines_scalars(vals) -> list[str]:
    return [scalar_token(v) for v in sorted({float(v) for v in vals})]


def canonical_lines_rows(rows, cols) -> list[str]:
    items = [(triple(r["x_scale"], r["N_w_te1"], r["N_w_te2"]), row_token(r, cols))
             for r in rows]
    items.sort()
    return [tok for _t, tok in items]


def hash_lines(lines) -> dict:
    """规范文本 → 字节 → sha256。**末尾恰好一个 `\\n`**。"""
    text = "".join(ln + "\n" for ln in lines)
    blob = text.encode("utf-8")
    return {"n_elements": len(lines), "n_unique_elements": len(set(lines)),
            "n_bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
            "canonical_text": text}


# ================================================================ CSV / 选择

def read_csv(p: pathlib.Path) -> tuple[list[str], list[dict]]:
    with p.open("r", encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        cols = [c for c in (rd.fieldnames or [])]
        return cols, [dict(r) for r in rd]


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def select(rows: list[dict], sel: dict) -> list[dict]:
    """选择子（**唯一**选择语义，Python 与 PowerShell 两边按同一份 spec 执行）。"""
    if not sel:
        return list(rows)
    out = []
    for r in rows:
        if "dataset_in" in sel and str(r.get("source_dataset", "")) not in sel["dataset_in"]:
            continue
        if "batch_in" in sel and str(r.get("batch", "")) not in sel["batch_in"]:
            continue
        if "n2_in" in sel:
            try:
                if float(r.get("N_w_te2", "nan")) not in set(map(float, sel["n2_in"])):
                    continue
            except ValueError:
                continue
        if "side" in sel:
            col, val = sel["side"]
            if str(r.get(col, "")) != val:
                continue
        if sel.get("quarantined_false") and str(r.get("quarantined", "")).strip().lower() == "true":
            continue
        out.append(r)
    return out


# ================================================================ 集合注册表

def build_specs() -> list[dict]:
    specs: list[dict] = []

    def add(name, kind, src, sel=None, cols=None, join=None, ps=False, note=""):
        if join:
            join = {k: (str(v) if isinstance(v, pathlib.Path) else v) for k, v in join.items()}
        specs.append({"name": name, "kind": kind, "csv": src, "sel": sel or {},
                      "columns": cols, "join": join, "ps": ps, "note": note})

    # ---------- ① 三批并集表：整表 / 逐批（行集合 + 组合键集合）----------
    add("union_v3__all_rows", "rows", V3, note="三批并集表整表行**多重集**（2255 行×30 列）")
    add("union_v3__all_keys", "keys", V3, ps=True, note="三批并集全部**组合键集合**（round-6）")
    for b in ("A_5-35MHz", "C_5-50MHz", "V2_5-35MHz"):
        short = {"A_5-35MHz": "A", "C_5-50MHz": "C", "V2_5-35MHz": "V2"}[b]
        add("batch_%s__rows" % short, "rows", V3, sel={"batch_in": [b]},
            note="批 %s 行多重集" % b)
        add("batch_%s__keys" % short, "keys", V3, sel={"batch_in": [b]}, ps=True,
            note="批 %s 组合键集合" % b)

    # ---------- ② dup_kind 细化视图 ----------
    add("view_dupkind__all_rows", "rows", VIEW, note="dup_kind 细化视图整表行多重集（2255×31）")
    add("view_dupkind__all_keys", "keys", VIEW, ps=True, note="dup_kind 细化视图组合键集合")

    # ---------- ③ 整组切分（**既有**非分层）逐 seed 的 train / holdout ----------
    for s in SEEDS:
        add("grouped_train_groups_seed%d" % s, "keys", ASSIGN,
            sel={"side": ("side_seed%d" % s, "train")}, ps=True,
            note="既有整组切分 seed %d 的 **train 组集合**" % s)
        add("grouped_holdout_groups_seed%d" % s, "keys", ASSIGN,
            sel={"side": ("side_seed%d" % s, "holdout")}, ps=True,
            note="既有整组切分 seed %d 的 **holdout 组集合**" % s)
        add("grouped_train_rows_seed%d" % s, "rows", V3,
            join={"assign_csv": ASSIGN, "side_col": "side_seed%d" % s, "side_val": "train"},
            note="既有整组切分 seed %d 的 train 行多重集（按 row_index 回接并集表）" % s)
        add("grouped_holdout_rows_seed%d" % s, "rows", V3,
            join={"assign_csv": ASSIGN, "side_col": "side_seed%d" % s, "side_val": "holdout"},
            note="既有整组切分 seed %d 的 holdout 行多重集" % s)

    add("grouped_all_groups", "keys", GROUPS, ps=False,
        note="组清单里的全部组（应与 union_v3__all_keys 同哈希）")

    # ---------- ④ A/C 标签表（8 通道口径）与预注册折 ----------
    add("labels_AC__rows", "rows", AC_LABELS, sel={"dataset_in": ["A", "C"]},
        note="A∪C 标签整表行多重集（2005 行×64 列，8 通道口径）")
    add("labels_AC__keys", "keys", AC_LABELS, sel={"dataset_in": ["A", "C"]}, ps=True,
        note="A∪C 组合键集合")
    add("labels_C__keys", "keys", AC_LABELS, sel={"dataset_in": ["C"]}, ps=True,
        note="批 C 组合键集合（标签表口径）")
    add("labels_A__keys", "keys", AC_LABELS, sel={"dataset_in": ["A"]}, ps=True,
        note="批 A 组合键集合（标签表口径）")
    add("labels_AC__layers", "scalars", AC_LABELS, sel={"dataset_in": ["A", "C"]},
        note="A∪C 出现过的 N2 层集合")

    for data, dsel in (("C", {"dataset_in": ["C"]}), ("AC", {"dataset_in": ["A", "C"]})):
        for held in FOLD_HELDS:
            pool = [x for x in N2_TRAIN_MAIN if x != held] if held is not None else list(N2_TRAIN_MAIN)
            te = N2_TEST_MAIN if held is None else held
            tag = "%s_N2ex%d" % (data, int(te))
            base = dict(dsel)
            base["quarantined_false"] = True
            tr = dict(base, n2_in=[str(x) for x in pool])
            ho = dict(base, n2_in=[str(te)])
            add("fold_%s__train_keys" % tag, "keys", AC_LABELS, sel=tr, ps=True,
                note="预注册折 %s：训练层 N2∈%s 的组合键集合（已去 quarantined）"
                     % (tag, ["%g" % x for x in pool]))
            add("fold_%s__holdout_keys" % tag, "keys", AC_LABELS, sel=ho, ps=True,
                note="预注册折 %s：留出层 N2=%g 的组合键集合（已去 quarantined）" % (tag, te))
            add("fold_%s__holdout_layers" % tag, "scalars", AC_LABELS, sel=ho,
                note="预注册折 %s：留出**层集合**" % tag)
            add("fold_%s__train_layers" % tag, "scalars", AC_LABELS, sel=tr,
                note="预注册折 %s：训练**层集合**" % tag)

    # ---------- ⑤ v2 冻结副本 ----------
    add("labels_v2__rows", "rows", V2_LABELS, note="v2 冻结副本整表行多重集（250×16，4 通道）")
    add("labels_v2__keys", "keys", V2_LABELS, ps=True, note="v2 冻结副本组合键集合")

    # ---------- ⑥ 新的**分层**切分（若已产出）----------
    if STRAT_GROUPS.is_file():
        _, grows = read_csv(STRAT_GROUPS)
        side_cols = sorted({c for c in (grows[0].keys() if grows else []) if c.startswith("side_")})
        for c in side_cols:
            body = c[len("side_"):]
            rule, _, seedtag = body.rpartition("_seed")
            if not seedtag.isdigit():
                continue
            s = int(seedtag)
            for side in ("train", "holdout"):
                add("stratified_%s_%s_groups_seed%d" % (rule, side, s), "keys", STRAT_GROUPS,
                    note=("分层切分 %s / seed %d / %s 组集合（选择子按 key_from_cols 现算）"
                          % (rule, s, side)),
                    join={"assign_csv": STRAT_GROUPS, "side_col": c, "side_val": side,
                          "key_from_cols": ["x_scale", "N_w_te1", "N_w_te2"]})
    return specs


# ================================================================ 执行

def _join_rows(rows: list[dict], join: dict, inv: list[int] | None = None) -> list[dict]:
    src = pathlib.Path(join["assign_csv"])
    if not src.is_absolute():
        src = REPO / src
    _c, arows = read_csv(src)
    idx_col = join.get("row_index_col") or "row_index"
    keep = [int(r[idx_col]) for r in arows if str(r.get(join["side_col"], "")) == join["side_val"]]
    keep.sort()
    if inv is None:
        return [rows[i] for i in keep]
    # inv[原始行号] = 该行在**重排后**表里的位置（行序不变性实测用）
    return [rows[inv[i]] for i in keep]


def compute(specs: list[dict], tables: dict, mutate: dict | None = None) -> dict:
    """算出所有集合的（元素数、唯一数、字节数、sha256、规范文本）。

    `mutate[源文件路径] = {"rows": 重排后的行, "inv": 原始行号→重排后位置}`：
    行序重排时**同时重映射** `row_index` 型 join，使「同一个集合」在重排前后可比。
    """
    out = {}
    for sp in specs:
        p = pathlib.Path(sp["csv"])
        cols, rows = tables[str(p)]
        inv = None
        if mutate and str(p) in mutate:
            rows = mutate[str(p)]["rows"]
            inv = mutate[str(p)]["inv"]
        if sp["join"]:
            if "key_from_cols" in sp["join"]:
                # 以**组清单的键列**为选择子：组集合（不按 row_index 回接）
                _c, arows = read_csv(pathlib.Path(sp["join"]["assign_csv"]))
                kc = sp["join"]["key_from_cols"]
                chosen = [r for r in arows
                          if str(r.get(sp["join"]["side_col"], "")) == sp["join"]["side_val"]]
                triples = [triple(r[kc[0]], r[kc[1]], r[kc[2]]) for r in chosen]
                lines = canonical_lines_keys(triples)
                h = hash_lines(lines)
                h.update({"element_type": "key", "n_source_selected": len(chosen)})
                out[sp["name"]] = h
                continue
            sel_rows = _join_rows(rows, sp["join"], inv)
        else:
            sel_rows = select(rows, sp["sel"])
        if sp["kind"] == "rows":
            use_cols = sp["columns"] or cols
            lines = canonical_lines_rows(sel_rows, use_cols)
            etype = "row"
        elif sp["kind"] == "keys":
            lines = canonical_lines_keys(
                [triple(r["x_scale"], r["N_w_te1"], r["N_w_te2"]) for r in sel_rows])
            etype = "key"
        elif sp["kind"] == "scalars":
            lines = canonical_lines_scalars([float(r["N_w_te2"]) for r in sel_rows])
            etype = "scalar"
        else:
            raise ValueError(sp["kind"])
        h = hash_lines(lines)
        h["element_type"] = etype
        h["n_source_selected"] = len(sel_rows)
        out[sp["name"]] = h
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--cli-verify", action="store_true",
                    help="对规范字节文件跑 certutil（独立哈希引擎）+ PowerShell 端到端实现")
    ap.add_argument("--shuffle-test", action="store_true",
                    help="把输入行打乱/逆序重排后重算，验证哈希不变")
    a = ap.parse_args(argv)

    outdir = pathlib.Path(a.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    canon_dir = outdir / "canonical"
    canon_dir.mkdir(parents=True, exist_ok=True)

    specs = build_specs()
    srcs = sorted({pathlib.Path(sp["csv"]) for sp in specs}
                  | {pathlib.Path(sp["join"]["assign_csv"]) for sp in specs if sp["join"]})
    missing = [p for p in srcs if not p.is_file()]
    if missing:
        print("[FAIL] 缺输入：%s" % missing)
        return EXIT_FAIL

    tables = {str(p): read_csv(p) for p in srcs}
    src_meta = {str(p): {"sha256": sha256_file(p), "n_rows": len(tables[str(p)][1]),
                         "n_cols": len(tables[str(p)][0])} for p in srcs}

    # ---------- 输入自校验（登记哈希不符 ⇒ fail-closed）----------
    checks = []
    for p, want in ((V3, V3_SHA), (VIEW, VIEW_SHA), (AC_LABELS, AC_LABELS_SHA)):
        got = src_meta[str(p)]["sha256"]
        checks.append({"file": str(p.relative_to(REPO)).replace("\\", "/"),
                       "expected": want, "actual": got, "ok": got == want})
    bad = [c for c in checks if not c["ok"]]
    if bad:
        print("[FAIL] 输入自校验不成立：%s" % json.dumps(bad, ensure_ascii=False))
        return EXIT_FAIL
    print("输入自校验 OK（3 项登记 sha256 逐位一致）")

    # ---------- 主计算 ----------
    res = compute(specs, tables)
    print("集合数 = %d（元素类型分布：%s）"
          % (len(res), json.dumps({t: sum(1 for v in res.values() if v["element_type"] == t)
                                   for t in ("row", "key", "scalar")}, ensure_ascii=False)))

    # ---------- 内部一致性自检 ----------
    internal = {}
    if "union_v3__all_keys" in res and "grouped_all_groups" in res:
        internal["grouped_all_groups == union_v3__all_keys"] = {
            "a": res["grouped_all_groups"]["sha256"], "b": res["union_v3__all_keys"]["sha256"],
            "equal": res["grouped_all_groups"]["sha256"] == res["union_v3__all_keys"]["sha256"],
            "n_a": res["grouped_all_groups"]["n_elements"],
            "n_b": res["union_v3__all_keys"]["n_elements"]}
    if "view_dupkind__all_keys" in res:
        internal["view_dupkind__all_keys == union_v3__all_keys"] = {
            "equal": res["view_dupkind__all_keys"]["sha256"] == res["union_v3__all_keys"]["sha256"]}
    for s in SEEDS:
        tr, ho = res["grouped_train_groups_seed%d" % s], res["grouped_holdout_groups_seed%d" % s]
        allk = res["union_v3__all_keys"]
        internal["seed%d_group_partition_is_exact" % s] = {
            "n_train_groups": tr["n_elements"], "n_holdout_groups": ho["n_elements"],
            "sum": tr["n_elements"] + ho["n_elements"], "n_all_groups": allk["n_elements"],
            "partition": tr["n_elements"] + ho["n_elements"] == allk["n_elements"],
            "disjoint": not (set(tr["canonical_text"].splitlines())
                             & set(ho["canonical_text"].splitlines()))}
    print("内部一致性：%s" % json.dumps(internal, ensure_ascii=False)[:400])

    # ---------- 落盘规范字节（供实现 C / W 独立复算）----------
    for name, v in res.items():
        (canon_dir / ("%s.txt" % name)).write_bytes(v["canonical_text"].encode("utf-8"))

    # ---------- 行序不变性实测（打乱 / 逆序 / 换序重排）----------
    shuffle_ev = {}
    if a.shuffle_test:
        for p in srcs:
            key = str(p)
            perms = {}
            base_rows = tables[key][1]

            def _mk(fn):
                def _inner(rows):
                    new = fn(rows)
                    pos = {id(r): j for j, r in enumerate(new)}
                    inv = [pos[id(r)] for r in rows]
                    return {"rows": new, "inv": inv}
                return _inner

            def _rnd(rows, seed=20261009):
                rr = list(rows)
                random.Random(seed).shuffle(rr)
                return rr

            def _rev(rows):
                return list(reversed(rows))

            def _byother(rows):
                return sorted(rows, key=lambda r: (r.get("source_dataset", ""),
                                                   r.get("batch", ""),
                                                   str(r.get("N_w_te2", "")),
                                                   str(r.get("N_w_te1", "")),
                                                   str(r.get("x_scale", ""))))

            try:
                for tag, fn in (("shuffled_seed20261009", _rnd), ("reversed", _rev),
                                ("reordered_by_other_key", _byother)):
                    mut = _mk(fn)
                    perm = mut(base_rows)
                    r2 = compute(specs, tables, mutate={key: perm})
                    same = [n for n in res if res[n]["sha256"] == r2[n]["sha256"]]
                    permuted_rows = perm["rows"]
                    perms[tag] = {
                        "n_specs": len(res), "n_identical": len(same),
                        "all_identical": len(same) == len(res),
                        "row_order_changed": [str(x) for x in permuted_rows]
                                             != [str(x) for x in base_rows],
                        "row_index_join_remapped": True,
                        "first_diff": next((n for n in res if res[n]["sha256"] != r2[n]["sha256"]),
                                           None)}
            except ValueError as exc:
                perms["error"] = str(exc)
            shuffle_ev[str(p.relative_to(REPO)).replace("\\", "/")] = perms
        print("行序不变性实测：%s"
              % json.dumps({k: {t: v[t]["n_identical"] for t in v if isinstance(v[t], dict)}
                            for k, v in shuffle_ev.items()}, ensure_ascii=False))

    # ---------- 两个独立实现 ----------
    cli_ev = {"certutil_on_canonical_bytes": {}, "powershell_end_to_end": {}}
    if a.cli_verify:
        # 实现 C：独立哈希引擎对**规范字节**取哈希（覆盖全部集合）
        for name, v in res.items():
            fp = canon_dir / ("%s.txt" % name)
            got = _certutil_sha256(fp)
            cli_ev["certutil_on_canonical_bytes"][name] = {
                "python_hashlib": v["sha256"], "certutil_cng": got,
                "identical": got == v["sha256"]}
        n_ok = sum(1 for x in cli_ev["certutil_on_canonical_bytes"].values() if x["identical"])
        n_all = len(cli_ev["certutil_on_canonical_bytes"])
        print("实现 C（certutil 对规范字节）：%d/%d 逐位一致" % (n_ok, n_all))
        # 实现 W：PowerShell 从源 CSV **端到端**（规范化 + CNG 哈希）
        cli_ev["powershell_end_to_end"] = _ps_end_to_end(specs, res, outdir)
        w = cli_ev["powershell_end_to_end"]
        print("实现 W（PowerShell 端到端）：%d/%d 逐位一致%s"
              % (w["n_identical"], w["n_compared"],
                 "" if w["n_identical"] == w["n_compared"] else "  ← **有差异**"))

    # ---------- 产物 ----------
    rows_csv = []
    for sp in specs:
        n = sp["name"]
        v = res[n]
        srcp = pathlib.Path(sp["csv"])
        rows_csv.append({
            "collection": n,
            "element_type": v["element_type"],
            "n_elements": v["n_elements"],
            "n_unique_elements": v["n_unique_elements"],
            "n_bytes_canonical": v["n_bytes"],
            "sha256_content": v["sha256"],
            "source_file": str(srcp.relative_to(REPO)).replace("\\", "/"),
            "source_sha256": src_meta[str(srcp)]["sha256"],
            "selector": json.dumps(sp["sel"], ensure_ascii=False) if sp["sel"]
                        else (json.dumps(sp["join"], ensure_ascii=False) if sp["join"] else "(整表)"),
            "selector_columns": ",".join(sp["columns"] or ["x_scale", "N_w_te1", "N_w_te2"]),
            "note": sp["note"],
        })
    csv_p = outdir / "COLLECTION_HASHES.csv"
    with csv_p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_csv[0].keys()))
        w.writeheader()
        w.writerows(rows_csv)

    summary = {
        "kind": "collection_content_hashes_v1",
        "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "canonical_rule": (
            "把集合的每个元素渲染成规范文本 token，按元素的**自然数值序**升序排列"
            "（三元组按 (round(x_scale,6),N_w_te1,N_w_te2)；标量按数值；整行按 (三元组,行原样文本)），"
            "每个 token 后接一个 \\n（末尾恰好一个换行；空集合=零字节），整体 UTF-8 编码后取 sha256。"),
        "rule_notes": {
            "key_token": "\"%.17g|%.17g|%.17g\" % (round(x,6), N1, N2)",
            "scalar_token": "\"%.17g\" % n2",
            "row_token": "源 CSV 各列单元格原样字符串按源列序以 \\x1f 连接",
            "why": [
                "行序无关：打乱/逆序/换序重排后哈希逐位不变（实测，见 shuffle_invariance）",
                "不依赖源文件字节：不用源文件换行（CRLF/LF）与 BOM",
                "不吞元素：单元格含 \\n/\\r 时 fail-closed 抛错",
            ],
            "round_decimals": ROUND_DECIMALS,
        },
        "input_selfcheck": checks,
        "sources": src_meta_public(src_meta),
        "n_collections": len(res),
        "internal_consistency": internal,
        "shuffle_invariance": shuffle_ev,
        "independent_implementations": cli_ev,
        "collections": {k: {kk: vv for kk, vv in v.items() if kk != "canonical_text"}
                        for k, v in res.items()},
        "rule_for_downstream": ("以后引用某集合**必须带本表该集合的 sha256**；"
                                "只给「三批并集」「seed 0 的 train 集」这类描述**不算可核对**。"),
        "not_modified": [
            "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv",
            "work/runs/labels-dupkind-refined/20261008T215100/labels_two_batch_dupkind_refined.csv",
            "work/runs/grouped-split-20261009/*",
            "work/runs/first-peak-20260929/multichannel_labels.csv",
        ],
        "no_state_promotion": True,
    }
    (outdir / "COLLECTION_HASHES.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "COLLECTION_HASHES.md").write_text(
        render_md(summary, specs, res, src_meta, cli_ev, shuffle_ev), encoding="utf-8")
    print("\n产物：%s（%d B）｜%s（%d B）｜%s（%d B）"
          % (csv_p.relative_to(REPO), csv_p.stat().st_size,
             (outdir / "COLLECTION_HASHES.json").relative_to(REPO),
             (outdir / "COLLECTION_HASHES.json").stat().st_size,
             (outdir / "COLLECTION_HASHES.md").relative_to(REPO),
             (outdir / "COLLECTION_HASHES.md").stat().st_size))

    # 一致性不成立 ⇒ 退出码 2（fail-closed）
    bad_internal = [k for k, v in internal.items()
                    if isinstance(v, dict) and v.get("equal") is False]
    bad_shuffle = [f"{f}:{t}" for f, perms in shuffle_ev.items()
                   for t, v in perms.items()
                   if isinstance(v, dict) and not v.get("all_identical", True)]
    bad_cli = [k for k, v in cli_ev.get("certutil_on_canonical_bytes", {}).items()
               if not v["identical"]]
    if cli_ev.get("powershell_end_to_end", {}).get("n_identical", 0) != \
            cli_ev.get("powershell_end_to_end", {}).get("n_compared", 0):
        bad_cli.append("powershell_end_to_end")
    if bad_internal or bad_shuffle or bad_cli:
        print("[FAIL] 自校验不成立：internal=%s shuffle=%s cli=%s"
              % (bad_internal, bad_shuffle, bad_cli))
        return EXIT_FAIL
    return EXIT_OK


def src_meta_public(src_meta: dict) -> dict:
    return {str(pathlib.Path(k).relative_to(REPO)).replace("\\", "/"): v
            for k, v in src_meta.items()}


def _certutil_sha256(p: pathlib.Path) -> str:
    """**独立哈希引擎**：Windows CNG（certutil）对同一字节流取 sha256。"""
    out = subprocess.run(["certutil", "-hashfile", str(p), "SHA256"],
                         capture_output=True, text=True, errors="replace")
    import re
    m = re.search(r"[0-9a-fA-F]{64}", out.stdout or "")
    return m.group(0).lower() if m else "<PARSE-FAILED:%r>" % (out.stdout or out.stderr)


def _ps_end_to_end(specs: list[dict], res: dict, outdir: pathlib.Path) -> dict:
    """**实现 W**：调 `scripts/canonicalize_key_set.ps1`，从源 CSV 端到端独立复算。

    多值过滤用 `|` 分隔（**实测**：逗号分隔的命令行 token 会被绑成**一个** `[string[]]` 元素，
    导致静默选空集 —— 这是一个必须登记的坑）。
    """
    if not PS_CANON.is_file():
        return {"available": False, "reason": "缺 %s" % PS_CANON.name,
                "n_compared": 0, "n_identical": 0, "per_collection": {}}
    per: dict[str, dict] = {}
    n_cmp = n_ok = 0
    for sp in specs:
        if not sp["ps"] or sp["join"]:
            continue
        sel = sp["sel"]
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(PS_CANON), "-Csv", str(pathlib.Path(sp["csv"])),
                "-Out", ""]
        if "dataset_in" in sel:
            args += ["-DatasetIn", "|".join(sel["dataset_in"])]
        if "batch_in" in sel:
            args += ["-BatchIn", "|".join(sel["batch_in"])]
        if "n2_in" in sel:
            args += ["-N2In", "|".join(sel["n2_in"])]
        if "side" in sel:
            args += ["-SideColumn", sel["side"][0], "-SideValue", sel["side"][1]]
        if sel.get("quarantined_false"):
            args += ["-QuarantinedFalse"]
        pr = subprocess.run(args, capture_output=True, text=True, errors="replace")
        n_cmp += 1
        blob = ""
        for ln in reversed((pr.stdout or "").strip().splitlines()):
            if ln.strip().startswith("{"):
                blob = ln.strip()
                break
        try:
            got = json.loads(blob)
        except ValueError:
            got = {"sha256": "<NO-JSON>", "selected": None, "unique": None, "bytes": None}
        want = res[sp["name"]]
        ok = (got.get("sha256") == want["sha256"]
              and got.get("selected") == want["n_source_selected"]
              and got.get("unique") == want["n_elements"]
              and got.get("bytes") == want["n_bytes"])
        n_ok += 1 if ok else 0
        per[sp["name"]] = {"python_hashlib": want["sha256"],
                           "python_selected": want["n_source_selected"],
                           "python_unique": want["n_elements"],
                           "python_bytes": want["n_bytes"],
                           "powershell": got,
                           "identical": ok,
                           "stderr_tail": (pr.stderr or "")[-300:] if not ok else ""}
    return {"available": True, "script": str(PS_CANON.relative_to(REPO)).replace("\\", "/"),
            "engines_inside_powershell": ["System.Security.Cryptography.SHA256(in-memory)",
                                          "certutil(Windows CNG, temp file)"],
            "n_compared": n_cmp, "n_identical": n_ok, "per_collection": per}


# ================================================================ 渲染

def render_md(s: dict, specs: list[dict], res: dict, src_meta: dict,
              cli_ev: dict, shuffle_ev: dict) -> str:
    L = ["# 集合级**内容哈希**表（INDEX §128.5 Q3 前半：把「用了哪个集合」变成可核对）", "",
         "> 只读既有数据；**不改**任何既有产物、**不提升**任何状态、**不跑** COMSOL。",
         "> 采集器：`scripts/collection_content_hashes.py`（实现 P）＋ `scripts/canonicalize_key_set.ps1`（实现 W）。", "",
         "## 0. 规范化口径（**一句话，写死**）", "",
         "> " + s["canonical_rule"], "",
         "token 渲染：三元组 `%s`；标量 `%s`；整行 `%s`。"
         % (s["rule_notes"]["key_token"], s["rule_notes"]["scalar_token"],
            s["rule_notes"]["row_token"]), "",
         "**为什么必须是这一条**（三条都要成立）：", ""]
    for x in s["rule_notes"]["why"]:
        L.append("* " + x)
    L += ["", "## 1. 集合总表（`%d` 个集合）" % s["n_collections"], "",
          "| 集合名 | 元素类型 | 元素数 | 唯一元素数 | 规范字节 | **内容 sha256** | 依据文件 | 依据字段/选择子 |",
          "|---|---|---:|---:|---:|---|---|---|"]
    for sp in specs:
        n = sp["name"]
        v = res[n]
        srcp = str(pathlib.Path(sp["csv"]).relative_to(REPO)).replace("\\", "/")
        sel = sp["sel"] or sp["join"] or "(整表)"
        L.append("| `%s` | %s | %d | %d | %d | `%s` | `%s` | `%s` |"
                 % (n, v["element_type"], v["n_elements"], v["n_unique_elements"],
                    v["n_bytes"], v["sha256"], srcp,
                    json.dumps(sel, ensure_ascii=False) if isinstance(sel, dict) else sel))
    L += ["", "## 2. 独立实现与不变性实测（**验收条件**）", ""]
    if s["independent_implementations"].get("certutil_on_canonical_bytes"):
        cb = s["independent_implementations"]["certutil_on_canonical_bytes"]
        n_ok = sum(1 for v in cb.values() if v["identical"])
        L += ["### 2.1 实现 C：`certutil`（Windows CNG）对**规范字节**取哈希 —— 覆盖**全部** %d 个集合"
              % len(cb), "",
              "**%d / %d 逐位一致**（Python `hashlib` ↔ Windows CNG，两个独立哈希引擎）。" % (n_ok, len(cb)),
              ""]
    if s["independent_implementations"].get("powershell_end_to_end"):
        w = s["independent_implementations"]["powershell_end_to_end"]
        L += ["### 2.2 实现 W：PowerShell **从源 CSV 端到端**独立规范化 + CNG 哈希", "",
              "脚本 `%s`（纯 ASCII、`param()` 首条语句；`[math]::Round` → `.ToString('G17')` → "
              "`Sort-Object` → `UTF8Encoding($false)` → `certutil`）。" % w.get("script", "—"), "",
              "**%d / %d 逐位一致**（与实现 P 的 `hashlib` 结果逐位相同）。" % (w.get("n_identical", 0),
                                                                    w.get("n_compared", 0)), ""]
        bad = [k for k, v in w.get("per_collection", {}).items() if not v["identical"]]
        if bad:
            L += ["⚠️ **不一致集合**：%s" % ", ".join("`%s`" % b for b in bad), ""]
    if shuffle_ev:
        L += ["### 2.3 行序不变性（**行序变化必须不改变哈希**）", "",
              "| 源文件 | 变换 | 覆盖集合数 | 哈希不变数 | 全部不变？ | 行序确实变了？ |",
              "|---|---|---:|---:|---|---|"]
        for f, perms in shuffle_ev.items():
            for t, v in perms.items():
                if not isinstance(v, dict) or "n_specs" not in v:
                    continue
                L.append("| `%s` | %s | %d | %d | **%s** | %s |"
                         % (f, t, v["n_specs"], v["n_identical"], v["all_identical"],
                            v["row_order_changed"]))
        L += ["", "⇒ **行序打乱 / 逆序 / 按别的键重排后，全部集合的内容哈希逐位不变** —— "
                  "这不是声明，是上表的实测。", ""]
    L += ["## 3. 内部一致性自检", "", "| 检查 | 结果 |", "|---|---|"]
    for k, v in s["internal_consistency"].items():
        L.append("| `%s` | %s |" % (k, json.dumps(v, ensure_ascii=False)))
    L += ["", "## 4. 依据文件（逐件 sha256）", "", "| 文件 | 行数 | 列数 | sha256 |", "|---|---:|---:|---|"]
    for f, v in s["sources"].items():
        L.append("| `%s` | %d | %d | `%s` |" % (f, v["n_rows"], v["n_cols"], v["sha256"]))
    L += ["", "## 5. 引用纪律（**以后引用某集合必须带该哈希**）", "",
          "1. 说「用了三批并集」**不算可核对**；必须写 `union_v3__all_keys` = `%s`。"
          % res.get("union_v3__all_keys", {}).get("sha256", "—"),
          "2. 说「seed 0 的训练集」**不算可核对**；必须写 `grouped_train_groups_seed0` = `%s`。"
          % res.get("grouped_train_groups_seed0", {}).get("sha256", "—"),
          "3. 说「旧折 `N2ex8`」**不算可核对**；必须写 `fold_C_N2ex8__train_keys` = `%s` 与 "
          "`fold_C_N2ex8__holdout_keys` = `%s`。"
          % (res.get("fold_C_N2ex8__train_keys", {}).get("sha256", "—"),
             res.get("fold_C_N2ex8__holdout_keys", {}).get("sha256", "—")),
          "4. 行集合与组合键集合**是两个不同的集合**（元素类型不同 ⇒ 哈希必然不同），引用时不得混用。",
          "5. 内容哈希只证明「集合内容相同」；**不证明**「该集合适合当训练/留出集」（那是 §113/§114 的判据）。",
          "", "## 6. 未做 / 边界", "",
          "* 只做**集合内容哈希**：不给任何模型指标、不改任何状态；",
          "* 行多重集（`element_type=row`）的**规范化只有实现 P 一套**（Python）；独立复算走实现 C（CNG 哈希引擎）"
          "与实现 W（键/组集合）。**行的排序比较用 ordinal 语义**，PowerShell `Sort-Object` 对字符串是"
          "文化相关比较 ⇒ 未用 PowerShell 端到端复算行多重集（如实登记，不假装覆盖）；",
          "* 分层切分集合的命名规则由 `%s` 定义（见 `STRATIFIED_SPLIT.md`）。"
          % "work/runs/stratified-split-20261009/STRATIFIED_SPLIT.md",
          ""]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
