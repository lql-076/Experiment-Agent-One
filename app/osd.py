"""游戏内显示（OSD）：像游戏加加那样，在游戏画面一角浮一个小框，显示帧数、1% 低帧、CPU、显卡、显存、内存、整机功耗、时间。

怎么做的（不注入游戏，不会被反作弊当外挂）：
- 单独一个进程（pythonw -m app.osd），用 Python 自带的 tkinter 开一个无边框小窗：
  永远在最上层、鼠标点击直接穿过去（WS_EX_TRANSPARENT）、不抢焦点、不进任务栏。
- 每秒问一次后端 /api/osd（设置 + 硬件读数），按设置画出来。
- 只对"窗口化 / 无边框全屏"的游戏有效；"独占全屏"的游戏会盖住所有别的窗口，这种情况看不到它——
  把游戏的显示模式改成"无边框"就行（现在大多数游戏默认就是）。
- 帧数、CPU 温度要「硬件监控助手」开着（硬件监控.bat，管理员）；显卡占用、温度、显存不需要。

后端这边（CTL）：设置 › 游戏内显示 打开时启动它、关掉时停掉，挂了 30 秒后再拉起；只按进程号停自己开的。
"""
import json
import os
import sys
import threading
import time
import urllib.request

ITEMS = [("fps", "帧数"), ("low1", "1% 低帧"), ("cpu", "CPU"), ("gpu", "显卡"), ("vram", "显存"), ("ram", "内存"), ("power", "整机功耗"), ("time", "时间")]
DEFAULTS = {"osdOn": False, "osdWhen": "game", "osdItems": "fps,low1,cpu,gpu,vram,power", "osdPos": "tl", "osdMargin": 16,
            "osdScreen": 0, "osdSize": "m", "osdOpacity": 80, "osdHotkey": "ctrl+alt+f10"}
COLORS = {"fps": "#5fe0b0", "low1": "#ffd166", "cpu": "#3fc6ff", "gpu": "#b49bff", "vram": "#ff8fc0", "ram": "#8fe3a5",
          "power": "#ffb547", "time": "#e8eaf0", "hot": "#ff5d5d", "label": "#9aa4b2"}
HOTKEYS = {"ctrl+alt+f10": (0x0001 | 0x0002, 0x79), "ctrl+shift+f10": (0x0002 | 0x0004, 0x79), "alt+f12": (0x0001, 0x7B), "off": None}


def _f(x, d=0):
    try:
        return f"{float(x):.{d}f}"
    except (TypeError, ValueError):
        return None


def lines(cfg: dict, hw: dict):
    """按设置把硬件读数排成几行：[(名字, 数值, 颜色)]。界面里的预览和游戏里的小框用同一套规则。"""
    want = [x for x in str(cfg.get("osdItems", DEFAULTS["osdItems"])).split(",") if x]
    hw = hw or {}
    cpu, gpu, ram, fps = hw.get("cpu") or {}, hw.get("gpu") or {}, hw.get("ram") or {}, hw.get("fps") or {}
    out = []
    for k in want:
        if k == "fps":
            out.append(("FPS", _f(fps.get("fps")) or "—", COLORS["fps"]))
        elif k == "low1":
            out.append(("1% 低", _f(fps.get("low1")) or "—", COLORS["low1"]))
        elif k == "cpu":
            bits = [b for b in ((_f(cpu.get("load")) or "—") + "%", (_f(cpu.get("temp")) + "°C") if _f(cpu.get("temp")) else None,
                                (_f(cpu.get("power")) + "W") if _f(cpu.get("power")) else None) if b]
            hot = (cpu.get("temp") or 0) >= 85
            out.append(("CPU", "  ".join(bits), COLORS["hot"] if hot else COLORS["cpu"]))
        elif k == "gpu":
            bits = [b for b in ((_f(gpu.get("load")) or "—") + "%", (_f(gpu.get("temp")) + "°C") if _f(gpu.get("temp")) else None,
                                (_f(gpu.get("power")) + "W") if _f(gpu.get("power")) else None) if b]
            hot = (gpu.get("temp") or 0) >= 83
            out.append(("GPU", "  ".join(bits), COLORS["hot"] if hot else COLORS["gpu"]))
        elif k == "vram":
            u, t = _f(gpu.get("vram"), 1), _f(gpu.get("vramTotal"))
            out.append(("显存", f"{u or '—'} / {t or '—'} G", COLORS["vram"]))
        elif k == "ram":
            u, t = _f(ram.get("used"), 1), _f(ram.get("total"))
            out.append(("内存", f"{u or '—'} / {t or '—'} G", COLORS["ram"]))
        elif k == "power":
            p = _f((hw.get("sys") or {}).get("power"))
            out.append(("整机", f"≈{p} W" if p else "—", COLORS["power"]))
        elif k == "time":
            out.append(("时间", time.strftime("%H:%M"), COLORS["time"]))
    return out


def visible(cfg: dict, hw: dict, hidden: bool) -> bool:
    """要不要显示：总开关开着、没被快捷键藏起来、并且（一直显示，或者正在玩游戏——读到了帧数）。"""
    if not cfg.get("osdOn") or hidden:
        return False
    if cfg.get("osdWhen") == "always":
        return True
    return bool(((hw or {}).get("fps") or {}).get("fps"))


