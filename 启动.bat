@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Agent
set "PYTHONUTF8=1"
rem pip 的下载缓存放在 Agent 文件夹里，不往 C 盘用户目录写
set "PIP_CACHE_DIR=%~dp0tools\cache\pip"
set "PY="
py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not defined PY py -3.13 -c "import sys" >nul 2>nul && set "PY=py -3.13"
if not defined PY python -c "import sys;sys.exit(0 if sys.version_info>=(3,12) else 1)" >nul 2>nul && set "PY=python"
if exist ".venv\Scripts\python.exe" goto deps
if not defined PY goto nopy
echo 第一次运行：正在创建环境、安装依赖，大约 1 分钟……
%PY% -m venv .venv
if errorlevel 1 goto nopy
".venv\Scripts\python.exe" -m pip install -U pip >nul

:deps
rem 依赖清单变了（比如更新了新版本）才重新装，平时直接跳过
fc /b requirements.txt ".venv\requirements.done" >nul 2>nul
if not errorlevel 1 goto run
echo 正在安装或更新依赖……
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 goto pipfail
copy /y requirements.txt ".venv\requirements.done" >nul

:run
set "AGENT_OPEN_UI=1"
if /i "%~1"=="log" goto console
if "%~1"=="看日志" goto console
if not exist ".venv\Scripts\pythonw.exe" goto console
rem 平时：用 pythonw 在后台跑，不留黑窗口。起不来会弹框说原因；说的话都在 data\logs\backend.log（界面「后台」页也能看）
start "" ".venv\Scripts\pythonw.exe" -m app.launch
exit

:console
rem 排查问题用：在这个黑窗口里跑，直接看输出。在 Agent 文件夹打开命令行，运行「启动.bat 看日志」就进这里
".venv\Scripts\python.exe" -m app.main
rem 10 = 已经在运行（刚帮你把界面拿出来了）；11 = 你在界面上点了「退出 Agent」：这两种都直接关掉这个黑窗口
if errorlevel 10 exit
echo.
echo Agent 已停止。关掉这个窗口就行。
pause
exit /b

:nopy
echo 没找到 Python 3.12。先装 Python 3.12，安装第一页勾选 Add python.exe to PATH，再双击本文件。
echo 官网：https://www.python.org/downloads/windows/
echo 国内镜像：https://registry.npmmirror.com/binary.html?path=python/
pause
exit /b

:pipfail
echo 依赖没装上，多半是网络问题。过一会再双击一次（已经装好的部分不会丢）。
".venv\Scripts\python.exe" -c "import fastapi,uvicorn,httpx,psutil,numpy" >nul 2>nul
if errorlevel 1 goto stop
echo 基础依赖是好的，先照旧启动（界面可能会用 Edge 窗口打开）。
goto run

:stop
pause
exit /b
