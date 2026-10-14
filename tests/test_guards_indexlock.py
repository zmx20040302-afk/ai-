# -*- coding: utf-8 -*-
"""**守卫 P1-⑤「索引单写者」**（`src\\memsharness\\guards_indexlock.py`
＋ `scripts\\append_record_locked.py`）的用例。

事故背景（`INDEX §104` 实测）：两条线**同时**追加索引，发生一次**节号竞争** ——
`读最大节号 → 写` 这一段不是原子的。本轮**没有改** `scripts\\append_record_section.py`
一个字节（它刚在 §110 被修过且有用例），而是用**新包装脚本**把这段放进独占锁里。

判据：**拿不到锁 ⇒ 拒绝写入**（退出码 3，索引一个字节都不变），且**不抢锁、不自动破锁**。
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from memsharness import guards_indexlock as g   # noqa: E402


def load_wrapper():
    spec = importlib.util.spec_from_file_location(
        "_append_record_locked_under_test", REPO / "scripts/append_record_locked.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def wrapper():
    return load_wrapper()


@pytest.fixture()
def fake_repo(tmp_path):
    """一个**替身仓库**：真索引（含 `## 7.`/`## 12.`）＋ 一个片段文件。"""
    (tmp_path / "docs").mkdir(parents=True)
    idx = tmp_path / "docs/INDEX-records-and-rulings.md"
    idx.write_text("# 索引\n\n## 7. 旧的\n\n内容。\n\n## 12. 另一个\n\n内容。\n",
                   encoding="utf-8")
    return tmp_path, idx


def write_section(tmp: pathlib.Path, name: str, num: int | None, title: str = "测试节") -> pathlib.Path:
    p = tmp / name
    head = ("## %d. %s" % (num, title)) if num is not None else ("## 标题缺号 %s" % title)
    p.write_text(head + "\n\n正文。\n", encoding="utf-8")
    return p


# ============================================================ ① 锁的互斥性
def test_lock_is_exclusive_and_second_acquire_is_refused(tmp_path):
    lp = tmp_path / "locks/x.lock"
    a = g.IndexLock(lp)
    assert a.try_acquire() == (True, "拿到锁：%s" % lp)
    assert lp.is_file()

    b = g.IndexLock(lp)
    ok, msg = b.try_acquire()
    assert ok is False
    assert "拒绝写入" in msg and "稍后重试" in msg, msg
    assert "pid=" in msg, "拒写消息必须带持锁者信息（否则无从排查）：%s" % msg
    a.release()
    assert not lp.exists()
    assert g.IndexLock(lp).try_acquire()[0] is True


def test_release_does_not_delete_a_lock_it_did_not_take(tmp_path):
    lp = tmp_path / "x.lock"
    lp.write_text("别人占着", encoding="utf-8")
    assert g.IndexLock(lp).release() is False
    assert lp.is_file(), "没拿到锁的实例不得删掉别人的锁"
    assert g.IndexLock(lp).release() is False                 # 幂等
    assert lp.is_file()


def test_lock_holder_info_is_readable(tmp_path):
    lp = tmp_path / "x.lock"
    with g.IndexLock(lp, purpose="单测"):
        h = g.IndexLock(lp).holder()
        assert h["pid"] == os.getpid() and h["purpose"] == "单测"
        assert "已持锁" in g.IndexLock(lp).describe_holder()


def test_timeout_can_wait_for_a_lock_to_be_released(tmp_path):
    lp = tmp_path / "x.lock"
    holder = g.IndexLock(lp)
    holder.acquire()
    import threading
    threading.Timer(0.3, holder.release).start()
    t0 = time.monotonic()
    waiter = g.IndexLock(lp, timeout_s=5.0)
    with waiter:
        pass
    assert time.monotonic() - t0 >= 0.25, "应当在等锁（而不是立刻拒）"
    assert not lp.exists()


def test_stale_lock_is_only_broken_when_explicitly_allowed(tmp_path):
    lp = tmp_path / "x.lock"
    lp.write_text('{"pid": 999999, "purpose": "僵死进程"}', encoding="utf-8")
    old = time.time() - 3600
    os.utime(lp, (old, old))

    assert g.IndexLock(lp, stale_after_s=900).try_acquire()[0] is False, \
        "缺省**不破锁**（不自动抢）"
    assert lp.is_file()

    lk = g.IndexLock(lp, stale_after_s=900, break_stale=True)
    assert lk.try_acquire()[0] is True
    assert lk.broke_stale and lk.broke_stale["holder"]["pid"] == 999999
    assert lk.broke_stale["age_s"] > 900
    lk.release()

    # 锁**没超龄**时即便允许破锁也不得破
    lp.write_text('{"pid": 1234}', encoding="utf-8")
    assert g.IndexLock(lp, stale_after_s=900, break_stale=True).try_acquire()[0] is False


# ============================================================ ② 拿不到锁 ⇒ 拒写（核心反侧）
def test_locked_append_refuses_and_never_touches_the_index(fake_repo):
    tmp, idx = fake_repo
    sec = write_section(tmp, "s.md", 13)
    lp = g.default_lock_path(tmp, idx.name)
    before = idx.read_bytes()

    calls: list[dict] = []
    with g.IndexLock(lp):
        res = g.locked_append(idx, sec, repo=tmp, lock_path=lp,
                              invoke=lambda **kw: calls.append(kw) or {"rc": 0, "stdout": ""})

    assert res["status"] == "refused" and res["ok"] is False
    assert "拒绝写入" in res["message"] and "索引未被改动" in res["message"], res["message"]
    assert calls == [], "拿不到锁时**不得**调用追加器（更不得写盘）"
    assert idx.read_bytes() == before, "索引被改动了！"
    assert res["chars_before"] is None and res["appender_rc"] is None


def test_wrapper_cli_returns_3_when_locked(wrapper, fake_repo):
    tmp, idx = fake_repo
    sec = write_section(tmp, "s.md", 13)
    lp = g.default_lock_path(tmp, idx.name)
    before = idx.read_bytes()
    with g.IndexLock(lp):
        rc = wrapper.main(["--section", str(sec), "--repo", str(tmp),
                           "--index", str(idx), "--lock", str(lp)])
    assert rc == wrapper.RC_LOCKED == 3
    assert idx.read_bytes() == before


# ============================================================ ③ 正侧：追加成功
def test_locked_append_appends_and_releases_the_lock(fake_repo):
    tmp, idx = fake_repo
    sec = write_section(tmp, "s.md", 13)
    lp = g.default_lock_path(tmp, idx.name)
    before = idx.read_text(encoding="utf-8")

    res = g.locked_append(idx, sec, repo=tmp, lock_path=lp)
    after = idx.read_text(encoding="utf-8")

    assert res["status"] == "appended" and res["ok"] is True, res
    assert res["heading"] == "## 13."
    assert after.startswith(before), "既有字节不得被改写（append-only）"
    assert "## 13. 测试节" in after
    assert res["chars_after"] > res["chars_before"]
    assert res["sha256_after"] != res["sha256_before"]
    assert not lp.exists(), "用完必须释放锁（否则后来者全被挡住）"
    # 原追加器的三道守卫仍在：备份落盘 + 输出原文转回来了
    baks = list((tmp / "work/logs").glob("INDEX-records-and-rulings.*.md.bak"))
    assert len(baks) == 1 and baks[0].read_text(encoding="utf-8") == before
    assert "追加 '## 13.'" in res["appender_stdout"], res["appender_stdout"]


def test_next_heading_is_max_plus_one(fake_repo):
    tmp, idx = fake_repo
    text = idx.read_text(encoding="utf-8")
    assert g.max_section_number(text) == 12
    assert g.next_heading(text) == "## 13."
    assert g.declared_section_number("## 13. 标题\n\n正文\n") == 13
    assert g.declared_section_number("\n\n没有标题\n") is None


# ============================================================ ④ 节号不合法 ⇒ 拒写
def test_section_number_not_max_plus_one_is_refused(fake_repo):
    """**反侧**：片段自称 §113，而索引 max=12 ⇒ 拒写（防跳号/撞号），索引一字不动。"""
    tmp, idx = fake_repo
    sec = write_section(tmp, "s.md", 113)
    before = idx.read_bytes()
    res = g.locked_append(idx, sec, repo=tmp)
    assert res["status"] == "failed" and "节号不合法" in res["message"], res["message"]
    assert "max+1 = §13" in res["message"]
    assert idx.read_bytes() == before
    assert not g.default_lock_path(tmp, idx.name).exists()


def test_heading_mismatch_is_refused_before_any_write(fake_repo):
    """**反侧（写前拦截）**：显式 `--heading "## 13."` 但片段首行是 `## 113.`。

    这个形态在原追加器里是「**先写盘**、再回读失败」（退出码 2 但字节已落盘）——
    本包装脚本必须在**写之前**拦住它。
    """
    tmp, idx = fake_repo
    sec = write_section(tmp, "s.md", 113)
    before = idx.read_bytes()
    res = g.locked_append(idx, sec, heading="## 13.", repo=tmp)
    assert res["status"] == "failed" and "片段与标题不对应" in res["message"], res["message"]
    assert idx.read_bytes() == before, "写了就不叫「写前拦截」"


def test_missing_section_file_is_refused(fake_repo):
    tmp, idx = fake_repo
    before = idx.read_bytes()
    res = g.locked_append(idx, tmp / "不存在.md", repo=tmp)
    assert res["status"] == "failed" and "读不出片段文件" in res["message"]
    assert idx.read_bytes() == before


def test_duplicate_heading_is_skipped_without_writing(fake_repo):
    """已存在同号标题 ⇒ 原追加器报 `[SKIP]`（rc=0 但没写）⇒ 状态必须是 skipped。"""
    tmp, idx = fake_repo
    sec = write_section(tmp, "s.md", 7)          # `## 7.` 已存在
    before = idx.read_bytes()
    res = g.locked_append(idx, sec, heading="## 7.", repo=tmp)
    assert res["status"] == "skipped" and res["ok"] is False, res
    assert idx.read_bytes() == before
    assert not g.default_lock_path(tmp, idx.name).exists()


def test_wrapper_cli_appends_and_reports(fake_repo, capsys):
    wrapper = load_wrapper()
    tmp, idx = fake_repo
    sec = write_section(tmp, "s.md", 13)
    rc = wrapper.main(["--section", str(sec), "--repo", str(tmp), "--index", str(idx),
                       "--lock", str(g.default_lock_path(tmp, idx.name))])
    out = capsys.readouterr().out
    assert rc == 0 and "[OK]" in out and "append-only" in out, out
    assert "## 13. 测试节" in idx.read_text(encoding="utf-8")


# ============================================================ ⑤ 真索引：只读且节号自洽
def test_real_index_next_heading_matches_max_plus_one_and_is_unused():
    idx = REPO / "docs/INDEX-records-and-rulings.md"
    if not idx.is_file():
        pytest.skip("缺索引")
    before = idx.read_bytes()
    text = idx.read_text(encoding="utf-8")
    head = g.next_heading(text)
    num = int(head.split()[1].rstrip("."))
    assert num == g.max_section_number(text) + 1
    assert head not in text, "算出来的「下一个可用号」居然已被占用 ⇒ 节号计算有 bug"
    assert idx.read_bytes() == before, "本用例**只读**索引"
