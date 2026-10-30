"""假的配音服务（只在 Linux 沙箱里测试用）：接口和 app/tts_server.py 一样，但不装模型、不要显卡，
念出来的是一段"嘟——"，长短按字数算（一个字 0.2 秒），标点处自己停一下，方便检查拼接、停顿、时间轴对不对。
测试后端（dev/test_backend.py）把配音服务的启动命令换成这个，所以"用到才启动、闲置关掉、让路关掉"走的是真的那一套。
/align（v1.8.14，假的对齐器）：不装模型，按音频里"有声音的一段一段"和原文里标点隔开的一小段一一对上，给每个字、词一个时间。
  句子的开始、结束是准的（这里的声音都是"嘟"，一段对一段）；对不上段数就按字数平均分（就不准了）。
  dev/.run/fake_tts_noalign.flag 在：当作对齐模型没下（404），测退回按停顿猜。
用法：python dev/fake_tts.py --port 8092"""
import argparse
import base64
import io
import math
import re
import struct
import threading
import time
import wave

import uvicorn
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import Response

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8092)
ap.add_argument("--models", default="")
A = ap.parse_args()
SR = 24000
LOCK = threading.Lock()
app = FastAPI()
st = {"kind": None, "n": 0, "align_n": 0, "last_align": None}
RUN = __import__("pathlib").Path(__file__).resolve().parent / ".run"


def secs(text):
    return round(0.2 * len(text.strip()), 3)


def tone(sec, f):
    n = int(SR * sec)
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * f * i / SR))) for i in range(n))


GAP = {"。": 0.3, "！": 0.3, "？": 0.3, "!": 0.3, "?": 0.3, "…": 0.3, "\n": 0.5, "，": 0.14, ",": 0.14, "、": 0.14, "；": 0.14, "：": 0.14}


def speak(text, f):
    """整段一次念（v1.8.9）：一个字 0.2 秒的"嘟"，句号后停 0.3 秒、换行停 0.5 秒、逗号停 0.14 秒（换行本身不念），
    像真模型那样在标点处自己停一下。后端按这些停顿对齐每句的时间。"""
    out, buf = b"", ""
    text = text.strip()
    for i, ch in enumerate(text):
        if ch != "\n":
            buf += ch
        last = i == len(text) - 1
        if ch in GAP and not (ch in "…" and not last and text[i + 1] in "…"):
            if buf:
                out += tone(0.2 * len(buf), f)
                buf = ""
            if not last:
                out += b"\0\0" * int(SR * GAP[ch])
    if buf:
        out += tone(0.2 * len(buf), f)
    return out


@app.get("/health")
def health():
    return {"ok": True, "cuda": True, "gpu": "假显卡", "loaded": st["kind"], "attn": "sdpa", "busy": LOCK.locked(), "error": "",
            "vram": {"alloc_gb": 4.2}, "models": {"custom": True, "design": True}, "align": not (RUN / "fake_tts_noalign.flag").exists(),
            "speakers": None, "stats": {"n": st["n"], "align_n": st["align_n"]}, "last_align": st["last_align"]}


TOK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]|[A-Za-z0-9']+")


def runs(pcm, sr):
    """有声音的一段一段（秒）：10 毫秒一格，连续 60 毫秒以上没声音就算断开。"""
    import numpy as np
    h = sr // 100
    a = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2")
    n = len(a) // h
    peak = np.abs(a[: n * h].astype(np.int32)).reshape(n, h).max(axis=1) if n else []
    out, cur, quiet = [], None, 0
    for k in range(n):
        loud = peak[k] > 300
        if loud:
            if cur is None:
                cur = [k, k + 1]
            cur[1], quiet = k + 1, 0
        elif cur is not None:
            quiet += 1
            if quiet >= 6:
                out.append((cur[0] / 100, cur[1] / 100))
                cur, quiet = None, 0
    if cur is not None:
        out.append((cur[0] / 100, cur[1] / 100))
    return out


@app.post("/align")
def align(body: dict = Body(...)):
    if (RUN / "fake_tts_noalign.flag").exists():
        raise HTTPException(404, "对齐模型还没下：models/tts/Qwen3-ForcedAligner-0.6B（设置 › 本地模型 点「接着装」）")
    sr = int(body.get("sr") or SR)
    pcm = base64.b64decode(body.get("pcm") or "")
    text = body.get("text") or ""
    if len(pcm) / 2 / sr > 180:
        raise HTTPException(400, "一次最多对齐 180 秒")
    with LOCK:
        st["align_n"] += 1
        rs = runs(pcm, sr)
        # 原文按标点、换行、空格以外的分隔切成一小段一小段：送来的字里标点已经换成空格了，所以用 raw（原文，只有假的对齐器看）
        raw = re.sub(r"\[[A-Za-z][A-Za-z ]{0,30}\]", "", body.get("raw") or text)
        phrases = [p for p in re.split(r"[，,、；;：:。！？!?…\n]+", raw) if TOK.search(p)]
        out = []
        if len(phrases) == len(rs):
            for (a, b), ph in zip(rs, phrases):
                toks = TOK.findall(ph)
                w = [len(t) for t in toks]
                acc = 0
                for t, k in zip(toks, w):
                    out.append({"t": t, "s": round(a + (b - a) * acc / sum(w), 3), "e": round(a + (b - a) * (acc + k) / sum(w), 3)})
                    acc += k
        else:                                          # 段数对不上：按字数平均分（不准，测试里看得出来）
            toks = TOK.findall(text)
            tot, acc, dur = sum(len(t) for t in toks) or 1, 0, len(pcm) / 2 / sr
            for t in toks:
                out.append({"t": t, "s": round(dur * acc / tot, 3), "e": round(dur * (acc + len(t)) / tot, 3)})
                acc += len(t)
        st["last_align"] = {"sec": round(len(pcm) / 2 / sr, 2), "runs": len(rs), "phrases": len(phrases), "items": len(out)}
        return {"items": out, "sec": 0.05}


@app.post("/generate")
def generate(body: dict = Body(...)):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "没有文字")
    if body.get("kind") == "design" and not body.get("instruct"):
        raise HTTPException(400, "描述音色要写一段音色描述")
    with LOCK:
        st["kind"] = body.get("kind")
        st["n"] += 1
        time.sleep(0.15 + min(3.0, 0.01 * len(text)))      # 长的一段念得久一点（测整段生成时点停下）
        b = io.BytesIO()
        with wave.open(b, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(SR)
            f.writeframes(speak(text, 220 + (int(body.get("seed") or 0) % 200)))
        return Response(content=b.getvalue(), media_type="audio/wav", headers={"X-Gen-Sec": "0.15", "X-Sr": str(SR)})


@app.post("/unload")
def unload():
    st["kind"] = None
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=A.port, log_level="warning")
