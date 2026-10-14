# -*- coding: utf-8 -*-
"""S5 覆盖率的**补充评估协议（预注册）**：n1_4 族的 8 折交叉覆盖。

## 为什么需要补充评估
已冻结的 5 点留出协议下，覆盖率只能取 {0,0.2,…,1.0}，目标区间 [0.85,0.95]
在该网格上**不可达** ⇒ S5 判据永远 inconclusive。这是**评估规模**问题，不是模型问题。
本脚本**不修改、不取代**已冻结协议：`route_a_gate_n1_4.json` 里的 5 点结论保持原样，
本脚本的结论一律标注 `supplemental: true`。

## 预注册协议（写在此处 = 写在看到任何覆盖数字**之前**）
1. 折划分：81 个 x 点按 **x 升序**，`fold = i % 8` ⇒ 每折 10–11 点，且**按 x 分层**
   （避免出现"某一折全在小 x 端"的分布偏移）。确定性、无随机种子。
2. 对每一折 F：用其余 81−|F| 点拟合模型 B（幅值 log10‖X‖ PCHIP + 单位范数形状 POD + 系数 PCHIP）。
3. 该折的保形半宽：在**训练折内部**再做 LOO（每次留出一个训练点、只用其余训练点拟合），
   得到 n_tr 个"逐快照相对 L2"得分；取第 `⌈(n_tr+1)(1−α)⌉` 小的得分作为半宽。
   —— 校准与测试**严格不相交**。
4. 判据：逐点看 rel_L2 ≤ 本折半宽，覆盖率 = 命中点数 / 81。
   阈值**沿用冻结值** `[S5_coverage_min, S5_coverage_max] = [0.85, 0.95]`，**不放宽**。
5. 同时报 α = 0.10 / 0.05 / 0.01 三档，以及逐折覆盖率（不只看总平均）。
6. 若总覆盖率落在区间内 ⇒ `s5_8fold_verdict = passed`，否则按同一阈值记 failed；
   任一折半宽为 inf（校准点不足）⇒ 记 inconclusive。

用法：python scripts\\s5_8fold_coverage_n1_4.py [--tag n1_4] [--folds 8]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
XF = REPO / "work/runs/te2_8_pod_fields_20261005/x_family"
SPEC = REPO / "work/runs/solver/pmut-f1/solver_spec.json"
ALPHAS = (0.10, 0.05, 0.01)


def main() -> int:
    import numpy as np
    from scipy.interpolate import PchipInterpolator

    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="n1_4")
    ap.add_argument("--folds", type=int, default=8)
    a = ap.parse_args()
    cache = XF / a.tag / ("interp_cache_x_%s.npz" % a.tag)
    z = np.load(cache)
    P, mask, xs = z["P"], z["mask"], z["x_scale"].astype(float)
    X = P[mask]
    n_snap = X.shape[1]

    def fit_b(train_idx, q_x):
        trn = np.asarray(train_idx)
        nrm = np.linalg.norm(X[:, trn], axis=0)
        shp = X[:, trn] / nrm[None, :]
        mu = shp.mean(axis=1, keepdims=True)
        U, s, _v = np.linalg.svd(shp - mu, full_matrices=False)
        k = max(1, int(np.searchsorted(np.cumsum(s ** 2) / (s ** 2).sum(), 0.999) + 1))
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
        sh = mu[:, 0] + B @ cq
        return (10 ** la) * (sh / np.linalg.norm(sh))

    def rel2(pred, j):
        return float(np.linalg.norm(pred - X[:, j]) / np.linalg.norm(X[:, j]))

    order_all = np.argsort(xs)                     # 按 x 升序
    fold_of = {int(idx): (i % a.folds) for i, idx in enumerate(order_all)}
    rep: dict = {
        "kind": "s5_supplemental_8fold_coverage", "supplemental": True,
        "supersedes": None,
        "frozen_protocol_verdict_note": "本结论**不取代** 5 点留出协议；后者见 route_a_gate 报告",
        "computed_at_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256_cache": hashlib.sha256(cache.read_bytes()).hexdigest(),
        "tag": a.tag, "n_folds": a.folds, "n_snapshots": int(n_snap),
        "fold_sizes": {}, "fold_coverage": {}, "bands": {}, "verdict": {}, "errors": []}

    for f in range(a.folds):
        rep["fold_sizes"][str(f)] = int(sum(1 for v in fold_of.values() if v == f))

    hits: dict[str, dict[int, list[float]]] = {str(al): {} for al in ALPHAS}
    for f in range(a.folds):
        test = np.array(sorted([i for i, v in fold_of.items() if v == f]))
        train = np.array(sorted([i for i, v in fold_of.items() if v != f]))
        # 校准：训练折内部 LOO
        cal = np.array(sorted(rel2(fit_b([t for t in train if t != i], xs[i]), i) for i in train))
        n_tr = int(cal.size)
        for al in ALPHAS:
            idx = min(n_tr - 1, int(np.ceil((n_tr + 1) * (1 - al))) - 1)
            band = float(cal[idx])
            if n_tr < 9:                                  # SOP §4：<9 个校准点不认证
                band = float("inf")
            rep["bands"].setdefault(str(al), {})[str(f)] = {
                "band_rel_L2": band, "n_calibration": n_tr}
            hits[str(al)][f] = [1.0 if rel2(fit_b(train, xs[j]), j) <= band else 0.0
                                for j in test]
        print("  折 %d/%d：test %d 点 ｜ train %d 点 ｜ 校准分位 p90=%.4f"
              % (f + 1, a.folds, test.size, train.size, float(cal[int(0.9 * n_tr) - 1])))
        sys.stdout.flush()

    sys.path.insert(0, str(REPO / "src"))
    from memsharness import solver as SV
    spec = SV.load_spec(SPEC)
    lo, hi = spec["thresholds"]["S5_coverage_min"], spec["thresholds"]["S5_coverage_max"]
    for al in ALPHAS:
        per_fold = [float(np.mean(hits[str(al)][f])) for f in range(a.folds)]
        h = np.concatenate([np.array(hits[str(al)][f]) for f in range(a.folds)])
        cov = float(h.mean())
        finite = all(rep["bands"][str(al)][str(f)]["band_rel_L2"] < float("inf")
                     for f in range(a.folds))
        v = "inconclusive" if not finite else ("passed" if lo <= cov <= hi else "failed")
        rep["fold_coverage"][str(al)] = per_fold
        rep["verdict"][str(al)] = {"coverage": cov, "n_points": int(h.size),
                                   "threshold": [lo, hi], "verdict": v,
                                   "min_fold_coverage": min(per_fold),
                                   "max_fold_coverage": max(per_fold)}
    rep["ok"] = True
    out = XF / a.tag / ("s5_8fold_%s.json" % a.tag)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    for al in ALPHAS:
        v = rep["verdict"][str(al)]
        print("α=%.2f 覆盖率 %.4f（%d 点，阈值 [%.2f,%.2f]）⇒ %s ｜ 逐折 min %.3f / max %.3f"
              % (al, v["coverage"], v["n_points"], lo, hi, v["verdict"],
                 v["min_fold_coverage"], v["max_fold_coverage"]))
    print("报告：", out.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
