# -*- coding: utf-8 -*-
"""第 3 项之 1：按**模型 B（幅值/形状分离）**重算 S2 与 S5（含重新校准半宽）。

为什么必须重算：上一轮的 S2/S5 是用**模型 A（原始场 POD）**的预测算的；
模型 B 把关键区误差从 2.13% 降到 0.70% ⇒ 旧的 S5 覆盖率（0.800，failed）**不能代表模型 B**。

做法（与前面同纪律：切分沿用导出方、折内选模、只报 max）：
* **S2**：域内 `max|p|` 的预测 vs 真值相对误差（5 个留出点，报 max）；
* **S5**：非一致性得分 = 逐快照**相对 L2**（`‖pred−true‖/‖true‖`），
  **校准只用 train 的 LOO 重拟合**（每次留出一个 train 快照、只用其余 75 个拟合模型 B 的全流程）；
  保形分位取第 `⌈(n+1)(1−α)⌉` 小的得分；覆盖率在 5 个留出点上评（点数少 ⇒ 如实标注噪声）；
* 同时给 α = 0.10 / 0.05 / 0.01 三档；
* 最后把 S1/S2/S5 喂给 `solver.evaluate_levels` 出门禁视图（S0/S3/S4 如实 inconclusive）。

用法：work\\.venv\\Scripts\\python.exe scripts\\s2s5_modelB_x_family.py
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
D = REPO / "work/runs/te2_8_pod_fields_20261005/x_family/n1_4"
CACHE = D / "interp_cache_x_n1_4.npz"
POINTS = REPO / "work/runs/te2_8_pod_fields_20261005/pod_pipeline_x020_v2/common_points_xyz_m.tsv"
SPEC = REPO / "work/runs/solver/pmut-f1/solver_spec.json"
OUT = D / "s2s5_modelB_x_n1_4.json"
KEY_F = 1 / 3
ALPHAS = (0.10, 0.05, 0.01)


def main() -> int:
    import numpy as np
    from scipy.interpolate import PchipInterpolator

    z = np.load(CACHE)
    P, mask, xs = z["P"], z["mask"], z["x_scale"].astype(float)
    role_x = [str(v) for v in z["role_x"]]
    X = P[mask]
    pts = np.loadtxt(POINTS, delimiter="\t", skiprows=1)[mask]
    key_idx = np.where(np.linalg.norm(pts, axis=1) <= KEY_F * float(
        np.linalg.norm(pts, axis=1).max()))[0]
    tr = np.array([i for i, r in enumerate(role_x) if r == "train"])
    ho = np.array([i for i, r in enumerate(role_x) if r == "holdout"])
    rep: dict = {"kind": "s2s5_modelB", "sha256_cache": hashlib.sha256(CACHE.read_bytes()).hexdigest(),
                 "model": "B: log10‖X‖ PCHIP + unit-norm shape POD + coeff PCHIP",
                 "n_train": int(tr.size), "n_holdout": int(ho.size), "errors": []}

    def fit_predict(train_idx, q_x, *, predict_idx=None):
        """在 train_idx 上拟合模型 B，预测 x=q_x 的场（返回完整掩膜向量）。"""
        trn = np.asarray(train_idx)
        nrm = np.linalg.norm(X[:, trn], axis=0)
        shp = X[:, trn] / nrm[None, :]
        mu_s = shp.mean(axis=1, keepdims=True)
        Us, Ss, _ = np.linalg.svd(shp - mu_s, full_matrices=False)
        e = np.cumsum((Ss ** 2) / (Ss ** 2).sum())
        k = max(1, int(np.searchsorted(e, 0.999) + 1))
        B = Us[:, :k]
        C = B.conj().T @ (X[:, trn] / np.linalg.norm(X[:, trn], axis=0)[None, :] - mu_s)
        xo = xs[trn]
        order = np.argsort(xo); xsort = xo[order]
        # 幅值
        la = float(PchipInterpolator(xsort, np.log10(nrm)[order])(q_x))
        # 形状系数
        cq = np.zeros(k, dtype=complex)
        for r_ in range(k):
            for part in ("re", "im"):
                y = (C[r_].real if part == "re" else C[r_].imag)[order]
                cq[r_] += float(PchipInterpolator(xsort, y)(q_x)) * (1 if part == "re" else 1j)
        s = mu_s[:, 0] + B @ cq
        s = s / np.linalg.norm(s)
        return (10 ** la) * s, k

    # ---- S2 ----
    s2 = []
    for j in ho:
        pred, k = fit_predict(tr, xs[j])
        t, p = float(np.max(np.abs(X[:, j]))), float(np.max(np.abs(pred)))
        s2.append({"x_scale": float(xs[j]), "max_abs_p_true": t, "max_abs_p_pred": p,
                   "rel_err": abs(p - t) / t, "k_shape": k})
    rep["s2"] = {"per_holdout": s2, "max_rel_err": max(r["rel_err"] for r in s2)}

    # ---- S5：校准 = train 的 LOO 重拟合 ----
    scores = []
    for i in tr:
        others = [t for t in tr if t != i]
        pred, _ = fit_predict(others, xs[i])
        scores.append(float(np.linalg.norm(pred - X[:, i]) / np.linalg.norm(X[:, i])))
    scores_sorted = np.array(sorted(scores))
    n = len(scores_sorted)
    rep["s5"] = {"n_calibration_train": n, "score_kind": "per-snapshot relative L2 (LOO refit)",
                 "scores": {"min": float(scores_sorted[0]), "p50": float(np.median(scores_sorted)),
                            "p90": float(scores_sorted[int(0.9 * n) - 1]), "max": float(scores_sorted[-1])},
                 "bands": {}}
    rels = []
    for j in ho:
        pred, _ = fit_predict(tr, xs[j])
        rels.append(float(np.linalg.norm(pred - X[:, j]) / np.linalg.norm(X[:, j])))
    rep["s5"]["holdout_rel_L2"] = rels
    for alpha in ALPHAS:
        idx = min(n - 1, int(np.ceil((n + 1) * (1 - alpha))) - 1)
        band = float(scores_sorted[idx])
        cov = float(np.mean([1.0 if r <= band else 0.0 for r in rels]))
        rep["s5"]["bands"][str(alpha)] = {"band_rel_L2": band, "coverage_on_holdout": cov,
                                          "n_holdout": len(rels),
                                          "holdout_rel": rels}

    # ---- 门禁视图 ----
    sys.path.insert(0, str(REPO / "src"))
    from memsharness import solver as SV
    amp = json.loads((D / "amp_shape_x_n1_4.json").read_text(encoding="utf-8"))
    spec = SV.load_spec(SPEC)
    ev = {"s1": {"global_rel_L2_max": amp["model_B_amp_shape"]["global_max"],
                 "key_region_rel_L2_max": amp["model_B_amp_shape"]["key_max"],
                 "n_holdout": int(ho.size), "is_independent": True},
          "s2": {"engineering_rel_err": {"max_abs_p": rep["s2"]["max_rel_err"]}},
          "s5": {"coverage": rep["s5"]["bands"]["0.1"]["coverage_on_holdout"],
                 "n_calibration": n, "certified": True,
                 "n_holdout": int(ho.size)}}
    lv = SV.evaluate_levels(spec, ev)
    rep["gate_view"] = {k: v["verdict"] for k, v in lv["levels"].items()}
    rep["gate_checks_S1"] = lv["levels"]["S1"]["checks"]
    rep["gate_checks_S5"] = lv["levels"]["S5"]["checks"]
    rep["ok"] = True
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print("S2（域内 max|p|，模型 B）：max 相对误差 = %.4f" % rep["s2"]["max_rel_err"])
    print("S5 校准（train LOO，n=%d）：得分 min %.4f / p50 %.4f / p90 %.4f / max %.4f"
          % (n, scores_sorted[0], np.median(scores_sorted),
             scores_sorted[int(0.9 * n) - 1], scores_sorted[-1]))
    for alpha in ALPHAS:
        b = rep["s5"]["bands"][str(alpha)]
        print("   α=%.2f 半宽(相对) %.4f ｜ 留出覆盖率 %.3f（%d 点）"
              % (alpha, b["band_rel_L2"], b["coverage_on_holdout"], b["n_holdout"]))
    print("门禁视图：", json.dumps(rep["gate_view"], ensure_ascii=False))
    print("S5 逐项：", json.dumps(rep["gate_checks_S5"], ensure_ascii=False)[:240])
    print("报告：", OUT.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
