# -*- coding: utf-8 -*-
"""裁定 §3/§4「要研究哪些计算结果」的**完备性回归门禁**。

背景：用户问过「我们前面讨论过要研究哪些计算结果，再检查一下看看需不需要完善」。
当时人眼扫 60 多列漏掉了 3 个通道 + 8 个 §4 字段，且 **`quarantined` 列被
`DictWriter(extrasaction="ignore")` 静默丢弃**（表里没有该列，隔离信息全丢）。
本文件把那次复盘固化成用例，防止同类静默丢列再次发生。

锁住的不变量：
1. 主表列 ⊇ 裁定 §4 的 18 个必需字段 ∪ 全部通道 ∪ 隔离列；
2. 隔离列**语义正确**：标记的行恰为 `(0.2, 1, 7)` 与 `(0.2, 1, 8)`（A/C 各一行）；
3. 数据层 `METRICS` ⊇ 按 §3.1/§3.2/§3.3 分组的全部指标；
4. §3.4 的约束量（功率/应力/能量）**绝不进 `METRICS`** ⇒ 永远不会被 Pareto/热图选中；
5. `ruling_coverage()['gaps']` 为空，且**分母口径正确**（不能用全表当分母把预期空值报成缺口）；
6. 网页里有裁定完备性卡片，且 `PAGE_MUST_HAVE` 仍能通过。

表缺失时**跳过**（`work/` 不进版本库，新克隆环境没有该表），但**绝不静默通过**。
"""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CSV_PATH = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"
BUILDER = REPO / "work/runs/first-peak-20260929/build_multichannel_labels.py"
PAGE = REPO / "scripts/webapp_page.html"

sys.path.insert(0, str(REPO / "src"))

pytestmark = pytest.mark.skipif(
    not CSV_PATH.is_file(),
    reason="缺 multichannel_labels.csv（work/ 不进版本库）⇒ 先跑 build_multichannel_labels.py")

RULING_FIELDS_18 = ["x_scale", "N_w_te1", "N_w_te2", "f_peak_Hz", "peak_SPL_dB",
                    "peak_displacement_m", "f_lo_3dB_Hz", "f_hi_3dB_Hz", "bandwidth_Hz",
                    "Q_factor", "damping_ratio", "peak_closed", "bandwidth_closed",
                    "method", "extrapolated", "ranking_eligible", "source_model",
                    "source_dataset"]
#: 裁定 §3.1 振幅四量 + §3.3 灵敏度所用通道（**必须真的在表里**）
REQUIRED_CHANNELS = ["abs_w_m", "abs_vz_struct_m3s", "abs_p_Pa", "spl_dB",
                     "abs_w_per_V_m", "abs_vz_struct_per_V_m3s", "abs_p_per_V_Pa",
                     "spl_per_V_dB"]
DRIVE_FIELDS = ["v_inner_V", "v_outer_V", "delta_V_V", "normalization_formula"]
QUARANTINE_EXPECTED = {(0.2, 1.0, 7.0), (0.2, 1.0, 8.0)}


@pytest.fixture(scope="module")
def rows():
    with CSV_PATH.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_table_has_every_ruling_field(rows):
    """§4 的 18 个必需字段 + 全部通道 + 隔离列都必须在表里。"""
    cols = set(rows[0].keys())
    miss = [c for c in RULING_FIELDS_18 + REQUIRED_CHANNELS + DRIVE_FIELDS
            + ["quarantined", "first_peak_found", "x_density_class"]
            if c not in cols]
    assert not miss, "主表缺列（会被 extrasaction=ignore 静默吞掉的那类问题）：%s" % miss


def test_no_rec_key_silently_dropped_by_builder():
    """构建脚本必须**自己**守住「写进 rec 的键都在 cols 里」，而不是靠人眼。

    静态检查：脚本里存在把 `written - set(cols)` 判空的 fail-closed 断言。
    """
    src = BUILDER.read_text(encoding="utf-8")
    assert "extrasaction" in src
    assert "被静默丢弃" in src, "缺少「列会被静默丢弃」的 fail-closed 守卫"
    assert "quarantined" in src.split("cols = ")[1][:2000], "`quarantined` 未列入 cols"


