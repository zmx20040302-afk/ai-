# -*- coding: utf-8 -*-
"""构建**统一数据骨架** `unified_skeleton.csv`（只含身份 + 输入轴，**不含任何输出值**）。

依据：
* 用户裁定（`feedback` `fb-20260923T110333Z-e0a59352`）：同一模型、结构相同、只是改参数扫描；
* 用户裁定（`feedback` `fb-20260923T142102Z-4bd9fd86`）：SHA-256 为最终硬标识，
  哈希取得前 `base_model_id` 保持 NULL + `pending_sha256`，**不得用文件名冒充**；
* `column_merge_matrix.json`：只有 `poolable=true` 的列可进统一表。

**为什么值一律不进**：`column_merge_matrix.json` 实测"输出轴可并列 = 0"
（B 无声压、A 无阻抗、功率量定义不同、两个速度量测点未统一）。
把值拼进来就会制造跨批虚假数据，因此本骨架**只有骨架**。

用法：
    python -B scripts/build_unified_skeleton.py
    python -B scripts/build_unified_skeleton.py --check
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.identity import (IDENTITY_FIELDS, assert_base_model_id,  # noqa: E402
                                 pending_identity, parameter_set_id)

RUN = REPO / "work/runs/remote-exported-20260922"
DATASET = RUN / "dataset"
GUI_DIR = REPO / "work/runs/gui-sweep-20260912T113936Z-bd387a56"
OUT = RUN / "unified_skeleton.csv"
MANIFEST = RUN / "unified_skeleton_manifest.json"

IDENTITY_BASIS = "user_confirmed_same_base_model"
SRC_A_PATH = "ubuntu-10-180-7-46:/home/lab/projAI4US/autodesign/exported_results"
SRC_B_PATH = "C:/Users/zmx/Desktop/换能器/扫面x&N1，间隔阵列扫描.csv"

SKELETON_COLS = ["batch"] + list(IDENTITY_FIELDS) + ["x_scale", "N_w_te1", "N_w_te2", "freq_Hz"]


def sha256_file(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def rows_batch_a() -> list[dict]:
    """数据 A：以 `points.csv` 为准（每个组合 × 每个频点一行）。"""
    out: list[dict] = []
    with (DATASET / "points.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            out.append({**pending_identity(identity_basis=IDENTITY_BASIS,
                                           source_file=r["model"], source_path=SRC_A_PATH,
                                           run_name=r["run"], run_id="run-" + r["run"]),
                        "batch": "A", "x_scale": r["x_scale"], "N_w_te1": r["N_w_te1"],
                        "N_w_te2": r["N_w_te2"], "freq_Hz": r["freq_Hz"]})
    return out


def rows_batch_b() -> list[dict]:
    """数据 B：GUI 扫描表（前 4 行元信息，第 5 行是表头且首格带 `% ` 前缀）。"""
    p = GUI_DIR / "source_table.csv"
    lines = p.read_text(encoding="utf-8-sig").splitlines()
    hdr = next(csv.reader([lines[4]]))
    xkey = hdr[0]                      # `% x_scale`
    out: list[dict] = []
    for r in csv.DictReader(lines[5:], fieldnames=hdr):
        out.append({**pending_identity(identity_basis=IDENTITY_BASIS,
                                       source_file="b_GE_task3_2-newyizu.mph",
                                       source_path=SRC_B_PATH,
                                       run_name="gui-sweep-20260912T113936Z-bd387a56",
                                       run_id="gui-sweep-20260912T113936Z-bd387a56"),
                    "batch": "B", "x_scale": r[xkey], "N_w_te1": r["N_w_te1"],
                    "N_w_te2": "",     # B 的表里没有 N2 列（模型常量 9，待数据侧确认）
                    "freq_Hz": r["freq (Hz)"]})
    return out


# ---------------------------------------------------------------------------
# 批次 C（2026-09-28：x 加密 0.01 + 频段 5–50 MHz）
# ---------------------------------------------------------------------------
C_RUN = REPO / "work/runs/x-densify-20260928"
C_MIRROR = C_RUN / "mirror"
C_MODEL_MANIFEST = C_RUN / "batch_meta" / "model_manifest.tsv"
C_REMOTE_DIR = "ubuntu-10-180-7-46:/home/lab/projAI4US/autodesign"
RE_RUN_SUFFIX = re.compile(r"_(20\d{6}_\d{9}_\d{3})$")


def load_model_manifest() -> dict[str, dict]:
    """远端 `model_manifest.tsv`（`sha256\\tsize\\tmtime\\tpath`）→ {basename: {sha256,size}}。

    这是 SHA-256 裁定第 2/3 条要的东西：**`.mph` 的哈希**（此前一直缺）。
    """
    out: dict[str, dict] = {}
    if not C_MODEL_MANIFEST.is_file():
        return out
    lines = C_MODEL_MANIFEST.read_text(encoding="utf-8", errors="replace").splitlines()
    for ln in lines[1:]:
        parts = ln.split("\t")
        if len(parts) < 4:
            continue
        out[parts[3].strip().split("/")[-1]] = {"sha256": parts[0].strip(),
                                                "size": parts[1].strip()}
    return out


def rows_batch_c() -> list[dict]:
    """数据 C：新批三个 run（1215 组合 × 91 频点）。**行来自 Table_9**，值不进骨架。"""
    man = load_model_manifest()
    if not man:
        raise SystemExit("[FAIL] 缺 %s ⇒ 拿不到 .mph 哈希，拒绝构建（不猜 artifact_sha256）"
                         % C_MODEL_MANIFEST)
    out: list[dict] = []
    seen_stems: set[str] = set()
    for run in sorted(p for p in C_MIRROR.iterdir() if p.is_dir() and p.name.startswith("cell_")):
        stem = RE_RUN_SUFFIX.sub("", run.name)
        mph = stem + ".mph"
        if mph not in man:
            raise SystemExit("[FAIL] run %s 推出的模型名 %s 不在 model_manifest.tsv 里 ⇒ 拒绝"
                             % (run.name, mph))
        seen_stems.add(stem)
        t9 = run / "Table_9.txt"
        if not t9.is_file():
            continue
        for ln in t9.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if not s or s.startswith("%"):
                continue
            f = s.split()
            if len(f) < 15:
                continue
            out.append({**pending_identity(identity_basis=IDENTITY_BASIS,
                                           source_file=mph,
                                           source_path="%s/%s" % (C_REMOTE_DIR, mph),
                                           run_name=run.name, run_id="run-" + run.name),
                        "artifact_sha256": man[mph]["sha256"],   # ← 真哈希（裁定第 3 条）
                        "batch": "C", "x_scale": f[0], "N_w_te1": f[1],
                        "N_w_te2": f[2], "freq_Hz": f[3]})
    if len(seen_stems) != 3:
        raise SystemExit("[FAIL] 预期 3 个 run，实际 %d 个 ⇒ 拒绝" % len(seen_stems))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="构建统一数据骨架（只含身份 + 输入轴）")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    mm = json.loads((RUN / "column_merge_matrix.json").read_text(encoding="utf-8"))
    poolable = {k for k, v in mm["columns"].items() if v["poolable"]}
    # 守卫①：骨架里的**每一个值列**都必须是矩阵里标为可并的
    bad = [c for c in ("x_scale", "N_w_te1", "N_w_te2", "freq_Hz") if c not in poolable]
    if bad:
        print("[FAIL] 骨架值列未在 column_merge_matrix 中标为可并：%s" % bad, file=sys.stderr)
        return 2
    # 守卫②（2026-09-28 改写）：**"输出轴可并"不再一律拒绝**——A↔C 的原始量已有逐列复现证据。
    # 改为两条更强的检查：① 每个"可并"列必须列出 ≥2 个批次；② 输出轴的"可并"列必须有证据。
    for c, v in mm["columns"].items():
        if not v["poolable"]:
            continue
        if len(v.get("poolable_batches") or []) < 2:
            print("[FAIL] 列 %s 标为可并但 poolable_batches 少于 2 个批次 ⇒ 拒绝构建" % c,
                  file=sys.stderr)
            return 2
        if v.get("axis") == "output" and not v.get("evidence"):
            print("[FAIL] 输出列 %s 标为可并但**没有证据**（需 column_repeatability 等实测）⇒ 拒绝"
                  % c, file=sys.stderr)
            return 2
    # 守卫③：身份块里 base_model_id 必须是 NULL（不得用文件名冒充）
    probe = pending_identity(identity_basis=IDENTITY_BASIS, source_file="x.mph")
    try:
        assert_base_model_id(probe["base_model_id"])
    except Exception as exc:                                   # pragma: no cover
        print("[FAIL] 身份块不合法：%s" % exc, file=sys.stderr)
        return 2

    rows = rows_batch_a() + rows_batch_b() + rows_batch_c()
    if not rows:
        print("[FAIL] 没有可写入的骨架行", file=sys.stderr)
        return 2
    # 守卫④：禁止在骨架里携带任何输出值列
    for r in rows:
        extra = set(r) - set(SKELETON_COLS)
        if extra:
            print("[FAIL] 骨架行出现未声明的列（疑似带值）：%s" % sorted(extra), file=sys.stderr)
            return 2

    # 逐行补 parameter_set_id（可算的指纹）
    n_ps = 0
    for r in rows:
        if r["N_w_te2"] in ("", None):
            r["parameter_set_id"] = None            # 缺 N2 ⇒ 不给指纹（不猜）
            continue
        r["parameter_set_id"] = parameter_set_id({"x_scale": float(r["x_scale"]),
                                                  "N_w_te1": float(r["N_w_te1"]),
                                                  "N_w_te2": float(r["N_w_te2"])})
        n_ps += 1

    if args.check:
        print("骨架可构建：%d 行（可算 parameter_set_id 的 %d 行）" % (len(rows), n_ps))
        return 0

    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.DictWriter(fh, fieldnames=SKELETON_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in SKELETON_COLS})

    by_batch: dict[str, int] = {}
    for r in rows:
        by_batch[r["batch"]] = by_batch.get(r["batch"], 0) + 1
    man = {
        "kind": "unified_skeleton_manifest", "created_utc": "2026-09-28",
        "n_rows": len(rows), "by_batch": by_batch,
        "columns": SKELETON_COLS,
        "values_included": False,
        "why_no_values": ("骨架按设计只含**身份 + 输入轴**。可并的**输出**列已由 "
                          "column_merge_matrix.json 逐列授权（A↔C 共 22 列，各有 "
                          "column_repeatability 实测证据），但那些值留在**各批自己的表**里，"
                          "不复制进骨架——骨架不是数据表，混进值会带来跨批虚假数据的风险。"),
        "artifact_sha256_filled_batches": ["C"],
        "artifact_sha256_source": ("远端 model_manifest.tsv（2026-09-28 批次）"
                                   "work/runs/x-densify-20260928/batch_meta/model_manifest.tsv"),
        "identity": {"base_model_id": None, "base_model_id_status": "pending_sha256",
                     "configuration_id": None,
                     "measurement_profile_id": None,
                     "identity_basis": IDENTITY_BASIS,
                     "parameter_set_id_computed_rows": n_ps,
                     "parameter_set_id_skipped_rows": len(rows) - n_ps,
                     "parameter_set_id_skipped_reason": "数据 B 表内无 N_w_te2 列（模型常量，待数据侧确认）"},
        "rulings": ["fb-20260923T110333Z-e0a59352", "fb-20260923T142102Z-4bd9fd86"],
        "files": {"unified_skeleton.csv": sha256_file(OUT),
                  "column_merge_matrix.json": sha256_file(RUN / "column_merge_matrix.json")},
    }
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote %s (%d 行, %d B)" % (OUT.relative_to(REPO), len(rows), OUT.stat().st_size))
    print("  按批次：%s" % by_batch)
    print("  parameter_set_id：可算 %d 行 / 跳过 %d 行（B 缺 N2）" % (n_ps, len(rows) - n_ps))
    n_sha = sum(1 for r in rows if r.get("artifact_sha256"))
    print("  artifact_sha256 已填 %d 行（批次 C）；base_model_id = NULL（pending_sha256）" % n_sha)
    print("  输出值 **0 列**（可并的输出列留在各批自己的表里）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
