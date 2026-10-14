# -*- coding: utf-8 -*-
"""论文 v9 → **v10** 生成器（fail-closed）：只做**账目对齐**（S3 0-None / 端口口径 / S0 采纳口径 / 模型身份）。

范围**只限**：版本头、v10 修订注、以及 v9 里已被 `INDEX §158–§163` 事实取代的 6 处表述。
**其余一字不动**（含全部既有数字）。

守卫（任一不满足即 rc=2、不写任何文件）：
 1. v9 的 sha256/字节数/行数与登记值一致；
 2. 每条 old 片段在 v9 中**恰好出现 1 次**；
 3. 每条 new 片段在结果中**恰好出现 1 次**；
 4. 反向还原（new→old + 删除插入行）可**逐字节还原 v9**；
 5. 产物纯 CRLF、行数 = v9 + 1（插入 1 行 v10 注）。
"""
from __future__ import annotations

import hashlib
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
V9 = REPO / "docs" / "PMUT_DAC2027_初稿_v9_20261010.md"
V10 = REPO / "docs" / "PMUT_DAC2027_初稿_v10_20261010.md"
V9_SHA = "7f9525961d32f020bb49d47637a9491defe2f3ec331e8adf6c913c2626b10a89"
V9_BYTES = 161772
V9_LINES = 746

#: v10 修订注（插在 v9 注之后）
NOTE_V10 = ("> **v10 修订（本轮；**只做 S3 / S0 / 模型身份的账目对齐**；依据 `INDEX §158`（能量闭合可判定）、"
            "`§159`（对称性精确几何零检验 + 三项 `None` 全部可判定）、`§160`（用户裁定 S0 口径 = 单极子恒等式 `ρ_eff`）、"
            "`§161`（写回：新门禁件 `s3_gate_c_batch.json`）、`§162`/`§163`（T0.1 FOM 交叉验证、T0.4 端口取证））**："
            "① **S3 的账目更新为 `2 false + 0 None`** —— 对称性 ×2 由「镜像对未解码」改为**精确几何一阶矩零检验**"
            "（`asym = |∫x·|p|²dV| / ∫|x|·|p|²dV`，六频点最大 **7.449e-05 / 3.326e-04** ≤ 0.01 ⇒ **`passed`**）；"
            "`energy_loss_radiation_separation` 由 `None` 改为**可判定 `false`（6.177%）**；`verdict` 仍 **`failed`**、"
            "`S3_complete` 仍 **`False`**；② **（新增）口径定性**：`conservation_current_circuit_vs_field_flux = 11.12%` 与上述 6.177% "
            "**不是物理守恒结论** —— 实测 `es.pot1` 无选择集（未生效）、`es.term1.I/Q` 不可用、`cir.R1` 仅单连接（电路未闭合）、"
            "`I01/I02` 是 `∫Jz dA` 而**闭合面（28 面）上的 `Σ∫Jz dA` 残差 98.3%–99.9%**；改用**正确法向** `Σ∫J·n dA` 后残差 "
            "**6.5e-04 – 1.0e-03 ≤ 0.005 ⇒ 该项（电流版闭合面守恒）通过**；能量平衡在修正口径下仍差 **6.57%**（未闭合，**不宣布无害**）；"
            "③ **S0**：用户 2026-10-10 裁定采纳**单极子恒等式**口径（`ρ_eff = ∫_hemi|p|²dA/(2c·P_rad)` 须 = `ρ_model`）⇒ "
            "最低频点（0.25 MHz，ka=0.045）相对误差 **0.0904% < 1%（余量 11 倍）**、λ/5 六频点全部 ≤0.091%、20 MHz 处按预期崩到 1.523%；"
            "**该口径为事后声明口径**，而**预注册的空间口径（各向同性 + r⁻¹ 律）仍为 `failed`**（r⁻¹ 2.90%）——**两条并列、不择优**；"
            "④ **模型身份更正**：S3 的证据载体是 `s34_h1um_out_Model.mph`（**185,349,336 B / `6005ca65…`**，零求解复用），"
            "**不是**本节此前所写的 103,681,444 B / `0f75ca1d…`（那是 S4 阶梯的载体）；⑤ **S4 及更早各节一字未改**（v9 内容原样）。\n")

