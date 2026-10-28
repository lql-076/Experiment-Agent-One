"""开机稳不稳（不用起服务）：
1. 开机头 2 分钟：会自己好的项（模型服务在加载、助手在启动、网还没连上）显示「启动中」，不判缺失；真缺的（没填 Key、Key 不对）照样缺失
2. 后台重查一项一项写回；查的时候你在界面上重查过这一项，以你那次为准；DeepSeek 好了就不再每半分钟问一次
3. 状态变了写进日志；开机缓冲过后变成缺失的写进进展报告；缓冲结束时还在「启动中」的再查一遍
4. 上次留下的子进程：只认本项目的模型服务、Kev、游戏内小框，别的 Python 程序不碰
5. 上次为什么停了：关机重启 / 崩溃 / 被结束
6. Windows 上「远程主机强迫关闭连接」的噪音不打印，别的报错照常打印
用法：python dev/test_startup.py"""
import asyncio
import io
import pathlib
import sys
import time
from contextlib import redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from app import checks, deepseek, feed, monitor, settings  # noqa: E402
from app.models import orphan_kind  # noqa: E402

bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


class FakeDB:
    def __init__(self):
        self.kv = {}

    def kv_get(self, k, d=None):
        return self.kv.get(k, d)

    def kv_set(self, k, v):
        self.kv[k] = v


DB = FakeDB()
checks.db = DB
fed = []
feed.add = lambda text, kind="info", **k: fed.append((kind, text))

# ---------- 1. 开机缓冲 ----------
checks.T0 = time.time()
r = checks.settle("hwmon", checks.wait("开关开着，助手正在启动或没起来", heal=True))
check(r["st"] == "run" and r["d"].startswith("启动中"), f"开机 2 分钟内，助手还没起来：显示「{r['d'][:12]}…」，不判缺失")
r = checks.settle("ds", checks.miss("还没有填 Key"))
check(r["st"] == "miss", "没填 Key：开机时也照样是缺失（不会自己好）")
checks.T0 = time.time() - 200
r = checks.settle("hwmon", checks.wait("开关开着，助手正在启动或没起来", heal=True))
check(r["st"] == "wait", "过了 2 分钟还没起来：按原样显示")

settings.get_secret = lambda k: "sk-test-0000"


async def bal(err):
    async def f(force=False):
        return {"err": err}
    deepseek.refresh_balance = f
    return await checks.c_ds()

r = asyncio.run(bal("ConnectError: 连不上"))
check(r["st"] == "miss" and r.get("heal"), "DeepSeek 连不上（刚开机没网）：算「会自己好」")
r = asyncio.run(bal("Key 不对（401）"))
check(r["st"] == "miss" and not r.get("heal"), "DeepSeek Key 不对：不算会自己好")

# ---------- 2. 后台重查一项一项写回 ----------
checks.T0 = time.time()
DB.kv = {"checks": {"ts": 1, "res": {k: {"st": "ok", "d": "好", "at": 1} for k in checks.CHECKS}}}
DB.kv["checks"]["res"]["models"] = {"st": "wait", "d": "没在运行", "at": 1}
t = time.time()
DB.kv["checks"]["res"]["hwmon"] = {"st": "miss", "d": "你刚点过重查", "at": t + 5}
with redirect_stdout(io.StringIO()) as out:
    ch1 = checks.record("models", checks.ok("在线"), since=t)
    ch2 = checks.record("hwmon", checks.ok("后台查到的"), since=t)
res = DB.kv["checks"]["res"]
check(ch1 and res["models"]["st"] == "ok", "模型服务后台查到在线：写回、状态变了")
check(not ch2 and res["hwmon"]["d"] == "你刚点过重查", "查的这会儿你在界面上重查过这一项：以你那次为准（别的项照样写回）")
check(DB.kv["checks"]["ts"] > 1, "状态变了：更新时间戳，界面会自己刷新")
check("自检：本地模型服务 待处理 → 已就绪" in out.getvalue(), f"状态变了写进日志：{out.getvalue().strip()[:40]}")

calls = []
for k in checks.LIVE:
    checks.CHECKS[k] = (lambda kk: (lambda: (calls.append(kk), asyncio.sleep(0, result=checks.ok("好")))[1]))(k)
with redirect_stdout(io.StringIO()):
    asyncio.run(checks.refresh_live())
check("ds" not in calls and "models" in calls, f"后台重查：DeepSeek 好着就不再问（这轮查了 {calls}）")
DB.kv["checks"]["res"]["ds"] = {"st": "miss", "d": "连不上", "at": 1}
calls.clear()
with redirect_stdout(io.StringIO()):
    asyncio.run(checks.refresh_live())
