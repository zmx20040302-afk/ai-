# -*- coding: utf-8 -*-
"""盘点器械：te2_9 v1 新导出的**产物清单 + 完整性普查**（产物到位即可运行；不解析语义、不出结论）。

回答三件事，并给出 `ready_for_parse`：

1. **有哪些文件**：`Table_9/10/11.txt`、`Zdisplacement.txt`、`Peak_frequency.txt`、`Bandwidth.txt`、
   `output_manifest.tsv`（+ `.mat`）是否到位、大小、sha256；
2. **manifest 对不对**：若 `output_manifest.tsv` 在位，按其 `sha256` / `size_bytes` 逐文件回读校验
   （**清单说 A、实际是 B ⇒ 报错**，不放过）；
3. **网格齐不齐**：Table_9 的 组合数 / 频点数 / 步长 / x 与 N1 取值，与声明
   （648 = 81×8×1、91 点 5–50 MHz 步长 0.5）对账，缺哪个组合点名列出。

只读：不改任何既有产物，输出只落 `--out-dir`。
退出码：0 齐全（`ready_for_parse=True`）｜2 用法错误｜3 **产物未到位**｜4 到位但内部不一致（网格/清单不符）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from parse_te29_v1 import (  # noqa: E402
    EXPECT_COMBOS, EXPECT_N1, EXPECT_N2, EXPECT_NFREQ, EXPECT_X, FREQ_HI_HZ, FREQ_LO_HZ,
    FREQ_STEP_HZ, FREQ_TOL_HZ, INVENTORY_FILES, REPO, parse_export,
)

DEFAULT_ROOT = REPO / "work/runs/te29-freq5-50-server-20261009"
DEFAULT_OUT_DIR = REPO / "work/runs/te29-prep-20261009/profile"


def sha256_of(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_product_dirs(root: pathlib.Path) -> list[pathlib.Path]:
    """root 下所有「含 Table_9.txt」的目录（去重、稳定排序）。"""
    hits = {p.parent.resolve() for p in root.rglob("Table_9.txt") if "__pycache__" not in p.parts}
    return sorted(hits)


def read_manifest(p: pathlib.Path) -> dict:
    """→ {basename: (sha256, size)}；同时记录重复 basename。"""
    out, dups = {}, []
    if not p.is_file():
        return {"entries": {}, "dups": [], "n_lines": 0, "error": "manifest 不存在"}
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    body = [ln for ln in lines[1:] if ln.strip()]
    for ln in body:
        toks = ln.split("\t")
        if len(toks) < 3:
            toks = ln.split()
            if len(toks) < 3:
                continue
        sha, size, path = toks[0], toks[1], "\t".join(toks[2:])
        name = pathlib.PurePosixPath(path.replace("\\", "/")).name
        if name in out:
            dups.append(name)
        try:
            out[name] = (sha, int(size))
        except ValueError:
            continue
    return {"entries": out, "dups": dups, "n_lines": len(lines), "n_entries": len(out)}


def profile(root: pathlib.Path) -> tuple[int, dict]:
    rep: dict = {"root": str(root), "declared": {
        "n_combos": EXPECT_COMBOS, "n_freq": EXPECT_NFREQ,
        "x_lo": EXPECT_X[0], "x_hi": EXPECT_X[-1], "n_x": len(EXPECT_X),
        "N_w_te1": list(EXPECT_N1), "N_w_te2": list(EXPECT_N2),
        "freq_lo_Hz": FREQ_LO_HZ, "freq_hi_Hz": FREQ_HI_HZ, "freq_step_Hz": FREQ_STEP_HZ},
        "n_table9_rows_expected": EXPECT_COMBOS * EXPECT_NFREQ}
    if not root.exists():
        return 3, {**rep, "ready_for_parse": False, "problems": ["根目录不存在"],
                   "error": "根目录不存在：%s（产物未到位）" % root}
    dirs = find_product_dirs(root)
    rep["product_dirs"] = [str(d) for d in dirs]
    if not dirs:
        rep["files"] = {}
        rep["ready_for_parse"] = False
        rep["error"] = ("在 %s 下没找到 Table_9.txt —— 产物未到位（导出可能还在跑）" % root)
        return 3, rep

    d = dirs[-1]                     # 多个时取最新（按路径排序的最末一个，并在报告里点明）
    rep["chosen_dir"] = str(d)
    rep["n_product_dirs"] = len(dirs)
    files = {}
    for name in INVENTORY_FILES:
        p = d / name
        if p.is_file():
            files[name] = {"present": True, "size_bytes": p.stat().st_size,
                           "sha256": sha256_of(p)}
        else:
            files[name] = {"present": False, "size_bytes": None, "sha256": None}
    for p in sorted(d.glob("*.mat")):
        files[p.name] = {"present": True, "size_bytes": p.stat().st_size, "sha256": sha256_of(p)}
    rep["files"] = files
    rep["missing_files"] = [n for n, v in files.items() if not v["present"]]

    man_path = d / "output_manifest.tsv"
    man = read_manifest(man_path)
    rep["manifest"] = {"present": man_path.is_file(), "n_lines": man["n_lines"],
                       "n_entries": man.get("n_entries", 0), "duplicate_basenames": man.get("dups", [])}
    problems: list[str] = []
    if man_path.is_file():
        checks, mismatch = [], []
        for name, info in sorted(files.items()):
            if not info["present"] or name == "output_manifest.tsv":
                continue
            ent = man["entries"].get(name)
            if ent is None:
                checks.append({"file": name, "in_manifest": False})
                continue
            ok = (ent[0] == info["sha256"] and ent[1] == info["size_bytes"])
            checks.append({"file": name, "in_manifest": True, "sha_ok": ent[0] == info["sha256"],
                           "size_ok": ent[1] == info["size_bytes"], "ok": ok})
            if not ok:
                mismatch.append(name)
        rep["manifest"]["checks"] = checks
        rep["manifest"]["n_mismatch"] = len(mismatch)
        rep["manifest"]["mismatch_files"] = mismatch
        if mismatch:
            problems.append("manifest 与实际文件不符：%s" % "、".join(mismatch))
        nm = [n for n, v in files.items() if v["present"] and n not in man["entries"]
              and n != "output_manifest.tsv"]
        if nm:
            problems.append("manifest 未列出：%s" % "、".join(sorted(nm)))
    else:
        problems.append("缺 output_manifest.tsv")

    if (d / "Table_9.txt").is_file():
        try:
            res = parse_export(d, strict_grid=False, expect_combos=EXPECT_COMBOS,
                               expect_nfreq=EXPECT_NFREQ)
            diag = res["diag"]
            rep["grid"] = {
                "n_table9_rows": diag["n_table9_rows"],
                "n_combos": diag["n_combos"], "n_points": diag["n_points"],
                "n_freq": diag["n_freq"], "freq_lo_Hz": diag["freq_lo_Hz"],
                "freq_hi_Hz": diag["freq_hi_Hz"], "freq_step_Hz": diag["freq_step_Hz"],
                "freq_step_uniform": diag["freq_step_uniform"],
                "n_x_values": diag["n_x_values"], "x_min": diag["x_min"], "x_max": diag["x_max"],
                "N_w_te1_values": diag["N_w_te1_values"], "N_w_te2_values": diag["N_w_te2_values"],
                "grid_combos_match": diag["grid_combos_match"],
                "grid_nfreq_match": diag["grid_nfreq_match"],
                "n_missing_expected_combos": diag["n_missing_expected_combos"],
                "missing_expected_combos_sample": diag["missing_expected_combos_sample"],
                "n_unexpected_combos": diag["n_unexpected_combos"],
                "n_combos_with_nfreq_mismatch": diag["n_combos_with_nfreq_mismatch"],
                "bw_matched": diag["bw_matched"], "bw_unmatched": diag["bw_unmatched"],
                "n_peak_at_scan_endpoint": diag["n_peak_at_scan_endpoint"],
                "n_bw_upper_cutoff_at_endpoint": diag["n_bw_upper_cutoff_at_endpoint"],
                "n_usable": diag["n_usable"], "n_Q_decidable": diag["n_Q_decidable"],
                "n_Q_pass_2p5_3p5": diag["n_Q_pass_2p5_3p5"],
                "n_Q_nan_rows": diag["n_Q_nan_rows"],
                "n_normalization_collisions": diag["n_normalization_collisions"],
            }
            if EXPECT_COMBOS and diag["n_combos"] != EXPECT_COMBOS:
                problems.append("组合数 %d ≠ 声明 %d" % (diag["n_combos"], EXPECT_COMBOS))
            if EXPECT_NFREQ and diag["n_freq"] != EXPECT_NFREQ:
                problems.append("频点数 %d ≠ 声明 %d" % (diag["n_freq"], EXPECT_NFREQ))
            if abs(diag["freq_lo_Hz"] - FREQ_LO_HZ) > FREQ_TOL_HZ:
                problems.append("扫描下限 %g ≠ 声明 %g" % (diag["freq_lo_Hz"], FREQ_LO_HZ))
            if abs(diag["freq_hi_Hz"] - FREQ_HI_HZ) > FREQ_TOL_HZ:
                problems.append("扫描上限 %g ≠ 声明 %g" % (diag["freq_hi_Hz"], FREQ_HI_HZ))
            if not diag["freq_step_uniform"]:
                problems.append("频点步长不均匀")
            if diag["n_normalization_collisions"]:
                problems.append("归一化撞键 %d 个" % diag["n_normalization_collisions"])
            if diag["bw_unmatched"]:
                problems.append("有 %d 个组合未挂回 −3 dB level" % diag["bw_unmatched"])
        except FileNotFoundError as e:
            problems.append("解析前置文件缺失：%s" % e)
        except ValueError as e:
            problems.append("表头/列定位失败（fail-closed，拒绝猜列号）：%s" % e)
    else:
        problems.append("缺 Table_9.txt")

    rep["problems"] = problems
    rep["ready_for_parse"] = not problems
    return (0 if not problems else 4), rep


def write_md(rep: dict, out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = ["# te2_9 v1 新导出：产物盘点", "",
          "| 项 | 值 |", "|---|---|",
          "| 根目录 | `%s` |" % rep.get("root"),
          "| 命中产物目录数 | %s |" % rep.get("n_product_dirs"),
          "| 采用目录 | `%s` |" % rep.get("chosen_dir"),
          "| ready_for_parse | **%s** |" % rep.get("ready_for_parse"), ""]
    if rep.get("error"):
        md += ["> %s" % rep["error"], ""]
    if rep.get("files"):
        md += ["## 文件清单", "", "| 文件 | 在位 | 字节 | sha256 |", "|---|---|---|---|"]
        for n, v in rep["files"].items():
            md.append("| %s | %s | %s | %s |" % (n, v["present"], v["size_bytes"],
                                                 (v["sha256"] or "")[:16] + ("…" if v["sha256"] else "")))
        md.append("")
    if rep.get("manifest", {}).get("present"):
        md += ["## manifest 回读校验", "",
               "* 条目数 %s ｜ 重复 basename %s ｜ 不符 %s"
               % (rep["manifest"].get("n_entries"), rep["manifest"].get("duplicate_basenames"),
                  rep["manifest"].get("n_mismatch")), ""]
    if rep.get("grid"):
        g = rep["grid"]
        md += ["## 网格", "",
               "| 项 | 实测 | 声明 |", "|---|---|---|",
               "| 组合数 | %s | %s |" % (g["n_combos"], rep["declared"]["n_combos"]),
               "| 频点数 | %s | %s |" % (g["n_freq"], rep["declared"]["n_freq"]),
               "| 扫描范围 (Hz) | %s–%s | %s–%s |"
               % (g["freq_lo_Hz"], g["freq_hi_Hz"], rep["declared"]["freq_lo_Hz"],
                  rep["declared"]["freq_hi_Hz"]),
               "| 频点步长 (Hz) | %s（均匀=%s） | %s |"
               % (g["freq_step_Hz"], g["freq_step_uniform"], rep["declared"]["freq_step_Hz"]),
               "| x 取值个数 | %s（%s–%s） | %s（%s–%s） |"
               % (g["n_x_values"], g["x_min"], g["x_max"], rep["declared"]["n_x"],
                  rep["declared"]["x_lo"], rep["declared"]["x_hi"]),
               "| 缺声明组合 | %s | — |" % g["n_missing_expected_combos"], ""]
    if rep.get("problems"):
        md += ["## 问题", ""] + ["* %s" % p for p in rep["problems"]] + [""]
    (out_dir / "profile_te29_export.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="te2_9 v1 新导出产物盘点（只读）")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="导出落地目录（或其上层）")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    code, rep = profile(pathlib.Path(a.root))
    out_dir = pathlib.Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "profile_te29_export.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_md(rep, out_dir)
    if not a.quiet:
        print("盘点根目录 : %s" % rep.get("root"))
        print("产物目录   : 命中 %s 个%s" % (rep.get("n_product_dirs"),
                                          "" if not rep.get("chosen_dir") else
                                          " ｜ 采用 %s" % rep["chosen_dir"]))
        if rep.get("error"):
            print("[待产物] %s" % rep["error"])
        if rep.get("files"):
            present = [n for n, v in rep["files"].items() if v["present"]]
            absent = [n for n, v in rep["files"].items() if not v["present"]]
            print("文件       : 在位 %d 个 ｜ 缺 %s" % (len(present), absent or "无"))
            if rep.get("manifest", {}).get("present"):
                print("manifest   : %s 条 ｜ 回读不符 %s 个%s"
                      % (rep["manifest"].get("n_entries"), rep["manifest"].get("n_mismatch"),
                         "" if not rep["manifest"].get("mismatch_files")
                         else "：%s" % rep["manifest"]["mismatch_files"]))
        if rep.get("grid"):
            g = rep["grid"]
            print("网格       : 组合 %s（声明 %s）｜ 频点 %s（声明 %s）｜ 范围 %g–%g 步长 %g 均匀=%s"
                  % (g["n_combos"], rep["declared"]["n_combos"], g["n_freq"],
                     rep["declared"]["n_freq"], g["freq_lo_Hz"], g["freq_hi_Hz"],
                     g["freq_step_Hz"] or float("nan"), g["freq_step_uniform"]))
            print("标志/分母  : 峰值删失 %s ｜ 带宽截断 %s ｜ 可用 %s ｜ Q 可判定 %s ｜ Q 达标 %s"
                  % (g["n_peak_at_scan_endpoint"], g["n_bw_upper_cutoff_at_endpoint"],
                     g["n_usable"], g["n_Q_decidable"], g["n_Q_pass_2p5_3p5"]))
        print("ready      : %s" % rep.get("ready_for_parse"))
        for p in rep.get("problems", []):
            print("  [!] %s" % p)
        print("已写出 %s 与 profile_te29_export.md" % (out_dir / "profile_te29_export.json"))
    return code


if __name__ == "__main__":
    sys.exit(main())