#: (old, new, 说明)
EDITS = [
    ("**v9**（**只做 S4 相关的针对性更新** —— 原文见 `PAPER_REVISION_LOG` §P",
     "**v10**（**只做 S3 / S0 / 模型身份的账目对齐** —— v9 的 S4 更新原文见 `PAPER_REVISION_LOG` §P",
     "版本号"),
    ("> 日期：2026-10-10（**v9 修订日**；v1–v8 的修订日均为 2026-10-09）",
     "> 日期：2026-10-10（**v10 修订日**；v9 同日；v1–v8 的修订日均为 2026-10-09）",
     "修订日"),
    ("、而**损耗-辐射分离与对称性 ×2 仍为 `None`**（`n_inconclusive` **4 → 3**、`S3_complete = False`；item ① **不被 `div(D)` 体积路线佐证**",
     "、而**对称性 ×2 与损耗-辐射分离三项均已可判定**（对称性 **`passed`**：精确几何一阶矩零检验最大 7.449e-05 / 3.326e-04；"
     "损耗-辐射分离 **`false`：6.177%**）⇒ `n_inconclusive` **0**、`S3_complete = False`（**v10 更新**；"
     "且实测该 6.177% 与 11.12% **均为端口/电流口径缺陷所致，不是物理守恒结论**）；item ① **不被 `div(D)` 体积路线佐证**",
     "§8 结论：三项 None"),
    ("③ **另 3 项仍 `None`**（损耗/辐射分离、对称性 ×2，见上行两行）。",
     "③ **三项 `None` 已全部可判定（v10）**：对称性 ×2 **`passed`**（精确几何零检验）、损耗/辐射分离 **`false`**（6.177%）；"
     "`n_inconclusive = 0`。",
     "§6.8：另 3 项 None"),
    ("1. **模型是不同实例**：S3/S4 所用模型为 `work/models/…_currentdrive_fmax45_v1.mph`（**103,681,444 B**，sha256 "
     "`0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d`），",
     "1. **模型是不同实例（v10 更正对象名与字节）**：**S3** 的证据载体是 `s34_h1um_out_Model.mph`（**185,349,336 B**，sha256 "
     "`6005ca652baa487d72db4b8a12269a010b0721f5e704ef35d4a7dd5bc4db781f`，零求解复用的已解输出）；"
     "**S4 阶梯**的载体是 `work/models/…_currentdrive_fmax45_v1.mph`（**103,681,444 B**，sha256 "
     "`0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d`），",
     "§6.8（三）1 模型身份"),
    ("**另 3 项 `None`**、`n_inconclusive = 3`、`S3_complete = False`；",
     "**三项 `None` 已全部可判定（v10：对称性 ×2 `passed`、损耗-辐射分离 `false` 6.177%）**、`n_inconclusive = 0`、"
     "`S3_complete = False`；",
     "G 清单：另 3 项 None"),
    ("S3 的 **`n_inconclusive` 由 4 更正为 3**（item ① 闭合面电荷守恒解为 `True`），**`verdict` 仍 `failed`**」",
     "S3 的 **`n_inconclusive` 已由 3 进一步降为 0**（v10：对称性 ×2 判 `passed`、损耗-辐射分离判 `false` 6.177%），"
     "**`verdict` 仍 `failed`**」",
     "摘要注：n_inconclusive"),
    ("| ⃞ **`None`（inconclusive）** —— **模型没有任何损耗输出**、且已取到的两项**不闭合**，**不允许**把差额当「损耗」报出 |",
     "| ❌ **`false`（v10：由「无法判定」改为可判定，残差 **6.177%** > 0.5%）** —— 模型仍**没有**专门损耗输出量；"
     "本项改用**能量闭合残差**判定；且实测该残差与 11.12% **同源于端口/电流口径缺陷**（`∫Jz` vs `∫J·n`、电路未闭合） |",
     "§6.8 表：损耗-辐射行"),
]


def main() -> int:
    b9 = V9.read_bytes()
    if hashlib.sha256(b9).hexdigest() != V9_SHA or len(b9) != V9_BYTES:
        print("[REFUSE] v9 sha/字节与登记值不符")
        return 2
    lines9 = b9.decode("utf-8").split("\n")
    if len(lines9) - 1 != V9_LINES:
        print("[REFUSE] v9 行数 %d ≠ %d" % (len(lines9) - 1, V9_LINES))
        return 2
    txt = b9.decode("utf-8")
    problems = []
    for old, new, tag in EDITS:
        c = txt.count(old)
        if c != 1:
            problems.append("%s：old 出现 %d 次（应为 1）" % (tag, c))
    if NOTE_V10 in txt:
        problems.append("v10 注已存在")
    if problems:
        for p in problems:
            print("[REFUSE] %s" % p)
        return 2
    for old, new, tag in EDITS:
        txt = txt.replace(old, new, 1)
    # 插入 v10 注：紧跟 v9 注那一行之后
    lines = txt.split("\n")
    anchor = None
    for i, l in enumerate(lines):
        if l.startswith("> **v9 修订（本轮；"):
            anchor = i
            break
    if anchor is None:
        print("[REFUSE] 找不到 v9 修订注锚点")
        return 2
    lines.insert(anchor + 1, NOTE_V10.rstrip("\n") + "\r")   # 逐行模型：CRLF 文件里除末行外都以 \r 结尾
    txt10 = "\n".join(lines)
    b10 = txt10.encode("utf-8")

    # ---- 反向还原校验 ----
    back = txt10
    back = back.replace(NOTE_V10.rstrip("\n") + "\r\n", "", 1)
    for old, new, tag in EDITS:
        if back.count(new) != 1:
            print("[REFUSE] 反向还原失败：new 片段 %r 出现 %d 次" % (tag, back.count(new)))
            return 2
        back = back.replace(new, old, 1)
    if back.encode("utf-8") != b9:
        print("[REFUSE] 反向还原不是逐字节等于 v9")
        return 2
    for _old, new, tag in EDITS:
        if txt10.count(new) != 1:
            print("[REFUSE] 结果里 new 片段 %r 出现 %d 次" % (tag, txt10.count(new)))
            return 2
    if b10.count(b"\n") != b10.count(b"\r\n") or b10.count(b"\r") != b10.count(b"\r\n"):
        print("[REFUSE] 产物行尾不是纯 CRLF")
        return 2
    V10.write_bytes(b10)
    print("== v10 写出：%d B（v9 %d B，Δ%+d）、%d 行（Δ%+d）" % (
        len(b10), len(b9), len(b10) - len(b9), len(lines) - 1, (len(lines) - 1) - V9_LINES))
    print("== sha256 %s" % hashlib.sha256(b10).hexdigest())
    print("== 反向还原 = 逐字节等于 v9 ✓；%d 处替换 + 1 行 v10 注" % len(EDITS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