# ======================= 后端这边：开、关、挂了再拉起 =======================
class Ctl:
    def __init__(self):
        from .models import Proc
        self.proc = Proc("osd")
        self.fail_ts = 0.0
        self.hk = None

    def tick(self):
        from . import paths, settings
        want = bool(settings.S.get("osdOn")) and paths.IS_WIN
        alive = self.proc.alive()
        hk = settings.S.get("osdHotkey")
        if alive and self.hk is not None and hk != self.hk:       # 换了快捷键：重开一次小框才生效
            self.proc.stop()
            alive, self.fail_ts = False, 0.0
        self.hk = hk
        if want and not alive and time.time() - self.fail_ts > 30:
            self.fail_ts = time.time()
            exe = sys.executable
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            try:
                self.proc.start([pyw if os.path.exists(pyw) else exe, "-m", "app.osd"], paths.ROOT, dict(os.environ))
            except Exception as e:
                print("游戏内显示没起来：", e)
        elif not want and alive:
            self.proc.stop()

    def stop(self):
        self.proc.stop()


_ctl = None


def ctl():
    global _ctl
    if _ctl is None:
        _ctl = Ctl()
    return _ctl


def state():
    """/api/osd：小框每秒来拿一次（设置 + 硬件读数）。"""
    from . import hw, settings
    cfg = {k: settings.S.get(k, v) for k, v in DEFAULTS.items()}
    return {"ts": time.time(), "cfg": cfg, "hw": hw._cache.get("data") or {}}


# ======================= 小框本身（在游戏上面那个窗口） =======================
def run(port=8765):
    import ctypes
    import tkinter as tk
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    url = f"http://127.0.0.1:{port}/api/osd"
    shared = {"cfg": dict(DEFAULTS), "hw": {}, "ok_ts": time.time(), "hidden": False}

    def fetch_loop():
        while True:
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    j = json.loads(r.read().decode("utf-8"))
                shared.update(cfg=j.get("cfg") or shared["cfg"], hw=j.get("hw") or {}, ok_ts=time.time())
            except Exception:
                pass
            time.sleep(1)

    def hotkey_loop(spec):
        if not spec:
            return
        if not user32.RegisterHotKey(None, 1, spec[0] | 0x4000, spec[1]):       # 0x4000 = MOD_NOREPEAT
            print("快捷键被别的程序占了：", spec)
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:                                            # WM_HOTKEY
                shared["hidden"] = not shared["hidden"]

    threading.Thread(target=fetch_loop, daemon=True).start()
    first_hk = shared["cfg"].get("osdHotkey", DEFAULTS["osdHotkey"])
    threading.Thread(target=hotkey_loop, args=(HOTKEYS.get(first_hk),), daemon=True).start()

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    bg = "#0b0f14"
    root.configure(bg=bg)
    box = tk.Frame(root, bg=bg, padx=10, pady=6)
    box.pack()
    root.attributes("-alpha", 0.0)
    root.update_idletasks()
    hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
    GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TOPMOST = -20, 0x80000, 0x20, 0x80, 0x08000000, 0x8
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST)

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    def monitors():
        out = []
        cb_t = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

        def cb(hmon, hdc, rect, data):
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
            r = mi.rcMonitor
            out.append(((r.left, r.top, r.right, r.bottom), bool(mi.dwFlags & 1)))
            return 1
        user32.EnumDisplayMonitors(None, None, cb_t(cb), 0)
        out.sort(key=lambda m: (not m[1], m[0][0], m[0][1]))                     # 主屏排第一个
        return [m[0] for m in out] or [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]

    rows, last = [], {"sig": None, "show": None, "geo": None}
    SIZES = {"s": 10, "m": 12, "l": 15}

    def draw():
        cfg, hw = shared["cfg"], shared["hw"]
        if time.time() - shared["ok_ts"] > 15 or not cfg.get("osdOn"):
            root.destroy()                                                       # 后端没了，或者设置里关了
            return
        show = visible(cfg, hw, shared["hidden"])
        ls = lines(cfg, hw)
        size = SIZES.get(cfg.get("osdSize"), 12)
        sig = (tuple(ls), size)
        if sig != last["sig"]:
            last["sig"] = sig
            for w in rows:
                w.destroy()
            rows.clear()
            for i, (name, val, color) in enumerate(ls):
                a = tk.Label(box, text=name, fg=COLORS["label"], bg=bg, font=("Microsoft YaHei UI", size - 1), anchor="w")
                b = tk.Label(box, text=val, fg=color, bg=bg, font=("Consolas", size, "bold"), anchor="e")
                a.grid(row=i, column=0, sticky="w", padx=(0, 12))
                b.grid(row=i, column=1, sticky="e")
                rows.extend([a, b])
        root.update_idletasks()
        mons = monitors()
        L, T, R, B = mons[min(int(cfg.get("osdScreen") or 0), len(mons) - 1)]
        w, h, m = root.winfo_reqwidth(), root.winfo_reqheight(), int(cfg.get("osdMargin") or 16)
        pos = cfg.get("osdPos", "tl")
        x = L + m if pos in ("tl", "bl") else R - w - m
        y = T + m if pos in ("tl", "tr") else B - h - m
        geo = f"+{x}+{y}"
        if geo != last["geo"]:
            last["geo"] = geo
            root.geometry(geo)
        alpha = max(0.3, min(1.0, float(cfg.get("osdOpacity") or 80) / 100)) if show else 0.0
        if alpha != last["show"]:
            last["show"] = alpha
            root.attributes("-alpha", alpha)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)    # 一直压在最上层（不移动、不改大小、不激活）
        root.after(500, draw)

    root.after(300, draw)
    root.mainloop()


if __name__ == "__main__":
    run(int(os.environ.get("AGENT_PORT", 8765)))
