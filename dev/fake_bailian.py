"""假的百炼语音合成接口（只在 Linux 沙箱里测试用；沙箱连不上百炼，真 Key 也永远不进沙箱）。dev/mocks.py 把它挂在 8097 端口。
POST /api/v1/services/audio/tts/SpeechSynthesizer：和百炼一样按 SSE 流式返回 sentence-begin / sentence-synthesis / sentence-end，
声音是 24kHz 16 位 PCM 的"嘟"（一个字 0.2 秒），逗号停 0.14 秒、句末停 0.3 秒；开了 word_timestamp_enabled 就给字级时间戳（从整段开始算）。
Key 只认 sk-test-0000。几个开关（dev/.run 里放文件）：
  fake_bl_nowords.flag  不给时间戳（测后端退回按停顿对齐）
  fake_bl_wordserr.flag 开时间戳就报参数错（测去掉时间戳再试一次）
  fake_bl_arrears.flag  欠费（400 Arrearage）
  fake_bl_slow.flag     每句慢一点（测停下）
文案超过 3000 字 → 400 InvalidParameter（文本太长）。
收到的每个请求（不含 Key，只记有没有带对）记下来，GET /_fake/log 看：测试用它检查只发了文案、没重试。"""
import base64
import json
import math
import re
import struct
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

RUN = Path(__file__).resolve().parent / ".run"
SR = 24000
KEY = "sk-test-0000"
TAG = re.compile(r"\[[A-Za-z][A-Za-z ]{0,30}\]")
app = FastAPI()
LOG = []


def flag(n):
    return (RUN / f"fake_bl_{n}.flag").exists()


def tone(sec, f=330):
    n = int(SR * sec)
    return b"".join(struct.pack("<h", int(7000 * math.sin(2 * math.pi * f * i / SR))) for i in range(n))


def sentences(text):
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in "。！？!?\n":
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def ev(i, o, usage):
    return f"id:{i}\nevent:result\n:HTTP_STATUS/200\ndata:" + json.dumps({"request_id": "fake-req", "output": o, "usage": usage}, ensure_ascii=False) + "\n\n"


@app.get("/_fake/log")
def fake_log():
    return {"n": len(LOG), "items": LOG[-20:]}


@app.post("/_fake/clear")
def fake_clear():
    LOG.clear()
    return {"ok": True}


@app.post("/api/v1/services/audio/tts/SpeechSynthesizer")
async def synth(req: Request):
    body = await req.json()
    auth = req.headers.get("authorization", "")
    LOG.append({"ts": time.time(), "body": body, "auth_ok": auth == f"Bearer {KEY}", "sse": req.headers.get("x-dashscope-sse"),
                "headers": sorted(h for h in req.headers.keys())})
    if auth != f"Bearer {KEY}":
        return JSONResponse({"request_id": "fake", "code": "InvalidApiKey", "message": "Invalid API-key provided."}, 401)
    if flag("arrears"):
        return JSONResponse({"request_id": "fake", "code": "Arrearage", "message": "Access denied, please make sure your account is in good standing."}, 400)
    inp = body.get("input") or {}
    text = inp.get("text") or ""
    if len(text) > 3000:
        return JSONResponse({"request_id": "fake", "code": "InvalidParameter", "message": "text length exceeds the limit"}, 400)
    if not str(inp.get("voice", "")).endswith("_v3.1"):
        return JSONResponse({"request_id": "fake", "code": "InvalidParameter", "message": "voice not supported"}, 400)
    words_on = bool(inp.get("word_timestamp_enabled"))
    if words_on and flag("wordserr"):
        return JSONResponse({"request_id": "fake", "code": "InvalidParameter", "message": "word_timestamp_enabled is not supported for this voice"}, 400)
    if inp.get("format") != "pcm":
        return JSONResponse({"request_id": "fake", "code": "InvalidParameter", "message": "this fake only does pcm"}, 400)
    bill = sum(2 if re.match(r"[一-鿿]", c) else 1 for c in re.sub(r"\s", "", text))
    sents = sentences(text)
    slow = flag("slow")
    nowords = flag("nowords")

    def gen():
        n, t_ms, done = 0, 0.0, 0
        for si, s in enumerate(sents):
            n += 1
            yield ev(n, {"finish_reason": "null", "type": "sentence-begin", "original_text": s, "sentence": {"index": si, "words": []},
                         "audio": {"data": "", "id": "a"}}, {"characters": done})
            audio, words = b"", []
            spoken = TAG.sub(lambda m: "\0" * len(m.group()), s)          # 标签不念（位置留着，下标和原文对得上）
            for k, ch in enumerate(spoken):
                if ch in "，,、；;：:":
                    audio += b"\0\0" * int(SR * 0.14)
                elif ch in "。！？!?…\n\0 ”“\"'" or ch.isspace():
                    continue
                else:
                    b0 = t_ms + len(audio) / 2 / SR * 1000
                    audio += tone(0.2)
                    words.append({"text": ch, "begin_index": k, "end_index": k + 1, "begin_time": round(b0), "end_time": round(b0 + 200)})
            if si < len(sents) - 1:
                audio += b"\0\0" * int(SR * 0.3)
            for a in range(0, len(audio), 9600):
                n += 1
                if slow:
                    time.sleep(0.25)
                yield ev(n, {"finish_reason": "null", "type": "sentence-synthesis", "sentence": {"index": si, "words": []},
                             "audio": {"data": base64.b64encode(audio[a:a + 9600]).decode(), "id": "a"}}, {"characters": done})
            t_ms += len(audio) / 2 / SR * 1000
            done += sum(2 if re.match(r"[一-鿿]", c) else 1 for c in re.sub(r"\s", "", s))
            n += 1
            yield ev(n, {"finish_reason": "null", "type": "sentence-end", "original_text": s,
                         "sentence": {"index": si, "words": [] if (nowords or not words_on) else words}, "audio": {"data": "", "id": "a"}},
                     {"characters": done})
        n += 1
        yield ev(n, {"finish_reason": "stop", "audio": {"data": "", "url": "", "id": "a", "expires_at": 0}}, {"characters": bill})

    return StreamingResponse(gen(), media_type="text/event-stream")
