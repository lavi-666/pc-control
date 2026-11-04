@echo off
chcp 65001 >nul
cd /d "%~dp0\.."

if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" scripts\change_password.py %*
) else (
    python scripts\change_password.py %*
)

echo.
pause
