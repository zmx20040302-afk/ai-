# -*- coding: utf-8 -*-
"""`scripts/append_record_section.py` 的**写前预校验 + 回读失败可回滚**自测（正反两侧）。

### 背景（`INDEX §130.3` / `§116` 登记的真实缺口）

旧实现把「片段首行与 `--heading` 是否一致」交给**回读**去发现：**先写盘、再回读失败**
⇒ rc=2 打印「回读校验不通过（写入不可信）」，可**索引已经被改、片段已经落盘、备份已经生成**
（实测字符数 21 → 60）⇒「失败」不等于「什么都没发生」。

本文件锁住两条修好的性质：

1. **能写前判定的项全部前置**（片段非空 / 首行 `## ` / 首行与 heading 对应 / 字符数只增）
   ⇒ 被拦下的场景**索引字节一个都不变、连备份都不产生**；
2. **回读失败（或写盘抛错）必须可回滚**：从**本轮刚写的** `.bak` 恢复，
   并**显式**打印「已回滚 / 未回滚 ＋ `.bak` 路径」。

其余守卫（重复标题拒收 / 空片段拒收 / 正常追加 / 备份命名）由
`tests/test_append_record_section_guard.py` 的既有 6 例覆盖，本文件不动它们。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/append_record_section.py"

_spec = importlib.util.spec_from_file_location("_append_record_section_rollback_ut", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

IDX_NAME = "INDEX-records-and-rulings.md"


def _setup(tmp_path, index_text):
    """建一个 tmp 仓库（docs/ 索引 + 片段），返回 (index_path, section_path)。"""
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    idx = tmp_path / "docs" / IDX_NAME
    idx.write_text(index_text, encoding="utf-8")
    return idx


def _run(monkeypatch, tmp_path, idx, section_text, heading="## 90."):
    sec = tmp_path / "section.md"
    sec.write_text(section_text, encoding="utf-8")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "IDX", idx)
    monkeypatch.setattr(sys, "argv", [
        "append_record_section.py", "--section", str(sec), "--heading", heading])
    return mod.main()


def _baks(tmp_path):
    d = tmp_path / "work" / "logs"
    return sorted(d.glob("*.bak")) if d.is_dir() else []


# ============================================================ ① 写前预校验 ⇒ 索引字节不变
def test_heading_mismatch_is_refused_before_any_write(tmp_path, monkeypatch, capsys):
    """**反侧**：片段首行 `## 113.`、`--heading "## 13."` ⇒ 写前拦住。

    断言三件事：rc=2、**索引字节逐字节不变**、**连备份都不产生**（说明确实在备份之前）。
    """
    idx_text = "# 索引\n\n## 12. 旧节\n\n正文。\n"
    idx = _setup(tmp_path, idx_text)
    before = idx.read_bytes()
    rc = _run(monkeypatch, tmp_path, idx, "## 113. 别的节\n\n正文。\n", heading="## 13.")
    out = capsys.readouterr().out
    assert rc == 2
    assert "写前" in out and "[FAIL]" in out
    assert idx.read_bytes() == before, "被拦下的场景不得改动索引一个字节"
    assert _baks(tmp_path) == [], "既然写前就拦下了，就不该产生备份"


def test_exact_number_boundary_is_refused_before_write(tmp_path, monkeypatch, capsys):
    """**反侧（边界）**：`## 9.` 不得被片段首行 `## 90. xxx` 冒充 ⇒ 写前拦住、字节不变。"""
    idx_text = "# 索引\n\n## 8. 旧节\n"
    idx = _setup(tmp_path, idx_text)
    before = idx.read_bytes()
    rc = _run(monkeypatch, tmp_path, idx, "## 90. 别的节\n\n正文。\n", heading="## 9.")
    out = capsys.readouterr().out
    assert rc == 2 and "写前" in out
    assert idx.read_bytes() == before
    assert _baks(tmp_path) == []


def test_char_count_not_increasing_is_refused_before_write(tmp_path, monkeypatch, capsys):
    """**反侧**：尾部空白极多的索引上，「字符数只增」不成立 ⇒ 写前拒写。

    `txt = "x" + "\\n"*200`（201 字符），片段很短 ⇒ `len(new) <= len(txt)`。
    这条判定**以前在备份之后**，现在前置：既不写盘，也不产生备份。
    """
    idx = _setup(tmp_path, "x" + "\n" * 200)
    before = idx.read_bytes()
    rc = _run(monkeypatch, tmp_path, idx, "## 9. y\n", heading="## 9.")
    out = capsys.readouterr().out
    assert rc == 2 and "字符数未增加" in out
    assert idx.read_bytes() == before
    assert _baks(tmp_path) == []


# ============================================================ ② 回读失败 ⇒ 必须回滚
def test_readback_failure_rolls_back_to_pre_write_bytes(tmp_path, monkeypatch, capsys):
    """**反侧（注入）**：回读必然失败 ⇒ 断言**回滚到写前字节**，且输出里点明 `.bak`。

    「注入」= 把 `_write_and_readback` 换成「写坏字节并返回坏文本」的替身。
    同时做**可失败性**核对：替身**确实**把索引写坏了（`calls[0] != 原文`）——
    否则这个用例什么都没证明。
    """
    idx_text = "# 索引\n\n## 12. 旧节\n\n正文。\n"
    idx = _setup(tmp_path, idx_text)
    before = idx.read_bytes()
    calls: list[str] = []

    def _poisoned(path, text):
        bad = text[:-7]                       # 丢掉尾巴 ⇒ 回读必然与 new 不等
        calls.append(bad)
        path.write_text(bad, encoding="utf-8")
        return path.read_text(encoding="utf-8")

    monkeypatch.setattr(mod, "_write_and_readback", _poisoned)
    rc = _run(monkeypatch, tmp_path, idx, "## 90. 新节\n\n正文。\n")
    out = capsys.readouterr().out

    assert rc == 2
    assert calls and calls[0] != idx_text, "替身没写坏索引 ⇒ 本用例不构成投毒"
    assert idx.read_bytes() == before, "回读失败必须回滚到写前字节"
    assert "已回滚" in out and "未回滚" not in out
    baks = _baks(tmp_path)
    assert len(baks) == 1, "本轮备份应当恰好一个"
    assert baks[0].read_bytes() == before, "备份 == 写前字节"
    assert baks[0].name in out, "输出里必须给出 .bak 路径"


def test_readback_failure_reports_not_rolled_back_with_bak_path(tmp_path, monkeypatch,
                                                                capsys):
    """**反侧（回滚也失败）**：输出必须**明确声明未回滚**并给出 `.bak` 路径（不许只报 rc=2）。"""
    idx_text = "# 索引\n\n## 12. 旧节\n"
    idx = _setup(tmp_path, idx_text)

    def _poisoned(path, text):
        path.write_text("坏字节", encoding="utf-8")
        return "坏字节"

    monkeypatch.setattr(mod, "_write_and_readback", _poisoned)
    monkeypatch.setattr(mod, "_rollback",
                        lambda path, bak: {"restored": False, "chars": None,
                                           "error": "PermissionError: 模拟回滚失败"})
    rc = _run(monkeypatch, tmp_path, idx, "## 90. 新节\n\n正文。\n")
    out = capsys.readouterr().out
    assert rc == 2
    assert "未回滚" in out and "模拟回滚失败" in out
    baks = _baks(tmp_path)
    assert len(baks) == 1 and baks[0].name in out, "未回滚时必须给出 .bak 路径"
    assert baks[0].read_text(encoding="utf-8") == idx_text


def test_write_error_also_rolls_back(tmp_path, monkeypatch, capsys):
    """**反侧（写盘抛错）**：`OSError` 也必须走回滚路径，不能留下半截写入。"""
    idx_text = "# 索引\n\n## 12. 旧节\n"
    idx = _setup(tmp_path, idx_text)
    before = idx.read_bytes()

    def _boom(path, text):
        path.write_text(text[:-3], encoding="utf-8")       # 半截写入
        raise OSError("模拟磁盘错误")

    monkeypatch.setattr(mod, "_write_and_readback", _boom)
    rc = _run(monkeypatch, tmp_path, idx, "## 90. 新节\n\n正文。\n")
    out = capsys.readouterr().out
    assert rc == 2
    assert "写盘抛错" in out and "已回滚" in out
    assert idx.read_bytes() == before


# ============================================================ ③ 正常路径仍成功
def test_normal_append_still_works_with_prechecks(tmp_path, monkeypatch, capsys):
    """**正侧**：合法片段 + 匹配 heading ⇒ rc=0、索引只增、备份 == 写前字节。"""
    idx_text = "# 索引\n\n## 12. 旧节\n\n正文。\n"
    idx = _setup(tmp_path, idx_text)
    before = idx.read_bytes()
    rc = _run(monkeypatch, tmp_path, idx, "## 90. 新节\n\n正文。\n")
    out = capsys.readouterr().out
    after = idx.read_bytes()
    assert rc == 0 and "追加 '## 90.'" in out and "[FAIL]" not in out
    assert after.startswith(before), "append-only：旧字节必须是新文件的前缀"
    assert "## 90. 新节".encode("utf-8") in after
    baks = _baks(tmp_path)
    assert len(baks) == 1 and baks[0].read_bytes() == before


# ============================================================ ④ 包装脚本仍正常（缺口 3 第 5 条）
def test_locked_wrapper_still_works_and_rechecks(tmp_path):
    """`scripts/append_record_locked.py` 的锁 / max+1 / 三项复核在改动后仍正常。"""
    sys.path.insert(0, str(REPO / "src"))
    from memsharness import guards_indexlock as g

    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    idx = tmp_path / "docs" / IDX_NAME
    idx.write_text("## 12. 旧节\n\n正文。\n", encoding="utf-8")
    sec = tmp_path / "s.md"
    sec.write_text("## 13. 新节\n\n正文。\n", encoding="utf-8")
    lp = g.default_lock_path(tmp_path, idx.name)
    before = idx.read_text(encoding="utf-8")

    res = g.locked_append(idx, sec, repo=tmp_path, lock_path=lp)
    assert res["status"] == "appended" and res["ok"] is True, res
    assert res["heading"] == "## 13."
    assert idx.read_text(encoding="utf-8").startswith(before)
    assert not lp.exists(), "用完必须释放锁"


def test_locked_wrapper_passes_prefix_number_to_appender_which_now_refuses(tmp_path):
    """**边界核对**：显式 `--heading "## 9"` + 片段首行 `## 90.`。

    包装脚本自己的写前判定用的是 `startswith`（`"## 9"` 是 `"## 90. 别的节"` 的前缀 ⇒ 放过），
    于是调用原追加器；**改动后**原追加器按行首边界规则（heading 之后必须是行尾或空白）
    **写前**拒收 ⇒ 包装脚本报「追加器 rc=2；索引未被改动」，索引仍一字不动
    （这一形态在改动前正是「先写盘、再回读失败」）。
    """
    sys.path.insert(0, str(REPO / "src"))
    from memsharness import guards_indexlock as g

    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    idx = tmp_path / "docs" / IDX_NAME
    idx.write_text("## 8. 旧节\n\n正文。\n", encoding="utf-8")
    sec = tmp_path / "s.md"
    sec.write_text("## 90. 别的节\n\n正文。\n", encoding="utf-8")
    before = idx.read_bytes()

    res = g.locked_append(idx, sec, heading="## 9", repo=tmp_path)
    assert res["status"] == "failed", res
    assert res["appender_rc"] == 2
    assert "索引未被改动" in res["message"], res["message"]
    assert "写前" in res["appender_stdout"], res["appender_stdout"]
    assert idx.read_bytes() == before
