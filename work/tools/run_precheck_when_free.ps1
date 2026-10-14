# 等 COMSOL GUI 退出后，**只跑哨兵点**验证 v2 预检的面积通路；跑完即停，不自动上全量。
# 为什么只跑哨兵：v2 是刚按 Codex §1 重写的脚本，先小样本验证"面积到底能不能取到"，
# 再决定是否放全量 162 组。守住"COMSOL 单实例串行"红线。
# 注意：本文件必须保存为 UTF-8 with BOM（PowerShell 5.1 对无 BOM 脚本按 GBK 解码会报解析错误）。
$ErrorActionPreference = 'Continue'
$repo = 'C:\Users\zmx\Desktop\memsharness'
$py   = Join-Path $repo 'work\.venv\Scripts\python.exe'
$script = Join-Path $repo 'scripts\geometry_selection_precheck.py'
$logDir = Join-Path $repo 'work\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = (Get-Date).ToString('yyyyMMddTHHmmss')
$log = Join-Path $logDir "precheck-sentinel-$stamp.log"
$model = Join-Path $env:USERPROFILE 'Desktop\b_GE_task3_2new.mph'

function Log([string]$m) {
    $line = "{0}  {1}" -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $m
    Add-Content -Path $log -Value $line -Encoding UTF8
    Write-Output $line
}

function PortOpen([int]$p) {
    try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', $p); $c.Close(); return $true }
    catch { return $false }
}

Log "守望启动：等 ComsolUI/comsolmphserver/comsol 退出（每 60 s 探一次）"
$waited = 0
while ($true) {
    $busy = Get-Process -Name ComsolUI, comsolmphserver, comsol -ErrorAction SilentlyContinue
    if (-not $busy) { break }
    if ($waited % 600 -eq 0) {
        $cpu = ($busy | Measure-Object -Property CPU -Sum).Sum
        Log ("仍在占用：{0}（CPU 合计 {1:N0} s）" -f (($busy | ForEach-Object { $_.Name }) -join ','), $cpu)
    }
    Start-Sleep -Seconds 60
    $waited += 60
}
Log "进程已退出（等待 $waited s）；留 30 s 给许可证释放"
Start-Sleep -Seconds 30

$serverBefore = @(Get-Process -Name comsolmphserver -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
Log "开始哨兵验证：--only-sentinels（0.4:1, 0.6:4, 0.8:8），phase both"
& $py $script --model $model --only-sentinels --phase both --device ge-task3-precheck-sentinel 2>&1 |
    Tee-Object -FilePath $log -Append | Out-Null
$code = $LASTEXITCODE
Log "哨兵验证结束：exit=$code"

# 只终止「本次运行期间新出现」的 mphserver，避免误杀用户自己的服务
$serverAfter = @(Get-Process -Name comsolmphserver -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$new = $serverAfter | Where-Object { $serverBefore -notcontains $_ }
foreach ($procId in $new) {
    Log "终止本次启动的 comsolmphserver PID=$procId"
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}
Log "端口 2036 仍开放 = $(PortOpen 2036)"
Log "已停止（按计划不自动进入全量 162 组）"
exit $code
