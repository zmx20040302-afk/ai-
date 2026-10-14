# -*- coding: utf-8 -*-
"""路线甲第 1 步：取 N1=4 的 x 族全部 81 个快照，插值到**已冻结的公共点集**。

本步**只做对齐**，不做 POD（先确认掩膜率与耗时，再进下一步）。
* 下载：仅缺失的才 `scp`（远端**只读**，不建临时文件）；
* 公共点集：**复用** `pod_pipeline_x020_v2/common_points_xyz_m.tsv`（1373 点，半径约 100 µm 的下半球）。
  理由：x_scale=0.20 是最小几何 ⇒ 其半球最小，其中的点在更大几何里仍应有限；
  该文件已冻结且有哈希（**不重新生成**，以便与 x=0.20 的既有结果同口径）；
* 插值：`griddata(linear)`，**复数拆实/虚**，域外留 NaN（**绝不当 0**）；
* 公共掩膜 = 所有快照上都有限且插值成功的点；
* 落缓存 `x_family/n1_4/interp_cache_x_n1_4.npz`，供下一步 POD 复用。

用法：work\\.venv\\Scripts\\python.exe scripts\\fetch_and_align_x_family.py --n1 4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
RUN = REPO / "work/runs/te2_8_pod_fields_20261005"
HOST = "ubuntu-10-180-7-46"
RDIR = "/home/lab/projAI4US/autodesign/exported_results/te2_8_pod_fields_20MHz_v1/pod_20MHz"
FROZEN_POINTS = RUN / "pod_pipeline_x020_v2/common_points_xyz_m.tsv"
OUTDIR = RUN / "x_family"


def sha(p: pathlib.Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n1", type=float, default=4.0)
    ap.add_argument("--timeout", type=float, default=900.0)
    a = ap.parse_args(argv)
    import numpy as np
    import scipy.io as sio
    from scipy.interpolate import griddata

    tag = "n1_%g" % a.n1
    d = OUTDIR / tag
    d.mkdir(parents=True, exist_ok=True)
    man_path = OUTDIR / ("x_family_manifest_n1_%g.json" % a.n1)
    if not man_path.is_file():
        print("[FAIL] 缺族清单 %s（先跑 plan_x_family.py --n1 %g）"
              % (man_path.name, a.n1)); return 2
    man = json.loads(man_path.read_text(encoding="utf-8"))
    # ⚠️ **参数一致性门禁**（初版只 WARN 就继续，结果拿 N1=7 的清单跑了"N1=4 的族"）：
    # 清单里的 N1 与命令行不一致 ⇒ **拒绝运行**，不猜、不自动纠正。
    if float(man["family"]["fixed"]["N_w_te1"]) != float(a.n1):
        print("[FAIL] 清单是 N1=%s 的，但本次请求 N1=%s ⇒ 拒绝运行（避免张冠李戴）"
              % (man["family"]["fixed"]["N_w_te1"], a.n1)); return 2
    items = man["items"]
    rep: dict = {"kind": "x_family_fetch_and_align", "n1": a.n1,
                 "n_files": len(items), "points_file": str(FROZEN_POINTS.relative_to(REPO)),
                 "sha256_points_file": sha(FROZEN_POINTS), "errors": [],
                 "download": {"n_fetched": 0, "bytes": 0, "seconds": 0.0}, "per_file": []}
    t_dl = time.perf_counter()
    for it in items:
        p = d / it["file"]
        if not p.is_file():
            r = subprocess.run(["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                                "%s:%s/%s" % (HOST, RDIR, it["file"]), str(p)],
                               capture_output=True, text=True, timeout=a.timeout)
            if r.returncode != 0 or not p.is_file():
                rep["errors"].append("下载失败 %s: rc=%s %s"
                                     % (it["file"], r.returncode, (r.stderr or "")[-120:]))
                continue
            rep["download"]["n_fetched"] += 1
            rep["download"]["bytes"] += p.stat().st_size
    rep["download"]["seconds"] = round(time.perf_counter() - t_dl, 1)

    pts = np.loadtxt(FROZEN_POINTS, delimiter="\t", skiprows=1)
    cols, xs, roles_x, roles_n, names, ok_files = [], [], [], [], [], []
    t0 = time.perf_counter()
    for it in items:
        f = d / it["file"]
        if not f.is_file():
            continue
        m = sio.loadmat(str(f))
        src = np.column_stack([m["x_m"].ravel(), m["y_m"].ravel(), m["z_m"].ravel()])
        p = np.asarray(m["p_total_Pa"]).ravel()
        fin = np.asarray(m["p_finite_mask"]).ravel().astype(bool)
        t1 = time.perf_counter()
        re = griddata(src[fin], p[fin].real, pts, method="linear", fill_value=np.nan)
        im = griddata(src[fin], p[fin].imag, pts, method="linear", fill_value=np.nan)
        dt = time.perf_counter() - t1
        v = re + 1j * im
        cols.append(v)
        xs.append(float(it["x_scale"]))
        roles_x.append(str(it.get("split_x")))
        roles_n.append(str(it.get("split_n")))
        names.append(it["file"])
        ok_files.append(int(np.isfinite(v).sum()))
        rep["per_file"].append({"file": it["file"], "x_scale": it["x_scale"],
                                "n_src_finite": int(fin.sum()),
                                "n_finite_after": int(np.isfinite(v).sum()),
                                "seconds": round(dt, 2)})
    rep["align_seconds"] = round(time.perf_counter() - t0, 1)
    if not cols:
        rep["errors"].append("没有任何快照可用")
        (d / "fetch_align_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
        print("[FAIL] 无可用快照"); return 2
    P = np.column_stack(cols)
    mask = np.isfinite(P.real).all(axis=1) & np.isfinite(P.imag).all(axis=1)
    cache = d / ("interp_cache_x_%s.npz" % tag)      # ⚠️ 括号必须加：`/` 与 `%` 的优先级坑过
    np.savez_compressed(cache, P=P, mask=mask,
                        x_scale=np.array(xs), role_x=np.array(roles_x),
                        role_n=np.array(roles_n), names=np.array(names))
    rep["common_mask"] = {"n_frozen": int(pts.shape[0]), "n_common": int(mask.sum()),
                          "frac": float(mask.mean()), "threshold": 0.80,
                          "pass": bool(mask.mean() >= 0.80)}
    rep["n_snapshots_aligned"] = len(cols)
    rep["n_finite_per_snapshot"] = {"min": int(min(ok_files)), "max": int(max(ok_files))}
    rep["x_span"] = [min(xs), max(xs)]
    rep["split_counts"] = {"x_role": {k: roles_x.count(k) for k in set(roles_x)},
                           "n_role": {k: roles_n.count(k) for k in set(roles_n)}}
    rep["cache"] = str(cache.relative_to(REPO))
    rep["ok"] = True
    (d / "fetch_align_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    print("N1=%g 族：对齐 %d 个快照 ｜ 下载 %d 个 / %.1f MB / %.1fs"
          % (a.n1, len(cols), rep["download"]["n_fetched"],
             rep["download"]["bytes"] / 1e6, rep["download"]["seconds"]))
    print("公共掩膜：%d/%d = %.4f%%（门槛 80%% ⇒ %s）"
          % (rep["common_mask"]["n_common"], rep["common_mask"]["n_frozen"],
             100 * rep["common_mask"]["frac"], "通过" if rep["common_mask"]["pass"] else "未通过"))
    print("逐快照可用点数 min/max = %d/%d ｜ 插值合计 %.1fs"
          % (rep["n_finite_per_snapshot"]["min"], rep["n_finite_per_snapshot"]["max"],
             rep["align_seconds"]))
    print("x 范围 %s..%s ｜ 切分 %s" % (rep["x_span"][0], rep["x_span"][1],
                                       json.dumps(rep["split_counts"], ensure_ascii=False)))
    for e in rep["errors"][:5]:
        print("  [错误]", e[:150])
    print("缓存：", rep["cache"])
    return 0 if rep["common_mask"]["pass"] else 2


if __name__ == "__main__":
    sys.exit(main())
