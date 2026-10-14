# -*- coding: utf-8 -*-
"""小数 N1 留出集：从**已求解模型**取正确口径的工程量（不重新求解）。

上一轮的教训（写在这里防重犯）：
* `max|p|` 被我用 `np.asarray(..., dtype=float)` 强转，**虚部被静默丢掉**
  （日志里的 `ComplexWarning: Casting complex values to real discards the imaginary part`
  就是它），于是记下的是 `max|Re(p)|` 而**不是**声压幅值 ⇒ 口径错误，不得用于趋势。
  正确做法：**保留复数**，再 `np.abs(arr).max()`。

本脚本对 `solved_N1_{4.5,5.5,6.5}.mph`（已含解，各约 145 MB）逐个：
1. 载入 → 直接求值（约 30 s/点，不重解）；
2. 记 `max|p|`（复数模）、`max|Re(p)|`、`max|Im(p)|`、`n_values`；
3. 记**解的有限性/非退化**作为最小 sanity（min/max/是否含 NaN）；
4. **不声称已核收敛**：残差/求解器日志我**没有**读（不猜 API）；取到就记，取不到就写没取到。

用法：work\\.venv\\Scripts\\python.exe scripts\\eval_frac_n1_from_solved.py
"""
from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMSOL_HOME = os.environ.get("MEMS_COMSOL_HOME", r"D:\COMSOL64\Multiphysics")
COMSOL_BIN = Path(COMSOL_HOME) / "bin" / "win64"
RUN_DIR = REPO / "work/runs/fractional-n1-probe-20261001"
N1S = (4.5, 5.5, 6.5)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="从已求解模型取正确口径的 max|p|")
    ap.add_argument("--out", default=str(RUN_DIR / "fractional_n1_engineering.json"))
    a = ap.parse_args(argv)
    os.environ["PATH"] = "%s%s%s" % (COMSOL_BIN, os.pathsep, os.environ.get("PATH", ""))

    import numpy as np
    ev = {"kind": "fractional_n1_engineering", "expr": "p (complex)", "unit": "Pa",
          "generated_at": datetime.now().isoformat(timespec="seconds"),
          "caliber_fix": "保留复数取模（上一轮 dtype=float 丢了虚部 ⇒ 记的是 max|Re(p)|）",
          "convergence_checked": False,
          "convergence_note": "残差/求解器日志**未读**（不猜 API）；本文件只给「解的有限性/非退化」这一层 sanity。",
          "per_point": {}, "errors": [], "steps": [], "ok": False}
    try:
        import mph
        client = mph.Client()
        ev["client_version"] = str(client.version)
        for n1 in N1S:
            tag = "N1=%g" % n1
            p = RUN_DIR / ("solved_N1_%g.mph" % n1)
            rec = {"file": p.name, "exists": p.is_file(),
                   "bytes": p.stat().st_size if p.is_file() else None}
            if not p.is_file():
                ev["errors"].append("%s 缺已求解模型：%s" % (tag, p.name))
                ev["per_point"][tag] = rec
                continue
            t0 = time.perf_counter()
            try:
                m = client.load(str(p))
                rec["load_seconds"] = round(time.perf_counter() - t0, 1)
                out = m.evaluate("p", "Pa")          # 不转 dtype！保留复数
                arr = np.asarray(out[0] if isinstance(out, (tuple, list)) else out)
                if np.iscomplexobj(arr):
                    rec["is_complex"] = True
                    rec["max_abs_p_Pa"] = float(np.nanmax(np.abs(arr)))
                    rec["max_abs_Re_Pa"] = float(np.nanmax(np.abs(arr.real)))
                    rec["max_abs_Im_Pa"] = float(np.nanmax(np.abs(arr.imag)))
                else:
                    rec["is_complex"] = False
                    rec["max_abs_p_Pa"] = float(np.nanmax(np.abs(arr)))
                rec["n_values"] = int(arr.size)
                rec["has_nan"] = bool(np.isnan(arr).any())
                rec["finite_and_nontrivial"] = bool(
                    not rec["has_nan"] and rec["max_abs_p_Pa"] > 0)
                rec["sol_tags"] = [str(x) for x in m.java.sol().tags()]
                ev["steps"].append("%s: OK (%.1fs)" % (tag, time.perf_counter() - t0))
            except Exception as exc:  # noqa: BLE001
                ev["errors"].append("%s: %s: %s" % (tag, type(exc).__name__, str(exc)[:200]))
            ev["per_point"][tag] = rec
            print("  - %s max|p|=%.6g Pa (Re=%.6g) complex=%s" % (
                tag, rec.get("max_abs_p_Pa") or -1, rec.get("max_abs_Re_Pa") or -1,
                rec.get("is_complex")), flush=True)
        got = [r for r in ev["per_point"].values() if r.get("max_abs_p_Pa")]
        ev["n_with_correct_caliber"] = len(got)
        ev["ok"] = True
        ev["verdict"] = "holdout_ready" if len(got) == len(N1S) else "partial"
    except Exception as exc:  # noqa: BLE001
        ev["errors"].append("fatal: %s: %s" % (type(exc).__name__, exc))
        ev["traceback"] = traceback.format_exc()
    Path(a.out).write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 66)
    print("正确口径 max|p|：%d/%d 点取到；verdict=%s" % (
        ev.get("n_with_correct_caliber") or 0, len(N1S), ev.get("verdict")))
    for e in ev["errors"]:
        print("  [错误]", e[:170])
    print("证据：", a.out)
    print("=" * 66)
    return 0 if ev.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
