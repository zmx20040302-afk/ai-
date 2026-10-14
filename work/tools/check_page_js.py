# -*- coding: utf-8 -*-
"""取出 `scripts/webapp_server.py` 里 PAGE 的前端 JS，写成文件以便 `node --check`。

为什么要它：PAGE 是 Python 普通三引号字符串，**反斜杠会被 Python 先吃一层**
（例如 JS 里要写 `split('\\\\')`、正则 `\\n`）。这类错误 Python 编译期发现不了，
只有把生成后的 HTML 交给 JS 解析器才知道。**改前端后必跑**：

    python -B work\\tools\\check_page_js.py            # 抽取 + 自检能跑
    node --check work\\tmp_page.js                     # 真的解析一遍

打印的文件大小与 HTML 字节数也用来核对"改动有没有生效"。
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "work" / "tmp_page.js"


def load_page() -> str:
    spec = importlib.util.spec_from_file_location("_web", REPO / "scripts" / "webapp_server.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.PAGE


def main() -> int:
    html = load_page()
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    print("script blocks:", len(blocks))
    if len(blocks) != 1:
        print("期望恰好 1 个 <script> 块（多块会让 node --check 语义变模糊）")
    OUT.write_text("\n".join(blocks), encoding="utf-8")
    hb, jb = len(html.encode("utf-8")), OUT.stat().st_size
    print("page bytes: %d  js bytes: %d" % (hb, jb))
    print("wrote:", OUT.relative_to(REPO))
    # 抽出的 JS 里出现裸的 \u / 未转义换行 ⇒ 多半是被 Python 吃掉一层反斜杠
    if re.search(r"\\u[0-9a-fA-F]{4}", OUT.read_text(encoding="utf-8")):
        print("SUSPECT: JS 里出现 \\uXXXX（检查是不是 Python 转义写错）")
    print("next: node --check %s" % OUT.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
