"""读取 COMSOL 导出的扫描结果（CSV / XLSX），先做结构勘察再下结论。

用法：python work\\tools\\read_sweep_results.py
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

D = Path(r"C:\Users\zmx\Desktop\换能器")
CSV = D / "扫面x&N1，间隔阵列扫描.csv"
XLSX = D / "扫描x&N1，间隔扫描.xlsx"


def read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk", "cp936", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def survey_csv(path: Path) -> None:
    print("=" * 90)
    print(f"CSV：{path.name}  （{path.stat().st_size/1024:.1f} KB）")
    text, enc = read_text(path)
    print(f"编码判定：{enc}　总行数（含表头）：{text.count(chr(10)) + 1}")
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    print(f"列数：{len(header)}")
    print(f"表头：{header}")
    body = rows[1:]
    print(f"数据行数：{len(body)}")
    print("\n前 8 行：")
    for row in body[:8]:
        print("  " + " | ".join(str(v) for v in row[:14]))
    print("\n后 3 行：")
    for row in body[-3:]:
        print("  " + " | ".join(str(v) for v in row[:14]))

    # 每列的唯一值数与样例（判断哪些是扫描参数、哪些是目标量）
    print("\n逐列概况（唯一值数 / 首尾样例）：")
    for j, name in enumerate(header[:16]):
        values = [r[j] for r in body if j < len(r)]
        uniq = []
        for v in values:
            if v not in uniq:
                uniq.append(v)
        try:
            nums = [float(v) for v in values if v not in ("", "NaN")]
            num_info = f"数值 {min(nums):.6g} … {max(nums):.6g}" if nums else "非数值"
        except ValueError:
            num_info = "含非数值"
        sample = uniq[:4]
        print(f"  [{j:2d}] {name[:36]:38s} 唯一 {len(uniq):4d}  {num_info}  样例={sample}")


def survey_xlsx(path: Path) -> None:
    print("\n" + "=" * 90)
    print(f"XLSX：{path.name}  （{path.stat().st_size/1024:.1f} KB）")
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        print(f"内部条目：{[n for n in names if 'sheet' in n or 'workbook' in n][:8]}")
        # 共享字符串
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
        sheets = sorted(n for n in names if n.startswith("xl/worksheets/sheet"))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for sheet in sheets:
            root = ET.fromstring(zf.read(sheet))
            rows = root.findall(".//m:row", ns)
            print(f"\n--- {sheet}：{len(rows)} 行 ---")
            for row in rows[:8]:
                cells = []
                for c in row.findall("m:c", ns):
                    v = c.find("m:v", ns)
                    val = v.text if v is not None else ""
                    if c.get("t") == "s" and val != "":
                        val = shared[int(val)]
                    cells.append(val)
                print("  " + " | ".join(str(x) for x in cells[:14]))


if __name__ == "__main__":
    survey_csv(CSV)
    survey_xlsx(XLSX)
