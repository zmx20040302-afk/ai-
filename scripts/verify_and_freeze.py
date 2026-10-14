# -*- coding: utf-8 -*-
"""A8「验证与冻结」门禁的**命令行入口**（fail-closed）。

用法：
    # 单个冻结件（按 id，默认在 <repo>/work/runs 下递归找 freezes/freeze_<id>）
    python scripts/verify_and_freeze.py --freeze-id phase1-executor-20260915-06

    # 直接给目录
    python scripts/verify_and_freeze.py --target-dir work/runs/.../freezes/freeze_xxx

    # 批量（常用于"哪些冻结件还站得住"）
    python scripts/verify_and_freeze.py --freeze-id a --freeze-id b --out verdicts.json

退出码（给自动化用）：
    0 = 全部 passed 且 release_allowed
    2 = 至少一个 failed
    3 = 没有 failed 但有 inconclusive（无法判定 ⇒ **不得放行**）
    4 = 用法/找不到目标
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.freeze_gate import render_md, run_gate  # noqa: E402

DEFAULT_ROOT = REPO / "work" / "runs"


def find_freeze(root: Path, freeze_id: str) -> Path | None:
    """在 root 下递归找 `freezes/freeze_<id>`（也接受直接是冻结目录本身）。"""
    direct = Path(freeze_id)
    if (direct / "freeze_manifest.json").is_file():
        return direct
    want = "freeze_%s" % freeze_id
    for p in root.rglob(want):
        if p.is_dir():
            return p
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A8 验证与冻结门禁（fail-closed）")
    ap.add_argument("--freeze-id", action="append", default=[],
                    help="冻结件 id（可重复）；在 --freezes-root 下递归查找 freeze_<id>")
    ap.add_argument("--target-dir", action="append", default=[],
                    help="直接指定冻结目录（可重复）")
    ap.add_argument("--freezes-root", default=str(DEFAULT_ROOT))
    ap.add_argument("--out", default=None, help="判定 JSON 输出路径")
    ap.add_argument("--md", default=None, help="人类可读报告输出路径")
    args = ap.parse_args(argv)

    targets: list[Path] = [Path(p) for p in args.target_dir]
    root = Path(args.freezes_root)
    for fid in args.freeze_id:
        p = find_freeze(root, fid)
        if p is None:
            print("找不到冻结件 %r（在 %s 下找 freeze_%s）" % (fid, root, fid), file=sys.stderr)
            return 4
        targets.append(p)
    if not targets:
        ap.print_help()
        return 4

    verdicts = []
    md_all = []
    for t in targets:
        if not t.is_dir():
            print("目标不是目录：%s" % t, file=sys.stderr)
            return 4
        v = run_gate(t)
        verdicts.append(v)
        md_all.append(render_md(v))
        flag = {True: "PASS", False: "FAIL", None: "INCONCLUSIVE"}[
            True if v["verdict"] == "passed" else (False if v["verdict"] == "failed" else None)]
        print("[%s] %-42s verdict=%s release_allowed=%s n_checks=%d"
              % (flag, t.name, v["verdict"], v["release_allowed"], v["n_checks"]))
        for c in v["checks"]:
            if c["passed"] is not True:
                print("        - %-28s passed=%-5s %s"
                      % (c["name"], c["passed"], (c["reason"] or "")[:80]))

    doc = {"kind": "verification_verdict_set", "n_targets": len(targets),
           "verdicts": verdicts,
           "summary": {
               "n_passed": sum(1 for v in verdicts if v["verdict"] == "passed"),
               "n_failed": sum(1 for v in verdicts if v["verdict"] == "failed"),
               "n_inconclusive": sum(1 for v in verdicts if v["verdict"] == "inconclusive"),
               "all_release_allowed": all(v["release_allowed"] for v in verdicts),
           }}
    if args.out:
        Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str),
                                  encoding="utf-8")
        print("json:", args.out)
    if args.md:
        Path(args.md).write_text("\n\n---\n\n".join(md_all), encoding="utf-8")
        print("md  :", args.md)

    s = doc["summary"]
    if s["n_failed"]:
        return 2
    if s["n_inconclusive"]:
        return 3
    return 0 if s["all_release_allowed"] else 3


if __name__ == "__main__":
    sys.exit(main())
