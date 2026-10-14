# -*- coding: utf-8 -*-
"""把 §89 小节按 append-only 追加到记录索引（不覆盖任何既有内容）。"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
IDX = REPO / "docs/INDEX-records-and-rulings.md"
SEC = REPO / "work/runs/te2_8_pod_fields_20261005/x_family/_s89_section.md"

txt = IDX.read_text(encoding="utf-8")
sec = SEC.read_text(encoding="utf-8")
if "## §89" in txt:
    print("[SKIP] 索引里已存在 §89，未重复追加")
    sys.exit(0)
before = txt.count("## §")
IDX.write_text(txt.rstrip("\n") + "\n" + sec, encoding="utf-8")
after = IDX.read_text(encoding="utf-8").count("## §")
print("索引小节数 %d -> %d ｜ 追加 %d 字符 ｜ 文件 %d 字符"
      % (before, after, len(sec), len(IDX.read_text(encoding='utf-8'))))
print("尾部 3 行：")
for ln in IDX.read_text(encoding="utf-8").rstrip("\n").splitlines()[-3:]:
    print("   ", ln[:110])
