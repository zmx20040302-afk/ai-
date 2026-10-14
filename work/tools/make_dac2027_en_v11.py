# -*- coding: utf-8 -*-
"""v11：由 **v10** 生成 —— 折入 **λ/11 追加测量**（20 MHz 单点实测达标）。

依据：用户 2026-10-13 裁定「出 v11」（INDEX §218 之后的提问）。
改动**两处**（正文 1 + 补充材料 1），每处恰好命中 1 次；其余一字不动；**LF**；
报告哈希从磁盘算；往返自检可逐字节还原 v10（正文）与其 v10 时代版本（补充材料）。

产物：`docs/PAPER_DAC2027_EN_v11_20261013.md`、`docs/PAPER_DAC2027_EN_v11_PROVENANCE.md`、
      `docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013.md`（**新文件**，保留 `…_20261012.md` 为 v10 时代版本）、
      `work/runs/eda64-20261010/n5_stage3/V11_GENERATION_REPORT.json`

⚠️ 本次**不改写** `…_SUPPLEMENT_20261012.md`（就地改写会让 v10/v11 共用同一文件名、溯源混乱）
   ⇒ **另存为 `…_SUPPLEMENT_20261013.md`**，并让 v11 正文与交接包都指向新名。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
V10 = REPO / "docs/PAPER_DAC2027_EN_v10_20261012.md"
V11 = REPO / "docs/PAPER_DAC2027_EN_v11_20261013.md"
V11P = REPO / "docs/PAPER_DAC2027_EN_v11_PROVENANCE.md"
SUP10 = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261012.md"
SUP11 = REPO / "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013.md"
OUT = REPO / "work/runs/eda64-20261010/n5_stage3"

# ---- 正文：外推 → 实测
R1_OLD = ("Even λ/9 remains above the 0.5 % criterion, and the fitted requirement at 20 MHz is a further "
          "factor of ≈1.9 in h (≈λ/9.4, extrapolated) — one more level of the same family, not a model "
          "change.")
R1_NEW = ("Even λ/9 remains above the 0.5 % criterion (0.5632 %), but one further level of the same "
          "family — **λ/11, 862,410 elements** — measures **0.3862 %** at 20 MHz and is inside it. Only "
          "this single point has been brought to that resolution: the rest of the 5–35 MHz band has not, "
          "so the item as a whole still fails, and closing it would need a per-frequency mesh "
          "requirement rather than a model change.")

# ---- 补充材料：加 λ/11 行 + 四点拟合 + p=2 偏乐观注记
R2_OLD = ("| **h reduction** | **1.4644×** | **1.8818×** | **2.1967×** | **2.6090×** | **2.9971×** |\n\n")
R2_NEW = (
    "| **h reduction** | **1.4644×** | **1.8818×** | **2.1967×** | **2.6090×** | **2.9971×** |\n\n"
    "**A fourth level was measured.** λ/11 (862,410 elements; same design point, same caliber, "
    "`ftet1` the only change) gives **0.38624819841137986 %** under the 16-face caliber and "
    "**0.36529723432485256 %** under the 17-face caliber — **both inside 0.5 %**, so the 20 MHz point "
    "meets the criterion at this resolution. The three-point fit above is unchanged (bit-identical); "
    "adding this level gives a four-point fit **p = 1.9441755672118854, C = 130201241.90139253, "
    "R² = 0.9991358812484448**, and the local exponent from λ/9 to λ/11 is **1.8790302127548892**.\n\n"
    "⚠️ **The `p = 2` column above is optimistic.** At λ/11 the fixed-`p = 2` fit predicts "
    "**0.370543 %** while the measurement is **0.386248 %**, i.e. **4.07 % higher** (and 0.1357 % below "
    "the three-point fitted curve, whose prediction is 0.386772 %). Because the measured exponent is "
    "slightly below 2, the four reductions in the table should be read as **lower bounds**; with "
    "`p = 1.9428` the same targets need somewhat smaller `h`.\n\n")


def rep_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit("[FAIL] %s 锚点命中 %d 次（要求 1）" % (label, n))
    return text.replace(old, new)


def main() -> int:
    v10 = V10.read_text(encoding="utf-8")
    sup10 = SUP10.read_text(encoding="utf-8")
    for nm, t in (("v10", v10), ("sup10", sup10)):
        if "\r\n" in t:
            raise SystemExit("[FAIL] %s 含 CRLF" % nm)
    v10_sha = hashlib.sha256(V10.read_bytes()).hexdigest()
    sup10_sha = hashlib.sha256(SUP10.read_bytes()).hexdigest()

    body = rep_once(v10, R1_OLD, R1_NEW, "R1")
    sup = rep_once(sup10, R2_OLD, R2_NEW, "R2")
    # 正文与补充材料的文件名引用：v11 用新补充材料名
    if "SUPPLEMENT_20261012" in body:
        raise SystemExit("[FAIL] 正文里不该出现补充材料文件名（预期无）")

    V11.write_bytes(body.encode("utf-8"))
    SUP11.write_bytes(sup.encode("utf-8"))

    db, ds = V11.read_bytes(), SUP11.read_bytes()
    if b"\r\n" in db or b"\r\n" in ds:
        raise SystemExit("[FAIL] 输出出现 CRLF")
    dt, st = db.decode("utf-8"), ds.decode("utf-8")
    if dt.replace(R1_NEW, R1_OLD) != v10:
        raise SystemExit("[FAIL] 正文往返校验失败")
    if st.replace(R2_NEW, R2_OLD) != sup10:
        raise SystemExit("[FAIL] 补充材料往返校验失败")
    for must in ("0.38624819841137986", "0.36529723432485256", "0.370543", "1.9441755672118854",
                 "0.9991358812484448", "1.8790302127548892", "lower bounds", "862,410"):
        if must not in st:
            raise SystemExit("[FAIL] 补充材料缺少必需项：%s" % must)
    if "λ/11, 862,410 elements" not in dt or "0.3862 %" not in dt:
        raise SystemExit("[FAIL] 正文缺少必需项")
    # 双盲
    for pat in (r"work[/\\]runs", r"docs/", r"\bsha256\b", r"[0-9a-f]{32,}", r"\bnode0\d\b"):
        if re.search(pat, st) or re.search(pat, dt):
            raise SystemExit("[FAIL] 双盲泄漏：%s" % pat)

    wc = lambda s: len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-\./%]*",
                                  s[:s.find("## Content Generated by AI")]))
    w10, w11 = wc(v10), wc(dt)
    rep = {"kind": "dac2027_en_v11_generation", "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "source": V10.name, "source_sha256": v10_sha, "source_bytes": len(V10.read_bytes()),
           "output": V11.name, "output_sha256": hashlib.sha256(db).hexdigest(),
           "output_bytes": len(db), "output_eol": "LF",
           "supplement_source": SUP10.name, "supplement_source_sha256": sup10_sha,
           "supplement_output": SUP11.name, "supplement_output_sha256": hashlib.sha256(ds).hexdigest(),
           "supplement_output_bytes": len(ds), "supplement_output_eol": "LF",
           "replacements": {"body": 1, "supplement": 1},
           "body_words_v10": w10, "body_words_v11": w11, "body_words_delta": w11 - w10,
           "roundtrip_restores_v10_and_sup10": True, "double_blind_clean": True,
           "content_added": ["λ/11 = 0.386248 % (16-face) / 0.365297 % (17-face), both inside 0.5 %",
                             "four-point fit p = 1.94418, R² = 0.9991359",
                             "p = 2 extrapolation shown to be optimistic by 4.07 % ⇒ table = lower bounds"]}
    if hashlib.sha256(V11.read_bytes()).hexdigest() != rep["output_sha256"]:
        raise SystemExit("[FAIL] 报告哈希与磁盘不一致")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "V11_GENERATION_REPORT.json").write_bytes(
        (json.dumps(rep, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    V11P.write_bytes(f"""# v11 出处说明（DAC 2027 英文稿）

