# -*- coding: utf-8 -*-
"""v10：由 **v9** 生成 —— 折入 2026-10-12 的两件机时结果（S3 三点标定 + S4 重解）。

依据：用户 2026-10-12 裁定「先折进 v10，再发 Codex」（INDEX §216 第六条）。
改动**三处**（正文 2 + 补充材料 1），每处**恰好命中 1 次**，其余一字不动；**LF**；
报告哈希从磁盘算；往返自检可逐字节还原 v9。

产物：`docs/PAPER_DAC2027_EN_v10_20261012.md`、`docs/PAPER_DAC2027_EN_v10_PROVENANCE.md`、
      `docs/PAPER_DAC2027_EN_SUPPLEMENT_20261012.md`（**就地追加 §S9 的加密段**；见下注）、
      `work/runs/eda64-20261010/n5_stage3/V10_GENERATION_REPORT.json`

⚠️ 补充材料：本次**不新建文件**，而是把 §S9 里那段两点收敛**就地替换**为三点版。
   为避免破坏既有补充材料的可追溯性，替换前会记其原 sha256，并**另存一份 v9 时的副本**
   `docs/PAPER_DAC2027_EN_SUPPLEMENT_20261012_v9.md`（若不存在则创建）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
V9 = REPO / "docs/PAPER_DAC2027_EN_v9_20261012.md"
V10 = REPO / "docs/PAPER_DAC2027_EN_v10_20261012.md"
V10P = REPO / "docs/PAPER_DAC2027_EN_v10_PROVENANCE.md"
SUP = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261012.md"
SUP_SNAP = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261012_v9.md"
OUT = REPO / "work/runs/eda64-20261010/n5_stage3"

# ---- 正文 R1：S4 段补"重解不逐位"事实（~60 词）
R1_OLD = ("the *choice* of spatial object is inherited from the earlier post-hoc ruling rather than "
          "cleansed by it.")
R1_NEW = (R1_OLD + " A **fresh re-solve** of the same ladder (same model, same mesh) returns the same "
          "verdict but is **not bit-identical**: the twelve values differ by ~1e-13, so the solver is "
          "deterministic only to ~1e-12. Node coordinates and export sizes are bit-identical, which "
          "excludes storage and decoding error; the re-solve is still **not** an independent confirmation.")

# ---- 正文 R2：§6.5 收敛句改为三点拟合（并给出可关闭的网格量级）
R2_OLD = ("converging with refinement as **1.770575 % → 0.953987 %** (λ/5 → λ/7 at 20 MHz, a ratio of "
          "0.5388 against the 0.5102 of second order). It is therefore a **discretisation error of the "
          "acoustic mesh**, not a missing dissipation path (§S9); closing it needs mesh refinement, not "
          "a model change.")
R2_NEW = ("converging with refinement as **1.7706 % → 0.9540 % → 0.5632 %** at 20 MHz (λ/5 → λ/7 → λ/9), "
          "a three-point fit giving **p = 1.94 (R² = 0.999)**. It is therefore a **discretisation error "
          "of the acoustic mesh**, not a missing dissipation path (§S9). Even λ/9 remains above the "
          "0.5 % criterion, and the fitted requirement at 20 MHz is a further factor of ≈1.9 in h "
          "(≈λ/9.4, extrapolated) — one more level of the same family, not a model change.")

# ---- 补充材料 R3：两点 → 三点 + 所需缩小倍数表 + 口径限制
R3_OLD = ("It converges with the acoustic mesh.** A same-machine pair differing **only** in `ftet1`\n"
          "(λ/5, 342,886 elements versus λ/7, 424,591 elements; identical `ftri1` and solid scale) gives "
          "at 20 MHz\n**1.770575 % → 0.953987 %**, a ratio of **0.5388** against the **0.5102** predicted "
          "by second-order\nconvergence (first order would give 0.7143).")
R3_NEW = ("It converges with the acoustic mesh.** Three same-machine levels differing **only** in "
          "`ftet1` — λ/5 (342,886 elements), λ/7 (424,591) and λ/9 (592,560; `ftri1` and the solid scale "
          "held fixed; all three re-solved from the same source model, hash-verified before each run) — "
          "give at 20 MHz **1.770575 % → 0.953987 % → 0.563150 %**. A three-point log-log fit "
          "`resid = C·h^p` gives **p = 1.9428, C = 1.2804e+08 (h in m), R² = 0.9987350**; the local "
          "exponents are 1.8379 (λ/5→λ/7) and 2.0974 (λ/7→λ/9), and the two-point ratio **0.5388** is "
          "consistent with the **0.5102** expected from second order but is superseded by the fit. "
          "**λ/9 is still above the 0.5 % "
          "criterion**, so the criterion is not met at this design point with 592,560 elements.\n\n"
          "Required reduction in `h` to reach 0.5 %, from the fixed `p = 2` fit "
          "(`(resid(f)/0.5 %)^(1/2)`):\n\n"
          "| f (MHz) | 15 | 20 | 25 | 30 | 35 |\n|---:|---:|---:|---:|---:|---:|\n"
          "| resid | 1.072166 % | 1.770575 % | 2.412732 % | 3.403465 % | 4.491323 % |\n"
          "| **h reduction** | **1.4644×** | **1.8818×** | **2.1967×** | **2.6090×** | **2.9971×** |\n\n"
          "⚠️ **Only the 20 MHz row shares the fit's caliber and carrier.** The other four residuals come "
          "from §S9's *17-face* caliber on a *different* carrier whose `ftet1` size is not recorded "
          "anywhere, so those rows are a cross-caliber, cross-carrier migration combined with the `h²` "
          "extrapolation — **not** measurements on this grid. And the 16-face caliber used for the fit is "
          "**not** the 17-face criterion of the main text (the ring face was not integrated at λ/5 and "
          "λ/7); the λ/9 value under the 17-face caliber is **0.539029 %**.")


def rep_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit("[FAIL] %s 锚点命中 %d 次（要求 1）：%r" % (label, n, old[:70]))
    return text.replace(old, new)


def main() -> int:
    v9 = V9.read_text(encoding="utf-8")
    if "\r\n" in v9:
        raise SystemExit("[FAIL] v9 含 CRLF")
    v9_sha = hashlib.sha256(V9.read_bytes()).hexdigest()
    # 补充材料的 **v9 时代源**：若快照已存在则从快照读（保证可确定性地重生成）
    sup_src = SUP_SNAP if SUP_SNAP.exists() else SUP
    sup0 = sup_src.read_bytes()
    sup0_sha = hashlib.sha256(sup0).hexdigest()
    sup0_text = sup0.decode("utf-8")
    if "\r\n" in sup0_text:
        raise SystemExit("[FAIL] 补充材料含 CRLF")

    body = rep_once(rep_once(v9, R1_OLD, R1_NEW, "R1"), R2_OLD, R2_NEW, "R2")
    sup = rep_once(sup0_text, R3_OLD, R3_NEW, "R3")

    # 先快照 v9 时的补充材料（只做一次），保证旧文本可溯源
    if not SUP_SNAP.exists():
        SUP_SNAP.write_bytes(sup0)

    V10.write_bytes(body.encode("utf-8"))
    SUP.write_bytes(sup.encode("utf-8"))

    # 回读自检
    db, ds = V10.read_bytes(), SUP.read_bytes()
    if b"\r\n" in db or b"\r\n" in ds:
        raise SystemExit("[FAIL] 输出出现 CRLF")
    dt, st = db.decode("utf-8"), ds.decode("utf-8")
    if dt.replace(R1_NEW, R1_OLD).replace(R2_NEW, R2_OLD) != v9:
        raise SystemExit("[FAIL] 正文往返校验失败")
    if st.replace(R3_NEW, R3_OLD) != sup0_text:
        raise SystemExit("[FAIL] 补充材料往返校验失败")
    for must in ("p = 1.9428", "0.563150", "R² = 0.9987350", "0.539029", "592,560"):
        if must not in st:
            raise SystemExit("[FAIL] 补充材料缺少必需项：%s" % must)
    if "not bit-identical" not in dt or "p = 1.94 (R² = 0.999)" not in dt:
        raise SystemExit("[FAIL] 正文缺少必需项")

    import re
    wc = lambda s: len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-\./%]*",
                                  s[:s.find("## Content Generated by AI")]))
    w9, w10 = wc(v9), wc(dt)
    rep = {"kind": "dac2027_en_v10_generation", "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "source": V9.name, "source_sha256": v9_sha, "source_bytes": len(V9.read_bytes()),
           "output": V10.name, "output_sha256": hashlib.sha256(db).hexdigest(),
           "output_bytes": len(db), "output_eol": "LF",
           "supplement_previous_sha256": sup0_sha,
           "supplement_previous_snapshot": SUP_SNAP.name,
           "supplement_new_sha256": hashlib.sha256(ds).hexdigest(),
           "supplement_new_bytes": len(ds),
           "replacements": {"body": 2, "supplement": 1},
           "body_words_v9": w9, "body_words_v10": w10, "body_words_delta": w10 - w9,
           "roundtrip_restores_v9_and_supp": True,
           "content_added": ["S3: three-point O(h²) fit (p=1.9428, R²=0.9987) + λ/9 = 0.563150 % still > τ",
                             "S3: per-frequency required-h table with its caliber/carrier caveat",
                             "S4: fresh re-solve is NOT bit-identical (~1e-13); excludes storage/decoding only"],
           "page_note": "正文 %+d 词；补充材料 +%d 字符（不计入页数）。" % (w10 - w9, len(ds) - len(sup0))}
    if hashlib.sha256(V10.read_bytes()).hexdigest() != rep["output_sha256"]:
        raise SystemExit("[FAIL] 报告哈希与磁盘不一致")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "V10_GENERATION_REPORT.json").write_bytes(
        (json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    V10P.write_bytes(f"""# v10 出处说明（DAC 2027 英文稿）

