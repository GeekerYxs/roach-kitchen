@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -X utf8 -m factory.wipe wipe.toml %*
echo.
echo exit code %ERRORLEVEL%  (0 = all ok; report: logs\wipe_report_*.md)
pause
