# -*- coding: utf-8 -*-
"""回归用例：锁住轮 2 `T_C/*/B_nn` 的**广播 bug 修复**（2026-09-28）。

缺陷回顾：`a6_round2_eval.py` 的 `T_C` 块里，`ytr` 形状是 `(n_train, 1)`，
于是最近邻基线 `yh` 是 `(n_test, 1)`，而 `ytrue` 是一维 `(n_test,)`
⇒ `inv(yh) - ytrue` **广播成 `(n_test, n_test)`**，`e.max()` 取到**错配组合**上的最大值。
`B_mean`/`B_fam` 天然一维、`M1/M2/M3` 显式取了 `[:, 0]`，**只有 `B_nn` 中招**。

本用例锁三件事（fail-closed）：
1. **修正值正确**：`CORRECTED.json` 的 `spl_20MHz_dB` B_nn = 10.03%，与轮 1 的基线一致；
   `p_abs_20MHz_Pa` 的 B_nn = 83.1%，与轮 1 文档记录的最优基线一致；
2. **历史不被改写**：原 `a6_round2_result.json` 仍是 48.54%（append-only 底线）；
3. **差异封闭**：新旧 JSON 的差异**只能**落在 `T_C/*/B_nn/*` —— 别处一处都不许变。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
A6 = REPO / "work/runs/remote-exported-20260922/a6"
OLD_J = A6 / "a6_round2_result.json"
NEW_J = A6 / "a6_round2_result.CORRECTED.json"
R1_J = A6 / "a6_debug_result.json"

pytestmark = pytest.mark.skipif(not (OLD_J.is_file() and NEW_J.is_file()),
                                reason="轮 2 结果文件不在（本机 work/ 缺失）")


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_corrected_baseline_matches_round1():
    new = load(NEW_J)
    s1o = new["T_C"]["R2-S1o"]
    spl = s1o["spl_20MHz_dB"]["F1"]["B_nn"]["max_rel_err"]
    pab = s1o["p_abs_20MHz_Pa"]["F1"]["B_nn"]["max_rel_err"]
    assert spl == pytest.approx(0.100292, abs=1e-5), spl
    assert pab == pytest.approx(0.831207, abs=1e-5), pab

    # 与轮 1 的基线交叉验证（两条独立代码路径必须一致）
    r1 = load(R1_J)["targets"]["S1_cross_family"]
    assert spl == pytest.approx(r1["spl_20MHz_dB"]["baselines_max"]["B3_nearest_neighbour"],
                               abs=1e-5), "spl_20MHz_dB 的 B_nn 必须等于轮 1 的 B3"
    assert pab == pytest.approx(r1["p_abs_20MHz_Pa"]["baselines_max"]["B3_nearest_neighbour"],
                               abs=1e-4), "p_abs 的 B_nn 必须等于轮 1 的 B3"


def test_history_is_not_rewritten():
    """append-only 底线：历史 JSON 必须保留**错误值**（48.54%），修正走新文件。"""
    old = load(OLD_J)
    v = old["T_C"]["R2-S1o"]["spl_20MHz_dB"]["F1"]["B_nn"]["max_rel_err"]
    assert v == pytest.approx(0.485379, abs=1e-5), (
        "历史 a6_round2_result.json 被改写了？修正必须落在 CORRECTED 文件里，不得回改历史")


def test_diff_is_confined_to_b_nn():
    """新旧差异**只能**在 `T_C/*/B_nn/*`；别处一处都不许变（证明修复是外科式的）。"""
    old, new = load(OLD_J), load(NEW_J)
    diffs: list[str] = []

    def walk(a, b, path=""):
        if type(a) is not type(b):
            diffs.append(path)
            return
        if isinstance(a, dict):
            for k in sorted(set(a) | set(b)):
                if k not in a or k not in b:
                    diffs.append(path + "/" + k)
                else:
                    walk(a[k], b[k], path + "/" + k)
        elif isinstance(a, list):
            if len(a) != len(b):
                diffs.append(path)
                return
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, "%s[%d]" % (path, i))
        elif a != b:
            diffs.append(path)

    walk(old, new)
    assert diffs, "新旧文件完全相同 ⇒ 修复没生效？"
    bad = [d for d in diffs if not (d.startswith("/T_C/") and "/B_nn/" in d)]
    assert not bad, "出现了 B_nn 之外的差异（修复不外科）：%s" % bad[:5]
    # 两个目标 × 两个切分 × 两个特征 × {max,median} = 16 处
    assert len(diffs) == 16, len(diffs)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