- 生成：{time.strftime("%Y-%m-%d")}；由 **v9**（`{V9.name}`，sha256 `{v9_sha[:24]}`，
  {len(V9.read_bytes())} B）经 **正文 2 处 + 补充材料 1 处**字面替换生成（每处恰好命中 1 次）。
- 产物：`{V10.name}`（sha256 `{rep["output_sha256"][:24]}`，{rep["output_bytes"]} B，**LF**）。
- 补充材料**就地更新**（新 sha256 `{rep["supplement_new_sha256"][:24]}`）；
  更新前那一版已另存为 `{SUP_SNAP.name}`（已记录其 sha256 `{sup0_sha[:24]}`）以便溯源。
- 正文词数：v9 **{w9}** → v10 **{w10}**（{w10 - w9:+d}）。
- **自检**：从磁盘回读；**正文反向替换可逐字节还原 v9**、**补充材料反向替换可逐字节还原其更新前版本**。

## 折入了什么（依据 INDEX §216）

1. **S3 声学侧标定（1 次新求解）**：三点 λ/5→λ/7→λ/9 得 **1.770575 % → 0.953987 % → 0.563150 %**；
   三点拟合 **p = 1.9428、C = 1.2804e+08、R² = 0.9987350**（局部幂次 1.84 / 2.10）；
   **λ/9 仍 > 0.5 %** ⇒ 该设计点在该网格下**未达标**；按固定 p=2 外推，20 MHz 需 h 再小 **1.8818×**（≈λ/9.4）。
