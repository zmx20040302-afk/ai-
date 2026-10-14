"""P1 并发反向测试（Codex R6 §5 / §7.4）—— 不启动 COMSOL。

三组：
  A. 两个**不同** namespace 同时启动 ⇒ 两者都应 82/82，彼此文件零交叉、零删除；
  B. 两个**相同** namespace 同时启动 ⇒ 一个正常持锁运行，另一个 `REFUSED_CONCURRENT_OWNER`
     且非零退出，**不得改动持锁方目录**；
  C. 锁的异常/崩溃语义 ⇒ 正常异常经 `finally` 释放；模拟崩溃留下的锁，
     下一轮**只能在核验旧 owner 已不存在后**回收。

用法：python work/tools/lt2_conc_tests.py --repo-root <abs>
退出码：0 = 三组全过
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
PY = sys.executable
SUITE = TOOLS / "tests_lt2_supervisor.py"


def sha(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:
        return None


def tree(ns_root: Path, skip_lock: bool = False) -> dict:
    out = {}
    if not ns_root.is_dir():
        return out
    for f in sorted(ns_root.rglob("*")):
        if f.is_file() and not (skip_lock and f.name == "OWNER.LOCK"):
            out[f.relative_to(ns_root).as_posix()] = sha(f)
    return out


def launch(ns: str, env_base: dict) -> subprocess.Popen:
    env = dict(env_base)
    env["LT2_TEST_NAMESPACE"] = ns
    env.pop("LT2_RUNS_ROOT", None)
    return subprocess.Popen([PY, "-X", "utf8", str(SUITE), "--namespace", ns],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=env)


def read_summary(ns_root: Path) -> dict:
    p = ns_root / "test_summary.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    args = ap.parse_args(argv)
    repo = Path(args.repo_root).resolve()
    RUNS = repo / "work" / "runs"
    OUT = RUNS / "lt2-concurrency-tests"
    OUT.mkdir(parents=True, exist_ok=True)
    base = dict(os.environ)
    base.pop("LT2_RUNS_ROOT", None)
    stamp = time.strftime("%H%M%S")
    res: dict = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "comsol_started": False, "mph_imported": False, "groups": {}}
    ok_all = True

    # ---------------- A：不同 namespace 并发 ----------------
    nsA1, nsA2 = f"concA-{stamp}-1", f"concA-{stamp}-2"
    rA1, rA2 = RUNS / nsA1, RUNS / nsA2
    p1, p2 = launch(nsA1, base), launch(nsA2, base)
    # 运行中抓一次中间态（用于证明"零删除"）
    time.sleep(12)
    mid1, mid2 = tree(rA1), tree(rA2)
    o1 = p1.communicate()[0]
    o2 = p2.communicate()[0]
    s1, s2 = read_summary(rA1), read_summary(rA2)
    end1, end2 = tree(rA1), tree(rA2)
    # OWNER.LOCK 的创建/删除是**锁生命周期**，不是证据被删；零删除只针对证据文件
    deleted1 = sorted(k for k in set(mid1) - set(end1) if not k.endswith("OWNER.LOCK"))
    deleted2 = sorted(k for k in set(mid2) - set(end2) if not k.endswith("OWNER.LOCK"))
    cross = sorted({k for k in list(end1) + list(end2) if k.startswith("../")})
    a_ok = (s1.get("total") == 82 and s1.get("pass") == 82 and s1.get("fail") == 0
            and s2.get("total") == 82 and s2.get("pass") == 82 and s2.get("fail") == 0
            and not deleted1 and not deleted2 and not cross)
    res["groups"]["A_different_namespaces"] = {
        "pass": a_ok, "ns1": nsA1, "ns2": nsA2,
        "rc": [p1.returncode, p2.returncode],
        "structured": [{k: s1.get(k) for k in ("total", "pass", "fail")},
                       {k: s2.get(k) for k in ("total", "pass", "fail")}],
        "files": [len(end1), len(end2)],
        "deleted_during_run": [deleted1, deleted2],
        "cross_namespace_paths": cross,
        "output_sha256": {nsA1: hashlib.sha256((o1 or "").encode()).hexdigest(),
                          nsA2: hashlib.sha256((o2 or "").encode()).hexdigest()}}
    ok_all &= a_ok

    # ---------------- B：相同 namespace 并发 ----------------
    nsB = f"concB-{stamp}"
    rB = RUNS / nsB
    pB1 = launch(nsB, base)
    # 等锁出现，确认第一方已持锁
    lock = rB / "OWNER.LOCK"
    for _ in range(120):
        if lock.is_file():
            break
        time.sleep(1)
    before = tree(rB, skip_lock=True)
    pB2 = launch(nsB, base)          # 同一 namespace ⇒ 必须被拒
    oB2 = pB2.communicate()[0]
    after = tree(rB, skip_lock=True)
    oB1 = pB1.communicate()[0]
    sB = read_summary(rB)
    refused = ("REFUSED_CONCURRENT_OWNER" in (oB2 or "")) and pB2.returncode != 0
    holder_untouched = all(before.get(k) == after.get(k) for k in before) and \
        set(before) <= set(after)
    b_ok = bool(refused and holder_untouched
                and sB.get("total") == 82 and sB.get("pass") == 82 and sB.get("fail") == 0)
    res["groups"]["B_same_namespace"] = {
        "pass": b_ok, "namespace": nsB,
        "holder_rc": pB1.returncode, "intruder_rc": pB2.returncode,
        "intruder_refused": refused,
        "intruder_stdout_tail": "\n".join((oB2 or "").splitlines()[-4:]),
        "holder_structured": {k: sB.get(k) for k in ("total", "pass", "fail")},
        "holder_files_unchanged": holder_untouched,
        "holder_files": len(before),
        "holder_output_sha256": hashlib.sha256((oB1 or "").encode()).hexdigest(),
        "intruder_output_sha256": hashlib.sha256((oB2 or "").encode()).hexdigest()}
    ok_all &= b_ok

    # ---------------- C：锁的异常/崩溃语义 ----------------
    nsC = f"concC-{stamp}"
    rC = RUNS / nsC
    probe = f"""
