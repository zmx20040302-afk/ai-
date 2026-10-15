@echo off
REM MEMS platform LAN console. ASCII only for cmd.exe compatibility.
setlocal
set "REPO=%~dp0..\.."
set "PY=%REPO%\work\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%REPO%\..\..\runtime\python312\python.exe"
if not exist "%PY%" (
  echo ERROR: Python runtime was not found. Create work\.venv first.
  pause
  exit /b 1
)
cd /d "%REPO%"
echo Starting the authenticated MEMS console for trusted LAN devices...
echo Keep this window open. Copy one printed URL to the other computer.
echo.
"%PY%" -B "%REPO%\scripts\webapp_server.py" --lan --port 8877
echo.
echo The MEMS LAN console has stopped.
pause
endlocal
