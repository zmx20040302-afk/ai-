"""COMSOL 环境冒烟检查（命令行入口）。

真正的探测逻辑在 ``memsharness.env``，本脚本只是薄封装，
便于在未安装包的情况下直接运行。

用法：
    work\\.venv\\Scripts\\python.exe scripts\\smoke_comsol.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# 未安装包时回退到源码目录（src/）
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from memsharness.env import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
