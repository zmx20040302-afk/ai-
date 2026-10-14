#!/bin/bash
# 只读：新批次的元数据文件（含可能的 .mph 哈希清单）
set -u
B=/home/lab/projAI4US/autodesign/exported_results/_batch_sep24_20260927_140741_699048

for f in status.txt exit_code.txt selected_models.txt model_manifest.tsv; do
  echo "################ $f"
  cat "$B/$f" 2>/dev/null || echo "(missing)"
  echo
done

echo "################ output_manifest.tsv (head -8 / tail -3)"
head -8 "$B/output_manifest.tsv" 2>/dev/null
echo "  ..."
tail -3 "$B/output_manifest.tsv" 2>/dev/null
echo -n "  总行数: "; wc -l < "$B/output_manifest.tsv" 2>/dev/null
echo

echo "################ exported_dirs.txt"
cat "$B/exported_dirs.txt" 2>/dev/null

echo "################ 远端是否有 .mph 与其哈希目录"
ls -la /home/lab/projAI4US/autodesign/*.mph 2>/dev/null | head -12
echo "-- autodesign 顶层（只列名与大小，不递归）--"
ls -la /home/lab/projAI4US/autodesign/ 2>/dev/null | head -25
