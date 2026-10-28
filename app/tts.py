"""配音（Qwen3-TTS 1.7B，Apache 2.0，可以商用）：后端这边的管家 + 接口。界面上的「配音」页用它。

- 配音服务（app/tts_server.py）在 tts-env 里跑，端口 8092。用到才启动；闲置 ttsIdle 分钟（默认 10）关掉；
  让路（在玩游戏、别的程序占显存）时直接关掉，正在生成就停下这次。不联网：模型都在 models\\tts。
- 两个模型：预设音色 CustomVoice（9 个音色，5 个中文，一句话控制语气）、描述音色 VoiceDesign（一段文字描述造音色）。
  不接克隆（Base）。以后接克隆时界面上要写明：不克隆任何真人的声音。
- 长文案：按句子切开一句一句生成，句子之间停 ttsGap 秒、段落之间停 ttsParaGap 秒，拼成一个 WAV；
  同时出时间轴（每句的开始、结束、原文），JSON 和 SRT 各一份，做视频时字幕和画面按它对齐。
- 生成完先放 data\\tts（试听用，只留最近一次）；点「保存」才放进「配音输出」，一次一个文件夹，名字带日期和音色名。
- 我的音色：描述音色的「描述 + 随机种子」存起来，下次一键用。存在数据库里（data），不进仓库。
"""
import asyncio
import io
import json
import os
import random
import re
import shutil
import time
import wave
from datetime import datetime

import httpx
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from . import db, feed, paths, settings
from .models import M, Proc

# 预设音色（CustomVoice 自带的 9 个；名字不分大小写）。每个音色用母语最好，但都能说别的语言
SPEAKERS = [
    {"id": "Vivian", "name": "Vivian", "d": "女声 · 明亮、略带锐气的年轻女声", "lang": "中文"},
    {"id": "Serena", "name": "Serena", "d": "女声 · 温柔、温暖的年轻女声", "lang": "中文"},
    {"id": "Uncle_Fu", "name": "Uncle_Fu", "d": "男声 · 低沉醇厚的成熟男声", "lang": "中文"},
    {"id": "Dylan", "name": "Dylan", "d": "男声 · 清亮自然的北京青年", "lang": "中文 · 北京话"},
    {"id": "Eric", "name": "Eric", "d": "男声 · 活泼、略带沙哑的成都男声", "lang": "中文 · 四川话"},
    {"id": "Ryan", "name": "Ryan", "d": "男声 · 节奏感强", "lang": "英文"},
    {"id": "Aiden", "name": "Aiden", "d": "男声 · 阳光的美式男声", "lang": "英文"},
    {"id": "Ono_Anna", "name": "Ono_Anna", "d": "女声 · 俏皮轻快", "lang": "日语"},
    {"id": "Sohee", "name": "Sohee", "d": "女声 · 温暖、情感丰富", "lang": "韩语"},
]
LANGS = [("Chinese", "中文"), ("English", "英文"), ("Auto", "自动")]
MODEL_INFO = {"custom": "预设音色（CustomVoice）", "design": "描述音色（VoiceDesign）"}
LICENSE = "Apache-2.0"
NEED_GB = 6.0          # 一个 1.7B 配音模型大概占多少显存（bf16 + 运行时，估的；真机实测后改）
MAX_CHARS = 20000
# 「试试是不是同一个人」：同一段描述 + 同一个种子，念两段内容完全不同的话，前后听像不像一个人
SAME_TEXT = "今天我们来聊一聊最近很火的几个 AI 工具，看看哪个真的好用。\n\n说完正事，再讲讲我这周写代码的时候踩过的一个坑。"
DRAFT = paths.DATA / "tts"

END = "。！？!?…"
CLOSE = "”’\"'」』）)】》"
SOFT = "，,、；;：:"


# ---------------- 切句子 ----------------
def _speak(s):
    return bool(re.search(r"\w", s))


