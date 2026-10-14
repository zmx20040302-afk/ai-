"""打印二级正式排名的 Pareto 前沿与关键指标（供提出精扫候选）。"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

D = Path(r"C:\Users\zmx\Desktop\memsharness\work\reports\analysis_decision\final_phase2_ranking")


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    rows = list(csv.DictReader((D / "03_coarse_sweep_metrics.csv").open(encoding="utf-8-sig")))
    clean = [r for r in rows if r.get("precheck_class") == "clean"]
    par = {((float(r["x_scale"])), int(float(r["N_w_te1"]))) for r in
           csv.DictReader((D / "04_pareto_candidates.csv").open(encoding="utf-8-sig"))
           if r.get("x_scale") not in (None, "")}
    f = lambda r, k: float(r[k]) if r.get(k) not in (None, "") else float("nan")

    def line(r):
        k = (float(r["x_scale"]), int(float(r["N_w_te1"])))
        return (f"  ({k[0]:g},{k[1]:<2d}) Ptot@20M={f(r,'Ptot_20MHz_W'):.4g} "
                f"Vave@20M={f(r,'Vave_20MHz'):.4g} FBW_Vave%={f(r,'FBW_Vave_percent'):.1f} "
                f"flat15-25={f(r,'flatness_15_25_dB'):.2f}dB "
                f"fpeak_Ptot={f(r,'f_peak_Ptot_MHz'):.0f} fpeak_Vave={f(r,'f_peak_Vave_MHz'):.0f} "
                f"顶边(P/V)={r.get('Ptot_upper_bound_not_found')}/{r.get('Vave_upper_bound_not_found')}")

    print(f"Pareto 前沿（{len(par)} 组，按 Ptot@20MHz 降序）：")
    for r in sorted([r for r in clean if (float(r["x_scale"]), int(float(r["N_w_te1"]))) in par],
                    key=lambda r: -f(r, "Ptot_20MHz_W")):
        print(line(r))
    print("\n基准 (0.6,4)：")
    for r in clean:
        if (float(r["x_scale"]), int(float(r["N_w_te1"]))) == (0.6, 4):
            print(line(r))
    print("\nFBW_Vave 最宽前 5：")
    for r in sorted(clean, key=lambda r: -f(r, "FBW_Vave_percent"))[:5]:
        print(line(r))
    print("\nflatness_15_25 最平前 5：")
    for r in sorted(clean, key=lambda r: f(r, "flatness_15_25_dB"))[:5]:
        print(line(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
