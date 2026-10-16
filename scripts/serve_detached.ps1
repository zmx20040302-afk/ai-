# -*- coding: utf-8 -*-
<# Web 服务脱离 DSH 作业对象的启动器（PowerShell 5.1 脚本，UTF-8 with BOM）。

为什么需要它：DSH 会把它的后台作业进程放进自己的 Windows **Job 对象**；
DSH 一重启，Job 对象被拆，里面的子进程被一起杀掉
（实测 2026-09-24：DSH 14:34 重启，8877 控制台与 8899 看板同时被终止，
退出码 `1073807364 = 0x40010004 = DBG_TERMINATE_PROCESS`）。

脱离手段：用 **WMI `Win32_Process.Create`** 创建进程——进程由 `WmiPrvSE.exe` 创建，
父链指向 WMI 服务而不是 DSH，因此**不在** DSH 的 Job 里，DSH 重启不再影响它。
（`Start-Process` 做不到：它仍在当前 Job 内，会被一起杀。）

用法：
    powershell -ExecutionPolicy Bypass -File scripts\\serve_detached.ps1 -Action status
    powershell -ExecutionPolicy Bypass -File scripts\\serve_detached.ps1 -Action start
    powershell -ExecutionPolicy Bypass -File scripts\\serve_detached.ps1 -Action stop
    powershell -ExecutionPolicy Bypass -File scripts\\serve_detached.ps1 -Action restart

注意：脱离后 DSH 的 jobs 列表里**看不到**它们；停止要用 `-Action stop`
（或按端口 taskkill）。日志在 `work\\logs\\webapp-8877.log` / `dashboard-8899.log`。
#>
param(
    [ValidateSet('start', 'stop', 'status', 'restart')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
$Repo = 'C:\Users\zmx\Desktop\memsharness'
$Targets = @(
    [pscustomobject]@{ Name = 'chat-console'; Port = 8877; Cmd = "$Repo\work\tools\serve_console.cmd" },
    [pscustomobject]@{ Name = 'static-dashboard'; Port = 8899; Cmd = "$Repo\work\tools\serve_dashboard.cmd" }
)

function Get-Listener([int]$Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($null -eq $c) { return @() }
    # 同一端口可能有多条记录，进程去重
    return @($c | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Get-ProcInfo([int]$Pid0) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$Pid0" -ErrorAction SilentlyContinue
    if ($null -eq $p) { return $null }
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ParentProcessId)" -ErrorAction SilentlyContinue
    $parentName = '(gone)'
    if ($parent) { $parentName = $parent.Name }
    return [pscustomobject]@{
        Pid = $Pid0
        Name = $p.Name
        ParentPid = $p.ParentProcessId
        Parent = $parentName
    }
}

function Stop-Port([int]$Port) {
    $killed = @()
    foreach ($procId in Get-Listener $Port) {
        $info = Get-ProcInfo $procId
        $name = '?'
        if ($info) { $name = $info.Name }
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        $killed += "$procId($name)"
    }
    # 等端口真的释放（实测终止后 PID/端口不会立刻消失，需带超时轮询）
    for ($i = 0; $i -lt 40; $i++) {
        if ((Get-Listener $Port).Count -eq 0) { break }
        Start-Sleep -Milliseconds 250
    }
    return , $killed
}

function Start-Detached([pscustomobject]$T) {
    # WMI 创建 => 父进程是 WmiPrvSE，脱离 DSH 的 Job 对象
    $res = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine    = "cmd.exe /c `"$($T.Cmd)`""
        CurrentDirectory = $Repo
    }
    if ($res.ReturnValue -ne 0) {
        throw "WMI 创建失败 ($($T.Name)) ReturnValue=$($res.ReturnValue)"
    }
    for ($i = 0; $i -lt 60; $i++) {
        if ((Get-Listener $T.Port).Count -gt 0) { break }
        Start-Sleep -Milliseconds 250
    }
    return [pscustomobject]@{ Name = $T.Name; Port = $T.Port; CreatedPid = $res.ProcessId;
                              Listening = ((Get-Listener $T.Port).Count -gt 0) }
}

function Show-Status {
    $rows = @()
    foreach ($t in $Targets) {
        $pids = Get-Listener $t.Port
        if ($pids.Count -eq 0) {
            $rows += [pscustomobject]@{ Service = $t.Name; Port = $t.Port; State = 'DOWN';
                                        Pid = ''; Parent = ''; Http = '' }
            continue
        }
        foreach ($procId in $pids) {
            $info = Get-ProcInfo $procId
            $parentTxt = ''
            if ($info) { $parentTxt = "$($info.Parent)($($info.ParentPid))" }
            $http = ''
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:$($t.Port)/" -UseBasicParsing -TimeoutSec 10
                $http = "$($r.StatusCode) $($r.RawContentLength)B"
            } catch { $http = 'ERR' }
            $rows += [pscustomobject]@{
                Service = $t.Name; Port = $t.Port; State = 'UP'; Pid = $procId
                Parent = $parentTxt
                Http = $http
            }
        }
    }
    return $rows
}

function Test-UnifiedPortal {
    <#
    8899 也被 COMSOL × AI 统一入口使用。统一入口会负责拉起 8880/8877、
    生成局域网令牌并自动恢复子服务；若这里再执行 restart，会先杀掉统一入口，
    随后把 8877 改回仅回环监听，导致其他电脑 ERR_CONNECTION_REFUSED。
    因此在任何会创建/替换服务的动作前 fail-closed。
    #>
    try {
        $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8899/api/status' -TimeoutSec 3
        return ($null -ne $r.portal_started_at -and $null -ne $r.services)
    } catch {
        return $false
    }
}

if (($Action -eq 'start' -or $Action -eq 'restart') -and (Test-UnifiedPortal)) {
    Write-Output '[guard] 检测到 COMSOL × AI 统一入口正在 8899 运行；不覆盖 8877/8899。'
    Write-Output '[guard] 请使用 C:\Users\zmx\Desktop\comsol1\unified_portal\service_control.py 管理统一工作台。'
    exit 0
}

switch ($Action) {
    'status' { Show-Status | Format-Table -AutoSize | Out-String -Width 200 }
    'start' {
        foreach ($t in $Targets) {
            $existing = Get-Listener $t.Port
            if ($existing.Count -gt 0) {
                Write-Output "[skip] $($t.Name) 已在 $($t.Port) 上监听（pid $($existing -join ','))"
                continue
            }
            $r = Start-Detached $t
            Write-Output "[start] $($r.Name) pid=$($r.CreatedPid) listening=$($r.Listening)"
        }
        Show-Status | Format-Table -AutoSize | Out-String -Width 200
    }
    'stop' {
        foreach ($t in $Targets) {
            $killed = Stop-Port $t.Port
            if ($killed.Count -eq 0) { Write-Output "[stop] $($t.Name) 本来就没在跑" }
            else { Write-Output "[stop] $($t.Name) 终止 $($killed -join ', ')" }
        }
    }
    'restart' {
        foreach ($t in $Targets) {
            $killed = Stop-Port $t.Port
            Write-Output "[stop] $($t.Name) $(if ($killed.Count) { '终止 ' + ($killed -join ', ') } else { '本来没跑' })"
        }
        foreach ($t in $Targets) {
            $r = Start-Detached $t
            Write-Output "[start] $($r.Name) pid=$($r.CreatedPid) listening=$($r.Listening)"
        }
        Show-Status | Format-Table -AutoSize | Out-String -Width 200
    }
}
