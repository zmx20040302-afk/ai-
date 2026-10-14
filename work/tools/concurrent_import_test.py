"""并发导入压力实验：同时拉起 N 个解释器导入 scipy 编译扩展。

目的：验证「0xc0000142（STATUS_DLL_INIT_FAILED）」是否与并发进程启动相关
（Windows 上典型诱因是 desktop heap 耗尽或加载器竞争），而非缺依赖。

用法：
    python work/tools/concurrent_import_test.py [N]
"""

import subprocess
import sys
import time
from pathlib import Path

N = int(sys.argv[1]) if len(sys.argv) > 1 else 16
PY = Path(sys.executable)
CODE = "import scipy.optimize, scipy.linalg, scipy.stats; print('ok')"

start = time.time()
procs = [
    subprocess.Popen(
        [str(PY), "-c", CODE],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for _ in range(N)
]

ok = bad = 0
for i, p in enumerate(procs):
    out, err = p.communicate()
    if p.returncode == 0 and "ok" in out:
        ok += 1
    else:
        bad += 1
        tail = (err or out).strip().splitlines()[-1] if (err or out).strip() else "?"
        print(f"  proc {i}: rc={p.returncode} :: {tail}")

print(f"concurrent N={N}: ok={ok} fail={bad} elapsed={time.time()-start:.1f}s")
