"""测试用的假服务：模型服务、Kev、LHM、DeepSeek、百炼语音合成（dev/fake_bailian.py，8097）、API易 生图（dev/fake_apiyi.py，8096）。只在沙箱里用。"""
import hashlib
import json
import math
import random
import threading
import time

import uvicorn
from fastapi import FastAPI, Request

DIM = 256


def vec(t):
    v = [0.0] * DIM
    t = t.split("Query:")[-1]
    grams = [t[i:i + 2] for i in range(len(t) - 1)] + list(t)
    for g in grams:
        h = int(hashlib.md5(g.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1
    return [x / n for x in v]


m = FastAPI()
st = {"base": False}


@m.get("/health")
def health():
    return {"ok": True, "cuda": True, "gpu": "NVIDIA GeForce RTX 5060 Ti", "embed_loaded": True, "base_loaded": st["base"],
            "loras": [], "vram": {"alloc_gb": 1.3 + (2 if st["base"] else 0), "free_gb": 12}, "error": "", "quant": "4bit"}


@m.post("/embed")
async def embed(r: Request):
    j = await r.json()
    return {"vectors": [vec(t) for t in j["texts"]], "dim": DIM}


@m.post("/chat")
async def chat(r: Request):
    j = await r.json()
    st["base"] = True
    u = j["messages"][-1]["content"]
    return {"text": f"（本地小脑）收到：{u[:30]}", "tokens": 18, "seconds": 0.4, "tok_per_s": 45}


@m.post("/unload")
async def unload(r: Request):
    st["base"] = False
    return health()


@m.post("/load")
async def load(r: Request):
    st["base"] = True
    return health()


k = FastAPI()


@k.get("/v1/models")
def models():
    return {"data": [{"id": "kev-latest"}]}


@k.post("/v1/systemone")
async def so(r: Request):
    j = await r.json()
    s = j["state"]
    ans = {}
    for qid, q in j["questions"].items():
        if q["type"] == "choice":
            keys = list(q["criteria"])
            w = {kk: random.random() * 0.3 for kk in keys}
            if any(x in s for x in ("提醒", "记", "药", "早", "晚")):
                w["local"] = 1.2
            elif any(x in s for x in ("架构", "规划", "系统", "设计")):
                w["cl"] = 1.0
            else:
                w["ds"] = 1.0
            t = sum(w.values())
            p = {kk: v / t for kk, v in w.items()}
            ans[qid] = {"type": "choice", "choice": max(p, key=p.get), "confidence": 0.5, "probabilities": p}
        else:
            ans[qid] = {"type": "noul", "noul": 0.8 if any(x in s for x in ("药", "累", "疼", "睡")) else 0.1}
    return {"model": "kev-latest", "answers": ans, "usage": {}, "latency_ms": 30}


ds = FastAPI()


SEARCHES = []
LAST = {}


@ds.get("/__last")
def ds_last():
    """测试用：最近一次对话请求（看系统提示词里带了什么）和搜过的词。"""
    return {"chat": LAST.get("chat"), "searches": SEARCHES[-10:]}


def _txt(c):
    """content 可能是字符串，也可能是列表（带图片时）。"""
    if isinstance(c, list):
        return " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return c or ""


@ds.post("/chat/completions")
async def dsc(r: Request):
    j = await r.json()
    LAST["chat"] = j
    msgs = j["messages"]
    u = _txt(msgs[-1].get("content"))
    usage = {"prompt_tokens": 400, "prompt_cache_hit_tokens": 100, "prompt_cache_miss_tokens": 300, "completion_tokens": 120}
    pics = [x for m in msgs if isinstance(m.get("content"), list) for x in m["content"] if isinstance(x, dict) and x.get("type") == "image_url"]
    LAST["images"] = len(pics)
    names = {(t.get("function") or {}).get("name") for t in j.get("tools") or []}
    ask0 = next((_txt(m.get("content")) for m in reversed(msgs) if m.get("role") == "user" and not _txt(m.get("content")).startswith(("（read_file", "（程序提示", "（他中途"))), "")
    tmsgs = [m for m in msgs if m.get("role") == "tool"]
    # v2.2：「【拒工具】」带图片又带工具就 400（模仿带图片 + 工具被拒）；「【DSML】」把工具调用写成文字；「【截断】」第一次回复被截断
    if "【拒工具】" in ask0 and pics and j.get("tools"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": {"message": "image input does not support tools", "type": "invalid_request_error"}}, status_code=400)
    if "【DSML】" in ask0 and "write_file" in names and not tmsgs:
        D = "｜DSML｜"
        txt = (f"好的，我来写。\n<{D}function_calls>\n<{D}invoke name=\"write_file\">\n<{D}parameter name=\"path\" string=\"true\">dsml测试/a.txt</{D}parameter>\n"
               f"<{D}parameter name=\"content\" string=\"true\">你好 DSML</{D}parameter>\n<{D}parameter name=\"append\" string=\"false\">false</{D}parameter>\n</{D}invoke>\n</{D}function_calls>")
        return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": txt}, "finish_reason": "stop"}], "usage": usage}
    if "【截断】" in ask0 and "write_file" in names and not tmsgs:
        hinted = any(m.get("role") == "user" and _txt(m.get("content")).startswith("（程序提示") for m in msgs)
        if not hinted:
            D = "｜DSML｜"
            txt = f"<{D}function_calls>\n<{D}invoke name=\"write_file\">\n<{D}parameter name=\"path\" string=\"true\">截断/a.html</{D}parameter>\n<{D}parameter name=\"content\" string=\"true\"><html>很长很长"
            return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": txt}, "finish_reason": "length"}], "usage": usage}
        call = {"id": "call_t1", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "截断/a.html", "content": "<html>第一段"}, ensure_ascii=False)}}
        return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [call]}, "finish_reason": "tool_calls"}], "usage": usage}
    if ("【DSML】" in ask0 or "【截断】" in ask0) and tmsgs:
        return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": "（DeepSeek 工作区）做完了：" + tmsgs[-1]["content"][:200]}}], "usage": usage}
    # 模仿 DeepSeek 翻文件：「【查笔记】词」先 find_files 再 read_file 第一个；「【读文件】路径」直接 read_file
    if "read_file" in names and ("【查笔记】" in ask0 or "【读文件】" in ask0) and not (tmsgs and tmsgs[-1]["content"].startswith(("文件：", "图片 ", "没读成"))):
        if "【读文件】" in ask0:
            call = {"name": "read_file", "arguments": {"path": ask0.split("【读文件】", 1)[1].split()[0]}}
        elif not tmsgs:
            call = {"name": "find_files", "arguments": {"query": ask0.split("【查笔记】", 1)[1].split()[0]}}
        else:
            m_ = __import__("re").search(r"^(\S.*?\.(?:md|txt|docx|png))$", tmsgs[-1]["content"], __import__("re").M)
            call = {"name": "read_file", "arguments": {"path": m_.group(1) if m_ else "/没有"}}
        call = {"id": f"call_{len(tmsgs)}", "type": "function", "function": {"name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)}}
        return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [call]}}], "usage": usage}
    # 模仿 DeepSeek 在工作文件夹里干活（v2.1）：「【工作区】」后面跟一串要调的工具（JSON 列表），一轮调一个，调完把最后一个工具的结果说出来
    if "【工作区】" in ask0 and "write_file" in names:
        tail = ask0.split("【工作区】", 1)[1]
        plan, _ = json.JSONDecoder().raw_decode(tail[tail.index("["):])
        k = len(tmsgs)
        if k < len(plan):
            call = {"id": f"call_w{k}", "type": "function", "function": {"name": plan[k]["name"], "arguments": json.dumps(plan[k]["arguments"], ensure_ascii=False)}}
            return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [call]}}], "usage": usage}
        return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": "（DeepSeek 工作区）做完了：" + (tmsgs[-1]["content"][:300] if tmsgs else "")}}], "usage": usage}
    if pics:
        return {"model": j.get("model"), "choices": [{"message": {"role": "assistant", "content": f"（DeepSeek 看图 · {j.get('model')}）看到了 {len(pics)} 张图。"}}], "usage": usage}
    if tmsgs and tmsgs[-1]["content"].startswith(("文件：", "没读成")):
        body = tmsgs[-1]["content"].split("\n\n", 1)[-1]
        return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": "（DeepSeek 读文件）读到了：" + body[:40]}}], "usage": usage}
    # 带工具时模仿 DeepSeek：问"最新"的先搜，搜完读第一条，再回答
    if j.get("tools"):
        asked = next((m.get("content") or "" for m in reversed(msgs) if m.get("role") == "user"), "")
        think = (j.get("thinking") or {}).get("type") == "enabled"
        # 模仿官方：思考模式带工具时，之前带 tool_calls 的那条必须把 reasoning_content 原样传回，否则 400
        if think and ("坏历史" in asked or any(m.get("role") == "assistant" and m.get("tool_calls") and not m.get("reasoning_content") for m in msgs)):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": {"message": "reasoning_content must be passed back", "type": "invalid_request_error"}}, status_code=400)
        asked = _txt(asked) if not isinstance(asked, str) else asked
        tools_used = [m for m in msgs if m.get("role") == "tool"]
        want = any(x in asked for x in ("最新", "最近", "价格", "新闻", "发布", "更新", "搜"))
        if want and not tools_used and "web_search" in names:          # 只调给了它的工具（v2.1：带着工作区工具时，联网搜索可能没给）
            call = {"id": "call_s1", "type": "function", "function": {"name": "web_search", "arguments": json.dumps({"query": asked[:30], "count": 5}, ensure_ascii=False)}}
            return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [call], **({"reasoning_content": "先搜一下"} if think else {})}}], "usage": usage}
        if want and len(tools_used) == 1 and "web_fetch" in names:
            url = (__import__("re").search(r"https?://\S+", tools_used[0]["content"]) or [None])[0]
            call = {"id": "call_f1", "type": "function", "function": {"name": "web_fetch", "arguments": json.dumps({"url": url})}}
            return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [call], **({"reasoning_content": "再读一页"} if think else {})}}], "usage": usage}
        if tools_used:
            txt = f"（DeepSeek 联网）查到了：关于「{asked[:20]}」，最新版本是 1.2.3。"
            return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": txt}}], "usage": usage}
    if j.get("response_format"):
        sys0 = _txt(msgs[0].get("content")) if msgs and msgs[0].get("role") == "system" else ""
        if "清单整理员" in sys0:                   # v3.3 批量清单：测试把想要的回答写在清单里「【JSON】」后面（去掉行号）
            m = __import__("re").search(r"【JSON】(.+)", u)
            txt = m.group(1).strip() if m else json.dumps({"items": []})
            if "【坏JSON】" in u:
                txt = "{不是 json"
        elif "可选修法" in u:
            txt = json.dumps({"why": "要管理员权限" if "硬件监控" in u else "看着是网络超时", "fix": "manual" if "硬件监控" in u else "retry",
                              "tell": "在弹出的窗口里点「是」" if "硬件监控" in u else ""}, ensure_ascii=False)
        elif "labels" in u or "分流器" in u:
            ids = [int(x) for x in __import__("re").findall(r'"id": (\d+)', u)]
            txt = json.dumps({"labels": [{"id": i, "label": "ds"} for i in ids]})
        else:
            txt = json.dumps({"items": ["变体一", "变体二"]})
    else:
        txt = f"（DeepSeek）关于「{u[:24]}」的回答。"
    return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"content": txt}}],
            "usage": {"prompt_tokens": 400, "prompt_cache_hit_tokens": 100, "prompt_cache_miss_tokens": 300, "completion_tokens": 120}}


