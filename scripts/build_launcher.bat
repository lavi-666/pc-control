@echo off
setlocal
cd /d "%~dp0.."
set "CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
"%CSC%" /nologo /optimize+ /target:winexe /win32icon:pc_control.ico /out:Launcher.exe scripts\Launcher.cs
set "BUILD_RESULT=%ERRORLEVEL%"
if %ERRORLEVEL% equ 0 (
    echo Launcher.exe successfully compiled with embedded icon!
) else (
    echo Compilation failed with code %ERRORLEVEL%
)
exit /b %BUILD_RESULT%
