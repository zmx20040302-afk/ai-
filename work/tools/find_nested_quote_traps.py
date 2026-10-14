# -*- coding: utf-8 -*-
"""找出 **Python 源码里"双引号字符串内部又用了 ASCII 双引号"** 的引号陷阱。

为什么需要它（2026-09-29 实测，本会话已踩 5 次）：写中文注释/字符串时习惯用引号强调，
于是出现 `"…数据**不支持"峰在 5 MHz 以下"**…"` 这种写法 —— Python 把它当成**字符串提前结束**，
报出来的却是 `SyntaxError: invalid syntax. Perhaps you forgot a comma?`，
**指向的行号还不一定是真凶**，很费时间。仓库约定是用 **`「」`** 代替内层引号。

判据（启发式，宁可多报）：一行里 `"` 的个数 ≥3、且该行含 CJK、
且**不是**三引号块的行、且不是纯注释里已用 `「」` 的。

用法：
    python -B work/tools/find_nested_quote_traps.py <文件.py> [...]
    python -B work/tools/find_nested_quote_traps.py --dir work/runs
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
CJK = re.compile(r"[\u3400-\u9fff]")
#: ⚠️ 最准的判据：**ASCII 双引号夹在两个中文字之间**（`中文"中文`）。
#: 头一版只用"引号数为奇数 + 含中文"，**漏掉了偶数个引号的情形**
#: （实测：`("证据指向"峰在窗口之上"（…` 共 6 个引号，仍会让字符串提前结束）。
TRAP = re.compile(r"[\u3400-\u9fff]\s*\"\s*[\u3400-\u9fff]")


def compile_error(p: pathlib.Path) -> tuple[int, str] | None:
    """**精确判据**：让 Python 自己解析；语法错就报出行号与信息。

    为什么要加这一层（2026-09-29 实测）：启发式 `TRAP` 要求**引号两侧都是中文**
    （`中文"中文`），于是 `证明"A 与 B 是同一物理量"`（中文在前、ASCII 在后）**被漏掉**，
    而它是**确定的语法错误**。启发式会漏，解析器不会。

    ⚠️ **只对 `.py` 生效**：对 markdown/文本文件 `compile()` 必然报
    `invalid character '：'`，那是**假警报**（实测：把 INDEX 的 .md 传进来就报了"确定性"）。

    ⚠️ **必须用 `utf-8-sig` 读**：CPython **允许**源码带 UTF-8 BOM，
    但若把它读成 `U+FEFF` 再 `compile()` 就会报
    `invalid non-printable character U+FEFF` —— 那又是**假警报**
    （实测：`work/tools` 下 10 个文件全被误报为"确定性语法错误"，
    只因为它们是我用 `Set-Content -Encoding UTF8` 写的、带 BOM）。
    判据必须**与解释器的真实导入方式一致**，否则门禁会制造噪音而不是价值。
    """
    if p.suffix != ".py":
        return None
    src = p.read_text(encoding="utf-8-sig", errors="replace")
    try:
        compile(src, str(p), "exec")
    except SyntaxError as exc:
        if exc.lineno:
            return int(exc.lineno), "%s: %s" % (type(exc).__name__, exc.msg)
        return 0, "%s: %s" % (type(exc).__name__, exc.msg)
    return None


def scan(p: pathlib.Path) -> list[tuple[int, str, str]]:
    """返回 [(行号, 级别, 原文)]；级别 ∈ {确定性, 可疑}。"""
    out: list[tuple[int, str, str]] = []
    ce = compile_error(p)
    if ce:
        out.append((ce[0], "确定性", ce[1]))
    in_triple = False
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if line.count('"""') % 2 == 1:
            in_triple = not in_triple
            continue
        if in_triple:
            continue
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if TRAP.search(line):
            out.append((i, "可疑", s[:140]))
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__.strip().splitlines()[-2])
        return 2
    files: list[pathlib.Path] = []
    if argv[0] == "--dir":
        root = pathlib.Path(argv[1])
        if not root.is_absolute():
            root = REPO / root
        files = sorted(root.rglob("*.py"))
    else:
        for a in argv:
            p = pathlib.Path(a)
            files.append(p if p.is_absolute() else REPO / p)
    total = 0
    n_hard = 0
    for p in files:
        if not p.is_file():
            continue
        hits = scan(p)
        if hits:
            total += len(hits)
            print("== %s ==" % p.relative_to(REPO) if p.is_relative_to(REPO) else p)
            for i, lvl, s in hits:
                if lvl == "确定性":
                    n_hard += 1
                print("   L%-5d [%s] %s" % (i, lvl, s))
    print("命中合计：%d（其中**确定性语法错误** %d）" % (total, n_hard))
    print("修法：把内层 ASCII 双引号改成「」；或改用单引号包字符串。")
    print("说明：「确定性」= Python 解析器直接报语法错（一定会炸）；"
          "「可疑」= 启发式（引号两侧都是中文），需人工确认。")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
