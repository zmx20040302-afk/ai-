# -*- coding: utf-8 -*-
"""生成 DAC 2027 初稿 v3（2026-10-09）：只改 §6.5 的拒答分类表述。

范围严格受限（人给的本轮唯一授权范围）：
  1. §6.5 拒答分类名按 E3 实测口径重写（层不存在 N1>=N2 102 + x 超层标定 51）；
  2. §6.5 覆盖率补精确值（67.857%）；
  3. 其余字节与 v2 逐位相同（脚本自证：unified diff 只落在 §6.5 行）。

不做的事（明文）：不重编号、不改结论、不改代码语义、不改 S4、不提升任何状态。

用法：
  work\\.venv\\Scripts\\python.exe -X utf8 work\\tools\\make_dac2027_v3_section65.py
"""
from __future__ import annotations

import difflib
import hashlib
import pathlib
import sys

from memsharness.guards_inplace import backup_before_edit

REPO = pathlib.Path(__file__).resolve().parents[2]
V2 = REPO / "docs/PMUT_DAC2027_初稿_v2_20261009.md"
V3 = REPO / "docs/PMUT_DAC2027_初稿_v3_20261009.md"

V2_SHA = "329b3f942a5e54c6db99203c2fd5566e4f5b7c5e89806b2929ea23fc1db6e5e3"

# ---- 改前片段（逐字节取自 v2；脚本 fail-closed 校验其唯一性）----
OLD_COVERAGE = "覆盖率为 67.9%。"
NEW_COVERAGE = "覆盖率为 67.9%（= 323/476 = 67.857%，E3 实测值）。"

OLD_REASON = (
    "**实测拒答原因是两类（不是四类）**：`x_outside_layer_range` **51**、"
    "`n2_out_of_domain` **102**（合计 153）。原句列出的「结构整数约束不成立」与"
    "「命中隔离记录」在**该网格的实测拒答直方图中没有出现**"
    "（隔离组合 (0.2,1,7)/(0.2,1,8) 不在该网格的实测拒答项内）。"
    "被拒答的网格点**单独计数并给出原因直方图，不混进排名**。"
)

# ---- 改后片段（实测口径；数字全部来自 E3 件）----
NEW_REASON = "\n".join([
    "**实测拒答原因是两类（不是四类），且必须按实测触发口径命名**："
    "**层不存在（`N1 ≥ N2`）102** ＋ **`x` 超出该层标定范围 51**（合计 153）。",
    "",
    "- **那 102 条的真实触发是结构约束 `N1 ≥ N2`（该层不存在）**："
    "6 组 `(N1,N2)`——`(5,5)`、`(6,5)`、`(6,6)`、`(7,5)`、`(7,6)`、`(7,7)`——各 17 个 `x`，共 102；"
    "而该网格内 `N2` 恒在 `[5,8] ⊂ [5,9]` ⇒ **真正因 `N2` 越域被拒 = 0**。",
    "- **隔离组合在该网格未触发**：模型确实声明了 `excluded_quarantine = [[0.2,1,7],[0.2,1,8]]`，"
    "但 `predict()` 路径**从不读取**该字段（只在 `model_card()` 中披露）⇒ 稿中「命中隔离记录」"
    "在本网格实测**触发 0 次**；网格内那两点实际因 **`x=0.20` 低于层标定下界 `0.31`** 被拒，"
    "归入「`x` 超出该层标定范围」。",
    "- 原句列出的「结构整数约束不成立」与「命中隔离记录」**不是两类之外的独立桶**："
    "前者正是那 102 条的真实触发（只是被自报标签写错），后者实测 0 次。",
    "",
    "**E3 实测直方图**（来源 `work/runs/paper-evidence-20261009/E3_refusal_histogram.csv`；"
    "逐点明细见同目录 `E3_refusal_grid_points.csv`，476 行）：",
    "",
    "| 桶 | 计数 |",
    "|---|---:|",
    "| refused｜`n2_out_of_domain`（**模型自报标签，归类有误，见下方限定**） | 102 |",
    "| refused｜`x_outside_layer_range` | 51 |",
    "| refused｜（**实测触发**）层不存在 `N1 ≥ N2` | 102 |",
    "| refused｜（**实测触发**）`N2 ∉ [5,9]` | 0 |",
    "| accepted｜`in_layer` | 323 |",
    "| accepted｜`n2_extrap` | 0 |",
    "| 合计 | 476 |",
    "",
    "被拒答的网格点**单独计数并给出原因直方图，不混进排名**。",
    "",
    "> **限定（必须与上表一起读）**：本节分类是**事后按 E3 逐点实测重分类**的结果，"
    "**不是**冻结模型自报标签的转抄。自报标签 `x_outside_layer_range` **51** ＋ "
    "`n2_out_of_domain` **102** 的总数（153）与实测一致，但**后 102 条的归类是错的**。"
    "以下两点属**已知缺陷、待处置**，本轮**只登记、不修代码**"
    "（修改分类逻辑属变更判定语义，须人拍板）："
    "① 分类函数按顺序匹配子串，而 `该层不存在：要求 N_w_te1 < N_w_te2` 这句本身含 `N_w_te2` ⇒ "
    "**先命中 `n2_out_of_domain`（标签碰撞）**，本应判 `layer_does_not_exist`；"
    "② 隔离组合 `excluded_quarantine` 未被 `predict()` 读取"
    "（§4.3 的 \\(I_{iso}\\) 门在实际预测路径上不生效）。"
    "**在其修复并重新冻结之前，任何沿用自报标签的拒答统计都必须按本节实测口径重述。**",
])


