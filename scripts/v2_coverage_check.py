# -*- coding: utf-8 -*-
"""v2 导出（te2_5/7/8/9）盘点：组合覆盖、频率栅格、**峰值/带宽的端点截断**、与既有标签的重叠。

背景：这批是`exported_results_v2` 的第二条管线，每个 cell 一个 N2 值（5/7/8/9），
`Table_9` 是点探针(0,0,-1e-5)的逐频表，`Peak_frequency` 是峰值图形标记，
`Bandwidth` 是 −3 dB 截断点（含宽度/Q/阻尼比）。

本脚本只读本地副本，产出 `v2_coverage.json` + 屏幕摘要。**重点回答两个问题**：
1. 哪些组合是**新**的（尤其 N2=9）；
2. 峰值/带宽有多少落在扫描端点（=被截断/右删失），这直接决定标签能不能用。
"""
from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
ROOT = REPO / "work/runs/remote-exported-v2-20260922/exported_results_v2"


def load_txt(p: pathlib.Path) -> tuple[list[str], list[list[str]]]:
    """跳过 `%` 注释，返回 (表头列名, 数据行)。

    ⚠️ COMSOL 的表头是**一长行、列名自带空格**（如 `freq (Hz)`、
    `总声压 (Pa), 点: (0, 0, -1E-5)`），按空白切会碎成几十个 token。
    正确做法：表头按 **2 个以上空格** 切；数据行按空白切（值是数字，不含空格）。
    """
    import re

    meta_re = re.compile(r"^%\s*(Model|Version|Date|Table)\s*:")
    head: list[str] = []
    rows: list[list[str]] = []
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            s = ln.rstrip("\n")
            if not s.strip():
                continue
            if s.lstrip().startswith("%"):
                # ⚠️ 表头本身也是 `%` 行（如 `% x_scale   N_w_te1   …`），
                # 只有 Model/Version/Date/Table 四类才是元数据 ⇒ 其余当作表头。
                if not meta_re.match(s.strip()):
                    body = s.lstrip()[1:]
                    head = [t.strip() for t in re.split(r"\s{2,}", body.strip()) if t.strip()]
                continue
            if not head:
                continue
            rows.append(s.split())
    return head, rows


