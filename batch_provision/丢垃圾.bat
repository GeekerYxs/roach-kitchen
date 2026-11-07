@echo off
rem Junk-drop watcher, one per PC (research/shitu/junk_watch.py). Close this window to stop.
chcp 65001 >nul
cd /d "%~dp0"
python -X utf8 research\shitu\junk_watch.py %*
pause
