# -*- coding: utf-8 -*-
"""桌面启动快捷方式安装器的契约测试（静态检查，不真的建快捷方式）。

为什么要有：这个脚本动的是**桌面**（仓库外），一旦写错（比如把仓库路径写死、
或者覆盖掉用户已有的同名快捷方式）后果不可逆。所以把它的不变量锁在仓库里：
含中文 ⇒ 必须 UTF-8 **with BOM**；仓库根必须从脚本自身推导；默认不覆盖；保存后**回读**校验。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PS1 = REPO / "scripts/install_desktop_shortcut.ps1"
LAUNCHER = REPO / "work/tools/open_console.cmd"


def _code(path: Path) -> str:
    """去掉注释行后的正文（用于"第一条语句是不是 param()"这类判断）。"""
    text = path.read_text(encoding="utf-8-sig")
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))


def test_installer_exists_and_launcher_is_ascii():
    assert PS1.is_file(), "缺安装器：%s" % PS1
    assert LAUNCHER.is_file(), "快捷方式指向的启动器不存在：%s" % LAUNCHER
    # 启动器是 .cmd ⇒ 必须纯 ASCII（cmd.exe 按 OEM 代码页读，中文会变乱码）
    raw = LAUNCHER.read_bytes()
    assert all(b < 128 for b in raw), "启动器含非 ASCII 字节"
    for needle in (b"-Action start", b"127.0.0.1", b"8877"):
        assert needle in raw, "启动器缺关键内容：%r" % needle


def test_installer_must_be_utf8_with_bom():
    """含中文的 .ps1 必须带 BOM：PowerShell 5.1 对无 BOM 脚本按 GBK 解码（AGENTS.md §3）。"""
    raw = PS1.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", "install_desktop_shortcut.ps1 必须存为 UTF-8 with BOM"
    assert not raw.startswith(b"\xef\xbb\xbf\xef\xbb\xbf"), "只许一个 BOM"


def test_param_is_the_first_statement():
    body = _code(PS1)
    assert body.lstrip().startswith("param("), \
        "param() 必须是第一条语句（前面写 Python 风格文档串会直接报 param 无法识别）"


@pytest.mark.parametrize("needle", ["$PSScriptRoot", "$Force", "$Remove", "WScript.Shell",
                                    "CreateShortcut", "Desktop", "回读"])
def test_installer_keeps_its_invariants(needle):
    code = PS1.read_text(encoding="utf-8-sig")
    assert needle in code, "安装器缺少：%s" % needle


def test_installer_does_not_hardcode_machine_paths():
    """仓库根必须从脚本自身推导；写死路径会在换机/换目录后静默建错快捷方式。"""
    code = _code(PS1)
    for bad in ("C:\\Users\\", "D:\\桌面", "memsharness\\work\\tools\\open_console"):
        assert bad not in code, "安装器里写死了机器路径：%s" % bad
    assert 'Join-Path $PSScriptRoot ".."' in code, "必须用 $PSScriptRoot 推导仓库根"


def test_installer_refuses_to_overwrite_by_default():
    code = PS1.read_text(encoding="utf-8-sig")
    assert "Test-Path $lnk" in code and "-Force" in code
    i_refuse = code.find("[FAIL] 快捷方式已存在")
    assert i_refuse > 0 and "exit 2" in code[i_refuse:], \
        "已存在时必须拒绝（fail-closed），而不是悄悄覆盖"


def test_installer_verifies_by_reading_back():
    """只检查"文件在"不够：必须回读 TargetPath 并断言它等于预期启动器。"""
    code = PS1.read_text(encoding="utf-8-sig")
    assert "回读 TargetPath" in code
    assert "if ($back.TargetPath -ne $target)" in code, "回读后必须做相等断言"


def test_shortcut_target_is_the_self_healing_launcher():
    """目标必须是 open_console.cmd（探测→按需启动→等到应答→才开页面），不是直接开 URL。"""
    code = PS1.read_text(encoding="utf-8-sig")
    assert 'Join-Path $repo "work\\tools\\open_console.cmd"' in code
