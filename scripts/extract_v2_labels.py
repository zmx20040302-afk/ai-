# -*- coding: utf-8 -*-
"""v2 导出 → 「组合×频率」结构表 + 峰值/带宽标志 + 截断组合清单（**草稿，尚未冻结为版本**）。

数据：`work/runs/remote-exported-v2-20260922/exported_results_v2/cell_te2_{5,7,8,9}_test_v2_*/`
每条 cell 是完整全因子网格：x_scale 0.1..1.0 × N_w_te1 1..N2−1，频率 5–35 MHz 步长 0.5 MHz。

三个必须带上的标志（否则删失/截断值会被当成正常测量值）：
* `peak_at_scan_endpoint` —— 逐组合在 Table_9 上取 SPL 最大处的频率，若 == 35 MHz（扫描上限）
  则该"峰值频率"是**下界**（右删失），不得参与排名；
* `bw_upper_cutoff_at_endpoint` —— −3 dB 截断点表里上截止点 == 35 MHz ⇒ 宽度/Q/阻尼比被截断；
* `freq_range` —— 本批是 **5–35 MHz**，与批次 C 的 5–50 MHz **不可直接混算**（红线 §4）。

桥接方法：`Bandwidth.txt` 只有 `freq/SPL/宽度/Q/阻尼比` 五列、**没有参数列**，
故用**峰值 SPL 的精确数值**把截断 level 挂回组合（SPL 是浮点标识符，可逐位匹配），
匹配不上的行如实报为未归属，**不猜**。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
ROOT = REPO / "work/runs/remote-exported-v2-20260922/exported_results_v2"
OUT = REPO / "work/runs/remote-exported-v2-20260922"
META_RE = re.compile(r"^%\s*(Model|Version|Date|Table)\s*:")


def load_txt(p: pathlib.Path) -> tuple[list[str], list[list[str]]]:
    head: list[str] = []
    rows: list[list[str]] = []
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            s = ln.rstrip("\n")
            if not s.strip():
                continue
            if s.lstrip().startswith("%"):
                if not META_RE.match(s.strip()):          # 表头本身也是 `%` 行
                    body = s.lstrip()[1:]
                    head = [t.strip() for t in re.split(r"\s{2,}", body.strip()) if t.strip()]
                continue
            if head:
                rows.append(s.split())
    return head, rows


def main() -> int:
    out_rows: list[dict] = []
    trunc: list[dict] = []
    sanity: dict = {}
    for c in sorted(p for p in ROOT.iterdir() if p.is_dir() and p.name.startswith("cell_")):
        cell = c.name.replace("cell_", "").split("_test_v2")[0]
        h9, r9 = load_txt(c / "Table_9.txt")
        i9 = {n: i for i, n in enumerate(h9)}
        F, S = i9["freq (Hz)"], i9["总声压级 (dB), 点: (0, 0, -1E-5)"] if \
            "总声压级 (dB), 点: (0, 0, -1E-5)" in i9 else i9[[k for k in i9 if k.startswith("总声压级")][0]]
        per: dict[tuple, list[tuple[float, float]]] = {}
        for r in r9:
            key = (r[i9["x_scale"]], r[i9["N_w_te1"]], r[i9["N_w_te2"]])
            per.setdefault(key, []).append((float(r[F]), float(r[S])))
        f_hi = max(f for v in per.values() for f, _ in v)
        f_lo = min(f for v in per.values() for f, _ in v)

        hb, rb = load_txt(c / "Bandwidth.txt")
        ib = {n: i for i, n in enumerate(hb)}
        levels: list[dict] = []
        for k in range(0, len(rb) - 1, 2):                 # 成对：下截止点 / 上截止点
            a, b = rb[k], rb[k + 1]
            levels.append({"spl": float(a[ib["总声压级 (dB)"]]),
                           "f_lo": float(a[ib["freq (Hz)"]]),
                           "f_hi": float(b[ib["freq (Hz)"]]),
                           "width": float(a[ib["宽度 (Hz)"]]),
                           "Q": float(a[ib["Q 因子"]]),
                           "zeta": float(a[ib["阻尼比"]])})
        by_spl: dict[float, list[dict]] = {}
        for lv in levels:
            # ⚠️ 实测：Bandwidth.txt 的 SPL 列 = 峰值 SPL **减 3.0 dB**（就是 −3 dB 电平本身），
            # 不是峰值 SPL。直接按峰值 SPL 匹配会 0 命中（我第一版就栽在这）。
            by_spl.setdefault(round(lv["spl"] + 3.0, 9), []).append(lv)

        matched = unmatched = 0
        for key, vals in sorted(per.items()):
            vals.sort()
            pk = max(vals, key=lambda t: t[1])
            row = {"cell": cell, "x_scale": key[0], "N_w_te1": key[1], "N_w_te2": key[2],
                   "n_freq": len(vals), "freq_min_Hz": vals[0][0], "freq_max_Hz": vals[-1][0],
                   "peak_freq_Hz": pk[0], "peak_spl_dB": pk[1],
                   "peak_at_scan_endpoint": bool(abs(pk[0] - f_hi) < 1.0)}
            hit = by_spl.get(round(pk[1], 9))
            if hit:
                lv = hit[0]
                row.update({"bw_f_lo_Hz": lv["f_lo"], "bw_f_hi_Hz": lv["f_hi"],
                            "bandwidth_Hz": lv["width"], "Q": lv["Q"], "zeta": lv["zeta"],
                            "bw_upper_cutoff_at_endpoint": bool(abs(lv["f_hi"] - f_hi) < 1.0)})
                matched += 1
            else:
                row.update({"bw_f_lo_Hz": None, "bw_f_hi_Hz": None, "bandwidth_Hz": None,
                            "Q": None, "zeta": None, "bw_upper_cutoff_at_endpoint": None})
                unmatched += 1
            out_rows.append(row)
            if row["peak_at_scan_endpoint"] or row.get("bw_upper_cutoff_at_endpoint"):
                trunc.append(row)
        sanity[cell] = {"n_combos": len(per), "n_levels_in_bw_table": len(levels),
                        "n_freq_per_combo": sorted({len(v) for v in per.values()}),
                        "freq_grid": [f_lo, f_hi],
                        "levels_matched_to_combo": matched,
                        "combos_without_level": unmatched}

    cols = ["cell", "x_scale", "N_w_te1", "N_w_te2", "n_freq", "freq_min_Hz", "freq_max_Hz",
            "peak_freq_Hz", "peak_spl_dB", "peak_at_scan_endpoint", "bw_f_lo_Hz", "bw_f_hi_Hz",
            "bandwidth_Hz", "Q", "zeta", "bw_upper_cutoff_at_endpoint"]
    csv_p = OUT / "v2_labels_draft.csv"
    with csv_p.open("w", encoding="utf-8", newline="") as fh:
        fh.write(",".join(cols) + "\n")
        for r in out_rows:
            fh.write(",".join("" if r.get(k) is None else str(r.get(k)) for k in cols) + "\n")

    print("== 结构 ==")
    for k, v in sanity.items():
        print("  %-7s 组合 %3d ｜ 截断 level 表 %3d 行 ｜ 每组合频点 %s ｜ 频率 %g–%g Hz"
              % (k, v["n_combos"], v["n_levels_in_bw_table"], v["n_freq_per_combo"],
                 v["freq_grid"][0], v["freq_grid"][1]))
        print("          挂回组合 %d 个 ｜ 无对应 level %d 个"
              % (v["levels_matched_to_combo"], v["combos_without_level"]))
    n_end = sum(1 for r in out_rows if r["peak_at_scan_endpoint"])
    n_bw = sum(1 for r in out_rows if r.get("bw_upper_cutoff_at_endpoint"))
    print("  合计 %d 组合 ｜ 峰值落在 35 MHz 端点 %d（%.1f%%）｜ 带宽上截止点=35 MHz %d（%.1f%%）"
          % (len(out_rows), n_end, 100 * n_end / len(out_rows), n_bw,
             100 * n_bw / len(out_rows)))

    md = ["# v2 批次中「被删失/被截断」的组合清单（5–35 MHz 扫描）", "",
          "扫描上限 35 MHz。以下组合的峰值落在上限（**真峰在 35 MHz 或更高，此处只是下界**），",
          "或 −3 dB 上截止点等于上限（**宽度/Q/阻尼比被截断**）⇒ 不得用于排名或带宽统计。", ""]
    md.append("| cell | x_scale | N_w_te1 | N2 | 峰值频率 (MHz) | 峰值 SPL (dB) | 峰在端点 | 带宽 (MHz) | Q | 上截止=端点 |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(trunc, key=lambda x: (x["cell"], x["x_scale"], int(x["N_w_te1"]))):
        md.append("| %s | %s | %s | %s | %.2f | %.2f | %s | %s | %s | %s |"
                  % (r["cell"], r["x_scale"], r["N_w_te1"], r["N_w_te2"],
                     r["peak_freq_Hz"] / 1e6, r["peak_spl_dB"],
                     "**是**" if r["peak_at_scan_endpoint"] else "—",
                     "%.3f" % (r["bandwidth_Hz"] / 1e6) if r["bandwidth_Hz"] else "—",
                     "%.2f" % r["Q"] if r["Q"] else "—",
                     "**是**" if r.get("bw_upper_cutoff_at_endpoint") else "—"))
    (OUT / "v2_truncated_combos.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (OUT / "v2_labels_draft_meta.json").write_text(json.dumps(
        {"kind": "v2_extraction_draft", "frozen": False, "sanity": sanity,
         "n_rows": len(out_rows), "n_peak_at_endpoint": n_end,
         "n_bw_truncated": n_bw,
         "note": "草稿：尚未注册为不可变数据版本；不得用于放行"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n结构表：", csv_p.relative_to(REPO))
    print("截断清单：", (OUT / "v2_truncated_combos.md").relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
