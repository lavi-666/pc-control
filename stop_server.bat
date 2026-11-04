@echo off
chcp 65001 >nul
title PC Control — Остановка сервера
cd /d "%~dp0"
echo =================================================================
echo        PC CONTROL - Остановка сервера и сторожевого процесса
echo =================================================================
echo.

if not exist "logs" mkdir "logs"
echo manual_stop > "logs\manual_stop.flag"

echo [1/2] Завершение процесса сервера (порт 5000)...
for /f "tokens=5" %%a in ('netstat -ano -p tcp ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    echo   Завершение PID %%a...
    taskkill /PID %%a /F >nul 2>&1
)

echo [2/2] Остановка фонового сторожевого процесса (watchdog)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*watchdog.pyw*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo.
echo =================================================================
echo [ГОТОВО] Сервер и служба наблюдения полностью остановлены.
echo Автоперезапуск отключен до следующего запуска сервера.
echo Нажмите Enter, чтобы закрыть это окно...
echo =================================================================
pause >nul
