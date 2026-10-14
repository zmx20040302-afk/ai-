set -u
D=/home/lab/zhangmx/n4_multifreq_20261010
cd "$D"
echo "=== ls"
ls -l | head -20
echo "=== stdout tail (n4_run_001)"
tail -c 1200 n4_run_001.stdout.log 2>/dev/null || echo "(no stdout log)"
echo "=== batchlog tail"
tail -c 1500 batchlog_n4_run_001.txt 2>/dev/null || echo "(no batchlog)"
echo "=== compile log"
cat compile_n4_run_001.log 2>/dev/null | head -20
echo "=== any comsol procs"
pgrep -a -f n4_run_001 | head -3 || echo none
echo "=== out mph"
ls -l n4_run_001_out.mph* 2>/dev/null || echo "(no out mph)"