def main() -> int:
    cells = sorted(p for p in ROOT.iterdir() if p.is_dir() and p.name.startswith("cell_"))
    rep: dict = {"root": str(ROOT.relative_to(REPO)), "cells": {}, "errors": []}
    all_combos: dict[str, set] = {}
    for c in cells:
        tag = c.name.split("_test_v2")[0].replace("cell_", "")   # te2_5 ...
        head, rows = load_txt(c / "Table_9.txt")
        idx = {name: i for i, name in enumerate(head)}
        need = ["x_scale", "N_w_te1", "N_w_te2", "freq (Hz)"]
        missing = [n for n in need if n not in idx]
        if missing:
            rep["errors"].append("%s 表头缺列 %s；实际表头=%s" % (tag, missing, head))
            print("[FAIL] %s 表头缺列 %s" % (tag, missing))
            print("       实际表头：", head)
            continue
        if len(head) != len(rows[0]):
            rep["errors"].append("%s 表头 %d 列 vs 数据 %d 列" % (tag, len(head), len(rows[0])))
            print("[WARN] %s 表头 %d 列 vs 数据 %d 列（按位置对齐，列名可能错位）"
                  % (tag, len(head), len(rows[0])))
        combos: set = set()
        freqs: set = set()
        for r in rows:
            combos.add((r[idx["x_scale"]], r[idx["N_w_te1"]], r[idx["N_w_te2"]]))
            freqs.add(float(r[idx["freq (Hz)"]]))
        fmin, fmax = min(freqs), max(freqs)
        dstep = sorted(freqs)[1] - sorted(freqs)[0]
        all_combos[tag] = combos

        ph, pr = load_txt(c / "Peak_frequency.txt")
        pi = {n: i for i, n in enumerate(ph)}
        n_peak = len(pr)
        n_at_hi = sum(1 for r in pr if abs(float(r[pi["freq (Hz)"]]) - fmax) < 1.0)
        n_at_lo = sum(1 for r in pr if abs(float(r[pi["freq (Hz)"]]) - fmin) < 1.0)

        bh, br = load_txt(c / "Bandwidth.txt")
        bi = {n: i for i, n in enumerate(bh)}
        fcol = "freq (Hz)"
        fr = [float(r[bi[fcol]]) for r in br]
        n_bw = len(br)
        bw_hi = sum(1 for f in fr if abs(f - fmax) < 1.0)
        bw_lo = sum(1 for f in fr if abs(f - fmin) < 1.0)
        # 每个 level 两行（下截断点 / 上截断点）成对出现
        rep["cells"][tag] = {
            "n_combos": len(combos), "n_freq": len(freqs),
            "freq_span_Hz": [fmin, fmax], "freq_step_Hz": dstep,
            "peak_rows": n_peak, "peak_at_upper_endpoint": n_at_hi,
            "peak_at_lower_endpoint": n_at_lo,
            "bandwidth_rows": n_bw, "bw_rows_at_upper_endpoint": bw_hi,
            "bw_rows_at_lower_endpoint": bw_lo,
            "bw_levels": n_bw // 2,
            "columns_Table_9": head,
        }
        x = sorted({float(t[0]) for t in combos})
        n1 = sorted({int(t[1]) for t in combos})
        print("\n### %s  (N_w_te2 = %s)" % (tag, sorted({t[2] for t in combos})))
        print("  组合 %d 个 ｜ x_scale %s ｜ N_w_te1 %s"
              % (len(combos), ("%g..%g 共%d个" % (x[0], x[-1], len(x))) if x else "-", n1))
        print("  频率 %g–%g Hz 步长 %g（%d 点）" % (fmin, fmax, dstep, len(freqs)))
        print("  峰值标记 %d 行：落在**上端点 %g Hz** %d 行（%.1f%%）、下端点 %d 行"
              % (n_peak, fmax, n_at_hi, 100 * n_at_hi / max(n_peak, 1), n_at_lo))
        print("  带宽表 %d 行（%d 个 level）：上端点出现 %d 次、下端点 %d 次"
              % (n_bw, n_bw // 2, bw_hi, bw_lo))

    # 与既有标签重叠
    cands = sorted(REPO.glob("work/runs/**/multichannel_labels.csv"))
    rep["labels_csv_found"] = [str(p.relative_to(REPO)) for p in cands]
    if cands:
        import csv
        with cands[0].open("r", encoding="utf-8", newline="") as fh:
            rd = list(csv.DictReader(fh))
        print("\n== 与既有标签表比对：%s（%d 行）=="
              % (cands[0].relative_to(REPO), len(rd)))
        cols = {c.lower(): c for c in rd[0].keys()}
        kx = cols.get("x_scale"); k1 = cols.get("n_w_te1"); k2 = cols.get("n_w_te2")
        print("  用列：x_scale=%r N_w_te1=%r N_w_te2=%r" % (kx, k1, k2))
        if kx and k1 and k2:
            old = set()
            for r in rd:
                try:
                    old.add((float(r[kx]), int(float(r[k1])), int(float(r[k2]))))
                except (TypeError, ValueError):
                    pass
            print("  既有组合 %d 个 ｜ 既有 N_w_te2 取值 %s"
                  % (len(old), sorted({c[2] for c in old})))
            for tag, combos in sorted(all_combos.items()):
                new = {(float(a), int(float(b)), int(float(c2))) for a, b, c2 in combos}
                only = new - old
                rep.setdefault("overlap", {})[tag] = {
                    "n_new_combos": len(only),
                    "examples": sorted(only)[:5],
                    "n2_values": sorted({c[2] for c in new})}
                print("  %-8s 新组合 %3d / %3d（N2=%s）示例 %s"
                      % (tag, len(only), len(new), sorted({c[2] for c in new}),
                         sorted(only)[:3]))
    out = ROOT.parent / "v2_coverage.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n覆盖摘要：", out.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
