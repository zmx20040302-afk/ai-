# -*- coding: utf-8 -*-
r"""te2_9 四件套解析器的**表头双语别名**用例（含四类夹具与投毒）。

背景（2026-10-09 实测缺陷，两处）
--------------------------------
1. **列名写死中文**：`scripts/parse_te29_v1.py` 曾以 `总声压级 (dB)` / `宽度 (Hz)` / `Q 因子` /
   `阻尼比` 作为唯一定位串。服务器 COMSOL 语言已切到 `en_US` ⇒ 我们的导出表头是**英文**
   （`Total sound pressure level (dB), Point: …`），列定位处直接抛异常
   （`profile_te29_export.py` 因此 rc=1）。
2. **更隐蔽的一处**：英文表头按「2 个以上空格」切会**并吞列**。COMSOL 按固定列宽排表头，
   列名一溢出就与下一个列名只隔 **1 个空格**。实测英文 `Table_9.txt` 表头切出 **12** 段、
   而数据行是 **15** 列（Bandwidth 是 4 段 vs 5 列）⇒ 若不改切分方式，即便换成英文别名，
   索引仍是错的。

本文件锁住四件事
----------------
① **中文表头夹具**可解析（**向后兼容**：2026-09-22 的 v2 中文表就是这种表头）；
② **英文表头夹具**可解析，且夹具**确实带着「并吞列」这个坑**（用 `naive_split_fields` 断言）；
   中英两套夹具喂同一批数字 ⇒ `cells/points` **逐字段相同**（双语等价，不只是「能跑」）；
③ **投毒**：第三种语言（整表俄文）/ 错拼列名 ⇒ **必须 fail-closed 抛 `ValueError`**
   （**不是**静默取 0 行），且 `profile_te29_export` 把同一夹具判成 `ready_for_parse=False`、rc=4；
④ **坐标后缀形态差异**（`, Point: (0, 0, -1E-5)` / `,Point:(0,0,-1E-5)` / `, 点: …` / `,点:…`）
   四种写法**都能命中**（后缀按前缀正则匹配，不写死整串）。

表头字面量的来源（**只读复制**，未改动任何产物）
---------------------------------------------
`EN_T9_HEADER` / `EN_BW_HEADER` 逐字取自英文本轮导出
`work/runs/te29-freq5-50-server-20261009/out/cell_te2_9_test_scal_0.2-1_0.01_freq5-50_v1_chunkedv1/`，
`ZH_T9_HEADER` / `ZH_BW_HEADER` 逐字取自 2026-09-22 的 v2 中文参照导出
`work/runs/remote-exported-v2-20260922/exported_results_v2/cell_te2_9_test_v2_20260922_195327416_001/`。
把真实表头行**抄进夹具**是为了让「英文单空格并入」这个坑在用例里真实存在；
**数据行是本文件合成的**（合成规则写在 `_t9_rows()` / `_bw_rows()`），不是产物数值。
另有 `test_embedded_*_header_matches_real_product_bytes`：产物在位时**逐字复核**上述字面量。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import parse_te29_v1 as P            # noqa: E402
import profile_te29_export as PROF   # noqa: E402
import regress_te29_vs_v2 as RG      # noqa: E402

# --------------------------------------------------------------------------- 真实表头字面量
EN_T9_HEADER = (" x_scale                                         N_w_te1                                           N_w_te2                                           freq (Hz)                                         real(acpr.v_tz) (m/s), Point: (0, 0, -1E-5)       imag(acpr.v_tz) (m/s), Point: (0, 0, -1E-5)       Total acoustic velocity, z-component (m/s), Point: (0, 0, -1E-5) real(acpr.p_t) (Pa), Point: (0, 0, -1E-5)         imag(acpr.p_t) (Pa), Point: (0, 0, -1E-5)         Total acoustic pressure (Pa), Point: (0, 0, -1E-5) Total acoustic pressure, RMS (Pa), Point: (0, 0, -1E-5) N_w_te1, Point: (0, 0, -1E-5)                     N_w_te2, Point: (0, 0, -1E-5)                     x_scale, Point: (0, 0, -1E-5)                     Total sound pressure level (dB), Point: (0, 0, -1E-5)")  # noqa: E501
EN_BW_HEADER = (" freq (Hz)              Total sound pressure level (dB) Width (Hz)               Q-factor                 Damping ratio")  # noqa: E501
ZH_T9_HEADER = (" x_scale                                         N_w_te1                                           N_w_te2                                           freq (Hz)                                         real(acpr.v_tz) (m/s), 点: (0, 0, -1E-5)           imag(acpr.v_tz) (m/s), 点: (0, 0, -1E-5)           总声速，z 分量 (m/s), 点: (0, 0, -1E-5)                  real(acpr.p_t) (Pa), 点: (0, 0, -1E-5)             imag(acpr.p_t) (Pa), 点: (0, 0, -1E-5)             总声压 (Pa), 点: (0, 0, -1E-5)                        总声压，均方根 (Pa), 点: (0, 0, -1E-5)                    N_w_te1, 点: (0, 0, -1E-5)                         N_w_te2, 点: (0, 0, -1E-5)                         x_scale, 点: (0, 0, -1E-5)                         总声压级 (dB), 点: (0, 0, -1E-5)")  # noqa: E501
ZH_BW_HEADER = (" freq (Hz)              总声压级 (dB)                宽度 (Hz)                  Q 因子                     阻尼比")  # noqa: E501

REAL_EN_DIR = (REPO / "work/runs/te29-freq5-50-server-20261009/out"
               / "cell_te2_9_test_scal_0.2-1_0.01_freq5-50_v1_chunkedv1")
REAL_ZH_DIR = (REPO / "work/runs/remote-exported-v2-20260922/exported_results_v2"
               / "cell_te2_9_test_v2_20260922_195327416_001")

# --------------------------------------------------------------------------- 合成夹具的数值
FREQS = [round(5.0e6 + 0.5e6 * k, 6) for k in range(7)]          # 5.0–8.0 MHz 步长 0.5
COMBOS = ((0.2, 1, 9), (0.2, 2, 9), (0.3, 1, 9), (0.3, 2, 9))
PEAK_IDX = (3, 3, 3, 6)                                          # 末格峰在 8.0 MHz（= 扫描上限）
PEAK_SPL = (100.0, 101.0, 102.0, 103.0)
# (f_lo, f_hi, width, Q)；末格 f_hi = 8.0 MHz ⇒ 带宽上截止点 == 端点（截断）
BANDS = ((5.5e6, 7.5e6, 2.0e6, 3.0), (5.5e6, 7.5e6, 2.0e6, 3.0),
         (5.5e6, 7.5e6, 2.0e6, 3.0), (7.5e6, 8.0e6, 0.5e6, 16.0))

EXPECT = {"n_combos": 4, "n_points": 28, "n_freq": 7,
          "n_peak_at_scan_endpoint": 1, "n_bw_upper_cutoff_at_endpoint": 1,
          "n_usable": 3, "n_Q_decidable": 4, "n_Q_pass_2p5_3p5": 3,
          "bw_matched": 4, "bw_unmatched": 0}


def _t9_rows():
    """合成 Table_9 数据行：15 列 = `x, N1, N2, freq, 10 个填充列, SPL`。"""
    rows = []
    for ci, (x, n1, n2) in enumerate(COMBOS):
        for k, f in enumerate(FREQS):
            spl = PEAK_SPL[ci] - 1.0 * abs(k - PEAK_IDX[ci])
            rows.append([x, n1, n2, f] + [0.0] * 10 + [spl])
    return rows


def _bw_rows():
    """合成 Bandwidth 数据行：一条 −3 dB 带 = 两行（下截止点 / 上截止点）。"""
    rows = []
    for ci in range(len(COMBOS)):
        f_lo, f_hi, width, q = BANDS[ci]
        spl = PEAK_SPL[ci] - 3.0                     # 桥接键：peak_spl == bw_spl + 3.0
        vals = [spl, width, q, 1.0 / (2.0 * q)]
        rows.append([f_lo] + vals)
        rows.append([f_hi] + vals)
    return rows


def _table_text(model: str, table_label: str, header_body: str, rows) -> str:
    out = ["% Model:              " + model,
           "% Version:            COMSOL 6.4.0.293",
           "% Date:               Oct 9 2026, 15:03",
           "% Table:              " + table_label,
           "%" + header_body]
    for r in rows:
        out.append(" ".join("%.10g" % v if isinstance(v, float) else str(v) for v in r))
    return "\n".join(out) + "\n"


def _write_cell(root: pathlib.Path, t9_header: str, bw_header: str) -> pathlib.Path:
    """按给定表头落一个**合成** cell 目录（Table_9.txt + Bandwidth.txt）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "Table_9.txt").write_text(
        _table_text("fixture.mph", "Table 9 - ", t9_header, _t9_rows()), encoding="utf-8")
    (root / "Bandwidth.txt").write_text(
        _table_text("fixture.mph", "Cutoff Points - Graph marker", bw_header, _bw_rows()),
        encoding="utf-8")
    return root


