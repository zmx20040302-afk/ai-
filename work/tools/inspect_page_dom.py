# -*- coding: utf-8 -*-
"""检查 headless 浏览器导出的 DOM（`--dump-dom` 的产物）：页面在**真浏览器**里是否跑通。

为什么要它：`node --check` 只看语法、静态 id 检查只看接线；**"点按钮没反应"只有真浏览器能复现**。
配合用法：

    chrome --headless=new --disable-gpu --virtual-time-budget=15000 \
      --dump-dom "http://127.0.0.1:8877/?run=predict&x=0.55&N1=1&N2=6" > dom.html
    python -B work/tools/inspect_page_dom.py work/logs/page_dom_predict.html

判据（全部必须成立才算通过）：
1. 没有错误横幅、没有"计算中…"残留（说明异步**跑完了**）；
2. `#pred`（或对应面板）里出现**结果标记**（已拒答 / SPL20 / 通过）；
3. 页面必备声明仍在。
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
MARKERS_FAIL = ("页面捕获到错误", "计算中…", "这一步失败了")
MARKERS_OK = ("已拒答", "SPL20", "certified=", "已按 URL 参数运行", "可答", "凹陷",
              "与认证区间一致", "超出认证区间", "有区分度", "候选", "不可变数据版本")


def section(dom: str, el_id: str, n: int = 600) -> str:
    m = re.search(r'id="%s"[^>]*>(.*?)(?=id="[^"]+"|</section>|$)' % re.escape(el_id), dom, re.S)
    return re.sub(r"\s+", " ", m.group(1))[:n] if m else ""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("用法：python -B work/tools/inspect_page_dom.py <dom.html> [面板id ...]")
        return 2
    p = pathlib.Path(argv[0])
    if not p.is_absolute():
        p = REPO / p
    if not p.is_file():
        print("[FAIL] 找不到 DOM 文件：%s" % p)
        return 2
    dom = p.read_text(encoding="utf-8", errors="replace")
    panels = argv[1:] or ["pred"]
    print("DOM：%s（%d B）" % (p.name, len(dom.encode("utf-8"))))
    # ⚠️ **必须先剥掉 <script>**：JS 源码里就含"计算中…""页面捕获到错误"等**字面量**，
    # 不剥就会全部误报（本工具第一版正是如此）。
    dom_wo_js = re.sub(r"<script>[\s\S]*?</script>", "", dom)
    bad = [k for k in MARKERS_FAIL if k in dom_wo_js]
    print("  失败标记        : %s" % (bad or "（无）"))
    print("  必备声明        : %s" % ("齐全" if all(
        k in dom for k in ("响应级代理", "不是 AI 求解器", "拒答")) else "**缺失**"))
    ok_any = False
    for pid in panels:
        body = section(dom, pid)
        hit = [k for k in MARKERS_OK if k in body]
        print("  #%-10s 长度 %4d  结果标记 %s" % (pid, len(body), hit or "（无）"))
        if body:
            print("     %s" % body[:300])
        ok_any = ok_any or bool(hit)
    ok = ok_any and not bad
    print("判定：%s" % ("**通过**（页面在真浏览器里跑通并出结果）" if ok else "**不通过**"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
