# -*- coding: utf-8 -*-
"""批次隔离门禁：对「按 `batch` 列并排」的数据表跑 fail-closed 检查（**只读**）。

## 为什么需要它

`AGENTS.md` 红线 4/6 与注入稿 §8 要求：

* **不同扫描范围（如 5–35 vs 5–50 MHz）或不同模型变体不得混算、不得合成总分**；
* **删失（峰值卡在扫描端点）或截断（上截止点 = 端点）的组合不得当作正常测量值用于排名**。

这两条此前只在**人写的文档**里，没有可执行守卫。本脚本把它们做成机器判据，
判定语义复用 `memsharness.consistency.evaluate_s3`（任一 False ⇒ failed；
任一 None ⇒ inconclusive 且**不放行**；空检查集 ⇒ inconclusive）—— 不另造一套。

## 退出码（fail-closed）

```text
0 = verdict == passed（全部检查通过，才允许放行）
3 = 有 failed
4 = 无 failed 但有 inconclusive  ⇒ **不等于通过**
2 = 输入不可用（文件不存在 / 无数据行）⇒ 同样不等于通过
```

## 用法

```powershell
python scripts\\check_batch_isolation.py work\\runs\\labels-two-batch\\<ts>\\labels_two_batch.csv
python scripts\\check_batch_isolation.py <表>.csv --decimals 6 --json-out <路径>.json
```

注意：本脚本**只读**输入表，不写任何既有产物；`--json-out` 缺省时只打印。
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.consistency import evaluate_s3  # noqa: E402
from memsharness.sweep_analysis import (  # noqa: E402
    IDENTITY_ROUND_DECIMALS,
    check_batch_isolation,
)

EXIT_PASS, EXIT_INPUT, EXIT_FAIL, EXIT_INCONCLUSIVE = 0, 2, 3, 4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="带批次列的宽表（CSV，UTF-8）")
    ap.add_argument("--batch-key", default="batch")
    ap.add_argument("--range-key", default="freq_range_MHz", help="扫描口径列（可留空表示未声明）")
    ap.add_argument("--decimals", type=int, default=IDENTITY_ROUND_DECIMALS,
                    help="组合身份键的 ulp 归一化小数位（默认 %d）" % IDENTITY_ROUND_DECIMALS)
    ap.add_argument("--json-out", default=None, help="可选：把判定结果另存为 JSON（不覆盖任何既有产物）")
    a = ap.parse_args()

    p = pathlib.Path(a.csv)
    if not p.is_absolute():
        p = REPO / p
    if not p.exists():
        print("[FAIL] 输入不存在：%s" % p)
        return EXIT_INPUT
    with p.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("[FAIL] 输入为 0 行 ⇒ 没有任何批次可判定（空集判失败）")
        return EXIT_INPUT

    checks = check_batch_isolation(rows, batch_key=a.batch_key, range_key=a.range_key,
                                   decimals=a.decimals)
    verdict = evaluate_s3(checks)

    print("== 批次隔离门禁 ==")
    print("  表：%s（%d 行，%d 列）" % (p.name, len(rows), len(rows[0])))
    print("  批次：%s" % sorted({str(r.get(a.batch_key, "")).strip() for r in rows}))
    print("  组合身份键 ulp 归一化小数位：%d" % a.decimals)
    print()
    for c in verdict["checks"]:
        tag = {True: "PASS", False: "FAIL", None: "????"}[c["passed"]]
        print("  [%s] %s" % (tag, c["name"]))
        if c["metric"] is not None:
            print("          metric=%s threshold=%s" % (c["metric"], c["threshold"]))
        if c["reason"]:
            print("          %s" % c["reason"])
    print()
    print("verdict = %s ｜ release_allowed = %s" % (verdict["verdict"], verdict["release_allowed"]))
    print("理由：%s" % verdict["reason"])
    if verdict["verdict"] != "passed":
        print("⚠️ 这不是通过：inconclusive 表示**判不了**（数据/列不足），不得复述成通过。")

    if a.json_out:
        outp = pathlib.Path(a.json_out)
        if not outp.is_absolute():
            outp = REPO / outp
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(
            {"kind": "batch_isolation_gate", "input_csv": str(p.relative_to(REPO))
             if p.is_relative_to(REPO) else str(p),
             "n_rows": len(rows), "decimals": a.decimals, "verdict": verdict},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print("判定已写入：%s" % outp)

    if verdict["verdict"] == "passed":
        return EXIT_PASS
    if verdict["n_failed"]:
        return EXIT_FAIL
    return EXIT_INCONCLUSIVE


if __name__ == "__main__":
    sys.exit(main())
