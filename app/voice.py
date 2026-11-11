r"""语音对话（v3.0）：对着 Agent 说话，它用声音回你。

- 说话的声音：Breeze TTS 2（BreezeBlue，3B，能按一段文字描述造音色，也能照一段参考音频来）。
  许可证：代码 Apache 2.0，权重「研究和非商业用途」——只给他自己聊天用；**它念的不进要挣钱的视频**（视频配音照旧走配音页的百炼 / Qwen3-TTS）。
  模型和代码不进仓库、不进压缩包，他自己下（设置 › 语音 里有地址）。官方只写了 Linux，Windows 要用社区版或自己装——所以这里不装它，只连它的接口：
    python -m breeze_infer.api <模型文件夹> --host 127.0.0.1 --port 8093
    POST /v1/audio/speech（表单：text、instruction、cfg_scale、seed，或者 ref_audio + ref_text）→ 一边生成一边回 24 kHz 单声道 16 位 PCM
  填了 breeze-tts 的文件夹（voiceDir）：用到才由 Agent 启动（不弹黑窗口，日志 data\logs\voice.log），闲置 voiceIdle 分钟关掉，打游戏让路时关掉。
  官方说一次推理约 7.7 GB 显存：启动前先把底座卸了。不填文件夹：只连 voiceUrl（他自己开着的）。
- 听写：Qwen3-ASR-0.6B（Apache 2.0），跑在配音服务里（tts-env 里本来就装着 qwen-asr 这个包，只差模型：设置 › 语音 点「下载听写模型」）。
- 界面录的音只发给本机这两个服务；说的话变成字以后，和打字发的走同一条路（隐私的照旧只在本地）。
- 念什么：回复去掉 Markdown、代码、链接，最多念 voiceMax 个字（后面的看屏幕）。
"""
import asyncio
import base64
import re
import shutil
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse

from . import db, feed, paths, settings, tts
from .models import M, Proc

NEED_GB = 8.0
SR = 24000
VD = paths.DATA / "voice"
REF = VD / "ref.wav"
ASR_MODEL = "Qwen3-ASR-0.6B"
JOBN = "语音"
PY_DIRS = (".venv/Scripts", "venv/Scripts", "python_embeded", "python", ".venv/bin", "venv/bin")
HF_ID = "BreezeBlue/breeze-tts-2"


class VoiceError(RuntimeError):
    pass


def speakable(text, cap=None) -> str:
    """回复 → 适合念出来的字：去掉代码块、链接、Markdown 记号、表格线；太长只念前面。"""
    t = re.sub(r"```.*?```", "（这里有一段代码，看屏幕）", text or "", flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"(?m)^\s*(来源|参考)[:：].*$", "", t)
    t = re.sub(r"(?m)^\s*\|?[-:| ]{3,}\|?\s*$", "", t)
    t = re.sub(r"(?m)^\s*(#{1,6}|[-*+]|\d+[.、)])\s+", "", t)
    t = re.sub(r"[*_#>|~]+", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t).strip()
    cap = int(cap or settings.S.get("voiceMax") or 400)
    if len(t) > cap:
        cut = max(t.rfind(x, 0, cap) for x in "。！？!?\n")
        t = t[:cut + 1 if cut > cap * 0.5 else cap].rstrip() + " 后面的在屏幕上。"
    return t


