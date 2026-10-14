#!/bin/bash
# 只读：每个 run 的真实参数三元组 / 频段 / 点数 / 峰值 / 导出器告警（ASCII 输出）
set -u
D=/home/lab/projAI4US/autodesign/exported_results
B=$(find "$D" -mindepth 1 -maxdepth 1 -type d -name '_batch_*' | sort | head -1)

echo "=== batch status ==="
cat "$B/status.txt" 2>/dev/null
echo "warnings in matlab.log: $(grep -c '^Warning' "$B/matlab.log" 2>/dev/null)"

echo
echo "=== per-run: params(x_scale N_w_te1 N_w_te2) | n_freq | freq_min..freq_max | peak_dB | width_Hz | Q ==="
for d in $(find "$D" -mindepth 1 -maxdepth 1 -type d -name 'cell_*' | sort); do
  name=$(basename "$d")
  t9="$d/Table_9.txt"
  bw="$d/Bandwidth.txt"
  if [ ! -f "$t9" ]; then
    printf '%-46s | EMPTY (%s files)\n' "$name" "$(find "$d" -type f | wc -l)"
    continue
  fi
  read -r xs n1 n2 f0 <<<"$(sed -n 6p "$t9" | awk '{print $1, $2, $3, $4}')"
  nf=$(($(wc -l < "$t9") - 5))
  fmin=$(sed -n 6p "$t9" | awk '{print $4}')
  fmax=$(tail -1 "$t9" | awk '{print $4}')
  if [ -f "$bw" ]; then
    peak=$(sed -n 6p "$bw" | awk '{printf "%.2f", $2}')
    wid=$(sed -n 6p "$bw" | awk '{printf "%.4g", $3}')
    q=$(sed -n 6p "$bw" | awk '{printf "%.4g", $4}')
    nbw=$(($(wc -l < "$bw") - 5))
  else
    peak="-"; wid="-"; q="-"; nbw=0
  fi
  printf '%-46s | x=%s N1=%s N2=%s | nf=%s | %s..%s | dB=%s | W=%s | Q=%s | bw_rows=%s\n' \
    "$name" "$xs" "$n1" "$n2" "$nf" "$fmin" "$fmax" "$peak" "$wid" "$q" "$nbw"
done

echo
echo "=== exporter warnings per model (from matlab.log) ==="
grep '^Warning ' "$B/matlab.log" 2>/dev/null | sed 's/^Warning //' | awk -F: '{m=$1; sub(/.*\//,"",m); sub(/\.mph$/,"",m); w=substr($0, index($0,":")+2); printf "%s\t%s\n", m, w}' | sort | uniq -c | sort -rn | head -40

echo
echo "=== warning kinds ==="
grep '^Warning ' "$B/matlab.log" 2>/dev/null | sed 's/.*: //' | sed 's/\[[0-9e+., ]*\]//' | sort | uniq -c | sort -rn

echo
echo "=== models listed in matlab.log but with no exported dir? ==="
grep -o 'cell_te2_[A-Za-z0-9._-]*\.mph' "$B/matlab.log" 2>/dev/null | sort -u | sed 's/\.mph$//' | while read -r m; do
  if ! ls -d "$D/${m}"_* >/dev/null 2>&1; then echo "MISSING EXPORT: $m"; fi
done
