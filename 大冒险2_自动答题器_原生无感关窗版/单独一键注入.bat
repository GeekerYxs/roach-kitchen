@echo off
title 游戏客户端 Hook 模块注入器
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 正在请求管理员权限以注入游戏客户端...
    powershell -Command "Start-Process '%~dp0injector.exe' -Verb RunAs"
    exit /b
)

injector.exe
pause