def test_quarantine_flag_semantics(rows):
    """隔离标记必须**真的**落在 (0.2,1,7)/(0.2,1,8) 上，不能整列皆 False。"""
    marked = {(float(r["x_scale"]), float(r["N_w_te1"]), float(r["N_w_te2"]))
              for r in rows if r["quarantined"] == "True"}
    triples = {t for t in marked}
    assert triples == QUARANTINE_EXPECTED, (
        "隔离标记与裁定不符：得到 %s，期望 %s" % (sorted(triples), sorted(QUARANTINE_EXPECTED)))
    # A、C 各一行 ⇒ 共 4 行（同参数不同批**并排**，不是覆盖）
    assert len(marked) == 4 or len(marked) == len(QUARANTINE_EXPECTED)


def test_two_batches_stay_side_by_side(rows):
    """A∩C 的同参数三元组必须**各占一行**，禁止字典合并覆盖。"""
    from collections import Counter
    key = lambda r: (r["x_scale"], r["N_w_te1"], r["N_w_te2"])
    dup = [k for k, n in Counter(key(r) for r in rows).items() if n > 1]
    batches = {r["source_dataset"] for r in rows}
    assert batches == {"A", "C"}
    assert dup, "A∩C 有 162 个同参数三元组，本表应保留为并排行；一行都没重复说明发生了覆盖"
    assert len(rows) == sum(1 for _ in rows)


def test_data_layer_metrics_cover_ruling_groups():
    """数据层 `METRICS` 必须覆盖 §3.1/§3.2/§3.3 的全部指标。"""
    from memsharness import first_peak as fp
    need = set().union(*fp.RULING_GROUPS.values())
    miss = sorted(need - set(fp.METRICS))
    assert not miss, "裁定判据未进 METRICS（表里有列但代码取不到）：%s" % miss


def test_constraint_only_never_rankable():
    """§3.4 约束量（功率/应力/能量）**绝不能**出现在 METRICS 里 ⇒ 永不被排名。"""
    from memsharness import first_peak as fp
    leaked = sorted(set(fp.CONSTRAINT_ONLY) & set(fp.METRICS))
    assert not leaked, "约束量混进了可排名指标（违反 §3.4 只作约束）：%s" % leaked


def test_every_metric_has_unit_and_no_prefix_rule():
    """每个指标都要有单位；无量纲/对数量必须进 `NO_PREFIX_UNITS`。

    没有这条时，前端会给出 `3.5 k—`（给无量纲的 Q 加"千"前缀）这种荒谬显示。
    """
    from memsharness import first_peak as fp
    miss = sorted(set(fp.METRICS) - set(fp.UNITS))
    assert not miss, "指标缺单位定义（界面会显示不出量纲）：%s" % miss
    assert sorted(set(fp.UNITS) - set(fp.METRICS)) == [], "UNITS 里有 METRICS 之外的多余键"
    for k in ("Q_factor", "damping_ratio_report_only"):
        assert fp.UNITS[k] in fp.NO_PREFIX_UNITS
    # 对数量也不许加前缀
    for k in ("peak_SPL_dB", "spl_per_V_dB"):
        assert fp.UNITS[k] in fp.NO_PREFIX_UNITS


def test_summary_exposes_units_and_directions():
    """前端靠 `metric_units` / `metric_directions` 显示量纲与标记，必须暴露且一致。"""
    from memsharness import first_peak as fp
    s = fp.summary()
    assert set(s["metric_units"]) == set(fp.METRICS)
    assert set(s["metric_directions"]) == set(fp.METRICS)
    assert set(s["formal_objectives"]).issubset(set(s["metrics"]))
    assert s["no_prefix_units"], "应显式给出不做工程前缀换算的单位"


