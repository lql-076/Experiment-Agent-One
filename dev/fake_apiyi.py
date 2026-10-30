"""假的 API易 生图接口（只在 Linux 沙箱里测试用；沙箱连不上 API易，真 Key 也永远不进沙箱）。dev/mocks.py 把它挂在 8096 端口。
Key 只认 sk-test-0000。收到的请求记下来（不含 Key，只记有没有带对），GET /_fake/img/log 看。
- GET /v1/models：和 API易 一样回 {data:[{id, owned_by}]}，里面混着聊天模型（要被挑掉）和一个没收录的生图模型
- POST /v1/images/generations（JSON）
  VIP（*-vip）：size 只认那 30 档、不许带 n、要明着 response_format=b64_json（不然回链接）
  官转（gpt-image-2.5-flare / -sunburst / gpt-image-2 ……）：size 合规矩（16 的倍数、长边 ≤3840、≤3:1、0.65~8.3 百万像素），回 usage
  All（*-all）：不认 size / quality，回 1536×1024，b64 带 data: 前缀
  Seedream：size 写像素（总像素 1280×720 ~ 4096×4096），watermark 要 false；5.0 出 PNG，4.x 出 JPEG；参考图在 image 数组
  Flux：size 写像素（≤4MP、16 的倍数），参考图 input_image / input_image_2…；只回 data[0].url（这里的 /_fake/img/dl/…）
- POST /v1/images/edits（multipart）：带参考图（字段 image 或 image[]），其余同上
- POST /v1beta/models/{id}:generateContent（Nano Banana）：aspectRatio + imageSize，参考图在 inlineData；
  被拦 → 200 但没有图、finishReason=IMAGE_SAFETY
- 提示词里有「【拦截】」→ 审核没过；dev/.run 里放文件：fake_img_slow.flag（每张慢 1.5 秒，测停下；文件里写数字就慢那么多秒，看界面动画用）、fake_img_quota.flag（余额不够）、
  fake_img_opaque.flag（要透明也给不透明的，测提醒）"""
import asyncio
import base64
import email.parser
import email.policy
import re
import struct
import time
import zlib
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

RUN = Path(__file__).resolve().parent / ".run"
KEY = "sk-test-0000"
app = FastAPI()
LOG, DL = [], {}
VIP = {"1k": {(1280, 1280), (848, 1280), (1280, 848), (960, 1280), (1280, 960), (1024, 1280), (1280, 1024), (720, 1280), (1280, 720), (1280, 544)},
       "2k": {(2048, 2048), (1360, 2048), (2048, 1360), (1536, 2048), (2048, 1536), (1632, 2048), (2048, 1632), (1152, 2048), (2048, 1152), (2048, 864)},
       "4k": {(2880, 2880), (2336, 3520), (3520, 2336), (2480, 3312), (3312, 2480), (2560, 3216), (3216, 2560), (2160, 3840), (3840, 2160), (3840, 1632)}}
VIP_ALL = set().union(*VIP.values())
MODELS = ["gpt-image-2.5-sunburst-vip", "gpt-image-2.5-flare-vip", "gpt-image-2-vip", "gpt-image-2.5-all", "gpt-image-2.5-sunburst", "gpt-image-2.5-flare",
          "gpt-image-2", "gemini-3.1-flash-image", "gemini-3-pro-image-preview", "seedream-5-0-flash-260915", "seedream-4-5-251128", "flux-2-pro",
          "flux-2-klein-4b", "gpt-image-3-preview", "deepseek-v4-flash", "gpt-5.5", "claude-sonnet-5-5", "text-embedding-3-small", "tts-1"]


def flag(n):
    return (RUN / f"fake_img_{n}.flag").exists()