def _parse(cell: pathlib.Path) -> dict:
    return P.parse_export(cell, strict_grid=False, expect_combos=None, expect_nfreq=None)


def _assert_census(diag: dict, expect_idx_spl: int = 14) -> None:
    for k, v in EXPECT.items():
        assert diag[k] == v, (k, diag[k], v)
    assert diag["freq_lo_Hz"] == FREQS[0] and diag["freq_hi_Hz"] == FREQS[-1]
    assert diag["n_table9_rows_skipped"] == 0, diag["n_table9_rows_skipped"]
    assert diag["n_normalization_collisions"] == 0


def _cell_rows_without_cell_field(res: dict):
    return [{k: v for k, v in c.items() if k != "cell"} for c in res["cells"]], \
           [{k: v for k, v in p.items() if k != "cell"} for p in res["points"]]


# ============================================================ ① 中文表头夹具（向后兼容）
def test_zh_header_fixture_parses(tmp_path):
    res = _parse(_write_cell(tmp_path / "zh", ZH_T9_HEADER, ZH_BW_HEADER))
    _assert_census(res["diag"])
    hl = res["diag"]["header_locate"]
    assert hl["Table_9.txt"]["language"] == "zh" and hl["Table_9.txt"]["n_localized_zh_hits"] == 4
    assert hl["Bandwidth.txt"]["language"] == "zh"
    assert hl["Table_9.txt"]["index"]["spl_dB"] == 14
    assert hl["Bandwidth.txt"]["index"] == {"freq_Hz": 0, "spl_dB": 1, "width_Hz": 2,
                                            "Q": 3, "zeta": 4}


