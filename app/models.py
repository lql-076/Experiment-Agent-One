"""模型管家：在主后端里管两个子进程——本地模型服务（嵌入 + 底座 + 小脑）和 Kev。

- 只启动、只关闭自己开的进程（按进程号），绝不按名字杀进程。
- 嵌入模型常驻；底座由模型服务自己闲置卸载；Kev 按需启动，闲置后关掉。
- 让路模式：显卡被别的程序（游戏、画图）占满时，不再加载底座，非隐私的活交给 DeepSeek。
"""
import asyncio
import os
import subprocess
import time

import httpx

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


class Manager:
    def __init__(self):
        self.server = Proc("model_server")
        self.kevp = Proc("kev")
        self.last_kev = 0.0
        self.busy_until = 0.0
        self.yielding = False
        self.yield_reason = ""
        self._hot = 0
        self._cold_since = 0.0
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
        """拿不到就返回 None（服务没起来时不阻塞）。"""
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
        if self.s["kevMode"] == "off":
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

    # ---------- 定时照看 ----------
    def tick(self, hw):
        """每次采样硬件后调用：处理让路模式和 Kev 闲置关闭。"""
        s = self.s
        if s["kevMode"] == "ondemand" and self.kevp.alive() and self.last_kev and time.time() - self.last_kev > float(s["idleUnload"]) * 60:
            self.kevp.stop()
        load = (hw or {}).get("gpu", {}).get("load")
        if not s["yieldAuto"] or load is None:
            self.yielding = False
            return
        if time.time() < self.busy_until:     # 自己在用显卡，不算
            return
        if load >= float(s["yieldGpuLoad"]):
            self._hot += 1
            self._cold_since = 0
            if self._hot >= 3 and not self.yielding:
                self.yielding = True
                self.yield_reason = f"显卡占用 {load:.0f}%（游戏或画图）"
                asyncio.get_event_loop().create_task(self.unload("base"))
        else:
            self._hot = 0
            if self.yielding:
                self._cold_since = self._cold_since or time.time()
                if time.time() - self._cold_since > 60:
                    self.yielding = False
                    self.yield_reason = ""

    async def status(self):
        h = await self.health(max_age=12)
        return {"ai_env": self.ai_ready(), "server": bool(h), "server_proc": self.server.alive(), "health": h,
                "kev_installed": self.kev_installed(), "kev_proc": self.kevp.alive(), "kev_ready": await self.kev_ready(max_age=12),
                "kev_mode": self.s["kevMode"], "yielding": self.yielding, "yield_reason": self.yield_reason}

    def stop_all(self):
        self.server.stop()
        self.kevp.stop()


M = Manager()
