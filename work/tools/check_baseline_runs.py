"""列出本机 baseline 相关的 run 行与 feedback 行（只读核对）。"""

from __future__ import annotations

from pathlib import Path

import duckdb

DB = Path(r"C:\Users\zmx\Desktop\memsharness\work\store\mems.duckdb")
con = duckdb.connect(str(DB), read_only=True)

print("== baseline run 行 ==")
rows = con.execute(
    "select run_id, pathway, status, round(wall_seconds,1), coalesce(diagnostic,'')"
    " from run where run_id like 'baseline-%' order by started_at"
).fetchall()
for r in rows:
    print(f"  {r[0]}  pathway={r[1]} status={r[2]} wall={r[3]}s diag={r[4][:60]}")

print("\n== run 表总计 ==")
print(" ", con.execute("select count(*) from run").fetchone()[0], "行")

print("\n== feedback 行 ==")
for r in con.execute(
    "select feedback_id, target_kind || ':' || target_id, verdict, author from feedback order by created_at"
).fetchall():
    print(f"  {r[0]}  {r[1]}  {r[2]}  by {r[3]}")

print("\n== sample 表按来源统计 ==")
for r in con.execute(
    "select fidelity, source_type, count(*) from sample group by 1,2 order by 1,2"
).fetchall():
    print(f"  {r[0]:4s} {r[1]:12s} {r[2]}")
