@echo off
chcp 65001 >nul
setlocal
set "BASE_DIR=%~dp0.."
for %%I in ("%BASE_DIR%") do set "BASE_DIR=%%~fI"

:: Проверка прав администратора
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Запрос прав администратора для настройки Брандмауэра Windows...
    "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "PY_EXE=%BASE_DIR%\runtime\python.exe"

:: Фиксируем исходное состояние правил брандмауэра в журнале состояния (для деинсталлятора)
if exist "%PY_EXE%" (
    "%PY_EXE%" -E -s -c "import json, pathlib, sys; sys.path.insert(0, r'%BASE_DIR%'); cfg_f = pathlib.Path(r'%BASE_DIR%') / 'config.json'; cfg = json.loads(cfg_f.read_text('utf-8')) if cfg_f.is_file() else {}; sp = int(cfg.get('port', 5000) or 5000); rp = int(cfg.get('relay_port', 5050) or 5050); from core.system_state import capture_firewall_before_change; capture_firewall_before_change(sp, rp)" >nul 2>&1
)

echo Настройка правил брандмауэра Windows для PC Control...
:: Путь передаётся через переменную окружения BASE_DIR: так кириллица и пробелы в пути не ломаются.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0firewall_rules.ps1"
set "FW_RESULT=%errorlevel%"
if %FW_RESULT% neq 0 (
    echo [ERROR] Не удалось настроить брандмауэр (код %FW_RESULT%).
    if not defined PC_CONTROL_NO_PAUSE pause
    exit /b %FW_RESULT%
)

echo.
echo [OK] Брандмауэр настроен: телефон может подключаться по Wi-Fi и через Tailscale.
if not defined PC_CONTROL_NO_PAUSE pause
