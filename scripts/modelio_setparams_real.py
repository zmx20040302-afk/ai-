"""一次性验证脚本：对真实 .mph 跑一次真实 set_parameters（改一个非几何参数），并留在工作区。

这是**实测证据生成器**，不是平台代码。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness import modelio as mio  # noqa: E402
from memsharness.comsol.backend import sha256_file  # noqa: E402

MODEL = REPO / "work" / "runs" / "run-20260911T030051Z-08e8921a" / "out_Model.mph"
CHANGES = {"p_load": "50000[Pa]", "hmax_mesh": "2e-5[m]"}


def main() -> int:
    if not MODEL.is_file():
        print(f"模型不存在：{MODEL}")
        return 2
    # 命令行给 --no-geometry 可跳过基线/写后探针（省两次批处理）
    baseline_geometry = "--no-geometry" not in sys.argv
    before = sha256_file(MODEL)
    print(f"# 目标模型：{MODEL}")
    print(f"# 预期改动：{CHANGES}")
    print(f"# baseline_geometry={baseline_geometry}")
    result = mio.set_parameters(MODEL, CHANGES, baseline_geometry=baseline_geometry)
    out = REPO / "work" / "reports" / "modelio"
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"setparam-{result['run_id']}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"# run_id={result['run_id']} ok={result['ok']} rejected={result['rejected']}")
    print(f"# 原文件哈希（操作前）={before}")
    print(f"# 原文件未被改动={result['source_original_untouched']}")
    print(f"# 新副本：{result['output_path']} sha256={result['output_sha256']}")
    print(f"# 落档：{target}")
    print("=== diff（实测） ===")
    print(json.dumps(result["diff"], ensure_ascii=False, indent=2))
    print("=== 几何/选择集状态（实测） ===")
    print(json.dumps(
        {
            "geometry_relative_shift": result["geometry_relative_shift"],
            "geometry_changing": result["geometry_changing"],
            "required_reverification": result["required_reverification"],
            "baseline_bounding_box": result["baseline_bounding_box"],
            "after_bounding_box": result["after_bounding_box"],
            "geometry_after_set": result["geometry_after_set"],
            "named_selections_after": result["named_selections_after"],
            "baseline_probe_run_id": result["baseline_probe_run_id"],
            "after_probe_run_id": result["after_probe_run_id"],
            "notes": result["notes"],
        },
        ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