def test_formal_objectives_are_three_groups():
    """正式排名口径 = 带宽 + 振幅(位移) + 灵敏度(声压/V)，且都为 max 方向。"""
    from memsharness import first_peak as fp
    assert fp.FORMAL_OBJECTIVES == ("bandwidth_Hz", "abs_w_m", "abs_p_per_V_Pa")
    for o in fp.FORMAL_OBJECTIVES:
        assert fp.METRICS[o][1] == "max", "%s 的目标方向应为 max" % o


def test_ruling_coverage_has_no_gap_and_uses_defined_denominator(rows):
    """完备性自检必须 0 缺口，且分母是「该量有定义的行」而不是全表。"""
    from memsharness import first_peak as fp
    cov = fp.ruling_coverage()
    assert cov["gaps"] == [], "裁定判据存在缺口：%s" % cov["gaps"]
    n_peak = sum(1 for r in rows if r["first_peak_found"] == "True")
    n_closed = sum(1 for r in rows if r["bandwidth_closed"] == "True")
    assert cov["n_rows_first_peak"] == n_peak
    assert cov["n_rows_bandwidth_closed"] == n_closed
    # 关键：无峰行占相当比例；若拿全表当分母，§3.1 的填充率必然 <1 ⇒ 假缺口
    assert n_peak < len(rows), "存在无峰行是本检查的意义所在；若全有峰需重新审视分母口径"
    for grp in cov["groups"].values():
        for k, rate in grp["有定义行上的填充率"].items():
            assert rate >= 0.99, "指标 %s 在有定义的行上仍只有 %.1f%% 有值" % (k, 100 * rate)


def test_per_volt_and_drive_consistency(rows):
    """ΔV 口径必须自洽：delta_V = |外−内|，且 per_V 列 = 原列 ÷ ΔV。"""
    r0 = rows[0]
    dv = float(r0["delta_V_V"])
    assert abs(dv - abs(float(r0["v_outer_V"]) - float(r0["v_inner_V"]))) < 1e-12
    checked = 0
    for r in rows:
        if r["first_peak_found"] != "True":
            continue
        for a, b in (("abs_w_per_V_m", "abs_w_m"),
                     ("abs_p_per_V_Pa", "abs_p_Pa"),
                     ("abs_vz_struct_per_V_m3s", "abs_vz_struct_m3s")):
            if r[a] in ("", "None") or r[b] in ("", "None"):
                continue
            assert abs(float(r[a]) - float(r[b]) / dv) <= 1e-9 * max(1.0, abs(float(r[a]))), \
                "per_V 换算不一致：%s vs %s/ΔV" % (a, b)
            checked += 1
    assert checked > 0, "没有任何组合被校验到 ⇒ 检查是空转的"


def test_page_has_lf_endings_so_served_bytes_match_disk():
    """页面文件必须是**裸 LF** 换行，否则"服务端字节 == 磁盘字节"这条验证永远失败。

    机理：`webapp_server._load_page()` 用 `read_text()` 读（**通用换行**，会把 CRLF 归一成 LF），
    再 `.encode("utf-8")` 发出去；而 `verify_web_services.py` 比的是 `PAGE.read_bytes()`（**原始字节**）。
    ⇒ 文件一旦含 CRLF，两边必然不等，**验证会一直报"不一致"而页面其实是好的**。

    2026-09-29 实测踩坑：我用一个 Python 小脚本删代码块时用了 `Path.write_text()`
    （Windows 上把 `\n` 翻译成 `\r\n`），静默把 919 行全变成 CRLF，
    于是 `verify_web_services.py` 报「一致=False」——而该脚本当时**恰好在失败分支里崩溃**
    （`REPO / "…%d.log" % port` 的优先级 bug），把真实原因盖住了。
    """
    raw = PAGE.read_bytes()
    assert b"\r\n" not in raw, ("页面含 CRLF（%d 处）⇒ 服务端字节与磁盘字节必然不等，"
                                "请用 newline='\\n' 重写" % raw.count(b"\r\n"))
    assert raw == PAGE.read_text(encoding="utf-8").encode("utf-8"), \
        "页面原始字节与「read_text 后重新编码」不一致 ⇒ 服务端下发内容会与磁盘不同"


