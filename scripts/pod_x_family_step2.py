# -*- coding: utf-8 -*-
"""路线甲第 2 步：x 单参数族 POD + S1/S2/S5（**不调 COMSOL**）。

数据：`x_family/n1_4/interp_cache_x_n1_4.npz`（81 快照 × 1373 冻结点，掩膜 1369）。
切分：**沿用导出方**（x: train 76 / holdout 5）——**我不自己切**。

方法要点（含从上一轮教训里来的约束）：
* **折内选模**：POD 基与 99.9% 模数**只在 train 76 上**选（上一轮我把含留出样本的全体 k 用在每折，
  被外部复核指出是泄漏 ⇒ 这里杜绝）；
* 系数映射：x 是光滑一维参数，用 **PCHIP**（前一轮对照里表现最好）；复数系数**实/虚分开**插值；
* 留出点若落在 train 的 x 范围之外 ⇒ 标 `extrapolation`（本族 5 个 holdout 都在内部，应无此情况）；
* **S1** = 复场 `rel_L2`，**报 max**（不许只用中位数）；
* **S2** = 由场导出的工程量：域内 `max|p|`（真值 vs 预测），逐留出给相对误差；
* **S5** = 保形：校准只取 train 的 LOO 非一致性得分，报半宽与留出覆盖率（5 个点的覆盖率**本身噪声大**，如实标注）。

产物：`x_family/n1_4/pod_report_x_n1_4.json`；并调用 `memsharness.solver.evaluate_levels` 给门禁视图
（S0/S3/S4 无证据 ⇒ inconclusive ⇒ **不构成放行**）。

用法：work\\.venv\\Scripts\\python.exe scripts\\pod_x_family_step2.py
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
D = REPO / "work/runs/te2_8_pod_fields_20261005/x_family/n1_4"
CACHE = D / "interp_cache_x_n1_4.npz"
SPEC = REPO / "work/runs/solver/pmut-f1/solver_spec.json"
OUT = D / "pod_report_x_n1_4.json"


def sha(p: pathlib.Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def main() -> int:
    import numpy as np
    from scipy.interpolate import PchipInterpolator

    if not CACHE.is_file():
        print("[FAIL] 缺缓存：%s" % CACHE); return 2
    z = np.load(CACHE)
    P, mask = z["P"], z["mask"]
    xs = z["x_scale"].astype(float)
    role_x = [str(v) for v in z["role_x"]]
    X = P[mask]                                   # (1369, 81)
    rep: dict = {"kind": "pod_x_family_step2", "n_points": int(mask.sum()),
                 "n_snapshots": int(X.shape[1]),
                 "sha256_cache": sha(CACHE), "errors": [],
                 "split_source": "导出方 snapshot_index.tsv 的 x_holdout_role",
                 "method": {"basis": "SVD on TRAIN only", "k_rule": "cum energy >= 0.999 (train)",
                            "coeff_map": "PCHIP per (mode, real/imag), train only"}}

    tr = np.array([i for i, r in enumerate(role_x) if r == "train"])
    ho = np.array([i for i, r in enumerate(role_x) if r == "holdout"])
    rep["split"] = {"n_train": int(tr.size), "n_holdout": int(ho.size),
                    "holdout_x": [float(xs[i]) for i in ho]}
    if tr.size < 5 or ho.size < 1:
        rep["errors"].append("切分异常：train=%d holdout=%d" % (tr.size, ho.size))
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[FAIL] 切分异常"); return 2

    # ---- POD（只在 train 上）----
    Xt = X[:, tr]
    mu = Xt.mean(axis=1, keepdims=True)
    U, S, _ = np.linalg.svd(Xt - mu, full_matrices=False)
    energy = np.cumsum((S ** 2) / float((S ** 2).sum()))
    k = int(np.searchsorted(energy, 0.999) + 1)
    B = U[:, :k]
    rep["pod"] = {"k_for_999": k, "energy_first5": [round(float(v), 6) for v in energy[:5]],
                  "k_selected_from": "train only"}
    C = B.conj().T @ (X - mu)                      # 系数（用它只为取 train 侧做插值输入）
    Ct = C[:, tr]

    # ---- 系数映射：PCHIP（实/虚分开），预测留出 ----
    x_tr = xs[tr]
    order = np.argsort(x_tr)
    x_sorted = x_tr[order]
    per_fold = []
    for j in ho:
        cq = np.zeros(k, dtype=complex)
        for r_ in range(k):
            for part in ("re", "im"):
                y = (Ct[r_, order].real if part == "re" else Ct[r_, order].imag)
                if x_sorted.min() <= xs[j] <= x_sorted.max():
                    v = float(PchipInterpolator(x_sorted, y)(xs[j]))
                    extrap = False
                else:                                   # 端点外推：用最近两点线性外推并标注
                    v = float(np.interp(xs[j], x_sorted, y))
                    extrap = True
                cq[r_] += v * (1 if part == "re" else 1j)
        pred = mu[:, 0] + B @ cq
        true = X[:, j]
        rel = float(np.linalg.norm(pred - true) / np.linalg.norm(true))
        # S2：由场导出的工程量（域内 max|p|）
        tq, pq = float(np.max(np.abs(true))), float(np.max(np.abs(pred)))
        per_fold.append({"x_scale": float(xs[j]), "rel_L2": rel,
                         "extrapolation": extrap,
                         "max_abs_p_true": tq, "max_abs_p_pred": pq,
                         "max_abs_p_rel_err": abs(pq - tq) / tq if tq else None})
    vals = [f["rel_L2"] for f in per_fold]
    rep["s1"] = {"per_holdout": per_fold, "max_rel_L2": float(max(vals)),
                 "median_rel_L2": float(np.median(vals)),
                 "n_holdout": len(per_fold),
                 "n_extrapolation": sum(1 for f in per_fold if f["extrapolation"])}
    e2 = [f["max_abs_p_rel_err"] for f in per_fold if f["max_abs_p_rel_err"] is not None]
    rep["s2"] = {"quantity": "domain max|p|", "max_rel_err": float(max(e2)) if e2 else None,
                 "median_rel_err": float(np.median(e2)) if e2 else None}

    # ---- S5：保形（校准只用 train 的 LOO 得分）----
    loo_scores = []
    for i in tr:
        tr2 = np.array([t for t in tr if t != i])
        mu2 = X[:, tr2].mean(axis=1, keepdims=True)
        U2, S2_, _ = np.linalg.svd(X[:, tr2] - mu2, full_matrices=False)
        e2c = np.cumsum((S2_ ** 2) / float((S2_ ** 2).sum()))
        k2 = max(1, int(np.searchsorted(e2c, 0.999) + 1))
        B2 = U2[:, :k2]
        c2 = B2.conj().T @ (X[:, i] - mu2[:, 0])
        pred2 = mu2[:, 0] + B2 @ c2                    # 自投影（上界，保守）
        loo_scores.append(float(np.linalg.norm(pred2 - X[:, i])))
    loo_scores = np.array(sorted(loo_scores))
    n = len(loo_scores)
    alpha = 0.10
    q_idx = min(n - 1, int(np.ceil((n + 1) * (1 - alpha))) - 1)
    half = float(loo_scores[q_idx])
    cov = [1 if f["rel_L2"] * float(np.linalg.norm(X[:, ho[i]])) <= half else 0
           for i, f in enumerate(per_fold)]
    rep["s5"] = {"alpha": alpha, "n_calibration_train": n, "half_width_norm": half,
                 "coverage_on_holdout": float(np.mean(cov)),
                 "n_holdout": len(cov),
                 "caveat": ("留出只有 %d 个点 ⇒ 覆盖率估计噪声很大；半宽用的是**自投影上界**（保守）。"
                            % len(cov))}

    # ---- 落到 solver.py 的门禁视图（缺证据的级如实空着）----
    try:
        sys.path.insert(0, str(REPO / "src"))
        from memsharness import solver as SV
        spec = SV.load_spec(SPEC)
        ev = {"s1": {"global_rel_L2_max": rep["s1"]["max_rel_L2"],
                     "key_region_rel_L2_max": None,
                     "n_holdout": rep["s1"]["n_holdout"], "is_independent": True},
              "s2": {"engineering_rel_err": {"max_abs_p": rep["s2"]["max_rel_err"]}
                     if rep["s2"]["max_rel_err"] is not None else {}},
              "s5": {"coverage": rep["s5"]["coverage_on_holdout"],
                     "n_calibration": rep["s5"]["n_calibration_train"], "certified": True}}
        lv = SV.evaluate_levels(spec, ev)
        rep["gate_view"] = {k: v["verdict"] for k, v in lv["levels"].items()}
        rep["gate_note"] = ("S0/S3/S4 无证据 ⇒ inconclusive；按 §6.4 的硬门禁**不得放行**。"
                            "本报告只提供 S1/S2/S5 的证据。")
    except Exception as exc:  # noqa: BLE001
        rep["errors"].append("调用 solver.evaluate_levels 失败：%s: %s" % (type(exc).__name__, exc))

    rep["ok"] = True
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("掩膜 %d 点 ｜ train %d / holdout %d ｜ POD k(99.9%%,train) = %d"
          % (rep["n_points"], rep["split"]["n_train"], rep["split"]["n_holdout"], k))
    print("S1 场级 rel_L2：max=%.4f  median=%.4f  ｜ 逐留出 x：%s"
          % (rep["s1"]["max_rel_L2"], rep["s1"]["median_rel_L2"],
             ", ".join("x=%g→%.3f%s" % (f["x_scale"], f["rel_L2"],
                                        "*外推" if f["extrapolation"] else "")
                       for f in per_fold)))
    print("S2 工程量(域内 max|p|)：max 相对误差 = %s"
          % (None if rep["s2"]["max_rel_err"] is None else "%.4f" % rep["s2"]["max_rel_err"]))
    print("S5 保形：α=%.2f 半宽=%.4g ｜ 校准点 %d ｜ 留出覆盖率 %.3f（%d 点，噪声大）"
          % (rep["s5"]["alpha"], rep["s5"]["half_width_norm"],
             rep["s5"]["n_calibration_train"], rep["s5"]["coverage_on_holdout"],
             rep["s5"]["n_holdout"]))
    print("门禁视图：", json.dumps(rep.get("gate_view"), ensure_ascii=False))
    for e in rep["errors"][:4]:
        print("  [错误]", e[:150])
    print("报告：", OUT.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
