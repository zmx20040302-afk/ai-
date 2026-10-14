# -*- coding: utf-8 -*-
"""小规模端到端打通（第 3 步）：x=0.20 那一列的 7 个快照 → 公共点集/掩膜 → POD → 留一验证。

为什么先做这一列：x 固定 ⇒ 几何相同、点云天然接近，最适合验证**管线**（不是科学结论）。
7 个快照沿 N1=1..7 变化 ⇒ POD 基描述"沿 N1 的场变化"，留一就是留一个 N1 出去。

口径（写死，与 field-io-contract 对齐）：
* **公共点集** = 取点数最少的那个快照的坐标作为参考网格（x 固定 ⇒ 几何一致）；
  其余快照用 KDTree 最近邻映射到该网格，**超过容差的点算未映射**（不得硬插）；
* **公共掩膜** = 所有快照在参考网格上都"有限且已映射"的点；POD 与误差**只在掩膜上**统计；
* **场级误差** = rel_L2 = ‖pred−true‖₂/‖true‖₂（掩膜点上、双方有限），**报 max**，不用平均值掩盖；
* 远端**只读**；本地落 `work/runs/te2_8_pod_fields_20261005/`。

用法：work\\.venv\\Scripts\\python.exe scripts\pipeline_smoke_x020.py
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
HOST = "ubuntu-10-180-7-46"
RDIR = "/home/lab/projAI4US/autodesign/exported_results/te2_8_pod_fields_20MHz_v1/pod_20MHz"
OUT = REPO / "work/runs/te2_8_pod_fields_20261005"
MATDIR = OUT / "x020"
REPORT = OUT / "pipeline_smoke_x020.json"
N1S = [1, 2, 3, 4, 5, 6, 7]
TOL_M = 1e-9          # 最近邻映射容差（几何相同 ⇒ 应能精确映射；超过即记未映射）


def fetch(name: str) -> tuple[pathlib.Path, dict]:
    p = MATDIR / name
    info = {"name": name}
    if not p.is_file():
        r = subprocess.run(["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                            "%s:%s/%s" % (HOST, RDIR, name), str(p)],
                           capture_output=True, text=True, timeout=600)
        info["rc"] = r.returncode
        if r.returncode != 0:
            info["stderr"] = (r.stderr or "")[-200:]
    if p.is_file():
        info["bytes"] = p.stat().st_size
        info["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    return p, info


def main() -> int:
    import numpy as np
    import scipy.io as sio
    from scipy.spatial import cKDTree

    MATDIR.mkdir(parents=True, exist_ok=True)
    rep: dict = {"kind": "pipeline_smoke_x020", "host_dir": "%s:%s" % (HOST, RDIR),
                 "n1s": N1S, "tol_m": TOL_M, "files": [], "steps": [], "errors": []}
    snaps = []
    for n1 in N1S:
        name = "x0.20_N%02d_f20MHz.mat" % n1
        p, info = fetch(name)
        rep["files"].append(info)
        if not p.is_file():
            rep["errors"].append("取不到 %s" % name)
            continue
        m = sio.loadmat(str(p))
        xyz = np.column_stack([m["x_m"].ravel(), m["y_m"].ravel(), m["z_m"].ravel()])
        pv = np.asarray(m["p_total_Pa"]).ravel()
        mask = np.asarray(m["p_finite_mask"]).ravel().astype(bool)
        snaps.append({"n1": n1, "xyz": xyz, "p": pv, "finite": mask,
                      "n_points": int(xyz.shape[0])})
    rep["loaded"] = [{"n1": s["n1"], "n_points": s["n_points"],
                      "n_finite": int(s["finite"].sum()),
                      "max_abs_p": float(np.nanmax(np.abs(s["p"][s["finite"]])))
                      if s["finite"].any() else None} for s in snaps]
    if len(snaps) < 3:
        rep["errors"].append("可用快照不足（%d）⇒ 无法做 POD" % len(snaps))
        REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(rep["errors"], ensure_ascii=False)); return 2

    # ---- 公共点集：以点数最少的快照为参考网格 ----
    ref = min(snaps, key=lambda s: s["n_points"])
    ref_xyz = ref["xyz"]
    rep["reference_snapshot"] = {"n1": ref["n1"], "n_points": ref["n_points"]}
    tree = cKDTree(ref_xyz)

    mapped, common = [], np.ones(ref_xyz.shape[0], dtype=bool)
    for s in snaps:
        t0 = time.perf_counter()
        d, idx = tree.query(s["xyz"], k=1)
        ok = d <= TOL_M                       # 参考网格点在源快照里能找到（就近）
        back = np.zeros(ref_xyz.shape[0], dtype=bool)
        val = np.full(ref_xyz.shape[0], np.nan, dtype=complex)
        src_ok = s["finite"] & ok
        back[idx[src_ok]] = True
        val[idx[src_ok]] = s["p"][src_ok]
        mapped.append(val)
        common &= back
        s["_map_ok_rate"] = float(back.mean())
        s["_map_seconds"] = round(time.perf_counter() - t0, 2)
    rep["mapping"] = [{"n1": s["n1"], "map_ok_rate": s["_map_ok_rate"],
                       "seconds": s["_map_seconds"]} for s in snaps]
    rep["common_mask"] = {"n_ref_points": int(ref_xyz.shape[0]),
                          "n_common": int(common.sum()),
                          "frac": float(common.mean())}
    if common.sum() < 100:
        rep["errors"].append("公共掩膜点太少（%d）⇒ 中止" % int(common.sum()))
        REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(rep["errors"], ensure_ascii=False)); return 2

    # ---- POD（在公共掩膜上）----
    X = np.column_stack([v[common] for v in mapped])          # (n_common, n_snap)
    mean = X.mean(axis=1, keepdims=True)
    A = X - mean
    U, S, Vt = np.linalg.svd(A, full_matrices=False)
    energy = (S ** 2) / float((S ** 2).sum())
    rep["pod"] = {"n_modes_kept_for_999": int(np.searchsorted(np.cumsum(energy), 0.999) + 1),
                  "energy_first5": [round(float(e), 6) for e in energy[:5]],
                  "energy_cumsum_999_ok": bool(np.cumsum(energy)[-1] >= 0.999)}

    # ---- 留一：留一个 N1 出去，用其余 N1 重构场，算 rel_L2 ----
    loo = []
    for j, s in enumerate(snaps):
        cols = [i for i in range(len(snaps)) if i != j]
        Xt = X[:, cols]
        mt = Xt.mean(axis=1, keepdims=True)
        At = Xt - mt
        Ut, St, _ = np.linalg.svd(At, full_matrices=False)
        k = max(1, int(np.searchsorted(np.cumsum((St ** 2) / (St ** 2).sum()), 0.999) + 1))
        B = Ut[:, :k]
        coef = B.conj().T @ (X[:, j] - mt[:, 0])
        pred = mt[:, 0] + B @ coef
        true = X[:, j]
        rel = float(np.linalg.norm(pred - true) / np.linalg.norm(true))
        loo.append({"held_out_n1": s["n1"], "k_modes": k, "rel_L2": rel})
    rep["loo"] = loo
    rep["loo_max_rel_L2"] = max(l["rel_L2"] for l in loo)
    rep["loo_median_rel_L2"] = float(np.median([l["rel_L2"] for l in loo]))
    rep["verdict"] = ("pipeline_ok" if rep["common_mask"]["frac"] > 0.5
                      and rep["loo_max_rel_L2"] < 1.0 else "pipeline_check_failed")
    rep["ok"] = True
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("参考快照 n1=%d  n_ref=%d  公共掩膜 %d (%.1f%%)"
          % (ref["n1"], ref["n_points"], rep["common_mask"]["n_common"],
             100 * rep["common_mask"]["frac"]))
    print("POD 前 5 能量占比:", rep["pod"]["energy_first5"])
    print("留一 rel_L2:", [(l["held_out_n1"], round(l["rel_L2"], 4)) for l in loo])
    print("loo max/median = %.4f / %.4f  verdict=%s"
          % (rep["loo_max_rel_L2"], rep["loo_median_rel_L2"], rep["verdict"]))
    for e in rep["errors"]:
        print("  [错误]", e[:160])
    print("报告：", REPORT.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
