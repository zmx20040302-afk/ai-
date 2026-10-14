# -*- coding: utf-8 -*-
"""页面静态一致性核对：**JS 里引用的每个 `$('#id')` 都必须在 HTML 里存在**。

为什么要它（2026-09-29 实测）：用户在页面上"点预测没反应"。JS 语法 `node --check` 通过、
`boot()` 也没有抛错，但**如果某个 `$('#xxx')` 取不到元素**，点击处理器第一行就抛异常，
而处理器里的异常**不会显示到页面上** ⇒ 表现为"点了没反应"。
这类错误纯静态就能查出来，不该靠人点。

顺带核对：
* **重复 id**（`querySelector` 只会拿到第一个 ⇒ 静默拿错元素）；
* 页面**必备声明**是否还在（缺了服务端会拒绝启动）；
* 是否**没有**禁止措辞；
* 每个 `<button id=...>` 是否都在 JS 里被绑过 `onclick`（未绑的按钮点了必然没反应）。

用法：python -B work\\tools\\check_page_ids.py [页面路径]
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_PAGE = REPO / "scripts/webapp_page.html"

MUST_HAVE = ("响应级代理", "不是 AI 求解器", "拒答", "model_id", "离线", "放行权在人")
FORBIDDEN = ("免 COMSOL 出解", "已验证等价", "可以替代 COMSOL", "solver_certified")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    page = pathlib.Path(argv[0]) if argv else DEFAULT_PAGE
    if not page.is_file():
        print("[FAIL] 页面不存在：%s" % page)
        return 2
    t = page.read_text(encoding="utf-8")

    ids = re.findall(r'id="([^"]+)"', t)
    id_set = set(ids)
    js_blocks = re.findall(r"<script>([\s\S]*?)</script>", t)
    js = "\n".join(js_blocks)
    used = sorted(set(re.findall(r"""\$\('#([A-Za-z0-9_-]+)'\)""", js)))
    missing = [u for u in used if u not in id_set]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    # 按钮：有 id 的 button 必须在 JS 里出现过（被绑过）
    btn_ids = re.findall(r'<button[^>]*id="([^"]+)"', t)
    unbound = [b for b in btn_ids if ("'#%s'" % b) not in js]

    print("页面：%s（%d B）" % (page.name, len(t.encode("utf-8"))))
    print("  <script> 块数        : %d" % len(js_blocks))
    print("  HTML id 数           : %d" % len(id_set))
    print("  JS 引用的 $(\"#id\") 数 : %d" % len(used))
    print("  重复 id              : %s" % (dup or "（无）"))
    print("  缺失的 id            : %s" % (missing or "（无）"))
    print("  有 id 但未绑定的按钮 : %s" % (unbound or "（无）"))
    print("  必备声明             : %s" % ("齐全" if all(m in t for m in MUST_HAVE)
                                            else [m for m in MUST_HAVE if m not in t]))
    bad = [b for b in FORBIDDEN if b in t]
    print("  禁止措辞             : %s" % (bad or "（无）"))
    ok = not missing and not dup and not unbound and all(m in t for m in MUST_HAVE) and not bad
    print("判定：%s" % ("**通过**" if ok else "**不通过**（上面已列出问题）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
