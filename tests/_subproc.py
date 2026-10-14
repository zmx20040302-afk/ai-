# -*- coding: utf-8 -*-
"""在测试里跑「仓库内 Python 脚本」的**唯一入口**：父子两侧都用 UTF-8。

### 为什么必须有它（2026-09-30 实测，不是推测）

本机是中文 Windows：`locale.getpreferredencoding(False) == cp936`。子进程往 **pipe**
写时按 cp936 编码，而多个测试用 `encoding="utf-8"` 解码 ⇒ 中文全变成 `\\ufffd`。
实测后果：`tests/test_freeze_and_amend.py` **11 个用例假失败**——断言要找的中文
（如「禁止覆盖」）确实被打印了，但落在乱码里 ⇒ 报告成「脚本拒绝行为不对」，
而脚本行为**完全正确**（同一份字节用 gbk 解就完整可读）。

`⇒`（U+21D2）更极端：**cp936 根本编不出来**（`UnicodeEncodeError`）；因为
`sys.stderr` 的默认错误处理器是 `backslashreplace`，它被静默转义成字面量 `\\u21d2`
而不是报错 —— 于是"编码问题"看起来像"脚本改了措辞"。

### 修法

`PYTHONUTF8=1`（等价于 `-X utf8`）让子进程进入 UTF-8 模式，与父进程的 utf-8 解码对齐；
`PYTHONIOENCODING=utf-8` 再兜一层。**不许只改一边**：
`scripts/webapp_server.py` 现在用的是 `text=True`（= cp936）配同 locale 的子进程，
两边一致所以中文正常；若哪天给那边也强推 UTF-8，**必须同时改它的解码**，否则控制台日志会变乱码。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: 父进程必须用这个解码键子进程的输出（与 `child_env()` 配对）。
TEXT_KW = dict(text=True, encoding="utf-8", errors="replace")


def child_env(**over: object) -> dict:
    """子进程环境：强制 UTF-8 模式 + 显式 stdio 编码。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    for k, v in over.items():
        env[k] = str(v)
    return env


def run_py(script, *args, cwd=None, timeout=300, **env_over) -> subprocess.CompletedProcess:
    """跑一个仓库内 Python 脚本，父子两侧**都**是 UTF-8。"""
    return subprocess.run(
        [sys.executable, "-B", str(script), *[str(a) for a in args]],
        capture_output=True, cwd=str(cwd or REPO), env=child_env(**env_over),
        timeout=timeout, **TEXT_KW)


def out_of(r: subprocess.CompletedProcess) -> str:
    """stdout + stderr 合并（断言中文消息时用；顺序与进程写出顺序无关）。"""
    return (r.stdout or "") + (r.stderr or "")
