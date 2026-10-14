# -*- coding: utf-8 -*-
"""`src/memsharness/guards_inplace.py` 的自测（正反两侧 ＋ **投毒**）。

### 缺口（`INDEX §109` / `§130.3` 登记的真实损失）

就地改既有文件**事前没有备份** ⇒ 旧字节不可恢复：

* 前科 A：`work/runs/paper-evidence-20261009/` 被就地重生成 3 次；
* 前科 B：`docs/INJECTION_SOLVER_AUTOMATION_MERGED_20261008.md` 就地改述，旧 sha256
  `d47edaae…` 从此指向**不存在的字节**。

本文件锁住四件事：

* ① **正侧**：`backup_before_edit()` 落 `.bak`、内容**逐字节等于改前**、返回的 sha256 可复核；
* ② **反侧**：目标不存在 / 为空 / `work/logs` 不可写（**临时目录替身**）⇒ **拒绝**，
  且被拒绝时目标文件**一个字节都没变**；
* ③ **投毒**：让备份函数「**假装成功**但没写文件」⇒ 断言**被抓住**（可失败性）；
* ④ **静态清单**：`scan_inplace_writers()` 只报「读+写同一路径」且**写前没备份、也没豁免理由**
  的脚本（含顺序敏感与无理由豁免的反侧）。
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness import guards_inplace as g   # noqa: E402

FIXED_NOW = _dt.datetime(2026, 10, 9, 12, 0, 0)


def _target(tmp_path, text="原始字节\n"):
    p = tmp_path / "docs" / "既有文件.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ============================================================ ① 正侧
def test_backup_creates_dot_bak_identical_to_pre_edit_bytes(tmp_path):
    """正侧：`.bak` 落在 log_dir、命名 `<name>.<ts>.bak`、内容 == 改前、sha 可复核。"""
    p = _target(tmp_path)
    before = p.read_bytes()
    log_dir = tmp_path / "work" / "logs"

    rec = g.backup_before_edit(p, log_dir=log_dir, now=FIXED_NOW)

    assert rec.bak_path.parent == log_dir
    assert rec.bak_path.name == "既有文件.md.20261009T120000.bak"
    assert rec.bak_path.read_bytes() == before, "备份必须逐字节等于改前"
    assert rec.sha256 == g.sha256_bytes(before) == g.sha256_file(rec.bak_path)
    assert rec.src_sha256 == rec.sha256 and rec.src_path == p
    assert (rec.bytes, rec.src_bytes) == (len(before), len(before))
    assert rec.existed_before is False


def test_backup_is_idempotent_for_same_timestamp(tmp_path):
    """同一时间戳重复调用**复用**同一份备份（不增生、不覆盖别的备份）。"""
    p = _target(tmp_path)
    log_dir = tmp_path / "work" / "logs"
    a = g.backup_before_edit(p, log_dir=log_dir, now=FIXED_NOW)
    b = g.backup_before_edit(p, log_dir=log_dir, now=FIXED_NOW)
    assert a.bak_path == b.bak_path
    assert b.existed_before is True
    assert len(list(log_dir.glob("*.bak"))) == 1


def test_different_content_never_overwrites_an_existing_backup(tmp_path):
    """反侧：同名备份已存在且内容不同 ⇒ 另起 `-2` 后缀，**绝不覆盖**既有备份。"""
    p = _target(tmp_path, "第一版\n")
    log_dir = tmp_path / "work" / "logs"
    first = g.backup_before_edit(p, log_dir=log_dir, now=FIXED_NOW)
    p.write_text("第二版\n", encoding="utf-8")
    second = g.backup_before_edit(p, log_dir=log_dir, now=FIXED_NOW)
    assert second.bak_path != first.bak_path
    assert first.bak_path.read_text(encoding="utf-8") == "第一版\n"     # 旧备份未被毁
    assert second.bak_path.read_text(encoding="utf-8") == "第二版\n"


# ============================================================ ② 拒绝（fail-closed）
def test_missing_target_is_refused(tmp_path):
    with pytest.raises(g.InplaceEditRefused) as ei:
        g.backup_before_edit(tmp_path / "不存在.md", log_dir=tmp_path / "work/logs")
    assert "不存在" in str(ei.value)


@pytest.mark.parametrize("content", ["", "   \n\t\n"])
def test_empty_or_blank_target_is_refused(tmp_path, content):
    p = _target(tmp_path, content)
    with pytest.raises(g.InplaceEditRefused) as ei:
        g.backup_before_edit(p, log_dir=tmp_path / "work" / "logs")
    assert "空" in str(ei.value)
    assert p.read_text(encoding="utf-8") == content, "拒绝时目标不得被改动"


def test_directory_target_is_refused(tmp_path):
    d = tmp_path / "一个目录"
    d.mkdir()
    with pytest.raises(g.InplaceEditRefused) as ei:
        g.backup_before_edit(d, log_dir=tmp_path / "work/logs")
    assert "目录" in str(ei.value)


def test_unwritable_log_dir_stand_in_is_refused(tmp_path):
    """**反侧（临时目录替身）**：`work/logs` 位置上放一个**普通文件** ⇒ 建不出目录 ⇒ 拒绝。

    （Windows 上「把目录设成只读」并不会阻止创建文件，所以这里用「同路径是文件」
     这个替身来构造「不可写」；另一条 `_write_backup_bytes` 抛 `PermissionError` 的
     替身见下一个用例。）
    """
    p = _target(tmp_path)
    before = p.read_bytes()
    (tmp_path / "work").mkdir(parents=True, exist_ok=True)
    (tmp_path / "work" / "logs").write_text("我是一个文件，不是目录", encoding="utf-8")

    with pytest.raises(g.InplaceEditRefused) as ei:
        g.backup_before_edit(p, log_dir=tmp_path / "work" / "logs")
    assert "拒绝" in str(ei.value)
    assert p.read_bytes() == before, "被拒绝就不得继续编辑"


def test_permission_error_while_writing_backup_is_refused(tmp_path, monkeypatch):
    """**反侧**：写备份抛 `PermissionError` ⇒ 拒绝（且目标字节不变）。"""
    p = _target(tmp_path)
    before = p.read_bytes()

    def _denied(bak_path, data):
        raise PermissionError("模拟 work/logs 不可写")

    monkeypatch.setattr(g, "_write_backup_bytes", _denied)
    with pytest.raises(g.InplaceEditRefused) as ei:
        g.backup_before_edit(p, log_dir=tmp_path / "work" / "logs")
    assert "PermissionError" in str(ei.value)
    assert p.read_bytes() == before


# ============================================================ ③ 投毒：假装成功
def test_poison_backup_that_pretends_success_is_caught(tmp_path, monkeypatch):
    """**投毒**：把写备份换成「什么都不做、直接返回」⇒ 断言**被抓住**。

    这条就是「可失败性」：没有写后**独立复读复核**的话，下面这次调用会**假装成功**，
    调用方就会以为「已经备份好了」而继续就地改 ⇒ 旧字节丢失。
    """
    p = _target(tmp_path)

    def _pretend(bak_path, data):
        return None                      # 「成功」返回，**但盘上什么都没写**

    monkeypatch.setattr(g, "_write_backup_bytes", _pretend)
    with pytest.raises(g.InplaceEditRefused) as ei:
        g.backup_before_edit(p, log_dir=tmp_path / "work" / "logs")
    assert "没有落盘" in str(ei.value)
    assert not list((tmp_path / "work/logs").glob("*.bak"))


def test_poison_backup_with_wrong_content_is_caught(tmp_path, monkeypatch):
    """**投毒**：备份写成了**截断**内容 ⇒ 断言被抓住（sha/字节数不符）。"""
    p = _target(tmp_path)

    def _truncate(bak_path, data):
        bak_path.write_bytes(data[: max(1, len(data) // 2)])

    monkeypatch.setattr(g, "_write_backup_bytes", _truncate)
    with pytest.raises(g.InplaceEditRefused) as ei:
        g.backup_before_edit(p, log_dir=tmp_path / "work" / "logs")
    assert "不符" in str(ei.value)


# ============================================================ ④ 静态清单
_COMPLIANT = """\
from memsharness.guards_inplace import backup_before_edit