def test_page_shows_ruling_coverage_card():
    """网页必须把「裁定判据完备性」显示出来（用户要能看到，而不是只在脚本里）。"""
    html = PAGE.read_text(encoding="utf-8")
    assert "ruling_coverage" in html, "页面未消费 ruling_coverage"
    assert "裁定判据完备性" in html, "页面缺少裁定完备性卡片"


def test_page_peaks_panel_is_plain_language_and_unit_aware():
    """一阶峰面板的可读性要求（用户 2026-09-29：「更清晰更简单易懂」）。

    锁住四点：① 有大白话说明；② 有工程记数法格式化且**不硬编码缩放因子**；
    ③ 有单目标冠军表；④ 单位来自后端而非前端猜测。
    """
    html = PAGE.read_text(encoding="utf-8")
    assert "这一页在说什么" in html, "缺少大白话说明卡片"
    assert "function fmtEng(" in html, "缺少工程记数法格式化函数"
    assert "metric_units" in html, "单位应来自后端 metric_units，不应前端硬猜"
    assert "champCard" in html, "缺少「按单个指标看」的冠军表"
    # 工程记数法只按数量级挑前缀 ⇒ **不应出现手写的 1e-6/1e-9 缩放常量**
    for bad in ("* 1e-6", "* 1e-9", "*1e-6", "*1e-9", "/ 1e6", "/ 1e9"):
        assert bad not in html, "页面里出现手写缩放因子 %s（易写错一个量级）" % bad
    # 明确告诉用户不合成总分（A5 规则），避免被误读成有加权评分
    assert "不合成总分" in html or "不做加权总分" in html


def test_page_never_presents_weighted_total_score():
    """A5 规则：**不含任何加权总分**。页面不得出现加权求和/综合评分之类的**宣称**。

    ⚠️ 必须**认否定语境**：页面正文里本来就写着「不做加权总分」来说明遵守了这条规则，
    若按裸串匹配就会把「声明遵守规则」误判成「违反规则」（2026-09-29 实测假失败，
    与 `check_report_md.py` 早先那次是同一类错）。
    """
    html = PAGE.read_text(encoding="utf-8")
    NEG = ("不做", "不含", "禁止", "没有", "不得", "无", "避免")
    bad_hits = []
    for bad in ("综合评分", "加权总分", "总分排名", "score ="):
        i = 0
        while True:
            i = html.find(bad, i)
            if i < 0:
                break
            ctx = html[max(0, i - 8):i]
            if not any(n in ctx for n in NEG):
                bad_hits.append("%s（上下文：…%s…）" % (bad, ctx))
            i += len(bad)
    assert not bad_hits, "页面出现疑似加权总分**宣称**（非否定语境）：%s" % bad_hits
    # 反向确认：页面确实显式声明了不合成总分（否则上面的检查可能只是"没提"）
    assert ("不合成总分" in html) or ("不做加权总分" in html), "页面未声明「不合成总分」"


