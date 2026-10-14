# -*- coding: utf-8 -*-
"""场级**查表**入口：只对**实测到的离散参数组合**给场，其余一律拒答。

为什么这样定（2026-10-06，用户把场级门禁定为 2%→5% 之后）：
实测证据表明 `N1` 方向**不光滑** —— 单位范数场形状在 `N1=2→3` 之间几乎正交（相关 **0.207**），
幅值在 `N1=3→4` 跳 **4.29 倍**。在 2% 门禁下最佳模型 **0/7 折**达标（最好折仍是阈值的 1.9 倍），
放宽到 5% 也只有 **2/7 折**达标、最坏折是阈值的 **16.2 倍**。
⇒ 任何"沿 N1 插值/外推的场"都**无法声称**满足门禁。**能声称的只有实测点本身。**

因此本模块的口径（写死，不许在调用处放宽）：
* **命中实测组合** ⇒ 返回该快照（文件名、点数、导出方的 train/holdout 标注、是否需要下载）；
* **未命中**（含任何**小数 N1**、未扫过的 x、N1 ≥ N2 等）⇒ **`refused=True` + 原因**，
  **不返回任何数字**，并提示回退 COMSOL；
* **只做查表，不做插值**：插值要另行通过预注册的 A 分支验证，不能在这里偷偷补上。

数据来源（只读）：`work/runs/te2_8_pod_fields_20261005/snapshot_index.tsv`（572 行，导出方清单）。

用法：
    work\\.venv\\Scripts\\python.exe -m memsharness.field_lookup --x 0.20 --n1 1 --n2 8 --freq 20000000
"""
from __future__ import annotations

import csv
import pathlib
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[2]
INDEX = REPO / "work/runs/te2_8_pod_fields_20261005/snapshot_index.tsv"
LOCAL_DIR = REPO / "work/runs/te2_8_pod_fields_20261005"
TOL = 1e-9

REASON_NO_FRACTIONAL = (
    "N_w_te1 是**电极对数**，数据里只有整数；小数 N1 需要插值，"
    "而实测表明场形状在 N1=2→3 几乎正交（相关 0.207）⇒ 插值口径**未获验证**，故拒答。"
    "如需小数 N1，请走预注册的 A 分支（用小数 N1 的 COMSOL 真值做留出集）并取得放行。")
REASON_NOT_MEASURED = "该 (x_scale, N1, N2, freq) 组合**不在已测量的离散网格上**；本口径只对实测点给场。"
REASON_FALLBACK = "回退 COMSOL：请对该组合提交求解，或先用相邻实测点做趋势判断（趋势 ≠ 绝对值）。"


def load_index(path: pathlib.Path | None = None) -> list[dict]:
    p = pathlib.Path(path) if path else INDEX
    if not p.is_file():
        raise FileNotFoundError("缺清单（work/ 不进版本库？）：%s" % p)
    with p.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def lookup(x_scale: float, n1: float, n2: float, freq_Hz: float,
           *, index: list[dict] | None = None, local_dir: pathlib.Path | None = None) -> dict:
    """查表。命中→给快照元数据；未命中→拒答（**不含任何数字**）。"""
    rows = index if index is not None else load_index()
    base: dict = {"query": {"x_scale": x_scale, "N_w_te1": n1, "N_w_te2": n2,
                           "freq_Hz": freq_Hz},
                  "mode": "discrete_lookup", "interpolation": "forbidden"}
    # ① 小数 N1：直接拒答（这是本次要立的规矩）
    if abs(n1 - round(n1)) > TOL:
        return {**base, "refused": True, "reason": REASON_NO_FRACTIONAL,
                "fallback": "comsol", "hint": REASON_FALLBACK}
    # ② 物理上不存在的层
    if n1 < 1 or round(n1) >= round(n2):
        return {**base, "refused": True,
                "reason": "该层不存在：要求 1 ≤ N1 < N2（收到 N1=%g, N2=%g）" % (n1, n2),
                "fallback": "comsol"}
    # ③ 精确命中
    hits = [r for r in rows
            if abs((_num(r.get("x_scale")) or -1) - x_scale) <= TOL
            and abs((_num(r.get("N_w_te1")) or -1) - n1) <= TOL
            and abs((_num(r.get("N_w_te2")) or -1) - n2) <= TOL
            and abs((_num(r.get("freq_Hz")) or -1) - freq_Hz) <= TOL]
    if not hits:
        return {**base, "refused": True, "reason": REASON_NOT_MEASURED,
                "fallback": "comsol", "hint": REASON_FALLBACK,
                "index_coverage": coverage(rows)}
    r = hits[0]
    name = pathlib.Path(str(r.get("file"))).name
    d = pathlib.Path(local_dir) if local_dir else LOCAL_DIR
    local = None
    for cand in (d / name, d / "x020" / name):
        if cand.is_file():
            local = str(cand.relative_to(REPO))
            break
    return {**base, "refused": False, "file": name,
            "remote_path": r.get("file"),
            "n_points": _num(r.get("n_points")),
            "split": {"x_holdout_role": r.get("x_holdout_role"),
                      "n_holdout_role": r.get("n_holdout_role")},
            "status": r.get("status"), "kind": r.get("kind", "").strip(),
            "local_copy": local,
            "needs_download": local is None,
            "note": ("这是**实测快照**（查表给场）；本模块不做插值，也不给任何外推。")}


def coverage(rows: list[dict] | None = None) -> dict:
    """这个数据集**能回答哪些查询**（用来解释为什么拒答）。"""
    rows = rows if rows is not None else load_index()
    xs = sorted({_num(r.get("x_scale")) for r in rows if _num(r.get("x_scale")) is not None})
    n1s = sorted({_num(r.get("N_w_te1")) for r in rows if _num(r.get("N_w_te1")) is not None})
    n2s = sorted({_num(r.get("N_w_te2")) for r in rows if _num(r.get("N_w_te2")) is not None})
    fs = sorted({_num(r.get("freq_Hz")) for r in rows if _num(r.get("freq_Hz")) is not None})
    return {"n_rows": len(rows), "x_scale": xs, "N_w_te1": n1s, "N_w_te2": n2s,
            "freq_Hz": fs,
            "note": "只有这些值可以查表；其余（含小数 N1、未扫 x）一律拒答。"}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="场级离散查表（不做插值）")
    ap.add_argument("--x", type=float, default=0.20)
    ap.add_argument("--n1", type=float, default=1.0)
    ap.add_argument("--n2", type=float, default=8.0)
    ap.add_argument("--freq", type=float, default=20000000.0)
    ap.add_argument("--coverage", action="store_true")
    a = ap.parse_args(argv)
    if a.coverage:
        print(json.dumps(coverage(), ensure_ascii=False, indent=1)[:1200])
        return 0
    print(json.dumps(lookup(a.x, a.n1, a.n2, a.freq), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
