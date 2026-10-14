"""复核 Codex 指出的"双口径闭合"计数（它用来纠正我方'唯一双闭合点'的错误表述）。"""

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
    rows = [r for r in csv.DictReader((D / "03_coarse_sweep_metrics.csv").open(encoding="utf-8-sig"))
            if r.get("precheck_class") == "clean"]
    par = {((float(r["x_scale"])), int(float(r["N_w_te1"])))
           for r in csv.DictReader((D / "04_pareto_candidates.csv").open(encoding="utf-8-sig"))
           if r.get("x_scale") not in (None, "")}

    def dual(r):
        return (str(r.get("bandwidth_closed_Vave")) == "True"
                and str(r.get("bandwidth_closed_Ptot")) == "True")

    d_all = [r for r in rows if dual(r)]
    d_par = [r for r in d_all
             if (float(r["x_scale"]), int(float(r["N_w_te1"]))) in par]
    print(f"72 组中双口径闭合：{len(d_all)} 组（Codex 声称 9）")
    print(f"其中属于 Pareto 前沿：{len(d_par)} 组（Codex 声称 3）")
    print(f"\n{'组合':>12} {'FBW_Vave%':>10} {'FBW_Ptot%':>10} {'flat15-25':>10}")
    for r in sorted(d_par, key=lambda r: float(r["flatness_15_25_dB"])):
        print(f"  ({float(r['x_scale']):g},{int(float(r['N_w_te1'])):>2d}) "
              f"{float(r['FBW_Vave_percent']):>10.2f} {float(r['FBW_Ptot_percent']):>10.2f} "
              f"{float(r['flatness_15_25_dB']):>10.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
