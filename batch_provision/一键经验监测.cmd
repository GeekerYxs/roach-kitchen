@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -X utf8 -m expwatch expwatch.toml
echo.
echo exit code %ERRORLEVEL%  (logs in %~dp0logs\expwatch_*.log, every battle in logs\expwatch\battles.csv)
pause
