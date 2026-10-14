# -*- coding: utf-8 -*-
"""生成 DAC 2027 初稿 v4（2026-10-09）：只改 §4.3 关于 \\(I_{iso}\\)／隔离／quarantine 的表述。

范围严格受限（人给的本轮唯一授权范围）：
  1. §4.3 的 \\(I_{iso}\\) 条目**标注实现状态**（设计意图／披露项；当前实现的实际预测路径中不生效）；
  2. §4.3 **新增一个限定段**，说明「仅在 `model_card()` 披露、`predict()` 不读取」并交叉引用 §6.5 限定段；
  3. 其余字节与 v3 逐位相同（脚本自证：前 179 行与改动之后的全部行与 v3 逐行相同，
     且把新增片段原样换回旧片段可**逐字节还原** v3）。

不做的事（明文）：不重编号、不改公式里的 \\(I_{iso}\\) 符号（保留设计意图）、不改结论、
不改代码语义、不碰 S4 与其它 `【待裁定】`、不提升任何状态。

行尾：v3 是 CRLF（620 个 CRLF），故本脚本按**二进制**读入/写出，避免写文本模式把
`\\r\\n` 二次翻译成 `\\r\\r\\n`。

用法：
  work\\.venv\\Scripts\\python.exe -X utf8 work\\tools\\make_dac2027_v4_section43_iso.py
"""
from __future__ import annotations

import difflib
import hashlib
import pathlib
import sys

from memsharness.guards_inplace import backup_before_edit

REPO = pathlib.Path(__file__).resolve().parents[2]
V3 = REPO / "docs/PMUT_DAC2027_初稿_v3_20261009.md"
V4 = REPO / "docs/PMUT_DAC2027_初稿_v4_20261009.md"

V3_SHA = "76e274a8924f237891839312d00a104b9e4dd2df8aad01cb63d81d6f7bdda94c"
NL = "\r\n"

# ---- 改前片段（逐字节取自 v3 §4.3 L180；脚本 fail-closed 校验其唯一性）----
OLD_BULLET = "- \\(I_{iso}\\)：输入未命中隔离组合。"

# ---- 改后片段（实现状态来自 src 实读 + E3 L41；措辞与 §6.5 限定段一致）----
NEW_BULLET = (
    "- \\(I_{iso}\\)：输入未命中隔离组合（**设计意图／披露项**）。"
    "⚠️ **实现状态：在当前实现的实际预测路径中不生效** —— `predict()` **从不读取** "
    "`excluded_quarantine`（该字段**仅在 `model_card()` 中披露**）⇒ 读者**不得**把 "
    "\\(I_{iso}\\) 读作生效的隔离门；详见下方限定段与 **§6.5 的限定段**。"
)

NOTE = (
    "> **限定（实现状态；必须与 §6.5 的限定段一起读）**：上式是**设计意图**的合取式。"
    "其中 \\(I_{iso}\\) 一项**在当前实现的实际预测路径中不生效**：冻结模型确实声明了 "
    "`excluded_quarantine = [[0.2,1,7],[0.2,1,8]]`，但 `predict()` 只经 `check_domain()`、"
    "**从不读取**该字段（该字段**仅在 `model_card()` 中披露**；响应级隔离拦截在另一模块 "
    "`surrogate.py` 上）⇒ 读者**不得**把 \\(I_{iso}\\) 读作生效的隔离门。实测口径见 §6.5："
    "那两个组合在 476 点网格上被拒的**真实原因是 `x=0.20` 低于层标定下界 `0.31`**"
    "（归入「`x` 超出该层标定范围」），拒答直方图中「命中隔离记录」实测**触发 0 次**。"
    "\\(I_{iso}\\) 作为设计的一部分**保留**于本式、**不删除**；其余四项的实现状态本轮"
    "**未逐项核验、不作断言**。修复该缺陷属变更判定语义、须人拍板 —— 本轮**只登记、不修代码**。"
)

ADDED = NEW_BULLET + NL + NL + NOTE


def main() -> int:
    b3 = V3.read_bytes()
    got = hashlib.sha256(b3).hexdigest()
    if got != V3_SHA:
        print("[FAIL] v3 基线哈希不符：%s" % got)
        return 2
    t3 = b3.decode("utf-8")
    if NL not in t3:
        print("[FAIL] v3 不是 CRLF 行尾 —— 拒绝（本脚本按 CRLF 处理）")
        return 2

    n = t3.count(OLD_BULLET)
    if n != 1:
        print("[FAIL] §4.3 的 \\(I_{iso}\\) 条目在 v3 中出现 %d 次（要求恰好 1 次）——拒绝改" % n)
        return 2

    t4 = t3.replace(OLD_BULLET, ADDED)
    if V4.is_file():
        # 就地改守卫（`INDEX §131.2`）：重跑时 V4 已存在 ⇒ 先备份改前字节；
        # 首次生成时不存在 ⇒ 无既有字节可保护。
        backup_before_edit(V4)
    V4.write_bytes(t4.encode("utf-8"))
    b4 = V4.read_bytes()

    print("v3 bytes=%d lines=%d sha256=%s" % (len(b3), t3.count("\n"), hashlib.sha256(b3).hexdigest()))
    print("v4 bytes=%d lines=%d sha256=%s" % (len(b4), t4.count("\n"), hashlib.sha256(b4).hexdigest()))
    print("字节变化=%+d；行数变化=%+d" % (len(b4) - len(b3), t4.count("\n") - t3.count("\n")))

    # unified diff（n=0）逐行列出实际改动
    d = [l for l in difflib.unified_diff(t3.split(NL), t4.split(NL), "v3", "v4", n=0, lineterm="")
         if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    print("diff 行数=%d（应恰好 4：1 删 + 3 增）" % len(d))
    for l in d:
        print("  DIFF %s" % l[:110])

    # 回读自证 A：改动**之前**的行与改动**之后**的全部行与 v3 逐行相同
    a, c = t3.split(NL), t4.split(NL)
    head_same = a[:179] == c[:179]         # 索引 0..178 = 行 1..179
    grew = len(c) - len(a)
    tail_same = a[181:] == c[181 + grew:]  # 索引 181 = 行 182（原「任一条件不满足时…」）

    # 回读自证 B（最强）：把新增片段原样换回旧片段，可逐字节还原 v3 ⇒ 无其它改动
    roundtrip = t4.replace(ADDED, OLD_BULLET) == t3

    print("前 179 行逐行相同=%s；改动段之后逐行相同=%s；净增行数=%d" % (head_same, tail_same, grew))
    print("逆替换逐字节还原 v3 = %s" % roundtrip)
    print("v3 未改：%s" % (hashlib.sha256(V3.read_bytes()).hexdigest() == V3_SHA))

    ok = head_same and tail_same and grew == 2 and roundtrip
    print("范围守卫（改动未溢出 §4.3）= %s" % ok)
    if not ok:
        print("[FAIL] 改动溢出或行数不符 —— 拒绝")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
