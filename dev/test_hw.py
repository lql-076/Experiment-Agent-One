"""硬件读数和显存让路（不用起服务，Windows 的计数器用假数据）：
1. 显卡占用和任务管理器一样：每个引擎把各程序加起来，取最忙的（录屏时视频编码 99%，3D 只有 6%）
2. CPU 占用、频率以 Windows 计数器为准，传感器偏低的"各核平均频率"不再盖掉它
3. 我们自己占了多少显存（连子进程）
4. 显存让路：放得下不让；底座放不下或在玩游戏 → 1 级；嵌入模型都放不下 → 2 级；答你的时候不让；空出来几分钟才退、退回时装回嵌入模型
5. 硬盘有几块列几块，带盘符，按任务管理器的顺序
6. 本地模型环境：模型服务在线就直接算就绪，不再另开 Python
用法：python dev/test_hw.py"""
import asyncio
import pathlib
import sys
from collections import namedtuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from app import checks, hw, models, settings  # noqa: E402
from app.models import M, yield_want  # noqa: E402

bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


# ---------- 1. 显卡占用 ----------
NV, IG = "luid_0x00000000_0x0000D1A3", "luid_0x00000000_0x0000AAAA"
eng = [(f"pid_100_{NV}_phys_0_eng_0_engtype_3D", 4.0), (f"pid_200_{NV}_phys_0_eng_0_engtype_3D", 2.0),
       (f"pid_300_{NV}_phys_0_eng_1_engtype_VideoEncode", 99.0), (f"pid_300_{NV}_phys_0_eng_2_engtype_VideoDecode", 1.0),
       (f"pid_100_{NV}_phys_0_eng_3_engtype_Copy", 0.5), (f"pid_400_{IG}_phys_0_eng_0_engtype_3D", 30.0)]
pmem = [(f"pid_100_{NV}_phys_0", 3.0 * 2**30), (f"pid_300_{NV}_phys_0", 1.0 * 2**30), (f"pid_400_{IG}_phys_0", 0.2 * 2**30),
        (f"pid_555_{NV}_phys_0", 1.5 * 2**30), (f"pid_556_{NV}_phys_0", 0.5 * 2**30)]
g = hw.gpu_engines(eng, pmem)
check(g and round(g["load"]) == 99 and g["top"] == "视频编码", f"录屏时显卡占用 99%（和任务管理器一样，最忙的是视频编码）：{g}")
check(g and round(g["load3d"]) == 6 and round(g["enc"]) == 99 and round(g["dec"]) == 1, "3D 6%（两个程序 4 + 2 加起来）、编码 99%、解码 1%")
check(g and g["load"] < 100, "核显那块（显存用得少）不算进来")
check(hw.gpu_engines([("乱七八糟", 5.0)]) is None, "读不到引擎就返回 None（退回显卡驱动的读数）")

# ---------- 2. CPU 以计数器为准 ----------
LHM = {"Text": "Sensor", "Children": [{"Text": "PC", "Children": [
    {"Text": "AMD Ryzen 5 5600", "ImageURL": "images_icon/cpu.png", "Children": [
        {"Text": "Clocks", "Children": [{"Text": "Core #1", "Value": "2120.0 MHz", "Children": []},
                                        {"Text": "Core #2", "Value": "2120.0 MHz", "Children": []}]},
        {"Text": "Load", "Children": [{"Text": "CPU Total", "Value": "16.0 %", "Children": []}]},
        {"Text": "Temperatures", "Children": [{"Text": "Core (Tctl/Tdie)", "Value": "57.0 °C", "Children": []}]}]},
    *[{"Text": n, "ImageURL": "images_icon/hdd.png", "Children": [{"Text": "Temperatures", "Children": [
        {"Text": "Temperature", "Value": f"{t} °C", "Children": []}]}]} for n, t in
      (("Lexar SSD NM710 500GB", 49), ("FIKWOT FX900 512GB", 40), ("WDC WD1003BYX-01Y7B1", 36))]]}]}


