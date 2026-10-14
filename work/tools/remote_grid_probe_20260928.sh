#!/bin/bash
# 只读探针：三个新 run 的参数/频率网格（不下载，先看清规模）
set -u
D=/home/lab/projAI4US/autodesign/exported_results

for n in cell_te2_5_test_scal_0.2-1_0.01_freq5-50_v1_20260928_071108962_001 \
         cell_te2_6_test_scal_0.2-1_0.01_freq5-50_v1_20260928_074201239_001 \
         cell_te2_7_test_scal_0.2-1_0.01_freq5-50_v1_20260928_085936317_001; do
  f="$D/$n/Table_9.txt"
  echo "################ $n"
  if [ ! -f "$f" ]; then echo "  MISSING"; continue; fi
  # 跳过 5 行表头
  tail -n +6 "$f" | awk '
    { rows++; x[$1]=1; n1[$2]=1; n2[$3]=1;
      if ($4+0<fmin || rows==1) fmin=$4+0;
      if ($4+0>fmax) fmax=$4+0; }
    END {
      printf "  rows=%d\n", rows;
      printf "  x_scale: %d unique\n", length(x);
      m=0; M=1e9; for (k in x) { v=k+0; if (v>m) m=v; if (v<M) M=v; }
      printf "    min=%.4f max=%.4f\n", M, m;
      printf "  N_w_te1: %d unique -> ", length(n1);
      c=0; for (k in n1) { printf "%s ", k; if (++c>=12) break } printf "\n";
      printf "  N_w_te2: %d unique -> ", length(n2);
      for (k in n2) printf "%s ", k; printf "\n";
      printf "  freq: min=%g max=%g MHz\n", fmin/1e6, fmax/1e6;
      printf "  rows / (x * N1) = %d combos，每组合频点数 = %.1f\n", 0, rows/0;
    }' 2>/dev/null | head -20
  # 组合数与每组合频点数（用 sort -u 精确算）
  echo -n "  distinct (x,N1,N2) combos: "
  tail -n +6 "$f" | awk '{print $1"_"$2"_"$3}' | sort -u | wc -l
  echo -n "  per-combo freq points: "
  tail -n +6 "$f" | awk '{print $1"_"$2"_"$3}' | sort | uniq -c | awk '{print $1}' | sort -u | tr '\n' ' '
  echo
  echo -n "  freq values per combo (first combo): "
  tail -n +6 "$f" | awk 'NR<=200{print $4}' | sort -un | head -3 | tr '\n' ' '
  echo "..."
  echo "  Peak_frequency rows: $(tail -n +6 "$D/$n/Peak_frequency.txt" | wc -l)"
done

echo
echo "=== 新批次标记目录 ==="
ls -la "$D/_batch_sep24_20260927_140741_699048" 2>/dev/null
echo "--- 其日志尾部 ---"
for g in "$D"/_batch_sep24_20260927_140741_699048/*.log; do
  [ -f "$g" ] && { echo "## $(basename "$g")"; tail -25 "$g"; }
done
