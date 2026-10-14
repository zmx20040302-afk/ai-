# -*- coding: utf-8 -*-
"""路线甲「一个族一跑到底」的门禁脚本：S1（模型 A / 模型 B）+ S2 + S5 + 门禁视图。

为什么单独有这个脚本：x 族现在不止一个（N1=4 是主族、N1=7 是**整层 holdout** 的跨层族），
`amp_shape_x_family.py` / `s2s5_modelB_x_family.py` 都把缓存路径写死成 n1_4，
再复制两份必然产生"两份会漂移的实现"。这里改成 `--tag` 参数化，
并把 S1 从「读别处的 JSON」改为**自己算**，使每个族的结论只依赖这一个文件。

⚠️ 本脚本是**独立重实现**：它算出的 n1_4 数字必须与 `amp_shape_x_n1_4.json` 对齐，
不一致就说明两份实现已经漂移，以本条为准并登记差异（不是"取好看的那个"）。

口径（与 §89 一致，不得在这里偷偷改）：
* 场级相对 L2 = ‖pred−true‖₂/‖true‖₂，**报 max，不报均值**；
* 关键区 = ‖xyz‖ ≤ R_max/3，R_max 取**公共掩膜内**点的最大模长；
* 幅值通道 = PCHIP 对 log10‖X‖；形状通道 = 单位范数形状的 POD 系数各自 PCHIP；
* S5 非一致性得分 = 逐快照相对 L2，校准用 **train 的 LOO 重拟合**，分位取第 ⌈(n+1)(1−α)⌉ 小。

用法：python scripts\\route_a_family_gate.py --tag n1_7
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
XF = REPO / "work/runs/te2_8_pod_fields_20261005/x_family"
POINTS = REPO / "work/runs/te2_8_pod_fields_20261005/pod_pipeline_x020_v2/common_points_xyz_m.tsv"
SPEC = REPO / "work/runs/solver/pmut-f1/solver_spec.json"
ALPHAS = (0.10, 0.05, 0.01)


def _svd_order(shp: np.ndarray, energy: float = 0.999) -> int:
    """按给定能量占比定 POD 阶数（在**只含训练点**的矩阵上做，避免折外信息）。"""
    import numpy as np
    mu = shp.mean(axis=1, keepdims=True)
    _u, s, _vt = np.linalg.svd(shp - mu, full_matrices=False)
    return max(1, int(np.searchsorted(np.cumsum(s ** 2) / (s ** 2).sum(), energy) + 1))


def main() -> int:
    import numpy as np
    from scipy.interpolate import PchipInterpolator

    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="n1_7")
    a = ap.parse_args()
    cache = XF / a.tag / ("interp_cache_x_%s.npz" % a.tag)
    if not cache.exists():
        print("[FAIL] 缺缓存：%s（先跑 fetch_and_align_x_family.py --n1 <n>）" % cache)
        return 2
    z = np.load(cache)
    P, mask, xs = z["P"], z["mask"], z["x_scale"].astype(float)
    role_x = [str(v) for v in z["role_x"]]
    role_n = [str(v) for v in z["role_n"]]
    X = P[mask]
    xyz = np.loadtxt(POINTS, delimiter="\t", skiprows=1)[mask]
    R = np.linalg.norm(xyz, axis=1)
    key = np.where(R <= R.max() / 3.0)[0]
    tr = np.array([i for i, r in enumerate(role_x) if r == "train"])
    ho = np.array([i for i, r in enumerate(role_x) if r == "holdout"])

    def fit_b(train_idx, q_x):
        trn = np.asarray(train_idx)
        nrm = np.linalg.norm(X[:, trn], axis=0)
        shp = X[:, trn] / nrm[None, :]
        mu = shp.mean(axis=1, keepdims=True)
        k = _svd_order(shp)
        U, _s, _v = np.linalg.svd(shp - mu, full_matrices=False)
        B = U[:, :k]
        C = B.conj().T @ (shp - mu)
        xo = xs[trn]
        order = np.argsort(xo)
        la = float(PchipInterpolator(xo[order], np.log10(nrm)[order])(q_x))
        cq = np.zeros(k, dtype=complex)
        for r_ in range(k):
            for part in ("re", "im"):
                y = (C[r_].real if part == "re" else C[r_].imag)[order]
                cq[r_] += float(PchipInterpolator(xo[order], y)(q_x)) * (1 if part == "re" else 1j)
        s = mu[:, 0] + B @ cq
        return (10 ** la) * (s / np.linalg.norm(s)), k

    def fit_pod3(train_idx, q_x):
        """模型 A：原始场 POD + 系数 PCHIP（k 由训练折能量 99.9% 定）。"""
        trn = np.asarray(train_idx)
        mu = X[:, trn].mean(axis=1, keepdims=True)
        U, _s, _v = np.linalg.svd(X[:, trn] - mu, full_matrices=False)
        k = max(1, int(np.searchsorted(
            np.cumsum(_s ** 2) / (_s ** 2).sum(), 0.999) + 1))
        B = U[:, :k]
        C = B.conj().T @ (X[:, trn] - mu)
        xo = xs[trn]
        order = np.argsort(xo)
        cq = np.zeros(k, dtype=complex)
        for r_ in range(k):
            for part in ("re", "im"):
                y = (C[r_].real if part == "re" else C[r_].imag)[order]
                cq[r_] += float(PchipInterpolator(xo[order], y)(q_x)) * (1 if part == "re" else 1j)
        return mu[:, 0] + B @ cq, k

    def rel2(pred, j):
        return float(np.linalg.norm(pred - X[:, j]) / np.linalg.norm(X[:, j]))

    rep: dict = {
        "kind": "route_a_family_gate", "tag": a.tag,
        "sha256_cache": hashlib.sha256(cache.read_bytes()).hexdigest(),
        "n_snapshots": int(X.shape[1]), "n_points_common": int(X.shape[0]),
        "n_frozen": int(P.shape[0]), "mask_frac": float(mask.mean()),
        "x_span": [float(xs.min()), float(xs.max())],
        "split": {"x_role": {k: role_x.count(k) for k in set(role_x)},
                  "n_role": {k: role_n.count(k) for k in set(role_n)}},
        "key_region": {"rule": "‖xyz‖ ≤ R_max/3", "n_points": int(key.size),
                       "R_max_m": float(R.max())},
        "errors": []}

    s1 = {}
    for label, fit in (("A_raw_pod", fit_pod3), ("B_amp_shape", fit_b)):
        g, kk = [], []
        for j in ho:
            pred, k = fit(tr, xs[j])
            g.append(rel2(pred, j))
            kk.append(float(np.linalg.norm(pred[key] - X[key, j]) / np.linalg.norm(X[key, j])))
        s1[label] = {"global_max": max(g), "key_max": max(kk),
                     "global_per_holdout": g, "key_per_holdout": kk, "k_last": k}
    rep["s1"] = s1

    s2 = []
    for j in ho:
        pred, _ = fit_b(tr, xs[j])
        t, p = float(np.max(np.abs(X[:, j]))), float(np.max(np.abs(pred)))
        s2.append({"x_scale": float(xs[j]), "true": t, "pred": p, "rel_err": abs(p - t) / t})
    rep["s2"] = {"per_holdout": s2, "max_rel_err": max(r["rel_err"] for r in s2)}

    cal = []
    for i in tr:
        others = [t for t in tr if t != i]
        cal.append(rel2(fit_b(others, xs[i])[0], i))
    cal_sorted = np.array(sorted(cal))
    n = int(cal_sorted.size)
    hold = [rel2(fit_b(tr, xs[j])[0], j) for j in ho]
    rep["s5"] = {"n_calibration": n, "certified": bool(n >= 9),
                 "calibration": {"min": float(cal_sorted[0]), "p50": float(np.median(cal_sorted)),
                                 "p90": float(cal_sorted[int(0.9 * n) - 1]),
                                 "max": float(cal_sorted[-1])},
                 "holdout_rel_L2": hold, "bands": {}}
    for al in ALPHAS:
        idx = min(n - 1, int(np.ceil((n + 1) * (1 - al))) - 1)
        band = float(cal_sorted[idx])
        rep["s5"]["bands"][str(al)] = {
            "band_rel_L2": band,
            "coverage_on_holdout": float(np.mean([1.0 if r <= band else 0.0 for r in hold])),
            "n_holdout": len(hold)}

    sys.path.insert(0, str(REPO / "src"))
    from memsharness import solver as SV
    spec = SV.load_spec(SPEC)
    ev = {"s1": {"global_rel_L2_max": s1["B_amp_shape"]["global_max"],
                 "key_region_rel_L2_max": s1["B_amp_shape"]["key_max"],
                 "n_holdout": int(ho.size), "is_independent": True},
          "s2": {"engineering_rel_err": {"max_abs_p": rep["s2"]["max_rel_err"]}},
          "s5": {"coverage": rep["s5"]["bands"]["0.1"]["coverage_on_holdout"],
                 "n_calibration": n, "certified": bool(n >= 9),
                 "n_holdout": int(ho.size)}}
    lv = SV.evaluate_levels(spec, ev)
    rep["gate_view"] = {k: v["verdict"] for k, v in lv["levels"].items()}
    rep["gate_checks"] = {k: lv["levels"][k]["checks"] for k in ("S1", "S2", "S5")}
    rep["ok"] = True
    out = XF / a.tag / ("route_a_gate_%s.json" % a.tag)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print("族 %s：%d 快照 × %d 公共点（掩膜 %.4f）｜x %g..%g｜切分 %s"
          % (a.tag, X.shape[1], X.shape[0], mask.mean(), xs.min(), xs.max(),
             json.dumps(rep["split"]["x_role"], ensure_ascii=False)))
    for label in ("A_raw_pod", "B_amp_shape"):
        print("  S1 %-11s 全域 max %.4f ｜ 关键区 max %.4f"
              % (label, s1[label]["global_max"], s1[label]["key_max"]))
    print("  S2 max|p| 相对误差 %.4f" % rep["s2"]["max_rel_err"])
    c = rep["s5"]["calibration"]
    print("  S5 校准 n=%d：min %.4f / p50 %.4f / p90 %.4f / max %.4f"
          % (n, c["min"], c["p50"], c["p90"], c["max"]))
    for al in ALPHAS:
        b = rep["s5"]["bands"][str(al)]
        print("     α=%.2f 半宽 %.4f ｜ 留出覆盖率 %.3f（%d 点）"
              % (al, b["band_rel_L2"], b["coverage_on_holdout"], b["n_holdout"]))
    print("  门禁视图：", json.dumps(rep["gate_view"], ensure_ascii=False))
    print("  报告：", out.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
