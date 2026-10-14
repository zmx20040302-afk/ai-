# -*- coding: utf-8 -*-
"""入包前审计：对**将要入包**的 vendored 件做禁串扫描 + LF 检查 + 导入面检查。

与构建器里的 FORBIDDEN 保持一致（此处独立实现一遍，便于在打包前就发现）。
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
DEV = R / "work/runs/ai11-m4-20261013/tasks_dev"
PKG_SRC = R / "work/runs/ai11-m4-20261013/pkg_src"

FILES = {
    "tasks/label_validity.py": DEV / "label_validity/label_validity.py",
    "tasks/m1_m2_m3.py": DEV / "m1_m2_m3/m1_m2_m3.py",
    "tasks/t1_t2.py": DEV / "t1_t2/tasks/t1_t2.py",
    "tasks/t1_t2_spacing.py": DEV / "t1_t2/tasks/t1_t2_spacing.py",
    "tasks/t5.py": DEV / "t5/tasks/t5.py",
    "tasks/t7_scheduling.py": DEV / "t7/tasks/t7_scheduling.py",
    "check_tasks.py": DEV / "_harness/check_tasks.py",
    "run_tasks.py": DEV / "_harness/run_tasks.py",
    "verify_package.py": DEV / "_harness/verify_package.py",
    "REPRODUCIBILITY.md": PKG_SRC / "REPRODUCIBILITY.md",
    "requirements.txt": PKG_SRC / "requirements.txt",
}
FORBIDDEN = [("内路径", re.compile(r"work[/\\]runs")),
             ("仓库名", re.compile(r"memsharness")),
             ("用户名", re.compile(r"\bzmx\b|zhangmx", re.I)),
             ("主机名", re.compile(r"node0\d|10\.180\.7\.46|ubuntu-10-180-7-46")),
             ("绝对路径", re.compile(r"[A-Za-z]:[\\/]")),
             ("COMSOL 安装", re.compile(r"COMSOL64|comsolbatch|comsolcompile")),
             ("桌面路径", re.compile(r"Desktop|桌面")),
             ("unix home", re.compile(r"/home/|/Users/")),
             ("邮箱", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
             ("ssh 痕迹", re.compile(r"\.ssh|id_rsa|codex_ubuntu")),
             ("模型文件", re.compile(r"[A-Za-z0-9_\-]+\.mph\b"))]
ALLOW_IMPORT = {"__future__", "argparse", "ast", "collections", "collections.abc", "csv", "hashlib",
                "importlib", "importlib.util", "itertools", "json", "math", "os", "pathlib",
                "random", "re", "statistics", "subprocess", "sys", "time", "typing",
                "numpy", "scipy", "sklearn", "bench", "check_results", "check_solution_identity",
                "check_tasks", "verify_package", "t1_t2"}

bad_total = 0
print("%-28s %8s %6s %6s  %s" % ("包内路径", "字节", "CRLF", "问题", "备注"))
for rel, src in sorted(FILES.items()):
    if not src.is_file():
        print("%-28s %8s %6s %6s  %s" % (rel, "-", "-", "缺", "尚未交付"))
        continue
    b = src.read_bytes()
    txt = b.decode("utf-8")
    probs = []
    notes = []
    if b"\r\n" in b:
        probs.append("CRLF")
    hits = [(n, rx.findall(txt)[:2]) for n, rx in FORBIDDEN if rx.search(txt)]
    if hits:
        probs.append("禁串:" + ",".join(n for n, _ in hits))
    if rel.endswith(".py"):
        try:
            tree = ast.parse(txt)
            mods = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module)
            unknown = sorted(m for m in mods if m.split(".")[0] not in
                             {x.split(".")[0] for x in ALLOW_IMPORT})
            if unknown:
                probs.append("导入:" + ",".join(unknown))
            notes.append("import %d" % len(mods))
        except SyntaxError as e:
            probs.append("语法错误:%s" % e)
    bad_total += len(probs)
    print("%-28s %8d %6s %6s  %s" % (rel, len(b), "有" if b"\r\n" in b else "无",
                                     len(probs), "；".join(probs) if probs else "、".join(notes) or "OK"))
print("\n问题总数：%d %s" % (bad_total, "⇒ 可以入包" if bad_total == 0 else "⇒ 先修"))
raise SystemExit(0 if bad_total == 0 else 1)
