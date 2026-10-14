# 在桌面创建一个"MEMS 控制台"启动快捷方式（幂等；默认不覆盖已有）
#
# 为什么要有这个脚本，而不是"手工右键新建快捷方式"：
#   1. 快捷方式的目标不是浏览器，而是 work\tools\open_console.cmd —— 它会
#      先探测端口 → 没跑才启动（幂等）→ 等 HTTP **真的应答** → 才开浏览器。
#      2026-09-29 实测过：服务"启动成功"后一分钟死掉，手点 URL 只会看到连不上；
#      所以"先等应答再开页面"这一步必须固化成可复现的脚本。
#   2. 仓库根目录从**脚本自身位置**推导（$PSScriptRoot\..），不写死机器路径。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_desktop_shortcut.ps1
#   powershell ... -File scripts\install_desktop_shortcut.ps1 -Name "我的控制台" -Force
#
# 本文件含中文 ⇒ 必须存为 **UTF-8 with BOM**（PowerShell 5.1 对无 BOM 脚本按 GBK 解码，
# 中文会变乱码并可能解析报错）。见 AGENTS.md §3「Shell」行。
param(
    [string]$Name = "启动 MEMS 控制台",
    [switch]$Force,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$target = Join-Path $repo "work\tools\open_console.cmd"
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop ($Name + ".lnk")

Write-Output "仓库根     : $repo"
Write-Output "启动器     : $target"
Write-Output "桌面       : $desktop"
Write-Output "快捷方式   : $lnk"

if ($Remove) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Output "[OK] 已删除快捷方式" }
    else { Write-Output "[skip] 不存在，无需删除" }
    exit 0
}

if (-not (Test-Path $target)) {
    Write-Output "[FAIL] 找不到启动器：$target"
    exit 2
}
if ((Test-Path $lnk) -and (-not $Force)) {
    Write-Output "[FAIL] 快捷方式已存在（不覆盖）。要重建请加 -Force。"
    exit 2
}

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnk)
# 直接指向 .cmd：Windows 会用 cmd.exe 执行它（不需要我们拼 /c 与引号）
$sc.TargetPath = $target
$sc.WorkingDirectory = $repo
$sc.Description = "启动 MEMS 平台控制台（按需启动服务，等到应答后再打开页面）"
$sc.WindowStyle = 1
$sc.Save()

if (-not (Test-Path $lnk)) {
    Write-Output "[FAIL] 创建后仍找不到文件（COM 写入失败？）"
    exit 2
}

# 回读校验：不能只看"文件在"，要确认它指向的正是那个启动器
$back = $shell.CreateShortcut($lnk)
Write-Output "[OK] 已创建"
Write-Output ("     回读 TargetPath      : " + $back.TargetPath)
Write-Output ("     回读 WorkingDirectory: " + $back.WorkingDirectory)
if ($back.TargetPath -ne $target) {
    Write-Output "[FAIL] 回读的目标与预期不一致"
    exit 2
}
exit 0
