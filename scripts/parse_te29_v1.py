# -*- coding: utf-8 -*-
r"""te2_9 新导出（v1：648 组合 × 91 频点，5–50 MHz）解析器 —— **器械**，产物到位即可运行。

用途
----
把「服务器上 `cell_te2_9_…_freq5-50_v1.mph` 的只读导出目录」变成两张结构化表：

* `te29_cells.csv`  —— **每组合一行**（宽表）；
* `te29_points.csv` —— **每组合×频点一行**（长表，供逐点回归比对）；
* `te29_parse_summary.json` —— 规模/网格/歧义/可判定分母等全部计数（不写数字的地方一律写 null）。

本脚本**不求解、不写任何既有产物**；只读输入目录，输出只落 `--out-dir`。

关键约定（与已注册导出器 `scripts/extract_v2_labels.py` 保持一致，便于与 v2 同口径比对）
-------------------------------------------------------------------------------
1. COMSOL 表的**表头本身是 `%` 行**（`% x_scale   N_w_te1 …`）；数据行按**空白**切分；
   元信息行形如 `% Model: …`，用前缀排除。
   ⚠️ **表头不能按「2 个以上空格」切分**（本仓 2026-10-09 实测缺陷）：COMSOL 按**固定列宽 50**
   排表头，列名一旦长于列宽就**溢出**到下一列、与下一个列名之间**只剩 1 个空格**。
   实测英文 `Table_9.txt` 表头按 `\s{2,}` 只切出 **12** 段，而数据行是 **15** 列（列 7/8/10
   被并吞）⇒ 索引整体错位。因此本脚本改用**别名扫描**（见下），不依赖分隔符宽度。
2. **列名双语别名 + fail-closed 定位**（`locate_columns()`）：表头里出现的每个列名必须能被
   **别名表**解释（中/英两套），且解析出的字段数 **必须等于**数据行的列数，
   字段之间不得残留别名表解释不了的非空白文本。命中 **0 个**或**多个候选（歧义）**
   ⇒ **抛 `ValueError`**，绝不「取第一个像的」。列名后的坐标后缀
   （`, 点: (0, 0, -1E-5)` / `, Point: (0, 0, -1E-5)` / `,Point:(0,0,-1E-5)`）按
   **前缀正则**匹配，**不写死整串**，故中英与有无空格都能命中。
3. **组合键做 ulp 归一化**：`(round(x_scale,6), round(N_w_te1,6), round(N_w_te2,6))`，
   否则浮点原样串会把 `0.30000000000000004` 与 `0.3` 当成两个组合（本轮实测教训：
   不归一化会把 83 误报成 117）。**归一化键与原始串同时保留**（`*_raw` 列）。
4. `Bandwidth.txt` 的 **SPL 列 = 峰值 SPL − 3.0 dB**（−3 dB 电平本身），这是把截断 level
   挂回组合的**桥接键**：`round(bw_spl + 3.0, 9) == round(peak_spl, 9)`。
5. **两个原始标志必须原样保留**，派生 `usable` 不得替代它们：
   * `peak_at_scan_endpoint`     = `|peak_freq − f_scan_hi| < 1 Hz`（峰值右删失）
   * `bw_upper_cutoff_at_endpoint` = `|bw_f_hi − f_scan_hi| < 1 Hz`（带宽/Q/阻尼比被截断）
   * `usable = 非 peak_at_scan_endpoint 且 非 bw_upper_cutoff_at_endpoint`（派生，单独一列）
6. **可判定分母单列计数**：`Q` 为 `nan`/空 的行只计入 `Q_decidable=False`，绝不并入分母。

⚠️ 本轮新增的**歧义暴露**（不是猜测，是实测）
------------------------------------------
同一个峰值 SPL 键可能对应 **>1 条 −3 dB 带**（v2 te2_9 实测：94 条带 / 80 组合，
14 个键各对应 2 条带）。已注册导出器取**文件序第一条**（`bw_match_rule = "spl_key_exact_first_occurrence"`），
本脚本为**保持与 v2 同口径**默认沿用该规则，但**同时记录**：

* `bw_n_candidates` / `bw_level_ambiguous` —— 歧义**不静默吞掉**；
* `*_alt` 一组列 —— 「**峰值频率落在带内**」的候选（物理上属于该组合的那条带），
  含 `bw_alt_unique`（是否唯一命中）。该组列纯属**诊断**，默认不参与 `usable`。

实测（v2 te2_9 只读复算）：14 个歧义键中 **6 个** 的「文件序第一条」**不含**该组合峰值频率；
其中 **3 格**（x=0.5/N1=7、x=0.5/N1=8、x=0.8/N1=7）在两条规则下 `usable` 不同
⇒ 注册基线「46 可用」在峰值感知规则下为 **43**；`Q_decidable=32` / `Q_pass=11` **两规则相同**。

退出码
------
* 0 成功；2 用法错误；3 **产物未到位**（缺 Table_9.txt / Bandwidth.txt）；
* 4 解析到不一致（归一化撞键、列缺失、带宽对不自洽…）；5 网格与本批声明不符（`--strict-grid`）。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "work/runs/te29-prep-20261009/parse"

META_RE = re.compile(r"^%\s*(Model|Version|Date|Table)\s*:")

#: **仅作诊断**（不是切分依据）：COMSOL 英文表头会因列名溢出而与下一列只隔 1 个空格，
#: 按它切会并吞列 ⇒ 用它来量化「本文件的表头有多不适合按空白切」。
NAIVE_HEADER_SPLIT_RE = re.compile(r"\s{2,}")

# ---- 本批扫描声明（来自任务书；只用于「是否齐全」的判定，不用于伪造数据） ----
FREQ_LO_HZ = 5.0e6
FREQ_HI_HZ = 50.0e6
FREQ_STEP_HZ = 0.5e6
EXPECT_NFREQ = 91                      # 5–50 MHz 步长 0.5
KEY_DECIMALS = 6
EXPECT_X = tuple(round(0.2 + 0.01 * k, KEY_DECIMALS) for k in range(81))   # 0.2→1.0 步长 0.01
EXPECT_N1 = tuple(range(1, 9))
EXPECT_N2 = (9,)
EXPECT_COMBOS = len(EXPECT_X) * len(EXPECT_N1) * len(EXPECT_N2)            # 648

FREQ_TOL_HZ = 1.0                      # 端点判定：|f − f_scan_hi| < 1 Hz
SPL_BRIDGE_DB = 3.0                    # Bandwidth.txt 的 SPL 列 = 峰值 SPL − 3.0
SPL_KEY_DECIMALS = 9
Q_PASS_LO, Q_PASS_HI = 2.5, 3.5        # 与 extract_v2_labels/te29_analysis 同窗口

REQUIRED_FILES = ("Table_9.txt", "Bandwidth.txt")
INVENTORY_FILES = ("Table_9.txt", "Table_10.txt", "Table_11.txt", "Zdisplacement.txt",
                   "Peak_frequency.txt", "Bandwidth.txt", "output_manifest.tsv")

_NAN_TOKENS = frozenset({"nan", "-nan", "+nan", "n/a", "na", ""})

# --------------------------------------------------------------------------- #
# 列名别名表（中/英双语）＋ fail-closed 表头定位
# --------------------------------------------------------------------------- #
#: 坐标后缀（**, 点: (0, 0, -1E-5)** / **, Point: (0, 0, -1E-5)** 及其无空格变体）。
#: **按前缀正则匹配**，不写死整串 ⇒ 中英、有无空格、坐标数值变化都能命中。
COORD_SUFFIX_RE = r"(?:\s*,\s*(?:点|Point)\s*:\s*\([^)]*\))?"

#: `(canonical, (别名…))`。别名是**表头里逐字出现的列名基名**（不含坐标后缀）。
#: canonical 是解析器内部用的稳定键名，跨语言不变。
TABLE9_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("x_scale", ("x_scale",)),
    ("N_w_te1", ("N_w_te1",)),
    ("N_w_te2", ("N_w_te2",)),
    ("freq_Hz", ("freq (Hz)",)),
    ("real_v_tz", ("real(acpr.v_tz) (m/s)",)),
    ("imag_v_tz", ("imag(acpr.v_tz) (m/s)",)),
    ("total_v_z", ("Total acoustic velocity, z-component (m/s)",
                   "总声速，z 分量 (m/s)", "总声速, z 分量 (m/s)")),
    ("real_p_t", ("real(acpr.p_t) (Pa)",)),
    ("imag_p_t", ("imag(acpr.p_t) (Pa)",)),
    ("total_p", ("Total acoustic pressure (Pa)", "总声压 (Pa)")),
    ("total_p_rms", ("Total acoustic pressure, RMS (Pa)",
                     "总声压，均方根 (Pa)", "总声压, 均方根 (Pa)")),
    ("spl_dB", ("Total sound pressure level (dB)", "总声压级 (dB)")),
)

#: `Bandwidth.txt`（−3 dB 截断点表）：`freq / SPL / 宽度 / Q / 阻尼比`。
BANDWIDTH_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("freq_Hz", ("freq (Hz)",)),
    ("spl_dB", ("Total sound pressure level (dB)", "总声压级 (dB)")),
    ("width_Hz", ("Width (Hz)", "宽度 (Hz)", "带宽 (Hz)")),
    ("Q", ("Q-factor", "Q factor", "Q 因子", "Q因子", "品质因子")),
    ("zeta", ("Damping ratio", "阻尼比", "阻尼系数")),
)

#: 组合参数列在 `Table_9.txt` 里**各出现两次**（无后缀的参数列在前、带 `, Point:` 的重复列在后）
#: ⇒ 定位规则是「**优先取无坐标后缀的那一次**」，见 `locate_columns()`。
_PARAM_COLUMNS = frozenset({"x_scale", "N_w_te1", "N_w_te2"})

_CJK_RE = re.compile(r"[\u3400-\u9fff]")


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def parse_float(tok: str) -> float | None:
    """COMSOL 数值 token → float；`NaN`/空 → None（**不**用 0 顶替，避免把不可判定算成 0）。"""
    if tok is None:
        return None
    s = str(tok).strip()
    if s.lower() in _NAN_TOKENS:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if math.isnan(v):
        return None
    return v


def fmt_num(v) -> str:
    """写 CSV 用：None → 空串；nan → 空串（与「不可判定」同一写法，另用 *_decidable 列区分）。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        if math.isnan(v):
            return "nan"          # 与既有 frozen CSV 的写法一致，保留「是 nan」这一事实
        return repr(v)
    return str(v)