def png(w, h, rgba, seed):
    """像样一点的假图：两种颜色的渐变 + 一个亮圆（numpy + zlib 现做，不用 Pillow）。透明的：圆里面有颜色，外面透明。"""
    c1 = np.array([(seed * 53) % 200 + 40, (seed * 97) % 200 + 40, (seed * 31) % 200 + 40], dtype=np.float32)
    c2 = np.array([(seed * 17) % 160 + 20, (seed * 71) % 160 + 60, (seed * 13) % 200 + 50], dtype=np.float32)
    sw, sh = max(1, w // 8), max(1, h // 8)                   # 先在 1/8 大小上算，再放大（快）
    y, x = np.mgrid[0:sh, 0:sw].astype(np.float32)
    t = ((x / max(1, sw - 1)) * 0.6 + (y / max(1, sh - 1)) * 0.4)[..., None]
    img = c1 * (1 - t) + c2 * t
    cx, cy, r = sw * 0.5, sh * 0.48, min(sw, sh) * 0.32
    dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    glow = np.clip(1 - dist / r, 0, 1)[..., None]
    img = np.clip(img + glow * 120, 0, 255)
    small = img.astype(np.uint8)
    if rgba:
        a = (dist < r).astype(np.uint8) * 255
        small = np.concatenate([small, a[..., None]], axis=2)
    ch = small.shape[2]
    big = np.repeat(np.repeat(small, 8, axis=0), 8, axis=1)
    big = np.pad(big, ((0, max(0, h - big.shape[0])), (0, max(0, w - big.shape[1])), (0, 0)), mode="edge")[:h, :w]
    raw = np.concatenate([np.zeros((h, 1), dtype=np.uint8), big.reshape(h, w * ch)], axis=1).tobytes()

    def chunk(tp, d):
        return struct.pack(">I", len(d)) + tp + d + struct.pack(">I", zlib.crc32(tp + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6 if rgba else 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


def jpeg(w, h):
    """只有文件头的 JPEG（够后端读宽高、认格式；Seedream 4.x 只出 JPEG）。"""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, h, w, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def err(status, msg, code="invalid_request_error"):
    return JSONResponse({"error": {"message": msg, "type": code, "code": code}}, status)


def b64(b):
    return base64.b64encode(b).decode()


def seed_of(prompt):
    return sum(map(ord, prompt)) % 997


@app.get("/_fake/img/log")
def fake_log():
    return {"n": len(LOG), "items": LOG[-30:]}


@app.post("/_fake/img/clear")
def fake_clear():
    LOG.clear()
    return {"ok": True}


@app.get("/_fake/img/dl/{n}")
def fake_dl(n: str):
    b = DL.get(n)
    return Response(b, media_type="image/png") if b else Response(status_code=404)


@app.get("/v1/models")
def models(req: Request):
    if req.headers.get("authorization", "") != f"Bearer {KEY}":
        return err(401, "Invalid API key provided", "invalid_api_key")
    return {"object": "list", "data": [{"id": m, "object": "model", "created": 1760000000, "owned_by": "custom"} for m in MODELS]}


def _common(auth, prompt):
    if auth != f"Bearer {KEY}":
        return err(401, "Invalid API key provided", "invalid_api_key")
    if flag("quota"):
        return err(429, "You exceeded your current quota, please check your plan and billing details.", "insufficient_quota")
    if "【拦截】" in prompt:
        return err(403, "Your request was rejected as a result of our safety system.", "moderation_blocked")
    return None


async def _slow():
    if flag("slow"):
        try:
            sec = float((RUN / "fake_img_slow.flag").read_text().strip() or 1.5)
        except (OSError, ValueError):
            sec = 1.5
        await asyncio.sleep(sec)


def _wh(body):
    m = re.fullmatch(r"(\d+)x(\d+)", str(body.get("size") or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _openai(body, refs):
    model, prompt = body.get("model") or "", body.get("prompt") or ""
    seed = seed_of(prompt) + refs * 7
    trans = body.get("background") == "transparent"
    if model.endswith("-all"):
        if "size" in body or "quality" in body:
            return err(400, "this model does not support size / quality")
        return {"created": int(time.time()), "data": [{"b64_json": "data:image/png;base64," + b64(png(1536, 1024, False, seed))}]}
    wh = _wh(body)
    if not wh:
        return err(400, "size is required in this fake")
    w, h = wh
    if model.endswith("-vip"):
        if "n" in body:
            return err(400, "VIP 模型不支持 n 参数")
        if wh not in VIP_ALL:
            return err(400, f"VIP 模型只认 30 档尺寸，{w}x{h} 不在里面（这个假接口不替你改）")
        if body.get("quality") not in ("auto", "low", "medium", "high") + (("xhigh", "max") if "2.5" in model else ()):
            return err(400, f"Invalid value for quality: {body.get('quality')}")
        b = png(w, h, trans and not flag("opaque"), seed)
        if body.get("response_format") == "b64_json":
            return {"created": int(time.time()), "data": [{"b64_json": b64(b)}]}
        n = str(len(DL) + 1)
        DL[n] = b
        return {"created": int(time.time()), "data": [{"url": f"http://127.0.0.1:8096/_fake/img/dl/{n}"}]}
    if w % 16 or h % 16 or max(w, h) > 3840 or max(w, h) / min(w, h) > 3 or not (655360 <= w * h <= 8294400):
        return err(400, f"Invalid size '{w}x{h}': edges must be multiples of 16, max edge 3840, ratio <= 3:1, 0.65MP-8.3MP")
    q = body.get("quality") or "auto"                    # 没收录的模型不发画质：按 auto
    if q not in ("low", "medium", "high", "xhigh", "max", "auto"):
        return err(400, f"Invalid value for quality: {q}")
    if trans and body.get("output_format") == "jpeg":
        return err(400, "transparent background requires png or webp")
    b = png(w, h, trans and not flag("opaque"), seed)
    tok = {"low": 196, "medium": 439, "high": 1756, "xhigh": 3122, "max": 7024, "auto": 439}[q]
    out = round(tok * w * h / 1048576)
    return {"created": int(time.time()), "data": [{"b64_json": b64(b)}],
            "usage": {"input_tokens": len(prompt) // 2, "output_tokens": out, "total_tokens": len(prompt) // 2 + out,
                      "input_tokens_details": {"text_tokens": len(prompt) // 2, "image_tokens": 0}}}


def _seedream(body):
    wh = _wh(body)
    if not wh or not (1280 * 720 <= wh[0] * wh[1] <= 4096 * 4096):
        return err(400, f"size 不对：{body.get('size')}")
    if body.get("watermark") is not False:
        return err(400, "这个假接口要求明着写 watermark=false（不然真的会加水印）")
    if "5-0-pro" in body["model"] and "sequential_image_generation" in body:
        return err(400, "5.0 Pro 不认 sequential_image_generation")
    refs = body.get("image") or []
    if any(not str(u).startswith("data:image/") for u in refs):
        return err(400, "image 要 data URI")
    w, h = wh
    b = png(w, h, False, seed_of(body.get("prompt") or "") + len(refs)) if body["model"].startswith("seedream-5") else jpeg(w, h)
    return {"created": int(time.time()), "data": [{"b64_json": b64(b), "size": f"{w}x{h}"}], "usage": {"generated_images": 1}}


def _flux(body):
    wh = _wh(body)
    if not wh or wh[0] % 16 or wh[1] % 16 or wh[0] * wh[1] > 4_194_304:
        return err(400, f"size 不对：{body.get('size')}")
    n = str(len(DL) + 1)
    DL[n] = png(*wh, False, seed_of(body.get("prompt") or ""))
    return {"created": int(time.time()), "data": [{"url": f"http://127.0.0.1:8096/_fake/img/dl/{n}"}]}


@app.post("/v1/images/generations")
async def gen(req: Request):
    body = await req.json()
    auth = req.headers.get("authorization", "")
    refs = len(body.get("image") or []) + sum(1 for k in body if k.startswith("input_image"))
    LOG.append({"ts": time.time(), "path": "generations", "body": {k: ("<图>" if k == "image" or k.startswith("input_image") else v) for k, v in body.items()},
                "refs": refs, "auth_ok": auth == f"Bearer {KEY}", "headers": sorted(req.headers.keys())})
    e = _common(auth, body.get("prompt") or "")
    if e:
        return e
    await _slow()
    m = body.get("model") or ""
    if m.startswith("seedream"):
        return _seedream(body)
    if m.startswith("flux"):
        return _flux(body)
    return _openai(body, 0)


@app.post("/v1/images/edits")
async def edits(req: Request):
    raw = await req.body()
    ct = req.headers.get("content-type", "")
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(b"Content-Type: " + ct.encode() + b"\r\n\r\n" + raw)
    body, files = {}, []
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if part.get_filename():
            files.append({"field": name, "name": part.get_filename(), "type": part.get_content_type(), "n": len(part.get_payload(decode=True) or b"")})
        else:
            body[name] = (part.get_payload(decode=True) or b"").decode("utf-8").strip()       # httpx 发的文字字段是 UTF-8、不带 charset
    auth = req.headers.get("authorization", "")
    LOG.append({"ts": time.time(), "path": "edits", "body": body, "files": files, "refs": len(files), "auth_ok": auth == f"Bearer {KEY}",
                "multipart": ct.startswith("multipart/form-data")})
    e = _common(auth, body.get("prompt") or "")
    if e:
        return e
    if not files:
        return err(400, "edits 要至少一张 image")
    await _slow()
    return _openai(body, len(files))


@app.post("/v1beta/models/{spec}")
async def gemini(spec: str, req: Request):
    mid, _, act = spec.partition(":")
    body = await req.json()
    auth = req.headers.get("authorization", "")
    parts = ((body.get("contents") or [{}])[0].get("parts")) or []
    prompt = " ".join(p.get("text", "") for p in parts if "text" in p)
    refs = sum(1 for p in parts if "inlineData" in p)
    cfg = (body.get("generationConfig") or {}).get("imageConfig") or {}
    LOG.append({"ts": time.time(), "path": "gemini", "model": mid, "act": act, "prompt": prompt, "refs": refs, "cfg": cfg,
                "modalities": (body.get("generationConfig") or {}).get("responseModalities"), "auth_ok": auth == f"Bearer {KEY}"})
    if act != "generateContent":
        return err(404, "unknown action")
    if auth != f"Bearer {KEY}":
        return err(401, "API key not valid")
    await _slow()
    if "【拦截】" in prompt:
        return {"candidates": [{"content": {"parts": []}, "finishReason": "IMAGE_SAFETY"}]}
    try:
        a, b_ = (int(x) for x in str(cfg.get("aspectRatio") or "1:1").split(":"))
    except ValueError:
        return err(400, "aspectRatio 不对")
    L = {"512": 512, "1K": 1024, "2K": 2048, "4K": 4096}.get(str(cfg.get("imageSize") or "1K"))
    if not L:
        return err(400, "imageSize 只能是 512 / 1K / 2K / 4K")
    w, h = (L, round(L * b_ / a)) if a >= b_ else (round(L * a / b_), L)
    img = png(w, h, False, seed_of(prompt) + refs)
    return {"candidates": [{"content": {"parts": [{"text": "好的，这是图。"}, {"inlineData": {"mimeType": "image/png", "data": b64(img)}}]},
                            "finishReason": "STOP"}], "usageMetadata": {"candidatesTokenCount": 1290}}
