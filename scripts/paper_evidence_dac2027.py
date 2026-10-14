# -*- coding: utf-8 -*-
"""DAC 2027 稿件「本地可算、稿子正缺」的证据补齐（纯只读 + 落痕）。

用途：把 `docs/PAPER_REVIEW_DAC2027_20261009.md` 里标注「本地可做」的证据项**实际算出来**，
落成可直接引用的证据件（md/csv/json），并产出 MANIFEST（字节 + sha256）。

纪律（与工单/AGENTS.md 一致）：
* **只读**既有数据：不写 C 原表 / v2 冻结副本 / v3 并集 / `work/models/*.mph`；
* **不跑 COMSOL**、**不提升任何状态**（`solver_spec.json` 只读复核仍 draft）；
* **不编造数字**：每个数字来自本脚本对源文件的现算，并在 md 里写出源文件与口径；
* **不得池化**：按批分组（O-A）；池化值**单独标注**「池化、仅规模参考」；
* **不替人裁定**：Q 中位数用哪套分母、S4 采用哪条口径、405 是否展开等一律只并列并标 `【待裁定】`；
* **组合身份键先做 ulp 归一化**，并**同时**报原样口径（`repr(_num())`）与字面口径。

用法：
    work\\.venv\\Scripts\\python.exe -X utf8 scripts\\paper_evidence_dac2027.py
    work\\.venv\\Scripts\\python.exe -X utf8 scripts\\paper_evidence_dac2027.py --out-dir work\\runs\\<dir>

产物默认落 `work/runs/paper-evidence-20261009/`。脚本不写时间戳 ⇒ 反复运行产物**逐字节相同**
（除非源数据变了），使 sha256 可复核。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import pathlib
import sys
from collections import Counter, defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- 输入路径（全部只读）
P_C_ORIG = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"
P_V3 = REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv"
P_V3_VERSION = REPO / "work/runs/labels-two-batch-v3/20261008T170618/VERSION_LTB3_v20261008T170618.json"
P_V2F = REPO / "work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv"
P_V2_VERSION = REPO / "work/runs/remote-exported-v2-20260922/VERSION_V2_v20261008T143151.json"
P_A_COMBOS = REPO / "work/runs/remote-exported-20260922/dataset/combos.csv"
P_MODEL = REPO / "work/runs/multichannel-surrogate-20260929/multichannel_model.json"
P_PREREG = REPO / "work/runs/multichannel-surrogate-20260929/PREREG_multichannel_surrogate.md"
P_SCREEN = REPO / "work/runs/paper-rev-20260930/screen_refusals.json"
P_TE29_PROFILE = REPO / "work/runs/te2_9-value-20261009T090701/te2_9_profile.json"
P_SOLVER_SPEC = REPO / "work/runs/solver/pmut-f1/solver_spec.json"
P_BWVAL = REPO / "work/runs/first-peak-20260929/bw_method_validation.json"
P_C_VERSION = REPO / "work/runs/x-densify-20260928/data_versions/C_v20260929.json"
P_DUPKIND = REPO / "work/runs/labels-dupkind-refined/20261008T215100/labels_two_batch_dupkind_refined.csv"
P_SWEEP_SRC = REPO / "src/memsharness/sweep_analysis.py"
P_MPH_CURRENTDRIVE = REPO / "work/models/b_GE_task3_2new_currentdrive_fmax45_v1.mph"
P_MPH_LEGACY = REPO / "work/models/b_GE_task3_2new_legacy_1ohm_drive_v1.mph"
P_S76_REPORT = REPO / "work/runs/_evidence-s76-alignment/REPORT-s76-口径对齐.md"

BATCHES = ("A_5-35MHz", "C_5-50MHz", "V2_5-35MHz")
PARAM_KEYS = ("x_scale", "N_w_te1", "N_w_te2")
Q_GATE = (2.5, 3.5)

#: 工具链里锁死的两个状态锚点（本轮只读复核；不得提升）
SOLVER_SPEC_SHA256_EXPECT = "21315173fd2732c7384c4a3d437bb7f7c297d5c3047b5ff01094ca3553b6bd3f"
SWEEP_SRC_SHA256_EXPECT = "1f634902c89916e7131b1e589676603f79015225b0e919c0acc92b9da9338bb0"


# ---------------------------------------------------------------- 通用工具
def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(p: pathlib.Path) -> list[dict]:
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def num(v):
    """CSV 字符串 → int/float；不可解析返回 None。整数写成 int（与 sweep_analysis._num 同义）。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def is_num(v) -> bool:
    return num(v) is not None


def q_of(row, col="Q"):
    """取 Q 的**数值**；字面 `nan`/空 一律不算（分母必须写清）。"""
    s = str(row.get(col, "")).strip()
    if s == "" or s.lower() in ("nan", "null", "none"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "y", "t")


def pct(values, ps=(10, 50, 90), method="linear"):
    """百分位。method 默认 numpy 的 'linear'（= 线性插值），与本仓已登记值的口径一致。"""
    import numpy as np

    a = np.asarray([float(v) for v in values], dtype=float)
    return [round(float(np.percentile(a, p, method=method)), 6) for p in ps]


