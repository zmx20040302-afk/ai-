# -*- coding: utf-8 -*-
"""A5「扫描分析与优化」的**确定性分析层**（fail-closed）。

## 为什么排名也不能交给 LLM

`AGENTS.md` 红线 1/4 要求：每个数字可回溯、**来源永不混同**。落到扫描分析上就是三条硬规则：

1. **绝不合成单一总分。** 目标之间天然冲突（带宽 vs 灵敏度 vs 功耗），加权成一个数
   等于把冲突藏起来。本模块**在结构上**不提供加权/求和字段，并有一项检查
   `no_composite_score` 主动扫描输出里是否混进了 `score/weight/composite/...` 这类键
   （防的是上层"顺手加个总分"）。
2. **绝不跨族合并统计。** 排名一律按 `(family, metric)` 分组；行缺族标签 ⇒ 判失败，
   而不是"当成同一族"。
3. **未过质量门的点单列，不进排名**（未闭合带宽、稀疏频点导致峰值只是下界、
   驱动未核实、退化几何……）。被排除的条目**必须逐条出现在 `quality.excluded` 里**。

判定语义复用 `memsharness.consistency.evaluate_s3()`（任一 False ⇒ failed；任一 None ⇒
inconclusive 且不放行；空检查集 ⇒ inconclusive 且不放行），与 A8 门禁同一套语义，
不另造一套。**本模块不"放行"任何东西**：`release_allowed` 只表示"该批排名可用于下游决策"，
最终放行权在人（红线 5）。

## 口径（caliber）

每个指标必须显式声明口径，取值限于 `ALLOWED_CALIBERS`：

| caliber | 含义 |
|---|---|
| `amplitude_20log10` | 幅值量的 dB 基准（**只能**用 20·log10） |
| `power_10log10` | 功率量的 dB 基准（**只能**用 10·log10） |
| `response_20log10` | 响应（速度/位移）量的 dB 基准 |
| `absolute` | 绝对物理量（Pa、W、m、MHz、%…），不做 dB 换算 |
| `drive_dependent` | 依赖激励口径的绝对量（如 `Ptot` 依赖 Vdiff）⇒ 必须声明激励 |

同一 `quantity_group` 下出现两个不同 dB 基准 ⇒ 判失败（那正是"20log10/10log10 混用"）。

## 与 A6/A7/A8/A9 的关系

* 输入是 A4 的合格数据集（带族标签）与 A1 的口径批准；
* 输出 `scan_analysis` / `next_batch` 供 A9 写报告；
* A5 **不触发求解**：建议点交给 A3；本模块只产出"选点建议 + 依据 + 成本 + 停止条件"。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .consistency import CheckResult, evaluate_s3

SWEEP_VERSION = "a5-sweep-analysis-1"

ALLOWED_CALIBERS = (
    "amplitude_20log10",
    "power_10log10",
    "response_20log10",
    "absolute",
    "drive_dependent",
)
DIRECTIONS = ("max", "min")

#: 质量标记：既可作为指标级"排除理由"，也可作为行级"提示"
KNOWN_FLAGS = (
    "bandwidth_not_closed_3dB_Vave",
    "bandwidth_not_closed_6dB_Vave",
    "bandwidth_not_closed_3dB_Vcenter_abs",
    "bandwidth_not_closed_6dB_Vcenter_abs",
    "bandwidth_not_closed_3dB_Ptot",
    "bandwidth_not_closed_6dB_Ptot",
    "pressure_bandwidth_unavailable",
    "sparse_frequency_grid",
    "peak_is_lower_bound",
    "peak_at_range_edge",
    "drive_not_verified",
    "measurement_point_unverified",
    "wrong_speed_of_sound",
    "solver_not_succeeded",
    "solver_status_unrecorded",
    "geometry_invalid",
    "mesh_invalid",
    "degenerate_geometry",
    "out_of_declared_grid",
    "missing_value",
    #: 几何/选择集预检判定为**非 clean**（A8 红队指出：预检给了却不影响排名 = 假接线）
    "precheck_not_clean",
    #: 远端导出族（`cell_te2_*`）实测专用
    #: ① 导出器自己在批次日志里报的告警（逐条转成 flag）
    "exporter_warning_peak_at_boundary",
    "exporter_warning_cutoff_at_endpoint",
    "exporter_warning_marker_pairing_ambiguous",
    #: ② 标记表（Bandwidth/Peak_frequency）无参数列、行数与组合数不成比例 ⇒ 无法归属
    "marker_table_not_attributable",
    #: ③ 标记表可归属时，其"峰"与逐点 argmax 不一致
    "marker_peak_mismatch",
    #: ④ 该 run 只覆盖 x_scale 的一部分（测试序列）
    "partial_x_scan",
    #: ⑤ −3 dB 交点没有同时落在扫描范围内（扫描端点仍高于 peak−3 dB）⇒ 带宽/Q 不可用
    "bandwidth_not_closed",
)

#: **全局取消资格**的标记：命中即该行在所有指标上都不参与排名，也不进 Pareto。
#: 为什么必须全局：几何无效 / 网格无效 / 两电极边界重合 / 预检非 clean 的点，
#: 其任何指标值都不可比——把它们仅列为"某个指标的排除项"会让它们从别的指标溜进排名
#: （A8 红队实测：标了 geometry_invalid+mesh_invalid 的点仍排 Ptot 第 1 并进 Pareto）。
GLOBAL_EXCLUDE_FLAGS = frozenset({
    "geometry_invalid", "mesh_invalid", "degenerate_geometry", "precheck_not_clean",
})

#: 合成总分守卫（防"顺手加个总分"）。只做**键名**层面的拦截，不猜语义。
COMPOSITE_KEY_PATTERN = re.compile(
    r"(?i)(^|_)(score|score_total|total_score|composite|composite_score|weight|weights|"
    r"weighted|weighted_sum|weighted_score|overall|overall_score|merit|figure_of_merit)($|_)"
)
#: 唯一豁免：守卫自己的声明字段（`no_composite_score` 里的 `_score` 会命中模式）。
#: 豁免是**固定集合**且写在这里，不是"调用方可传参"——否则豁免本身就变成后门。
COMPOSITE_GUARD_EXEMPT_KEYS = frozenset({"no_composite_score"})


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MetricSpec:
    """一个指标的口径与筛选策略。

    ``exclude_flags``：命中即把该 **行×该指标** 排除出排名（单列原因）。
    ``advisory_flags``：命中只让该行在该指标上标 `provisional`，仍参与排名。
    """

    name: str
    label: str
    unit: str
    direction: str
    caliber: str
    exclude_flags: tuple[str, ...] = ()
    advisory_flags: tuple[str, ...] = ()
    quantity_group: str = ""

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise ValueError("direction 必须是 %s 之一：%r" % (DIRECTIONS, self.direction))
        if self.caliber not in ALLOWED_CALIBERS:
            raise ValueError("caliber 必须是 %s 之一：%r" % (ALLOWED_CALIBERS, self.caliber))
        bad = [f for f in list(self.exclude_flags) + list(self.advisory_flags)
               if f not in KNOWN_FLAGS]
        if bad:
            raise ValueError("未登记的质量标记 %r（请先在 KNOWN_FLAGS 登记，避免拼写漂移）" % bad)
        if COMPOSITE_KEY_PATTERN.search(self.name):
            raise ValueError("指标名 %r 命中合成总分守卫：A5 禁止加权/总分指标" % self.name)

    def to_dict(self) -> dict:
        return {"name": self.name, "label": self.label, "unit": self.unit,
                "direction": self.direction, "caliber": self.caliber,
                "quantity_group": self.quantity_group or self.name,
                "exclude_flags": list(self.exclude_flags),
                "advisory_flags": list(self.advisory_flags)}


@dataclass
class Row:
    """一行 = 一个已求解的参数组合（同一几何族内）。"""

    family: str
    params: dict[str, Any]
    values: dict[str, float | None]
    flags: set[str] = field(default_factory=set)
    source_run_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        return "%s|%s" % (self.family, json.dumps(self.params, sort_keys=True, default=str))

    def to_dict(self) -> dict:
        return {"family": self.family, "params": dict(self.params),
                "values": dict(self.values), "flags": sorted(self.flags),
                "source_run_id": self.source_run_id}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _is_finite(x: Any) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)


def _num(v: Any) -> Any:
    """把"看起来是数"的参数值统一成 int/float。

    实测必要性：CSV 里 `x_scale=0.40`、`N_w_te1=6.0` 都是**字符串**，而候选网格 JSON 里是
    数字；不做归一化会导致"同一个点"被当成两个点（质量修复目标永远匹配不上、选点重复）。
    """
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if not s:
        return v
    try:
        f = float(s)
    except ValueError:
        return v
    return int(f) if f.is_integer() else f


def rows_from_records(
    records: Iterable[Mapping[str, Any]],
    *,
    family_key: str = "source_family",
    param_keys: Sequence[str] = ("x_scale", "N_w_te1"),
    metric_keys: Sequence[str],
    flag_rules: Mapping[str, Any] | None = None,
    run_id_key: str = "run_id",
) -> list[Row]:
    """把宽表记录（CSV 行）转成 `Row`。

    * 值缺失/非有限 ⇒ **记 `missing_value` 标记**，**绝不填 0**（红线：NaN 不填 0）；
    * 参数值做数值归一化（见 `_num`），保证 CSV 与候选网格能对上同一个点；
    * `flag_rules`：`{flag: callable(record) -> bool}`，由调用方声明"什么情况算这个标记"，
      使标记的产生方式与数据一起可复核（不把判据藏在分析层里）。
    """
    out: list[Row] = []
    rules = dict(flag_rules or {})
    for rec in records:
        fam = rec.get(family_key)
        fam = "" if fam is None else str(fam)
        params = {k: _num(rec.get(k)) for k in param_keys}
        values: dict[str, float | None] = {}
        flags: set[str] = set()
        for k in metric_keys:
            v = rec.get(k)
            if v in (None, "") or not _is_finite(v):
                values[k] = None
                flags.add("missing_value")
            else:
                values[k] = float(v)
        for flag, fn in rules.items():
            if flag not in KNOWN_FLAGS:
                raise ValueError("未登记的质量标记 %r" % flag)
            try:
                hit = bool(fn(rec))
            except Exception as exc:            # 规则自身出错不能静默算作"没问题"
                raise ValueError("质量标记规则 %r 求值出错：%s" % (flag, exc)) from exc
            if hit:
                flags.add(flag)
        out.append(Row(family=fam.strip(), params=params, values=values, flags=flags,
                       source_run_id=(str(rec.get(run_id_key)) if rec.get(run_id_key) else None)))
    return out


# ---------------------------------------------------------------------------
# 质量检查（单项）
# ---------------------------------------------------------------------------
def check_input_nonempty(rows: Sequence[Row]) -> CheckResult:
    n = len(rows)
    return CheckResult("input_nonempty", n > 0, float(n), 1.0,
                       "" if n else "输入行为 0 ⇒ 没有任何数据可分析（空集判失败）",
                       {"n_rows": n})


def check_family_label_present(rows: Sequence[Row]) -> CheckResult:
    missing = [i for i, r in enumerate(rows) if not r.family]
    ok = bool(rows) and not missing
    return CheckResult("family_label_present", ok, float(len(missing)), 0.0,
                       "" if ok else ("%d/%d 行缺几何族标签 ⇒ 无法保证不跨族合并（判失败）"
                                      % (len(missing), len(rows))),
                       {"n_missing": len(missing), "missing_index": missing[:10]})


def check_caliber_declared(metrics: Sequence[MetricSpec]) -> CheckResult:
    if not metrics:
        return CheckResult("caliber_declared", None, None, None,
                           "未声明任何指标口径 ⇒ 无法判定（不等同通过）")
    bad = [m.name for m in metrics if m.caliber not in ALLOWED_CALIBERS]
    ok = not bad
    return CheckResult("caliber_declared", ok, float(len(bad)), 0.0,
                       "" if ok else "指标口径未声明或越界：%r" % bad,
                       {"n_metrics": len(metrics), "calibers": {m.name: m.caliber for m in metrics}})


def check_caliber_consistency(metrics: Sequence[MetricSpec]) -> CheckResult:
    """同一 `quantity_group` 下不得出现两个不同 dB 基准（20log10 vs 10log10 混用）。"""
    groups: dict[str, set[str]] = {}
    for m in metrics:
        g = m.quantity_group or m.name
        groups.setdefault(g, set()).add(m.caliber)
    bad = {g: sorted(c) for g, c in groups.items() if len(c) > 1}
    ok = not bad
    return CheckResult("caliber_consistency", ok, float(len(bad)), 0.0,
                       "" if ok else "同一 quantity_group 出现多个口径（dB 基准混用）：%r" % bad,
                       {"groups": {g: sorted(c) for g, c in groups.items()}})


def _rows_rankable(row: Row, m: MetricSpec) -> tuple[bool, list[str]]:
    """该行的该指标能否进排名。**全局取消资格标记优先**（任何指标都不参与）。"""
    reasons = [f for f in sorted(row.flags) if f in GLOBAL_EXCLUDE_FLAGS]
    reasons += [f for f in sorted(row.flags)
                if f in m.exclude_flags and f not in GLOBAL_EXCLUDE_FLAGS]
    if row.values.get(m.name) is None and "missing_value" not in reasons:
        reasons.append("missing_value")
    return (not reasons), reasons


def check_effective_points(rows: Sequence[Row], metrics: Sequence[MetricSpec],
                           *, min_effective: int) -> tuple[list[CheckResult], dict]:
    """有效点（**逐族**统计）不足 ⇒ **无法判定**（不出结论，不判失败）。

    区分两类判定：`failed` 是"产物本身违规"（空输入、跨族、口径混用），
    `inconclusive` 是"数据不足以支撑结论"（点太少、排除率过高、口径未批准）。
    两者都不放行，但把后者误标成 `failed` 会让失败分类失去意义。

    **逐族出检查项**（`effective_points[<族>]`）：一个族不可用不应掩盖另一个族可用。
    """
    families = sorted({r.family for r in rows if r.family})
    per_family: dict[str, int] = {f: 0 for f in families}
    for r in rows:
        if r.family and any(_rows_rankable(r, m)[0] for m in metrics):
            per_family[r.family] = per_family.get(r.family, 0) + 1
    if not families:
        return ([CheckResult("effective_points", False, 0.0, float(min_effective),
                             "没有任何（族内）有效点 ⇒ 无法排名（空集判失败）",
                             {"per_family": {}})],
                {"per_family": {}})
    out: list[CheckResult] = []
    for fam, n in sorted(per_family.items()):
        if n == 0:                                  # 该族一个有效点都没有 ⇒ 空集判失败
            out.append(CheckResult(
                "effective_points[%s]" % fam, False, 0.0, float(min_effective),
                "族 %r 没有任何有效点 ⇒ 无法排名（空集判失败）" % fam,
                {"family": fam, "n_effective": 0, "min_effective": min_effective}))
            continue
        ok = n >= min_effective
        out.append(CheckResult(
            "effective_points[%s]" % fam, True if ok else None, float(n), float(min_effective),
            "" if ok else "族 %r 仅 %d 个有效点 < 下限 %d ⇒ 无法判定"
                          "（停止条件：样本不足不出结论）" % (fam, n, min_effective),
            {"family": fam, "n_effective": n, "min_effective": min_effective}))
    return out, {"per_family": per_family}


def check_exclusion_rate(rows: Sequence[Row], metrics: Sequence[MetricSpec],
                         *, max_rate: float) -> list[CheckResult]:
    """质量门失败率过高 ⇒ **无法判定**（停止条件；被排除条目仍逐条单列）。

    **按族计算**：跨族平均会掩盖某个族整批不可用的事实。
    """
    if not rows or not metrics:
        return [CheckResult("exclusion_rate", None, None, max_rate, "无数据，无法判定")]
    per_family: dict[str, dict] = {}
    for r in rows:
        fam = per_family.setdefault(r.family, {"cells": 0, "excluded": 0})
        for m in metrics:
            fam["cells"] += 1
            if not _rows_rankable(r, m)[0]:
                fam["excluded"] += 1
    out: list[CheckResult] = []
    for f, v in sorted(per_family.items()):
        rate = (v["excluded"] / v["cells"]) if v["cells"] else 0.0
        ok = rate <= max_rate
        out.append(CheckResult(
            "exclusion_rate[%s]" % f, True if ok else None, rate, max_rate,
            "" if ok else "族 %r 的质量门排除率 %.1f%% > 上限 %.1f%% ⇒ 无法判定"
                          "（停止条件：该族不足以选最优参数）"
                          % (f, 100 * rate, 100 * max_rate),
            {"family": f, "n_cells": v["cells"], "n_excluded": v["excluded"],
             "max_rate": max_rate}))
    return out


def check_cross_family_isolation(rankings: Sequence[dict]) -> CheckResult:
    """结构守卫：任何一条排名都只能属于**一个**族。"""
    bad = [r for r in rankings if len({str(x) for x in r.get("families", [r.get("family")])}) != 1]
    ok = not bad
    return CheckResult("cross_family_isolation", ok, float(len(bad)), 0.0,
                       "" if ok else "存在跨族排名条目（禁止跨族合并统计）",
                       {"n_rankings": len(rankings), "n_bad": len(bad)})


def check_no_cross_family_duplicate_points(rows: Sequence[Row]) -> CheckResult:
    """同**参数组合**不得同时出现在多个族里。

    A8 红队漏检 #9：同一个参数点在两族各排 #1，会被读成"两族独立复算一致"——
    那是重复计数，不是独立证据。命中即判失败（不是"标个提示"）。
    """
    owners: dict[str, set[str]] = {}
    for r in rows:
        owners.setdefault(json.dumps({k: _num(v) for k, v in r.params.items()},
                                     sort_keys=True, default=str), set()).add(r.family)
    dup = {k: sorted(v) for k, v in owners.items() if len(v) > 1}
    ok = not dup
    return CheckResult("no_cross_family_duplicate_points", ok, float(len(dup)), 0.0,
                       "" if ok else "%d 个参数组合同时出现在多个族 ⇒ 会被当作独立复算" % len(dup),
                       {"n_duplicate_params": len(dup),
                        "examples": list(dup.items())[:5]})


# ---------------------------------------------------------------------------
# 跨批次纪律（红线 §8.4 / §8.5）
# ---------------------------------------------------------------------------
#: 批次**聚合标签**：出现即说明有人把多批合并成一批/一行（红线 §8.4 禁止混算与合成总分）。
#: 只做**标签字面**层面的拦截，不猜语义 —— 与 `COMPOSITE_KEY_PATTERN` 同一思路。
BATCH_MERGE_LABELS = frozenset({
    "all", "combined", "merge", "merged", "total", "both", "union", "pooled",
    "overall", "综合", "合并", "合计", "全部", "总计",
})

#: 组合身份键的 ulp 归一化小数位。
#: R5 实测（2026-10-08 数据侧）：`x_scale` 在两批间存在 **1 ulp 表示差**
#: （C 批存 `0.30000000000000004`、v2 批存 `0.3`）。不做归一化 ⇒ 同一组合被判成两个组合
#: ⇒ **新增数虚高**（实测把 83 误报成 117，虚高 34）。归一化是**判等**用的，不改存储值。
IDENTITY_ROUND_DECIMALS = 6


def _truthy(v: Any) -> bool:
    """只有字面 true/1/yes 算真。**空字符串不是真** —— 缺列不得被当作通过。"""
    return str(v).strip().lower() in ("true", "1", "yes", "y", "t")


def _identity_key(rec: Mapping[str, Any], param_keys: Sequence[str],
                  decimals: int | None) -> tuple:
    """组合身份键。``decimals=None`` ⇒ 原样（用 `repr` 保留 1 ulp 差）。"""
    out: list[Any] = []
    for k in param_keys:
        v = _num(rec.get(k))
        if decimals is not None and isinstance(v, float):
            v = round(v, decimals)
        out.append(repr(v) if decimals is None else v)
    return tuple(out)


def check_batch_isolation(
    records: Sequence[Mapping[str, Any]],
    *,
    batch_key: str = "batch",
    range_key: str = "freq_range_MHz",
    param_keys: Sequence[str] = ("x_scale", "N_w_te1", "N_w_te2"),
    censor_keys: Sequence[str] = ("peak_at_scan_endpoint", "bw_upper_cutoff_at_endpoint"),
    eligible_keys: Sequence[str] = ("ranking_eligible", "usable"),
    decimals: int = IDENTITY_ROUND_DECIMALS,
) -> list[CheckResult]:
    """跨批次纪律检查：红线 §8.4（不同扫描范围不得混算）＋ §8.5（删失/截断不得进排名）。

    用途：`analyze()` 之外的**独立批次门禁** —— 标签并集表、多批对比表这类
    「按 `batch` 列并排」的产物走本函数。判定语义复用 `evaluate_s3`
    （任一 False ⇒ failed；任一 None ⇒ inconclusive 且不放行；空检查集 ⇒ inconclusive）。

    五项检查：

    1. ``batch_label_present`` —— 每行必须有批次标签。缺标签 ⇒ 无法判定归属，
       也就无法判定是否混算 ⇒ **判失败**（不得「当成同一批」）。
    2. ``batch_no_merge_label`` —— 批次标签不得是聚合标签（``all``/``combined``/``综合``…）：
       出现聚合标签意味着多批已被**合成**一批 ⇒ 判失败。
    3. ``batch_single_range[<批>]`` —— 同一批次只允许**一个**扫描口径（频率范围等）。
       同名两口径 ⇒ 判失败；口径列全空 ⇒ **无法判定**（不等同通过）。
    4. ``batch_censored_not_eligible`` —— 命中删失/截断标记的行**不得**同时被标为可排名/可用。
       违反 ⇒ 判失败（红线 §8.5）；未提供任何删失/截断标记列 ⇒ **无法判定**。
       **逐批**核验原始标志列的**可得性**：某批的标志列**整列为空**（该批**无法复验**）
       ⇒ 本项判**无法判定**（``None``），**不得**因为「空列里没有违规」就判通过 ——
       **空列 ≠ 通过**（那是假通过）。判定次序固定为
       「先已发现的违规（有 ⇒ failed，与收紧前一致）→ 再整列为空的批（有 ⇒ None）→ 否则通过」，
       因此本项相对收紧前**只可能把 True 变成 None**，**不会**把 False 变成 None（那才叫放宽）。
    5. ``batch_no_cross_batch_combo`` —— 同一参数组合不得出现在多个批次里。
       命中 ⇒ **无法判定**（``None``，不判 failed）：它既让 batch 失去「防泄漏整组切分键」资格，
       也让未归一化的「新增数」虚高。note 同时报**原样**与**归一化**两种口径的重叠数，
       使 1 ulp 造成的虚高一眼可见。
    """
    recs = list(records)
    out: list[CheckResult] = []
    norm = lambda s: str(s or "").strip().lower()   # noqa: E731

    # ---- 1. 批次标签齐全 ----
    missing = [i for i, r in enumerate(recs)
               if not str(r.get(batch_key, "") or "").strip()]
    ok1 = bool(recs) and not missing
    if not recs:
        reason1 = "输入为 0 行 ⇒ 没有任何批次可判定（空集判失败）"
    elif missing:
        reason1 = "%d/%d 行缺批次标签 ⇒ 无法判定是否混算（判失败）" % (len(missing), len(recs))
    else:
        reason1 = ""
    out.append(CheckResult(
        "batch_label_present", ok1, float(len(missing)), 0.0, reason1,
        {"n_rows": len(recs), "n_missing": len(missing), "missing_index": missing[:10]}))

    # ---- 2. 不得出现聚合（合并）标签 ----
    merged = sorted({norm(r.get(batch_key)) for r in recs} & BATCH_MERGE_LABELS)
    ok2 = not merged
    out.append(CheckResult(
        "batch_no_merge_label", ok2, float(len(merged)), 0.0,
        "" if ok2 else
        "批次标签出现聚合标签 %r ⇒ 多批被合并成一批（红线：不得混算 / 不得合成总分）" % merged,
        {"merge_labels": merged, "known_merge_labels": sorted(BATCH_MERGE_LABELS)}))

    # ---- 3. 一批一口径 ----
    by_batch: dict[str, list[Mapping[str, Any]]] = {}
    for r in recs:
        by_batch.setdefault(norm(r.get(batch_key)), []).append(r)
    for b, rows_b in sorted(by_batch.items()):
        ranges = sorted({str(r.get(range_key, "") or "").strip() for r in rows_b})
        if len(ranges) == 1 and not ranges[0]:
            out.append(CheckResult(
                "batch_single_range[%s]" % (b or "(空批次标签)"), None, 0.0, 1.0,
                "批次 %r 未声明扫描口径（列 %r 全空）⇒ 无法判定是否混算（不等同通过）"
                % (b, range_key),
                {"batch": b, "ranges": ranges, "range_key": range_key}))
            continue
        okb = len([x for x in ranges if x]) <= 1
        out.append(CheckResult(
            "batch_single_range[%s]" % (b or "(空批次标签)"), okb, float(len(ranges)), 1.0,
            "" if okb else
            "批次 %r 出现 %d 个扫描口径 %r ⇒ 同名两口径，判失败" % (b, len(ranges), ranges),
            {"batch": b, "ranges": ranges, "range_key": range_key}))

    # ---- 4. 删失/截断的组合不得被标为可排名/可用（红线 §8.5）----
    present = [k for k in censor_keys if any(k in r for r in recs)]
    if not present:
        out.append(CheckResult(
            "batch_censored_not_eligible", None, None, 0.0,
            "未提供任何删失/截断标记列 %r ⇒ 无法判定（不等同通过）" % list(censor_keys),
            {"censor_keys": list(censor_keys), "eligible_keys": list(eligible_keys)}))
    else:
        # ① 逐批核验原始标志列的**可得性**（R15：判不了 ≠ 通过）。
        #    某批的标志列**整列为空** ⇒ 该批没有任何可复核的原始值 ⇒ 该批**无法复验**。
        #    空列里"没有违规"只是"没看到"，**不是**"没有"——照旧判 PASS 就是**假通过**。
        flag_cov: dict[str, dict] = {}
        blank_batches: list[str] = []
        for b, rows_b in sorted(by_batch.items()):
            per_key = {k: sum(1 for r in rows_b if str(r.get(k, "") or "").strip())
                       for k in present}
            flag_cov[b] = {"n_rows": len(rows_b), "n_flag_nonempty": per_key}
            if all(n == 0 for n in per_key.values()):
                blank_batches.append(b)

        # ② 违规扫描（与收紧前逐字一致）。**先算违规**：已发现的违规是硬事实，
        #    不因"别的批判不了"而降级 —— 这保证本项只会更严，不会把 failed 变成 None。
        viol: list[dict] = []
        for i, r in enumerate(recs):
            hit = [k for k in present if _truthy(r.get(k))]
            if not hit:
                continue
            elig = [k for k in eligible_keys if _truthy(r.get(k))]
            if elig:
                viol.append({"index": i, "batch": norm(r.get(batch_key)),
                             "censored_by": hit, "marked_eligible_by": elig,
                             "params": {k: _num(r.get(k)) for k in param_keys}})

        def _disp(b: str) -> str:
            return "「%s」" % b if b else "「(空批次标签)」"

        detail4 = {"n_violations": len(viol), "examples": viol[:5],
                   "censor_keys": present, "eligible_keys": list(eligible_keys),
                   "per_batch_flag_coverage": flag_cov,
                   "blank_batches": blank_batches}
        blank_txt = "、".join(_disp(b) for b in blank_batches)
        if viol:
            reason4 = ("%d 行同时命中删失/截断标记与可排名标记 ⇒ 不得把删失/截断组合"
                       "当正常测量值参与排名（红线 §8.5）" % len(viol))
            if blank_batches:
                reason4 += ("；另有 %d 个批的标志列**整列为空**（%s）⇒ 那些批**无法复验**"
                            "（空列 ≠ 通过）" % (len(blank_batches), blank_txt))
            out.append(CheckResult(
                "batch_censored_not_eligible", False, float(len(viol)), 0.0, reason4, detail4))
        elif blank_batches:
            out.append(CheckResult(
                "batch_censored_not_eligible", None, 0.0, 0.0,
                "批 %s 的删失/截断标记列 %r **整列为空**（该批 0 行有原始标志值）"
                "⇒ 这些批**无法复验**：**空列 ≠ 通过**（空列里没有违规只是「没看到」，"
                "不是「没有」）⇒ 本项判「无法判定」（不等同通过）" % (blank_txt, present),
                detail4))
        else:
            out.append(CheckResult(
                "batch_censored_not_eligible", True, 0.0, 0.0, "", detail4))

    # ---- 5. 跨批组合重叠（泄漏前提 + 新增数虚高）----
    batches = sorted({norm(r.get(batch_key)) for r in recs})
    if len(batches) < 2:
        out.append(CheckResult(
            "batch_no_cross_batch_combo", None, None, 0.0,
            "只有 %d 个批次 ⇒ 无跨批对比可判定（单批不构成混算风险，但也不产生证据）"
            % len(batches),
            {"batches": batches}))
    else:
        norm_sets: dict[str, set] = {b: set() for b in batches}
        raw_sets: dict[str, set] = {b: set() for b in batches}
        for r in recs:
            b = norm(r.get(batch_key))
            norm_sets[b].add(_identity_key(r, param_keys, decimals))
            raw_sets[b].add(_identity_key(r, param_keys, None))
        pairs: dict[str, dict] = {}
        total_norm = total_raw = 0
        for i, a in enumerate(batches):
            for c in batches[i + 1:]:
                n_int = norm_sets[a] & norm_sets[c]
                r_int = raw_sets[a] & raw_sets[c]
                total_norm += len(n_int)
                total_raw += len(r_int)
                if n_int or r_int:
                    pairs["%s|%s" % (a, c)] = {
                        "n_overlap_normalized": len(n_int),
                        "n_overlap_raw": len(r_int),
                        "ulp_only_overlap": len(n_int) - len(r_int),
                        "examples_normalized": sorted(map(repr, n_int))[:5],
                    }
        ok5 = (total_norm == 0 and total_raw == 0)
        reason5 = "" if ok5 else (
            "跨批组合重叠 %d 个（ulp 归一化口径 %d、原样口径 %d）⇒ "
            "batch 失去「防泄漏整组切分键」资格；且不做 ulp 归一化时「新增数」会虚高"
            "（实测 1 ulp 表示差把 83 误报成 117）" % (total_norm, total_norm, total_raw))
        out.append(CheckResult(
            "batch_no_cross_batch_combo", True if ok5 else None,
            float(total_norm), 0.0, reason5,
            {"decimals": decimals, "param_keys": list(param_keys),
             "n_overlap_normalized": total_norm, "n_overlap_raw": total_raw,
             "ulp_only_overlap": total_norm - total_raw, "pairs": pairs}))
    return out


def _iter_keys(obj: Any, *, skip_metric_names: set[str], path: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            if ks in skip_metric_names or ks in COMPOSITE_GUARD_EXEMPT_KEYS:
                continue
            yield "%s.%s" % (path, ks)
            yield from _iter_keys(v, skip_metric_names=skip_metric_names,
                                  path="%s.%s" % (path, ks))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _iter_keys(v, skip_metric_names=skip_metric_names,
                                  path="%s[%d]" % (path, i))


def check_no_composite_score(payload: Any, metrics: Sequence[MetricSpec]) -> CheckResult:
    """结构守卫：输出里不得出现加权/总分字段。"""
    names = {m.name for m in metrics}
    hits = [p for p in _iter_keys(payload, skip_metric_names=names)
            if COMPOSITE_KEY_PATTERN.search(p.rsplit(".", 1)[-1])]
    ok = not hits
    return CheckResult("no_composite_score", ok, float(len(hits)), 0.0,
                       "" if ok else "输出含加权/总分字段（禁止用单一总分掩盖目标冲突）：%r" % hits[:5],
                       {"hits": hits[:20],
                        "policy": "A5 只给分指标排名与 Pareto 非支配集，不合成总分"})


# ---------------------------------------------------------------------------
# 排名 / Pareto
# ---------------------------------------------------------------------------
def _verdict_by_family(checks: Sequence[CheckResult], rows: Sequence[Row], *,
                       provisional: bool, caliber_approved: bool
                       ) -> tuple[dict[str, str], list[str]]:
    """逐族判定：把 `...[族]` 形式的检查项聚合到该族。

    **全局检查失败/无法判定会下调所有族**（A8 红队实测漏洞：口径混用或空输入让顶层判 failed 时，
    逐族仍报 ranked 且 `released_families` 非空 ⇒ 会被读成"这些族已放行"）。
    一个族不可用**不应掩盖**另一个族可用，但**全局性违规**必须掩盖：那是整批的问题。
    """
    families = sorted({r.family for r in rows if r.family})
    out: dict[str, str] = {}
    scoped_names = {c.name for c in checks if "[" in c.name}
    globals_ = [c for c in checks if c.name not in scoped_names]
    global_failed = any(c.passed is False for c in globals_)
    global_unknown = any(c.passed is None for c in globals_)
    for fam in families:
        scoped = [c for c in checks if c.name.endswith("[%s]" % fam)]
        if not caliber_approved or global_failed or global_unknown:
            out[fam] = "failed" if global_failed else "inconclusive"
            continue
        if any(c.passed is False for c in scoped):
            out[fam] = "failed"
        elif any(c.passed is None for c in scoped):
            out[fam] = "inconclusive"
        else:
            out[fam] = "provisional" if provisional else "ranked"
    return out, [f for f, v in out.items() if v == "ranked"]


def _exclusion_by_family(rows: Sequence[Row], metrics: Sequence[MetricSpec]) -> dict[str, float]:
    """逐族排除率（跨族平均会掩盖某个族整批不可用）。"""
    per: dict[str, list[int]] = {}
    for r in rows:
        c = per.setdefault(r.family, [0, 0])
        for m in metrics:
            c[0] += 1
            if not _rows_rankable(r, m)[0]:
                c[1] += 1
    return {f: (c[1] / c[0] if c[0] else 0.0) for f, c in sorted(per.items())}


def _sort_key(v: float, direction: str) -> float:
    return -float(v) if direction == "max" else float(v)


def rank_rows(rows: Sequence[Row], metrics: Sequence[MetricSpec], *,
              top_n: int = 10) -> tuple[list[dict], list[dict], dict]:
    """按 `(family, metric)` 排名，并逐条单列被排除的条目。"""
    rankings: list[dict] = []
    excluded: list[dict] = []
    flag_counts: dict[str, int] = {}
    families = sorted({r.family for r in rows if r.family})
    for fam in families:
        fam_rows = [r for r in rows if r.family == fam]
        for m in metrics:
            kept, dropped = [], []
            for r in fam_rows:
                ok, reasons = _rows_rankable(r, m)
                if ok:
                    kept.append(r)
                else:
                    dropped.append((r, reasons))
                    for x in reasons:
                        flag_counts[x] = flag_counts.get(x, 0) + 1
                    excluded.append({
                        "family": fam, "metric": m.name, "params": dict(r.params),
                        "reasons": reasons,
                        "flags": sorted(r.flags),
                        "source_run_id": r.source_run_id,
                    })
            kept.sort(key=lambda r: (_sort_key(r.values[m.name], m.direction),
                                     json.dumps(r.params, sort_keys=True, default=str)))
            top = []
            for i, r in enumerate(kept[:top_n], start=1):
                advisory = sorted(f for f in r.flags if f in m.advisory_flags)
                top.append({"rank": i, "params": dict(r.params), "value": r.values[m.name],
                            "advisory_flags": advisory,
                            "source_run_id": r.source_run_id})
            rankings.append({
                "family": fam, "families": [fam], "metric": m.name, "label": m.label,
                "unit": m.unit, "caliber": m.caliber, "direction": m.direction,
                "n_available": len(kept), "n_excluded": len(dropped),
                "n_ranked": len(top),
                "provisional": any(t["advisory_flags"] for t in top),
                "top": top,
            })
    return rankings, excluded, flag_counts


def _dominates(a: dict, b: dict, metrics: Sequence[MetricSpec]) -> bool:
    """a 是否支配 b（全部指标不劣于，且至少一个严格更优）。

    入参形如 ``{"params": {...}, "values": {metric: float}}``。
    """
    better = False
    for m in metrics:
        va, vb = a["values"][m.name], b["values"][m.name]
        if m.direction == "max":
            if va < vb:
                return False
            better = better or (va > vb)
        else:
            if va > vb:
                return False
            better = better or (va < vb)
    return better


def pareto_front(rows: Sequence[Row], metrics: Sequence[MetricSpec],
                 *, all_metrics: Sequence[MetricSpec] | None = None
                 ) -> tuple[list[dict], dict]:
    """分族 Pareto 非支配集。

    **参与者资格**：在 `metrics`（Pareto 参与指标）以及 `all_metrics`（本批**全部**已声明指标，
    缺省等于 `metrics`）上都未被排除。A8 红队指出：只按参与子集判可比，会让"在别的指标上被
    质量门排除的点"照样进前沿——所以默认要求**全指标干净**才进前沿。
    """
    gate_metrics = list(all_metrics if all_metrics is not None else metrics)
    out: list[dict] = []
    stats: dict[str, dict] = {}
    for fam in sorted({r.family for r in rows if r.family}):
        fam_rows = [r for r in rows if r.family == fam]
        usable = [r for r in fam_rows if all(_rows_rankable(r, m)[0] for m in gate_metrics)]
        dropped = len(fam_rows) - len(usable)
        pts = [{"params": dict(r.params), "values": {m.name: r.values[m.name] for m in metrics}}
               for r in usable]
        front = [p for p in pts
                 if not any(_dominates(q, p, metrics) for q in pts if q is not p)]
        out.append({"family": fam, "metrics": [m.name for m in metrics],
                    "gate_metrics": [m.name for m in gate_metrics],
                    "directions": {m.name: m.direction for m in metrics},
                    "n_considered": len(usable), "n_dropped_incomparable": dropped,
                    "n_front": len(front), "members": front})
        stats[fam] = {"n_considered": len(usable), "n_front": len(front),
                      "n_dropped_incomparable": dropped}
    return out, stats


# ---------------------------------------------------------------------------
# 汇总分析
# ---------------------------------------------------------------------------
NOT_CHECKED_BASE = [
    "未做任何 COMSOL 求解或复算（A5 只读数据，不触发求解）",
    "未做几何/选择集实体预检（是否 `clean` 由 A2/A3 的预检产物决定；缺预检 ⇒ 排名降级为临时）",
    "未评估代理模型/场求解器的误差界（那是 A6/A7 的职责）",
    "未做测量不确定度传播（数据本身若无可信误差边界，排名只能谈次序）",
]


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CLEAN_CLASSES = ("clean", "ok")


def parse_precheck(precheck: Any) -> tuple[dict[str, str], str]:
    """把预检产物解析成 `{组合键: 分类}`；无法解析 ⇒ 返回 ({}, 原因)。

    为什么要这么严：A8 红队实测「给个空预检 `{}` + 任意 sha 字符串就能拿到
    `ranked` + `release_allowed=true`」——**声明存在但内容为空**的预检等于没有预检。
    组合键接受 `"<family>|<x_scale>"`、`"<x_scale>"`、`"<x_scale>|<N_w_te1>"` 等形式。
    """
    if precheck is None:
        return {}, "未提供"
    if not isinstance(precheck, dict) or not precheck:
        return {}, "不是非空 dict"
    cls = precheck.get("classification") or precheck.get("classes") or precheck.get("combos")
    if not isinstance(cls, dict) or not cls:
        return {}, "缺 classification/classes/combos 或为空"
    out: dict[str, str] = {}
    for k, v in cls.items():
        if isinstance(v, dict):
            v = v.get("class") or v.get("classification") or v.get("status") or ""
        out[str(k)] = str(v)
    return out, ""


def _precheck_key(row: Row) -> list[str]:
    fam = row.family
    xs = row.params.get("x_scale")
    n1 = row.params.get("N_w_te1")
    keys = ["%s|%s" % (fam, xs), str(xs)]
    if xs is not None and n1 is not None:
        keys.append("%s|%s" % (xs, n1))
        keys.append("%s|%s|%s" % (fam, xs, n1))
    return keys


def apply_precheck(rows: Sequence[Row], cls: Mapping[str, str]) -> int:
    """把非 clean 的预检分类落到行上（`precheck_not_clean` 全局取消资格）。返回命中行数。"""
    n = 0
    for r in rows:
        hit = None
        for k in _precheck_key(r):
            if k in cls:
                hit = cls[k]
                break
        if hit is not None and str(hit).strip().lower() not in CLEAN_CLASSES:
            r.flags.add("precheck_not_clean")
            n += 1
    return n


def analyze(
    rows: Sequence[Row],
    metrics: Sequence[MetricSpec],
    *,
    top_n: int = 10,
    min_effective: int = 5,
    max_exclusion_rate: float = 0.5,
    model_sha256: str | None = None,
    precheck: dict | None = None,
    caliber_approved: bool = True,
    rows_path: str | None = None,
    rows_sha256: str | None = None,
    pareto_metrics: Sequence[str] | None = None,
    script_sha256: str | None = None,
) -> dict:
    """产出 `scan_analysis` 判定文档（fail-closed）。

    参数
    ----
    caliber_approved : A1 是否已批准该口径。未批准 ⇒ `inconclusive`（停止条件之一）。
    precheck : A2/A3 的几何/选择集预检产物。**必须可解析且非空**；缺省或空 ⇒ 排名降级为临时。
               可解析时，非 clean 的组合会被**全局取消排名资格**（不只是标个提示）。
    model_sha256 : 被扫模型的哈希，**必须是 64 位十六进制**；否则视同未提供（临时）。
    """
    # ① 预检必须在"算排名之前"生效，否则非 clean 的点已经进了排名
    cls, precheck_problem = parse_precheck(precheck)
    n_precheck_not_clean = apply_precheck(rows, cls) if cls else 0

    checks: list[CheckResult] = []
    c = check_input_nonempty(rows)
    checks.append(c)
    checks.append(check_family_label_present(rows))
    checks.append(check_caliber_declared(metrics))
    checks.append(check_caliber_consistency(metrics))
    ce, _ = check_effective_points(rows, metrics, min_effective=min_effective)
    checks.extend(ce)
    checks.extend(check_exclusion_rate(rows, metrics, max_rate=max_exclusion_rate))

    rankings, excluded, flag_counts = rank_rows(rows, metrics, top_n=top_n)
    pm = [m for m in metrics if (pareto_metrics is None or m.name in set(pareto_metrics))]
    pareto, pareto_stats = (pareto_front(rows, pm, all_metrics=metrics) if pm else ([], {}))
    checks.append(check_cross_family_isolation(rankings))
    checks.append(check_no_cross_family_duplicate_points(rows))

    # 逐行记录「该行在哪些指标上被排除」，便于 A9 单列而不静默丢弃
    measured: list[dict] = []
    for r in rows:
        d = r.to_dict()
        if any(v is None for v in r.values.values()):
            d["flags"] = sorted(set(d["flags"]) | {"missing_value"})
        d["excluded_for"] = [m.name for m in metrics if not _rows_rankable(r, m)[0]]
        measured.append(d)

    provisional_reasons: list[str] = []
    hash_ok = bool(model_sha256 and SHA256_RE.match(str(model_sha256).strip().lower()))
    if model_sha256 is None:
        provisional_reasons.append("未提供被扫模型 sha256 ⇒ 该批**禁止与其它批合并排名/统计**")
    elif not hash_ok:
        provisional_reasons.append("model_sha256 不是 64 位十六进制（%r）⇒ 视同未提供，"
                                   "该批禁止与其它批合并" % str(model_sha256)[:32])
    precheck_used = bool(cls)
    if not precheck_used:
        provisional_reasons.append(
            "几何/选择集预检**不可用**（%s）⇒ 排名为**临时**（可能含选择集张冠李戴的点）"
            % (precheck_problem or "空"))
    if n_precheck_not_clean:
        provisional_reasons.append(
            "预检判定 **%d 个组合非 clean** ⇒ 这些组合已被全局取消排名资格（不只标提示）"
            % n_precheck_not_clean)
    provisional = bool(provisional_reasons)

    payload_for_guard = {"rankings": rankings, "pareto": pareto,
                         "quality": {"excluded": excluded, "flag_counts": flag_counts},
                         "measured": measured}
    checks.append(check_no_composite_score(payload_for_guard, metrics))

    verdict = dict(evaluate_s3(checks))
    status = {"passed": ("provisional" if provisional else "ranked"),
              "failed": "failed", "inconclusive": "inconclusive"}[verdict["verdict"]]
    # 停止条件 = 任何"未通过"或"无法判定"且有说明的检查项
    stop_reasons = [c2.reason for c2 in checks if c2.passed is not True and c2.reason]
    if not caliber_approved:
        status = "inconclusive"
        stop_reasons.append("A1 口径未批准 ⇒ 不得出排名结论（停止条件）")

    n_cells = len(rows) * len(metrics)
    n_excl = sum(1 for r in rows for m in metrics if not _rows_rankable(r, m)[0])
    verdict_by_family, released_families = _verdict_by_family(
        checks, rows, provisional=provisional, caliber_approved=caliber_approved)
    if status == "failed":
        # 硬违规批次**不给下游任何可用结论**：逐族判定照实记录，但 released_families 必须为空
        released_families = []
    doc = {
        "kind": "scan_analysis",
        "sweep_version": SWEEP_VERSION,
        "verdict": status,
        "release_allowed": bool(status == "ranked"),
        "verdict_by_family": verdict_by_family,
        "released_families": released_families,
        "provisional": provisional,
        "provisional_reasons": provisional_reasons,
        "stop_reasons": stop_reasons,
        "input": {
            "rows_path": rows_path, "rows_sha256": rows_sha256,
            "n_rows": len(rows), "n_families": len({r.family for r in rows if r.family}),
            "families": sorted({r.family for r in rows if r.family}),
            "model_sha256": model_sha256,
            "precheck_provided": precheck is not None,
            "caliber_approved": bool(caliber_approved),
            "script_sha256": script_sha256,
        },
        "calibers": {m.name: m.to_dict() for m in metrics},
        "quality": {
            "n_rows": len(rows), "n_cells": n_cells, "n_excluded_cells": n_excl,
            "exclusion_rate": (n_excl / n_cells) if n_cells else None,
            "exclusion_rate_by_family": _exclusion_by_family(rows, metrics),
            "n_excluded_rows": len({(e["family"], json.dumps(e["params"], sort_keys=True))
                                    for e in excluded}),
            "flag_counts": dict(sorted(flag_counts.items())),
            "excluded": excluded,
        },
        "rankings": rankings,
        "pareto": pareto,
        "pareto_stats": pareto_stats,
        "measured": measured,
        "precheck": {
            "used": precheck_used,
            "problem": precheck_problem or None,
            "n_combos_classified": len(cls),
            "n_not_clean": n_precheck_not_clean,
            "clean_classes": list(CLEAN_CLASSES),
            "global_exclude_flags": sorted(GLOBAL_EXCLUDE_FLAGS),
            "note": ("非 clean 组合被**全局取消排名资格**（`precheck_not_clean`），"
                     "不只是标提示；预检不可用（缺省/空/无法解析）⇒ 排名降级为临时"),
        },
        "checks": verdict["checks"],
        "n_checks": verdict["n_checks"], "n_failed": verdict["n_failed"],
        "n_inconclusive": verdict["n_inconclusive"], "reason": verdict["reason"],
        "no_composite_score": True,
        "not_checked": list(NOT_CHECKED_BASE) + (
            ["未做多批并排比较（只分析了单批；跨批比较必须并排且各带 model_sha256）"]),
        "semantics": (
            "fail-closed：任一检查 False ⇒ verdict=failed；任一 None（无法判定）⇒ "
            "verdict=inconclusive 且 release_allowed=False；空输入判 failed。"
            "verdict=ranked 仅表示『该批排名可用于下游决策』，**不表示模型状态可升级**"
            "（红线 §5：放行权在人）；模型哈希非 64 位十六进制、或预检缺失/为空/无法解析 ⇒ "
            "自动降级为 provisional，此时 release_allowed=False。"
            "排名一律按 (family, metric) 分组，**禁止跨族合并**；"
            "被质量门排除的条目逐条列在 quality.excluded，**不静默丢弃**。"
            "几何无效/网格无效/退化几何/预检非 clean 属**全局取消资格**（任何指标都不参与）。"
            "多族批次另给 verdict_by_family 与 released_families：某族可用不代表整批已放行，"
            "而**全局性违规会下调所有族**。"),
    }
    return doc


# ---------------------------------------------------------------------------
# 下一批选点建议
# ---------------------------------------------------------------------------
ROLE_PRIORITY = {"quality_repair": 0, "baseline_refine": 1, "contrast": 2}


def _param_step_key(params: Mapping[str, Any]) -> str:
    return json.dumps({k: _num(v) for k, v in params.items()}, sort_keys=True, default=str)


def _grid_ranks(rows: Sequence[Mapping[str, Any]],
                keys: Sequence[str]) -> dict[str, tuple[list[float], float]]:
    """每个参数键 → (已声明网格坐标, 中位步长)。

    距离按**格数**算（不是"有几个键不同"）：实测踩坑——把"有 1 个键不同"当成相邻，
    会让 (0.45, N1=4) 被判为 (0.80, N1=4) 的"相邻格点"，从而给出无依据的细化建议。
    """
    out: dict[str, tuple[list[float], float]] = {}
    for k in keys:
        vals = sorted({float(r["params"][k]) for r in rows
                       if isinstance(r.get("params", {}).get(k), (int, float))})
        if not vals:
            continue
        diffs = [b - a for a, b in zip(vals, vals[1:]) if b > a]
        step = min(diffs) if diffs else 1.0
        out[k] = (vals, step)
    return out


def _rank_of(v: Any, coords: Sequence[float], step: float) -> float | None:
    if not isinstance(v, (int, float)):
        return None
    v = float(v)
    if v in coords:
        return float(coords.index(v))
    if v < coords[0]:
        return (v - coords[0]) / step
    if v > coords[-1]:
        return (len(coords) - 1) + (v - coords[-1]) / step
    # 落在网格内部但不在某个刻度上：线性插值给出小数格号
    for a, b in zip(coords, coords[1:]):
        if a < v < b:
            return coords.index(a) + (v - a) / (b - a)
    return None


def _dist(a: Mapping[str, Any], b: Mapping[str, Any], keys: Sequence[str],
          ranks: Mapping[str, tuple[list[float], float]] | None = None) -> float:
    """两个参数组合之间相差**几格**（按已声明网格坐标与步长）。

    未提供 `ranks` 时退化为"有差异的键数"（仅用于无网格信息的粗略判断）。
    """
    if ranks is None:
        n = 0
        for k in keys:
            va, vb = a.get(k), b.get(k)
            if va is None or vb is None:
                continue
            if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                if abs(float(va) - float(vb)) > 1e-12:
                    n += 1
            elif str(va) != str(vb):
                n += 1
        return float(n)
    total = 0.0
    for k in keys:
        if k not in ranks:
            continue
        coords, step = ranks[k]
        ra, rb = _rank_of(a.get(k), coords, step), _rank_of(b.get(k), coords, step)
        if ra is None or rb is None:
            if str(a.get(k)) != str(b.get(k)):
                total += 1.0
            continue
        total += abs(ra - rb)
    return total


def build_next_batch(
    scan: dict,
    *,
    candidate_grid: Sequence[Mapping[str, Any]],
    budget: int = 6,
    param_keys: Sequence[str] = ("x_scale", "N_w_te1"),
    per_point_cost_s: float | None = None,
    primary_metric: str | None = None,
) -> dict:
    """产出 `next_batch`：**只在已声明网格上**、**必须有实测邻居作依据**的选点建议。

    禁止事项（红线 + SOP）：**不得无依据地插值/外推**——每个建议必须有同族实测邻居；
    若候选落在实测范围**外侧一格**，则必须存在"最优点 + 同轴对侧实测点"给出的局部差分，
    并在 `expected_gain.extrapolates_beyond_measured_range=true` **显式披露**
    （A8 红队指出：模块文档曾笼统写"不得外推"，与"有依据的一格外推会被选中"的行为不一致，
    这里改为如实描述实际规则）。不得给无依据的"预期收益"；
    不得在 A8 未放行或 A5 判 inconclusive/failed 时仍给建议。
    每个建议必须带：`role` / `reason` / `expected_gain`（含依据与邻居 id）/ `cost` / `stop_condition`。
    """
    metrics = [MetricSpec(**{k: v for k, v in c.items() if k in MetricSpec.__dataclass_fields__})
               for c in scan.get("calibers", {}).values()]
    if primary_metric is None and metrics:
        primary_metric = metrics[0].name
    if primary_metric is None:
        return _blocked_next_batch(scan, ["分析文档未声明任何指标口径 ⇒ 无法给选点建议"])

    measured_rows = scan.get("measured", [])
    measured_by_key = {(_param_step_key(r["params"]), r["family"]): r for r in measured_rows}
    # 每族的"已声明网格坐标 + 最小步长"：坐标 = 实测值 ∪ 候选值（候选网格定义步长，
    # 否则某族在某键上只有 1 个实测值时步长无从推断，相邻关系会判错）
    cand_by_family: dict[str, list[dict]] = {}
    for cand in candidate_grid:
        fam = str(cand.get("family") or "")
        cand_by_family.setdefault(fam, []).append(
            {"params": {k: _num(cand.get(k)) for k in param_keys}})
    ranks_by_family = {
        fam: _grid_ranks([r for r in measured_rows if r["family"] == fam]
                         + cand_by_family.get(fam, []), param_keys)
        for fam in {r["family"] for r in measured_rows} | set(cand_by_family)}
    # 每个 (族, 指标) 的最优点
    best: dict[tuple[str, str], dict] = {}
    for rk in scan.get("rankings", []):
        if rk["top"]:
            best[(rk["family"], rk["metric"])] = rk["top"][0]

    stop_conditions: list[str] = []
    if scan.get("verdict") in ("failed", "inconclusive"):
        stop_conditions.append("A5 判定为 %s ⇒ 该批不足以选点（先补数据/补口径）"
                               % scan.get("verdict"))
    stop_conditions.extend(scan.get("stop_reasons", []))

    selected: list[dict] = []
    rejected: list[dict] = []
    if stop_conditions:
        return _blocked_next_batch(scan, stop_conditions)

    # 质量修复目标：主指标上被质量门排除的**首个**实测点（例如稀疏频点 ⇒ 峰值只是下界）
    repair_targets: dict[str, str] = {}
    for e in scan.get("quality", {}).get("excluded", []):
        if e["metric"] == primary_metric and e["family"] not in repair_targets:
            repair_targets[e["family"]] = _param_step_key(e["params"])

    seen: set[str] = set()
    for cand in candidate_grid:
        fam = str(cand.get("family") or "")
        params = {k: cand.get(k) for k in param_keys}
        cid = _param_step_key(params)
        if not fam:
            rejected.append({"candidate": dict(cand), "reason": "候选点缺族标签"})
            continue
        is_repair = (repair_targets.get(fam) == cid)
        if (cid, fam) in measured_by_key and not is_repair:
            rejected.append({"candidate": dict(cand), "reason": "already_measured"})
            continue
        if cid in seen:
            rejected.append({"candidate": dict(cand), "reason": "duplicate_candidate"})
            continue
        # 同族实测点（用于邻居/一阶差分依据）
        fam_measured = [r for r in measured_rows if r["family"] == fam]
        if not fam_measured:
            rejected.append({"candidate": dict(cand),
                             "reason": "no_measured_in_family：该族无实测点，任何建议都只能是外推"})
            continue
        neighbours = [r for r in fam_measured
                      if _param_step_key(r["params"]) != cid
                      and _dist(r["params"], params, param_keys, ranks_by_family.get(fam)) == 1]
        if not neighbours and not is_repair:
            # 质量修复目标本身就是已测点，不需要邻居：它的依据是**排除原因**而非数值外推
            rejected.append({"candidate": dict(cand),
                             "reason": "no_measured_neighbour：在已声明网格上找不到实测邻居"
                                       "（禁止插值/外推选点）"})
            continue

        chosen = None
        for role in ("quality_repair", "baseline_refine", "contrast"):
            if role == "quality_repair":
                # 触发条件：主指标最优点在本批被质量门排除（例如稀疏频点 ⇒ 峰值只是下界）
                excl = [e for e in scan.get("quality", {}).get("excluded", [])
                        if e["family"] == fam and e["metric"] == primary_metric]
                if not excl:
                    continue
                tgt = excl[0]
                if _param_step_key(tgt["params"]) != cid:
                    continue
                chosen = {
                    "role": role,
                    "reason": "本批主指标最优点被质量门排除（%s）⇒ 该点**修质量**而不是换点："
                              "加密频点/核实驱动口径后重扫" % ("; ".join(tgt["reasons"])),
                    "expected_gain": {
                        "metric": primary_metric,
                        "basis": "quality_repair（依据是排除原因本身，不是数值外推）",
                        "neighbour_ids": [],
                        "observed_delta": None,
                        "note": "收益是**可判定性**（把下界变成可判定峰值），不是预测数值",
                    },
                }
            elif role == "baseline_refine":
                b = best.get((fam, primary_metric))
                ranks = ranks_by_family.get(fam)
                if b is None or _dist(b["params"], params, param_keys, ranks) != 1:
                    continue
                # 差在哪个键上（相邻只可能差一个键）
                diff_keys = [k for k in param_keys
                             if _rank_of(params.get(k), *ranks[k]) !=
                             _rank_of(b["params"].get(k), *ranks[k])] if ranks else []
                # 依据 = 最优点 B 在**同一键**上"对侧"的那个实测邻居 B2 ⇒ 一阶差分幅度
                b2 = None
                for k in diff_keys:
                    for r in fam_measured:
                        if r["params"] == b["params"]:
                            continue
                        if _dist(b["params"], r["params"], param_keys, ranks) != 1:
                            continue
                        # 必须在 k 上不同（即 B 的另一侧），且确实在对面（非候选同侧）
                        if _rank_of(r["params"].get(k), *ranks[k]) == \
                                _rank_of(b["params"].get(k), *ranks[k]):
                            continue
                        same_side = (_rank_of(r["params"].get(k), *ranks[k]) -
                                     _rank_of(b["params"].get(k), *ranks[k])) * \
                                    (_rank_of(params.get(k), *ranks[k]) -
                                     _rank_of(b["params"].get(k), *ranks[k])) > 0
                        if same_side:
                            continue
                        b2 = r
                        break
                    if b2 is not None:
                        break
                val_b = b["value"]
                if b2 is None or b2["values"].get(primary_metric) is None:
                    rejected.append({
                        "candidate": dict(cand),
                        "reason": "would_extrapolate_without_measured_slope：该候选只在已测范围的"
                                  "**外侧一格**，但没有对侧实测点给出局部差分 ⇒ 无依据，不选"})
                    continue
                val_b2 = b2["values"][primary_metric]
                delta = abs(float(val_b) - float(val_b2))
                outside = _rank_of(params.get(diff_keys[0]), *ranks[diff_keys[0]]) > \
                    _rank_of(b["params"].get(diff_keys[0]), *ranks[diff_keys[0]]) if diff_keys else False
                chosen = {
                    "role": role,
                    "reason": "主指标 %s 最优点 B=%s 的相邻格点；B 与同轴对侧实测点 B2=%s "
                              "构成一阶差分，用于判断该方向是否仍在上升/下降"
                              % (primary_metric,
                                 json.dumps(b["params"], ensure_ascii=False),
                                 json.dumps(b2["params"], ensure_ascii=False)),
                    "expected_gain": {
                        "metric": primary_metric,
                        "basis": "first_difference_along_grid（B 与对侧实测点 B2 的差分幅度）",
                        "neighbour_ids": [b.get("source_run_id"), b2.get("source_run_id")],
                        "neighbour_params": [b["params"], b2["params"]],
                        "observed_delta": delta,
                        "extrapolates_beyond_measured_range": bool(outside),
                        "note": "只给「该方向的变化幅度」，**不预测符号**（不得凭空外推）",
                    },
                }
            else:  # contrast
                others = [rk for rk in scan.get("rankings", [])
                          if rk["family"] == fam and rk["metric"] != primary_metric and rk["top"]]
                if not others:
                    continue
                b = best.get((fam, primary_metric))
                if b is None or _dist(b["params"], params, param_keys,
                                      ranks_by_family.get(fam)) < 2:
                    continue
                v0 = neighbours[0]["values"].get(others[0]["metric"])
                v1 = neighbours[0]["values"].get(primary_metric)
                if v0 is None or v1 is None:
                    continue
                chosen = {
                    "role": role,
                    "reason": "与主指标最优点参数距离 ≥2 格，且与实测点相邻 ⇒ 用于**对照**"
                              "（检验另一指标 %s 是否真的反向）" % others[0]["metric"],
                    "expected_gain": {
                        "metric": others[0]["metric"],
                        "basis": "contrast_on_measured_neighbour（邻居实测值，不做外推）",
                        "neighbour_ids": [neighbours[0]["source_run_id"]],
                        "neighbour_params": [neighbours[0]["params"]],
                        "observed_delta": abs(float(v0)),
                        "extrapolates_beyond_measured_range": False,
                        "note": "目的是分辨目标冲突（Pareto 形状），不是预测新数值",
                    },
                }
            if chosen:
                break
        if chosen is None:
            rejected.append({"candidate": dict(cand),
                             "reason": "not_top_quartile_or_no_contrast_basis：不满足任何选点角色"
                                       "（基准细化/对照/质量修复）"})
            continue

        n_freq = int(cand.get("n_freq_points") or 1)
        chosen.update({
            "family": fam, "params": {k: _num(v) for k, v in params.items()},
            "grid_steps_from_best": _dist(best.get((fam, primary_metric), {}).get("params", {}),
                                          params, param_keys, ranks_by_family.get(fam))
            if best.get((fam, primary_metric)) else None,
            "cost": {"n_solves": 1, "n_freq_points": n_freq,
                     "est_wall_seconds": (per_point_cost_s * n_freq / 1.0
                                          if per_point_cost_s else None)},
            "stop_condition": _stop_condition(chosen, scan, primary_metric),
            "priority": ROLE_PRIORITY[chosen["role"]],
        })
        selected.append(chosen)
        seen.add(cid)

    selected.sort(key=lambda s: (s["priority"],
                                 -(s["expected_gain"].get("observed_delta") or 0.0)))
    over = selected[budget:]
    for s in over:
        rejected.append({"candidate": {"family": s["family"], **s["params"]},
                         "reason": "budget_exhausted"})
    selected = selected[:budget]

    n_solves = sum(s["cost"]["n_solves"] for s in selected)
    est = [s["cost"]["est_wall_seconds"] for s in selected if s["cost"]["est_wall_seconds"]]
    provisional = bool(scan.get("provisional"))
    if provisional and selected:
        stop_conditions.append("上游排名为**临时**（%s）⇒ 建议可沿用，但必须在 A3 补预检后复核"
                               % "；".join(scan.get("provisional_reasons", [])))
    doc = {
        "kind": "next_batch",
        "sweep_version": SWEEP_VERSION,
        "source_scan": {"verdict": scan.get("verdict"),
                        "rows_sha256": (scan.get("input") or {}).get("rows_sha256"),
                        "model_sha256": (scan.get("input") or {}).get("model_sha256")},
        "verdict": "proposed" if selected else "blocked",
        "blocked": not selected,
        "provisional": provisional,
        "stop_conditions": stop_conditions,
        "budget": {"max_points": int(budget), "n_selected": len(selected),
                   "n_rejected": len(rejected), "n_solves": n_solves,
                   "est_wall_seconds": (sum(est) if est else None),
                   "per_point_cost_s": per_point_cost_s},
        "selected": selected,
        "rejected": rejected,
        "release_allowed": bool(selected) and not provisional,
        "not_checked": [
            "本模块**不触发**任何求解（建议点须经 A3 排队执行）",
            "未估计预算内的总内存/许可占用（须在 A3 提交前核）",
            "未做实验设计的最优性证明（DOE/LHS/贝叶斯仅为候选策略，未比较）",
        ],
        "no_composite_score": True,
        "semantics": (
            "选点只在**已声明候选网格**上进行，且每个建议必须有同族**实测邻居**作依据；"
            "无邻居 ⇒ 进 rejected（禁止插值/外推）。expected_gain 给的是实测一阶差分**幅度**，"
            "不预测符号。A5 判定 failed/inconclusive 或存在 stop_reasons ⇒ verdict=blocked、"
            "selected 为空（空集不得当作『没有问题』）；上游排名为临时 ⇒ 建议可以给出但 "
            "release_allowed=False（先补预检再执行）。"),
    }
    # A8 红队实测：合成总分守卫只扫了 scan_analysis，没扫 next_batch ⇒ 总分字段可原样进产物。
    # 这里对自己产出的结构做同一套守卫（发现即抛错，不静默输出）。
    guard = check_no_composite_score(doc, metrics)
    if guard.passed is not True:
        raise ValueError("next_batch 输出命中合成总分守卫：%r" % guard.detail.get("hits"))
    return doc


def _stop_condition(s: dict, scan: dict, primary_metric: str | None) -> str:
    d = s["expected_gain"].get("observed_delta")
    if s["role"] == "quality_repair":
        return ("若加密频点/核实驱动后该点仍被质量门排除，或主指标变化 <5%，"
                "则停止在该点继续投入（改换参数方向）")
    if d:
        return ("若该方向一阶差分幅度 <5%%（当前 %.3g）或 %s 的最优参数在 2 格内出现反复，"
                "则停止细化（说明该方向已近平坦）" % (0.05 * abs(d), primary_metric))
    return "若本批新增点未改变前 3 名次序，则停止在该族继续扫描"


def _blocked_next_batch(scan: dict, reasons: Sequence[str]) -> dict:
    return {
        "kind": "next_batch", "sweep_version": SWEEP_VERSION,
        "source_scan": {"verdict": scan.get("verdict"),
                        "rows_sha256": (scan.get("input") or {}).get("rows_sha256"),
                        "model_sha256": (scan.get("input") or {}).get("model_sha256")},
        "verdict": "blocked", "blocked": True, "provisional": bool(scan.get("provisional")),
        "stop_conditions": [r for r in reasons if r],
        "budget": {"max_points": 0, "n_selected": 0, "n_rejected": 0, "n_solves": 0,
                   "est_wall_seconds": None, "per_point_cost_s": None},
        "selected": [], "rejected": [],
        "release_allowed": False,
        "not_checked": ["因上游未放行，未做任何选点分析"],
        "semantics": ("上游判定不允许选点（failed/inconclusive 或存在 stop_reasons）⇒ "
                      "selected 为空且 release_allowed=False；空集不得被读成『无需补数据』。"),
    }


# ---------------------------------------------------------------------------
# 人读层
# ---------------------------------------------------------------------------
def render_md(scan: dict) -> str:
    L = ["# A5 扫描分析 —— 分指标排名（不含总分）", "",
         "- 判定：**%s**（release_allowed=%s；provisional=%s）"
         % (scan["verdict"], scan["release_allowed"], scan["provisional"]),
         "- 输入：%d 行 / %d 族；rows_sha256=%s"
         % (scan["input"]["n_rows"], scan["input"]["n_families"],
            str(scan["input"]["rows_sha256"])[:16] or "（未提供）"),
         "- 版本：%s；脚本 sha256=%s" % (scan["sweep_version"],
                                        str(scan["input"]["script_sha256"])[:16] or "（未提供）"),
         ""]
    if scan["stop_reasons"]:
        L += ["## 停止条件（出现即不出结论）", ""]
        L += ["- %s" % r for r in scan["stop_reasons"]] + [""]
    if scan["provisional_reasons"]:
        L += ["## 临时性声明（该批不可与其它批合并比较）", ""]
        L += ["- %s" % r for r in scan["provisional_reasons"]] + [""]
    if scan.get("verdict_by_family"):
        L += ["## 逐族判定（某族可用 ≠ 整批已放行）", "",
              "| 族 | 判定 |", "|---|---|"]
        for fam, v in scan["verdict_by_family"].items():
            L.append("| %s | %s |" % (fam, v))
        L += ["", "- 逐族可放行的族：%s"
              % (", ".join("`%s`" % f for f in scan.get("released_families", [])) or "（无）"), ""]
    L += ["## 逐指标排名（按族分开；幅值 20log10 / 功率 10log10 不得混用）", "",
          "| 族 | 指标 | 口径 | 方向 | 有效 | 排除 | 榜首参数 | 值 | 单位 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for rk in scan["rankings"]:
        top = rk["top"][0] if rk["top"] else None
        L.append("| %s | `%s` | %s | %s | %d | %d | %s | %s | %s |" % (
            rk["family"], rk["metric"], rk["caliber"], rk["direction"],
            rk["n_available"], rk["n_excluded"],
            (json.dumps(top["params"], ensure_ascii=False) if top else "—"),
            ("%.6g" % top["value"]) if top else "—", rk["unit"]))
    L += ["", "## Pareto 非支配集", "",
          "| 族 | 参与指标 | 参与点 | 前沿点数 | 因指标不可比而剔除 |", "|---|---|---|---|---|"]
    for p in scan["pareto"]:
        L.append("| %s | %s | %d | %d | %d |" % (
            p["family"], ", ".join("`%s`" % m for m in p["metrics"]),
            p["n_considered"], p["n_front"], p["n_dropped_incomparable"]))
    q = scan["quality"]
    L += ["", "## 质量门单列（不进排名，不静默丢弃）", "",
          "- 单元总数 %d；被排除 %d（%.1f%%）" % (
              q["n_cells"], q["n_excluded_cells"],
              100 * (q["exclusion_rate"] or 0.0)), ""]
    if q["flag_counts"]:
        L += ["| 排除原因 | 次数 |", "|---|---|"]
        L += ["| `%s` | %d |" % (k, v) for k, v in q["flag_counts"].items()]
    L += ["", "## 本次**没有**检查的项（不得读成「查过且通过」）", ""]
    L += ["- %s" % x for x in scan["not_checked"]]
    L += ["", "## 判定语义", "", "```text", scan["semantics"], "```", ""]
    return "\n".join(L) + "\n"


def render_next_batch_md(nb: dict) -> str:
    L = ["# A5 下一批选点建议", "",
         "- 判定：**%s**（release_allowed=%s）" % (nb["verdict"], nb["release_allowed"]),
         "- 预算：最多 %d 点；已选 %d 点 / %d 次求解"
         % (nb["budget"]["max_points"], nb["budget"]["n_selected"], nb["budget"]["n_solves"]),
         ""]
    if nb["stop_conditions"]:
        L += ["## 停止条件", ""] + ["- %s" % s for s in nb["stop_conditions"]] + [""]
    if nb["selected"]:
        L += ["| 角色 | 族 | 参数 | 依据 | 一阶差分幅度 | 成本(求解/频点) | 停止条件 |",
              "|---|---|---|---|---|---|---|"]
        for s in nb["selected"]:
            eg = s["expected_gain"]
            L.append("| %s | %s | %s | %s | %s | %d / %d | %s |" % (
                s["role"], s["family"], json.dumps(s["params"], ensure_ascii=False),
                eg["basis"], ("%.4g" % eg["observed_delta"]) if eg.get("observed_delta") else "—",
                s["cost"]["n_solves"], s["cost"]["n_freq_points"],
                s["stop_condition"][:60]))
    else:
        L += ["**未给出任何建议点**（空集不得读成「无需补数据」）。", ""]
    if nb["rejected"]:
        L += ["", "## 被拒候选（逐条给理由）", "", "| 候选 | 理由 |", "|---|---|"]
        L += ["| %s | `%s` |" % (json.dumps(r["candidate"], ensure_ascii=False),
                                 r["reason"]) for r in nb["rejected"][:40]]
    L += ["", "## 本次**没有**做的", ""] + ["- %s" % x for x in nb["not_checked"]]
    return "\n".join(L) + "\n"
