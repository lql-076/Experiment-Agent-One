"""后台监控：正在跑的任务、各个服务的状态、日志。给界面的「后台」页用。

日志都在 data\\logs\\ 里：
  backend.log        后端自己说的话（没有黑窗口了，都写在这里）
  hw_helper.log      硬件监控助手
  osd.log            游戏内显示
  model_server.log   本地模型服务
  kev.log            Kev
  tts.log            配音服务
  setup_*.log        一键补齐的每一步
  crash.log          后端底层崩溃的记录（正常时只有每次启动的一行）
"""
import os
import re
import sys
import time
from datetime import datetime

from . import db, deepseek, feed, paths, settings, setup, websearch
from .models import M
from .qq import BOT

T0 = time.time()
LOG_RE = re.compile(r"^[\w.\-]+\.log$")
LABEL = {"setup_git.log": "补齐 1 · Git", "setup_aienv.log": "补齐 2 · 模型环境", "setup_models.log": "补齐 3 · 下载模型",
         "setup_start.log": "补齐 4 · 启动服务", "setup_kev.log": "补齐 5 · Kev 权重", "setup_hwmon.log": "补齐 6 · 硬件监控",
         "backend.log": "后端", "crash.log": "崩溃记录", "model_server.log": "模型服务", "kev.log": "Kev", "tts.log": "配音服务", "hw_helper.log": "硬件监控助手", "osd.log": "游戏内显示"}


# ---------- 后端有没有正常退出 ----------
# 后端在跑的时候，data\logs\running.json 里记着进程号、什么时候起来的、最近一次"还活着"的时间（每半分钟更新）。
# 点「退出 Agent」会删掉它；下次启动时它还在，就说明上次不是正常退出的：电脑关机重启、被结束进程、或者崩溃了。
# 底层崩溃（Python 自己都来不及打印报错的那种）由 faulthandler 写进 data\logs\crash.log。
_guard = {"crash": None, "last": None}


def _flag():
    return paths.LOGS / "running.json"


def exit_reason(flag, boot_time, crash_text):
    """上次为什么停了。flag：上次留下的 running.json；boot_time：这次开机时间；crash_text：crash.log 里上次那一段。
    返回 (种类, 一句话)：reboot 电脑关机或重启了 / crash 崩溃了 / killed 被结束了（或者崩溃了没留下记录）。"""
    beat = float(flag.get("beat") or flag.get("start") or 0)
    when = datetime.fromtimestamp(beat).strftime("%m-%d %H:%M") if beat else "不知道什么时候"
    if beat and boot_time and beat < boot_time:
        return "reboot", f"上次 Agent 在 {when} 前后随电脑关机或重启停了"
    if crash_text and "Fatal Python error" in crash_text:
        line = next((x for x in crash_text.splitlines() if "Fatal Python error" in x), "").strip()
        return "crash", f"上次 Agent 在 {when} 前后崩溃了：{line[:120]}（详细记在 data\\logs\\crash.log）"
    return "killed", (f"上次 Agent 在 {when} 前后停了，不是点「退出 Agent」停的：可能是在任务管理器里结束了 Python 进程，"
                      "也可能是崩溃了没留下记录。它开的模型服务这些子进程，这次启动时会先清理掉")


def start_guard():
    """后端一起来就调：打开崩溃记录，看看上次是不是正常退出，再写上这一次的运行标记。"""
    import faulthandler
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    crash = paths.LOGS / "crash.log"
    prev_crash = ""
    try:
        txt = crash.read_text("utf-8", errors="replace") if crash.exists() else ""
        prev_crash = txt.rsplit("===== ", 1)[-1] if "===== " in txt else txt
    except Exception:
        pass
    try:
        f = open(crash, "a", encoding="utf-8")
        f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 后端启动 · 进程 {os.getpid()}\n")
        f.flush()
        faulthandler.enable(file=f, all_threads=True)
        _guard["crash"] = f
    except Exception as e:
        print("打不开崩溃记录：", e)
    try:
        if _flag().exists():
            import json as _json
            import psutil
            old = _json.loads(_flag().read_text("utf-8") or "{}")
            _guard["last"] = exit_reason(old, psutil.boot_time(), prev_crash)
            print(_guard["last"][1])
    except Exception as e:
        print("读不了上次的运行标记：", e)
    beat()


def beat():
    """写运行标记（后台照看每半分钟调一次）。"""
    import json as _json
    try:
        old = _json.loads(_flag().read_text("utf-8")) if _flag().exists() else {}
        start = old.get("start") if old.get("pid") == os.getpid() else time.time()
        _flag().write_text(_json.dumps({"pid": os.getpid(), "start": start, "beat": time.time()}), "utf-8")
    except Exception:
        pass


