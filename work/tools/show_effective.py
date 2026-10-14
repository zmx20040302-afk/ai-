"""打印某个 .m 中匹配给定子串的**末次生效值**（复用 diff_model_m.extract，保证同一套 last-wins 口径）。

用法：python work\\tools\\show_effective.py <file.m> <子串1> [子串2 ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diff_model_m as d  # noqa: E402


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    f = Path(sys.argv[1])
    needles = sys.argv[2:]
    items, meta = d.extract(f)
    print(f"{f.name}｜sha256={meta['sha256'][:16]}…｜唯一生效属性 {meta['unique_effective_properties']} 个")
    for needle in needles:
        print(f"\n=== 匹配 {needle!r} 的末次生效值 ===")
        n = 0
        for cat in sorted(items):
            for key, val in sorted(items[cat].items()):
                if needle.lower() in key.lower() or needle.lower() in str(val["value"]).lower():
                    print(f"  [{cat}] {key} = {val['value']}  (L{val['line']})")
                    n += 1
        if n == 0:
            print("  （无匹配）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