@ds.post("/v1/tools/search")
async def ds_search(r: Request):
    j = await r.json()
    SEARCHES.append(j)
    q = j.get("query", "")
    if "没结果" in q:
        return {"results": []}
    n = min(int(j.get("count") or 10), 5)
    return {"results": [{"rerank_score": 2.1 - i * 0.2, "title": f"{q[:12]} · 结果 {i + 1}", "url": f"https://example.com/news/{i + 1}",
                         "snippet": "短摘要", "summary": f"这是关于「{q[:20]}」的第 {i + 1} 条结果的长摘要。", "content": "",
                         "site_name": "示例网站", "site_icon": "", "date": "2026-10-20T08:00:00Z", "authority": 3} for i in range(n)]}


@ds.post("/v1/tools/fetch")
async def ds_fetch(r: Request):
    j = await r.json()
    if "blocked" in j.get("url", ""):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": {"message": "no content", "type": "not_found"}}, status_code=404)
    return {"title": "示例网页", "content": "# 示例网页\n\n最新版本是 1.2.3，发布于 2026-10-20。"}


@ds.get("/models")
def ds_models():
    return {"object": "list", "data": [{"id": "deepseek-chat", "object": "model", "owned_by": "deepseek"}, {"id": "deepseek-reasoner", "object": "model", "owned_by": "deepseek"}]}


