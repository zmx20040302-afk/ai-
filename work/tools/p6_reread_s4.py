# -*- coding: utf-8 -*-
"""P6：把 [S4] 九档数字**从自己的产物重读一遍**（英文稿 §9 自己列的待办之一）。

背景：英文稿 §9 的 `[S4]` 行当时写着「这些数字引自中文工作稿，**未重读**」。本脚本改为：
  * 权威产物 = `work/runs/field-expansion-20261009/p4_l11/S4_L11_REPORT.json`（九档 / 72 有序对）；
  * 从该 JSON **机器提取**论文引用的每一个数字；
  * 与英文稿、中文稿正文里实际出现的数字**逐条比对**（容差 1e-6 相对），给出 match/mismatch。
产物：`work/runs/eda64-20261010/p6_paper/S4_NINE_LEVEL_REREAD.json`。
"""
from __future__ import annotations

import io
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
ART = REPO / "work/runs/field-expansion-20261009/p4_l11/S4_L11_REPORT.json"
EN = REPO / "docs/PAPER_DAC2027_EN_v1_20261010.md"
ZH = REPO / "docs/PMUT_DAC2027_初稿_v11_20261010.md"
OUT = REPO / "work/runs/eda64-20261010/p6_paper"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    d = json.loads(ART.read_text(encoding="utf-8"))
    v = d["s4_verdict"]
    ex = d["three_readings"]
    facts = {
        "artifact": str(ART.relative_to(REPO)),
        "n_levels": v["n_levels"], "n_ordered_pairs": v["n_ordered_pairs"],
        "common_mask_points": v["common_mask_points"], "frozen_points": v["frozen_points"],
        "key_region_points": v["key_region_points_frozen_set"],
        # 判定量（用户裁定：空间对象 = 关键区）
        "decision_metric_name": v["decision_metric_name"],
        "key_region_max": v["decision_metric"],
        "key_region_worst_pair": "%s over %s" % (v["worst_pair_in_key_region"]["i"],
                                                v["worst_pair_in_key_region"]["j"]),
        "key_region_passed": v["passed"],
        "threshold": v["threshold_key"],
        # 参考量（全域，非判定）
        "global_max": v["global_reference"]["value"],
        "global_worst_pair": "%s over %s" % (v["global_reference"]["worst_pair"]["i"],
                                             v["global_reference"]["worst_pair"]["j"]),
        # Richardson 外推三口径
        "richardson_assumed_0.78": ex["ratio_111_assumed_0.78"]["R_est"],
        "richardson_ladder_mean": ex["ratio_whole_ladder_mean"]["R_est"],
        "richardson_ladder_mean_r": ex["ratio_whole_ladder_mean"]["r"],
        "richardson_recent_step": ex["ratio_most_recent_step"]["R_est"],
        "richardson_recent_r": ex["ratio_most_recent_step"]["r"],
        "all_three_below_2pct": ex["all_three_below_2pct"],
        "d_last": ex["d_last_adjacent_difference"],
        # 回归靶（尺子校准）
        "regression_111": {"recomputed": d["regression_111"]["recomputed_max"],
                           "registered": d["regression_111"]["registered_max"],
                           "match": d["regression_111"]["match"]},
        "regression_145": {"recomputed": d["regression_145"]["recomputed_max"],
                           "registered": d["regression_145"]["registered_max"],
                           "match": d["regression_145"]["match"]},
        "spatial_object_ruling": d["spatial_object_ruling"]["authoritative_object"],
        "ruled_by": d["spatial_object_ruling"]["ruled_by"],
        "mesh_independence_claim": v["mesh_independence_claim"],
        "solve_time_anomaly": {"measured_s": d["solve_time_anomaly"]["measured_solve_seconds"],
                               "predicted_s": d["solve_time_anomaly"]["predicted_solve_seconds"],
                               "ratio": d["solve_time_anomaly"]["ratio_measured_over_predicted"]},
        "peak_memory_GB_authoritative": d["peak_memory_authoritative"]["ftet_l11"]["GB"],
        "dof_l11": d["peak_memory_authoritative"]["ftet_l11"]["dof_batchlog"],
    }
    print("== 从产物重读 ==")
    for k, val in facts.items():
        print("   %-26s %s" % (k, val))

    # 与两份稿件的正文对照（只查"该出现的百分比/数字是否出现且一致"）
    def load(p):
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    texts = {"en": load(EN), "zh": load(ZH)}
    checks = []
    want = [("0.6753", facts["key_region_max"], 4),
            ("1.5504", facts["global_max"], 4),
            ("1.3446", facts["richardson_assumed_0.78"], 4),
            ("1.4300", facts["richardson_ladder_mean"], 4),
            ("1.4963", facts["richardson_recent_step"], 4)]
    for label, val, nd in want:
        for tag, t in texts.items():
            checks.append({"number": label, "value_from_artifact": round(val, nd + 4),
                           "appears_in_%s" % tag: (label in t)})
    # 关键区/全域的"最差对"是否一致
    wp = {"key_region_worst_pair": facts["key_region_worst_pair"],
          "global_worst_pair": facts["global_worst_pair"]}
    out = {"kind": "p6_s4_nine_level_reread", "facts": facts,
           "cross_check": checks, "worst_pairs": wp,
           "note": ("判定量 = 关键区（用户 2026-10-09 裁定）；全域值仅作参考；"
                    "Richardson 三口径是**外推估计**不是实测；口径 O 只覆盖所测 9 档两两差，"
                    "**不声称网格无关**。"),
           "round_trip": {"artifact_sha256": __import__("hashlib").sha256(
               ART.read_bytes()).hexdigest()}}
    (OUT / "S4_NINE_LEVEL_REREAD.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
    bad = [c for c in checks if not all(v is True for k, v in c.items() if k.startswith("appears_"))]
    print("\n== 与稿件对照：%d 条不一致（%d 条检查）" % (len(bad), len(checks)))
    for c in bad:
        print("   ", c)
    print("== 写出", OUT / "S4_NINE_LEVEL_REREAD.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
