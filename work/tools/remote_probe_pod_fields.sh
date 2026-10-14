#!/usr/bin/env bash
# 只读远程探针：清点 te2_8_pod_fields_20MHz_v1（不写远端任何东西）
set -u
D=/home/lab/projAI4US/autodesign/exported_results/te2_8_pod_fields_20MHz_v1
echo "== 目录 =="
ls -la "$D"
echo "== representative_full 内容（前 15）=="
find "$D/representative_full" -type f | head -15
echo "== representative_full 文件数与体积 =="
find "$D/representative_full" -type f | wc -l
du -sh "$D/representative_full"
echo "== pod_20MHz 参数覆盖（从文件名解析）=="
cd "$D/pod_20MHz" || exit 1
ls *.mat > /tmp/_mems_ls.txt 2>/dev/null
echo "n_files=$(wc -l < /tmp/_mems_ls.txt)"
echo "distinct_x=$(ls *.mat | sed -E 's/^x([0-9.]+)_N.*/\1/' | sort -u | wc -l)"
echo "distinct_N=$(ls *.mat | sed -E 's/^x[0-9.]+_N([0-9]+)_.*/\1/' | sort -u | tr '\n' ' ')"
echo "x_min=$(ls *.mat | sed -E 's/^x([0-9.]+)_N.*/\1/' | sort -g | head -1)"
echo "x_max=$(ls *.mat | sed -E 's/^x([0-9.]+)_N.*/\1/' | sort -g | tail -1)"
echo "per_N_counts:"
ls *.mat | sed -E 's/^x[0-9.]+_N([0-9]+)_.*/\1/' | sort | uniq -c
echo "== 单个 .mat 元信息 =="
F=$(ls *.mat | head -1)
echo "file=$F  bytes=$(stat -c %s "$F")"
file "$F" 2>/dev/null || true
echo "== 可用的 .mat 读取工具 =="
for t in python3 h5dump h5ls octave; do printf '%s: ' "$t"; command -v "$t" || echo "(none)"; done
echo "== python3 模块 =="
python3 - <<'PY' 2>&1 | head -20
mods = []
for m in ("h5py", "scipy.io", "numpy"):
    try:
        __import__(m)
        mods.append(m + "=OK")
    except Exception as e:
        mods.append(m + "=MISSING(%s)" % type(e).__name__)
print(" ".join(mods))
try:
    import h5py, glob, os
    f = sorted(glob.glob("*.mat"))[0]
    with h5py.File(f, "r") as h:
        print("HDF5 root keys:", list(h.keys()))
        def walk(g, p="", d=0):
            if d >= 2:
                return
            for k in g.keys():
                o = g[k]
                try:
                    shp = getattr(o, "shape", None)
                except Exception:
                    shp = None
                print("  %s/%s  type=%s shape=%s" % (p, k, type(o).__name__, shp))
                if hasattr(o, "keys") and d < 1:
                    walk(o, p + "/" + k, d + 1)
        walk(h)
except Exception as e:
    print("h5py probe failed:", type(e).__name__, e)
PY
echo "== snapshot_index.tsv 头 5 行 / 行数 =="
head -5 "$D/snapshot_index.tsv"
wc -l "$D/snapshot_index.tsv"
