"""PMUT 参数扫描结果分析管线（Codex《计算结果分析指令》§3–§9 + 决策回复 §6/§8）。

一条命令完成：质量检查 → 逐组合指标 → 排名/Pareto → 候选与精扫计划 → 图 → 报告。

严格遵循的规则：
  - 幅值量归一化用 20*log10，功率量用 10*log10，**绝不混用**；
  - −6 dB 交点在相邻频点间线性插值；若曲线在边界仍未回落 6 dB → 标 lower/upper_bound_not_found，**不得**把边界当交点；
  - `Ptot` 负值只标记不静默取绝对值；
  - `N_w_te1=0` 单列 `N0_control`，不参与双电极主排名；
  - 只对几何/选择预检为 `clean` 的组合做最终排名（未提供预检文件时明确降级并声明）；
  - 不使用"无依据的单一加权总分"，改为多指标 top-10 + Pareto 非支配前沿；
  - 命名限制：只报 `Vave` −6 dB 响应带宽 / `Ptot` −6 dB 功率带宽，**不称往返带宽**。

用法：
    python scripts\\analyze_sweep.py --csv "<导出表>" --out-dir work\\reports\\analysis_decision\\<批次> \
        [--precheck work\\runs\\<precheck run>\\geometry_selection_precheck.json]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]

try:  # Windows 控制台多为 GBK 码页：Emoji 等字符降级输出，避免 UnicodeEncodeError 中断整条管线（2026-09-13 实测）
    sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(errors="replace")  # type: ignore[union-attr]
except Exception:
    pass


def sha256_file(path: Path) -> str:
    """文件 sha256（用于给每批数据钉死来源；读不到就抛错，不返回假值）。"""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- 读取与解析

COL_PATTERNS = {
    "x_scale": r"x[\s_-]*scale",
    "N_w_te1": r"n[\s_-]*w[\s_-]*te1",
    "freq": r"freq",
    "Ptot": r"ptot",
    "Zin1_R": r"zin1[\s_-]*r",
    "Zin1_X": r"zin1[\s_-]*x",
    "Zin2_R": r"zin2[\s_-]*r",
    "Zin2_X": r"zin2[\s_-]*x",
    "Vave": r"v[\s_-]*ave",
    "V_center": r"v[\s_-]*center",
}


def read_table(path: Path) -> tuple[dict[str, str], list[dict], str, str]:
    """容错读取：编码级联 + 关键词识别列名 + 自动分隔符。返回 (列映射, 行, 编码, 分隔符)。"""
    raw = path.read_bytes()
    used_enc = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "cp936", "latin-1"):
        try:
            text = raw.decode(enc)
            used_enc = enc
            break
        except UnicodeDecodeError:
            continue
    if used_enc is None:
        text, used_enc = raw.decode("utf-8", errors="replace"), "utf-8(replace)"

    delim = "\t" if text.count("\t") > text.count(",") else ","
    grid = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if r]
    hi = next(
        i for i, r in enumerate(grid)
        if r and re.search(COL_PATTERNS["x_scale"], r[0], re.I)
    )
    header = [c.strip().lstrip("% ").strip() for c in grid[hi]]
    mapping: dict[str, str] = {}
    for key, pat in COL_PATTERNS.items():
        for col in header:
            if re.search(pat, col, re.I):
                mapping[key] = col
                break
    rows = []
    for r in grid[hi + 1:]:
        if len(r) < len(header) or not r[0].strip():
            continue
        rows.append(dict(zip(header, r)))
    missing = [k for k in ("x_scale", "N_w_te1", "freq") if k not in mapping]
    if missing:
        raise SystemExit(f"[错误] 关键列缺失：{missing}；实际表头={header}")
    return mapping, rows, used_enc, ("tab" if delim == "\t" else "comma")


def parse_complex(text: str) -> complex | None:
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


# ---------------------------------------------------------------- 指标计算


def db_amplitude(values: np.ndarray, peak: float) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return 20.0 * np.log10(np.where(values > 0, values / peak, np.nan))


def db_power(values: np.ndarray, peak: float) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return 10.0 * np.log10(np.where(values > 0, values / peak, np.nan))


def cross_6db(freqs: np.ndarray, db: np.ndarray) -> dict:
    """从峰值处向两侧找 −6 dB 交点（线性插值）。找不到就标 not_found，不拿边界冒充。"""
    out = {"f_low_MHz": None, "f_high_MHz": None,
           "lower_bound_not_found": False, "upper_bound_not_found": False}
    if freqs.size < 2 or np.all(np.isnan(db)):
        return out
    i_peak = int(np.nanargmax(db))
    target = -6.0
    f_low = None
    for i in range(i_peak, 0, -1):
        a, b = db[i], db[i - 1]
        if np.isnan(a) or np.isnan(b):
            continue
        if a >= target > b:
            frac = (a - target) / (a - b)
            f_low = freqs[i] - frac * (freqs[i] - freqs[i - 1])
            break
    if f_low is None:
        out["lower_bound_not_found"] = True
    f_high = None
    for i in range(i_peak, freqs.size - 1):
        a, b = db[i], db[i + 1]
        if np.isnan(a) or np.isnan(b):
            continue
        if a >= target > b:
            frac = (a - target) / (a - b)
            f_high = freqs[i] + frac * (freqs[i + 1] - freqs[i])
            break
    if f_high is None:
        out["upper_bound_not_found"] = True
    if f_low is not None:
        out["f_low_MHz"] = float(f_low / 1e6)
    if f_high is not None:
        out["f_high_MHz"] = float(f_high / 1e6)
    if f_low is not None and f_high is not None:
        fc = (f_high + f_low) / 2.0
        out.update(fc_MHz=float(fc / 1e6), BW_MHz=float((f_high - f_low) / 1e6),
                   FBW_percent=float((f_high - f_low) / fc * 100.0))
    return out


def interp_at(freqs: np.ndarray, values: np.ndarray, target: float) -> tuple[float | None, bool]:
    """在 target（Hz）处取值；若不在采样点上则线性插值并返回 interpolated=True。"""
    if freqs.size == 0:
        return None, False
    exact = np.where(np.isclose(freqs, target))[0]
    if exact.size:
        v = values[exact[0]]
        return (None if np.isnan(v) else float(v)), False
    if target < freqs.min() or target > freqs.max():
        return None, False
    v = float(np.interp(target, freqs, values))
    return (None if math.isnan(v) else v), True


def flatness(freqs: np.ndarray, db: np.ndarray, lo: float, hi: float) -> tuple[float | None, float | None, int]:
    mask = (freqs >= lo) & (freqs <= hi) & ~np.isnan(db)
    if mask.sum() < 2:
        return None, None, int(mask.sum())
    band = db[mask]
    return float(band.max() - band.min()), float(band.min()), int(mask.sum())


# ---------------------------------------------------------------- 主流程


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PMUT 扫描结果分析管线")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--precheck", default=None, help="geometry_selection_precheck.json（可选）")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--baseline-x", type=float, default=0.6)
    ap.add_argument("--baseline-n", type=int, default=4)
    ap.add_argument("--target-mhz", type=float, default=20.0)
    ap.add_argument("--band-lo", type=float, default=10.0)
    ap.add_argument("--band-mid-lo", type=float, default=15.0)
    ap.add_argument("--band-mid-hi", type=float, default=25.0)
    ap.add_argument("--band-hi", type=float, default=30.0)
    # ---- 批次溯源（Codex §9 版本字段；多模型数据严禁混排）----
    ap.add_argument("--batch-label", default=None, help="批次标识，默认取 CSV 文件名（不含扩展名）")
    ap.add_argument("--model-file", default="", help="产生本批数据的模型文件（仓库外，只读引用）")
    ap.add_argument("--model-sha256", default="", help="模型 sha256；未知就留空，**禁止编造**")
    ap.add_argument("--model-version", default="unknown",
                    choices=["original_selection_original_drive",
                             "corrected_selection_original_drive",
                             "corrected_selection_explicit_reverse_drive",
                             "unknown"])
    ap.add_argument("--drive-mode", default="unknown",
                    help="驱动口径，如 'pot1-off/term1-circuit(R1=1ohm)/termI1.V_src=es.V0_1'")
    ap.add_argument("--notes", default="", help="批次备注（写入 00_provenance.json）")
    ap.add_argument("--plan-candidates", default=None,
                    help="显式精扫候选，形如 '0.6:4:基准,0.7:5:双闭合,0.45:6:最大输出,0.75:5:最平坦'")
    ap.add_argument("--plan-optional", default=None,
                    help="第二阶段补充候选，格式同 --plan-candidates")
    ap.add_argument("--freq-start-mhz", type=float, default=5.0)
    ap.add_argument("--freq-stop-mhz", type=float, default=45.0)
    ap.add_argument("--freq-step-mhz", type=float, default=0.5)
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    (out_dir / "figures").mkdir(parents=True, exist_ok=True)

    mapping, rows, enc, delim = read_table(Path(args.csv))
    print(f"读取 {len(rows)} 行；编码={enc} 分隔符={delim}")
    print(f"列映射：{mapping}")

    # 预检分类
    precheck: dict[tuple[float, float], str] = {}
    precheck_sha = ""
    if args.precheck and Path(args.precheck).is_file():
        spec = json.loads(Path(args.precheck).read_text(encoding="utf-8"))
        for r in spec.get("rows", []):
            precheck[(float(r["x_scale"]), float(r["N_w_te1"]))] = r.get("classification", "unknown")
        precheck_sha = sha256_file(Path(args.precheck))
        print(f"预检分类载入 {len(precheck)} 个组合（sha256 {precheck_sha[:12]}…）")

    combos: dict[tuple[float, float], list[dict]] = {}
    for r in rows:
        combos.setdefault((float(r[mapping["x_scale"]]), float(r[mapping["N_w_te1"]])), []).append(r)

    # ---- 批次溯源 00：每行都带批次身份，多模型数据严禁混排 ----
    csv_path = Path(args.csv)
    prov = {
        "batch_label": args.batch_label or csv_path.stem,
        "source_csv": str(csv_path.resolve()),
        "source_csv_sha256": sha256_file(csv_path),
        "row_count": len(rows),
        "combo_count": len(combos),
        "grid": {
            "x_scale": sorted({float(k[0]) for k in combos}),
            "N_w_te1": sorted({int(k[1]) for k in combos}),
        },
        "freqs_MHz": sorted({round(float(r[mapping["freq"]]) / 1e6, 6) for r in rows}),
        "model_file": args.model_file,
        "model_sha256": args.model_sha256,
        "model_version": args.model_version,
        "drive_mode": args.drive_mode,
        "precheck_file": str(Path(args.precheck).resolve()) if args.precheck else "",
        "precheck_sha256": precheck_sha,
        "precheck_combos_loaded": len(precheck),
        "analysis_script": str(Path(__file__).resolve()),
        "analysis_script_sha256": sha256_file(Path(__file__).resolve()),
        "notes": args.notes,
        "csv_encoding": enc,
        "csv_delimiter": delim,
    }
    if not args.model_sha256:
        prov["model_sha256_note"] = "未提供模型哈希 ⇒ 本批不得与其它批次合并统计"
    (out_dir / "00_provenance.json").write_text(
        json.dumps(prov, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"批次：{prov['batch_label']}｜模型 {args.model_file or '(未声明)'}"
          f"｜csv sha256 {prov['source_csv_sha256'][:12]}…")
    if not args.model_sha256:
        print(f"  [!] 未提供 --model-sha256：本批溯源不完整，禁止与其它批次合并排名")

    # ---- 清洗表 01 ----
    cleaned = []
    for (x, n), group in sorted(combos.items()):
        for r in sorted(group, key=lambda r: float(r[mapping["freq"]])):
            f = float(r[mapping["freq"]])
            vave = parse_complex(r.get(mapping.get("Vave", ""), ""))
            vcent = parse_complex(r.get(mapping.get("V_center", ""), ""))
            ptot = float(r[mapping["Ptot"]]) if mapping.get("Ptot") else None
            zr = float(r[mapping["Zin1_R"]]) if mapping.get("Zin1_R") else None
            zx = float(r[mapping["Zin1_X"]]) if mapping.get("Zin1_X") else None
            cleaned.append({
                "batch_label": prov["batch_label"],
                "model_version": args.model_version,
                "model_sha256": args.model_sha256,
                "source_csv_sha256": prov["source_csv_sha256"],
                "freq_MHz": f / 1e6, "x_scale": x, "N_w_te1": n,
                "Ptot_W": ptot, "Vave_mps": None if vave is None else abs(vave),
                "V_center_abs": None if vcent is None else abs(vcent),
                "Zin1_R_Ohm": zr, "Zin1_X_Ohm": zx,
                "Zin1_abs_Ohm": None if (zr is None or zx is None) else math.hypot(zr, zx),
                "Zin1_phase_deg": None if (zr is None or zx is None) else math.degrees(math.atan2(zx, zr)),
                "Ptot_negative_flag": bool(ptot is not None and ptot < 0),
            })
    with (out_dir / "01_cleaned_results.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(cleaned[0]))
        writer.writeheader()
        writer.writerows(cleaned)

    # ---- 逐组合指标 03 ----
    summaries = []
    curves: dict[tuple[float, float], dict] = {}
    for (x, n), group in sorted(combos.items()):
        group = sorted(group, key=lambda r: float(r[mapping["freq"]]))
        freqs = np.array([float(r[mapping["freq"]]) for r in group])
        vave = np.array([abs(parse_complex(r.get(mapping.get("Vave", ""), "")) or np.nan) for r in group])
        ptot = np.array([float(r[mapping["Ptot"]]) if mapping.get("Ptot") else np.nan for r in group])
        zr = np.array([float(r[mapping["Zin1_R"]]) if mapping.get("Zin1_R") else np.nan for r in group])
        zx = np.array([float(r[mapping["Zin1_X"]]) if mapping.get("Zin1_X") else np.nan for r in group])
        vc = np.array([abs(parse_complex(r.get(mapping.get("V_center", ""), "")) or np.nan) for r in group])
        vave_dB = db_amplitude(vave, np.nanmax(vave)) if np.isfinite(vave).any() else np.full(freqs.size, np.nan)
        ptot_dB = db_power(ptot, np.nanmax(ptot)) if np.isfinite(ptot).any() and np.nanmax(ptot) > 0 else np.full(freqs.size, np.nan)
        ban_v = cross_6db(freqs, vave_dB)
        ban_p = cross_6db(freqs, ptot_dB)
        flat_lo, min_lo, cnt_lo = flatness(freqs, vave_dB, args.band_lo * 1e6, args.band_hi * 1e6)
        flat_mid, min_mid, cnt_mid = flatness(freqs, vave_dB, args.band_mid_lo * 1e6, args.band_mid_hi * 1e6)
        v20, interp20 = interp_at(freqs, vave, args.target_mhz * 1e6)
        p20, _ = interp_at(freqs, ptot, args.target_mhz * 1e6)
        za20 = interp_at(freqs, np.hypot(zr, zx), args.target_mhz * 1e6)[0]
        zp20 = interp_at(freqs, np.degrees(np.arctan2(zx, zr)), args.target_mhz * 1e6)[0]
        if freqs.size and np.isfinite(vave).any():
            i_v = int(np.nanargmax(vave)); f_peak_v = float(freqs[i_v]); v_peak = float(vave[i_v])
        else:
            f_peak_v = v_peak = None
        if freqs.size and np.isfinite(ptot).any():
            i_p = int(np.nanargmax(ptot)); f_peak_p = float(freqs[i_p]); p_peak = float(ptot[i_p])
        else:
            f_peak_p = p_peak = None
        cls = precheck.get((x, n), "precheck_missing")
        summaries.append({
            "batch_label": prov["batch_label"],
            "model_version": args.model_version,
            "model_sha256": args.model_sha256,
            "source_csv_sha256": prov["source_csv_sha256"],
            "x_scale": x, "N_w_te1": n, "precheck_class": cls,
            "frequency_count": int(freqs.size),
            "f_peak_Vave_MHz": None if f_peak_v is None else f_peak_v / 1e6, "Vave_peak": v_peak,
            "Vave_20MHz": v20, "Vave_20MHz_interpolated": interp20,
            "f_low_Vave_MHz": ban_v.get("f_low_MHz"), "f_high_Vave_MHz": ban_v.get("f_high_MHz"),
            "fc_Vave_MHz": ban_v.get("fc_MHz"), "FBW_Vave_percent": ban_v.get("FBW_percent"),
            "Vave_lower_bound_not_found": ban_v["lower_bound_not_found"],
            "Vave_upper_bound_not_found": ban_v["upper_bound_not_found"],
            f"flatness_{args.band_lo:g}_{args.band_hi:g}_dB": flat_lo,
            f"flatness_{args.band_mid_lo:g}_{args.band_mid_hi:g}_dB": flat_mid,
            f"min_Vave_dB_{args.band_mid_lo:g}_{args.band_mid_hi:g}": min_mid,
            "f_peak_Ptot_MHz": None if f_peak_p is None else f_peak_p / 1e6, "Ptot_peak_W": p_peak,
            "Ptot_20MHz_W": p20, "fc_Ptot_MHz": ban_p.get("fc_MHz"),
            "FBW_Ptot_percent": ban_p.get("FBW_percent"),
            "Ptot_lower_bound_not_found": ban_p["lower_bound_not_found"],
            "Ptot_upper_bound_not_found": ban_p["upper_bound_not_found"],
            "Zin1_abs_20MHz_Ohm": za20, "Zin1_phase_20MHz_deg": zp20,
            "Ptot_min_W": float(np.nanmin(ptot)) if np.isfinite(ptot).any() else None,
            "Ptot_has_negative": bool(np.isfinite(ptot).any() and np.nanmin(ptot) < 0),
            "bandwidth_closed_Vave": (not ban_v["lower_bound_not_found"]) and (not ban_v["upper_bound_not_found"]),
            "bandwidth_closed_Ptot": (not ban_p["lower_bound_not_found"]) and (not ban_p["upper_bound_not_found"]),
        })
        curves[(x, n)] = {"freqs": freqs, "vave": vave, "vave_dB": vave_dB, "ptot": ptot,
                          "ptot_dB": ptot_dB, "zin1_r": zr, "zin1_x": zx, "vcenter_abs": vc}
    with (out_dir / "03_coarse_sweep_metrics.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)

    # ---- 排名与 Pareto（只在允许的子集内）----
    allowed = {"clean", "N0_control"} if precheck else None
    primary = [s for s in summaries if (allowed is None or s["precheck_class"] in allowed)]
    design = [s for s in primary if s["N_w_te1"] != 0]
    note_rank = ("预检文件已提供：仅在 clean/N0_control 内排名" if precheck
                 else "⚠️ 未提供几何/选择预检 → 排名为**临时**结果，最终排名须待预检完成（Codex §2.2）")

    def top(key: str, n: int = 10, reverse: bool = True, pool: list | None = None):
        pool = pool if pool is not None else design
        vals = [s for s in pool if s.get(key) is not None]
        return sorted(vals, key=lambda s: s[key], reverse=reverse)[:n]

    tops = {
        "FBW_Vave_percent": top("FBW_Vave_percent"),
        "Vave_20MHz": top("Vave_20MHz"),
        "Ptot_20MHz_W": top("Ptot_20MHz_W"),
        f"flatness_{args.band_mid_lo:g}_{args.band_mid_hi:g}_dB": top(
            f"flatness_{args.band_mid_lo:g}_{args.band_mid_hi:g}_dB", reverse=False),
    }
    pareto_rows = []
    if design:
        pts = {}
        for s in design:
            vals = [s.get("FBW_Vave_percent"), s.get("Vave_20MHz"), s.get("Ptot_20MHz_W"),
                    s.get(f"flatness_{args.band_mid_lo:g}_{args.band_mid_hi:g}_dB")]
            if any(v is None for v in vals):
                continue
            pts[(s["x_scale"], s["N_w_te1"])] = vals
        keys = list(pts)
        dirs = [1, 1, 1, -1]
        for k in keys:
            dominated = False
            for other in keys:
                if other == k:
                    continue
                if all(pts[other][i] * dirs[i] >= pts[k][i] * dirs[i] for i in range(4)) and \
                   any(pts[other][i] * dirs[i] > pts[k][i] * dirs[i] for i in range(4)):
                    dominated = True
                    break
            if not dominated:
                s = next(s for s in design if (s["x_scale"], s["N_w_te1"]) == k)
                pareto_rows.append(s)
    with (out_dir / "04_pareto_candidates.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        if pareto_rows:
            writer = csv.DictWriter(fh, fieldnames=list(pareto_rows[0]))
            writer.writeheader()
            writer.writerows(pareto_rows)
        else:
            fh.write("（无可计算 Pareto 的组合：指标缺失）\n")

    # ---- 精扫计划 05（Codex 裁决 §3.2/§4：候选显式给出；频率范围参数化，禁止写死）----
    freq_n = int(round((args.freq_stop_mhz - args.freq_start_mhz) / args.freq_step_mhz)) + 1
    freq_desc = (f"{args.freq_start_mhz:g}–{args.freq_stop_mhz:g} MHz "
                 f"@{args.freq_step_mhz:g} MHz = {freq_n} 点")

    def _row(order, stage, role, reason, key):
        if key is None:
            return None
        s = next((x for x in summaries if (x["x_scale"], x["N_w_te1"]) == key), None)
        common = {"order": order, "stage": stage, "role": role, "frequency_count": freq_n,
                  "frequency_range": freq_desc, "reason": reason}
        if s is None:
            return {**common, "x_scale": key[0], "N_w_te1": key[1],
                    "precheck_class": "not_in_data", "FBW_Vave_percent": None,
                    "flatness_15_25_dB": None}
        return {**common, **{k: s[k] for k in ("x_scale", "N_w_te1", "precheck_class",
                                               "FBW_Vave_percent", "flatness_15_25_dB")}}

    plan = []
    base = next((s for s in summaries if s["x_scale"] == args.baseline_x
                 and s["N_w_te1"] == args.baseline_n), None)
    if args.plan_candidates:
        for i, tok in enumerate([t for t in args.plan_candidates.split(",") if t.strip()], start=1):
            parts = tok.split(":")
            r = _row(i, 1, parts[2] if len(parts) > 2 else f"候选{i}",
                     "由 --plan-candidates 显式指定（Codex §4.1）",
                     (round(float(parts[0]), 4), int(parts[1])))
            if r:
                plan.append(r)
        for tok in [t for t in (args.plan_optional or "").split(",") if t.strip()]:
            parts = tok.split(":")
            r = _row(len(plan) + 1, 2, parts[2] if len(parts) > 2 else "补充候选",
                     "第二阶段补充候选（资源允许时执行，Codex §4.2）",
                     (round(float(parts[0]), 4), int(parts[1])))
            if r:
                plan.append(r)
    else:
        # 自动回退；Codex §3.2 修正：优先"双口径闭合"（Ptot 与 Vave 都闭合），而非只看 Vave
        base = next((s for s in summaries if s["x_scale"] == args.baseline_x
                     and s["N_w_te1"] == args.baseline_n), None)
        if base:
            plan.append(_row(1, 1, "基准", "基准组合：所有候选与之对比",
                             (base["x_scale"], base["N_w_te1"])))
        dual = [s for s in design if s.get("bandwidth_closed_Vave")
                and s.get("bandwidth_closed_Ptot") and s.get("FBW_Vave_percent")]
        pool = dual or [s for s in design if s.get("bandwidth_closed_Vave")
                        and s.get("FBW_Vave_percent")]
        if pool:
            pick = max(pool, key=lambda s: s["FBW_Vave_percent"])
            plan.append(_row(len(plan) + 1, 1, "双口径闭合中 FBW_Vave 最大",
                             "Ptot 与 Vave 两条 −6 dB 上界均在频段内；若无双闭合则退化为 Vave 闭合",
                             (pick["x_scale"], pick["N_w_te1"])))
        used = {(p["x_scale"], p["N_w_te1"]) for p in plan}
        flat_pool = [s for s in design if s.get("flatness_15_25_dB") is not None
                     and (s["x_scale"], s["N_w_te1"]) not in used]
        if flat_pool:
            pf = min(flat_pool, key=lambda s: s["flatness_15_25_dB"])
            plan.append(_row(len(plan) + 1, 1, "15–25 MHz 最平坦（且与前面不同）",
                             "平坦度（max−min，越小越好）最优",
                             (pf["x_scale"], pf["N_w_te1"])))
    plan = [p for p in plan if p]
    with (out_dir / "05_fine_sweep_plan.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        if plan:
            writer = csv.DictWriter(fh, fieldnames=list(plan[0]))
            writer.writeheader()
            writer.writerows(plan)

    # ---- 图 ----
    xs_sorted = sorted({s["x_scale"] for s in summaries})
    ns_sorted = sorted({s["N_w_te1"] for s in summaries})
    heat_specs = [
        ("Vave_20MHz", "|Vave| @20 MHz (m/s)", "heat_Vave_20MHz.png"),
        ("Ptot_20MHz_W", "Ptot @20 MHz (W)", "heat_Ptot_20MHz.png"),
        ("f_peak_Vave_MHz", "f_peak(Vave) (MHz)", "heat_fpeak_Vave.png"),
        ("FBW_Vave_percent", "Vave −6 dB FBW (%)", "heat_FBW_Vave.png"),
        (f"flatness_{args.band_mid_lo:g}_{args.band_mid_hi:g}_dB", "flatness 15–25 MHz (dB)",
         "heat_flatness_15_25.png"),
        ("Zin1_abs_20MHz_Ohm", "|Zin1| @20 MHz (Ohm)", "heat_Zin1_abs_20MHz.png"),
    ]
    for key, label, fname in heat_specs:
        mat = np.full((len(ns_sorted), len(xs_sorted)), np.nan)
        for s in summaries:
            if s.get(key) is None:
                continue
            mat[ns_sorted.index(s["N_w_te1"]), xs_sorted.index(s["x_scale"])] = s[key]
        fig, ax = plt.subplots(figsize=(6.4, 4.2))
        masked = np.ma.masked_invalid(mat)
        im = ax.imshow(masked, origin="lower", aspect="auto", cmap="viridis")
        ax.set_xticks(range(len(xs_sorted)), [f"{x:g}" for x in xs_sorted])
        ax.set_yticks(range(len(ns_sorted)), [str(n) for n in ns_sorted])
        ax.set_xlabel("x_scale"); ax.set_ylabel("N_w_te1"); ax.set_title(label)
        fig.colorbar(im, ax=ax)
        fig.tight_layout(); fig.savefig(out_dir / "figures" / fname, dpi=140); plt.close(fig)

    picks = [k for k in [(args.baseline_x, args.baseline_n)] + [(p["x_scale"], p["N_w_te1"]) for p in plan[1:]]
             if k in curves]
    n0 = next((k for k in curves if k[1] == 0), None)
    for key, label, fname in (
        ("vave", "|Vave| (m/s)", "curve_Vave.png"),
        ("vave_dB", "Vave (dB, 20log10)", "curve_Vave_dB.png"),
        ("ptot", "Ptot (W)", "curve_Ptot.png"),
        ("vcenter_abs", "|V_center| (m/s)", "curve_Vcenter.png"),
    ):
        fig, ax = plt.subplots(figsize=(7.2, 4.6))
        for k in picks:
            ax.plot(curves[k]["freqs"] / 1e6, curves[k][key], marker="o", label=f"x={k[0]:g}, N={k[1]}")
        if n0 is not None and key != "vave_dB":
            ax.plot(curves[n0]["freqs"] / 1e6, curves[n0][key], marker="s", ls="--",
                    label=f"N0 control x={n0[0]:g}")
        if key == "vave_dB":
            ax.axhline(-6, color="r", ls=":", label="−6 dB")
            ax.axvline(args.target_mhz, color="gray", ls=":", label=f"{args.target_mhz:g} MHz")
        ax.set_xlabel("freq (MHz)"); ax.set_ylabel(label); ax.grid(alpha=.3); ax.legend(fontsize=8)
        fig.tight_layout(); fig.savefig(out_dir / "figures" / fname, dpi=140); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    for k in picks:
        ax.plot(curves[k]["freqs"] / 1e6, curves[k]["zin1_r"], marker="o", label=f"Re x={k[0]:g},N={k[1]}")
        ax.plot(curves[k]["freqs"] / 1e6, curves[k]["zin1_x"], marker="x", ls="--", label=f"Im x={k[0]:g},N={k[1]}")
    ax.set_xlabel("freq (MHz)"); ax.set_ylabel("Zin1 (Ohm)"); ax.grid(alpha=.3); ax.legend(fontsize=7)
    fig.tight_layout(); fig.savefig(out_dir / "figures" / "curve_Zin1.png", dpi=140); plt.close(fig)

    # ---- 报告 06 ----
    L = ["# 粗扫结果分析（单元模型 · 结构筛选）", ""]
    L.append(f"- 输入：`{args.csv}`（编码 {enc}，分隔符 {delim}，{len(rows)} 行，{len(combos)} 组合）")
    L.append(f"- 批次：`{prov['batch_label']}`｜模型 `{args.model_file or '(未声明)'}`"
             f"｜`{args.model_version}`｜模型 sha256 `{args.model_sha256[:16] or '(未提供)'}`")
    L.append(f"- 数据 csv sha256：`{prov['source_csv_sha256']}`")
    L.append(f"- 驱动口径：`{args.drive_mode}`")
    _pk = (f"（sha256 `{precheck_sha[:16]}…`，载入 {prov['precheck_combos_loaded']} 组合）"
           if precheck_sha else "（**未提供**）")
    L.append(f"- 几何/选择预检：`{prov['precheck_file'] or '(未提供)'}`{_pk}")
    L.append(f"- 排名口径：{note_rank}")
    L.append(f"- 归一化：幅值 `20log10`、功率 `10log10`（不混用）；−6 dB 交点用相邻点线性插值。")
    L.append("")
    L.append("## 1. 文献/模型基准")
    if base:
        L.append(f"- (x_scale={base['x_scale']}, N_w_te1={base['N_w_te1']})："
                 f"`Vave` −6 dB FBW = {base['FBW_Vave_percent']}%，"
                 f"15–25 MHz 平坦度 = {base['flatness_15_25_dB']} dB，"
                 f"Vave@20MHz = {base['Vave_20MHz']}")
    else:
        L.append("- ⚠️ **基准组合不在数据中**；按指令 §7，不得用最近组合冒充基准。")
    L.append("")
    L.append("## 2. 多指标 top-10（不做无依据加权总分）")
    for key, items in tops.items():
        L.append(f"### {key}")
        L.append("")
        L.append("| x_scale | N_w_te1 | 值 | precheck |")
        L.append("|---|---|---|---|")
        for s in items:
            L.append(f"| {s['x_scale']:g} | {s['N_w_te1']} | {s[key]:.6g} | {s['precheck_class']} |")
        L.append("")
    L.append("## 3. Pareto 非支配候选（FBW↑、Vave@20MHz↑、Ptot@20MHz↑、平坦度↓）")
    L.append("")
    if pareto_rows:
        L.append("| x_scale | N_w_te1 | FBW_Vave% | Vave@20MHz | Ptot@20MHz | flatness15–25 | precheck |")
        L.append("|---|---|---|---|---|---|---|")
        for s in pareto_rows:
            L.append(f"| {s['x_scale']:g} | {s['N_w_te1']} | {s['FBW_Vave_percent']:.3g} | "
                     f"{s['Vave_20MHz']:.4g} | {s['Ptot_20MHz_W']:.4g} | "
                     f"{s['flatness_15_25_dB']:.3g} | {s['precheck_class']} |")
    else:
        L.append("（无可计算组合）")
    L.append("")
    L.append(f"## 4. 建议精扫的 {len(plan)} 组（{freq_desc}）")
    L.append("")
    for p in plan:
        L.append(f"{p['order']}. **x_scale={p['x_scale']:g}, N_w_te1={p['N_w_te1']}**（{p['role']}）—— {p['reason']}")
    L.append("")
    L.append("## 5. 必须随结论声明的限制")
    L.append("")
    L.extend([
        "- 本报告只描述**机械响应**（`Vave`）与**发射声功率**（`Ptot`）的带宽；**不得**称为往返/脉冲回波/阵列带宽；",
        "- 5 MHz 步长的粗网格下，−6 dB 交点为插值估计，仅为**粗筛**；",
        "- 未提供几何/选择预检时，排名为**临时**结果；",
        "- `Zin2` 存在已知公式错误（`=v0/I01`），本报告不使用 `Zin2`；",
        "- 单 PMUT 单元模型结论**不得**外推为阵列性能；",
    ])
    if any(s["Ptot_has_negative"] for s in summaries):
        L.append("- ⚠️ 存在 `Ptot` 负值组合：可能来自积分面法向问题，已在 `03_` 表中标记 `Ptot_has_negative`。")
    (out_dir / "06_final_comparison.md").write_text("\n".join(L), encoding="utf-8")

    print(f"\n输出目录：{out_dir}")
    for p in sorted(out_dir.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(out_dir)}  ({p.stat().st_size/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
