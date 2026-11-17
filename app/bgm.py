r"""配乐（v3.4）：本地 Stable Audio 3 Medium 出纯音乐。

模型：`stabilityai/stable-audio-3-medium`（1.4B DiT + SAME-L 44.1kHz 立体声自编码器 + T5Gemma 文本编码器；
8 步对抗蒸馏，单次 10~380 秒）。许可证是 Stability AI Community License + Gemma Terms：
非商用免费；年收入 100 万美元以下可商用；超过要 Enterprise。用在要挣钱的视频里之前先看清。

怎么装：设置 › 整备 ›「配音、语音、配乐」一键装好（scripts\install_bgm.py）：
  - bgm-env（diffusers + soundfile + lameenc；torch/transformers 通过 .pth 复用 ai-env）；
  - 魔搭优先、hf-mirror 兜底，下到 models\bgm\stable-audio-3-medium-src；
  - 转成 diffusers 格式，放 models\bgm\stable-audio-3-medium。
设置 › 配乐 里什么都不用填；也能填自己的模型文件夹（bgmDir）或已经开着的接口地址（bgmUrl）。

用到才启动 `app/bgm_server.py`（独立进程，日志 data\logs\bgm.log）；闲置 bgmIdle 分钟关、打游戏让路时关，
和配音服务一个规矩。它内部用 PyTorch 原生 SDPA，不装 flash-attn，避免 Windows 上回退不当产生电流杂音。

服务接口沿用原来的异步任务契约（release_task / query_result / v1/audio），前端和批量队列不用大改：
  POST /release_task {prompt, duration, format, num_inference_steps, seed} → task_id
  POST /query_result {task_id_list} → 0=跑着 / 1=好了 / 2=失败
  GET  /v1/audio?path=… 下载音频
"""
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

from . import db, feed, mediainfo, paths, privacy, settings, telemetry
from .models import M, Proc

OUT = paths.ROOT / "配乐输出"
MODEL = Path(os.environ.get("AGENT_BGM_MODEL") or paths.BGM_MODEL)     # 转换好的 diffusers 格式（整备一键装好）
SRC = Path(os.environ.get("AGENT_BGM_SRC") or paths.BGM_SRC)           # 原始 checkpoint + T5Gemma（转换用）
SERVER = paths.APP / "bgm_server.py"
NEED_GB = 7.0
MIN_S, MAX_S = 10, 380
JOBN = "配乐"
CN = re.compile(r"[一-鿿]")


