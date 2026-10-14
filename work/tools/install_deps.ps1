# 依赖安装：本机网络对镜像的索引页偶发截断，用「重试收敛」策略
# （pip 的 HTTP 缓存会保留已成功的包，每轮都会前进，直至全部装完）
$ErrorActionPreference = 'Continue'
$ws = 'C:\Users\zmx\Desktop\memsharness'
$vpy = "$ws\work\.venv\Scripts\python.exe"
$env:TMP = "$ws\work\tmp"
$env:TEMP = $env:TMP
$env:PIP_CACHE_DIR = "$ws\work\.pip-cache"
$idx = 'https://pypi.tuna.tsinghua.edu.cn/simple/'
$log = "$ws\work\tmp\install.log"

"=== install start $(Get-Date -Format o) ===" | Add-Content $log
$ok = $false
for ($i = 1; $i -le 12; $i++) {
    "===== attempt $i $(Get-Date -Format HH:mm:ss) =====" | Add-Content $log
    & $vpy -m pip install -e . pytest -i $idx --timeout 120 --retries 10 --progress-bar off *>> $log
    if ($LASTEXITCODE -eq 0) {
        "INSTALL OK on attempt $i" | Add-Content $log
        $ok = $true
        break
    }
    Start-Sleep -Seconds 5
}
if (-not $ok) { "INSTALL FAILED after 12 attempts" | Add-Content $log }

"=== verify ===" | Add-Content $log
& $vpy -c "import memsharness, numpy, scipy, pandas, sklearn, pint, duckdb, pyarrow, yaml, jsonschema, pytest; print('all imports OK')" *>> $log
& $vpy -m pytest --version *>> $log
Get-Content $log -Tail 10
