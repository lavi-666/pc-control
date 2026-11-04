@echo off
chcp 65001 >nul
cd /d "%~dp0\.."

echo ==========================================================
echo        PC CONTROL - INSTALL PYTHON DEPENDENCIES       
echo ==========================================================
echo.

set "PY_BIN=python"
if exist "venv\Scripts\python.exe" (
    set "PY_BIN=venv\Scripts\python.exe"
)

%PY_BIN% --version >nul 2>&1
if "%ERRORLEVEL%" NEQ "0" (
    echo [ERROR] Python not found on your system!
    echo Please download and install Python [3.11 or 3.12 recommended]:
    echo https://www.python.org/downloads/
    echo During installation, MAKE SURE to check the box:
    echo "Add python.exe to PATH"
    echo.
    if "%1" NEQ "--no-pause" pause
    exit /b 1
)

echo Updating pip...
%PY_BIN% -m pip install --upgrade pip

echo.
echo Installing required libraries from requirements.txt...
%PY_BIN% -m pip install -r requirements.txt
set "INSTALL_RESULT=%ERRORLEVEL%"

if "%ERRORLEVEL%" NEQ "0" (
    echo.
    echo ==========================================================
    echo [WARNING] If installation failed on the winsdk package:
    echo The winsdk wheel is officially built for Python 3.8-3.12.
    echo On Python 3.13+, pip attempts to compile via Visual Studio C++.
    echo See README.md for details and troubleshooting.
    echo ==========================================================
) else (
    echo.
    echo All dependencies installed successfully!
)

echo.
if "%1" NEQ "--no-pause" pause
exit /b %INSTALL_RESULT%
