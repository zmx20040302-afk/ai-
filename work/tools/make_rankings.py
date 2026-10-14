"""生成两套粗扫排名产物 + 一级/二级差异表（Codex 裁决 §5）。

- `provisional_phase1_ranking/`：一级条件通过的 72 组；`ranking_status = provisional_phase1`
- `final_phase2_ranking/`：一级条件 **AND** `mesh_status == ok`；`ranking_status = final_phase2_screening`
- 两套各自调用 `scripts/analyze_sweep.py`（限定 `clean` 子集），再产出
  `phase1_vs_phase2_ranking_diff.csv`（§5.4 的 11 个字段）。

驱动口径按前面裁决：`drive_mode = circuit_terminal_1ohm_current_model`。
用法：python work\\tools\\make_rankings.py
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
PY = REPO / "work" / ".venv" / "Scripts" / "python.exe"
AGG = REPO / "work" / "runs" / "precheck-b2-phase2-v5-aggregate" / "geometry_selection_precheck.json"
CSV = REPO / "work" / "reports" / "analysis_decision" / "newrange005" / "raw_source_table.csv"
BASE = REPO / "work" / "reports" / "analysis_decision"
MODEL = r"C:\Users\zmx\Desktop\b_GE_task3_2new.mph"
MODEL_SHA = "0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d"
DRIVE = "circuit_terminal_1ohm_current_model"


def compat_rows(rows: list[dict], keep) -> dict:
    """转成 analyze_sweep 认得的 `precheck` 结构（只用 classification 做门禁）。"""
    return {
        "note": "由 stage2 聚合结果适配；'clean' 仅表示预检通过，不代表最终设计结论",
        "rows": [{"x_scale": r["x_scale"], "N_w_te1": r["N_w_te1"],
                  "classification": "clean" if keep(r) else "excluded_by_precheck",
                  "eligibility_level": r.get("eligibility_level"),
                  "mesh_status": r.get("mesh_status")}
                 for r in rows],
    }


def run_analysis(tag: str, precheck: Path, extra_note: str) -> Path:
    out = BASE / tag
    out.mkdir(parents=True, exist_ok=True)
    log = out / "analyze_sweep.log"
    cmd = [str(PY), str(REPO / "scripts" / "analyze_sweep.py"),
           "--csv", str(CSV), "--precheck", str(precheck), "--out-dir", str(out),
           "--batch-label", f"batch2-{tag}", "--model-file", MODEL, "--model-sha256", MODEL_SHA,
           "--model-version", "original_selection_original_drive", "--drive-mode", DRIVE,
           "--plan-candidates", "0.6:4:基准与网格桥接,0.7:5:双带宽闭合均衡点,"
                                "0.45:6:最大输出点,0.75:5:最平坦点",
           "--plan-optional", "0.5:5:中间高输出折中点",
           "--freq-start-mhz", "5", "--freq-stop-mhz", "45", "--freq-step-mhz", "0.5",
           "--notes", extra_note]
    with log.open("w", encoding="utf-8") as fh:
        code = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=str(REPO)).returncode
    print(f"  analyze_sweep[{tag}] exit={code} → {out}", flush=True)
    return out


def load_metrics(out: Path) -> tuple[dict, set]:
    m = {}
    with (out / "03_coarse_sweep_metrics.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r.get("precheck_class") != "clean":
                continue
            k = (float(r["x_scale"]), int(float(r["N_w_te1"])))
            m[k] = r
    pareto = set()
    pf = out / "04_pareto_candidates.csv"
    if pf.is_file():
        with pf.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if r.get("x_scale") not in (None, ""):
                    pareto.add((float(r["x_scale"]), int(float(r["N_w_te1"]))))
    return m, pareto


def ranks(metrics: dict, col: str) -> dict:
    vals = [(k, float(v[col])) for k, v in metrics.items() if v.get(col) not in (None, "")]
    vals.sort(key=lambda kv: -kv[1])
    return {k: i + 1 for i, (k, _) in enumerate(vals)}


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    agg = json.loads(AGG.read_text(encoding="utf-8"))
    p1_rows = agg["phase1_rows_with_pattern_id"]
    p2_rows = agg["phase2_rows"]

    # ---- 两套输入 ----
    d1 = BASE / "provisional_phase1_ranking"
    d2 = BASE / "final_phase2_ranking"
    for d in (d1, d2):
        d.mkdir(parents=True, exist_ok=True)
    f1 = d1 / "precheck_compat.json"
    f2 = d2 / "precheck_compat.json"
    f1.write_text(json.dumps(compat_rows(p1_rows, lambda r: r.get("eligible_for_ranking")),
                             ensure_ascii=False, indent=2), encoding="utf-8")
    f2.write_text(json.dumps(compat_rows(p2_rows, lambda r: True), ensure_ascii=False, indent=2),
                  encoding="utf-8")

    print("生成一级临时排名（provisional_phase1）…", flush=True)
    run_analysis("provisional_phase1_ranking", f1, "一级条件通过的 72 组；临时排名，不得用于最终设计决策")
    print("生成二级正式排名（final_phase2_screening）…", flush=True)
    run_analysis("final_phase2_ranking", f2, "一级条件 AND mesh_status==ok；仍仅为粗频网格筛选")

    # ---- 状态标记 ----
    (d1 / "ranking_status.json").write_text(json.dumps({
        "ranking_status": "provisional_phase1", "not_for_final_design_selection": True,
        "eligible_rule": "design==intended_design AND geometry==ok AND selection==verified AND area==valid_geometry",
        "n_combos": len(json.loads(f1.read_text(encoding='utf-8'))["rows"]),
        "ptot_definition_cn": "穿过固定外部半球辐射边界的向外声功率；在候选范围内可跨 x_scale 比较",
        "forbidden_interpretations": ["膜面局部压力", "往返回波功率", "接收灵敏度", "阵列声功率/阵列带宽"],
        "drive_mode": DRIVE,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (d2 / "ranking_status.json").write_text(json.dumps({
        "ranking_status": "final_phase2_screening", "not_for_final_design_selection": False,
        "eligible_rule": "phase1 rules AND mesh_status==ok",
        "n_combos": 72,
        "note": "“正式”仅指粗频网格筛选完成，不能替代 5–45 MHz 精扫与 7R 声压评价",
        "ptot_definition_cn": "穿过固定外部半球辐射边界的向外声功率；在候选范围内可跨 x_scale 比较",
        "drive_mode": DRIVE,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 差异表（§5.4）----
    m1, par1 = load_metrics(d1)
    m2, par2 = load_metrics(d2)
    r_p1, r_v1 = ranks(m1, "Ptot_20MHz_W"), ranks(m1, "Vave_20MHz")
    r_p2, r_v2 = ranks(m2, "Ptot_20MHz_W"), ranks(m2, "Vave_20MHz")
    keys = sorted(set(m1) | set(m2))
    out_csv = d2 / "phase1_vs_phase2_ranking_diff.csv"
    with out_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["x_scale", "N_w_te1", "phase1_eligible", "phase2_eligible",
                    "phase1_rank_ptot20", "phase2_rank_ptot20",
                    "phase1_rank_vave20", "phase2_rank_vave20",
                    "pareto_phase1", "pareto_phase2", "status_change_reason"])
        for k in keys:
            in1, in2 = k in m1, k in m2
            reason = ("证据等级由一级提升为二级（集合相同）"
                      if in1 and in2 else ("仅二级有记录" if in2 else "仅一级有记录"))
            w.writerow([k[0], k[1], in1, in2, r_p1.get(k, ""), r_p2.get(k, ""),
                        r_v1.get(k, ""), r_v2.get(k, ""), k in par1, k in par2, reason])

    # ---- 汇总打印 ----
    same_set = set(m1) == set(m2)
    print(f"\n一级集合 {len(m1)}｜二级集合 {len(m2)}｜集合相同={same_set}")
    print(f"Pareto：一级 {len(par1)}｜二级 {len(par2)}｜相同={par1 == par2}")
    top2 = sorted(m2.items(), key=lambda kv: -float(kv[1]["Ptot_20MHz_W"]))[:5]
    print("\n二级按 Ptot@20MHz 前 5：")
    for k, v in top2:
        print(f"  ({k[0]:g},{k[1]}) Ptot@20MHz={float(v['Ptot_20MHz_W']):.4g} W｜"
              f"Vave@20MHz={float(v['Vave_20MHz']):.4g}｜FBW_Vave%={v['FBW_Vave_percent']}｜"
              f"峰值@={v['f_peak_Ptot_MHz']} MHz")
    print(f"\n差异表：{out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
