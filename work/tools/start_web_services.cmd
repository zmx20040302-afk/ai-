@echo off
REM MEMS Harness - start the web services ON DEMAND (ASCII only, on purpose:
REM cmd.exe reads .cmd under the OEM codepage, so non-ASCII would be mojibake).
REM
REM Double-click this file, or run it from a terminal, when you want the
REM console/dashboard. Nothing is resident by default: no logon autostart,
REM no scheduled task, no watchdog.
setlocal
set REPO=C:\Users\zmx\Desktop\memsharness
echo Starting MEMS Harness web services on demand...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO%\scripts\serve_detached.ps1" -Action start
echo.
echo   Chat console   http://127.0.0.1:8877/
echo   Dashboard      http://127.0.0.1:8899/
echo.
echo To stop them:
echo   powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO%\scripts\serve_detached.ps1" -Action stop
echo.
echo This window closes in 8 seconds.
REM Use ping as the delay: `timeout /t` fails ("Input redirection is not supported")
REM whenever stdin is redirected (e.g. launched from a script/CI), ping never does.
ping -n 9 127.0.0.1 >nul
endlocal
