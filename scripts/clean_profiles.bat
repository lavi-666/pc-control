@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist "runtime\python.exe" (
    echo Private runtime missing. Run Launcher.exe first.
    exit /b 1
)
"runtime\python.exe" -E -s scripts\manage_server.py clean-profiles
exit /b %ERRORLEVEL%
