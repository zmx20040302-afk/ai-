"""沙箱适配包装器：执行目标 Python 模块前，强制新建目录使用可写模式。

背景（本机实测，2026-09）：
    本机 DSH 沙箱对「以 0o700 模式创建」的目录拒绝后续写入，
    而 ``tempfile.mkdtemp`` / ``os.makedirs(mode=0o700)`` 正是这么建的，
    pip、venv 内部大量依赖它，导致 ``PermissionError: [Errno 13]``。
    复现：
        os.mkdir(p, 0o777)  -> 写入 OK
        os.mkdir(p, 0o700)  -> 写入 FAIL（PermissionError）
    因此这里把 os.mkdir / os.makedirs 的 mode 一律重写为 0o777。

用法：
    python work\\tools\\pymod.py <module> [args...]
    例：python work\\tools\\pymod.py venv work\\.venv
        python work\\tools\\pymod.py pip install -e .
"""

import os
import runpy
import sys

_real_mkdir = os.mkdir
_real_makedirs = os.makedirs


def _mkdir(path, mode=0o777, *args, **kwargs):
    return _real_mkdir(path, 0o777, *args, **kwargs)


def _makedirs(name, mode=0o777, exist_ok=False):
    return _real_makedirs(name, 0o777, exist_ok=exist_ok)


os.mkdir = _mkdir
os.makedirs = _makedirs

if len(sys.argv) < 2:
    sys.exit(__doc__)

_module = sys.argv[1]
sys.argv = [_module] + sys.argv[2:]
runpy.run_module(_module, run_name="__main__", alter_sys=True)
