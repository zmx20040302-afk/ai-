"""模型 M-file 差异比对（全量覆盖版 + Codex §9 要求的溯源字段）。

用途：回答"我改了哪些参数/设置"——把 GUI 新导出的 `.m` 与旧 `.m` 逐项比对。

## 为什么是"全量覆盖"而不是按类别白名单

第一版按类别写白名单正则，结果**漏掉了 `setIndex(` 这一类赋值**，而扫描区间恰好写成
`model.study('std1').feature('param').setIndex('plistarr', 'range(0.4,0.05,0.8)', 0);`
——于是"用户改了扫描区间"这件事完全没被读出来。教训：白名单正则一定会漏，
改为**对每一行 `model.` 开头的语句做通用归一化**，再分类。

## 铁律（AGENTS.md §4）

**同名属性取文件中最后一次赋值**。COMSOL 导出脚本会在文件末尾再覆盖一次
（实测 `N_w_te2` 前部写 5、L2389 覆盖为 9），只看文件头会读到失效的历史值。

## Codex §9 要求的字段（v2 起提供）

    unique_effective_properties   唯一生效属性数（末次赋值后）
    assignment_statement_count    赋值语句数（含被覆盖的）
    overwritten_assignments       被覆盖的记录：每条的历史值与末次值
    final_effective_value         末次生效值（含行号）
    source_line                   该生效值所在行号

并且 diff 结论只表述为"**在当前提取器覆盖的导出语句范围内**未发现差异"，
不扩大为两份二进制 `.mph` 完全等价。

用法：
    python work\\tools\\diff_model_m.py --ref <旧>.m --cmp <新>.m [--cmp <另一个>.m] [--out <json>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# 通用模式：路径用非贪婪，值用贪婪到行尾最后一个 `);`
SET_RX = re.compile(r"^model\.(.+?)\.set\('([^']+)',\s*(.*)\);\s*$")
SETIDX_RX = re.compile(r"^model\.(.+?)\.setIndex\('([^']+)',\s*(.*?),\s*(\d+)\);\s*$")
ACTIVE_RX = re.compile(r"^model\.(.+?)\.active\((\w+)\);\s*$")
NAMED_RX = re.compile(r"^model\.(.+?)\.selection\.named\('([^']+)'\);\s*$")
ASCII = re.compile(rb"[ -~]{4,}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def classify(path: str) -> str:
    for token, cat in (
        ("param", "param"), ("batch", "batch"), ("study", "study"), ("selection", "selection"),
        ("physics", "physics"), ("variable", "variable"), ("cpl", "intop"), ("geom", "geometry"),
        ("mesh", "mesh"), ("result", "result"), ("sol(", "solver"), ("probe", "probe"),
        ("material", "material"), ("func", "function"), ("nonlocal", "coupling"),
    ):
        if token in path:
            return cat
    return "other"


def extract(path: Path) -> tuple[dict[str, dict[str, dict]], dict]:
    """返回 ({类别: {key: {"value","line"}}}, 溯源元数据)；**同名取最后一次赋值**。"""
    items: dict[str, dict[str, dict]] = {}
    overwritten: dict[str, list[dict]] = {}
    statements = 0

    def put(cat: str, key: str, value, line: int) -> None:
        bucket = items.setdefault(cat, {})
        prev = bucket.get(key)
        if prev is not None:                      # 记录被覆盖的历史值（append-only）
            overwritten.setdefault(f"{cat}::{key}", []).append(prev)
        bucket[key] = {"value": value, "line": line}

    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    for i, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line.startswith("model."):
            continue
        statements += 1

        m = SETIDX_RX.match(line)
        if m:
            path_obj, prop, value, idx = m.groups()
            cat = classify(path_obj)
            if cat == "param":
                cat = "param_other"
            put(cat, f"{path_obj}::{prop}[{idx}]", value, i)
            continue

        m = SET_RX.match(line)
        if m:
            path_obj, prop, value = m.groups()
            put(classify(path_obj), f"{path_obj}::{prop}", value, i)
            continue

        m = ACTIVE_RX.match(line)
        if m:
            put("active", m.group(1), m.group(2), i)
            continue

        m = NAMED_RX.match(line)
        if m:
            put("selection_named", m.group(1), m.group(2), i)
            continue

        # 其余 model.* 调用（create/duplicate/remove/move/run/rename/descr/…）按整行集合比对
        put("call", line, "", i)

    meta = {
        "source_file": str(path.resolve()),
        "sha256": sha256(path),
        "assignment_statement_count": statements,
        "unique_effective_properties": sum(len(v) for v in items.values()),
        "overwritten_assignment_count": len(overwritten),
        "overwritten_assignments": overwritten,
    }
    return items, meta


def diff(ref: dict, cmp: dict) -> dict:
    out: dict[str, dict] = {}
    for cat in sorted(set(ref) | set(cmp)):
        a, b = ref.get(cat, {}), cmp.get(cat, {})
        changed, only_ref, only_cmp = {}, {}, {}
        for k in sorted(set(a) | set(b)):
            if k in a and k in b:
                if a[k]["value"] != b[k]["value"]:
                    changed[k] = {
                        "ref": a[k], "cmp": b[k],
                        "final_effective_value_ref": a[k]["value"],
                        "final_effective_value_cmp": b[k]["value"],
                        "source_line_ref": a[k]["line"], "source_line_cmp": b[k]["line"],
                    }
            elif k in a:
                only_ref[k] = a[k]
            else:
                only_cmp[k] = b[k]
        if changed or only_ref or only_cmp:
            out[cat] = {"changed": changed, "only_in_ref": only_ref, "only_in_cmp": only_cmp}
    return out


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="模型 M-file 差异比对（全量覆盖，同名取最后一次赋值）")
    ap.add_argument("--ref", required=True)
    ap.add_argument("--cmp", required=True, action="append")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-call", type=int, default=40)
    args = ap.parse_args(argv)

    ref_path = Path(args.ref)
    ref, ref_meta = extract(ref_path)
    print(f"REF {ref_path.name}")
    print(f"  sha256={ref_meta['sha256'][:16]}…｜赋值语句 {ref_meta['assignment_statement_count']} 条"
          f"｜唯一生效属性 {ref_meta['unique_effective_properties']} 个"
          f"｜被覆盖 {ref_meta['overwritten_assignment_count']} 个")
    if ref_meta["overwritten_assignments"]:
        real = {k: v for k, v in ref_meta["overwritten_assignments"].items() if not k.startswith("call::")}
        calls = len(ref_meta["overwritten_assignments"]) - len(real)
        print(f"  被覆盖项：属性类 {len(real)} 个（末次生效，链式展示历史→生效）"
              f"｜重复调用行 {calls} 个（key 即整行，无需链式）")
        for k, hist in sorted(real.items())[:10]:
            cat, key = k.split("::", 1)
            final = ref.get(cat, {}).get(key)
            parts = [f"L{h['line']}:{str(h['value'])[:20]}" for h in hist]
            if final:
                parts.append(f"L{final['line']}:{str(final['value'])[:20]}（末次生效）")
            print(f"    {k}: " + " → ".join(parts))
        if len(real) > 10:
            print(f"    …（其余 {len(real) - 10} 项见 JSON）")

    payload = {"ref": str(ref_path), "ref_meta": ref_meta, "comparisons": {}}
    for cmp_arg in args.cmp:
        cmp_path = Path(cmp_arg)
        cmp, cmp_meta = extract(cmp_path)
        d = diff(ref, cmp)
        payload["comparisons"][str(cmp_path)] = {"cmp_meta": cmp_meta, "diff": d}
        print(f"\n{'=' * 70}\nCMP {cmp_path.name}")
        print(f"  sha256={cmp_meta['sha256'][:16]}…｜赋值语句 {cmp_meta['assignment_statement_count']} 条"
              f"｜唯一生效属性 {cmp_meta['unique_effective_properties']} 个"
              f"｜被覆盖 {cmp_meta['overwritten_assignment_count']} 个")
        if not d:
            print("  >>> 在当前提取器覆盖的导出语句范围内**未发现差异** <<<")
            continue
        for cat in sorted(d):
            blk = d[cat]
            print(f"\n  [{cat}] 改值 {len(blk['changed'])}｜仅REF {len(blk['only_in_ref'])}"
                  f"｜仅CMP {len(blk['only_in_cmp'])}")
            for k, v in blk["changed"].items():
                print(f"    ~ {k}")
                print(f"        REF L{v['source_line_ref']}: {v['final_effective_value_ref']}")
                print(f"        CMP L{v['source_line_cmp']}: {v['final_effective_value_cmp']}")
            for k, v in blk["only_in_ref"].items():
                print(f"    - REF 独有 L{v['line']}: {k if cat == 'call' else k + ' = ' + str(v['value'])}")
            shown = 0
            for k, v in blk["only_in_cmp"].items():
                if cat == "call" and shown >= args.max_call:
                    print(f"    + CMP 独有 …（其余 {len(blk['only_in_cmp']) - shown} 条见 JSON）")
                    break
                print(f"    + CMP 独有 L{v['line']}: {k if cat == 'call' else k + ' = ' + str(v['value'])}")
                shown += 1

    payload["scope_note"] = ("'未发现差异'仅指本提取器覆盖的 model.* 导出语句范围；"
                             "不表示两份二进制 .mph 在保存态解/缓存/网格实体/结果数据集上等价")
    if args.out:
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n落档：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
