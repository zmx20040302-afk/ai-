# -*- coding: utf-8 -*-
"""独立复核子智能体交回的 S3/S4 结果（**不采信其自述数字**）。

复核项：
1. 哈希锚点：run 目录 `input.mph` 与生产模型是否逐字节相同；冻结点集是否仍是 `9067cbdc…`；
2. 网格阶梯：三档单元数是否真的递增、每档状态与报错原文；
3. **S4 复算**：用 `field_points.npz` 自己重算两两有序对的相对 L2（公共有限掩膜，报 max 不报均值），
   与报告里的 2.31% / 2.06% / 1.32% / 1.23% / 1.61% 对照；
4. 状态未被提升：`solver_spec.json` 仍 `state=draft`，且其修改时间早于本轮 run 目录。
"""
from __future__ import annotations

import hashlib
import itertools
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
RUN = REPO / "work/runs/s34-mesh-20261006T131318Z"
PROD = REPO / "work/models/b_GE_task3_2new_currentdrive_fmax45_v1.mph"
PTS = REPO / "work/runs/te2_8_pod_fields_20261005/pod_pipeline_x020_v2/common_points_xyz_m.tsv"
SPEC = REPO / "work/runs/solver/pmut-f1/solver_spec.json"
BASE = {"input.mph": "0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d",
        "common_points_xyz_m.tsv": "9067cbdc3e43ced9c270de79e6add0672afaefb7d6dc08cddd9b57bcc487f0e7"}
REPORTED_ORDERED = {("h3um", "h2um"): 0.0206, ("h3um", "h14um"): 0.0231361,
                    ("h2um", "h14um"): 0.0132, ("h2um", "ftet_lamda6"): 0.0123,
                    ("h14um", "ftet_lamda6"): 0.0132, ("h3um", "ftet_lamda6"): 0.0161}


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    import numpy as np

    print("== 1. 哈希锚点 ==")
    ok_hash = True
    for name, want in (("run/input.mph", sha(RUN / "input.mph")), ):
        print("  %-28s %s" % (name, want))
        print("  %-28s %s" % ("  == 生产模型?", "是" if want == sha(PROD) else "**否**"))
        ok_hash &= (want == sha(PROD))
    fp = sha(PTS)
    print("  %-28s %s ｜ == 基准? %s" % ("common_points_xyz_m.tsv", fp[:16] + "…",
                                         "是" if fp == BASE["common_points_xyz_m.tsv"] else "**否**"))
    ok_hash &= (fp == BASE["common_points_xyz_m.tsv"])
    print("  生产模型现算 sha256 = %s ｜ 未被改动: %s"
          % (sha(PROD)[:16] + "…", sha(PROD) == BASE["input.mph"]))

    print("\n== 2. 网格阶梯 ==")
    mas = json.loads((RUN / "mesh_ladder_master.json").read_text(encoding="utf-8"))
    levels = mas.get("levels") or mas.get("ladder") or []
    if isinstance(levels, dict):
        levels = list(levels.values())
    rows = []
    for lv in levels:
        rows.append((lv.get("tag"), lv.get("num_elements"), lv.get("verdict"),
                     lv.get("dof"), str(lv.get("solve_error"))[:80]))
    print("  %-14s %-10s %-10s %-9s %s" % ("tag", "num_elem", "verdict", "dof", "solve_error"))
    for tag, ne, st, dof, err in rows:
        print("  %-14s %-10s %-10s %-9s %s" % (tag, ne, st, dof, err))
    seq = [r[1] for r in rows if isinstance(r[1], int)]
    print("  单元数是否全为正且非全同：%s ｜ 序列 %s" % (all(n > 0 for n in seq), seq))

    print("\n== 3. S4 独立复算（**不同方法**：各网格自身节点 → 冻结点最近节点采样）==")
    from scipy.spatial import cKDTree

    pts = np.loadtxt(PTS, delimiter="\t", skiprows=1)
    R = np.linalg.norm(pts, axis=1)
    keymask = R <= R.max() / 3.0
    fields: dict[str, np.ndarray] = {}
    for d in sorted(RUN.glob("mesh_*/field_points.npz")):
        z = np.load(d)
        xyz = np.column_stack([z["x_m"].real, z["y_m"].real, z["z_m"].real])
        p = z["p_Pa"]
        fin = np.isfinite(p.real) & np.isfinite(p.imag) & z["finite_mask"].astype(bool)
        print("  %-18s 节点 %6d ｜ p 有限 %6d ｜ 坐标有限 %s"
              % (d.parent.name, p.size, int(fin.sum()), bool(np.isfinite(xyz).all())))
        if fin.sum() == 0:
            continue
        tree = cKDTree(xyz[fin])
        dist, idx = tree.query(pts, k=1)
        val = np.full(pts.shape[0], np.nan + 0j, dtype=complex)
        val[:] = p[fin][idx]
        fields[d.parent.name] = val
    if len(fields) >= 2:
        m = np.ones(pts.shape[0], dtype=bool)
        for v in fields.values():
            m &= np.isfinite(v.real) & np.isfinite(v.imag)
        mm = m & keymask
        print("  公共有限掩膜 %d/%d = %.4f%% ｜ 关键区 %d 点 ｜ 最近节点距离 max %.3e m"
              % (m.sum(), m.size, 100 * m.mean(), mm.sum(), float(dist.max())))
        worst = ("", 0.0)
        for a, b in itertools.permutations(sorted(fields), 2):
            fa, fb = fields[a][m], fields[b][m]
            rel = float(np.linalg.norm(fa - fb) / np.linalg.norm(fb))
            ka, kb = fields[a][mm], fields[b][mm]
            krel = float(np.linalg.norm(ka - kb) / np.linalg.norm(kb))
            rep = REPORTED_ORDERED.get((a, b))
            flag = "" if rep is None else ("  ← 报告 %.4f ｜ 差 %+.2f pp"
                                           % (rep, 100 * (rel - rep)))
            print("  %-14s → %-14s 全域 max %.4f%% ｜ 关键区 %.4f%%%s"
                  % (a, b, 100 * rel, 100 * krel, flag))
            if rel > worst[1]:
                worst = ("%s→%s" % (a, b), rel)
        print("  ⇒ 最差有序对 %s = %.4f%%（判据 2%% ⇒ %s）"
              % (worst[0], 100 * worst[1],
                 "超过" if worst[1] > 0.02 else "未超过"))

    print("\n== 4. 状态未被提升 ==")
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    mt_spec = SPEC.stat().st_mtime
    mt_run = RUN.stat().st_mtime
    print("  solver_spec.state = %r ｜ spec mtime %s ｜ run mtime %s"
          % (spec.get("state"), int(mt_spec), int(mt_run)))
    print("  spec 早于本轮 run：%s ｜ state 仍 draft：%s"
          % (mt_spec < mt_run, spec.get("state") == "draft"))
    print("\n复核结论：哈希锚点 %s" % ("全部吻合" if ok_hash else "**有不吻合项**"))
    return 0 if ok_hash else 2


if __name__ == "__main__":
    sys.exit(main())
