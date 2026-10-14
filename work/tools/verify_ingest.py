"""入库后核对：把库里样本与源 CSV 对应行逐位比对（确认无解析/单位损失）。"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(r"C:\Users\zmx\Desktop\memsharness\scripts")))
from ingest_gui_sweep import parse_complex  # noqa: E402

RUN = "gui-sweep-20260912T113936Z-bd387a56"
CSV = Path(r"C:\Users\zmx\Desktop\换能器\扫面x&N1，间隔阵列扫描.csv")
RUNDIR = Path(r"C:\Users\zmx\Desktop\memsharness\work\runs") / RUN

con = duckdb.connect(str(Path(r"C:\Users\zmx\Desktop\memsharness\work\store\mems.duckdb")), read_only=True)

print("== run 行 ==")
for r in con.execute(
    "select run_id, pathway, status, model_path, round(wall_seconds,1) from run where run_id = ?", [RUN]
).fetchall():
    print("  ", r)

print("\n== run.settings 关键字段 ==")
settings = json.loads(con.execute("select settings from run where run_id = ?", [RUN]).fetchone()[0])
for k in ("pathway_detail", "csv_sha256", "m_file_sha256", "model_mph_sha256", "n_combos", "n_rows",
          "frequencies_MHz", "geometry_family", "fidelity"):
    print(f"   {k}: {settings.get(k)}")

print("\n== 基线组合 (x_scale=0.6, N_w_te1=4) 的库内样本 ==")
rows = con.execute(
    "select sample_id, inputs, outputs from sample where run_id = ? and design_id like ?"
    " order by cast(json_extract(inputs, '$.freq_Hz') as double)",
    [RUN, f"design-{RUN}-x0.6-n4"],
).fetchall()
for sid, inputs, outputs in rows:
    i, o = json.loads(inputs), json.loads(outputs)
    print(f"   {sid}  f={i['freq_Hz']/1e6:.0f} MHz  Ptot={o['Ptot_W']:.6g} W  "
          f"|Zin1|={abs(complex(o['Zin1_R_ohm'], o['Zin1_X_ohm'])):.6g} Ω  "
          f"|Vave|={o['Vave_m_s']:.6g} m/s  ∠Vave={o['Vave_phase_rad']:.4f} rad")

print("\n== 与源 CSV 逐位比对（同组合、同频点）==")
text = CSV.read_text(encoding="utf-8-sig", errors="replace")
grid = [r for r in csv.reader(io.StringIO(text)) if r]
hi = next(i for i, r in enumerate(grid) if r and r[0].strip().lstrip("% ").strip() == "x_scale")
header = [c.strip() for c in grid[hi]]
header[0] = header[0].lstrip("%").strip()
csv_rows = {
    (float(r[header.index("x_scale")]), float(r[header.index("N_w_te1")]), float(r[header.index("freq (Hz)")])): r
    for r in grid[hi + 1:] if len(r) >= len(header) and r[0].strip()
}
mismatch = 0
checked = 0
for sid, inputs, outputs in rows:
    i, o = json.loads(inputs), json.loads(outputs)
    src = csv_rows[(i["x_scale"], i["N_w_te1"], i["freq_Hz"])]
    pairs = [
        ("Ptot (W)", o["Ptot_W"]),
        ("Zin1_R (Ω)", o["Zin1_R_ohm"]),
        ("Zin1_X (Ω)", o["Zin1_X_ohm"]),
    ]
    for col, db_value in pairs:
        checked += 1
        if float(src[header.index(col)]) != db_value:
            mismatch += 1
            print(f"   ✗ {sid} {col}: csv={src[header.index(col)]} db={db_value}")
    vc = parse_complex(src[header.index("V_center (m/s)")])
    if vc is not None and abs(abs(vc) - o["V_center_m_s"]) > 0:
        mismatch += 1
        print(f"   ✗ {sid} V_center 幅值不一致")
print(f"   比对 {checked} 个标量 + 复数量：不一致 {mismatch} 个")

print("\n== 全库样本构成 ==")
for r in con.execute(
    "select fidelity, source_type, count(*) from sample group by 1,2 order by 1,2"
).fetchall():
    print("  ", r)
print("  design 表:", con.execute("select count(*) from design").fetchone()[0], "行")
print("  run 表:", con.execute("select count(*) from run").fetchone()[0], "行")

print("\n== run 目录（证据副本）==")
for p in sorted(RUNDIR.iterdir()):
    print(f"   {p.name:20s} {p.stat().st_size/1024:.1f} KB")