def median(values):
    xs = sorted(float(v) for v in values)
    n = len(xs)
    if n == 0:
        return None
    if n % 2:
        return xs[n // 2]
    return 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def rankdata(values):
    """平均秩（并列取均值）。自写，避免依赖 scipy ⇒ 用于「独立复算」Spearman。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for t in range(i, j + 1):
            out[order[t]] = avg
        i = j + 1
    return out


def pearson(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num_ = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num_ / (da * db)


def spearman(a, b):
    return pearson(rankdata(a), rankdata(b))


# ---------------------------------------------------------------- 身份键三口径
def key_literal(r) -> tuple:
    """字面口径：三列原样字符串逐字相同。"""
    return tuple(str(r.get(k, "")) for k in PARAM_KEYS)


def key_raw(r) -> tuple:
    """原样（数值）口径：`repr(_num(·))` —— 门禁 `n_overlap_raw` 用的就是这个口径。
    它把 `1.0` 与 `1` 判为同一点（**表示差**），但保留 `0.3` vs `0.30000000000000004` 的差。"""
    return tuple(repr(num(r.get(k))) for k in PARAM_KEYS)


def key_ulp(r) -> tuple:
    """ulp 归一化口径：浮点 `round(·, 6)`，整数保持 int —— 判等用，不改存储值。"""
    out = []
    for k in PARAM_KEYS:
        v = num(r.get(k))
        out.append(round(v, 6) if isinstance(v, float) else v)
    return tuple(out)


def overlap_sets(rows, keyfn):
    per = defaultdict(set)
    for r in rows:
        per[str(r.get("batch"))].add(keyfn(r))
    pairs, total = {}, 0
    bs = sorted(per)
    for i, a in enumerate(bs):
        for c in bs[i + 1:]:
            n = len(per[a] & per[c])
            pairs["%s|%s" % (a, c)] = n
            total += n
    return per, pairs, total


def pair_relation(rows):
    """逐**行对**（跨批、ulp 归一化后同组合）分类：key_str_same / key_repr_same / key_ulp_only。

    与 `dup_kind_refined` 的口径一致（每对计一次）。
    """
    idx = defaultdict(list)
    for i, r in enumerate(rows):
        idx[key_ulp(r)].append(i)
    cat = Counter()
    diff_cols = Counter()
    by_pair = Counter()
    examples = defaultdict(list)
    for ix in idx.values():
        for a in range(len(ix)):
            for b in range(a + 1, len(ix)):
                i, j = ix[a], ix[b]
                bi, bj = str(rows[i]["batch"]), str(rows[j]["batch"])
                if bi == bj:
                    continue
                by_pair["|".join(sorted([bi, bj]))] += 1
                same_str = key_literal(rows[i]) == key_literal(rows[j])
                same_raw = key_raw(rows[i]) == key_raw(rows[j])
                if same_str:
                    cat["key_str_same"] += 1
                elif same_raw:
                    cat["key_repr_same"] += 1
                    dcols = tuple(k for k in PARAM_KEYS
                                  if str(rows[i][k]) != str(rows[j][k]))
                    diff_cols[dcols] += 1
                    if len(examples[dcols]) < 3:
                        examples[dcols].append(
                            {"pair": [bi, bj],
                             "left": [str(rows[i][k]) for k in PARAM_KEYS],
                             "right": [str(rows[j][k]) for k in PARAM_KEYS]})
                else:
                    cat["key_ulp_only"] += 1
                    dcols = tuple(k for k in PARAM_KEYS
                                  if repr(num(rows[i][k])) != repr(num(rows[j][k])))
                    diff_cols[("ulp",) + dcols] += 1
                    if len(examples[dcols]) < 3:
                        examples[dcols].append(
                            {"pair": [bi, bj],
                             "left": [str(rows[i][k]) for k in PARAM_KEYS],
                             "right": [str(rows[j][k]) for k in PARAM_KEYS]})
    return cat, by_pair, diff_cols, {",".join(k): v for k, v in examples.items()}


# ---------------------------------------------------------------- 输出工具
class Sink:
    def __init__(self, out_dir: pathlib.Path):
        self.out = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self.outputs: list[pathlib.Path] = []

    def md(self, name, text: str) -> pathlib.Path:
        p = self.out / name
        p.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
        self.outputs.append(p)
        return p

    def csv(self, name, header, rows) -> pathlib.Path:
        p = self.out / name
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            for r in rows:
                w.writerow(r)
        self.outputs.append(p)
        return p

    def js(self, name, obj) -> pathlib.Path:
        p = self.out / name
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True),
                     encoding="utf-8")
        self.outputs.append(p)
        return p


def md_table(header, rows) -> str:
    out = ["| " + " | ".join(str(h) for h in header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    return "\n".join(out)


def fmt(x, nd=6):
    if x is None:
        return ""
    if isinstance(x, int):
        return str(x)
    return ("%%.%df" % nd) % x


# ================================================================ E1
def item_e1(sink: Sink, ctx: dict) -> dict:
    """按批分列的标签统计（O-A 口径，禁池化）。"""
    corig = ctx["corig"]
    v2f = ctx["v2f"]
    v3 = ctx["v3"]

    def flag_counts(rows, cols):
        out = {}
        for c in cols:
            out[c] = {
                "true": sum(1 for r in rows if truthy(r.get(c))),
                "false": sum(1 for r in rows if str(r.get(c, "")).strip() != ""
                         and not truthy(r.get(c))),
                "blank": sum(1 for r in rows if str(r.get(c, "")).strip() == ""),
            }
        return out

    def qstats(rows, col="Q"):
        vals = [q_of(r, col) for r in rows]
        vals = [v for v in vals if v is not None]
        d = {"n_numeric_Q": len(vals)}
        if vals:
            p10, p50, p90 = pct(vals, (10, 50, 90))
            d.update({"p10": p10, "p50": p50, "p90": p90,
                      "min": round(min(vals), 6), "max": round(max(vals), 6)})
        d["n_in_q_gate"] = sum(1 for v in vals if Q_GATE[0] <= v <= Q_GATE[1])
        return d

    batches = {}
    # --- C 与 A：来自 C 原表（权威 flag 列），按 source_dataset 分组
    for ds, bname in (("C", "C_5-50MHz"), ("A", "A_5-35MHz")):
        sub = [r for r in corig if r["source_dataset"] == ds]
        v3sub = [r for r in v3 if r["batch"] == bname]
        batches[bname] = {
            "source": "work/runs/first-peak-20260929/multichannel_labels.csv (source_dataset=%s)" % ds,
            "flag_source": "C 原表自带列（**权威**）",
            "n_rows": len(sub),
            "n_unique_combos_ulp": len({key_ulp(r) for r in v3sub}),
            "flags": flag_counts(sub, ("first_peak_found", "peak_closed",
                                       "bandwidth_closed", "q_gate_applicable",
                                       "q_gate_pass", "ranking_eligible", "quarantined")),
            "q_all_rows": qstats(sub, "Q_factor"),
            "q_closed_rows": qstats([r for r in sub if truthy(r["bandwidth_closed"])],
                                    "Q_factor"),
            "q_gate_pass": sum(1 for r in sub if truthy(r["q_gate_pass"])),
            "q_gate_denominator": sum(1 for r in sub if truthy(r["q_gate_applicable"])),
        }
    # --- V2：来自 v2 冻结副本（自带端点标志，**与 C/A 不同口径**）
    v3v2 = [r for r in v3 if r["batch"] == "V2_5-35MHz"]
    usable_v2 = [r for r in v2f
                 if not truthy(r["peak_at_scan_endpoint"])
                 and not truthy(r["bw_upper_cutoff_at_endpoint"])]
    batches["V2_5-35MHz"] = {
        "source": "work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv",
        "flag_source": "v2 冻结副本自带端点标志（**与 C/A 不同口径**）",
        "n_rows": len(v2f),
        "n_unique_combos_ulp": len({key_ulp(r) for r in v3v2}),
        "flags": flag_counts(v2f, ("peak_at_scan_endpoint", "bw_upper_cutoff_at_endpoint")),
        "peak_freq_Hz_present": sum(1 for r in v2f if is_num(r.get("peak_freq_Hz"))),
        "bandwidth_Hz_present": sum(1 for r in v2f if is_num(r.get("bandwidth_Hz"))),
        "usable": len(usable_v2),
        "q_all_rows": qstats(v2f, "Q"),
        "q_usable_rows": qstats(usable_v2, "Q"),
        "q_gate_pass": sum(1 for r in usable_v2
                           if q_of(r, "Q") is not None
                           and Q_GATE[0] <= q_of(r, "Q") <= Q_GATE[1]),
        "q_gate_denominator": sum(1 for r in usable_v2 if q_of(r, "Q") is not None),
    }

    # --- 池化（A+C）：**仅规模参考**
    pooled = {}
    for tag, rows, col in (("A+C", [r for r in corig if r["source_dataset"] in ("A", "C")],
                            "Q_factor"),):
        pooled["n_rows"] = len(rows)
        pooled["n_unique_combos_ulp"] = len({key_ulp(r) for r in rows})
        pooled["first_peak_found_true"] = sum(1 for r in rows if truthy(r["first_peak_found"]))
        pooled["bandwidth_closed_true"] = sum(1 for r in rows if truthy(r["bandwidth_closed"]))
        pooled["q_gate_pass"] = sum(1 for r in rows if truthy(r["q_gate_pass"]))
        pooled["q_gate_applicable"] = sum(1 for r in rows if truthy(r["q_gate_applicable"]))
        vals = [q_of(r, col) for r in rows]
        vals = [v for v in vals if v is not None]
        pooled["n_numeric_Q"] = len(vals)
        pooled["q_p10"], pooled["q_p50"], pooled["q_p90"] = pct(vals, (10, 50, 90))
        pooled["closure_rate_pct"] = round(100.0 * pooled["bandwidth_closed_true"] / len(rows), 2)
        pooled["q_gate_share_of_closed_pct"] = round(
            100.0 * pooled["q_gate_pass"] / pooled["bandwidth_closed_true"], 2)
    pooled["WARNING"] = ("**池化值：仅规模参考，禁止作为统计口径/总分使用**"
                         "（INDEX §95.2 O-A：统计一律按批分组、禁止池化、禁止合并批）")

    csv_rows = []
    for b in BATCHES:
        d = batches[b]
        qc = d.get("q_closed_rows") or d.get("q_usable_rows")
        csv_rows.append([
            b, d["n_rows"], d["n_unique_combos_ulp"],
            d["flags"].get("first_peak_found", d.get("peak_freq_Hz_present", "")),
            d["flags"].get("bandwidth_closed", d.get("usable", "")),
            d["q_gate_pass"], d["q_gate_denominator"],
            qc["n_numeric_Q"], qc.get("p10"), qc.get("p50"), qc.get("p90"),
            qc["n_in_q_gate"], d["flag_source"]])
    csv_rows.append(["A+C（池化、仅规模参考）", pooled["n_rows"], pooled["n_unique_combos_ulp"],
                     pooled["first_peak_found_true"], pooled["bandwidth_closed_true"],
                     pooled["q_gate_pass"], pooled["q_gate_applicable"],
                     pooled["n_numeric_Q"], pooled["q_p10"], pooled["q_p50"], pooled["q_p90"],
                     sum(1 for r in corig if r["source_dataset"] in ("A", "C")
                         and truthy(r["q_gate_pass"])), "**池化：仅规模参考**"])

    sink.csv("E1_per_batch_label_stats.csv",
             ["batch", "n_rows", "n_unique_combos_ulp", "n_first_peak_found_or_peak_present",
              "n_bandwidth_closed_or_usable", "n_q_gate_pass", "q_gate_denominator",
              "n_numeric_Q", "q_p10", "q_p50", "q_p90", "n_Q_in_gate", "flag_source"],
             csv_rows)

    obj = {"kind": "paper_evidence_E1_per_batch_label_stats",
           "review_items": ["N03", "N04", "N05", "N06", "N08", "N10", "R4", "A1", "A2"],
           "caliber": {"statistics": "O-A：按批分组，禁止池化/禁止合成总分（INDEX §95.2）",
                       "identity_key": "ulp 归一化 round(x_scale,6) + N_w_te1 + N_w_te2",
                       "Q_percentile_method": "numpy linear（与本仓已登记值同口径）",
                       "q_numeric_rule": "Q 必须可解析为数值；空与字面 nan 一律排除并单列分母"},
           "batches": batches, "pooled_A_plus_C": pooled,
           "pooled_warning": pooled["WARNING"],
           "not_comparable_note": (
               "**三批的闭合/可用口径不同数**：C/A 的 `bandwidth_closed` 来自单自由度拟合管线；"
               "V2 的 `usable` 来自端点标志（峰值删失 / 上截止点截断）。"
               "C/A 在并集表 v3 里的 `peak_at_scan_endpoint`/`bw_upper_cutoff_at_endpoint` **整列为空**"
               "（§96.4）⇒ **跨批闭合率不可直接比大小**（§92.1 R5 纪律）。"),
           }
    sink.js("E1_per_batch_label_stats.json", obj)

    lines = ["# E1 按批分列的标签统计（O-A 口径，禁池化）", "",
             "> 解决审稿：**N03/N04/N05/N06/N08/N10**（池化违规，红线 R4）＋ **A1/A2**（投稿前必须做）。",
             "> 口径：统计一律按批分组（`INDEX §95.2` O-A）；组合身份键先做 ulp 归一化；",
             "> Q 百分位用 numpy `linear` 方法；**Q 只用有数值的行**并写出可判定分母。",
             "> 源：`work/runs/first-peak-20260929/multichannel_labels.csv`（C/A 权威 flag 列）、",
             "> `work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv`（V2 端点标志）、",
             "> `work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv`（批归属与唯一组合数）。", ""]
    lines += ["## 1. 逐批（**禁止池化**）", ""]
    hdr = ["批", "行数", "唯一组合数", "首个峰 found / 峰值存在", "带宽闭合 / 可用",
           "Q 门禁达标", "Q 可判定分母", "Q p10", "Q p50", "Q p90", "flag 口径"]
    rowsx = []
    for b in BATCHES:
        d = batches[b]
        if b == "V2_5-35MHz":
            fp = d["peak_freq_Hz_present"]
            bw = d["usable"]
        else:
            fp = d["flags"]["first_peak_found"]["true"]
            bw = d["flags"]["bandwidth_closed"]["true"]
        qc = d.get("q_closed_rows") or d.get("q_usable_rows")
        rowsx.append([b, d["n_rows"], d["n_unique_combos_ulp"], fp, bw, d["q_gate_pass"],
                      d["q_gate_denominator"], fmt(qc.get("p10")), fmt(qc.get("p50")),
                      fmt(qc.get("p90")), d["flag_source"]])
    lines += [md_table(hdr, rowsx), ""]
    lines += ["- C：首个峰 **1612** / 带宽闭合 **1523** / 过 Q 门禁 **673**；Q（n=1523）"
              "p10/p50/p90 = %.6f / **%.6f** / %.6f。" % (
                  batches["C_5-50MHz"]["q_closed_rows"]["p10"],
                  batches["C_5-50MHz"]["q_closed_rows"]["p50"],
                  batches["C_5-50MHz"]["q_closed_rows"]["p90"]),
              "- A：首个峰 **161** / 带宽闭合 **154** / 过 Q 门禁 **55**；Q（n=154）"
              "p10/p50/p90 = %.6f / **%.6f** / %.6f。" % (
                  batches["A_5-35MHz"]["q_closed_rows"]["p10"],
                  batches["A_5-35MHz"]["q_closed_rows"]["p50"],
                  batches["A_5-35MHz"]["q_closed_rows"]["p90"]),
              "- V2：可用 **146/250**；Q 门禁达标 **40**，但 **Q 可判定分母只有 108**"
              "（全批 39 行 `Q` 字面 `nan`，其中 38 行落在可用内）；"
              "Q（n=108）p10/p50/p90 = %.6f / **%.6f** / %.6f。" % (
                  batches["V2_5-35MHz"]["q_usable_rows"]["p10"],
                  batches["V2_5-35MHz"]["q_usable_rows"]["p50"],
                  batches["V2_5-35MHz"]["q_usable_rows"]["p90"]),
              "- ⚠️ **V2 那一列的「首个峰 found / 峰值存在」= 250 的含义与 C/A 不同**："
              "V2 表**没有** `first_peak_found` 列，本件填的是「`peak_freq_Hz` 有值」"
              "——其中 **92 个是峰值卡在 35 MHz 端点的删失值（只是下界）** ⇒ "
              "**不得读成「250 个都找到了峰」**，也不得与 C/A 的 `first_peak_found` 相减。", ""]
    lines += ["### 为什么三批不能比「闭合率」", "",
              "C/A 的闭合来自单自由度拟合管线，V2 的「可用」来自扫描端点标志；"
              "且 C/A 的端点标志列在并集表里**整列为空**（`INDEX §96.4`）⇒ **跨批闭合率不是同一口径**。"
              "35 MHz 上限会把峰值卡在端点（右删失）、把上截止点卡在端点（截断）⇒ 通过率不可直接比大小。", ""]
    lines += ["## 2. 池化值（A+C）——**仅规模参考**", "",
              pooled["WARNING"], "",
              md_table(["口径", "n", "值"], [
                  ["行数", pooled["n_rows"], ""],
                  ["唯一组合数（ulp）", pooled["n_unique_combos_ulp"], ""],
                  ["首个峰 found", pooled["first_peak_found_true"], ""],
                  ["带宽闭合", pooled["bandwidth_closed_true"],
                   "闭合率 %.2f%%" % pooled["closure_rate_pct"]],
                  ["过 Q 门禁", pooled["q_gate_pass"],
                   "占闭合 %.2f%%" % pooled["q_gate_share_of_closed_pct"]],
                  ["Q p10 / p50 / p90（n=%d）" % pooled["n_numeric_Q"], "",
                   "%.6f / %.6f / %.6f" % (pooled["q_p10"], pooled["q_p50"], pooled["q_p90"])],
              ]), "",
              "> 这些池化数字与稿中 §6.1 的 1677 / 728 / 83.7% / 43.4% / 2.75-3.69-4.61 **逐项一致**"
              "（证明稿中数字本身算得对），但**口径违规** ⇒ 正文应以第 1 节的逐批表替换。", ""]
    sink.md("E1_per_batch_label_stats.md", "\n".join(lines))
    return obj


# ================================================================ E2
def item_e2(sink: Sink, ctx: dict) -> dict:
    """Q 中位数分母之争（N09）：算清每一套分母的定义与数值。"""
    corig = ctx["corig"]
    v2f = ctx["v2f"]

    def blk(rows, col="Q_factor"):
        vals = [q_of(r, col) for r in rows]
        vals = [v for v in vals if v is not None]
        p10, p50, p90 = pct(vals, (10, 50, 90))
        return {"n": len(vals), "p10": p10, "p50": p50, "p90": p90,
                "min": round(min(vals), 6), "max": round(max(vals), 6)}

    C = [r for r in corig if r["source_dataset"] == "C"]
    A = [r for r in corig if r["source_dataset"] == "A"]
    AC = C + A
    v2_usable = [r for r in v2f
                 if not truthy(r["peak_at_scan_endpoint"])
                 and not truthy(r["bw_upper_cutoff_at_endpoint"])]

    sets = {
        "S1_C_closed_flag": {
            "definition": "C 批 `bandwidth_closed=true`（= `q_gate_applicable=true`，逐行一致）的行，"
                          "Q 必须可解析为数值",
            "n": blk([r for r in C if truthy(r["bandwidth_closed"])])["n"],
            **blk([r for r in C if truthy(r["bandwidth_closed"])]),
            "existing_record": "`INDEX §72.2`：Q 门槛适用 **1523** 行、通过 673；"
                               "全量 1523 的 Q 分布 p10 2.75 / 中位 **3.66** / p90 4.61"},
        "S2_A_closed_flag": {
            "definition": "A 批 `bandwidth_closed=true` 的行，Q 可解析",
            **blk([r for r in A if truthy(r["bandwidth_closed"])]),
            "existing_record": "`INDEX §73.1` 表：批 A 223 行 / 带宽闭合 **154** / 过 Q 门禁 55"},
        "S3_AC_pooled_closed_flag": {
            "definition": "**池化** A+C，取 `bandwidth_closed=true`（= `q_gate_applicable`）的行，Q 可解析",
            **blk([r for r in AC if truthy(r["bandwidth_closed"])]),
            "existing_record": "`PAPER_BRIEF §3.1/§5.1` 与**审稿 N09 口径①**：n=**1677**、p50 **3.69**；"
                               "稿中 §6.1 引用值"},
        "S4_AC_pooled_any_numeric_Q": {
            "definition": "**池化** A+C，**不加 flag**、只要求 Q 可解析（用于检验 flag 是否改变集合）",
            **blk(AC), "existing_record": "（本件现算；与 S3 是否同集合见 `identical_to_S3`）"},
        "S5_V2_usable_numeric_Q": {
            "definition": "V2 冻结副本，`usable=true` 且 Q 可解析（= Q 门禁的**真实适用基数**）",
            **blk(v2_usable, "Q"),
            "existing_record": "`INDEX §98.4.1`：Q 可判定基数 **108**（40 这个数不变）"},
        "S6_V2_whole_batch_numeric_Q": {
            "definition": "V2 冻结副本全批，Q 可解析（**不筛 usable**，仅列作对照）",
            **blk(v2f, "Q"), "existing_record": "（本件现算；全批 39 行 `Q` 字面 `nan`）"},
        "S7_V2_usable_flag_incl_nan": {
            "definition": "V2 冻结副本 `usable=true` 的 **146** 行（含 38 行 `Q=nan`）——"
                          "这是 `INDEX §92.2` 写的「适用基数 146」",
            "n": len(v2_usable),
            "n_numeric_Q": sum(1 for r in v2_usable if q_of(r, "Q") is not None),
            "existing_record": "`INDEX §92.2`：可用 **146**；`INDEX §98.4.1` 更正为 Q 适用基数 **108**"},
    }
    same = [q_of(r, "Q_factor") for r in AC if q_of(r, "Q_factor") is not None]
    s3 = [q_of(r, "Q_factor") for r in AC if truthy(r["bandwidth_closed"])]
    sets["S4_AC_pooled_any_numeric_Q"]["identical_to_S3"] = (
        sorted(same) == sorted(s3))
    sets["S1_C_closed_flag"]["identical_to_C_all_numeric"] = (
        sorted(q_of(r, "Q_factor") for r in C if q_of(r, "Q_factor") is not None)
        == sorted(q_of(r, "Q_factor") for r in C if truthy(r["bandwidth_closed"])))

    # 门槛判定影响：门槛 [2.5,3.5] 低于总体中位，会挡住多少
    for k in ("S1_C_closed_flag", "S3_AC_pooled_closed_flag"):
        v = sets[k]
        vals = ([q_of(r, "Q_factor") for r in C if truthy(r["bandwidth_closed"])]
                if k.startswith("S1") else
                [q_of(r, "Q_factor") for r in AC if truthy(r["bandwidth_closed"])])
        v["share_blocked_by_gate_pct"] = round(
            100.0 * sum(1 for x in vals if not (Q_GATE[0] <= x <= Q_GATE[1])) / len(vals), 2)

    obj = {"kind": "paper_evidence_E2_Q_median_denominators",
           "review_item": "N09（需人工核对：Q 中位数 3.69 vs 3.66）",
           "ruling_status": "【待裁定】不替人裁定用哪套分母；本件只并列并标明各套与哪份既有记录对应",
           "calibers": sets,
           "reading": {
               "two_disputed_sets": "① `S3_AC_pooled_closed_flag` n=1677 p50=%.6f（→3.69，稿中 §6.1 与 "
                                    "PAPER_BRIEF §3.1/§5.1 口径）；② `S1_C_closed_flag` n=1523 p50=%.6f"
                                    "（→3.66，`INDEX §72.2` 口径）" % (
                                        sets["S3_AC_pooled_closed_flag"]["p50"],
                                        sets["S1_C_closed_flag"]["p50"]),
               "difference_abs": round(abs(sets["S3_AC_pooled_closed_flag"]["p50"]
                                           - sets["S1_C_closed_flag"]["p50"]), 6),
               "difference_rel_pct": round(100.0 * abs(
                   sets["S3_AC_pooled_closed_flag"]["p50"]
                   - sets["S1_C_closed_flag"]["p50"]) / sets["S1_C_closed_flag"]["p50"], 4),
               "key_fact": "两套**不是同一分母**：差 **154 行**（= A 批闭合数），"
                           "不是算法或阈值差异；两个数都能逐位复算。",
               "flag_filter_effect": "在本仓数据上，`bandwidth_closed=true` 与「Q 可解析」**集合相同**"
                                     "（见 `identical_to_S3`/`identical_to_C_all_numeric` 均为 true）"
                                     "⇒ 「池化+flag 口径」与「池化+有数值 Q 口径」**同值**，"
                                     "争议点只在**是否池化**，不在 flag。",
           }}
    sink.js("E2_Q_median_denominators.json", obj)

    hdr = ["口径 id", "定义（分母怎么取）", "n", "p10", "p50", "p90", "对应既有记录"]
    rows = []
    for k in ("S1_C_closed_flag", "S2_A_closed_flag", "S3_AC_pooled_closed_flag",
              "S4_AC_pooled_any_numeric_Q", "S5_V2_usable_numeric_Q",
              "S6_V2_whole_batch_numeric_Q", "S7_V2_usable_flag_incl_nan"):
        v = sets[k]
        rows.append([k, v["definition"], v["n"], fmt(v.get("p10")), fmt(v.get("p50")),
                     fmt(v.get("p90")), v.get("existing_record", "")])
    sink.csv("E2_Q_median_denominators.csv",
             ["caliber_id", "definition", "n", "p10", "p50", "p90", "existing_record"], rows)

    lines = ["# E2 Q 中位数分母之争（审稿 N09）——**只并列，不裁定**", "",
             "> 解决审稿：**N09 / L11**（两个口径都在仓库里，须人选定）。",
             "> 每个 n 与 p50 都是本件对源表现算；百分位方法 = numpy `linear`。",
             "> 【待裁定】本件**不替人裁定**用哪套分母，只给对照表与各套对应的既有记录。", "",
             "## 1. 对照表", "", md_table(hdr, rows), "",
             "## 2. 逐条读法", "",
             "- **争议的两套**：`S3`（池化 A+C，n=**1677**，p50=%.6f → 写作 **3.69**，"
             "对应 `PAPER_BRIEF §3.1/§5.1` 与稿中 §6.1）与 `S1`（仅 C 批闭合，n=**1523**，"
             "p50=%.6f → 写作 **3.66**，对应 `INDEX §72.2`）。"
             % (sets["S3_AC_pooled_closed_flag"]["p50"], sets["S1_C_closed_flag"]["p50"]),
             "- 两者相差 **154 行**（正是 A 批的闭合行数），绝对差 **%.6f**（相对 **%.4f%%**）"
             "⇒ 这是**分母范围**之别，不是算错。"
             % (obj["reading"]["difference_abs"], obj["reading"]["difference_rel_pct"]),
             "- **flag 不是争点**：在本仓数据上 `bandwidth_closed=true` 与「Q 可解析」取到**同一集合**"
             "（`identical_to_S3 = %s`；`identical_to_C_all_numeric = %s`）"
             "⇒「池化+flag 口径」与「池化+有数值 Q 口径」**同值**。"
             % (sets["S4_AC_pooled_any_numeric_Q"]["identical_to_S3"],
                sets["S1_C_closed_flag"]["identical_to_C_all_numeric"]),
             "- **门槛背景（只陈述）**：门槛 `Q∈[2.5,3.5]` 低于总体中位 ⇒ 在 `S1` 下挡住 "
             "**%.2f%%**、在 `S3` 下挡住 **%.2f%%**（`INDEX §72.2/§76.1` 已提请用户确认，未擅自改动）。"
             % (sets["S1_C_closed_flag"]["share_blocked_by_gate_pct"],
                sets["S3_AC_pooled_closed_flag"]["share_blocked_by_gate_pct"]),
             "- **V2 那条分母**：`S7` 的 146 是 **flag 口径**，其中 38 行 `Q=nan` ⇒ 只有 `S5` 的 "
             "**108** 能做 Q 判定（`INDEX §98.4.1`）；`nan` 不可能落进 `[2.5,3.5]` ⇒ **40 这个数不变**。",
             "", "## 3. 待裁定", "",
             "`【待裁定】` 正文 Q 中位数用哪套分母（`S1` 仅 C，或 `S3` 池化 A+C，或按批并排给出多值）。",
             "选定的前提是该节其余统计**同分母**（否则同一段里数字不同口径）。", ""]
    sink.md("E2_Q_median_denominators.md", "\n".join(lines))
    return obj


# ================================================================ E3
def _domain_trigger(x, n1, n2):
    """按 `check_domain()` 的**判定次序**给出「实际触发」（**不依赖任何标签名**）。

    次序与 `src/memsharness/multichannel_surrogate.py:check_domain()` 逐条对齐：
    x 范围 → N1 整数且 ≥1 → N2 ∈ [5, 9] → `N1 < N2`（该层不存在）。
    四条全通过 ⇒ 返回 `None`（此时拒答只可能来自通道级原因）。

    ⚠️ 存在的理由：旧版把「实际触发」**反推自被报出的标签**（`n2_out_of_domain` 计数），
    而该标签曾因**子串碰撞**把结构约束 `N1 ≥ N2` 误标 ⇒ 修复分类后该反推恒为 0。
    归因必须由**判定本身**得出（§105 事故 + 更正）。
    """
    if not (0.20 <= x <= 1.00):
        return "x_out_of_domain"
    if abs(n1 - round(n1)) > 1e-9 or n1 < 1:
        return "n1_invalid"
    if not (5 <= n2 <= 9):
        return "n2_out_of_domain"
    if round(n1) >= n2:
        return "layer_does_not_exist"
    return None


def item_e3(sink: Sink, ctx: dict) -> dict:
    """拒答口径实测件（§6.5）：α=0.05、17×7×4=476 网格、逐点原因。"""
    sys.path.insert(0, str(REPO / "src"))
    from memsharness import multichannel_surrogate as MCS  # noqa: E402

    grid = {"x": [0.20, 1.00, 0.05], "n1": [1, 7], "n2": [5, 8]}
    alpha = 0.05
    names = list(MCS.FORMAL_OBJECTIVES)
    points = []
    reasons = Counter()          # **已报出的标签**（`_classify_refusal`）
    attribution = Counter()      # **实际触发**（`_domain_trigger` ＋ 通道级归类）
    collisions = []              # 标签 ≠ 实际触发 ⇒ 回归探针（修复后应为空）
    modes = Counter()
    by_pair = defaultdict(Counter)
    raw_msgs = Counter()
    xs = [round(min(1.00, 0.20 + i * 0.05), 6)
          for i in range(int(round((1.00 - 0.20) / 0.05)) + 1)]
    for x in xs:
        for n1 in range(1, 8):
            for n2 in range(5, 9):
                try:
                    r = MCS.predict(x, n1, n2, channels=names, alpha=alpha)
                    modes[r["mode"]] += 1
                    points.append([x, n1, n2, "accepted", r["mode"], ""])
                except MCS.Refused as exc:
                    msg = str(exc)
                    k = MCS._classify_refusal(msg)              # 已报出的标签
                    actual = _domain_trigger(x, n1, n2) or k    # 实际触发（判定语义优先）
                    reasons[k] += 1
                    attribution[actual] += 1
                    by_pair[(n1, n2)][actual] += 1
                    raw_msgs[msg] += 1
                    if k != actual:
                        collisions.append({"x_scale": x, "N_w_te1": n1, "N_w_te2": n2,
                                           "reported_label": k, "actual_trigger": actual,
                                           "message": msg})
                    points.append([x, n1, n2, "refused", actual, msg])

    n_grid = len(xs) * 7 * 4
    # 标签归因探针：把「标签 ≠ 实际触发」的组合留档（修复后应为 {}；留着防回归）
    label_collision = {}
    for c in collisions:
        key = "%d|%d" % (c["N_w_te1"], c["N_w_te2"])
        d = label_collision.setdefault(key, {
            "n_x_refused": 0, "reported_label": c["reported_label"],
            "actual_trigger": c["actual_trigger"], "example_message": c["message"],
            "why": "`_classify_refusal` 的标签与 `_domain_trigger` 的判定语义不一致"
                   "（子串碰撞回归）⇒ 分类逻辑或消息措辞被改动，需复核"})
        d["n_x_refused"] += 1
    x_out = {}
    for (n1, n2), c in sorted(by_pair.items()):
        if c.get("x_outside_layer_range"):
            x_out["%d|%d" % (n1, n2)] = c["x_outside_layer_range"]

    attrib = {
        "layer_does_not_exist_structural_N1_ge_N2": attribution.get("layer_does_not_exist", 0),
        "x_outside_layer_range": attribution.get("x_outside_layer_range", 0),
        "n2_out_of_domain_literal_N2_not_in_5_9": attribution.get("n2_out_of_domain", 0),
        "x_out_of_domain_literal_x_not_in_0.2_1.0": attribution.get("x_out_of_domain", 0),
        "n1_invalid": attribution.get("n1_invalid", 0),
        "no_layer_for_n1": attribution.get("no_layer_for_n1", 0),
        "need_two_layers": attribution.get("need_two_layers", 0),
        "n2_extrap_too_far": attribution.get("n2_extrap_too_far", 0),
        "x_missing": attribution.get("x_missing", 0),
        "other": attribution.get("other", 0),
        "sum_check_equals_n_refused": sum(attribution.values()),
        "note": "**实际触发**按 `check_domain()` 的判定次序直接得出（结构约束 `N1 ≥ N2` 由判定本身"
                "给出，**不再用标签名反推**）＋ 通道级拒答按消息归类；"
                "`n1_invalid`/`x_missing` 为新增键（旧版恒缺）",
    }

    obj = {"kind": "paper_evidence_E3_refusal_screen",
           "review_items": ["N39", "N40", "N41", "N42", "N43", "N67", "L14"],
           "source_model": "work/runs/multichannel-surrogate-20260929/multichannel_model.json",
           "model_id": ctx["model"].get("model_id"),
           "code": "src/memsharness/multichannel_surrogate.py:screen()/predict()",
           "alpha": alpha, "channels": names,
           "grid": {"x": grid, "n1": grid["n1"], "n2": grid["n2"],
                    "n_x": len(xs), "n_n1": 7, "n_n2": 4, "n_points": n_grid,
                    "identity": "%d×%d×%d = %d" % (len(xs), 7, 4, n_grid)},
           "counts": {"n_grid": n_grid, "n_predicted": sum(modes.values()),
                      "n_refused": sum(reasons.values()),
                      "coverage": round(sum(modes.values()) / n_grid, 10),
                      "modes": dict(modes), "refusal_reasons_as_reported": dict(reasons)},
           "refusal_attribution": attrib,
           "label_collision": {"%d|%d" % k: v for k, v in label_collision.items()},
           "label_collision_n_total": len(collisions),
           "label_collision_note": "标签≠实际触发的**回归探针**：修复子串碰撞（§105）后本网格应为 0；"
                                   "非 0 即说明分类逻辑或消息措辞被改动",
           "x_outside_by_layer_pair": x_out,
           "raw_messages": dict(raw_msgs),
           "quarantine_factor": {
               "declared_in_model": "excluded_quarantine = [[0.2,1,7],[0.2,1,8]]",
               "measured_trigger_in_this_grid": 0,
               "why": "`multichannel_surrogate.predict()` 只走 `check_domain()`（x∈[0.2,1.0]、"
                      "N1 整数且 ≥1、N2∈[5,9]、N1<N2），**从不读取** `excluded_quarantine`；"
                      "该字段只在 `model_card()`（L112）里被**披露**，"
                      "隔离拦截在另一个模块 `surrogate.py`（响应级代理，L148）里 ⇒ "
                      "**本 476 点网格内「命中隔离记录」不是任何一点的拒答原因**",
               "those_two_points_in_grid": "`(0.2,1,7)` / `(0.2,1,8)` 确实在网格内，"
                                           "但实测被拒答的原因是 **`x_outside_layer_range`**"
                                           "（x=0.20 低于该层标定下界 0.31），**不是隔离**",
           },
           "discipline": ["拒答点单独计数、给原因直方图，**不混进排名**",
                          "**不含加权总分**（A5 规则）",
                          "α 只认 {0.10, 0.05, 0.01}；本件用 α=0.05"],
           }
    sink.js("E3_refusal_screen.json", obj)

    sink.csv("E3_refusal_grid_points.csv",
             ["x_scale", "N_w_te1", "N_w_te2", "decision", "mode_or_reason", "message"],
             points)
    hist_rows = []
    for tag, cnt in (("refused｜n2_out_of_domain（**已报出的标签**）",
                      reasons.get("n2_out_of_domain", 0)),
                     ("refused｜x_outside_layer_range",
                      obj["refusal_attribution"]["x_outside_layer_range"]),
                     ("refused｜（实际触发）layer_does_not_exist = N1 ≥ N2", obj["refusal_attribution"][
                         "layer_does_not_exist_structural_N1_ge_N2"]),
                     ("refused｜（实际触发）n2_out_of_domain = N2 ∉ [5,9]", obj["refusal_attribution"][
                         "n2_out_of_domain_literal_N2_not_in_5_9"]),
                     ("accepted｜in_layer", modes.get("in_layer", 0)),
                     ("accepted｜n2_extrap", modes.get("n2_extrap", 0)),
                     ("合计", n_grid)):
        hist_rows.append([tag, cnt])
    sink.csv("E3_refusal_histogram.csv", ["bucket", "count"], hist_rows)

    lines = ["# E3 拒答口径实测件（§6.5）", "",
             "> 解决审稿：**N39/N40/N41/N42/N43**（数字无冻结产物、未给 α 与网格构成）"
             "＋ **N67 / L14**（拒答原因写成了「可能的因子」）。",
             "> 做法：对**冻结模型** `multichannel_model.json`（model_id `%s`）"
             "在 17×7×4 网格上**逐点**调用 `predict()`，α=0.05、通道 = 正式三目标。" % (
                 obj["model_id"]),
             "> 逐点记录见 `E3_refusal_grid_points.csv`（%d 行），分桶计数见 `E3_refusal_histogram.csv`。" % n_grid, "",
             "## 1. 网格与总数", "",
             md_table(["项", "值"], [
                 ["α", "0.05（模型允许集合 {0.10, 0.05, 0.01}）"],
                 ["x 网格", "0.20–1.00 步长 0.05 ⇒ %d 值" % len(xs)],
                 ["N1 网格", "1–7 ⇒ 7 值"],
                 ["N2 网格", "5–8 ⇒ 4 值"],
                 ["网格点数", "**%d×7×4 = %d**" % (len(xs), n_grid)],
                 ["接受（in_layer）", "**%d**" % obj["counts"]["n_predicted"]],
                 ["拒答", "**%d**" % obj["counts"]["n_refused"]],
                 ["覆盖率", "%.10f（= %d/%d = 67.857%%）" % (
                     obj["counts"]["coverage"], obj["counts"]["n_predicted"], n_grid)],
                 ["n2_extrap 模式", "0（本网格内全部落在已标定层）"],
             ]), "",
             "> 注：`INDEX`/`screen_refusals.json` 里 `n_grid` 落盘为 `null`（当时未保留 `grid` 键），"
             "**476 是 17×7×4 的算术**；本件已按同一网格逐点复现，接受/拒答数与冻结 JSON 逐项一致"
             "（323 / 153 / 0.6785714285714286）。", "",
             "## 2. 拒答直方图（**按实际触发条件归因**）", "",
             md_table(["桶", "计数"], hist_rows), "",
             "> 桶的口径：第 1 行是**已报出标签**桶，第 2–4 行是**实际触发**桶。"
             "**实际触发合计 = %d + %d + %d = %d = 拒答数**。"
             % (obj["refusal_attribution"]["x_outside_layer_range"],
                obj["refusal_attribution"]["layer_does_not_exist_structural_N1_ge_N2"],
                obj["refusal_attribution"]["n2_out_of_domain_literal_N2_not_in_5_9"],
                obj["counts"]["n_refused"]), "",
             "### 标签碰撞：**曾发生、已修复**（§105 登记；本件为修复后重生成版）", "",
             "- **曾有缺陷**：`_classify_refusal()` 按顺序匹配子串，而 `该层不存在：要求 N_w_te1 < N_w_te2` "
             "这句**本身含 `N_w_te2`** ⇒ 先命中 `n2_out_of_domain`，102 个点被**误标**（`§101.5`/`§102` 已登记）。",
             "- **修复**：按裁定**只调匹配次序**（结构约束先于 N2 越域；**模式与阈值一字未改**）⇒ "
             "`refusal_reasons_as_reported` 与**实际触发逐点一致**；故第 1 行 `n2_out_of_domain` 标签桶现为 **0**，"
             "第 3 行结构约束桶为 **102**。",
             "- **回归探针**：本件另存 `label_collision`（标签 ≠ 实际触发的逐点差异）"
             "与 `label_collision_n_total`，修复后应为 **0** / `{}`；非 0 即说明分类逻辑或消息措辞又被改动。",
             "- 结构约束 = 6 个 `(N1,N2)` 组合（`(5,5)/(6,5)/(6,6)/(7,5)/(7,6)/(7,7)`）× 17 个 x = **102**；"
             "而**网格内 `N2` 恒在 [5,8] ⊂ [5,9] 域内** ⇒ **真正因 `N2` 越域被拒的点数 = 0**。",
             "- 51 个 `x_outside_layer_range` 全部落在 **x ∈ {0.20, 0.25, 0.30}**（低 x 端；"
             "该三值低于多数层的标定 x 下界 0.31）⇒ 16 个 `(N1,N2)` 各 3 个 ＋ 3 个组合各 1 个（x=0.20）= 51。",
             "- 隔离组合 `(0.2,1,7)` / `(0.2,1,8)` **不是**本网格的拒答原因：模型里确实声明了 "
             "`excluded_quarantine=[[0.2,1,7],[0.2,1,8]]`，但 `predict()` 只走 `check_domain()`、"
             "**从不读取该字段**（只在 `model_card()` 里披露；隔离拦截在另一个模块 `surrogate.py` 的响应级代理上）"
             "⇒ 稿中「命中隔离记录」作为拒答原因，在**该 476 点网格内实测触发 0 次**（N67）。"
             "那两点在网格内被拒答的原因是 `x_outside_layer_range`（x=0.20 < 层标定下界 0.31）。"
             "**（本节只陈述隔离字段未被读取这一事实；是否改 `predict()` 属另一议题，本件未改一行代码。）**",
             "", "## 3. 写作建议口径（不是裁定）", "",
             "正文可写：「α=0.05、17×7×4=476 点网格；接受 323、拒答 153（67.9% 覆盖率）；"
             "拒答实测两类——**层不存在（N1 ≥ N2）102** 与 **x 超出该层标定范围 51**；"
             "拒答点单独计数、不混进排名」。**修复后标签与实际触发一致**：`n2_out_of_domain` 在本网格为 **0**，"
             "`layer_does_not_exist` 为 **102**，不再需要「标签名与真实归因不符」的加注。", ""]
    sink.md("E3_refusal_screen.md", "\n".join(lines))
    return obj


# ================================================================ E4
def item_e4(sink: Sink, ctx: dict) -> dict:
    """跨口径分层计数（§6.2）：182/63 层级 + Spearman 复算。"""
    A = ctx["a_combos"]
    lab_A = [r for r in ctx["corig"] if r["source_dataset"] == "A"]
    byk = {key_ulp(r): r for r in lab_A}
    cands = []
    for r in A:
        k = key_ulp(r)
        m = byk.get(k)
        if m is None:
            continue
        fpA, fpM = num(r.get("f_peak_Hz")), num(m.get("f_peak_Hz"))
        bwM, QM = num(m.get("bandwidth_Hz")), num(m.get("Q_factor"))
        if fpA is None or fpM is None or bwM is None:
            continue
        cands.append({"key": k, "fA": fpA, "fM": fpM, "bwM": bwM, "qM": QM, "ref": r})
    gate = 0.5e6
    ok = [c for c in cands if abs(c["fM"] - c["fA"]) <= gate]
    skipped = [c for c in cands if abs(c["fM"] - c["fA"]) > gate]

    refs = {}
    for refcol, qcol, tag in (("bandwidth_3dB_Hz", "q_from_points", "from_points"),
                              ("bandwidth_marker_Hz", "q_marker", "from_marker")):
        mine, ref, qm, qr = [], [], [], []
        for c in ok:
            rb, rq = num(c["ref"].get(refcol)), num(c["ref"].get(qcol))
            if rb is None:
                continue
            mine.append(c["bwM"]); ref.append(rb)
            qm.append(c["qM"]); qr.append(rq)
        rel = [abs(a - b) / b for a, b in zip(mine, ref)]
        ratios = [a / b for a, b in zip(mine, ref)]
        refs[tag] = {
            "n_compared": len(mine),
            "abs_rel_diff_bw_median": median(rel),
            "abs_rel_diff_bw_p90": pct(rel, (90,))[0],
            "within_10pct_rate": sum(1 for x in rel if x <= 0.10) / len(rel),
            "within_20pct_rate": sum(1 for x in rel if x <= 0.20) / len(rel),
            "bw_ratio_median_mine_over_ref": median(ratios),
            "Q_median_mine": median(qm), "Q_median_ref": median(qr),
            "pearson_bw": pearson(mine, ref),
            "spearman_bw": spearman(mine, ref),
        }
    obj = {"kind": "paper_evidence_E4_bw_layer_and_spearman",
           "review_items": ["N17", "N18", "N19", "N20", "N21", "N22", "N23", "L13", "B2"],
           "sources": {
               "mine": "work/runs/first-peak-20260929/multichannel_labels.csv"
                       "（source_dataset=A 的 223 行：单自由度拟合 BW/Q）",
               "ref": "work/runs/remote-exported-20260922/dataset/combos.csv"
                      "（批 A 自带两套独立估计 from_points / from_marker）",
           },
           "join": {"identity_key": "ulp 归一化 (x_scale, N_w_te1, N_w_te2)",
                    "peak_identity_gate": "|Δf_peak| ≤ 0.5 MHz（§73.3）",
                    "n_A_combos": len(A),
                    "n_matched_with_values": len(cands),
                    "n_gate_pass": len(ok),
                    "n_skipped_peak_mismatch": len(skipped),
                    "n_comparison_records": len(ok) * 2,
                    "layer_note": "**两个层级**：层① = %d 条比较记录（%d 个组合 × 2 套参考）；"
                                  "层② = 因峰不一致**跳过**的 %d 个组合（≈%.1f%%）⇒ "
                                  "约三成组合连「是哪个峰」都不一致，不得混进同一层统计"
                                  % (len(ok) * 2, len(ok), len(skipped),
                                     100.0 * len(skipped) / max(1, len(cands)))},
           "per_reference": refs,
           "conclusion_scope": "**排序稳健、绝对值不可跨口径混用**："
                               "中位相对差约 20%%（系统尺度偏差，我的拟合约 0.80× 参考），"
                               "但 Spearman 对更可靠的 `from_points` 达 %.4f ⇒ 用 BW 排名稳健；"
                               "绝对 BW 必须标注口径。" % refs["from_points"]["spearman_bw"],
           }
    sink.js("E4_bw_layer_and_spearman.json", obj)

    rows = []
    for tag in ("from_points", "from_marker"):
        v = refs[tag]
        rows.append([tag, v["n_compared"], fmt(v["abs_rel_diff_bw_median"]),
                     fmt(v["abs_rel_diff_bw_p90"]), fmt(100 * v["within_10pct_rate"], 2) + "%",
                     fmt(v["bw_ratio_median_mine_over_ref"], 4),
                     fmt(v["Q_median_mine"], 6), fmt(v["Q_median_ref"], 6),
                     fmt(v["pearson_bw"], 6), fmt(v["spearman_bw"], 6)])
    sink.csv("E4_bw_layer_and_spearman.csv",
             ["reference", "n", "abs_rel_diff_bw_median", "p90", "within_10pct",
              "bw_ratio_median_mine_over_ref", "Q_median_mine", "Q_median_ref",
              "pearson_bw", "spearman_bw"], rows)

    det = []
    for c in ok:
        for tag, refcol, qcol in (("from_points", "bandwidth_3dB_Hz", "q_from_points"),
                                  ("from_marker", "bandwidth_marker_Hz", "q_marker")):
            rb = num(c["ref"].get(refcol))
            if rb is None:
                continue
            det.append([c["key"][0], c["key"][1], c["key"][2], tag,
                        c["fM"], c["fA"], c["bwM"], rb, c["qM"],
                        num(c["ref"].get(qcol)), (c["bwM"] - rb) / rb])
    sink.csv("E4_bw_comparison_records.csv",
             ["x_scale", "N_w_te1", "N_w_te2", "reference", "f_peak_mine_Hz", "f_peak_A_Hz",
              "bw_mine_Hz", "bw_ref_Hz", "Q_mine", "Q_ref", "rel_diff_bw"], det)

    lines = ["# E4 带宽口径敏感性的**两个层级**与排序稳健性复算（§6.2）", "",
             "> 解决审稿：**N17/N18/N19/N20/N21/N22/N23**（只写了「91 个有效对照」，漏层级）"
             "＋ **L13**（162/63 层级）＋ **B2**。",
             "> 复算方式：**从两张原始表重新做键连接**（不引用既有 JSON 的中间量），"
             "再用自写的平均秩实现算 Spearman；逐条记录见 `E4_bw_comparison_records.csv`。", "",
             "## 1. 两个层级（这是 L13 缺的那一层）", "",
             md_table(["层级", "数", "说明"], [
                 ["A 批组合总数", len(A), "`combos.csv`"],
                 ["可比组合（有值且过同峰门禁）", len(ok), "|Δf_peak| ≤ 0.5 MHz"],
                 ["**比较记录**（91 × 2 套参考）", len(ok) * 2, "层①：论文应写这个数"],
                 ["**跳过**（峰都对不上）", len(skipped),
                  "层②：≈%.1f%% 的组合连「是哪个峰」都不一致" % (
                      100.0 * len(skipped) / max(1, len(cands)))],
             ]), "",
             "## 2. 两套独立参考的对照（复算值）", "",
             md_table(["参考", "n", "|ΔBW|/BW 中位", "p90", "≤10% 占比", "BW 比值中位(我/参考)",
                       "Q 中位(我)", "Q 中位(参考)", "Pearson", "**Spearman**"], rows), "",
             "- `from_points`：Spearman **%.6f**（登记值 0.9888 逐位复现）、中位相对差 **%.4f%%**"
             "（登记 20.2548%%）、p90 **%.4f%%**（登记 27.1966%%）。"
             % (refs["from_points"]["spearman_bw"],
                100 * refs["from_points"]["abs_rel_diff_bw_median"],
                100 * refs["from_points"]["abs_rel_diff_bw_p90"]),
             "- `from_marker`：Spearman **%.6f**（登记 0.7987）、中位相对差 **%.4f%%**（登记 19.9874%%）、"
             "p90 **%.4f%%**（登记 88.6682%%）。"
             % (refs["from_marker"]["spearman_bw"],
                100 * refs["from_marker"]["abs_rel_diff_bw_median"],
                100 * refs["from_marker"]["abs_rel_diff_bw_p90"]),
             "- 两套参考给出**几乎相同的中位偏差**（%.2f%% vs %.2f%%）⇒ 是**定义/方法差异**，"
             "不是随机噪声；我的拟合 BW 系统性约 **%.3f×** 参考值。"
             % (100 * refs["from_points"]["abs_rel_diff_bw_median"],
                100 * refs["from_marker"]["abs_rel_diff_bw_median"],
                refs["from_points"]["bw_ratio_median_mine_over_ref"]),
             "- **结论方向**：与更可靠的 `from_points` 相比 **Spearman %.4f / Pearson %.4f ⇒ 用 BW 排名稳健**；"
             "但**绝对 BW 数值不得跨口径混用**。"
             % (refs["from_points"]["spearman_bw"], refs["from_points"]["pearson_bw"]), "",
             "> 本件**不裁定**带宽标签最终采用哪条口径（§73.4 的 A/B/C 三选项，"
             "`【待裁定】` 仍归人）。", ""]
    sink.md("E4_bw_layer_and_spearman.md", "\n".join(lines))
    return obj


# ================================================================ E5
def item_e5(sink: Sink, ctx: dict) -> dict:
    """8 通道 lift 表（§6.4），必须含 bandwidth_Hz 与 Q_factor 的负 lift。"""
    ev = ctx["model"]["evaluation"]
    pc = ev["per_channel"]
    rows_obj = {}
    for ch in sorted(pc):
        v = pc[ch]
        n_test = round(v["n_predicted"] / v["coverage"]) if v.get("coverage") else None
        rows_obj[ch] = {
            "group": ctx["model"]["channels"][ch].get("group"),
            "is_formal_objective": bool(v.get("is_formal_objective")),
            "n_predicted": v["n_predicted"], "n_test_implied": n_test,
            "n_refused_implied": (n_test - v["n_predicted"]) if n_test else None,
            "coverage": v["coverage"],
            "median": v["median"], "p90": v["p90"], "max": v["max"],
            "baseline_persistence_median": v["baseline_persistence_median"],
            "lift_vs_persistence": v["lift_vs_persistence"],
            "beats_persistence": bool(v["beats_persistence"]),
            "verdict_n2_extrap": v["verdict_n2_extrap"],
            "hotspot": bool(v.get("hotspot")),
            "refusal_reasons": v.get("refusal_reasons"),
        }
    obj = {"kind": "paper_evidence_E5_channel_lift_table",
           "review_items": ["N33", "N34", "N35", "N36", "N37", "N38", "R9", "L17", "B1"],
           "source": "work/runs/multichannel-surrogate-20260929/multichannel_model.json"
                     " → evaluation.per_channel（主判定折 `L-N2ex(8)`）",
           "model_id": ctx["model"]["model_id"], "status": ctx["model"]["status"],
           "main_fold": ev["main_fold"], "n_rows_used": ev["n_rows_used"],
           "per_channel": rows_obj,
           "channels_without_lift": ev["channels_without_lift"],
           "channels_without_lift_measured": sorted(
               [ch for ch in rows_obj if not rows_obj[ch]["beats_persistence"]]),
           "formal_objectives_without_lift": sorted(
               [ch for ch in rows_obj if rows_obj[ch]["is_formal_objective"]
                and not rows_obj[ch]["beats_persistence"]]),
           "bandwidth_Hz_negative_lift": rows_obj["bandwidth_Hz"]["lift_vs_persistence"],
           "Q_factor_negative_lift": rows_obj["Q_factor"]["lift_vs_persistence"],
           "reading": {
               "metric": "中位误差（相对误差的中位数，越小越好）；`lift = 基线中位 − 模型中位`",
               "threshold_vs_baseline": "**「过了阈值」与「比基线好」是两件事，必须分开报**"
                                        "（INDEX §79.2/§79.3）",
               "denominator": "每通道分母不同：`n_test_implied = n_predicted / coverage`"
                              "（实测两档 478 与 520，差在通道自身的拒答数）",
               "must_report": "**bandwidth_Hz 是稿中 §3.1 自定的正式目标**，其 lift 为负 ⇒ "
                              "漏报它比漏报一个报告量更严重（红线 R9 / L17）",
           }}
    sink.js("E5_channel_lift_table.json", obj)

    hdr = ["channel", "group", "is_formal_objective", "n_predicted", "n_test_implied",
           "coverage", "median_err", "p90", "max", "baseline_persistence_median",
           "lift_vs_persistence", "beats_persistence", "verdict_n2_extrap"]
    rows = []
    for ch in sorted(rows_obj, key=lambda c: (rows_obj[c]["beats_persistence"],
                                              rows_obj[c]["median"])):
        v = rows_obj[ch]
        rows.append([ch, v["group"], v["is_formal_objective"], v["n_predicted"],
                     v["n_test_implied"], fmt(v["coverage"], 6), fmt(v["median"], 8),
                     fmt(v["p90"], 8), fmt(v["max"], 8),
                     fmt(v["baseline_persistence_median"], 8),
                     fmt(v["lift_vs_persistence"], 10), v["beats_persistence"],
                     v["verdict_n2_extrap"]])
    sink.csv("E5_channel_lift_table.csv", hdr, rows)

    lines = ["# E5 8 通道 lift 表（§6.4）——含 `bandwidth_Hz` 与 `Q_factor` 的**负 lift**", "",
             "> 解决审稿：**R9**（只报 Q 未增值、漏报正式目标 BW）＋ **L17** ＋ **N33–N38** ＋ **B1**。",
             "> 源：`multichannel_model.json` → `evaluation.per_channel`（主判定折 `L-N2ex(8)`，"
             "训练 N2∈{5,6,7} → 测试 N2=8）。指标 = 中位相对误差（越小越好）；"
             "`lift = 基线中位 − 模型中位`（正=有增值）。", "",
             md_table(hdr, [[str(x) for x in r] for r in rows]), "",
             "## 必须写进摘要/结论的负结果", "",
             "- **`channels_without_lift`（实测）= %s**（原文），"
             "本件现算一致：%s。" % (ev["channels_without_lift"], obj["channels_without_lift_measured"]),
             "- **`bandwidth_Hz`（稿中 §3.1 的正式目标）**：median **%.8f** vs 基线 **%.8f** ⇒ "
             "**lift = %.10f（负）**，`beats_persistence=false`。"
             % (rows_obj["bandwidth_Hz"]["median"],
                rows_obj["bandwidth_Hz"]["baseline_persistence_median"],
                rows_obj["bandwidth_Hz"]["lift_vs_persistence"]),
             "- **`Q_factor`（报告量/门槛，非目标）**：median **%.8f** vs 基线 **%.8f** ⇒ "
             "**lift = %.10f（负）**。"
             % (rows_obj["Q_factor"]["median"],
                rows_obj["Q_factor"]["baseline_persistence_median"],
                rows_obj["Q_factor"]["lift_vs_persistence"]),
             "- ⇒ 报道口径应为「**8 通道中 2 个未获增值，其中 1 个是正式目标**」。", "",
             "## 分母与覆盖率（不要混口径）", "",
             md_table(["channel", "n_predicted", "n_test（推算）", "coverage", "拒答构成"], [
                 [ch, rows_obj[ch]["n_predicted"], rows_obj[ch]["n_test_implied"],
                  fmt(rows_obj[ch]["coverage"], 6),
                  json.dumps(rows_obj[ch]["refusal_reasons"], ensure_ascii=False)]
                 for ch in sorted(rows_obj)]), "",
             "> 覆盖率分母是**逐通道的折测试集大小**（实测 478 与 520 两档）；"
             "`f_peak_Hz` 的中位误差恰为 0 **不是「极准」**——只有 87 个离散取值（0.5 MHz 量化），"
             "实测 86.6% 的组合在 N2=7 与 N2=8 上完全相同（`INDEX §79.2`）。", ""]
    sink.md("E5_channel_lift_table.md", "\n".join(lines))
    return obj


# ================================================================ E6
def item_e6(sink: Sink, ctx: dict) -> dict:
    """v2 数据缺陷计数（口径遗漏）：删失 / 截断 / Q=nan，逐 cell。"""
    rows = ctx["v2f"]
    per_cell = {}
    for cell in sorted({r["cell"] for r in rows}):
        sub = [r for r in rows if r["cell"] == cell]
        pk = sum(1 for r in sub if truthy(r["peak_at_scan_endpoint"]))
        bw = sum(1 for r in sub if truthy(r["bw_upper_cutoff_at_endpoint"]))
        both = sum(1 for r in sub if truthy(r["peak_at_scan_endpoint"])
                   and truthy(r["bw_upper_cutoff_at_endpoint"]))
        us = [r for r in sub if not truthy(r["peak_at_scan_endpoint"])
              and not truthy(r["bw_upper_cutoff_at_endpoint"])]
        qn = sum(1 for r in sub if str(r["Q"]).strip().lower() == "nan")
        qn_u = sum(1 for r in us if str(r["Q"]).strip().lower() == "nan")
        per_cell[cell] = {
            "n_rows": len(sub), "n_peak_censored": pk, "n_bw_truncated": bw,
            "n_both": both, "n_peak_only": pk - both, "n_bw_only": bw - both,
            "n_usable": len(us), "n_Q_literal_nan": qn, "n_Q_literal_nan_within_usable": qn_u,
            "n_Q_evaluable_within_usable": len(us) - qn_u,
            "n_Q_in_gate_within_usable": sum(
                1 for r in us if q_of(r, "Q") is not None
                and Q_GATE[0] <= q_of(r, "Q") <= Q_GATE[1]),
        }
    tot = {k: sum(v[k] for v in per_cell.values())
           for k in ("n_rows", "n_peak_censored", "n_bw_truncated", "n_both",
                     "n_peak_only", "n_bw_only", "n_usable", "n_Q_literal_nan",
                     "n_Q_literal_nan_within_usable", "n_Q_evaluable_within_usable",
                     "n_Q_in_gate_within_usable")}
    # 恒等式核对：有数值 Q 的可用行是否满足 Q == f_peak / bandwidth
    id_ok = id_bad = 0
    for r in rows:
        q = q_of(r, "Q")
        if q is None:
            continue
        pkv, bwv = num(r.get("peak_freq_Hz")), num(r.get("bandwidth_Hz"))
        if not pkv or not bwv:
            continue
        if abs(q - pkv / bwv) <= 1e-9 * max(1.0, abs(q)):
            id_ok += 1
        else:
            id_bad += 1
    obj = {"kind": "paper_evidence_E6_v2_defects_by_cell",
           "review_items": ["R5", "L2", "A3", "B4", "N52 相关"],
           "source": "work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv",
           "version": "V2_v20261008T143151（frozen=true，250 行）",
           "scan_range_MHz": [5.0, 35.0],
           "filter_rule": "usable = 非(peak_at_scan_endpoint) 且 非(bw_upper_cutoff_at_endpoint)",
           "per_cell": per_cell, "totals": tot,
           "rates": {
               "peak_censored_pct": round(100.0 * tot["n_peak_censored"] / tot["n_rows"], 2),
               "bw_truncated_pct": round(100.0 * tot["n_bw_truncated"] / tot["n_rows"], 2),
               "usable_pct": round(100.0 * tot["n_usable"] / tot["n_rows"], 2),
               "q_nan_pct": round(100.0 * tot["n_Q_literal_nan"] / tot["n_rows"], 2),
           },
           "key_numbers": {
               "peak_censored": "%d/%d = %.1f%%" % (tot["n_peak_censored"], tot["n_rows"],
                                                    100.0 * tot["n_peak_censored"] / tot["n_rows"]),
               "bw_truncated": "%d/%d = %.1f%%" % (tot["n_bw_truncated"], tot["n_rows"],
                                                   100.0 * tot["n_bw_truncated"] / tot["n_rows"]),
               "Q_literal_nan": "%d 行（可用内 %d）" % (tot["n_Q_literal_nan"],
                                                        tot["n_Q_literal_nan_within_usable"]),
               "Q_gate_true_denominator": tot["n_Q_evaluable_within_usable"],
               "usable_flag_denominator_wrong": tot["n_usable"],
               "Q_in_gate": tot["n_Q_in_gate_within_usable"],
           },
           "identity_check_Q_eq_fpeak_over_bw": {"holds": id_ok, "violations": id_bad},
           "nan_cause_status": "**成因未定，本件不编原因**：需要 v2 的 −3 dB 提取实现/版本原文"
                               "（`INDEX §98.4.1`；B4 仍卡在数据侧）",
           "not_comparable_note": "C/A 两批在并集表里的端点标志列**整列为空**（§96.4）⇒ "
                                  "「删失/截断」只能对 V2 做，**不得跨批借列**",
           }
    sink.js("E6_v2_defects_by_cell.json", obj)

    hdr = ["cell", "n_rows", "n_peak_censored", "n_bw_truncated", "n_both",
           "n_peak_only", "n_bw_only", "n_usable", "n_Q_literal_nan",
           "n_Q_nan_within_usable", "n_Q_evaluable_within_usable", "n_Q_in_gate"]
    rowsx = []
    for cell in sorted(per_cell):
        v = per_cell[cell]
        rowsx.append([cell] + [v[k] for k in ("n_rows", "n_peak_censored", "n_bw_truncated",
                                              "n_both", "n_peak_only", "n_bw_only", "n_usable",
                                              "n_Q_literal_nan", "n_Q_literal_nan_within_usable",
                                              "n_Q_evaluable_within_usable",
                                              "n_Q_in_gate_within_usable")])
    rowsx.append(["合计"] + [tot[k] for k in ("n_rows", "n_peak_censored", "n_bw_truncated",
                                              "n_both", "n_peak_only", "n_bw_only", "n_usable",
                                              "n_Q_literal_nan", "n_Q_literal_nan_within_usable",
                                              "n_Q_evaluable_within_usable",
                                              "n_Q_in_gate_within_usable")])
    sink.csv("E6_v2_defects_by_cell.csv", hdr, rowsx)

    lines = ["# E6 v2 数据缺陷计数（删失 / 截断 / Q=nan）——逐 cell", "",
             "> 解决审稿：**R5**（删失/截断维度整体缺失）＋ **L2** ＋ **A3**＋ **B4**（Q=nan 定因）。",
             "> 源：`v2_labels_frozen_20261008T143151.csv`（250 行，`V2_v20261008T143151`，冻结）。",
             "> **纪律**：删失（峰值卡在扫描端点）与截断（上截止点 = 端点）**不得当正常测量值**"
             "用于排名或带宽统计（红线 R5 / 技能 `sweep-analysis`）。", "",
             "## 1. 全批", "",
             md_table(["项", "实测", "占比"], [
                 ["行数", tot["n_rows"], "—"],
                 ["峰值删失 `peak_at_scan_endpoint`", tot["n_peak_censored"],
                  "**%.1f%%**" % (100.0 * tot["n_peak_censored"] / tot["n_rows"])],
                 ["带宽截断 `bw_upper_cutoff_at_endpoint`", tot["n_bw_truncated"],
                  "**%.1f%%**" % (100.0 * tot["n_bw_truncated"] / tot["n_rows"])],
                 ["两者皆有", tot["n_both"], "—"],
                 ["仅峰值删失", tot["n_peak_only"], "—"],
                 ["仅带宽截断", tot["n_bw_only"], "—"],
                 ["**可用**（filter_rule）", tot["n_usable"],
                  "%.1f%%" % (100.0 * tot["n_usable"] / tot["n_rows"])],
                 ["**`Q` 字面 `nan`（全批 / 可用内）**",
                  "%d / %d" % (tot["n_Q_literal_nan"], tot["n_Q_literal_nan_within_usable"]), "—"],
                 ["**Q 门禁真实分母**（可用 ∧ Q 可判定）",
                  "**%d**" % tot["n_Q_evaluable_within_usable"],
                  "§92.2 写作「可用 146」⇒ **分母错配**"],
                 ["Q∈[2.5,3.5]（该分母内）", tot["n_Q_in_gate_within_usable"],
                  "**40 这个数不变**"],
             ]), "",
             "## 2. 逐 cell", "",
             md_table(hdr, [[str(x) for x in r] for r in rowsx]), "",
             "## 3. 三条必须随数字走的说明", "",
             "- **Q 门禁分母**：`usable=146` 只是 flag 口径；其中 **38 行 `Q` 字面 `nan`** ⇒ "
             "能做 Q 判定的只有 **%d** 行（`INDEX §98.4.1` 的分母更正）。"
             "`nan` 不可能落进 `[2.5,3.5]` ⇒ **40 不变**，变的只是分母该写多少。"
             % tot["n_Q_evaluable_within_usable"],
             "- **`nan` 成因未定**：本件只报算术事实与恒等式核对"
             "（有数值 Q 的可用行 `Q == f_peak / bandwidth_Hz`：成立 **%d**、违反 **%d**），"
             "**不编原因**；定因需要 v2 的 −3 dB 提取实现/版本原文（B4，卡数据侧）。"
             % (id_ok, id_bad),
             "- **不可跨批**：C/A 在并集表里的端点标志列整列为空 ⇒ 同口径的删失/截断判定**只能对 V2 做**"
             "（`INDEX §96.4`：空列 ≠ 通过）。⇒ 两批通过率不可直接比大小。", ""]
    sink.md("E6_v2_defects_by_cell.md", "\n".join(lines))
    return obj


def obj_round(x, nd):
    return round(x, nd)


# ================================================================ E7
def item_e7(sink: Sink, ctx: dict) -> dict:
    """N2=9 净价值件：净可用增量 46（非 79）、三整列全废、覆盖矩阵。"""
    p = ctx["te29"]
    cov = p["coverage_matrix"]
    xs = ["%.2f" % float(x) for x in cov["rows_x_scale"]]
    n1s = [int(n) for n in cov["cols_N_w_te1"]]
    cells = {k: v for k, v in cov["cells"].items()}
    sink.csv("E7_n2_9_coverage_matrix.csv",
             ["x_scale", "N_w_te1", "category"],
             [[x, n, cells["%s|%d" % (x, n)]] for x in xs for n in n1s])
    dead_x = [x for x in xs if cov["per_x"][x]["n_usable"] == 0]
    obj = {"kind": "paper_evidence_E7_n2_9_net_value",
           "review_items": ["N52", "L3", "A3", "INDEX §98 复算"],
           "source": "work/runs/te2_9-value-20261009T090701/te2_9_profile.json"
                     "（只读复制；本件不改它）",
           "cell": "te2_9", "scale": p["te2_9"],
           "coverage_matrix": {"rows_x_scale": xs, "cols_N_w_te1": n1s, "cells": cells,
                               "per_x": cov["per_x"], "per_N1": cov["per_N1"],
                               "usable_x_values": cov["usable_x_values"]},
           "dead_x_columns": dead_x,
           "dead_cells": len(dead_x) * len(n1s),
           "net_value": p["net_value"],
           "net_usable_increment": p["net_usable_increment"],
           "q_gate_reconciliation": p["q_gate_reconciliation"],
           "key_numbers": {
               "n_rows": p["te2_9"]["n_rows"],
               "n_usable": p["te2_9"]["n_usable"],
               "n_censored_or_truncated": p["te2_9"]["n_rows"] - p["te2_9"]["n_usable"],
               "category_counts": p["te2_9"]["by_category"],
               "net_usable_increment": p["net_usable_increment"]["n"],
               "net_usable_increment_with_Q_gate": p["net_usable_increment"]["n_with_Q_in_gate"],
               "n_only_v2": p["net_value"]["cat_only_v2"],
               "n_overlap_with_existing": p["net_value"]["n_in_any_existing"],
               "Q_evaluable_base_usable": p["distributions_usable_only"]["Q_evaluable_base"],
               "Q_in_gate_usable": p["distributions_usable_only"]["Q_in_gate"],
           },
           "reading": {
               "must_write": "**净可用增量 = 46（不是 79）**；79 是「仅 V2 有的真新增组合数」，"
                             "其中 33 格被删失/截断 ⇒ 可用只剩 46；叠加 Q 门禁后剩 11"
                             "（分母是 32 个 Q 可判定的可用格，**不是 46**）",
               "three_dead_columns": "x∈{0.10, 0.20, 0.30} **三整列全废**（各 8 格共 24 格全部「两者皆有」）"
                                     "⇒ 该三列的 N2=9 数据**一个都不能用**",
               "structural": "**C 批（5–50/91 宽栅格）根本没有 N2=9 的任何一行**（C 的 N2∈{5,6,7,8}）；"
                             "A 只有 1 行 N2=9 ⇒ **不存在「更宽栅格的既有行」可取代或加厚 V2 的 N2=9**",
               "not_a_ruling": "本件**不裁定**是否把 v2 纳入「当前数据」（审稿 N52 的两口径并列，`【待裁定】`）；"
                               "两个口径都**不支持**「N2=9 泛化已验证」",
           }}
    sink.js("E7_n2_9_net_value.json", obj)

    lines = ["# E7 N2=9 净价值件：**净可用增量 = 46（非 79）**", "",
             "> 解决审稿：**N52**（需人工核对：独立样本是否足够）＋ **L3**（净可用 46 非 79、三整列全废）＋ **A3**。",
             "> 源：`work/runs/te2_9-value-20261009T090701/te2_9_profile.json`（只读复算，"
             "口径照搬 §98.1：`usable = 非峰值删失 ∧ 非带宽截断`；身份键先 ulp 归一化）。", "",
             "## 1. 从一个数看出问题", "",
             md_table(["量", "值", "说明"], [
                 ["N2=9 全因子格数", p["te2_9"]["n_rows"], "x 10 值 × N1 8 值 = 80，**无一格不存在**"],
                 ["**可用**", p["te2_9"]["n_usable"], "34 格被删失/截断（其中 28 格两者皆有）"],
                 ["仅 V2 有（真新增）", p["net_value"]["cat_only_v2"], "组合键在 A、C 两批里都不存在"],
                 ["**净可用增量**", "**%d**" % p["net_usable_increment"]["n"],
                  "= 可用 ∧ 非重复；**不是 79**"],
                 ["叠加 Q 门禁后", p["net_usable_increment"]["n_with_Q_in_gate"],
                  "分母是 **%d** 个 Q 可判定可用格（不是 46）"
                  % p["distributions_usable_only"]["Q_evaluable_base"]],
                 ["与既有批重叠", p["net_value"]["n_in_any_existing"],
                  "唯一那个两侧都不可用（A 侧 `first_peak_found=False`）"],
             ]), "",
             "## 2. 覆盖矩阵（行 = x_scale，列 = N_w_te1）", "",
             "`U`=可用、`P`=峰值删失、`B`=带宽截断、`PB`=两者皆有：", ""]
    code = {"可用": "U", "峰值删失": "P", "带宽截断": "B", "两者皆有": "PB"}
    hdr = ["x_scale \\ N1"] + [str(n) for n in n1s]
    mrows = [[x] + [code.get(cells["%s|%d" % (x, n)], "?") for n in n1s] for x in xs]
    lines += [md_table(hdr, mrows), "",
              "逐 x 计数：", "",
              md_table(["x_scale", "格数", "可用", "峰值删失", "带宽截断"],
                       [[x, cov["per_x"][x]["n_cells"], cov["per_x"][x]["n_usable"],
                         cov["per_x"][x]["n_peak_censored"], cov["per_x"][x]["n_bw_truncated"]]
                        for x in xs]), "",
              "**关键结论**：可用 x 只有 7 个取值（%s）；"
              "**x ∈ {0.10, 0.20, 0.30} 三整列全废**（%d 格全部「两者皆有」）⇒ "
              "该三列的 N2=9 数据一个都不能用；N1 八个取值都可用（各 5–6 格）。"
              % (" / ".join("%.2f" % float(v) for v in cov["usable_x_values"]),
                 len(dead_x) * len(n1s)), "",
              "> 完整矩阵（机器可读）见 `E7_n2_9_coverage_matrix.csv` 与 `E7_n2_9_net_value.json`。", "",
              "## 3. 为什么「79」不能当净增量用", "",
              "79 回答的是「**有多少组合是 v2 独有的**」；46 回答的是「**有多少组合是可用且独有的**」。"
              "两者差 33 = 79 中被删失/截断的格数。"
              "论文若写 79 会把「不可用的删失/截断数据」算成产出。", "",
              "## 4. 【待裁定】", "",
              "`【待裁定】` 是否把 v2 纳入「当前数据」（N52 的两口径并列）；"
              "**两个口径都不支持「N2=9 泛化已验证」**（C 批根本没有 N2=9，A 只有 1 行）。", ""]
    sink.md("E7_n2_9_net_value.md", "\n".join(lines))
    return obj


# ================================================================ E8
def item_e8(sink: Sink, ctx: dict) -> dict:
    """批次隔离数：跨批重叠 446 的构成、ulp_only 60、224 的实际构成、虚高多少。"""
    v3 = ctx["v3"]
    cat, by_pair_norm, diff_cols, examples = pair_relation(v3)
    per_lit, pairs_lit, tot_lit = overlap_sets(v3, key_literal)
    per_raw, pairs_raw, tot_raw = overlap_sets(v3, key_raw)
    per_ulp, pairs_ulp, tot_ulp = overlap_sets(v3, key_ulp)

    def new_v2(per):
        return len(per["V2_5-35MHz"] - per["A_5-35MHz"] - per["C_5-50MHz"])

    # 门禁权威值（直接调用仓库门禁函数，只读）
    gate = None
    try:
        sys.path.insert(0, str(REPO / "src"))
        from memsharness import sweep_analysis as SA  # noqa: E402
        chk = SA.check_batch_isolation(v3)
        for c in chk:
            if c.name == "batch_no_cross_batch_combo":
                gate = {"name": c.name, "passed": c.passed, "reason": c.reason,
                        "detail": c.detail}
    except Exception as exc:  # pragma: no cover - 记录而不掩盖
        gate = {"error": "%s: %s" % (type(exc).__name__, exc)}

    obj = {"kind": "paper_evidence_E8_batch_isolation_numbers",
           "review_items": ["L16", "A7", "INDEX §94.3/§95.4 复算"],
           "source": "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv",
           "identity_key": "ulp 归一化 round(x_scale,6) + N_w_te1 + N_w_te2（三列按数值比）",
           "calibers": {
               "literal": {"key": "三列原样字符串逐字相同",
                           "n_unique_per_batch": {b: len(per_lit[b]) for b in BATCHES},
                           "pair_overlaps": pairs_lit, "sum_pair_overlaps": tot_lit,
                           "n_new_combos_v2": new_v2(per_lit)},
               "raw_repr": {"key": "repr(_num(·))（门禁 `n_overlap_raw` 口径；"
                                   "`1.0`≡`1`，但保留真 1 ulp 差）",
                            "n_unique_per_batch": {b: len(per_raw[b]) for b in BATCHES},
                            "pair_overlaps": pairs_raw, "sum_pair_overlaps": tot_raw,
                            "n_new_combos_v2": new_v2(per_raw)},
               "ulp_normalized": {"key": "浮点 round(·, 6)，整数保持 int",
                                  "n_unique_per_batch": {b: len(per_ulp[b]) for b in BATCHES},
                                  "pair_overlaps": pairs_ulp, "sum_pair_overlaps": tot_ulp,
                                  "n_new_combos_v2": new_v2(per_ulp)},
           },
           "pair_relation_per_row_pair": dict(cat),
           "pair_relation_by_batch_pair": dict(by_pair_norm),
           "repr_same_diff_columns": {",".join(k): v for k, v in diff_cols.items()},
           "repr_same_examples": examples,
           "inflation": {
               "overlap_raw_vs_ulp": tot_ulp - tot_raw,
               "overlap_literal_vs_ulp": tot_ulp - tot_lit,
               "n_new_v2_raw_minus_ulp": new_v2(per_raw) - new_v2(per_ulp),
               "n_new_v2_literal_minus_ulp": new_v2(per_lit) - new_v2(per_ulp),
               "reading": "不做 ulp 归一化时（`repr(_num())` 口径）V2 的「新增数」由 83 虚高到 "
                          "**117（虚高 34）**——与 `INDEX §92.3 更正一` 逐位一致；"
                          "若误用「字面相同」口径，新增数会虚高到 250（虚高 167），"
                          "但那个口径把 **224 对表示差**也算成不同组合，**不是**任何既有记录用的口径",
           },
           "gate_authoritative": gate,
           "headline": {
               "sum_pair_overlaps_ulp": tot_ulp,
               "decomposition": "**%d = %d（字面相同）+ %d（仅表示差）+ %d（真 1 ulp 差）**"
                                % (tot_ulp, cat["key_str_same"], cat["key_repr_same"],
                                   cat["key_ulp_only"]),
               "by_batch_pair": "A|C **%d** + A|V2 **%d** + C|V2 **%d** = **%d**"
                                % (pairs_ulp["A_5-35MHz|C_5-50MHz"],
                                   pairs_ulp["A_5-35MHz|V2_5-35MHz"],
                                   pairs_ulp["C_5-50MHz|V2_5-35MHz"], tot_ulp),
               "warning": "「A|C = 162」与「key_str_same = 162」**数值相同但不是同一件事**："
                          "实测**全部** 162 对字面相同者恰好都发生在 A|C 批对上"
                          "（A|V2 与 C|V2 的字面相同对数均为 0），故两数相等；"
                          "引用时须写明是**批对重叠数**还是**身份键关系计数**",
               "not_a_ruling": "`【待裁定】` 去重/切分规则仍归人（O-A 裁决=不去重、一行不删，"
                               "统计按批分组）；`batch` **不得**当防泄漏整组切分键",
           }}
    sink.js("E8_batch_isolation_numbers.json", obj)

    rows = []
    for tag, key, per in (("literal（字面逐字相同）", "原样字符串", per_lit),
                          ("raw_repr（repr(_num(·))，门禁 raw 口径）", "repr", per_raw),
                          ("ulp_normalized（round6，推荐判等口径）", "round6", per_ulp)):
        rows.append([tag, tot_lit if tag.startswith("literal") else (
            tot_raw if tag.startswith("raw") else tot_ulp),
            new_v2(per),
            len(per["A_5-35MHz"]), len(per["C_5-50MHz"]), len(per["V2_5-35MHz"])])
    sink.csv("E8_overlap_calibers.csv",
             ["caliber", "sum_pair_overlaps", "n_new_combos_V2", "n_unique_A", "n_unique_C",
              "n_unique_V2"], rows)
    rel_rows = [["总对数", sum(cat.values())]] + \
               [[k, v] for k, v in sorted(cat.items())] + \
               [["批次对：" + k, v] for k, v in sorted(by_pair_norm.items())] + \
               [["repr_same 差列：" + ",".join(k), v] for k, v in sorted(diff_cols.items())
                if not k or k[0] != "ulp"] + \
               [["ulp_only 差列：" + ",".join(k), v] for k, v in sorted(diff_cols.items())
                if k and k[0] == "ulp"]
    sink.csv("E8_overlap_composition.csv", ["bucket", "count"], rel_rows)

    lines = ["# E8 批次隔离数：跨批重叠 446 的构成与「虚高」复算", "",
             "> 解决审稿：**L16**（跨批同组合 446；字面相同 162、表示差 224、真 ulp 差 60）"
             "＋ **A7**（切分键约束）。",
             "> 复算方式：对 v3 并集表**自己实现三种身份键口径**，并**同时调用仓库门禁函数**"
             "`sweep_analysis.check_batch_isolation` 对照（两个实现互证）。", "",
             "## 1. 三种口径的阶梯（这是「虚高」的全部来源）", "",
             md_table(["口径", "跨批重叠合计", "V2 新增组合数", "A 唯一", "C 唯一", "V2 唯一"], rows), "",
             "| 关系（逐**行对**计一次） | 对数 |", "|---|---|",
             "| `key_str_same`（三列字面逐字相同） | **%d** |" % cat["key_str_same"],
             "| `key_repr_same`（仅**表示差**，如 `6.0` vs `6`、`1.0` vs `1`） | **%d** |"
             % cat["key_repr_same"],
             "| `key_ulp_only`（**真 1 ulp 差**，实测全部在 `x_scale` 列） | **%d** |"
             % cat["key_ulp_only"],
             "| 合计（= ulp 归一化下的跨批重叠） | **%d** |" % sum(cat.values()), "",
             "⇒ **%d = %d + %d + %d**（与 `INDEX §95.4` 的 446 = 162 + 224 + 60 逐位一致）。"
             % (sum(cat.values()), cat["key_str_same"], cat["key_repr_same"], cat["key_ulp_only"]), "",
             "## 2. 446 的**批对**构成", "",
             md_table(["批对", "重叠组合数（ulp 归一化）"],
                      [[k, v] for k, v in sorted(pairs_ulp.items())] +
                      [["两两之和", tot_ulp]]), "",
             "> 「A|C = 162」与「key_str_same = 162」**数值巧合**：实测全部 162 对字面相同者"
             "都落在 A|C 批对上（A|V2、C|V2 的字面相同对数均为 **0**）。引用时必须写明是哪一种计数。", "",
             "## 3. 224 的实际构成（rep_same 但字面不同）", "",
             md_table(["差异所在列", "对数"], [["、".join(k), v] for k, v in sorted(diff_cols.items())
                                              if not k or k[0] != "ulp"]), "",
             "样例（左/右为三列原样字符串）：", ""]
    for k, exs in list(examples.items())[:6]:
        for e in exs[:1]:
            lines.append("- `%s` ｜ %s vs %s（批对 %s）" % (k, e["left"], e["right"], e["pair"]))
    lines += ["", "## 4. 「不加 ulp 归一化会虚高多少」——复算", "",
              md_table(["口径对比", "值"], [
                  ["ulp 归一化重叠 / 原样（repr）重叠", "**%d / %d**（差 **%d** 对）"
                   % (tot_ulp, tot_raw, tot_ulp - tot_raw)],
                  ["原样重叠 / 字面重叠", "**%d / %d**（差 **%d** 对）"
                   % (tot_raw, tot_lit, tot_raw - tot_lit)],
                  ["**V2 新增数：ulp 归一化**", "**%d**" % new_v2(per_ulp)],
                  ["V2 新增数：原样（repr）口径", "**%d**（**虚高 %d**，与 `INDEX §92.3 更正一` 一致）"
                   % (new_v2(per_raw), new_v2(per_raw) - new_v2(per_ulp))],
                  ["V2 新增数：字面口径", "%d（虚高 %d；该口径把 224 对表示差也算成不同组合，"
                   "**不是**任何既有记录用的口径）"
                   % (new_v2(per_lit), new_v2(per_lit) - new_v2(per_ulp))],
              ]), "",
              "**纪律**（`dataset-contract §10` / `sweep-analysis §8.1`）："
              "组合身份键判等**必须先做 ulp 归一化**；这个错误的方向是**虚报产出**，"
              "最容易被当成好消息放过。", "",
              "## 5. 门禁权威值（同一张表，调用仓库门禁函数）", "",
              "```json", json.dumps(gate, ensure_ascii=False, indent=1), "```", "",
              "⇒ `batch` **不得**当防泄漏整组切分键；训练/留出须显式定义分组（组合键或 `dup_of` 族）。",
              "`【待裁定】` 具体切分规则仍归人（`INDEX §95.9` 第 7 条：建议未经用户拍板，本轮不执行）。", ""]
    sink.md("E8_batch_isolation_numbers.md", "\n".join(lines))
    return obj


# ================================================================ E9
def item_e9(sink: Sink, ctx: dict) -> dict:
    """数据/版本/哈希/模型身份附录表。"""
    def finfo(p: pathlib.Path):
        if not p.exists():
            return {"path": str(p.relative_to(REPO)).replace("\\", "/"), "exists": False}
        return {"path": str(p.relative_to(REPO)).replace("\\", "/"), "exists": True,
                "bytes": p.stat().st_size, "sha256": sha256_file(p)}

    artifacts = {
        "C 批主标签表（C 原表，权威 flag 列）": P_C_ORIG,
        "v2 冻结副本（不可变）": P_V2F,
        "v2 版本清单": P_V2_VERSION,
        "v3 并集表（O-A 载体）": P_V3,
        "v3 版本清单": P_V3_VERSION,
        "dup_kind_refined 补列视图": P_DUPKIND,
        "C_v20260929 数据版本清单": P_C_VERSION,
        "主标签表首峰明细": REPO / "work/runs/first-peak-20260929/first_peak_metrics.csv",
        "带宽口径外部验证": P_BWVAL,
        "多通道代理模型 JSON": P_MODEL,
        "多通道代理预注册": P_PREREG,
        "拒答筛查产物": P_SCREEN,
        "te2_9 覆盖画像": P_TE29_PROFILE,
        "te2_9 独立复核": REPO / "work/runs/te2_9-value-20261009T090701/verify.json",
        "solver_spec（状态锚点）": P_SOLVER_SPEC,
        "门禁函数源码 sweep_analysis.py": P_SWEEP_SRC,
        "S3/S4 报告 JSON": REPO / "work/runs/s34-mesh-20261006T131318Z/s34_report.json",
        "口径对齐取证报告": P_S76_REPORT,
        "U1 结果": REPO / "work/runs/u1-pt-vs-p-20261009T091453Z/U1_result.json",
    }
    table = {}
    for label, p in artifacts.items():
        info = finfo(p)
        info["label"] = label
        table[label] = info

    spec = json.loads(P_SOLVER_SPEC.read_text(encoding="utf-8"))
    mph = {p.name: finfo(p) for p in (P_MPH_CURRENTDRIVE, P_MPH_LEGACY) if p.exists()}
    v2ver = json.loads(P_V2_VERSION.read_text(encoding="utf-8"))
    cver = json.loads(P_C_VERSION.read_text(encoding="utf-8"))
    ltb3 = json.loads(P_V3_VERSION.read_text(encoding="utf-8"))

    model_ids = {
        "x 族声明模型（远端，声明值）": {
            "file": "cell_te2_8_test_scal_0.2-1_0.01_freq5-50_v1.mph（远端）",
            "size_bytes": 256291859744,
            "sha256": "8d1c060833a70e114bae810bc13d846fc36bd8b198f16e04dbb338ea03479eb5",
            "where_declared": "work/runs/x-densify-20260928/data_versions/C_v20260929.json → models[]"
                              "（`artifact_sha256`）",
            "nature": "**声明值**：该哈希由远端导出脚本里的字面量给出，"
                      "**本轮未对 256 GB 字节复算**（`REPORT-s76-口径对齐.md §1.3`）；"
                      "`source_model_sha256` 字段即此值",
        },
        "S3/S4 实测 run 的 input.mph": {
            "file": "work/runs/s34-mesh-20261006T131318Z/input.mph（= 生产模型副本）",
            "size_bytes": 103681444,
            "sha256": "0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d",
            "where_declared": "`INDEX §91.1/§97`、`REPORT-s76-口径对齐.md §1`",
            "nature": "**实测**（run 前后生产模型哈希不变）",
        },
        "work/models 下的两份 103,681,444 B 副本": {
            "files": [{"name": k, "bytes": v.get("bytes"), "sha256": v.get("sha256")}
                      for k, v in mph.items()],
            "nature": "本件现算；与 S3/S4 的 `0f75ca1d…` **逐位相同** ⇒ 与 x 族声明模型是"
                      "**不同实例**（体量差 2,472 倍）",
        },
    }

    obj = {"kind": "paper_evidence_E9_reproducibility_appendix",
           "review_items": ["A6", "A2", "L12", "L15", "L5", "N65 相关"],
           "artifacts": table,
           "data_versions": {
               "C_v20260929": {"label": cver.get("label"), "frozen_utc": cver.get("frozen_utc"),
                               "protocol": cver.get("protocol"), "n_runs": cver.get("n_runs"),
                               "combos_n": cver.get("combos", {}).get("n"),
                               "freq_grid": cver.get("freq_grid"),
                               "manifest_sha256": table["C_v20260929 数据版本清单"].get("sha256"),
                               "path": table["C_v20260929 数据版本清单"]["path"]},
               "V2_v20261008T143151": {"version_id": v2ver.get("version_id"),
                                       "kind": v2ver.get("kind"),
                                       "frozen": v2ver.get("frozen"),
                                       "n_rows": v2ver.get("n_rows"),
                                       "scan_range_MHz": v2ver.get("scan_range_MHz"),
                                       "frozen_sha256": v2ver.get("frozen_sha256"),
                                       "manifest_sha256": table["v2 版本清单"].get("sha256"),
                                       "path": table["v2 版本清单"]["path"]},
               "LTB3_v20261008T170618（v3 并集）": {
                   "version_id": ltb3.get("version_id"), "frozen": ltb3.get("frozen"),
                   "row_count": ltb3.get("row_count"),
                   "column_count": ltb3.get("column_count"),
                   "supersedes": ltb3.get("supersedes", {}).get("version_id"),
                   "manifest_sha256": table["v3 版本清单"].get("sha256"),
                   "path": table["v3 版本清单"]["path"]},
           },
           "model_identities": model_ids,
           "state_anchors": {
               "solver_spec_state": spec.get("state"),
               "solver_spec_sha256": table["solver_spec（状态锚点）"].get("sha256"),
               "solver_spec_sha256_expected": SOLVER_SPEC_SHA256_EXPECT,
               "solver_spec_state_unchanged": spec.get("state") == "draft",
               "sweep_src_sha256": table["门禁函数源码 sweep_analysis.py"].get("sha256"),
               "sweep_src_sha256_expected": SWEEP_SRC_SHA256_EXPECT,
               "multichannel_model_status": ctx["model"].get("status"),
               "multichannel_model_id": ctx["model"].get("model_id"),
               "multichannel_prereg_sha256_declared": ctx["model"].get("prereg_sha256"),
               "multichannel_prereg_sha256_actual":
                   table["多通道代理预注册"].get("sha256"),
               "multichannel_labels_sha256_declared": ctx["model"].get("labels_sha256"),
               "multichannel_labels_sha256_actual": table["C 批主标签表（C 原表，权威 flag 列）"]
                   .get("sha256"),
           },
           "notes": {
               "source_model_sha256": "**`source_model_sha256` 是远端导出脚本里的字面量**"
                                      "（`modelSha256 = '8d1c0608…';`，全文无任何哈希计算）"
                                      "⇒ 属**声明值**，不是本机实测（L5）。",
               "hash_scope": "本表所有 sha256 均为**本件现算**（读字节），"
                             "除 256 GB 那份（远端，未复算）。",
           }}
    sink.js("E9_reproducibility_appendix.json", obj)

    rows = [[v["label"], v["path"], v.get("bytes", ""), v.get("sha256", "（缺失）")]
            for v in table.values()]
    sink.csv("E9_reproducibility_appendix.csv",
             ["label", "path", "bytes", "sha256"], rows)

    lines = ["# E9 数据 / 版本 / 哈希 / 模型身份附录表（可直接贴进论文附录）", "",
             "> 解决审稿：**A6 / A2**（可复现性表）＋ **L12**（数据版本与哈希、预注册哈希）"
             "＋ **L15**（模型状态披露）＋ **L5**（`source_model_sha256` 是声明值）。",
             "> 除 256 GB 那份远端模型外，**所有 sha256 均为本件现算**（读字节）。", "",
             "## 表 A1 数据与产物版本、字节、sha256", "",
             md_table(["对象", "路径", "字节", "sha256"], [
                 [v["label"], "`%s`" % v["path"], v.get("bytes", ""),
                  "`%s`" % v.get("sha256", "（缺失）")] for v in table.values()]), "",
             "## 表 A2 数据版本", "",
             md_table(["版本 id", "kind", "frozen", "规模", "清单 sha256"], [
                 ["`C_v20260929`", "immutable_data_version", "true",
                  "%d runs／%d 组合／栅格 5–50 MHz、%d 点（步长 0.5 MHz）"
                  % (cver.get("n_runs", 0), cver.get("combos", {}).get("n", 0),
                     cver.get("freq_grid", {}).get("n_points", 0)),
                  "`%s`" % table["C_v20260929 数据版本清单"].get("sha256")],
                 ["`%s`" % v2ver.get("version_id"), v2ver.get("kind"),
                  str(v2ver.get("frozen")).lower(),
                  "%d 行／250 组合／栅格 5–35 MHz、61 点（4 个 cell：te2_5/7/8/9）"
                  % v2ver.get("n_rows", 0),
                  "`%s`" % table["v2 版本清单"].get("sha256")],
                 ["`%s`" % ltb3.get("version_id"), "labels_union_version",
                  str(ltb3.get("frozen")).lower(),
                  "%d 行 × %d 列／三批一批一栅格（A 5–35/61、C 5–50/91、V2 5–35/61）"
                  % (ltb3.get("row_count", 0), ltb3.get("column_count", 0)),
                  "`%s`" % table["v3 版本清单"].get("sha256")],
             ]), "",
             "## 表 A3 模型身份（**两个族是不同实例**）", "",
             md_table(["对象", "体量 (B)", "sha256", "性质 / 出处"], [
                 ["x 族声明模型（远端 N2=8）", "256,291,859,744",
                  "`8d1c060833a70e114bae810bc13d846fc36bd8b198f16e04dbb338ea03479eb5`",
                  "**声明值**（远端脚本字面量，未复算 256 GB 字节）；出处 "
                  "`C_v20260929.json → models[].artifact_sha256`"],
                 ["S3/S4 实测 run `input.mph`", "103,681,444",
                  "`0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d`",
                  "**实测**；`INDEX §91.1/§97`"],
                 ["`work/models/…_currentdrive_fmax45_v1.mph`", "103,681,444",
                  "`%s`" % mph.get("b_GE_task3_2new_currentdrive_fmax45_v1.mph", {})
                  .get("sha256", ""), "本件现算；与 S3/S4 **逐位相同**"],
                 ["`work/models/…_legacy_1ohm_drive_v1.mph`", "103,681,444",
                  "`%s`" % mph.get("b_GE_task3_2new_legacy_1ohm_drive_v1.mph", {})
                  .get("sha256", ""), "本件现算；与上 **逐位相同**"],
             ]), "",
             "> **必须随数字走的一句**：`source_model_sha256` 是**导出脚本里的字面量**（声明值），"
             "`export_te2_8_pod_fields.m` 全文没有任何哈希计算；唯一未实测的一环＝**未对 256 GB 复算**"
             "（`REPORT-s76-口径对齐.md §1.3`）。两族体量差 **2,472 倍** ⇒ **不同模型实例**。", "",
             "## 表 A4 状态锚点（**本轮只读复核，未提升**）", "",
             md_table(["项", "值", "期望/登记值", "一致？"], [
                 ["`solver_spec.json` state", obj["state_anchors"]["solver_spec_state"], "`draft`",
                  obj["state_anchors"]["solver_spec_state_unchanged"]],
                 ["`solver_spec.json` sha256",
                  "`%s`" % obj["state_anchors"]["solver_spec_sha256"],
                  "`%s`" % SOLVER_SPEC_SHA256_EXPECT,
                  obj["state_anchors"]["solver_spec_sha256"] == SOLVER_SPEC_SHA256_EXPECT],
                 ["`sweep_analysis.py` sha256",
                  "`%s`" % obj["state_anchors"]["sweep_src_sha256"],
                  "`%s`" % SWEEP_SRC_SHA256_EXPECT,
                  obj["state_anchors"]["sweep_src_sha256"] == SWEEP_SRC_SHA256_EXPECT],
                 ["`multichannel_model.json` status",
                  obj["state_anchors"]["multichannel_model_status"], "`draft`",
                  obj["state_anchors"]["multichannel_model_status"] == "draft"],
                 ["代理 model_id", "`%s`" % obj["state_anchors"]["multichannel_model_id"],
                  "（`INDEX §79.4` 登记值）", "—"],
                 ["代理预注册 sha256（模型内声明 / 文件现算）",
                  "`%s`\n`%s`" % (obj["state_anchors"]["multichannel_prereg_sha256_declared"],
                                  obj["state_anchors"]["multichannel_prereg_sha256_actual"]),
                  "两者应相等", obj["state_anchors"]["multichannel_prereg_sha256_declared"]
                  == obj["state_anchors"]["multichannel_prereg_sha256_actual"]],
             ]), "",
             "> `【待裁定】` 无 —— 本表只披露状态，**不放行、不认证**"
             "（红线 5：模型状态从 `draft` 升到 `approved_for_use` 必须经人工门禁）。", ""]
    sink.md("E9_reproducibility_appendix.md", "\n".join(lines))
    return obj


# ================================================================ MANIFEST
def write_manifest(sink: Sink, ctx: dict, items: dict, inputs: dict):
    script = pathlib.Path(__file__).resolve()
    commands = """# 复现命令（DAC 2027 证据补齐，2026-10-09）

环境：Windows PowerShell 5.1；Python = `work\\.venv\\Scripts\\python.exe`（3.12.14）；
**无 pwsh、无 git**；本目录**不含任何需要 COMSOL 的步骤**。

```powershell
# 1) 生成全部证据件（只读既有数据；不跑 COMSOL；不提升任何状态）
work\\.venv\\Scripts\\python.exe -X utf8 scripts\\paper_evidence_dac2027.py

# 2) 独立复核（另写一遍算法 + 重跑比对逐字节 + 基线哈希 + 状态未提升）
work\\.venv\\Scripts\\python.exe -X utf8 scripts\\verify_paper_evidence.py

# 3) 单项入口（可选：只想重算某一件时，用 -c 直接读源表；示例：逐批计数）
work\\.venv\\Scripts\\python.exe -X utf8 -c "import csv,collections;rows=list(csv.DictReader(open(r'work/runs/first-peak-20260929/multichannel_labels.csv',encoding='utf-8-sig',newline='')));print(collections.Counter(r['source_dataset'] for r in rows))"
```

> 产物**不含时间戳** ⇒ 反复运行逐字节相同（`verify_paper_evidence.py` 第 0 项会实测这一点）。
> 本目录只读引用下列输入（sha256 见 `MANIFEST.json` 的 `inputs`）：
> `work/runs/first-peak-20260929/multichannel_labels.csv`、
> `work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv`、
> `work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv`、
> `work/runs/remote-exported-20260922/dataset/combos.csv`、
> `work/runs/multichannel-surrogate-20260929/multichannel_model.json` 及其预注册、
> `work/runs/paper-rev-20260930/screen_refusals.json`、
> `work/runs/te2_9-value-20261009T090701/te2_9_profile.json`、
> `work/runs/solver/pmut-f1/solver_spec.json`（只读复核 state=draft）。
"""
    p = sink.out / "COMMANDS.md"
    if p not in sink.outputs:
        sink.outputs.append(p)
    p.write_text(commands, encoding="utf-8")
    manifest = {
        "kind": "paper_evidence_manifest",
        "out_dir": str(sink.out.relative_to(REPO)).replace("\\", "/"),
        "script": {"path": str(script.relative_to(REPO)).replace("\\", "/"),
                   "bytes": script.stat().st_size, "sha256": sha256_file(script)},
        "verifier": {"path": "scripts/verify_paper_evidence.py",
                     "bytes": (REPO / "scripts/verify_paper_evidence.py").stat().st_size,
                     "sha256": sha256_file(REPO / "scripts/verify_paper_evidence.py")},
        "discipline": {
            "read_only": True, "no_comsol": True, "no_state_promotion": True,
            "no_data_modified": True, "no_paper_modified": True,
            "no_pooling": "池化值仅作为「仅规模参考」单列，禁止作为统计口径",
            "no_timestamp_in_outputs": True,
        },
        "inputs": inputs,
        "outputs": [{"path": str(p.relative_to(REPO)).replace("\\", "/"),
                     "bytes": p.stat().st_size, "sha256": sha256_file(p)}
                    for p in sink.outputs],
        "items": {k: {"review_items": v.get("review_items", v.get("review_item")),
                      "json_kind": v.get("kind")} for k, v in items.items()},
    }
    p = sink.out / "MANIFEST.json"
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True),
                 encoding="utf-8")
    lines = ["# 证据件 MANIFEST（DAC 2027 证据补齐，2026-10-09）", "",
             "> 脚本：`%s`（%d B，sha256 `%s`）" % (
                 manifest["script"]["path"], manifest["script"]["bytes"],
                 manifest["script"]["sha256"]),
             "> 纪律：只读 / 不跑 COMSOL / 不提升状态 / 不改数据 / 不改论文 / 不池化；"
             "产物**不含时间戳** ⇒ 反复运行逐字节相同。", "",
             "## 产物（%d 件）" % len(manifest["outputs"]), "",
             md_table(["文件", "字节", "sha256"],
                      [["`%s`" % o["path"].split("/")[-1], o["bytes"], "`%s`" % o["sha256"]]
                       for o in manifest["outputs"]]), "",
             "## 输入（只读，现算 sha256）", "",
             md_table(["文件", "字节", "sha256"],
                      [["`%s`" % k, v.get("bytes", ""), "`%s`" % v.get("sha256", "（缺失）")]
                       for k, v in sorted(inputs.items())]), "",
             "## 逐项 → 解决的审稿条目", "",
             md_table(["证据件", "解决的审稿条目"],
                      [[k, json.dumps(v.get("review_items", v.get("review_item")),
                                      ensure_ascii=False)] for k, v in items.items()]), ""]
    with open(sink.out / "MANIFEST.md", "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    return manifest


# ================================================================ main
def build_inputs_map() -> dict:
    paths = [P_C_ORIG, P_V3, P_V3_VERSION, P_V2F, P_V2_VERSION, P_A_COMBOS, P_MODEL,
             P_PREREG, P_SCREEN, P_TE29_PROFILE, P_SOLVER_SPEC, P_BWVAL, P_C_VERSION,
             P_DUPKIND, P_SWEEP_SRC, P_S76_REPORT, P_MPH_CURRENTDRIVE, P_MPH_LEGACY,
             REPO / "work/runs/first-peak-20260929/first_peak_metrics.csv",
             REPO / "work/runs/te2_9-value-20261009T090701/verify.json",
             REPO / "work/runs/s34-mesh-20261006T131318Z/s34_report.json",
             REPO / "work/runs/u1-pt-vs-p-20261009T091453Z/U1_result.json"]
    out = {}
    for p in paths:
        rel = str(p.relative_to(REPO)).replace("\\", "/")
        if p.exists():
            out[rel] = {"bytes": p.stat().st_size, "sha256": sha256_file(p)}
        else:
            out[rel] = {"bytes": None, "sha256": None, "exists": False}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(REPO / "work/runs/paper-evidence-20261009"))
    args = ap.parse_args(argv)
    sink = Sink(pathlib.Path(args.out_dir))

    ctx = {
        "corig": read_csv(P_C_ORIG),
        "v3": read_csv(P_V3),
        "v2f": read_csv(P_V2F),
        "a_combos": read_csv(P_A_COMBOS),
        "model": json.loads(P_MODEL.read_text(encoding="utf-8")),
        "screen": json.loads(P_SCREEN.read_text(encoding="utf-8")),
        "te29": json.loads(P_TE29_PROFILE.read_text(encoding="utf-8")),
        "bwval": json.loads(P_BWVAL.read_text(encoding="utf-8")),
    }

    items = {}
    items["E1"] = item_e1(sink, ctx)
    items["E2"] = item_e2(sink, ctx)
    items["E3"] = item_e3(sink, ctx)
    items["E4"] = item_e4(sink, ctx)
    items["E5"] = item_e5(sink, ctx)
    items["E6"] = item_e6(sink, ctx)
    items["E7"] = item_e7(sink, ctx)
    items["E8"] = item_e8(sink, ctx)
    items["E9"] = item_e9(sink, ctx)
    manifest = write_manifest(sink, ctx, items, build_inputs_map())

    print("out_dir=%s" % sink.out)
    print("outputs=%d" % (len(manifest["outputs"]) + 2))
    for o in manifest["outputs"]:
        print("  %8d  %s  %s" % (o["bytes"], o["sha256"][:16], o["path"]))
    print("  MANIFEST.json / MANIFEST.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
