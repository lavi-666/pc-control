@echo off
chcp 65001 >nul
title PC Control — Автологин и автозапуск
echo =================================================================
echo    PC CONTROL - Настройка автологина Windows (UAC)
echo =================================================================
echo Запуск PowerShell от имени Администратора...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath powershell.exe -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','\"%~dp0setup_autologon.ps1\"'"