class R:
    def json(self):
        return LHM


class FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        return R()


hw.httpx.AsyncClient = FakeClient
Freq = namedtuple("Freq", "current min max")
hw.psutil.cpu_freq = lambda: Freq(3501.0, 0.0, 3501.0)
hw.PDH.read = lambda: {"util": 21.0, "perf": 122.0, "eng": eng, "pmem": pmem}
hw.DISKS["tried"] = True
hw.DISKS["win"] = [{"Num": 3, "Name": "FIKWOT FX900 512GB", "Bus": "NVMe", "Letters": ["C", "E"]},
                   {"Num": 0, "Name": "WDC WD1003FZEX-00MK2A0", "Bus": "SATA", "Letters": ["H"]},
                   {"Num": 1, "Name": "WDC WD1003BYX-01Y7B1", "Bus": "SATA", "Letters": "D"},
                   {"Num": 2, "Name": "Lexar SSD NM710 500GB", "Bus": "NVMe", "Letters": ["F"]},
                   {"Num": 4, "Name": "Msft Virtual Disk", "Bus": "File Backed Virtual", "Letters": ["Z"]}]
d = asyncio.run(hw.sample())
c = d["cpu"]
check(round(c["load"]) == 21, f"CPU 占用用任务管理器的「利用率」：{c['load']}%（传感器说 16%）")
check(abs(c["clock"] - 3501 * 1.22 / 1000) < 0.01, f"CPU 频率 = 基础频率 × 性能百分比：{c['clock']:.2f} GHz（传感器的各核平均 2.12 不再盖掉它）")
check(c["temp"] == 57, "CPU 温度还是从传感器来")
check(round(d["gpu"]["load"]) == 99 and d["gpu"]["topTxt"] == " · 视频编码", f"显卡总占用 99%，标出「视频编码」：{d['gpu']['topTxt']!r}")

# ---------- 5. 硬盘 ----------
names = [x["n"] for x in d["disks"]]
check(len(names) == 4, f"4 块盘都列出来（虚拟盘不算）：{names}")
check(names[0].startswith("H:") and names[1].startswith("D:") and names[2].startswith("F:") and names[3].startswith("C: E:"),
      "按任务管理器的顺序（磁盘 0、1、2、3），名字前面带盘符")
check(d["disks"][0]["temp"] is None and d["disks"][3]["temp"] == 40, "传感器没读到的那块温度是「—」，对上型号的带温度")
check(hw.merge_disks([], hw.DISKS["win"]) == [], "助手没开（没有温度）时照旧显示「打开助手后显示」")
check(len(hw.parse_lhm({"Text": "S", "Children": [{"Text": f"盘{i}", "ImageURL": "images_icon/hdd.png", "Children": [
    {"Text": "Temperatures", "Children": [{"Text": "T", "Value": "30 °C", "Children": []}]}]} for i in range(5)]}).get("disks", [])) == 5,
      "传感器那边也不再只取前 3 块")

# ---------- 3. 自己占的显存 ----------
check(abs(hw.vram_of({555, 556}, pmem) - 2.0) < 1e-6, "我们自己占的显存：模型服务和它的子进程加起来 2.0 GB")
check(hw.vram_of({1}, None) is None or isinstance(hw.vram_of({1}, None), float), "读不到计数器时返回 None（改用估算）")

# ---------- 4. 显存让路 ----------
need = {"embed": 1.3, "base": 2.2, "kev": 2.0}
check(yield_want(16, 6, 2, 2, need)[0] == 0, "别的程序占 4 GB：不用让")
check(yield_want(16, 12, 2, 2, need)[0] == 1, "别的程序占 10 GB：底座 + Kev 放不下 → 1 级")
check(yield_want(16, 15.5, 1.3, 2, need)[0] == 2, "别的程序占 14.2 GB：嵌入模型都放不下 → 2 级")
check(yield_want(16, 6, 2, 2, need, game=True)[0] == 1, "认出在玩游戏 → 直接 1 级")

calls = []


