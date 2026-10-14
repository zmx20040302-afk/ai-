# -*- coding: utf-8 -*-
"""把一段 markdown 小节按 append-only 追加到记录索引。

用法：
  python scripts/append_record_section.py --section <片段文件> --heading "## 90."

守卫（fail-closed；**能在写前判定的全部前置**，见下）：
* 片段必须**非空**、必须以 `## ` 开头的标题行；
* 片段**首行**必须与 `--heading` 对应（`_has_section_heading` 的同一条行首匹配规则）。
  这个形态**以前**是「先写盘、再回读失败」：rc=2 但索引已经被改、备份也已生成
  ⇒「失败」不等于「什么都没发生」（`INDEX §116` 与 `§130.3` 登记的就是这类账）；
* 目标索引里**已存在同一标题前缀**时拒绝追加（防重复记录）——判定按**行首精确匹配**
  （见 `_has_section_heading`：只有整行以 heading 开头、且其后是行尾或空白才算命中）；
* **字符数会只增**（`len(new) > len(txt)`）——**前置到备份与写盘之前**判定；
* 追加前把索引备份到 `work/logs/`（文件名带时间戳）；
* 追加后回读校验；**回读校验失败（或写盘抛错）必须可回滚**：
  从**本轮刚写的** `.bak` 把索引恢复回写前字节，并**显式打印**
  「已回滚 / **未回滚** ＋ `.bak` 路径」——**不得只报 rc=2 就结束**。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
IDX = REPO / "docs/INDEX-records-and-rulings.md"


def _has_section_heading(txt: str, heading: str) -> bool:
    """索引里是否**已存在该节标题行**（按行首精确匹配，非子串包含）。

    原实现用 `heading in txt` ⇒ `## 90.` 会被正文/子节里的 `### 90.1` 命中，
    造成**假拒绝**（偏安全方向，但会让人误以为已记录、从而漏记一节）。

    只有满足「整行以 heading 开头，且 heading 之后紧跟行尾或空白」才算命中：
    * `### 90.1` 不以 `## 90.` 开头 ⇒ **不算**；
    * `## 900.` 与 `## 90.` 在 heading 末尾的 `.` 处不同（或其后是 `0`） ⇒ **不算**；
    * 正文里提到的 `§90.` 不在行首 ⇒ **不算**；
    * `## 90.`（行尾）与 `## 90.  `（尾随空白） ⇒ **算**。

    同一个函数也用来做**片段首行与 `--heading` 是否对应**的**写前**判定（`main()`）。
    """
    h = heading.strip()
    if not h:
        return False
    for line in txt.splitlines():
        if line.startswith(h) and (len(line) == len(h) or line[len(h)].isspace()):
            return True
    return False


def _write_and_readback(path: pathlib.Path, text: str) -> str:
    """写盘 + 回读；返回**盘上真正读到**的文本。

    单独成一个函数是为了让「回读必然失败」这种注入场景可测
    （测试把本函数换成「写坏字节并返回坏文本」的替身）。

    INPLACE-ALLOW: 本函数不自己备份是**有意的**：写前备份由 `main()` 在调用它**之前**
    落盘（顺序 = 预校验 → 备份 → 本函数），本函数只是把「写 + 回读」放进一个可注入的接缝。
    """
    path.write_text(text, encoding="utf-8")
    return path.read_text(encoding="utf-8")


def _rollback(path: pathlib.Path, bak: pathlib.Path) -> dict:
    """用**本轮备份**把索引恢复回写前字节。

    返回的是**测量**结果，不是写死的状态字符串：
    `{"restored": bool, "chars": int | None, "error": str | None}`，
    其中 `restored` 由「恢复后的盘上文本 == 备份文件**现读**文本」比较得出。

    INPLACE-ALLOW: 本函数写的正是**本轮刚备份过的写前字节**（`bak` 就是那次备份），
    只做「还原」、不产生任何新内容 ⇒ 不存在「旧字节被新内容覆盖」的风险。
    """
    try:
        bak_text = bak.read_text(encoding="utf-8")
        path.write_bytes(bak.read_bytes())
        back = path.read_text(encoding="utf-8")
        return {"restored": back == bak_text, "chars": len(back), "error": None}
    except OSError as exc:
        return {"restored": False, "chars": None,
                "error": "%s: %s" % (type(exc).__name__, exc)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--section", required=True)
    ap.add_argument("--heading", required=True, help="形如 '## 90.' 的唯一前缀")
    a = ap.parse_args()
    sec_p = pathlib.Path(a.section)
    if not sec_p.is_absolute():
        sec_p = REPO / sec_p
    if not sec_p.exists():
        print("[FAIL] 片段文件不存在：%s" % sec_p)
        return 2
    sec = sec_p.read_text(encoding="utf-8")

    # ---------------- 写前预校验（一）：片段本身 ----------------
    if not sec.strip():
        print("[FAIL] 片段为空 —— 拒绝把空记录写进索引")
        return 2
    if not sec.lstrip().startswith("## "):
        print("[FAIL] 片段第一行必须是 `## ` 标题行（分隔线由本脚本插入，不要写进片段）")
        return 2
    first = next((ln for ln in sec.splitlines() if ln.strip()), "")
    if not _has_section_heading(first, a.heading):
        print("[FAIL] 片段首行与 --heading 不对应：首行 %r 不以 %r 开头"
              " ⇒ 拒绝写入（**写前**拦截，不写一个字节）"
              % (first.strip()[:60], a.heading))
        return 2

    if not sec.startswith("\n"):
        sec = "\n---\n" + sec          # 统一插入小节分隔线，避免每个片段各写各的

    txt = IDX.read_text(encoding="utf-8")
    if _has_section_heading(txt, a.heading):
        print("[SKIP] 索引里已存在 %r，未重复追加（append-only）" % a.heading)
        return 0

    # ---------------- 写前预校验（二）：索引侧、可写前判定的项 ----------------
    new = txt.rstrip("\n") + "\n" + sec
    if len(new) <= len(txt):
        print("[FAIL] 追加后字符数未增加 —— 拒绝写入（写前判定，未生成备份、未动索引）")
        return 2

    # ---------------- 备份（仍在写之前）----------------
    bk = REPO / "work/logs" / ("INDEX-records-and-rulings.%s.md.bak"
                              % _dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    bk.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(IDX, bk)

    # ---------------- 写 + 回读；失败必须回滚 ----------------
    try:
        back = _write_and_readback(IDX, new)
    except OSError as exc:
        print("[FAIL] 写盘抛错（%s: %s）⇒ 尝试回滚" % (type(exc).__name__, exc))
        rb = _rollback(IDX, bk)
        _report_rollback(rb, bk)
        return 2
    if a.heading not in back or len(back) != len(new):
        print("[FAIL] 回读校验不通过（写入不可信）：字符 %d -> %d（期望 %d）、标题在盘上 = %s"
              % (len(txt), len(back), len(new), a.heading in back))
        rb = _rollback(IDX, bk)
        _report_rollback(rb, bk)
        return 2
    print("追加 %r ｜ 字符 %d -> %d ｜ 备份 %s" % (a.heading, len(txt), len(back),
                                              bk.relative_to(REPO)))
    return 0


def _report_rollback(rb: dict, bk: pathlib.Path) -> None:
    """把回滚结果**显式**打出来（已回滚 / 未回滚 ＋ 备份路径）——不许静默。"""
    try:
        shown = bk.relative_to(REPO)
    except ValueError:
        shown = bk
    if rb["restored"]:
        print("       ⇒ 已回滚：索引已从本轮备份恢复为**写前字节**（%s，%d 字符）"
              % (shown, rb["chars"]))
    else:
        print("       ⇒ **未回滚**（%s）；写前全文在本轮备份里：%s —— 请人工核对"
              % (rb["error"], shown))


if __name__ == "__main__":
    sys.exit(main())
