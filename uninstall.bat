@echo off
chcp 65001 >nul
cd /d "%~dp0"
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
if exist "%LOCALAPPDATA%\PCControl" (
    rmdir /s /q "%LOCALAPPDATA%\PCControl" >nul 2>&1
    echo   - Папка %%LOCALAPPDATA%%\PCControl успешно удалена.
) else (
    echo   - Папка %%LOCALAPPDATA%%\PCControl не найдена.
)

:clean_firewall
echo.
echo [3/4] Удаление правила брандмауэра Windows...
net session >nul 2>&1
if errorlevel 1 (
    if not defined PC_CONTROL_NO_PAUSE (
        "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "Start-Process -FilePath 'cmd.exe' -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList '/c netsh advfirewall firewall delete rule name=\"PC Control Server\" >nul 2>&1 & netsh advfirewall firewall delete rule name=\"PC Control WOL Relay\" >nul 2>&1 & netsh advfirewall firewall delete rule name=\"PC Control Server (TCP 5000)\" >nul 2>&1'" >nul 2>&1
    ) else (
        echo   [!] Run uninstall.bat as Administrator to remove firewall rules.
    )
) else (
    netsh advfirewall firewall delete rule name="PC Control Server" >nul 2>&1
    netsh advfirewall firewall delete rule name="PC Control WOL Relay" >nul 2>&1
    netsh advfirewall firewall delete rule name="PC Control Server (TCP 5000)" >nul 2>&1
)
if "%choice%"=="3" (
    echo   - Правило брандмауэра удалено.
    goto :done
)

echo.
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PC_Control_Server.lnk" >nul 2>&1
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
if exist "%LOCALAPPDATA%\PCControl" (
    rmdir /s /q "%LOCALAPPDATA%\PCControl" >nul 2>&1
    echo - Кэш и профили браузеров в %%LOCALAPPDATA%%\PCControl очищены!
) else (
    echo - Папка %%LOCALAPPDATA%%\PCControl не существует или уже очищена.
)
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
