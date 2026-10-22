"""硬件数据：占用、频率、温度、功耗。

来源按顺序拼起来：
1. 硬件监控助手（硬件监控.bat，管理员运行）或 LibreHardwareMonitor 自带的网页服务 → CPU 温度/频率/功耗、硬盘温度等
2. NVIDIA 驱动自带的 NVML → 显卡占用、频率、温度、功耗、显存（不需要管理员）
3. psutil → CPU 占用、内存
整机功耗读不到真实值（普通电源没有数据接口），按 (CPU + 显卡 + 其他部件估计) ÷ 电源效率 估算。
"""
import re
import sys
import threading
import time

import httpx
import psutil

from . import settings

try:
    import pynvml
    pynvml.nvmlInit()
    NV = pynvml.nvmlDeviceGetHandleByIndex(0)
except Exception:
    pynvml, NV = None, None

_cache = {"ts": 0, "data": None}
psutil.cpu_percent(None)
RAM = {"freq": None, "desc": None, "tried": False}
_CPU = {"name": None}


def cpu_name():
    """CPU 型号：Windows 注册表里有（ProcessorNameString），读一次记住。"""
    if _CPU["name"] is None:
        n = ""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                n = winreg.QueryValueEx(k, "ProcessorNameString")[0]
        except Exception:
            import platform
            n = platform.processor() or ""
        n = re.sub(r"\((R|TM)\)|\s+\d+-Core Processor.*$|\s+with Radeon.*$|\s+CPU\s*@.*$", "", n)
        _CPU["name"] = re.sub(r"^(AMD|Intel)\s+", "", n).strip() or "CPU"
    return _CPU["name"]


def machine():
    """一句话说这台电脑的配置（给 DeepSeek 排查安装问题时用），从实际读数来，不写死。"""
    d = _cache.get("data") or {}
    g = d.get("gpu") or {}
    parts = [cpu_name()]
    if g.get("name") and g["name"] != "显卡":
        parts.append(g["name"] + (f" {g['vramTotal']:.0f}G" if g.get("vramTotal") else ""))
    return "、".join(parts)


def _ram_info():
    """内存频率和型号：Windows 自己记着（WMI 的 Win32_PhysicalMemory），读一次就行，不用你手填。"""
    import json as _json
    import subprocess
    from .models import NOWIN
    RAM["tried"] = True
    try:
        ps = ("Get-CimInstance Win32_PhysicalMemory | Select-Object Manufacturer,PartNumber,Capacity,Speed,"
              "ConfiguredClockSpeed,SMBIOSMemoryType | ConvertTo-Json -Compress")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=20,
                           encoding="utf-8", errors="replace", creationflags=NOWIN)
        mods = _json.loads(r.stdout or "[]")
        mods = mods if isinstance(mods, list) else [mods]
        if not mods:
            return
        speed = max((m.get("ConfiguredClockSpeed") or m.get("Speed") or 0) for m in mods) or None
        gb = sum(int(m.get("Capacity") or 0) for m in mods) / 2**30
        kind = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5"}.get(mods[0].get("SMBIOSMemoryType"), "")
        RAM["freq"] = speed
        RAM["desc"] = f"{gb:.0f} GB {kind}".strip() + (f" · {len(mods)} 条" if len(mods) > 1 else "")
    except Exception as e:
        print("读不到内存信息：", e)


def _num(v):
    if v is None:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(v).replace(",", "."))
    return float(m.group(0)) if m else None


def parse_lhm(j):
    hws = []

    def walk(n, cur, grp):
        img = str(n.get("ImageURL", "")).lower()
        kids = n.get("Children") or []
        typ = ("cpu" if "cpu.png" in img else "gpu" if re.search(r"(nvidia|ati|amd|intel)[^/]*\.png", img) else
               "ram" if "ram.png" in img else "disk" if "hdd.png" in img else None)
        if typ:
            cur = {"type": typ, "name": n.get("Text"), "s": []}
            hws.append(cur)
        if not kids and cur is not None and n.get("Value") not in (None, ""):
            cur["s"].append({"g": grp or "", "t": n.get("Text", ""), "v": n.get("Value")})
        g = n.get("Text") if (not typ and kids and cur is not None) else grp
        for c in kids:
            walk(c, cur, g)

    walk(j, None, None)

    def pick(h, g, pat):
        for x in h["s"]:
            if x["g"] == g and re.search(pat, x["t"], re.I):
                return _num(x["v"])
        return None

    def every(h, g, pat):
        return [v for v in (_num(x["v"]) for x in h["s"] if x["g"] == g and re.search(pat, x["t"], re.I)) if v is not None]

    first = lambda t: next((h for h in hws if h["type"] == t), None)
    out = {}
    cpu, gpu, ram = first("cpu"), first("gpu"), first("ram")
    if cpu:
        cl = every(cpu, "Clocks", r"core #")
        t = pick(cpu, "Temperatures", r"tctl|tdie|package")
        if t is None:
            ts = every(cpu, "Temperatures", r".")
            t = ts[0] if ts else None
        out["cpu"] = {"name": cpu["name"], "load": pick(cpu, "Load", r"total"), "temp": t,
                      "clock": (sum(cl) / len(cl) / 1000) if cl else None, "power": pick(cpu, "Powers", r"package")}
    if gpu:
        used = pick(gpu, "SmallData", r"memory used") or pick(gpu, "Data", r"memory used")
        tot = pick(gpu, "SmallData", r"memory total") or pick(gpu, "Data", r"memory total")
        out["gpu"] = {"name": gpu["name"], "load": pick(gpu, "Load", r"gpu core"), "temp": pick(gpu, "Temperatures", r"gpu core"),
                      "clock": pick(gpu, "Clocks", r"gpu core"), "power": pick(gpu, "Powers", r"gpu (package|power)"),
                      "vram": (used / 1024 if used and used > 64 else used), "vramTotal": (tot / 1024 if tot and tot > 64 else tot)}
    if ram:
        u, a = pick(ram, "Data", r"memory used"), pick(ram, "Data", r"memory available")
        out["ram"] = {"load": pick(ram, "Load", r"^memory$"), "used": u, "total": (u + a) if (u is not None and a is not None) else None}
    disks = [h for h in hws if h["type"] == "disk"][:3]
    if disks:
        out["disks"] = [{"n": d["name"], "temp": (every(d, "Temperatures", r".") or [None])[0]} for d in disks]
    return out


