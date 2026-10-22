"""测试用的假服务：模型服务、Kev、LHM、DeepSeek。只在沙箱里用。"""
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


@ds.post("/chat/completions")
async def dsc(r: Request):
    j = await r.json()
    u = j["messages"][-1]["content"]
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
    return n("Sensor", kids=[n("PC", kids=[cpu, disk, disk2])])


def serve(app, port):
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    import sys
    apps = ((k, 8091), (ds, 8099), (lhm, 8085)) if "--no-model" in sys.argv else ((m, 8090), (k, 8091), (ds, 8099), (lhm, 8085))
    for app, port in apps:
        threading.Thread(target=serve, args=(app, port), daemon=True).start()
    while True:
        time.sleep(60)