async def fake(what, kind):
    calls.append(kind + ":" + what)


M.unload = lambda w: fake(w, "unload")
M.load = lambda w: fake(w, "load")
now = [1000.0]
models.time.time = lambda: now[0]
settings.S.update(yieldAuto=True, yieldVram=2.0, yieldCool=3, baseQuant="4bit", kevMode="ondemand")
own = [1.3]
M.own_vram = lambda: own[0]


def hwd(used, fps=None):
    return {"gpu": {"vram": used, "vramTotal": 16.0}, "fps": fps}


async def run():
    def tick(used, fps=None, dt=2):
        now[0] += dt
        M.tick(hwd(used, fps))

    for _ in range(5):
        tick(5.0)
    check(M.yield_level == 0, "显存够：不让路")
    tick(15.6)
    tick(15.6)
    check(M.yield_level == 0, "才 2 次（4 秒）：先不动，免得一闪就让")
    tick(15.6)
    await asyncio.sleep(0)
    check(M.yield_level == 2 and "unload:base" in calls and "unload:embed" in calls, f"连续 3 次放不下：2 级，底座、嵌入模型都卸掉（{calls}）")
    check(M.yielding and "显存全让出来" in M.yield_reason, f"让路原因：{M.yield_reason}")
    check(await M.embed(["x"]) is None, "2 级时不去用（也不会把）嵌入模型（装回去）")
    own[0] = 0.4
    tick(9.0)                       # 第一次放得下：开始计时
    tick(9.0, dt=60)
    tick(9.0, dt=60)
    check(M.yield_level == 2, "空出来才 2 分钟：还不退")
    tick(9.0, dt=61)
    await asyncio.sleep(0)
    check(M.yield_level == 1 and "load:embed" in calls, f"空出来 3 分钟（别的占 8.6 GB）：退到 1 级，把嵌入模型装回去（{calls}）")
    calls.clear()
    tick(4.0)
    tick(4.0, dt=60)
    tick(4.0, dt=60)
    check(M.yield_level == 1, "又空了 2 分钟：还在 1 级")
    tick(4.0, dt=61)
    check(M.yield_level == 0 and not M.yielding and not any(c.startswith("load:base") for c in calls), "又空了 3 分钟：让路结束，底座不提前装")
    for _ in range(3):
        tick(4.0, fps={"fps": 140, "fg": True, "proc": "Palworld-Win64-Shipping.exe"})
    check(M.yield_level == 1 and "Palworld" in M.yield_reason, f"认出在玩游戏：{M.yield_reason}")
    tick(4.0)
    tick(4.0, dt=60)
    tick(4.0, dt=60)
    check(M.yield_level == 1, "游戏退了：等 3 分钟")
    tick(4.0, dt=61)
    check(M.yield_level == 0, "退了 3 分钟后让路结束")
    M.busy_until = now[0] + 600
    for _ in range(4):
        tick(15.6)
    check(M.yield_level == 0, "正在用本地模型回答你：答完再让")
    M.busy_until = 0
    for _ in range(3):
        tick(15.6)
    check(M.yield_level == 2, "答完了：该让就让")
    settings.S["yieldAuto"] = False
    tick(15.6)
    check(M.yield_level == 0, "设置里关了让路：马上恢复")


asyncio.run(run())

# ---------- 6. 本地模型环境 ----------
M.ai_ready = lambda: True


async def health(**k):
    return {"cuda": True, "torch": "2.9.0+cu128", "cuda_version": "12.8"}


M.health = health
r = asyncio.run(checks.c_aienv())
check(r["st"] == "ok" and "模型服务正在用它跑" in r["d"], f"模型服务在线：直接就绪，不另开 Python（{r['d']}）")


async def no_health(**k):
    return None


M.health = no_health
M.server.alive = lambda: True
checks._ai_cache.update(ts=0, res=None)
r = asyncio.run(checks.c_aienv())
check(r["st"] == "run", f"模型服务正在启动：显示「检测中」，不是缺失（{r['d']}）")

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
