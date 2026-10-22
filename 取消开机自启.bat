@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 goto elevate
schtasks /delete /tn "AgentMain" /f
schtasks /delete /tn "AgentHW" /f
echo 已取消开机自启。
pause
exit /b

:elevate
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b