def edit(p):
    txt = p.read_text(encoding="utf-8")
    backup_before_edit(p)
    p.write_text(txt + "x", encoding="utf-8")
"""

_UNBACKED = """\
def edit(p):
    txt = p.read_text(encoding="utf-8")
    p.write_text(txt + "x", encoding="utf-8")
"""

_EXEMPT = """\
def edit(p):
    # INPLACE-ALLOW: 只改本 run 目录里自己刚生成的台账，不存在需要保护的既有字节
    txt = p.read_text(encoding="utf-8")
    p.write_text(txt + "x", encoding="utf-8")
"""

_EXEMPT_NO_REASON = """\
def edit(p):
    # INPLACE-ALLOW:
    txt = p.read_text(encoding="utf-8")
    p.write_text(txt + "x", encoding="utf-8")
"""

_COPY_BAK = """\
import shutil
from pathlib import Path

REPO = Path(".")


def edit(p):
    txt = p.read_text(encoding="utf-8")
    bk = REPO / "work/logs" / ("x.%s.bak" % "ts")
    shutil.copy2(p, bk)
    p.write_text(txt + "x", encoding="utf-8")
"""

_BACKUP_AFTER_WRITE = """\
from memsharness.guards_inplace import backup_before_edit


def edit(p):
    txt = p.read_text(encoding="utf-8")
    p.write_text(txt + "x", encoding="utf-8")
    backup_before_edit(p)
