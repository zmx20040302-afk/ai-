"""Codex 决策回复 §9 第 1 步：冻结并哈希现有输入，形成可复核的冻结记录。

哈希对象：决策回复文件、Model M-file、导出表（CSV/XLSX）、相关 .mph。
对被 GUI 打开（存在 .lock）的 .mph **不取哈希**，只记 size/mtime 并注明原因（避免记录到未保存状态）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

WS = Path(r"C:\Users\zmx\Desktop\memsharness")
DESK = Path(r"C:\Users\zmx\Desktop")
TRANS = DESK / "换能器"
ATTACH = Path(
    r"C:\Users\zmx\.dsh\attachments\v1\files\d8"
    r"\d8ac8899bedae67dca396fcb535e4c6979b242efe317e8b68821d4a5209eff5a"
    r"\TO_DEEPSEEK_HARNESS_决策回复.md"
)
OUT_DIR = WS / "work" / "reports" / "analysis_decision"


def sha256(path: Path, chunk: int = 1 << 22) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ① 决策回复入仓（留档）
    reply_dst = WS / "docs" / "TO_CODEX_decision_reply.md"
    if ATTACH.is_file() and not reply_dst.exists():
        shutil.copy2(ATTACH, reply_dst)

    candidates = [
        ("决策回复（Codex）", reply_dst),
        ("Model M-file（yizu，扫描所用参数定义）", TRANS / "b_GE_task3_2newyizu.m"),
        ("Model M-file（小模型/桌面）", DESK / "b_GE_task3_2new.m"),
        ("导出表 CSV（旧扫描 490 行）", TRANS / "扫面x&N1，间隔阵列扫描.csv"),
        ("导出表 XLSX（同表）", TRANS / "扫描x&N1，间隔扫描.xlsx"),
        ("目标模型 .mph（98.9 MB，未锁）", DESK / "b_GE_task3_2-new.mph"),
        ("扫描源模型 .mph（4.15 GB，yizu）", DESK / "b_GE_task3_2-newyizu.mph"),
        ("GUI 当前打开的 .mph（带锁，跳过哈希）", DESK / "b_GE_task3_2new.mph"),
        ("T1 电气审计报告", WS / "work" / "reports" / "modelio" / "T1-electrode-wiring-audit.md"),
        ("新网格几何预判 JSON", WS / "work" / "reports" / "modelio" / "new-grid-geometry-precheck.json"),
    ]

    records = []
    for label, path in candidates:
        item = {"label": label, "path": str(path), "exists": path.is_file()}
        if not item["exists"]:
            item["note"] = "文件不存在"
            records.append(item)
            continue
        stat = path.stat()
        item.update(bytes=stat.st_size, mtime=stat.st_mtime, lock_present=(path.parent / (path.name + ".lock")).exists())
        if item["lock_present"]:
            item["sha256"] = None
            item["note"] = "被 COMSOL GUI 打开（.lock 存在）→ 不取哈希，避免记录到未保存状态"
        else:
            print(f"hashing {path.name} ({stat.st_size/1e6:.1f} MB) …", flush=True)
            item["sha256"] = sha256(path)
            item["note"] = None
        records.append(item)
        print(f"  {label}: {item.get('sha256') or '(skip)'}", flush=True)

    (OUT_DIR / "freeze_inputs.json").write_text(
        json.dumps({"frozen_at": "2026-09-13", "purpose": "Codex 决策回复 §9 第 1 步",
                    "items": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n冻结记录：{OUT_DIR / 'freeze_inputs.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
