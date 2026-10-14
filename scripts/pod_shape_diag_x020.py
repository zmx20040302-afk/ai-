# -*- coding: utf-8 -*-
"""场形状诊断 + 门禁改写（不需要新增仿真）。

回答一个问题：**N1=2/3 的坏折，是"插值密度不够"还是"场形状真的变了"？**
做法（全部用已缓存的插值结果，不重插值、不联网、不动冻结点集）：
1. 逐 N1 的 `‖场‖₂` 与相邻比值；
2. **单位范数复场形状** `u_j = X_j/‖X_j‖`，算相邻内积 `|<u_i,u_{j+1}>|` ⇒ 形状突变的**位置**；
3. 形状矩阵的 POD 能量（与原始场 POD 对照）⇒ 形状需要几模；
4. `max|p|` 及其**空间位置**随 N1 的变化 ⇒ 是否有峰位迁移（模式变化的另一证据）；
5. **门禁改写**：主判据 = 最坏折相对**原始场最近邻保持基线**的比值（< 1）+ 全体 max；
   "优于基线的折数"降为**诊断量**（它会掩盖单折严重劣化）。

用法：work\\.venv\\Scripts\\python.exe scripts\\pod_shape_diag_x020.py
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
RUN = REPO / "work/runs/te2_8_pod_fields_20261005"
V2 = RUN / "pod_pipeline_x020_v2"
CACHE = V2 / "interp_cache.npz"
POINTS = V2 / "common_points_xyz_m.tsv"
GPT_REPORT = V2 / "coeff_models_v2/coeff_models_x020_normalized_report.json"
OUTDIR = V2 / "shape_diag"
REPORT = OUTDIR / "shape_diag_x020.json"
N1S = [1, 2, 3, 4, 5, 6, 7]


def sha(p: pathlib.Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def main() -> int:
    import numpy as np

    OUTDIR.mkdir(parents=True, exist_ok=True)
    rep: dict = {"kind": "pod_shape_diag_x020", "n1s": N1S,
                 "sha256_cache": sha(CACHE), "sha256_points": sha(POINTS),
                 "sha256_gpt_report": sha(GPT_REPORT), "errors": []}
    if not CACHE.is_file():
        print("[FAIL] 缺插值缓存：%s" % CACHE.relative_to(REPO)); return 2
    z = np.load(CACHE)
    P, mask = z["P"], z["mask"]
    X = P[mask]                      # (n_common, 7) complex
    pts = np.loadtxt(POINTS, delimiter="\t", skiprows=1)[mask]
    rep["n_common"] = int(mask.sum())

    norms = np.linalg.norm(X, axis=0)
    rep["field_norm_by_n1"] = {str(n): float(v) for n, v in zip(N1S, norms)}
    rep["norm_ratio_consecutive"] = {
        "%d->%d" % (N1S[i], N1S[i + 1]): float(norms[i + 1] / norms[i])
        for i in range(len(N1S) - 1)}
    rep["norm_max_over_min"] = float(norms.max() / norms.min())

    U = X / norms[None, :]                       # 单位范数形状（复数）
    G = np.abs(U.conj().T @ U)                   # 7x7 形状相关（|内积|，1 = 完全相同）
    rep["shape_gram_abs"] = [[round(float(v), 6) for v in row] for row in G]
    rep["shape_corr_consecutive"] = {
        "%d-%d" % (N1S[i], N1S[i + 1]): float(G[i, i + 1]) for i in range(len(N1S) - 1)}
    i_min = int(np.argmin([G[i, i + 1] for i in range(len(N1S) - 1)]))
    rep["biggest_shape_change"] = {"between": [N1S[i_min], N1S[i_min + 1]],
                                   "corr": float(G[i_min, i_min + 1])}

    def modes_999(M):
        s = np.linalg.svd(M, compute_uv=False)
        e = np.cumsum((s ** 2) / float((s ** 2).sum()))
        return int(np.searchsorted(e, 0.999) + 1), [round(float(x), 6) for x in e[:5]]
    k_raw, cum_raw = modes_999(X - X.mean(axis=1, keepdims=True))
    k_shape, cum_shape = modes_999(U - U.mean(axis=1, keepdims=True))
    rep["modes_999_raw_field"] = k_raw
    rep["modes_999_unit_shape"] = k_shape
    rep["energy_cum_raw_head"] = cum_raw
    rep["energy_cum_shape_head"] = cum_shape

    # 峰位迁移：max|p| 及其坐标
    peak = []
    for j, n in enumerate(N1S):
        a = np.abs(X[:, j]); i = int(np.argmax(a))
        peak.append({"n1": n, "max_abs_p": float(a[i]),
                     "xyz_um": [round(float(v) * 1e6, 3) for v in pts[i]]})
    rep["peak_location_by_n1"] = peak
    rng = [np.linalg.norm(np.array(p["xyz_um"]) - np.array(peak[0]["xyz_um"])) for p in peak]
    rep["peak_shift_from_n1_1_um"] = [round(float(v), 3) for v in rng]

    # 门禁改写：以 GPT 报告里的数字现算"最坏折/基线"比值（主判据）
    gate = {"primary": "worst_fold_ratio_vs_raw_persistence_baseline_lt_1 AND overall_max_reported",
            "secondary_diagnostic_only": ["n_folds_better_than_baseline"],
            "reason": "6/7 折优于基线会掩盖单折严重劣化（实测 N1=2 折为基线的 1.99 倍）"}
    if GPT_REPORT.is_file():
        d = json.loads(GPT_REPORT.read_text(encoding="utf-8"))
        ms = d.get("models") or {}
        def folds(name):
            v = (ms.get(name) or {})
            return [f.get("rel_L2") for f in (v.get("per_fold") or [])]
        base = folds("raw_linear")  # 占位：真基线见下
        raw_p = d.get("raw_persistence") or {}
        base_folds = [f.get("rel_L2") for f in (raw_p.get("per_fold") or [])]
        best = folds("norm_shape_pchip")
        if base_folds and best:
            base_max, best_max = max(base_folds), max(best)
            k = int(np.argmax(best))
            gate.update({
                "baseline_max": float(base_max), "best_model": "norm_shape_pchip",
                "best_max": float(best_max), "ratio": float(best_max / base_max),
                "worst_fold": {"n1": N1S[k] if k < len(N1S) else None,
                               "rel_L2": float(best_max),
                               "vs_baseline_ratio": float(best_max / base_folds[k])
                               if k < len(base_folds) else None},
                "n_folds_better_than_baseline": int(sum(
                    1 for a, b in zip(best, base_folds) if a < b)),
                "primary_pass": bool(best_max / base_max < 1.0)})
    rep["gate"] = gate
    rep["ok"] = True
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print("公共点 %d" % rep["n_common"])
    print("‖场‖ 相邻比值:", {k: round(v, 3) for k, v in rep["norm_ratio_consecutive"].items()})
    print("形状相关（相邻）:", {k: round(v, 4) for k, v in rep["shape_corr_consecutive"].items()})
    print("形状变化最大处:", rep["biggest_shape_change"])
    print("99.9%% 模数：原始场 %d ｜ 单位形状 %d" % (k_raw, k_shape))
    print("max|p| 峰位迁移(µm):", rep["peak_shift_from_n1_1_um"])
    print("门禁:", json.dumps({k: v for k, v in gate.items() if k != "reason"}, ensure_ascii=False))
    print("报告：", REPORT.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
