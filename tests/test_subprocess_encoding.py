# -*- coding: utf-8 -*-
"""锁住「父子两侧都是 UTF-8」这条边界（成因与实测见 `tests/_subproc.py` 的模块注释）。

背景一句话：本机中文 Windows 的 `locale.getpreferredencoding(False) == cp936`，
子进程往 pipe 写用 cp936、父进程若按 utf-8 解 ⇒ 中文变乱码，
**断言的中文在乱码里找不到** ⇒ 把"脚本行为完全正确"报成失败（实测 11 个用例）。
本文件做两件事：
1. **功能**：证明 `_subproc.run_py()` 确实让子进程吐 UTF-8（含 cp936 编不出来的 `⇒`），
   并给出**反向对照**（不强制时在本机读不回来）—— 对照仅在非 UTF-8 locale 下断言，
   免得在 UTF-8 机器上变成假失败；
2. **扫描**：任何"用 utf-8 解 `sys.executable` 输出"的测试文件，必须同时强制子进程 UTF-8。
"""
from __future__ import annotations

import locale
import pathlib

import pytest

import _subproc  # noqa: E402  （tests/ 目录由 pytest 加进 sys.path）

REPO = pathlib.Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

CJK = "目标版本已存在"
RARR = "\u21d2"          # cp936 **编不出来**（实测 UnicodeEncodeError）


def _child(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "child_echo.py"
    p.write_text(
        "# -*- coding: utf-8 -*-\n"
        "import sys\n"
        "msg = %r\n"
        "sys.stdout.write(msg + chr(10))\n"
        "sys.stderr.write(msg + chr(10))\n" % (CJK + " " + RARR),
        encoding="utf-8", newline="\n")
    return p


def test_helper_forces_utf8_on_the_child(tmp_path):
    """`run_py()` 的子进程必须吐 UTF-8：中文与 `⇒` 都要原样读回来。"""
    r = _subproc.run_py(_child(tmp_path))
    assert r.returncode == 0, _subproc.out_of(r)
    for nm, txt in (("stdout", r.stdout), ("stderr", r.stderr)):
        assert CJK in txt, "%s 里的中文没读回来：%r" % (nm, txt)
        assert RARR in txt, "%s 里的 ⇒ 没读回来：%r" % (nm, txt)


def test_reverse_control_without_forcing_utf8(tmp_path):
    """反向对照：**不**强制 UTF-8 时，本机（非 UTF-8 locale）这条消息读不回来。

    这条不是"测试环境洁癖"：它证明上一条测的是**真实机制**，而不是一个恒真的断言。
    在本来就用 UTF-8 的机器上跳过（并说明原因），不静默通过。
    """
    enc = locale.getpreferredencoding(False)
    if enc.lower().replace("-", "") in ("utf8", "utf_8"):
        pytest.skip("本机 locale 已是 %s ⇒ 不存在这个失败模式" % enc)
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-B", str(_child(tmp_path))],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    both = (r.stdout or "") + (r.stderr or "")
    assert CJK not in both, ("不强制 UTF-8 竟然也读回来了（locale=%s）⇒ "
                             "本用例的前提变了，请复核 tests/_subproc.py 的说明" % enc)


def _decodes_python_child_as_utf8(src: str) -> bool:
    """这个测试文件里有没有「跑 `sys.executable` 子进程 + 显式 `encoding=` 解码」的调用？

    初版用**子串**判断（文件里同时出现 `sys.executable` 与 `encoding="utf-8"`），
    当场误报了 `test_webapp_mc_agents_tasks.py` —— 它的 `sys.executable` 出现在一个
    **不捕获输出**的 `sleep` 子进程上，而 `encoding="utf-8"` 全是 `read_text` 读文件。
    子串判定又一次骗人（本仓库第 N 次），故改为 AST：**只看同一个调用**。
    """
    import ast

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "attr", None) or getattr(fn, "id", None)
        if name not in ("run", "Popen", "check_output", "call"):
            continue
        enc = None
        for kw in node.keywords:
            if kw.arg == "encoding" and isinstance(kw.value, ast.Constant):
                enc = kw.value.value
        if not isinstance(enc, str) or enc.lower().replace("-", "") != "utf8":
            continue
        # ⚠️ argv 是**列表字面量**（`[sys.executable, "-B", …]`）⇒ `sys.executable`
        # 藏在 `ast.List.elts` 里，只看 `node.args` 会**永远匹配不到**。
        # 本守卫的自检（work/_guard_selftest.py）当场抓到了这个"恒不报错"的假守卫。
        for sub in ast.walk(node):
            if isinstance(sub, ast.Attribute) and sub.attr == "executable":
                return True
    return False


@pytest.mark.parametrize("src,want", [
    # 旧写法（正是造成 11 个假失败的那行）⇒ 必须报
    ('r = subprocess.run([sys.executable, "-B", str(s)],\n'
     '     capture_output=True, text=True, encoding="utf-8", errors="replace")', True),
    # 非 Python 子进程（node 的语法检查）⇒ 不报（PYTHONUTF8 管不到它）
    ('r = subprocess.run([node, "--check", str(tmp)],\n'
     '     capture_output=True, text=True, encoding="utf-8")', False),
    # 不显式解码（两边同 locale，天然一致）⇒ 不报
    ('p = subprocess.Popen([sys.executable, "-c", "import time"], text=True)', False),
    # gbk 解码不在本扫描口径内
    ('r = subprocess.run([sys.executable, "-B", "x.py"], encoding="gbk")', False),
    # `read_text(encoding=…)` 读的是文件、不是子进程 ⇒ 不报
    ('h = PAGE.read_text(encoding="utf-8")', False),
])
def test_scanner_can_actually_flag_violations(src, want):
    """**守卫的守卫**：扫描器必须能对旧写法报错，否则它只是恒真的摆设。

    实测教训：初版按 `node.args` 找 `sys.executable`，而 argv 是**列表字面量**
    （`[sys.executable, …]`）⇒ 永远匹配不到 ⇒ **永远不会失败**。
    "检查通过"当时什么都没证明。
    """
    assert _decodes_python_child_as_utf8(src) is want


def test_no_test_decodes_utf8_without_forcing_it():
    """扫描：用 utf-8 解 **Python 子进程**输出的测试，必须强制子进程 UTF-8。"""
    bad = []
    for p in sorted(TESTS.glob("test_*.py")):
        src = p.read_text(encoding="utf-8")
        if not _decodes_python_child_as_utf8(src):
            continue
        if ("PYTHONUTF8" in src) or ("_subproc" in src):
            continue
        bad.append(p.name)
    assert not bad, (
        "这些测试用 utf-8 解 **Python 子进程**输出，却没让子进程进 UTF-8 模式 —— "
        "本机默认 cp936，中文会变乱码、断言会假失败。改用 `_subproc.run_py(...)`：%s" % bad)
