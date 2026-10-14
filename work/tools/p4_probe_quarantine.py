# -*- coding: utf-8 -*-
"""P4 前置探测：隔离组合在**加隔离判定前后**各自的拒答原因（别猜，实测）。

回答两件事：
  1. 隔离组合 `(0.2, 1, 7)` / `(0.2, 1, 8)` 是否本来就落在层标定范围之外（那只是换了原因桶），
     还是本来会被**正常出数**（那才是 #10 的真实风险）。
  2. 三个正式目标在模型里的层键与 x 节点范围。
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from memsharness import multichannel_surrogate as MCS  # noqa: E402

m = MCS.load()
print("excluded_quarantine =", json.dumps(m.get("excluded_quarantine"), ensure_ascii=False))
for ch in ("bandwidth_Hz", "abs_w_m", "abs_p_per_V_Pa"):
    info = m["channels"][ch]
    print("\n== %s  (space=%s)" % (ch, info["space"]))
    for key in ("7|1", "8|1"):
        lay = info["layers"].get(key)
        if lay is None:
            print("   layer %-6s 不存在" % key)
            continue
        xs = lay["x"]
        print("   layer %-6s n=%d  x ∈ [%g, %g]  含 0.2? %s  含 0.25? %s"
              % (key, len(xs), xs[0], xs[-1], 0.2 in [round(v, 6) for v in xs],
                 0.25 in [round(v, 6) for v in xs]))

print("\n== 隔离点预测结果（当前代码已含隔离判定）")
for (x, n1, n2) in ((0.2, 1, 7), (0.2, 1, 8), (0.2, 2, 7), (0.25, 1, 7)):
    try:
        r = MCS.predict(x, n1, n2)
        print("   (%g,%d,%d) → 出数 mode=%s 值=%s"
              % (x, n1, n2, r["mode"], {k: round(v["value"], 6) for k, v in r["channels"].items()}))
    except MCS.Refused as e:
        print("   (%g,%d,%d) → 拒答 标签=%s" % (x, n1, n2, MCS._classify_refusal(str(e))))
        print("       原文：%s" % e)
