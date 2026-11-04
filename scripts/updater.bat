@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

set "BASE_DIR=%~1"
if "%BASE_DIR%"=="" set "BASE_DIR=%~dp0.."
set "TARGET_EXE=%BASE_DIR%\Launcher.exe"
set "NEW_EXE=%BASE_DIR%\Launcher.exe.new"
set "OLD_EXE=%BASE_DIR%\Launcher.exe.old"
set "PARENT_PID=%~2"

echo [PC Control Updater] Starting update process...

:: 1. If PID is provided, wait for parent process to terminate
if not "%PARENT_PID%"=="" (
    for /L %%i in (1,1,30) do (
        tasklist /FI "PID eq %PARENT_PID%" 2>nul | findstr /i "%PARENT_PID%" >nul
        if errorlevel 1 goto :proc_done
        timeout /t 1 /nobreak >nul
    )
)
:proc_done
timeout /t 1 /nobreak >nul

:: 2. Ensure new exe exists
if not exist "%NEW_EXE%" (
    echo [PC Control Updater] Error: New executable not found at "%NEW_EXE%".
    exit /b 1
)

:: 3. Replace executable with retry loop
set RETRIES=0
:retry_swap
set /a RETRIES+=1
if exist "%TARGET_EXE%" (
    if exist "%OLD_EXE%" del /f /q "%OLD_EXE%" >nul 2>&1
    move /y "%TARGET_EXE%" "%OLD_EXE%" >nul 2>&1
    if errorlevel 1 goto :swap_failed
)

move /y "%NEW_EXE%" "%TARGET_EXE%" >nul 2>&1
if errorlevel 1 goto :swap_failed
goto :swap_done

:swap_failed
if %RETRIES% lss 10 (
    timeout /t 1 /nobreak >nul
    goto :retry_swap
)
echo [PC Control Updater] Failed to place new executable. Restoring backup...
if not exist "%TARGET_EXE%" if exist "%OLD_EXE%" move /y "%OLD_EXE%" "%TARGET_EXE%" >nul 2>&1
exit /b 2

:swap_done

:: 4. Clean up backup old exe
if exist "%OLD_EXE%" del /f /q "%OLD_EXE%" >nul 2>&1

:: 5. Launch the updated Launcher.exe
echo [PC Control Updater] Starting updated Launcher.exe...
start "" "%TARGET_EXE%"

exit /b 0
