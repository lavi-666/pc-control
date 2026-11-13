@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "%~dp0Uninstall.exe" (
    if "%~1"=="" (
        start "" "%~dp0Uninstall.exe"
        exit /b 0
    ) else (
        "%~dp0Uninstall.exe" %*
        exit /b %ERRORLEVEL%
    )
)

title PC Control — Деинсталляция и очистка кэша
echo ======================================================================
echo             PC CONTROL — ДЕИНСТАЛЛЯЦИЯ И ОЧИСТКА СИСТЕМЫ             
echo ======================================================================
echo.
echo Выберите действие:
echo   [1] Полная деинсталляция (остановка процессов, очистка кэша браузеров,
echo       удаление правил брандмауэра Windows и временных логов)
echo   [2] Очистить только профили браузеров (%%LOCALAPPDATA%%\PCControl)
echo   [3] Удалить только правило брандмауэра для порта 5000
echo   [4] Отмена
echo.
set "choice=%~1"
if "%choice%"=="" set /p "choice=Введите номер действия (1-4): "

if "%choice%"=="4" goto :cancel
if "%choice%"=="3" goto :clean_firewall
if "%choice%"=="2" goto :clean_profiles
if "%choice%"=="1" goto :full_uninstall
goto :cancel

:full_uninstall
echo.
echo [1/4] Завершение запущенных процессов PC Control...
cd /d "%~dp0"
if not exist "logs" mkdir "logs" >nul 2>&1
echo manual_stop> "logs\manual_stop.flag"
if not exist "runtime\python.exe" (
    echo [ERROR] Private runtime missing. Cannot safely stop application processes.
    exit /b 1
)
"runtime\python.exe" -E -s scripts\manage_server.py stop-all
if errorlevel 1 exit /b 1
echo   - Процессы остановлены.

echo.
echo [2/4] Очистка профилей и кэша браузеров (%%LOCALAPPDATA%%\PCControl)...
rem QA L-6: only the browser profiles / cache of THIS installation - %%LOCALAPPDATA%%\PCControl also holds
rem the shared system-state journal of other PC Control installations.
"runtime\python.exe" -E -s scripts\manage_server.py clean-profiles
echo   - Профили и кэш браузеров очищены.

:clean_firewall
echo.
echo [3/4] Удаление правила брандмауэра Windows...
net session >nul 2>&1
if errorlevel 1 (
    if not defined PC_CONTROL_NO_PAUSE (
        rem QA L-6: firewall_rules.ps1 -Remove deletes only this installation's rules (its ports / programs)
        "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0scripts\firewall_rules.ps1','-Remove'" >nul 2>&1
    ) else (
        echo   [!] Run uninstall.bat as Administrator to remove firewall rules.
    )
) else (
    set "BASE_DIR=%~dp0."
    "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\firewall_rules.ps1" -Remove >nul 2>&1
)
if "%choice%"=="3" (
    echo   - Правило брандмауэра удалено.
    goto :done
)

echo.
rem QA L-5/L-6: the Startup shortcut is removed only if it starts THIS installation
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "$l = Join-Path ([Environment]::GetFolderPath('Startup')) 'PC_Control_Server.lnk'; if (Test-Path -LiteralPath $l) { $s = (New-Object -ComObject WScript.Shell).CreateShortcut($l); $d = (Resolve-Path -LiteralPath '%~dp0.').Path.TrimEnd('\') + '\'; if (($s.TargetPath + ' ' + $s.Arguments).IndexOf($d, [StringComparison]::OrdinalIgnoreCase) -ge 0) { Remove-Item -LiteralPath $l -Force } }" >nul 2>&1
echo [4/4] Удаление временных логов и кэша Python...
if exist "logs" (
    del /f /q "logs\*.flag" >nul 2>&1
    del /f /q "logs\*.log" >nul 2>&1
)
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" >nul 2>&1
echo   - Временные файлы удалены.
goto :done

:clean_profiles
echo.
echo Очистка профилей браузеров...
"runtime\python.exe" -E -s scripts\manage_server.py clean-profiles
echo - Кэш и профили браузеров этой установки очищены.
goto :done

:cancel
echo.
echo Операция отменена пользователем.
goto :exit

:done
echo.
echo ======================================================================
echo Операция успешно завершена!
echo ======================================================================

:exit
echo.
if not defined PC_CONTROL_NO_PAUSE pause
