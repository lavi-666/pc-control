@echo off
chcp 65001 >nul
title PC Control — Запуск сервера
cd /d "%~dp0\.."

if "%1"=="--silent" goto run_silent
if "%1"=="/silent" goto run_silent

echo =================================================================
echo                    PC CONTROL - ЗАПУСК СЕРВЕРА
echo =================================================================
echo.

if exist "logs\manual_stop.flag" del /f /q "logs\manual_stop.flag"

echo [1/2] Запуск сервера PC Control в фоновом режиме (порт 5000)...
if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" server.py
    start "" "venv\Scripts\pythonw.exe" scripts\watchdog.pyw
) else (
    start "" pythonw server.py
    start "" pythonw scripts\watchdog.pyw
)
echo [2/2] Сторожевой процесс (watchdog) активирован.
echo.
echo =================================================================
echo [ГОТОВО] Сервер успешно запущен и работает в фоне.
echo Для управления сервером используйте Launcher.exe.
echo =================================================================
timeout /t 3 >nul 2>&1
exit /b 0

:run_silent
if exist "logs\manual_stop.flag" del /f /q "logs\manual_stop.flag"
if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" server.py
    start "" "venv\Scripts\pythonw.exe" scripts\watchdog.pyw
) else (
    start "" pythonw server.py
    start "" pythonw scripts\watchdog.pyw
)
exit /b 0
