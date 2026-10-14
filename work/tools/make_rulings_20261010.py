# -*- coding: utf-8 -*-
"""把用户 2026-10-10 的两条口径裁定写成**机读记录**（append-only；不改任何既有件）。

裁定 1：**L1 口径**由「每一对相邻加密 < 1%」改为「**最细一对 < 1%**（GCI 式渐近判据）」。
裁定 2：**S5 口径**由「冻结 5 点留出」改为「**8 折覆盖率协议**」（原补充件转正）。

两者都只改**判据口径**，不改任何既有记录；S 级状态（含 `solver_spec.state`）**不因此提升**。
产物：`work/runs/rulings-20261010/{L1_ladder_caliber.json,S5_coverage_protocol.json}`。

L1 的数值来自 `validation` 表两条记录（本会话实查，逐条 quote）：
  * val-pmut-l1-mesh-20261001（本机 3 档 x1.5/x1.0/x0.7，15/20/25 MHz）
  * val-pmut-l1-mesh-4level-20261003（服务器 4 档，加 x0.5）
S5 的数值直接读 `s5_8fold_n1_{4,7}.json`（不手抄）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "work/runs/rulings-20261010"
FAM = REPO / "work/runs/te2_8_pod_fields_20261005/x_family"

USER_RULING = ("用户 2026-10-10 指示（逐字）：目标会议 = https://dac.com/2027；"
               "「改」（批准把 L1 口径改为最细一对）、「转正」（批准把 8 折覆盖率补充协议"
               "转正为正式 S5 口径）、「先不展开」（405 组维持不展开）、"
               "「图片先不需要你修改」（本轮不改图）。")


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def s5(tag: str) -> dict:
    p = FAM / ("%s/s5_8fold_%s.json" % (tag, tag))
    d = json.loads(p.read_text(encoding="utf-8"))
    v = d["verdict"]["0.1"]
    bands = d["bands"]["0.1"]
    vals = [float(bands[k]["band_rel_L2"]) if isinstance(bands[k], dict) else float(bands[k])
            for k in sorted(bands)]
    return {"tag": tag, "path": str(p.relative_to(REPO)), "sha256": sha(p),
            "n_folds": d["n_folds"], "n_snapshots": d["n_snapshots"],
            "alpha": 0.10, "threshold": v["threshold"], "coverage": v["coverage"],
            "verdict": v["verdict"], "min_fold_coverage": v["min_fold_coverage"],
            "max_fold_coverage": v["max_fold_coverage"],
            "band_rel_L2_min": min(vals), "band_rel_L2_max": max(vals),
            "band_rel_L2_per_fold": vals, "fold_sizes": d["fold_sizes"],
            "self_declared": {"supplemental": d["supplemental"], "supersedes": d["supersedes"],
                              "frozen_protocol_verdict_note": d["frozen_protocol_verdict_note"]}}


OUT.mkdir(parents=True, exist_ok=True)

# ---------------- 裁定 1：L1 ----------------
l1 = {
    "kind": "ruling_l1_ladder_caliber",
    "ruled_local": "2026-10-10",
    "authority": USER_RULING,
    "subject": "L1 网格收敛的判据口径",
    "old_caliber": {
        "rule": "**每一对相邻加密**的相对差 < 1%（预注册严格口径）",
        "verdict": "false（不通过）",
        "evidence": [
            {"validation_id": "val-pmut-l1-mesh-20261001", "host": "本机",
             "levels": {"x1.5": 88886, "x1.0": 136250, "x0.7": 213534},
             "frequencies_MHz": [15, 20, 25],
             "coarser_pair_max_rel": 0.022349013290873375,
             "finer_pair_max_rel": 0.006652329409969794,
             "note": "目标量 Ptot（≡ gev1）；×0.5 档（342,635 单元）本机内存失败"},
            {"validation_id": "val-pmut-l1-mesh-4level-20261003", "host": "服务器 node01（-np 16）",
             "levels": {"x1.5": 88889, "x1.0": 136246, "x0.7": 213560, "x0.5": 342886},
             "frequencies_MHz": [15, 20, 25],
             "pair_max_rel": {"1.5->1.0": 0.021860471074723865,
                              "1.0->0.7": 0.006609034523888908,
                              "0.7->0.5": 0.004063757021458511},
             "note": "单调下降（渐近自 x1.0 起）；最细一对每个频点都 < 1%；"
                     "服务器 ×0.5 峰值物理内存 54.08 GB、虚拟 83.23 GB"},
        ],
    },
    "new_caliber": {
        "rule": "**最细一对**（finest pair）的相对差 < 1%（GCI 式渐近判据）",
        "verdict": "true（通过）",
        "evidence": [
            {"validation_id": "val-pmut-l1-mesh-20261001",
             "finest_pair_max_rel": 0.006652329409969794},
            {"validation_id": "val-pmut-l1-mesh-4level-20261003",
             "finest_pair_max_rel": 0.004063757021458511},
        ],
        "supersedes_in_reference_only": ["L1 的严格口径读数（本机 val-pmut-l1-mesh-20261001 判 false）",
                                         "val-pmut-l1-mesh-x050-attempt-20261001（×0.5 本机内存失败的登记）"],
        "old_records_unchanged": True,
    },
    "limits": [
        "只覆盖**所测档之间的两两差**；**不得**表述为「网格无关已验证」。",
        "h 比值非均匀 ⇒ **不报** observed order / GCI 数值。",
        "×0.5 档在本机仍不可解（内存）；服务器可解（54.08 GB 峰值），跨机数值一致性已单独登记。",
        "本裁定**不提升任何模型状态**：S 级第一跳要求 S0 **与 S3** 同时成立，而 S3 仍 `failed`。",
    ],
}
(OUT / "L1_ladder_caliber.json").write_text(json.dumps(l1, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")

# ---------------- 裁定 2：S5 ----------------
a4, a7 = s5("n1_4"), s5("n1_7")
s5rec = {
    "kind": "ruling_s5_coverage_protocol",
    "ruled_local": "2026-10-10",
    "authority": USER_RULING,
    "subject": "S5（误差界校准）的正式口径",
    "old_caliber": {
        "rule": "冻结 **5 点**留出协议",
        "verdict": "inconclusive（k/5 无法取到 [0.85, 0.95]）",
        "note": "该口径记录保持原样，不修改（append-only）",
    },
    "new_caliber": {
        "rule": "**8 折覆盖率协议**（原 `supplemental: true` 件转正为正式 S5 口径），α = 0.10，"
                "阈值区间 [0.85, 0.95]，**覆盖率与区间宽度必须同报**",
        "verdict": "passed（两族）",
        "evidence": [a4, a7],
        "alpha_mismatch_note": "同一件里 α=0.05 / 0.01 两行判 `failed` **不是缺陷**："
                               "[0.85, 0.95] 本就是 **90% 区间**的判据，套到 95%/99% 属**口径错配**。",
        "supersedes_in_reference_only": ["冻结 5 点口径的 `inconclusive` 结论（其记录不改）"],
        "old_records_unchanged": True,
    },
    "interval_width_summary": {
        "n1_4": {"band_rel_L2_min": a4["band_rel_L2_min"], "band_rel_L2_max": a4["band_rel_L2_max"]},
        "n1_7": {"band_rel_L2_min": a7["band_rel_L2_min"], "band_rel_L2_max": a7["band_rel_L2_max"]},
        "unit": "band_rel_L2 = 90% 区间半宽（相对 L2 口径）",
    },
    "limits": [
        "覆盖率是对**校准折**的经验覆盖率，不是对未见设计族的保证；8 折在同一 81 快照族内 ⇒ 只覆盖 x 方向。",
        "两族均为 **N2=8、20 MHz 单频**族；未见频率不在此证据内（属 N4）。",
        "本裁定**不提升任何模型状态**（同裁定 1 的理由：S3 仍 failed）。",
    ],
}
(OUT / "S5_coverage_protocol.json").write_text(json.dumps(s5rec, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")

print("== L1 新口径：最细一对 max = %.6f%%（本机）/ %.6f%%（服务器 4 档）"
      % (l1["new_caliber"]["evidence"][0]["finest_pair_max_rel"] * 100,
         l1["new_caliber"]["evidence"][1]["finest_pair_max_rel"] * 100))
print("== S5 新口径：n1_4 coverage %.4f（%d/%d）、半宽 %.4f–%.4f"
      % (a4["coverage"], round(a4["coverage"] * a4["n_snapshots"]), a4["n_snapshots"],
         a4["band_rel_L2_min"], a4["band_rel_L2_max"]))
print("          n1_7 coverage %.4f（%d/%d）、半宽 %.4f–%.4f"
      % (a7["coverage"], round(a7["coverage"] * a7["n_snapshots"]), a7["n_snapshots"],
         a7["band_rel_L2_min"], a7["band_rel_L2_max"]))
print("== 写出", OUT / "L1_ladder_caliber.json", "与", OUT / "S5_coverage_protocol.json")