def norm_key(x_raw, n1_raw, n2_raw) -> tuple:
    """ulp 归一化组合键。x 用 round(...,6)；N 先转 int（若整值）再 round，保证 1.0 == 1。"""

    def _num(tok: str):
        v = float(str(tok).strip())
        r = round(v)
        if abs(v - r) < 1e-9:
            return int(r)
        return round(v, KEY_DECIMALS)

    return (_num(x_raw), _num(n1_raw), _num(n2_raw))


def combo_key_str(key: tuple) -> str:
    x, n1, n2 = key
    return "x%.6f_N1%d_N2%d" % (float(x), int(n1), int(n2))


def cell_id_from_dir(d: pathlib.Path) -> str:
    return d.name


def find_cell_dir(root: pathlib.Path) -> tuple[pathlib.Path | None, list[pathlib.Path]]:
    """在 root 下定位导出的 cell 目录（含 Table_9.txt 的目录）。root 自身命中优先。"""
    if (root / "Table_9.txt").is_file():
        return root, [root]
    cands = [p.parent for p in root.rglob("Table_9.txt")
             if "__pycache__" not in p.parts]
    # 去重 + 只保留同时有 Bandwidth.txt 的
    uniq = sorted({p.resolve() for p in cands})
    good = [p for p in uniq if (p / "Bandwidth.txt").is_file()]
    if len(good) == 1:
        return good[0], good
    if len(good) > 1:
        return None, good
    return None, uniq


