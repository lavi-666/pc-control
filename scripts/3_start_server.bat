@echo off
call "%~dp0..\start_server.bat" %*
exit /b %ERRORLEVEL%
