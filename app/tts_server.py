"""配音服务（Qwen3-TTS）：在 tts-env 里运行（不是主后端的环境）。主后端用到时启动它，闲置一会儿、玩游戏时直接关掉（显存全还回去）。

只用显卡：检测不到 CUDA 就拒绝工作（和本地模型服务一样）。不联网：模型都在 models\\tts 里。
一次只装一个模型：预设音色（CustomVoice）/ 描述音色（VoiceDesign），换另一个时先卸掉这个。
注意力：装了 flash-attn 就用它；Windows 上一般装不上，用 PyTorch 自带的 sdpa；sdpa 也不行再退到 eager。
不装 SoX：只有旧版 25Hz 模型用它，下面放了一个空的 sox 模块顶替（免得一导入就去开 cmd 找 sox）。

手动运行（一般不需要）：
  tts-env\\Scripts\\python.exe app\\tts_server.py --port 8092 --models models\\tts
接口：
  GET  /health    在不在、装了哪个模型、显卡、显存、用的什么注意力、有没有对齐模型
  POST /generate  {kind: custom|design, text, speaker, instruct, language, seed} → 一段 WAV（16 位单声道），头尾的静音切掉
  POST /align     {pcm: base64 的 16 位单声道, sr, text, language} → {items: [{t 字或词, s 开始秒, e 结束秒}]}（v1.8.14）
                  时间轴对齐：Qwen3-ForcedAligner-0.6B（qwen-asr 包里的），拿音频和原文对出每个字的开始、结束。一次最多 180 秒
  POST /unload    卸掉模型（配音模型和对齐模型都卸）
"""
import argparse
import base64
import gc
import io
import os
import sys
import threading
import time
import types
import wave
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8092)
ap.add_argument("--models", default="models/tts")
A = ap.parse_args()
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def _no_sox(*a, **k):
    raise RuntimeError("没装 SoX（我们用的 12Hz 模型用不到它）")


# qwen-tts 一导入就 import sox；pysox 一导入就跑一次 `sox -h`（Windows 上要开一个 cmd，可能闪黑窗口），
# 而 SoX 只有旧版 25Hz 模型才用。放一个空的 sox 模块顶替：不装 SoX，也不开 cmd
if "sox" not in sys.modules:
    sys.modules["sox"] = types.ModuleType("sox")
    sys.modules["sox"].Transformer = _no_sox


def _no_nagisa(*a, **k):
    raise RuntimeError("没装 nagisa（只有日语分词用它，我们按中文的分法对齐）")


# qwen-asr 的对齐器一导入就 import nagisa（日语分词，要编译、装起来麻烦），我们只用中文的分法：同样放一个空模块顶替
if "nagisa" not in sys.modules:
    sys.modules["nagisa"] = types.ModuleType("nagisa")
    sys.modules["nagisa"].tagging = _no_nagisa

import numpy as np  # noqa: E402
import torch  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import Body, FastAPI, HTTPException  # noqa: E402
from fastapi.responses import Response  # noqa: E402

NAMES = {"custom": "Qwen3-TTS-12Hz-1.7B-CustomVoice", "design": "Qwen3-TTS-12Hz-1.7B-VoiceDesign"}   # 和 app/paths.py 的 TTS_MODELS 一致
ALIGN = "Qwen3-ForcedAligner-0.6B"                  # 和 app/paths.py 的 ALIGN_MODEL 一致
ALIGN_MAX = 180.0                                   # 对齐器一次最多吃多长的音频（qwen-asr 里写的 180 秒）
CUDA = torch.cuda.is_available()
GPU = torch.cuda.get_device_name(0) if CUDA else ""
LOCK = threading.Lock()          # 一次只生成一句
app = FastAPI(title="agent-tts")
st = {"kind": None, "model": None, "attn": "", "error": "", "load_s": 0.0, "n": 0, "gen_s": 0.0, "audio_s": 0.0, "aligner": None, "align_n": 0}


def attn_order():
    try:
        import flash_attn  # noqa: F401
        return ["flash_attention_2", "sdpa", "eager"]
    except Exception:
        return ["sdpa", "eager"]


