# -*- coding: utf-8 -*-
"""路线甲（x 单参数族 POD 场求解器）的**族清单**：从本地索引抽出训练/留出集，不下载。

为什么先做这一步：路线甲的唯一参数是 `x_scale`（固定 N1、N2、freq）。
在动手下载与 POD 之前，必须先把"哪些快照是训练、哪些是导出方划的留出"钉死，
并估算体积与插值成本——**下载 81 个快照前先知道要花多少**。

只读本地 `snapshot_index.tsv`；不联网、不写远端。
用法：work\\.venv\\Scripts\\python.exe scripts\\plan_x_family.py --n1 4
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
RUN = REPO / "work/runs/te2_8_pod_fields_20261005"
INDEX = RUN / "snapshot_index.tsv"
OUTDIR = RUN / "x_family"
OUT = OUTDIR / "x_family_manifest.json"


def sha(p: pathlib.Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="路线甲 x 单参数族的训练/留出清单")
    ap.add_argument("--n1", type=float, default=4.0, help="固定的 N_w_te1（避开已被证明不光滑的 N1 方向）")
    ap.add_argument("--n2", type=float, default=8.0)
    ap.add_argument("--freq", type=float, default=20000000.0)
    ap.add_argument("--index", default=str(INDEX))
    ap.add_argument("--out", default=None,
                    help="缺省 = x_family_manifest_n1_<N1>.json（**按族命名**，避免互相覆盖）")
    a = ap.parse_args(argv)
    # ⚠️ 输出**按族命名**：初版用一个固定文件名，循环跑 N1=1/4/7 时后一次把前一次**静默覆盖**，
    # 导致我拿 N1=7 的清单去跑"N1=4 的族"（实测踩到）。
    out = (pathlib.Path(a.out) if a.out
           else OUTDIR / ("x_family_manifest_n1_%g.json" % a.n1))

    OUTDIR.mkdir(parents=True, exist_ok=True)
    ip = pathlib.Path(a.index)
    if not ip.is_file():
        print("[FAIL] 缺本地清单：%s" % ip); return 2
    rows = list(csv.DictReader(ip.open(encoding="utf-8", newline=""), delimiter="\t"))
    sel = [r for r in rows
           if num(r.get("kind") and str(r.get("kind")).strip() == "pod20")
           and num(r.get("N_w_te1")) == a.n1 and num(r.get("N_w_te2")) == a.n2
           and num(r.get("freq_Hz")) == a.freq]
    rep: dict = {"kind": "x_family_manifest",
                 "family": {"fixed": {"N_w_te1": a.n1, "N_w_te2": a.n2, "freq_Hz": a.freq},
                            "varying": "x_scale"},
                 "index_file": str(ip.relative_to(REPO)), "sha256_index": sha(ip),
                 "n_rows_in_index": len(rows), "n_family": len(sel),
                 "why_this_family": ("N1 方向实测不光滑（单位形状相关 2→3 仅 0.207；幅值跨 60.9 倍）"
                                     "⇒ 首个可放行族只取 x 单变量"),
                 "errors": []}
    if not sel:
        rep["errors"].append("该族在索引里没有快照，检查 N1/N2/freq 取值")
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[FAIL] 族为空"); return 2

    items = []
    for r in sel:
        f = pathlib.Path(str(r.get("file")))
        items.append({"x_scale": num(r.get("x_scale")), "file": f.name,
                      "remote_path": str(r.get("file")),
                      "n_points": num(r.get("n_points")),
                      "status": r.get("status"),
                      "split_x": r.get("x_holdout_role"), "split_n": r.get("n_holdout_role"),
                      "source_model": r.get("source_model", "").strip() if r.get("source_model") else None})
    items.sort(key=lambda d: (d["x_scale"] if d["x_scale"] is not None else 1e9))
    rep["items"] = items
    xs = [d["x_scale"] for d in items if d["x_scale"] is not None]
    reps_ = [d["n_points"] for d in items if d["n_points"] is not None]
    by_split_x: dict[str, int] = {}
    by_split_n: dict[str, int] = {}
    for d in items:
        by_split_x[str(d["split_x"])] = by_split_x.get(str(d["split_x"]), 0) + 1
        by_split_n[str(d["split_n"])] = by_split_n.get(str(d["split_n"]), 0) + 1
    rep["summary"] = {
        "n_snapshots": len(items), "x_min": min(xs), "x_max": max(xs),
        "x_step_est": round((max(xs) - min(xs)) / max(1, len(set(xs)) - 1), 6) if len(set(xs)) > 1 else None,
        "n_distinct_x": len(set(xs)),
        "n_points_min": int(min(reps_)), "n_points_max": int(max(reps_)),
        "n_points_sum": int(sum(reps_)),
        "by_split_x": by_split_x, "by_split_n": by_split_n,
        "download_bytes_estimate": None,
        "interp_cost_note": ("公共点集建好前无法精确估；按 7 快照实测（每快照 griddata ≈1.4 s / 6 万点），"
                             "该族合计 %d 点 ⇒ 插值量级为分钟到十几分钟" % int(sum(reps_))),
    }
    # 本地已有几个（x020 那 7 个属于 N1=1..7；若本族 N1!=1 则为 0）
    local = [d["file"] for d in items if (RUN / "x020" / d["file"]).is_file()]
    rep["summary"]["n_local_already"] = len(local)
    rep["ok"] = True
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    s = rep["summary"]
    print("族：N1=%g, N2=%g, f=%g ｜ 快照 %d 个 ｜ x ∈ [%s, %s]（%d 个不同值，步长≈%s）"
          % (a.n1, a.n2, a.freq, s["n_snapshots"], s["x_min"], s["x_max"],
             s["n_distinct_x"], s["x_step_est"]))
    print("点数：min %d / max %d ｜ 合计 %d" % (s["n_points_min"], s["n_points_max"], s["n_points_sum"]))
    print("导出方切分：x_role=%s ｜ n_role=%s" % (s["by_split_x"], s["by_split_n"]))
    print("本地已有 %d 个（需下载 %d 个）" % (s["n_local_already"], s["n_snapshots"] - s["n_local_already"]))
    print("报告：", out.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