@ds.get("/user/balance")
def bal():
    return {"is_available": True, "balance_infos": [{"currency": "CNY", "total_balance": "9.58"}]}


# ---------- 假的 QQ 开放平台（v2.3，挂在 8099 的 /qq 下面）：附件下载、富媒体上传、发消息 ----------
QQ = {"files": [], "msgs": []}
PNG1 = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc0000003010100c9fe92ef0000000049454e44ae426082")


@ds.get("/qq/att/{name}")
def qq_att(name: str):
    from fastapi.responses import Response
    if name == "404":
        return Response(status_code=404)
    return Response(PNG1 if name.endswith(".png") else ("QQ 发来的文件：" + name).encode("utf-8"),
                    media_type="image/png" if name.endswith(".png") else "application/octet-stream")


@ds.post("/qq/v2/users/{oid}/files")
async def qq_files(oid: str, r: Request):
    j = await r.json()
    QQ["files"].append({"oid": oid, "file_type": j.get("file_type"), "n": len(j.get("file_data") or ""), "srv_send_msg": j.get("srv_send_msg")})
    return {"file_uuid": "U1", "file_info": f"FI_{len(QQ['files'])}", "ttl": 3600}


@ds.post("/qq/v2/users/{oid}/messages")
async def qq_msgs(oid: str, r: Request):
    j = await r.json()
    QQ["msgs"].append(dict(j, oid=oid))
    return {"id": "m1", "timestamp": 1}


