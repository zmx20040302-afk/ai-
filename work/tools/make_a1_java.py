# -*- coding: utf-8 -*-
"""A1 生成器：把已验证的 `n1c_mesh_study.java`（本地 N1c 网格研究）**原样搬到服务器**跑 ×0.5 档。

为什么要生成而不是重写：A1 的全部价值在于**口径与本地各档逐字相同**（同一套电极/闭合面/声学面积分、
同一组选择集、同一表达式）。所以本脚本只做**两处**改动，其余**逐字节保持**：
  1. `public class n1c_mesh_study` → `public class p5_a1_solid_half`
  2. `__LEVEL_INDEX__` → 1（= `LEVELS[1]` = `solid_half`：ftri1 = 1E-6/3E-6/1.5E-6，ftet1 = lamda/5）

并打印**改动前后的 sha256**与**未改动字节数**，便于事后复核「没有顺手改口径」。
本地产物对照：`n1c_mesh_study/n1c_solid_half.json` 里 `mesh.status=ok`（342,635 单元）但
`solve.status=failed`（`FlException: Failed_to_find_a_solution`，墙钟 175.8 s）⇒ 那一档**从来只有网格、没有数**。
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
SRC = REPO / "work/runs/eda64-20261010/n1c_mesh_study/n1c_mesh_study.java"
DST = REPO / "work/runs/eda64-20261010/p5_a1/p5_a1_solid_half.java"
NEW_CLS = "p5_a1_solid_half"
LEVEL_INDEX = 1


def main() -> int:
    DST.parent.mkdir(parents=True, exist_ok=True)
    src = SRC.read_text(encoding="utf-8")
    s0 = hashlib.sha256(src.encode("utf-8")).hexdigest()
    n_lvl = len(re.findall(r"__LEVEL_INDEX__", src))
    n_cls = len(re.findall(r"__CLASS__", src))
    assert n_lvl == 1 and n_cls == 1, ("占位符计数不符", n_cls, n_lvl)
    # 注意：`n1c_mesh_study.java` 本身是**模板**，类名占位符是 `__CLASS__`（不是文件名）
    out = src.replace("__CLASS__", NEW_CLS).replace("__LEVEL_INDEX__", str(LEVEL_INDEX))
    # 复核「只改了这两处」：把改动**反向还原**后必须与原文逐字节相同
    restored = out.replace(NEW_CLS, "__CLASS__")
    restored = re.sub(r"(int li = )\d+(;)", r"\g<1>__LEVEL_INDEX__\g<2>", restored, count=1)
    assert restored == src, "还原后与原文不一致 ⇒ 生成过程动了口径之外的东西"
    DST.write_text(out, encoding="utf-8", newline="\n")
    s1 = hashlib.sha256(DST.read_bytes()).hexdigest()
    print("源    :", SRC.name, len(src), "chars", s0[:16])
    print("目标  :", DST.name, len(out), "chars", s1[:16])
    print("改动  : 类名 1 处 → %s；档位 1 处 → %d（solid_half）" % (NEW_CLS, LEVEL_INDEX))
    print("反向还原逐字节一致：True（⇒ 口径未动）")
    print("写出  :", DST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
