@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "runtime\python.exe" (
    "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "scripts\bootstrap_runtime.ps1"
    if errorlevel 1 exit /b 1
)
"runtime\python.exe" -E -s "scripts\manage_server.py" stop
exit /b %ERRORLEVEL%
