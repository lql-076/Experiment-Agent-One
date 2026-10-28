"""模型管家：在主后端里管两个子进程——本地模型服务（嵌入 + 底座 + 小脑）和 Kev（配音服务在 app/tts.py 里管，显存一起算）。

- 只启动、只关闭自己开的进程（按进程号），绝不按名字杀进程。
- 嵌入模型常驻；底座由模型服务自己闲置卸载；Kev 按需启动，闲置后关掉。
- 让路：按显存算。别的程序（游戏、画图）占的显存多了，先卸底座和 Kev，还不够再卸嵌入模型；
  显存空出来几分钟再装回嵌入模型（底座还是用到才装）。让路期间非隐私的活交给 DeepSeek，隐私的排队。
"""
import asyncio
import os
import subprocess
import time

import httpx
import psutil

from . import paths, settings

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Proc:
    def __init__(self, name):
        self.name, self.p, self.started, self.cmd = name, None, 0.0, []

    def alive(self):
        return self.p is not None and self.p.poll() is None

    def start(self, cmd, cwd, env):
        if self.alive():
            return
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        log = open(paths.LOGS / f"{self.name}.log", "a", encoding="utf-8", errors="replace")
        log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动：{' '.join(map(str, cmd))}\n")
        log.flush()
        self.cmd = cmd
        self.p = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, creationflags=NOWIN)
        self.started = time.time()

    def stop(self):
        if self.alive():
            self.p.terminate()
            try:
                self.p.wait(10)
            except subprocess.TimeoutExpired:
                self.p.kill()
        self.p = None

    def tail(self, n=12):
        try:
            lines = (paths.LOGS / f"{self.name}.log").read_text("utf-8", errors="replace").splitlines()
            return "\n".join(lines[-n:])
        except FileNotFoundError:
            return ""


def orphan_kind(cmd, exe, cwd, root):
    """这个进程是不是上一次 Agent 留下的子进程（后端被直接结束时，它开的模型服务、Kev、游戏内小框还活着，占着端口）。
    只认本项目的：命令行里带本项目的模型服务脚本，或者在本项目文件夹里跑的 Kev / 游戏内显示。别的程序一概不碰。"""
    c, e, w, r = (cmd or "").lower(), (exe or "").lower(), (cwd or "").lower(), str(root).lower().rstrip("\\/")
    ours = any(x == r or x.startswith(r + "\\") or x.startswith(r + "/") for x in (e, w))
    if (r + "\\app\\model_server.py") in c or (r + "/app/model_server.py") in c:
        return "本地模型服务"
    if (r + "\\app\\tts_server.py") in c or (r + "/app/tts_server.py") in c:
        return "配音服务"
    if "-m kev.serve" in c and ours:
        return "Kev"
    if "-m app.osd" in c and ours:
        return "游戏内显示"
    return None


def yield_want(total, used, ours, reserve, need, game=False):
    """该让到哪一级。room = 显卡总显存 − 别的程序占的 − 预留，是我们最多能用的。
    嵌入模型都放不下 → 2；底座 + 嵌入 + Kev 放不下，或者在玩游戏 → 1；放得下 → 0。返回 (级别, 别的程序占的 GB)。"""
    others = max(0.0, used - ours)
    room = total - others - reserve
    if room < need["embed"]:
        return 2, others
    if game or room < need["embed"] + need["base"] + need["kev"]:
        return 1, others
    return 0, others


