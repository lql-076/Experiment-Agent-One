r"""硬件监控助手的开和关（设置 › 硬件监控 的开关、一键补齐第 6 步、后台照看都走这里）。

助手要管理员权限才读得到 CPU 温度、功耗和游戏帧数。为了不每次都弹管理员确认，也不留黑窗口：
1. 第一次打开时，用管理员身份（弹一次确认，点「是」）在 Windows 计划任务里登记一个任务 ExperimentAgent-HwHelper：
   用 pythonw 跑 app\hw_helper.py（pythonw 没有黑窗口），"使用最高权限"，不限运行时长。
2. 以后启动：schtasks /Run 这个任务，Windows 直接用管理员权限起它，不再弹确认。
3. 关：POST 127.0.0.1:8085/quit（带 X-Agent 头）让它自己退；退不掉再 schtasks /End。
登记不上（你没点「是」、公司电脑不让建计划任务）就退回老办法：每次用管理员身份直接起 pythonw（每次弹一次确认）。
只停自己开的这个助手，不按名字杀任何进程。
"""
import asyncio
import ctypes
import os
import subprocess
import time
from xml.sax.saxutils import escape

import httpx

from . import feed, paths, settings
from .models import NOWIN

TASK = "ExperimentAgent-HwHelper"
ST = {"busy": False, "msg": "", "fail_ts": 0.0, "last_try": 0.0}


def pythonw():
    w = paths.ROOT / ".venv" / "Scripts" / "pythonw.exe"
    return w if w.exists() else paths.ROOT / ".venv" / "Scripts" / "python.exe"


def script():
    return paths.APP / "hw_helper.py"


def _base():
    u = str(settings.S.get("hwUrl") or "http://127.0.0.1:8085/data.json")
    return u.rsplit("/", 1)[0]


async def running() -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.2) as c:
            r = await c.get(settings.S["hwUrl"])
            return r.status_code == 200
    except Exception:
        return False


def _schtasks(*args, timeout=20):
    r = subprocess.run(["schtasks", *args], capture_output=True, text=True, timeout=timeout, encoding="mbcs" if paths.IS_WIN else "utf-8",
                       errors="replace", creationflags=NOWIN)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


_TASK = {"ts": 0.0, "v": False}


def task_exists(fresh=False) -> bool:
    """登记过计划任务没有（查一次要几十毫秒，界面轮询用 30 秒缓存）。"""
    if not paths.IS_WIN:
        return False
    if not fresh and time.time() - _TASK["ts"] < 30:
        return _TASK["v"]
    try:
        v = _schtasks("/Query", "/TN", TASK)[0] == 0
    except Exception:
        v = False
    _TASK.update(ts=time.time(), v=v)
    return v