def clean_exit():
    """正常退出（点「退出 Agent」、命令行里 Ctrl+C）：删掉运行标记，下次启动就不会当成意外退出。"""
    try:
        _flag().unlink()
    except Exception:
        pass


def report_last_exit():
    """进展报告加载好以后调：上次是意外停的（不是关机重启），写一句进去。"""
    last = _guard.get("last")
    if last and last[0] != "reboot":
        feed.add(last[1], "warn", job="后端")


def quiet_handler(loop, ctx):
    """Windows 上对方先断开连接时，asyncio 会打一大段「远程主机强迫关闭了一个现有的连接」：没有坏处，不往日志里写，
    免得把真正的报错淹掉。别的照常打印。"""
    if isinstance(ctx.get("exception"), (ConnectionResetError, ConnectionAbortedError)):
        return
    loop.default_exception_handler(ctx)


class _Tee:
    """打印的同时写一份到 backend.log（带时间）；没有黑窗口时就只写日志。"""

    def __init__(self, stream, path):
        self.s, self.path, self.bol = stream, path, True

    def write(self, text):
        try:
            self.s.write(text)
        except Exception:
            pass
        try:
            with open(self.path, "a", encoding="utf-8", errors="replace") as f:
                for part in text.splitlines(True):
                    if self.bol and part.strip():
                        f.write(time.strftime("%m-%d %H:%M:%S  "))
                    f.write(part)
                    self.bol = part.endswith("\n")
        except Exception:
            pass
        return len(text)

    def flush(self):
        try:
            self.s.flush()
        except Exception:
            pass

    def __getattr__(self, k):
        return getattr(self.s, k)


def tee_console():
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    p = paths.LOGS / "backend.log"
    try:   # 太大了就从头写（只保留最近的）
        if p.exists() and p.stat().st_size > 5 << 20:
            p.replace(p.with_suffix(".old.log"))
    except Exception:
        pass
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout, p)
        sys.stderr = _Tee(sys.stderr, p)


def logs():
    """标签页的顺序固定（后端、模型服务、Kev、一键补齐的 6 步），不会随写入时间跳来跳去。"""
    order = list(LABEL)
    out = []
    files = [f for f in paths.LOGS.glob("*.log") if not f.name.endswith(".old.log")]
    for f in sorted(files, key=lambda x: (order.index(x.name) if x.name in order else 99, x.name)):
        st = f.stat()
        out.append({"name": f.name, "label": LABEL.get(f.name, f.stem), "size": st.st_size, "mtime": st.st_mtime})
    return out


def tail(name, n=300):
    if not LOG_RE.match(name or ""):
        raise ValueError("日志名不对")
    p = paths.LOGS / name
    if not p.exists():
        return {"name": name, "lines": [], "size": 0, "mtime": 0}
    st = p.stat()
    with open(p, "rb") as f:
        f.seek(max(0, st.st_size - 96 * 1024))
        data = f.read().decode("utf-8", errors="replace")
    # Windows 上一行结尾是 \r\n：先去掉结尾的 \r，再取 \r 分开的最后一段（进度条用 \r 原地刷新）
    lines = [ln.rstrip("\r").split("\r")[-1] for ln in data.split("\n")]
    if st.st_size > 96 * 1024:
        lines = lines[1:]
    lines = [ln for ln in lines if ln.strip()][-n:]
    return {"name": name, "lines": lines, "size": st.st_size, "mtime": st.st_mtime, "path": paths.show(p)}


def _proc_info(pid):
    try:
        import psutil
        p = psutil.Process(pid)
        return {"pid": pid, "mem": round(p.memory_info().rss / 2**20), "up": time.time() - p.create_time()}
    except Exception:
        return {"pid": pid}


def _ago(ts):
    if not ts:
        return "还没有"
    d = time.time() - ts
    return "刚刚" if d < 60 else f"{int(d // 60)} 分钟前" if d < 3600 else f"{int(d // 3600)} 小时前" if d < 86400 else datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