def vram():
    if not CUDA:
        return {}
    free, total = torch.cuda.mem_get_info()
    return {"alloc_gb": round(torch.cuda.memory_allocated() / 2**30, 2), "reserved_gb": round(torch.cuda.memory_reserved() / 2**30, 2),
            "free_gb": round(free / 2**30, 2), "total_gb": round(total / 2**30, 2)}


def unload():
    if st["model"] is not None:
        st["model"], st["kind"] = None, None
        gc.collect()
        if CUDA:
            torch.cuda.empty_cache()
        print("卸掉了配音模型", flush=True)


def load(kind):
    if kind not in NAMES:
        raise HTTPException(400, f"没有这个模型：{kind}")
    if st["kind"] == kind and st["model"] is not None:
        return st["model"]
    if not CUDA:
        raise HTTPException(503, "没检测到可用的显卡（CUDA）。按约定只用显卡，不在 CPU 上跑。")
    d = Path(A.models) / NAMES[kind]
    if not (d / "config.json").exists():
        raise HTTPException(404, f"模型还没下：{d}（设置 › 本地模型 点「安装配音」）")
    unload()
    if st["aligner"] is not None:          # 换配音模型时对齐模型也先放下（显存留给大的；要对齐时几秒就装回来）
        st["aligner"] = None
        gc.collect()
        torch.cuda.empty_cache()
    from qwen_tts import Qwen3TTSModel
    t0, err = time.time(), None
    for at in attn_order():
        try:
            m = Qwen3TTSModel.from_pretrained(str(d), device_map="cuda:0", dtype=torch.bfloat16, attn_implementation=at)
            st.update(model=m, kind=kind, attn=at, error="", load_s=round(time.time() - t0, 1))
            print(f"装好了 {NAMES[kind]}（注意力 {at}，用时 {st['load_s']} 秒，显存 {vram()}）", flush=True)
            return m
        except Exception as e:
            err = e
            print(f"用 {at} 装模型没成：{e}", flush=True)
            gc.collect()
            torch.cuda.empty_cache()
    st["error"] = f"模型装不上：{err}"[:300]
    raise HTTPException(500, st["error"])


def trim(w, sr, thr=0.01, margin=0.05):
    """切掉头尾的静音（留 0.05 秒），这样时间轴上的开始、结束就是真正开口、收声的时候。"""
    loud = np.flatnonzero(np.abs(w) > thr)
    if not len(loud):
        return w
    m = int(sr * margin)
    return w[max(0, loud[0] - m): min(len(w), loud[-1] + m)]


