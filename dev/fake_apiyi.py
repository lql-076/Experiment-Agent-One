"""假的 API易 生图接口（只在 Linux 沙箱里测试用；沙箱连不上 API易，真 Key 也永远不进沙箱）。dev/mocks.py 把它挂在 8096 端口。
POST /v1/images/generations：和 API易（OpenAI 兼容）一样收 JSON、回 data[0].b64_json + usage。Key 只认 sk-test-0000。
- 官转模型（gpt-image-2.5-flare / -sunburst）：按 size 出一张纯色 PNG；background=transparent → 带透明通道（四周透明、中间一块颜色）；
  size 不合规矩（不是 16 的倍数、超过 3840、比例超过 3:1、像素太多太少）→ 400；transparent 配 jpeg → 400
- 官逆模型（gpt-image-2.5-all）：不认 size，回 1536×1024 的图，b64 带 data: 前缀（真的有时会带）
- 提示词里有「【拦截】」→ 403 审核没过；dev/.run 里放文件：fake_img_slow.flag（每张慢 1.5 秒，测停下）、fake_img_quota.flag（余额不够）、
  fake_img_opaque.flag（要透明也给不透明的，测提醒）
收到的请求记下来（不含 Key，只记有没有带对），GET /_fake/img/log 看。"""
import base64
import re
import struct
import time
import zlib
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

RUN = Path(__file__).resolve().parent / ".run"
KEY = "sk-test-0000"
app = FastAPI()
LOG = []


def flag(n):
    return (RUN / f"fake_img_{n}.flag").exists()


def png(w, h, rgba, seed):
    """纯色 PNG（numpy + zlib 现做，不用 Pillow）。透明的：四周透明，中间一块有颜色。"""
    c = [(seed * 53) % 200 + 40, (seed * 97) % 200 + 40, (seed * 31) % 200 + 40]
    ch = 4 if rgba else 3
    a = np.zeros((h, w, ch), dtype=np.uint8)
    a[:, :, :3] = c
    if rgba:
        a[h // 4: h * 3 // 4, w // 4: w * 3 // 4, 3] = 255
    raw = np.concatenate([np.zeros((h, 1), dtype=np.uint8), a.reshape(h, w * ch)], axis=1).tobytes()

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6 if rgba else 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def err(status, msg, code="invalid_request_error"):
    return JSONResponse({"error": {"message": msg, "type": code, "code": code}}, status)


@app.get("/_fake/img/log")
def fake_log():
    return {"n": len(LOG), "items": LOG[-30:]}


@app.post("/_fake/img/clear")
def fake_clear():
    LOG.clear()
    return {"ok": True}


@app.post("/v1/images/generations")
async def gen(req: Request):
    body = await req.json()
    auth = req.headers.get("authorization", "")
    LOG.append({"ts": time.time(), "body": body, "auth_ok": auth == f"Bearer {KEY}", "headers": sorted(req.headers.keys())})
    if auth != f"Bearer {KEY}":
        return err(401, "Invalid API key provided", "invalid_api_key")
    if flag("quota"):
        return err(429, "You exceeded your current quota, please check your plan and billing details.", "insufficient_quota")
    prompt, model = body.get("prompt") or "", body.get("model") or ""
    if "【拦截】" in prompt:
        return err(403, "Your request was rejected as a result of our safety system.", "moderation_blocked")
    if flag("slow"):
        time.sleep(1.5)
    seed = sum(map(ord, prompt)) % 997
    if model.endswith("-all"):
        if "size" in body or "quality" in body:
            return err(400, "this model does not support size / quality")
        b = png(1536, 1024, False, seed)
        return {"created": int(time.time()), "data": [{"b64_json": "data:image/png;base64," + base64.b64encode(b).decode()}]}
    m = re.fullmatch(r"(\d+)x(\d+)", str(body.get("size") or ""))
    if not m:
        return err(400, "size is required in this fake")
    w, h = int(m.group(1)), int(m.group(2))
    if w % 16 or h % 16 or max(w, h) > 3840 or max(w, h) / min(w, h) > 3 or not (655360 <= w * h <= 8294400):
        return err(400, f"Invalid size '{w}x{h}': edges must be multiples of 16, max edge 3840, ratio <= 3:1, 0.65MP-8.3MP")
    if body.get("quality") not in ("low", "medium", "high", "xhigh", "max", "auto"):
        return err(400, f"Invalid value for quality: {body.get('quality')}")
    trans = body.get("background") == "transparent"
    if trans and body.get("output_format") == "jpeg":
        return err(400, "transparent background requires png or webp")
    b = png(w, h, trans and not flag("opaque"), seed)
    tok = {"low": 196, "medium": 439, "high": 1756, "xhigh": 3122, "max": 7024, "auto": 439}[body["quality"]]
    out = round(tok * w * h / 1048576)
    return {"created": int(time.time()), "data": [{"b64_json": base64.b64encode(b).decode()}],
            "usage": {"input_tokens": len(prompt) // 2, "output_tokens": out, "total_tokens": len(prompt) // 2 + out,
                      "input_tokens_details": {"text_tokens": len(prompt) // 2, "image_tokens": 0}}}
