"""把**用户在 COMSOL GUI 里跑的批处理扫描结果**入库（source_type=simulation、fidelity=F3）。

为什么单独写：
    这批数据不是平台队列跑出来的，而是 GUI 批处理（`model.batch('p1')`）导出的一张全局计算表。
    红线要求每个数值可追溯到 `run_id`，所以本脚本**新增一条 run 行**（pathway='comsol-gui-batch'），
    以导出表 / Model M-file 的 SHA256 作为证据锚，并把这批文件复制进 `work/runs/<run_id>/`
    使该运行自包含、可复核；**绝不冒充成平台队列的结果**。

契约遵循（`.dsh/skills/dataset-contract`）：
    - inputs/outputs 同时非空；单位进键名（SI 值 + 原始单位记录）；
    - `source_type='simulation'` 必须带 `run_id`，且对应 run 状态必须是 `succeeded`；
    - `fidelity=F3`（全 3D 多物理耦合；F2 是 2D 轴对称/简化 3D）；
    - `uncertainty` 按输出分量记录，无法量化写 null 并注明原因（**不得用 0 表示不确定**）；
    - `extractor` 含名称+版本；`quality` 记录校验标记；
    - 频率与角频率不混列；复数量拆成幅值+相位（并注明变换）。

用法：
    python scripts\\ingest_gui_sweep.py --csv "C:\\...\\扫面x&N1，间隔阵列扫描.csv" ^
        --xlsx "C:\\...\\扫描x&N1，间隔扫描.xlsx" ^
        --m-file "C:\\...\\b_GE_task3_2newyizu.m" ^
        --model-mph "C:\\...\\b_GE_task3_2newyizu.mph" --family GF-pmut-ge-task3-oval --dry-run
"""

from __future__ import annotations

import argparse
import cmath
import csv
import io
import json
import re
import shutil
import sys
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from memsharness.onboard import sha256_of  # noqa: E402  （store 里没有这个工具函数）
from memsharness.paths import work_root  # noqa: E402
from memsharness.store import connect, insert_run, insert_sample, now_utc  # noqa: E402

EXTRACTOR = "comsol-gui-batch-csv@v1+memsharness.ingest_gui_sweep@0.1.0"


def parse_complex(text: str) -> complex | None:
    """解析 COMSOL 导出的复数字符串，如 ``4.064e-9-3.543e-4i``。"""
    body = text.strip().replace(" ", "")
    if not body:
        return None
    if not body.endswith("i"):
        try:
            return complex(float(body), 0.0)
        except ValueError:
            return None
    head = body[:-1]
    split = None
    for m in re.finditer(r"[+-]", head):
        if m.start() == 0:
            continue
        if head[m.start() - 1] in "eE":
            continue
        split = m.start()
    if split is None:
        try:
            return complex(0.0, float(head))
        except ValueError:
            return None
    try:
        return complex(float(head[:split]), float(head[split:]))
    except ValueError:
        return None