async def services():
    out = []
    me = _proc_info(os.getpid())
    out.append({"k": "backend", "name": "后端", "st": "ok", "detail": "127.0.0.1:8765 · 界面和所有接口", "log": "backend.log", **me})
    h = await M.health(max_age=12)     # 用后台刚查过的结果，不现查（现查在 Windows 上要等 1~2 秒）
    if h:
        bits = ["嵌入模型已加载" if h.get("embed_loaded") else "嵌入模型没加载", "底座已加载" if h.get("base_loaded") else "底座闲置"]
        if (h.get("vram") or {}).get("alloc_gb") is not None:
            bits.append(f"占显存 {h['vram']['alloc_gb']} GB")
        st = "bad" if h.get("error") else "ok"
        detail = " · ".join(bits) + (f" · 出错：{h['error'][:80]}" if h.get("error") else "")
    elif M.server.alive():
        st, detail = "warn", "正在启动"
    else:
        st, detail = "off", "没在运行" if M.ai_ready() else "还没装本地模型环境"
    out.append({"k": "model", "name": "本地模型服务", "st": st, "detail": detail + (" · 让路中：" + M.yield_reason if M.yielding else ""),
                "log": "model_server.log", **(_proc_info(M.server.p.pid) if M.server.alive() else {})})
    if settings.S["kevMode"] == "off":
        kst, kd = "off", "设置里关掉了"
    elif await M.kev_ready(max_age=12):
        kst, kd = "ok", f"在线 · 127.0.0.1:{settings.S['kevPort']}"
    elif M.kevp.alive():
        kst, kd = "warn", "正在启动（第一次会下载权重）"
    else:
        kst, kd = "off", "用到才启动"
    out.append({"k": "kev", "name": "Kev（决策脑第二票）", "st": kst, "detail": kd, "log": "kev.log",
                **(_proc_info(M.kevp.p.pid) if M.kevp.alive() else {})})
    from .tts import T as tts
    th = tts._h if tts.proc.alive() else None
    if th:
        tst, td = "ok", ("在线 · " + ("装着" + {"custom": "预设音色", "design": "描述音色"}.get(th.get("loaded"), "") + "模型" if th.get("loaded") else "模型没装")
                         + (f" · 注意力 {th['attn']}" if th.get("attn") else "") + (" · 正在生成" if tts.busy() else ""))
    elif tts.proc.alive():
        tst, td = "warn", "正在启动"
    else:
        tst, td = "off", "用到才启动，闲置 " + str(settings.S.get("ttsIdle", 10)) + " 分钟关掉" if tts.env_ok() else "还没装（设置 › 本地模型 点「安装配音」）"
    out.append({"k": "tts", "name": "配音服务", "st": tst, "detail": td, "log": "tts.log", **(_proc_info(tts.proc.p.pid) if tts.proc.alive() else {})})
    qs = {"online": "ok", "connecting": "warn", "error": "bad"}.get(BOT.status, "off")
    out.append({"k": "qq", "name": "QQ 通道", "st": qs, "detail": BOT.detail, "log": "backend.log"})
    from . import hw
    src = (hw._cache.get("data") or {}).get("sources") or {}
    out.append({"k": "hw", "name": "硬件监控助手", "st": "ok" if src.get("sensors") else "off",
                "detail": ("传感器可读（管理员运行中）" + (" · 游戏帧数可读" if src.get("fps") else " · 游戏帧数读不了（看「硬件监控助手」日志）"))
                          if src.get("sensors") else "没在运行：CPU 温度、功耗、硬盘温度、游戏帧数读不到（设置 › 硬件监控 打开）"})
    b = deepseek.balance_cached() or {}
    last = db.one("SELECT ts, purpose FROM costs ORDER BY id DESC LIMIT 1")
    calls = db.one("SELECT COUNT(*) n FROM costs WHERE ts>?", (time.time() - 86400,))["n"]
    if settings.get_secret("dsKey"):
        out.append({"k": "ds", "name": "DeepSeek", "st": "bad" if b.get("err") else "ok",
                    "detail": f"余额 {deepseek.money(b.get('total'), b.get('currency', 'CNY'))} · 24 小时内调用 {calls} 次（其中联网 {websearch.stats()['day']['n']} 次） · 最近一次 {_ago(last['ts'] if last else 0)}"
                              + (f"（{last['purpose']}）" if last else "")})
    else:
        out.append({"k": "ds", "name": "DeepSeek", "st": "off", "detail": "还没填 Key"})
    nl = db.kv_get("nightly_last") or {}
    out.append({"k": "nightly", "name": "每日差事", "st": "ok" if nl else "off",
                "detail": f"上次 {_ago(nl.get('ts'))}" + (f" · 有问题：{'；'.join(list((nl.get('errs') or {}).values())[:2])[:80]}" if nl.get("errs") else "")
                          + " · 电脑开着、你 20 分钟没找它时跑，一天一次"})
    q = db.one("SELECT COUNT(*) n FROM events WHERE status='queued'")["n"]
    out.append({"k": "queue", "name": "排队的事", "st": "warn" if q else "ok", "detail": f"{q} 件等本地模型（隐私内容）" if q else "没有"})
    return out


async def overview():
    st = setup.status()
    return {"ts": time.time(), "up": time.time() - T0, "root": paths.show(paths.ROOT),
            "setup": {"running": st["running"], "cur": st["cur"], "line": st["line"], "say": feed.last(setup.JOBN) if st["running"] else "",
            "started": st["started"], "finished": st["finished"],
            "steps": [{k: s[k] for k in ("k", "t", "st", "info", "prog", "t0", "t1")} for s in st["steps"]]},
            "services": await services(), "logs": logs()}
