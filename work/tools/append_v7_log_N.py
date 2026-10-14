# -*- coding: utf-8 -*-
"""把 v7 的改动说明 §N 以**纯 LF** append 到 docs/PAPER_REVISION_LOG_20261009.md。

守卫：目标文件必须纯 LF（无 CR）；旧字节必须是新文件的**前缀**；字符数只增；
备份到 work/logs/；回读复核。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG = ROOT / "docs" / "PAPER_REVISION_LOG_20261009.md"
FRAG = ROOT / "work" / "tools" / "v7_log_N.md"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    old = LOG.read_bytes()
    if b"\r" in old:
        print("FAIL 目标改动说明含 CR（预期纯 LF）")
        return 2
    frag = FRAG.read_bytes().replace(b"\r\n", b"\n")
    if b"\r" in frag:
        print("FAIL 片段含 CR")
        return 2
    if not frag.startswith(b"\n---\n"):
        print("FAIL 片段未以 '\\n---\\n' 开头")
        return 2
    if b"## N. " not in frag:
        print("FAIL 片段缺少 '## N. ' 标题")
        return 2
    if b"## N. " in old:
        print("SKIP 目标文件已存在 '## N. '，未重复追加")
        return 0
    new = old + frag
    if not new.startswith(old) or len(new) <= len(old):
        print("FAIL append-only / 字符数只增 校验不通过")
        return 2
    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    bak = ROOT / "work" / "logs" / ("PAPER_REVISION_LOG_20261009.md.%s.v7N.bak" % ts)
    bak.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LOG, bak)
    LOG.write_bytes(new)
    back = LOG.read_bytes()
    ok = back.startswith(old) and len(back) == len(new) and b"## N. " in back
    print("LOG_APPEND_%s" % ("OK" if ok else "FAIL"))
    print("before: %d B / %d LF / sha256 %s" % (len(old), old.count(b"\n"), sha(old)))
    print("after : %d B / %d LF / sha256 %s" % (len(back), back.count(b"\n"), sha(back)))
    print("delta_bytes: +%d" % (len(back) - len(old)))
    print("add_chars: +%d" % (len(back.decode("utf-8")) - len(old.decode("utf-8"))))
    print("old_bytes_is_prefix_of_new: %s" % back.startswith(old))
    print("backup: %s" % bak.relative_to(ROOT))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