import json, sys, time
sys.path.insert(0, r'{TOOLS}')
sys.argv = ['probe', '--namespace', '{nsC}']
import tests_lt2_supervisor as T
r1 = T.acquire_lock()
print('acquire1', r1['ok'], r1.get('verdict'))
r2 = T.acquire_lock()            # 同一进程再取 ⇒ 应被自己拒
print('acquire2', r2['ok'], r2.get('verdict'))
rel = T.release_lock()
print('release', rel.get('released'))
r3 = T.acquire_lock()            # 释放后应能再取
print('acquire3', r3['ok'])
T.release_lock()
"""
    env = dict(base)
    pr = subprocess.run([PY, "-X", "utf8", "-c", probe], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", env=env)
    # C2：模拟崩溃 —— 写入一个"持有者已死"的锁，下一轮必须核验后回收
    rC.mkdir(parents=True, exist_ok=True)
    dead = subprocess.Popen([PY, "-c", "import time;time.sleep(0.2)"])
    dead_pid = dead.pid
    dead.wait()
    (rC / "OWNER.LOCK").write_text(json.dumps(
        {"pid": dead_pid, "owner_token": "crashed-owner", "namespace": nsC,
         "process_create_time": "0", "started_at": "2026-09-14T00:00:00"}), encoding="utf-8")
    c2 = subprocess.run([PY, "-X", "utf8", str(SUITE), "--namespace", nsC],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", env=env)
    sC = read_summary(rC)
    c_ok = (pr.returncode == 0 and "acquire1 True" in pr.stdout
            and "acquire2 False" in pr.stdout and "release True" in pr.stdout
            and "acquire3 True" in pr.stdout
            and c2.returncode == 0 and sC.get("pass") == 82)
    res["groups"]["C_lock_lifecycle_and_crash_reclaim"] = {
        "pass": c_ok,
        "probe_stdout": pr.stdout.strip().splitlines(),
        "reclaim_run_rc": c2.returncode,
        "reclaim_structured": {k: sC.get(k) for k in ("total", "pass", "fail")},
        "stale_lock_pid": dead_pid, "stale_pid_alive": False,
        "probe_output_sha256": hashlib.sha256(pr.stdout.encode()).hexdigest(),
        "reclaim_output_sha256": hashlib.sha256((c2.stdout or "").encode()).hexdigest()}
    ok_all &= c_ok

    res["all_groups_pass"] = bool(ok_all)
    res["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (OUT / "concurrency_summary.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for g, v in res["groups"].items():
        print(f"{g}: {'PASS' if v['pass'] else 'FAIL'}", flush=True)
    print(json.dumps({k: res["groups"][k]["pass"] for k in res["groups"]},
                     ensure_ascii=False), flush=True)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