def soft_split(s, maxlen=60, piece=40):
    """太长的句子（超过 maxlen 字）在逗号、顿号、分号处再切开，每块不超过 piece 字左右；没有逗号就硬切。"""
    if len(s) <= maxlen:
        return [s]
    parts = re.findall(r"[^，,、；;：:]+[，,、；;：:]*|[，,、；;：:]+", s)
    out, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(p) > piece:
            out.append(cur)
            cur = p
        else:
            cur += p
    if cur:
        out.append(cur)
    res = []
    for o in out:
        while len(o) > maxlen:
            cut = o.rfind(" ", 0, piece)
            cut = cut if cut > piece // 2 else piece
            res.append(o[:cut])
            o = o[cut:]
        if o:
            res.append(o)
    final = []
    for o in (x.strip() for x in res):
        if not o:
            continue
        if final and not _speak(o):
            final[-1] += o
        else:
            final.append(o)
    return final


def split(text, gap=0.35, para=0.7, comma=0.15):
    """文案 → [{text, gap}]。gap 是这一块念完后停几秒：句子之间 gap，段落（空一行）之间 para，
    长句在逗号处切开的块之间 comma，最后一块 0。只有标点没有字的块并到前一块里。"""
    out = []
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    for p in re.split(r"\n\s*\n", text):
        sents = []
        for line in p.split("\n"):
            line = line.strip()
            buf, i = "", 0
            while i < len(line):
                ch = line[i]
                buf += ch
                if ch in END or (ch == "." and (i + 1 == len(line) or line[i + 1].isspace())):
                    while i + 1 < len(line) and (line[i + 1] in END or line[i + 1] in CLOSE or line[i + 1] == "."):
                        i += 1
                        buf += line[i]
                    sents.append(buf.strip())
                    buf = ""
                i += 1
            if buf.strip():
                sents.append(buf.strip())
        added = False
        for s in sents:
            if not _speak(s):
                if out:
                    out[-1]["text"] += s
                continue
            for piece in soft_split(s):
                out.append({"text": piece, "gap": comma})
                added = True
            out[-1]["gap"] = gap
        if added:
            out[-1]["gap"] = para
    if out:
        out[-1]["gap"] = 0.0
    return out


# ---------------- 时间轴 ----------------
def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def to_srt(segs):
    return "\n".join(f"{s['i']}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['text']}\n" for s in segs)


def read_wav(b):
    with wave.open(io.BytesIO(b), "rb") as f:
        if f.getnchannels() != 1 or f.getsampwidth() != 2:
            raise RuntimeError("配音服务返回的音频格式不对（要 16 位单声道）")
        return f.getframerate(), f.readframes(f.getnframes())


def write_wav(path, sr, pcm):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(bytes(pcm))


def safe_name(s, n=24):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", str(s or "")).strip(" .")
    return s[:n] or "配音"


def mmss(sec):
    sec = int(round(sec))
    return f"{sec // 60} 分 {sec % 60:02d} 秒" if sec >= 60 else f"{sec} 秒"


class Stopped(Exception):
    pass


