"""G3-2 第三方独立复算（只读；不重跑任何求解）。

目的：套件自己声明「前序 child 未被改写」（T9c）强度不足；本脚本**独立**读取两个 namespace 内
全部文件，逐项与确定性 manifest 中记录的 bytes/SHA256 比对，并在读前/读后各算一次以证明
读取期间无人改动这些文件。

判定：
  run1 manifest vs run1 current  → 若全等，说明 run1 的文件自验收以来未被改动
  run2 manifest vs run2 current  → 同上
  run1 manifest vs run2 manifest → 若全等，说明 run2 的存在/写入没有改写 run1 的内容（即 before==after）
  两次 sweep 相等                → 证明本脚本读取期间无第三方写入

用法：python work/tools/g3_2_independent_recheck.py
退出码：0 = INDEPENDENTLY_RECONFIRMED；2 = MISMATCH（停下报告，不修）
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

RUNS = pathlib.Path(r"C:\Users\zmx\Desktop\memsharness\work\runs")
ACC = RUNS / "lt2-acceptance-20260914-1810-credit"
OUT = ACC / "g3_2_independent_recheck.json"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sweep(ns: str) -> dict:
    root = RUNS / ns
    out = {}
    for f in sorted(root.rglob("*")):
        if f.is_file():
            out[f.relative_to(root).as_posix()] = [f.stat().st_size, sha(f)]
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    d = json.loads((ACC / "acceptance_summary.json").read_text(encoding="utf-8"))
    ns = [r["namespace"] for r in d["runs"]]
    man = [d["deterministic_manifest_run1"], d["deterministic_manifest_run2"]]

    read_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    first = [sweep(ns[0]), sweep(ns[1])]
    second = [sweep(ns[0]), sweep(ns[1])]
    read_again_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    rows = []
    for i in (0, 1):
        cur = first[i]
        m = man[i]
        diff = sorted(k for k in m if k not in cur
                      or cur[k][1] != m[k]["sha256"] or cur[k][0] != m[k]["bytes"])
        rows.append({"namespace": ns[i], "manifest_entries": len(m),
                     "current_files": len(cur), "diff": diff,
                     "all_equal": not diff})

    keys = set(man[0]) | set(man[1])
    cross_diff = sorted(k for k in keys
                        if man[0].get(k, {}).get("sha256") != man[1].get(k, {}).get("sha256"))

    tl = [{k: v[1] for k, v in s.items() if k.endswith("resource_timeline.jsonl")}
          for s in first]

    stable = (first[0] == second[0]) and (first[1] == second[1])

    # 全量集合（含按设计本就不同的根）的差异。**字段名必须自解释**：否则未来读者会把
    # 「全量含设计差异 ⇒ false」误读成「G3-2 没过」。判定只看确定性集合。
    full_keys = set(first[0]) | set(first[1])
    full_diff = sorted(k for k in full_keys
                       if first[0].get(k, [None, None])[1] != first[1].get(k, [None, None])[1])
    by_design_roots = {}
    excl = (d.get("exclusions_run1") or []) + (d.get("exclusions_run2") or [])
    for k in full_diff:
        root = k.split("/", 1)[0]
        # 先按**精确路径**匹配（覆盖 namespace 根级文件如 test_summary.json），
        # 再退化为按根前缀匹配；两者都取 allowlist_rule，避免出现 null 误导读者。
        by_design_roots[root] = (
            next((e.get("allowlist_rule") for e in excl if e.get("path") == k), None)
            or next((e.get("allowlist_rule") for e in excl
                     if (e.get("path") or "").startswith(root + "/")), None))

    deterministic_set_equal = (not cross_diff) and all(r["all_equal"] for r in rows)
    ok = deterministic_set_equal and stable

    doc = {
        "purpose": "G3-2 第三方独立复算（前序 child 未被改写）",
        "read_at": read_at, "read_again_at": read_again_at,
        "namespaces": ns,
        "per_namespace": rows,
        "run1_manifest_vs_run2_manifest_diff": cross_diff,
        "resource_timeline_counts": [len(tl[0]), len(tl[1])],
        "resource_timeline_sha256": tl,
        "second_sweep_stable": stable,
        # ---- 判定字段（自解释命名；判定逻辑未改）----
        "full_set_including_by_design_differences_equal": not full_diff,
        "deterministic_set_equal": deterministic_set_equal,
        "by_design_differing_roots": by_design_roots,
        "g3_2_verdict": ("INDEPENDENTLY_RECONFIRMED" if ok else "MISMATCH_STOP"),
        "field_note": ("full_set_including_by_design_differences_equal=false 表示全量集合含"
                       "按设计本就不同的根（见 by_design_differing_roots，已在 allowlist 内），"
                       "**不是**判定失败；G3-2 的判据是 deterministic_set_equal。"),
        "note": "只读；未重跑任何求解；两次 sweep 相等用于证明读取期间无第三方写入",
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: doc[k] for k in
                      ("read_at", "read_again_at", "per_namespace",
                       "run1_manifest_vs_run2_manifest_diff",
                       "resource_timeline_counts", "second_sweep_stable",
                       "full_set_including_by_design_differences_equal",
                       "deterministic_set_equal", "by_design_differing_roots",
                       "g3_2_verdict")}, ensure_ascii=False), flush=True)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
