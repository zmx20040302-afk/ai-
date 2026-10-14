# -*- coding: utf-8 -*-
"""把 §P 片段**按 append-only** 追加到 `docs\\PAPER_REVISION_LOG_20261009.md`（fail-closed）。

为什么不用 `scripts\\append_record_locked.py`：那个追加器**硬绑** `docs\\INDEX-records-and-rulings.md`
（`append_record_section.py` 里 `IDX` 是常量），不能指向本文件；而本文件是**纯 LF**，
索引是**纯 CRLF**，混用会污染行尾。故本节另写一个同规格的追加器，守卫逐条对等：

1. **目标前置锚点**：字节数与 sha256 必须等于调用时给定的值（本文件在复核前实测
   `180319 B / 000855a1…`）——不符即 rc=2，**不写**；
2. 目标必须是**纯 LF**（`\\n` 计数 == 行长数、`\\r` == 0）；
3. 片段非空、**无 BOM**、**无 `\\r`**、首行以 `## P.` 开头、以 `\\n` 结尾；
4. 目标里**不得已有** `## P.` 标题行（**行首精确匹配**，非子串包含 —— 实测宽松正则
   `^#+ P[\\s.]` 会**假阳性**，不能用来判锚点是否存在）；
5. 追加前把目标备份到 `work\\logs\\`，并**回读备份字节 == 旧字节**；
6. 追加后回读三项：新字节**以旧字节为前缀**、长度 == 旧 + 片段、`## P.` 标题**恰好 1 处**；
7. 回读失败 ⇒ 从**本轮刚写的** `.bak` 回滚，并**显式打印**「已回滚 / 未回滚」与 `.bak` 路径；
   不得只报 rc=2 就结束；
8. 机读报告落 `--report`（缺省 `work\\tmp\\paper-v9-20261010\\append_section_P_report.json`）。

用法：
    work\\.venv\\Scripts\\python.exe -X utf8 work\\tools\\append_revision_log_section.py ^
        --section work\\tmp\\paper-v9-20261010\\REVISION_LOG_SECTION_P.md
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import pathlib
import shutil

REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_TARGET = REPO / "docs" / "PAPER_REVISION_LOG_20261009.md"
#: 本文件在复核开始时的实测锚点（改一行都不许写）
EXPECT_BYTES = 180319
EXPECT_SHA256 = "000855a1f90b96ca98efdbab395e0533f39983728c766dc8c06c79946de8d612"
HEADING = "## P."


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def has_heading_line(txt: str, heading: str) -> bool:
    """**行首精确匹配**：整行以 `heading` 开头，且其后紧跟行尾或空白。"""
    for ln in txt.split("\n"):
        if ln == heading or (ln.startswith(heading) and len(ln) > len(heading)
                             and ln[len(heading)].isspace()):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="append-only 追加 §P 到论文改动说明")
    ap.add_argument("--section", required=True)
    ap.add_argument("--target", default=str(DEFAULT_TARGET))
    ap.add_argument("--report", default=None)
    ap.add_argument("--heading", default=HEADING,
                    help="片段首行必须以此开头（缺省 '## P.'；更正节可传 '### P.8'）")
    ap.add_argument("--expect-bytes", type=int, default=EXPECT_BYTES)
    ap.add_argument("--expect-sha256", default=EXPECT_SHA256)
    args = ap.parse_args(argv)
    heading = args.heading

    target = pathlib.Path(args.target)
    section = pathlib.Path(args.section)
    report_path = pathlib.Path(args.report) if args.report else (
        REPO / "work" / "tmp" / "paper-v9-20261010" / "append_section_P_report.json")
    rep: dict = {"target": str(target), "section": str(section),
                 "when": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    old = target.read_bytes()
    frag = section.read_bytes()
    rep["before"] = {"bytes": len(old), "sha256": sha256(old),
                     "crlf": old.count(b"\r\n"), "cr": old.count(b"\r")}
    rep["fragment"] = {"bytes": len(frag), "sha256": sha256(frag),
                       "cr": frag.count(b"\r"), "bom": frag[:3] == b"\xef\xbb\xbf"}

    # ---- 前置守卫（全部在写盘之前）----
    problems = []
    if len(old) != args.expect_bytes or sha256(old) != args.expect_sha256:
        problems.append("目标前置锚点不符：bytes %d/%d、sha %s/%s"
                        % (len(old), args.expect_bytes, sha256(old)[:12], args.expect_sha256[:12]))
    if old.count(b"\r") != 0:
        problems.append("目标不是纯 LF（CR 计数 %d）" % old.count(b"\r"))
    if not frag:
        problems.append("片段为空")
    if frag.count(b"\r") != 0:
        problems.append("片段含 CR（%d）—— 目标为纯 LF，拒绝写" % frag.count(b"\r"))
    if frag[:3] == b"\xef\xbb\xbf":
        problems.append("片段含 BOM——拒绝写")
    if not frag.startswith(heading.encode("utf-8")):
        problems.append("片段首行不以 %r 开头" % heading)
    if not frag.endswith(b"\n"):
        problems.append("片段不以换行结尾")
    if has_heading_line(old.decode("utf-8"), heading):
        problems.append("目标已存在 %r 标题行（防重复记录）" % heading)
    rep["pre_guard_problems"] = problems
    if problems:
        rep["result"] = "REFUSED_BEFORE_WRITE"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_bytes((json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        for p in problems:
            print("[REFUSE] %s" % p)
        print("[OK] 未写任何文件（除本报告）：%s" % report_path)
        return 2

    # ---- 备份 ----
    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    bak = REPO / "work" / "logs" / ("%s.%s.bak" % (target.name, ts))
    bak.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, bak)
    bak_bytes = bak.read_bytes()
    rep["backup"] = {"path": str(bak), "bytes": len(bak_bytes), "sha256": sha256(bak_bytes),
                     "equals_old": bak_bytes == old}
    if bak_bytes != old:
        rep["result"] = "REFUSED_BACKUP_MISMATCH"
        report_path.write_bytes((json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        print("[REFUSE] 备份字节 != 旧字节 ⇒ 未写目标")
        return 2

    # ---- 写入（字节级追加）----
    try:
        with open(target, "ab") as fh:
            fh.write(frag)
    except OSError as exc:
        rep["result"] = "WRITE_RAISED"
        rep["error"] = repr(exc)
        report_path.write_bytes((json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        print("[FAIL] 写盘抛错：%r" % exc)
        return 2

    # ---- 回读复核 ----
    new = target.read_bytes()
    txt = new.decode("utf-8")
    hb = heading.encode("utf-8")
    checks = {
        "prefix_append_only": new.startswith(old),
        "length_increased_by_fragment": len(new) == len(old) + len(frag),
        "heading_present_once": len([ln for ln in txt.split("\n")
                                     if ln == heading or (ln.startswith(heading)
                                                          and ln[len(heading):len(heading) + 1].isspace())]) == 1,
        "pure_lf_after": new.count(b"\r") == 0,
        "old_length_strictly_less": len(new) > len(old),
    }
    rep["after"] = {"bytes": len(new), "sha256": sha256(new),
                    "checks": checks, "all_ok": all(checks.values())}
    if not all(checks.values()):
        rolled = False
        try:
            shutil.copy2(bak, target)
            rolled = target.read_bytes() == old
        except OSError as exc:
            rep["rollback_error"] = repr(exc)
        rep["result"] = "READBACK_FAILED_ROLLED_BACK" if rolled else "READBACK_FAILED_NOT_ROLLED_BACK"
        report_path.write_bytes((json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        print("[FAIL] 回读复核未过：%s" % checks)
        print("[%s] 备份：%s" % ("已回滚" if rolled else "**未回滚**", bak))
        return 2

    rep["result"] = "OK"
    report_path.write_bytes((json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print("追加 %r ｜ 字节 %d -> %d ｜ sha %s -> %s"
          % (heading, len(old), len(new), sha256(old)[:12], sha256(new)[:12]))
    print("备份 %s ｜ append-only(旧字节是新文件前缀) = %s ｜ 长度 = 旧 + 片段 = %s ｜ 纯 LF = %s"
          % (bak, checks["prefix_append_only"], checks["length_increased_by_fragment"],
             checks["pure_lf_after"]))
    print("[OK] 报告：%s" % report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