def _task_xml():
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip("\\")
    uid = f"<UserId>{escape(user)}</UserId>" if user else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Experiment Agent 的硬件监控助手：读 CPU 温度、功耗和游戏帧数。由 Agent 设置 › 硬件监控 开关；删掉这个任务不影响别的。</Description></RegistrationInfo>
  <Principals><Principal id="Author">{uid}<LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(pythonw()))}</Command>
      <Arguments>"{escape(str(script()))}"</Arguments>
      <WorkingDirectory>{escape(str(paths.ROOT))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _runas(exe, params, wait_s=90):
    """用管理员身份运行（弹一次确认）。等它结束，返回退出码；你点了「否」返回 None。"""
    from ctypes import wintypes

    class SEI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    sei = SEI()
    sei.cbSize = ctypes.sizeof(SEI)
    sei.fMask = 0x40 | 0x8000                     # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE
    sei.hwnd = ctypes.windll.user32.GetForegroundWindow()
    sei.lpVerb, sei.lpFile, sei.lpParameters, sei.lpDirectory = "runas", str(exe), params, str(paths.ROOT)
    sei.nShow = 0                                 # SW_HIDE：不出黑窗口
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        return None                               # 多半是你点了「否」
    if not sei.hProcess:
        return 0
    k32 = ctypes.windll.kernel32
    k32.WaitForSingleObject(sei.hProcess, int(wait_s * 1000))
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    k32.CloseHandle(sei.hProcess)
    return code.value


def _register():
    """登记计划任务（要管理员：弹一次确认）。"""
    paths.TMP.mkdir(parents=True, exist_ok=True)
    xml = paths.TMP / "hw_helper_task.xml"
    xml.write_text(_task_xml(), encoding="utf-16")
    code = _runas("schtasks.exe", f'/Create /F /TN "{TASK}" /XML "{xml}"')
    _TASK["ts"] = 0
    return code == 0


def _start_sync(allow_prompt: bool):
    """起助手。allow_prompt=False 时（开机自动起）不弹管理员确认：没登记过任务就算了。"""
    if not paths.IS_WIN:
        return False, "只在 Windows 上能用"
    if not pythonw().exists():
        return False, "还没装基础环境：先双击一次 启动.bat"
    if not task_exists(fresh=True):
        if not allow_prompt:
            return False, "还没登记过：在 设置 › 硬件监控 打开一次（会弹一次管理员确认）"
        feed.add("第一次打开硬件监控助手：登记一个 Windows 计划任务，会弹一次管理员确认，点「是」", "warn", job="硬件监控助手")
        if not _register():
            # 退回老办法：直接用管理员身份起（这次弹确认，以后每次都弹）
            code = _runas(pythonw(), f'"{script()}"', wait_s=0)
            return (code is not None), ("计划任务登记不上，这次直接用管理员身份起了（以后每次打开都会弹确认）" if code is not None
                                        else "你没点「是」，或者这台电脑不让提权")
    code, out = _schtasks("/Run", "/TN", TASK)
    return code == 0, ("已启动" if code == 0 else f"启动不了：{out.strip()[:120]}")


async def start(allow_prompt=True):
    if await running():
        return True, "已经在运行"
    if ST["busy"]:
        return False, "正在启动，等一下"
    ST["busy"] = True
    try:
        ok, msg = await asyncio.to_thread(_start_sync, allow_prompt)
        if ok:
            for _ in range(20):                   # 等它连上（最多 20 秒）
                await asyncio.sleep(1)
                if await running():
                    break
            else:
                ok, msg = False, "起了，但 20 秒内没连上：看 data\\logs\\hw_helper.log"
        ST["msg"] = msg
        if not ok:
            ST["fail_ts"] = time.time()
        feed.add("硬件监控助手：" + msg, "ok" if ok else "warn", job="硬件监控助手")
        return ok, msg
    finally:
        ST["busy"] = False


async def stop():
    ok = False
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.post(_base() + "/quit", headers={"X-Agent": "1"})
            ok = r.status_code == 200
    except Exception:
        pass
    if not ok and paths.IS_WIN and task_exists(fresh=True):
        try:
            await asyncio.to_thread(_schtasks, "/End", "/TN", TASK)
            ok = True
        except Exception:
            pass
    for _ in range(10):
        await asyncio.sleep(0.5)
        if not await running():
            feed.add("硬件监控助手已关闭", "info", job="硬件监控助手")
            return True, "已关闭"
    return ok, ("已关闭" if ok else "关不掉：它是不是用别的方式开的（比如 LibreHardwareMonitor 程序本身）？")


def tick(n):
    """后台照看（每 2 秒一次，这里每 30 秒真查一次）：开关开着、助手没在跑、任务登记过 → 不弹确认地拉起来。
    不在这里等它：另开一个任务去起，后台照看接着干别的。"""
    if n % 15 or not settings.S.get("hwOn") or not paths.IS_WIN or ST["busy"]:
        return
    if time.time() - ST["fail_ts"] < 300 or time.time() - ST["last_try"] < 60:
        return
    ST["last_try"] = time.time()
    asyncio.get_event_loop().create_task(_auto())


async def _auto():
    if not await running():
        await start(allow_prompt=False)


def state():
    return {"on": bool(settings.S.get("hwOn")), "busy": ST["busy"], "msg": ST["msg"], "task": task_exists() if paths.IS_WIN else False,
            "win": paths.IS_WIN}
