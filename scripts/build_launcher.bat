@echo off
setlocal
cd /d "%~dp0.."
set "CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
echo Compiling Launcher.exe...
"%CSC%" /nologo /optimize+ /target:winexe /win32icon:pc_control.ico /out:Launcher.exe scripts\Launcher.cs
set "BUILD_RESULT=%ERRORLEVEL%"
if %BUILD_RESULT% neq 0 (
    echo Launcher.exe compilation failed with code %BUILD_RESULT%
    exit /b %BUILD_RESULT%
)
echo Launcher.exe successfully compiled with embedded icon!

echo Compiling Uninstall.exe...
"%CSC%" /nologo /optimize+ /target:winexe /win32icon:pc_control.ico /out:Uninstall.exe scripts\Uninstall.cs
set "UNINSTALL_RESULT=%ERRORLEVEL%"
if %UNINSTALL_RESULT% neq 0 (
    echo Uninstall.exe compilation failed with code %UNINSTALL_RESULT%
    exit /b %UNINSTALL_RESULT%
)
echo Uninstall.exe successfully compiled with embedded icon!
exit /b 0
