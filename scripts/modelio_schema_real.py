"""一次性验证脚本：跑真实 probe_model，并单独展示 schema（补全数据）来源与枚举校验结果。"""

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
    print("# ---- schema 来源（本地权威） ----")
    print(json.dumps(mio.schema_source(), ensure_ascii=False, indent=2))
    print("# ---- 直接查 forceType 的合法取值 ----")
    print(json.dumps(
        {k: v for k, v in mio.lookup_enum(
            "forceType", feature="BoundaryLoad", topic="solid_bndl").items()
         if k in ("ok", "values", "intersection_values", "variant_dependent_values",
                  "default", "descr", "variant_count")},
        ensure_ascii=False, indent=2))
    print("# ---- 历史 bug 的取值校验 ----")
    print(json.dumps(
        mio.validate_enum_value("BoundaryLoad", "forceType", "Pressure", topic="solid_bndl"),
        ensure_ascii=False, indent=2))

    print("# ---- 真实 probe_model ----")
    result = mio.probe_model(MODEL)
    out = REPO / "work" / "reports" / "modelio"
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"probe-{result['run_id']}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"# run_id={result['run_id']} ok={result['ok']} run_dir={result['run_dir']}")
    print(f"# 落档：{target}")
    print(json.dumps(
        {
            "schema_source": result["schema_source"],
            "enum_validation": {
                k: v for k, v in (result["enum_validation"] or {}).items()
                if k in ("available", "checked_count", "enum_checked", "illegal",
                         "variant_dependent", "notes")
            },
        },
        ensure_ascii=False, indent=2)[:4000])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
