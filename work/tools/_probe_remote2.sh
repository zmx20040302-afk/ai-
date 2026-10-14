set -u
echo "--- comsol64 wrapper"
ls -l /usr/local/bin/comsol64 2>/dev/null
/usr/local/bin/comsol64 --version 2>&1 | head -3
echo "--- prepare N4 staging (ASCII path only)"
D=/home/lab/zhangmx/n4_multifreq_20261010
mkdir -p "$D" && echo "staging=$D ok"
df -h "$D" | tail -1
echo "--- local N3 leftovers (should be none)"
pgrep -a -f comsolbatch | head -3 || true
echo "--- existing N4 files"
ls -l "$D" | head -5
