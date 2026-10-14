# -*- coding: utf-8 -*-
"""M4 前置侦察：两个待打包源码 + 4 个数据文件里的**身份/路径**风险串（只读）。"""
from __future__ import annotations

import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(r"C:\Users\zmx\Desktop\memsharness")
SRC = {
    "runner": REPO / "work/runs/eda64-20261010/n2_baselines/run_n2_baselines.py",
    "fitter": REPO / "work/runs/multichannel-surrogate-20260929/fit_multichannel_surrogate.py",
}
DATA = {
    "v3": REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv",
    "ac": REPO / "work/runs/first-peak-20260929/multichannel_labels.csv",
    "v2": REPO / "work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv",
    "splits": REPO / "work/runs/grouped-split-20261009/grouped_split_assignments.csv",
}
PAT = {
    "user_zmx": re.compile(r"\bzmx\b", re.I),
    "user_zhangmx": re.compile(r"zhangmx", re.I),
    "drive_path": re.compile(r"[A-Za-z]:\\\\|[A-Za-z]:\\"),
    "unix_home": re.compile(r"/home/|/Users/"),
    "desktop": re.compile(r"Desktop|桌面"),
    "host": re.compile(r"\bnode0\d\b|ubuntu-10-180-7-46"),
    "repo_name": re.compile(r"memsharness"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "ssh_key": re.compile(r"\.ssh|id_rsa|codex_ubuntu"),
    "work_runs": re.compile(r"work[/\\]runs"),
    "mph": re.compile(r"\.mph\b"),
    "sqlite_abs": re.compile(r"\\\\\?\\"),
}
for label, p in list(SRC.items()) + list(DATA.items()):
    t = p.read_text(encoding="utf-8-sig", errors="replace")
    print("== %-7s %-58s %9d B" % (label, p.name, p.stat().st_size))
    for name, rx in PAT.items():
        hits = rx.findall(t)
        if hits:
            u = sorted({h if isinstance(h, str) else str(h) for h in hits})[:4]
            print("     %-14s %4d 次  例：%s" % (name, len(hits), u))
