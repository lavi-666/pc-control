@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "runtime\python.exe" (
    "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "scripts\bootstrap_runtime.ps1"
    if errorlevel 1 exit /b 1
)
:: autostart: при входе в Windows ждёт готовности системы и повторяет попытки несколько минут.
:: Работает в фоне через pythonw.exe (без окна консоли), окно задания закрывается сразу.
:: Ход и результат каждой попытки - в logs\autostart.log.
start "" "runtime\pythonw.exe" -E -s "scripts\manage_server.py" autostart
if errorlevel 1 exit /b 1
echo PC Control: server start continues in the background. Log: logs\autostart.log
exit /b 0
