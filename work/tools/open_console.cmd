@echo off
REM One-click: make sure the MEMS console is UP, then open it in the DEFAULT browser.
REM ASCII only on purpose: cmd.exe reads .cmd under the OEM codepage.
REM
REM Why this file exists (2026-09-29): the console was started detached but died a
REM minute later, so opening the URL by hand hit a closed port. This script
REM (a) probes the port, (b) starts the service if needed, (c) WAITS until the HTTP
REM API really answers, and only then (d) opens the browser.
setlocal
set REPO=C:\Users\zmx\Desktop\memsharness
set PORT=8877
set PY=%REPO%\work\.venv\Scripts\python.exe
set URL=http://127.0.0.1:%PORT%/

if not exist "%PY%" (
  echo [FAIL] python not found: %PY%
  pause
  exit /b 2
)

REM --- probe: is the HTTP API already answering? ---
"%PY%" -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:%PORT%/api/mode',timeout=2)" >nul 2>&1
if not errorlevel 1 goto ready

echo Starting MEMS console on port %PORT% ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO%\scripts\serve_detached.ps1" -Action start

set /a N=0
:wait
"%PY%" -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:%PORT%/api/mode',timeout=2)" >nul 2>&1
if not errorlevel 1 goto ready
set /a N+=1
if %N% GEQ 40 goto timeout
REM ping, not timeout /t: timeout fails when stdin is redirected
ping -n 2 127.0.0.1 >nul
goto wait

:timeout
echo [WARN] the console did not answer within ~40s. Recent log:
if exist "%REPO%\work\logs\webapp-%PORT%.log" powershell -NoProfile -Command "Get-Content '%REPO%\work\logs\webapp-%PORT%.log' -Tail 8"
echo Opening the URL anyway.
goto open

:ready
echo Console is answering on %URL%

:open
start "" "%URL%"
endlocal
