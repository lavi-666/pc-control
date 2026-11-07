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

set "SRV_PORT=5000"
set "REL_PORT=5050"
set "PY_EXE=%BASE_DIR%\runtime\python.exe"

:: Читаем порты и фиксируем исходное состояние правил брандмауэра в журнале состояния
if exist "%PY_EXE%" (
    "%PY_EXE%" -E -s -c "import json, pathlib, sys; sys.path.insert(0, r'%BASE_DIR%'); cfg_f = pathlib.Path(r'%BASE_DIR%') / 'config.json'; cfg = json.loads(cfg_f.read_text('utf-8')) if cfg_f.is_file() else {}; sp = int(cfg.get('port', 5000) or 5000); rp = int(cfg.get('relay_port', 5050) or 5050); from core.system_state import capture_firewall_before_change; capture_firewall_before_change(sp, rp)" >nul 2>&1
)

for /f "usebackq tokens=1,2 delims=," %%a in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$sp = 5000; $rp = 5050; $cfg = Join-Path $env:BASE_DIR 'config.json'; if (Test-Path -LiteralPath $cfg) { try { $j = Get-Content -LiteralPath $cfg -Raw -Encoding UTF8 | ConvertFrom-Json; if ($j.port) { $sp = [int]$j.port }; if ($j.relay_port) { $rp = [int]$j.relay_port } } catch {} }; Write-Output ($sp.ToString() + ',' + $rp.ToString())"`) do (
    if not "%%a"=="" set "SRV_PORT=%%a"
    if not "%%b"=="" set "REL_PORT=%%b"
)

echo Добавление правил Брандмауэра для PC Control Server (порт %SRV_PORT%) и WOL Relay (порт %REL_PORT%)...
netsh advfirewall firewall delete rule name="PC Control Server" >nul 2>&1
netsh advfirewall firewall add rule name="PC Control Server" dir=in action=allow protocol=TCP localport=%SRV_PORT% profile=any remoteip=LocalSubnet,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,100.64.0.0/10
if %errorlevel% neq 0 exit /b %errorlevel%

netsh advfirewall firewall delete rule name="PC Control WOL Relay" >nul 2>&1
netsh advfirewall firewall add rule name="PC Control WOL Relay" dir=in action=allow protocol=TCP localport=%REL_PORT% profile=any remoteip=LocalSubnet,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,100.64.0.0/10
if %errorlevel% neq 0 exit /b %errorlevel%

echo.
echo [OK] Порты %SRV_PORT% и %REL_PORT% успешно открыты для локальной сети Wi-Fi и Tailscale!
if not defined PC_CONTROL_NO_PAUSE pause
