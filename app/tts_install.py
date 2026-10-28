r"""安装配音：设置 › 本地模型 里的「安装配音」按钮走这里（和双击「安装配音.bat」做的一样，bat 留着备用）。

在后台跑 scripts\install_tts.py（没有黑窗口）：建配音环境 tts-env → PyTorch → qwen-tts 和它要的库 → 从魔搭下两个模型。
可以关掉界面，它接着装；进度在设置页和配音页上显示，每一步写进展报告（后台页，任务名「安装配音」），
原始输出在 data\logs\setup_tts.log。装过的跳过、下到一半的接着下，所以失败了再点一次就行。
停下：按进程号结束它和它开的子进程（pip 这些），不碰别的程序。一键补齐正在跑时不开始（两个都在下东西，容易打架）。
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time

from fastapi import APIRouter, Body, HTTPException

from . import feed, paths, setup
from .models import NOWIN

JOBN = "安装配音"
LOG = paths.LOGS / "setup_tts.log"
ST = {"st": "idle", "phase": "", "pct": None, "done": None, "total": None, "speed": None, "eta": None, "line": "",
      "t0": 0.0, "t1": 0.0, "code": None, "hf": False, "stop": False}
_p = {"p": None, "hist": [], "key": "", "pt0": 0.0}


def command():
    return [sys.executable, paths.ROOT / "scripts" / "install_tts.py"]


def public():
    return {k: ST[k] for k in ("st", "phase", "pct", "done", "total", "speed", "eta", "line", "t0", "t1", "code", "hf")} | {"log": paths.show(LOG)}


def _log(text):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
    except Exception:
        pass


def _finish_phase():
    """一个阶段结束：进展报告里的进度行改成一句结论（下载的写大小、用时、平均速度）。"""
    key, total = _p["key"], ST["total"] or 0
    if not key or not feed.has(key):
        return
    took = max(0.1, time.time() - _p["pt0"])
    if total > 1 and (ST["pct"] or 0) >= 99:
        feed.finish(key, f"{ST['phase']} 完成 · {feed.size(total)} · 用时 {feed.dur(took)} · 平均 {feed.size(total / took)}/s", "ok")
    elif total > 1:
        feed.finish(key, f"{ST['phase']} 停在 {ST['pct'] or 0:.0f}%（{feed.size(ST['done'] or 0)} / {feed.size(total)}）", "warn")
    else:
        feed.drop(key)


def _prog(phase, done=None, total=None, speed=None, eta=None, pct=None):
    now = time.time()
    if phase != ST["phase"]:
        _finish_phase()
        _p.update(hist=[], key=f"tts-install:{phase}", pt0=now)
    hist = [h for h in _p["hist"] if now - h[0] <= 5]
    if done is not None:
        hist.append((now, done))
    _p["hist"] = hist
    if speed is None and len(hist) > 1 and hist[-1][0] > hist[0][0]:
        speed = max(0.0, (hist[-1][1] - hist[0][1]) / (hist[-1][0] - hist[0][0]))
    if pct is None and total:
        pct = min(100.0, (done or 0) / total * 100)
    if eta is None and speed and total and done is not None:
        eta = max(0.0, (total - done) / speed)
    ST.update(phase=phase, done=done, total=total, speed=speed, eta=eta, pct=pct)
    if total and total < (20 << 20) and phase.startswith("下载 "):
        return                                          # 20MB 以下的小文件不单独写进展报告，免得刷屏
    feed.add(phase, "prog", job=JOBN, key=_p["key"], prog={"pct": pct, "done": done, "total": total, "speed": speed, "eta": eta})


def _line(line):
    """子程序打印的一行：进度行更新进度（不写日志），讲解写进展报告。返回要写进日志的内容（None = 不写）。"""
    s = line.strip()
    if not s:
        return None
    if s.startswith("@@PROGRESS "):
        try:
            j = json.loads(s[11:])
            _prog(j.get("phase") or "下载", j.get("done"), j.get("total") or None, j.get("speed"), j.get("eta"))
        except Exception:
            pass
        return None
    m = setup.PIP_RAW.match(s)
    if m:
        _prog("下载 " + (_p.get("pip") or "安装包"), int(m.group(1)), int(m.group(2)) or None)
        return None
    m = setup.TQDM.search(s)
    if m:
        u = setup.UNIT
        d, t = float(m.group("d")) * u[m.group("du")], float(m.group("t")) * u[m.group("tu")]
        r = float(m.group("r")) * u[m.group("ru")] if m.group("r") else None
        name = re.sub(r"^(Downloading|Downloading \[|下载)\s*", "", m.group("name").strip()).strip("[]: ") or "下载"
        _prog("下载 " + name[:50], d, t or None, r, setup._secs(m.group("eta") or ""), float(m.group("pct")))
        return None
    m = setup.PIP_DL.match(s)
    if m:
        _p["pip"] = m.group(1).split("/")[-1][:60]
    if s.startswith("@@SAY "):
        msg, kind = s[6:].strip(), "info"
        if msg[:1] in "!！":
            msg, kind = msg[1:].strip(), "warn"
        elif msg[:1] == "✓":
            msg, kind = msg[1:].strip(), "ok"
        feed.add(msg, kind, job=JOBN)
        ST["line"] = msg[:160]
        return msg
    m = setup.PIP_OK.match(s)
    if m:
        pk = m.group(1).split()
        names = [re.sub(r"-\d[\w.+!]*$", "", x) for x in pk]
        feed.add(f"装好了 {len(pk)} 个包：" + "、".join(names[:8]) + ("……" if len(pk) > 8 else ""), "ok", job=JOBN)
    elif s.startswith("Installing collected packages:"):
        feed.add("都下好了，正在把包装进配音环境（大的包要一两分钟，这时候没有进度条）", "info", job=JOBN)
    elif s.startswith("ERROR:"):
        feed.add("pip 报错：" + s[6:].strip()[:220], "err", job=JOBN)
    ST["line"] = s[:160]
    return s


def _blocking(hf):
    env = os.environ.copy()
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "AGENT_FEED": "1"})
    if hf:
        env["AGENT_MODEL_SOURCE"] = "hf"
    cmd = command()
    _log(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(map(str, cmd))}")
    p = subprocess.Popen([str(c) for c in cmd], cwd=str(paths.ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=NOWIN)
    setup._in_job(p)                                    # 后端没了，Windows 会把它一起结束
    _p["p"] = p
    if ST["stop"]:
        _kill(p)
    buf = ""
    while True:
        chunk = p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(4096)
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="replace")
        parts = re.split(r"[\r\n]", buf)
        buf = parts.pop()
        out = [x for x in (_line(x) for x in parts) if x]
        if out:
            _log("\n".join(out))
        if buf.strip() and setup.TQDM.search(buf.strip()):
            _line(buf)
    if buf.strip():
        x = _line(buf)
        if x:
            _log(x)
    code = p.wait()
    _p["p"] = None
    return code


async def _run(hf):
    try:
        code = await asyncio.to_thread(_blocking, hf)
    except Exception as e:
        code = -1
        ST["line"] = str(e)[:160]
    _finish_phase()
    ST.update(code=code, t1=time.time(), eta=None)
    if ST["stop"]:
        ST["st"] = "stop"
        feed.add("安装配音停了。再点「安装配音」会接着装、接着下", "warn", job=JOBN)
    elif code == 0:
        ST["st"] = "ok"
        feed.add(f"配音装好了（用时 {feed.dur(ST['t1'] - ST['t0'])}）。左边点「配音」就能用", "ok", job=JOBN)
    else:
        ST["st"] = "fail"
        feed.add(f"安装配音没完成（退出码 {code}）。再点一次会接着装；原始输出在 {paths.show(LOG)}", "err", job=JOBN)


def start(hf=False):
    if ST["st"] == "run":
        raise HTTPException(409, "已经在装了")
    if setup.status()["running"]:
        raise HTTPException(409, "一键补齐正在跑，等它完了再装配音")
    ST.update(st="run", phase="", pct=None, done=None, total=None, speed=None, eta=None, line="准备中", t0=time.time(), t1=0.0,
              code=None, hf=bool(hf), stop=False)
    _p.update(hist=[], key="", pt0=0.0)
    feed.add("开始安装配音：配音环境 tts-env、PyTorch、Qwen3-TTS，再从" + ("hf-mirror" if hf else "魔搭") + "下两个模型（一共约 14 GB，装过的跳过）",
             "head", job=JOBN)
    asyncio.get_event_loop().create_task(_run(hf))
    return public()


def stop():
    if ST["st"] != "run":
        return public()
    ST["stop"] = True
    _kill(_p["p"])                 # 还没起来的话，起来那一刻就停（_blocking 里看 ST["stop"]）
    return public()


def _kill(p):
    if not p or p.poll() is not None:
        return
    try:
        if paths.IS_WIN:      # 按进程号结束它和它开的子进程（pip、下载），不碰别的程序
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=NOWIN)
        else:
            import psutil
            for c in psutil.Process(p.pid).children(recursive=True):
                c.kill()
            p.terminate()
    except Exception:
        pass


api = APIRouter()


@api.post("/api/tts/install")
async def tts_install(body: dict = Body(default={})):
    return start(hf=bool(body.get("hf")))


@api.post("/api/tts/install/stop")
def tts_install_stop():
    return stop()
