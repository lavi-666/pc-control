@echo off
chcp 65001 >nul
title PC Control — Автологин и автозапуск
echo =================================================================
echo    PC CONTROL - Настройка автологина Windows (UAC)
echo =================================================================
echo Запуск PowerShell от имени Администратора...
set "PS_SCRIPT=%~dp0setup_autologon.ps1"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe' -Verb RunAs -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',(\"`\"\" + $env:PS_SCRIPT + \"`\"\"))"
