# -*- coding: utf-8 -*-
"""M4 任务套件收尾复核：包状态、期望件、冒烟事实、留证、INDEX、git。全部从磁盘读。"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
P = R / "work/dist/peakguard-bench-v1-20261013"
M4 = R / "work/runs/ai11-m4-20261013"
G = r"C:\Program Files\Git\cmd\git.exe"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def line(tag, ok, detail=""):
    print("  [%s] %-44s %s" % ("OK " if ok else "BAD", tag, detail))
    return ok


ok = True
print("== 包状态 ==")
man = json.loads((P / "MANIFEST.json").read_text(encoding="utf-8"))
fs = sorted(p.relative_to(P).as_posix() for p in P.rglob("*") if p.is_file())
ok &= line("件数 = 清单 + MANIFEST", len(fs) == man["n_files"] + 1, "%d 件" % len(fs))
ok &= line("身份审计干净", man["identity_audit_clean"] is True)
ok &= line("清单键全 POSIX", not any("\\" in k for k in man["files"]))
ok &= line("无 pycache / results 残留",
           not any("__pycache__" in f or f.startswith("results/") for f in fs))
bad = [f for f in fs if f != "MANIFEST.json" and sha(P / f) != man["files"][f]["sha256"]]
ok &= line("逐件哈希与清单一致", not bad, "%d 件核对" % (len(fs) - 1))
vs = man["vendored_task_suite"]
TASK_SCRIPTS = ("tasks/label_validity.py", "tasks/m1_m2_m3.py", "tasks/t1_t2.py",
                "tasks/t1_t2_spacing.py", "tasks/t5.py", "tasks/t7_scheduling.py")
ok &= line("任务脚本 6 个齐全", all(t in vs["files"] for t in TASK_SCRIPTS),
           "tasks/ 下共 %d 件（含支持件）" % sum(1 for k in vs["files"] if k.startswith("tasks/")))
ok &= line("oracle 94 点", vs["oracle"]["n_points"] == 94, "%.2f MB" % (vs["oracle"]["bytes"] / 1e6))
ok &= line("禁串扫描记录在清单", all(v["forbidden_scan"] == "clean" for v in vs["files"].values()))

print("== 期望件 ==")
et = json.loads((P / "expected/EXPECTED_TASKS.json").read_text(encoding="utf-8"))
cjk = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")
ok &= line("5 个任务 / 8 个输出件", len(et["tasks"]) == 5 and sum(len(v) for v in et["tasks"].values()) == 8)
ok &= line("对比树内无中日韩/全角字符", not cjk.search(json.dumps(et["tasks"], ensure_ascii=False)))
ok &= line("剥离策略含 per_output", "per_output" in et["strip_policy"],
           "%d 条剥离" % len(et["removed_keys"]))

print("== 冒烟与留证 ==")
sm = json.loads((M4 / "SMOKE_RUN_LATEST.json").read_text(encoding="utf-8-sig"))
ok &= line("三段全 PASS", all(sm[k]["verdict"] == "PASS" for k in ("check_only", "benchmark", "tasks")),
           "总 %.1f s" % sm["wall_seconds_total"])
snap = (sm.get("produced_artifacts_snapshot") or {})
snapdir = R / snap.get("dir", "")
ok &= line("产物快照存在", snapdir.is_dir() and snap.get("n_files", 0) > 0, "%d 文件" % snap.get("n_files", 0))
ok &= line("快照哈希与事实件一致",
           all(sha(snapdir / f["file"]) == f["sha256"] for f in snap.get("files", [])))

print("== 报告与 INDEX ==")
rep = json.loads((M4 / "M4_PACKAGE_REPORT.json").read_text(encoding="utf-8-sig"))
ok &= line("报告三段冒烟", rep["smoke_test"].get("three_stage") is True)
ok &= line("报告留证数 > 0", rep["smoke_test"]["evidence_file_count"] > 0)
idx = R / "docs/INDEX-records-and-rulings.md"
b = idx.read_bytes()
ok &= line("INDEX 含 §244 与 §245",
           "## 244." in b.decode("utf-8") and "## 245." in b.decode("utf-8"))
ok &= line("INDEX CRLF", b"\r\n" in b, "%d B sha %s" % (len(b), hashlib.sha256(b).hexdigest()[:16]))

print("== git ==")
head = subprocess.run([G, "rev-parse", "HEAD"], cwd=str(R), capture_output=True, text=True).stdout.strip()
rem = subprocess.run([G, "rev-parse", "origin/master"], cwd=str(R), capture_output=True, text=True).stdout.strip()
st = subprocess.run([G, "status", "--porcelain"], cwd=str(R), capture_output=True, text=True).stdout.strip()
ok &= line("本地 == 远端", head == rem, head[:12])
ok &= line("工作区干净", st == "")

print("\n== 总结：%s ==" % ("全部通过" if ok else "有失败项"))
raise SystemExit(0 if ok else 1)