- 生成：{time.strftime("%Y-%m-%d")}；由 **v10**（`{V10.name}`，sha256 `{v10_sha[:24]}`，
  {len(V10.read_bytes())} B）经 **正文 1 处 + 补充材料 1 处**字面替换生成。
- 产物：`{V11.name}`（sha256 `{rep["output_sha256"][:24]}`，{rep["output_bytes"]} B，**LF**）。
- 补充材料**另存新名**：`{SUP11.name}`（sha256 `{rep["supplement_output_sha256"][:24]}`，
  {len(SUP11.read_bytes())} B）；**v10 时代版本保留**为 `{SUP10.name}`（sha256 `{sup10_sha[:24]}`）
  —— 本次**没有**就地改写它（避免 v10/v11 共用同一文件名导致溯源混乱）。
- 正文词数：v10 **{w10}** → v11 **{w11}**（{w11 - w10:+d}）。
- **自检**：从磁盘回读；正文反向替换**逐字节还原 v10**、补充材料反向替换**逐字节还原 v10 时代版本**；
  **双盲扫描干净**（无仓库路径/`sha256` token/长十六进制/主机名）。

## 折入了什么（依据 INDEX §218）

1. **λ/11 追加测量（1 次新求解，862,410 单元）**：16 面 **0.38624819841137986 %**、
   17 面 **0.36529723432485256 %** ⇒ **20 MHz 单点已在 0.5 % 阈值内**；
2. **三点拟合逐位未变**；**四点拟合 p = 1.9441755672118854、R² = 0.9991358812484448**；
   局部幂次 λ/9→λ/11 = **1.8790302127548892**；
3. **`p = 2` 外推被证偏乐观 4.07 %**（预测 0.370543 % vs 实测 0.386248 %）⇒ 那张"所需 h 缩小倍数"表
   应读作**下界**。

## 边界（不得删）

- 正文明确写：**只有 20 MHz 这一点被做该分辨率**，5–35 MHz 其余频点**没有** ⇒ **整体能量项仍失败**；
- 补充材料保留"只有 20 MHz 那行与拟合同口径同载体"的逐行限制，以及 16 面 ≠ 17 面的说明；
- **不改任何图表**；除上述两处外**一字未动**。

## 不主张

- **不主张** S3 通过（能量项仍失败；τ 是**全频段**判据）；
- **不主张** 15/25/30/35 MHz 有同样收敛行为；**不主张**"20 MHz 变绿 ⇒ 能量项可关闭"；
- 不提升任何状态；`release_allowed` 仍 `false`；`solver_spec` 仍 `draft`。
""".encode("utf-8"))

    print("v10 %d B（sha %s）→ v11 %d B（sha %s）" % (rep["source_bytes"], v10_sha[:16],
                                                   rep["output_bytes"], rep["output_sha256"][:16]))
    print("补充材料：%s（%d B，sha %s）另存为新名；v10 时代版本保留 %s"
          % (SUP11.name, len(SUP11.read_bytes()), rep["supplement_output_sha256"][:16], SUP10.name))
    print("正文词数 v10 %d → v11 %d（%+d）" % (w10, w11, w11 - w10))
    print("自检：正文往返还原 v10 ✓；补充材料往返还原 v10 时代版本 ✓；双盲干净 ✓；无 CRLF ✓")
    print("写出:", V11.name, "|", V11P.name, "|", SUP11.name, "| V11_GENERATION_REPORT.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