check("ds" in calls, "DeepSeek 没好：每轮都重查，网连上了自己变绿")

# ---------- 3. 缓冲过后变缺失写进展报告；缓冲结束再查一遍 ----------
fed.clear()
checks.T0 = time.time() - 200
with redirect_stdout(io.StringIO()):
    checks.record("qq", checks.miss("连不上 QQ 开放平台"))
check(any("「QQ 官方机器人」缺失" in t for _, t in fed), "开机缓冲过后变成缺失：写进进展报告")
DB.kv["checks"]["res"]["driver"] = {"st": "run", "d": "启动中 · 检测超时", "at": 1}
checks.CHECKS["driver"] = lambda: asyncio.sleep(0, result=checks.ok("RTX 5060 Ti"))
fed.clear()
with redirect_stdout(io.StringIO()) as out:
    left = asyncio.run(checks.after_boot())
check(DB.kv["checks"]["res"]["driver"]["st"] == "ok", "缓冲结束时还在「启动中」的：再查一遍，变成真实结果")
check("开机 2 分钟后的整备" in out.getvalue() and any("没好的" in t for _, t in fed) == bool(left),
      f"缓冲结束写一句整备情况：{out.getvalue().strip().splitlines()[-1][:50]}")

# ---------- 4. 上次留下的子进程 ----------
ROOT = r"F:\Agent"
ms = r"F:\Agent\ai-env\Scripts\python.exe F:\Agent\app\model_server.py --port 8090"
check(orphan_kind(ms, r"F:\Agent\ai-env\Scripts\python.exe", r"F:\Agent", ROOT) == "本地模型服务", "认出上次留下的本地模型服务")
check(orphan_kind(r"C:\Python313\python.exe F:\Agent\app\model_server.py --port 8090", r"C:\Python313\python.exe", r"F:\Agent", ROOT) == "本地模型服务",
      "虚拟环境真正干活的那个子进程也认得出")
check(orphan_kind(r"python.exe -m kev.serve --run x --port 8091", r"F:\Agent\ai-env\Scripts\python.exe", r"F:\Agent\kev", ROOT) == "Kev", "认出 Kev")
check(orphan_kind(r"pythonw.exe -m app.osd", r"F:\Agent\.venv\Scripts\pythonw.exe", r"F:\Agent", ROOT) == "游戏内显示", "认出游戏内小框")
check(orphan_kind(r"pythonw.exe F:\Agent\app\launch.py", r"F:\Agent\.venv\Scripts\pythonw.exe", r"F:\Agent", ROOT) is None, "后端自己不算")
check(orphan_kind(r"python.exe -m kev.serve", r"E:\gongzuochengxu\Hermes\python.exe", r"E:\gongzuochengxu", ROOT) is None, "别的文件夹里跑的同名程序不碰")
check(orphan_kind(r"python.exe -m app.osd", r"F:\Agent2\python.exe", r"F:\Agent2", ROOT) is None, "名字像（F:\\Agent2）也不碰")
check(orphan_kind(r"node.exe server.js", r"C:\node\node.exe", r"F:\Agent", ROOT) is None, "别的程序一概不碰")

# ---------- 5. 上次为什么停了 ----------
now = time.time()
k, msg = monitor.exit_reason({"pid": 1, "start": now - 9000, "beat": now - 8000}, now - 3600, "")
check(k == "reboot", f"运行标记比这次开机还早：随电脑关机或重启停的（{msg[:24]}…）")
k, msg = monitor.exit_reason({"pid": 1, "start": now - 900, "beat": now - 60}, now - 86400, "Fatal Python error: Segmentation fault\n...")
check(k == "crash" and "Segmentation" in msg, "crash.log 里有底层报错：崩溃了")
k, msg = monitor.exit_reason({"pid": 1, "start": now - 900, "beat": now - 60}, now - 86400, "")
check(k == "killed" and "任务管理器" in msg, "开机后、没崩溃记录：被结束了（或者崩溃了没留下记录）")

# ---------- 6. 日志噪音 ----------
seen = []


class Loop:
    def default_exception_handler(self, ctx):
        seen.append(ctx)


monitor.quiet_handler(Loop(), {"message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost()", "exception": ConnectionResetError(10054)})
check(not seen, "「远程主机强迫关闭连接」不打印")
monitor.quiet_handler(Loop(), {"message": "别的错", "exception": ValueError("x")})
check(len(seen) == 1, "别的报错照常打印")

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
