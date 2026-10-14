# -*- coding: utf-8 -*-
"""**守卫 P1-②「证据只读检查」**（`src\\memsharness\\guards_readonly.py`）的用例。

事故背景（`INDEX §105`/§109.3，实测）：`scripts\\verify_paper_evidence.py` 旧版第 0 项
**先重跑生成脚本、再比对产物** ⇒ 2026-10-09 09:54:53 一次「校验」把
`work\\runs\\paper-evidence-20261009\\` 31 件产物**整个重写**，而它同时报告「逐位相同」。

本文件锁住两条：

* **动态**：目录「文件集合 + sha256 + size + mtime_ns」快照 —— **只读**时前后全等，
  **故意写一个字节**时必须报出来（正反两侧），连「内容相同但被重写」（只有 mtime 变）也要抓；
* **静态（R16）**：`scripts\\verify_*.py` 里「读了某个目录根、又写回同一个根」
  或在非 `regen*` 函数里起子进程/调生成器 ⇒ 报错；且**不许出现新的越界点**
  （已登记的 2 处遗留写入点如实单列，不静默）。
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from memsharness import guards_readonly as g   # noqa: E402


# ============================================================ ① 快照：正反两侧
def test_snapshot_unchanged_when_code_only_reads(tmp_path):
    d = tmp_path / "evidence"
    d.mkdir()
    (d / "a.json").write_text('{"n": 1}', encoding="utf-8")
    (d / "b.csv").write_text("x,y\n1,2\n", encoding="utf-8")

    v = g.check_dir_readonly(d, lambda: [
        p.read_text(encoding="utf-8") for p in sorted(d.glob("*"))])
    assert v["read_only_ok"] is True and v["ok"] is True
    assert v["problems"] == [] and v["n_files_before"] == v["n_files_after"] == 2
    assert g.format_snapshot_diff(v["diff"]).startswith("目录快照前后全等")
    # 断言版也必须放过只读代码
    g.assert_dir_readonly(d, lambda: (d / "a.json").read_text(encoding="utf-8"))


def test_snapshot_reports_a_single_byte_write(tmp_path):
    """**反侧**：故意写一个字节 ⇒ 必须报「被改写」并指出 sha256 变了。"""
    d = tmp_path / "evidence"
    d.mkdir()
    f = d / "a.json"
    f.write_text('{"n": 1}', encoding="utf-8")

    v = g.check_dir_readonly(d, lambda: f.write_text('{"n": 2}', encoding="utf-8"))
    assert v["read_only_ok"] is False and v["ok"] is False
    joined = " ".join(v["problems"])
    assert "被改写" in joined and "a.json" in joined and "sha256" in joined, v["problems"]
    with pytest.raises(g.ReadOnlyViolation) as ei:
        g.assert_dir_readonly(d, lambda: f.write_text('{"n": 3}', encoding="utf-8"))
    assert "被改写" in str(ei.value)
    assert ei.value.verdict is not None


def test_snapshot_catches_rewrite_with_identical_content(tmp_path):
    """只比 sha256 会漏掉「同样的内容被重写」⇒ mtime_ns 必须一起比。"""
    d = tmp_path / "evidence"
    d.mkdir()
    f = d / "a.txt"
    f.write_text("x", encoding="utf-8")
    before = g.snapshot_dir(d)
    f.write_text("x", encoding="utf-8")                 # 内容逐字节相同
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
    after = g.snapshot_dir(d)
    assert before["a.txt"][0] == after["a.txt"][0], "内容相同 ⇒ sha256 应相同"
    assert before["a.txt"][2] != after["a.txt"][2], "mtime_ns 变化必须被快照抓到"
    cmp = g.compare_snapshots(before, after)
    assert cmp["ok"] is False
    assert cmp["changed"][0]["fields"] == ["mtime_ns"], cmp["changed"]
    assert "内容逐字节相同但被重写" in cmp["problems"][0]


@pytest.mark.parametrize("action,needle", [
    (lambda d: (d / "new.json").write_text("{}", encoding="utf-8"), "新增文件"),
    (lambda d: (d / "a.json").unlink(), "文件消失"),
    (lambda d: (d / "sub").mkdir(), "新增文件"),
])
def test_snapshot_reports_add_remove_and_new_dirs(tmp_path, action, needle):
    d = tmp_path / "evidence"
    d.mkdir()
    (d / "a.json").write_text("{}", encoding="utf-8")
    v = g.check_dir_readonly(d, lambda: action(d))
    assert v["read_only_ok"] is False
    assert any(needle in p for p in v["problems"]), v["problems"]


def test_exception_does_not_excuse_writes(tmp_path):
    """「它中途崩了」不能成为「它没写」的借口 ⇒ 抛异常也照做快照比对。"""
    d = tmp_path / "evidence"
    d.mkdir()

    def bad():
        (d / "half.json").write_text("{}", encoding="utf-8")
        raise RuntimeError("boom")

    v = g.check_dir_readonly(d, bad)
    assert v["read_only_ok"] is False, "写入必须照旧被判出来"
    assert v["error"] and "boom" in v["error"]
    assert any("新增文件" in p for p in v["write_problems"])
    assert any("抛异常" in p for p in v["problems"])


def test_missing_dir_snapshot_is_empty(tmp_path):
    assert g.snapshot_dir(tmp_path / "不存在") == {}
    v = g.check_dir_readonly(tmp_path / "不存在", lambda: None)
    assert v["read_only_ok"] is True and v["n_files_before"] == 0


def test_snapshot_ignores_noise_but_not_evidence(tmp_path):
    d = tmp_path / "evidence"
    (d / "__pycache__").mkdir(parents=True)
    (d / "__pycache__" / "x.pyc").write_text("junk", encoding="utf-8")
    (d / "a.json").write_text("{}", encoding="utf-8")
    snap = g.snapshot_dir(d)
    assert list(snap) == ["a.json"], snap


# ============================================================ ② 静态（R16）
CLEAN_SRC = '''# -*- coding: utf-8 -*-
import json, pathlib
REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = REPO / "work/runs/x"

def main(argv):
    doc = json.loads((OUT / "MANIFEST.json").read_text(encoding="utf-8"))
    parts = [p.name for p in OUT.glob("*.json")]
    if argv.report:
        pathlib.Path(argv.report).write_text(json.dumps(doc), encoding="utf-8")
    return 0
'''

BAD_WRITE_SRC = '''# -*- coding: utf-8 -*-
import pathlib
OUT = pathlib.Path("work/runs/x")

def main():
    text = (OUT / "MANIFEST.json").read_text(encoding="utf-8")
    (OUT / "independent_recheck.json").write_text(text, encoding="utf-8")
    return 0
'''

BAD_SUBPROCESS_SRC = '''# -*- coding: utf-8 -*-
import subprocess, sys, pathlib
OUT = pathlib.Path("work/runs/x")

def main():
    subprocess.run([sys.executable, "scripts/paper_evidence_dac2027.py"], check=True)
    return 0
'''

EXEMPT_SRC = '''# -*- coding: utf-8 -*-
import pathlib
OUT = pathlib.Path("work/runs/x")

def main():
    text = (OUT / "MANIFEST.json").read_text(encoding="utf-8")
    # R16-ALLOW-WRITE: 这里写的是校验器自己的日志，与被校验对象无关（已人工确认）
    (OUT / "verifier.log").write_text(text, encoding="utf-8")
    return 0
'''


def _scan(tmp_path, name, src):
    p = tmp_path / name
    p.write_text(src, encoding="utf-8")
    return g.scan_verify_source(p)


def test_clean_verifier_is_not_flagged(tmp_path):
    """正侧：从目标目录读、把报告写到**别处** ⇒ 不是违例。"""
    r = _scan(tmp_path, "verify_clean.py", CLEAN_SRC)
    assert r["findings"] == [] and r["exempt"] == []


def test_write_into_verified_dir_is_flagged(tmp_path):
    """反侧：读了 `OUT` 又写回 `OUT` ⇒ 必须报，且点名是哪个根。"""
    r = _scan(tmp_path, "verify_bad.py", BAD_WRITE_SRC)
    kinds = [(f.kind, f.root) for f in r["findings"]]
    assert ("write_to_read_root", "OUT") in kinds, kinds
    assert "既被读" in r["findings"][0].detail


def test_subprocess_outside_regen_is_flagged(tmp_path):
    """反侧：在 `main()` 里调生成器（§109 事故的机制）⇒ 必须报。"""
    r = _scan(tmp_path, "verify_gen.py", BAD_SUBPROCESS_SRC)
    kinds = [(f.kind, f.root) for f in r["findings"]]
    assert ("subprocess_outside_regen", "main") in kinds, kinds
    assert any("paper_evidence_dac2027.py" in f.detail for f in r["findings"]), r["findings"]


def test_subprocess_inside_regen_function_is_allowed(tmp_path):
    """正侧 + 反证：放进 `regen_outputs()`（显式开关）就不算违例。"""
    src = BAD_SUBPROCESS_SRC.replace("def main():", "def regen_outputs():").replace(
        "    return 0", "    return 0", 1)
    r = _scan(tmp_path, "verify_regen.py", src)
    assert r["findings"] == [], [f.render() for f in r["findings"]]


def test_exemption_requires_explicit_reason(tmp_path):
    """豁免必须显式带理由：有理由 ⇒ 进 `exempt`（列出来）；只有记号没理由 ⇒ 照报。"""
    r = _scan(tmp_path, "verify_exempt.py", EXEMPT_SRC)
    assert r["findings"] == []
    assert r["exempt"] and "R16-ALLOW-WRITE" in r["exempt"][0]["reason"]

    no_reason = EXEMPT_SRC.replace("R16-ALLOW-WRITE: 这里写的是校验器自己的日志，与被校验对象无关（已人工确认）",
                                   "R16-ALLOW-WRITE:")
    r2 = _scan(tmp_path, "verify_exempt2.py", no_reason)
    assert [f.kind for f in r2["findings"]] == ["write_to_read_root"], r2
    assert r2["exempt"] == []


def test_str_replace_is_not_mistaken_for_a_write(tmp_path):
    """`str.replace("\\\\", "/")` 在本仓库的 verify 脚本里到处都是 ⇒ 不得误判成写操作。"""
    src = '''# -*- coding: utf-8 -*-
import pathlib
OUT = pathlib.Path("work/runs/x")

def main():
    rel = (OUT / "MANIFEST.json").read_text(encoding="utf-8").replace("\\\\", "/")
    print(rel)
    return 0
'''
    r = _scan(tmp_path, "verify_replace.py", src)
    assert r["findings"] == [], [f.render() for f in r["findings"]]


def test_new_offender_is_never_swallowed_by_the_legacy_allowlist(tmp_path):
    """在**另一个**脚本里出现同类越界 ⇒ 必须进 `new`（遗留在别的脚本，不得连带豁免）。"""
    (tmp_path / "verify_bad.py").write_text(BAD_WRITE_SRC, encoding="utf-8")
    res = g.scan_verify_scripts(tmp_path)
    assert res["ok"] is False
    assert [f.key for f in res["new"]] == [("verify_bad.py", "write_to_read_root", "OUT")]
    assert res["legacy_hits"] == () and len(res["legacy_absent"]) == len(g.LEGACY_KNOWN_OFFENDERS)


def test_unparsable_script_is_not_a_pass(tmp_path):
    (tmp_path / "verify_broken.py").write_text("def broken(:\n  pass\n", encoding="utf-8")
    r = g.scan_verify_source(tmp_path / "verify_broken.py")
    assert [f.kind for f in r["findings"]] == ["unreadable"]
    res = g.scan_verify_scripts(tmp_path)
    assert res["ok"] is False and len(res["new"]) == 1


def test_scan_empty_dir_is_ok_but_reports_zero_scanned(tmp_path):
    res = g.scan_verify_scripts(tmp_path)
    assert res["ok"] is True and res["n_scanned"] == 0


# ============================================================ ③ 真仓库：不许有新越界点
#: 已登记遗留写入点的「见证串」：源码里只要还有这段，扫描就必须报出对应的 key
#: （否则扫描器是恒真的摆设 —— 这条是「守卫的守卫」）
WITNESSES = {
    ("verify_s34_s4_interp.py", "write_to_read_root", "RUN"):
        'independent_s4_recheck.json',
    ("verify_te2_9_value_profile.py", "write_to_read_root", "pd"):
        '"verify.json"',
}


def test_real_repo_scan_has_no_new_r16_offenders():
    res = g.scan_verify_scripts()
    assert res["n_scanned"] >= 5, res["scanned"]
    assert res["ok"] is True, "出现未登记的 R16 越界点（写了被校验目录 / 非 regen 里起子进程）：" \
                             "%s" % [f.render() for f in res["new"]]
    keys = {f.key for f in res["findings"]}
    for key, witness in WITNESSES.items():
        p = REPO / "scripts" / key[0]
        if not p.is_file():
            continue
        if witness not in p.read_text(encoding="utf-8"):
            continue                       # 该写法已被修掉/改写 ⇒ 不要求仍被抓到
        assert key in keys, (
            "扫描器漏了真实遗留点 %s（见证串 %r 仍在源码里）⇒ 该静态守卫不可信" % (key, witness))
    # 遗留项如实单列（不是静默通过）
    legacy_keys = {f.key for f in res["legacy_hits"]} | set(res["legacy_absent"])
    assert legacy_keys == set(g.LEGACY_KNOWN_OFFENDERS), legacy_keys
    for f in res["legacy_hits"]:
        assert f.key in g.LEGACY_KNOWN_OFFENDERS


def test_legacy_allowlist_entries_are_documented():
    """允许清单里每一项都必须写清「为什么留、没修」—— 白名单本身也要被守卫。"""
    src = (REPO / "src/memsharness/guards_readonly.py").read_text(encoding="utf-8")
    for script, kind, root in g.LEGACY_KNOWN_OFFENDERS:
        assert script in src and root in src
        i = src.index('("%s", "%s", "%s")' % (script, kind, root))
        ctx = src[max(0, i - 600):i]
        assert "既是读的根" in ctx, "遗留项 %s 缺少「为什么留」的说明" % script


# ============================================================ ④ allowlist 状态位
# 「曾经越界、现已修复」与「从未越界」必须可区分（`INDEX §140.6 第 1 条` 的待办落地）。
# 四条要求逐一对应：① 已修条目状态 = fixed 且**不计入** legacy_hits；② 「已修」**不是永久
# 豁免**（再次命中 ⇒ 重新计入 legacy_hits 并标 regressed）；③ 状态缺失 ⇒ **明确报错**
# （`assert_...` 抛）＋ 扫描侧**如实降级**（`legacy_status_ok=False`，缺状态者不算已修）；
# ④ 状态表与 allowlist **逐条对齐**（分母可判定）。`ok` / `new` 的语义**一个字都没改**。
def test_legacy_allowlist_status_covers_every_entry():
    """正侧：状态表与 allowlist 逐条对齐，`fixed` 条目的 `fixed_at`/`evidence` 都非空。"""
    gaps = g.legacy_status_gaps()
    assert gaps["ok"] is True, gaps["problems"]
    assert gaps["missing"] == [] and gaps["invalid"] == [] and gaps["extra"] == []
    assert set(g.LEGACY_OFFENDER_STATUSES) == set(g.LEGACY_KNOWN_OFFENDERS)
    assert gaps["n_fixed"] >= 1, "两处已修条目（§140）应当被登记为 fixed"
    for k, v in g.LEGACY_OFFENDER_STATUSES.items():
        assert v.status in g.LEGACY_STATUS_VALUES, (k, v)
        if v.status == g.LEGACY_STATUS_FIXED:
            assert v.fixed_at.strip() and v.evidence.strip(), (k, v)
    assert g.assert_legacy_allowlist_status_complete()["ok"] is True    # 完整 ⇒ 不抛


def test_fixed_entry_is_not_counted_as_a_legacy_hit():
    """① 已修条目 ⇒ 状态 = `fixed`、**不计入** `legacy_hits`，而是进 `legacy_fixed_absent`。

    这条就是「曾经越界、现已修复」（`fixed` ＋ 未命中）与「从未越界」
    （`never_offended` ＋ 未命中）的分野：只有前者带「修好了」这层含义。
    """
    res = g.scan_verify_scripts()
    fixed = {k for k, v in g.LEGACY_OFFENDER_STATUSES.items()
             if v.status == g.LEGACY_STATUS_FIXED}
    absent = set(res["legacy_absent"])
    hit = {f.key for f in res["legacy_hits"]}
    assert fixed, "本仓至少应有一条 `fixed` 条目（§140 修掉的两处）"
    for k in fixed:
        assert k in absent, "已修条目当前不该命中（否则谈不上已修）：%s" % (k,)
        assert k not in hit, "已修条目不得计入 legacy_hits：%s" % (k,)
        assert k in set(res["legacy_fixed_absent"]), k
        assert k not in set(res["legacy_never_offended_absent"]), \
            "状态 = fixed 的条目不得落进「从未越界」那一档：%s" % (k,)
    assert res["legacy_regressed"] == (), "当前不应有回归"
    assert res["legacy_status_ok"] is True and res["ok"] is True


def test_a_fixed_entry_that_reoffends_is_legacy_hit_again(tmp_path):
    """② **「已修」不是永久豁免**：同一脚本再出现同一写入点 ⇒ 重新计入 `legacy_hits`。

    用真脚本名 `verify_s34_s4_interp.py` 装回**修掉前那种写法**（读 `RUN` 又写回 `RUN`）：
    key 与 allowlist 条目逐字相同 ⇒ 必须重新命中，并同时被标 `legacy_regressed`；
    而 `ok` / `new` 的语义**未变**（命中 allowlist 仍不算 `new`）。
    """
    regressed = '''# -*- coding: utf-8 -*-
import pathlib
RUN = pathlib.Path("work/runs/s34-mesh-20261006T131318Z")

def main():
    txt = (RUN / "s34_report.json").read_text(encoding="utf-8")
    (RUN / "independent_s4_recheck.json").write_text(txt, encoding="utf-8")
    return 0
'''
    (tmp_path / "verify_s34_s4_interp.py").write_text(regressed, encoding="utf-8")
    res = g.scan_verify_scripts(tmp_path)
    key = ("verify_s34_s4_interp.py", "write_to_read_root", "RUN")
    assert key in {f.key for f in res["legacy_hits"]}, \
        "回归的写入点必须重新计入 legacy_hits（已修 ≠ 永久豁免）"
    assert res["legacy_regressed"] == (key,), res["legacy_regressed"]
    assert key not in res["legacy_fixed_absent"]
    assert res["new"] == () and res["ok"] is True, \
        "allowlist 命中仍不算 new —— ok/new 的判定语义未改"

    # 反证：同一段代码换个脚本名 ⇒ 必须进 `new`（豁免只覆盖它自己那一条）
    (tmp_path / "verify_s34_s4_interp.py").rename(tmp_path / "verify_someone_else.py")
    res2 = g.scan_verify_scripts(tmp_path)
    assert res2["ok"] is False and len(res2["new"]) == 1, res2["new"]
    assert res2["legacy_hits"] == ()


def test_never_offended_entry_is_not_reported_as_fixed(tmp_path):
    """正侧（分野的另一半）：`never_offended` ＋ 未命中 ⇒ 进「从未越界」那一档，**不算已修**。"""
    key = ("verify_absent.py", "write_to_read_root", "OUT")
    allow = frozenset({key})
    st = {key: g.LegacyOffenderStatus(status=g.LEGACY_STATUS_NEVER_OFFENDED,
                                      evidence="§116.3 登记但从未实测命中（本用例构造）")}
    (tmp_path / "verify_absent.py").write_text("# 只有注释，无任何读/写\n", encoding="utf-8")
    res = g.scan_verify_scripts(tmp_path, allowlist=allow, statuses=st)
    assert res["legacy_status_ok"] is True
    assert res["legacy_absent"] == (key,)
    assert res["legacy_never_offended_absent"] == (key,)
    assert res["legacy_fixed_absent"] == (), "从未越界 ≠ 已修"
    assert res["ok"] is True


def test_missing_legacy_status_is_raised_and_degraded_honestly(tmp_path):
    """③ 状态缺失 ⇒ **明确报错** ＋ 扫描侧**如实降级**（两条一起，不许静默通过）。

    选定口径（说明见 `guards_readonly.assert_legacy_allowlist_status_complete` 的 docstring）：
    `assert_legacy_allowlist_status_complete()` **抛** `RuntimeError`（附缺失键原文）；
    `scan_verify_scripts()` **不抛**，但把 `legacy_status_ok` 置假并列出 `legacy_status_missing`；
    缺状态的键**绝不**被当成「已修」（不进 `legacy_fixed_absent`），而 `ok` 语义不动。
    """
    one = frozenset(list(g.LEGACY_KNOWN_OFFENDERS)[:1])
    assert len(one) == 1
    with pytest.raises(RuntimeError) as ei:
        g.assert_legacy_allowlist_status_complete(one, {})
    assert "缺状态位" in str(ei.value)
    assert str(sorted(one)[0]) in str(ei.value)

    gaps = g.legacy_status_gaps(one, {})
    assert gaps["ok"] is False and gaps["missing"] == sorted(one) and gaps["problems"]

    res = g.scan_verify_scripts(tmp_path, allowlist=one, statuses={})
    assert res["legacy_status_ok"] is False
    assert res["legacy_status_missing"] == tuple(sorted(one))
    assert res["legacy_fixed_absent"] == (), "缺状态位的条目不得被当成已修"
    assert res["ok"] is True, "`ok` 只判「新越界点」，语义未变"


@pytest.mark.parametrize("bad", [
    g.LegacyOffenderStatus(status="maybe_fixed", fixed_at="2026-10-09", evidence="随便"),
    g.LegacyOffenderStatus(status=g.LEGACY_STATUS_FIXED, fixed_at="", evidence=""),
    g.LegacyOffenderStatus(status=g.LEGACY_STATUS_NEVER_OFFENDED, fixed_at="2026-10-09",
                           evidence="不该带日期"),
])
def test_invalid_legacy_status_is_rejected(bad):
    """反侧：状态值非法 / `fixed` 缺依据 / `never_offended` 带日期 ⇒ 一律算状态不成立。"""
    key = sorted(g.LEGACY_KNOWN_OFFENDERS)[0]
    one = frozenset({key})
    gaps = g.legacy_status_gaps(one, {key: bad})
    assert gaps["ok"] is False, gaps
    assert set(gaps["invalid"]) | set(gaps["unknown_status"]) == {key}, gaps
    with pytest.raises(RuntimeError):
        g.assert_legacy_allowlist_status_complete(one, {key: bad})


def test_stale_status_entry_without_allowlist_entry_is_rejected():
    """反侧：状态表里多出一条 allowlist 没有的键 ⇒ `extra` 报出（分母对不上）。"""
    ghost = ("verify_ghost.py", "write_to_read_root", "OUT")
    st = dict(g.LEGACY_OFFENDER_STATUSES)
    st[ghost] = g.LegacyOffenderStatus(status=g.LEGACY_STATUS_NEVER_OFFENDED,
                                       evidence="本用例构造的陈旧条目")
    gaps = g.legacy_status_gaps(g.LEGACY_KNOWN_OFFENDERS, st)
    assert gaps["ok"] is False and ghost in gaps["extra"], gaps
    with pytest.raises(RuntimeError):
        g.assert_legacy_allowlist_status_complete(g.LEGACY_KNOWN_OFFENDERS, st)
