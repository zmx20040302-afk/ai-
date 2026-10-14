# -*- coding: utf-8 -*-
"""**数据字典**的契约测试：把「每个数据名字都讲清楚了」变成可机器检查的不变量。

用户要求：「讲解各个参数和计算结果……不需要计算，只需要把每一个数据名称讲清楚」。
"每一个"是可验证的：真实表里出现的**每一个列名**都必须能解析到一条解释。
本文件锁住这一点，并锁住"不许把未确认的口径说成已确认"。

表缺失时跳过（`work/` 不进版本库），但**不静默通过**。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "scripts/webapp_page.html"
sys.path.insert(0, str(REPO / "src"))

pytestmark = pytest.mark.skipif(
    not (REPO / "work/runs/remote-exported-20260922/dataset/points.csv").is_file(),
    reason="缺批 A 数据集（work/ 不进版本库）⇒ 字典覆盖率无法核对")


def _g():
    from memsharness import glossary
    return glossary


def test_every_real_column_name_is_explained():
    """**核心不变量**：真实表里的每个列名都有解释，0 处遗漏。"""
    cov = _g().coverage()
    assert cov["n_missing"] == 0, "有列名没有解释：%s" % cov["missing"]
    assert cov["n_distinct_column_names"] >= 100, cov["n_distinct_column_names"]
    assert cov["n_canonical_entries"] >= 60
    for table, d in cov["per_table"].items():
        assert d["n_columns"] > 0, "%s 读不到列（路径变了？）" % table
        assert not d["unexplained"], "%s 未解释：%s" % (table, d["unexplained"])
    assert "0 处遗漏" in cov["verdict"]


def test_glossary_actually_generated_an_explanation():
    """覆盖率不能靠「空解释」刷过去：每条解释必须有实义内容。"""
    g = _g()
    for name, e in g.ENTRIES.items():
        # `zh` 是**名字**，3 个字（如「频点数」）就是好名字 ⇒ 只要求非空；
        # 真正要求"有实义"的是 what/how。
        assert e["zh"], name
        # 阈值只用来挡"空解释/占位符"：10 个汉字已是一句有实义的话。
        # （曾把阈值定成 12，结果把「加在内圈电极上的电位。」这种合格短句误判为太短。）
        assert e["what"] and len(e["what"]) >= 10, "%s 的「它是什么」太短" % name
        assert e["how"] and len(e["how"]) >= 6, "%s 的「口径」太短" % name
        assert e["kind"] in g.KIND_ORDER, "%s 的类别不在预定义里：%s" % (name, e["kind"])
        assert e["ranking"] in g.RANK_LABEL, name


def test_unconfirmed_entries_are_marked_not_guessed():
    """**不许猜**：口径未书面确认的量必须标出来，而不是给一个看起来对的解释。"""
    g = _g()
    unconf = g.coverage()["unconfirmed_entries"]
    # 这些量的表达式/取样点确实没有书面确认（旧问题 §5.4/§5.5 仍未闭合）
    for name in ("p_total_re_N", "vv_m4s2", "sGp_du_W", "u_du_m4s2"):
        assert name in unconf, "%s 应按「口径未书面确认」标注" % name
    # 反过来：已确认的量（如 ΔV、SPL 口径）不得被标成未确认
    for name in ("delta_V_V", "spl_dB", "bandwidth_Hz", "Q_factor"):
        assert name not in unconf, "%s 的口径已确认，不该标未确认" % name


def test_ranking_semantics_match_the_rulings():
    """字典必须与被裁定的排名口径一致（否则它会变成一处新的口径来源）。"""
    g = _g()
    assert g.ENTRIES["bandwidth_Hz"]["ranking"] == "formal"
    assert g.ENTRIES["abs_w_m"]["ranking"] == "formal"
    assert g.ENTRIES["abs_p_per_V_Pa"]["ranking"] == "formal"
    # Q/ζ 只作门槛
    for name in ("Q_factor", "damping_ratio"):
        assert g.ENTRIES[name]["ranking"] == "gate", name
    # §3.4 约束量只作约束、永不排名
    for name in ("abs_pv_W", "abs_stress_zz_N", "sGp_du_W", "u_du_m4s2"):
        assert g.ENTRIES[name]["ranking"] == "constraint", name
    # 方向标注与"越大越好"一致
    for name in ("bandwidth_Hz", "abs_w_m", "abs_p_per_V_Pa"):
        assert g.ENTRIES[name]["direction"] == "max"
    assert g.ENTRIES["abs_stress_zz_N"]["direction"] == "min"


def test_ambiguous_column_resolves_per_table():
    """`v_z_m3s` 在 power.csv（全局）与 mech.csv（结构）里**不是同一个量** ⇒ 必须按表解析。

    这条是覆盖率自检当场抓出来的真问题：只按列名解析会把两处合并成一条解释。
    """
    g = _g()
    a, _ = g.resolve("v_z_m3s", "A/power.csv")
    b, _ = g.resolve("v_z_m3s", "A/mech.csv")
    assert a == "v_z_re_m3s" and b == "vz_struct_re_m3s"
    assert a != b
    # 且两条解释里都要有"别混"的提醒
    assert "混" in g.ENTRIES["v_z_re_m3s"]["caveat"]


def test_no_computation_claim_and_payload_shape():
    """本页**不做计算**：载荷必须自带这句声明，且不含任何数值型「结果」。"""
    g = _g()
    p = g.payload()
    assert "不做任何计算" in p["no_computation"]
    assert p["coverage"]["n_missing"] == 0
    assert p["sections"], "没有可展示的分类"
    # 每条都带排名标签与别名清单（页面要能回答「表里那个名字在哪」）
    for sec in p["sections"]:
        for it in sec["items"]:
            assert it["ranking_label"]
            assert isinstance(it["alias_in_table" + "s"], list)


def test_server_exposes_glossary_endpoint():
    spec = importlib.util.spec_from_file_location(
        "_webapp_srv_gloss", REPO / "scripts/webapp_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = mod._glossary()
    assert "error" not in r, r
    assert r["coverage"]["n_missing"] == 0
    assert mod._glossary()["sections"]


def test_panel_is_reachable_from_the_sidebar():
    """**面板存在 ≠ 用户点得到**：侧栏 `NAV` 与 `class="panel"` 必须一一对应。

    这一条挡的是"加了分区却忘了挂到侧栏"⇒ 那个分区就是**死页**（用户根本点不到），
    以及反向的"侧栏有、面板没有"⇒ 点了空白。两种都在本仓库发生过（"点按钮没反应"）。
    """
    import re

    html = PAGE.read_text(encoding="utf-8")
    m = re.search(r"const NAV=\[(.*?)\];", html, re.S)
    assert m, "页面里找不到侧栏 NAV 定义（结构变了？）"
    nav_keys = set(re.findall(r"\['([a-z]+)','", m.group(1)))
    panel_keys = set(re.findall(r'class="panel" id="p-([a-z]+)"', html))
    assert "gloss" in nav_keys, "数据字典没有挂到侧栏 ⇒ 用户点不到"
    assert nav_keys == panel_keys, ("侧栏与面板不对应：只在侧栏 %s；只在页面 %s"
                                    % (sorted(nav_keys - panel_keys),
                                       sorted(panel_keys - nav_keys)))


def test_page_has_glossary_panel_and_no_literal_markdown():
    html = PAGE.read_text(encoding="utf-8")
    for must in ("数据字典", 'id="p-gloss"', 'id="bGloss"', "loadGloss", "renderGloss",
                 'id="glQ"', 'id="glKind"'):
        assert must in html, "页面缺少：%s" % must
    # 后端文本（what/how/caveat/where/verdict）**必须**走 mdInline，否则 `**` 会字面显示
    for field in ("it.what", "it.how", "it.caveat", "it.where", "cov.verdict"):
        assert ("esc(%s" % field) not in html, "%s 走了 esc()（markdown 会字面显示）" % field
    assert "不做任何计算" in html
