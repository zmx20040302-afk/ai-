# -*- coding: utf-8 -*-
"""按**远端哈希清单**校验本地镜像（通用版：`sha256<TAB>size<TAB>path` 或 `sha256  path`）。

与旧批次专用 `verify_mirror.py` 的区别：本脚本不写死任何目录名或文件数，
清单与镜像都由命令行给出 ⇒ 可复用于任何批次（x 加密、后续扩频段…）。

用法：
    python -B scripts/verify_mirror_manifest.py \
        --manifest work/runs/x-densify-20260928/batch_meta/output_manifest.tsv \
        --mirror   work/runs/x-densify-20260928/mirror \
        --path-prefix /home/lab/projAI4US/autodesign/exported_results \
        --report   work/runs/x-densify-20260928/mirror_verify.json

退出码：0 = 全部一致；1 = 有缺失/不一致（fail-closed，逐条列出）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_manifest(path: Path) -> dict[str, dict]:
    """支持两种格式：`sha256<TAB>size<TAB>path`（本批）与 `sha256  path`（旧批）。"""
    out: dict[str, dict] = {}
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t") if "\t" in line else line.split(None, 1)
        if len(parts) < 2:
            continue
        digest = parts[0].strip()
        if len(digest) != 64:
            continue
        if len(parts) >= 3 and parts[1].strip().isdigit():
            size, rel = int(parts[1].strip()), parts[2].strip()
        else:
            size, rel = None, parts[1].strip()
        out[rel] = {"sha256": digest, "size": size, "line": i + 1}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按远端哈希清单校验本地镜像（通用）")
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--mirror", required=True, type=Path)
    ap.add_argument("--path-prefix", default="", help="清单里路径的前缀，用于得到镜像内相对路径")
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args(argv)

    entries = parse_manifest(args.manifest)
    if not entries:
        print("[FAIL] 清单解析为空：%s" % args.manifest, file=sys.stderr)
        return 1

    prefix = args.path_prefix.rstrip("/")
    ok, bad, missing = [], [], []
    for rel, meta in sorted(entries.items()):
        r = rel
        if prefix and r.startswith(prefix + "/"):
            r = r[len(prefix) + 1:]
        local = args.mirror / r
        if not local.is_file():
            missing.append({"path": rel, "expected_sha256": meta["sha256"]})
            continue
        got = sha256_file(local)
        if got == meta["sha256"]:
            ok.append(rel)
        else:
            bad.append({"path": rel, "expected_sha256": meta["sha256"], "actual_sha256": got})

    n = len(entries)
    report = {
        "kind": "mirror_verification",
        "manifest": str(args.manifest).replace("\\", "/"),
        "mirror": str(args.mirror).replace("\\", "/"),
        "n_expected": n, "n_match": len(ok), "n_mismatch": len(bad), "n_missing": len(missing),
        "verdict": "passed" if (not bad and not missing) else "failed",
        "mismatch": bad, "missing": missing,
        "semantics": "只比对清单里列出的文件；清单未覆盖的本地文件不计入通过数",
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("清单条目 %d | 一致 %d | 不一致 %d | 缺失 %d | 判定 %s"
          % (n, len(ok), len(bad), len(missing), report["verdict"]))
    for b in bad[:10]:
        print("   MISMATCH %s\n      expect %s\n      actual %s"
              % (b["path"], b["expected_sha256"], b["actual_sha256"]))
    for m in missing[:10]:
        print("   MISSING  %s" % m["path"])
    return 0 if report["verdict"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
