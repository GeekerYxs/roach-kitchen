@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -X utf8 -m factory.coast factory.toml
echo.
echo exit code %ERRORLEVEL%  (0 = all ok; logs in %~dp0logs)
pause
