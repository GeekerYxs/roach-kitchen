@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist bin\launcher.exe powershell -NoProfile -ExecutionPolicy Bypass -File native\build.ps1
python -X utf8 -m factory.guard supervisor.toml
echo.
echo exit code %ERRORLEVEL%  (logs in %~dp0logs\guard_*.log and supervisor_*.log)
pause
