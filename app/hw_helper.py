"""硬件监控助手：用 LibreHardwareMonitor 的核心库读传感器，在 127.0.0.1:8085/data.json 提供数据
（格式和 LibreHardwareMonitor 自带的网页服务一样）。

必须用管理员身份运行（双击 硬件监控.bat 会自动请求管理员权限），否则 CPU 温度、功耗读不到。
CPU 温度还需要 PawnIO 驱动（https://pawnio.eu 下载安装一次）。
只监听本机 127.0.0.1，别的电脑访问不到。

游戏帧数（FPS 和 1% 低帧）：用 Windows 自带的 ETW 事件读（和 Intel PresentMon、很多帧数工具的办法一样），
不往游戏里注入任何东西，不会被反作弊当成外挂。统计每个程序交画面（DXGI Present）的时间间隔：
- FPS：最近 1 秒交了几帧
- 1% 低帧：最近 30 秒里最慢的 1% 那些帧，换算成帧数（越接近 FPS 越稳）
DirectX 10/11/12 的游戏都能读；Vulkan、OpenGL 的读不到。也需要管理员权限。
"""
import ctypes
import json
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8085

try:
    from HardwareMonitor.Hardware import Computer
except Exception as e:  # pragma: no cover - 只在 Windows 上能用
    print("读不了 HardwareMonitor 库：", e)
    print("这个助手只能在 Windows 上运行，并且要先运行一次 启动.bat 装好依赖。")
    input("按回车退出")
    sys.exit(1)

IMG = {"Cpu": "images_icon/cpu.png", "GpuNvidia": "images_icon/nvidia.png", "GpuAmd": "images_icon/ati.png",
       "GpuIntel": "images_icon/intel.png", "Memory": "images_icon/ram.png", "Storage": "images_icon/hdd.png",
       "Motherboard": "images_icon/mainboard.png"}
GROUP = {"Load": "Load", "Temperature": "Temperatures", "Clock": "Clocks", "Power": "Powers", "Data": "Data",
         "SmallData": "SmallData", "Voltage": "Voltages", "Fan": "Fans", "Control": "Controls"}
UNIT = {"Load": " %", "Temperature": " °C", "Clock": " MHz", "Power": " W", "Data": " GB", "SmallData": " MB",
        "Voltage": " V", "Fan": " RPM", "Control": " %"}

pc = Computer()
pc.IsCpuEnabled = True
pc.IsGpuEnabled = True
pc.IsMemoryEnabled = True
pc.IsStorageEnabled = True
pc.IsMotherboardEnabled = True
pc.Open()

latest = {"json": b"{}"}


