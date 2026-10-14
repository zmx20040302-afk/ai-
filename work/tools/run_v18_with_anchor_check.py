# -*- coding: utf-8 -*-
"""用生成器自己的常量复核锚点，然后调用生成器 main()。"""
import importlib.util
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("g18", R / "work/tools/make_dac2027_en_v18.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

v17 = g.V17.read_text(encoding="utf-8")
sup = g.SUPD.read_text(encoding="utf-8")
pairs = [("body", v17, g.B_OLD), ("S9", sup, g.S_OLD), ("T3", sup, g.T3_OLD), ("T5", sup, g.T5_OLD)]
ok = True
for name, text, anchor in pairs:
    c = text.count(anchor)
    print("%-5s anchor count = %d" % (name, c))
    ok &= (c == 1)
if not ok:
    raise SystemExit("[FAIL] 锚点未逐字命中，先修生成器")
print("\n--- 常量与磁盘一致，运行生成器 ---\n")
raise SystemExit(g.main())
