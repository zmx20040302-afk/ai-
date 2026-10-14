# -*- coding: utf-8 -*-
"""扫描**将要入库**的工作区内容（排除 work/ 与 .git/）：只看凭据类硬风险 + 身份/基础设施暴露面。

私有库也**不应**放凭据；身份/内网信息则只报告、由人决定（用户已裁定论文与内部记录入库）。
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]

CRED = {
    "私钥正文": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"),
    "AWS key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "通用密钥赋值": re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|password|passwd)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    "SSH 私钥路径": re.compile(r"\.ssh[/\\](id_[a-z0-9]+|codex_[A-Za-z0-9_\-]+)\b"),
    "known_hosts 内容": re.compile(r"ssh-(ed25519|rsa) AAAA[A-Za-z0-9+/]{40,}"),
}
IDENT = {
    "内网主机/IP": re.compile(r"10\.180\.7\.46|ubuntu-10-180-7-46|\bnode0\d\b"),
    "用户名": re.compile(r"\bzmx\b|zmx20040302|zhangmx", re.I),
    "Windows 绝对路径": re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9_.\-]+"),
    "邮箱": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "仓库绝对路径": re.compile(r"[A-Za-z]:\\[^\s\"']*memsharness"),
}

files = [p for p in REPO.rglob("*") if p.is_file()
         and "work" not in p.relative_to(REPO).parts[:1]
         and ".git" not in p.relative_to(REPO).parts[:1]
         and p.name not in ("session.jsonl", "memsharness-history.bundle")]
print("扫描 %d 个待入库文件（已排除 work/、.git/、session.jsonl、bundle）\n" % len(files))

cred_hits, ident_hits = [], {}
for p in files:
    try:
        t = p.read_text(encoding="utf-8-sig")
    except Exception:
        try:
            t = p.read_bytes().decode("utf-8", "ignore")
        except Exception:
            continue
    rel = p.relative_to(REPO).as_posix()
    for name, rx in CRED.items():
        m = rx.findall(t)
        if m:
            cred_hits.append((rel, name, len(m)))
    for name, rx in IDENT.items():
        m = rx.findall(t)
        if m:
            ident_hits.setdefault(name, []).append((rel, len(m)))

print("=== 凭据类（必须为空）===")
if not cred_hits:
    print("  无")
for rel, name, n in cred_hits:
    print("  ⚠️ %-56s %s × %d" % (rel, name, n))

print("\n=== 身份/基础设施暴露面（只报告，已裁定可入私有库）===")
for name in IDENT:
    lst = ident_hits.get(name) or []
    print("  %-14s 命中 %d 个文件" % (name, len(lst)))
    for rel, n in sorted(lst, key=lambda x: -x[1])[:6]:
        print("        %-58s × %d" % (rel, n))
