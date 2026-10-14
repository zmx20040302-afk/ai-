# -*- coding: utf-8 -*-
"""T5：**拒答行为**的合并评测（纯提取，零求解）。

本脚本是上游注册脚本的**打包内置版（vendored）**：口径、聚合口径与输出结构逐字保持不变，
只把输入/输出改成本包内相对路径，并去掉运行区路径、绝对路径、用户名/主机名痕迹。

输入（包内 `results/`，均由本包自身产出）：
  * `baselines_by_seed.json`（`bench.py` 产出）：逐种子逐格的 `coverage_of_defined`、
    三档容差下的 `false_accept`、pchip 的结构性拒答模式计数；
  * `M3_RESULT.json`（`tasks/m1_m2_m3.py` 产出）：跨批适用域接受率（第二类拒答来源）；
  * `M2_RESULT.json`（`tasks/m1_m2_m3.py` 产出）：risk–coverage 的预注册分歧分与格数。
输出（包内 `results/`）：
  * `T5_RESULT.json`（主产物）；
  * `T5_REPORT.md`（同源报告）。

口径与上游预注册件的 T5 段一致：**描述性**、逐批逐通道、不池化、不给阈值。
该预注册件**不随本包分发**，其文件名与 sha256 以常量内联（`PREREG_NAME` / `PREREG_SHA256`），
只用于在产物里标出上游口径来源，**在包内无法复核**。
"""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _text  # noqa: E402  （自由文本的英文渲染表；见其 docstring）
PKG = HERE.parent
RES = PKG / "results"
N2 = RES / "baselines_by_seed.json"
M3 = RES / "M3_RESULT.json"
M2 = RES / "M2_RESULT.json"
# 上游预注册件的身份（内联常量；该文件不在包内，故记录而不读取）
PREREG_NAME = "PREREG_T1_T2_T5.json"
PREREG_SHA256 = "85afa8abbec347ba2fe03cc03593123af8e0bb68c868fb72a19d9ed4bf6ecb5b"
BATCHES = ("A_5-35MHz", "C_5-50MHz", "V2_5-35MHz")


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def rel(p): return str(p.relative_to(PKG)).replace("\\", "/")


def med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return float(statistics.median(xs)) if xs else None