# ============================================================ ② 英文表头夹具（带「并吞列」坑）
def test_en_header_fixture_parses(tmp_path):
    res = _parse(_write_cell(tmp_path / "en", EN_T9_HEADER, EN_BW_HEADER))
    _assert_census(res["diag"])
    hl = res["diag"]["header_locate"]
    assert hl["Table_9.txt"]["language"] == "en" and hl["Table_9.txt"]["n_localized_en_hits"] == 4
    assert hl["Table_9.txt"]["index"]["spl_dB"] == 14
    assert hl["Bandwidth.txt"]["index"] == {"freq_Hz": 0, "spl_dB": 1, "width_Hz": 2,
                                            "Q": 3, "zeta": 4}


def test_en_fixture_really_carries_the_column_merge_trap(tmp_path):
    """英文表头按空白切会**少**于真实列数 —— 夹具必须保留这个坑，否则用例是空转的。"""
    res = _parse(_write_cell(tmp_path / "en", EN_T9_HEADER, EN_BW_HEADER))
    hl = res["diag"]["header_locate"]
    for name, true_cols, naive in (("Table_9.txt", 15, 12), ("Bandwidth.txt", 5, 4)):
        assert hl[name]["n_data_cols"] == true_cols
        assert hl[name]["n_fields"] == true_cols
        assert hl[name]["naive_split_fields"] == naive < true_cols, (name, hl[name])
    assert P.naive_header_field_count(EN_T9_HEADER) == 12
    assert P.naive_header_field_count(ZH_T9_HEADER) == 15      # 中文表头恰好切得动


def test_zh_and_en_fixtures_are_numerically_identical(tmp_path):
    """同一批数字、两套表头 ⇒ `cells`/`points` 逐字段相同（双语等价，不只是「能跑起来」）。"""
    zh = _parse(_write_cell(tmp_path / "zh", ZH_T9_HEADER, ZH_BW_HEADER))
    en = _parse(_write_cell(tmp_path / "en", EN_T9_HEADER, EN_BW_HEADER))
    assert _cell_rows_without_cell_field(zh) == _cell_rows_without_cell_field(en)


# ============================================================ ④ 坐标后缀形态（4 种写法）
SUFFIX_VARIANTS = (
    ("en_suffix_space", EN_T9_HEADER, ", Point: (0, 0, -1E-5)", ", Point: (0, 0, -1E-5)"),
    ("en_suffix_nospace", EN_T9_HEADER, ", Point: (0, 0, -1E-5)", ",Point:(0,0,-1E-5)"),
    ("zh_suffix_space", ZH_T9_HEADER, ", 点: (0, 0, -1E-5)", ", 点: (0, 0, -1E-5)"),
    ("zh_suffix_nospace", ZH_T9_HEADER, ", 点: (0, 0, -1E-5)", ",点:(0,0,-1E-5)"),
)


