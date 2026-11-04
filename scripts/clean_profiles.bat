@echo off
chcp 65001 >nul
title PC Control — Очистка профилей браузеров
echo ======================================================================
echo          ОЧИСТКА ВРЕМЕННЫХ ПРОФИЛЕЙ БРАУЗЕРОВ PC CONTROL             
echo ======================================================================
echo.
echo Удаление профилей из %%LOCALAPPDATA%%\PCControl...
if exist "%LOCALAPPDATA%\PCControl" (
    rmdir /s /q "%LOCALAPPDATA%\PCControl" >nul 2>&1
    echo [OK] Профили браузеров (Edge / Chrome) успешно очищены.
) else (
    echo [INFO] Папка %%LOCALAPPDATA%%\PCControl уже чиста.
)
echo.
pause