class FpsMeter:
    GUID = "{CA11C036-0102-4A2D-A6AD-F03CFED5D3C9}"     # Microsoft-Windows-DXGI
    PRESENT = (42, 55)                                     # Present_Start、PresentMultiplaneOverlay_Start
    SKIP = {"dwm.exe", "explorer.exe", "msedge.exe", "msedgewebview2.exe", "chrome.exe", "firefox.exe", "pythonw.exe",
            "python.exe", "qq.exe", "wechat.exe", "weixin.exe", "steamwebhelper.exe", "searchhost.exe", "shellexperiencehost.exe",
            "startmenuexperiencehost.exe", "textinputhost.exe", "applicationframehost.exe"}

    def __init__(self):
        self.lock = threading.Lock()
        self.ts = {}             # pid -> deque[秒]
        self.err = None
        self.job = None
        self.freq = None
        self.names = {}
        self.seen = {}           # pid -> 最近一次收到它交画面的时刻（本机时钟）

    def start(self):
        try:
            import subprocess
            # 上次助手没正常退出的话，同名的监听会话还留着：先关掉再开
            subprocess.run(["logman", "stop", "AgentFpsSession", "-ets"], capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass
        try:
            import etw
            from etw.common import RETURN_RAW_DATA_ONLY
            prov = etw.ProviderInfo("Microsoft-Windows-DXGI", etw.GUID(self.GUID), level=4,
                                    any_keywords=0xFFFFFFFFFFFFFFFF, all_keywords=0)
            self.job = etw.ETW(providers=[prov], event_callback=self._on, event_id_filters=list(self.PRESENT),
                               callback_data_flag=RETURN_RAW_DATA_ONLY, session_name="AgentFpsSession")
            self.job.start()
            import atexit
            atexit.register(self.stop)
            f = ctypes.c_int64()
            ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(f))
            self.freq = f.value or 10_000_000
            print("游戏帧数：已开始读（DXGI Present 事件）")
        except Exception as e:
            self.err = str(e)[:200]
            print("游戏帧数读不了（不影响别的）：", e)

    def stop(self):
        try:
            if self.job:
                self.job.stop()
        except Exception:
            pass

    def _on(self, ev):
        try:
            h = ev[1]["EventHeader"]
            t = int(h["TimeStamp"])
            sec = t / 1e7 if t > 10**16 else t / self.freq     # 系统时间（100 纳秒）或 QPC
            with self.lock:
                d = self.ts.get(h["ProcessId"])
                if d is None:
                    d = self.ts[h["ProcessId"]] = deque(maxlen=12000)
                d.append(sec)
                self.seen[h["ProcessId"]] = time.monotonic()
        except Exception:
            pass

    def _name(self, pid):
        if pid not in self.names:
            try:
                import psutil
                self.names[pid] = psutil.Process(pid).name()
            except Exception:
                self.names[pid] = ""
        return self.names[pid]

    def _fg(self):
        try:
            u = ctypes.windll.user32
            pid = ctypes.c_ulong()
            u.GetWindowThreadProcessId(u.GetForegroundWindow(), ctypes.byref(pid))
            return pid.value
        except Exception:
            return 0

    def stats(self):
        if self.err or not self.job:
            return {"ok": False, "err": self.err}
        with self.lock:
            now = time.monotonic()
            for pid in [p for p, t in self.seen.items() if now - t > 60]:      # 退出了的程序，清掉
                self.seen.pop(pid, None)
                self.ts.pop(pid, None)
            snap = {pid: list(d) for pid, d in self.ts.items() if d and now - self.seen.get(pid, 0) < 2}
        if not snap:
            return {"ok": True, "fps": None}
        newest = max(d[-1] for d in snap.values())
        live = {}
        for pid, d in snap.items():
            n2 = sum(1 for x in d if x >= newest - 2)
            if d[-1] >= newest - 2 and n2 >= 20 and self._name(pid).lower() not in self.SKIP:
                live[pid] = n2
        if not live:
            return {"ok": True, "fps": None}
        fg = self._fg()
        pid = fg if fg in live else max(live, key=live.get)
        d = snap[pid]
        end = d[-1]
        fps = sum(1 for x in d if x > end - 1)
        win = [x for x in d if x > end - 30]
        gaps = sorted((b - a for a, b in zip(win, win[1:]) if 0 < b - a < 2), reverse=True)
        low = None
        if len(gaps) >= 20:
            k = max(1, len(gaps) // 100)
            low = 1 / (sum(gaps[:k]) / k)
        return {"ok": True, "fps": fps, "low1": round(low, 1) if low else None, "proc": self._name(pid), "pid": pid}


FPS = FpsMeter()


def enum_name(e):
    """.NET 枚举转名字（Temperature、Cpu……），兼容不同版本的 pythonnet。"""
    try:
        return str(e.ToString())
    except Exception:
        return str(e).split(".")[-1]


def node(text, img="", kids=None, value=""):
    return {"Text": text, "ImageURL": img, "Value": value, "Children": kids or []}


def sensors_of(hw):
    groups = {}
    for s in hw.Sensors:
        t = enum_name(s.SensorType)
        if s.Value is None:
            continue
        g = GROUP.get(t, t)
        groups.setdefault(g, []).append(node(str(s.Name), value=f"{float(s.Value):.1f}{UNIT.get(t, '')}"))
    return [node(g, kids=v) for g, v in groups.items()]


def snapshot():
    tree = []
    for hw in pc.Hardware:
        hw.Update()
        kids = sensors_of(hw)
        for sub in hw.SubHardware:
            sub.Update()
            kids.extend(sensors_of(sub))
        t = enum_name(hw.HardwareType)
        tree.append(node(str(hw.Name), IMG.get(t, ""), kids))
    return node("Sensor", kids=[node("本机", "images_icon/computer.png", tree)])


def loop():
    while True:
        try:
            snap = snapshot()
            snap["AgentFps"] = FPS.stats()
            latest["json"] = json.dumps(snap, ensure_ascii=False).encode("utf-8")
        except Exception as e:
            print("读取传感器出错：", e)
        time.sleep(1)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] != "/data.json":
            self.send_response(404)
            self.end_headers()
            return
        body = latest["json"]
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    FPS.start()
    threading.Thread(target=loop, daemon=True).start()
    print(f"硬件监控助手已启动：http://127.0.0.1:{PORT}/data.json （这个窗口可以最小化，关掉就停止）")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
