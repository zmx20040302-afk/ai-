# -*- coding: utf-8 -*-
"""跨来源自愈验证：**页面从别的端口打开时，能否自动回落到 8877 的 API**。

为什么需要它（2026-09-29 用户实际故障）：用户看到的组合是
「两个模式按钮都点不动 + 无法预测 + 出现"页面捕获到错误"横幅」。
该组合精确对应：**页面不是从 8877 打开的**（被别的本地端口/界面内嵌），
于是相对路径 `/api/...` 打到了错的服务器、返回非 JSON ⇒ 模式探测拿不到 `mode`
⇒ 旧代码把两个按钮**同时 disable**。

本脚本复刻该情形：在**另一个端口**（默认 8898）用 `http.server` 提供
`scripts/webapp_page.html`，再用 headless Chrome 打开它，然后检查：
* `#pStat` 是否变成「服务在线（经 http://127.0.0.1:8877）」⇒ 回落成功；
* 预测是否仍能出结果（`SPL20` / `certified=`）；
* 是否**没有**出现"连不上本平台的本地服务"横幅。

用法：
    python -B work/tools/cross_origin_check.py [--static-port 8898] [--chrome <path>]
"""
from __future__ import annotations

import argparse
import functools
import http.server
import pathlib
import re
import socketserver
import subprocess
import sys
import threading

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
LOGS = REPO / "work" / "logs"
CHROME_DEFAULT = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def start_static(port: int):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SCRIPTS))
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    httpd.allow_reuse_address = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def dump_dom(chrome: str, url: str, out: pathlib.Path, budget: int = 25000) -> str:
    p = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                        "--virtual-time-budget=%d" % budget, "--dump-dom", url],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=120)
    out.write_text(p.stdout or "", encoding="utf-8")
    return p.stdout or ""


def check(dom: str, label: str) -> list[tuple[str, bool, str]]:
    res: list[tuple[str, bool, str]] = []
    no_js = re.sub(r"<script>[\s\S]*?</script>", "", dom)
    res.append(("没有「连不上」横幅", "连不上本平台的本地服务" not in no_js, ""))
    res.append(("没有错误横幅", "页面捕获到错误" not in no_js, ""))
    m = re.search(r'id="pStat"[^>]*>([^<]{0,90})', dom)
    stat = (m.group(1).strip() if m else "")
    res.append(("服务状态显示在线", "服务在线" in stat, "#pStat = %r" % stat))
    m2 = re.search(r'id="pMode"[^>]*>([^<]{0,60})', dom)
    mode = (m2.group(1).strip() if m2 else "")
    res.append(("模式已识别", ("离线" in mode or "DeepSeek" in mode), "#pMode = %r" % mode))
    res.append(("预测出结果", ("SPL20" in dom or "certified=" in dom), ""))
    res.append(("模式按钮未被双双禁用",
                "off.disabled=false; onb.disabled=false;" in dom, ""))
    print("== %s ==" % label)
    for name, ok, detail in res:
        print("  [%s] %s%s" % ("OK  " if ok else "FAIL", name, ("　" + detail) if detail else ""))
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="跨来源自愈验证（页面从别的端口打开）")
    ap.add_argument("--static-port", type=int, default=8898)
    ap.add_argument("--console-port", type=int, default=8877)
    ap.add_argument("--chrome", default=CHROME_DEFAULT)
    args = ap.parse_args(argv)
    LOGS.mkdir(parents=True, exist_ok=True)

    httpd = start_static(args.static_port)
    try:
        same = dump_dom(args.chrome,
                        "http://127.0.0.1:%d/?run=predict&x=0.55&N1=1&N2=6" % args.console_port,
                        LOGS / "dom_same.html")
        r1 = check(same, "A) 同源打开 127.0.0.1:%d" % args.console_port)
        cross = dump_dom(args.chrome,
                         "http://127.0.0.1:%d/webapp_page.html?run=predict&x=0.55&N1=1&N2=6"
                         % args.static_port,
                         LOGS / "dom_cross.html")
        r2 = check(cross, "B) 跨源打开（页面 %d / API %d）—— 用户遇到的情形"
                   % (args.static_port, args.console_port))
        # 跨源时**必须**能回落到 8877
        base_ok = ("服务在线（经 http://127.0.0.1:8877）" in cross
                   or "服务在线（经 http://localhost:8877）" in cross)
        print("  [%s] 回落到 8877 成功（#pStat 里出现「经 …:8877」）"
              % ("OK  " if base_ok else "FAIL"))
        ok = all(o for _, o, _ in r1) and all(o for _, o, _ in r2) and base_ok
        print("判定：%s" % ("**通过**（无论从哪个端口打开都能自愈）" if ok else "**不通过**"))
        return 0 if ok else 1
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    sys.exit(main())
