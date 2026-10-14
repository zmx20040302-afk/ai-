# -*- coding: utf-8 -*-
"""独立核验：S3 标定与 S4 重解的**关键数字**是否与产物一致（只读；不照搬子智能体的叙述）。"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
D = REPO / "work/runs/s3-calib-20261012"
E = REPO / "work/runs/s4-resolve-20261012"
A = REPO / "work/runs/eda64-20261010"

ok, bad = [], []


def chk(tag, claimed, actual, tol=5e-4):
    good = actual is not None and abs(actual - claimed) <= max(abs(claimed) * tol, 1e-15)
    (ok if good else bad).append(tag)
    print("  %s %-52s 声称 %-22s 产物 %s" % ("OK" if good else "**不符**", tag,
                                            ("%.10g" % claimed), ("%.10g" % actual)))


print("=" * 100)
print("A) S3 标定")
a = json.loads((D / "S3_CALIB_RESULT.json").read_text(encoding="utf-8"))
pts = a["points"]
for p in (pts if isinstance(pts, list) else []):
    print("   point:", json.dumps(p, ensure_ascii=False)[:200])
fit = a.get("fit") or {}
print("  fit:", json.dumps(fit, ensure_ascii=False)[:400])
print("  decision:", json.dumps(a.get("decision"), ensure_ascii=False)[:300])
print("  solves_performed:", json.dumps(a.get("solves_performed"), ensure_ascii=False)[:200])
print("  anchors:", json.dumps(a.get("anchors"), ensure_ascii=False)[:300])

print("=" * 100)
print("B) S4 重解")
b = json.loads((E / "S4_RESOLVE_RESULT.json").read_text(encoding="utf-8"))
print("  top keys:", list(b.keys()))
for k in ("operative_key_max", "operative", "verdict", "n_common", "n_key_common", "solves_performed"):
    if k in b:
        print("  %-22s %s" % (k, json.dumps(b[k], ensure_ascii=False)[:200]))
print("  primary:", json.dumps(b.get("primary"), ensure_ascii=False)[:600])

print("=" * 100)
print("C) 既有文件是否被动过（与 INDEX §207/§206 记录的哈希比对）")
targets = [("PREREG_S4_RESOLVE", E / "PREREG_S4_RESOLVE.json", None),
           ("PREREG_S3_CALIB", D / "PREREG_S3_CALIB.json", None),
           ("s4_same_machine.py", REPO / "work/runs/s34-ladder-server-20261008/s4_same_machine.py",
            "8d96d859994667ee0e424984b0cd39def1bebdf22abc5b94548bd57ce550ae4b"),
           ("frozen points tsv",
            REPO / "work/runs/te2_8_pod_fields_20261005/pod_pipeline_x020_v2/common_points_xyz_m.tsv",
            "9067cbdc3e43ced9c270de79e6add0672afaefb7d6dc08cddd9b57bcc487f0e7")]
for label, p, exp in targets:
    if not p.is_file():
        print("  %-22s 缺文件" % label)
        continue
    got = hashlib.sha256(p.read_bytes()).hexdigest()
    if exp:
        good = got == exp
        (ok if good else bad).append(label)
        print("  %s %-22s %s" % ("OK" if good else "**不符**", label, got[:24]))
    else:
        print("  -- %-22s %s（本次新增，无基线）" % (label, got[:24]))

print("\n小计 OK %d / 不符 %d" % (len(ok), len(bad)))
for x in bad:
    print("  不符:", x)
