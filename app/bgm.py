r"""配乐（v3.0）：本地 ACE-Step 1.5 出纯音乐，替 Suno（MIT 协议，能商用；显存最低不到 4 GB）。

怎么装（v3.1 起）：设置 › 整备 ›「配音、语音、配乐」一键装好（scripts\install_bgm.py）：下官方 Windows 便携包、解压到 Agent 文件夹里的
ace-step\、用它自带的 Python 下好模型。装好了这里直接用那一份，设置里什么都不用填。
- 用到时 Agent 自己启动它的接口：照它的 start_api_server.bat 那样跑 python_embedded\python.exe acestep\api_server.py（不走那个 bat：
  它会检查更新、问 Y/N，没有窗口就卡住），不弹黑窗口，日志在 data\logs\bgm.log；只开出曲子要的部分（ACESTEP_INIT_LLM=false，不装语言模型）；
  闲置 bgmIdle 分钟关掉，打游戏让路时关掉——和配音服务一个规矩。
- 也能用自己装的一份：设置 › 配乐 填它的文件夹（bgmDir）；或者自己把接口开着，Agent 只连 bgmUrl（默认 http://127.0.0.1:8001）。

接口（ACE-Step 1.5 的 REST API）：POST /release_task 交任务 → POST /query_result 每 2 秒问一次 → 拿到 file（/v1/audio?path=…）下载。
纯音乐：歌词写 [Instrumental]。一次出一首。出好的存在 配乐输出\日期\时分秒_描述.wav，旁边一份同名 .json（描述、时长、用时）。
只连本机；发给它的只有描述和时长。"""
import asyncio
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from . import db, feed, mediainfo, paths, settings
from .models import M, Proc

OUT = paths.ROOT / "配乐输出"
INSTALL = paths.ROOT / "ace-step"                    # 整备一键装好的那一份（v3.1）
NEED_GB = 5.0
JOBN = "配乐"
PY_DIRS = ("python_embeded", "python_embedded", "python", ".venv/Scripts", "venv/Scripts", ".venv/bin", "venv/bin")


class BgmError(RuntimeError):
    pass


