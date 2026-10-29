"""配音服务（Qwen3-TTS）：在 tts-env 里运行（不是主后端的环境）。主后端用到时启动它，闲置一会儿、玩游戏时直接关掉（显存全还回去）。

只用显卡：检测不到 CUDA 就拒绝工作（和本地模型服务一样）。不联网：模型都在 models\\tts 里。
一次只装一个模型：预设音色（CustomVoice）/ 描述音色（VoiceDesign），换另一个时先卸掉这个。
注意力：装了 flash-attn 就用它；Windows 上一般装不上，用 PyTorch 自带的 sdpa；sdpa 也不行再退到 eager。
不装 SoX：只有旧版 25Hz 模型用它，下面放了一个空的 sox 模块顶替（免得一导入就去开 cmd 找 sox）。

手动运行（一般不需要）：
  tts-env\\Scripts\\python.exe app\\tts_server.py --port 8092 --models models\\tts
接口：
  GET  /health    在不在、装了哪个模型、显卡、显存、用的什么注意力
  POST /generate  {kind: custom|design, text, speaker, instruct, language, seed} → 一段 WAV（16 位单声道），头尾的静音切掉
  POST /unload    卸掉模型
"""
import argparse
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

import numpy as np  # noqa: E402
import torch  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import Body, FastAPI, HTTPException  # noqa: E402
from fastapi.responses import Response  # noqa: E402

NAMES = {"custom": "Qwen3-TTS-12Hz-1.7B-CustomVoice", "design": "Qwen3-TTS-12Hz-1.7B-VoiceDesign"}   # 和 app/paths.py 的 TTS_MODELS 一致
CUDA = torch.cuda.is_available()
GPU = torch.cuda.get_device_name(0) if CUDA else ""
LOCK = threading.Lock()          # 一次只生成一句
app = FastAPI(title="agent-tts")
st = {"kind": None, "model": None, "attn": "", "error": "", "load_s": 0.0, "n": 0, "gen_s": 0.0, "audio_s": 0.0}


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


@app.get("/health")
def health():
    return {"ok": True, "cuda": CUDA, "gpu": GPU, "loaded": st["kind"], "attn": st["attn"], "busy": LOCK.locked(), "error": st["error"],
            "vram": vram(), "models": {k: (Path(A.models) / v / "config.json").exists() for k, v in NAMES.items()},
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


@app.post("/unload")
def unload_ep():
    with LOCK:
        unload()
    return {"ok": True}


if __name__ == "__main__":
    print(f"配音服务启动：显卡 {GPU or '没有'}，模型在 {A.models}，注意力候选 {attn_order()}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=A.port, log_level="warning")
