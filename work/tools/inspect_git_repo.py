# -*- coding: utf-8 -*-
"""只读解析 `.git`：列出该单提交跟踪的全部文件，并对将入库内容做身份/密钥扫描。

不需要 git 二进制：直接按 git 对象格式解压 commit → tree → blob 元数据。
"""
from __future__ import annotations

import pathlib
import re
import sys
import zlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
GIT = REPO / ".git"
HEAD = "e31ccc7e1cc5abdcc167cc691d3cdf5b276aeee0"


def read_obj(sha: str):
    p = GIT / "objects" / sha[:2] / sha[2:]
    if not p.is_file():
        # 可能在 pack 里
        return None, None
    raw = zlib.decompress(p.read_bytes())
    i = raw.index(b"\x00")
    hdr = raw[:i].decode()
    kind, size = hdr.split(" ")
    return kind, raw[i + 1:]


def walk(sha: str, prefix: str, out: list):
    kind, body = read_obj(sha)
    if kind is None:
        out.append((prefix, "<in-pack>", None))
        return
    if kind == "tree":
        j = 0
        while j < len(body):
            k = body.index(b"\x00", j)
            mode_name = body[j:k].decode("utf-8", "replace")
            mode, name = mode_name.split(" ", 1)
            sub = body[k + 1:k + 21].hex()
            j = k + 21
            if mode == "40000" or mode == "040000":
                walk(sub, prefix + name + "/", out)
            else:
                k2, b2 = read_obj(sub)
                out.append((prefix + name, mode, (len(b2) if b2 is not None else None)))
    else:
        out.append((prefix, kind, len(body)))


kind, body = read_obj(HEAD)
print("HEAD 对象类型:", kind)
if kind == "commit":
    txt = body.decode("utf-8", "replace")
    print("--- commit ---")
    print(txt[:600])
    tree = re.search(r"^tree ([0-9a-f]{40})$", txt, re.M).group(1)
    files: list = []
    walk(tree, "", files)
    print("\n--- 该提交跟踪 %d 个文件 ---" % len(files))
    tot = 0
    for path, mode, size in sorted(files):
        tot += size or 0
        print("  %-58s %8s  %s" % (path, mode, size))
    print("合计约 %.1f KB" % (tot / 1024))

    print("\n--- 工作区里被跟踪文件是否还在 ---")
    miss = [p for p, _, _ in files if not (REPO / p).is_file()]
    print("缺失:", len(miss))
    for m in miss[:20]:
        print("   -", m)

    print("\n--- 身份/密钥扫描（对被跟踪文件当前内容）---")
    RISK = {
        "user": re.compile(r"\bzmx\b|zmx20040302|zhangmx", re.I),
        "host_lan": re.compile(r"10-180-7-46|node0\d"),
        "ssh_key": re.compile(r"\.ssh|id_rsa|id_ed25519|codex_ubuntu|BEGIN [A-Z ]*PRIVATE KEY"),
        "abs_path": re.compile(r"[A-Za-z]:\\"),
        "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_"),
        "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
        "api_key": re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*\S{8,}"),
    }
    hits_total = 0
    for path, _, _ in sorted(files):
        f = REPO / path
        if not f.is_file():
            continue
        try:
            t = f.read_text(encoding="utf-8-sig")
        except Exception:
            continue
        hits = {}
        for name, rx in RISK.items():
            fs = rx.findall(t)
            if fs:
                hits[name] = sorted({str(x) for x in fs})[:6]
        if hits:
            hits_total += 1
            print("  ⚠️ %s  %s" % (path, hits))
    print("有风险串的受跟踪文件数:", hits_total)
