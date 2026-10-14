# -*- coding: utf-8 -*-
"""**守卫 P1-①「可失败性元测试」**（`src\\memsharness\\guards_metatest.py`）的用例。

事故背景（三次实测，见 `docs\\INDEX-records-and-rulings.md` 行 4307 与
`tests\\test_subprocess_encoding.py` 行 119）：校验写成 `n_prod == 0 or True`（恒真）、
期望值用通配 `"*"`、扫描器按 `node.args` 找 `sys.executable`（永远匹配不到）
—— 三者都**必然打印「通过」却什么都没检查**。

本文件锁住两件事：

1. **投毒真的能抓**：一个「恒真 / 恒假 / 契约不明」的检查器，`falsifiability_report()`
   必须判它**不可失败**（正反两侧都做）；
2. **本模块自带的 2 个示例挂载 ＋ 跨模块挂载**，逐件通过两侧检查。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from memsharness import guards_denominator as gden          # noqa: E402
from memsharness import guards_envfacts as genv             # noqa: E402
from memsharness import guards_metatest as g                # noqa: E402
from memsharness import guards_readonly as gro              # noqa: E402


@pytest.fixture()
def restore_registry():
    """登记表是模块级状态：用例里登记的挂载点用完必须还原（免得污染别的用例）。"""
    saved = list(g.REGISTRY)
    try:
        yield g
    finally:
        g.REGISTRY[:] = saved


# ============================================================ ① 登记表逐件投毒
def test_registry_has_the_two_required_example_mounts():
    names = [e.name for e in g.registry()]
    assert len(names) >= 2, "至少要给 2 个示例挂载（哈希比对器 / 计数一致性检查器）"
    assert any("sha256" in n for n in names), names
    assert any("计数" in n for n in names), names


@pytest.mark.parametrize("entry", list(g.registry()), ids=lambda e: e.name)
def test_every_registered_mount_is_falsifiable(entry):
    """**两侧都要成立**：干净输入不报错、投毒输入必须报错。"""
    rep = g.assert_falsifiable(entry)          # 不可失败 ⇒ 抛 NotFalsifiable
    assert rep["falsifiable"] is True
    assert entry.poisons, "没有投毒用例的挂载点无法证明可失败"
    assert rep["clean"]["reported"] is False, rep["clean"]
    for row in rep["poisons"]:
        assert row["reported"] is True, "投毒用例 %r 未报错：%s" % (row["case"], row["detail"])


def test_summarize_reports_all_mounts_falsifiable():
    s = g.summarize()
    assert s["ok"] is True, s["not_falsifiable"]
    assert s["n_mounts"] == s["n_falsifiable"] >= 2


# ============================================================ ② 假校验必须被抓（原事故回归）
def _fake_always_pass(payload):
    """恒真：不看输入，永远返回「无问题」（正是 `n_prod == 0 or True` 的等价物）。"""
    return []


def _fake_none(payload):
    return None


def _fake_wildcard(payload):
    """期望值用通配 `\"*\"` ⇒ 比对必然成立。"""
    import fnmatch
    expected = "*"
    got = str(payload.get("name", ""))
    return ["不一致"] if not fnmatch.fnmatch(got, expected) else []


@pytest.mark.parametrize("fake,name", [
    (_fake_always_pass, "恒真：永远返回空问题清单"),
    (_fake_none, "恒真：永远返回 None"),
    (_fake_wildcard, "通配期望值：fnmatch(got, '*') 必然成立"),
])
def test_unfalsifiable_checkers_are_rejected(fake, name):
    """三个「写了等于没写」的检查器都必须在投毒输入上**不报错** ⇒ 元测试判它不可失败。"""
    entry = g.mount(name, fake, lambda: {"name": "artifact"},
                    [g.PoisonCase("必然不一致的输入", lambda: {"name": "TAMPERED"})])
    rep = g.falsifiability_report(entry)
    assert rep["falsifiable"] is False, "假校验没被抓到：%s" % name
    assert any("假校验" in p for p in rep["problems"]), rep["problems"]
    with pytest.raises(g.NotFalsifiable):
        g.assert_falsifiable(entry)


def test_always_failing_checker_is_also_rejected():
    """**反侧**：恒假的检查器（无脑报错）同样不合格 —— 否则「必须报错」这一侧毫无意义。"""
    def always_fail(payload):
        return ["无论如何都报错"]
    entry = g.mount("恒假", always_fail, lambda: {}, [g.PoisonCase("poison", lambda: {})])
    rep = g.falsifiability_report(entry)
    assert rep["falsifiable"] is False
    assert any("误报" in p for p in rep["problems"]), rep["problems"]


def test_mount_without_poison_cases_is_rejected():
    entry = g.mount("无投毒用例", lambda p: [], lambda: 1, [])
    rep = g.falsifiability_report(entry)
    assert rep["falsifiable"] is False
    assert any("没有提供任何投毒用例" in p for p in rep["problems"]), rep["problems"]


# ============================================================ ③ 契约：不猜
def test_reports_problem_contract():
    assert g.reports_problem(None) == (False, "返回 None（无问题）")
    assert g.reports_problem(True)[0] is False
    assert g.reports_problem(False)[0] is True
    assert g.reports_problem("")[0] is False
    assert g.reports_problem([])[0] is False
    assert g.reports_problem(["x"])[0] is True
    assert g.reports_problem({"problems": []})[0] is False
    assert g.reports_problem({"problems": ["a"]})[0] is True
    assert g.reports_problem({"ok": True})[0] is False
    assert g.reports_problem({"ok": False})[0] is True


@pytest.mark.parametrize("weird", [3.14, {"count": 3}, object()])
def test_unknown_contract_is_not_a_pass(weird):
    """契约不明的返回值**既不判通过也不判失败** ⇒ 让元测试失败（不猜）。"""
    with pytest.raises(g.CheckerContractError):
        g.reports_problem(weird)
    entry = g.mount("契约不明", lambda p: weird, lambda: 1, [g.PoisonCase("p", lambda: 2)])
    rep = g.falsifiability_report(entry)
    assert rep["falsifiable"] is False
    assert any("契约不明" in p for p in rep["problems"]), rep["problems"]


def test_raised_exception_counts_as_reported_and_keyboardinterrupt_propagates():
    def boom(payload):
        raise ValueError("故意的")
    ev = g.evaluate(boom, {})
    assert ev["reported"] is True and "ValueError" in ev["raised"]

    def interrupted(payload):
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        g.evaluate(interrupted, {})


# ============================================================ ④ 示例挂载 ①：哈希比对器
def test_hash_compare_positive_and_negative(tmp_path):
    """正反两侧都手写一遍（不只依赖元测试的聚合结论）。"""
    import hashlib
    p = tmp_path / "a.bin"
    p.write_bytes(b"payload")
    good = hashlib.sha256(b"payload").hexdigest()
    assert g.hash_compare({"path": p, "expected_sha256": good, "label": "a.bin"}) == []

    p.write_bytes(b"payload!")                      # 只改一个字节
    probs = g.hash_compare({"path": p, "expected_sha256": good, "label": "a.bin"})
    assert probs and "sha256 不符" in probs[0] and good in probs[0], probs

    assert g.hash_compare({"path": p, "expected_sha256": "", "label": "a.bin"}), \
        "空期望必须判不合格（空期望与通配同类）"
    assert g.hash_compare({"path": tmp_path / "缺.bin", "expected_sha256": good}), "缺文件必须报"


# ============================================================ ⑤ 示例挂载 ②：计数一致性
def test_counts_consistent_positive_and_negative():
    assert g.counts_consistent({"counts": {"a": 51, "b": 102, "c": 323}, "total": 476}) == []
    probs = g.counts_consistent({"counts": {"a": 51, "b": 0, "c": 323}, "total": 476})
    assert probs and "374" in probs[0] and "476" in probs[0], probs
    bad = g.counts_consistent({"counts": {"a": float("nan")}, "total": 1})
    assert bad and "不是整数" in bad[0], bad


# ============================================================ ⑥ 静态：恒真写法
@pytest.mark.parametrize("src,hit", [
    ("assert n_prod == 0 or True", True),                       # 原事故写法
    ("if flag:\n    pass\nassert True", True),
    ("if True:\n    pass", True),
    ('assert got == "*"', True),                                # 通配期望值
    ('assert fnmatch(name, "*")', True),
    ('assert got != "*"', True),
    ("assert n_prod == 0", False),
    ("assert got is True", False),
    ("assert flag or fallback", False),
    ('assert got == "abc"', False),
    # 文档串里**引用**这些写法不算（AST 判定，不是正则扫文本）
    ('"""事故写法是 `n_prod == 0 or True` 与 `== \\"*\\"`"""\nassert x == 1', False),
])
def test_tautology_smells(src, hit):
    found = g.find_tautology_smells(src)
    assert bool(found) is hit, (src, found)


def test_tautology_smells_unparsable_is_not_a_pass():
    out = g.find_tautology_smells("def broken(:\n  pass")
    assert out and out[0]["smell"] == "unparsable", out


def test_own_checkers_have_no_tautology_smells():
    """守卫的守卫：示例检查器自己的源码里不许出现恒真写法。"""
    bad = {}
    for entry in g.registry():
        smells = g._checker_source_smells(entry.checker)
        if smells:
            bad[entry.name] = smells
    assert not bad, bad


# ============================================================ ⑦ 跨模块挂载（怎么挂新检查器）
def test_cross_module_mounts_are_falsifiable(restore_registry, tmp_path):
    """分母纪律 / 只读快照 / 环境事实时间戳 —— 三个别的模块的检查器也能挂上来。"""
    rows = [{"usable": True, "Q": (float("nan") if i < 38 else 1.0 + i % 3)}
            for i in range(146)]
    good_rec = gden.make_rate_record("V2 Q 达标率", 40, rows)

    def rate_checker(payload):
        return gden.check_rate_record(payload)
    rate_entry = g.mount("分母纪律（guards_denominator.check_rate_record）", rate_checker,
                         lambda: dict(good_rec),
                         [g.PoisonCase("146 被当成 108（缺 n_nondecidable）",
                                       lambda: {k: v for k, v in good_rec.items()
                                                if k != "n_nondecidable"}),
                          g.PoisonCase("缺 denominator",
                                       lambda: {k: v for k, v in good_rec.items()
                                                if k != "denominator"})],
                         doc="比例必须同时带可判定基数与标志口径计数")

    ev_dir = tmp_path / "evidence"
    ev_dir.mkdir()
    (ev_dir / "a.txt").write_text("evidence", encoding="utf-8")

    def readonly_checker(payload):
        return gro.check_dir_readonly(payload["root"], payload["fn"])["problems"]
    readonly_entry = g.mount("证据只读（guards_readonly.check_dir_readonly）", readonly_checker,
                             lambda: {"root": ev_dir,
                                      "fn": lambda: (ev_dir / "a.txt").read_text(encoding="utf-8")},
                             [g.PoisonCase("往被校验目录写一个字节",
                                           lambda: {"root": ev_dir,
                                                    "fn": lambda: (ev_dir / "a.txt").write_text(
                                                        "evidence!", encoding="utf-8")})],
                             doc="R16：校验者不得改写被校验对象")

    import datetime as _dt
    now = _dt.datetime(2026, 10, 9, 12, 0, 0, tzinfo=_dt.timezone.utc)
    good_fact = genv.make_fact("sac_blocks_sklearn", False, source="现场全量 pytest", now=now)

    def fact_checker(payload):
        return genv.check_fact(payload["fact"], max_age_s=payload.get("max_age_s"), now=now)
    fact_entry = g.mount("环境事实时间戳（guards_envfacts.check_fact）", fact_checker,
                         lambda: {"fact": dict(good_fact)},
                         [g.PoisonCase("缺观测时间",
                                       lambda: {"fact": {"capability": "sac_blocks_sklearn",
                                                         "value": False, "source": "当时听说"}}),
                          g.PoisonCase("观测时间过旧（瞬时环境当长期事实）",
                                       lambda: {"fact": dict(
                                           good_fact,
                                           observed_at=genv.now_stamp(
                                               now - _dt.timedelta(hours=3))),
                                           "max_age_s": 600})],
                         doc="缺观测时间 ⇒ 不合格")

    for entry in (rate_entry, readonly_entry, fact_entry):
        g.register(entry)
        g.assert_falsifiable(entry)
    names = [e.name for e in g.registry()]
    assert len(names) == len(set(names)), "登记表里出现重名 ⇒ 后者会悄悄掩盖前者"


def test_register_rejects_duplicate_name(restore_registry):
    entry = g.mount("唯一名", lambda p: [], lambda: 1, [g.PoisonCase("p", lambda: 2)])
    g.register(entry)
    with pytest.raises(ValueError, match="重名"):
        g.register(entry)


# ============================================================ ⑧ 守卫的守卫（元层次）
@pytest.mark.parametrize("mod_name", [
    "guards_metatest", "guards_readonly", "guards_denominator",
    "guards_envfacts", "guards_indexlock",
])
def test_guard_modules_have_no_tautology_smells(mod_name):
    """五个新增守卫模块自己的源码里**不许有**恒真写法（上游扫描自己）。"""
    src = (REPO / ("src/memsharness/%s.py" % mod_name)).read_text(encoding="utf-8")
    smells = g.find_tautology_smells(src)
    assert not smells, smells


def test_checker_source_smells_reads_real_source():
    """`_checker_source_smells()` 必须真的读到源码（否则它是恒真的摆设）。"""
    smells = g._checker_source_smells(g.hash_compare)
    assert isinstance(smells, list) and smells == []
    assert g.find_tautology_smells("def fake(p):\n    assert True\n"), \
        "对真源码的扫描必须能报出恒真断言"
