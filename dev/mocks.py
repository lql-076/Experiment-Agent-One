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


@ds.post("/chat/completions")
async def dsc(r: Request):
    j = await r.json()
    LAST["chat"] = j
    msgs = j["messages"]
    u = msgs[-1].get("content") or ""
    usage = {"prompt_tokens": 400, "prompt_cache_hit_tokens": 100, "prompt_cache_miss_tokens": 300, "completion_tokens": 120}
    # 带工具时模仿 DeepSeek：问"最新"的先搜，搜完读第一条，再回答
    if j.get("tools"):
        asked = next((m.get("content") or "" for m in reversed(msgs) if m.get("role") == "user"), "")
        think = (j.get("thinking") or {}).get("type") == "enabled"
        # 模仿官方：思考模式带工具时，之前带 tool_calls 的那条必须把 reasoning_content 原样传回，否则 400
        if think and ("坏历史" in asked or any(m.get("role") == "assistant" and m.get("tool_calls") and not m.get("reasoning_content") for m in msgs)):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": {"message": "reasoning_content must be passed back", "type": "invalid_request_error"}}, status_code=400)
        tools_used = [m for m in msgs if m.get("role") == "tool"]
        want = any(x in asked for x in ("最新", "最近", "价格", "新闻", "发布", "更新", "搜"))
        if want and not tools_used:
            call = {"id": "call_s1", "type": "function", "function": {"name": "web_search", "arguments": json.dumps({"query": asked[:30], "count": 5}, ensure_ascii=False)}}
            return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [call], **({"reasoning_content": "先搜一下"} if think else {})}}], "usage": usage}
        if want and len(tools_used) == 1:
            url = (__import__("re").search(r"https?://\S+", tools_used[0]["content"]) or [None])[0]
            call = {"id": "call_f1", "type": "function", "function": {"name": "web_fetch", "arguments": json.dumps({"url": url})}}
            return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [call], **({"reasoning_content": "再读一页"} if think else {})}}], "usage": usage}
        if tools_used:
            txt = f"（DeepSeek 联网）查到了：关于「{asked[:20]}」，最新版本是 1.2.3。"
            return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"role": "assistant", "content": txt}}], "usage": usage}
    if j.get("response_format"):
        if "可选修法" in u:
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
    apps += ((bl, 8097), (yi, 8096))
    for app, port in apps:
        threading.Thread(target=serve, args=(app, port), daemon=True).start()
    while True:
        time.sleep(60)
