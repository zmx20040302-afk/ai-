# -*- coding: utf-8 -*-
"""侦察：从 6 个注册结果件里抽出**可被断言的数字**，并列出各任务脚本的输入依赖。

只读；不改任何东西。目的是把「要复现什么」先钉死，再动手 vendor。
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
M13 = R / "work/runs/ai11-m1m3-20261013"
T15 = R / "work/runs/ai11-t1t2t5-20261013"
T7 = R / "work/runs/ai11-t7-multiseed-20261013"

SCALARS = (int, float, str, bool, type(None))


def dump(path: pathlib.Path, prefix: str = "", depth: int = 0, maxdepth: int = 3):
    d = json.loads(path.read_text(encoding="utf-8"))
    print("\n" + "=" * 78)
    print("### %s   (%d B)" % (path.name, path.stat().st_size))
    print("=" * 78)

    def walk(o, ind=0, key=""):
        pad = "  " * ind
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, (dict, list)):
                    n = len(v)
                    print("%s%s: <%s %d>" % (pad, k, type(v).__name__, n))
                    if ind < maxdepth:
                        walk(v, ind + 1, k)
                else:
                    print("%s%s = %r" % (pad, k, v))
        elif isinstance(o, list):
            if o and isinstance(o[0], dict) and ind < maxdepth:
                print("%s[0] 示例:" % pad)
                walk(o[0], ind + 1)
            elif o and isinstance(o[0], SCALARS):
                print("%s%s" % (pad, repr(o[:8])[:160]))
            else:
                print("%s<%d items>" % (pad, len(o)))

    walk(d)


for f in ("M1_RESULT_V2.json", "M3_RESULT.json"):
    dump(M13 / f, maxdepth=2)

print("\n\n########## M2（大件，只看骨架）##########")
d = json.loads((M13 / "M2_RESULT.json").read_text(encoding="utf-8"))
print("顶层键:", list(d.keys()))
for k, v in d.items():
    if isinstance(v, dict):
        print("  %s: <%d 子键> %s" % (k, len(v), list(v.keys())[:8]))
    elif isinstance(v, list):
        print("  %s: <%d items>" % (k, len(v)))
        if v and isinstance(v[0], dict):
            print("       样例键:", list(v[0].keys()))
    else:
        print("  %s = %r" % (k, v))

for f in ("T1_T2_RESULT.json", "T5_RESULT.json"):
    dump(T15 / f, maxdepth=2)

dump(T7 / "T7_MULTISEED_RESULT.json", maxdepth=3)

print("\n\n########## 输入依赖 ##########")
import re
for p in (M13 / "run_m1_m2_m3.py", M13 / "m1_analyze_v2.py", T15 / "run_t1_t2.py",
          T15 / "run_t1_t2_spacing.py", T15 / "run_t5.py", T7 / "dse/run_dse.py"):
    t = p.read_text(encoding="utf-8")
    print("\n--- %s (%d 行) ---" % (p.name, t.count("\n") + 1))
    for m in re.finditer(r'^(REPO|HERE|OUT|N2\w*|ASSIGN|AC|V3|V2L|SPEC|REG|M\d\w*|T\d\w*|SRC|DST|CACHE|LEDGER)\s*=\s*(.+)$',
                         t, re.M):
        print("   %-8s = %s" % (m.group(1), m.group(2).strip()[:96]))
    print("   work/runs 引用 %d 处" % len(re.findall(r"work[/\\]runs", t)))