# ---------------- 管家 ----------------
class TTS:
    def __init__(self):
        self.proc = Proc("tts")
        self.proc.vram_est = NEED_GB
        M.extra.append(self.proc)        # 显存按"我们自己的"算；退出 Agent 时一起停
        self.last = 0.0
        self.job = None
        self._task = None
        self._h, self._hts = None, 0.0

    @property
    def s(self):
        return settings.S

    def py(self):
        return paths.resolve(self.s.get("ttsPython", ""), paths.tts_python())

    def env_ok(self):
        return self.py().exists()

    def model_dir(self, kind):
        return paths.MODELS_TTS / paths.TTS_MODELS[kind]

    def model_ok(self, kind):
        d = self.model_dir(kind)
        return (d / "config.json").exists() and (d / "speech_tokenizer" / "config.json").exists() and any(d.glob("*.safetensors"))

    def out_dir(self):
        return paths.resolve(self.s.get("ttsOut", ""), paths.TTS_OUT)

    def url(self, p=""):
        return f"http://127.0.0.1:{self.s['ttsPort']}{p}"

    def cmd(self):
        return [self.py(), paths.APP / "tts_server.py", "--port", self.s["ttsPort"], "--models", paths.MODELS_TTS]

    def env(self):
        e = M.env()
        e.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        return e

    def busy(self):
        return bool(self.job and self.job["st"] == "run")

    async def health(self, fresh=False):
        if not fresh and time.time() - self._hts < 2:
            return self._h
        try:
            async with httpx.AsyncClient(timeout=1.5) as c:
                r = await c.get(self.url("/health"))
                self._h = r.json() if r.status_code == 200 else None
        except Exception:
            self._h = None
        self._hts = time.time()
        return self._h

    async def ensure(self, timeout=240):
        h = await self.health(fresh=True)
        if h:
            return h
        if not self.env_ok():
            raise RuntimeError("还没装配音环境：双击 Agent 文件夹里的「安装配音.bat」")
        if not self.proc.alive():
            self.proc.start(self.cmd(), paths.ROOT, self.env())
            self.last = time.time()
        t0 = time.time()
        while time.time() - t0 < timeout:
            await asyncio.sleep(1)
            h = await self.health(fresh=True)
            if h:
                return h
            if not self.proc.alive():
                raise RuntimeError("配音服务没起来（看 data\\logs\\tts.log）：\n" + self.proc.tail(6))
        raise RuntimeError("配音服务启动超时（看 data\\logs\\tts.log）")

    def stop(self, why=""):
        if self.proc.alive():
            kids = []
            try:                       # Windows 上虚拟环境的 python.exe 会再起一个真正干活的子进程：按进程号一起停（只停自己开的）
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
            self._h, self._hts = None, 0.0
            feed.add(f"配音服务关了：{why}，显存还回去了" if why else "配音服务关了", "info", job="配音")

    def tick(self):
        """后台照看每 2 秒调一次：让路（在玩游戏、显存不够）→ 停下正在生成的、关掉服务；闲置 ttsIdle 分钟 → 关掉服务。"""
        if M.yielding:
            if self.busy() and not self.job["stop"]:
                self.job["stop"] = M.yield_reason or "显存让路"
            if self.proc.alive():
                self.stop(M.yield_reason or "显存让路")
            return
        idle = float(self.s.get("ttsIdle") or 10) * 60
        if self.proc.alive() and not self.busy() and time.time() - (self.last or self.proc.started) > idle:
            self.stop(f"闲置 {int(idle // 60)} 分钟")

    async def free_vram(self):
        """显卡剩的不够一个配音模型：先让模型服务把底座卸了（底座用到时会自己再装）。"""
        v = M.vram_info or {}
        if v.get("total") and v.get("used") is not None and v["total"] - v["used"] < NEED_GB and not self.proc.alive():
            await M.unload("base")
            feed.add("显卡剩的显存不够配音，先把底座卸了（用到时会自己装回来）", "info", job="配音")

    # ---------- 一次生成 ----------
    def voice(self, req):
        """把界面传来的选择整理成：用哪个模型、念的时候带什么说明、名字叫什么（文件名用）。"""
        mode = req.get("mode") or "preset"
        tone = (req.get("tone") or "").strip()[:200]
        lang = req.get("lang") if req.get("lang") in dict(LANGS) else "Chinese"
        seed = req.get("seed")
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = random.randint(1, 2**31 - 1)
        seed = max(1, min(seed, 2**31 - 1))
        if mode == "preset":
            spk = next((x["id"] for x in SPEAKERS if x["id"].lower() == str(req.get("speaker") or "").lower()), None)
            if not spk:
                raise HTTPException(400, "选一个预设音色")
            return {"mode": "preset", "kind": "custom", "speaker": spk, "tone": tone, "instruct": tone, "lang": lang, "seed": seed,
                    "label": spk}
        desc = (req.get("desc") or "").strip()[:500]
        if not desc:
            raise HTTPException(400, "写一段音色描述（比如：三十岁左右的男声，声音低沉温和，语速平稳）")
        name = (req.get("name") or "").strip()[:40]
        instruct = desc + ("；" + tone if tone else "")
        return {"mode": "design", "kind": "design", "desc": desc, "name": name, "tone": tone, "instruct": instruct, "lang": lang,
                "seed": seed, "label": name or "描述音色"}

    def start(self, req):
        if self.busy():
            raise HTTPException(409, "上一段还在生成，等它好了或者先点「停下」")
        if M.yielding:
            raise HTTPException(409, f"现在在让路（{M.yield_reason or '显存不够'}），配音先不开；游戏关了再生成")
        same = bool(req.get("same"))
        text = SAME_TEXT if same else (req.get("text") or "")
        if len(text) > MAX_CHARS:
            raise HTTPException(400, f"一次最多 {MAX_CHARS} 字，分几次生成吧")
        v = self.voice(req)
        if not self.model_ok(v["kind"]) and not ((self._h or {}).get("models") or {}).get(v["kind"]):
            raise HTTPException(400, f"{MODEL_INFO[v['kind']]}的模型还没下：双击「安装配音.bat」")
        gap = float(self.s.get("ttsGap", 0.35))
        segs = split(text, gap=1.0 if same else gap, para=1.2 if same else float(self.s.get("ttsParaGap", 0.7)))
        if not segs:
            raise HTTPException(400, "没有要念的字")
        chars = sum(len(x["text"]) for x in segs)
        self.job = {"id": int(time.time() * 1000), "st": "run", "i": 0, "n": len(segs), "chars": chars, "done_chars": 0, "cur": "",
                    "msg": "准备中", "err": "", "stop": "", "same": same, "voice": v, "t0": time.time(), "t1": 0.0,
                    "audio_s": 0.0, "eta": None}
        self._task = asyncio.get_event_loop().create_task(self._run(self.job, text, segs))
        feed.add(f"开始配音：{len(segs)} 句、{chars} 字，音色 {v['label']}" + ("（试同一个人）" if same else ""), "head", job="配音")
        return self.public()

    async def _run(self, job, text, segs):
        v = job["voice"]
        try:
            job["msg"] = "启动配音服务（第一次要等半分钟到一分钟）" if not self._h else "准备中"
            await self.free_vram()
            await self.ensure()
            job["msg"] = f"装{MODEL_INFO[v['kind']]}的模型（换模型时要等一会）"
            pcm, sr, tl = bytearray(), None, []
            job["t1"] = time.time()
            async with httpx.AsyncClient(timeout=900) as c:
                for i, sg in enumerate(segs):
                    if job["stop"]:
                        raise Stopped(job["stop"])
                    job.update(i=i, cur=sg["text"])
                    if i:
                        job["msg"] = f"第 {i + 1}/{len(segs)} 句"
                    try:
                        r = await c.post(self.url("/generate"), json={"kind": v["kind"], "text": sg["text"], "speaker": v.get("speaker"),
                                                                       "instruct": v["instruct"], "language": v["lang"], "seed": v["seed"]})
                    except httpx.HTTPError as e:
                        if job["stop"]:
                            raise Stopped(job["stop"]) from None
                        raise RuntimeError(f"配音服务断了：{e}") from None
                    self.last = time.time()
                    if r.status_code != 200:
                        try:
                            why = r.json().get("detail") or r.text
                        except Exception:
                            why = r.text
                        raise RuntimeError(str(why)[:300])
                    rate, frames = read_wav(r.content)
                    sr = sr or rate
                    if rate != sr:
                        raise RuntimeError("前后两句的采样率对不上")
                    start = len(pcm) / 2 / sr
                    pcm += frames
                    end = len(pcm) / 2 / sr
                    tl.append({"i": i + 1, "start": round(start, 3), "end": round(end, 3), "text": sg["text"]})
                    if sg["gap"] > 0 and i < len(segs) - 1:
                        pcm += bytes(2 * int(sr * sg["gap"]))
                    job["done_chars"] += len(sg["text"])
                    job["audio_s"] = round(end, 2)
                    per = (time.time() - job["t1"]) / max(1, job["done_chars"])
                    job["eta"] = round(per * (job["chars"] - job["done_chars"]))
            gen = time.time() - job["t1"]
            meta = self._write_draft(job, text, sr, pcm, tl, gen)
            speed = {"audio_s": meta["duration"], "gen_s": round(gen, 1), "per_min": round(gen / max(meta["duration"], 0.1) * 60),
                     "attn": (self._h or {}).get("attn", ""), "kind": v["kind"], "ts": time.time()}
            db.kv_set("tts_speed", speed)
            job.update(st="done", i=len(segs), cur="", eta=0,
                       msg=f"好了：{mmss(meta['duration'])}音频，用时 {mmss(gen)}（每分钟音频约 {mmss(speed['per_min'])}）")
            feed.add(f"配音好了：{len(segs)} 句，{mmss(meta['duration'])}音频，生成用了 {mmss(gen)}", "ok", job="配音")
        except Stopped as e:
            job.update(st="stop", msg=f"停了：{e}（这次没生成完，没保存）")
            feed.add(f"配音停了：{e}", "warn", job="配音")
        except Exception as e:
            job.update(st="err", err=str(e)[:400], msg="没生成成：" + str(e)[:200])
            feed.add(f"配音没生成成：{str(e)[:200]}", "err", job="配音")

    def _write_draft(self, job, text, sr, pcm, tl, gen):
        v = job["voice"]
        DRAFT.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        voice = {k: v[k] for k in ("mode", "speaker", "desc", "name", "tone", "seed") if v.get(k) not in (None, "")}
        meta = {"app": "Agent 配音", "created": now.strftime("%Y-%m-%d %H:%M:%S"),
                "name": f"{now:%Y-%m-%d_%H%M}_{safe_name(v['label'])}", "model": paths.TTS_MODELS[v["kind"]], "license": LICENSE,
                "voice": voice, "language": v["lang"], "sample_rate": sr, "duration": round(len(pcm) / 2 / sr, 3),
                "gen_seconds": round(gen, 1), "same_test": job["same"],
                "gaps": {"sentence": float(self.s.get("ttsGap", 0.35)), "paragraph": float(self.s.get("ttsParaGap", 0.7))},
                "segments": tl}
        tmp = DRAFT / "draft.tmp.wav"
        write_wav(tmp, sr, pcm)
        tmp.replace(DRAFT / "draft.wav")
        (DRAFT / "draft.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        (DRAFT / "draft.srt").write_text(to_srt(tl), "utf-8")
        (DRAFT / "draft.txt").write_text(text.strip() + "\n", "utf-8")
        return meta

    def draft(self):
        try:
            m = json.loads((DRAFT / "draft.json").read_text("utf-8"))
        except Exception:
            return None
        if not (DRAFT / "draft.wav").exists():
            return None
        m["ver"] = int((DRAFT / "draft.wav").stat().st_mtime)
        return m

    def save(self):
        m = self.draft()
        if not m:
            raise HTTPException(404, "还没有生成过")
        out = self.out_dir()
        d, k = out / m["name"], 2
        while d.exists():
            d, k = out / f"{m['name']}_{k}", k + 1
        d.mkdir(parents=True)
        base = d.name
        shutil.copy2(DRAFT / "draft.wav", d / f"{base}.wav")
        meta = dict(m, audio=f"{base}.wav", subtitles=f"{base}_字幕.srt", script=f"{base}_文案.txt")
        meta.pop("ver", None)
        (d / f"{base}_时间轴.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        shutil.copy2(DRAFT / "draft.srt", d / f"{base}_字幕.srt")
        shutil.copy2(DRAFT / "draft.txt", d / f"{base}_文案.txt")
        db.kv_set("tts_saved", {"dir": str(d), "name": base, "ts": time.time()})
        feed.add(f"配音保存好了：{paths.show(d)}", "ok", job="配音")
        return d

    def public(self):
        j = self.job
        if not j:
            return None
        keys = ("id", "st", "i", "n", "chars", "done_chars", "cur", "msg", "err", "same", "audio_s", "eta")
        out = {k: j[k] for k in keys}
        out["voice"] = j["voice"]["label"]
        out["elapsed"] = round(time.time() - j["t0"])
        return out

    # ---------- 我的音色 ----------
    def voices(self):
        return db.kv_get("tts_voices", []) or []

    def add_voice(self, body):
        name = (body.get("name") or "").strip()[:40]
        desc = (body.get("desc") or "").strip()[:500]
        if not name or not desc:
            raise HTTPException(400, "起个名字，写好描述")
        try:
            seed = int(body.get("seed"))
        except (TypeError, ValueError):
            raise HTTPException(400, "种子要是数字") from None
        vs = [v for v in self.voices() if v["name"] != name]
        vs.append({"id": int(time.time() * 1000), "name": name, "desc": desc, "seed": seed, "lang": body.get("lang") or "Chinese",
                   "ts": time.time()})
        db.kv_set("tts_voices", vs[-40:])
        return vs

    def del_voice(self, vid):
        vs = [v for v in self.voices() if str(v["id"]) != str(vid)]
        db.kv_set("tts_voices", vs)
        return vs

    async def status(self):
        h = await self.health()
        return {"env": self.env_ok(), "models": {k: self.model_ok(k) for k in paths.TTS_MODELS}, "model_names": paths.TTS_MODELS,
                "server": bool(h), "proc": self.proc.alive(), "loaded": (h or {}).get("loaded"), "attn": (h or {}).get("attn"),
                "cuda": (h or {}).get("cuda"), "yield": (M.yield_reason or "显存让路") if M.yielding else "",
                "job": self.public(), "draft": self.draft(), "speakers": SPEAKERS, "langs": LANGS, "voices": self.voices(),
                "out": paths.show(self.out_dir()), "saved": db.kv_get("tts_saved"), "speed": db.kv_get("tts_speed"),
                "idle": self.s.get("ttsIdle"), "gap": self.s.get("ttsGap"), "para": self.s.get("ttsParaGap"), "license": LICENSE}


T = TTS()

# ---------------- 接口 ----------------
api = APIRouter()


@api.get("/api/tts")
async def tts_status():
    return await T.status()


@api.post("/api/tts/gen")
async def tts_gen(body: dict = Body(...)):
    return {"job": T.start(body)}


@api.post("/api/tts/stop")
def tts_stop():
    if T.busy():
        T.job["stop"] = "你点了「停下」"        # 念完手上这一句就停（服务不关，模型还在，下次不用重新装）
        T.job["msg"] = "念完这一句就停"
    return {"job": T.public()}


@api.post("/api/tts/off")
def tts_off():
    if T.busy():
        raise HTTPException(409, "正在生成，先点「停下」")
    T.stop("你点了「关掉」")
    return {"ok": True}


@api.get("/api/tts/draft.wav")
def tts_draft_wav():
    p = DRAFT / "draft.wav"
    if not p.exists():
        raise HTTPException(404, "还没有生成过")
    return FileResponse(p, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@api.post("/api/tts/save")
def tts_save():
    d = T.save()
    return {"dir": paths.show(d), "name": d.name, "msg": f"存好了：{paths.show(d)}"}


@api.post("/api/tts/open")
def tts_open(body: dict = Body(default={})):
    saved = db.kv_get("tts_saved") or {}
    d = saved.get("dir") if body.get("last") and saved.get("dir") and os.path.isdir(saved.get("dir")) else T.out_dir()
    d = str(d)
    os.makedirs(d, exist_ok=True)
    if paths.IS_WIN:
        os.startfile(d)          # 打开资源管理器（不是黑窗口）
        return {"msg": "打开了：" + paths.show(d)}
    return {"msg": "文件夹在：" + paths.show(d)}


@api.post("/api/tts/voices")
def tts_add_voice(body: dict = Body(...)):
    return {"voices": T.add_voice(body), "msg": f"存好了：{(body.get('name') or '').strip()}"}


@api.delete("/api/tts/voices/{vid}")
def tts_del_voice(vid: str):
    return {"voices": T.del_voice(vid)}
