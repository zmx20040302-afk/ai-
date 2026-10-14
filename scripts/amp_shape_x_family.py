# -*- coding: utf-8 -*-
"""第 2 项：振幅/形状分离（并在同一次运行里更正适用范围）。

为什么做这个：第 1 项（提模数）显示误差在 k≥5 **平台化**（关键区恒 ~2.09%）⇒ 瓶颈不在基；
而 train 自投影在 k=3 时高达 **2.2051（220%）** ⇒ 说明**均值减除对小幅值快照极具破坏性**
（幅值跨几十倍，均值被大幅值样本主导）。外部实施方在 N1 族上正是用"幅值/形状分离"把最坏折降了 87%。

本次对比（同一缓存、同一 train 76 / holdout 5、同一 PCHIP、**都不调 COMSOL**）：
* **模型 A（现状）**：对原始复场做 POD + 系数 PCHIP；
* **模型 B（分离）**：`log10 ‖X‖` 用 PCHIP 建模；**单位范数形状**做 POD + 系数 PCHIP；
  预测后先归一化形状、再乘回幅值；
* 两者都报 **全域 max** 与 **关键区 max**（关键区 = `R/R_max ≤ 1/3`，51 点）。

同时：
* **定位 220%**：给出逐 x 的自投影相对误差（预期在小 x 端爆炸）；
* **更正 applicability**：`x_scale` 收窄到**留出证据覆盖的范围**（0.33–0.93），
  并在 spec 里写明"训练范围更宽但两端无留出证据"——**声明不得超出证据**（本仓库红线）。

用法：work\\.venv\\Scripts\\python.exe scripts\\amp_shape_x_family.py
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
OUT = D / "amp_shape_x_n1_4.json"
KEY_F = 1 / 3


def main() -> int:
    import numpy as np
    from scipy.interpolate import PchipInterpolator

    z = np.load(CACHE)
    P, mask, xs = z["P"], z["mask"], z["x_scale"].astype(float)
    role_x = [str(v) for v in z["role_x"]]
    X = P[mask]
    pts = np.loadtxt(POINTS, delimiter="\t", skiprows=1)[mask]
    R = np.linalg.norm(pts, axis=1)
    key_idx = np.where(R <= KEY_F * float(R.max()))[0]
    all_idx = np.arange(X.shape[0])
    tr = np.array([i for i, r in enumerate(role_x) if r == "train"])
    ho = np.array([i for i, r in enumerate(role_x) if r == "holdout"])
    x_tr = xs[tr]; order = np.argsort(x_tr); xs_s = x_tr[order]

    def pchip_predict(C, k, xq):
        out = np.zeros(k, dtype=complex)
        for r_ in range(k):
            for part in ("re", "im"):
                y = (C[r_].real if part == "re" else C[r_].imag)[order]
                out[r_] += float(PchipInterpolator(xs_s, y)(xq)) * (1 if part == "re" else 1j)
        return out

    def relmax(idx, pred, j):
        return float(np.linalg.norm(pred[idx] - X[:, j][idx]) / np.linalg.norm(X[:, j][idx]))

    rep: dict = {"kind": "amp_shape_x_family", "sha256_cache": hashlib.sha256(
        CACHE.read_bytes()).hexdigest(), "key_region_f": KEY_F, "n_key_points": int(key_idx.size),
        "n_train": int(tr.size), "n_holdout": int(ho.size), "errors": []}

    # ---------- 模型 A：原始场 POD ----------
    Xt = X[:, tr]; mu = Xt.mean(axis=1, keepdims=True)
    U, S, _ = np.linalg.svd(Xt - mu, full_matrices=False)
    kA = int(np.searchsorted(np.cumsum((S ** 2) / (S ** 2).sum()), 0.999) + 1)
    BA = U[:, :kA]; CA = BA.conj().T @ (X - mu)
    gA = kA_ = 0.0
    for j in ho:
        pred = mu[:, 0] + BA @ pchip_predict(CA[:, tr], kA, xs[j])
        gA = max(gA, relmax(all_idx, pred, j)); kA_ = max(kA_, relmax(key_idx, pred, j))
    rep["model_A_raw_pod"] = {"k": kA, "global_max": gA, "key_max": kA_}
    # 逐 x 自投影（定位 220%）
    selfproj = []
    for i in tr:
        pred = mu[:, 0] + BA @ (BA.conj().T @ (X[:, i] - mu[:, 0]))
        selfproj.append({"x_scale": float(xs[i]), "selfproj_rel": relmax(all_idx, pred, i)})
    selfproj.sort(key=lambda d: d["x_scale"])
    rep["model_A_selfproj_by_x"] = selfproj
    rep["model_A_selfproj_max"] = {"x_scale": max(selfproj, key=lambda d: d["selfproj_rel"])["x_scale"],
                                   "value": max(d["selfproj_rel"] for d in selfproj)}

    # ---------- 模型 B：振幅/形状分离 ----------
    nrm = np.linalg.norm(X, axis=0)
    shp = X / nrm[None, :]
    logn = np.log10(nrm)
    # 幅值：PCHIP over train x
    y_amp = logn[tr][order]
    amp_pred = {float(xs[j]): float(PchipInterpolator(xs_s, y_amp)(xs[j])) for j in ho}
    # 形状：POD（train）
    St = shp[:, tr]; mu_s = St.mean(axis=1, keepdims=True)
    Us, Ss, _ = np.linalg.svd(St - mu_s, full_matrices=False)
    kS = int(np.searchsorted(np.cumsum((Ss ** 2) / (Ss ** 2).sum()), 0.999) + 1)
    BS = Us[:, :kS]; CS = BS.conj().T @ (shp - mu_s)
    gB = kB = 0.0
    per = []
    for j in ho:
        s_pred = mu_s[:, 0] + BS @ pchip_predict(CS[:, tr], kS, xs[j])
        s_pred = s_pred / np.linalg.norm(s_pred)                 # 先归一化形状
        pred = (10 ** amp_pred[float(xs[j])]) * s_pred           # 再乘回预测幅值
        g_ = relmax(all_idx, pred, j); k_ = relmax(key_idx, pred, j)
        gB = max(gB, g_); kB = max(kB, k_)
        per.append({"x_scale": float(xs[j]), "global_rel_L2": g_, "key_rel_L2": k_,
                    "amp_true": float(nrm[j]), "amp_pred": float(10 ** amp_pred[float(xs[j])]),
                    "amp_rel_err": abs(10 ** amp_pred[float(xs[j])] - nrm[j]) / nrm[j]})
    rep["model_B_amp_shape"] = {"k_shape": kS, "global_max": gB, "key_max": kB, "per_holdout": per}

    # ---------- 更正 applicability（声明不得超出证据）----------
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    before = spec["applicability"]["param_bounds"].get("x_scale")
    ho_xs = sorted(float(xs[j]) for j in ho)
    spec["applicability"]["param_bounds"]["x_scale"] = [min(ho_xs), max(ho_xs)]
    spec["applicability"]["extrapolation"] = {
        "allowed_steps": 0,
        "policy": ("**声明范围 = 留出证据覆盖范围**（x∈[%.2f, %.2f]）；训练集更宽（x∈[0.20, 1.00]）"
                   "但两端**无留出证据**，其中小幅值端（x≈0.20）已知自投影失真（见 k_sweep 的 220%%），"
                   "故不纳入声明范围。" % (min(ho_xs), max(ho_xs)))}
    spec["note"] = (spec.get("note", "") + " | 2026-10-06 更正：applicability.x_scale 由 [0.20,1.00] "
                    "收窄为留出证据范围 [%.2f,%.2f]（原先声明超出证据）。" % (min(ho_xs), max(ho_xs)))
    SPEC.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8", newline="\n")
    rep["spec_correction"] = {"path": str(SPEC.relative_to(REPO)), "x_scale_before": before,
                              "x_scale_after": spec["applicability"]["param_bounds"]["x_scale"],
                              "evidence": "holdout x = %s" % ho_xs}
    rep["compare"] = {"A_global": gA, "A_key": kA_, "B_global": gB, "B_key": kB,
                      "global_improve_x": (gA / gB if gB else None),
                      "key_improve_x": (kA_ / kB if kB else None),
                      "B_global_pass_5pct": bool(gB <= 0.05), "B_key_pass_2pct": bool(kB <= 0.02)}
    rep["ok"] = True
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print("模型 A（原始场 POD, k=%d）：全域 max=%.4f ｜ 关键区 max=%.4f" % (kA, gA, kA_))
    print("模型 B（幅值/形状分离, k_shape=%d）：全域 max=%.4f ｜ 关键区 max=%.4f" % (kS, gB, kB))
    print("改善倍数：全域 ×%.2f ｜ 关键区 ×%.2f" % (gA / gB if gB else 0, kA_ / kB if kB else 0))
    print("自投影最大处：x=%g → %.4f（印证小幅值端失真）"
          % (rep["model_A_selfproj_max"]["x_scale"], rep["model_A_selfproj_max"]["value"]))
    print("B 逐留出：", ", ".join("x=%g→全%.3f/关%.3f" % (p["x_scale"], p["global_rel_L2"],
                                                      p["key_rel_L2"]) for p in per))
    print("B 幅值相对误差：", ", ".join("x=%g→%.3f" % (p["x_scale"], p["amp_rel_err"]) for p in per))
    print("spec 更正：x_scale %s → %s（声明 = 留出证据范围）"
          % (before, rep["spec_correction"]["x_scale_after"]))
    print("报告：", OUT.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
