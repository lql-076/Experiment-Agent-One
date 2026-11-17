r"""语音对话（v3.0）：对着 Agent 说话，它用声音回你。

- 说话的声音：Breeze TTS 2（BreezeBlue，3B，能按一段文字描述造音色，也能照一段参考音频来）。
  许可证：代码 Apache 2.0，权重「研究和非商业用途」——只给他自己聊天用；**它念的不进要挣钱的视频**（视频配音照旧走配音页的百炼 / Qwen3-TTS）。
  模型和代码不进仓库、不进压缩包，他自己下（设置 › 语音 里有地址）。官方只写了 Linux，Windows 要用社区版或自己装——所以这里不装它，只连它的接口：
    python -m breeze_infer.api <模型文件夹> --host 127.0.0.1 --port 8093
    POST /v1/audio/speech（表单：text、instruction、cfg_scale、seed，或者 ref_audio + ref_text）→ 一边生成一边回 24 kHz 单声道 16 位 PCM
  填了 breeze-tts 的文件夹（voiceDir）：用到才由 Agent 启动（不弹黑窗口，日志 data\logs\voice.log）。
  v3.5.2 显存：默认常驻；扣除 Breeze 自己后占用超过 80% 立刻卸载，低于 50% 连续 voiceIdle 分钟自动加载；
  打游戏让路时也释放。官方说一次推理约 7.7 GB（我们的 CUDA Graph 模式约 10 GB）：启动前先把底座卸了。
  不填文件夹：只连 voiceUrl（他自己开着的）。
- 听写：Qwen3-ASR-0.6B（Apache 2.0），跑在配音服务里（tts-env 里本来就装着 qwen-asr 这个包，只差模型：设置 › 语音 点「下载听写模型」）。
- 界面录的音只发给本机这两个服务；说的话变成字以后，和打字发的走同一条路（隐私的照旧只在本地）。
- 念什么：回复去掉 Markdown、代码、链接，最多念 voiceMax 个字（后面的看屏幕）。
"""
import asyncio
import base64
import os
import re
import shutil
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse

from . import db, feed, paths, settings, tts
from .models import M, Proc

NEED_GB = 10.5                       # CUDA Graph 兼容模式（SDPA + backbone/depth 图）实测约 10 GB；eager 约 8 GB
SR = 24000
VD = paths.DATA / "voice"
REF = VD / "ref.wav"
ASR_MODEL = "Qwen3-ASR-0.6B"
JOBN = "语音"
PY_DIRS = (".venv/Scripts", "venv/Scripts", "python_embeded", "python", ".venv/bin", "venv/bin")
HF_ID = "BreezeBlue/Breeze-TTS-2"
CODE = paths.ROOT / "vendor" / "breeze-tts"            # 推理代码随包带着（v3.1；Apache-2.0，见那里的说明）
MODEL = paths.MODELS_TTS / "breeze-tts-2"               # 一键装好时把权重下到这里（scripts/install_tts.py --breeze）


_OK_CACHE = {"ts": 0.0, "model": False, "installed": False}


def model_ok(d=None):
    """权重下全了没有：config.json、.safetensors、它自带的声音编解码器（audio_tokenizer），根目录没有下到一半的文件。
    `.cache` 里 HF 下载留下的半截文件不算（和 install_tts.py 的 breeze_done() 同一规则，v3.3.2）。
    `rglob` 在这 6.6GB 的模型目录上要扫一会儿；状态接口/每次朗读前缓存 30 秒。"""
    if d is None and time.time() - _OK_CACHE["ts"] < 30:
        return _OK_CACHE["model"]
    d = Path(d or MODEL)
    ok = ((d / "config.json").exists() and any(d.glob("*.safetensors")) and (d / "audio_tokenizer" / "config.json").exists()
          and not any(p for p in d.rglob("*.incomplete") if ".cache" not in p.parts))
    if d is not None and Path(d) == MODEL:
        _OK_CACHE.update(model=ok, ts=time.time())
    return ok


