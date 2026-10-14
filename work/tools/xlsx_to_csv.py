"""把 .xlsx 转成 CSV —— **只用标准库**（zipfile + xml.etree），不依赖 openpyxl。

背景：本机 venv 未装 openpyxl（且 `pyproject.toml` 也没声明它），而 COMSOL 导出的表格
常是 `.xlsx`。2026-09-13 实测清华镜像 SSL 断连装不上，因此不把工作卡在网络上：
xlsx 本质是 zip + XML，直接解析即可。

用法：
    python work\\tools\\xlsx_to_csv.py <in.xlsx> <out.csv>
"""

from __future__ import annotations

import csv
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CELL_RX = re.compile(r"^([A-Z]+)(\d+)$")


def col_index(ref: str) -> int:
    """'A1' -> 0；'AB12' -> 27。"""
    letters = CELL_RX.match(ref).group(1)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out: list[str] = []
    for si in root.findall("m:si", NS):
        # 一个 si 内可能有多个 <t>（富文本分段），全部拼接
        out.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    return out


def sheet_names(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """返回 [(sheet 名, zip 内路径)]，按 workbook 顺序；失败则按文件名排序兜底。"""
    try:
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rid2target = {}
        for rel in rels:
            rid2target[rel.get("Id")] = rel.get("Target")
        rns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        out = []
        for sh in wb.iter(f"{{{NS['m']}}}sheet"):
            name = sh.get("name") or "sheet"
            target = rid2target.get(sh.get(rns), "")
            path = target.lstrip("/")
            if not path.startswith("xl/"):
                path = "xl/" + path
            out.append((name, path))
        if out:
            return out
    except Exception:
        pass
    return [(Path(p).stem, p) for p in sorted(zf.namelist()) if p.startswith("xl/worksheets/sheet")]


def read_sheet(zf: zipfile.ZipFile, path: str, sst: list[str]) -> list[list[str]]:
    root = ET.fromstring(zf.read(path))
    rows: list[list[str]] = []
    for row in root.iter(f"{{{NS['m']}}}row"):
        cells: dict[int, str] = {}
        for c in row.findall("m:c", NS):
            ref = c.get("r")
            if not ref:
                continue
            idx = col_index(ref)
            ctype = c.get("t")
            if ctype == "s":
                v = c.find("m:v", NS)
                val = sst[int(v.text)] if v is not None and v.text is not None else ""
            elif ctype == "inlineStr":
                is_el = c.find("m:is", NS)
                val = "".join(t.text or "" for t in is_el.iter(f"{{{NS['m']}}}t")) if is_el is not None else ""
            else:
                v = c.find("m:v", NS)
                val = v.text if v is not None and v.text is not None else ""
            cells[idx] = val
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
    return rows


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    sel = sys.argv[3] if len(sys.argv) > 3 else None
    with zipfile.ZipFile(src) as zf:
        sst = shared_strings(zf)
        sheets = sheet_names(zf)
        print(f"源：{src}（{src.stat().st_size} B）")
        print(f"共享字符串 {len(sst)} 条；工作表：{[n for n, _ in sheets]}")
        if sel is None:
            # 未指定：逐表预览，便于人工判断哪张是数据
            for i, (nm, pth) in enumerate(sheets, start=1):
                rr = read_sheet(zf, pth, sst)
                print(f"\n  [{i}] {nm!r} → {len(rr)} 行")
                for r in rr[:4]:
                    print(f"      {r[:8]}")
            print("\n提示：用第 3 个参数指定工作表（名称或 1 起的序号）后重跑。")
            return 0
        if sel.isdigit():
            name, path = sheets[int(sel) - 1]
        else:
            name, path = next((s for s in sheets if s[0] == sel), sheets[0])
        rows = read_sheet(zf, path, sst)
    print(f"选取工作表：{name!r} → {len(rows)} 行；表头 {rows[0] if rows else '(空)'}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerows(rows)
    print(f"写出：{dst}（{dst.stat().st_size} B）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