@pytest.mark.parametrize("tag,base,old,new", SUFFIX_VARIANTS,
                         ids=[v[0] for v in SUFFIX_VARIANTS])
def test_coordinate_suffix_variants_all_match(tmp_path, tag, base, old, new):
    """`, Point: (0, 0, -1E-5)` 与 `,点:(0,0,-1E-5)` 这类差异都只动后缀，必须都命中同一组列号。"""
    assert old in base, (tag, "变体锚点不在表头里 ⇒ 用例写错了")
    header = base.replace(old, new)
    bw = EN_BW_HEADER if base == EN_T9_HEADER else ZH_BW_HEADER
    res = _parse(_write_cell(tmp_path / tag, header, bw))
    _assert_census(res["diag"])
    idx = res["diag"]["header_locate"]["Table_9.txt"]["index"]
    assert idx["spl_dB"] == 14 and idx["x_scale"] == 0 and idx["N_w_te1"] == 1


def test_nospace_suffix_really_differs_from_real_header(tmp_path):
    """反侧自证：把后缀改成无空格写法后，表头字节确实变了（否则上一条用例是空转的）。"""
    cooked = EN_T9_HEADER.replace(", Point: (0, 0, -1E-5)", ",Point:(0,0,-1E-5)")
    assert cooked != EN_T9_HEADER
    assert ", Point:" not in cooked and ",Point:" in cooked
    res = _parse(_write_cell(tmp_path / "en_nospace", cooked, EN_BW_HEADER))
    assert res["diag"]["n_points"] == EXPECT["n_points"]


# ============================================================ ③ 投毒：必须 fail-closed
RU_T9_HEADER = (EN_T9_HEADER
                .replace("x_scale", "масштаб_x")
                .replace("N_w_te1", "Н_обм_te1")
                .replace("N_w_te2", "Н_обм_te2")
                .replace("freq (Hz)", "частота (Гц)")
                .replace("real(acpr.v_tz) (m/s)", "действ(acpr.v_tz) (м/с)")
                .replace("imag(acpr.v_tz) (m/s)", "мним(acpr.v_tz) (м/с)")
                .replace("Total acoustic velocity, z-component (m/s)",
                         "Суммарная акустическая скорость, z-компонента (м/с)")
                .replace("real(acpr.p_t) (Pa)", "действ(acpr.p_t) (Па)")
                .replace("imag(acpr.p_t) (Pa)", "мним(acpr.p_t) (Па)")
                .replace("Total acoustic pressure, RMS (Pa)",
                         "Суммарное акустическое давление, СКЗ (Па)")
                .replace("Total acoustic pressure (Pa)", "Суммарное акустическое давление (Па)")
                .replace("Total sound pressure level (dB)",
                         "Суммарный уровень звукового давления (дБ)"))

RU_BW_HEADER = (EN_BW_HEADER
                .replace("freq (Hz)", "частота (Гц)")
                .replace("Total sound pressure level (dB)", "Суммарный уровень звукового давления (дБ)")
                .replace("Width (Hz)", "Ширина (Гц)")
                .replace("Q-factor", "Добротность")
                .replace("Damping ratio", "Коэффициент затухания"))

MISSPELLED_T9_HEADER = EN_T9_HEADER.replace("Total sound pressure level (dB)",
                                            "Total sound pressure leval (dB)")
AMBIGUOUS_T9_HEADER = EN_T9_HEADER.replace("Total acoustic pressure, RMS (Pa)",
                                           "Total sound pressure level (dB)")


def test_poison_third_language_is_refused_not_silently_empty(tmp_path):
    """整表第三种语言（俄文）⇒ **零命中** ⇒ 抛错；绝不静默返回 0 行。"""
    cell = _write_cell(tmp_path / "ru", RU_T9_HEADER, RU_BW_HEADER)
    with pytest.raises(ValueError) as ei:
        _parse(cell)
    msg = str(ei.value)
    assert "零命中" in msg and "fail-closed" in msg, msg
    assert "Table_9.txt" in msg


def test_poison_bandwidth_third_language_also_refused(tmp_path):
    """`Table_9.txt` 正常、只有 `Bandwidth.txt` 是第三语言 ⇒ 同样抛错（不静默取 0 级）。"""
    cell = _write_cell(tmp_path / "ru_bw", EN_T9_HEADER, RU_BW_HEADER)
    with pytest.raises(ValueError) as ei:
        _parse(cell)
    msg = str(ei.value)
    assert "Bandwidth.txt" in msg and "fail-closed" in msg, msg


