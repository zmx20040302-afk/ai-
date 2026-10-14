# -*- coding: utf-8 -*-
"""R2 只读检查器：把标签表的「**输入行序依赖**」从隐式变成**可查**。

## 为什么有这个脚本（R2 裁决：维持 O-A ＋ 披露实际生效行 ＋ 显式化行序依赖）

评估内核 `fit_multichannel_surrogate.py` **L145** 是

    layers.setdefault((r["n2"], r["n1"]), {})[round(r["x"], 6)] = to_space(ch, r[ch])

* **行序** = `csv.DictReader` 顺序（同文件 **L78**）；
* 同一 `(n2, n1, round(x,6))` 出现多行时是**沉默的 last-write-wins**（后写覆盖先写）；
* ⚠️ 但 `build()` 在 **L143** 先过一道 `defined(r, ch)`（该通道需 `peak`/`closed` 且值 > 0）
  ⇒ **「生效行」是「该键里最后一个 `defined()` 为真的行」**，**不必然**是文件里的最后一行。

⇒ 母表「一行不删」并不等于「两行都被使用」：**每个重复键实际只有一行进模型**。
本脚本给两张视图（都是**只读**、都**不写盘**，除非显式 `--out`）：

* **视图 A｜行序视图**（不看通道）：逐键给「生效行（= 末行）/ 被覆盖行 / 行序位置
  （`row_index` = `DictReader` 顺序，即 `build()` 看到的顺序；另给物理行号 `line_no`）」，
  以及重复键的**行序签名**（如 `(A,C)` / `(A,C,V2)`）与逐签名计数；
* **视图 B｜通道视图**（`build()` 的实际行为）：对**有 8 通道列 ＋ 原生 `peaked`/`closed` 标志**
  的表（= `multichannel_labels.csv`），import 既有内核（只读、不复制代码）跑 `build()`，
  逐键逐通道报「最后一个 `defined()` 为真的行」以及**模型里存的值是否真的等于那一行**
  （判据先定后算；不等即 rc=3，fail-closed）。

⚠️ 本脚本**不改 `build()`**、**不删任何行**、**不改任何母表**。

## 用法

    python -X utf8 scripts/check_label_row_order.py --labels <csv> [--batch-col source_dataset]
    python -X utf8 scripts/check_label_row_order.py --labels <csv> --out <dir>

退出码：`0` 成功；`2` 输入不可读；`3` 通道视图出现「模型值 ≠ 该通道生效行」的键。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

EXIT_OK, EXIT_INPUT, EXIT_MISMATCH = 0, 2, 3

#: 既有评估内核（**只读 import**）
FITTER = REPO / "work/runs/multichannel-surrogate-20260929/fit_multichannel_surrogate.py"

KEY_COLS = ("x_scale", "N_w_te1", "N_w_te2")
#: 行序依赖的**代码出处**（本脚本只引用、不修改）
BUILD_SEMANTICS = {
    "file": "work/runs/multichannel-surrogate-20260929/fit_multichannel_surrogate.py",
    "assign_line": 145,
    "row_order_line": 78,
    "defined_filter_line": 143,
    "expression": 'layers.setdefault((r["n2"], r["n1"]), {})[round(r["x"], 6)] = to_space(ch, r[ch])',
    "rule": "last-write-wins（后写覆盖先写；先过 defined() 过滤）",
    "row_order": "csv.DictReader 顺序",
    "runtime_guard": None,   # 现读源码：build() 内无任何重复键断言（本脚本不改它）
}


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load_rows(p: pathlib.Path) -> tuple[list[dict], list[str]]:
    with p.open("r", encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        return list(rd), list(rd.fieldnames or [])


def key_of(r: dict) -> tuple | None:
    try:
        return (round(float(r["x_scale"]), 6), float(r["N_w_te1"]), float(r["N_w_te2"]))
    except (TypeError, ValueError):
        return None


def detect_batch_col(cols: list[str], override: str | None) -> str | None:
    if override:
        return override
    for c in ("batch", "source_dataset", "source_file"):
        if c in cols:
            return c
    return None


def group_by_key(rows: list[dict]) -> dict[tuple, list[int]]:
    """逐键归组（**保序**：位置即 `DictReader` 行序）。"""
    idx: dict[tuple, list[int]] = {}
    for i, r in enumerate(rows):
        k = key_of(r)
        if k is None:
            continue
        idx.setdefault(k, []).append(i)
    return idx


def _diff_cols(a: dict, b: dict, cols: list[str]) -> list[str]:
    return [c for c in cols if (a.get(c) or "").strip() != (b.get(c) or "").strip()]


def row_order_view(rows: list[dict], cols: list[str], batch_col: str | None) -> dict:
    """视图 A：行序视图（不看通道）。生效行 = 该键的**最后一行**。"""
    idx = group_by_key(rows)
    dups = {k: v for k, v in idx.items() if len(v) > 1}
    sig: dict[str, int] = {}
    eff_by_batch: dict[str, int] = {}
    shadow_by_batch: dict[str, int] = {}
    per_key: list[dict] = []
    for k in sorted(dups):
        pos = dups[k]
        eff = pos[-1]
        seq = [((rows[i].get(batch_col) if batch_col else None) or "?") for i in pos]
        s = "(%s)" % ",".join(seq)
        sig[s] = sig.get(s, 0) + 1
        eff_by_batch[seq[-1]] = eff_by_batch.get(seq[-1], 0) + 1
        for b in seq[:-1]:
            shadow_by_batch[b] = shadow_by_batch.get(b, 0) + 1
        per_key.append({
            "key": "|".join("%g" % v for v in k),
            "n_rows": len(pos),
            "batch_sequence": seq,
            "signature": s,
            "effective_row_index": eff,
            "effective_line_no": eff + 2,          # 1 行表头 + 1-based
            "effective_batch": seq[-1],
            "shadowed_row_index": pos[:-1],
            "shadowed_line_no": [i + 2 for i in pos[:-1]],
            "shadowed_batch": seq[:-1],
            "shadowed_diff": [{"row_index": i,
                               "n_diff_cols": len(_diff_cols(rows[i], rows[eff], cols)),
                               "diff_cols": _diff_cols(rows[i], rows[eff], cols)}
                              for i in pos[:-1]],
        })
    return {"n_rows": len(rows), "n_unique_keys": len(idx), "n_duplicate_keys": len(dups),
            "n_shadowed_rows": sum(len(v) - 1 for v in dups.values()),
            "signatures": dict(sorted(sig.items())),
            "effective_by_batch": dict(sorted(eff_by_batch.items())),
            "shadowed_by_batch": dict(sorted(shadow_by_batch.items())),
            "per_key": per_key}


def channel_view(rows: list[dict], cols: list[str]) -> dict:
    """视图 B：`build()` 的实际行为（逐键逐通道）。只在原生标志齐备时执行。"""
    if not FITTER.is_file():
        return {"performed": False, "reason": "缺既有内核：%s" % FITTER}
    missing = [c for c in ("first_peak_found", "bandwidth_closed") if c not in cols]
    if missing:
        return {"performed": False,
                "reason": "缺原生标志列 %s ⇒ 拒绝用代理标志冒充（只出视图 A）" % missing}
    spec = importlib.util.spec_from_file_location("_mc_fitter_roworder", FITTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    chans = tuple(mod.CHANNELS)
    have = [c for c in chans if c in cols]
    if not have:
        return {"performed": False, "reason": "表内没有任何 8 通道列 ⇒ 只出视图 A"}
    q = {("0.2", "1", "7"), ("0.2", "1", "8")}          # 既有 QUARANTINE 口径（只影响是否进模型）
    idx = group_by_key(rows)
    dups = {k: v for k, v in idx.items() if len(v) > 1}

    # 构造 build() 需要的行（与既有内核 load_rows() 同形；标志用原生列）
    def row_dict(i: int) -> dict:
        r = rows[i]
        k = key_of(r)
        d = {"key": k, "x": k[0], "n1": k[1], "n2": k[2],
             "peaked": str(r.get("first_peak_found", "")).lower() == "true",
             "closed": str(r.get("bandwidth_closed", "")).lower() == "true"}
        for c in chans:
            s = (r.get(c) or "").strip()
            try:
                d[c] = float(s) if s else None
            except ValueError:
                d[c] = None
        return d

    trains = [row_dict(i) for i in range(len(rows))]
    quarantined = sum(1 for d in trains if "%g" % d["n1"] == "1"
                      and any(abs(d["x"] - x) < 1e-12 for x in (0.2,))
                      and "%g" % d["n2"] in ("7", "8"))
    per_channel: dict[str, dict] = {}
    problems: list[str] = []
    per_key_channel: list[dict] = []
    for ch in have:
        model = mod.build(trains, ch)
        layers = model["layers"]
        n_eff_last = n_eff_nonlast = n_no_eff = n_match = n_mismatch = 0
        n_shadowed_effective = 0
        recs = []
        for k, pos in sorted(dups.items()):
            x, n1, n2 = k
            defined_rows = [i for i in pos if mod.defined(trains[i], ch)]
            cell = (layers.get((n2, n1)) or {}).get(round(x, 6))
            if not defined_rows:
                n_no_eff += 1
                recs.append({"key": "|".join("%g" % v for v in k), "rows_defined": [],
                             "effective_row_index": None, "model_matches_effective": None,
                             "n_rows_shadowed_for_this_channel": 0})
                continue
            eff = defined_rows[-1]
            n_shadowed_effective += len(defined_rows) - 1
            if eff == pos[-1]:
                n_eff_last += 1
            else:
                n_eff_nonlast += 1
            ok = None
            if cell is not None:
                ok = abs(float(cell) - mod.to_space(ch, trains[eff][ch])) < 1e-15
                n_match += 1 if ok else 0
                n_mismatch += 0 if ok else 1
                if not ok:
                    problems.append("%s 键 %s：模型值 %r ≠ 生效行 %d 的值 %r"
                                    % (ch, "|".join("%g" % v for v in k), cell, eff,
                                       trains[eff][ch]))
            recs.append({"key": "|".join("%g" % v for v in k),
                         "rows_defined": defined_rows,
                         "effective_row_index": eff,
                         "model_matches_effective": ok,
                         "n_rows_shadowed_for_this_channel": len(defined_rows) - 1})
        per_channel[ch] = {
            "n_dup_keys": len(dups),
            "n_keys_with_effective_row": len(dups) - n_no_eff,
            "n_keys_all_rows_undefined": n_no_eff,
            "n_effective_is_last_row": n_eff_last,
            "n_effective_is_not_last_row": n_eff_nonlast,
            "n_rows_shadowed_within_defined": n_shadowed_effective,
            "n_model_value_checked": n_match + n_mismatch,
            "n_model_value_matches_effective": n_match,
            "n_model_value_mismatch": n_mismatch,
        }
        per_key_channel.append({"channel": ch, "per_key": recs})
    return {"performed": True, "fitter": str(FITTER.relative_to(REPO)).replace("\\", "/"),
            "fitter_sha256": sha256_file(FITTER), "channels": list(have),
            "n_trains_rows": len(trains), "n_quarantine_matched_rows": quarantined,
            "quarantine_note": ("本脚本**不**排除 QUARANTINE（既有内核 load_rows() 会排；"
                                "这里为了逐行对账保留全部行）⇒ 层内可能多出被隔离的行，"
                                "故 `n_model_value_mismatch` 才是判据，不是按名单剔行"),
            "per_channel": per_channel, "problems": problems,
            "verdict": ("模型值逐键逐通道 == 「最后一个 defined() 为真的行」⇒ **last-write-wins "
                        "（defined 过滤后）成立**" if not problems else
                        "；".join(problems[:5]))}


def render_md(name: str, sha: str, ro: dict, cv: dict, batch_col: str | None,
              example_keys: int = 4) -> str:
    L = ["# 标签表「输入行序依赖」只读检查（R2 显式化）", "",
         "> 母表：`%s`（sha256 `%s`）" % (name, sha),
         "> 生效规则：**%s**（`%s` L%d 赋值；行序 = 同文件 L%d；先过 L%d 的 `defined()` 过滤）"
         % (BUILD_SEMANTICS["rule"], BUILD_SEMANTICS["file"], BUILD_SEMANTICS["assign_line"],
            BUILD_SEMANTICS["row_order_line"], BUILD_SEMANTICS["defined_filter_line"]),
         "> ⚠️ **不得声称两行都被使用**：下表逐键给出「生效行 / 被覆盖行」。",
         "> ⚠️ 本脚本**不改 `build()`**、**不删任何行**；写盘只在显式 `--out` 时发生。", "",
         "## 0. 汇总（视图 A｜行序视图）", "",
         "| 项 | 值 |", "|---|---:|",
         "| 数据行数 | %d |" % ro["n_rows"],
         "| 唯一组合键（round-6） | %d |" % ro["n_unique_keys"],
         "| **重复键数** | %d |" % ro["n_duplicate_keys"],
         "| **被覆盖（未进模型）行数** | %d |" % ro["n_shadowed_rows"],
         "| 批次列 | `%s` |" % (batch_col or "（无）"), "",
         "**行序签名计数（本表实测）**：", "",
         "| 签名（批次序） | 重复键数 |", "|---|---:|"]
    for s, n in ro["signatures"].items():
        L.append("| `%s` | %d |" % (s, n))
    L += ["", "**生效 / 被覆盖 按批**：", "",
          "| 批 | 生效行数（末行） | 被覆盖行数 |", "|---|---:|---:|"]
    for b in sorted(set(ro["effective_by_batch"]) | set(ro["shadowed_by_batch"])):
        L.append("| `%s` | %d | %d |" % (b, ro["effective_by_batch"].get(b, 0),
                                         ro["shadowed_by_batch"].get(b, 0)))
    L += ["", "## 1. 逐键明细（视图 A 样例：前 %d 个重复键）" % example_keys, "",
          "| 键 (x\\|N1\\|N2) | 行数 | 签名 | **生效行** row_index / line_no / 批 | **被覆盖行** row_index / line_no / 批（与生效行不同的列数） |",
          "|---|---:|---|---|---|"]
    for e in ro["per_key"][:example_keys]:
        sh = "；".join("%d / %d / %s（%d 列不同）"
                       % (s["row_index"], e["shadowed_line_no"][i], e["shadowed_batch"][i],
                          s["n_diff_cols"])
                       for i, s in enumerate(e["shadowed_diff"]))
        L.append("| `%s` | %d | `%s` | %d / %d / `%s` | %s |"
                 % (e["key"], e["n_rows"], e["signature"], e["effective_row_index"],
                    e["effective_line_no"], e["effective_batch"], sh or "—"))
    L += ["", "## 2. 视图 B｜`build()` 的实际行为（逐键逐通道，import 既有内核对照）", ""]
    if not cv.get("performed"):
        L += ["⚠️ **未做通道视图**：%s ⇒ `build_check_performed=false`（不得当成已验证）。"
              % cv.get("reason"), "",
              "（视图 A 已足够回答「输入行序依赖」这一问题：生效行由**行序**决定，"
              "与通道无关；但**不**据此声称任何通道的具体生效行。）"]
        return "\n".join(L) + "\n"
    L += ["内核：`%s`（sha256 `%s`）；通道 %s；构造行数 %d。"
          % (cv["fitter"], cv["fitter_sha256"], "、".join("`%s`" % c for c in cv["channels"]),
             cv["n_trains_rows"]),
          "⚠️ %s" % cv["quarantine_note"], "",
          "| 通道 | 重复键 | 有生效行 | 全行未定义 | **生效行 = 末行** | **生效行 ≠ 末行** | 通道内被覆盖行 | 已对照的模型值 | 相符 | 不符 |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for ch, v in cv["per_channel"].items():
        L.append("| `%s` | %d | %d | %d | %d | %d | %d | %d | %d | %d |"
                 % (ch, v["n_dup_keys"], v["n_keys_with_effective_row"],
                    v["n_keys_all_rows_undefined"], v["n_effective_is_last_row"],
                    v["n_effective_is_not_last_row"], v["n_rows_shadowed_within_defined"],
                    v["n_model_value_checked"], v["n_model_value_matches_effective"],
                    v["n_model_value_mismatch"]))
    L += ["", "**结论（由上面的数字现算）**：%s" % cv["verdict"], "",
          "> ⚠️ **「生效行 ≠ 末行」不为 0 时必须这样读**：`build()` 的生效行是"
          "「该键里最后一个 `defined()` 为真的行」，**不是**文件里的最后一行 —— "
          "即行序依赖是**两段式**的（行序 → `defined()` 过滤），披露时不能只说「末行生效」。"]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="标签表行序依赖只读检查（R2）")
    ap.add_argument("--labels", required=True, help="标签表 CSV")
    ap.add_argument("--batch-col", default=None)
    ap.add_argument("--out", default=None, help="显式才写：输出目录（缺省只打印，不写盘）")
    ap.add_argument("--no-build-check", action="store_true")
    a = ap.parse_args(argv)

    p = pathlib.Path(a.labels)
    if not p.is_file():
        p = REPO / a.labels
    if not p.is_file():
        print("[FAIL] 标签表不存在：%s" % a.labels)
        return EXIT_INPUT
    rows, cols = load_rows(p)
    batch_col = detect_batch_col(cols, a.batch_col)
    ro = row_order_view(rows, cols, batch_col)
    sha = sha256_file(p)
    cv = {"performed": False, "reason": "已用 --no-build-check 关闭"}
    if not a.no_build_check:
        cv = channel_view(rows, cols)

    rel = str(p.relative_to(REPO)).replace("\\", "/") if p.is_relative_to(REPO) else str(p)
    print("== %s（sha256 %s）==" % (rel, sha))
    print("行数 %d ｜ 唯一键 %d ｜ 重复键 %d ｜ **被覆盖行 %d** ｜ 批次列 %s"
          % (ro["n_rows"], ro["n_unique_keys"], ro["n_duplicate_keys"],
             ro["n_shadowed_rows"], batch_col))
    print("签名计数：%s" % json.dumps(ro["signatures"], ensure_ascii=False))
    print("生效（末行）按批：%s ｜ 被覆盖按批：%s"
          % (json.dumps(ro["effective_by_batch"], ensure_ascii=False),
             json.dumps(ro["shadowed_by_batch"], ensure_ascii=False)))
    for e in ro["per_key"][:2]:
        print("  [视图A] 键 %-22s 行数 %d 签名 %-10s 生效 row_index=%d(行 %d, %s) 被覆盖 %s"
              % (e["key"], e["n_rows"], e["signature"], e["effective_row_index"],
                 e["effective_line_no"], e["effective_batch"],
                 [(s["row_index"], e["shadowed_line_no"][i], e["shadowed_batch"][i])
                  for i, s in enumerate(e["shadowed_diff"])]))
    if cv.get("performed"):
        print("视图B（build 对照）：%s" % cv["verdict"])
        for ch, v in cv["per_channel"].items():
            print("  %-20s 生效=末行 %3d ｜ 生效≠末行 %3d ｜ 模型值不符 %d"
                  % (ch, v["n_effective_is_last_row"], v["n_effective_is_not_last_row"],
                     v["n_model_value_mismatch"]))
    else:
        print("视图B（build 对照）：**未做**（%s）" % cv.get("reason"))

    md = render_md(rel, sha, ro, cv, batch_col)
    if a.out:
        outdir = pathlib.Path(a.out)
        if not outdir.is_absolute():
            outdir = REPO / outdir
        outdir.mkdir(parents=True, exist_ok=True)
        stem = p.stem
        (outdir / ("%s_roworder.json" % stem)).write_text(
            json.dumps({"labels": rel, "sha256": sha, "columns": cols, "batch_col": batch_col,
                        "build_semantics": BUILD_SEMANTICS, "row_order_view": ro,
                        "channel_view": cv}, ensure_ascii=False, indent=2), encoding="utf-8")
        (outdir / ("%s_roworder.md" % stem)).write_text(md, encoding="utf-8")
        with (outdir / ("%s_roworder_perkey.csv" % stem)).open(
                "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["key", "n_rows", "signature", "row_index",
                                               "line_no", "batch", "role",
                                               "shadowed_by_row_index", "n_diff_cols", "diff_cols"])
            w.writeheader()
            for e in ro["per_key"]:
                diffs = {d["row_index"]: d for d in e["shadowed_diff"]}
                for j, ri in enumerate([e["effective_row_index"]] + e["shadowed_row_index"]):
                    role = "effective" if j == 0 else "shadowed"
                    d = diffs.get(ri, {"n_diff_cols": 0, "diff_cols": []})
                    w.writerow({"key": e["key"], "n_rows": e["n_rows"],
                                "signature": e["signature"], "row_index": ri,
                                "line_no": ri + 2,
                                "batch": (e["effective_batch"] if role == "effective"
                                          else e["shadowed_batch"][j - 1]),
                                "role": role,
                                "shadowed_by_row_index": ("" if role == "effective"
                                                          else e["effective_row_index"]),
                                "n_diff_cols": d["n_diff_cols"],
                                "diff_cols": ";".join(d["diff_cols"])})
        print("产物：%s（%s_roworder.json/.md/_perkey.csv）"
              % (outdir.relative_to(REPO) if outdir.is_relative_to(REPO) else outdir, stem))

    if cv.get("performed") and cv.get("problems"):
        print("[FAIL] 通道视图未成立：%d 处模型值 ≠ 生效行" % len(cv["problems"]))
        return EXIT_MISMATCH
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
