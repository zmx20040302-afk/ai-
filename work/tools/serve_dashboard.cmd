@echo off
REM MEMS platform - static dashboard (port 8899). ASCII only on purpose.
REM NOTE (2026-10-01): launched with pythonw.exe (NO console) via `start /b /wait`
REM so that a console control event (^C / window close) cannot kill the service.
REM Same reasoning as serve_console.cmd -- see the note there.
setlocal
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
set REPO=C:\Users\zmx\Desktop\memsharness
set PYW=%REPO%\work\.venv\Scripts\pythonw.exe
if not exist "%PYW%" set PYW=%REPO%\work\.venv\Scripts\python.exe
cd /d "%REPO%"
if not exist "%REPO%\work\logs" mkdir "%REPO%\work\logs"
echo [%DATE% %TIME%] starting static dashboard on 8899 (pythonw, no console) >> "%REPO%\work\logs\dashboard-8899.log"
start "" /b /wait "%PYW%" -B -m http.server 8899 --bind 127.0.0.1 --directory "%REPO%\work\reports\mems-dashboard" >> "%REPO%\work\logs\dashboard-8899.log" 2>&1
echo [%DATE% %TIME%] dashboard exited with %ERRORLEVEL% >> "%REPO%\work\logs\dashboard-8899.log"
endlocal
