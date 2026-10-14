"""对照：同一段解析代码分别处理两份 .m，定位「参数表为空」的结构差异。"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
sys.path.insert(0, str(REPO / "src"))
from memsharness import modelio as mio  # noqa: E402

SMALL = Path(r"C:\Users\zmx\Desktop\b_GE_task3_2new.m")
YIZU = Path(r"C:\Users\zmx\Desktop\换能器\b_GE_task3_2newyizu.m")

for label, path in (("小模型 b_GE_task3_2new.m", SMALL), ("yizu b_GE_task3_2newyizu.m", YIZU)):
    spec = mio.parse_matlab_export(path)
    print(f"== {label} ==")
    print(f"   parsed={spec.get('parsed')} 参数数={len(spec.get('parameters') or [])} "
          f"几何={len(spec.get('geometry') or [])} 材料={len(spec.get('materials') or [])} "
          f"物理场={len(spec.get('physics') or [])} 选择集={len(spec.get('selections') or [])} "
          f"研究={len(spec.get('study') or [])} 求解器={len(spec.get('solvers') or [])}")
    print(f"   notes={spec.get('notes')}")
    print(f"   行数={len(path.read_text(encoding='utf-8', errors='replace').splitlines())}")

small_lines = SMALL.read_text(encoding="utf-8", errors="replace").splitlines()
yizu_lines = YIZU.read_text(encoding="utf-8", errors="replace").splitlines()
print("\n== 前 220 行差异（unified，仅显示差异行）==")
diff = list(difflib.unified_diff(small_lines[:220], yizu_lines[:220], "small", "yizu", lineterm="", n=1))
shown = 0
for line in diff:
    if line.startswith(("+++", "---")):
        continue
    print("  " + line[:150])
    shown += 1
    if shown > 60:
        print("  …（截断）")
        break

print("\n== small 里 param.set 之前 20 行的上下文（看块标记）==")
for i, line in enumerate(small_lines[:70], 1):
    if "param.set" in line:
        for j in range(max(0, i - 12), i + 2):
            print(f"  small L{j+1}: {small_lines[j][:120]}")
        break
print("\n== yizu 里 param.set 之前 20 行的上下文 ==")
for i, line in enumerate(yizu_lines[:70], 1):
    if "param.set" in line:
        for j in range(max(0, i - 12), i + 2):
            print(f"  yizu  L{j+1}: {yizu_lines[j][:120]}")
        break
