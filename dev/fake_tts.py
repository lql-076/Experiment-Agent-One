"""假的配音服务（只在 Linux 沙箱里测试用）：接口和 app/tts_server.py 一样，但不装模型、不要显卡，
念出来的是一段"嘟——"，长短按字数算（一个字 0.2 秒），标点处自己停一下，方便检查拼接、停顿、时间轴对不对。
测试后端（dev/test_backend.py）把配音服务的启动命令换成这个，所以"用到才启动、闲置关掉、让路关掉"走的是真的那一套。
用法：python dev/fake_tts.py --port 8092"""
import argparse
import io
import math
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
st = {"kind": None, "n": 0}


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
            "vram": {"alloc_gb": 4.2}, "models": {"custom": True, "design": True}, "speakers": None, "stats": {"n": st["n"]}}


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
