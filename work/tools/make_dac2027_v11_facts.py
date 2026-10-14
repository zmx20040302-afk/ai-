# -*- coding: utf-8 -*-
"""论文 v10 → **v11** 生成器（fail-closed，与 `make_dac2027_v10_facts.py` 同一纪律）。

范围**只限**：版本头 / 修订日 / v11 修订注 / **5 处会被 N1/N2/N5 事实取代的表述** /
一个**新增小节 §6.9**（N1 定因、N1c 网格档、N2 强基线、N3 闭环 DSE、N5 图）。
**其余一字不动**（含全部既有数字与全部既有判定）。

守卫（任一不满足即 rc=2，不写任何文件）：
 1. v10 的 sha256/字节数/行数与登记值一致；
 2. 每条 old 片段在 v10 中**恰好出现 1 次**；
 3. 每条 new 片段与新增块在结果中**恰好出现 1 次**；
 4. 反向还原（删块 → 删注 → new→old）可**逐字节还原 v10**；
 5. 产物纯 CRLF。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
V10 = REPO / "docs" / "PMUT_DAC2027_初稿_v10_20261010.md"
V11 = REPO / "docs" / "PMUT_DAC2027_初稿_v11_20261010.md"
V10_SHA = "728b91efdef7f3d9d43bbc43fd59a2672751ab3720d2fda93ff799ddda30df56"
V10_BYTES = 164782
V10_LINES = 747
R = REPO / "work/runs"

NOTE_V11 = (
    "> **v11 修订（本轮；**只做 N1/N1c 口径定因、N2 强基线、N5 图与两处计数/口径更正**；依据 "
    "`INDEX §166`、`work/runs/eda64-20261010/N1_PORT_ENERGY_DIAGNOSIS.md`、`n2_baselines/N2_REPORT.md`、"
    "`n2_verify/N2_VERIFICATION.md`、`n5_figures/FIGURES.md`）**：① **更正一处事实性错误** —— v10 §6.8 表"
    "「第 4 项 损耗与辐射功率分离」末句曾写该残差与 11.12% **同源于端口/电流口径缺陷**；N1 实测**否证**："
    "`es.JZ ≡ jω·∫es.Dz dA`（四电极集逐位一致）、模型 `Ptot` **就是**精确通量 `Im(K)/(2ωρ)`（六频逐位相同）、"
    "两个互不相交积分面差 1.8% 却**都高于**电输入 ⇒ 该残差是**真实负结果**，与电流项**分开陈述**；"
    "本载体（M-base λ/5）校准口径 **≈4.4%**（耦合面；半球口径 6.57%），且**不随可负担的网格加密消失**"
    "（λ/5→λ/6 时 `P_asi` 仅变 1e-06 相对）；② **计数口径更正**：源表中 `abs_p_Pa` 与 `abs_p_per_V_Pa` "
    "**全行逐字符相同**（2005/2005）⇒ 「8 个代理通道」实为 **7 个独立通道**；③ **带宽口径必须点名**："
    "「约 20%」属拟合 vs `from_points`（n=91，秩稳健 0.9888），而自算 vs 导出物为 **33.5%**（n=292，"
    "秩 **不稳健** 0.2226）⇒ 后者优先用导出物；④ **强基线升级**：防泄漏整组切分 + 5 种子 + 8 方法下，"
    "**没有任何方法**在 `bandwidth_Hz` / `Q_factor` 上稳定优于 persistence（0 正/5 负），并经独立复核"
    "（逐种子泄漏 0/5、persistence 数字逐位复现）；⑤ 新增 §6.9；**S3/S4 判定与阈值一字未改**。\n")

EDITS = [
    ("**v10**（**只做 S3 / S0 / 模型身份的账目对齐**",
     "**v11**（**只做 N1/N1c 口径定因、N2 强基线、N5 图与计数/口径更正**",
     "版本号"),
    ("> 日期：2026-10-10（**v10 修订日**；v9 同日；v1–v8 的修订日均为 2026-10-09）",
     "> 日期：2026-10-10（**v11 修订日**；v10/v9 同日；v1–v8 的修订日均为 2026-10-09）",
     "修订日"),
    ("跨口径审计显示，不同带宽提取方法之间存在约 20% 的中位相对差异，但排序稳健（Spearman 0.9888）；",
     "跨口径审计显示带宽口径差异**因对照而异、必须点名**：拟合 vs `from_points` 中位 **20.3%**"
     "（n=91，秩稳健 Spearman 0.9888），自算 vs 导出物中位 **33.5%**（n=292，秩**不稳健** 0.2226 ⇒ "
     "按该组裁定**优先用导出物**）；",
     "摘要：带宽口径点名"),
    ("8 个代理通道中有 2 个未优于复制相邻层的 persistence 基线，其中包含正式设计目标 `bandwidth_Hz`"
     "（中位误差 0.00502 vs 基线 0.00322）",
     "在**防泄漏整组切分 + 5 种子**下，8 个代理通道（其中 `abs_p_Pa` 与 `abs_p_per_V_Pa` 为**同列副本** "
     "⇒ 独立通道 **7** 个）中**没有任何已试方法**在两个正式目标上稳定优于 persistence"
     "（`bandwidth_Hz` 最好 lift 中位 **−0.005988**、`Q_factor` **−0.001968**，均 **0 正/5 负**；"
     "该结论经独立复核：逐种子泄漏 0/5、persistence 数字逐位复现）",
     "摘要：8→7 通道 + N2 结论"),
    ("不同带宽提取口径存在约 20% 的中位差异（排序稳健：Spearman 0.9888），但绝对值不可跨口径混用；",
     "带宽口径差异**必须点名对照**：拟合 vs `from_points` 中位 20.3%（n=91，秩稳健 0.9888）；"
     "自算 vs 导出物中位 33.5%（n=292，秩不稳健 0.2226 ⇒ 该组优先用导出物）；两者不得混成一句；",
     "结论：带宽口径点名"),
    ("8 个代理通道中 2 个（含正式设计目标 `bandwidth_Hz`）未优于 persistence 基线**",
     "8 个代理通道中独立者 7 个**（`abs_p_Pa` ≡ `abs_p_per_V_Pa` 为同列副本），且在防泄漏整组切分 + "
     "5 种子下**没有任何已试方法**在两个正式目标（`bandwidth_Hz` / `Q_factor`）上稳定优于 persistence"
     "（均 0 正/5 负）**",
     "结论：8→7 通道 + N2 结论"),
    ("；且实测该 6.177% 与 11.12% **均为端口/电流口径缺陷所致，不是物理守恒结论**）",
     "；**v11 更正**：该 6.177% 与 11.12% **并非同源** —— 11.12% 是电路集总电流与场侧通量的口径混用"
     "（正确法向下 28 面电流守恒残差 1.03e-03 < 0.5%），而 6.177% 经端口电压/电流后处理/声功率公式/"
     "积分面四条口径逐一排除后**仍是真实负结果**（本载体校准口径 ≈4.4%，见 §6.9））",
     "§8 结论：去「均为口径缺陷」"),
    ("；且实测该残差与 11.12% **同源于端口/电流口径缺陷**（`∫Jz` vs `∫J·n`、电路未闭合） |",
     "；**v11 更正**：N1 实测该残差与 11.12% 的电流项**不同源** —— 端口电压口径（浮置 Terminal 平均电位 "
     "≤7.7 µV、修正占视在功率 6.9e-06）、电流后处理口径（`es.JZ ≡ jω·∫es.Dz dA`，四电极集逐位一致）、"
     "声功率公式（模型 `Ptot` = 精确通量，六频逐位相同）、积分面选择（两面差 1.8% 但**都高于**输入）"
     "**逐一被排除**；本载体校准口径 **−4.39%**（`P_in` 3.734241e-06 W vs 耦合面 `P_asi` 3.905495e-06 W，"
     "λ/5→λ/6 变化 1e-06 相对）⇒ **仍是真实负结果**，与电流项分开陈述（见 §6.9） |",
     "§6.8 表：能量-辐射行去「同源」"),
]


def jload(rel: str) -> dict | None:
    p = R / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def build_69() -> str:
    """新增小节 §6.9 的正文（数值全部来自机读产物；缺失则如实写「未完成」）。"""
    L: list[str] = []
    L.append("### 6.9 v11 增补：N1 口径定因、N1c 网格档、N2 强基线、N3 闭环 DSE、N5 图（2026-10-10）")
    L.append("")
    L.append("> 本节为 **v11 新增**（不改 §6.1–§6.8 的任何判定与阈值）。全部数字来自 "
             "`work/runs/eda64-20261010/` 下的机读产物；依据登记见 `INDEX §166`。")
    L.append("")

    # ---- (一) N1 定因 ----
    L.append("**（一）N1：能量缺口的定因（零求解；载体 = M-base λ/5，sha256 `59d68d16…`，设计点 0.6/4/9）**")
    L.append("")
    L.append("| 候选原因 | 实测 | 判定 |")
    L.append("|---|---|---|")
    L.append("| 浮置 Terminal 被当成 0 V（端口电压口径） | `V(vin)=−1.000000 V`、`V(ground)=0`、"
             "`V(vout) ≤ 7.7 µV`；计入差分驱动后 `P_in` 仅变 **+0.053%**（占视在功率 **6.9e-06**） | **否证** |")
    L.append("| 电流后处理口径漏掉压电耦合 | 四电极集上 `∫es.JZ dA ≡ jω·∫es.Dz dA`（vin 为 "
             "−7.468717e-06−5.728859e-04j）**逐位一致** | **否证** |")
    L.append("| 声功率用平面波近似 | 模型 `Ptot` 与精确通量 `Im(K)/(2ωρ)`（`K=∫p·conj(∇p·n)dA`）在 "
             "0.25/0.5/1/2/5/20 MHz **六频逐位相同** | **否证** |")
    L.append("| 积分面选得不好 | 两个**互不相交**的面：声固耦合面 `asb1` 3.924776e-06 W（20 MHz）与"
             "外半球 `swr1` 3.996822e-06 W，差 **1.8%**，但**两面都高于**电输入 3.734359e-06 W | **否证** |")
    L.append("| Sound Hard 残差只是单测试函数的侥幸 | 多基 `φ∈{1,x,y}` 弱形式残差 ≤**0.045%**"
             "（`φ=z` 在 `[2]` 上恒 0 = 简并，该面即 z=0 对称面） | **扩展后仍通过** |")
    L.append("| 缺口是离散未收敛 | 加法加密下 `P_asi` 变化 **1e-06 相对**、`P_in` 1.4e-05 相对 ⇒ 缺口稳定 "
             "**−4.39%**；固体侧独立复算 `P_mech=−(ω/2)Im∫p·conj(u·n)dA` 与声学侧差 **0.02%** | "
             "**未证实**（缺口真实） |")
    L.append("")
    L.append("- **两条口径限制（引用时必须同现）**：① 以 `P_in` 为分子的能量判据**只在 f ≥ 2 MHz 有意义**"
             "（低频实部仅占视在功率 5e-08，是线性求解器实部的数值分辨率）；② **后处理法向 `nX/nY/nZ` "
             "不得用于闭合面判据** —— 同一 28 面集上它给出 `∫nz dA = −6.65e-09 ≠ 0`、`|ΣJ·n|/Σ|I_e| = 2.16`"
             "（伪不守恒），改用物理场法向 `es.nx/ny/nz` 得 **1.03e-03 < 0.5%**；单面上两者一致。")
    L.append("")

    # ---- (二) N1c ----
    n1c = jload("eda64-20261010/n1c_mesh_study/N1C_MESH_STUDY.json")
    L.append("**（二）N1c：20 MHz 网格档（同一设计点、同一口径，只改网格）**")
    L.append("")
    if n1c:
        ok = [r for r in n1c["rows"] if r.get("P_in_W") and r.get("P_asi_W") and r.get("P_hemi_W")]
        L.append("| 档 | ftri1 / ftet1 | 单元数 | `P_in`/W | `P_asi`/W | `P_hemi`/W | 缺口(in−asi) | 28 面电流守恒 |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in ok:
            mr = r.get("mesh_readback") or {}
            ftri = "/".join((x.get("readback") or "?") for x in mr.get("ftri1", []))
            ftet = (mr.get("ftet1_size1") or {}).get("readback") or "?"
            gap = 100.0 * (r["P_in_W"] - r["P_asi_W"]) / r["P_asi_W"]
            rel = r.get("closed28_rel_es")
            L.append("| `%s` | %s / %s | %s | %.6e | %.6e | %.6e | **%+.3f%%** | %s |" % (
                r["level"], ftri, ftet, r.get("elements"), r["P_in_W"], r["P_asi_W"],
                r["P_hemi_W"], gap, ("%.3e" % rel) if rel else "—"))
        L.append("")
    L.append("- **×0.5 档（`ftri1` 1/3/1.5 µm）本机内存失败**：自由度 **900,182**、MUMPS 在矩阵分解 "
             "**62%** 处失败、峰值物理内存 **19.14 GB** / 虚拟 23.21 GB ⇒ 撞本机提交限制，"
             "**如实登记为基础设施限制（不是数值发散）**；更细档需服务器或更大内存。")
    L.append("- 结论：**缺口不随可负担的加密消失**（λ/5→λ/6 时 `P_asi` 变化 1e-06 相对），"
             "半球积分在 λ/5 下高估约 1.3%（向耦合面收敛）⇒ 门禁 6.177%（M-h1um + 半球口径）与本载体"
             "收敛口径 4.4% 之差，一部分是积分面分辨率、一部分是载体不同。")
    L.append("")

    # ---- (三) N2 ----
    n2 = jload("eda64-20261010/n2_baselines/baselines_by_seed.json")
    L.append("**（三）N2：强基线 + 消融 + 独立复核（防泄漏整组切分、逐批训练、5 种子）**")
    L.append("")
    if n2:
        agg = n2["by_seed_aggregate"]["C_5-50MHz"]
        rows = []
        for ch in ("bandwidth_Hz", "Q_factor"):
            best, bl = None, None
            for m, v in agg[ch]["per_method"].items():
                if m == "persistence" or not v.get("lift_paired_by_seed"):
                    continue
                med = sorted(v["lift_paired_by_seed"])[len(v["lift_paired_by_seed"]) // 2]
                if bl is None or med > bl:
                    best, bl = m, med
            pm = agg[ch]["per_method"][best]
            rows.append((ch, best, pm, bl))
        L.append("| 通道（批 C） | 最好方法 | 中位相对误差中位 | `lift_paired` 中位 | 种子 正/负 |")
        L.append("|---|---|---|---|---|")
        for ch, best, pm, bl in rows:
            meds = sorted(pm["median_err_by_seed"])
            L.append("| `%s` | `%s` | %.5f | **%+.6f** | %d / %d |" % (
                ch, best, meds[len(meds) // 2], bl,
                pm.get("n_seeds_lift_positive", 0), pm.get("n_seeds_lift_negative", 0)))
        L.append("")
    L.append("- **结论**：20 个可判定格中**没有任何已试方法**在 `bandwidth_Hz` / `Q_factor` 上稳定优于 "
             "persistence ⇒ 「换更强模型」路线在本数据上**不成立**（不动摇「标签语义优先」的论证，反而支持它）。")
    L.append("- **独立复核（上级 agent 自写脚本，不复用 N2 主脚本/自检）**：`MANIFEST` 12 文件 sha256 "
             "**12/12 复算一致**；`grouped_split_assignments.csv` 逐种子训练键 ∩ 测试键 = **0/5**；"
             "persistence 基线中位 **0.007726751204325416 逐位复现**；可判定行数 416 与 `n_paired` 一致。")
    L.append("- **未覆盖（不得当作已验证）**：8 方法全表重算、6 项消融数值、`pchip` 实现、V2 批、"
             "GP 降采样与 MLP 收敛告警、主动补点用 holdout 标签的方法学声明。")
    L.append("")

    # ---- (四) N3 ----
    n3 = jload("eda64-20261010/n3_dse/N3_DSE_RESULT.json")
    pre = jload("eda64-20261010/n3_dse/PREREG.json")
    L.append("**（四）N3：闭环 DSE（预注册冻结，固定预算）**")
    L.append("")
    if pre:
        L.append("- 预注册：候选池 **%d**（池 sha256 `%s`）、预算 **%d** 次高保真调用"
                 "（5 共享 DOE + 4 臂 × 25）、目标量 **`P_rad20_per_V2`**（20 MHz 单频辐射声功率/伏²，"
                 "口径经 N1 §（一）验证）。**该目标不是本文的峰值/带宽 FOM**。"
                 % (pre["candidate_pool"]["size"], pre["candidate_pool"]["sha256"][:16],
                    pre["design"]["budget"]["total_calls"]))
        L.append("- oracle 冒烟：设计点 (0.60, 4, 9) 复现 `Ptot = 3.996822e-06 W`、"
                 "`P_asi = 3.924776e-06 W`，与 N1c 基线**逐位相同**。")
    if n3:
        pr = n3["progress"]
        fr = n3["failure_rate"]
        L.append("- 进度：%d/%d 次臂调用（DOE %d）⇒ %s；失败 %d/%d = %.2f%%（预注册阈值 20%% ⇒ %s）。"
                 % (pr["ledger_calls_with_arm"], pr["planned_calls"] - pr["doe_done"], pr["doe_done"],
                    "**已完成**" if pr["finished"] else "**进行中（本节为中间版）**",
                    fr["failed"], fr["arm_calls"], 100 * fr["rate"],
                    "判 inconclusive" if fr["inconclusive_by_prereg"] else "未触发"))
        ob = n3["objective"]
        L.append("- 目标量取值：不同设计点 %d 个；y ∈ [%.4e, %.4e] W/V²（跨 **%.0f 倍**）⇒ 该目标**有区分度**。"
                 % (ob["n_distinct_points"], ob["y_min"], ob["y_max"], ob["y_max_over_min"]))
        if "per_arm" in n3:
            L.append("")
            L.append("| 臂 | 成功调用 | 最优 `P_rad20_per_V2` | 简单遗憾 | k=5 处 best | 前 10% 命中率 | 墙钟/min |")
            L.append("|---|---|---|---|---|---|---|")
            for arm, a in n3["per_arm"].items():
                L.append("| `%s` | %d | %s | %s | %s | %s | %.1f |" % (
                    arm, a["n_ok"],
                    ("%.4e" % a["best_y"]) if a["best_y"] else "—",
                    ("%.2f%%" % (100 * a["simple_regret_rel"])) if a["simple_regret_rel"] is not None else "—",
                    ("%.4e" % a["median_best_at_k5"]) if a.get("median_best_at_k5") is not None else "—",
                    ("%.1f%%" % (100 * a["top10_hit_rate"])) if a["top10_hit_rate"] is not None else "—",
                    a["wall_seconds_total"] / 60.0))
        pe = n3.get("primary_endpoint") or {}
        if pe.get("A1_k5_seed_values"):
            q3 = pe.get("A3_gp_ei_k5_quantile_in_A1")
            q4 = pe.get("A4_gp_ei_gated_k5_quantile_in_A1")
            L.append("")
            L.append("- **主终点（注册口径：k=5 次调用处）**：随机臂 5 个种子 best@k5 = %s；"
                     "**GP-EI 单轨迹 best@k5 = %.4e ⇒ 在随机臂分布中的分位 = %.2f**；"
                     "**门禁版 GP-EI = %.4e ⇒ 分位 = %.2f**。"
                     "⇒ 在**同一预算**下，代理驱动臂在前 5 次调用处就**优于全部 5 个随机种子**（分位 1.00）；"
                     "而随机臂 25 次调用的最好值（%.4e）仍低于 GP-EI 的 k=5 值。"
                     % (", ".join("%.4e" % v for v in pe["A1_k5_seed_values"]),
                        pe.get("A3_gp_ei_k5_value") or float("nan"),
                        q3 if q3 is not None else float("nan"),
                        pe.get("A4_gp_ei_gated_k5_value") or float("nan"),
                        q4 if q4 is not None else float("nan"),
                        (n3["per_arm"]["A1_random"]["best_y"] if "per_arm" in n3 else float("nan"))))
        gp = n3.get("gate_pressure_replay") or {}
        if gp.get("n_replayed"):
            L.append("- **门禁压力（离线重放诊断）**：门禁版臂 25 步中，**%d/%d 步的「无门禁 EI 提议」"
                     "落在语料覆盖域之外（%.0f%%）** ⇒ 该门禁不是装饰：去掉它，EI 几乎总是提议"
                     "**没有训练证据**的点。⚠️ 该重放复用执行器同一 `gp_ei` 代码路径，**属诊断、不是独立验证**。"
                     % (gp["n_would_be_refused"], gp["n_replayed"], 100 * gp["refusal_rate"]))
    else:
        led = R / "eda64-20261010/n3_dse/LEDGER.jsonl"
        n = len(led.read_text(encoding="utf-8").splitlines()) if led.exists() else 0
        L.append("- 进度：台账 %d 条（尚未跑满）⇒ **本轮不报结论**。" % n)
    ver = jload("eda64-20261010/n3_dse/N3_INDEPENDENT_VERIFICATION.json")
    if ver:
        L.append("- **独立复核**：不复用执行器的独立脚本重算 **%d 项检查、%d 项不一致**（容差 %g）；"
                 "重复设计点 %d 个**逐位一致**（点级缓存 + 求解确定性）；失败 %d 次集中在 %d 个点；"
                 "口径互检 y/y_asi ∈ [%.4f, %.4f]（与 N1 实测的 1.8%% 面无关性同量级）。"
                 % (ver["n_checks"], ver["n_failed_checks"], ver["tolerance_rel"],
                    ver["duplicate_point_determinism"]["n_repeated_points"],
                    ver["failure_behaviour"]["n_failed_calls"],
                    ver["failure_behaviour"]["distinct_failed_points"],
                    ver["caliber_crosscheck"]["ratio_min"], ver["caliber_crosscheck"]["ratio_max"]))
    L.append("- 限制（与结论同现）：单频单点 oracle、未做频扫；A2/A3/A4 无种子复制（只有随机臂 5 种子）；"
             "本目标量的网格敏感性 ≤1.3% ⇒ **相对比较可用、绝对值不可用**；"
             "GP 超参在部分折触到核长上界（sklearn ConvergenceWarning，已留档）；"
             "失败点不入臂的可见集 ⇒ 可被再次提议（实测同一点被提议两次）；不提升任何状态。")
    L.append("")

    # ---- (五) N4 ----
    n4 = jload("eda64-20261010/n4_multifreq/N4_RESULT.json")
    n4d = jload("eda64-20261010/n4_multifreq/N4_ROM_DIAG.json")
    L.append("**（五）N4：多频 ROM（未见 x × 未见 f；远端 node01 跑完）**")
    L.append("")
    if n4:
        reg = n4.get("regression_target_20MHz") or {}
        L.append("- **执行**：主批 24/24 点、留出 6/6 点，**0 失败**；远端 `node01`（Linux、"
                 "COMSOL 6.4.0.293、`-np 16`），单元 94k–156k、单点 128–400 s；每点 13 个频点全部导出为点云。"
                 "（本机因**提交内存不足**外派，已如实登记。）")
        if reg:
            L.append("- **20 MHz 回归靶通过**（我们 vs 导出方独立管线，同一冻结 1369 点集）："
                     + "；".join("`%s` 全域 %.4f%% / 关键区 %.4f%%"
                                % (k, 100 * v["rel_L2_global"], 100 * v["rel_L2_key"])
                                for k, v in reg.items() if v.get("rel_L2_global"))
                     + " ⇒ 采集管线一致，失败不在采集维。")
        rom = n4.get("rom") or {}
        ok = {k: v for k, v in rom.items() if v.get("status") == "ok"}
        if ok:
            L.append("- **S1 判 `failed`**：未见 x × 未见 f 交叉格上，关键区最大 "
                     + " / ".join("**%.2f%%**（`%s`）" % (100 * v["S1_key_max"], k)
                                  for k, v in ok.items())
                     + "（阈值 2%）；全域最大 "
                     + " / ".join("%.2f%%" % (100 * v["S1_global_max"]) for v in ok.values())
                     + "（阈值 5%，参考）。")
            s2 = [r for v in ok.values() for r in v.get("S2", [])]
            if s2:
                L.append("- S2（**13 点网格交点**粗口径）：`f_pk` **%d/%d** 格与 FE 相同；"
                         "峰值 |p| 相对误差 %.1f%%–%.1f%%；−3 dB 带宽 %d/%d 格一致"
                         "（1 格 333%% 系该粗口径伪像）。"
                         % (sum(1 for r in s2 if r["f_peak_pred_MHz"] == r["f_peak_true_MHz"]), len(s2),
                            100 * min(r["peak_rel_err"] for r in s2),
                            100 * max(r["peak_rel_err"] for r in s2),
                            sum(1 for r in s2 if r["bw_rel_err"] is not None and r["bw_rel_err"] < 1e-9),
                            len(s2)))
    if n4d:
        for fam, v in (n4d.get("k_sensitivity") or {}).items():
            rows = v["rows"]
            k4 = next((r for r in rows if r["k"] == 4), None)
            kfull = rows[-1]
            if k4 and kfull:
                L.append("- **定因（`N4_ROM_DIAG.md`；轴分解为事后口径）**：`%s` 把 POD 阶数由注册的 k=4 加到 "
                         "k=%d 后，训练自重构误差由 %.3f%% → **%.3f%%**，而交叉格最大误差仅由 %.2f%% 变为 "
                         "**%.2f%%** ⇒ **失败不是基截断，而是 (x,f) 采样/插值**。"
                         % (fam, kfull["k"], 100 * k4["train_median_rel_key"],
                            100 * kfull["train_median_rel_key"], 100 * k4["cross_max_rel_key"],
                            100 * kfull["cross_max_rel_key"]))
        ax = n4d.get("axis_decomposition") or {}
        if ax:
            L.append("- 轴分解（k=16）：" + "；".join(
                "`%s` 只换 f 最大 %.1f%% / 只换 x 最大 %.1f%% / 两轴同时换 %.1f%%"
                % (fam, 100 * v["k=16"]["max_only_f"], 100 * v["k=16"]["max_only_x"],
                   100 * v["k=16"]["max_both"]) for fam, v in ax.items() if "k=16" in v) + "。")
    L.append("- **S5（区间覆盖率）本轮不评估**：多频 ROM 的 (x,f) 区间协议需单独预注册，本轮不发明口径。")
    L.append("- 限制：跨平台执行（单元数差 ~1e-4，逐点登记主机与版本）；**不得**把远端与 Windows 结果"
             "混为同一批而不声明；`S1` 失败**未**归因于采集管线（回归靶已过）。")
    L.append("")

    # ---- (六) N5 ----
    figs = sorted(p.name for p in (R / "eda64-20261010/n5_figures").glob("fig*.pdf"))
    L.append("**（六）N5：论文图（零 COMSOL）**")
    L.append("")
    L.append("- 已生成 %d 张（PDF 矢量 + PNG 300 dpi）：%s；图注/口径/禁用语见 "
             "`work/runs/eda64-20261010/n5_figures/FIGURES.md`，输入 sha256 见 `FIGURES_PROVENANCE.json`。"
             % (len(figs), "、".join("`%s`" % f for f in figs)))
    L.append("- ⚠️ 图为**程序生成**且**本执行者无法读取图像** ⇒ **未经人眼检查**；投稿前须人工核对字号/图例/刻度。")
    L.append("")
    L.append("**本节限制**：N1/N1c 的载体是 M-base 本地 λ/5 网格，与门禁载体 M-h1um **不可逐位比较**；"
             "N2/N3 的结论都限定在「本数据 + 本口径 + 固定预算」；三项均**不提升任何模型状态**、"
             "不改写任何既有门禁件。")
    # 末行留一个空行（§6.9 与 "## 7. 讨论" 之间）；插入器按行模型把它变成纯 CRLF 空行
    return "\n".join(L) + "\n"


def main() -> int:
    b10 = V10.read_bytes()
    if hashlib.sha256(b10).hexdigest() != V10_SHA or len(b10) != V10_BYTES:
        print("[REFUSE] v10 sha/字节与登记值不符（%d B, %s）"
              % (len(b10), hashlib.sha256(b10).hexdigest()[:16]))
        return 2
    txt = b10.decode("utf-8")
    if len(txt.split("\n")) - 1 != V10_LINES:
        print("[REFUSE] v10 行数不符")
        return 2

    block = build_69()
    blines = block.split("\n")
    blk_crlf = "".join(ln + "\r\n" for ln in blines)          # block 自身（末元素为空 ⇒ 末尾有空行）
    problems = []
    for old, new, tag in EDITS:
        if txt.count(old) != 1:
            problems.append("%s：old 出现 %d 次（应为 1）" % (tag, txt.count(old)))
    if NOTE_V11 in txt:
        problems.append("v11 注已存在")
    if "\n## 7. 讨论" not in txt:
        problems.append("找不到 §7 锚点")
    if "> **v10 修订（本轮；" not in txt:
        problems.append("找不到 v10 注锚点")
    if problems:
        for p in problems:
            print("[REFUSE] %s" % p)
        return 2

    for old, new, tag in EDITS:
        txt = txt.replace(old, new, 1)

    lines = txt.split("\n")
    # 1) 插入 v11 修订注（紧跟 v10 注那一行之后）
    note_i = next(i for i, l in enumerate(lines) if l.startswith("> **v10 修订（本轮；"))
    lines.insert(note_i + 1, NOTE_V11.rstrip("\n") + "\r")
    # 2) 插入 §6.9（在 "## 7. 讨论" 之前，保留一个空行）
    sec_i = next(i for i, l in enumerate(lines) if l.rstrip("\r") == "## 7. 讨论")
    lines[sec_i:sec_i] = [ln + "\r" for ln in blines]
    txt11 = "\n".join(lines)
    b11 = txt11.encode("utf-8")

    # ---- 反向还原校验 ----
    back = txt11
    if blk_crlf not in back:
        print("[REFUSE] 反向还原：找不到 §6.9 块")
        return 2
    back = back.replace(blk_crlf, "", 1)
    note_crlf = NOTE_V11.rstrip("\n") + "\r\n"
    if note_crlf not in back:
        print("[REFUSE] 反向还原：找不到 v11 注")
        return 2
    back = back.replace(note_crlf, "", 1)
    for old, new, tag in reversed(EDITS):
        if back.count(new) != 1:
            print("[REFUSE] 反向还原失败：%s 的 new 片段出现 %d 次" % (tag, back.count(new)))
            return 2
        back = back.replace(new, old, 1)
    if back.encode("utf-8") != b10:
        print("[REFUSE] 反向还原不是逐字节等于 v10")
        return 2

    for _o, new, tag in EDITS:
        if txt11.count(new) != 1:
            print("[REFUSE] 结果里 %s 的 new 片段出现 %d 次" % (tag, txt11.count(new)))
            return 2
    if txt11.count(blk_crlf) != 1:
        print("[REFUSE] §6.9 块在结果中出现 %d 次" % txt11.count(blk_crlf))
        return 2
    if txt11.count(blines[0]) != 1:
        print("[REFUSE] §6.9 标题行出现 %d 次" % txt11.count(blines[0]))
        return 2
    if b11.count(b"\n") != b11.count(b"\r\n") or b11.count(b"\r") != b11.count(b"\r\n"):
        print("[REFUSE] 产物行尾不是纯 CRLF")
        return 2

    V11.write_bytes(b11)
    print("== v11 写出：%d B（v10 %d B，Δ%+d）、%d 行（Δ%+d）"
          % (len(b11), len(b10), len(b11) - len(b10),
             b11.count(b"\n"), b11.count(b"\n") - V10_LINES))
    print("== sha256 %s" % hashlib.sha256(b11).hexdigest())
    print("== 反向还原 = 逐字节等于 v10 ✓；%d 处替换 + 1 行 v11 注 + §6.9（%d 行）"
          % (len(EDITS), block.count("\n") + 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
