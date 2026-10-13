@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist bin\launcher.exe powershell -NoProfile -ExecutionPolicy Bypass -File native\build.ps1
python -X utf8 -m factory.relay relay.toml
echo.
echo exit code %ERRORLEVEL%  (0 = all ok; per-role results in %~dp0state\relay, logs in %~dp0logs)
pause