def model_ok(d=None):
    """转换好的模型全不全：核心 safetensors、配置齐备；`.cache` 里的半截文件不算。"""
    d = Path(d or MODEL)
    return ((d / "model_index.json").exists()
            and all((d / n).is_dir() and any((d / n).glob("*.safetensors")) for n in ("transformer", "vae", "text_encoder"))
            and (d / "scheduler" / "scheduler_config.json").exists()
            and not any(p for p in d.rglob("*.incomplete") if ".cache" not in p.parts))


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
        return (self.s.get("bgmUrl") or "http://127.0.0.1:8094").rstrip("/") + p

    def folder(self):
        v = str(self.s.get("bgmDir") or "").strip().strip('"')
        if v:
            return Path(v)
        return MODEL if model_ok(MODEL) else None

    def builtin(self):
        """用的是整备里一键装好的那一份（没在设置里填别的文件夹）。"""
        return not str(self.s.get("bgmDir") or "").strip() and self.folder() == MODEL

    def installed(self):
        """整备一键装好的那一份：环境在、模型转换好了、服务脚本在。"""
        return paths.bgm_python().exists() and model_ok() and SERVER.exists()

    def python(self):
        return paths.bgm_python() if paths.bgm_python().exists() else None

    def configured(self):
        """配没配：填了模型文件夹（里面有转换好的模型），或者整备装好了，或者接口本来就开着（最近连上过）。"""
        d = self.folder()
        if d and model_ok(d) and self.python():
            return True
        return bool(not d and time.time() - float(db.kv_get("bgm_seen") or 0) < 30 * 86400)

    def cmd(self):
        d, py = self.folder(), self.python()
        m = re.match(r"https?://([^:/]+)(?::(\d+))?", self.url())
        host, port = (m.group(1), m.group(2) or "8094") if m else ("127.0.0.1", "8094")
        if py and d and model_ok(d):
            return [py, SERVER, "--model", d, "--host", host, "--port", port, "--log"]
        return None

    def out_dir(self):
        return paths.resolve(self.s.get("bgmOut", ""), OUT)

    def busy(self):
        return bool(self.job and self.job["st"] == "run")

    async def health(self):
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(self.url("/health"))
            ok = r.status_code == 200
        except Exception:
            ok = False
        if ok:
            db.kv_set("bgm_seen", time.time())
        return ok

    async def ensure(self, say=None, timeout=900):
        t0 = time.time()
        if await self.health():
            self.proc.mark_ready((time.time() - t0) * 1000, "配乐服务")
            return
        cmd = self.cmd()
        if not cmd:
            raise BgmError("配乐还没装：到 设置 › 整备 点「配音、语音、配乐」那张卡片的一键装好（或者只装 Stable Audio 3 那一项）")
        if M.yielding:
            raise BgmError(f"现在在让路（{M.yield_reason or '显存不够'}），配乐先不开")
        if not self.proc.alive():
            env = M.env()
            env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
                       PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")
            self.proc.start(cmd, paths.ROOT, env, "配乐出曲")
            self.last = time.time()
            feed.add("配乐服务（Stable Audio 3）启动中：第一次要加载模型，会久一点（日志 data\\logs\\bgm.log）", "info", job=JOBN)
        while time.time() - t0 < timeout:
            await asyncio.sleep(1.5)
            if await self.health():
                self.proc.mark_ready((time.time() - t0) * 1000, "配乐服务")
                return
            if not self.proc.alive():
                raise BgmError("配乐服务没起来（看 data\\logs\\bgm.log）：\n" + self.proc.tail(6))
            if say:
                say(f"正在启动配乐服务（{int(time.time() - t0)} 秒，第一次要加载模型）……")
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

    async def _english(self, prompt):
        """纯中文描述 + 配了 DeepSeek Key：轻量转成英文风格/乐器/BPM 标签。
        没 Key、离线、是隐私内容或翻译失败：原样送 T5Gemma。"""
        if not prompt or not CN.search(prompt):
            return prompt
        if not settings.get_secret("dsKey"):
            return prompt
        try:
            private, _ = privacy.check(prompt)
            if private:
                return prompt
            from . import deepseek
            r = await deepseek.chat(
                [{"role": "system", "content": "把这段中文音乐描述改写成一句英文的音乐生成提示词：只写风格、情绪、乐器、速度/BPM、画面感；"
                                                "不要解释、不要引号、不要中文，最多 60 个英文单词。"},
                 {"role": "user", "content": prompt}],
                thinking=False, max_tokens=120, temperature=0.2, purpose="bgm_prompt", timeout=20)
            t = (r.get("text") or "").strip().strip('"').strip()
            if t and len(t) <= 1000 and not CN.search(t):
                return t
        except Exception as e:
            feed.add(f"配乐描述没转成英文，按原文送模型：{str(e)[:80]}", "info", job=JOBN)
        return prompt

    async def generate(self, prompt, seconds=60, say=None, stopped=None, dest=None):
        """出一首纯音乐。返回 {id, path, name, duration, sec, prompt}。一次只出一首（排队）。
        dest：存成哪个文件（批量用：配乐输出\\日期_清单名\\名字.wav，同名的旧文件挪进「旧版」）；不给就存 配乐输出\\日期\\时分秒_描述.wav。"""
        prompt = str(prompt or "").strip()
        if not prompt:
            raise BgmError("写一句描述：风格、情绪、乐器、快慢")
        if len(prompt) > 1000:
            raise BgmError("描述太长了（最多 1000 字）")
        try:
            seconds = max(MIN_S, min(MAX_S, int(float(seconds or 60))))
        except (TypeError, ValueError):
            seconds = 60
        say = say or (lambda _m: None)
        async with self._lock:
            job = self.job = {"id": int(time.time() * 1000), "st": "run", "prompt": prompt, "seconds": seconds,
                              "t0": time.time(), "t1": 0.0, "msg": "准备中", "stop": "", "err": "", "file": ""}
            try:
                r = await self._gen(job, say, stopped, dest)
                job.update(st="done", t1=time.time(), msg=f"好了：{r['name']}", file=r["name"])
                feed.add(f"配乐好了：{paths.show(Path(r['path']))}（{mediainfo.clock(r['duration'] or seconds)}，用了 {r['sec']:.0f} 秒）", "ok", job=JOBN)
                feed.done(f"配乐 · {prompt[:20]} · {mediainfo.clock(r['duration'] or seconds)}", "本地 Stable Audio 3", r["sec"], "", "bgm")
                telemetry.log("bgm", "done", "配乐", "ok", r["sec"] * 1000,
                              {"seconds": seconds, "duration": r.get("duration"), "format": self.s.get("bgmFormat") or "wav",
                               "model": "stable-audio-3-medium", "prompt_len": len(prompt)},
                              f"配乐完成 · {mediainfo.clock(r['duration'] or seconds)} · 用了 {r['sec']:.0f} 秒")
                return r
            except BgmError as e:
                job.update(st="err", t1=time.time(), err=str(e), msg=str(e))
                feed.add(f"配乐没成：{e}", "warn", job=JOBN)
                raise
            finally:
                self.last = time.time()

    async def _gen(self, job, say, stopped, dest=None):
        await self.ensure(lambda m: (job.update(msg=m), say(m)))
        fmt = "wav" if (self.s.get("bgmFormat") or "wav") not in ("mp3", "flac") else self.s["bgmFormat"]
        steps = max(1, min(32, int(self.s.get("bgmSteps") or 8)))
        prompt_en = await self._english(job["prompt"])
        job["prompt_en"] = prompt_en
        body = {"prompt": prompt_en, "duration": job["seconds"], "format": fmt, "num_inference_steps": steps,
                "seed": int(time.time() * 1000) & 0x7FFFFFFF}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=120, write=30, pool=None)) as c:
                r = await c.post(self.url("/release_task"), json=body)
                if r.status_code != 200:
                    raise BgmError(f"Stable Audio 3 没接下任务（{r.status_code}）：{r.text[:160]}")
                tid = (self._data(r.json()) or {}).get("task_id")
                if not tid:
                    raise BgmError("Stable Audio 3 没给任务编号")
                t0 = time.time()
                while True:
                    await asyncio.sleep(2)
                    if job["stop"] or (stopped and stopped()):
                        raise BgmError("停下了" + (f"（{job['stop']}）" if job["stop"] else "") + "：Stable Audio 3 那边这一首会自己出完，不保存")
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
                        why = str(row.get("error") or "")[:200]
                        raise BgmError("Stable Audio 3 说这一首没出成" + (f"：{why}" if why else "（看 data\\logs\\bgm.log）"))
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
                        raise BgmError("Stable Audio 3 出完了但没给音频")
                    a = await c.get(f if f.startswith("http") else self.url(f if f.startswith("/") else "/" + f))
                    if a.status_code != 200 or len(a.content) < 1000:
                        raise BgmError(f"音频没拿到（{a.status_code}）")
                    break
        except httpx.HTTPError as e:
            raise BgmError(f"和 Stable Audio 3 的连接断了：{type(e).__name__}") from None
        if dest:
            from .media_batch import keep_old
            p = Path(dest).with_suffix("." + fmt)
            p.parent.mkdir(parents=True, exist_ok=True)
            keep_old(p)
            keep_old(p.with_suffix(".json"))
        else:
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
        meta = {"prompt": job["prompt"], "prompt_en": prompt_en, "seconds": job["seconds"], "duration": dur,
                "took": round(sec, 1), "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "model": "stable-audio-3-medium", "steps": steps, "seed": body["seed"], "format": fmt}
        p.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        hist = db.kv_get("bgm_hist", []) or []
        hid = int(time.time() * 1000)
        hist.append({"id": hid, "ts": time.time(), "path": str(p), "name": p.name, "prompt": job["prompt"],
                     "seconds": job["seconds"], "duration": dur, "took": round(sec, 1)})
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
        return {k: j.get(k) for k in ("id", "st", "prompt", "prompt_en", "seconds", "msg", "err", "file")} | {"elapsed": round((j["t1"] or time.time()) - j["t0"])}

    async def status(self):
        d, up = self.folder(), await self.health()
        return {"up": up, "alive": self.proc.alive(), "configured": self.configured(), "url": self.url(), "dir": str(d) if d else "",
                "dir_ok": bool(d and d.is_dir()), "python": paths.show(self.python()) if self.python() else "", "can_start": bool(self.cmd()),
                "builtin": self.builtin(), "installed": self.installed(), "model": "Stable Audio 3 Medium", "max_seconds": MAX_S,
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
    from .media_batch import MB
    if B.busy() or MB.busy():
        raise HTTPException(409, "正在批量配乐，等这批出完（或者先在「批量」里点「停下」）" if MB.busy() else "上一首还在出，等它好了")
    prompt, seconds = str(body.get("prompt") or "").strip(), body.get("seconds") or 60
    if not prompt:
        raise HTTPException(400, "写一句描述：风格、情绪、乐器、快慢")
    if not B.cmd() and not await B.health():
        raise HTTPException(400, "配乐还没装：到 设置 › 整备 点「配音、语音、配乐」那张卡片的一键装好（或者只装 Stable Audio 3 那一项）")

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
