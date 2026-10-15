@echo off
title 大冒险2.0 自动答题器 (原生无感关窗版)
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 正在请求管理员权限以注入游戏客户端...
    powershell -Command "Start-Process '%~dp0启动答题器.exe' -Verb RunAs"
    exit /b
)

echo ===============================================================================
echo   正在启动: 《什么什么大冒险2.0》自动答题与原生无感关窗辅助
echo   - 独立免安装版: 无需 Python, 无需任何第三方运行环境
echo   - 自动检测并多开注入 WAATClient.exe
echo   - 221 道精选离线题库 + 原生 CloseDialog 瞬间销毁答题弹窗
echo ===============================================================================
echo.
"%~dp0启动答题器.exe"
pause
