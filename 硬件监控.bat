@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 平时不用双击这个：在 Agent 的 设置 › 硬件监控 打开就行（不弹黑窗口，第一次确认一次管理员，之后跟着 Agent 自己起）。
rem 这个文件留着手动启动用：用管理员身份在后台起硬件监控助手（pythonw，没有黑窗口），说的话写在 data\logs\hw_helper.log。
if not exist ".venv\Scripts\pythonw.exe" goto first
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath '%~dp0.venv\Scripts\pythonw.exe' -ArgumentList '%~dp0app\hw_helper.py' -WorkingDirectory '%~dp0' -Verb RunAs"
exit /b

:first
echo 先双击一次「启动.bat」，装好基础环境后再运行本文件。
pause
exit /b
