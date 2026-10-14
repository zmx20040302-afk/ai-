import csv, pathlib, re
R = pathlib.Path("work/runs/remote-exported-20260922")
M = R/"mirror"

def read_table(p):
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    hdr = [c.strip() for c in re.split(r"\s{2,}", lines[4].strip()) if c.strip()]
    rows = []
    for ln in lines[5:]:
        cs = [c.strip() for c in re.split(r"\s{2,}", ln.strip()) if c.strip()]
        if len(cs) >= 4: rows.append(cs)
    return hdr, rows

d = M/"cell_te2_9_test_v1_20260922_154543665_022"
h9, r9 = read_table(d/"Table_9.txt")
h10, r10 = read_table(d/"Table_10.txt")
h11, r11 = read_table(d/"Table_11.txt")
hz, rz = read_table(d/"Zdisplacement.txt")

def row_at(rows, f_mhz):
    for r in rows:
        if abs(float(r[3]) - f_mhz*1e6) < 1:
            return r
    return None

print("=== 数据 A：N29 = (x=0.1, N1=1, N2=9)，20 MHz 各列原值 ===")
for name, h, rr in (("Table_9", h9, r9), ("Table_10", h10, r10), ("Table_11", h11, r11), ("Zdisplacement", hz, rz)):
    r = row_at(rr, 20)
    print("-- %s" % name)
    for i, (c, v) in enumerate(zip(h, r)):
        print("     [%2d] %-52s = %s" % (i, c[:52], v))

print("\n=== 数据 B：(x=0.1, N1=1, N2=9) 20 MHz 原值 ===")
lines = (R/"gui-sweep-20260912T113936Z-bd387a56/source_table.csv").read_text(encoding="utf-8-sig").splitlines()
hb = next(csv.reader([lines[4]]))
for r in csv.DictReader(lines[5:], fieldnames=hb):
    if abs(float(r[hb[0]]) - 0.1) < 1e-9 and abs(float(r["N_w_te1"]) - 1) < 1e-9 and abs(float(r["freq (Hz)"]) - 2e7) < 1:
        for k in hb: print("     %-22s = %s" % (k, r[k]))
