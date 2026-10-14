# -*- coding: utf-8 -*-
"""支点检查：注册结果里记录的**输入 sha256** 是否与包内件逐字节相同。

若相同，则 vendored 任务应当**逐位**复现注册数字（可断言精确相等，而非仅容差）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
P = R / "work/dist/peakguard-bench-v1-20261013"
M4 = R / "work/runs/ai11-m4-20261013"
M13 = R / "work/runs/ai11-m1m3-20261013"
T15 = R / "work/runs/ai11-t1t2t5-20261013"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cmp(label: str, pkg_file: pathlib.Path, expected: str, src: str):
    if not pkg_file.is_file():
        print("  [缺 ] %-34s %s" % (label, pkg_file))
        return False
    h = sha(pkg_file)
    ok = h == expected
    print("  [%s] %-34s %s" % ("OK " if ok else "DIFF", label, h[:24]))
    if not ok:
        print("        %-34s 期望 %s  （%s）" % ("", expected[:24], src))
    return ok


print("== 注册件里记录的输入 → 包内对应件 ==")
t1 = json.loads((T15 / "T1_T2_RESULT.json").read_text(encoding="utf-8"))
t5 = json.loads((T15 / "T5_RESULT.json").read_text(encoding="utf-8"))
ins = {**t1["inputs"], **t5["inputs"]}
for src, exp in sorted(ins.items()):
    name = pathlib.Path(src).name
    pkg = {"multichannel_labels.csv": P / "data/channels_multichannel.csv",
           "grouped_split_assignments.csv": P / "data/splits_grouped_five_seeds.csv",
           "baselines_by_seed.json": M4 / "smoke_results/baselines_by_seed.json",
           "M3_RESULT.json": M13 / "M3_RESULT.json",
           "M2_RESULT.json": M13 / "M2_RESULT.json"}.get(name)
    cmp(name, pkg, exp, src)

print("\n== 包内数据 vs 主标签表 ==")
print("  包内 labels_two_batch_v3.csv sha:", sha(P / "data/labels_two_batch_v3.csv")[:24])
print("  源 labels_two_batch.csv      sha:", sha(R / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv")[:24])
print("  包内 channels_multichannel   sha:", sha(P / "data/channels_multichannel.csv")[:24])
print("  源 multichannel_labels.csv   sha:", sha(R / "work/runs/first-peak-20260929/multichannel_labels.csv")[:24])

print("\n== bench.py 复跑的基线注册件 vs 注册原件的**键集** ==")
reg_src = json.loads((R / "work/runs/eda64-20261010/n2_baselines/baselines_by_seed.json").read_text(encoding="utf-8"))
smoke = json.loads((M4 / "smoke_results/baselines_by_seed.json").read_text(encoding="utf-8"))
print("  源 sha256 :", sha(R / "work/runs/eda64-20261010/n2_baselines/baselines_by_seed.json")[:24])
print("  复跑 sha256:", sha(M4 / "smoke_results/baselines_by_seed.json")[:24])
print("  字节相同  :", sha(R / "work/runs/eda64-20261010/n2_baselines/baselines_by_seed.json") == sha(M4 / "smoke_results/baselines_by_seed.json"))
a = json.dumps(reg_src, sort_keys=True)
b = json.dumps(smoke, sort_keys=True)
print("  规范化 JSON 相同:", a == b)
