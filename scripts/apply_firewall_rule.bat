@echo off
chcp 65001 >nul
cd /d "%~dp0\.."

net session >nul 2>&1
if errorlevel 1 (
    echo Запрос прав администратора...
    set "SELF_BAT=%~f0"
    "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "Start-Process -FilePath $env:SELF_BAT -Verb RunAs"
    exit /b
)

title PC Control - Настройка брандмауэра Windows

set "SRV_PORT=5000"
set "RELAY_PORT=5050"
for /f "usebackq delims=" %%p in (`"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "try { $c = Get-Content -LiteralPath 'config.json' -Raw -Encoding UTF8 | ConvertFrom-Json; if ($c.port) { $c.port } else { 5000 } } catch { 5000 }"`) do set "SRV_PORT=%%p"
for /f "usebackq delims=" %%p in (`"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "try { $c = Get-Content -LiteralPath 'config.json' -Raw -Encoding UTF8 | ConvertFrom-Json; if ($c.relay_port) { $c.relay_port } else { 5050 } } catch { 5050 }"`) do set "RELAY_PORT=%%p"

echo =================================================================
echo    PC CONTROL - Настройка правил брандмауэра Windows [TCP %SRV_PORT%]
echo =================================================================
echo.

netsh advfirewall firewall delete rule name="PC Control Server" >nul 2>&1
netsh advfirewall firewall delete rule name="PC Control WOL Relay" >nul 2>&1

set "FW_OK=1"
netsh advfirewall firewall add rule name="PC Control Server" dir=in action=allow protocol=TCP localport=%SRV_PORT% profile=any remoteip=LocalSubnet,100.64.0.0/10 >nul
if errorlevel 1 set "FW_OK=0"
netsh advfirewall firewall add rule name="PC Control WOL Relay" dir=in action=allow protocol=TCP localport=%RELAY_PORT% profile=any remoteip=LocalSubnet,100.64.0.0/10 >nul
if errorlevel 1 set "FW_OK=0"

if "%FW_OK%"=="1" (
    echo [OK] Порты %SRV_PORT% и %RELAY_PORT% открыты только для домашней сети и Tailscale.
) else (
    echo [ОШИБКА] Не удалось применить правила брандмауэра.
)
echo.
echo =================================================================
echo [ГОТОВО / DONE] Окно закроется автоматически через 3 секунды...
echo =================================================================
if not defined PC_CONTROL_NO_PAUSE timeout /t 3 >nul 2>&1
if "%FW_OK%"=="1" exit /b 0
exit /b 1
