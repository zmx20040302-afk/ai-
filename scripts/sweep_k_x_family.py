# -*- coding: utf-8 -*-
"""第 1 项：模数扫描——k 从 3 扫到 train 全秩，看 S1（全域 + 关键区）能否压过阈值。

背景：k(99.9%)=3 时 S1 全域 2.26%、**关键区 2.13%**（阈值 2%）⇒ 差 6% 相对量。
本脚本**只扫描 k**，其余全不变（同一缓存、同一 train/holdout、同一折内选模纪律、同一 PCHIP 系数映射），
这样"是模数不够还是方法不行"就被隔离出来了。

规则（写死）：
* POD 基**只用 train 76** 拟；k 是唯一的自变量；
* 关键区定义 = `R/R_max ≤ 1/3`（与 §88.4 一致，声学域为下半球，R_max≈99.8 µm）；
* **报 max**（全域与关键区各一个）；
* 同时报 train 侧自投影误差作参考（**它不是验证**，只用来判断"基能不能表示这些场"）。

用法：work\\.venv\\Scripts\\python.exe scripts\\sweep_k_x_family.py
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
OUT = D / "k_sweep_x_n1_4.json"
KS = (3, 5, 8, 12, 16, 24, 40, 76)      # 76 = train 全秩（n_train）
KEY_F = 1 / 3
THR_KEY, THR_GLOBAL = 0.02, 0.05


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
    Xt = X[:, tr]
    mu = Xt.mean(axis=1, keepdims=True)
    U, S, _ = np.linalg.svd(Xt - mu, full_matrices=False)
    energy = np.cumsum((S ** 2) / float((S ** 2).sum()))
    x_s = xs[tr]
    order = np.argsort(x_s)
    xs_sorted = x_s[order]

    rep: dict = {"kind": "k_sweep_x_family", "sha256_cache": hashlib.sha256(
        CACHE.read_bytes()).hexdigest(), "key_region_f": KEY_F,
        "n_key_points": int(key_idx.size), "thresholds": {"key": THR_KEY, "global": THR_GLOBAL},
        "n_train": int(tr.size), "n_holdout": int(ho.size),
        "note": "只扫 k，其余不变；train 侧数字是自投影，不是验证。", "rows": []}

    def rel(idx, pred_full, j):
        return float(np.linalg.norm(pred_full[idx] - X[:, j][idx])
                     / np.linalg.norm(X[:, j][idx]))

    for k in KS:
        B = U[:, :k]
        C = B.conj().T @ (X - mu)
        Ct = C[:, tr]
        gmax = kmax = tmax = 0.0
        for j in ho:
            cq = np.zeros(k, dtype=complex)
            for r_ in range(k):
                for part in ("re", "im"):
                    y = (Ct[r_, order].real if part == "re" else Ct[r_, order].imag)
                    cq[r_] += float(PchipInterpolator(xs_sorted, y)(xs[j])) * (
                        1 if part == "re" else 1j)
            pred = mu[:, 0] + B @ cq
            gmax = max(gmax, rel(all_idx, pred, j))
            kmax = max(kmax, rel(key_idx, pred, j))
        # train 侧自投影（参考）
        for i in tr:
            pred = mu[:, 0] + B @ (B.conj().T @ (X[:, i] - mu[:, 0]))
            tmax = max(tmax, rel(all_idx, pred, i))
        rep["rows"].append({"k": k, "energy_at_k": round(float(energy[k - 1]), 6),
                            "holdout_global_max": gmax, "holdout_key_max": kmax,
                            "train_selfproj_global_max": tmax,
                            "key_pass": bool(kmax <= THR_KEY),
                            "global_pass": bool(gmax <= THR_GLOBAL)})
    ok = [r for r in rep["rows"] if r["key_pass"] and r["global_pass"]]
    rep["first_k_passing_both"] = ok[0]["k"] if ok else None
    rep["best_key_max"] = min(r["holdout_key_max"] for r in rep["rows"])
    rep["best_global_max"] = min(r["holdout_global_max"] for r in rep["rows"])
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print("关键区 %d 点（R/R_max≤1/3）｜ 阈值：关键区 ≤%.2g、全域 ≤%.2g" % (key_idx.size, THR_KEY, THR_GLOBAL))
    print("%5s %10s %12s %11s %11s  %s" % ("k", "能量", "全域max", "关键区max", "train自投影", "两项都过?"))
    for r in rep["rows"]:
        print("%5d %10.4f %12.4f %11.4f %11.4f  %s"
              % (r["k"], r["energy_at_k"], r["holdout_global_max"], r["holdout_key_max"],
                 r["train_selfproj_global_max"], "是" if (r["key_pass"] and r["global_pass"]) else "否"))
    print("关键区最小值 = %.4f ｜ 全域最小值 = %.4f ｜ 首个两项都过的 k = %s"
          % (rep["best_key_max"], rep["best_global_max"], rep["first_k_passing_both"]))
    print("报告：", OUT.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
