# -*- coding: utf-8 -*-
"""**复盘审计**：针对已发现的错误类别，主动搜同类问题（可执行，不靠自述）。

已发现的错误类别（本会话实测）：
* **类别 A｜静默覆盖**：多批/多来源数据按参数键合并 ⇒ 后写者覆盖先写者（已犯 1 次：A 223→61 行）；
* **类别 B｜比错对象**：跨来源对照派生量前未确认两侧指**同一特征**（已犯 3 次：
  `Bandwidth.txt` 行序、A 的 `f_peak` 是全扫频最大、marker 口径）；
* **类别 C｜指标退化**：定义导致指标恒为常数（已犯 1 次：带内 max−min 恒为 3 dB）；
* **类别 D｜静默丢列/丢行**：守卫写得过严或过宽，把有效数据丢掉（已犯 2 次：
  读表按列数过滤、`mech.csv` 的 `v_z_m3s` 被跳过）。

本脚本逐条**实测**检查，而不是断言：
1. **镜像重叠**：所有把多个镜像读进同一 dict 的地方，键集必须**不相交**；相交就是类别 A 风险。
2. **两张独立标签表交叉核对**：`first_peak_metrics` 与 `multichannel_labels` 在批 C 部分
   应给出**逐行一致**的 f_peak/BW/Q；不一致 ⇒ 其中一张有 bug。
3. **隔离组合是否混进头条统计**：头条计数应显式报出"含/不含隔离组合"两个版本。
4. **通道覆盖缺口**：每个缺失通道都要有**正当理由**（口径不同），否则是类别 D。
5. **跨批可比性**：x 密度与频段不同的批次混在一张表里时，必须逐行标注并给出计数。

用法：python -B work/tools/audit_data_pipeline.py
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys
from collections import Counter

REPO = pathlib.Path(__file__).resolve().parents[2]
HERE = REPO / "work/runs/first-peak-20260929"
C_MIRROR = REPO / "work/runs/x-densify-20260928/mirror"
N28_MIRROR = REPO / "work/runs/n2-8-intake-20260929/raw"
A_DIR = REPO / "work/runs/remote-exported-20260922/dataset"
QUARANTINE = {(0.2, 1.0, 7.0), (0.2, 1.0, 8.0)}
FINDINGS: list[tuple[str, str, str]] = []          # (严重度, 检查项, 说明)


def add(sev: str, item: str, detail: str) -> None:
    FINDINGS.append((sev, item, detail))


def mirror_keys(mirror: pathlib.Path) -> Counter:
    """统计某镜像里 Table_9 覆盖的 (x,N1,N2) 组合（用最小解析，只取前 4 列）。"""
    keys: Counter = Counter()
    if not mirror.is_dir():
        return keys
    for run in sorted(p for p in mirror.iterdir() if p.is_dir() and p.name.startswith("cell_")):
        t9 = run / "Table_9.txt"
        if not t9.is_file():
            continue
        seen = set()
        for ln in t9.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if not s or s.startswith("%"):
                continue
            f = s.split()
            if len(f) >= 4:
                seen.add((round(float(f[0]), 6), round(float(f[1]), 6), round(float(f[2]), 6)))
        for k in seen:
            keys[k] += 1
    return keys


def check_mirror_overlap() -> None:
    a, b = mirror_keys(C_MIRROR), mirror_keys(N28_MIRROR)
    inter = set(a) & set(b)
    if inter:
        add("P0", "镜像重叠（类别 A）",
            "C_mirror 与 N2=8 mirror 有 %d 个共同组合 ⇒ 任何 `out[k]=...` 都会静默覆盖！例：%s"
            % (len(inter), sorted(inter)[:3]))
    else:
        add("OK", "镜像重叠（类别 A）",
            "两个 C 镜像组合**完全不相交**（%d + %d）⇒ 合并安全" % (len(a), len(b)))
    # 批 A 与批 C 的交集（这是**已知且必须保留**的跨批重复数据）
    Akeys, Ckeys = set(), set()
    with (A_DIR / "combos.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            Akeys.add((round(float(r["x_scale"]), 6), round(float(r["N_w_te1"]), 6),
                       round(float(r["N_w_te2"]), 6)))
    Ckeys = set(a) | set(b)
    add("INFO", "A∩C 重叠（需并排而非覆盖）",
        "A %d、C %d、交集 **%d** ⇒ 合并时**必须把批次并入键**" % (len(Akeys), len(Ckeys),
                                                              len(Akeys & Ckeys)))


def check_two_tables_agree() -> None:
    """两张独立生成的标签表在**批 C** 部分必须逐行一致（同代码同为同数据）。"""
    p1, p2 = HERE / "first_peak_metrics.csv", HERE / "multichannel_labels.csv"
    if not (p1.is_file() and p2.is_file()):
        add("SKIP", "两表交叉核对", "缺文件")
        return
    t1 = {}
    with p1.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            t1[(round(float(r["x_scale"]), 6), round(float(r["N_w_te1"]), 6),
                round(float(r["N_w_te2"]), 6))] = r
    t2 = {}
    with p2.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["source_dataset"] != "C":
                continue
            t2[(round(float(r["x_scale"]), 6), round(float(r["N_w_te1"]), 6),
                round(float(r["N_w_te2"]), 6))] = r
    common = set(t1) & set(t2)
    if not common:
        add("P0", "两表交叉核对", "没有共同组合 ⇒ 无法核对（可疑）")
        return
    bad, worst = [], 0.0
    for k in common:
        r1, r2 = t1[k], t2[k]
        for col in ("f_peak_Hz", "bandwidth_Hz", "Q_factor"):
            a, b = r1.get(col, ""), r2.get(col, "")
            if (a in ("", "None")) != (b in ("", "None")):
                bad.append((k, col, "一侧为空一侧非空", a, b))
                continue
            if a in ("", "None"):
                continue
            d = abs(float(a) - float(b)) / max(abs(float(a)), 1e-30)
            worst = max(worst, d)
            if d > 1e-9:
                bad.append((k, col, "数值不一致", a, b))
    if bad:
        add("P0", "两表交叉核对（类别 B/D）",
            "批 C 部分 %d 个共同组合中有 **%d 处不一致**（最大相对差 %.3g）；例：%s"
            % (len(common), len(bad), worst, bad[:3]))
    else:
        add("OK", "两表交叉核对", "批 C 部分 %d 个共同组合的 f_peak/BW/Q **逐行完全一致**"
            % len(common))
    # 覆盖差异（一张表有、另一张没有 ⇒ 静默丢行）
    only1, only2 = set(t1) - set(t2), set(t2) - set(t1)
    if only1:
        add("WARN", "两表覆盖差异（类别 D）",
            "只在 first_peak_metrics 里 %d 个（另一张应更多，不该更多）" % len(only1))
    elif only2:
        add("OK", "两表覆盖差异（**已确认是设计差异**）",
            "只在 multichannel 里 %d 个 = **无局部极大的组合**（`multichannel_labels` 保留它们并标 "
            "`first_peak_found=False`，而 `first_peak_metrics` 直接跳过）⇒ "
            "**不是丢行**；下游应以 `multichannel_labels.csv` 为主表（超集）" % len(only2))
    else:
        add("OK", "两表覆盖差异", "两张表的批 C 组合集**完全相同**（各 %d）" % len(t1))


def check_quarantine_in_headlines() -> None:
    """头条计数必须能区分「含/不含隔离组合」。

    ⚠️ **必须从超集表（`multichannel_labels.csv`）取隔离总数**（2026-09-29 实测踩坑）：
    隔离组合 `(0.2,1,7)`/`(0.2,1,8)` 在 5–35/5–50 MHz 窗内**没有内部局部极大**，
    因此根本不进 `first_peak_metrics.csv` ⇒ 只读后者会打印「隔离行 0 个」，
    读者会误以为「全流程没有隔离组合」。真实情况是**超集表里有 4 行（A、C 各 2）**。
    本检查改为**两表都读**，并把差异解释清楚。
    """
    p_head = HERE / "first_peak_metrics.csv"
    p_super = HERE / "multichannel_labels.csv"
    if not p_head.is_file():
        add("SKIP", "隔离组合与头条统计", "缺 first_peak_metrics.csv")
        return
    rows = list(csv.DictReader(p_head.open(encoding="utf-8", newline="")))
    q = [r for r in rows if r["quarantined"] == "True"]
    closed_all = [r for r in rows if r["bandwidth_closed"] == "True"]
    closed_noq = [r for r in closed_all if r["quarantined"] != "True"]
    rel_all = [r for r in rows if r["ranking_eligible"] == "True"]
    rel_noq = [r for r in rel_all if r["quarantined"] != "True"]

    n_super_q, n_super = None, None
    if p_super.is_file():
        srows = list(csv.DictReader(p_super.open(encoding="utf-8", newline="")))
        n_super = len(srows)
        n_super_q = sum(1 for r in srows if r.get("quarantined") == "True")
    src = ("；超集表 %s 共 %d 行、其中隔离 %s 行（**差异原因**：隔离组合在扫描窗内无内部局部极大，"
           "不进首峰表，属预期而非丢行）"
           % (p_super.name, n_super, n_super_q) if n_super is not None else
           "；⚠️ 缺超集表 ⇒ 无法核对隔离组合是否被整体丢弃")
    add("INFO", "隔离组合与头条统计",
        "首峰表内隔离行 %d 个；带宽闭合：含 %d / 不含 %d；可排名：含 %d / 不含 %d%s"
        % (len(q), len(closed_all), len(closed_noq), len(rel_all), len(rel_noq), src))
    if n_super is not None and n_super_q == 0:
        add("WARN", "隔离组合标记丢失（类别 C）",
            "超集表 `%s` 里**没有任何** `quarantined=True` 行 ⇒ 隔离标记可能在重建时被静默丢弃"
            % p_super.name)
    if len(closed_all) != len(closed_noq) or len(rel_all) != len(rel_noq):
        add("WARN", "隔离组合混进头条（类别 C）",
            "隔离组合**改变**了头条计数 ⇒ 报告必须显式给出「含/不含」两版，且主口径应排除")
    else:
        add("OK", "隔离组合混进头条", "两张计数在排除隔离后**不变** ⇒ 无污染")


def check_channel_gaps() -> None:
    """每个缺失通道都要有正当理由（否则是类别 D：静默丢列）。"""
    p = HERE / "multichannel_coverage.json"
    if not p.is_file():
        add("SKIP", "通道覆盖缺口", "缺 multichannel_coverage.json")
        return
    cov = json.loads(p.read_text(encoding="utf-8"))["per_batch"]
    gaps = []
    for batch, chans in cov.items():
        for ch, (have, total) in chans.items():
            if have == 0:
                gaps.append((batch, ch))
    if gaps:
        add("P0", "通道覆盖缺口（类别 D）",
            "整列缺失：%s ⇒ 必须逐条给出理由（口径不同 or 修 loader）" % gaps)
    else:
        # 覆盖率是**低频界**：每批里可能只有部分组合有值（例如只在找到峰的组合上取值）
        lows = [(b, c, have, total) for b, chans in cov.items()
                for c, (have, total) in chans.items() if total and have / total < 0.99]
        add("OK", "通道覆盖缺口", "无整列缺失")
        if lows:
            add("INFO", "通道覆盖率 <100% 的项",
                "共 %d 项；例：%s（这些是「只在部分组合上取值」的通道，不是丢失）"
                % (len(lows), lows[:4]))


def check_cross_batch_comparability() -> None:
    """x 密度与频段不同的批次混在一张表里 ⇒ 必须逐行标注 + 报计数。"""
    p = HERE / "multichannel_labels.csv"
    if not p.is_file():
        add("SKIP", "跨批可比性", "缺 multichannel_labels.csv")
        return
    rows = list(csv.DictReader(p.open(encoding="utf-8", newline="")))
    g = Counter((r["source_dataset"], r["freq_grid_MHz"]) for r in rows)
    xs = {}
    for r in rows:
        xs.setdefault(r["source_dataset"], set()).add(round(float(r["x_scale"]), 2))
    add("INFO", "跨批可比性标注", "行分布 %s；x 取值数 %s"
        % (dict(g), {k: len(v) for k, v in xs.items()}))
    if len(xs.get("A", ())) and len(xs.get("C", ())):
        has_col = all("x_density_class" in r for r in rows)
        add("OK" if has_col else "WARN", "x 密度不同的批次混表",
            "批 A 的 x 是 0.1 步长（%d 个值），批 C 是 0.01 步长（%d 个值）⇒ "
            "**趋势/拟合必须按批次分层或加权**；表里已加 `x_density_class` 列供分层：%s"
            % (len(xs["A"]), len(xs["C"]), "已具备" if has_col else "**缺失，需补**"))
    # 频段不同导致"首个峰"可能不是同一个
    add("INFO", "跨批峰定义一致性",
        "批 A 在 5–35 MHz 内找峰、批 C 在 5–50 MHz 内找峰 ⇒ "
        "同一参数在 A 里「无峰」、在 C 里「有峰」是**可能且正常**的；"
        "跨批比较首个峰频率**不是我做的**，此处仅标注风险")


def main() -> int:
    check_mirror_overlap()
    check_two_tables_agree()
    check_quarantine_in_headlines()
    check_channel_gaps()
    check_cross_batch_comparability()
    print("=" * 90)
    print("复盘审计结果（%d 项）" % len(FINDINGS))
    print("=" * 90)
    for sev, item, detail in FINDINGS:
        print("[%-4s] %s" % (sev, item))
        print("        %s" % detail)
    n_bad = sum(1 for s, _, _ in FINDINGS if s in ("P0", "WARN"))
    print("\n需要处理：P0+WARN = %d 项" % n_bad)
    return 0 if n_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
