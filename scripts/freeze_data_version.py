# -*- coding: utf-8 -*-
"""冻结**不可变数据版本**（裁定 §6）：`C_v20260928`，后续新 run 追加为 `C_v20260929` …

每版本绑定（裁定 §6 要求）：数据清单 SHA-256、模型列表、组合集合、频率网格、
异常隔离表、切分定义、随机种子、预注册版本。

为什么要它：原规则是"新 run 到达 ⇒ 旧结果整体作废"，**过严**（每来一个 run 就把工作推倒）。
改成不可变版本后：**旧结论对旧快照继续成立**（不称"作废"），新 run 先作为**锁定的外部增量测试**，
只有要加入训练才开新预注册与新模型版本。

**追加而不是重建**（2026-09-29 新增）：`--mirror` 给原批次镜像，`--extra-mirror` 追加新 run 的镜像，
`--parent-manifest` 指上一版清单 ⇒ 新版记录 `based_on`（父版本 label + sha256）与**组合/run 增量**，
**父版本文件一字不改**。每个 run 的来源镜像记进 `run_provenance`（同一 run 名出现两次即拒绝冻结）。

用法：
    python -B scripts/freeze_data_version.py \
        --label C_v20260928 --mirror work/runs/x-densify-20260928/mirror \
        --model-manifest work/runs/x-densify-20260928/batch_meta/model_manifest.tsv \
        --out-dir work/runs/x-densify-20260928/data_versions

    # 追加 N2=8（te2_8）：
    python -B scripts/freeze_data_version.py \
        --label C_v20260929 --mirror work/runs/x-densify-20260928/mirror \
        --extra-mirror work/runs/n2-8-intake-20260929/raw \
        --parent-manifest work/runs/x-densify-20260928/data_versions/C_v20260928.json \
        --model-manifest work/runs/n2-8-intake-20260929/batch_meta/model_manifest.tsv \
        --extra-model-manifest work/runs/x-densify-20260928/batch_meta/model_manifest.tsv
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 与该版本绑定的异常隔离表（裁定 §5.1：状态 `quarantined_pending_rerun`，只隔离不删除）
QUARANTINE = [{
    "combo": {"x_scale": 0.2, "N_w_te1": 1, "N_w_te2": 7},
    "status": "quarantined_pending_rerun",
    "why": ("批间唯一实质不一致：5 MHz 处 A=102.180 / C=95.671 dB（差 6.51 dB）；"
            "同层邻点全部复现到 1e-11 dB"),
    "localized_to": "批 C 的低频点（5–12 MHz）；用 C 自身邻居趋势外推得 103.251 dB，C 低 7.58 dB 而 A 只低 1.07 dB",
    "rule": "批间 |ΔSPL|>max(0.5dB, 10×正常重合点p99) 且 连续≥3个共享频点超阈 且 批内 |z_MAD|>8（三项同时满足）",
    "pending": "从 .mph 核对解索引/参数/复声压实虚；只重跑该组合 5–12 MHz；不改写镜像",
    "reporting": "主统计暂不纳入，但**必须同时给含该点与不含该点的敏感性版本**",
}]

#: 切分定义（第 4/5 轮用到的；写进版本以便复现）
SPLITS = {
    "S-D(h)": "每层 (N2,N1) 内训练 x={0.2+k·h}，测试其余且必须被两个训练点夹住（不外推）",
    "R-CB": ("跨批重复性/口径一致性检查：A 的 x 与 C 的同参数组合逐一配对"
             "（**不是泛化测试**，裁定 §3.1 改名）"),
    "R-CB-offgrid": ("真正的跨批泛化折（需预注册）：训练 A 粗网格 → 测试 C 中**不与 A 坐标重复**的"
                     "x 加密点，仅保留同层已知 x 范围内的**内部插值点**；外推点单独建折；"
                     "异常组合标 quarantined，并给含/不含的敏感性结果"),
    "S-N1ex": "训练 N1<max → 测试 N1=max（N1 外推，单列参考，不进主判据）",
}

RANDOM_SEED = 0


def sha256_file(p: pathlib.Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def read_models(manifest: pathlib.Path, out: list, seen: set) -> None:
    """读 `sha256<TAB>size<TAB>mtime<TAB>path` 清单；同名（basename）不重复登记。"""
    if not manifest or not manifest.is_file():
        return
    for ln in manifest.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        c = ln.split("\t")
        if len(c) < 4:
            continue
        name = c[3].strip().split("/")[-1]
        if name in seen:
            continue
        seen.add(name)
        out.append({"mph": name, "artifact_sha256": c[0].strip(),
                    "size_bytes": int(c[1]) if c[1].strip().isdigit() else None,
                    "measured_mtime": c[2].strip() if len(c) > 2 else None,
                    "manifest": str(manifest).replace("\\", "/")})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="冻结不可变数据版本")
    ap.add_argument("--label", required=True)
    ap.add_argument("--mirror", type=pathlib.Path, required=True)
    ap.add_argument("--extra-mirror", action="append", default=[],
                    help="追加镜像目录（可重复）；用于把新 run 追加进同一版本")
    ap.add_argument("--model-manifest", type=pathlib.Path, default=None)
    ap.add_argument("--extra-model-manifest", action="append", default=[],
                    help="追加模型清单（可重复）")
    ap.add_argument("--parent-manifest", type=pathlib.Path, default=None,
                    help="上一版版本清单：记录 based_on 与增量（**不改动父版本**）")
    ap.add_argument("--out-dir", type=pathlib.Path,
                    default=REPO / "work/runs/x-densify-20260928/data_versions")
    ap.add_argument("--prereg", default=None, help="绑定到本版本的预注册文件名")
    ap.add_argument("--extra-file", action="append", default=[],
                    help="额外绑定文件（可重复）；其 sha256 会进 manifest")
    args = ap.parse_args(argv)

    # 相对路径先解析成绝对路径，否则 `out.relative_to(REPO)` 会抛 ValueError（实测踩到）
    args.out_dir = args.out_dir.resolve()
    args.mirror = args.mirror.resolve()
    args.extra_mirror = [pathlib.Path(m).resolve() for m in args.extra_mirror]
    mirrors = [args.mirror] + [pathlib.Path(m) for m in args.extra_mirror]
    for m in mirrors:
        if not m.is_dir():
            print("[FAIL] 镜像目录不存在：%s" % m, file=sys.stderr)
            return 2

    runs, files = [], {}
    freq_grids: set[tuple] = set()
    combos: dict[tuple, list[float]] = {}
    combo_owner: dict[tuple, str] = {}
    provenance: dict[str, str] = {}
    for m in mirrors:
        for run in sorted(p for p in m.iterdir() if p.is_dir() and p.name.startswith("cell_")):
            t9 = run / "Table_9.txt"
            if not t9.is_file():
                continue
            if run.name in provenance:
                print("[FAIL] run 同名重复：%s（%s 与 %s）⇒ 拒绝冻结"
                      % (run.name, provenance[run.name], m), file=sys.stderr)
                return 2
            provenance[run.name] = str(m).replace("\\", "/")
            runs.append(run.name)
            for ln in t9.read_text(encoding="utf-8", errors="replace").splitlines():
                s = ln.strip()
                if not s or s.startswith("%"):
                    continue
                f = s.split()
                if len(f) < 15:
                    continue
                k = (round(float(f[0]), 6), round(float(f[1]), 6), round(float(f[2]), 6))
                # ⚠️ 必须**显式**报"组合重复"：否则同一组合出现在两个 run 里时，
                # 频点列表会出现重复值，最终只会报出误导性的「频点非严格升序」（实测踩坑）。
                prev = combo_owner.get(k)
                if prev is not None and prev != run.name:
                    print("[FAIL] 组合 %s 同时出现在 run %s 与 run %s ⇒ 归属不明，拒绝冻结"
                          % (k, prev, run.name), file=sys.stderr)
                    return 2
                combo_owner[k] = run.name
                combos.setdefault(k, []).append(float(f[3]))
            for p in sorted(run.glob("*")):
                if p.is_file():
                    files[str(p.relative_to(m)).replace("\\", "/")] = sha256_file(p)

    # ⚠️ 网格签名必须**逐组合**算：早先把全文件的频率值收成一个列表，
    # 于是 n = 组合数 × 每组合频点数（29484/36855/44226），守卫直接拒绝冻结。
    for k, fs in combos.items():
        fs.sort()
        freq_grids.add((len(fs), round(fs[0], 3), round(fs[-1], 3),
                        round((fs[-1] - fs[0]) / (len(fs) - 1), 3) if len(fs) > 1 else None))

    if len(freq_grids) != 1:
        print("[FAIL] 频率网格不唯一：%s ⇒ 拒绝冻结" % sorted(freq_grids), file=sys.stderr)
        return 2
    n_f, f_lo, f_hi, f_step = freq_grids.pop()
    combo_list = sorted(combos)
    # 升序也要检查
    bad_order = [k for k, fs in combos.items() if any(b <= a for a, b in zip(fs, fs[1:]))]
    if bad_order:
        print("[FAIL] %d 个组合的频点非严格升序（如 %s）⇒ 拒绝冻结"
              % (len(bad_order), bad_order[:3]), file=sys.stderr)
        return 2

    models: list = []
    seen_models: set = set()
    read_models(args.model_manifest, models, seen_models)
    for mm in args.extra_model_manifest:
        read_models(pathlib.Path(mm), models, seen_models)

    # ---- 与父版本的增量（父版本文件**只读**，绝不改写）----
    parent = None
    delta = None
    if args.parent_manifest and args.parent_manifest.is_file():
        pj = json.loads(args.parent_manifest.read_text(encoding="utf-8"))
        parent = {"label": pj.get("label"),
                  "sha256": sha256_file(args.parent_manifest),
                  "path": str(args.parent_manifest).replace("\\", "/"),
                  "n_runs": pj.get("n_runs"),
                  "n_combos": (pj.get("combos") or {}).get("n")}
        prev_runs = set(pj.get("runs") or [])
        delta = {
            "added_runs": sorted(set(runs) - prev_runs),
            "n_added_combos": len(combo_list) - int(parent["n_combos"] or 0),
            "combos_sha256_changed": sha256_text(json.dumps(combo_list, separators=(",", ":")))
            != (pj.get("combos") or {}).get("sha256"),
        }
        if args.label == parent["label"]:
            print("[FAIL] --label 与父版本同名（%s）⇒ 会覆盖历史版本，拒绝" % args.label,
                  file=sys.stderr)
            return 2

    # 不可变版本**永不覆盖**：目标文件已存在即拒绝（不论是否给了父版本）
    _target = args.out_dir / ("%s.json" % args.label)
    if _target.exists():
        print("[FAIL] 目标版本已存在：%s ⇒ 不可变版本禁止覆盖（换 label 或先人工确认）"
              % _target, file=sys.stderr)
        return 2

    man = {
        "kind": "immutable_data_version",
        "label": args.label,
        "frozen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "protocol": "metric_protocol_v2",
        "mirrors": [str(m).replace("\\", "/") for m in mirrors],
        "mirror": str(args.mirror).replace("\\", "/"),
        "run_provenance": provenance,
        "based_on": parent,
        "delta_vs_parent": delta,
        "runs": runs,
        "n_runs": len(runs),
        "models": models,
        "combos": {"n": len(combo_list),
                   "sha256": sha256_text(json.dumps(combo_list, separators=(",", ":"))),
                   "first": combo_list[0], "last": combo_list[-1]},
        "freq_grid": {"n_points": n_f, "scan_fmin_Hz": f_lo, "scan_fmax_Hz": f_hi,
                      "step_Hz": f_step,
                      "note": "扫描范围是**数据版本的一部分**（裁定 §4.2）；范围依赖量不可跨批比较"},
        "files": {"n": len(files), "sha256": sha256_text(json.dumps(files, sort_keys=True)),
                  "per_file": files},
        "quarantine": QUARANTINE,
        "splits": SPLITS,
        "random_seed": RANDOM_SEED,
        "prereg": args.prereg,
        "extra_files": {p: sha256_file(pathlib.Path(p)) for p in args.extra_file},
        "version_rules": [
            "旧结论继续对旧快照成立，**不称作废**",
            "新 run 先作为**锁定的外部增量测试**，不得先看结果再调模型",
            "仅评估 ⇒ 不需重训、不必重跑历史折",
            "把新 run 加入训练 ⇒ 必须新预注册 + 新模型版本",
            "跨版本只比较**完全相同的冻结测试集**；不得直接比较各版本各自的 max",
        ],
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / ("%s.json" % args.label)
    out.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        shown = out.relative_to(REPO)
    except ValueError:
        shown = out
    print("wrote %s (%d B)" % (shown, out.stat().st_size))
    print("  runs=%d  combos=%d  grid=%d 点 / %.1f–%.1f MHz"
          % (len(runs), len(combo_list), n_f, f_lo / 1e6, f_hi / 1e6))
    print("  models=%d（含 artifact_sha256）  files=%d" % (len(models), len(files)))
    print("  combos sha256=%s  files sha256=%s"
          % (man["combos"]["sha256"][:16], man["files"]["sha256"][:16]))
    if delta:
        print("  based_on %s (%s)  新增 run=%d  组合 %d→%d（%+d）"
              % (parent["label"], (parent["sha256"] or "")[:16], len(delta["added_runs"]),
                 parent["n_combos"], len(combo_list), delta["n_added_combos"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