class Manager:
    def __init__(self):
        self.server = Proc("model_server")
        self.kevp = Proc("kev")
        self.extra = []                  # 别的模块开的、也占显存的子进程（配音服务 app/tts.py）：算显存、退出时一起停
        self.last_kev = 0.0
        self.busy_until = 0.0
        self.yield_level = 0             # 让路：0 不让 / 1 底座、Kev 不装 / 2 嵌入模型也卸，显存全让出来
        self.yield_reason = ""
        self.vram_info = {}
        self._up = 0
        self._down_since = 0.0
        self._lock = asyncio.Lock()
        self._health = None
        self._health_ts = 0.0
        self._kev_ok = False
        self._kev_ts = 0.0
        self._kev_offline = False        # 这次是不是"不联网"启动的（权重都在本机）
        self._kev_seen = False           # 这次启动后有没有真正在线过

    # ---------- 路径 ----------
    @property
    def s(self):
        return settings.S

    def aipy(self):
        return paths.resolve(self.s["aiPython"], paths.ai_python())

    def base_dir(self):
        return paths.resolve(self.s["baseDir"], paths.MODELS_BASE)

    def embed_dir(self):
        return paths.resolve(self.s["embedDir"], paths.MODELS_EMBED)

    def lora_dir(self):
        return paths.resolve(self.s["loraDir"], paths.MODELS_BRAINS)

    def kev_dir(self):
        return paths.resolve(self.s["kevDir"], paths.KEV)

    def url(self, p=""):
        return f"http://127.0.0.1:{self.s['modelPort']}{p}"

    def kurl(self, p=""):
        return f"http://127.0.0.1:{self.s['kevPort']}{p}"

    def env(self):
        e = dict(os.environ)
        e.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HOME=str(paths.HF_CACHE), TOKENIZERS_PARALLELISM="false")
        if self.s["hfMirror"]:
            e["HF_ENDPOINT"] = "https://hf-mirror.com"
        return e

    def ai_ready(self):
        return self.aipy().exists()

    # ---------- 模型服务 ----------
    async def health(self, fresh=False, max_age=2):
        # 服务没开时，Windows 上连一个没人听的端口要等 1~2 秒；界面轮询用缓存（后台每 10 秒刷新一次）
        if not fresh and time.time() - self._health_ts < max_age:
            return self._health
        try:
            async with httpx.AsyncClient(timeout=1.5) as c:
                r = await c.get(self.url("/health"))
                self._health = r.json() if r.status_code == 200 else None
        except Exception:
            self._health = None
        self._health_ts = time.time()
        return self._health

    def start_server(self):
        if not self.ai_ready():
            raise RuntimeError("还没装本地模型环境（运行 安装本地模型环境.bat）")
        cmd = [self.aipy(), paths.APP / "model_server.py", "--port", self.s["modelPort"], "--embed", self.embed_dir(),
               "--base", self.base_dir(), "--loras", self.lora_dir(), "--quant", self.s["baseQuant"],
               "--idle", self.s["idleUnload"]]
        self.server.start(cmd, paths.ROOT, self.env())

    async def ensure_server(self, timeout=120):
        h = await self.health(fresh=True)
        if h:
            return h
        async with self._lock:
            if not self.server.alive():
                self.start_server()
            t0 = time.time()
            while time.time() - t0 < timeout:
                await asyncio.sleep(1.0)
                h = await self.health(fresh=True)
                if h:
                    return h
                if not self.server.alive():
                    raise RuntimeError("本地模型服务启动失败：\n" + self.server.tail())
        raise RuntimeError("本地模型服务启动超时")

    async def restart_server(self):
        self.server.stop()
        self._health = None
        if self.ai_ready():
            self.start_server()

    async def embed(self, texts, instruct=True):
        """拿不到就返回 None（服务没起来、或者显存全让出来了时不阻塞，也不把嵌入模型装回去）。"""
        if self.yield_level >= 2:
            return None
        h = await self.health()
        if not h or not h.get("cuda"):
            return None
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(self.url("/embed"), json={"texts": texts, "instruct": instruct})
            if r.status_code != 200:
                return None
            return r.json()["vectors"]
        except Exception:
            return None

    async def chat(self, messages, lora=None, max_new_tokens=512, temperature=0.7, thinking=False):
        await self.ensure_server()
        self.busy_until = time.time() + 600
        try:
            async with httpx.AsyncClient(timeout=300) as c:
                r = await c.post(self.url("/chat"), json={"messages": messages, "lora": lora, "max_new_tokens": max_new_tokens,
                                                          "temperature": temperature, "thinking": thinking})
            if r.status_code != 200:
                raise RuntimeError(r.json().get("detail", r.text)[:300])
            return r.json()
        finally:
            self.busy_until = time.time() + 8

    async def unload(self, what):
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                await c.post(self.url("/unload"), json={"what": what})
        except Exception:
            pass

    # ---------- Kev ----------
    async def kev_ready(self, max_age=0):
        if max_age and time.time() - self._kev_ts < max_age:
            return self._kev_ok
        try:
            async with httpx.AsyncClient(timeout=1.5) as c:
                r = await c.get(self.kurl("/v1/models"))
                ok = r.status_code == 200
        except Exception:
            ok = False
        self._kev_ok, self._kev_ts = ok, time.time()
        if ok and not self._kev_seen:
            self._kev_seen = True
            from . import db
            if db.kv_get("kev_ok") != self.s["kevRun"]:
                db.kv_set("kev_ok", self.s["kevRun"])      # 完整启动过一次：底座和头都在本机了，以后不联网启动
        return ok

    def kev_installed(self):
        return (self.kev_dir() / "kev" / "serve.py").exists() and self.ai_ready()

    def kev_weights(self) -> bool:
        """Kev 的权重在不在本机（models\\hf-cache\\hub）：Kev 的快照在；它要是 LoRA，底座的快照也要在；
        没有下了一半的 .incomplete 文件。"""
        run = str(self.s.get("kevRun") or "")
        if os.path.isdir(run):
            return True
        hub = paths.HF_CACHE / "hub"

        def snaps(repo):
            d = hub / ("models--" + repo.split("@")[0].replace("/", "--")) / "snapshots"
            return [x for x in d.iterdir() if x.is_dir()] if d.is_dir() else []

        def has_weights(dirs):
            return any(f.suffix in (".pt", ".safetensors") for x in dirs for f in x.iterdir())

        try:
            mine = snaps(run)
            if not has_weights(mine):
                return False
            for x in mine:
                ac = x / "adapter_config.json"
                if ac.exists():
                    import json
                    base = json.loads(ac.read_text(encoding="utf-8")).get("base_model_name_or_path") or ""
                    if base and not os.path.isdir(base) and not any((y / "config.json").exists() for y in snaps(base)):
                        return False
                    if base and not os.path.isdir(base) and not has_weights(snaps(base)):
                        return False
            return not any(hub.glob("models--*/blobs/*.incomplete"))
        except (OSError, ValueError):
            return False

    def kev_cached(self) -> bool:
        """成功启动过一次、权重还在：以后启动不联网（HF_HUB_OFFLINE），不会再去下载。"""
        from . import db
        return db.kv_get("kev_ok") == self.s["kevRun"] and self.kev_weights()

    def start_kev(self):
        if not self.kev_installed():
            raise RuntimeError("Kev 还没装好（运行 安装本地模型环境.bat）")
        if self._kev_offline and not self._kev_seen:
            # 上次不联网启动、没起来（本机的文件不全）：这次联网，缺什么补什么
            from . import db
            db.kv_set("kev_ok", None)
        cmd = [self.aipy(), "-m", "kev.serve", "--run", self.s["kevRun"], "--port", self.s["kevPort"], "--device", "cuda"]
        env = self.env()
        self._kev_offline, self._kev_seen = self.kev_cached(), False
        if self._kev_offline:
            env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        self.kevp.start(cmd, self.kev_dir(), env)

    async def ensure_kev(self, wait=False, timeout=600):
        if self.s["kevMode"] == "off":
            return False
        if await self.kev_ready():
            return True
        if not self.kevp.alive():
            self.start_kev()
        if not wait:
            return False
        t0 = time.time()
        while time.time() - t0 < timeout:
            await asyncio.sleep(2)
            if await self.kev_ready():
                return True
            if not self.kevp.alive():
                if self._kev_offline and not self._kev_seen:
                    self.start_kev()                    # 不联网没起来：联网再起一次（缺的文件补上）
                    continue
                raise RuntimeError("Kev 启动失败：\n" + self.kevp.tail())
        return False

    async def kev(self, state, questions):
        """Kev 没准备好就返回 None，并在后台启动它（下次就能用）。"""
        if self.s["kevMode"] == "off" or self.yielding:
            return None
        if not await self.kev_ready():
            try:
                await self.ensure_kev(wait=False)
            except Exception:
                pass
            return None
        self.last_kev = time.time()
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(self.kurl("/v1/systemone"), json={"state": state, "model": "kev-latest", "questions": questions})
            if r.status_code != 200:
                return None
            return r.json().get("answers")
        except Exception:
            return None

    # ---------- 让路：按显存 ----------
    @property
    def yielding(self):
        """让路中（底座、Kev 不装）：本地的活交 DeepSeek，隐私的排队。"""
        return self.yield_level >= 1

    def need(self):
        """各部分大概要多少显存（GB），算"放不放得下"用。"""
        q = self.s["baseQuant"]
        return {"embed": 1.3, "base": {"4bit": 2.2, "8bit": 3.2}.get(q, 5.5), "kev": 0.0 if self.s["kevMode"] == "off" else 2.0}

    def own_pids(self):
        pids = set()
        for pr in (self.server, self.kevp, *self.extra):
            if pr.alive():
                pids.add(pr.p.pid)
                try:                                   # Windows 上虚拟环境的 python.exe 会再起一个真正干活的子进程
                    pids.update(c.pid for c in psutil.Process(pr.p.pid).children(recursive=True))
                except Exception:
                    pass
        return pids

    def own_vram(self):
        """我们自己（模型服务 + Kev）现在占了多少显存（GB）。
        Windows 上按每个程序的专用显存算（和任务管理器"详细信息"一样准）；读不到时估：模型服务报的 + 0.5 GB 运行环境，Kev 开着按 2 GB。"""
        from . import hw
        v = hw.vram_of(self.own_pids())
        if v is not None:
            return v
        est, h = 0.0, self._health
        if h:
            vr = h.get("vram") or {}
            est += (vr.get("reserved_gb") or vr.get("alloc_gb") or 0) + 0.5
        if self.kevp.alive() or self._kev_ok:
            est += 2.0
        est += sum(getattr(pr, "vram_est", 0) for pr in self.extra if pr.alive())
        return est

    def tick(self, hw):
        """每次采样硬件后调用（约 2 秒一次）：Kev 闲置关闭；按显存让路。
        让路分两级：1 = 底座、Kev 不装（已装的卸掉）；2 = 嵌入模型也卸掉，显存全让出来。
        - 要让得更多：连续 3 次（约 6 秒）都这么判才动手；正在用本地模型回答你时，答完再让。
        - 要退回来：连续 yieldCool 分钟（默认 3）都放得下（多留 0.5 GB 余量，免得来回切）才退；从 2 级退回时把嵌入模型装回去。
          底座还是用到才装，不提前装。"""
        s = self.s
        if s["kevMode"] == "ondemand" and self.kevp.alive() and self.last_kev and time.time() - self.last_kev > float(s["idleUnload"]) * 60:
            self.kevp.stop()
        g = (hw or {}).get("gpu") or {}
        used, total = g.get("vram"), g.get("vramTotal")
        if not s["yieldAuto"] or used is None or not total:
            if self.yield_level:
                self._set_level(0, "")
            self._up, self._down_since = 0, 0.0
            return
        f = (hw or {}).get("fps") or {}
        game = (f.get("proc") or "游戏") if f.get("fps") and f.get("fg", True) else ""
        ours, need, reserve = self.own_vram(), self.need(), float(s.get("yieldVram", 2))
        want, others = yield_want(total, used, ours, reserve, need, bool(game))
        self.vram_info = {"total": round(total, 1), "used": round(used, 1), "ours": round(ours, 1), "others": round(others, 1),
                          "reserve": reserve, "want": want}
        why = (lambda w: "" if not w else
               f"别的程序占了 {others:.1f} GB 显存，显存全让出来" if w >= 2 else
               f"在玩游戏（{game.replace('.exe', '')}），不装底座和 Kev" if game else
               f"别的程序占了 {others:.1f} GB 显存，不装底座和 Kev")
        if want > self.yield_level:
            self._down_since = 0.0
            if time.time() < self.busy_until:     # 正在用本地模型回答你：答完再让
                return
            self._up += 1
            if self._up >= 3:
                self._up = 0
                self._set_level(want, why(want))
            return
        self._up = 0
        if want < self.yield_level:
            w2, _ = yield_want(total, used, ours, reserve + 0.5, need, bool(game))
            if w2 >= self.yield_level:
                self._down_since = 0.0
            else:
                self._down_since = self._down_since or time.time()
                if time.time() - self._down_since >= float(s.get("yieldCool", 3)) * 60:
                    self._down_since = 0.0
                    self._set_level(w2, why(w2))
                    return
        else:
            self._down_since = 0.0
        if self.yield_level:
            self.yield_reason = why(self.yield_level)

    def _set_level(self, new, reason):
        old = self.yield_level
        self.yield_level, self.yield_reason = new, (reason if new else "")
        loop = asyncio.get_event_loop()
        if new >= 1 and old < 1:
            loop.create_task(self.unload("base"))
            if self.kevp.alive():
                self.kevp.stop()
        if new >= 2 and old < 2:
            loop.create_task(self.unload("embed"))
        if old >= 2 and new < 2:
            loop.create_task(self.load("embed"))
        try:
            from . import feed
            if new > old:
                feed.add(f"显存让路：{reason}" + ("。本地的活先交 DeepSeek，隐私的排队" if old == 0 else ""), "warn", job="显存让路")
            elif new == 0:
                feed.add("显存空出来了，让路结束" + ("，嵌入模型装回去了" if old >= 2 else ""), "ok", job="显存让路")
            else:
                feed.add(f"显存空出来一些，嵌入模型装回去了（{reason}）", "info", job="显存让路")
        except Exception:
            pass

    async def load(self, what):
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                await c.post(self.url("/load"), json={"what": what})
        except Exception:
            pass

    async def status(self):
        h = await self.health(max_age=12)
        return {"ai_env": self.ai_ready(), "server": bool(h), "server_proc": self.server.alive(), "health": h,
                "kev_installed": self.kev_installed(), "kev_proc": self.kevp.alive(), "kev_ready": await self.kev_ready(max_age=12),
                "kev_mode": self.s["kevMode"], "yielding": self.yielding, "yield_level": self.yield_level,
                "yield_reason": self.yield_reason, "vram": self.vram_info}

    def cleanup_orphans(self):
        """后端启动时：上一次留下的模型服务、Kev、游戏内小框（后端被直接结束、崩溃时它们会活下来）按 PID 停掉，
        免得新起的模型服务报「端口已被占用」。硬件监控助手是管理员权限跑的、可以接着用，不动它。"""
        n = []
        for p in psutil.process_iter(["pid", "cmdline", "exe", "cwd"]):
            try:
                if p.pid == os.getpid():
                    continue
                kind = orphan_kind(" ".join(p.info["cmdline"] or []), p.info["exe"], p.info["cwd"], paths.ROOT)
                if not kind:
                    continue
                for c in p.children(recursive=True):
                    c.kill()
                p.kill()
                n.append(kind)
            except Exception:
                continue
        if n:
            print("停掉了上次留下的子进程：" + "、".join(n))
        return n

    def stop_all(self):
        self.server.stop()
        self.kevp.stop()
        for pr in self.extra:
            pr.stop()


M = Manager()
