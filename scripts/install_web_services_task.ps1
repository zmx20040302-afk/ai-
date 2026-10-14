# -*- coding: utf-8 -*-
<# 让两个常驻 Web 服务"以后不用再管"：**登录自启 + 定时自愈**。

为什么还需要它：`serve_detached.ps1` 只解决了"DSH 重启会杀掉服务"（脱离 Job 对象），
但**机器重启/注销重登后进程一样会没**，服务自己崩了也没人拉。本脚本补上这两件事。

【实测约束（2026-09-24）】两条注册途径权限不同，必须按实际可行的走：
* `Register-ScheduledTask -Trigger (New-ScheduledTaskTrigger -AtLogOn)` ⇒ **Access is denied** (0x80070005)
* `schtasks /create /sc onlogon` ⇒ **ACCESS DENIED**（登录触发器会影响所有用户，需管理员）
* `Register-ScheduledTask`（不带登录触发器）⇒ 同样 **Access is denied**
* `schtasks /create /sc minute /mo 15` ⇒ **SUCCESS**（当前用户级，**无需管理员**）

⇒ 方案：**定时任务（无需管理员）负责自愈并覆盖重启后的恢复**；
**登录自启用「当前用户启动文件夹」**（同为用户级、无需管理员）。
动作都是 `serve_detached.ps1 -Action start`，**幂等**（端口已在监听就跳过）。

用法：
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_web_services_task.ps1 -Action install
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_web_services_task.ps1 -Action show
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_web_services_task.ps1 -Action run
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_web_services_task.ps1 -Action remove

⚠️ 注册后 `serve_detached.ps1 -Action stop` 只**临时**停服务，最多 N 分钟后被自动拉回。
   **要长期停掉必须 `-Action remove`**（或 disable 任务）。
   用 `-IntervalMinutes 0` 可只保留登录自启、不要自愈。

想改用"登录触发器"的原生任务，需用**管理员** PowerShell 跑一次 install。
#>
param(
    [ValidateSet('install', 'remove', 'show', 'run')]
    [string]$Action = 'show',
    [int]$IntervalMinutes = 15
)

$ErrorActionPreference = 'Stop'
$TaskName = 'MEMS-Harness-Web'
$Repo = 'C:\Users\zmx\Desktop\memsharness'
$Serve = Join-Path $Repo 'scripts\serve_detached.ps1'
$LogonCmd = Join-Path $Repo 'scripts\start_web_services_at_logon.cmd'
$StartupDir = [Environment]::GetFolderPath('Startup')
$StartupEntry = Join-Path $StartupDir 'MEMS-Harness-Web.cmd'
$TaskRun = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Serve`" -Action start"

function Get-Task {
    return Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

function Show-All {
    Write-Output "=== 计划任务：$TaskName ==="
    $t = Get-Task
    if (-not $t) {
        Write-Output '  （未注册）'
    } else {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Output "  状态     : $($t.State)"
        Write-Output "  动作     : $($t.Actions[0].Execute) $($t.Actions[0].Arguments)"
        Write-Output "  触发器   : $(($t.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ', ')"
        Write-Output "  上次运行 : $($info.LastRunTime)  结果=$($info.LastTaskResult)"
        Write-Output "  下次运行 : $($info.NextRunTime)"
    }
    Write-Output ''
    Write-Output '=== 登录自启（当前用户启动文件夹）==='
    Write-Output "  目录     : $StartupDir"
    if (Test-Path $StartupEntry) {
        Write-Output '  入口     : MEMS-Harness-Web.cmd  （已就位）'
    } else {
        Write-Output '  入口     : （未安装）'
    }
    Write-Output ''
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Serve -Action status
}

switch ($Action) {
    'show' { Show-All }

    'run' {
        if (-not (Get-Task)) { throw "任务 $TaskName 未注册，先跑 -Action install" }
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 6
        Show-All
    }

    'remove' {
        if (Get-Task) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
            if (Get-Task) { & schtasks.exe /delete /tn $TaskName /f | Out-Null }
            Write-Output "[remove] 已移除计划任务 $TaskName"
        } else {
            Write-Output "[remove] 任务 $TaskName 本来就不存在"
        }
        if (Test-Path $StartupEntry) {
            Remove-Item $StartupEntry -Force
            Write-Output '[remove] 已移除登录自启入口'
        } else {
            Write-Output '[remove] 登录自启入口本来就不存在'
        }
        Write-Output '（服务进程本身仍在跑；要停用 serve_detached.ps1 -Action stop）'
    }

    'install' {
        # ---- ① 定时任务（无需管理员的那条路）----
        if ($IntervalMinutes -gt 0) {
            $out = & schtasks.exe /create /tn $TaskName /tr $TaskRun /sc minute `
                /mo $IntervalMinutes /f 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "schtasks 注册失败（rc=$LASTEXITCODE）：$out"
            }
            Write-Output "[install] 计划任务 $TaskName 已注册（每 $IntervalMinutes 分钟自愈一次）"
        } else {
            Write-Output '[install] -IntervalMinutes 0 ⇒ 跳过定时任务（只要登录自启）'
        }

        # ---- ② 登录自启（当前用户启动文件夹，无需管理员）----
        if (-not (Test-Path $LogonCmd)) { throw "缺少 $LogonCmd" }
        Copy-Item $LogonCmd $StartupEntry -Force
        Write-Output "[install] 登录自启入口已就位：$StartupEntry"

        Write-Output ''
        Write-Output '立刻试跑一次…'
        if (Get-Task) { Start-ScheduledTask -TaskName $TaskName; Start-Sleep -Seconds 6 }
        Show-All
    }
}
