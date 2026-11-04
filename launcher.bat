@echo off
chcp 65001 >nul
cd /d "%~dp0"
title PC Control - Панель управления

if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" scripts\control_panel.py %*
    exit /b %ERRORLEVEL%
)

python --version >nul 2>&1
if errorlevel 1 (
    echo ==========================================================
    echo [ОШИБКА] Python не найден в вашей системе!
    echo Скачайте и установите Python [рекомендуется 3.11 или 3.12]:
    echo https://www.python.org/downloads/
    echo Обязательно отметьте пункт: "Add python.exe to PATH"
    echo ==========================================================
    pause
    exit /b 1
)

python scripts\control_panel.py %*
