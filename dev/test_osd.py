"""游戏内显示：小框里显示什么（lines）、什么时候显示（visible）、后端给它的数据（state）。
Win32 和 tkinter 那部分沙箱里跑不了，只能在 Windows 上实测。用法：python dev/test_osd.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import osd  # noqa: E402

bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg)
    if not ok:
        bad.append(msg)


hw = {"cpu": {"load": 35.2, "temp": 62.4, "power": 48}, "gpu": {"load": 97, "temp": 84, "power": 210.5, "vram": 9.83, "vramTotal": 16},
      "ram": {"used": 18.2, "total": 32}, "sys": {"power": 321}, "fps": {"fps": 142, "low1": 98.4, "proc": "Palworld-Win64-Shipping.exe"}}
cfg = dict(osd.DEFAULTS, osdOn=True, osdItems="fps,low1,cpu,gpu,vram,ram,power,time")
ls = osd.lines(cfg, hw)
names = [x[0] for x in ls]
check(names == ["FPS", "1% 低", "CPU", "GPU", "显存", "内存", "整机", "时间"], f"按设置的顺序排：{names}")
check(ls[0][1] == "142" and ls[1][1] == "98", f"帧数取整：{ls[0][1]} / {ls[1][1]}")
check(ls[2][1] == "35%  62°C  48W", f"CPU 一行：{ls[2][1]}")
check(ls[3][2] == osd.COLORS["hot"], "显卡 84°C 标成红色")
check(ls[4][1] == "9.8 / 16 G", f"显存：{ls[4][1]}")
check(osd.lines(dict(cfg, osdItems="fps,cpu"), {})[0][1] == "—", "读不到就显示 —")
check(osd.visible(cfg, hw, False) is True, "玩游戏时（读到帧数）显示")
check(osd.visible(cfg, {"fps": None}, False) is False, "没在玩游戏时不显示（只在游戏里显示）")
check(osd.visible(dict(cfg, osdWhen="always"), {}, False) is True, "选「一直显示」就一直显示")
check(osd.visible(cfg, hw, True) is False, "按了快捷键藏起来")
check(osd.visible(dict(cfg, osdOn=False), hw, False) is False, "总开关关着不显示")
scr = (0, 0, 2560, 1440)
check(osd.place("tc", scr, 600, 30, 16) == (980, 16), "顶部居中：横着一行放在屏幕上边正中间")
check(osd.place("bc", scr, 600, 30, 16) == (980, 1394), "底部居中")
check(osd.place("tr", scr, 200, 150, 16) == (2344, 16) and osd.place("bl", scr, 200, 150, 16) == (16, 1274), "四个角照旧")
check(osd.place("tc", (2560, 0, 4480, 1080), 600, 30, 16) == (3220, 16), "第二块屏幕上也居中")
print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
