"""批次数据质量检查 + 输入冻结（sweep-analysis SOP §1–§2）。

由上一批的一次性脚本 `data_quality_check.py` 参数化而来（检查逻辑沿用已验证版本），
并合并"冻结哈希"一步，使每批数据都自带 sha256 锚点。

用法：
    python work\\tools\\batch_quality.py --csv <表> --out-dir <批次目录> --label <批次名> \\
        [--input <被冻结的文件> ...]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def sha256(path: Path, chunk: int = 1 << 22) -> str:
    import hashlib

    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for blk in iter(lambda: fh.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def parse_complex(text: str):
    body = (text or "").strip().replace(" ", "")
    if not body:
        return None
    if not body.endswith("i"):
        try:
            return complex(float(body), 0.0)
        except ValueError:
            return None
    head = body[:-1]
    split = None
    for i, ch in enumerate(head):
        if ch in "+-" and i > 0 and head[i - 1] not in "eE":
            split = i
    if split is None:
        try:
            return complex(0.0, float(head))
        except ValueError:
            return None
    try:
        return complex(float(head[:split]), float(head[split:]))
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="批次数据质量检查 + 输入冻结")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--label", default=None)
    ap.add_argument("--input", action="append", default=[], help="要冻结哈希的输入文件（可重复）")
    args = ap.parse_args(argv)

    csv_path = Path(args.csv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    label = args.label or csv_path.stem

    # ---- 冻结 ----
    frozen = {"label": label, "items": []}
    for p in [csv_path] + [Path(x) for x in args.input]:
        item = {"path": str(p), "exists": p.exists()}
        if p.exists():
            st = p.stat()
            item.update(bytes=st.st_size, mtime=st.st_mtime,
                        sha256=None if p.suffix.lower() == ".mph" and Path(str(p) + ".lock").exists()
                        else sha256(p))
            if item["sha256"] is None:
                item["note"] = "带 .mph.lock（GUI 打开中）⇒ 不取哈希，避免记录未保存状态"
            lock = Path(str(p) + ".lock")
            item["lock_present"] = lock.exists()
        frozen["items"].append(item)
    (out_dir / "freeze_inputs.json").write_text(
        json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[冻结] {len(frozen['items'])} 个输入 → {out_dir / 'freeze_inputs.json'}")
    for it in frozen["items"]:
        print(f"   {Path(it['path']).name}: {it.get('sha256') or '(跳过)'}")

    # ---- 读表 ----
    text = csv_path.read_text(encoding="utf-8-sig", errors="replace")
    grid = [r for r in csv.reader(io.StringIO(text)) if r]
    hi = next(i for i, r in enumerate(grid)
              if r and r[0].strip().lstrip("% ").strip() in ("x_scale", "x scale", "xscale"))
    meta = [" , ".join(r) for r in grid[:hi]]
    header = [c.strip() for c in grid[hi]]
    header[0] = header[0].lstrip("%").strip()
    data = [dict(zip(header, r)) for r in grid[hi + 1:] if len(r) >= len(header) and r[0].strip()]

    def col(*names: str) -> str | None:
        for n in names:
            for h in header:
                if h.lower().startswith(n.lower()):
                    return h
        return None

    c_ptot, c_vave, c_vc = col("Ptot"), col("Vave"), col("V_center")
    c_z1r, c_z1x, c_z2r, c_z2x = col("Zin1_R"), col("Zin1_X"), col("Zin2_R"), col("Zin2_X")
    c_freq = col("freq")

    issues: list[str] = []
    L: list[str] = []
    add = L.append
    add(f"# 数据质量报告 · 批次 `{label}`（sweep-analysis SOP §2）")
    add("")
    add(f"- 源文件：`{csv_path}`")
    add(f"- sha256：`{sha256(csv_path)}`")
    for m in meta:
        add(f"  - 元信息：`{m}`")
    add(f"- 列（{len(header)}）：`{header}`")
    add("")

    xs = sorted({float(r["x_scale"]) for r in data})
    n1s = sorted({float(r[col('N_w_te1')]) for r in data})
    freqs = sorted({float(r[c_freq]) for r in data})
    combos: dict[tuple[float, float], list[dict]] = defaultdict(list)
    for r in data:
        combos[(float(r["x_scale"]), float(r[col('N_w_te1')]))].append(r)
    expected = len(xs) * len(n1s) * len(freqs)

    add("## 1. 行数与组合完整性")
    add("")
    add("| 项 | 值 |")
    add("|---|---|")
    add(f"| 实际数据行数 | **{len(data)}** |")
    add(f"| `x_scale` 档位 | {len(xs)}：{xs} |")
    add(f"| `N_w_te1` 档位 | {len(n1s)}：{[int(v) for v in n1s]} |")
    add(f"| 频率点 | {len(freqs)}：{[f / 1e6 for f in freqs]} MHz |")
    add(f"| 实际组合数 | {len(combos)} |")
    add(f"| 满格应有 | {len(xs)}×{len(n1s)}×{len(freqs)} = {expected} 行 |")
    add("")
    counts = Counter(len(v) for v in combos.values())
    add(f"每组合行数分布：{dict(counts)}（应全为 {len(freqs)}）")
    full_grid = {(x, n) for x in xs for n in n1s}
    missing = sorted(full_grid - set(combos))
    if missing:
        add("")
        add(f"**缺失组合 {len(missing)} 个**：{missing}")
        issues.append(f"缺失 {len(missing)} 个组合")
    bad_count = [k for k, v in combos.items() if len(v) != len(freqs)]
    if bad_count:
        issues.append(f"{len(bad_count)} 个组合频率点数异常：{bad_count[:8]}")
    add("")

    # ---- 数值有效性 ----
    add("## 2. 数值有效性")
    add("")
    nan = inf = empty = badcomplex = 0
    neg_ptot: list[tuple] = []
    zero_ptot = 0
    order_bad: list[tuple] = []
    zin_equal = 0
    ptot_values: list[float] = []
    for r in data:
        for key in header:
            v = (r.get(key) or "").strip()
            if v == "":
                empty += 1
            elif v.lower() in ("nan", "-nan"):
                nan += 1
            elif "inf" in v.lower():
                inf += 1
        if c_ptot:
            try:
                ptot = float(r[c_ptot])
                ptot_values.append(ptot)
                if ptot < 0:
                    neg_ptot.append((r["x_scale"], r[col('N_w_te1')], r[c_freq], ptot))
                elif ptot == 0.0:
                    zero_ptot += 1
            except ValueError:
                pass
        for key in (c_vave, c_vc):
            if key and parse_complex(r.get(key, "")) is None:
                badcomplex += 1
        if c_z1r and c_z2r and r[c_z1r] == r[c_z2r] and r[c_z1x] == r[c_z2x]:
            zin_equal += 1
    for key, group in combos.items():
        seq = [float(r[c_freq]) for r in group]
        if any(seq[i] <= seq[i - 1] for i in range(1, len(seq))):
            order_bad.append(key)
    add("| 检查 | 结果 |")
    add("|---|---|")
    add(f"| 空值单元格 | {empty} |")
    add(f"| `NaN` / `Inf` | {nan} / {inf} |")
    add(f"| 无法解析的复数 | {badcomplex} |")
    add(f"| **`Ptot` 负值行** | **{len(neg_ptot)}** |")
    add(f"| `Ptot` 恰为 0 | {zero_ptot} |")
    add(f"| 频率未严格递增的组合 | {len(order_bad)} |")
    add(f"| `Zin1` 与 `Zin2` 逐位相同的行 | **{zin_equal}/{len(data)}** |")
    add("")
    if ptot_values:
        add(f"`Ptot` 量级：min={min(ptot_values):.4g} W，max={max(ptot_values):.4g} W")
        add("")
    if neg_ptot:
        add(f"⚠️ **{len(neg_ptot)} 行 `Ptot` < 0**（前 5 条）：{neg_ptot[:5]}")
        issues.append(f"{len(neg_ptot)} 行 Ptot<0（需核查积分面法向）")
    else:
        add("✅ 未发现 `Ptot` 负值。")
    add("")
    if zin_equal == len(data) and data:
        add("⚠️ **`Zin2` 与 `Zin1` 在全部行上逐位相同** ⇒ 已知公式缺陷（`Zin2 = v0/I01`），"
            "修正前 `Zin2` 不参与评分/排名。")
        issues.append("Zin2≡Zin1（公式复制错误，已知）")

    # ---- 频段包覆性 ----
    add("")
    add("## 3. 频段包覆性（决定这批数据能否用来选「最优」）")
    add("")
    if c_ptot:
        peak_top = 0
        peak_dist: Counter = Counter()
        for key, group in combos.items():
            best = max(group, key=lambda r: float(r[c_ptot]))
            peak_dist[float(best[c_freq]) / 1e6] += 1
            if float(best[c_freq]) == max(freqs):
                peak_top += 1
        add(f"- `Ptot` 峰值落在最高频（{max(freqs) / 1e6:g} MHz）的组合：**{peak_top}/{len(combos)}**")
        add(f"- 峰值频率分布（MHz→组合数）：{dict(sorted(peak_dist.items()))}")
        add("")
        if peak_top:
            issues.append(f"{peak_top}/{len(combos)} 个组合 Ptot 峰值落在频段上边界 ⇒ 谐振未被频段包住")
    if c_vave:
        peak_top_v = sum(1 for g in combos.values()
                         if float(max(g, key=lambda r: abs(parse_complex(r[c_vave]) or 0))[c_freq]) == max(freqs))
        add(f"- `Vave` 峰值落在最高频的组合：**{peak_top_v}/{len(combos)}**")
        add("")

    add("## 4. 结论与待办")
    add("")
    if issues:
        add("**发现的问题**：")
        for i, s in enumerate(issues, 1):
            add(f"{i}. {s}")
    else:
        add("未发现阻断性问题。")
    add("")
    add("**下一步**：几何/选择预检（`scripts\\geometry_selection_precheck.py`，需 COMSOL 空闲）"
        "→ 仅对 `clean` 组合排名 → 精扫候选。")

    (out_dir / "02_data_quality_report.md").write_text("\n".join(L), encoding="utf-8")
    (out_dir / "_data_quality.json").write_text(json.dumps({
        "label": label, "source": str(csv_path), "source_sha256": sha256(csv_path),
        "n_rows": len(data), "x_scale_values": xs, "N_w_te1_values": [int(v) for v in n1s],
        "frequencies_MHz": [f / 1e6 for f in freqs], "n_combos": len(combos),
        "expected_rows": expected, "missing_combos": missing,
        "rows_per_combo": {str(k): v for k, v in counts.items()},
        "nan": nan, "inf": inf, "empty": empty, "bad_complex": badcomplex,
        "negative_ptot_rows": len(neg_ptot), "zero_ptot_rows": zero_ptot,
        "zin_equal_rows": zin_equal, "issues": issues,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(L[L.index("## 1. 行数与组合完整性"):]))
    print(f"\n落档：{out_dir / '02_data_quality_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
