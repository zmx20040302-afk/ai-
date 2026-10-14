# -*- coding: utf-8 -*-
"""核验交接包 / 清单 / 出处说明里引用的**每个哈希与字节数**是否与磁盘相符。

为什么单独成件：本项目已多次出现"记录值取自内存字符串而非磁盘字节"导致哈希不符（INDEX §211）。
本件用**统一的解析+比对**把这类错误挡在交付前。

用法：`python verify_handoff_hashes.py`
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]      # 脚本在 work/tools/ ⇒ repo = parents[2]

DOCS = ["docs/PAPER_DAC2027_CODEX_HANDOFF_20261012.md",
        "docs/DAC2027_SUBMISSION_CHECKLIST.md",
        "docs/PAPER_DAC2027_EN_v8_PROVENANCE.md"]

#: 形如 `docs/xxx.md` | 12,345 | `abcdef0123456789`
ROW = re.compile(r"`(docs/[^`]+?)`\s*\|[^|]*?([\d,]{3,})\s*(?:→新)?\s*\|[^|]*?`([0-9a-f]{16})`")


def main() -> int:
    bad, n = [], 0
    for d in DOCS:
        p = REPO / d
        if not p.is_file():
            print("[skip] 缺文件 %s" % d)
            continue
        text = p.read_text(encoding="utf-8")
        hits = ROW.findall(text)
        print("== %s：解析出 %d 条 (文件, 字节, 哈希)" % (pathlib.Path(d).name, len(hits)))
        for f, b, hh in hits:
            fp = REPO / f
            n += 1
            if not fp.is_file():
                print("   %-56s **文件不存在**" % f)
                bad.append((d, f, "missing"))
                continue
            raw = fp.read_bytes()
            gb, gh = len(raw), hashlib.sha256(raw).hexdigest()[:16]
            ok = (f"{gb:,}" == b.strip()) if b.strip().replace(",", "").isdigit() else True
            ok = ok and gh == hh
            print("   %-56s 声称 %8s/%s  实测 %8d/%s  %s"
                  % (pathlib.Path(f).name, b.strip(), hh, gb, gh, "OK" if ok else "**不符**"))
            if not ok:
                bad.append((d, f, "%s/%s vs %d/%s" % (b.strip(), hh, gb, gh)))
    print("\n小计：核验 %d 条；**不符 %d 条**" % (n, len(bad)))
    for b in bad:
        print("  不符:", b)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
