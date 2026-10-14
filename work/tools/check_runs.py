"""列出最近若干 run 行与 feedback 行（只读核对）。"""

from __future__ import annotations

from pathlib import Path

import duckdb

con = duckdb.connect(
    str(Path(r"C:\Users\zmx\Desktop\memsharness\work\store\mems.duckdb")), read_only=True
)

print("== run 表总计 ==", con.execute("select count(*) from run").fetchone()[0], "行")
print("== 最近的 run 行 ==")
for r in con.execute(
    "select run_id, pathway, status, round(wall_seconds,1)"
    " from run order by started_at desc nulls last limit 8"
).fetchall():
    print(f"  {r[0]:44s} {r[1]:12s} {r[2]:10s} {r[3]}s")

print("\n== 按 pathway/status 统计 ==")
for r in con.execute(
    "select pathway, status, count(*) from run group by 1,2 order by 1,2"
).fetchall():
    print(f"  {r[0]:14s} {r[1]:10s} {r[2]}")

print("\n== feedback ==", con.execute("select count(*) from feedback").fetchone()[0], "行")
print("== sample ==", con.execute("select count(*) from sample").fetchone()[0], "行")
print("== validation ==", con.execute("select count(*) from validation").fetchone()[0], "行")
