@echo off
REM MEMS platform - chat console (port 8877). ASCII only on purpose:
REM .cmd is read by cmd.exe under the OEM codepage, so keep it ASCII.
REM
REM NOTE (2026-10-01): the server is launched with pythonw.exe (NO console) via
REM `start /b /wait`, NOT with python.exe inside this console. Reason (measured):
REM webapp-8877.log ended with a literal ^C right after a start, i.e. the server
REM was killed by a CONSOLE control event (Ctrl+C / window close). Being detached
REM from DSH's Job only protects against DSH restarts -- it does NOT protect a
REM console child from console events. With pythonw there is no console to hit.
REM `start /wait` keeps the "exited with N" line truthful (it logs when pythonw
REM really exits, and ERRORLEVEL is the child's exit code).
setlocal
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
set PYTHONPYCACHEPREFIX=%TEMP%\memscache
set REPO=C:\Users\zmx\Desktop\memsharness
set PYW=%REPO%\work\.venv\Scripts\pythonw.exe
if not exist "%PYW%" set PYW=%REPO%\work\.venv\Scripts\python.exe
cd /d "%REPO%"
if not exist "%REPO%\work\logs" mkdir "%REPO%\work\logs"
echo [%DATE% %TIME%] starting webapp_server on 8877 (pythonw, no console) >> "%REPO%\work\logs\webapp-8877.log"
start "" /b /wait "%PYW%" -B "%REPO%\scripts\webapp_server.py" --port 8877 >> "%REPO%\work\logs\webapp-8877.log" 2>&1
echo [%DATE% %TIME%] webapp_server exited with %ERRORLEVEL% >> "%REPO%\work\logs\webapp-8877.log"
endlocal
