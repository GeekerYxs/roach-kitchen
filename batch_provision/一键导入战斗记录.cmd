@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -X utf8 -m battlelog import
echo.
echo exit code %ERRORLEVEL%  (database: %~dp0logs\battlelog\battles.sqlite)
pause