def installed():
    """一键装好的那套能不能用：配音环境（tts-env）在、权重下全了、代码在。缓存 30 秒（同上）。"""
    if time.time() - _OK_CACHE["ts"] < 30:
        return _OK_CACHE["installed"]
    ok = bool(tts.T.env_ok() and model_ok() and (CODE / "breeze_infer" / "api.py").exists())
    _OK_CACHE.update(installed=ok, ts=time.time())
    return ok


class VoiceError(RuntimeError):
    pass


def vram_policy(used, total, breeze, alive, low_since, now=None, idle_s=600):
    """v3.5.2 显存策略的纯函数，方便回归。
    返回 (动作, 百分比)：keep / stop / wait / load / hold。
    - Breeze 活着：扣除自己后占用 >=80% → stop；否则 keep。
    - Breeze 没活：扣除自己（0）后 <50% → 计时，够 idle_s → load；50~80 → hold。
    """
    now = time.time() if now is None else float(now)
    pressure = max(0.0, float(used) - float(breeze))
    capacity = max(1.0, float(total) - float(breeze))
    pct = pressure / capacity * 100.0
    if alive:
        return ("stop" if pct >= 80.0 else "keep"), pct
    if pct >= 50.0:
        return "hold", pct
    if low_since is None:
        return "wait", pct
    return ("load" if now - float(low_since) >= float(idle_s) else "wait"), pct


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
        self.sr_out = SR
        self._fast_mode = None
        self._last_fast = None
        self._lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._warm_task = None
        self._low_since = None
        self._health_ok = False
        self._health_ts = 0.0

    @property
    def s(self):
        return settings.S

    def url(self, p=""):
        return (self.s.get("voiceUrl") or "http://127.0.0.1:8093").rstrip("/") + p

    def fast_mode(self):
        """v3.5.2：默认 graph（SDPA + CUDA Graph，不依赖 Triton），显存不够时退回 eager（只开 SDPA）。
        AGENT_BREEZE_MODE 可强制 compile/all/eager/off；设置里的 voiceFast 也可以写 auto/graph/compile/eager/off/all。"""
        env = os.environ.get("AGENT_BREEZE_MODE", "").strip().lower()
        if env in ("compile", "all", "graph", "eager", "off"):
            return env
        want = str(self.s.get("voiceFast") or "auto").strip().lower()
        if want in ("compile", "all", "graph", "eager", "off"):
            return want
        v = M.vram_info or {}
        try:
            total = float(v["total"])
            free = total - float(v["used"])
        except Exception:
            total = free = None
        if free is None:
            return "graph"
        # 刚停掉服务时显存可能还没释放完；按总显存和“底座可以卸”的余量判断，
        # 不要因为这一两秒的空窗就退回 eager（eager 一进一出会让第一句又慢回去）。
        base_can_free = 2.2 if M.server.alive() else 0.0
        if total is not None and total >= NEED_GB + 4.0 and free + base_can_free >= NEED_GB:
            return "graph"
        return "eager"

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
        custom = str(self.s.get("voiceCmd") or "").strip()
        if custom:                                              # 自己写的启动命令（比如用 WSL 跑：wsl -d Ubuntu -- bash -lc "cd ~/breeze-tts && python -m breeze_infer.api ../breeze-tts-2 --port 8093"）
            import shlex
            try:
                return shlex.split(custom, posix=not paths.IS_WIN)
            except ValueError:
                return None
        d, py = self.folder(), self.python()
        m = re.match(r"https?://([^:/]+)(?::(\d+))?", self.url())
        host, port = (m.group(1) if m else "127.0.0.1"), ((m.group(2) if m else None) or "8093")
        if d and d.is_dir() and py:                              # 自己装的一份（填了文件夹）
            return [py, "-m", "breeze_infer.api", self.model(), "--host", host, "--port", port]
        if not d and installed():                                # 整备里一键装好的：配音环境 + 随包的代码 + 下好的权重
            return [paths.tts_python(), paths.ROOT / "app" / "breeze_run.py", MODEL, "--host", host, "--port", port]
        return None

    def cwd(self):
        d = self.folder()
        return d if d and d.is_dir() else CODE if CODE.is_dir() else paths.ROOT

    async def health(self, fresh=False):
        # Breeze 只有一个推理 worker；生成时 /v1/model 可能排队。缓存 10 秒，
        # 避免每次朗读前的 ensure、每次状态查询都多等一个 2 秒超时。
        if not fresh and time.time() - self._health_ts < 10:
            return self._health_ok
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                r = await c.get(self.url("/v1/model"))
            ok = r.status_code == 200
        except Exception:
            ok = False
        self._health_ok, self._health_ts = ok, time.time()
        if ok:
            db.kv_set("voice_seen", time.time())
        return ok

    def configured(self):
        return bool(self.cmd()) or (not self.folder() and time.time() - float(db.kv_get("voice_seen") or 0) < 30 * 86400)

    async def warm(self):
        """v3.5.2：用户一开始说话/确定要朗读时，在后台把 Breeze 加载好；不常驻，闲置照旧关。"""
        if await self.health():
            return
        if self._warm_task and not self._warm_task.done():
            return

        async def _run():
            try:
                await self.ensure()
            except Exception:
                pass

        self._warm_task = asyncio.create_task(_run())

    async def ensure(self, timeout=600):
        t0 = time.time()
        # 自己拉起的服务进程还活着、上次已经健康过：朗读前不再多打一次 /v1/model；
        # Breeze 只有一个推理 worker，健康检查也会排队。
        if self.proc.alive() and self._health_ok:
            self.proc.mark_ready((time.time() - t0) * 1000, "语音服务")
            return
        if await self.health():
            self.proc.mark_ready((time.time() - t0) * 1000, "语音服务")
            return
        cmd = self.cmd()
        if not cmd:
            raise VoiceError("说话的声音还没装：到 设置 › 整备 点「配音、语音、配乐」那张卡片的一键装好（或者只装 Breeze TTS 2 那一项）")
        if M.yielding:
            raise VoiceError(f"现在在让路（{M.yield_reason or '显存不够'}），先不开口")
        async with self._start_lock:
            if await self.health():
                self.proc.mark_ready((time.time() - t0) * 1000, "语音服务")
                return
            if not self.proc.alive():
                mode = self.fast_mode()
                if str(self.s.get("voiceFast") or "auto").strip().lower() == "auto" and self._last_fast and mode == "eager":
                    mode = self._last_fast          # 刚停服务时的显存空窗，不要误退回 eager
                self._fast_mode = self._last_fast = mode
                need = NEED_GB if mode in ("graph", "compile", "all") else 8.0
                v = M.vram_info or {}
                if v.get("total") and v.get("used") is not None and v["total"] - v["used"] < need:
                    await M.unload("base")                  # 显存不够：先把底座卸了（用到时它自己装回来）
                    if tts.T.proc.alive() and not tts.T.busy():
                        tts.T.stop("给语音让显存")
                env = M.env()
                env.update(PYTHONUTF8="1", AGENT_BREEZE_MODE=mode)
                if mode == "all":
                    env["TORCHINDUCTOR_USE_STATIC_CUDA_LAUNCHER"] = "0"
                self.proc.start(cmd, self.cwd(), env, "语音朗读")
                self.last = time.time()
                feed.add(f"语音（Breeze TTS 2）启动中：{mode} 模式，模型+预热约二十秒（日志 data\\logs\\voice.log）", "info", job=JOBN)
            while time.time() - t0 < timeout:
                await asyncio.sleep(1.5)
                if await self.health(fresh=True):
                    self.proc.mark_ready((time.time() - t0) * 1000, "语音服务")
                    return
                if not self.proc.alive():
                    raise VoiceError("语音服务没起来（看 data\\logs\\voice.log）：\n" + self.proc.tail(6))
        raise VoiceError("语音服务启动超时（看 data\\logs\\voice.log）")

    def stop(self, why=""):
        self._fast_mode = None
        self._low_since = None
        self._health_ok, self._health_ts = False, 0.0
        if self._warm_task and not self._warm_task.done():
            self._warm_task.cancel()
        self._warm_task = None
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

    def _breeze_gb(self):
        """Breeze 自己现在占多少显存（GB）；读不到就按启动时估的 10.5。"""
        if not self.proc.alive():
            return 0.0
        try:
            from . import hw
            pids = {self.proc.p.pid}
            try:
                import psutil
                pids.update(c.pid for c in psutil.Process(self.proc.p.pid).children(recursive=True))
            except Exception:
                pass
            v = hw.vram_of(pids)
            if v is not None:
                return max(0.0, float(v))
        except Exception:
            pass
        return NEED_GB

    def tick(self):
        """v3.5.2 显存策略（不按闲置分钟）：
        - Breeze 常驻；**扣除 Breeze 自己后**，剩下的显存占用超过 80% 时立刻卸载；
        - 卸载后，剩下的占用低于 50% 连续 voiceIdle 分钟（默认 10）就自动加载回来；
        - 关掉语音、改用本地配音、打游戏让路时仍然释放。
        用「除 Breeze 以外的可用显存」算：Breeze 自己就占约 10GB，用总占用会刚加载就超过 80% 自己卸自己。"""
        if not self.s.get("voiceOn") or self.engine() == "local":
            self._low_since = None
            self.stop("语音关了或改用本地配音")
            return
        if M.yielding:
            self._low_since = None
            self.stop(M.yield_reason or "显存让路")
            return
        v = M.vram_info or {}
        total, used = v.get("total"), v.get("used")
        if not total or used is None:
            return
        breeze = self._breeze_gb() if self.proc.alive() else 0.0
        idle_s = float(self.s.get("voiceIdle") if self.s.get("voiceIdle") is not None else 10) * 60
        action, pct = vram_policy(used, total, breeze, self.proc.alive(), self._low_since, idle_s=idle_s)
        if action == "keep":
            return
        if action == "stop":
            self._low_since = None
            self.stop(f"显存占用 {pct:.0f}%（超过 80%）")
            return
        if action == "hold":
            self._low_since = None
            return
        if action == "wait":
            if self._low_since is None:
                self._low_since = time.time()
            return
        if action == "load":
            self._low_since = None
            try:
                asyncio.get_event_loop().create_task(self.warm())
            except Exception:
                pass

    def engine(self):
        """用谁出声：breeze（配好了）/ local（现有的本地配音，Breeze 没配好时的退路）/ none。"""
        want = str(self.s.get("voiceEngine") or "auto")
        if want != "local" and self.configured():
            return "breeze"
        if want != "breeze" and tts.T.env_ok() and tts.T.model_ok("custom"):
            return "local"
        return "breeze" if want == "breeze" else "none"

    async def speak_local(self, text):
        """退路：用配音服务里的预设音色一句一句念（Qwen3-TTS，本地）。给出的也是 16 位单声道 PCM，采样率在 self.sr_out。"""
        if M.yielding:
            raise VoiceError(f"现在在让路（{M.yield_reason or '显存不够'}），先不开口")
        try:
            await tts.T.ensure()
        except RuntimeError as e:
            raise VoiceError(str(e)[:200]) from None
        parts = [p for p in re.split(r"(?<=[。！？!?\n])", text) if p.strip()]
        buf, chunks = "", []
        for p in parts:                                          # 短句并一并，一次念二三十个字：太碎了停顿怪，太长了等得久
            buf += p
            if len(buf) >= 24:
                chunks.append(buf)
                buf = ""
        if buf.strip():
            chunks.append(buf)
        self.speaking = True
        try:
            async with httpx.AsyncClient(timeout=180) as c:
                for ch in chunks:
                    r = await c.post(tts.T.url("/generate"), json={"kind": "custom", "text": ch.strip(), "speaker": self.s.get("voiceSpeaker") or "Vivian",
                                                                   "language": "Chinese", "seed": int(self.s.get("voiceSeed") or 0)})
                    if r.status_code != 200:
                        try:
                            d = r.json().get("detail")
                        except Exception:
                            d = r.text
                        raise VoiceError(f"本地配音没念（{r.status_code}）：{str(d)[:120]}")
                    sr, pcm = tts.read_wav(r.content)
                    self.sr_out = sr
                    tts.T.last = time.time()
                    yield bytes(pcm) + b"\x00\x00" * int(sr * 0.12)
        except httpx.HTTPError as e:
            raise VoiceError(f"配音服务断了：{type(e).__name__}") from None
        finally:
            self.speaking = False

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
        eng = self.engine()
        self.sr_out = SR
        if eng == "local":
            async for chunk in self.speak_local(text):
                yield chunk
            return
        if eng == "none":
            raise VoiceError("还没有能出声的：到 设置 › 语音 配 Breeze TTS 2，或者先在 设置 › 本地模型 装配音（用它的声音顶着）")
        await self.ensure()
        data, fs = self.form(text)
        async with self._lock:
            self.speaking = True
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=120, write=30, pool=None)) as c:
                    for attempt in range(40):
                        async with c.stream("POST", self.url("/v1/audio/speech"), files={k: (None, v) for k, v in data.items()} | (fs or {})) as r:   # 一律 multipart（它的说明里就是这么收的）
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
        d, up = self.folder(), await self.health()
        return {"on": bool(self.s.get("voiceOn")), "engine": self.engine(), "want": self.s.get("voiceEngine") or "auto", "cmd": self.s.get("voiceCmd") or "",
                "speaker": self.s.get("voiceSpeaker") or "Vivian", "up": up, "alive": self.proc.alive(), "configured": self.configured(), "url": self.url(),
                "dir": str(d) if d else "", "dir_ok": bool(d and d.is_dir()), "python": paths.show(self.python()) if self.python() else "",
                "model": self.model(), "can_start": bool(self.cmd()), "fast": self._fast_mode or self.fast_mode(), "ref": REF.exists(), "ref_text": self.s.get("voiceRefText") or "",
                "desc": self.s.get("voiceDesc") or "", "installed": installed(), "model_ok": model_ok(), "asr": self.asr_ok(), "asr_why": self.asr_why(), "tts_env": tts.T.env_ok(),
                "yielding": M.yielding, "yield_reason": M.yield_reason, "auto": bool(self.s.get("voiceAuto", True)), "hands": bool(self.s.get("voiceHands", False)), "all": bool(self.s.get("voiceAll", False)),
                "max": int(self.s.get("voiceMax") or 400), "sr": SR}


V = Voice()
api = APIRouter()


@api.get("/api/voice")
async def voice_status():
    return await V.status()


@api.post("/api/voice/warm")
async def voice_warm():
    """v3.5.2：用户开始说话/确定要朗读时，后台预热 Breeze；不常驻，闲置和让路照旧释放显存。"""
    if not settings.S.get("voiceOn") or V.engine() != "breeze":
        return {"ok": False, "msg": "现在不用 Breeze"}
    await V.warm()
    return {"ok": True, "fast": V.fast_mode(), "alive": V.proc.alive()}


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
    sr = int(getattr(V, "sr_out", SR) or SR)
    return StreamingResponse(body_(), media_type=f"audio/L16;rate={sr};channels=1", headers={"X-Sr": str(sr), "X-Engine": V.engine(), "Cache-Control": "no-store"})


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
