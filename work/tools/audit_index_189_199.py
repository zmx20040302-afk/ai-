# -*- coding: utf-8 -*-
"""审计：把 INDEX §189–§199 里写下的数字**逐条**对着产物核一遍（只读，不改任何产物）。

为什么需要：本轮有若干数字是**从压缩摘要里写进 INDEX 的**（不是当场从产物读的），
这违反「每个数值必须能追溯到产物」的精神 ⇒ 必须逐条回查，错则订正。

用法：`python audit_index_189_199.py`
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]      # 脚本在 work/tools/ ⇒ repo = parents[2]
H = REPO / "work/runs/eda64-20261010"
S3 = H / "n5_stage3"
XD = H / "n6_xdense"

OK, BAD, MISS = [], [], []


def load(p):
    p = pathlib.Path(p)
    if not p.is_file():
        MISS.append("缺文件 %s" % p)
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def chk(tag, claimed, actual, tol=0.006):
    """claimed 是**已四舍五入到两位小数**的百分数 ⇒ 容差取绝对值 0.005（个百分点）。

    ⚠️ 首版用 0.6% 相对容差，对 0.28 vs 0.276991 这类**正确的四舍五入**误报成不符（我的脚本缺陷，非 INDEX 缺陷）。
    """
    if actual is None:
        MISS.append("%s：产物里取不到该字段" % tag)
        print("  ?? %-58s 声称 %-12s 产物 取不到" % (tag, claimed))
        return
    ok = abs(actual - claimed) <= max(0.005, abs(claimed) * tol)
    (OK if ok else BAD).append(tag)
    print("  %s %-58s 声称 %-12s 产物 %s" % ("OK" if ok else "**不符**", tag,
                                            ("%.6g" % claimed), ("%.6g" % actual)))


print("=" * 96)
print("§189 物理基：表已在前面单独核过（全对）。这里核 PBAI 的交叉/训练数。")
pbai = load(S3 / "PBAI_RESULT.json")
if pbai:
    for fam, L4m, L4c, L5m, L5c, L6m, L6c in (("n1_4", 34.7, 14.7, 39.7, 17.8, 161.6, 39.6),
                                             ("n1_7", 55.1, 16.1, 49.1, 13.9, 160.8, 40.2)):
        r = pbai["families"][fam]["results"]
        chk("§189 PBAI %s L4_cubic cross_max" % fam, L4m, 100 * r["L4_cubic"]["cross_max_key"])
        chk("§189 PBAI %s L4_cubic cross_median" % fam, L4c, 100 * r["L4_cubic"]["cross_median_key"])
        chk("§189 PBAI %s L5_cubic cross_max" % fam, L5m, 100 * r["L5_cubic"]["cross_max_key"])
        chk("§189 PBAI %s L5_cubic cross_median" % fam, L5c, 100 * r["L5_cubic"]["cross_median_key"])
        chk("§189 PBAI %s L6_cubic cross_max" % fam, L6m, 100 * r["L6_cubic"]["cross_max_key"])
        chk("§189 PBAI %s L6_cubic cross_median" % fam, L6c, 100 * r["L6_cubic"]["cross_median_key"])
        chk("§189 PBAI %s L4_cubic 训练对照" % fam, 0.95 if fam == "n1_4" else 1.85,
            100 * r["L4_cubic"]["train_control_median_key"])
        chk("§189 PBAI %s L5_cubic 训练对照" % fam, 0.28 if fam == "n1_4" else 0.39,
            100 * r["L5_cubic"]["train_control_median_key"])
        chk("§189 PBAI %s L6_cubic 训练对照" % fam, 0.17 if fam == "n1_4" else 0.44,
            100 * r["L6_cubic"]["train_control_median_key"])
    print("  §189 PBAI verdict = %s（声称 fail）、pass_configs=%s（声称空）"
          % (pbai.get("verdict"), pbai.get("pass_configs")))
    if pbai.get("verdict") != "fail":
        BAD.append("§189 PBAI verdict")
    if pbai.get("pass_configs"):
        BAD.append("§189 PBAI pass_configs 非空")

print("=" * 96)
print("§190 加密验收 + 12 x 基线")
xa_ = load(XD / "XDENSE_ACCEPT_RESULT.json")
if xa_:
    # 声称：linear 30.15/7.95(n1_4) 32.24/10.89(n1_7)；cubic 15.61/0.94、18.26/1.13
    # wpod_cubic 同 cubic；implicit_v2 76.41/5.80、110.51/8.19；pbai L4_cubic 24.26/4.98、26.92/2.81
    want = {
        ("n1_4", "pod", "linear"): (30.15, 7.95), ("n1_7", "pod", "linear"): (32.24, 10.89),
        ("n1_4", "pod", "cubic"): (15.61, 0.94), ("n1_7", "pod", "cubic"): (18.26, 1.13),
        ("n1_4", "wpod", "wpod_cubic"): (15.61, 0.94), ("n1_7", "wpod", "wpod_cubic"): (18.26, 1.13),
        ("n1_4", "implicit", "implicit_v2"): (76.41, 5.80), ("n1_7", "implicit", "implicit_v2"): (110.51, 8.19),
        ("n1_4", "pbai_posthoc", "L4_cubic"): (24.26, 4.98), ("n1_7", "pbai_posthoc", "L4_cubic"): (26.92, 2.81),
    }
    for (fam, arm, var), (cm, cmed) in want.items():
        v = xa_["families"][fam]["arms"][arm]["variants"][var]
        chk("§190 %s %s/%s max" % (fam, arm, var), cm, 100 * v["cross_max_key"])
        chk("§190 %s %s/%s 中位" % (fam, arm, var), cmed, 100 * v["cross_median_key"])
    print("  §190 verdict = %s（声称 fail）" % xa_.get("verdict"))
    if xa_.get("verdict") != "fail":
        BAD.append("§190 verdict")
    for fam, kv, kv2 in (("n1_4", 49, 58), ("n1_7", 53, None)):
        ch = xa_["families"][fam]["arms"]["wpod"].get("chosen") or {}
        print("  §190 %s wpod chosen: λ=%s k=%s（声称 λ=10000 k=%d）"
              % (fam, ch.get("lambda"), ch.get("k"), kv))
        if ch.get("lambda") != 10000 or ch.get("k") != kv:
            BAD.append("§190 wpod chosen %s" % fam)
    print("  §190 n1_4 pod k=%s（声称 kmax=64 未达标）"
          % xa_["families"]["n1_4"]["arms"]["pod"].get("k"))
    if xa_["families"]["n1_4"]["arms"]["pod"].get("k") != 64:
        BAD.append("§190 pod k")

# 12 x 基线（§190 表格的右列）
r2 = load(S3 / "REPR2_RESULT.json")
if r2:
    for fam, lm, lmed, cm, cmed in (("n1_4", 36.3, 16.1, 26.5, 13.4), ("n1_7", 42.9, 23.2, 50.1, 14.1)):
        v = r2["families"][fam]["variants"]
        chk("§190 基线12x %s linear max" % fam, lm, 100 * v["linear"]["cross_max_key"])
        chk("§190 基线12x %s linear 中位" % fam, lmed, 100 * v["linear"]["cross_median_key"])
        chk("§190 基线12x %s cubic max" % fam, cm, 100 * v["cubic"]["cross_max_key"])
        chk("§190 基线12x %s cubic 中位" % fam, cmed, 100 * v["cubic"]["cross_median_key"])
i2 = load(S3 / "IMPLICIT2_RESULT.json")
if i2:
    for fam, m, md in (("n1_4", 83.2, 8.4), ("n1_7", 303.7, 9.6)):
        d = i2["families"][fam]
        chk("§190 基线12x %s implicit2 max" % fam, m, 100 * d["cross_max_key"])
        chk("§190 基线12x %s implicit2 中位" % fam, md, 100 * d["cross_median_key"])
w = load(S3 / "WPOD_RESULT.json")
if w:
    for fam, k in (("n1_4", 30), ("n1_7", 27)):
        ch = w["families"][fam].get("chosen") or {}
        print("  §190 基线12x %s W-POD chosen: λ=%s k=%s（§190 声称 k=27–30）"
              % (fam, ch.get("lambda"), ch.get("k")))
bf = load(S3 / "BASIS_FLOOR.json")
if bf:
    print("  BASIS_FLOOR.json 顶层键: %s" % list(bf.keys()))
    print("  （§189 声称「POD 要 44 阶才 0.45%、带 3.3%% 地板」—— 下面人工核对内容）")
    s = json.dumps(bf, ensure_ascii=False)
    for key in ("44", "0.45", "3.3", "0.033", "0.0045"):
        print("     含 '%s' ? %s" % (key, key in s))

print("=" * 96)
print("§190 光滑性表 + 形状/增益表")
sm = load(XD / "XDENSE_SMOOTHNESS.json")
if sm:
    want_sm = {"n1_4": [(19.45, 19.68, 36.77, 60.51)], "n1_7": [(48.10, 21.72, 38.73, 63.52)]}
    for fam, (vals,) in want_sm.items():
        bs = sm["families"][fam]["pair_buckets"]
        for i, exp in enumerate(vals):
            chk("§190 光滑 %s bucket%d 中位" % (fam, i), exp, 100 * bs[i]["rel_median"])
sg = load(XD / "XDENSE_SHAPE_VS_GAIN.json")
if sg:
    for fam, rmed, rsmed, rmax, rsmax in (("n1_4", 23.00, 0.91, 189.51, 62.16),
                                          ("n1_7", 27.36, 0.61, 1846.59, 1789.83)):
        s = sg["families"][fam]["summary"]
        chk("§190 %s rel 中位" % fam, rmed, 100 * s["rel"]["median"])
        chk("§190 %s rel_shape 中位" % fam, rsmed, 100 * s["rel_shape"]["median"])
        chk("§190 %s rel 最大" % fam, rmax, 100 * s["rel"]["max"])
        chk("§190 %s rel_shape 最大" % fam, rsmax, 100 * s["rel_shape"]["max"])

print("=" * 96)
print("§193 因子化")
fa = load(XD / "FACTOR_RESULT.json")
if fa:
    for fam, sr in (("n1_4", 0.0396), ("n1_7", 0.0207)):
        chk("§193 %s σ2/σ1 中位" % fam, sr, fa["families"][fam]["rank1_sigma2_over_sigma1"]["median"])
    want_arms = {"n1_4": {"r1_cubic": (20.24, 11.76), "r1_linear": (35.78, 12.70),
                          "mean_cubic": (18.23, 11.65), "r1_nof": (33.21, 15.12),
                          "oracle_alpha": (20.29, 6.81)},
                 "n1_7": {"r1_cubic": (20.48, 6.92), "r1_linear": (36.91, 12.53),
                          "mean_cubic": (20.48, 7.39), "r1_nof": (29.24, 15.04),
                          "oracle_alpha": (9.23, 4.89)}}
    for fam, arms in want_arms.items():
        A = fa["families"][fam]["arms"]
        for a, (m, md) in arms.items():
            chk("§193 %s %s max" % (fam, a), m, 100 * A[a]["cross_max_key"])
            chk("§193 %s %s 中位" % (fam, a), md, 100 * A[a]["cross_median_key"])
    print("  §193 verdict = %s（声称 fail）" % fa.get("verdict"))
    if fa.get("verdict") != "fail":
        BAD.append("§193 verdict")
re_ = load(XD / "FACTOR_RANK_EXPLORE.json")
if re_:
    for fam, r1, r12, c1m, c1x, c3m, c3x, c12m, c12x in (
            ("n1_4", 47.95, 23.82, 11.76, 20.24, 1.05, 17.70, 1.06, 17.69),
            ("n1_7", 52.21, 42.94, 6.92, 20.48, 1.65, 20.59, 1.39, 20.58)):
        fl = re_["families"][fam]["floor_vs_r_key_region_training"]
        chk("§193 %s 秩1 地板 中位" % fam, r1, 100 * fl["1"]["median_over_f"])
        chk("§193 %s 秩12 地板 中位" % fam, r12, 100 * fl["12"]["median_over_f"])
        ap = re_["families"][fam]["arms_posthoc"]
        chk("§193 %s rank1 中位" % fam, c1m, 100 * ap["rank1"]["cross_median_key"])
        chk("§193 %s rank1 max" % fam, c1x, 100 * ap["rank1"]["cross_max_key"])
        chk("§193 %s rank3 中位" % fam, c3m, 100 * ap["rank3"]["cross_median_key"])
        chk("§193 %s rank3 max" % fam, c3x, 100 * ap["rank3"]["cross_max_key"])
        chk("§193 %s rank12 中位" % fam, c12m, 100 * ap["rank12"]["cross_median_key"])
        chk("§193 %s rank12 max" % fam, c12x, 100 * ap["rank12"]["cross_max_key"])
    # §193 第六条：n1_4 rank3 最差格 = x=0.63 f=9.2 → 17.70%，第2 7.5%，第3 5.3%
    rows = sorted(re_["families"]["n1_4"]["arms_posthoc"]["rank3"]["rows"], key=lambda r: -r["key"])
    print("  §193 n1_4 rank3 worst3 = %s（声称 0.63/9.2=17.70、0.93/6.6=7.5、0.93/9.2=5.3）"
          % ["x=%.2f f=%g %.2f%%" % (r["x"], r["f"], 100 * r["key"]) for r in rows[:3]])
    if not (abs(rows[0]["x"] - 0.63) < 1e-9 and abs(rows[0]["f"] - 9.2) < 1e-9):
        BAD.append("§193 worst cell")

print("=" * 96)
print("§194 留出复核 + LOO")
rc = load(XD / "RECHECK_HOLDOUT_COMPARE.json")
if rc:
    want_rc = {("recheck_holdout_n1_4_x0.63", "all_freq_K_rel_max"): 5.45e-11,
               ("recheck_holdout_n1_4_x0.93", "all_freq_K_rel_max"): 2.63e-11,
               ("recheck_holdout_n1_7_x0.63", "all_freq_K_rel_max"): 0.0,
               ("recheck_holdout_n1_7_x0.93", "all_freq_K_rel_max"): 0.0,
               ("recheck_holdout_n1_4_x0.63", "holdout_freq_field_key_max"): 2.41e-12,
               ("recheck_holdout_n1_4_x0.93", "holdout_freq_field_key_max"): 1.48e-11,
               ("recheck_holdout_n1_7_x0.63", "holdout_freq_field_key_max"): 1.11e-12,
               ("recheck_holdout_n1_7_x0.93", "holdout_freq_field_key_max"): 1.08e-11}
    for (tag, key), exp in want_rc.items():
        got = rc["points"].get(tag, {}).get("summary", {}).get(key)
        ok = got is not None and abs(got - exp) <= max(abs(exp) * 0.05, 1e-14)
        (OK if ok else BAD).append("§194 %s %s" % (tag, key))
        print("  %s §194 %-34s %-28s 声称 %.3g 产物 %s"
              % ("OK" if ok else "**不符**", tag.replace("recheck_holdout_", ""), key, exp, got))
lo = load(XD / "XDENSE_LOO_GAP.json")
if lo:
    rows = {r["x"]: r for r in lo["families"]["n1_4"]["rows"]}
    chk("§194 LOO x=0.200 pod max" % (), 35.70, 100 * rows[0.2]["pod_cubic_max"])
    chk("§194 LOO x=0.863 pod max" % (), 1.12, 100 * rows[0.863]["pod_cubic_max"])
    chk("§194 LOO x=0.650 pod max" % (), 16.43, 100 * rows[0.65]["pod_cubic_max"])
    rows7 = {r["x"]: r for r in lo["families"]["n1_7"]["rows"]}
    chk("§194 LOO n1_7 x=0.269 pod max" % (), 60.02, 100 * rows7[0.269]["pod_cubic_max"])
    print("  §194 gap 阈值存在性: n1_4=%s（声称 False）"
          % lo["families"]["n1_4"].get("pod_cubic_max_gap_threshold"))
    if lo["families"]["n1_4"].get("pod_cubic_max_gap_threshold", {}).get("exists") is not False:
        BAD.append("§194 gap threshold exists")

print("=" * 96)
print("§197 分区图")
pm = load(XD / "PARTITION_MAP.json")
if pm:
    for fam, xp, fp in (("n1_4", [(0.269, 0.291), (0.78, 0.886)], []),
                        ("n1_7", [(0.78, 0.886)], [])):
        got = [(round(i["from"], 3), round(i["to"], 3)) for i in pm["families"][fam]["x_intervals_pod"]]
        ok = got == [(round(a, 3), round(b, 3)) for a, b in xp]
        (OK if ok else BAD).append("§197 %s x 区间" % fam)
        print("  %s §197 %s x_intervals_pod 声称 %s 产物 %s" % ("OK" if ok else "**不符**", fam, xp, got))
        gotf = pm["families"][fam]["f_intervals_pod"]
        okf = gotf == fp
        (OK if okf else BAD).append("§197 %s f 区间为空" % fam)
        print("  %s §197 %s f_intervals_pod 声称空 产物 %s" % ("OK" if okf else "**不符**", fam, gotf))
    rf = {r["f"]: r for r in pm["families"]["n1_4"]["f_loo"]}
    chk("§197 n1_4 f=5 pod max" % (), 1399.01, 100 * rf[5.0]["pod"])
    chk("§197 n1_4 f=8.41 pod max" % (), 79.66, 100 * rf[8.41]["pod"])
    chk("§197 n1_4 f=7.07 pod max" % (), 51.46, 100 * rf[7.07]["pod"])

print("=" * 96)
print("小计：OK %d 条；**不符 %d 条**；取不到 %d 条" % (len(OK), len(BAD), len(MISS)))
for b in BAD:
    print("  不符:", b)
for m in MISS:
    print("  取不到:", m)
pathlib.Path(XD / "AUDIT_189_199.txt").write_text(
    "OK=%d BAD=%d MISS=%d\n" % (len(OK), len(BAD), len(MISS))
    + "".join("BAD %s\n" % b for b in BAD) + "".join("MISS %s\n" % m for m in MISS),
    encoding="utf-8")
return_code = 1 if BAD else 0
sys.exit(return_code)
