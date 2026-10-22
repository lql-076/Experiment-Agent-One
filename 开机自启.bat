@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 goto elevate
cd /d "%~dp0"
schtasks /create /tn "AgentMain" /tr "\"%~dp0启动.bat\"" /sc onlogon /it /f
rem 硬件监控助手不再单独开机自启：设置 › 硬件监控 打开后，它跟着 Agent 一起起。旧版建的任务删掉
schtasks /delete /tn "AgentHW" /f >nul 2>&1
echo.
echo 好了：下次登录 Windows 时会自动启动 Agent。硬件监控助手在 设置 › 硬件监控 打开后，会跟着 Agent 一起起。
echo 想取消就双击「取消开机自启.bat」。
pause
exit /b

:elevate
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b
