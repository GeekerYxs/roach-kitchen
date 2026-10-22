@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -X utf8 -m factory.unquarantine %*
echo.
echo exit code %ERRORLEVEL%  (0 = all ok; logs in %~dp0logs\unquarantine_*.log)
pause
