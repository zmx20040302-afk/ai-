"""对指定的真实 .mph 跑一次只读 probe，并把证据落档。

与 ``scripts/modelio_probe_real.py`` 的区别：那个脚本把目标路径**写死**成一个
迁移包里已被剥离的 ``work/runs/.../out_Model.mph``；这里改成命令行传参，
便于对任意（仓库外的）生产模型做只读探针。

安全约定（AGENTS.md 第 3/4 节）：
    ``mio.probe_model`` 自己会复制到暂存区，绝不改动原件，并记录源路径 + SHA256 +
    ``lock_present`` + ``original_untouched``；本脚本只负责传参与落档。

用法：
    python work\\tools\\probe_real_model.py "C:\\Users\\zmx\\Desktop\\b_GE_task3_2-new.mph"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from memsharness import modelio as mio  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    model = Path(sys.argv[1])
    if not model.is_file():
        print(f"模型不存在：{model}")
        return 2

    lock = model.with_suffix(model.suffix + ".lock")
    print(f"# 目标模型：{model}")
    print(f"# 大小：{model.stat().st_size} bytes")
    print(f"# 旁路 .lock 是否存在（GUI 打开中）：{lock.exists()}")

    result = mio.probe_model(model)

    out_dir = _REPO_ROOT / "work" / "reports" / "modelio"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"probe-{result['run_id']}.json"
    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    src = result.get("source", {})
    print("=" * 70)
    print(f"run_id        : {result['run_id']}")
    print(f"ok            : {result['ok']}")
    print(f"run_dir       : {result['run_dir']}")
    print(f"COMSOL 版本   : {result.get('comsol_version')}")
    print(f"源文件 SHA256 : {src.get('sha256')}")
    print(f"原件未被改动  : {src.get('original_untouched')}（lock_present={src.get('lock_present')}）")
    print(f"参数条数      : {len(result.get('parameters') or [])}")
    print(f"几何体        : {len(result.get('geometry') or [])}")
    print(f"物理场节点    : {len(result.get('physics') or [])}")
    print(f"研究          : [{(', '.join(s.get('tag', '?') for s in (result.get('studies') or [])))}]")
    print(f"网格统计      : {result.get('mesh')}")
    if result.get("payload_error") or result.get("diagnostic"):
        print(f"payload_error : {result.get('payload_error')}")
        print(f"diagnostic    : {json.dumps(result.get('diagnostic'), ensure_ascii=False, default=str)}")
    print(f"落档          : {target}")
    print("=" * 70)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
