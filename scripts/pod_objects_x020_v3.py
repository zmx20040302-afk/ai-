# -*- coding: utf-8 -*-
"""x=0.20 七快照管线：补齐**两个此前缺失的对象**（关键区相对 L2 与 S2 工程量误差）。

## 为什么必须补（口径，而非精度）

2026-10-06 生成的两个门禁文件 `gate_verdict_field_rel_L2.json`（阈值 0.02）与
`gate_verdict_field_rel_L2_thr5pct.json`（阈值 0.05）**逐折数值完全相同**，只换了阈值；
其中 0.02 那一份的 `threshold_source` 原文写着「与 WORKING_PLAN §6.1.1 **关键区** <2% 同源」，
却把该阈值判在**全域**对象上。同一批预测因此被两个不同对象的口径各读了一遍：

    * 关键区域（R/R_max ≤ 1/3）——规范阈值 2%
    * 全域（全部公共点）    ——规范阈值 5%

而这条管线**只算过全域**。所以「2% ⇒ 0/7 折通过」是**对象错配**下的读数，
不是关键区读数，也不代表关键区不达标。

## 本脚本做什么（本地计算，不调 COMSOL、不联网）

1. **回归**：逐位复算冻结 v2 脚本（`scripts/pod_coeff_models_x020_v2.py`）的全域 per-fold
   rel_L2，与冻结报告比对；任何偏差超容差即**报错退出**（不产出任何数字）；
2. **补对象 A**：关键区相对 L2 —— R = ‖(x,y,z)‖（原点距离），`R ≤ (1/3)·R_max`，
   与 x 族（`amp_shape_x_family.py` / `s2s5_modelB_x_family.py`）及 S4 同机脚本（`s4_same_machine.py`）
   **同一个 R 定义**（该定义在 `finalize_x_family_gate.py` 有留档：声学域=原点为中心的下半球）；
3. **补对象 B**：S2 工程量候选「域内 max|p|」相对误差 —— 与 x 族同定义
   （`np.max(np.abs(...))` 在同一掩膜点集上取，取绝对值最大点）；
4. 三个对象并列出门禁视图，阈值**从 `solver_spec.json` 读**（不硬编码）；
5. 同时**计算适用范围命中判定**：把 x_scale 与 N_w_te1 代入 spec 的 `applicability.param_bounds`，
   如实记录该管线是否落在声明范围内。

## 本脚本不做什么

* 不修改任何冻结产物（冻结报告、门禁文件、点集、插值缓存一律只读，仅记哈希）；
* 不升级任何模型状态：门禁视图只作「**按对象的读数**」，且该管线参数落在声明范围之外
  ⇒ 依红线 7 不得用于出解，结论只能是"回退 COMSOL"；
* 不把 S2 当成已裁定的工程量清单：本次只算清单中的候选之一。

用法：work\\.venv\\Scripts\\python.exe scripts\\pod_objects_x020_v3.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Any

import numpy as np


REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
#: 冻结的 x=0.20 七快照管线产物（**只读**）
PRUN = REPO / "work/runs/te2_8_pod_fields_20261005/pod_pipeline_x020_v2"
FROZEN_REPORT = PRUN / "coeff_models_v2/coeff_models_x020_normalized_report.json"
GATE_FILES = (
    PRUN / "gate_verdict_field_rel_L2.json",
    PRUN / "gate_verdict_field_rel_L2_thr5pct.json",
)
V2_SCRIPT = SCRIPTS / "pod_coeff_models_x020_v2.py"
SPEC = REPO / "work/runs/solver/pmut-f1/solver_spec.json"
OUT_DIR = REPO / "work/runs/pod-objects-x020-20261008"
OUT_JSON = OUT_DIR / "pod_objects_x020_three_objects.json"
OUT_MD = OUT_DIR / "pod_objects_x020_three_objects.md"
OUT_KEY = OUT_DIR / "key_region_index.json"
OUT_TSV = OUT_DIR / "three_objects_per_fold.tsv"

#: 冻结报告的哈希（取自门禁文件自述的 `sha256_input_report`，两边必须互证）
EXPECTED_REPORT_SHA256 = "56fba97bb95c1bfa6ad1d9e88736c683e1aa3d2e3d6a647b3e6a4ed263c5e956"
#: 关键区归一化半径因子（与 x 族 / S4 同一取值）
KEY_F = 1.0 / 3.0
#: 全域 per-fold rel_L2 的回归容差（相对）；超限即退出
REG_TOL = 1e-9
#: 该管线实际扫过的参数（来自冻结报告的 inputs / data_scope，非本脚本假设）
X_SCALE = 0.20
N1 = (1, 2, 3, 4, 5, 6, 7)
N2 = 8
FREQ_HZ = 20_000_000


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_frozen_v2() -> tuple[Any, str]:
    """按文件路径 import 冻结的 v2 脚本（**不复制其代码**，保证口径逐位同源）。"""
    spec = importlib.util.spec_from_file_location("pod_coeff_models_x020_v2", V2_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法 import 冻结脚本：{V2_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, sha256_file(V2_SCRIPT)


def rel_l2(pred: np.ndarray, truth: np.ndarray, idx: np.ndarray) -> float:
    return float(np.linalg.norm(pred[idx] - truth[idx]) / np.linalg.norm(truth[idx]))


def eng_object(pred: np.ndarray, truth: np.ndarray, key: np.ndarray) -> dict[str, Any]:
    """S2 候选工程量：域内 max|p| 的相对误差（在同一公共点集上取 max）。

    `argmax_in_key` 记录该工程量**落在哪个区域**：若落点固定在关键区内，
    则 S2 与关键区对象虽相关但不是同一个对象（一个是标量极值，一个是整场向量误差）。
    """
    abs_truth = np.abs(truth)
    abs_pred = np.abs(pred)
    idx_t = int(np.argmax(abs_truth))
    idx_p = int(np.argmax(abs_pred))
    t = float(abs_truth[idx_t])
    p = float(abs_pred[idx_p])
    if t <= 0:
        raise ValueError("真值 max|p| 为零，无法定义相对误差")
    return {
        "max_abs_p_true_Pa": t,
        "max_abs_p_pred_Pa": p,
        "rel_err": abs(p - t) / t,
        "argmax_true_in_key": bool(key[idx_t]),
        "argmax_pred_in_key": bool(key[idx_p]),
    }


def summarize(values: list[float], threshold: float, folds: list[int],
              fold_types: list[str]) -> dict[str, Any]:
    arr = np.asarray(values, dtype=float)
    worst = int(np.argmax(arr))
    endpoint = [v for v, t in zip(values, fold_types) if t == "endpoint_extrapolation"]
    interior = [v for v, t in zip(values, fold_types) if t == "interior"]
    return {
        "threshold": threshold,
        "per_fold": {str(f): float(v) for f, v in zip(folds, values)},
        "max": float(arr.max()),
        "median": float(np.median(arr)),
        "worst_fold_n1": folds[worst],
        "n_folds_pass": int(np.sum(arr <= threshold)),
        "n_folds": int(arr.size),
        "max_interior": max(interior) if interior else None,
        "max_endpoint": max(endpoint) if endpoint else None,
    }


def main() -> int:
    v2, v2_sha = load_frozen_v2()

    # ---- 输入校验：三个冻结输入都必须与冻结报告自述的哈希一致 ----
    report_sha = sha256_file(FROZEN_REPORT)
    if report_sha != EXPECTED_REPORT_SHA256:
        raise RuntimeError(f"冻结报告哈希不符：{report_sha}（期望 {EXPECTED_REPORT_SHA256}）")
    frozen = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))

    points_sha = v2.sha256_file(v2.POINTS)
    if points_sha != v2.EXPECTED_POINTS_SHA256 or points_sha != frozen["inputs"]["sha256_points_file"]:
        raise RuntimeError(f"冻结点集哈希不符：{points_sha}")
    cache_sha = v2.sha256_file(v2.CACHE)
    if cache_sha != frozen["inputs"]["sha256_interp_cache"]:
        raise RuntimeError(f"插值缓存哈希不符：{cache_sha}")

    spec_module = _load_solver_module()
    spec = spec_module.load_spec(SPEC)
    thr = spec["thresholds"]
    thr_key = float(thr["S1_key_region_rel_L2_max"])
    thr_global = float(thr["S1_global_rel_L2_max"])
    thr_eng = float(thr["S2_engineering_rel_err_max"])

    # ---- 数据与三个对象的作用域 ----
    loaded = np.load(v2.CACHE)
    pressure = np.asarray(loaded["P"], dtype=np.complex128)
    mask = np.asarray(loaded["mask"], dtype=bool)
    fields = pressure[mask]
    points = np.loadtxt(v2.POINTS, delimiter="\t", skiprows=1)[mask]
    radius = np.linalg.norm(points, axis=1)
    key = radius <= KEY_F * float(radius.max())
    all_idx = np.arange(fields.shape[0])

    # ---- 适用范围命中判定（红线 7：超出声明范围只能拒答并回退 COMSOL）----
    bounds = spec["applicability"]["param_bounds"]
    x_lo, x_hi = (float(v) for v in bounds["x_scale"])
    n1_lo, n1_hi = (float(v) for v in bounds.get("N_w_te1", [float("nan")] * 2))
    n2_lo, n2_hi = (float(v) for v in bounds.get("N_w_te2", [float("nan")] * 2))
    scope = {
        "declared_x_scale": [x_lo, x_hi],
        "declared_N_w_te1": [n1_lo, n1_hi],
        "declared_N_w_te2": [n2_lo, n2_hi],
        "this_pipeline": {"x_scale": X_SCALE, "N_w_te1": list(N1), "N_w_te2": N2,
                          "freq_Hz": FREQ_HZ},
        "x_scale_in_range": bool(x_lo <= X_SCALE <= x_hi),
        "N_w_te1_in_range": bool(n1_lo <= min(N1) and max(N1) <= n1_hi),
        "N_w_te2_in_range": bool(n2_lo <= N2 <= n2_hi),
        "extrapolation_policy": spec["applicability"].get("extrapolation", {}).get("policy"),
    }
    scope["in_declared_scope"] = bool(
        scope["x_scale_in_range"] and scope["N_w_te1_in_range"] and scope["N_w_te2_in_range"]
    )

    report: dict[str, Any] = {
        "kind": "pod_objects_x020_three_objects",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "补齐 x=0.20 七快照管线缺失的两个对象（关键区相对 L2、S2 候选工程量），"
            "以便同一批预测按正确对象被判读；**不是**放行该管线"
        ),
        "inputs": {
            "v2_script": str(V2_SCRIPT.relative_to(REPO)),
            "sha256_v2_script": v2_sha,
            "frozen_report": str(FROZEN_REPORT.relative_to(REPO)),
            "sha256_frozen_report": report_sha,
            "points_file": str(v2.POINTS.relative_to(REPO)),
            "sha256_points_file": points_sha,
            "interp_cache": str(v2.CACHE.relative_to(REPO)),
            "sha256_interp_cache": cache_sha,
            "solver_spec": str(SPEC.relative_to(REPO)),
            "sha256_solver_spec": sha256_file(SPEC),
            "n1": list(N1),
        },
        "objects": {
            "global_rel_L2": {
                "definition": "‖pred−truth‖₂/‖truth‖₂ 在**全部公共掩膜点**上",
                "threshold": thr_global,
                "threshold_key": "S1_global_rel_L2_max",
                "n_points": int(all_idx.size),
                "already_computed_by_v2": True,
            },
            "key_region_rel_L2": {
                "definition": "同一 rel_L2，仅取 R=‖(x,y,z)‖ ≤ (1/3)·R_max 的点",
                "threshold": thr_key,
                "threshold_key": "S1_key_region_rel_L2_max",
                "n_points": int(key.sum()),
                "n_points_total": int(all_idx.size),
                "R_max_m": float(radius.max()),
                "R_cut_m": float(KEY_F * radius.max()),
                "same_R_definition_as": [
                    "scripts/amp_shape_x_family.py",
                    "scripts/s2s5_modelB_x_family.py",
                    "work/runs/s34-ladder-server-20261008/s4_same_machine.py",
                ],
                "already_computed_by_v2": False,
            },
            "S2_max_abs_p_rel_err": {
                "definition": "|max|pred| − max|truth|| / max|truth|（同一公共点集内的 max|p|）",
                "threshold": thr_eng,
                "threshold_key": "S2_engineering_rel_err_max",
                "already_computed_by_v2": False,
                "list_status": "**候选清单中的一项**；S2 工程量清单仍待用户裁定",
            },
        },
        "object_mismatch_evidence": _gate_evidence(),
        "scope_check": scope,
        "geometry_of_key_region": {},
        "raw_persistence": {},
        "models": {},
        "per_object_ranking": {},
        "gate_view_per_object_reading_not_a_release": {},
        "regression_vs_frozen_report": {},
        "caveats": [],
        "errors": [],
    }

    report["geometry_of_key_region"] = {
        "radius_min_m": float(radius.min()),
        "radius_max_m": float(radius.max()),
        "coord_range_m": {
            "x": [float(points[:, 0].min()), float(points[:, 0].max())],
            "y": [float(points[:, 1].min()), float(points[:, 1].max())],
            "z": [float(points[:, 2].min()), float(points[:, 2].max())],
        },
        "note": (
            "R 起算点是**坐标系原点**（声学域为原点为中心的下半球，z<0），"
            "不是声轴距离；该口径与 x 族/S4 一致，换口径会让关键区点集改变，"
            "故不得在此处换定义。"
        ),
        "max_abs_p_argmax_in_key_by_snapshot": {},
    }

    # ---- 七折：真值、基线、10 个模型，三个对象一并算 ----
    folds = [{"held_out_n1": int(N1[i]), "key_points": int(key.sum())} for i in range(len(N1))]

    def fold_type_of(train_x: np.ndarray, held: int) -> str:
        return ("interior" if train_x.min() < N1[held] < train_x.max()
                else "endpoint_extrapolation")

    truth_max_abs = [float(np.max(np.abs(fields[:, i]))) for i in range(len(N1))]
    for i in range(len(N1)):
        report["geometry_of_key_region"]["max_abs_p_argmax_in_key_by_snapshot"][str(N1[i])] = bool(
            key[int(np.argmax(np.abs(fields[:, i])))]
        )

    baseline_rows: list[dict[str, Any]] = []
    for held_out in range(len(N1)):
        train = [i for i in range(len(N1)) if i != held_out]
        train_x = np.asarray([N1[i] for i in train], dtype=float)
        nearest = int(np.argmin(np.abs(train_x - N1[held_out])))
        predicted = fields[:, train[nearest]]
        truth = fields[:, held_out]
        eng = eng_object(predicted, truth, key)
        baseline_rows.append({
            "held_out_n1": int(N1[held_out]),
            "nearest_training_n1": int(train_x[nearest]),
            "fold_type": fold_type_of(train_x, held_out),
            "global_rel_L2": rel_l2(predicted, truth, all_idx),
            "key_region_rel_L2": rel_l2(predicted, truth, key),
            "S2_max_abs_p_rel_err": eng["rel_err"],
            "eng_detail": eng,
        })

    def object_summaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
        f = [int(r["held_out_n1"]) for r in rows]
        t = [str(r["fold_type"]) for r in rows]
        return {
            "global_rel_L2": summarize([r["global_rel_L2"] for r in rows], thr_global, f, t),
            "key_region_rel_L2": summarize([r["key_region_rel_L2"] for r in rows], thr_key, f, t),
            "S2_max_abs_p_rel_err": summarize(
                [r["S2_max_abs_p_rel_err"] for r in rows], thr_eng, f, t),
        }

    report["raw_persistence"] = {
        "definition": "最近邻训练快照（不做 POD 截断）",
        "per_fold": _jsonable_folds(baseline_rows),
        "objects": object_summaries(baseline_rows),
    }

    for representation in ("raw", "norm_shape"):
        for method in v2.METHODS:
            name = f"{representation}_{method}"
            rows: list[dict[str, Any]] = []
            for held_out in range(len(N1)):
                train = [i for i in range(len(N1)) if i != held_out]
                train_x = np.asarray([N1[i] for i in train], dtype=float)
                train_fields = fields[:, train]
                if representation == "raw":
                    predicted, k = v2.raw_pod_prediction(
                        method, train_x, train_fields, float(N1[held_out]))
                    predicted_norm = float(np.linalg.norm(predicted))
                else:
                    predicted, k, predicted_norm = v2.norm_shape_prediction(
                        method, train_x, train_fields, float(N1[held_out]))
                truth = fields[:, held_out]
                truth_norm = float(np.linalg.norm(truth))
                eng = eng_object(predicted, truth, key)
                rows.append({
                    "held_out_n1": int(N1[held_out]),
                    "fold_type": fold_type_of(train_x, held_out),
                    "k_modes_selected_from_training_fold": int(k),
                    "global_rel_L2": rel_l2(predicted, truth, all_idx),
                    "key_region_rel_L2": rel_l2(predicted, truth, key),
                    "S2_max_abs_p_rel_err": eng["rel_err"],
                    "eng_detail": eng,
                    "true_field_norm": truth_norm,
                    "predicted_field_norm": predicted_norm,
                    "relative_norm_error": abs(predicted_norm - truth_norm) / truth_norm,
                })
            report["models"][name] = {
                "per_fold": _jsonable_folds(rows),
                "objects": object_summaries(rows),
            }

    # ---- 回归：全域 per-fold 必须与冻结报告一致 ----
    devs: list[float] = []
    for row, old in zip(baseline_rows, frozen["raw_persistence"]["per_fold"]):
        devs.append(abs(row["global_rel_L2"] - float(old["rel_L2"])))
    for name, res in report["models"].items():
        for row, old in zip(res["per_fold"], frozen["models"][name]["per_fold"]):
            devs.append(abs(row["global_rel_L2"] - float(old["rel_L2"])))
    max_dev = max(devs) if devs else 0.0
    report["regression_vs_frozen_report"] = {
        "n_values_compared": len(devs),
        "max_abs_deviation": float(max_dev),
        "tolerance": REG_TOL,
        "reproduced": bool(max_dev <= REG_TOL),
        "note": (
            "全域对象逐折复算与冻结报告一致 ⇒ 关键区/工程量两个新对象是在**同一批预测**上算出的，"
            "不是另一套模型或另一次重训"
        ),
    }
    if not report["regression_vs_frozen_report"]["reproduced"]:
        raise RuntimeError(
            f"全域对象未能复现冻结报告：max_abs_deviation={max_dev:g} > {REG_TOL:g}；"
            "拒绝产出新对象（否则两个新对象无法与冻结结论同源）"
        )

    # ---- 逐对象排名 + 门禁视图（按对象读，不作放行）----
    ranking: dict[str, Any] = {}
    for obj in ("global_rel_L2", "key_region_rel_L2", "S2_max_abs_p_rel_err"):
        ranked = sorted(
            ((name, res["objects"][obj]) for name, res in report["models"].items()),
            key=lambda kv: float(kv[1]["max"]),
        )
        ranking[obj] = {
            "ranking_by_max": [
                {"model": name, "max": float(o["max"]), "median": float(o["median"]),
                 "n_folds_pass": int(o["n_folds_pass"]), "threshold": float(o["threshold"]),
                 "worst_fold_n1": int(o["worst_fold_n1"])}
                for name, o in ranked
            ],
            "best_model": ranked[0][0],
            "best_max": float(ranked[0][1]["max"]),
            "best_n_folds_pass": int(ranked[0][1]["n_folds_pass"]),
            "n_models_passing_all_folds": int(sum(
                1 for _, o in ranked if int(o["n_folds_pass"]) == int(o["n_folds"]))),
            "baseline_max": float(report["raw_persistence"]["objects"][obj]["max"]),
            "baseline_n_folds_pass": int(
                report["raw_persistence"]["objects"][obj]["n_folds_pass"]),
        }
    ranking["_note"] = (
        "按对象分别排名：**不同对象的最优模型可能不同**（全域看重整体 L2，工程量只看极值点），"
        "故禁止用某个对象的最优模型去代表另一个对象"
    )
    report["per_object_ranking"] = ranking

    gate: dict[str, Any] = {}
    for name, res in report["models"].items():
        ev = {
            "s1": {
                "key_region_rel_L2_max": float(res["objects"]["key_region_rel_L2"]["max"]),
                "global_rel_L2_max": float(res["objects"]["global_rel_L2"]["max"]),
                "n_holdout": len(N1),
                "is_independent": True,
            },
            "s2": {"engineering_rel_err": {
                "max_abs_p": float(res["objects"]["S2_max_abs_p_rel_err"]["max"])}},
        }
        levels = spec_module.evaluate_levels(spec, ev)
        gate[name] = {
            "verdicts": {k: v["verdict"] for k, v in levels["levels"].items()},
            "S1_checks": levels["levels"]["S1"]["checks"],
            "S2_checks": levels["levels"]["S2"]["checks"],
        }
    report["gate_view_per_object_reading_not_a_release"] = {
        "warning": (
            "这是**按对象的读数**，不是放行结论：①该管线参数落在 spec 声明范围之外"
            "（见 scope_check）⇒ 依红线 7 只能拒答并回退 COMSOL；"
            "②S3/S4 本脚本未做、S5 未校准 ⇒ 如实 inconclusive，None 不得复述为通过"
        ),
        "per_model": gate,
        "s0_s3_s4_s5": "inconclusive（本脚本未提供对应证据）",
    }

    report["caveats"] = [
        "关键区只有 %d/%d 个点（R/R_max ≤ 1/3）：点数少 ⇒ 该对象的 rel_L2 对个别点敏感，"
        "与全域不可互相替代。" % (int(key.sum()), int(all_idx.size)),
        "七折是**同一 x_scale=0.20、同一频率**下的 N1 留一：留出快照确实不在训练折内，"
        "但七折共享同一几何与网格，属族内留一，不等价于独立数据集。",
        "N1=1 与 N1=7 是端点外推折（训练区间不含端点），必须与内插折分开报告。",
        "S2 的 max|p| 是在**冻结公共点集**上取的最大值，不是连续域上的真极值；"
        "x 族同此口径，故可横向比较，但不能当作绝对声压峰值。",
        "本脚本只读冻结产物；两个新对象是在与冻结报告**同一批预测**上算出的"
        "（回归已核）。",
        "§6.1.1 的 S1 要求「独立留出集」，本条管线的留出集是族内留一；"
        "S1 的这个前提是否满足需人工裁定。",
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8", newline="\n")
    OUT_MD.write_text(_markdown(report), encoding="utf-8", newline="\n")
    write_key_index(key, radius, points, points_sha)
    write_per_fold_tsv(report)

    check = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    for required in ("objects", "models", "per_object_ranking", "regression_vs_frozen_report",
                     "scope_check", "gate_view_per_object_reading_not_a_release"):
        if required not in check:
            raise RuntimeError(f"报告缺少字段：{required}")

    print(json.dumps({
        "report": str(OUT_JSON.relative_to(REPO)),
        "regression_max_abs_deviation": max_dev,
        "n_key_points": int(key.sum()),
        "in_declared_scope": scope["in_declared_scope"],
        "global": {"best": ranking["global_rel_L2"]["best_model"],
                   "max": ranking["global_rel_L2"]["best_max"],
                   "folds_pass": ranking["global_rel_L2"]["best_n_folds_pass"]},
        "key_region": {"best": ranking["key_region_rel_L2"]["best_model"],
                       "max": ranking["key_region_rel_L2"]["best_max"],
                       "folds_pass": ranking["key_region_rel_L2"]["best_n_folds_pass"]},
        "S2_max_abs_p": {"best": ranking["S2_max_abs_p_rel_err"]["best_model"],
                         "max": ranking["S2_max_abs_p_rel_err"]["best_max"],
                         "folds_pass": ranking["S2_max_abs_p_rel_err"]["best_n_folds_pass"]},
    }, ensure_ascii=False, indent=2))
    return 0


def _load_solver_module() -> Any:
    src = REPO / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from memsharness import solver as solver_module
    return solver_module


def _gate_evidence() -> dict[str, Any]:
    """把两个冻结门禁文件的自述原文摘出来（**逐字**），作为对象错配的书证。"""
    out: dict[str, Any] = {}
    for path in GATE_FILES:
        if not path.is_file():
            out[path.name] = {"present": False}
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        out[path.name] = {
            "present": True,
            "sha256": sha256_file(path),
            "threshold": data.get("threshold"),
            "threshold_source_verbatim": data.get("threshold_source"),
            "rule_verbatim": data.get("rule"),
            "input_report": data.get("input_report"),
            "sha256_input_report": data.get("sha256_input_report"),
            "best_model": (data.get("best_model") or {}).get("model")
            if isinstance(data.get("best_model"), dict) else None,
        }
    return out


def _jsonable_folds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in row.items()} for row in rows]


def _markdown(report: dict[str, Any]) -> str:
    thr = {name: obj for name, obj in report["objects"].items()}
    lines: list[str] = []
    lines.append("# x=0.20 七快照管线：三个对象并列读数（补齐缺失的两个对象）")
    lines.append("")
    lines.append("生成时间：`%s`（UTC）。本文件由 `scripts/pod_objects_x020_v3.py` 生成。"
                 % report["generated_at"])
    lines.append("")
    lines.append("## 0. 定位（先读这一段）")
    lines.append("")
    lines.append("* 目的：**校正判读口径** —— 让同一批预测在正确的对象下被读数，不是放行该管线。")
    sc = report["scope_check"]
    lines.append("* 适用范围命中：**在声明范围内 = %s**（spec 声明 x∈[%.2f, %.2f]、N_w_te1∈[%.0f, %.0f]；"
                 "本管线 x=%.2f、N_w_te1=%s）⇒ 依红线 7，本管线的结果**只能拒答并回退 COMSOL**。"
                 % (sc["in_declared_scope"], sc["declared_x_scale"][0], sc["declared_x_scale"][1],
                    sc["declared_N_w_te1"][0], sc["declared_N_w_te1"][1],
                    sc["this_pipeline"]["x_scale"], sc["this_pipeline"]["N_w_te1"]))
    reg = report["regression_vs_frozen_report"]
    lines.append("* 回归：%d 个全域逐折值复算，最大偏差 %.3g（容差 %.3g）⇒ 复现 = %s。"
                 % (reg["n_values_compared"], reg["max_abs_deviation"], reg["tolerance"],
                    reg["reproduced"]))
    lines.append("")
    lines.append("## 1. 三个对象的定义与阈值")
    lines.append("")
    lines.append("| 对象 | 定义 | 点数 | 阈值 | 此前是否算过 |")
    lines.append("|---|---|---|---|---|")
    for name in ("global_rel_L2", "key_region_rel_L2", "S2_max_abs_p_rel_err"):
        o = thr[name]
        n = o.get("n_points", "—")
        if name == "S2_max_abs_p_rel_err":
            n = o.get("n_points", "极值点（在 %d 点内取 max）" % report["objects"]["global_rel_L2"]["n_points"])
        lines.append("| `%s` | %s | %s | %.3g | %s |"
                     % (name, o["definition"], n, o["threshold"],
                        "是" if o["already_computed_by_v2"] else "**否（本次补）**"))
    lines.append("")
    lines.append("## 2. 逐对象读数（10 个模型，按各对象 max 排名）")
    lines.append("")
    for obj, label in (("global_rel_L2", "全域相对 L2"),
                       ("key_region_rel_L2", "关键区相对 L2"),
                       ("S2_max_abs_p_rel_err", "S2 候选工程量 max|p| 相对误差")):
        r = report["per_object_ranking"][obj]
        o = thr[obj]
        lines.append(f"### {label}（阈值 {o['threshold']:.3g}）")
        lines.append("")
        lines.append("基线（最近邻持久化）：max %.4f，通过折 %d/7。"
                     % (r["baseline_max"], r["baseline_n_folds_pass"]))
        lines.append("")
        lines.append("| 模型 | max | 中位 | 通过折数 | 最差折 N1 |")
        lines.append("|---|---|---|---|---|")
        for row in r["ranking_by_max"]:
            lines.append("| `%s` | %.6f | %.6f | %d/7 | %d |"
                         % (row["model"], row["max"], row["median"],
                            row["n_folds_pass"], row["worst_fold_n1"]))
        lines.append("")
        lines.append("该对象下：全折通过的模型数 = **%d**；最优 max = %.6f。"
                     % (r["n_models_passing_all_folds"], r["best_max"]))
        lines.append("")
    lines.append("## 3. 对象错配的书证（逐字摘录）")
    lines.append("")
    for fname, ev in report["object_mismatch_evidence"].items():
        if not ev.get("present"):
            lines.append(f"* `{fname}`：**不存在**")
            continue
        lines.append(f"* `{fname}`（sha256 `{ev['sha256'][:16]}…`）阈值 {ev['threshold']}，"
                     f"`threshold_source` 原文：「{ev['threshold_source_verbatim']}」")
    lines.append("")
    lines.append("## 4. 每个模型的门禁视图（按对象读数，**不是放行**）")
    lines.append("")
    lines.append("| 模型 | S1 关键区 | S1 全域 | S2 max\\|p\\| | S0/S3/S4/S5 |")
    lines.append("|---|---|---|---|---|")
    for name, g in report["gate_view_per_object_reading_not_a_release"]["per_model"].items():
        v = g["verdicts"]
        lines.append("| `%s` | %s | %s | %s | inconclusive |"
                     % (name, v["S1"], v["S1"], v["S2"]))
    lines.append("")
    lines.append("> S1 一栏按代码口径给出（关键区与全域必须**同时**满足才 passed）；"
                 "S0/S3/S4/S5 本次无证据 ⇒ inconclusive，不得复述为通过。")
    lines.append("")
    lines.append("## 5. 注意事项（随报告同源）")
    lines.append("")
    for c in report["caveats"]:
        lines.append(f"* {c}")
    lines.append("")
    return "\n".join(lines)


def write_key_index(key: np.ndarray, radius: np.ndarray, points: np.ndarray,
                    points_sha: str) -> None:
    """把**关键区对象**本身固化成可复算的指纹（对象定义也是证据的一部分）。"""
    idx = np.flatnonzero(key)
    payload = {
        "kind": "key_region_index",
        "rule": "R = ‖(x,y,z)‖（原点距离）；key ⇔ R ≤ (1/3)·R_max",
        "key_f": KEY_F,
        "n_points_total": int(radius.size),
        "n_key_points": int(idx.size),
        "R_max_m": float(radius.max()),
        "R_cut_m": float(KEY_F * radius.max()),
        "points_file": str((PRUN / "common_points_xyz_m.tsv").relative_to(REPO)),
        "sha256_points_file": points_sha,
        "indices_in_masked_point_set": [int(i) for i in idx],
        "sha256_indices_int64_le": hashlib.sha256(idx.astype("<i8").tobytes()).hexdigest(),
        "first_point_m": [float(v) for v in points[idx[0]]],
        "note": ("掩膜后的点序号（0 基）。同一掩膜下该索引数组的哈希是对象的身份；"
                 "与 x 族缓存算出的哈希一致即证明两个『关键区』是同一批点。"),
    }
    OUT_KEY.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8", newline="\n")


def write_per_fold_tsv(report: dict[str, Any]) -> None:
    """逐折三对象平表（论文表格与后续复核直接取用，避免手抄）。"""
    header = ("model\theld_out_n1\tfold_type\tk_modes\tglobal_rel_L2\tkey_region_rel_L2\t"
              "S2_max_abs_p_rel_err\tmax_abs_p_true_Pa\tmax_abs_p_pred_Pa\t"
              "argmax_true_in_key\targmax_pred_in_key")
    rows = [header]
    for name, res in report["models"].items():
        for r in res["per_fold"]:
            rows.append("\t".join([
                name, str(r["held_out_n1"]), r["fold_type"],
                str(r["k_modes_selected_from_training_fold"]),
                "%.12g" % r["global_rel_L2"], "%.12g" % r["key_region_rel_L2"],
                "%.12g" % r["S2_max_abs_p_rel_err"],
                "%.12g" % r["eng_detail"]["max_abs_p_true_Pa"],
                "%.12g" % r["eng_detail"]["max_abs_p_pred_Pa"],
                str(r["eng_detail"]["argmax_true_in_key"]),
                str(r["eng_detail"]["argmax_pred_in_key"]),
            ]))
    for r in report["raw_persistence"]["per_fold"]:
        rows.append("\t".join([
            "raw_persistence", str(r["held_out_n1"]), r["fold_type"], "0",
            "%.12g" % r["global_rel_L2"], "%.12g" % r["key_region_rel_L2"],
            "%.12g" % r["S2_max_abs_p_rel_err"],
            "%.12g" % r["eng_detail"]["max_abs_p_true_Pa"],
            "%.12g" % r["eng_detail"]["max_abs_p_pred_Pa"],
            str(r["eng_detail"]["argmax_true_in_key"]),
            str(r["eng_detail"]["argmax_pred_in_key"]),
        ]))
    OUT_TSV.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())