"""

_READ_THEN_WRITE_VIA_OPEN = """\
def edit(p):
    with p.open("r", encoding="utf-8") as f:
        txt = f.read()
    with p.open("w", encoding="utf-8") as f:
        f.write(txt)
"""

_ONLY_READ_RB = """\
from pathlib import Path


def sha(p):
    with Path(p).open("rb") as fh:
        return fh.read()
"""

_NO_OVERLAP = """\
def edit(src, dst):
    txt = src.read_text(encoding="utf-8")
    dst.write_text(txt, encoding="utf-8")
"""

_WRITE_ONLY = """\
def edit(p):
    p.write_text("x", encoding="utf-8")
"""


def _scan(tmp_path, **files):
    root = tmp_path / "scripts"
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (root / ("%s.py" % name)).write_text(text, encoding="utf-8")
    return g.scan_inplace_writers([root], repo=tmp_path)


def _verdict(findings, stem):
    got = [f for f in findings if Path(f.path).stem == stem]
    assert len(got) == 1, (stem, findings)
    return got[0]


def test_scan_flags_unbacked_inplace_editor(tmp_path):
    """**反侧**：读+写同一路径、写前无备份、无豁免 ⇒ 报 `unbacked`。"""
    f = _verdict(_scan(tmp_path, edit=_UNBACKED), "edit")
    assert f.verdict == "unbacked"
    assert f.target == "p" and f.scope == "edit"
    assert "没有**备份调用" in f.detail


def test_scan_accepts_canonical_backup_call(tmp_path):
    """**正侧**：写前调了 `backup_before_edit` ⇒ 不算未备份。"""
    f = _verdict(_scan(tmp_path, edit=_COMPLIANT), "edit")
    assert f.verdict == "backup_call"
    assert "backup_before_edit" in f.detail


def test_scan_accepts_shutil_copy_to_dot_bak(tmp_path):
    """**正侧**：写前 `shutil.copy2(p, bk)` 且 `bk` 值里含 `.bak` ⇒ 算已备份（启发式一档）。"""
    f = _verdict(_scan(tmp_path, edit=_COPY_BAK), "edit")
    assert f.verdict == "copy_to_bak"


def test_scan_honours_explicit_exemption_with_reason(tmp_path):
    """**正侧**：`INPLACE-ALLOW: <理由>` ⇒ 记 `exempt` 并把理由带进 detail。"""
    f = _verdict(_scan(tmp_path, edit=_EXEMPT), "edit")
    assert f.verdict == "exempt" and "不存在需要保护的既有字节" in f.detail


def test_scan_rejects_exemption_without_reason(tmp_path):
    """**反侧**：`INPLACE-ALLOW:` 后面**没写理由** ⇒ 不豁免，仍报 `unbacked`。"""
    f = _verdict(_scan(tmp_path, edit=_EXEMPT_NO_REASON), "edit")
    assert f.verdict == "unbacked"


def test_scan_is_order_sensitive_backup_after_write_is_unbacked(tmp_path):
    """**反侧（顺序敏感）**：备份调用在**写之后** ⇒ 不算「写前备份」，仍报 `unbacked`。

    这条是防「先改后补备份」冒充合规 —— 那正是前科 A/B 的形态。
    """
    f = _verdict(_scan(tmp_path, edit=_BACKUP_AFTER_WRITE), "edit")
    assert f.verdict == "unbacked"
    assert "写之后" in f.detail


def test_scan_detects_open_r_plus_open_w_inplace_editor(tmp_path):
    """读用 `p.open("r")`、写用 `p.open("w")` 也算就地改（mode 解析到位）。"""
    f = _verdict(_scan(tmp_path, edit=_READ_THEN_WRITE_VIA_OPEN), "edit")
    assert f.verdict == "unbacked" and f.target == "p"


@pytest.mark.parametrize("name,text", [
    ("only_read_rb", _ONLY_READ_RB),        # 只有读（回归：`Path(p).open("rb")` 曾被误当成写）
    ("no_overlap", _NO_OVERLAP),            # 读 A 写 B ⇒ 不是就地改
    ("write_only", _WRITE_ONLY),            # 只有写 ⇒ 不是就地改
])
def test_scan_has_no_false_positive(tmp_path, name, text):
    """**反侧（不误报）**：只读 / 只写 / 读写不同路径 ⇒ 一处判定都不该有。"""
    assert _scan(tmp_path, **{name: text}) == []


def test_scan_reports_unparsable_file_instead_of_guessing(tmp_path):
    """坏脚本 ⇒ 报 `unparsed`（不猜、不静默跳过）。"""
    f = _verdict(_scan(tmp_path, broken="def edit(p):\n    p.write_text(\n"), "broken")
    assert f.verdict == "unparsed" and "AST 解析失败" in f.detail


def test_format_findings_counts_unbacked(tmp_path):
    """报告首行给出「未备份 N 处」（数字来自判定，不是写死的）。"""
    fs = _scan(tmp_path, a=_UNBACKED, b=_COMPLIANT, c=_EXEMPT)
    txt = g.format_findings(fs)
    assert "共 3 处判定" in txt and "**未备份 1 处**" in txt


# ============================================================ ④b 真仓库（只读）
def test_real_repo_scan_runs_and_appender_is_recognised_as_backed_up():
    """真仓库扫描：跑得通；`scripts/append_record_section.py`（顺序：读→备份→写）算已备份。

    ⚠️ 这里**不锁**全仓未备份条数：另有执行者**同时在** `scripts/` 下增删脚本
    （本会话实测到过），锁死条数会让用例变成随机噪声。只锁「这个文件必须是已备份」，
    因为它正是本轮的缺口-3 交付物。
    """
    fs = g.scan_inplace_writers(repo=REPO)
    assert fs, "真仓库上不该一处都扫不出来（否则扫描器是空转的）"
    rel = [f for f in fs if f.path.replace("\\", "/").endswith("scripts/append_record_section.py")]
    assert rel, "必须在清单里（读+写同一 idx）"
    assert all(f.verdict != "unbacked" for f in rel), rel
    assert any(f.verdict == "copy_to_bak" for f in rel), rel
