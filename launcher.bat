@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "Launcher.exe" (
    start "" "Launcher.exe" %*
    exit /b 0
)
echo Launcher.exe is missing. Extract the complete PC Control ZIP.
exit /b 1
