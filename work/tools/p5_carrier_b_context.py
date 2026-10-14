# -*- coding: utf-8 -*-
"""P5-1 前置：把载体 B（M-h1um）的**模型身份、设计点、频点、选择集**从既有产物里读出来。

不猜：只读 `s3_gate_c_batch.json` 与远端 batchlog，把要用的选择集编号与频点**逐项列出**，
写进 `work/runs/eda64-20261010/p5_h1um/P5_CARRIER_B_CONTEXT.json`，供随后的零求解复测使用。
"""
from __future__ import annotations

import io
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "work/runs/eda64-20261010/p5_h1um"
S3 = REPO / "work/runs/c-batch-20261010/s3_gate_c_batch.json"
N1 = REPO / "work/runs/eda64-20261010/N1_PORT_ENERGY_DIAGNOSIS.md"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s3 = json.loads(S3.read_text(encoding="utf-8"))
    res: dict = {"kind": "p5_carrier_b_context", "source": str(S3.relative_to(REPO))}

    def find(o, keys, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if any(kk in str(k).lower() for kk in keys):
                    yield path + "/" + str(k), v
                yield from find(v, keys, path + "/" + str(k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                yield from find(v, keys, path + "[%d]" % i)

    for pat in ("model", "carrier", "sha", "design", "param", "freq", "selection", "solution",
                "study", "mesh", "level", "h1um"):
        hits = list(find(s3, [pat]))
        if hits:
            res.setdefault("s3_gate_facts", {})[pat] = [
                {"path": p, "value": (v if not isinstance(v, (dict, list)) else
                                      json.dumps(v, ensure_ascii=False)[:400])}
                for p, v in hits[:10]]

    # N1 文档里关于载体 B 的登记（逐字摘录，作为口径依据）
    t = io.open(N1, encoding="utf-8").read()
    keep = [l for l in t.split("\n") if "载体 B" in l or "s34_h1um" in l or "3.7338" in l
            or "3.96446" in l or "6.177" in l]
    res["n1_doc_lines_on_carrier_B"] = keep

    # 远端 batchlog（若已取回）里的频点与参数
    for cand in (OUT / "batchlog_s34_h1um.txt", OUT / "s34_h1um.stdout.log"):
        if cand.is_file():
            txt = cand.read_text(encoding="utf-8", errors="replace")
            res.setdefault("remote_log_facts", {})[cand.name] = {
                "freq_lines": re.findall(r".*(?:MHz|frequency).*", txt)[:12],
                "param_lines": re.findall(r".*(?:x_scale|N_w_te1|N_w_te2|v0).*", txt)[:12],
            }
    (OUT / "P5_CARRIER_B_CONTEXT.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1)[:4000])
    print("== 写出", OUT / "P5_CARRIER_B_CONTEXT.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
