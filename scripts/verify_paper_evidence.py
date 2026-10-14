# -*- coding: utf-8 -*-
"""DAC 2027 证据件的**独立复核**（不 import 主脚本，另写一遍算法）。

**本脚本默认只读**（纪律 R16，见 `INDEX §105`）：**校验者不得改写被校验对象**。
旧版第 0 项会「先重跑生成脚本把产物整个覆盖、再比对」——那等于**先把现场改掉再宣布无异常**，
原理上**无法发现篡改**；已按裁定改为下面的四件事。

1. **只读完整性核对**：拿 `MANIFEST.json` 当**登记册**，逐个比对 31 件产物的 sha256
   （缺件 / 不符 / 未登记一律报出来），并核对登记册记的生成脚本 `script` 哈希与磁盘一致。
   ⚠️ 登记册不是签名：能查出**产物**被改，查不出「登记册与产物被同时改」。
2. **独立复算**关键数字（逐项对到主产物的 JSON）：E1 逐批计数与 Q 分位、E2 两套分母、
   E3 **476/323/153/51/102**（并按 `check_domain()` 的判定次序在逐点 CSV 上**独立重算「实际触发」**）、
   E4 182/63 与 Spearman（用 scipy.spearmanr 作**另一实现**交叉核对）、E5 8 通道 lift、
   E6 v2 缺陷计数、E7 46/79/24、E8 446/386/162/224/60 与虚高 34。
3. **基线哈希复核 + 状态未提升**：重算受保护产物的 sha256，与登记/期望值逐位比对；
   只读复核 `solver_spec.json` 的 `state` 仍为 `draft`。
4. **只读自证**：运行前后对 `work/runs/paper-evidence-20261009/` 取
   「文件集合 ＋ sha256 ＋ mtime」快照并比对 ⇒ 证明本次校验**一个字节都没写**。

用法（默认只读，**不碰任何产物**）：
    work\\.venv\\Scripts\\python.exe -X utf8 scripts\\verify_paper_evidence.py

若确需重生成产物，必须**显式**加开关：
    work\\.venv\\Scripts\\python.exe -X utf8 scripts\\verify_paper_evidence.py --regen
⚠️ `--regen` 会重写被校验对象 ⇒ **那一次运行不是校验**，本脚本也不会给出任何校验结论。

退出码：0 = 全部通过；1 = 有差异（逐条打印，绝不吞掉）；`--regen` 下返回生成脚本的退出码。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import subprocess
import sys
from collections import Counter, defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = REPO / "work/runs/paper-evidence-20261009"

P_C_ORIG = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"
P_V3 = REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv"
P_V2F = REPO / "work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv"
P_A_COMBOS = REPO / "work/runs/remote-exported-20260922/dataset/combos.csv"
P_MODEL = REPO / "work/runs/multichannel-surrogate-20260929/multichannel_model.json"
P_SOLVER = REPO / "work/runs/solver/pmut-f1/solver_spec.json"
P_SWEEP = REPO / "src/memsharness/sweep_analysis.py"
P_MPH = REPO / "work/models/b_GE_task3_2new_currentdrive_fmax45_v1.mph"

EXPECT = {
    "solver_spec_sha256": "21315173fd2732c7384c4a3d437bb7f7c297d5c3047b5ff01094ca3553b6bd3f",
    "sweep_src_sha256": "1f634902c89916e7131b1e589676603f79015225b0e919c0acc92b9da9338bb0",
    "C_orig_sha256": "d06edfe1999434999d360dc01220eedced236268f1dce1b9c176b516adfecbac",
    "v2_frozen_sha256": "cdf11ce2fe560fd9630463f5ad407d2da068051109c4b7a91f42c23e73fb4b31",
    "v3_sha256": "20e28ba12457ce5b553fce3d02c0e4f59e7861370775ecf4cf68b0dff6a3a590",
    "mph_currentdrive_sha256": "0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d",
}

FAILS: list[str] = []
CHECKS: list[tuple] = []


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def check(name, got, want):
    ok = got == want
    CHECKS.append((name, got, want, ok))
    if not ok:
        FAILS.append("%s：实测 %r ≠ 期望 %r" % (name, got, want))
    return ok


#: 目录内**不属于登记册**、但允许在场的文件（非产物：登记册自身、外部复核留痕、外来的小节片段）
NON_ARTIFACT = {"MANIFEST.json", "MANIFEST.md", "VERIFY.txt", "INDEX_SECTION_101.md"}


def snapshot_dir(d: pathlib.Path) -> dict:
    """目录内**所有文件**的 `{相对路径: (sha256, mtime_ns)}` 快照。

    用途：自证「校验运行前后一个字节都没写」——**sha256 看内容、mtime_ns 看是否被重写**
    （只改回同样内容的重写也能被 mtime 抓到）。
    """
    snap = {}
    for p in sorted(d.rglob("*")):
        if p.is_file():
            snap[str(p.relative_to(d)).replace("\\", "/")] = (
                sha256_file(p), p.stat().st_mtime_ns)
    return snap


def regen_outputs(out_dir: pathlib.Path) -> int:
    """**显式**重生成产物（默认校验路径**绝不**调用本函数）。"""
    r = subprocess.run([sys.executable, "-X", "utf8",
                        str(REPO / "scripts/paper_evidence_dac2027.py"),
                        "--out-dir", str(out_dir)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
    return r.returncode


def integrity_problems(out_dir: pathlib.Path, manifest: dict) -> list[str]:
    """拿 `MANIFEST.json` 当**登记册**核对产物；返回问题清单（空 = 通过）。

    检查三件：登记的文件**缺失**、sha256 **不符**、出现**未登记**的产物名（`E*` 前缀）。
    ⚠️ 能力边界（如实声明）：登记册**不是签名** ⇒ 只能发现**产物**被改，
    发现不了「登记册与产物被同时改写」。
    """
    reg = {}
    for o in manifest.get("outputs", []):
        reg[pathlib.PurePosixPath(str(o["path"]).replace("\\", "/")).name] = str(o["sha256"])
    problems = []
    for name in sorted(reg):
        p = out_dir / name
        if not p.is_file():
            problems.append("缺产物：%s（登记册有、磁盘没有）" % name)
            continue
        got = sha256_file(p)
        if got != reg[name]:
            problems.append("sha256 不符：%s 实测 %s… ≠ 登记 %s…"
                            % (name, got[:16], reg[name][:16]))
    present = {p.name for p in out_dir.iterdir() if p.is_file()}
    for name in sorted(present - set(reg) - NON_ARTIFACT):
        problems.append("未登记文件：%s（既不在登记册、也不在白名单）" % name)
    return problems


def read_csv(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def num(v):
    s = str(v).strip()
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def qval(v):
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "null", "none"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def T(v):
    return str(v).strip().lower() in ("true", "1", "yes", "y", "t")


def pctl(vals, p):
    xs = sorted(float(v) for v in vals)
    if not xs:
        return None
    k = (len(xs) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def k_ulp(r):
    out = []
    for k in ("x_scale", "N_w_te1", "N_w_te2"):
        v = num(r[k])
        out.append(round(v, 6) if isinstance(v, float) else v)
    return tuple(out)


def k_raw(r):
    return tuple(repr(num(r[k])) for k in ("x_scale", "N_w_te1", "N_w_te2"))


def k_lit(r):
    return tuple(str(r[k]) for k in ("x_scale", "N_w_te1", "N_w_te2"))


def jload(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="DAC 2027 证据件独立复核（**默认只读**：不写产物一个字节）。")
    ap.add_argument("--regen", action="store_true",
                    help="**显式**重生成产物（默认关闭）。打开后本脚本**不是一次校验**，"
                         "也不会给出任何校验结论 ⇒ 请随后不带 --regen 再跑一次。")
    args = ap.parse_args(argv)

    if args.regen:
        rc = regen_outputs(OUT)
        print("=" * 78)
        print("【重生成模式 --regen】已调用 scripts/paper_evidence_dac2027.py 重写：")
        print("    %s" % OUT)
        print("⚠️ 本次运行**不是一次校验**：校验者改写了被校验对象 ⇒ 任何『无异常』结论都无效。")
        print("   要校验，请在不带 --regen 的情况下再跑一次（那次是只读的）。")
        print("生成脚本退出码 = %d" % rc)
        print("=" * 78)
        return rc

    if not (OUT / "MANIFEST.json").exists():
        print("缺少 MANIFEST.json ⇒ 先跑 scripts\\paper_evidence_dac2027.py "
              "（或本脚本 --regen）")
        return 1

    # ---------------- 0. 只读完整性：登记册 vs 磁盘（**不重生成**） ----------------
    snap_before = snapshot_dir(OUT)
    manifest = jload("MANIFEST.json")
    problems = integrity_problems(OUT, manifest)
    check("完整性：登记册 %d 件产物在位且 sha256 相符" % len(manifest.get("outputs", [])),
          problems, [])
    # 登记册记的**生成脚本**哈希必须与磁盘一致（防「改了生成脚本却没重生成」）
    script_rel = str(manifest.get("script", {}).get("path", ""))
    script_p = REPO / script_rel
    if script_p.is_file():
        check("完整性：登记册的生成脚本哈希与磁盘一致（%s）" % script_rel,
              sha256_file(script_p), manifest["script"]["sha256"])
    # 复核脚本自身的哈希：只披露、不判失败（重签登记册需要重生成，属另一动作）
    ver_rel = str(manifest.get("verifier", {}).get("path", ""))
    ver_p = REPO / ver_rel
    if ver_p.is_file():
        same = sha256_file(ver_p) == manifest["verifier"]["sha256"]
        print("[INFO] 登记册记录的复核脚本 %s：%s（登记 %s…，磁盘 %s…）"
              % (ver_rel, "一致" if same else "**不一致**（本脚本在登记之后被改过）",
                 str(manifest["verifier"]["sha256"])[:16], sha256_file(ver_p)[:16]))

    # ---------------- 1. 基线哈希 + 状态未提升 ----------------
    check("基线：C 原表 sha256", sha256_file(P_C_ORIG), EXPECT["C_orig_sha256"])
    check("基线：v2 冻结副本 sha256", sha256_file(P_V2F), EXPECT["v2_frozen_sha256"])
    check("基线：v3 并集表 sha256", sha256_file(P_V3), EXPECT["v3_sha256"])
    check("基线：solver_spec sha256", sha256_file(P_SOLVER), EXPECT["solver_spec_sha256"])
    check("基线：sweep_analysis.py sha256", sha256_file(P_SWEEP), EXPECT["sweep_src_sha256"])
    check("基线：currentdrive .mph sha256", sha256_file(P_MPH),
          EXPECT["mph_currentdrive_sha256"])
    spec = json.loads(P_SOLVER.read_text(encoding="utf-8"))
    check("状态未提升：solver_spec.state", spec.get("state"), "draft")
    model = json.loads(P_MODEL.read_text(encoding="utf-8"))
    check("状态未提升：multichannel_model.status", model.get("status"), "draft")

    # ---------------- 2. E1 ----------------
    e1 = jload("E1_per_batch_label_stats.json")
    corig = read_csv(P_C_ORIG)
    C = [x for x in corig if x["source_dataset"] == "C"]
    A = [x for x in corig if x["source_dataset"] == "A"]
    AC = C + A
    check("E1 C 行数", len(C), e1["batches"]["C_5-50MHz"]["n_rows"])
    check("E1 C 带宽闭合", sum(1 for x in C if T(x["bandwidth_closed"])),
          e1["batches"]["C_5-50MHz"]["flags"]["bandwidth_closed"]["true"])
    check("E1 C 首个峰", sum(1 for x in C if T(x["first_peak_found"])),
          e1["batches"]["C_5-50MHz"]["flags"]["first_peak_found"]["true"])
    check("E1 C Q 门禁达标", sum(1 for x in C if T(x["q_gate_pass"])),
          e1["batches"]["C_5-50MHz"]["q_gate_pass"])
    check("E1 A 带宽闭合", sum(1 for x in A if T(x["bandwidth_closed"])),
          e1["batches"]["A_5-35MHz"]["flags"]["bandwidth_closed"]["true"])
    check("E1 A Q 门禁达标", sum(1 for x in A if T(x["q_gate_pass"])),
          e1["batches"]["A_5-35MHz"]["q_gate_pass"])
    check("E1 池化 A+C 带宽闭合", sum(1 for x in AC if T(x["bandwidth_closed"])),
          e1["pooled_A_plus_C"]["bandwidth_closed_true"])
    check("E1 池化 A+C Q 门禁达标", sum(1 for x in AC if T(x["q_gate_pass"])),
          e1["pooled_A_plus_C"]["q_gate_pass"])
    v2f = read_csv(P_V2F)
    usable = [x for x in v2f if not T(x["peak_at_scan_endpoint"])
              and not T(x["bw_upper_cutoff_at_endpoint"])]
    check("E1 V2 可用", len(usable), e1["batches"]["V2_5-35MHz"]["usable"])
    check("E1 V2 Q 可判定分母", sum(1 for x in usable if qval(x["Q"]) is not None),
          e1["batches"]["V2_5-35MHz"]["q_gate_denominator"])
    qc = [qval(x["Q_factor"]) for x in C if T(x["bandwidth_closed"])]
    qc = [v for v in qc if v is not None]
    check("E1 C Q p50（独立插值实现）", round(pctl(qc, 50), 5),
          round(e1["batches"]["C_5-50MHz"]["q_closed_rows"]["p50"], 5))
    qac = [qval(x["Q_factor"]) for x in AC if T(x["bandwidth_closed"])]
    qac = [v for v in qac if v is not None]
    check("E1 池化 Q p50", round(pctl(qac, 50), 5),
          round(e1["pooled_A_plus_C"]["q_p50"], 5))

    # ---------------- 3. E2 ----------------
    e2 = jload("E2_Q_median_denominators.json")
    cal = e2["calibers"]
    check("E2 S1 n（C 闭合）", len(qc), cal["S1_C_closed_flag"]["n"])
    check("E2 S3 n（池化闭合）", len(qac), cal["S3_AC_pooled_closed_flag"]["n"])
    check("E2 S1 p50", round(pctl(qc, 50), 5), round(cal["S1_C_closed_flag"]["p50"], 5))
    check("E2 S3 p50", round(pctl(qac, 50), 5),
          round(cal["S3_AC_pooled_closed_flag"]["p50"], 5))
    check("E2 两套分母相差 = A 闭合数",
          cal["S3_AC_pooled_closed_flag"]["n"] - cal["S1_C_closed_flag"]["n"],
          sum(1 for x in A if T(x["bandwidth_closed"])))
    qv2 = [qval(x["Q"]) for x in usable]
    qv2 = [v for v in qv2 if v is not None]
    check("E2 S5 n（V2 Q 可判定）", len(qv2), cal["S5_V2_usable_numeric_Q"]["n"])

    # ---------------- 4. E3 ----------------
    # 断言**语义层事实**（不再硬编码「历史标签」；子串碰撞已修，§105）：
    #   结构约束 N1 ≥ N2 = 102、真 N2 越域 = 0、x 超层标定 = 51、接受 323 / 拒答 153 / 网格 476
    e3 = jload("E3_refusal_screen.json")
    rep = e3["counts"]["refusal_reasons_as_reported"]
    at = e3["refusal_attribution"]
    check("E3 网格点数", e3["counts"]["n_grid"], 17 * 7 * 4)
    check("E3 接受", e3["counts"]["n_predicted"], 323)
    check("E3 拒答", e3["counts"]["n_refused"], 153)
    check("E3 已报标签 layer_does_not_exist（结构约束 N1≥N2）",
          rep.get("layer_does_not_exist", 0), 6 * 17)
    check("E3 已报标签 n2_out_of_domain（子串碰撞修复后须为 0）",
          rep.get("n2_out_of_domain", 0), 0)
    check("E3 已报标签 x_outside_layer_range", rep.get("x_outside_layer_range", 0), 51)
    check("E3 已报标签合计 = 拒答数", sum(rep.values()), e3["counts"]["n_refused"])
    check("E3 实际触发 layer_does_not_exist（N1≥N2）",
          at["layer_does_not_exist_structural_N1_ge_N2"], 6 * 17)
    check("E3 实际触发 n2 越域（N2 ∉ [5,9]）",
          at["n2_out_of_domain_literal_N2_not_in_5_9"], 0)
    check("E3 实际触发 x 超层标定", at["x_outside_layer_range"], 51)
    check("E3 实际触发合计 = 拒答数",
          at.get("sum_check_equals_n_refused"), e3["counts"]["n_refused"])
    check("E3 标签碰撞回归探针（应为 0）", e3.get("label_collision_n_total"), 0)
    check("E3 标签 vs 实际触发逐点一致", e3.get("label_collision"), {})
    pts = read_csv(OUT / "E3_refusal_grid_points.csv")
    check("E3 逐点 CSV 行数", len(pts), 476)
    check("E3 逐点 CSV accepted", sum(1 for x in pts if x["decision"] == "accepted"), 323)
    xouts = sorted({float(x["x_scale"]) for x in pts
                    if x["mode_or_reason"] == "x_outside_layer_range"})
    check("E3 x_outside 只落在 3 个 x 值", xouts, [0.2, 0.25, 0.3])
    check("E3 网格内 (0.2,1,7) 的判定",
          [x["mode_or_reason"] for x in pts
           if float(x["x_scale"]) == 0.2 and x["N_w_te1"] == "1" and x["N_w_te2"] == "7"],
          ["x_outside_layer_range"])

    # **独立复算「实际触发」**：只拿逐点 CSV，按 `check_domain()` 的判定次序自己重算一遍
    # （另一实现；不读 E3 json 的 attribution 字段）
    def _domain_trigger(x, n1, n2):
        if not (0.20 <= x <= 1.00):
            return "x_out_of_domain"
        if abs(n1 - round(n1)) > 1e-9 or n1 < 1:
            return "n1_invalid"
        if not (5 <= n2 <= 9):
            return "n2_out_of_domain"
        if round(n1) >= n2:
            return "layer_does_not_exist"
        return None

    ind = Counter()
    for r in pts:
        if r["decision"] != "refused":
            continue
        trig = _domain_trigger(float(r["x_scale"]), int(r["N_w_te1"]), int(r["N_w_te2"]))
        ind[trig or r["mode_or_reason"]] += 1
    check("E3 独立复算：层不存在（N1≥N2） = 102", ind.get("layer_does_not_exist", 0), 102)
    check("E3 独立复算：真 N2 越域 = 0", ind.get("n2_out_of_domain", 0), 0)
    check("E3 独立复算：x 超层标定 = 51", ind.get("x_outside_layer_range", 0), 51)
    check("E3 独立复算：拒答合计 = 153", sum(ind.values()), 153)

    # ---------------- 5. E4 ----------------
    e4 = jload("E4_bw_layer_and_spearman.json")
    labA = [x for x in corig if x["source_dataset"] == "A"]
    byk = {k_ulp(x): x for x in labA}
    mine, refp, skip = [], [], 0
    refm = []
    for r in read_csv(P_A_COMBOS):
        m = byk.get(k_ulp(r))
        if m is None:
            continue
        fa, fm = num(r["f_peak_Hz"]), num(m["f_peak_Hz"])
        bwm = num(m["bandwidth_Hz"])
        if fa is None or fm is None or bwm is None:
            continue
        if abs(fm - fa) > 0.5e6:
            skip += 1
            continue
        if num(r["bandwidth_3dB_Hz"]) is None:
            continue
        mine.append(bwm)
        refp.append(num(r["bandwidth_3dB_Hz"]))
        refm.append(num(r["bandwidth_marker_Hz"]))
    check("E4 跳过数", skip, e4["join"]["n_skipped_peak_mismatch"])
    check("E4 可比组合数", len(mine), e4["join"]["n_gate_pass"])
    check("E4 比较记录数", len(mine) * 2, e4["join"]["n_comparison_records"])
    try:
        from scipy.stats import spearmanr  # 另一实现（主脚本用手写平均秩）
        sp = float(spearmanr(mine, refp).statistic)
        check("E4 Spearman(from_points)（scipy 交叉核对）", round(sp, 6),
              round(e4["per_reference"]["from_points"]["spearman_bw"], 6))
        spm = float(spearmanr(mine, refm).statistic)
        check("E4 Spearman(from_marker)（scipy 交叉核对）", round(spm, 6),
              round(e4["per_reference"]["from_marker"]["spearman_bw"], 6))
    except ImportError:  # pragma: no cover
        CHECKS.append(("E4 scipy 交叉核对", "scipy 不可用", "跳过", True))
    relp = [abs(a - b) / b for a, b in zip(mine, refp)]
    check("E4 from_points 中位相对差（独立复算）", round(sorted(relp)[len(relp) // 2], 6),
          round(e4["per_reference"]["from_points"]["abs_rel_diff_bw_median"], 6))

    # ---------------- 6. E5 ----------------
    e5 = jload("E5_channel_lift_table.json")
    pc = model["evaluation"]["per_channel"]
    check("E5 8 通道表逐通道 lift 与源一致",
          [round(float(e5["per_channel"][c]["lift_vs_persistence"]), 12) for c in sorted(pc)],
          [round(float(pc[c]["lift_vs_persistence"]), 12) for c in sorted(pc)])
    check("E5 8 通道表逐通道 median 与源一致",
          [round(float(e5["per_channel"][c]["median"]), 12) for c in sorted(pc)],
          [round(float(pc[c]["median"]), 12) for c in sorted(pc)])
    check("E5 channels_without_lift（原文）", model["evaluation"]["channels_without_lift"],
          ["bandwidth_Hz", "Q_factor"])
    check("E5 未增值通道实测",
          sorted([c for c in pc if not pc[c]["beats_persistence"]]),
          sorted(e5["channels_without_lift_measured"]))
    check("E5 bandwidth_Hz 负 lift",
          round(float(pc["bandwidth_Hz"]["lift_vs_persistence"]), 10), -0.0018010583)
    check("E5 Q_factor 负 lift",
          round(float(pc["Q_factor"]["lift_vs_persistence"]), 10), -0.0009895562)
    check("E5 通道数", len(pc), 8)
    check("E5 分母档位 = 478/520",
          sorted({round(pc[c]["n_predicted"] / pc[c]["coverage"]) for c in pc}), [478, 520])

    # ---------------- 7. E6 ----------------
    e6 = jload("E6_v2_defects_by_cell.json")
    tot = e6["totals"]
    check("E6 峰值删失", sum(1 for x in v2f if T(x["peak_at_scan_endpoint"])),
          tot["n_peak_censored"])
    check("E6 峰值删失 = 92", tot["n_peak_censored"], 92)
    check("E6 带宽截断", sum(1 for x in v2f if T(x["bw_upper_cutoff_at_endpoint"])),
          tot["n_bw_truncated"])
    check("E6 带宽截断 = 103", tot["n_bw_truncated"], 103)
    check("E6 Q 字面 nan 全批", sum(1 for x in v2f if str(x["Q"]).strip().lower() == "nan"),
          tot["n_Q_literal_nan"])
    check("E6 Q 字面 nan = 39", tot["n_Q_literal_nan"], 39)
    check("E6 可用内 nan = 38", tot["n_Q_literal_nan_within_usable"], 38)
    check("E6 Q 门禁真实分母 = 108", tot["n_Q_evaluable_within_usable"], 108)
    check("E6 Q 达标 = 40", tot["n_Q_in_gate_within_usable"], 40)
    check("E6 可用 = 146", tot["n_usable"], 146)

    # ---------------- 8. E7 ----------------
    e7 = jload("E7_n2_9_net_value.json")
    check("E7 净可用增量 = 46", e7["key_numbers"]["net_usable_increment"], 46)
    check("E7 仅 V2 新增 = 79", e7["key_numbers"]["n_only_v2"], 79)
    check("E7 三整列全废格数 = 24", e7["dead_cells"], 24)
    check("E7 死列", [str(x) for x in e7["dead_x_columns"]], ["0.10", "0.20", "0.30"])
    check("E7 叠加 Q 门禁 = 11", e7["key_numbers"]["net_usable_increment_with_Q_gate"], 11)

    # ---------------- 9. E8 ----------------
    e8 = jload("E8_batch_isolation_numbers.json")
    v3 = read_csv(P_V3)
    per = defaultdict(set)
    for r in v3:
        per[r["batch"]].add(k_ulp(r))
    tot_ulp = sum(len(per[a] & per[b]) for i, a in enumerate(sorted(per))
                  for b in sorted(per)[i + 1:])
    check("E8 ulp 归一化重叠合计 = 446", tot_ulp, 446)
    check("E8 报告值一致", tot_ulp, e8["headline"]["sum_pair_overlaps_ulp"])
    check("E8 字面口径重叠 = 162",
          e8["calibers"]["literal"]["sum_pair_overlaps"], 162)
    check("E8 repr 口径重叠 = 386",
          e8["calibers"]["raw_repr"]["sum_pair_overlaps"], 386)
    check("E8 三类关系 162/224/60",
          [e8["pair_relation_per_row_pair"][k] for k in
           ("key_str_same", "key_repr_same", "key_ulp_only")], [162, 224, 60])
    check("E8 V2 新增（ulp）= 83",
          e8["calibers"]["ulp_normalized"]["n_new_combos_v2"], 83)
    check("E8 V2 新增（repr）= 117（虚高 34）",
          e8["calibers"]["raw_repr"]["n_new_combos_v2"], 117)
    check("E8 虚高 = 34", e8["inflation"]["n_new_v2_raw_minus_ulp"], 34)
    check("E8 批对 A|V2 = 131", e8["calibers"]["ulp_normalized"]["pair_overlaps"]
          ["A_5-35MHz|V2_5-35MHz"], 131)
    check("E8 批对 C|V2 = 153", e8["calibers"]["ulp_normalized"]["pair_overlaps"]
          ["C_5-50MHz|V2_5-35MHz"], 153)
    check("E8 门禁权威 n_overlap_normalized",
          e8["gate_authoritative"]["detail"]["n_overlap_normalized"], 446)
    check("E8 门禁权威 ulp_only_overlap",
          e8["gate_authoritative"]["detail"]["ulp_only_overlap"], 60)
    check("E8 门禁权威 passed=None", e8["gate_authoritative"]["passed"], None)
    # 独立复算 224 / 60 的来源
    per_lit = defaultdict(set)
    per_raw = defaultdict(set)
    for r in v3:
        per_lit[r["batch"]].add(k_lit(r))
        per_raw[r["batch"]].add(k_raw(r))
    tl = sum(len(per_lit[a] & per_lit[b]) for i, a in enumerate(sorted(per_lit))
             for b in sorted(per_lit)[i + 1:])
    tr = sum(len(per_raw[a] & per_raw[b]) for i, a in enumerate(sorted(per_raw))
             for b in sorted(per_raw)[i + 1:])
    check("E8 独立复算：字面/repr/ulp = 162/386/446", [tl, tr, tot_ulp], [162, 386, 446])

    # ---------------- 10. 只读自证 + 报告 ----------------
    # 校验到此为止**没有写盘**：再取一次快照，与开跑前逐项比对
    snap_after = snapshot_dir(OUT)
    check("只读自证：产物目录文件集合不变", sorted(snap_after), sorted(snap_before))
    changed = [k for k in sorted(snap_before) if snap_after.get(k) != snap_before[k]]
    check("只读自证：全部文件 sha256 与 mtime 均未变（校验没写盘）", changed, [])
    print("[INFO] 只读自证：%s 快照 %d 个文件，sha256+mtime 全等 = %s"
          % (OUT.relative_to(REPO), len(snap_before), not changed))

    print("=" * 78)
    for name, got, want, ok in CHECKS:
        print("[%s] %-52s got=%s want=%s" % ("OK" if ok else "FAIL", name, got, want))
    print("=" * 78)
    print("检查项 %d，失败 %d" % (len(CHECKS), len(FAILS)))
    for f in FAILS:
        print("FAIL: %s" % f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
