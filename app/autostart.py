r"""开机自启：设置 › 自动化 里的开关。

开：在「当前用户的启动项」写一条（注册表 HKCU\Software\Microsoft\Windows\CurrentVersion\Run 里的 ExperimentAgent）：
    登录 Windows 后用 pythonw 跑 app\launch.py --autostart。不要管理员、不弹确认、没有黑窗口；和双击 启动.bat 一样会打开界面。
    依赖清单变了（刚解压了新版本）时，launch.py 改交给 启动.bat 去补装依赖。
关：删掉这一条；以前用「开机自启.bat」建的计划任务 AgentMain 也一起删（那个任务是管理员建的，删它要弹一次管理员确认）。
「开机自启.bat」「取消开机自启.bat」照样留着能用：开关认得出 bat 建的任务，两个都开着也只会起一个 Agent。
"""
import asyncio

from fastapi import APIRouter, Body, HTTPException

from . import paths

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "ExperimentAgent"
TASK = "AgentMain"                   # 开机自启.bat 建的计划任务


def command():
    w = paths.ROOT / ".venv" / "Scripts" / "pythonw.exe"
    return f'"{w}" -X utf8 "{paths.APP / "launch.py"}" --autostart'


# ---- 这几个碰 Windows 的小函数单独放，测试时换成假的 ----
def _reg_get():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, NAME)[0]
    except FileNotFoundError:
        return None


def _reg_set(v):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, v)


def _reg_del():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, NAME)
    except FileNotFoundError:
        pass


def _task_exists():
    from . import hwctl
    try:
        return hwctl._schtasks("/Query", "/TN", TASK)[0] == 0
    except Exception:
        return False


def _task_delete():
    """删 bat 建的计划任务（要管理员：弹一次确认）。点了「否」返回 False。"""
    from . import hwctl
    return hwctl._runas("schtasks.exe", f'/Delete /F /TN "{TASK}"', wait_s=30) == 0


def state():
    if not paths.IS_WIN:
        return {"ok": False, "on": False, "run": False, "task": False, "other": "", "msg": "开机自启只在 Windows 上能用"}
    v = _reg_get() or ""
    ours = bool(v) and str(paths.APP / "launch.py").lower() in v.lower()
    task = _task_exists()
    return {"ok": True, "on": ours or task, "run": ours, "task": task, "other": v if v and not ours else "", "msg": ""}


def switch(on):
    """打开 / 关掉。返回新的状态 + 一句话。"""
    st = state()
    if not st["ok"]:
        raise HTTPException(400, st["msg"])
    if on:
        if st["task"] and not st["run"]:
            return dict(st, msg="已经开着（用的是「开机自启.bat」建的计划任务）")
        _reg_set(command())
        return dict(state(), msg="开了：下次登录 Windows 自动启动 Agent（不要管理员，没有黑窗口）")
    _reg_del()
    msg = "关了：下次登录不会自动启动"
    if st["task"]:
        msg = msg + "（「开机自启.bat」建的旧任务也删了）" if _task_delete() else "启动项删了，但「开机自启.bat」建的旧任务还在：你点了「否」。再关一次，或者双击「取消开机自启.bat」"
    return dict(state(), msg=msg)


api = APIRouter()


@api.get("/api/autostart")
async def autostart_state():
    return await asyncio.to_thread(state)


@api.post("/api/autostart")
async def autostart_switch(body: dict = Body(...)):
    return await asyncio.to_thread(switch, bool(body.get("on")))
