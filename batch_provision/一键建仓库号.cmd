@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist bin\launcher.exe powershell -NoProfile -ExecutionPolicy Bypass -File native\build.ps1
python -X utf8 -m factory.store store.toml
echo.
echo exit code %ERRORLEVEL%  (0 = all ok; logs in %~dp0logs\store_*.log)
pause