class Voice:
    def __init__(self):
        self.proc = Proc("voice")
        self.proc.vram_est = NEED_GB
        M.extra.append(self.proc)
        self.last = 0.0
        self.speaking = False
        self._lock = asyncio.Lock()

    @property
    def s(self):
        return settings.S

    def url(self, p=""):
        return (self.s.get("voiceUrl") or "http://127.0.0.1:8093").rstrip("/") + p

    def folder(self):
        v = str(self.s.get("voiceDir") or "").strip().strip('"')
        return Path(v) if v else None

    def python(self):
        v = str(self.s.get("voicePython") or "").strip().strip('"')
        if v:
            return Path(v) if Path(v).exists() else None
        d = self.folder()
        if not d:
            return None
        for sub in PY_DIRS:
            for exe in ("python.exe", "python"):
                if (d / sub / exe).exists():
                    return d / sub / exe
        return None

    def model(self):
        v = str(self.s.get("voiceModel") or "").strip().strip('"')
        if v:
            return v
        d = self.folder()
        for c in ((d / "breeze-tts-2") if d else None, (d.parent / "breeze-tts-2") if d else None):
            if c and c.is_dir():
                return str(c)
        return HF_ID

    def cmd(self):
        d, py = self.folder(), self.python()
        if not (d and d.is_dir() and py):
            return None
        m = re.match(r"https?://([^:/]+)(?::(\d+))?", self.url())
        return [py, "-m", "breeze_infer.api", self.model(), "--host", m.group(1) if m else "127.0.0.1", "--port", (m.group(2) if m else None) or "8093"]

    async def health(self):
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                r = await c.get(self.url("/v1/model"))
            ok = r.status_code == 200
        except Exception:
            ok = False
        if ok:
            db.kv_set("voice_seen", time.time())
        return ok

    def configured(self):
        return bool(self.cmd()) or (not self.folder() and time.time() - float(db.kv_get("voice_seen") or 0) < 30 * 86400)

    async def ensure(self, timeout=600):
        if await self.health():
            return
        cmd = self.cmd()
        if not cmd:
            raise VoiceError("说话的声音还没配好：到 设置 › 语音 填 Breeze TTS 2 的文件夹（或者先自己把它的接口开着）")
        if M.yielding:
            raise VoiceError(f"现在在让路（{M.yield_reason or '显存不够'}），先不开口")
        if not self.proc.alive():
            v = M.vram_info or {}
            if v.get("total") and v.get("used") is not None and v["total"] - v["used"] < NEED_GB:
                await M.unload("base")                      # 显存不够 7.7 GB：先把底座卸了（用到时它自己装回来）
                if tts.T.proc.alive() and not tts.T.busy():
                    tts.T.stop("给语音让显存")
            env = M.env()
            env.update(PYTHONUTF8="1")
            self.proc.start(cmd, self.folder(), env)
            self.last = time.time()
            feed.add("语音（Breeze TTS 2）启动中：装模型要几十秒（日志 data\\logs\\voice.log）", "info", job=JOBN)
        t0 = time.time()
        while time.time() - t0 < timeout:
            await asyncio.sleep(1.5)
            if await self.health():
                return
            if not self.proc.alive():
                raise VoiceError("语音服务没起来（看 data\\logs\\voice.log）：\n" + self.proc.tail(6))
        raise VoiceError("语音服务启动超时（看 data\\logs\\voice.log）")

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
            feed.add(f"语音服务关了：{why}，显存还回去了" if why else "语音服务关了", "info", job=JOBN)

    def tick(self):
        if not self.proc.alive():
            return
        if M.yielding:
            self.stop(M.yield_reason or "显存让路")
            return
        idle = float(self.s.get("voiceIdle") or 10) * 60
        if not self.speaking and time.time() - (self.last or self.proc.started) > idle:
            self.stop(f"闲置 {int(idle // 60)} 分钟")

    def form(self, text):
        """发给 Breeze 的表单：有参考音频就照它的声音（克隆），没有就按音色描述造（设计）。"""
        data = {"text": text, "seed": str(int(self.s.get("voiceSeed") or 0))}
        fs = None
        desc = str(self.s.get("voiceDesc") or "").strip()
        if REF.exists() and str(self.s.get("voiceRefText") or "").strip():
            data["ref_text"] = str(self.s["voiceRefText"]).strip()
            fs = {"ref_audio": ("ref.wav", REF.read_bytes(), "audio/wav")}
        else:
            data["instruction"] = desc or settings.DEFAULTS["voiceDesc"]
            data["cfg_scale"] = str(float(self.s.get("voiceCfg") or 4))
        return data, fs

    async def speak(self, text):
        """一边生成一边给：24 kHz 单声道 16 位 PCM 的一块一块。"""
        text = speakable(text)
        if not text:
            raise VoiceError("没有要念的字")
        await self.ensure()
        data, fs = self.form(text)
        async with self._lock:
            self.speaking = True
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=120, write=30, pool=None)) as c:
                    for attempt in range(40):
                        async with c.stream("POST", self.url("/v1/audio/speech"), data=data, files=fs) as r:
                            if r.status_code == 409 and attempt < 39:          # 它一次只念一段：上一段还没完，等一下
                                await asyncio.sleep(0.5)
                                continue
                            if r.status_code != 200:
                                raise VoiceError(f"Breeze 没念（{r.status_code}）：{(await r.aread())[:160].decode('utf-8', 'replace')}")
                            odd = b""
                            async for chunk in r.aiter_bytes(4800):
                                chunk = odd + chunk
                                odd = chunk[len(chunk) - len(chunk) % 2:]
                                if len(chunk) > 1:
                                    yield chunk[:len(chunk) - len(chunk) % 2]
                            return
            except httpx.HTTPError as e:
                raise VoiceError(f"和语音服务的连接断了：{type(e).__name__}") from None
            finally:
                self.speaking = False
                self.last = time.time()

    # ---------- 听写 ----------
    def asr_dir(self):
        return paths.MODELS_TTS / ASR_MODEL

    def asr_ok(self):
        d = self.asr_dir()
        return (d / "config.json").exists() and any(d.glob("*.safetensors"))

    def asr_why(self):
        if not tts.T.env_ok():
            return "没装配音环境（听写跑在配音服务里）：设置 › 本地模型 点「安装配音」"
        if not self.asr_ok():
            return "听写模型还没下：设置 › 语音 点「下载听写模型」（约 1.9 GB）"
        if M.yielding:
            return f"在让路（{M.yield_reason or '显存不够'}），不用显卡"
        return ""

    async def transcribe(self, wav: bytes):
        why = self.asr_why()
        if why:
            raise VoiceError(why)
        try:
            sr, pcm = tts.read_wav(wav)
        except Exception:
            raise VoiceError("录音格式不对（要 16 位单声道 WAV）") from None
        if len(pcm) < sr * 2 * 0.3:
            raise VoiceError("太短了，没听清")
        if len(pcm) > sr * 2 * 120:
            raise VoiceError("一次最多说两分钟")
        try:
            await tts.T.ensure()
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(tts.T.url("/asr"), json={"pcm": base64.b64encode(bytes(pcm)).decode(), "sr": sr, "language": "Chinese"})
        except RuntimeError as e:
            raise VoiceError(str(e)[:200]) from None
        except httpx.HTTPError as e:
            raise VoiceError(f"配音服务断了：{type(e).__name__}") from None
        tts.T.last = time.time()
        if r.status_code != 200:
            try:
                d = r.json().get("detail")
            except Exception:
                d = r.text
            raise VoiceError(str(d)[:200])
        j = r.json()
        return {"text": (j.get("text") or "").strip(), "sec": j.get("sec"), "audio_s": round(len(pcm) / 2 / sr, 1)}

    async def status(self):
        d = self.folder()
        return {"on": bool(self.s.get("voiceOn")), "up": await self.health(), "alive": self.proc.alive(), "configured": self.configured(), "url": self.url(),
                "dir": str(d) if d else "", "dir_ok": bool(d and d.is_dir()), "python": paths.show(self.python()) if self.python() else "",
                "model": self.model(), "can_start": bool(self.cmd()), "ref": REF.exists(), "ref_text": self.s.get("voiceRefText") or "",
                "desc": self.s.get("voiceDesc") or "", "asr": self.asr_ok(), "asr_why": self.asr_why(), "tts_env": tts.T.env_ok(),
                "yielding": M.yielding, "yield_reason": M.yield_reason, "auto": bool(self.s.get("voiceAuto", True)), "hands": bool(self.s.get("voiceHands", False)),
                "max": int(self.s.get("voiceMax") or 400), "sr": SR}


