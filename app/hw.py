"""硬件数据：占用、频率、温度、功耗。

来源按顺序拼起来：
1. 硬件监控助手（设置 › 硬件监控 打开，管理员权限，见 hwctl.py）或 LibreHardwareMonitor 自带的网页服务 → CPU 温度/频率/功耗、硬盘温度等
2. NVIDIA 驱动自带的 NVML → 显卡占用、频率、温度、功耗、显存（不需要管理员）
3. psutil → CPU 占用、内存
4. Windows 自带的性能计数器（PDH）→ CPU 占用和频率、显卡占用（含视频编码、解码）、每个程序占的显存。
   和任务管理器是同一套算法，不用驱动、不用管理员；有它就以它为准，前面几个只是兜底。
PawnIO 驱动只管 CPU 温度和功耗（任务管理器里也没有这两项）。没装时 LibreHardwareMonitor 读到的是 0：0 当成"读不到"，界面显示"—"。
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


DISKS = {"win": None, "tried": False}


def _disk_info():
    """Windows 的磁盘列表（和任务管理器的"磁盘 0、1、2……"一样全）和每块盘的盘符，读一次就行。"""
    import json as _json
    import subprocess
    from .models import NOWIN
    DISKS["tried"] = True
    try:
        ps = ("Get-Disk | Sort-Object Number | ForEach-Object { $n = $_.Number; [pscustomobject]@{ Num = $n; Name = $_.FriendlyName; "
              "Bus = [string]$_.BusType; Letters = @(Get-Partition -DiskNumber $n -ErrorAction SilentlyContinue | "
              "Where-Object { [string]$_.DriveLetter -match '^[A-Za-z]$' } | ForEach-Object { [string]$_.DriveLetter }) } } | ConvertTo-Json -Compress")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace", creationflags=NOWIN)
        ds = _json.loads(r.stdout or "[]")
        DISKS["win"] = ds if isinstance(ds, list) else [ds]
    except Exception as e:
        print("读不到磁盘列表：", e)


def merge_disks(lhm_disks, win):
    """传感器读到的硬盘（有温度）+ Windows 的磁盘列表（全、有盘符）→ 有几块显示几块，按任务管理器的顺序，名字前面带盘符。
    按型号对上；传感器没读到的盘也列出来（温度显示"—"）。"""
    if not win or not lhm_disks:            # 助手没开就没有温度：照旧显示"打开助手后显示"
        return list(lhm_disks)

    def norm(t):
        return re.sub(r"[^0-9a-z]", "", str(t or "").lower())

    left, out = list(lhm_disks), []
    for w in sorted(win, key=lambda x: x.get("Num") if isinstance(x.get("Num"), int) else 99):
        if "virtual" in str(w.get("Bus") or "").lower():     # 虚拟磁盘（VHD）不算
            continue
        nm = norm(w.get("Name"))
        hit = next((d for d in left if nm and norm(d.get("n")) and (norm(d.get("n")) == nm or norm(d.get("n")) in nm or nm in norm(d.get("n")))), None)
        if hit:
            left.remove(hit)
        lt = w.get("Letters") or []
        lt = [lt] if isinstance(lt, str) else lt
        letters = " ".join(f"{x}:" for x in lt if x)
        out.append({"n": (letters + " " + (hit["n"] if hit else str(w.get("Name") or "磁盘"))).strip(), "temp": hit.get("temp") if hit else None})
    return out + left


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


class _Pdh:
    """Windows 自带的性能计数器（PDH）：和任务管理器用的是同一套，不用驱动、不用管理员。只在 Windows 上有。
    - CPU 占用：% Processor Utility（任务管理器的"利用率"，把睿频算进去，封顶 100）
    - CPU 频率：基础频率 × % Processor Performance（任务管理器的"速度"，睿频时超过 100）
    - 显卡占用：GPU Engine 的 Utilization Percentage，每个引擎把各程序加起来，取最高的那个（任务管理器的"GPU"）
    - 每个程序占的专用显存：GPU Process Memory 的 Dedicated Usage（让路时算"别的程序占了多少"）
    这几个都是按两次采样之间算的，第一次只起个头，下一次才有值。"""
    PATHS = {"util": r"\Processor Information(_Total)\% Processor Utility",
             "perf": r"\Processor Information(_Total)\% Processor Performance",
             "eng": r"\GPU Engine(*)\Utilization Percentage",
             "pmem": r"\GPU Process Memory(*)\Dedicated Usage"}

    def __init__(self):
        self.ok = sys.platform.startswith("win")
        self.q, self.c, self.last, self.ts = None, {}, {}, 0.0

    def read(self):
        """{"util": %, "perf": %, "eng": [(实例名, %)], "pmem": [(实例名, 字节)]}；读不到的键没有。"""
        if not self.ok:
            return {}
        if time.time() - self.ts < 0.5:
            return self.last
        try:
            import ctypes
            pdh = ctypes.WinDLL("pdh")
            if self.q is None:
                q = ctypes.c_void_p()
                if pdh.PdhOpenQueryW(None, None, ctypes.byref(q)) != 0:
                    raise OSError("PdhOpenQuery")
                for k, path in self.PATHS.items():
                    c = ctypes.c_void_p()
                    if pdh.PdhAddEnglishCounterW(q, path, None, ctypes.byref(c)) == 0:
                        self.c[k] = c
                if not self.c:
                    raise OSError("PdhAddEnglishCounter")
                pdh.PdhCollectQueryData(q)
                self.q, self.ts = q, time.time()
                return {}
            pdh.PdhCollectQueryData(self.q)
            self.ts = time.time()

            class V(ctypes.Structure):
                _fields_ = [("CStatus", ctypes.c_ulong), ("doubleValue", ctypes.c_double)]

            class Item(ctypes.Structure):
                _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", V)]

            fmt = 0x200 | 0x8000                   # PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
            out = {}
            for k in ("util", "perf"):
                v = V()
                if k in self.c and pdh.PdhGetFormattedCounterValue(self.c[k], fmt, None, ctypes.byref(v)) == 0 and v.CStatus in (0, 1):
                    out[k] = v.doubleValue
            for k in ("eng", "pmem"):
                if k not in self.c:
                    continue
                size, cnt = ctypes.c_ulong(0), ctypes.c_ulong(0)
                r = pdh.PdhGetFormattedCounterArrayW(self.c[k], fmt, ctypes.byref(size), ctypes.byref(cnt), None) & 0xFFFFFFFF
                if r != 0x800007D2 or not size.value:  # PDH_MORE_DATA：先问要多大
                    continue
                size.value *= 2                    # 两次调用之间程序可能多了（GPU 引擎的实例跟着程序变），多留点地方
                buf = (ctypes.c_byte * size.value)()
                if pdh.PdhGetFormattedCounterArrayW(self.c[k], fmt, ctypes.byref(size), ctypes.byref(cnt), buf) != 0:
                    continue
                items = ctypes.cast(buf, ctypes.POINTER(Item * cnt.value)).contents
                out[k] = [(it.szName or "", it.FmtValue.doubleValue) for it in items if it.FmtValue.CStatus in (0, 1)]
            self.last = out
            return out
        except Exception as e:
            print("读不到 Windows 性能计数器：", e)
            self.ok = False                        # 读不了就别再试了，退回 psutil 和 NVML
            return {}


ENG_NAME = {"3d": "3D", "videoencode": "视频编码", "videodecode": "视频解码", "copy": "复制", "videoprocessing": "视频处理",
            "compute": "计算", "cuda": "计算"}


def _eng_name(t):
    t = t.lower()
    return next((v for k, v in ENG_NAME.items() if t.startswith(k)), t)


def gpu_engines(eng, pmem=()):
    """GPU Engine 的各个实例（每个程序 × 每个引擎一个）→ 和任务管理器一样的显卡占用。
    同一块显卡的同一个引擎，把各程序的占用加起来（封顶 100）；最忙的那个引擎就是总占用。
    有几块显卡时，取各程序占专用显存最多的那块（独立显卡）。
    返回 {"load": 总占用, "load3d": 3D 和计算, "enc": 视频编码, "dec": 视频解码, "top": 最忙的是哪个}，读不到返回 None。"""
    per = {}
    for name, v in eng:
        m = re.search(r"luid_(0x[0-9a-f]+_0x[0-9a-f]+)_phys_(\d+)_eng_(\d+)_engtype_(.*)$", name, re.I)
        if not m:
            continue
        e = per.setdefault(m.group(1), {}).setdefault((m.group(2), m.group(3)), {"t": _eng_name(m.group(4)), "v": 0.0})
        e["v"] += max(0.0, v)
    if not per:
        return None
    mem = {}
    for name, v in pmem:
        m = re.search(r"luid_(0x[0-9a-f]+_0x[0-9a-f]+)_phys", name, re.I)
        if m:
            mem[m.group(1)] = mem.get(m.group(1), 0) + max(0.0, v)
    luid = max(per, key=lambda x: (mem.get(x, 0), max(e["v"] for e in per[x].values())))
    by = {}
    for e in per[luid].values():
        by[e["t"]] = max(by.get(e["t"], 0.0), min(100.0, e["v"]))
    top = max(by, key=by.get)
    return {"load": by[top], "load3d": max(by.get("3D", 0.0), by.get("计算", 0.0)), "enc": by.get("视频编码", 0.0),
            "dec": by.get("视频解码", 0.0), "top": top}


def vram_of(pids, pmem=None):
    """这几个进程一共占了多少专用显存（GB），按 Windows 的 GPU Process Memory 算（任务管理器"详细信息"里那一列）。
    读不到返回 None。"""
    if pmem is None:
        pmem = PDH.last.get("pmem")
    if pmem is None:
        return None
    tot = 0.0
    for name, v in pmem:
        m = re.match(r"pid_(\d+)_", name)
        if m and int(m.group(1)) in pids:
            tot += max(0.0, v)
    return tot / 2**30


PDH = _Pdh()


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
    disks = [h for h in hws if h["type"] == "disk"]       # 有几块列几块（v1.8.4 以前只取前 3 块）
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
        g["load3d"] = float(pynvml.nvmlDeviceGetUtilizationRates(NV).gpu)      # 只是图形/计算，不含视频编码、解码
        g["temp"] = float(pynvml.nvmlDeviceGetTemperature(NV, pynvml.NVML_TEMPERATURE_GPU))
        g["clock"] = float(pynvml.nvmlDeviceGetClockInfo(NV, pynvml.NVML_CLOCK_GRAPHICS))
        g["power"] = pynvml.nvmlDeviceGetPowerUsage(NV) / 1000.0
        mem = pynvml.nvmlDeviceGetMemoryInfo(NV)
        g["vram"], g["vramTotal"] = mem.used / 2**30, mem.total / 2**30
    except Exception:
        pass
    try:
        g["enc"] = float(pynvml.nvmlDeviceGetEncoderUtilization(NV)[0])
        g["dec"] = float(pynvml.nvmlDeviceGetDecoderUtilization(NV)[0])
    except Exception:
        pass
    if g.get("load3d") is not None:          # 和任务管理器一样：最忙的那个引擎就是总占用
        parts = {"3D": g["load3d"], "视频编码": g.get("enc") or 0.0, "视频解码": g.get("dec") or 0.0}
        g["top"] = max(parts, key=parts.get)
        g["load"] = parts[g["top"]]
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
    if not DISKS["tried"] and sys.platform.startswith("win"):
        threading.Thread(target=_disk_info, daemon=True).start()
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
    # 优先级从低到高：psutil → 传感器（LibreHardwareMonitor）→ Windows 性能计数器（和任务管理器一样）。
    # 占用和频率以任务管理器的算法为准；传感器只在读不到计数器时兜底（装了 PawnIO 后，传感器的"各核平均频率"
    # 会把睡着的核也平均进去，偏低，v1.8.4 以前它盖掉了正确的读数）。CPU 温度、功耗只有传感器有。
    pd = PDH.read()
    cpu = {"name": cpu_name(), "load": psutil.cpu_percent(None), "clock": None, "temp": None, "power": None}
    f = psutil.cpu_freq()
    if f and f.current:
        cpu["clock"] = f.current / 1000
    cpu.update({k: v for k, v in (lhm.get("cpu") or {}).items() if v is not None})
    if pd.get("util") is not None:
        cpu["load"] = min(100.0, max(0.0, pd["util"]))
    base = (f.max or f.current) if f else 0
    if pd.get("perf") and base:
        cpu["clock"] = base * pd["perf"] / 100 / 1000
    gpu = {"name": "显卡", "load": None, "clock": None, "temp": None, "power": None, "vram": None, "vramTotal": None,
           "load3d": None, "enc": None, "dec": None, "top": None}
    gpu.update({k: v for k, v in (lhm.get("gpu") or {}).items() if v is not None})
    if gpu.get("load") is not None:
        gpu["load3d"] = gpu["load"]
    gpu.update({k: v for k, v in nvml().items() if v is not None})
    ge = gpu_engines(pd.get("eng") or [], pd.get("pmem") or [])
    if ge:
        gpu.update(ge)
    # 最忙的不是 3D（比如录屏、直播时视频编码占满），标出来：常驻屏写「GPU · 视频编码」
    gpu["topTxt"] = (" · " + gpu["top"]) if gpu.get("top") and gpu["top"] not in ("3D", "计算") and (gpu.get("load") or 0) >= 10 else ""
    if isinstance(gpu.get("name"), str):
        gpu["name"] = gpu["name"].replace("NVIDIA GeForce ", "")
    gpu["vramPct"] = (gpu["vram"] / gpu["vramTotal"] * 100) if gpu.get("vram") is not None and gpu.get("vramTotal") else None
    ram = {"load": vm.percent, "used": (vm.total - vm.available) / 2**30, "total": vm.total / 2**30, "freq": RAM["freq"], "desc": RAM["desc"]}
    disks = merge_disks(lhm.get("disks") or [], DISKS["win"])
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
