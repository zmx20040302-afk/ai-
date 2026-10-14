import csv, pathlib
W = pathlib.Path("work/runs")
p = W/"gui-sweep-20260912T113936Z-bd387a56/source_table.csv"
lines = p.read_text(encoding="utf-8-sig").splitlines()
hb = next(csv.reader([lines[4]]))
print("=== 数据 B：(x=0.1, N1=1) N2=9? 全 7 个频点 ===")
for r in csv.DictReader(lines[5:], fieldnames=hb):
    if abs(float(r[hb[0]]) - 0.1) < 1e-9 and abs(float(r["N_w_te1"]) - 1) < 1e-9:
        print("  f=%5.1f MHz | Ptot=%-24s Vave=%-24s V_center=%-42s Zin1=(%s, %s)"
              % (float(r["freq (Hz)"])/1e6, r["Ptot (W)"], r["Vave (m/s)"],
                 r["V_center (m/s)"], r["Zin1_R (Ω)"], r["Zin1_X (Ω)"]))