V = Voice()
api = APIRouter()


@api.get("/api/voice")
async def voice_status():
    return await V.status()


@api.post("/api/voice/speak")
async def voice_speak(body: dict = Body(...)):
    """把一段话念出来：回的是原始 PCM（24 kHz、单声道、16 位），界面一边收一边放。"""
    text = speakable(body.get("text") or "")
    if not text:
        raise HTTPException(400, "没有要念的字")
    gen = V.speak(text)
    try:
        first = await gen.__anext__()                      # 先拿到第一块：起不来、没配好的在这里就报出来，而不是放到一半断掉
    except StopAsyncIteration:
        raise HTTPException(502, "语音服务什么都没念出来") from None
    except VoiceError as e:
        raise HTTPException(503, str(e)) from None

    async def body_():
        yield first
        try:
            async for chunk in gen:
                yield chunk
        except VoiceError:
            return
    return StreamingResponse(body_(), media_type="audio/L16;rate=24000;channels=1", headers={"X-Sr": str(SR), "Cache-Control": "no-store"})


@api.post("/api/voice/asr")
async def voice_asr(request: Request):
    """界面录的一段话（WAV，16 位单声道）→ 文字。"""
    b = await request.body()
    if len(b) > 30 << 20:
        raise HTTPException(413, "录音太大了")
    try:
        return await V.transcribe(b)
    except VoiceError as e:
        raise HTTPException(503, str(e)) from None


@api.post("/api/voice/ref")
async def voice_ref(request: Request):
    """换说话的声音：传一段参考音频（WAV，3~30 秒，你有权用的声音），配上它念的字（设置里的 voiceRefText）。"""
    b = await request.body()
    try:
        sr, pcm = tts.read_wav(b)
    except Exception:
        raise HTTPException(400, "要 16 位的 WAV 文件") from None
    sec = len(pcm) / 2 / sr
    if not 2 <= sec <= 40:
        raise HTTPException(400, f"参考音频要 3~30 秒（这段 {sec:.0f} 秒）")
    VD.mkdir(parents=True, exist_ok=True)
    REF.write_bytes(b)
    return await V.status()


@api.delete("/api/voice/ref")
async def voice_ref_del():
    if REF.exists():
        REF.replace(REF.with_name(f"ref_{int(time.time())}.old.wav"))      # 不删，改名留着
    return await V.status()


@api.post("/api/voice/off")
def voice_off():
    V.stop("你关的")
    return {"ok": True}


@api.post("/api/voice/open")
def voice_open():
    import os
    VD.mkdir(parents=True, exist_ok=True)
    if paths.IS_WIN:
        os.startfile(str(VD))
        return {"msg": "打开了：" + paths.show(VD)}
    return {"msg": "文件夹在：" + paths.show(VD)}


_ = shutil
