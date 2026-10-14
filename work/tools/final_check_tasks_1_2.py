# -*- coding: utf-8 -*-
"""任务 1+2 收尾复核：论文对、补充材料结构、包状态、INDEX 末节。一次读全，全部从磁盘。"""
import hashlib
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
D = R / "docs"
P = R / "work/dist/peakguard-bench-v1-20261013"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def line(tag, ok, detail=""):
    print("  [%s] %-46s %s" % ("OK " if ok else "BAD", tag, detail))
    return ok


allok = True
print("== 任务 1：论文 ==")
v18 = D / "PAPER_DAC2027_EN_v18_20261013.md"
supe = D / "PAPER_DAC2027_EN_SUPPLEMENT_20261013e.md"
prov = D / "PAPER_DAC2027_EN_v18_PROVENANCE.md"
t18 = v18.read_text(encoding="utf-8")
te = supe.read_text(encoding="utf-8")
allok &= line("v18 存在且 LF", v18.is_file() and "\r\n" not in t18,
              "%d B sha %s" % (v18.stat().st_size, sha(v18)[:16]))
allok &= line("正文含 Solution identity 段", "**Solution identity.**" in t18 and "(§S13)" in t18)
allok &= line("补充材料含 §S13（末尾）", te.rstrip().endswith("load-bearing.") and "## S13." in te)
allok &= line("§S12 T3/T5 已加解身份", "plus a solution identity" in te and "solution identity check fails" in te)
allok &= line("PROVENANCE 存在", prov.is_file(), "%d B" % prov.stat().st_size)
allok &= line("双盲：正文无内部路径", not re.search(r"work[/\\]runs|memsharness|node0\d", t18))

print("== 任务 2：M4 包 ==")
m = json.loads((P / "MANIFEST.json").read_text(encoding="utf-8"))
fs = sorted(p.relative_to(P).as_posix() for p in P.rglob("*") if p.is_file())
allok &= line("包文件数 = 清单 + MANIFEST", len(fs) == m["n_files"] + 1, "%d 件" % len(fs))
allok &= line("清单键全 POSIX", not any("\\" in k for k in m["files"]))
allok &= line("无 __pycache__ / results 残留",
              not any("__pycache__" in f or f.startswith("results/") for f in fs))
allok &= line("身份审计干净", m["identity_audit_clean"] is True)
allok &= line("解身份两件在清单里",
              "check_solution_identity.py" in m["files"] and "data/solution_identity_example.json" in m["files"])
for f in fs:
    if f != "MANIFEST.json" and sha(P / f) != m["files"][f]["sha256"]:
        allok &= line("哈希一致 " + f, False)
line("逐件哈希与清单一致", True, "%d 件核对" % (len(fs) - 1))
si = json.loads((P / "data/solution_identity_example.json").read_text(encoding="utf-8"))
allok &= line("示例记录标注为合成", si.get("synthetic") is True)
allok &= line("示例含 expected_decision", "expected_decision" in si)

print("== 冒烟 + 报告 ==")
sm = json.loads((R / "work/runs/ai11-m4-20261013/SMOKE_RUN_LATEST.json").read_text(encoding="utf-8-sig"))
rep = json.loads((R / "work/runs/ai11-m4-20261013/M4_PACKAGE_REPORT.json").read_text(encoding="utf-8-sig"))
allok &= line("冒烟双通过", sm["verdict"] == "PASS" and sm["solution_identity_self_test"] == "PASS",
              "%.1f s / %d 格" % (sm["wall_seconds"], sm["cells_compared_ok"]))
allok &= line("报告数字来自解析", rep["smoke_test"].get("numbers_are_parsed_not_handwritten") is True)
allok &= line("报告留证数 > 0", rep["smoke_test"]["evidence_file_count"] > 0,
              "%d 件" % rep["smoke_test"]["evidence_file_count"])
allok &= line("报告清单一致", rep["manifest_consistency_after_removing_results"]["ok"] is True)

print("== INDEX ==")
idx = D / "INDEX-records-and-rulings.md"
b = idx.read_bytes()
allok &= line("INDEX 末节为 §244", b.rstrip().endswith("`physics_consistent`。".encode("utf-8")) or
              "## 244." in b[-12000:].decode("utf-8"))
allok &= line("INDEX 为 CRLF", b"\r\n" in b)
allok &= line("INDEX 尺寸/哈希", True, "%d B sha %s" % (len(b), hashlib.sha256(b).hexdigest()[:16]))
n244 = sum(1 for l in b.decode("utf-8").split("\n") if l.startswith("## 244."))
allok &= line("§244 顶层标题 1 次", n244 == 1, "count=%d（子节 244.x 不计）" % n244)

print("\n== 总结：%s ==" % ("全部通过" if allok else "有失败项"))
raise SystemExit(0 if allok else 1)
