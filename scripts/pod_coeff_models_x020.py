# -*- coding: utf-8 -*-
"""DS-POD-3 + DS-POD-2：先诊断 N1=1 的 6.25，再在同一冻结点集上对照系数模型。

顺序说明（我建议并已获同意）：**先诊断再对照**。若 N1=1 的场量级本身就与其它点差一个数量级，
那 6.25 是"量级/归一化问题"而不是"模型差"；此时先做系数模型对照会浪费一轮工作。

硬约束（来自数据提供方与需求书）：
* **公共点集用已冻结的** `common_points_xyz_m.tsv`（1,373 点），**不得为了好看调整**；
* 远端**只读**（本脚本只读本地已下载的 7 个快照，不联网）；
* 复数**绝不丢虚部**；NaN **绝不当 0**；每折只用**训练**快照拟合（留出真值不得参与系数计算）；
* 报 **max**，不许只用 median 掩盖；每个数字写进 JSON 报告。

用法：work\\.venv\\Scripts\\python.exe scripts\\pod_coeff_models_x020.py
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
RUN = REPO / "work/runs/te2_8_pod_fields_20261005"
POINTS = RUN / "pod_pipeline_x020_v2/common_points_xyz_m.tsv"
MATDIR = RUN / "x020"
CACHE = RUN / "pod_pipeline_x020_v2/interp_cache.npz"
OUTDIR = RUN / "pod_pipeline_x020_v2/coeff_models"
REPORT = OUTDIR / "coeff_models_x020_report.json"
N1S = [1, 2, 3, 4, 5, 6, 7]
MODELS = ("persistence", "linear", "pchip", "rbf_tps", "poly1_ridge", "poly2_ridge")


def sha(p: pathlib.Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def main() -> int:
    import numpy as np
    import scipy.io as sio
    from scipy.interpolate import griddata, PchipInterpolator, RBFInterpolator

    OUTDIR.mkdir(parents=True, exist_ok=True)
    rep: dict = {"kind": "pod_coeff_models_x020", "points_file": str(POINTS.relative_to(REPO)),
                 "sha256_points_file": sha(POINTS), "n1s": N1S, "models": list(MODELS),
                 "errors": [], "steps": []}

    pts = np.loadtxt(POINTS, delimiter="\t", skiprows=1)
    rep["n_points_frozen"] = int(pts.shape[0])

    # ---- 载入 7 快照并插值到冻结点集（缓存）----
    if CACHE.is_file():
        z = np.load(CACHE)
        P = z["P"]                      # (n_points, n_snap) complex
        mask = z["mask"]                # (n_points,) bool
        rep["steps"].append("复用插值缓存 %s" % CACHE.name)
    else:
        cols = []
        for n1 in N1S:
            f = MATDIR / ("x0.20_N%02d_f20MHz.mat" % n1)
            m = sio.loadmat(str(f))
            src = np.column_stack([m["x_m"].ravel(), m["y_m"].ravel(), m["z_m"].ravel()])
            p = np.asarray(m["p_total_Pa"]).ravel()
            fin = np.asarray(m["p_finite_mask"]).ravel().astype(bool)
            t0 = time.perf_counter()
            re = griddata(src[fin], p[fin].real, pts, method="linear", fill_value=np.nan)
            im = griddata(src[fin], p[fin].imag, pts, method="linear", fill_value=np.nan)
            cols.append(re + 1j * im)
            rep["steps"].append("%s 插值 %.1fs 有限 %d/%d" % (
                f.name, time.perf_counter() - t0, int(np.isfinite(re).sum()), pts.shape[0]))
        P = np.column_stack(cols)
        mask = np.isfinite(P.real).all(axis=1) & np.isfinite(P.imag).all(axis=1)
        np.savez_compressed(CACHE, P=P, mask=mask)
        rep["steps"].append("写插值缓存 %s" % CACHE.name)
    rep["common_mask"] = {"n_frozen": int(pts.shape[0]), "n_common": int(mask.sum()),
                          "frac": float(mask.mean())}
    X = P[mask]                                    # (n_common, 7) complex
    norms = np.linalg.norm(X, axis=0)
    rep["field_norm_by_n1"] = {str(n): float(v) for n, v in zip(N1S, norms)}
    rep["field_norm_ratio_max_min"] = float(norms.max() / max(norms.min(), 1e-300))
    rep["real_imag_energy_by_n1"] = {
        str(n): {"re": float(np.linalg.norm(X[:, i].real)), "im": float(np.linalg.norm(X[:, i].imag))}
        for i, n in enumerate(N1S)}

    # ---- POD（全 7 点，仅作诊断：系数轨迹）----
    mean_all = X.mean(axis=1, keepdims=True)
    U, S, Vt = np.linalg.svd(X - mean_all, full_matrices=False)
    energy = (S ** 2) / float((S ** 2).sum())
    k999 = int(np.searchsorted(np.cumsum(energy), 0.999) + 1)
    rep["pod_diagnostic"] = {"n_modes_999": k999,
                             "energy_first5": [float(e) for e in energy[:5]]}
    C = U[:, :k999].conj().T @ (X - mean_all)      # (k, 7) 系数（诊断用）
    rep["coeff_trajectory"] = {
        "n1": N1S,
        "coeff_real": [[float(C[r, j].real) for j in range(len(N1S))] for r in range(k999)],
        "coeff_imag": [[float(C[r, j].imag) for j in range(len(N1S))] for r in range(k999)],
        "coeff_abs": [[float(abs(C[r, j])) for j in range(len(N1S))] for r in range(k999)]}
    # 全局相位诊断（不做相位对齐，只报告）
    ph = np.angle(X.sum(axis=0))
    rep["global_phase_rad_by_n1"] = {str(n): float(v) for n, v in zip(N1S, ph)}

    # ---- DS-POD-2：逐折对照（每折只用训练快照拟合）----
    def fit_coeffs(train_idx, k):
        Xt = X[:, train_idx]
        mu = Xt.mean(axis=1, keepdims=True)
        Ut, St, _ = np.linalg.svd(Xt - mu, full_matrices=False)
        kk = max(1, min(k, Ut.shape[1]))
        B = Ut[:, :kk]
        Ct = B.conj().T @ (Xt - mu)                 # (kk, n_train)
        return mu, B, Ct

    def predict(kind, xs, Ct, xq):
        """xs = 训练 N1（升序），Ct = (kk, n_train)；返回 (kk,) 预测系数。"""
        kk = Ct.shape[0]
        out = np.zeros(kk, dtype=complex)
        for r in range(kk):
            for part, idx in (("re", 0), ("im", 1)):
                y = (Ct[r].real if part == "re" else Ct[r].imag)
                if kind == "persistence":
                    v = y[int(np.argmin(np.abs(xs - xq)))]
                elif kind == "linear":
                    v = (np.interp(xq, xs, y) if xs.min() <= xq <= xs.max()
                         else float(y[0] + (y[1] - y[0]) * (xq - xs[0]) / (xs[1] - xs[0]))
                         if xq < xs.min() else
                         float(y[-1] + (y[-1] - y[-2]) * (xq - xs[-1]) / (xs[-1] - xs[-2])))
                elif kind == "pchip":
                    v = (float(PchipInterpolator(xs, y)(xq)) if xs.min() <= xq <= xs.max()
                         else float(y[0] + (y[1] - y[0]) * (xq - xs[0]) / (xs[1] - xs[0]))
                         if xq < xs.min() else
                         float(y[-1] + (y[-1] - y[-2]) * (xq - xs[-1]) / (xs[-1] - xs[-2])))
                elif kind == "rbf_tps":
                    v = float(RBFInterpolator(xs[:, None].astype(float), y,
                                              kernel="thin_plate_spline",
                                              degree=1, smoothing=0.0)([[float(xq)]])[0])
                elif kind in ("poly1_ridge", "poly2_ridge"):
                    deg = 1 if kind == "poly1_ridge" else 2
                    xn = (xs - xs.mean()) / max(xs.std(), 1e-12)
                    V = np.vander(xn, deg + 1, increasing=True)
                    coef = np.linalg.solve(V.T @ V + 1e-8 * np.eye(deg + 1), V.T @ y)
                    xq_n = (xq - xs.mean()) / max(xs.std(), 1e-12)
                    v = float(np.asarray(
                        np.vander([xq_n], deg + 1, increasing=True) @ coef).ravel()[0])
                else:
                    raise ValueError(kind)
                out[r] += v * (1 if part == "re" else 1j)
        return out

    res: dict = {}
    for kind in MODELS:
        rows = []
        for j, n1 in enumerate(N1S):
            tr = [i for i in range(len(N1S)) if i != j]
            xs = np.array([N1S[i] for i in tr], dtype=float)
            mu, B, Ct = fit_coeffs(tr, k999)
            cq = predict(kind, xs, Ct, float(n1))
            pred = mu[:, 0] + B @ cq
            true = X[:, j]
            rel = float(np.linalg.norm(pred - true) / np.linalg.norm(true))
            interior = bool(xs.min() < n1 < xs.max())
            rows.append({"held_out_n1": n1, "rel_L2": rel, "interior": interior,
                         "kind_of_point": "interior" if interior else "endpoint_extrapolation"})
        vals = [r["rel_L2"] for r in rows]
        res[kind] = {"per_fold": rows, "max": float(max(vals)),
                     "median": float(np.median(vals)),
                     "max_interior": float(max([r["rel_L2"] for r in rows if r["interior"]] or [float("nan")])),
                     "max_endpoint": float(max([r["rel_L2"] for r in rows if not r["interior"]] or [float("nan")]))}
    rep["coefficient_models"] = res
    rep["verdict"] = {
        "best_by_max": min(MODELS, key=lambda m: res[m]["max"]),
        "best_by_median": min(MODELS, key=lambda m: res[m]["median"]),
        "persistence_max": res["persistence"]["max"],
        "note": "max 是门禁；median 仅供参考，二者差距大时必须点出。"}
    rep["ok"] = True
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print("冻结点集 %d，公共掩膜 %d (%.4f%%)" % (pts.shape[0], rep["common_mask"]["n_common"],
                                              100 * rep["common_mask"]["frac"]))
    print("‖场‖ 随 N1:", {k: round(v, 3) for k, v in rep["field_norm_by_n1"].items()})
    print("‖场‖ max/min 比 = %.3g" % rep["field_norm_ratio_max_min"])
    print("POD 99.9% 模数 =", k999, " 首模能量 %.6f" % energy[0])
    print()
    print("%-14s %8s %8s | 逐点 rel_L2（N1=1..7）" % ("模型", "max", "median"))
    for kind in MODELS:
        r = res[kind]
        print("%-14s %8.4f %8.4f | %s" % (
            kind, r["max"], r["median"],
            " ".join("%.3f%s" % (f["rel_L2"], "" if f["interior"] else "*") for f in r["per_fold"])))
    print("（* = 端点外推折）")
    print("最好（按 max）:", rep["verdict"]["best_by_max"], "｜最好（按 median）:",
          rep["verdict"]["best_by_median"])
    print("报告：", REPORT.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
