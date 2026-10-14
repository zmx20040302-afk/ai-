# -*- coding: utf-8 -*-
"""入库前审计：`work/tools` 与 `work/dist` 是否适合进版本库。

检查：危险文件类型、凭据类、身份/绝对路径暴露面、体积异常件、目录构成。
"""
from __future__ import annotations

import collections
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
TARGETS = {"work/tools": R / "work/tools", "work/dist": R / "work/dist"}

DANGER = [("模型", re.compile(r"\.mph$")), ("字节码", re.compile(r"\.pyc$|__pycache__")),
          ("私钥", re.compile(r"id_(rsa|ed25519)|\.pem$|\.key$")),
          ("会话流水", re.compile(r"session\.jsonl$")),
          ("bundle", re.compile(r"\.bundle$")), ("大二进制", re.compile(r"\.(zip|7z|tar|gz|exe|dll|so)$"))]
CRED = [("私钥正文", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
        ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_")),
        ("AWS key", re.compile(r"AKIA[0-9A-Z]{16}")),
        ("密钥赋值", re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|password)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"))]
IDENT = [("用户名", re.compile(r"\bzmx\b|zhangmx", re.I)),
         ("Windows 绝对路径", re.compile(r"[A-Za-z]:\\")),
         ("内网主机", re.compile(r"10\.180\.7\.46|node0\d")),
         ("仓库绝对路径", re.compile(r"[A-Za-z]:\\[^\s\"']*memsharness"))]

for name, root in TARGETS.items():
    if not root.is_dir():
        print("== %s：不存在" % name)
        continue
    files = [p for p in root.rglob("*") if p.is_file()]
    tot = sum(p.stat().st_size for p in files)
    print("\n== %s：%d 文件 / %.2f MB" % (name, len(files), tot / 1e6))
    danger = [(p.relative_to(R).as_posix(), why) for p in files for why, rx in DANGER if rx.search(p.as_posix())]
    print("   危险文件 %d：" % len(danger))
    for f, why in danger[:10]:
        print("      %-70s %s" % (f, why))
    big = sorted((p for p in files if p.stat().st_size > 2_000_000), key=lambda p: -p.stat().st_size)[:5]
    if big:
        print("   大于 2 MB 的件：")
        for p in big:
            print("      %-70s %.2f MB" % (p.relative_to(R).as_posix(), p.stat().st_size / 1e6))
    top = collections.Counter(p.relative_to(root).parts[0] for p in files)
    print("   顶层构成：", dict(top.most_common(8)))

    cred, ident, ident_files = [], collections.Counter(), 0
    for p in files:
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for why, rx in CRED:
            if rx.search(t):
                cred.append((p.relative_to(R).as_posix(), why))
        hit = False
        for why, rx in IDENT:
            if rx.search(t):
                ident[why] += 1
                hit = True
        ident_files += int(hit)
    print("   凭据类：%s" % (cred if cred else "无"))
    print("   身份/路径暴露面：%d 个文件含；%s" % (ident_files, dict(ident)))
