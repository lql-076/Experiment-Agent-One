"""硬件数据：占用、频率、温度、功耗。

来源按顺序拼起来：
1. 硬件监控助手（设置 › 硬件监控 打开，管理员权限，见 hwctl.py）或 LibreHardwareMonitor 自带的网页服务 → CPU 温度/频率/功耗、硬盘温度等
2. NVIDIA 驱动自带的 NVML → 显卡占用、频率、温度、功耗、显存（不需要管理员）
3. psutil → CPU 占用、内存
4. Windows 自带的性能计数器（PDH）→ CPU 实时频率（和任务管理器的"速度"一个算法，不用驱动、不用管理员）
没装 PawnIO 驱动时，LibreHardwareMonitor 读 CPU 温度、功耗、频率全是 0：0 当成"读不到"，界面显示"—"，不显示 0。
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


class _CpuPerf:
    """CPU 实时频率 = 基础频率 × "% Processor Performance"（可以超过 100，睿频时就是这样）。只在 Windows 上有。"""

    def __init__(self):
        self.q = self.c = None
        self.ok = sys.platform.startswith("win")

    def mhz(self):
        if not self.ok:
            return None
        try:
            import ctypes
            pdh = ctypes.WinDLL("pdh")
            if self.q is None:
                q, c = ctypes.c_void_p(), ctypes.c_void_p()
                if pdh.PdhOpenQueryW(None, None, ctypes.byref(q)) != 0:
                    raise OSError("PdhOpenQuery")
                if pdh.PdhAddEnglishCounterW(q, r"\Processor Information(_Total)\% Processor Performance", None, ctypes.byref(c)) != 0:
                    raise OSError("PdhAddEnglishCounter")
                pdh.PdhCollectQueryData(q)
                self.q, self.c = q, c
                return None                        # 第一次只是起个头，下一次才有值

            class V(ctypes.Structure):
                _fields_ = [("CStatus", ctypes.c_ulong), ("doubleValue", ctypes.c_double)]
            v = V()
            pdh.PdhCollectQueryData(self.q)
            if pdh.PdhGetFormattedCounterValue(self.c, 0x200, None, ctypes.byref(v)) != 0:     # 0x200 = PDH_FMT_DOUBLE
                return None
            f = psutil.cpu_freq()
            base = (f.max or f.current) if f else 0
            return base * v.doubleValue / 100 if base and v.doubleValue > 0 else None
        except Exception:
            self.ok = False                        # 读不了就别再试了，退回 psutil
            return None


PERF = _CpuPerf()


def _pos(v):
    """没装驱动时 LibreHardwareMonitor 给的是 0：0 和负数都当成读不到"""
    return v if v is not None and v > 0 else None


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
        cl = [c for c in every(cpu, "Clocks", r"core #") if c > 0]
        t = _pos(pick(cpu, "Temperatures", r"tctl|tdie|package"))
        if t is None:
            ts = [x for x in every(cpu, "Temperatures", r".") if x > 0]
            t = ts[0] if ts else None
        out["cpu"] = {"name": cpu["name"], "load": pick(cpu, "Load", r"total"), "temp": t,
                      "clock": (sum(cl) / len(cl) / 1000) if cl else None, "power": _pos(pick(cpu, "Powers", r"package"))}
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


def pick_fps(f):
    """硬件监控助手报上来几个正在出画面的程序（cands，前台的排第一）。去掉你在设置里说过"不是游戏"的，剩下第一个就是游戏。
    seen：这些候选都给界面看，设置 › 游戏内显示 里能点「这不是游戏」。"""
    if not isinstance(f, dict) or not f.get("ok"):
        return f, []
    skip = {x.strip().lower() for x in str(settings.S.get("fpsSkip", "")).split(",") if x.strip()}
    cands = f.get("cands")
    if cands is None:                      # 老版本的助手：只有它自己挑的那一个
        cands = [{k: f.get(k) for k in ("proc", "pid", "fps", "low1")} | {"fg": True}] if f.get("fps") else []
    seen = [dict(c, skipped=(str(c.get("proc") or "").lower() in skip)) for c in cands]
    ok = [c for c in seen if not c["skipped"]]
    if not ok:
        return {"ok": True, "fps": None}, seen
    best = ok[0]
    return {"ok": True, "fps": best.get("fps"), "low1": best.get("low1"), "proc": best.get("proc"), "pid": best.get("pid"),
            "fg": best.get("fg", True)}, seen


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
            src["helper"] = isinstance(fps, dict)        # 是我们自己的助手（不是 LibreHardwareMonitor 程序自带的网页服务）
    except Exception:
        src["lhm"] = False
    fps, seen = pick_fps(fps)
    vm = psutil.virtual_memory()
    cpu = {"name": cpu_name(), "load": psutil.cpu_percent(None), "clock": None, "temp": None, "power": None}
    f = psutil.cpu_freq()
    if f and f.current:
        cpu["clock"] = f.current / 1000
    mhz = PERF.mhz()
    if mhz:
        cpu["clock"] = mhz / 1000
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
            "sources": {"sensors": src["lhm"], "nvml": NV is not None, "fps": bool(fps and fps.get("ok")),
                        "cpuTemp": bool((lhm.get("cpu") or {}).get("temp")), "cpuPower": cp is not None},
            "fps": fps if fps and fps.get("fps") else None, "fpsSeen": seen}
    _cache.update(ts=time.time(), data=data)
    for k, v in (("cpu", cpu.get("load")), ("gpu", gpu.get("load")), ("ram", ram["load"]), ("vram", gpu.get("vramPct")), ("pw", sysp),
                 ("fps", (fps or {}).get("fps"))):
        HIST[k].append(v)
        del HIST[k][:-60]
    return data


HIST = {"cpu": [], "gpu": [], "ram": [], "vram": [], "pw": [], "fps": []}   # 最近 60 次（约 2 分钟），界面一打开走势线就是满的
