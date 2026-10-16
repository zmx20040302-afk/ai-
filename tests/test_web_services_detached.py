# -*- coding: utf-8 -*-
"""常驻 Web 服务链路（脱离 DSH + 登录自启/定时自愈）的离线自测。

锁住几个**实测踩过**的坑与**实测约束**：
1. **`.ps1` 必须 UTF-8 with BOM**：PowerShell 5.1 对无 BOM 脚本按 ANSI/GBK 解码，
   中文注释会变乱码并触发解析错误（本仓库 `AGENTS.md` 已记录该坑）；
2. **`param()` 必须是脚本第一条语句**：初版在开头写了 Python 风格的 `\"\"\"…\"\"\"` 文档串，
   PowerShell 把它当表达式 ⇒ `param : The term 'param' is not recognized`；
3. **`.cmd` 必须纯 ASCII**：cmd.exe 按 OEM 代码页读；
4. **权限约束**：`Register-ScheduledTask`（含登录触发器）与 `schtasks /sc onlogon`
   实测都是 **Access denied**，只有 `schtasks /create /sc minute /mo N` 在无管理员时可用
   ⇒ 安装脚本必须走这条可行路径，并且**失败要抛错**（不得静默跳过自启）。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PS1_SERVE = REPO / "scripts/serve_detached.ps1"
PS1_INSTALL = REPO / "scripts/install_web_services_task.ps1"
CMD_CONSOLE = REPO / "work/tools/serve_console.cmd"
CMD_DASHBOARD = REPO / "work/tools/serve_dashboard.cmd"
CMD_LOGON = REPO / "scripts/start_web_services_at_logon.cmd"
CMD_ONDEMAND = REPO / "work/tools/start_web_services.cmd"

PS1_ALL = [PS1_SERVE, PS1_INSTALL]
PORTS = (8877, 8899)
TASK_NAME = "MEMS-Harness-Web"


def strip_ps_comments(text: str) -> str:
    """去掉 `#` 行注释与 `<# ... #>` 块注释，只留"可判定首条语句"的骨架。"""
    text = re.sub(r"<#.*?#>", "", text, flags=re.S)
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))


def strip_cmd_comments(text: str) -> str:
    """去掉 `.cmd` 的 `REM` / `::` 注释行。

    注释里会**提到**不该用的写法（例如"不要用 `timeout /t`，因为 …"），
    直接对全文断言"不得出现"会产生假阳性——本用例集已被这个坑咬过两次。
    """
    return "\n".join(ln for ln in text.splitlines()
                     if not re.match(r"\s*(rem\b|::)", ln, flags=re.I))


@pytest.mark.parametrize("ps1", PS1_ALL, ids=lambda p: p.name)
def test_ps1_has_bom_and_crlf(ps1: Path):
    raw = ps1.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", "%s 必须存为 UTF-8 with BOM（PS 5.1 陷阱）" % ps1.name
    assert b"\r\n" in raw, "%s 应使用 CRLF 行尾" % ps1.name


@pytest.mark.parametrize("ps1", PS1_ALL, ids=lambda p: p.name)
def test_param_is_first_statement(ps1: Path):
    text = ps1.read_text(encoding="utf-8-sig")
    body = strip_ps_comments(text)
    first = next(ln for ln in body.splitlines() if ln.strip())
    assert first.strip().startswith("param("), (
        "%s 的 param() 前出现非注释语句（例如 Python 风格文档串）⇒ PS 5.1 会报 "
        "'param is not recognized'；实际首行：%r" % (ps1.name, first))
    assert '"""' not in text, "%s 不得残留 Python 三引号文档串" % ps1.name


@pytest.mark.parametrize("ps1", PS1_ALL, ids=lambda p: p.name)
def test_ps1_parses_under_powershell(ps1: Path):
    """用真实 PowerShell 解析器过一遍（比正则可靠）。"""
    script = ("$e=$null;"
              "[System.Management.Automation.Language.Parser]::ParseFile("
              "'%s',[ref]$null,[ref]$e)|Out-Null;"
              "if($e -and $e.Count){$e|%%{Write-Output $_.Message};exit 1}else{exit 0}"
              % str(ps1).replace("'", "''"))
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, "%s PowerShell 解析失败：%s" % (ps1.name, r.stdout or r.stderr)


@pytest.mark.parametrize("cmd,port,script", [
    (CMD_CONSOLE, 8877, "webapp_server.py"),
    (CMD_DASHBOARD, 8899, "http.server"),
])
def test_service_launchers_use_a_consoleless_interpreter(cmd: Path, port: int, script: str):
    """启动器必须用 **pythonw.exe（无控制台）** + `start /b /wait` 跑服务。

    为什么锁这条（2026-10-01 实测事故）：服务原来在启动器 cmd 的控制台里前台跑，
    `work/logs/webapp-8877.log` 尾部出现字面 `^C` —— 服务是被**控制台事件**
    （Ctrl+C / 窗口关闭）打死的。而"脱离 DSH 的 Job"只挡 DSH 重启，**挡不住控制台事件**。
    换 pythonw 后没有控制台可打；已用实验验证：杀掉启动器 cmd 后服务仍 HTTP 200。
    """
    text = cmd.read_bytes().decode("ascii")
    assert "pythonw.exe" in text, "必须用 pythonw.exe（无控制台）"
    assert 'start "" /b /wait' in text, "必须 start /b /wait（保留 exited with N 的真实语义）"
    assert 'if not exist "%PYW%"' in text, "pythonw 缺失时要有回退，不能静默失败"
    assert "Scripts\\python.exe" in text, "回退目标必须存在"
    assert str(port) in text and script in text