@ds.get("/__qq")
def qq_seen():
    return QQ


# ---------- 假的 ACE-Step 1.5 接口（v3.0，8001）：交任务 → 问结果 → 下音频 ----------
ace = FastAPI()
ACE = {"tasks": {}, "last": None}


def _wav(sec, sr=16000, f=330):
    import struct
    n = int(sec * sr)
    pcm = b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * f * i / sr))) for i in range(n))
    return b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16) + b"data" + struct.pack("<I", len(pcm)) + pcm


def _env(d):
    return {"data": d, "code": 200, "error": None, "timestamp": int(time.time() * 1000), "extra": None}


@ace.get("/files/{name}")
def ace_files(name: str):
    """一键装测试用的「下载站」（v3.1）：dev/.run/mockfiles 里的文件，支持分段下载（Range）。"""
    from pathlib import Path
    from fastapi.responses import FileResponse, JSONResponse
    p = Path(__file__).resolve().parent / ".run" / "mockfiles" / name
    if not p.is_file():
        return JSONResponse({"detail": "没有"}, status_code=404)
    return FileResponse(p)


@ace.get("/health")
def ace_health():
    return _env({"status": "ok", "service": "ACE-Step API", "version": "1.0"})


@ace.post("/release_task")
async def ace_release(r: Request):
    j = await r.json()
    ACE["last"] = j
    tid = f"T{len(ACE['tasks']) + 1}"
    ACE["tasks"][tid] = {"t0": time.time(), "body": j}
    return _env({"task_id": tid, "status": "queued", "queue_position": 1})


@ace.post("/query_result")
async def ace_query(r: Request):
    j = await r.json()
    out = []
    for tid in j.get("task_id_list") or []:
        t = ACE["tasks"].get(tid)
        if not t:
            out.append({"task_id": tid, "result": "[]", "status": 0})
        elif "【失败】" in (t["body"].get("prompt") or ""):
            out.append({"task_id": tid, "result": "[]", "status": 2})
        elif time.time() - t["t0"] < (6 if "【慢】" in (t["body"].get("prompt") or "") else 1.0):
            out.append({"task_id": tid, "result": "[]", "status": 0})
        else:
            sec = float(t["body"].get("audio_duration") or 10)
            res = [{"file": f"/v1/audio?path=%2Ftmp%2F{tid}_{int(min(sec, 20))}.wav", "status": 1, "metas": {"bpm": 120, "duration": sec}, "dit_model": "acestep-v15-turbo"}]
            out.append({"task_id": tid, "result": json.dumps(res), "status": 1})
    return _env(out)


