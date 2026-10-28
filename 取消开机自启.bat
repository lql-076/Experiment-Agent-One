@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 goto elevate
schtasks /delete /tn "AgentMain" /f
schtasks /delete /tn "AgentHW" /f
rem 设置 › 自动化 的「开机自启」开关写的是当前用户的启动项，也一起删
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v ExperimentAgent /f >nul 2>&1
echo 已取消开机自启。
pause
exit /b

:elevate
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b
