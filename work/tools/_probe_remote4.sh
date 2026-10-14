set -u
D=/home/lab/zhangmx/n4_multifreq_20261010
cd "$D"
# 等当前这批（n4_run_001）自然结束，最多等 20 分钟；再报告状态
for i in $(seq 1 60); do
  P=$(pgrep -c -f n4_run_001.class 2>/dev/null); P=${P:-0}
  DONE=$(grep -c '^MEMS_DONE=1' n4_run_001.stdout.log 2>/dev/null); DONE=${DONE:-0}
  if [ "$P" = "0" ] && [ "$DONE" != "0" ]; then echo "finished after ~$((i*20))s"; break; fi
  if [ "$P" = "0" ] && [ "$i" -gt 3 ]; then echo "process gone after ~$((i*20))s (no MEMS_DONE)"; break; fi
  sleep 20
done
echo "=== stdout size / done markers"
wc -c < n4_run_001.stdout.log
grep -c '^MEMS_DONE=1' n4_run_001.stdout.log || true
grep -c '^MEMS_CHUNK:' n4_run_001.stdout.log || true
echo "=== status file"
cat n4_run_001_out.mph.status 2>/dev/null || echo "(none)"
echo "=== result json present?"
grep -c '^MEMS_RESULT_JSON=' n4_run_001.stdout.log || true
