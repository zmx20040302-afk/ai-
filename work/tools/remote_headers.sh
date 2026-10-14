#!/bin/bash
# 只读：把六类导出表的表头与规模读全（ASCII 标签，避免控制台编码问题）
set -u
D=/home/lab/projAI4US/autodesign/exported_results
first=$(find "$D" -mindepth 1 -maxdepth 1 -type d -name 'cell_*' | sort | head -1)
big=$(find "$D" -mindepth 1 -maxdepth 1 -type d -name 'cell_te2_7*' | sort | head -1)

echo "=== batch dir ==="
ls -la "$D"/_batch_* 2>/dev/null
for f in "$D"/_batch_*/*; do echo "--- $f"; head -20 "$f" 2>/dev/null; done

echo
echo "=== headers of the 6 txt types (small run) ==="
for n in Bandwidth Peak_frequency Table_9 Table_10 Table_11 Zdisplacement; do
  f="$first/$n.txt"
  echo "--- $n : $(wc -l < "$f") lines"
  head -6 "$f"
  echo "    ..."
done

echo
echo "=== big run (cell_te2_7) line counts ==="
for n in Bandwidth Peak_frequency Table_9 Table_10 Table_11 Zdisplacement; do
  printf '%-16s %s lines  %s bytes\n' "$n" "$(wc -l < "$big/$n.txt")" "$(stat -c%s "$big/$n.txt")"
done
echo "--- Bandwidth head (big)"; head -8 "$big/Bandwidth.txt"
echo "--- Peak_frequency head (big)"; head -8 "$big/Peak_frequency.txt"

echo
echo "=== Model header of every run (which .mph each run used) ==="
for d in $(find "$D" -mindepth 1 -maxdepth 1 -type d -name 'cell_*' | sort); do
  f="$d/Bandwidth.txt"
  if [ -f "$f" ]; then
    printf '%s | %s | %s\n' "$(basename "$d")" "$(sed -n 2p "$f" | tr -s ' ')" "$(sed -n 1p "$f" | cut -c22-)"
  else
    printf '%s | (no Bandwidth.txt: %s files)\n' "$(basename "$d")" "$(find "$d" -type f | wc -l)"
  fi
done