@ace.get("/v1/audio")
def ace_audio(path: str):
    from fastapi.responses import Response
    sec = int(path.rsplit("_", 1)[-1].split(".")[0] or 5)
    return Response(_wav(sec), media_type="audio/wav")


@ace.get("/__last")
def ace_last():
    return {"last": ACE["last"], "n": len(ACE["tasks"])}


# ---------- 假的 Breeze TTS 2 接口（v3.0，8093）：表单进来，24 kHz 单声道 16 位 PCM 一块一块出去 ----------
brz = FastAPI()
BRZ = {"last": None, "n": 0}


@brz.get("/v1/model")
def brz_model():
    return {"model": "breeze-tts-2", "sample_rate": 24000, "max_batch": 128}


@brz.post("/v1/audio/speech")
async def brz_speech(r: Request):
    from fastapi.responses import JSONResponse, StreamingResponse
    raw = await r.body()
    txt = raw.decode("utf-8", "replace")
    form = {k: v[0] for k, v in __import__("urllib.parse").parse.parse_qs(txt).items()} if "urlencoded" in r.headers.get("content-type", "") else None

    def field(k):                                          # 真的服务两种表单都收：没带参考音频的时候 httpx 发的是 urlencoded
        if form is not None:
            return form.get(k)
        m_ = __import__("re").search(r'name="' + k + r'"\r\n\r\n(.*?)\r\n--', txt, __import__("re").S)
        return m_.group(1) if m_ else None
    BRZ["n"] += 1
    BRZ["last"] = {k: field(k) for k in ("text", "instruction", "cfg_scale", "seed", "ref_text")} | {"ref_audio": 'name="ref_audio"' in txt}
    if "【忙】" in (BRZ["last"]["text"] or "") and BRZ["n"] % 2:
        return JSONResponse({"detail": "busy"}, status_code=409)
    sec = max(0.4, min(6.0, len(BRZ["last"]["text"] or "") * 0.08))
    pcm = _wav(sec, 24000, 440)[44:]

    async def gen():
        for i in range(0, len(pcm), 4801):                 # 故意用奇数的块：看接的那头会不会把一个采样切成两半
            yield pcm[i:i + 4801]
    return StreamingResponse(gen(), media_type="audio/L16")


@brz.get("/__last")
def brz_last():
    return BRZ


lhm = FastAPI()


@lhm.get("/data.json")
def data():
    def n(t, img="", kids=None, value=""):
        return {"Text": t, "ImageURL": img, "Value": value, "Children": kids or []}
    cpu = n("AMD Ryzen 5 5600", "images_icon/cpu.png", [
        n("Load", kids=[n("CPU Total", value=f"{random.uniform(5, 30):.1f} %")]),
        n("Temperatures", kids=[n("Core (Tctl/Tdie)", value=f"{random.uniform(42, 60):.1f} °C")]),
        n("Clocks", kids=[n(f"Core #{i}", value=f"{random.uniform(3600, 4400):.0f} MHz") for i in range(1, 7)]),
        n("Powers", kids=[n("Package", value=f"{random.uniform(25, 60):.1f} W")])])
    disk = n("Samsung 980 1TB", "images_icon/hdd.png", [n("Temperatures", kids=[n("Temperature", value="41.0 °C")])])
    disk2 = n("ST2000DM008", "images_icon/hdd.png", [n("Temperatures", kids=[n("Temperature", value="34.0 °C")])])
    disk3 = n("Lexar SSD NM710 500GB", "images_icon/hdd.png", [n("Temperatures", kids=[n("Temperature", value="47.0 °C")])])
    disk4 = n("WDC WD1003BYX-01Y7B1", "images_icon/hdd.png", [n("Temperatures", kids=[n("Temperature", value="36.0 °C")])])
    return n("Sensor", kids=[n("PC", kids=[cpu, disk, disk2, disk3, disk4])])     # 4 块盘：查"有几块列几块"


def serve(app, port):
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    import sys
    from fake_apiyi import app as yi
    from fake_bailian import app as bl
    apps = ((k, 8091), (ds, 8099), (lhm, 8085)) if "--no-model" in sys.argv else ((m, 8090), (k, 8091), (ds, 8099), (lhm, 8085))
    apps += ((bl, 8097), (yi, 8096), (ace, 8001), (brz, 8093))
    for app, port in apps:
        threading.Thread(target=serve, args=(app, port), daemon=True).start()
    while True:
        time.sleep(60)