def main() -> int:
    reg = json.loads(N2.read_text(encoding="utf-8"))
    m3 = json.loads(M3.read_text(encoding="utf-8"))
    m2 = json.loads(M2.read_text(encoding="utf-8"))
    tol = None
    rows, refusal_modes, coverage_table = [], {}, {}
    for b in BATCHES:
        for s, cell in reg["per_seed"][b].items():
            for ch, cd in cell["channels"].items():
                for m, md in (cd.get("methods") or {}).items():
                    fa = md.get("false_accept") or {}
                    if tol is None and fa:
                        tol = sorted(fa.keys(), key=lambda z: float(z))
                    rows.append({"batch": b, "seed": s, "channel": ch, "method": m,
                                 "coverage_of_defined": md.get("coverage_of_defined"),
                                 "false_accept": fa or {},
                                 "n_predicted": md.get("n_predicted")})
                    if m == "pchip" and md.get("refusals"):
                        refusal_modes.setdefault(b, {})[s] = md["refusals"]
    # 聚合：逐 (批×通道×方法)
    agg = {}
    for b in BATCHES:
        for ch in sorted({r["channel"] for r in rows if r["batch"] == b}):
            for m in sorted({r["method"] for r in rows if r["batch"] == b and r["channel"] == ch}):
                sel = [r for r in rows if r["batch"] == b and r["channel"] == ch and r["method"] == m]
                if not sel:
                    continue
                a = {"n_seeds": len(sel), "coverage_median": med([r["coverage_of_defined"] for r in sel]),
                     "false_accept_median": {t: med([r["false_accept"].get(t) for r in sel]) for t in (tol or [])}}
                agg.setdefault(b, {}).setdefault(ch, {})[m] = a
    # pchip 拒答模式（跨种子合计）
    pchip_modes = {}
    for b, per_seed in refusal_modes.items():
        c = collections.Counter()
        for s, modes in per_seed.items():
            for k, v in (modes or {}).items():
                c[k] += v
        pchip_modes[b] = dict(c)
    # M3 的跨批接受率（第二类拒答）
    m3_rows = [c for c in m3["cells"] if "acceptance_of_defined" in c]
    m3_acc = {}
    for c in m3_rows:
        m3_acc.setdefault("%s→%s" % (c["train"], c["test"]), []).append(c["acceptance_of_defined"])
    out = {"kind": "ai11_t5_refusal_behaviour", "created_local": "2026-10-13",
           "prereg": {"file": PREREG_NAME, "sha256": PREREG_SHA256},
           "inputs": {rel(N2): sha(N2), rel(M3): sha(M3), rel(M2): sha(M2)},
           "tolerances": tol, "aggregate": agg, "pchip_refusal_modes": pchip_modes,
           "cross_batch_acceptance": {k: {"n": len(v), "median": med(v), "min": min(v)} for k, v in m3_acc.items()},
           "risk_coverage_reference": {"file": M2.name, "n_cells": len(m2["per_cell_raw"]),
                                       "score": m2["score_preregistered"]},
           "non_claims": ["**未预测 ≠ 正确**：拒答覆盖率与被接受子集上的精度/容差必须并置读；",
                          "本件**描述性**、不设通过/失败阈值；逐批逐通道、不池化；",
                          "不主张拒答机制已最优（只评已注册机制）；零 COMSOL 求解。"]}
    (RES / "T5_RESULT.json").write_bytes(
        (json.dumps(_text.to_en(out), ensure_ascii=False, indent=2, default=str) + "\n").replace("\n", "\r\n").encode("utf-8"))

    L = ["# AI1.1 · T5：拒答行为（纯提取，零求解）· 2026-10-13", "",
         "> 预注册 `%s`（sha `%s`）。三个容差：%s。逐批逐通道、**不池化**、**不过滤**。"
         % (PREREG_NAME, PREREG_SHA256[:16], tol), "",
         "## 1. 逐 (批×通道×方法)：拒答覆盖率 vs 三档容差下的 false-accept", "",
         "| 批 | 通道 | 方法 | 覆盖（5 种子中位） | false-accept @%s |" % " / ".join(tol or []),
         "|---|---|---|---:|---|"]
    for b in agg:
        for ch in sorted(agg[b]):
            for m in sorted(agg[b][ch]):
                a = agg[b][ch][m]
                fas = " / ".join("—" if a["false_accept_median"].get(t) is None
                                 else "%.4f" % a["false_accept_median"][t] for t in (tol or []))
                L.append("| %s | %s | %s | %s | %s |" % (
                    b, ch, m, "—" if a["coverage_median"] is None else "%.3f" % a["coverage_median"], fas))
    L += ["", "## 2. pchip 的结构性拒答模式（跨种子合计）", ""]
    for b, modes in pchip_modes.items():
        L.append("- **%s**：%s" % (b, ", ".join("%s=%d" % (k, v) for k, v in sorted(modes.items())) or "无"))
    L += ["", "## 3. 第二类拒答来源：跨批适用域接受率（来自 M3）", "",
          "| 迁移 | 格数 | 接受率中位 | 最低 |", "|---|---:|---:|---:|"]
    for k, v in out["cross_batch_acceptance"].items():
        L.append("| %s | %d | %.3f | %.3f |" % (k, v["n"], v["median"], v["min"]))
    L += ["", "## 4. 与 risk–coverage（M2）的关系", "",
          "M2 用**预注册的模型—基线分歧分**把接受比例当自变量：`%s`；%d 个格。"
          % (m2["score_preregistered"], len(m2["per_cell_raw"])),
          "两套是**两个口径**：T5 是**结构性**拒答（定义域/口径），M2 是**评分式**弃权；**不得混称**。", "",
          "## 不主张", ""] + ["- " + x for x in out["non_claims"]]
    (RES / "T5_REPORT.md").write_bytes(("\n".join(L) + "\n").encode("utf-8"))
    print("T5 完成：格数=%d（批×通道×方法）pchip 拒答模式批数=%d 跨批接受率组=%d"
          % (sum(len(v) for bb in agg.values() for v in bb.values()), len(pchip_modes),
             len(out["cross_batch_acceptance"])))
    print("写出 T5_RESULT.json + T5_REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
