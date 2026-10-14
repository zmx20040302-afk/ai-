# -*- coding: utf-8 -*-
"""一次性取证：由**当前**脚本逐字反演改动前文本，核对改前 sha256。

反演 = 逆向应用本轮的 3 处编辑（docstring 一句、新增 `_has_section_heading`、守卫调用点）。
若反演结果的 sha256 与开工时 `Get-FileHash` 实测值逐位相符 ⇒ 本轮改动范围被逐字封闭。
"""
from __future__ import annotations

import hashlib
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
P = REPO / "scripts/append_record_section.py"
BEFORE_SHA = "C7D4F3CE9B0EF795CB99E9069EF4E8BBFD4392DF687AF5889DE55E8337DA321F"

NEW_DOC = """守卫（fail-closed）：
* 片段必须**非空**、必须以 `## ` 开头的标题行；
* 目标索引里**已存在同一标题前缀**时拒绝追加（防重复记录）——判定按**行首精确匹配**
  （见 `_has_section_heading`：只有整行以 heading 开头、且其后是行尾或空白才算命中）；
* 追加前备份到 `work/logs/`（文件名带时间戳），追加后校验字符数只增不减。
"""

OLD_DOC = """守卫（fail-closed）：
* 片段必须**非空**、必须以 `## ` 开头的标题行；
* 目标索引里**已存在同一标题前缀**时拒绝追加（防重复记录）；
* 追加前备份到 `work/logs/`（文件名带时间戳），追加后校验字符数只增不减。
"""

NEW_CALL = "    if _has_section_heading(txt, a.heading):"
OLD_CALL = "    if a.heading in txt:"


def main() -> int:
    cur = P.read_text(encoding="utf-8")
    old = cur
    assert NEW_DOC in old, "docstring 片段未找到"
    old = old.replace(NEW_DOC, OLD_DOC)
    i0 = old.index("def _has_section_heading")
    i1 = old.index("def main() -> int:")
    old = old[:i0] + old[i1:]
    assert NEW_CALL in old, "守卫调用点未找到"
    old = old.replace(NEW_CALL, OLD_CALL)
    raw = old.encode("utf-8")
    h = hashlib.sha256(raw).hexdigest()
    print("反演出的改前文本 = %d B / %d 行" % (len(raw), old.count("\n")))
    print("反演 sha256 = %s" % h)
    print("与开工实测 %s 逐位相符 = %s" % (BEFORE_SHA, h.upper() == BEFORE_SHA))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