def to_wav(w, sr):
    pcm = (np.clip(w, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    b = io.BytesIO()
    with wave.open(b, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(int(sr))
        f.writeframes(pcm)
    return b.getvalue()


def load_aligner():
    """对齐模型（0.6B，bf16 大约 1.5 GB 显存）：用到才装，装上就留着（和配音模型可以同时在）；显存不够先卸掉配音模型再装一次。"""
    if st["aligner"] is not None:
        return st["aligner"]
    if not CUDA:
        raise HTTPException(503, "没检测到可用的显卡（CUDA）。按约定只用显卡，不在 CPU 上跑。")
    d = Path(A.models) / ALIGN
    if not (d / "config.json").exists():
        raise HTTPException(404, f"对齐模型还没下：{d}（设置 › 本地模型 点「接着装」）")
    from qwen_asr import Qwen3ForcedAligner
    t0 = time.time()
    for k in range(2):
        try:
            st["aligner"] = Qwen3ForcedAligner.from_pretrained(str(d), dtype=torch.bfloat16, device_map="cuda:0")
            break
        except torch.cuda.OutOfMemoryError:
            gc.collect()
            torch.cuda.empty_cache()
            if k or st["model"] is None:
                raise HTTPException(507, "显存不够装对齐模型：先关掉占显存的程序再试") from None
            unload()
    print(f"装好了对齐模型 {ALIGN}（用时 {time.time() - t0:.1f} 秒，显存 {vram()}）", flush=True)
    return st["aligner"]


@app.get("/health")
def health():
    return {"ok": True, "cuda": CUDA, "gpu": GPU, "loaded": st["kind"], "attn": st["attn"], "busy": LOCK.locked(), "error": st["error"],
            "vram": vram(), "models": {k: (Path(A.models) / v / "config.json").exists() for k, v in NAMES.items()},
            "align": (Path(A.models) / ALIGN / "config.json").exists(), "aligner": st["aligner"] is not None,
            "speakers": (st["model"].get_supported_speakers() if st["kind"] == "custom" else None),
            "stats": {"n": st["n"], "gen_s": round(st["gen_s"], 1), "audio_s": round(st["audio_s"], 1)}}


@app.post("/generate")
def generate(body: dict = Body(...)):
    kind, text = body.get("kind") or "custom", (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "没有文字")
    lang = body.get("language") or "Auto"
    instruct = (body.get("instruct") or "").strip()
    seed = int(body.get("seed") or 0)
    with LOCK:
        m = load(kind)
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        # 12Hz：一秒 12 帧，中文一个字大约 3 帧。按一个字 6 帧给够（10 分钟的一整段也够），又不至于偶尔停不下来一直念
        kw = {"max_new_tokens": min(24000, 96 + len(text) * 6)}
        t0 = time.time()
        try:
            if kind == "custom":
                wavs, sr = m.generate_custom_voice(text=text, speaker=body.get("speaker") or "Vivian", language=lang,
                                                   instruct=instruct or None, **kw)
            else:
                if not instruct:
                    raise HTTPException(400, "描述音色要写一段音色描述")
                wavs, sr = m.generate_voice_design(text=text, instruct=instruct, language=lang, **kw)
        except HTTPException:
            raise
        except ValueError as e:                     # 音色名、语言不对
            raise HTTPException(400, str(e)[:300]) from None
        except torch.cuda.OutOfMemoryError:
            gc.collect()
            torch.cuda.empty_cache()
            raise HTTPException(507, "显存不够：先关掉占显存的程序再试") from None
        w = trim(np.asarray(wavs[0], dtype=np.float32).reshape(-1), sr)
        dt = time.time() - t0
        st["n"] += 1
        st["gen_s"] += dt
        st["audio_s"] += len(w) / sr
        print(f"生成 {len(text)} 字 → {len(w) / sr:.1f} 秒音频，用时 {dt:.1f} 秒（{kind}，种子 {seed}）", flush=True)
        return Response(content=to_wav(w, sr), media_type="audio/wav", headers={"X-Gen-Sec": f"{dt:.2f}", "X-Sr": str(sr)})


@app.post("/align")
def align(body: dict = Body(...)):
    """时间轴对齐：音频 + 原文 → 每个字（英文、数字是一个词）的开始、结束（秒，从这段音频开头算）。标点不算，不听写、不改字。"""
    text = (body.get("text") or "").strip()
    try:
        sr = int(body.get("sr") or 24000)
        w = np.frombuffer(base64.b64decode(body.get("pcm") or ""), dtype="<i2").astype(np.float32) / 32768
    except Exception:
        raise HTTPException(400, "音频格式不对（要 base64 的 16 位单声道）") from None
    if not text or not len(w):
        raise HTTPException(400, "没有文字或者没有音频")
    if len(w) / sr > ALIGN_MAX:
        raise HTTPException(400, f"一次最多对齐 {ALIGN_MAX:.0f} 秒（这段 {len(w) / sr:.0f} 秒），分开对")
    with LOCK:
        m = load_aligner()
        t0 = time.time()
        try:
            res = m.align(audio=(w, sr), text=text, language=body.get("language") or "Chinese")
        except torch.cuda.OutOfMemoryError:
            gc.collect()
            torch.cuda.empty_cache()
            raise HTTPException(507, "显存不够：先关掉占显存的程序再试") from None
        dt = time.time() - t0
        st["align_n"] += 1
    items = [{"t": it.text, "s": float(it.start_time), "e": float(it.end_time)} for it in (res[0] if res else [])]
    print(f"对齐 {len(text)} 字、{len(w) / sr:.1f} 秒音频 → {len(items)} 个字/词，用时 {dt:.1f} 秒", flush=True)
    return {"items": items, "sec": round(dt, 2)}


@app.post("/unload")
def unload_ep():
    with LOCK:
        unload()
        if st["aligner"] is not None:
            st["aligner"] = None
            gc.collect()
            if CUDA:
                torch.cuda.empty_cache()
    return {"ok": True}


if __name__ == "__main__":
    print(f"配音服务启动：显卡 {GPU or '没有'}，模型在 {A.models}，注意力候选 {attn_order()}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=A.port, log_level="warning")
