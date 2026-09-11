"""报告与出图（A10）：面向**组会/论文可直接使用**的产物。

设计要点：
1. **每个数字可回溯**：证据表把报告里出现的数值与其来源（run_id / design_id / sample_id、
   来源类型、保真度、抽取器版本）逐行绑定；报告正文不出现无出处的数字。
2. **图必须自带口径**：坐标轴单位、样本量、阈值线（如 S1 的 5%）与不确定度区间都画进图里，
   避免"图好看但读者不知道它说了什么"。
3. **中文可显示**：显式设置 CJK 字体，否则中文标签会变成方框（论文/组会不可接受）。
4. 不依赖 COMSOL：输入是已入库的数据与已算好的数组，因此可离线复现。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .paths import work_root

# 中文字体（Windows 自带）；最后兜底 DejaVu Sans，避免缺字直接报错
_CJK_FONTS = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]


def _setup_matplotlib():
    import matplotlib

    matplotlib.use("Agg")  # 无界面环境
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = _CJK_FONTS
    plt.rcParams["axes.unicode_minus"] = False   # 负号显示
    plt.rcParams["figure.dpi"] = 130
    plt.rcParams["savefig.bbox"] = "tight"
    return plt


def figures_dir(prefix: str) -> Path:
    target = work_root() / "reports" / prefix / "figures"
    target.mkdir(parents=True, exist_ok=True)
    return target


# ---------------------------------------------------------------------------------------
# 图 1：Pareto 前沿（多目标）
# ---------------------------------------------------------------------------------------


def pareto_front(points: Sequence[Sequence[float]], maximize: Sequence[bool]) -> list[int]:
    """返回 Pareto 最优点的下标（``maximize`` 逐目标声明方向）。

    实现为 O(n²) 的支配判定：n 在几千量级以内足够，且**判定逻辑直白可核对**，
    比引入外部库更适合需要审计的场合。
    """
    n = len(points)
    keep: list[int] = []
    for i in range(n):
        dominated = False
        for j in range(n):
            if i == j:
                continue
            better_or_equal = True
            strictly_better = False
            for k, want_max in enumerate(maximize):
                a, b = float(points[i][k]), float(points[j][k])
                if want_max:
                    if b < a:
                        better_or_equal = False
                        break
                    if b > a:
                        strictly_better = True
                else:
                    if b > a:
                        better_or_equal = False
                        break
                    if b < a:
                        strictly_better = True
            if better_or_equal and strictly_better:
                dominated = True
                break
        if not dominated:
            keep.append(i)
    return keep


def plot_pareto(
    points: Sequence[Sequence[float]],
    *,
    labels: tuple[str, str] = ("目标 1", "目标 2"),
    maximize: tuple[bool, bool] = (True, True),
    units: tuple[str, str] = ("", ""),
    title: str = "Pareto 前沿",
    prefix: str = "report",
    baseline: Sequence[float] | None = None,
) -> dict[str, Any]:
    """画 Pareto 前沿：全部候选点 + 前沿连线 + 基线点（如"现状设计"）。"""
    plt = _setup_matplotlib()
    front_idx = pareto_front(points, list(maximize))
    order = sorted(front_idx, key=lambda i: float(points[i][0]), reverse=maximize[0])
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]

    fig, ax = plt.subplots(figsize=(6.2, 4.6))
    ax.scatter(xs, ys, s=26, alpha=0.55, label=f"候选设计（n={len(points)}）", color="#4C78A8")
    ax.plot([float(points[i][0]) for i in order], [float(points[i][1]) for i in order],
            "-o", color="#E45756", lw=1.6, ms=6, label=f"Pareto 前沿（{len(front_idx)} 点）")
    if baseline is not None:
        ax.scatter([float(baseline[0])], [float(baseline[1])], marker="*", s=180,
                   color="#54A24B", zorder=5, label="现状基线")
    ax.set_xlabel(f"{labels[0]}{f' [{units[0]}]' if units[0] else ''}")
    ax.set_ylabel(f"{labels[1]}{f' [{units[1]}]' if units[1] else ''}")
    ax.set_title(title)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, loc="best")

    path = figures_dir(prefix) / "pareto_front.png"
    fig.savefig(path)
    plt.close(fig)
    return {
        "figure": str(path),
        "n_candidates": len(points),
        "n_front": len(front_idx),
        "front_indices": front_idx,
        "dominated_count": len(points) - len(front_idx),
    }


# ---------------------------------------------------------------------------------------
# 图 2：曲线对比（谱线 / 频响）
# ---------------------------------------------------------------------------------------


def plot_curves(
    x: Sequence[float],
    series: dict[str, Sequence[float]],
    *,
    xlabel: str = "频率 [Hz]",
    ylabel: str = "幅值",
    title: str = "频响对比",
    prefix: str = "report",
    bands: dict[str, tuple[Sequence[float], Sequence[float]]] | None = None,
    markers: dict[str, Any] | None = None,
    logx: bool = False,
) -> dict[str, Any]:
    """多条曲线对比；``bands`` 可给某条曲线加不确定度带（下界、上界）。"""
    plt = _setup_matplotlib()
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    colors = ["#4C78A8", "#E45756", "#54A24B", "#B279A2", "#F58518"]
    for i, (name, y) in enumerate(series.items()):
        color = colors[i % len(colors)]
        ax.plot(x, y, label=name, color=color, lw=1.6)
        if bands and name in bands:
            lo, hi = bands[name]
            ax.fill_between(x, lo, hi, color=color, alpha=0.18, label=f"{name} 90% 区间")
        if markers and name in markers:
            point = markers[name]
            ax.scatter([point["x"]], [point["y"]], marker="v", s=70, color=color, zorder=5)
            ax.annotate(point.get("label", ""), (point["x"], point["y"]),
                        textcoords="offset points", xytext=(6, 6), fontsize=8, color=color)
    if logx:
        ax.set_xscale("log")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    path = figures_dir(prefix) / "curves.png"
    fig.savefig(path)
    plt.close(fig)
    return {"figure": str(path), "n_series": len(series), "n_points": len(x)}


# ---------------------------------------------------------------------------------------
# 图 3：场对比（真值 / 预测 / 差值）
# ---------------------------------------------------------------------------------------


def plot_field_comparison(
    coords: Sequence[Sequence[float]],
    truth: Sequence[float],
    prediction: Sequence[float],
    *,
    label: str = "T [K]",
    title: str = "AI 场解 vs COMSOL 场解",
    prefix: str = "report",
    mask: Sequence[bool] | None = None,
) -> dict[str, Any]:
    """三面板：COMSOL 真值 / AI 预测 / 差值。附场级相对 L2（只在掩膜点上算）。"""
    import numpy as np
    from scipy.interpolate import griddata

    plt = _setup_matplotlib()
    pts = np.asarray(coords, dtype=float)
    t = np.asarray(truth, dtype=float)
    p = np.asarray(prediction, dtype=float)
    if mask is not None:
        keep = np.asarray(mask, dtype=bool)
        pts, t, p = pts[keep], t[keep], p[keep]
    finite = np.isfinite(t) & np.isfinite(p)
    pts, t, p = pts[finite], t[finite], p[finite]

    gx = np.linspace(pts[:, 0].min(), pts[:, 0].max(), 160)
    gy = np.linspace(pts[:, 1].min(), pts[:, 1].max(), 120)
    GX, GY = np.meshgrid(gx, gy)
    Zt = griddata(pts, t, (GX, GY), method="linear")
    Zp = griddata(pts, p, (GX, GY), method="linear")
    Zd = Zp - Zt

    denom = float(np.sqrt(np.sum(t**2)))
    rel_l2 = float(np.sqrt(np.sum((p - t) ** 2)) / denom) if denom > 0 else float("nan")

    fig, axes = plt.subplots(1, 3, figsize=(12.6, 3.9))
    for ax, Z, subtitle, cmap in (
        (axes[0], Zt, "COMSOL 真值", "viridis"),
        (axes[1], Zp, "AI 预测", "viridis"),
        (axes[2], Zd, "AI − COMSOL", "coolwarm"),
    ):
        im = ax.pcolormesh(GX, GY, Z, cmap=cmap, shading="auto")
        ax.set_title(f"{subtitle}", fontsize=10)
        ax.set_xlabel("x [m]", fontsize=9)
        ax.set_aspect("equal")
        fig.colorbar(im, ax=ax, fraction=0.046, label=label, pad=0.03)
    axes[0].set_ylabel("y [m]", fontsize=9)
    fig.suptitle(f"{title}（场级相对 L2 = {rel_l2:.3e}，掩膜点 {t.size} 个）", fontsize=11)
    path = figures_dir(prefix) / "field_comparison.png"
    fig.savefig(path)
    plt.close(fig)
    return {"figure": str(path), "field_rel_l2": rel_l2, "n_points": int(t.size),
            "max_abs_diff": float(np.max(np.abs(Zd[np.isfinite(Zd)]))) if np.isfinite(Zd).any() else None}


# ---------------------------------------------------------------------------------------
# 证据表 + 报告装配
# ---------------------------------------------------------------------------------------


@dataclass
class EvidenceRow:
    value: str
    run_id: str | None
    sample_id: str | None
    source_type: str | None
    fidelity: str | None
    extractor: str | None
    note: str = ""

    def as_markdown(self) -> str:
        def cell(text: str | None) -> str:
            return f"`{text}`" if text else "—"
        return (f"| {self.value} | {cell(self.run_id)} | {cell(self.sample_id)} | "
                f"{self.source_type or '—'} | {self.fidelity or '—'} | {cell(self.extractor)} | {self.note} |")


def evidence_rows(conn: Any, sample_ids: Iterable[str]) -> list[EvidenceRow]:
    """把样本 ID 展开成证据表行（数值 + 完整溯源链）。**报告里的数值必须来自这里。**"""
    from .store import query

    rows: list[EvidenceRow] = []
    for sid in sample_ids:
        got = query(
            conn,
            "SELECT s.sample_id, s.run_id, s.source_type, s.fidelity, s.extractor, s.outputs"
            " FROM sample s WHERE s.sample_id = ?",
            [sid],
            limit=1,
        )
        if not got:
            rows.append(EvidenceRow(f"(缺失样本 {sid})", None, sid, None, None, None, "样本不存在"))
            continue
        row = got[0]
        outputs = json.loads(row["outputs"]) if isinstance(row["outputs"], str) else (row["outputs"] or {})
        value = ", ".join(f"{k}={v:g}" if isinstance(v, (int, float)) else f"{k}={v}"
                          for k, v in list(outputs.items())[:3])
        rows.append(EvidenceRow(value, row["run_id"], row["sample_id"], row["source_type"],
                                row["fidelity"], row["extractor"]))
    return rows


def write_report(
    *,
    title: str,
    summary_lines: Sequence[str],
    figures: Sequence[dict[str, Any]],
    rows: Sequence[EvidenceRow],
    caveats: Sequence[str] = (),
    prefix: str = "report",
    extra_sections: dict[str, str] | None = None,
) -> Path:
    """装配 Markdown 报告：结论 → 图 → 证据表 → 如实声明（caveats）。

    ``caveats`` 是**必填的诚实声明位**（样本量、未认证项、未做的验证），不写就等于夸大结论。
    """
    out_dir = work_root() / "reports" / prefix
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "report.md"
    lines: list[str] = [
        f"# {title}",
        "",
        f"> 生成时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}（UTC）",
        "> 本报告的每个数值都可由证据表回溯到具体运行/样本；无出处的数字不写入。",
        "",
        "## 结论",
        "",
    ]
    lines += [f"- {line}" for line in summary_lines] or ["- （无）"]
    lines.append("")

    for i, fig in enumerate(figures, start=1):
        rel = Path(fig["figure"])
        try:
            rel = rel.relative_to(out_dir)
        except ValueError:
            rel = Path("figures") / Path(fig["figure"]).name
        lines += [f"## 图 {i}", "", f"![图 {i}]({rel.as_posix()})", ""]
        for key, value in fig.items():
            if key != "figure":
                lines.append(f"- {key}: `{value}`")
        lines.append("")

    lines += [
        "## 证据表（数值 → 来源）",
        "",
        "| 数值 | run_id | sample_id | 来源 | 保真度 | 抽取器 | 备注 |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [row.as_markdown() for row in rows] or ["| （无） | — | — | — | — | — | — |"]
    lines.append("")

    for name, body in (extra_sections or {}).items():
        lines += [f"## {name}", "", body, ""]

    lines += ["## 如实声明（未做/未达标项）", ""]
    lines += [f"- {c}" for c in caveats] or ["- （无）"]
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
