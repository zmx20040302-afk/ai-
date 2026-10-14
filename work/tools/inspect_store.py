"""只读核对溯源库：列出表与行数，并按 source_type 统计（红线：来源永不混同）。"""

import sys
from pathlib import Path

import duckdb

db = Path(sys.argv[1] if len(sys.argv) > 1 else "work/store/mems.duckdb")
con = duckdb.connect(str(db), read_only=True)

tabs = [
    r[0]
    for r in con.execute(
        "select table_name from information_schema.tables order by table_name"
    ).fetchall()
]
print(f"db: {db}  ({db.stat().st_size/1e6:.1f} MB)")
print(f"tables ({len(tabs)}): {tabs}")
for t in tabs:
    n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
    print(f"  {t:26s} {n:6d} rows")

for t in tabs:
    cols = [r[0] for r in con.execute(f'describe "{t}"').fetchall()]
    if "source_type" in cols:
        print(f"\n-- {t}.source_type --")
        for st, n in con.execute(
            f'select source_type, count(*) from "{t}" group by 1 order by 2 desc'
        ).fetchall():
            print(f"  {st:20s} {n:6d}")
