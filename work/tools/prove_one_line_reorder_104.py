# -*- coding: utf-8 -*-
"""内存内重建改动前的 `_classify_refusal`，证明本轮**只调了一次次序**（不写任何文件）。"""
from __future__ import annotations

import difflib
import hashlib
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
P = REPO / "src/memsharness/multichannel_surrogate.py"

NEW = '''def _classify_refusal(msg: str) -> str:
    """把拒答原因归类，便于筛查时做直方图（**只归类，不改变拒答本身**）。

    \u26a0\ufe0f **本表的次序就是优先级（先命中先返回），不得随意调换**：
    结构约束的原文是 `该层不存在：要求 N_w_te1 < N_w_te2`，**这句本身含子串 `N_w_te2`**
    \u21d2 若把 `N_w_te2` 排在 `该层不存在` 之前，结构约束会被**误报成 N2 越域**
    （\u00a7101.5/\u00a7102 实测：E3 的 476 点网格上 102 条被误标）。
    本轮修法**只调次序、不动任何模式与阈值**，故只有「层不存在」这一类的归属会变。
    """
    for key, pat in (("no_layer_for_n1", "没有该 N1"), ("need_two_layers", "只有一层"),
                     ("x_outside_layer_range", "超出该层标定"), ("x_out_of_domain", "x_scale"),
                     # \u2193 结构约束必须**先于** N2 越域匹配（上句含 "N_w_te2" 子串，会子串碰撞）
                     ("layer_does_not_exist", "该层不存在"), ("n2_out_of_domain", "N_w_te2"),
                     ("n2_extrap_too_far", "外推超过"), ("x_missing", "同一个 x")):
        if pat in msg:
            return key
    return "other"'''

OLD = '''def _classify_refusal(msg: str) -> str:
    """把拒答原因归类，便于筛查时做直方图（**只归类，不改变拒答本身**）。"""
    for key, pat in (("no_layer_for_n1", "没有该 N1"), ("need_two_layers", "只有一层"),
                     ("x_outside_layer_range", "超出该层标定"), ("x_out_of_domain", "x_scale"),
                     ("n2_out_of_domain", "N_w_te2"), ("layer_does_not_exist", "该层不存在"),
                     ("n2_extrap_too_far", "外推超过"), ("x_missing", "同一个 x")):
        if pat in msg:
            return key
    return "other"'''


def main() -> int:
    cur = P.read_text(encoding="utf-8")
    assert cur.count(NEW) == 1, "找不到改动后的函数原文（count=%d）" % cur.count(NEW)
    rec = cur.replace(NEW, OLD)
    nb, ob = cur.encode("utf-8"), rec.encode("utf-8")
    print("改动后文件 %d B  sha256 %s" % (len(nb), hashlib.sha256(nb).hexdigest()))
    print("重建改动前 %d B  sha256 %s" % (len(ob), hashlib.sha256(ob).hexdigest()))
    print("重建 sha == 改动前实测 sha 81df9ca0…d1f4b ⇒ %s"
          % (hashlib.sha256(ob).hexdigest() ==
             "81df9ca0935d3d7a1bb3b6b2344afec7ffb2d5461119e73ad860bf1bec2d1f4b"))
    print("净增字节 = %+d（%d → %d）" % (len(nb) - len(ob), len(ob), len(nb)))
    print("除去本函数外，文件其余部分逐字节相同 = %s"
          % (rec.replace(OLD, "") == cur.replace(NEW, "")))
    print("---- 函数体 unified diff（n=0，无上下文） ----")
    for line in difflib.unified_diff(OLD.splitlines(), NEW.splitlines(),
                                     "before", "after", lineterm="", n=0):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