@pytest.mark.parametrize("cmd,port,script", [
    (CMD_CONSOLE, 8877, "webapp_server.py"),
    (CMD_DASHBOARD, 8899, "http.server"),
])
def test_service_launchers_are_ascii_and_consistent(cmd: Path, port: int, script: str):
    raw = cmd.read_bytes()
    assert raw, cmd
    text = raw.decode("ascii")            # cmd.exe 按 OEM 代码页读 ⇒ 必须纯 ASCII
    assert str(port) in text, "端口不对：%s" % cmd
    assert script in text, "启动的脚本不对：%s" % cmd
    assert "work\\.venv\\Scripts\\python.exe" in text
    assert "work\\logs" in text, "必须重定向日志（脱离后没有 DSH 的 stdout 可看）"


def test_logon_launcher_is_ascii_and_calls_serve():
    text = CMD_LOGON.read_bytes().decode("ascii")
    assert "serve_detached.ps1" in text and "-Action start" in text
    assert "powershell.exe" in text


def test_ondemand_launcher_is_ascii_and_selfcontained():
    """默认策略是**按需启动**，这个入口是主路径：必须纯 ASCII、能双击、并能告知怎么停。"""
    raw = CMD_ONDEMAND.read_bytes()
    assert raw, CMD_ONDEMAND
    text = raw.decode("ascii")            # 含中文会按 OEM 代码页变乱码
    assert "serve_detached.ps1" in text and "-Action start" in text
    assert "-Action stop" in text, "必须告诉用户怎么停"
    for port in PORTS:
        assert str(port) in text, "应打印端口/URL（%d）" % port
    # 延迟不能用 timeout（stdin 被重定向时会报 Input redirection is not supported）——
    # 只看**可执行部分**，注释里会提到 timeout 以说明为何不用它
    code = strip_cmd_comments(text)
    assert "ping -n" in code
    assert "timeout /t" not in code


def test_default_policy_is_not_resident():
    """默认**不常驻**：仓库里不应存在任何"偷偷自启"的安装动作。

    安装脚本仍保留为**可选**（§3.4），但它的默认动作必须是只看状态，
    否则一次误跑就又变成常驻了。
    """
    ps = PS1_INSTALL.read_text(encoding="utf-8-sig")
    assert "[string]$Action = 'show'" in ps, "安装脚本的默认动作必须是 show，不能是 install"
    # 仓库里不得有其它自动注册自启的入口（只允许这一个显式脚本）
    others = [p for p in REPO.glob("scripts/*.ps1") if "task" in p.name.lower()]
    assert others == [PS1_INSTALL], "自动自启只允许 %s 一个入口，实际：%s" % (
        PS1_INSTALL.name, [p.name for p in others])


def test_serve_script_detaches_via_wmi():
    ps = PS1_SERVE.read_text(encoding="utf-8-sig")
    for port in PORTS:
        assert str(port) in ps, "serve_detached.ps1 未管理端口 %d" % port
    assert ps.count("serve_console.cmd") == 1 and ps.count("serve_dashboard.cmd") == 1
    code = strip_ps_comments(ps)          # 注释里会提到 Start-Process 以说明为何不用它
    assert "Win32_Process" in code and "Create" in code, (
        "必须用 WMI 创建进程：Start-Process 仍在 DSH 的 Job 对象里，DSH 重启会被一起杀")
    assert "Start-Process" not in code, "代码里不得用 Start-Process（无法脱离 Job 对象）"
    for needle in ("Job", "WmiPrvSE", "1073807364", "status", "stop"):
        assert needle in ps, needle


def test_serve_script_never_overwrites_unified_portal():
    """8899 是统一入口时，独立启动器不得杀掉它再把 8877 改回 loopback。"""
    ps = PS1_SERVE.read_text(encoding="utf-8-sig")
    code = strip_ps_comments(ps)
    assert "Test-UnifiedPortal" in code
    assert "http://127.0.0.1:8899/api/status" in code
    assert "portal_started_at" in code and ".services" in code
    guard = code.index("if (($Action -eq 'start' -or $Action -eq 'restart')")
    switch = code.index("switch ($Action)")
    assert guard < switch, "统一入口保护必须在 stop/restart 分支执行前生效"


def test_installer_uses_the_permission_feasible_path():
    """两条注册途径的权限差异是**实测**的，安装脚本必须按可行的那条走。"""
    ps = PS1_INSTALL.read_text(encoding="utf-8-sig")
    code = strip_ps_comments(ps)
    assert "schtasks.exe /create" in code, "必须用 schtasks /sc minute（无管理员时唯一可行）"
    assert "/sc minute" in code
    assert "Startup" in code and "Copy-Item" in code, (
        "登录触发器需管理员 ⇒ 登录自启改走当前用户启动文件夹")
    # 失败不得静默：schtasks 非 0 必须抛错
    assert "throw" in code and "LASTEXITCODE" in code, "schtasks 失败必须抛错，不得静默跳过自启"
    # 任务名一致（安装/查询/删除三处必须同一个名字）
    assert ps.count("$TaskName = '%s'" % TASK_NAME) == 1
    assert code.count("$TaskName") >= 5


def test_installer_uses_idempotent_action():
    """自愈动作必须幂等（端口在监听就跳过），否则每 15 分钟会重复堆进程。"""
    ps = PS1_INSTALL.read_text(encoding="utf-8-sig")
    assert "-Action start" in ps
    serve = PS1_SERVE.read_text(encoding="utf-8-sig")
    code = strip_ps_comments(serve)
    # start 分支必须**先查端口**再决定是否创建
    assert "Get-Listener" in code and "[skip]" in code, "start 必须先查监听端口，已监听则跳过"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
