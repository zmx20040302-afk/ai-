# -*- coding: utf-8 -*-
"""按用户给定阈值（场级 rel_L2 = 2%）落定门禁裁定。

阈值来源：**用户 2026-10-06 明确指示「先用 2%」**（与 `WORKING_PLAN.md` §6.1.1 的
"关键区 < 2%" 同源）。本脚本**不改任何数据、不重算模型**，只把现有报告里的逐折 `rel_L2`
与这条阈值对撞，得出可复现的裁定。

判据（写死，避免事后挪动）：
* 单位 = 场级 `rel_L2`（复场、公共掩膜、逐折留一）；
* **放行条件** = 每一折都 ≤ 阈值（"全部折 max ≤ 2%"），并**同时报出**内插折与端点折各自的最坏值；
* 只要有一折超阈 ⇒ 不得放行、不得扩到 405、只能声称"趋势"。

用法：work\\.venv\\Scripts\\python.exe scripts\\apply_field_threshold.py --threshold 0.02
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
V2 = REPO / "work/runs/te2_8_pod_fields_20261005/pod_pipeline_x020_v2"
GPT = V2 / "coeff_models_v2/coeff_models_x020_normalized_report.json"
OUT = V2 / "gate_verdict_field_rel_L2.json"
N1S = [1, 2, 3, 4, 5, 6, 7]
ENDPOINTS = (1, 7)          # 外推折（N1 的两端）


def sha(p: pathlib.Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.02)
    ap.add_argument("--report", default=str(GPT))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)

    rep: dict = {"kind": "field_rel_L2_gate_verdict",
                 "threshold": a.threshold,
                 "threshold_source": "用户 2026-10-06 指示「先用 2%」；与 WORKING_PLAN §6.1.1 关键区 <2% 同源",
                 "input_report": pathlib.Path(a.report).name,
                 "sha256_input_report": sha(pathlib.Path(a.report)),
                 "rule": "每一折 rel_L2 ≤ 阈值才算放行（全折 max 判据）；同时单列内插/端点最坏值",
                 "data_scope": {"x_scale": [0.20], "N1": N1S, "N2": [8], "freq_Hz": [20000000],
                                "n_snapshots": 7},
                 "errors": []}
    p = pathlib.Path(a.report)
    if not p.is_file():
        print("[FAIL] 找不到输入报告：%s" % p); return 2
    d = json.loads(p.read_text(encoding="utf-8"))
    models = d.get("models") or {}
    raw_p = d.get("raw_persistence") or {}

    def folds_of(v):
        return {f["held_out_n1"]: f["rel_L2"] for f in (v.get("per_fold") or [])}

    thr = a.threshold
    rows = []
    for name, v in sorted(models.items()):
        fl = folds_of(v)
        if not fl:
            continue
        worst_n1 = max(fl, key=lambda k: fl[k])
        inter = [fl[n] for n in fl if n not in ENDPOINTS]
        endp = [fl[n] for n in fl if n in ENDPOINTS]
        rows.append({
            "model": name, "per_fold": fl,
            "max": max(fl.values()), "median": sorted(fl.values())[len(fl) // 2],
            "n_folds_pass": sum(1 for x in fl.values() if x <= thr),
            "best_fold": min(fl.values()), "worst_fold_n1": worst_n1,
            "worst_fold_value": fl[worst_n1],
            "max_interior": max(inter) if inter else None,
            "max_endpoint": max(endp) if endp else None,
        })
    base = folds_of(raw_p)
    rep["raw_persistence_baseline"] = {
        "per_fold": base, "max": max(base.values()) if base else None,
        "n_folds_pass": sum(1 for x in base.values() if x <= thr) if base else None}

    rows.sort(key=lambda r: r["max"])
    rep["models"] = rows
    best = rows[0] if rows else None
    rep["best_model_by_max"] = best["model"] if best else None
    if best:
        rep["verdict"] = {
            "release_allowed": bool(best["n_folds_pass"] == len(N1S)),
            "n_folds_pass_best_model": best["n_folds_pass"],
            "n_folds": len(N1S),
            "best_fold_value": best["best_fold"],
            "worst_fold_value": best["worst_fold_value"],
            "required_improvement_factor": float(best["worst_fold_value"] / thr),
            "best_suboptimal_fold_ratio_vs_threshold": float(best["best_fold"] / thr),
            "beat_baseline_on_max": bool(best["max"] < rep["raw_persistence_baseline"]["max"]),
            "expansion_to_405_allowed": False,
            "allowed_claims": ["趋势（同一 x_scale 层内、N1 内插的相对变化）"],
            "forbidden_claims": ["工程绝对值", "已验证等价于 COMSOL", "把该代理用于设计放行"],
        }
    rep["ok"] = True
    pathlib.Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print("阈值 = %.4g（场级 rel_L2，逐折判据）" % thr)
    print("%-24s %8s %8s %7s  逐折（N1=1..7）" % ("模型", "max", "median", "过折数"))
    for r in rows:
        print("%-24s %8.4f %8.4f %5d/%d  %s" % (
            r["model"], r["max"], r["median"], r["n_folds_pass"], len(N1S),
            " ".join("%.4f%s" % (r["per_fold"].get(n, float("nan")),
                                 "*" if n in ENDPOINTS else "") for n in N1S)))
    print("%-24s %8.4f %8s %5d/%d" % ("raw_persistence(基线)",
          rep["raw_persistence_baseline"]["max"], "-",
          rep["raw_persistence_baseline"]["n_folds_pass"] or 0, len(N1S)))
    if best:
        print()
        print("最佳模型 %s：过折 %d/%d ｜ 最好折 %.4f（阈值的 %.1f 倍）｜ 最坏折 N1=%d = %.4f（阈值的 %.1f 倍）"
              % (best["model"], best["n_folds_pass"], len(N1S), best["best_fold"],
                 best["best_fold"] / thr, best["worst_fold_n1"], best["worst_fold_value"],
                 best["worst_fold_value"] / thr))
        print("放行 =", rep["verdict"]["release_allowed"],
              "｜ 扩到 405 =", rep["verdict"]["expansion_to_405_allowed"])
    print("报告：", pathlib.Path(a.out).relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
