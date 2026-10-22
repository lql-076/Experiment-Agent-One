@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 下载模型
if not exist ".venv\Scripts\python.exe" goto first
set "PYTHONUTF8=1"
".venv\Scripts\python.exe" scripts\download_models.py
echo.
pause
exit /b

:first
echo 先双击一次「启动.bat」，装好基础环境后再运行本文件。
pause
exit /b