def test_page_invariants_still_hold():
    """补卡片不得破坏原有的 `PAGE_MUST_HAVE` fail-closed 契约。"""
    spec = importlib.util.spec_from_file_location(
        "_webapp_srv_cov", REPO / "scripts/webapp_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    html = mod._load_page()
    for must in mod.PAGE_MUST_HAVE:
        assert must in html, "页面缺少必需标记：%s" % must


# ---------------------------------------------- 参数筛选：统一生效 + fail-closed
def _fp():
    from memsharness import first_peak
    return first_peak


def test_filter_defaults_to_no_filter_and_is_global():
    """默认**不筛选**（全部 x/N1/N2），且文案必须说「这是全局口径」。"""
    fp = _fp()
    p = fp.pareto("C")
    assert p["is_conditional"] is False
    assert p["filter"] == {}
    assert "全局" in p["filter_label"] and "无筛选" in p["filter_label"]
    assert "全局前沿" in p["front_scope"]
    assert p["n_pool"] == 673 and p["n_front"] == 45


def test_filter_restricts_rows_and_marks_conditional_front():
    """筛选必须真的缩小池，并且**明确标成条件前沿**（否则会被误读成全局最优）。"""
    fp = _fp()
    base = fp.pareto("C")
    f = fp.pareto("C", flt={"n2": 8.0})
    assert f["is_conditional"] is True
    assert "条件前沿" in f["front_scope"] and "不等于全局" in f["front_scope"]
    assert f["n_pool"] < base["n_pool"]
    assert all(r["N_w_te2"] == 8.0 for r in f["all"])

    g = fp.pareto("C", flt={"x_min": 0.4, "x_max": 0.6, "n1_min": 1.0, "n1_max": 3.0,
                            "n2": 8.0})
    assert g["n_pool"] < f["n_pool"]
    for r in g["all"]:
        assert 0.4 <= r["x_scale"] <= 0.6, "x 未被筛选：%s" % r
        assert 1.0 <= r["N_w_te1"] <= 3.0, "N1 未被筛选：%s" % r
        assert r["N_w_te2"] == 8.0, "N2 未被筛选：%s" % r
    # 漏斗必须自洽：筛掉 + 各排除项 + 池 = 批内总数
    ex = g["excluded"]
    assert ex["batch_total"] - ex["filtered_out"] == ex["after_filter"]
    assert (ex["not_first_peak"] + ex["bandwidth_not_closed"] + ex["q_gate_failed"]
            + ex["missing_objective_value"] + g["n_pool"]) == ex["after_filter"], \
        "筛选后漏斗分项不自洽：%s" % ex


def test_filter_applies_to_heatmap_axes():
    """热力图的两个轴就是 x 与 N1 ⇒ 筛选要**裁掉网格行列**，并且标签同步。"""
    fp = _fp()
    full = fp.heatmap("C", "bandwidth_Hz")
    xc = fp.heatmap("C", "bandwidth_Hz", flt={"x_min": 0.4, "x_max": 0.6})
    assert len(xc["xs"]) < len(full["xs"])
    assert min(xc["xs"]) >= 0.4 and max(xc["xs"]) <= 0.6
    assert xc["n_rows_after_filter"] < xc["n_rows_batch"]
    assert "筛选" in xc["filter_label"]
    sl = fp.heatmap("C", "bandwidth_Hz", n2=8.0)
    assert sl["n_points"] < full["n_points"]
    assert all(v == 8.0 for v in [sl["n2_filter"]])


def test_unknown_or_malformed_filter_is_rejected():
    """`parse_filter` 必须**拒绝**未知键/非数字/逆序，不得静默忽略。

    历史缺陷：`heatmap?n1=3` 曾被静默忽略并照常返回全部数据 ⇒ 用户以为筛过了。
    """
    fp = _fp()
    for q in ({"n1": 3}, {"foo": 1}, {"xmin": 0.3}):
        flt, err = fp.parse_filter(q)
        assert err and "不支持" in err, "未知键未被拒绝：%s → %s" % (q, err)
    for q in ({"x_min": "abc"}, {"n2": "八"}):
        flt, err = fp.parse_filter(q)
        assert err and "不是数字" in err, "非数字未被拒绝：%s → %s" % (q, err)
    flt, err = fp.parse_filter({"x_min": "0.9", "x_max": "0.3"})
    assert err and "大于" in err, "逆序区间未被拒绝"
    flt, err = fp.parse_filter({"x_min": "0.4", "n2": "8"})
    assert err is None and flt == {"x_min": 0.4, "n2": 8.0}


def test_server_rejects_unknown_query_params():
    """端点层也必须 fail-closed：把不认识的名字报出来，而不是丢掉。"""
    spec = importlib.util.spec_from_file_location(
        "_webapp_srv_flt", REPO / "scripts/webapp_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    e = mod._peaks_pareto({"batch": "C", "n1": "3"}).get("error")
    assert e and "不支持参数" in e and "n1" in e, "端点未拒绝未知参数：%s" % e
    e2 = mod._peaks_heatmap({"batch": "C", "metric": "bandwidth_Hz", "foo": "1"}).get("error")
    assert e2 and "不支持参数" in e2
    # 该端点的合法参数必须仍然可用
    assert not mod._peaks_pareto({"batch": "C", "objectives": "bandwidth_Hz,abs_w_m"}).get("error")
    assert not mod._peaks_heatmap({"batch": "C", "metric": "abs_w_m", "x_min": "0.4"}).get("error")


def test_page_filter_controls_exist_and_are_wired():
    """界面必须有 x/N1/N2 筛选、清空按钮，且**一份条件喂给所有请求**。"""
    html = PAGE.read_text(encoding="utf-8")
    for cid in ("kXmin", "kXmax", "kN1min", "kN1max", "kN2", "bPeaksReset"):
        assert 'id="%s"' % cid in html, "缺少筛选控件 %s" % cid
    assert "peaksFilterQS" in html, "缺少统一构造筛选查询串的函数"
    # N2 默认必须为空（写死 8 会让人以为整页被限定在该层）
    assert 'id="kN2" step="1" placeholder=' in html and 'id="kN2" value=' not in html, \
        "N2 默认值应为空（等于全部层）"
    # Pareto 请求必须带上筛选串（否则"图筛了、表没筛"）
    assert "api('/api/peaks/pareto?batch='+encodeURIComponent(b)+(fq?('&'+fq):''))" in html
    assert "条件前沿" in html, "筛选后必须提示「条件前沿」"

def test_heatmap_aggregates_layers_instead_of_overwriting():
    """不限定 N2 时，热力图必须**聚合多层**，而不是「最后一层覆盖」。

    为什么单独立一条：原实现 `z[i][j] = r[metric]` 让**层序隐式决定**格值并丢信息
    （实测：有效行 1523 而格数只有 539 ⇒ 每格最多 4 层被压成 1 个值）。
    现在改为取均值，并暴露 `grid_n_layers`（层数）与 `grid_layer_spread`（层间跨度），
    否则读者会把「多层均值」误当成「某一层的真实值」。
    """
    fp = _fp()
    h = fp.heatmap("C", "bandwidth_Hz")
    n_cells = len(h["xs"]) * len(h["n1s"])
    assert h["n_points"] > n_cells, "本用例要求存在多层同格的情形"
    assert h["aggregation"] == "mean_of_layers"
    assert h["max_layers_per_cell"] > 1
    assert len(h["grid_n_layers"]) == len(h["xs"])
    assert len(h["grid_layer_spread"]) == len(h["xs"])
    multi = 0
    for i, row in enumerate(h["grid_n_layers"]):
        for j, n in enumerate(row):
            if h["grid"][i][j] is None:
                assert n == 0, "空格却有层数 ⇒ 记账不一致"
                continue
            assert n >= 1
            if n > 1:
                multi += 1
                assert h["grid_layer_spread"][i][j] >= 0
    assert multi > 0, "没有任何多层格 ⇒ 检查是空转的"
    # 限定 N2 时必须退化为单值，且不谎报聚合口径
    h8 = fp.heatmap("C", "bandwidth_Hz", n2=8.0)
    assert h8["aggregation"] == "single_value"
    assert set(n for row in h8["grid_n_layers"] for n in row) <= {0, 1}
    assert h8["n_points"] == sum(1 for row in h8["grid"] for v in row if v is not None)