# --------------------------------------------------------------------------- #
# COMSOL 表解析
# --------------------------------------------------------------------------- #
def load_comsol_table(path: pathlib.Path):
    """读 COMSOL 导出文本表 → (header_body:str, rows:list[list[str]], meta:dict)。

    表头 = **最后一个**非 `Model/Version/Date/Table` 的 `%` 行；数据 = 该表头之后的所有非空非 `%` 行。
    **表头按原文整串返回**（不做空白切分 —— 英文表头会因列名溢出而与下一列只隔 1 个空格，
    切了就会并吞列 ⇒ 交给 `locate_columns()` 用别名表定位）。
    """
    meta: dict[str, str] = {}
    pct_lines: list[tuple[int, str]] = []
    data_lines: list[tuple[int, list[str]]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        for ln, raw in enumerate(fh, 1):
            s = raw.rstrip("\n").rstrip("\r")
            if not s.strip():
                continue
            if s.lstrip().startswith("%"):
                body = s.lstrip()[1:]
                m = META_RE.match(s.strip())
                if m:
                    meta[m.group(1)] = body.split(":", 1)[1].strip() if ":" in body else ""
                else:
                    pct_lines.append((ln, body))
                continue
            data_lines.append((ln, s.split()))
    if not pct_lines:
        raise ValueError("表头缺失：%s 里没有非元信息的 `%%` 表头行" % path.name)
    h_ln, h_body = pct_lines[-1]
    rows = [toks for ln, toks in data_lines if ln > h_ln]
    for ln, toks in data_lines:
        if ln < h_ln:
            raise ValueError("%s：表头行 L%d 之前出现了数据行 L%d（结构异常，拒绝猜测）"
                             % (path.name, h_ln, ln))
    return h_body, rows, meta


def naive_header_field_count(header_body: str) -> int:
    """诊断用：按「2 个以上空格」切表头会得到几段（英文溢出表头会**少**于真实列数）。"""
    return len([t for t in NAIVE_HEADER_SPLIT_RE.split(header_body.strip()) if t.strip()])


def modal_row_width(rows: list[list[str]], table: str) -> int:
    """数据行的**众数**列数（fail-closed：无数据行 / 众数并列 ⇒ 拒绝）。"""
    if not rows:
        raise ValueError("%s：没有数据行 ⇒ 无法校验表头列数（拒绝猜测，fail-closed）" % table)
    counts: dict[int, int] = {}
    for r in rows:
        counts[len(r)] = counts.get(len(r), 0) + 1
    top = max(counts.values())
    winners = sorted(w for w, n in counts.items() if n == top)
    if len(winners) != 1:
        raise ValueError("%s：数据行列数不唯一（众数并列 %s，分布 %s）⇒ 拒绝猜测"
                         % (table, winners, dict(sorted(counts.items()))))
    return winners[0]


def locate_columns(header_body: str, aliases, rows: list[list[str]], table: str) -> dict:
    """别名扫描表头 → `{"index": {canonical: 列号}, "language": …, "alias_hits": …}`。

    fail-closed 四条（任一条不满足 ⇒ `ValueError`，**绝不取「第一个像的」**）：

    1. **零命中**：表头里的列名一个别名都匹配不上（换语言/整表错拼）⇒ 报错；
    2. **解释不全**：相邻命中之间（含首尾）残留**非空白**文本 ⇒ 表头存在别名表解释不了的字段 ⇒ 报错；
    3. **字段数不符**：解释出的字段数 ≠ 数据行众数列数 ⇒ 报错（防「静默取 0 行」与错位）；
    4. **歧义**：同一 canonical 命中 **0 个**或 **>1 个**候选 ⇒ 报错。
       组合参数列（`x_scale`/`N_w_te1`/`N_w_te2`）在 `Table_9.txt` 里各出现两次，
       规则是**优先取无坐标后缀的那一次**；若「无后缀」候选不止一个、或没有无后缀候选
       且带后缀候选也不止一个 ⇒ 仍按歧义报错。
    """
    n_cols = modal_row_width(rows, table)
    matches: list[tuple[int, int, str, str, bool]] = []   # (start, end, canonical, alias, 带后缀)
    for canonical, alias_list in aliases:
        for alias in alias_list:
            pat = re.compile(re.escape(alias) + COORD_SUFFIX_RE)
            for m in pat.finditer(header_body):
                had_suffix = m.end() > m.start() + len(alias)
                matches.append((m.start(), m.end(), canonical, alias, had_suffix))
    if not matches:
        raise ValueError(
            "%s：表头零命中 —— 没有任何列名能用中/英别名表解释（表头=%r）"
            "（换语言或整表错拼；拒绝静默取 0 行，fail-closed）" % (table, header_body.strip()[:200]))

    # 同一位置只保留**最长**匹配（防 `Total acoustic pressure (Pa)` 吃掉 `…, RMS (Pa)`）
    longest: dict[int, tuple[int, int, str, str, bool]] = {}
    for mt in matches:
        cur = longest.get(mt[0])
        if cur is None or (mt[1] - mt[0]) > (cur[1] - cur[0]):
            longest[mt[0]] = mt
    chosen: list[tuple[int, int, str, str, bool]] = []
    cursor = 0
    for start in sorted(longest):
        if start < cursor:                      # 与已选字段重叠 ⇒ 丢弃（贪心从左到右）
            continue
        chosen.append(longest[start])
        cursor = longest[start][1]

    # ② 解释不全：命中之间/首尾必须是纯空白
    gaps, pos = [], 0
    for start, end, _c, _a, _s in chosen:
        gaps.append(header_body[pos:start])
        pos = end
    gaps.append(header_body[pos:])
    leftover = [g for g in gaps if g.strip()]
    if leftover:
        raise ValueError(
            "%s：表头有别名表解释不了的字段 %r（表头=%r）⇒ 拒绝猜列号（fail-closed）"
            % (table, leftover[0].strip()[:80], header_body.strip()[:200]))

    # ③ 字段数必须等于数据列数
    if len(chosen) != n_cols:
        raise ValueError(
            "%s：表头解释出 %d 个字段，但数据行是 %d 列 ⇒ 拒绝按位置推断列号（fail-closed）"
            % (table, len(chosen), n_cols))

    # ④ 歧义判定
    hits: list[dict] = []
    by_canon: dict[str, list[tuple[int, bool]]] = {}
    for i, (start, end, canonical, alias, had_suffix) in enumerate(chosen):
        hits.append({"index": i, "canonical": canonical, "alias": alias,
                     "coord_suffix": bool(had_suffix)})
        by_canon.setdefault(canonical, []).append((i, had_suffix))

    resolved: dict[str, int] = {}
    for canonical in sorted(by_canon):
        cands = by_canon[canonical]
        plain = [i for i, sfx in cands if not sfx]
        pool = plain if plain else [i for i, _sfx in cands]
        if len(pool) == 0:
            raise ValueError("%s：列 %r 命中 0 个候选 ⇒ 拒绝（fail-closed）" % (table, canonical))
        if len(pool) > 1:
            raise ValueError("%s：列 %r 命中 %d 个候选（列号 %s）⇒ 歧义，拒绝取「第一个像的」"
                             "（fail-closed）" % (table, canonical, len(pool), pool))
        resolved[canonical] = pool[0]

    # 语言判定：只看**有本地化对应词**的那几列（如 `总声压级 (dB)` ↔
    # `Total sound pressure level (dB)`、`Q 因子` ↔ `Q-factor`）；`x_scale` / `freq (Hz)` /
    # `real(acpr.p_t) (Pa)` 这类中英**同名**的列不参与投票（否则中文导出会被误判成 mixed）。
    localized = {c for c, al in aliases if any(_CJK_RE.search(a) for a in al)}
    votes: set[str] = set()
    n_zh = n_en = 0
    for _s, _e, canonical, alias, _f in chosen:
        if canonical not in localized:
            continue
        if _CJK_RE.search(alias):
            n_zh += 1
            votes.add("zh")
        else:
            n_en += 1
            votes.add("en")
    language = votes.pop() if len(votes) == 1 else ("mixed" if votes else "unknown")
    return {"index": resolved, "language": language,
            "n_localized_zh_hits": n_zh, "n_localized_en_hits": n_en,
            "n_fields": len(chosen), "n_data_cols": n_cols,
            "naive_split_fields": naive_header_field_count(header_body),
            "alias_hits": hits}


def _require_col(colmap: dict, canonical: str, table: str) -> int:
    """从 `locate_columns()` 的结果取列号；缺 ⇒ 报错（不回落、不猜）。"""
    try:
        return colmap["index"][canonical]
    except KeyError:
        raise ValueError("%s：表头里没有定位到列 %r（已知 %s）⇒ 拒绝"
                         % (table, canonical, sorted(colmap["index"]))) from None


def parse_bandwidth_levels(path: pathlib.Path):
    """Bandwidth.txt → (levels, meta, diag)。带按**成对**（下截止点 / 上截止点）分组。"""
    header_body, rows, meta = load_comsol_table(path)
    colmap = locate_columns(header_body, BANDWIDTH_ALIASES, rows, path.name)
    i_f = _require_col(colmap, "freq_Hz", path.name)
    i_spl = _require_col(colmap, "spl_dB", path.name)
    i_w = _require_col(colmap, "width_Hz", path.name)
    i_q = _require_col(colmap, "Q", path.name)
    i_z = _require_col(colmap, "zeta", path.name)

    levels: list[dict] = []
    diag = {"n_rows": len(rows), "n_levels": 0, "pair_order_bad": 0,
            "nonfinite_freq_rows": 0, "q_nan_levels": 0,
            "header_language": colmap["language"],
            "header_n_fields": colmap["n_fields"],
            "header_n_data_cols": colmap["n_data_cols"],
            "header_n_localized_zh_hits": colmap["n_localized_zh_hits"],
            "header_n_localized_en_hits": colmap["n_localized_en_hits"],
            "header_naive_split_fields": colmap["naive_split_fields"],
            "header_index": dict(colmap["index"]),
            "header_alias_hits": colmap["alias_hits"]}
    if len(rows) % 2 != 0:
        diag["odd_rows"] = True
    for k in range(0, len(rows) - 1, 2):
        a, b = rows[k], rows[k + 1]
        f_lo, f_hi = parse_float(a[i_f]), parse_float(b[i_f])
        if f_lo is None or f_hi is None:
            diag["nonfinite_freq_rows"] += 1
            continue
        if not (f_lo <= f_hi):
            diag["pair_order_bad"] += 1
        spl = parse_float(a[i_spl])
        q = parse_float(a[i_q])
        levels.append({
            "pair_index": k // 2,
            "spl_raw": a[i_spl].strip(),
            "spl_dB": spl,
            "f_lo_Hz": f_lo, "f_hi_Hz": f_hi,
            "width_raw": a[i_w].strip(),
            "width_Hz": parse_float(a[i_w]),
            "Q_raw": a[i_q].strip(), "Q": q,
            "zeta_raw": a[i_z].strip(), "zeta": parse_float(a[i_z]),
            "b_spl_matches_a": (a[i_spl].strip() == b[i_spl].strip()),
        })
        if q is None:
            diag["q_nan_levels"] += 1
    diag["n_levels"] = len(levels)
    return levels, meta, diag


def index_levels_by_spl(levels: list[dict]):
    """桥接键：round(bw_spl + 3.0, 9) → [level, …]（**保持文件序**，故 first == 既有口径）。"""
    by: dict[float, list[dict]] = {}
    for lv in levels:
        if lv["spl_dB"] is None:
            continue
        by.setdefault(round(lv["spl_dB"] + SPL_BRIDGE_DB, SPL_KEY_DECIMALS), []).append(lv)
    return by


def bridge_level(cands: list[dict], peak_freq_Hz: float) -> dict:
    """在候选带中选一条。返回 {primary, alt, n_candidates, ambiguous, alt_unique}。

    * primary = 文件序第一条（**与已注册导出器同口径**，保证与 v2 可比）；
    * alt     = 「峰值频率落在 [f_lo, f_hi] 内」的唯一候选（物理归属，诊断用）。
    """
    out = {"primary": None, "alt": None, "n_candidates": len(cands),
           "ambiguous": len(cands) > 1, "alt_unique": False}
    if not cands:
        return out
    out["primary"] = cands[0]
    inband = [c for c in cands
              if c["f_lo_Hz"] - FREQ_TOL_HZ <= peak_freq_Hz <= c["f_hi_Hz"] + FREQ_TOL_HZ]
    if len(inband) == 1:
        out["alt"] = inband[0]
        out["alt_unique"] = True
    return out


# --------------------------------------------------------------------------- #
# 主解析
# --------------------------------------------------------------------------- #
def parse_export(cell_dir: pathlib.Path, strict_grid: bool = False,
                 expect_combos: int | None = EXPECT_COMBOS,
                 expect_nfreq: int | None = EXPECT_NFREQ) -> dict:
    """解析一个导出 cell 目录 → 结构化结果（cells 宽表 + points 长表 + sanity）。"""
    cell_dir = pathlib.Path(cell_dir)
    missing = [f for f in REQUIRED_FILES if not (cell_dir / f).is_file()]
    if missing:
        raise FileNotFoundError("产物未到位：%s 缺 %s" % (cell_dir, "、".join(missing)))

    h9, r9, meta9 = load_comsol_table(cell_dir / "Table_9.txt")
    t9map = locate_columns(h9, TABLE9_ALIASES, r9, "Table_9.txt")
    i_x = _require_col(t9map, "x_scale", "Table_9.txt")
    i_n1 = _require_col(t9map, "N_w_te1", "Table_9.txt")
    i_n2 = _require_col(t9map, "N_w_te2", "Table_9.txt")
    i_f = _require_col(t9map, "freq_Hz", "Table_9.txt")
    i_s = _require_col(t9map, "spl_dB", "Table_9.txt")

    per: dict[tuple, list[tuple[float, float]]] = {}
    raw_seen: dict[tuple, set] = {}
    per_rows = 0
    bad_rows = 0
    for r in r9:
        try:
            key = norm_key(r[i_x], r[i_n1], r[i_n2])
            f = parse_float(r[i_f])
            s = parse_float(r[i_s])
        except (ValueError, IndexError):
            bad_rows += 1
            continue
        if f is None or s is None:
            bad_rows += 1
            continue
        per.setdefault(key, []).append((f, s))
        raw_seen.setdefault(key, set()).add((r[i_x].strip(), r[i_n1].strip(), r[i_n2].strip()))
        per_rows += 1

    collisions = {combo_key_str(k): sorted(v) for k, v in raw_seen.items() if len(v) > 1}
    all_keys = sorted(per)
    f_scan_hi = max(f for v in per.values() for f, _ in v)
    f_scan_lo = min(f for v in per.values() for f, _ in v)

    levels, meta_bw, bw_diag = parse_bandwidth_levels(cell_dir / "Bandwidth.txt")
    by_spl = index_levels_by_spl(levels)

    cells: list[dict] = []
    points: list[dict] = []
    n_matched = n_unmatched = 0
    for key in all_keys:
        vals = sorted(per[key])
        pk_f, pk_s = max(vals, key=lambda t: t[1])
        x, n1, n2 = key
        cands = by_spl.get(round(pk_s, SPL_KEY_DECIMALS), [])
        br = bridge_level(cands, pk_f)
        lv, alt = br["primary"], br["alt"]
        peak_end = bool(abs(pk_f - f_scan_hi) < FREQ_TOL_HZ)

        row = {
            "cell": cell_id_from_dir(cell_dir),
            "combo_key": combo_key_str(key),
            "x_scale": x, "x_scale_raw": sorted(raw_seen[key])[0][0],
            "N_w_te1": n1, "N_w_te1_raw": sorted(raw_seen[key])[0][1],
            "N_w_te2": n2, "N_w_te2_raw": sorted(raw_seen[key])[0][2],
            "n_freq": len(vals),
            "freq_min_Hz": vals[0][0], "freq_max_Hz": vals[-1][0],
            "peak_freq_Hz": pk_f, "peak_spl_dB": pk_s,
            "peak_at_scan_endpoint": peak_end,
            "bw_level_matched": bool(lv),
            "bw_n_candidates": br["n_candidates"],
            "bw_level_ambiguous": br["ambiguous"],
            "bw_match_rule": "spl_key_exact_first_occurrence",
            "bw_alt_unique": br["alt_unique"],
        }
        if lv:
            n_matched += 1
            row.update({
                "bw_f_lo_Hz": lv["f_lo_Hz"], "bw_f_hi_Hz": lv["f_hi_Hz"],
                "bandwidth_Hz": lv["width_Hz"], "Q": lv["Q"], "zeta": lv["zeta"],
                "Q_raw": lv["Q_raw"], "zeta_raw": lv["zeta_raw"],
                "bw_upper_cutoff_at_endpoint": bool(abs(lv["f_hi_Hz"] - f_scan_hi) < FREQ_TOL_HZ),
            })
        else:
            n_unmatched += 1
            row.update({"bw_f_lo_Hz": None, "bw_f_hi_Hz": None, "bandwidth_Hz": None,
                        "Q": None, "zeta": None, "Q_raw": "", "zeta_raw": "",
                        "bw_upper_cutoff_at_endpoint": None})
        if alt:
            row.update({
                "bw_f_lo_alt_Hz": alt["f_lo_Hz"], "bw_f_hi_alt_Hz": alt["f_hi_Hz"],
                "bandwidth_alt_Hz": alt["width_Hz"], "Q_alt": alt["Q"], "zeta_alt": alt["zeta"],
                "bw_upper_cutoff_at_endpoint_alt":
                    bool(abs(alt["f_hi_Hz"] - f_scan_hi) < FREQ_TOL_HZ),
                "bandwidth_alt_neq_primary":
                    (row["bandwidth_Hz"] is not None and alt["width_Hz"] is not None
                     and alt["width_Hz"] != row["bandwidth_Hz"]),
            })
        else:
            row.update({"bw_f_lo_alt_Hz": None, "bw_f_hi_alt_Hz": None,
                        "bandwidth_alt_Hz": None, "Q_alt": None, "zeta_alt": None,
                        "bw_upper_cutoff_at_endpoint_alt": None,
                        "bandwidth_alt_neq_primary": None})

        # ---- 派生列（不得替代上面的原始标志） ----
        blocked = None
        if row["bw_upper_cutoff_at_endpoint"] is None:
            blocked = "bw_level_unmatched"
        row["usable"] = bool((not peak_end) and (row["bw_upper_cutoff_at_endpoint"] is False))
        row["usable_blocked_by"] = blocked
        q = row["Q"]
        row["Q_decidable"] = bool(q is not None and math.isfinite(float(q)))
        row["Q_pass_2p5_3p5"] = bool(row["Q_decidable"] and Q_PASS_LO <= float(q) <= Q_PASS_HI)
        alt_end = row["bw_upper_cutoff_at_endpoint_alt"]
        row["usable_alt"] = bool((not peak_end) and (alt_end is False))
        cells.append(row)

        for f, s in vals:
            points.append({
                "combo_key": row["combo_key"], "cell": row["cell"],
                "x_scale": x, "N_w_te1": n1, "N_w_te2": n2,
                "freq_Hz": f, "spl_dB": s,
                "is_cell_peak": bool(f == pk_f and s == pk_s),
            })

    # ---- 网格与规模诊断（只报事实，不补零） ----
    xs_norm = sorted({k[0] for k in all_keys})
    n1s = sorted({k[1] for k in all_keys})
    n2s = sorted({k[2] for k in all_keys})
    freqs = sorted({f for v in per.values() for f, _ in v})
    diffs = [b - a for a, b in zip(freqs, freqs[1:])]
    step_ok = bool(diffs) and all(abs(d - diffs[0]) < 1e-6 for d in diffs)
    expect_keys = {(x, n1, n2) for x in EXPECT_X for n1 in EXPECT_N1 for n2 in EXPECT_N2}
    got_keys = set(all_keys)
    missing = sorted(expect_keys - got_keys)
    unexpected = sorted(got_keys - expect_keys)
    nfreq_mismatch = sorted((combo_key_str(k), len(v)) for k, v in per.items()
                            if expect_nfreq is not None and len(v) != expect_nfreq)

    diag = {
        "cell_dir": str(cell_dir),
        "is_v2_reference_path": "remote-exported-v2" in str(cell_dir),
        "model": meta9.get("Model"), "version": meta9.get("Version"), "date": meta9.get("Date"),
        "table9_meta": meta9, "bandwidth_meta": meta_bw,
        "header_locate": {
            "Table_9.txt": {"language": t9map["language"],
                            "n_fields": t9map["n_fields"],
                            "n_data_cols": t9map["n_data_cols"],
                            "n_localized_zh_hits": t9map["n_localized_zh_hits"],
                            "n_localized_en_hits": t9map["n_localized_en_hits"],
                            "naive_split_fields": t9map["naive_split_fields"],
                            "index": dict(t9map["index"]),
                            "alias_hits": t9map["alias_hits"]},
            "Bandwidth.txt": {"language": bw_diag["header_language"],
                              "n_fields": bw_diag["header_n_fields"],
                              "n_data_cols": bw_diag["header_n_data_cols"],
                              "n_localized_zh_hits": bw_diag["header_n_localized_zh_hits"],
                              "n_localized_en_hits": bw_diag["header_n_localized_en_hits"],
                              "naive_split_fields": bw_diag["header_naive_split_fields"],
                              "index": dict(bw_diag["header_index"]),
                              "alias_hits": bw_diag["header_alias_hits"]},
        },
        "n_table9_rows": len(r9), "n_table9_rows_used": per_rows, "n_table9_rows_skipped": bad_rows,
        "n_combos": len(all_keys),
        "n_points": len(points),
        "n_x_values": len(xs_norm), "x_min": xs_norm[0], "x_max": xs_norm[-1],
        "n_N_w_te1_values": len(n1s), "N_w_te1_values": n1s,
        "n_N_w_te2_values": len(n2s), "N_w_te2_values": n2s,
        "n_freq": len(freqs), "freq_lo_Hz": f_scan_lo, "freq_hi_Hz": f_scan_hi,
        "freq_step_Hz": (diffs[0] if diffs else None), "freq_step_uniform": step_ok,
        "expected": {"n_combos": expect_combos, "n_freq": expect_nfreq,
                     "freq_lo_Hz": FREQ_LO_HZ, "freq_hi_Hz": FREQ_HI_HZ,
                     "freq_step_Hz": FREQ_STEP_HZ,
                     "x_lo": EXPECT_X[0], "x_hi": EXPECT_X[-1], "n_x": len(EXPECT_X)},
        "grid_combos_match": (len(all_keys) == expect_combos) if expect_combos else None,
        "grid_nfreq_match": (len(freqs) == expect_nfreq) if expect_nfreq else None,
        "n_missing_expected_combos": len(missing),
        "missing_expected_combos_sample": [combo_key_str(k) for k in missing[:40]],
        "n_unexpected_combos": len(unexpected),
        "unexpected_combos_sample": [combo_key_str(k) for k in unexpected[:40]],
        "n_combos_with_nfreq_mismatch": len(nfreq_mismatch),
        "combos_with_nfreq_mismatch_sample": nfreq_mismatch[:40],
        "normalization_collisions": collisions,
        "n_normalization_collisions": len(collisions),
        "bw_levels": {"n_levels": bw_diag["n_levels"], "n_rows": bw_diag["n_rows"],
                      "q_nan_levels": bw_diag["q_nan_levels"],
                      "pair_order_bad": bw_diag["pair_order_bad"],
                      "odd_rows": bool(bw_diag.get("odd_rows", False))},
        "bw_matched": n_matched, "bw_unmatched": n_unmatched,
        "n_ambiguous_bridge_cells": sum(1 for c in cells if c["bw_level_ambiguous"]),
        "n_ambiguous_alt_unique": sum(1 for c in cells
                                      if c["bw_level_ambiguous"] and c["bw_alt_unique"]),
        "n_ambiguous_primary_disagrees_alt": sum(
            1 for c in cells
            if c["bw_level_ambiguous"] and c["bw_alt_unique"]
            and c["bw_f_hi_Hz"] != c["bw_f_hi_alt_Hz"]),
        # ---- 计数：原始标志 / 派生 / 可判定分母 ----
        "n_peak_at_scan_endpoint": sum(1 for c in cells if c["peak_at_scan_endpoint"]),
        "n_bw_upper_cutoff_at_endpoint": sum(1 for c in cells
                                            if c["bw_upper_cutoff_at_endpoint"] is True),
        "n_bw_upper_cutoff_undefined": sum(1 for c in cells
                                          if c["bw_upper_cutoff_at_endpoint"] is None),
        "n_censored_or_truncated": sum(1 for c in cells if (c["peak_at_scan_endpoint"]
                                                           or c["bw_upper_cutoff_at_endpoint"] is True)),
        "n_usable": sum(1 for c in cells if c["usable"]),
        "n_usable_alt_peakaware": sum(1 for c in cells if c["usable_alt"]),
        "n_Q_nan_rows": sum(1 for c in cells if not c["Q_decidable"]),
        "n_Q_nan_but_flagged_usable": sum(1 for c in cells
                                          if (not c["Q_decidable"]) and c["usable"]),
        "n_Q_decidable": sum(1 for c in cells if c["Q_decidable"]),
        "n_Q_decidable_among_usable": sum(1 for c in cells
                                          if c["usable"] and c["Q_decidable"]),
        "n_Q_pass_2p5_3p5": sum(1 for c in cells if c["Q_pass_2p5_3p5"]),
        "Q_pass_window": [Q_PASS_LO, Q_PASS_HI],
    }

    problems = []
    if collisions:
        problems.append("归一化撞键 %d 个（同键多个原始串）" % len(collisions))
    if bad_rows:
        problems.append("跳过无法解析的数据行 %d 行" % bad_rows)
    if bw_diag["pair_order_bad"]:
        problems.append("带宽表有 %d 对 f_lo > f_hi" % bw_diag["pair_order_bad"])
    if bw_diag.get("odd_rows"):
        problems.append("带宽表行数为奇数，最后一行为孤儿")
    if n_unmatched:
        problems.append("有 %d 个组合未挂回 −3 dB level" % n_unmatched)
    if strict_grid:
        if expect_combos and len(all_keys) != expect_combos:
            problems.append("组合数 %d ≠ 声明 %d" % (len(all_keys), expect_combos))
        if expect_nfreq and len(freqs) != expect_nfreq:
            problems.append("频点数 %d ≠ 声明 %d" % (len(freqs), expect_nfreq))
        if missing:
            problems.append("缺 %d 个声明组合" % len(missing))
        if unexpected:
            problems.append("多 %d 个非声明组合" % len(unexpected))
        if abs(f_scan_lo - FREQ_LO_HZ) > FREQ_TOL_HZ:
            problems.append("扫描下限 %g ≠ 声明 %g" % (f_scan_lo, FREQ_LO_HZ))
        if abs(f_scan_hi - FREQ_HI_HZ) > FREQ_TOL_HZ:
            problems.append("扫描上限 %g ≠ 声明 %g" % (f_scan_hi, FREQ_HI_HZ))
    diag["problems"] = problems
    return {"cells": cells, "points": points, "diag": diag,
            "f_scan_lo_Hz": f_scan_lo, "f_scan_hi_Hz": f_scan_hi}


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
CELL_COLS = [
    "cell", "combo_key", "x_scale", "x_scale_raw", "N_w_te1", "N_w_te1_raw",
    "N_w_te2", "N_w_te2_raw", "n_freq", "freq_min_Hz", "freq_max_Hz",
    "peak_freq_Hz", "peak_spl_dB", "peak_at_scan_endpoint",
    "bw_f_lo_Hz", "bw_f_hi_Hz", "bandwidth_Hz", "Q", "Q_raw", "zeta", "zeta_raw",
    "bw_upper_cutoff_at_endpoint", "bw_level_matched", "bw_n_candidates",
    "bw_level_ambiguous", "bw_match_rule",
    "bw_f_lo_alt_Hz", "bw_f_hi_alt_Hz", "bandwidth_alt_Hz", "Q_alt", "zeta_alt",
    "bw_upper_cutoff_at_endpoint_alt", "bw_alt_unique", "bandwidth_alt_neq_primary",
    "usable", "usable_blocked_by", "usable_alt",
    "Q_decidable", "Q_pass_2p5_3p5",
]
POINT_COLS = ["combo_key", "cell", "x_scale", "N_w_te1", "N_w_te2", "freq_Hz",
              "spl_dB", "is_cell_peak"]


def write_outputs(res: dict, out_dir: pathlib.Path) -> dict:
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cells_p = out_dir / "te29_cells.csv"
    points_p = out_dir / "te29_points.csv"
    summary_p = out_dir / "te29_parse_summary.json"
    with cells_p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CELL_COLS)
        for c in res["cells"]:
            w.writerow([fmt_num(c.get(k)) for k in CELL_COLS])
    with points_p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(POINT_COLS)
        for p in res["points"]:
            w.writerow([fmt_num(p.get(k)) for k in POINT_COLS])
    summary_p.write_text(json.dumps(res["diag"], ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
    return {"cells_csv": str(cells_p), "points_csv": str(points_p), "summary_json": str(summary_p)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="te2_9 v1 新导出解析器（器械；只读输入）")
    ap.add_argument("--export-dir", required=True,
                    help="导出目录，或其上层目录（会自动向下找含 Table_9.txt 的 cell 目录）")
    ap.add_argument("--cell-dir", default=None, help="当找到多个候选 cell 目录时显式指定")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--expect-combos", type=int, default=EXPECT_COMBOS)
    ap.add_argument("--expect-nfreq", type=int, default=EXPECT_NFREQ)
    ap.add_argument("--strict-grid", action="store_true",
                    help="组合数/频点数/扫描上下限与声明不符时非零退出")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    root = pathlib.Path(a.export_dir)
    if not root.exists():
        print("[待产物] 导出目录不存在：%s" % root)
        return 3
    if a.cell_dir:
        cell = root / a.cell_dir
        if not (cell / "Table_9.txt").is_file():
            print("[待产物] 指定 cell 目录缺 Table_9.txt：%s" % cell)
            return 3
    else:
        cell, cands = find_cell_dir(root)
        if cell is None:
            if not cands:
                print("[待产物] 在 %s 下没找到 Table_9.txt（产品可能还没到）" % root)
            else:
                print("[用法] 找到多个候选 cell 目录，请用 --cell-dir 指定其一：")
                for c in cands:
                    print("   ", c)
            return 3

    try:
        res = parse_export(cell, strict_grid=a.strict_grid,
                           expect_combos=a.expect_combos, expect_nfreq=a.expect_nfreq)
    except FileNotFoundError as e:
        print("[待产物] %s" % e)
        return 3
    except ValueError as e:
        print("[解析失败] %s" % e)
        return 4

    d = res["diag"]
    if not a.quiet:
        print("cell 目录 : %s" % d["cell_dir"])
        print("Model     : %s ｜ COMSOL %s ｜ %s" % (d["model"], d["version"], d["date"]))
        hl = d["header_locate"]
        print("表头定位  : Table_9 %s（%d 字段 = %d 列；按空白切只得 %d 段）｜ Bandwidth %s"
              "（%d 字段 = %d 列；按空白切只得 %d 段）"
              % (hl["Table_9.txt"]["language"], hl["Table_9.txt"]["n_fields"],
                 hl["Table_9.txt"]["n_data_cols"], hl["Table_9.txt"]["naive_split_fields"],
                 hl["Bandwidth.txt"]["language"], hl["Bandwidth.txt"]["n_fields"],
                 hl["Bandwidth.txt"]["n_data_cols"], hl["Bandwidth.txt"]["naive_split_fields"]))
        print("列号      : Table_9 %s" % (hl["Table_9.txt"]["index"],))
        print("            Bandwidth %s" % (hl["Bandwidth.txt"]["index"],))
        print("Table_9   : %d 行（用 %d / 跳过 %d）｜ 组合 %d ｜ 组合×频点 %d"
              % (d["n_table9_rows"], d["n_table9_rows_used"], d["n_table9_rows_skipped"],
                 d["n_combos"], d["n_points"]))
        print("网格      : x %d 值 [%g, %g] ｜ N1 %s ｜ N2 %s ｜ 频点 %d [%g, %g] 步长 %g 均匀=%s"
              % (d["n_x_values"], d["x_min"], d["x_max"], d["N_w_te1_values"],
                 d["N_w_te2_values"], d["n_freq"], d["freq_lo_Hz"], d["freq_hi_Hz"],
                 d["freq_step_Hz"] or float("nan"), d["freq_step_uniform"]))
        print("与声明比  : 组合 %s（期望 %s）｜ 频点 %s（期望 %s）｜ 缺 %d ｜ 多 %d"
              % (d["grid_combos_match"], d["expected"]["n_combos"],
                 d["grid_nfreq_match"], d["expected"]["n_freq"],
                 d["n_missing_expected_combos"], d["n_unexpected_combos"]))
        print("原始标志  : peak_at_scan_endpoint %d ｜ bw_upper_cutoff_at_endpoint %d ｜ 未定义 %d"
              % (d["n_peak_at_scan_endpoint"], d["n_bw_upper_cutoff_at_endpoint"],
                 d["n_bw_upper_cutoff_undefined"]))
        print("派生/分母 : usable %d（峰值感知口径 %d）｜ 删失或截断 %d ｜ Q=nan %d（其中被 flag 判可用 %d）"
              " ｜ Q 可判定 %d ｜ Q 达标 %d"
              % (d["n_usable"], d["n_usable_alt_peakaware"], d["n_censored_or_truncated"],
                 d["n_Q_nan_rows"], d["n_Q_nan_but_flagged_usable"],
                 d["n_Q_decidable"], d["n_Q_pass_2p5_3p5"]))
        print("桥接      : 命中 %d ｜ 未命中 %d ｜ 歧义格 %d（唯一落在峰值带内 %d；主规则与峰值带不一致 %d）"
              % (d["bw_matched"], d["bw_unmatched"], d["n_ambiguous_bridge_cells"],
                 d["n_ambiguous_alt_unique"], d["n_ambiguous_primary_disagrees_alt"]))
        if d["problems"]:
            for p in d["problems"]:
                print("  [!] %s" % p)
    if not a.no_write:
        paths = write_outputs(res, pathlib.Path(a.out_dir))
        if not a.quiet:
            for k, v in paths.items():
                print("wrote %s: %s" % (k, v))
    return 5 if (a.strict_grid and d["problems"]) else 0


if __name__ == "__main__":
    sys.exit(main())
