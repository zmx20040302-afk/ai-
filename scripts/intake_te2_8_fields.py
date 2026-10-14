# -*- coding: utf-8 -*-
"""取回并解析 te2_8 场级导出的**最小集**（清单 + 1 个 .mat），不搬 998 MB。

步骤（全部只读远端）：
1. scp `snapshot_index.tsv`（94 KB）与 `pod_20MHz/x0.20_N01_f20MHz.mat`（842 KB）；
2. 本地 sha256 留痕；
3. 解析清单：按 kind/status/role 计数、n_points 分布、x/N/频率覆盖、文件总数与"是否都真实存在"；
4. `scipy.io.loadmat` 列出 .mat 的**变量名与形状**（确认场变量、坐标、是否复数）
   —— 这一步决定 POD 怎么读；**读不到就如实写读不到，不猜**。
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
HOST = "ubuntu-10-180-7-46"
REMOTE = "/home/lab/projAI4US/autodesign/exported_results/te2_8_pod_fields_20MHz_v1"
OUT = REPO / "work/runs/te2_8_pod_fields_20261005"
OUT.mkdir(parents=True, exist_ok=True)
TSV = OUT / "snapshot_index.tsv"
MAT = OUT / "x0.20_N01_f20MHz.mat"
REPORT = OUT / "intake_report.json"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def scp(remote_rel: str, dest: pathlib.Path) -> dict:
    if dest.is_file():
        return {"skipped": "already local", "bytes": dest.stat().st_size}
    r = subprocess.run(["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                        "%s:%s/%s" % (HOST, REMOTE, remote_rel), str(dest)],
                       capture_output=True, text=True, timeout=600)
    return {"rc": r.returncode, "stderr": (r.stderr or "")[-300:],
            "bytes": dest.stat().st_size if dest.is_file() else None}


def main() -> int:
    rep: dict = {"kind": "te2_8_pod_fields_intake", "remote": "%s:%s" % (HOST, REMOTE),
                 "fetched": {}, "ok": False, "steps": [], "errors": []}
    rep["fetched"]["snapshot_index.tsv"] = scp("snapshot_index.tsv", TSV)
    rep["fetched"]["x0.20_N01_f20MHz.mat"] = scp("pod_20MHz/x0.20_N01_f20MHz.mat", MAT)
    if TSV.is_file():
        rep["sha256_snapshot_index"] = sha(TSV)
    if MAT.is_file():
        rep["sha256_one_mat"] = sha(MAT)

    # ---- 3 解析清单（权威统计）----
    if TSV.is_file():
        rows = list(csv.DictReader(TSV.open(encoding="utf-8", newline=""),
                                   delimiter="\t"))
        rep["tsv_rows"] = len(rows)
        for key in ("kind", "status", "x_holdout_role", "n_holdout_role"):
            rep["by_" + key] = dict(collections.Counter(
                (r.get(key) or "").strip() for r in rows))
        np_ = []
        for r in rows:
            try:
                np_.append(int(r["n_points"]))
            except (KeyError, TypeError, ValueError):
                pass
        if np_:
            np_.sort()
            rep["n_points"] = {"n": len(np_), "min": np_[0], "p50": np_[len(np_) // 2],
                               "max": np_[-1], "sum": sum(np_)}
        def uniq(key):
            return sorted({(r.get(key) or "").strip() for r in rows})
        rep["x_values"] = uniq("x_scale")
        rep["n1_values"] = uniq("N_w_te1")
        rep["n2_values"] = uniq("N_w_te2")
        rep["freq_values"] = uniq("freq_Hz")
        # 清单引用的文件在本地镜像里存在几个（远端路径 → 相对 pod_20MHz 的文件名）
        names = [pathlib.Path((r.get("file") or "").strip()).name for r in rows]
        rep["n_distinct_referenced_files"] = len(set(names))
        rep["file_ext_counts"] = dict(collections.Counter(
            pathlib.Path(n).suffix for n in names))
        rep["steps"].append("解析清单：%d 行" % len(rows))

    # ---- 4 读一个 .mat ----
    if MAT.is_file():
        try:
            import scipy.io as sio
            import numpy as np
            m = sio.loadmat(str(MAT))
            vars_ = {}
            for k, v in m.items():
                if k.startswith("__"):
                    continue
                info = {"type": type(v).__name__}
                try:
                    info["shape"] = list(np.shape(v))
                    info["dtype"] = str(np.asarray(v).dtype)
                    info["is_complex"] = bool(np.iscomplexobj(v))
                except Exception as exc:  # noqa: BLE001
                    info["note"] = "形状读取失败：%s" % exc
                vars_[k] = info
            rep["mat_variables"] = vars_
            rep["mat_reader"] = "scipy.io.loadmat (v5)"
            rep["steps"].append("读 .mat：%d 个变量" % len(vars_))
        except Exception as exc:  # noqa: BLE001
            rep["errors"].append("读 .mat 失败：%s: %s" % (type(exc).__name__, exc))

    rep["ok"] = bool(rep.get("tsv_rows"))
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("tsv_rows        :", rep.get("tsv_rows"))
    print("kind            :", json.dumps(rep.get("by_kind"), ensure_ascii=False))
    print("status          :", json.dumps(rep.get("by_status"), ensure_ascii=False))
    print("x_holdout_role  :", json.dumps(rep.get("by_x_holdout_role"), ensure_ascii=False))
    print("n_holdout_role  :", json.dumps(rep.get("by_n_holdout_role"), ensure_ascii=False))
    print("n_points        :", json.dumps(rep.get("n_points"), ensure_ascii=False))
    print("x_values        :", rep.get("x_values"))
    print("n1_values       :", rep.get("n1_values"))
    print("n2_values       :", rep.get("n2_values"))
    print("freq_values     :", rep.get("freq_values"))
    print("distinct files  :", rep.get("n_distinct_referenced_files"),
          rep.get("file_ext_counts"))
    print("mat variables   :", json.dumps(rep.get("mat_variables"), ensure_ascii=False)[:900])
    for e in rep["errors"]:
        print("  [错误]", e[:200])
    print("报告：", REPORT.relative_to(REPO))
    return 0 if rep["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
