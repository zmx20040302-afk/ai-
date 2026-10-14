# -*- coding: utf-8 -*-
"""为批次 C 生成**公共窗口 5–35 MHz** 的派生列（裁定 §4「双视图」）。

背景：范围依赖量（峰值/带宽/Q/端点旗标）**由扫描范围定义**。A 的上界是 35 MHz、C 是 50 MHz，
直接跨批比较会得出错误结论（A 里 `peak_at_range_edge` 指"顶在 35"，C 里指"顶在 50"）。
裁定要求**双视图并存**：C 的 5–50 原生列**不得覆盖**，另新增带 `_5_35` 后缀的列。

跨批比较**只允许**用公共窗口列，且**仅限**同时满足（裁定 §4.2）：
1. 峰不在公共窗口边界；
2. 左右 −3 dB 交点均在公共窗口内部；
3. **两批对同一组合均满足**闭合条件（本条要在与 A 配对时才判，本脚本只出各批自身的两个条件）。

另显式写出 `scan_fmin_Hz` / `scan_fmax_Hz`，使扫描范围成为数据版本的一部分。

⚠️ 只**新增**文件；不覆盖 `dataset/`（批 A）与 `mirror/`（批 C）。

用法：
    python -B scripts/build_public_window.py --mirror work/runs/x-densify-20260928/mirror \
        --out work/runs/x-densify-20260928/combos_public5_35.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
PUB_LO, PUB_HI = 5e6, 35e6          # 公共窗口
NATIVE_LO, NATIVE_HI = 5e6, 50e6     # C 的原生范围


def read_rows(p: pathlib.Path):
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = ln.strip()
        if s and not s.startswith("%"):
            yield s.split()


def local_maxima(ys: list[float]) -> list[int]:
    return [i for i in range(1, len(ys) - 1) if ys[i] > ys[i - 1] and ys[i] > ys[i + 1]]


def half_power(fs: list[float], db: list[float], i_peak: int):
    """围绕 i_peak 的 −3 dB 带宽：左右各取最近穿越点（线性插值）。

    返回 (f_low, f_high, width, q, closed)；未同时落在窗口内 ⇒ closed=False（**绝不填 0**）。
    """
    level = db[i_peak] - 3.0
    f_peak = fs[i_peak]
    lo = hi = None
    for i in range(len(fs) - 1):
        y0, y1 = db[i], db[i + 1]
        if (y0 - level) * (y1 - level) <= 0 and y1 != y0:
            f = fs[i] + (fs[i + 1] - fs[i]) * (level - y0) / (y1 - y0)
            if f <= f_peak:
                lo = f if lo is None else max(lo, f)
            if f >= f_peak:
                hi = f if hi is None else min(hi, f)
    closed = lo is not None and hi is not None and lo >= PUB_LO and hi <= PUB_HI
    if not closed:
        return lo, hi, None, None, False
    w = hi - lo
    return lo, hi, w, (f_peak / w if w > 0 else None), True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成 C 的 5–35 MHz 公共窗口派生列")
    ap.add_argument("--mirror", type=pathlib.Path,
                    default=REPO / "work/runs/x-densify-20260928/mirror")
    ap.add_argument("--out", type=pathlib.Path,
                    default=REPO / "work/runs/x-densify-20260928/combos_public5_35.csv")
    args = ap.parse_args(argv)

    if not args.mirror.is_dir():
        print("[FAIL] 镜像不存在：%s" % args.mirror, file=sys.stderr)
        return 2

    combos: dict[tuple, list[tuple[float, float]]] = {}
    for run in sorted(p for p in args.mirror.iterdir() if p.is_dir() and p.name.startswith("cell_")):
        t9 = run / "Table_9.txt"
        if not t9.is_file():
            continue
        for f in read_rows(t9):
            if len(f) < 15:
                continue
            k = (round(float(f[0]), 6), round(float(f[1]), 6), round(float(f[2]), 6))
            combos.setdefault(k, []).append((float(f[3]), float(f[14])))

    rows = []
    for k in sorted(combos):
        v = sorted(combos[k])
        native = [f for f, _ in v]
        # 公共窗口子区间（严格 5–35 MHz 内的点）
        idx = [i for i, f in enumerate(native) if PUB_LO - 1 <= f <= PUB_HI + 1]
        fs = [native[i] for i in idx]
        db = [v[i][1] for i in idx]
        rec = {"x_scale": k[0], "N_w_te1": k[1], "N_w_te2": k[2],
               "scan_fmin_Hz": int(min(native)), "scan_fmax_Hz": int(max(native)),
               "n_points_native": len(native), "n_points_5_35": len(fs),
               "window_fmin_Hz": int(PUB_LO), "window_fmax_Hz": int(PUB_HI)}
        if fs:
            i_pk = max(range(len(db)), key=lambda j: db[j])
            edge = i_pk in (0, len(db) - 1)
            loc = local_maxima(db)
            lo, hi, w, q, closed = half_power(fs, db, i_pk)
            rec.update({
                "spl_max_5_35_dB": db[i_pk], "f_peak_5_35_Hz": fs[i_pk],
                "peak_at_range_edge_5_35": edge,
                "n_local_maxima_5_35": len(loc),
                "f_low_3dB_5_35_Hz": lo, "f_high_3dB_5_35_Hz": hi,
                "bandwidth_3dB_5_35_Hz": w, "q_from_points_5_35": q,
                "bandwidth_not_closed_5_35": (not closed),
                # 裁定 §4.2 的两个自身条件（第三个"两批都闭合"需与 A 配对时才判）
                "peak_interior_5_35": (not edge),
                "bandwidth_closed_5_35": closed,
                "public_window_usable_5_35": bool((not edge) and closed),
            })
        rows.append(rec)

    cols = list(rows[0].keys())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})

    n = len(rows)
    usable = sum(1 for r in rows if r.get("public_window_usable_5_35"))
    edge = sum(1 for r in rows if r.get("peak_at_range_edge_5_35"))
    unclosed = sum(1 for r in rows if r.get("bandwidth_not_closed_5_35"))
    man = {
        "kind": "public_window_derived_columns",
        "protocol": "metric_protocol_v2",
        "batch": "C", "source_mirror": str(args.mirror).replace("\\", "/")[:0] or "…",
        "native_scan_MHz": [NATIVE_LO / 1e6, NATIVE_HI / 1e6],
        "public_window_MHz": [PUB_LO / 1e6, PUB_HI / 1e6],
        "n_combos": n,
        "n_public_window_usable": usable,
        "n_peak_at_range_edge_5_35": edge,
        "n_bandwidth_not_closed_5_35": unclosed,
        "policy": ("原生 5–50 列**未被覆盖**（本文件是新增的独立产物）；"
                   "跨批比较只用 `*_5_35` 列，且要求两批对同一组合均满足 "
                   "peak_interior_5_35 且 bandwidth_closed_5_35"),
        "note": "未闭合一律记带宽 = 空（不填 0），并置 bandwidth_not_closed_5_35 = True",
    }
    (args.out.with_suffix(".manifest.json")).write_text(
        json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote %s (%d 组合, %d 列)" % (args.out.relative_to(REPO), n, len(cols)))
    print("  公共窗口可用（峰在内部且带宽闭合）：%d / %d (%.1f%%)" % (usable, n, 100 * usable / n))
    print("  峰顶在窗口边界：%d ；带宽未闭合：%d" % (edge, unclosed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
