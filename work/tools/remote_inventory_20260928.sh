#!/bin/bash
# 只读清单：用户 2026-09-28 新扫的两个 run（x 加密 + 频段 5-50 MHz）
set -u
D=/home/lab/projAI4US/autodesign/exported_results
A="$D/cell_te2_6_test_scal_0.2-1_0.01_freq5-50_v1_20260928_074201239_001"
B="$D/cell_te2_7_test_scal_0.2-1_0.01_freq5-50_v1_20260928_085936317_001"

echo "=== batch status ==="
cat "$D/status.txt" 2>/dev/null || echo "(no status.txt)"
echo "=== launcher log ==="
cat "$D"/launcher_*.log 2>/dev/null | tail -20 || true

for p in "$A" "$B"; do
  echo
  echo "################ $p"
  if [ -d "$p" ]; then
    echo "-- exists; total size:"; du -sh "$p"
    echo "-- file count:"; find "$p" -type f | wc -l
    echo "-- listing:"; ls -la "$p"
    echo "-- Table_9 header (5 lines) + first data row:"
    head -6 "$p/Table_9.txt" 2>/dev/null
  else
    echo "-- MISSING"
  fi
done

echo
echo "=== 全库目录一览（按名字排序，看还有没有其它新批次）==="
find "$D" -mindepth 1 -maxdepth 1 -type d | sort | while read -r d; do
  printf '%-72s %s files\n' "$(basename "$d")" "$(find "$d" -type f | wc -l)"
done
