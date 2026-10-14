# -*- coding: utf-8 -*-
"""看住"有没有真实 headless DSH 被意外拉起来"（跑一套命令期间持续采样）。

为什么需要它：2026-09-30 实测出现过**来源不明**的真实 headless DSH 进程
（11:48:43 一个 node `bin.js --profile headless`），而当时没有任何测试应当启动它。
与其靠事后翻进程，不如在跑测试/校验的**同时**采样，一旦出现就报出来并（可选）杀掉。

用法：
    python -B work\\tools\\watch_headless_dsh.py -- <要跑的命令...>
例：
    python -B work\\tools\\watch_headless_dsh.py -- python -m pytest -q
"""
from __future__ import annotations

import subprocess
import sys
import time

PS = ("Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
      "Where-Object { $_.CommandLine -match 'dsh\\\\lib\\\\bin\\.js\"?\\s+--profile\\s+headless' } | "
      "ForEach-Object { \"$($_.ProcessId)`t$($_.CreationDate)`t$($_.CommandLine)\" }")
# ⚠️ 判据必须要求 **`lib\\bin.js` 与 `--profile headless` 连续出现**。
# 初版用两个分开的 `-like '*bin.js*'` + `'*headless*'`，结果**匹配到了我自己那条命令**：
# 本机跑命令是 `runner.js -- powershell -Command "<命令全文>"`，命令全文里就带着这两个词
# ⇒ 我把自己吓了两次（先数出 6 个、又数出 1 个"漏网的真实 DSH"）。子串判定第 N 次骗人。


def sample() -> list[str]:
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                            "-Command", PS],
                           capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return ["SAMPLE-ERROR %s" % exc]
    return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]


def main(argv: list[str]) -> int:
    if "--" not in argv:
        print(__doc__)
        return 2
    cmd = argv[argv.index("--") + 1:]
    if not cmd:
        print("[FAIL] `--` 后面要给命令")
        return 2
    print("监视真实 headless DSH … 命令：%s" % " ".join(cmd), flush=True)
    before = {s.split("\t")[0] for s in sample()}
    print("  跑之前已在跑的：%s" % (sorted(before) or "（无）"), flush=True)
    proc = subprocess.Popen(cmd)
    seen: dict[str, str] = {}
    while proc.poll() is None:
        for s in sample():
            pid = s.split("\t")[0]
            if pid not in before and pid not in seen:
                seen[pid] = s
                print("  ⚠️ 新出现真实 headless DSH：PID %s" % pid, flush=True)
                print("     %s" % s[:300], flush=True)
        time.sleep(1.5)
    rc = proc.returncode
    time.sleep(1.0)
    for s in sample():
        pid = s.split("\t")[0]
        if pid not in before and pid not in seen:
            seen[pid] = s
            print("  ⚠️ 收尾时发现真实 headless DSH：PID %s" % pid, flush=True)
            print("     %s" % s[:300], flush=True)
    print("命令退出码=%s；期间新出现的真实 headless 进程数=%d" % (rc, len(seen)), flush=True)
    if seen:
        print("判定：**有真实 headless DSH 被启动**（下面这些要么是设计内的，要么是缺陷）")
        for s in seen.values():
            print("  - %s" % s[:200])
        return 1
    print("判定：**干净**（全程没有真实 headless DSH 被启动）")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
