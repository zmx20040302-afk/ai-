@echo off
REM MEMS Harness - start the resident web services at user logon (ASCII only).
REM Copied into the per-user Startup folder by scripts\install_web_services_task.ps1.
REM Recipe: Task Scheduler logon triggers need admin (/sc onlogon => Access denied),
REM so logon autostart uses the per-user Startup folder instead; the repeating
REM scheduled task (every N minutes) additionally self-heals after a crash or reboot.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\zmx\Desktop\memsharness\scripts\serve_detached.ps1" -Action start
endlocal