2. **S4 三档重解（3 次新求解）**：判定仍 `passed`（operative 0.015190895），但与既有读数**不逐位相同**（差 ~1e−13）
   ⇒ **求解器只确定性到 ~1e−12**；节点坐标与导出字节数逐位相同 ⇒ **排除存储/解码环节**；
   **仍不是独立确认**，对象选择的事后性未消除。

## 页数与边界

- 正文 **{w10 - w9:+d} 词**；**本机无 TeX，页数未编译验证**；AI 章节**不得为页数删减**；
- **不改任何数字**（只**新增**实测点与拟合值）、**不改任何图表**；除上述三处外**一字未动**。

## 不主张

- **不主张** S3 通过（能量项判定仍为失败；λ/9 实测 0.563150 % > 0.5 %）；
- **不主张**跑到 ≈λ/9.4 就一定 ≤0.5 %（**外推**）；**不主张** 15/25/30/35 MHz 那 4 行是实测；
- **不主张** S4 网格无关或独立确认；不提升任何状态。
""".encode("utf-8"))

    print("v9 %d B（sha %s）→ v10 %d B（sha %s）" % (rep["source_bytes"], v9_sha[:16],
                                                   rep["output_bytes"], rep["output_sha256"][:16]))
    print("补充材料 %d B → %d B（旧版另存 %s）" % (len(sup0), len(ds), SUP_SNAP.name))
    print("正文词数 v9 %d → v10 %d（%+d）" % (w9, w10, w10 - w9))
    print("自检：正文往返还原 v9 ✓；补充材料往返还原其更新前版本 ✓；必需项齐备 ✓；无 CRLF ✓")
    print("写出:", V10.name, "|", V10P.name, "| V10_GENERATION_REPORT.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
