# -*- coding: utf-8 -*-
"""S4 的**独立复算**（第二方法）：各网格节点 → 冻结点**线性插值**，再算两两相对 L2。

为什么不用最近节点：λ(20 MHz, 水) ≈ 75 µm，最粗网格节点间距 3 µm ⇒ 最近节点是**分段常数**，
自身误差 ~2π·(h/λ)/2 ≈ 10%，**大于被测的量（2%）**，用它复核会得出 13–17% 的假差异。
线性插值的误差是 O(h²)，与报告所用口径同量级，且实现完全独立。

守卫：只在**公共有限掩膜**上比（各网格插值都成功的点），NaN **不用 0 填**；报 max 不报均值。

⚠️ **默认只读（R16 修复，见 INDEX 本轮 R1–R4 裁决与落地的末尾节；节号以锁内定号为准）**：
本脚本**不写任何文件**，除非显式给 `--out <路径>`。修复前它会把结果 JSON 写进 `RUN`
（= **被校验目录**），而同一个 `RUN` 在同一作用域又被 `RUN.glob("mesh_*/field_points.npz")` 读
⇒ 命中 R16 的 D2 `write_to_read_root`。修复后输出路径**由调用方显式给出**
（建议落在被校验树**之外**），默认路径下**不写被校验树**。
"""
from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
RUN = REPO / "work/runs/s34-mesh-20261006T131318Z"
PTS = REPO / "work/runs/te2_8_pod_fields_20261005/pod_pipeline_x020_v2/common_points_xyz_m.tsv"
REPORTED = {("h3um", "h2um"): 0.0206, ("h3um", "h14um"): 0.0231361,
            ("h2um", "h14um"): 0.0132, ("h2um", "ftet_lamda6"): 0.0123,
            ("h14um", "ftet_lamda6"): 0.0132, ("h3um", "ftet_lamda6"): 0.0161}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="S4 独立复算（默认**只读**：不给 --out 就不写任何文件）")
    ap.add_argument("--out", default=None,
                    help="显式给出才写结果 JSON；缺省不写盘（R16：默认路径不得写被校验树）")
    a = ap.parse_args(argv)
    args = a                       # 下面 `for a, b in itertools.permutations(...)` 会复用名字 `a`

    import numpy as np
    from scipy.interpolate import LinearNDInterpolator

    pts = np.loadtxt(PTS, delimiter="\t", skiprows=1)
    R = np.linalg.norm(pts, axis=1)
    keymask = R <= R.max() / 3.0
    vals: dict[str, np.ndarray] = {}
    for d in sorted(RUN.glob("mesh_*/field_points.npz")):
        z = np.load(d)
        xyz = np.column_stack([z["x_m"].real, z["y_m"].real, z["z_m"].real])
        p = z["p_Pa"]
        fin = np.isfinite(p.real) & np.isfinite(p.imag) & z["finite_mask"].astype(bool) \
            & np.isfinite(xyz).all(axis=1)
        tag = d.parent.name.replace("mesh_", "")
        assert tag not in vals, "重复的档名：%s" % tag
        interp = LinearNDInterpolator(xyz[fin], p[fin], fill_value=np.nan + 0j)
        v = np.asarray(interp(pts), dtype=complex).reshape(-1)
        vals[tag] = v
        print("  %-14s 源节点 %6d（有限 %6d）→ 冻结点可插值 %4d / %d"
              % (tag, p.size, int(fin.sum()), int(np.isfinite(v.real).sum()), v.size))

    common = np.ones(pts.shape[0], dtype=bool)
    for v in vals.values():
        common &= np.isfinite(v.real) & np.isfinite(v.imag)
    ck = common & keymask
    print("\n  公共有限掩膜 %d/%d = %.4f%%（报告 1369/1373 = 99.7087%%）｜ 关键区 %d 点"
          % (common.sum(), common.size, 100 * common.mean(), ck.sum()))

    out: dict = {"method": "linear ND interpolation onto frozen points (independent reimpl)",
                 "mask": int(common.sum()), "pairs": {}}
    worst = ("", 0.0)
    print("\n  %-16s %-16s %10s %10s %10s" % ("A", "B", "复算全域", "报告", "差(pp)"))
    for a, b in itertools.permutations(sorted(vals), 2):
        if a > b:
            continue
        fa, fb = vals[a][common], vals[b][common]
        rel = float(np.linalg.norm(fa - fb) / np.linalg.norm(fb))
        krel = float(np.linalg.norm(vals[a][ck] - vals[b][ck]) / np.linalg.norm(vals[b][ck]))
        rep = REPORTED.get((a, b), REPORTED.get((b, a)))
        out["pairs"]["%s|%s" % (a, b)] = {"rel_L2": rel, "key_rel_L2": krel, "reported": rep}
        print("  %-16s %-16s %9.4f%% %9s %10s"
              % (a, b, 100 * rel, "%.4f%%" % (100 * rep) if rep else "—",
                 "%+.2f" % (100 * (rel - rep)) if rep else "—"))
        if rel > worst[1]:
            worst = ("%s|%s" % (a, b), rel)
    out["worst_pair"] = worst[0]
    out["worst_rel_L2"] = worst[1]
    out["verdict_vs_2pct"] = "failed" if worst[1] > 0.02 else "passed"
    # ---- 输出：**默认只读**；只有显式 --out 才落盘（且由调用方选在被校验树之外）（R16）
    out_path = pathlib.Path(args.out) if args.out else None
    if out_path is not None:
        if not out_path.is_absolute():
            out_path = REPO / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n  结果 JSON 已写出：%s" % out_path)
    else:
        print("\n  未给 --out ⇒ **未写任何文件**（本脚本默认只读）")
    print("\n  ⇒ 独立复算最差对 %s = %.4f%%（判据 2%% ⇒ %s）"
          % (worst[0], 100 * worst[1], out["verdict_vs_2pct"]))
    print("  报告最差 = 2.3136%%（h3um|h14um）；两者是否同向超线：%s"
          % (worst[1] > 0.02))
    return 0


if __name__ == "__main__":
    sys.exit(main())
