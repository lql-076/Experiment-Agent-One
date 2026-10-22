@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 安装本地模型环境
if not exist ".venv\Scripts\python.exe" goto first
set "PYTHONUTF8=1"
".venv\Scripts\python.exe" scripts\install_ai.py
echo.
pause
exit /b

:first
echo 先双击一次「启动.bat」，装好基础环境后再运行本文件。
pause
exit /b
