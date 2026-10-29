@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -X utf8 -m battlelog live battlelog.toml
echo.
echo exit code %ERRORLEVEL%
pause