class Bgm:
    def __init__(self):
        self.proc = Proc("bgm")
        self.proc.vram_est = NEED_GB
        M.extra.append(self.proc)
        self.last = 0.0
        self.job = None
        self._lock = asyncio.Lock()

    @property
    def s(self):
        return settings.S

    def url(self, p=""):
        return (self.s.get("bgmUrl") or "http://127.0.0.1:8001").rstrip("/") + p

    def folder(self):
        v = str(self.s.get("bgmDir") or "").strip().strip('"')
        if v:
            return Path(v)
        return INSTALL if (INSTALL / "acestep" / "api_server.py").exists() else None

    def builtin(self):
        """用的是整备里一键装好的那一份（没在设置里填别的文件夹）。"""
        return not str(self.s.get("bgmDir") or "").strip() and self.folder() == INSTALL

    def installed(self):
        """整备一键装好的那一份：程序在、模型下全了。"""
        ck = INSTALL / "checkpoints"
        return ((INSTALL / "acestep" / "api_server.py").exists() and any((INSTALL / s / "python.exe").exists() or (INSTALL / s / "python").exists()
                                                                          for s in ("python_embedded", "python_embeded"))
                and all((ck / m).is_dir() and any((ck / m).rglob("*.safetensors")) for m in ("acestep-v15-turbo", "vae", "Qwen3-Embedding-0.6B")))

    def python(self):
        d = self.folder()
        if not d:
            return None
        for sub in PY_DIRS:
            for exe in ("python.exe", "python"):
                p = d / sub / exe
                if p.exists():
                    return p
        return None

    def configured(self):
        """配没配：填了文件夹（找得到它的 Python 或 uv），或者接口本来就开着（最近连上过）。"""
        d = self.folder()
        if d and d.is_dir() and (self.python() or shutil.which("uv")):
            return True
        return bool(not d and time.time() - float(db.kv_get("bgm_seen") or 0) < 30 * 86400)

    def cmd(self):
        d, py = self.folder(), self.python()
        m = re.match(r"https?://([^:/]+)(?::(\d+))?", self.url())
        host, port = (m.group(1), m.group(2) or "8001") if m else ("127.0.0.1", "8001")
        if py and (d / "acestep" / "api_server.py").exists():      # 和它的 start_api_server.bat 一样直接跑脚本（便携包的 Python 不认当前文件夹）
            return [py, d / "acestep" / "api_server.py", "--host", host, "--port", port]
        if py:
            return [py, "-m", "acestep.api_server", "--host", host, "--port", port]
        if d and shutil.which("uv"):
            return [shutil.which("uv"), "run", "acestep-api", "--host", host, "--port", port]
        return None

    def out_dir(self):
        return paths.resolve(self.s.get("bgmOut", ""), OUT)

    def busy(self):
        return bool(self.job and self.job["st"] == "run")

    async def health(self):
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                r = await c.get(self.url("/health"))
            ok = r.status_code == 200
        except Exception:
            ok = False
        if ok:
            db.kv_set("bgm_seen", time.time())
        return ok

    async def ensure(self, say=None, timeout=900):
        if await self.health():
            return
        cmd = self.cmd()
        if not cmd:
            raise BgmError("配乐还没装：到 设置 › 整备 点「配音、语音、配乐」那张卡片的一键装好（或者只装 ACE-Step 那一项）")
        if M.yielding:
            raise BgmError(f"现在在让路（{M.yield_reason or '显存不够'}），配乐先不开")
        if not self.proc.alive():
            env = M.env()
            env.update(ACESTEP_API_HOST=cmd[cmd.index("--host") + 1], ACESTEP_API_PORT=cmd[cmd.index("--port") + 1], PYTHONUTF8="1")
            env.setdefault("ACESTEP_INIT_LLM", "false")              # 只出纯音乐：语言模型不装（省 3GB 显存）
            if self.builtin():
                env["ACESTEP_CHECKPOINTS_DIR"] = str(INSTALL / "checkpoints")
            self.proc.start(cmd, self.folder(), env)
            self.last = time.time()
            feed.add("配乐服务（ACE-Step）启动中：第一次要下模型、装模型，会久一点（日志 data\\logs\\bgm.log）", "info", job=JOBN)
        t0 = time.time()
        while time.time() - t0 < timeout:
            await asyncio.sleep(1.5)
            if await self.health():
                return
            if not self.proc.alive():
                raise BgmError("配乐服务没起来（看 data\\logs\\bgm.log）：\n" + self.proc.tail(6))
            if say:
                say(f"正在启动配乐服务（{int(time.time() - t0)} 秒，第一次要下模型）……")
        raise BgmError("配乐服务启动超时（看 data\\logs\\bgm.log）")

    def stop(self, why=""):
        if self.proc.alive():
            kids = []
            try:
                import psutil
                kids = psutil.Process(self.proc.p.pid).children(recursive=True)
            except Exception:
                pass
            self.proc.stop()
            for k in kids:
                try:
                    k.kill()
                except Exception:
                    pass
            feed.add(f"配乐服务关了：{why}，显存还回去了" if why else "配乐服务关了", "info", job=JOBN)

    def tick(self):
        if not self.proc.alive():
            return
        if M.yielding:
            if self.busy():
                self.job["stop"] = M.yield_reason or "显存让路"
            self.stop(M.yield_reason or "显存让路")
            return
        idle = float(self.s.get("bgmIdle") or 10) * 60
        if not self.busy() and time.time() - (self.last or self.proc.started) > idle:
            self.stop(f"闲置 {int(idle // 60)} 分钟")

    @staticmethod
    def _data(j):
        return j.get("data") if isinstance(j, dict) and "data" in j and "code" in j else j

    async def generate(self, prompt, seconds=60, say=None, stopped=None):
        """出一首纯音乐。返回 {path, name, duration, sec, prompt}。一次只出一首（排队）。"""
        prompt = str(prompt or "").strip()
        if not prompt:
            raise BgmError("写一句描述：风格、情绪、乐器、快慢")
        if len(prompt) > 1000:
            raise BgmError("描述太长了（最多 1000 字）")
        try:
            seconds = max(10, min(600, int(float(seconds or 60))))
        except (TypeError, ValueError):
            seconds = 60
        say = say or (lambda _m: None)
        async with self._lock:
            job = self.job = {"id": int(time.time() * 1000), "st": "run", "prompt": prompt, "seconds": seconds, "t0": time.time(), "t1": 0.0, "msg": "准备中",
                              "stop": "", "err": "", "file": ""}
            try:
                r = await self._gen(job, say, stopped)
                job.update(st="done", t1=time.time(), msg=f"好了：{r['name']}", file=r["name"])
                feed.add(f"配乐好了：{paths.show(Path(r['path']))}（{mediainfo.clock(r['duration'] or seconds)}，用了 {r['sec']:.0f} 秒）", "ok", job=JOBN)
                feed.done(f"配乐 · {prompt[:20]} · {mediainfo.clock(r['duration'] or seconds)}", "本地 ACE-Step", r["sec"], "", "bgm")
                return r
            except BgmError as e:
                job.update(st="err", t1=time.time(), err=str(e), msg=str(e))
                feed.add(f"配乐没成：{e}", "warn", job=JOBN)
                raise
            finally:
                self.last = time.time()

    async def _gen(self, job, say, stopped):
        await self.ensure(lambda m: (job.update(msg=m), say(m)))
        fmt = "wav" if (self.s.get("bgmFormat") or "wav") not in ("mp3", "flac") else self.s["bgmFormat"]
        body = {"prompt": job["prompt"], "lyrics": "[Instrumental]", "audio_duration": job["seconds"], "audio_format": fmt, "batch_size": 1,
                "inference_steps": max(1, min(64, int(self.s.get("bgmSteps") or 8))), "thinking": False, "use_random_seed": True}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=120, write=30, pool=None)) as c:
                r = await c.post(self.url("/release_task"), json=body)
                if r.status_code != 200:
                    raise BgmError(f"ACE-Step 没接下任务（{r.status_code}）：{r.text[:160]}")
                tid = (self._data(r.json()) or {}).get("task_id")
                if not tid:
                    raise BgmError("ACE-Step 没给任务编号")
                t0 = time.time()
                while True:
                    await asyncio.sleep(2)
                    if job["stop"] or (stopped and stopped()):
                        raise BgmError("停下了" + (f"（{job['stop']}）" if job["stop"] else "") + "：ACE-Step 那边这一首会自己出完，不保存")
                    if time.time() - t0 > 1800:
                        raise BgmError("半小时还没出完，不等了")
                    m = f"正在配乐（{int(time.time() - t0)} 秒，{job['seconds']} 秒的曲子）……"
                    job["msg"] = m
                    say(m)
                    q = await c.post(self.url("/query_result"), json={"task_id_list": [tid]})
                    if q.status_code != 200:
                        continue
                    rows = self._data(q.json()) or []
                    row = rows[0] if isinstance(rows, list) and rows else {}
                    st = int(row.get("status") or 0)
                    if st == 2:
                        raise BgmError("ACE-Step 说这一首没出成（看 data\\logs\\bgm.log 或它自己的窗口）")
                    if st != 1:
                        continue
                    res = row.get("result")
                    if isinstance(res, str):
                        try:
                            res = json.loads(res)
                        except ValueError:
                            res = []
                    item = (res or [{}])[0] if isinstance(res, list) else {}
                    f = str(item.get("file") or "")
                    if not f:
                        raise BgmError("ACE-Step 出完了但没给音频")
                    a = await c.get(f if f.startswith("http") else self.url(f if f.startswith("/") else "/" + f))
                    if a.status_code != 200 or len(a.content) < 1000:
                        raise BgmError(f"音频没拿到（{a.status_code}）")
                    break
        except httpx.HTTPError as e:
            raise BgmError(f"和 ACE-Step 的连接断了：{type(e).__name__}") from None
        day = self.out_dir() / datetime.now().strftime("%Y-%m-%d")
        day.mkdir(parents=True, exist_ok=True)
        head = re.sub(r'[\\/:*?"<>|\r\n\t\s，。、；：！？,.;:!?]+', "", job["prompt"])[:14] or "配乐"
        p, k = day / f"{datetime.now():%H%M%S}_{head}.{fmt}", 2
        while p.exists():
            p, k = day / f"{datetime.now():%H%M%S}_{head}_{k}.{fmt}", k + 1
        tmp = p.with_name(p.name + ".part")
        tmp.write_bytes(a.content)
        tmp.replace(p)
        sec = time.time() - job["t0"]
        dur = mediainfo.probe(p).get("duration")
        meta = {"prompt": job["prompt"], "seconds": job["seconds"], "duration": dur, "took": round(sec, 1), "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "metas": item.get("metas"), "model": item.get("dit_model"), "steps": body["inference_steps"]}
        p.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        hist = db.kv_get("bgm_hist", []) or []
        hid = int(time.time() * 1000)
        hist.append({"id": hid, "ts": time.time(), "path": str(p), "name": p.name, "prompt": job["prompt"], "seconds": job["seconds"], "duration": dur, "took": round(sec, 1)})
        db.kv_set("bgm_hist", hist[-80:])
        return {"id": hid, "path": str(p), "name": p.name, "duration": dur, "sec": sec, "prompt": job["prompt"]}

    def history(self):
        out = []
        for h in reversed(db.kv_get("bgm_hist", []) or []):
            out.append({k: h.get(k) for k in ("id", "ts", "name", "prompt", "seconds", "duration", "took")} | {"exists": os.path.isfile(h.get("path") or "")})
        return out

    def hpath(self, hid):
        h = next((x for x in db.kv_get("bgm_hist", []) or [] if x.get("id") == int(hid)), None)
        if not h or not os.path.isfile(h.get("path") or ""):
            raise HTTPException(404, "这首找不到了（文件被挪走或删了）")
        return Path(h["path"])

    def public(self):
        j = self.job
        if not j:
            return None
        return {k: j.get(k) for k in ("id", "st", "prompt", "seconds", "msg", "err", "file")} | {"elapsed": round((j["t1"] or time.time()) - j["t0"])}

    async def status(self):
        d, up = self.folder(), await self.health()
        return {"up": up, "alive": self.proc.alive(), "configured": self.configured(), "url": self.url(), "dir": str(d) if d else "",
                "dir_ok": bool(d and d.is_dir()), "python": paths.show(self.python()) if self.python() else "", "can_start": bool(self.cmd()),
                "builtin": self.builtin(), "installed": self.installed(),
                "yielding": M.yielding, "yield_reason": M.yield_reason, "job": self.public(), "out": paths.show(self.out_dir()), "recent": self.history()[:30],
                "idle": int(self.s.get("bgmIdle") or 10), "steps": int(self.s.get("bgmSteps") or 8)}


B = Bgm()
api = APIRouter()


@api.get("/api/bgm")
async def bgm_status():
    return await B.status()


@api.post("/api/bgm/gen")
async def bgm_gen(body: dict = Body(...)):
    """开始出一首（马上返回，进度看 GET /api/bgm 的 job）。"""
    if B.busy():
        raise HTTPException(409, "上一首还在出，等它好了")
    prompt, seconds = str(body.get("prompt") or "").strip(), body.get("seconds") or 60
    if not prompt:
        raise HTTPException(400, "写一句描述：风格、情绪、乐器、快慢")
    if not B.cmd() and not await B.health():
        raise HTTPException(400, "配乐还没装：到 设置 › 整备 点「配音、语音、配乐」那张卡片的一键装好（或者只装 ACE-Step 那一项）")

    async def run():
        try:
            await B.generate(prompt, seconds)
        except BgmError:
            pass
    asyncio.get_running_loop().create_task(run())
    await asyncio.sleep(0.05)
    return {"job": B.public()}


@api.post("/api/bgm/stop")
def bgm_stop():
    if B.busy():
        B.job["stop"] = "你点了停下"
    return {"job": B.public()}


@api.post("/api/bgm/off")
def bgm_off():
    if B.busy():
        raise HTTPException(409, "正在出，先点「停下」")
    B.stop("你关的")
    return {"ok": True}


@api.get("/api/bgm/file/{hid}")
def bgm_file(hid: int):
    return FileResponse(B.hpath(hid), headers={"Cache-Control": "private, max-age=31536000"})


@api.post("/api/bgm/tows")
def bgm_tows(body: dict = Body(...)):
    """把一首放进 工作区\\素材\\配乐\\。"""
    from . import workspace
    p = B.hpath(body.get("id"))
    try:
        return workspace.take_in([p], "配乐")
    except workspace.Denied as e:
        raise HTTPException(400, str(e)) from None


@api.post("/api/bgm/open")
def bgm_open(body: dict = Body(default={})):
    d = B.hpath(body["id"]).parent if body.get("id") else B.out_dir()
    d.mkdir(parents=True, exist_ok=True)
    if paths.IS_WIN:
        os.startfile(str(d))
        return {"msg": "打开了：" + paths.show(d)}
    return {"msg": "文件夹在：" + paths.show(d)}
