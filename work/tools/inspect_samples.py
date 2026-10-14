"""核对样本载荷：按 fidelity/source_type 统计 inputs/outputs 的键分布与缺失情况。

目的是解释「F2 有 49 条样本，但训练脚本 dropna 后为 0」这一现象。
"""

import json
from collections import Counter

import duckdb

DB = r"C:\Users\zmx\Desktop\memsharness\work\store\mems.duckdb"
con = duckdb.connect(DB, read_only=True)

rows = con.execute(
    "select sample_id, fidelity, source_type, inputs, outputs, design_id from sample"
).fetchall()

by_group: dict[tuple, list] = {}
for sid, fid, st, ins, outs, did in rows:
    ins = json.loads(ins) if isinstance(ins, str) else (ins or {})
    outs = json.loads(outs) if isinstance(outs, str) else (outs or {})
    by_group.setdefault((fid, st), []).append((sid, ins, outs, did))

for (fid, st), items in sorted(by_group.items()):
    print(f"\n=== fidelity={fid} source_type={st}  n={len(items)} ===")
    in_keys = Counter(k for _, i, _, _ in items for k in i)
    out_keys = Counter(k for _, _, o, _ in items for k in o)
    print(f"  input keys : {dict(in_keys)}")
    print(f"  output keys: {dict(out_keys)}")
    # 逐条完整性：该组所有输入键都齐、且值非 None
    all_in = set(in_keys)
    all_out = set(out_keys)
    complete = sum(
        1
        for _, i, o, _ in items
        if all_in <= set(i) and all_out <= set(o)
        and all(v is not None for v in i.values())
        and all(v is not None for v in o.values())
    )
    print(f"  该组内键全齐且无 None 的样本: {complete}/{len(items)}")
    print("  前 3 条载荷：")
    for sid, i, o, _ in items[:3]:
        print(f"    {sid}: inputs={i} outputs={o}")
