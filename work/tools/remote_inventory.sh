#!/bin/bash
# 只读清单：远端结果目录（ASCII 输出，避免控制台编码问题）
set -u
D=/home/lab/projAI4US/autodesign/exported_results

echo "=== launcher log ==="
cat "$D"/launcher_*.log 2>/dev/null || true

echo "=== total size / file count ==="
du -sh "$D"
echo -n "files total: "; find "$D" -type f | wc -l

echo "=== extensions ==="
find "$D" -type f -printf '%f\n' | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -15

echo "=== per-dir file counts ==="
find "$D" -mindepth 1 -maxdepth 1 -type d | sort | while read -r d; do
  printf '%s %s\n' "$(basename "$d")" "$(find "$d" -type f | wc -l)"
done

echo "=== listing: first result dir ==="
first=$(find "$D" -mindepth 1 -maxdepth 1 -type d -name 'cell_*' | sort | head -1)
echo "dir: $first"
ls -la "$first"

echo "=== listing: cell_te2_7 ==="
ls -la "$D"/cell_te2_7_* 2>/dev/null | head -30

echo "=== peek: one txt (head -5) ==="
one=$(find "$first" -type f -name '*.txt' | sort | head -1)
echo "file: $one"
head -5 "$one" 2>/dev/null

echo "=== peek: txt sizes in first dir ==="
find "$first" -type f -name '*.txt' -printf '%s %f\n' | sort -rn | head -10
