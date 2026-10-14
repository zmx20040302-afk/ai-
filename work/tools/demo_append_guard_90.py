# -*- coding: utf-8 -*-
"""一次性取证：证明 `scripts/append_record_section.py` 的重复守卫修复有效。

场景（§109 登记的真实缺陷）：目标索引里**没有** `## 90.` 标题行，
只有正文/子节里的 `### 90.1`。旧守卫 `if heading in txt` 会**假拒绝**。

本脚本**不碰**真正的 `docs/INDEX-records-and-rulings.md`：
它在临时目录里造一份假索引，把脚本模块的 `REPO`/`IDX` 指向该临时目录再跑 `main()`。
"""
from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/append_record_section.py"

INDEX = (
    "# 假索引\n"
    "\n"
    "### 90.1 一个更深的子节标题（不是 §90 本身）\n"
    "\n"
    "正文里也提到 ## 90. 与 §90.，但**没有任何一行以 `## 90.` 开头**。\n"
)
SECTION = "## 90. 测试节\n\n本节只用于取证。\n"


def main() -> int:
    b = SCRIPT.read_bytes()
    print("脚本 sha256 = %s（%d B）" % (hashlib.sha256(b).hexdigest(), len(b)))

    spec = importlib.util.spec_from_file_location("_guard_demo", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # 旧口径（子串包含）在**逐字节相同**的输入上的判定
    old_hit = "## 90." in INDEX
    print("旧守卫 `'## 90.' in txt` = %s ⇒ %s"
          % (old_hit, "[SKIP] 假拒绝" if old_hit else "允许追加"))

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        (tmp / "docs").mkdir(parents=True)
        idx = tmp / "docs" / "INDEX-records-and-rulings.md"
        # INPLACE-ALLOW: `idx` 是本脚本在**刚建的临时目录**里刚刚创建的文件（上一行 mkdir、本行创建），
        # 盘上不存在任何「改前既有字节」⇒ 没有可备份的对象；L56 的回读读的是本脚本自己刚写的字节。
        # 这不是就地改（`guards_inplace.scan_inplace_writers` 判它是「读在写之后」的自证型误报）。
        idx.write_text(INDEX, encoding="utf-8")
        sec = tmp / "sec.md"
        sec.write_text(SECTION, encoding="utf-8")
        mod.REPO = tmp
        mod.IDX = idx
        sys.argv = ["append_record_section.py", "--section", str(sec),
                    "--heading", "## 90."]
        rc = mod.main()
        after = idx.read_text(encoding="utf-8")
        print("新守卫 main() rc = %d；追加后字符 %d -> %d；含 `## 90. 测试节` = %s"
              % (rc, len(INDEX), len(after), "\n## 90. 测试节" in after))
        baks = sorted((tmp / "work/logs").glob("*.bak"))
        print("备份 = %s（内容 = 追加前全文 = %s）"
              % (baks[0].name if baks else "(无)",
                 baks[0].read_text(encoding="utf-8") == INDEX if baks else False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