def read_table(path: Path) -> tuple[list[str], list[dict], list[str]]:
    """读 COMSOL 全局计算表：跳过 `%` 元信息，返回 (表头, 数据行, 元信息)。"""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    grid = [r for r in csv.reader(io.StringIO(text)) if r]
    header_idx = next(i for i, r in enumerate(grid) if r and r[0].strip().lstrip("% ").strip() == "x_scale")
    meta = [" , ".join(r) for r in grid[:header_idx]]
    header = [c.strip() for c in grid[header_idx]]
    header[0] = header[0].lstrip("%").strip()
    rows = [dict(zip(header, r)) for r in grid[header_idx + 1:] if len(r) >= len(header) and r[0].strip()]
    return header, rows, meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GUI 批处理扫描结果入库")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--xlsx", default=None)
    ap.add_argument("--m-file", default=None)
    ap.add_argument("--model-mph", default=None, help="被扫描的 .mph（只记录路径；GUI 打开时不取哈希）")
    ap.add_argument("--family", default="GF-pmut-ge-task3-oval", help="design.geometry_family（防泄漏切分键）")
    ap.add_argument("--fidelity", default="F3", choices=["F0", "F1", "F2", "F3"])
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="同一份导出表已入库时也再入一次")
    args = ap.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print(f"[错误] 找不到导出表：{csv_path}", file=sys.stderr)
        return 2

    header, rows, meta = read_table(csv_path)
    required = {"x_scale", "N_w_te1", "freq (Hz)"}
    if not required <= set(header):
        print(f"[错误] 表头缺少必需列 {required - set(header)}；实际表头={header}", file=sys.stderr)
        return 2

    csv_sha = sha256_of(csv_path)
    xlsx_sha = sha256_of(Path(args.xlsx)) if args.xlsx and Path(args.xlsx).is_file() else None
    m_sha = sha256_of(Path(args.m_file)) if args.m_file and Path(args.m_file).is_file() else None

    run_id = args.run_id or f"gui-sweep-{now_utc().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = work_root() / "runs" / run_id

    combos: dict[tuple[float, float], list[dict]] = {}
    for r in rows:
        combos.setdefault((float(r["x_scale"]), float(r["N_w_te1"])), []).append(r)
    freqs = sorted({float(r["freq (Hz)"]) for r in rows})

    # 每个组合的峰值是否顶在频率上边界（供下游标注"谐振未被频段包住"）
    peak_at_edge: dict[tuple[float, float], bool] = {}
    for key, group in combos.items():
        top = max(float(r["Ptot (W)"]) for r in group)
        f_top = float(max(group, key=lambda r: float(r["Ptot (W)"]))["freq (Hz)"])
        peak_at_edge[key] = f_top == max(freqs)

    print(f"导出表：{csv_path.name}（sha256 {csv_sha[:16]}…）")
    print(f"  元信息：{meta}")
    print(f"  列：{header}")
    print(f"  行数 {len(rows)}；组合 {len(combos)} 个；频率 {len(freqs)} 个：{[f/1e6 for f in freqs]} MHz")
    print(f"  峰值顶在上边界的组合：{sum(1 for v in peak_at_edge.values() if v)}/{len(peak_at_edge)}")
    print(f"  拟登记 run_id={run_id}  pathway=comsol-gui-batch  fidelity={args.fidelity}  family={args.family}")

    if args.dry_run:
        print("\n[dry-run] 不写库、不建 run 目录。")
        return 0

    with connect() as conn:
        existing = conn.execute(
            "select run_id from run where settings like ?", [f"%{csv_sha}%"]
        ).fetchall()
        if existing and not args.force:
            print(f"[拒绝] 同一份导出表（sha256 {csv_sha[:16]}…）已入库为 run {existing[0][0]}；要重复入库请加 --force",
                  file=sys.stderr)
            return 3

        # ---- run 行（先登记，sample 要引用它） ----
        run_dir.mkdir(parents=True, exist_ok=True)
        copied = {}
        for label, src in (("source_table.csv", csv_path),
                           ("model_export.m", Path(args.m_file) if args.m_file else None),
                           ("source_table.xlsx", Path(args.xlsx) if args.xlsx else None)):
            if src and Path(src).is_file():
                dst = run_dir / label
                shutil.copy2(src, dst)
                copied[label] = {"from": str(src), "sha256": sha256_of(dst), "bytes": dst.stat().st_size}
        (run_dir / "provenance.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "pathway": "comsol-gui-batch",
                    "note": "用户在 COMSOL GUI 里用 model.batch('p1') 跑的参数化扫描，导出全局计算表后入库；"
                            "不是平台队列执行的结果。",
                    "csv": {"path": str(csv_path), "sha256": csv_sha},
                    "xlsx": {"path": args.xlsx, "sha256": xlsx_sha},
                    "m_file": {"path": args.m_file, "sha256": m_sha},
                    "model_mph": {"path": args.model_mph, "sha256": None,
                                  "note": "入库时该 .mph 被 GUI 打开（.lock 存在），未取哈希以免记录到未保存状态"},
                    "copied": copied,
                    "meta": meta,
                    "header": header,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        settings = {
            "pathway_detail": "COMSOL GUI Batch (model.batch('p1'))",
            "csv_sha256": csv_sha,
            "xlsx_sha256": xlsx_sha,
            "m_file_sha256": m_sha,
            "model_mph_path": args.model_mph,
            "model_mph_sha256": None,
            "model_mph_sha256_note": "GUI 打开中，未取哈希",
            "batch_node": {"pname": ["x_scale", "N_w_te1"],
                           "plistarr": ["range(0.1,0.1,1)", "range(1,1,8)"],
                           "sweeptype": "filled"},
            "n_combos": len(combos),
            "n_rows": len(rows),
            "frequencies_MHz": [f / 1e6 for f in freqs],
            "geometry_family": args.family,
            "fidelity": args.fidelity,
            "comsol_version": next((m.split(",")[-1].strip() for m in meta if "Version" in m), None),
        }
        insert_run(
            conn,
            run_id=run_id,
            backend="local",
            pathway="comsol-gui-batch",
            model_path=args.model_mph,
            model_sha256=None,
            software={"comsol": settings["comsol_version"] or "6.4.0.293", "extractor": EXTRACTOR},
            settings=settings,
            status="succeeded",
            exit_code=0,
            wall_seconds=None,
            run_dir=str(run_dir),
            started_at=None,
            finished_at=None,
        )
        print(f"已登记 run：{run_id}（run 目录 {run_dir}）")

        # ---- design 行（每个参数组合一条） ----
        design_ids: dict[tuple[float, float], str] = {}
        for key in sorted(combos):
            design_id = f"design-{run_id}-x{key[0]:g}-n{key[1]:g}"
            design_ids[key] = design_id
            conn.execute(
                "insert into design (design_id, params, units, geometry_family, source_type, created_at)"
                " values (?, ?, ?, ?, ?, ?)",
                [
                    design_id,
                    json.dumps({"x_scale": key[0], "N_w_te1": key[1]}),
                    json.dumps({"x_scale": "1", "N_w_te1": "1"}),
                    args.family,
                    "simulation",
                    now_utc(),
                ],
            )
        print(f"已写入 design：{len(design_ids)} 条（geometry_family={args.family}）")

        # ---- sample 行（每条导出表记录一条） ----
        uncertainty = {
            "_note": "本批为线性频域扫描，未做网格收敛（L1），数值离散误差未量化；"
                     "参数效验实测该模型求解器为确定性（同参数复算逐位一致，噪声地板 0），"
                     "故未把数值噪声计入不确定度。",
            "components": {
                "numerical_discretization": None,
                "mesh_dependency": None,
                "model_form": None,
                "parameter": None,
                "measurement": None,
            },
        }
        n_samples = 0
        for index, r in enumerate(rows, 1):
            key = (float(r["x_scale"]), float(r["N_w_te1"]))
            vave = parse_complex(r["Vave (m/s)"])
            vcent = parse_complex(r["V_center (m/s)"])
            outputs = {
                "Ptot_W": float(r["Ptot (W)"]),
                "Zin1_R_ohm": float(r["Zin1_R (Ω)"]),
                "Zin1_X_ohm": float(r["Zin1_X (Ω)"]),
                # Zin2 与 Zin1 逐位相同（模型里 Zin2 = v0/I01，疑似应为 I02）；仍如实入库并打标记
                "Zin2_R_ohm": float(r["Zin2_R (Ω)"]),
                "Zin2_X_ohm": float(r["Zin2_X (Ω)"]),
            }
            if vave is not None:
                outputs["Vave_m_s"] = abs(vave)
                outputs["Vave_phase_rad"] = cmath.phase(vave)
            else:
                outputs["Vave_m_s"] = None
                outputs["Vave_phase_rad"] = None
            if vcent is not None:
                outputs["V_center_m_s"] = abs(vcent)
                outputs["V_center_phase_rad"] = cmath.phase(vcent)
            else:
                outputs["V_center_m_s"] = None
                outputs["V_center_phase_rad"] = None

            flags = ["zin2_equals_zin1_known_defect", "frequency_grid_5MHz_coarse", "no_mesh_convergence_L1"]
            if peak_at_edge.get(key):
                flags.append("combo_peak_at_upper_frequency_boundary")
            quality = {
                "source_table": "COMSOL global evaluation table",
                "csv_row_index": index,
                "flags": flags,
                "units_note": "输出键名含单位；复数量拆为幅值+相位（相位来自 COMSOL 复数字符串）",
            }
            insert_sample(
                conn,
                sample_id=f"smpl-{run_id}-{index:04d}",
                run_id=run_id,
                design_id=design_ids[key],
                fidelity=args.fidelity,
                source_type="simulation",
                inputs={
                    "x_scale": key[0],
                    "N_w_te1": key[1],
                    "freq_Hz": float(r["freq (Hz)"]),
                },
                outputs=outputs,
                uncertainty=uncertainty,
                extractor=EXTRACTOR,
                quality=quality,
            )
            n_samples += 1
        print(f"已写入 sample：{n_samples} 条（fidelity={args.fidelity}）")

        # ---- 核对 ----
        checks = {
            "run_rows": conn.execute("select count(*) from run where run_id = ?", [run_id]).fetchone()[0],
            "design_rows": conn.execute(
                "select count(*) from design where design_id like ?", [f"design-{run_id}-%"]
            ).fetchone()[0],
            "sample_rows": conn.execute("select count(*) from sample where run_id = ?", [run_id]).fetchone()[0],
            "sample_total": conn.execute("select count(*) from sample").fetchone()[0],
            "sample_by_fidelity": conn.execute("select fidelity, count(*) from sample group by 1 order by 1").fetchall(),
            "sample_by_source": conn.execute(
                "select source_type, count(*) from sample group by 1 order by 1"
            ).fetchall(),
        }
    print("\n== 入库核对 ==")
    for k, v in checks.items():
        print(f"  {k}: {v}")
    print(f"\n运行目录：{run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