def nvml():
    if not NV:
        return {}
    g = {}
    try:
        g["name"] = pynvml.nvmlDeviceGetName(NV)
        if isinstance(g["name"], bytes):
            g["name"] = g["name"].decode()
        g["load"] = float(pynvml.nvmlDeviceGetUtilizationRates(NV).gpu)
        g["temp"] = float(pynvml.nvmlDeviceGetTemperature(NV, pynvml.NVML_TEMPERATURE_GPU))
        g["clock"] = float(pynvml.nvmlDeviceGetClockInfo(NV, pynvml.NVML_CLOCK_GRAPHICS))
        g["power"] = pynvml.nvmlDeviceGetPowerUsage(NV) / 1000.0
        mem = pynvml.nvmlDeviceGetMemoryInfo(NV)
        g["vram"], g["vramTotal"] = mem.used / 2**30, mem.total / 2**30
    except Exception:
        pass
    return g


async def sample():
    if time.time() - _cache["ts"] < 0.8 and _cache["data"]:
        return _cache["data"]
    s = settings.S
    src = {}
    lhm, fps = {}, None
    if not RAM["tried"] and sys.platform.startswith("win"):
        threading.Thread(target=_ram_info, daemon=True).start()
    try:
        async with httpx.AsyncClient(timeout=1.2) as c:
            r = await c.get(s["hwUrl"])
            j = r.json()
            lhm = parse_lhm(j)
            fps = j.get("AgentFps") if isinstance(j, dict) else None
            src["lhm"] = True
    except Exception:
        src["lhm"] = False
    vm = psutil.virtual_memory()
    cpu = {"name": cpu_name(), "load": psutil.cpu_percent(None), "clock": None, "temp": None, "power": None}
    f = psutil.cpu_freq()
    if f and f.current:
        cpu["clock"] = f.current / 1000
    cpu.update({k: v for k, v in (lhm.get("cpu") or {}).items() if v is not None})
    gpu = {"name": "显卡", "load": None, "clock": None, "temp": None, "power": None, "vram": None, "vramTotal": None}
    gpu.update({k: v for k, v in (lhm.get("gpu") or {}).items() if v is not None})
    gpu.update({k: v for k, v in nvml().items() if v is not None})
    if isinstance(gpu.get("name"), str):
        gpu["name"] = gpu["name"].replace("NVIDIA GeForce ", "")
    gpu["vramPct"] = (gpu["vram"] / gpu["vramTotal"] * 100) if gpu.get("vram") is not None and gpu.get("vramTotal") else None
    ram = {"load": vm.percent, "used": (vm.total - vm.available) / 2**30, "total": vm.total / 2**30, "freq": RAM["freq"], "desc": RAM["desc"]}
    disks = lhm.get("disks") or []
    cp, gp = cpu.get("power"), gpu.get("power")
    sysp = ((cp or 0) + (gp or 0) + float(s["sysOther"])) / (float(s["psuEff"]) / 100) if (cp is not None or gp is not None) else None
    data = {"src": "lhm" if src["lhm"] else "basic", "ok": True, "cpu": cpu, "gpu": gpu, "ram": ram, "disks": disks,
            "sys": {"power": sysp, "estimated": True, "parts": {"cpu": cp is not None, "gpu": gp is not None}},
            "sources": {"sensors": src["lhm"], "nvml": NV is not None, "fps": bool(fps and fps.get("ok"))},
            "fps": fps if fps and fps.get("fps") else None}
    _cache.update(ts=time.time(), data=data)
    for k, v in (("cpu", cpu.get("load")), ("gpu", gpu.get("load")), ("ram", ram["load"]), ("vram", gpu.get("vramPct")), ("pw", sysp),
                 ("fps", (fps or {}).get("fps"))):
        HIST[k].append(v)
        del HIST[k][:-60]
    return data


HIST = {"cpu": [], "gpu": [], "ram": [], "vram": [], "pw": [], "fps": []}   # 最近 60 次（约 2 分钟），界面一打开走势线就是满的