def main() -> int:
    b2 = V2.read_bytes()
    got = hashlib.sha256(b2).hexdigest()
    if got != V2_SHA:
        print("[FAIL] v2 基线哈希不符：%s" % got)
        return 2
    t2 = b2.decode("utf-8")

    for name, s in (("OLD_COVERAGE", OLD_COVERAGE), ("OLD_REASON", OLD_REASON)):
        n = t2.count(s)
        if n != 1:
            print("[FAIL] %s 在 v2 中出现 %d 次（要求恰好 1 次）——拒绝改" % (name, n))
            return 2

    t3 = t2.replace(OLD_COVERAGE, NEW_COVERAGE).replace(OLD_REASON, NEW_REASON)

    # 只允许落在 §6.5（L343-351）内的改动
    d = [l for l in difflib.unified_diff(t2.split("\n"), t3.split("\n"),
                                         "v2", "v3", n=0, lineterm="")
         if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    if V3.is_file():
        # 就地改守卫（`INDEX §131.2` 的新规矩）：重跑到同一路径时 V3 已存在 ⇒ 先备份改前字节；
        # 首次生成时它不存在 ⇒ 无「改前既有字节」可保护（`backup_before_edit` 按设计会拒绝空目标）。
        backup_before_edit(V3)
    V3.write_text(t3, encoding="utf-8")
    b3 = V3.read_bytes()

    print("v2 bytes=%d sha256=%s" % (len(b2), hashlib.sha256(b2).hexdigest()))
    print("v3 bytes=%d sha256=%s" % (len(b3), hashlib.sha256(b3).hexdigest()))
    print("v3 lines=%d" % t3.count("\n"))
    print("diff 行数=%d（应全部落在 §6.5）" % len(d))
    for l in d:
        print("  DIFF %s" % l[:100])

    # 回读自证：v2 的前 344 行（到 §6.5 标题）与 §6.5 之后的全部行，与 v3 逐行相同
    a, c = t2.split("\n"), t3.split("\n")
    head_same = a[:344] == c[:344]              # 索引 0..343 = 行 1..344（含 §6.5 标题行 343）
    grew = len(c) - len(a)
    tail_same = a[347:] == c[347 + grew:]       # 索引 347 起 = 行 348 起的空白与后续章节
    print("前 344 行逐行相同=%s；§6.5 之后逐行相同=%s；净增行数=%d" % (head_same, tail_same, grew))
    if not (head_same and tail_same):
        print("[FAIL] 改动溢出 §6.5 —— 拒绝")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
