@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 goto elevate
cd /d "%~dp0"
schtasks /create /tn "AgentMain" /tr "\"%~dp0启动.bat\"" /sc onlogon /it /f
schtasks /create /tn "AgentHW" /tr "\"%~dp0硬件监控.bat\"" /sc onlogon /rl highest /it /f
echo.
echo 好了：下次登录 Windows 时会自动启动 Agent 和硬件监控助手，不会再弹管理员确认。
echo 想取消就双击「取消开机自启.bat」。
pause
exit /b

:elevate
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b
