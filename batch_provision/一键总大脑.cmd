@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist bin\launcher.exe powershell -NoProfile -ExecutionPolicy Bypass -File native\build.ps1
python -X utf8 -m factory.supervisor supervisor.toml
echo.
echo exit code %ERRORLEVEL%  (logs in %~dp0logs\supervisor_*.log)
pause
