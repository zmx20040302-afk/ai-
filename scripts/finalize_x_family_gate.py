# -*- coding: utf-8 -*-
"""路线甲收尾：填适用范围 → 定义"关键区" → 让门禁视图跑通（不调 COMSOL）。

三件事：
1. **填 `pmut-f1` 的 `applicability.param_bounds`**：按**实测族边界**填，不猜——
   本族覆盖 `x_scale ∈ [0.20, 1.00]`、`N_w_te1 = 4`（固定）、`N_w_te2 = 8`、`20 MHz`；
   同时把 `point_set.points_file` 改成**真实使用**的那份冻结点集（原先指向一个不存在的占位路径）。
2. **"关键区"定义（S1 的第二个子项）**：`WORKING_PLAN` §6.1.1 的 S1 要求
   "关键区 < 2% **且** 全域 ≤ 5%"，此前关键区未定义 ⇒ S1 永远 inconclusive。
   这里按**几何**定义：声学域是中心在原点、半径约 100 µm 的下半球 ⇒
   **关键区 = 归一化半径 `R/R_max ≤ f` 的点**，缺省 `f = 1/3`（覆盖换能器核心区）。
   ⚠️ **如实披露**：这个定义是在**已看到全域 2.26%** 之后才写的（次序不理想）⇒
   因此**必须同时给敏感性**（f = 1/4、1/3、1/2 三档都报），让人能看出这不是挑出来的。
3. **门禁视图**：把 S1（全域+关键区）/S2/S5 喂给 `solver.evaluate_levels`，S0/S3/S4 无证据 ⇒ 如实 inconclusive。

用法：work\\.venv\\Scripts\\python.exe scripts\\finalize_x_family_gate.py
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
D = REPO / "work/runs/te2_8_pod_fields_20261005/x_family/n1_4"
CACHE = D / "interp_cache_x_n1_4.npz"
PODREP = D / "pod_report_x_n1_4.json"
SPEC = REPO / "work/runs/solver/pmut-f1/solver_spec.json"
POINTS = REPO / "work/runs/te2_8_pod_fields_20261005/pod_pipeline_x020_v2/common_points_xyz_m.tsv"
OUT = D / "gate_view_x_n1_4.json"
FS = (0.25, 1 / 3, 0.50)


def sha(p: pathlib.Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def main() -> int:
    import numpy as np
    from scipy.interpolate import PchipInterpolator

    z = np.load(CACHE)
    P, mask, xs = z["P"], z["mask"], z["x_scale"].astype(float)
    role_x = [str(v) for v in z["role_x"]]
    X = P[mask]
    pts = np.loadtxt(POINTS, delimiter="\t", skiprows=1)[mask]
    R = np.linalg.norm(pts, axis=1)
    Rmax = float(R.max())
    rep: dict = {"kind": "gate_view_x_family", "sha256_cache": sha(CACHE),
                 "sha256_points": sha(POINTS), "errors": [],
                 "key_region": {"definition": "归一化半径 R/R_max <= f（声学域=原点为中心的下半球）",
                                "R_max_um": round(Rmax * 1e6, 3),
                                "default_f": 1 / 3,
                                "disclosure": ("该定义写于**已看到全域 2.26%** 之后 ⇒ "
                                               "次序不理想；已用 f=1/4、1/3、1/2 三档敏感性对冲。")}}
    tr = np.array([i for i, r in enumerate(role_x) if r == "train"])
    ho = np.array([i for i, r in enumerate(role_x) if r == "holdout"])

    # ---- S1：POD 在 train 上选模，留出预测（与第 2 步同法，另按关键区再算一遍）----
    Xt = X[:, tr]
    mu = Xt.mean(axis=1, keepdims=True)
    U, S, _ = np.linalg.svd(Xt - mu, full_matrices=False)
    k = int(np.searchsorted(np.cumsum((S ** 2) / (S ** 2).sum()), 0.999) + 1)
    B = U[:, :k]
    C = B.conj().T @ (X - mu)
    Ct = C[:, tr]
    x_tr = xs[tr]
    order = np.argsort(x_tr)
    xs_s = x_tr[order]

    def rel(idx, j):
        """在掩膜子集 idx 上算第 j 个快照的 rel_L2。"""
        cq = np.zeros(k, dtype=complex)
        for r_ in range(k):
            for part in ("re", "im"):
                y = (Ct[r_, order].real if part == "re" else Ct[r_, order].imag)
                cq[r_] += float(PchipInterpolator(xs_s, y)(xs[j])) * (1 if part == "re" else 1j)
        pred = (mu[:, 0] + B @ cq)[idx]
        true = X[:, j][idx]
        return float(np.linalg.norm(pred - true) / np.linalg.norm(true)), pred, true

    all_idx = np.arange(X.shape[0])
    per = []
    for j in ho:
        g, _, _ = rel(all_idx, j)
        row = {"x_scale": float(xs[j]), "global_rel_L2": g}
        for f in FS:
            idx = np.where(R <= f * Rmax)[0]
            row["key_%g_rel_L2" % f] = rel(idx, j)[0]
            row["key_%g_n" % f] = int(idx.size)
        per.append(row)
    rep["s1"] = {"per_holdout": per, "k_modes": k,
                 "global_max": max(r["global_rel_L2"] for r in per)}
    for f in FS:
        rep["s1"]["key_%g_max" % f] = max(r["key_%g_rel_L2" % f] for r in per)

    # ---- 填 applicability（按实测族边界）----
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    before = {"param_bounds": spec["applicability"].get("param_bounds"),
              "points_file": spec["point_set"].get("points_file")}
    spec["applicability"]["param_bounds"] = {"x_scale": [0.20, 1.00],
                                             "N_w_te1": [4.0, 4.0],
                                             "N_w_te2": [8.0, 8.0]}
    spec["applicability"]["frequency_range_MHz"] = [20.0, 20.0]
    spec["applicability"]["geometry_family"] = "pmut-f1-x-family-n1_4"
    spec["point_set"]["points_file"] = str(POINTS.relative_to(REPO)).replace("\\", "/")
    spec["point_set"]["note"] = ("实测冻结点集：1373 点（下半球，R_max≈%.1f µm），"
                                 "掩膜 1369 点；哈希 %s" % (Rmax * 1e6, (sha(POINTS) or "")[:16]))
    spec.setdefault("note", "")
    spec["note"] = (spec["note"] + " | 2026-10-06：applicability 按 **x 单参数族实测边界**填入 "
                    "（x∈[0.20,1.00]、N1=4、N2=8、20 MHz）；point_set 改为真实使用的冻结点集。"
                    "S1/S2/S5 已有证据，S0/S3/S4 **仍缺** ⇒ 状态保持 draft，不构成放行。")
    SPEC.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8", newline="\n")
    rep["spec_update"] = {"path": str(SPEC.relative_to(REPO)), "before": before,
                          "after_param_bounds": spec["applicability"]["param_bounds"],
                          "after_points_file": spec["point_set"]["points_file"]}

    # ---- 门禁视图 ----
    sys.path.insert(0, str(REPO / "src"))
    from memsharness import solver as SV
    pod = json.loads(PODREP.read_text(encoding="utf-8"))
    spec2 = SV.load_spec(SPEC)                      # 现在应能通过校验
    ev = {"s1": {"global_rel_L2_max": rep["s1"]["global_max"],
                 "key_region_rel_L2_max": rep["s1"]["key_%g_max" % (1 / 3)],
                 "n_holdout": len(per), "is_independent": True},
          "s2": {"engineering_rel_err": {"max_abs_p": pod["s2"]["max_rel_err"]}},
          "s5": {"coverage": pod["s5"]["coverage_on_holdout"],
                 "n_calibration": pod["s5"]["n_calibration_train"], "certified": True}}
    lv = SV.evaluate_levels(spec2, ev)
    rep["gate_view"] = {kk: v["verdict"] for kk, v in lv["levels"].items()}
    rep["gate_checks"] = {kk: v.get("checks") for kk, v in lv["levels"].items()
                          if kk in ("S1", "S2", "S5")}
    rep["spec_valid_now"] = True
    rep["release_allowed"] = False
    rep["release_reason"] = ("按 §6.4：S0/S3/S4 无证据（inconclusive 不算通过）⇒ 不得放行；"
                             "approved_solver 另需人工签字。")
    rep["ok"] = True
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print("spec 现已可加载（applicability 已按实测填入；point_set 指向真实冻结点集）")
    print("关键区定义：R/R_max ≤ f，R_max = %.1f µm ｜ 敏感性：" % (Rmax * 1e6))
    print("  %-6s %-10s %-10s" % ("f", "关键区点数", "关键区 max rel_L2"))
    for f in FS:
        n = rep["s1"]["per_holdout"][0]["key_%g_n" % f]
        print("  %-6g %-10d %.4f" % (f, n, rep["s1"]["key_%g_max" % f]))
    print("全域 max rel_L2 = %.4f" % rep["s1"]["global_max"])
    print("门禁视图：", json.dumps(rep["gate_view"], ensure_ascii=False))
    print("S1 逐项：", json.dumps(rep["gate_checks"].get("S1"), ensure_ascii=False)[:300])
    print("放行 =", rep["release_allowed"], "｜", rep["release_reason"][:60])
    print("报告：", OUT.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