def test_poison_misspelled_column_is_refused(tmp_path):
    """错拼一个列名（`level` → `leval`）⇒ 别名表解释不了 ⇒ 抛错。"""
    cell = _write_cell(tmp_path / "typo", MISSPELLED_T9_HEADER, EN_BW_HEADER)
    with pytest.raises(ValueError) as ei:
        _parse(cell)
    msg = str(ei.value)
    assert "解释不了" in msg and "fail-closed" in msg, msg


def test_poison_ambiguous_column_is_refused(tmp_path):
    """把另一个列名也写成 SPL ⇒ 同一 canonical 两个候选 ⇒ **歧义** ⇒ 抛错（不取第一个像的）。"""
    cell = _write_cell(tmp_path / "amb", AMBIGUOUS_T9_HEADER, EN_BW_HEADER)
    with pytest.raises(ValueError) as ei:
        _parse(cell)
    msg = str(ei.value)
    assert "歧义" in msg and "fail-closed" in msg, msg


def test_poison_is_refused_by_profile_with_rc4(tmp_path):
    """四件套入口同样 fail-closed：`profile_te29_export` 判 `ready_for_parse=False`、rc=4。"""
    root = tmp_path / "run"
    _write_cell(root / "cell_x", RU_T9_HEADER, RU_BW_HEADER)
    (root / "output_manifest.tsv").write_text("sha256\tsize_bytes\tfile_path\n", encoding="utf-8")
    code, rep = PROF.profile(root)
    assert code == 4
    assert rep["ready_for_parse"] is False
    assert any("fail-closed" in p for p in rep["problems"]), rep["problems"]


@pytest.mark.skipif(not (REAL_ZH_DIR / "Table_9.txt").is_file(),
                    reason="真实 v2 中文参照导出不在本机（work/ 不进版本库）")
def test_regress_fails_closed_on_poisoned_new_export(tmp_path):
    """回归靶在「新导出表头无法解释」时 rc=4，且**不产出**任何比较数字。"""
    cell = _write_cell(tmp_path / "ru", RU_T9_HEADER, RU_BW_HEADER)
    code, rep = RG.run(cell, REAL_ZH_DIR, RG.V2_LABELS_DEFAULT, 1e-3, None, None, None, True)
    assert code == 4, rep
    assert "fail-closed" in rep["error"], rep["error"]
    assert "regression" not in rep


# ============================================================ 夹具字面量的真实性复核（只读）
def _first_header_body(path: pathlib.Path) -> str:
    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            if line.startswith("%") and not P.META_RE.match(line.strip()):
                return line.lstrip()[1:].rstrip("\n").rstrip("\r")
    raise AssertionError("没有表头行：%s" % path)


@pytest.mark.skipif(not (REAL_EN_DIR / "Table_9.txt").is_file(),
                    reason="真实英文本轮导出不在本机（work/ 不进版本库）")
def test_embedded_en_header_matches_real_product_bytes():
    assert _first_header_body(REAL_EN_DIR / "Table_9.txt") == EN_T9_HEADER
    assert _first_header_body(REAL_EN_DIR / "Bandwidth.txt") == EN_BW_HEADER


@pytest.mark.skipif(not (REAL_ZH_DIR / "Table_9.txt").is_file(),
                    reason="真实 v2 中文参照导出不在本机（work/ 不进版本库）")
def test_embedded_zh_header_matches_real_product_bytes():
    assert _first_header_body(REAL_ZH_DIR / "Table_9.txt") == ZH_T9_HEADER
    assert _first_header_body(REAL_ZH_DIR / "Bandwidth.txt") == ZH_BW_HEADER


# ============================================================ 真实中文旧产物仍可解析（向后兼容）
@pytest.mark.skipif(not (REAL_ZH_DIR / "Table_9.txt").is_file(),
                    reason="真实 v2 中文参照导出不在本机（work/ 不进版本库）")
def test_real_v2_chinese_export_still_parses_with_registered_profile():
    """**向后兼容的硬证据**：2026-09-22 的中文表解析出的剖面 === 已登记剖面（80/28/34/46/32/11）。"""
    res = _parse(REAL_ZH_DIR)
    d = res["diag"]
    assert d["header_locate"]["Table_9.txt"]["language"] == "zh"
    for k, v in (("n_combos", 80), ("n_peak_at_scan_endpoint", 28),
                 ("n_bw_upper_cutoff_at_endpoint", 34), ("n_usable", 46),
                 ("n_Q_decidable_among_usable", 32), ("n_Q_pass_2p5_3p5", 11)):
        assert d[k] == v, (k, d[k], v)
    assert d["n_points"] == 80 * 61
