@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 goto elevate
cd /d "%~dp0"
title 硬件监控助手（管理员）
if not exist ".venv\Scripts\python.exe" goto first
set "PYTHONUTF8=1"
".venv\Scripts\python.exe" app\hw_helper.py
pause
exit /b

:elevate
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:first
echo 先双击一次「启动.bat」，装好基础环境后再运行本文件。
pause
exit /b
