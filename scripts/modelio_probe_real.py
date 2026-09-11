"""一次性验证脚本：对 work/runs 下真实存在的 .mph 跑一次真实 probe_model，并落档。

这是**实测证据生成器**，不是平台代码（放在 scripts/ 只作为运维脚本）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness import modelio as mio  # noqa: E402

MODEL = REPO / "work" / "runs" / "run-20260911T030051Z-08e8921a" / "out_Model.mph"


def main() -> int:
    if not MODEL.is_file():
        print(f"模型不存在：{MODEL}")
        return 2
    print(f"# 目标模型：{MODEL} ({MODEL.stat().st_size} bytes)")
    result = mio.probe_model(MODEL)
    out = REPO / "work" / "reports" / "modelio"
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"probe-{result['run_id']}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"# run_id={result['run_id']} ok={result['ok']} run_dir={result['run_dir']}")
    print(f"# 落档：{target}")
    print("=== 实测输出（原样） ===")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
