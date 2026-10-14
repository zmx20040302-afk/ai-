# -*- coding: utf-8 -*-
"""通用远端 Java 批处理驱动（上传 → 编译 → 脱离会话执行 → 轮询 → 取回 stdout）。

为什么单独抽出来：本项目已多次需要「在 node01 上跑一个零求解/求解的 COMSOL Java 类」，
每次都复制一遍轮询逻辑既啰嗦又容易把已踩过的坑（`grep -c` 双打印错位、ssh 掉线杀进程、
中文路径传给 scp 等）重新引入。本脚本把这些纪律固化在一处。

纪律（均来自实测）：
  * 远端目录必须 **ASCII**；模型文件必须在**该目录**里（类里用相对路径 loadCopy）；
  * 用 `nohup ... &` 脱离 ssh 会话；轮询用 **key=value** 输出；
  * 完成判据：`MEMS_DONE=1`，或进程消失且（有 .status 或 stdout 非空）；
  * 取回的 stdout **逐字**落盘；若含 `MEMS_RESULT_JSON=` 则单独另存一份 JSON。

用法：
  python run_remote_java.py --java <x.java> --cls <ClassName> --remote-dir /home/lab/zhangmx/xxx \
      --out <本地输出目录> [--stoptime 1800] [--timeout_s 2400]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SSH_HOST = "ubuntu-10-180-7-46"
KEY = str(pathlib.Path.home() / ".ssh" / "codex_ubuntu_10_180_7_46")
COMSOL = "/usr/local/bin/comsol64"
NP = "16"
SSH = ["ssh", "-i", KEY, "-o", "BatchMode=yes", SSH_HOST]
SCP = ["scp", "-i", KEY, "-o", "BatchMode=yes"]


def ssh_script(script: str, timeout: int = 120) -> tuple[int, str, str]:
    p = subprocess.run(SSH + ["bash -s"], input=script.encode("utf-8"),
                       capture_output=True, timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--java", required=True)
    ap.add_argument("--cls", required=True)
    ap.add_argument("--remote-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stoptime", default="1800")
    ap.add_argument("--timeout_s", type=int, default=2400)
    a = ap.parse_args()
    java = pathlib.Path(a.java).resolve()
    outdir = pathlib.Path(a.out).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    cls, rd = a.cls, a.remote_dir
    rec: dict = {"kind": "remote_java_run", "host": SSH_HOST, "remote_dir": rd, "cls": cls,
                 "np": NP, "comsol": COMSOL, "java": str(java), "stoptime": a.stoptime,
                 "java_sha256": hashlib.sha256(java.read_bytes()).hexdigest()}
    t0 = time.time()
    up = subprocess.run(SCP + [str(java), "%s:%s/%s.java" % (SSH_HOST, rd, cls)],
                        capture_output=True, timeout=300)
    rec["upload_rc"] = up.returncode
    if up.returncode != 0:
        rec["upload_err"] = up.stderr.decode("utf-8", "replace")[:400]
        print(json.dumps(rec, ensure_ascii=False, indent=1))
        return 1
    rc, out, err = ssh_script(
        "set -u\ncd %s\nls -l *.mph 2>/dev/null | awk '{print \"MPH=\"$9\":\"$5}'\n"
        "rm -f %s.class %s.stdout.log\n"
        "%s compile %s.java > compile_%s.log 2>&1\n"
        "echo compile_rc=$?\ntail -3 compile_%s.log\nls -l %s.class 2>/dev/null || echo NO_CLASS\n"
        % (rd, cls, cls, COMSOL, cls, cls, cls, cls), timeout=900)
    rec["preflight"] = out.strip()[-500:]
    if "NO_CLASS" in out:
        rec["status"] = "compile_failed"
        rec["compile_err"] = err.strip()[:400]
        (outdir / "REMOTE_RUN.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
        print(json.dumps(rec, ensure_ascii=False, indent=1))
        return 1
    ssh_script(
        "set -u\ncd %s\nnohup %s batch -inputfile %s.class -outputfile %s_out.mph "
        "-batchlog batchlog_%s.txt -np %s -stoptime %s > %s.stdout.log 2>&1 &\n"
        "echo pid=$!\nsleep 2\n" % (rd, COMSOL, cls, cls, cls, NP, a.stoptime, cls), timeout=180)
    polls = []
    ok = False
    while time.time() - t0 < a.timeout_s:
        time.sleep(20)
        rc, out, _ = ssh_script(
            "cd %s\nD=$(grep -c '^MEMS_DONE=1' %s.stdout.log 2>/dev/null); D=${D:-0}\n"
            "P=$(pgrep -c -f %s.class 2>/dev/null); P=${P:-0}\n"
            "S=$([ -f %s_out.mph.status ] && echo 1 || echo 0)\n"
            "B=$(wc -c < %s.stdout.log 2>/dev/null); B=${B:-0}\n"
            "echo D=$D P=$P S=$S B=$B\n" % (rd, cls, cls, cls, cls), timeout=90)
        kv = dict(tok.split("=", 1) for tok in out.split() if "=" in tok)
        polls.append(kv)
        if int(kv.get("D", 0)) >= 1:
            ok = True
            break
        if int(kv.get("P", -1)) == 0 and (int(kv.get("S", 0)) == 1 or int(kv.get("B", 0)) > 0):
            ok = True
            break
        if int(kv.get("P", -1)) == 0 and time.time() - t0 > 300:
            ok = True
            break
    rec["poll_ok"] = ok
    rec["polls"] = polls[-8:]
    rec["wall_seconds"] = round(time.time() - t0, 1)
    rc, out, err = ssh_script("cd %s\ncat %s.stdout.log\n" % (rd, cls), timeout=600)
    (outdir / (cls + ".stdout.log")).write_text(out, encoding="utf-8", newline="\n")
    payload = None
    for ln in out.split("\n"):
        if ln.startswith("MEMS_RESULT_JSON="):
            payload = ln[len("MEMS_RESULT_JSON="):]
    rec["stdout_bytes"] = len(out)
    rec["has_result"] = payload is not None
    if payload:
        (outdir / (cls.upper() + "_RAW.json")).write_text(payload + "\n", encoding="utf-8")
    rec["stdout_head"] = out[:600]
    (outdir / "REMOTE_RUN.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    print("poll_ok=%s wall=%.0fs stdout=%dB has_result=%s"
          % (rec["poll_ok"], rec["wall_seconds"], rec["stdout_bytes"], rec["has_result"]))
    if not rec["has_result"]:
        print(out[-1500:])
    return 0 if rec["has_result"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
