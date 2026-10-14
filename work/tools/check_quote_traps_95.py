# -*- coding: utf-8 -*-
"""检查本轮**新增**的 §95 / §1.9 文本里有没有「中文串内嵌套 ASCII 双引号」的陷阱。"""
import pathlib

IDX = pathlib.Path(r"docs/INDEX-records-and-rulings.md")
INJ = pathlib.Path(r"docs/INJECTION_SOLVER_AUTOMATION_MERGED_20261008.md")
DQ = chr(34)


def has_cjk(s):
    return any("\u4e00" <= c <= "\u9fff" for c in s)


def main():
    idx = IDX.read_text(encoding="utf-8")
    sec95 = idx[idx.index("## 95. "):]
    inj = INJ.read_text(encoding="utf-8")
    a = inj.index("### 1.9 ")
    b = inj.index("---\n\n## 2. 2026-10-06 轮", a)
    sec19 = inj[a:b]
    for name, s in (("95", sec95), ("1.9", sec19)):
        bad = [(n, ln) for n, ln in enumerate(s.splitlines(), 1)
               if DQ in ln and has_cjk(ln)]
        print("== section %s: chars=%d  ASCII-DQ 总数=%d  含中文且含 ASCII-DQ 的行=%d"
              % (name, len(s), s.count(DQ), len(bad)))
        for n, ln in bad[:15]:
            print("   L%d: %s" % (n, ln[:200]))


main()
