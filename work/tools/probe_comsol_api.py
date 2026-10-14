"""离线探测 COMSOL Java API 的真实类名/方法名（不启动 COMSOL，不需要许可证）。

原理：class 文件的常量池以 UTF-8 明文存放方法名与类名，直接扫 jar 即可作为**证据**，
避免凭记忆猜 API（红线 3：不猜测）。

用法：
    python work\\tools\\probe_comsol_api.py classes <jar> <子串>
    python work\\tools\\probe_comsol_api.py strings <jar> <classEntry> <子串>
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

ASCII = re.compile(rb"[ -~]{4,}")


def classes(jar: Path, needle: str) -> int:
    with zipfile.ZipFile(jar) as z:
        hits = [n for n in z.namelist() if n.endswith(".class") and needle.lower() in n.lower()]
    print(f"{jar.name}: 匹配 {len(hits)} 个 class")
    for h in sorted(hits)[:60]:
        print("   ", h)
    return 0


def strings(jar: Path, entry: str, needle: str) -> int:
    with zipfile.ZipFile(jar) as z:
        names = [n for n in z.namelist() if n.endswith(".class") and entry.lower() in n.lower()]
        if not names:
            print(f"未找到包含 {entry!r} 的 class")
            return 1
        for n in names[:6]:
            data = z.read(n)
            found = sorted({m.decode("ascii") for m in ASCII.findall(data)
                            if needle == "-" or needle.lower() in m.decode("ascii", "ignore").lower()})
            print(f"\n== {n} ==")
            for f in found[:120]:
                print("   ", f)
    return 0


def scan(jar: Path, needle: str) -> int:
    """全 jar 扫描：找出哪些 class 含指定字符串（用于定位"谁声明了这个方法"）。"""
    with zipfile.ZipFile(jar) as z:
        hits = []
        for n in z.namelist():
            if not n.endswith(".class"):
                continue
            try:
                strs = {m.decode("ascii", "ignore") for m in ASCII.findall(z.read(n))}
            except Exception:
                continue
            matched = sorted(s for s in strs if needle.lower() in s.lower())
            if matched:
                hits.append((n, matched[:6]))
    print(f"{jar.name}: {len(hits)} 个 class 含 {needle!r}")
    for n, s in hits[:40]:
        print(f"  {n}")
        for x in s:
            print(f"       {x}")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    mode, jar, a = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    if mode == "classes":
        return classes(jar, a)
    if mode == "strings":
        return strings(jar, a, sys.argv[4] if len(sys.argv) > 4 else "get")
    if mode == "scan":
        return scan(jar, a)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
