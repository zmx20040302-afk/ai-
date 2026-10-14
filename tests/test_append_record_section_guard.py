# -*- coding: utf-8 -*-
"""`scripts/append_record_section.py` 重复守卫的**行首精确匹配**自测。

### 背景（§109 登记的真实缺陷）

旧守卫用子串判定 `if heading in txt` ⇒ 目标索引正文/子节里只要出现 `### 90.1`
（或任何含 `## 90.` 字样的行），`--heading "## 90."` 就被判「已存在」而 **假拒绝**。
方向偏安全，但会让人**误以为已记录、从而漏记一节** ⇒ 本轮改为按行首精确匹配。

### 锁住的判定规则

只有一行**以 heading 开头**且 heading 之后紧跟**行尾或空白**才算命中：

* ① 正文含 `### 90.1`（无 `## 90.`） ⇒ **允许追加**（原缺陷回归）；
* ② 已存在真正的 `## 90.` 标题行 ⇒ **拒收**；
* ③ `## 900.` 存在不得让 `## 90.` 被拒（前缀更长 ≠ 同节）；
* ④ 正文提到 `§90.` ⇒ **不得拒收**（不在行首）；
* ⑤ 带尾随空白的标题行 `## 90.  ` ⇒ **仍算命中**（真标题行 + 尾随空白）。

其余守卫（非空、必须 `## ` 开头、字符数只增、回读校验、备份）**未改**；
本文件只覆盖重复守卫这一处修复。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/append_record_section.py"

_spec = importlib.util.spec_from_file_location("_append_record_section_under_test", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ---------------------------------------------------------------- 判定规则（纯函数）
@pytest.mark.parametrize("txt,heading,expected", [
    # ① 正文/子节里的更深标题不算命中（原缺陷回归）
    ("### 90.1 子节\n", "## 90.", False),
    ("## 90.1 真子节\n", "## 90.", False),
    ("正文里提到 ### 90.1 但无本节标题\n", "## 90.", False),
    # ② 真正的标题行算命中
    ("## 90. 标题\n", "## 90.", True),
    ("## 90.\n", "## 90.", True),
    # ⑤ 尾随空白仍算命中
    ("## 90.  \n", "## 90.", True),
    ("## 90.\t尾随制表符\n", "## 90.", True),
    # ③ 更长编号不得冒充本节
    ("## 900. 别的节\n", "## 90.", False),
    ("## 900. 别的节\n", "## 90", False),
    ("## 90\n", "## 90", True),
    # ④ 正文提及 § 引用不算命中；行内出现也不算（必须在行首）
    ("见 §90. 的引用\n", "## 90.", False),
    ("x ## 90. 行内提及\n", "## 90.", False),
    # 别的节不受影响
    ("## 91. 别的节\n", "## 90.", False),
    # 空 heading 不做任何命中（防误拒）
    ("## 90. 标题\n", "   ", False),
])
def test_has_section_heading_rule(txt, heading, expected):
    assert mod._has_section_heading(txt, heading) is expected


def test_old_substring_guard_would_have_falsely_refused():
    """反证：旧口径（子串包含）在这份文本上会**假拒绝**，新口径不会。"""
    txt = "# 索引\n\n### 90.1 子节\n\n正文\n"
    assert "## 90." in txt                       # 旧守卫：命中 ⇒ 假拒绝
    assert mod._has_section_heading(txt, "## 90.") is False   # 新守卫：未命中 ⇒ 允许


# ---------------------------------------------------------------- 端到端（main）
def _run(tmp_path, monkeypatch, index_text, heading="## 90.",
         section="## 90. 测试节\n\n正文。\n"):
    """把索引与片段都放进 tmp，跑一次 main()，返回 (rc, 追加后索引全文)。"""
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    idx = tmp_path / "docs" / "INDEX-records-and-rulings.md"
    idx.write_text(index_text, encoding="utf-8")
    sec = tmp_path / "section.md"
    sec.write_text(section, encoding="utf-8")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "IDX", idx)
    monkeypatch.setattr(sys, "argv", [
        "append_record_section.py", "--section", str(sec), "--heading", heading])
    rc = mod.main()
    return rc, idx.read_text(encoding="utf-8")


def test_body_with_deeper_heading_is_appended_not_skipped(tmp_path, monkeypatch, capsys):
    """① 正文含 `### 90.1` 但无 `## 90.` ⇒ **允许追加**（原缺陷回归）。"""
    idx_text = "# 索引\n\n### 90.1 子节\n\n这一段正文提到 ## 90. 但没有该节标题。\n"
    rc, after = _run(tmp_path, monkeypatch, idx_text)
    out = capsys.readouterr().out
    assert rc == 0
    assert "[SKIP]" not in out and "[FAIL]" not in out
    assert "追加" in out
    assert after.startswith(idx_text.rstrip("\n"))          # 既有字节未被改写
    assert "\n## 90. 测试节" in after                        # 片段确实落盘


def test_existing_heading_is_still_refused(tmp_path, monkeypatch, capsys):
    """② 已存在 `## 90.` ⇒ 拒收（守卫未被放宽）。"""
    idx_text = "# 索引\n\n## 90. 旧节\n\n旧内容。\n"
    rc, after = _run(tmp_path, monkeypatch, idx_text)
    out = capsys.readouterr().out
    assert rc == 0
    assert "[SKIP]" in out
    assert after == idx_text                                 # 一字未动


def test_longer_number_does_not_refuse(tmp_path, monkeypatch, capsys):
    """③ `## 900.` 存在不得让 `## 90.` 被拒。"""
    idx_text = "# 索引\n\n## 900. 另一个节\n\n内容。\n"
    rc, after = _run(tmp_path, monkeypatch, idx_text)
    out = capsys.readouterr().out
    assert rc == 0
    assert "[SKIP]" not in out
    assert "\n## 90. 测试节" in after


def test_section_reference_in_body_does_not_refuse(tmp_path, monkeypatch, capsys):
    """④ 正文提到 `§90.` 不得拒收。"""
    idx_text = "# 索引\n\n按 §90. 的裁定执行。\n"
    rc, after = _run(tmp_path, monkeypatch, idx_text)
    out = capsys.readouterr().out
    assert rc == 0
    assert "[SKIP]" not in out
    assert "\n## 90. 测试节" in after


def test_trailing_whitespace_heading_is_a_hit(tmp_path, monkeypatch, capsys):
    """⑤ 带尾随空格的标题行 `## 90.  ` 仍应算命中 ⇒ 拒收。"""
    idx_text = "# 索引\n\n## 90.  \n\n旧内容。\n"
    rc, after = _run(tmp_path, monkeypatch, idx_text)
    out = capsys.readouterr().out
    assert rc == 0
    assert "[SKIP]" in out
    assert after == idx_text


def test_normal_append_still_works_and_readback_passes(tmp_path, monkeypatch, capsys):
    """正常路径未被修坏：空索引 + 合法片段 ⇒ 追加成功、备份落盘、rc=0。"""
    rc, after = _run(tmp_path, monkeypatch, "# 索引\n")
    out = capsys.readouterr().out
    assert rc == 0
    assert "追加" in out and "[FAIL]" not in out
    assert after.rstrip("\n").endswith("## 90. 测试节\n\n正文。")
    baks = list((tmp_path / "work/logs").glob("INDEX-records-and-rulings.*.md.bak"))
    assert len(baks) == 1                                    # 备份仍在
    assert baks[0].read_text(encoding="utf-8") == "# 索引\n"  # 备份 = 追加前全文


def test_other_guards_unchanged_empty_fragment_still_refused(tmp_path, monkeypatch, capsys):
    """其余守卫未放宽：空片段仍拒收（rc=2），索引未被改写。"""
    idx_text = "# 索引\n"
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    idx = tmp_path / "docs" / "INDEX-records-and-rulings.md"
    idx.write_text(idx_text, encoding="utf-8")
    sec = tmp_path / "empty.md"
    sec.write_text("   \n", encoding="utf-8")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "IDX", idx)
    monkeypatch.setattr(sys, "argv", [
        "append_record_section.py", "--section", str(sec), "--heading", "## 90."])
    assert mod.main() == 2
    assert "[FAIL]" in capsys.readouterr().out
    assert idx.read_text(encoding="utf-8") == idx_text
