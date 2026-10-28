"""本地模型服务：在 ai-env 里运行（不是主后端的环境）。主后端会自动启动和关闭它。

只用显卡：检测不到 CUDA 就拒绝工作，不会偷偷跑在 CPU 上。
- 嵌入模型（Qwen3-Embedding-0.6B）：语义路由、记忆检索。常驻，约 1.2GB 显存。
- 底座（MiniCPM5-2B）+ 小脑 LoRA：用到才加载，闲置一段时间自动卸载。默认 4bit 量化，约 2GB。
小脑 = models/brains 下的一个子文件夹（PEFT 格式，有 adapter_config.json）。

手动运行（一般不需要）：
  ai-env\\Scripts\\python.exe app\\model_server.py --port 8090 --embed <路径> --base <路径> --loras <路径>
"""
import argparse
import contextlib
import gc
import os
import re
import threading
import time
from pathlib import Path

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8090)
ap.add_argument("--embed", default="")
ap.add_argument("--base", default="")
ap.add_argument("--loras", default="")
ap.add_argument("--quant", default="4bit", choices=["4bit", "8bit", "bf16"])
ap.add_argument("--idle", type=float, default=15.0, help="底座闲置多少分钟后卸载")
ap.add_argument("--no-embed-preload", action="store_true")
A = ap.parse_args()

DEVICE = os.environ.get("AGENT_TEST_DEVICE") or "cuda"   # 只给开发测试用；正常运行永远是 cuda
CUDA = torch.cuda.is_available() or DEVICE == "cpu"
GPU = torch.cuda.get_device_name(0) if torch.cuda.is_available() else ("测试用 CPU" if DEVICE == "cpu" else "")
IMPORT_LOCK = threading.Lock()   # 刚启动时后台在加载嵌入模型，同时来一个请求，两个线程一起第一次导入 transformers 会报 ImportError
ELOCK = threading.RLock()   # 嵌入模型
BLOCK = threading.RLock()   # 底座 + 小脑（两把锁互不阻塞）
EMBED_INSTRUCT = "Given a user message to a personal assistant, retrieve messages that should be handled the same way"

app = FastAPI(title="agent-models")
state = {"embed": None, "etok": None, "base": None, "btok": None, "loras": [], "peft": False,
         "last_base": 0.0, "base_loading": False, "error": "", "load_s": {}}


def need_cuda():
    if not CUDA:
        raise HTTPException(503, "没检测到可用的显卡（CUDA）。按约定只用显卡，不在 CPU 上跑。")


def vram():
    if not torch.cuda.is_available():
        return {}
    free, total = torch.cuda.mem_get_info()
    return {"alloc_gb": round(torch.cuda.memory_allocated() / 2**30, 2), "reserved_gb": round(torch.cuda.memory_reserved() / 2**30, 2),
            "free_gb": round(free / 2**30, 2),
            "total_gb": round(total / 2**30, 2)}


# ---------------- 嵌入 ----------------
def load_embed():
    with IMPORT_LOCK:
        from transformers import AutoModel, AutoTokenizer
    with ELOCK:
        if state["embed"] is not None:
            return
        if not A.embed or not Path(A.embed, "config.json").exists():
            raise HTTPException(503, f"嵌入模型文件不在：{A.embed}")
        t0 = time.time()
        tok = AutoTokenizer.from_pretrained(A.embed, padding_side="left")
        m = AutoModel.from_pretrained(A.embed, dtype=torch.float16 if DEVICE == "cuda" else torch.float32).to(DEVICE).eval()
        state.update(embed=m, etok=tok)
        state["load_s"]["embed"] = round(time.time() - t0, 1)


def last_token_pool(h, mask):
    if bool((mask[:, -1].sum() == mask.shape[0]).item()):
        return h[:, -1]
    idx = mask.sum(dim=1) - 1
    return h[torch.arange(h.shape[0], device=h.device), idx]


class EmbedReq(BaseModel):
    texts: list[str]
    instruct: bool | str = True   # True = 路由用的说明；字符串 = 自定义说明；False = 当文档编码
    max_length: int = 512


@app.post("/embed")
def embed(r: EmbedReq):
    need_cuda()
    load_embed()
    ins = EMBED_INSTRUCT if r.instruct is True else (r.instruct or "")
    texts = [f"Instruct: {ins}\nQuery:{t}" if ins else t for t in r.texts]
    out = []
    with ELOCK, torch.inference_mode():
        for i in range(0, len(texts), 16):
            b = state["etok"](texts[i:i + 16], padding=True, truncation=True, max_length=r.max_length, return_tensors="pt").to(DEVICE)
            h = state["embed"](**b).last_hidden_state
            e = torch.nn.functional.normalize(last_token_pool(h, b["attention_mask"]).float(), p=2, dim=1)
            out.extend(e.cpu().tolist())
    return {"vectors": out, "dim": len(out[0]) if out else 0}


# ---------------- 底座 + 小脑 ----------------
def scan_loras():
    root = Path(A.loras) if A.loras else None
    if not root or not root.exists():
        return []
    return sorted(p for p in root.iterdir() if (p / "adapter_config.json").exists())


def load_base():
    with IMPORT_LOCK:
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    with BLOCK:
        if state["base"] is not None:
            return
        if not A.base or not Path(A.base, "config.json").exists():
            raise HTTPException(503, f"底座模型文件不在：{A.base}")
        state["base_loading"] = True
        try:
            t0 = time.time()
            kw = {"dtype": torch.bfloat16, "device_map": {"": 0 if DEVICE == "cuda" else "cpu"}}
            if DEVICE != "cuda":
                kw["dtype"] = torch.float32
            elif A.quant == "4bit":
                kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                               bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
            elif A.quant == "8bit":
                kw["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
            tok = AutoTokenizer.from_pretrained(A.base)
            m = AutoModelForCausalLM.from_pretrained(A.base, **kw).eval()
            loras = scan_loras()
            if loras:
                with IMPORT_LOCK:
                    from peft import PeftModel
                m = PeftModel.from_pretrained(m, str(loras[0]), adapter_name=loras[0].name)
                for p in loras[1:]:
                    m.load_adapter(str(p), adapter_name=p.name)
                state["peft"] = True
            state.update(base=m, btok=tok, loras=[p.name for p in loras], last_base=time.time())
            state["load_s"]["base"] = round(time.time() - t0, 1)
        finally:
            state["base_loading"] = False


def unload_base():
    with BLOCK:
        if state["base"] is None:
            return False
        state.update(base=None, btok=None, peft=False, loras=[])
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return True


class ChatReq(BaseModel):
    messages: list[dict]
    lora: str | None = None
    max_new_tokens: int = 512
    temperature: float = 0.7
    thinking: bool = False


THINK = re.compile(r"<think>.*?</think>", re.S)


@app.post("/chat")
def chat(r: ChatReq):
    need_cuda()
    load_base()
    with BLOCK, torch.inference_mode():
        m, tok = state["base"], state["btok"]
        state["last_base"] = time.time()
        prompt = tok.apply_chat_template(r.messages, tokenize=False, add_generation_prompt=True, enable_thinking=r.thinking)
        ids = tok(prompt, return_tensors="pt").to(DEVICE)
        if state["peft"]:
            if r.lora and r.lora in state["loras"]:
                m.set_adapter(r.lora)
                ctx = contextlib.nullcontext()
            else:
                ctx = m.disable_adapter()
        else:
            ctx = contextlib.nullcontext()
        t0 = time.time()
        gen = {"max_new_tokens": r.max_new_tokens, "repetition_penalty": 1.05}
        if r.temperature > 0:
            gen.update(do_sample=True, temperature=r.temperature, top_p=0.95, min_p=0.0)
        else:
            gen.update(do_sample=False)
        with ctx:
            out = m.generate(**ids, **gen, pad_token_id=tok.pad_token_id or tok.eos_token_id)
        new = out[0][ids["input_ids"].shape[-1]:]
        text = THINK.sub("", tok.decode(new, skip_special_tokens=True)).strip()
        state["last_base"] = time.time()
        dt = time.time() - t0
        return {"text": text, "tokens": int(new.shape[-1]), "seconds": round(dt, 2),
                "tok_per_s": round(new.shape[-1] / dt, 1) if dt else 0}


class NameReq(BaseModel):
    what: str


@app.post("/load")
def load(r: NameReq):
    need_cuda()
    (load_embed if r.what == "embed" else load_base)()
    return health()


@app.post("/unload")
def unload(r: NameReq):
    if r.what == "base":
        unload_base()
    elif r.what == "embed":
        with ELOCK:
            state.update(embed=None, etok=None)
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    return health()


@app.get("/health")
def health():
    return {"ok": CUDA, "cuda": CUDA, "gpu": GPU, "torch": torch.__version__, "cuda_version": torch.version.cuda,
            "embed_loaded": state["embed"] is not None, "base_loaded": state["base"] is not None,
            "base_loading": state["base_loading"], "loras": state["loras"] or [p.name for p in scan_loras()],
            "quant": A.quant, "idle_min": A.idle, "vram": vram(), "load_seconds": state["load_s"],
            "base_idle_s": round(time.time() - state["last_base"]) if state["base"] is not None else None,
            "error": state["error"] if CUDA else "没检测到 CUDA：请确认装的是显卡版 PyTorch（cu128）"}


def idle_watch():
    while True:
        time.sleep(30)
        if state["base"] is not None and A.idle > 0 and time.time() - state["last_base"] > A.idle * 60:
            unload_base()


def _try(fn):
    try:
        fn()
    except Exception as e:
        state["error"] = str(getattr(e, "detail", e))


if __name__ == "__main__":
    threading.Thread(target=idle_watch, daemon=True).start()
    if CUDA and A.embed and not A.no_embed_preload:
        threading.Thread(target=lambda: _try(load_embed), daemon=True).start()
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    uvicorn.run(app, host="127.0.0.1", port=A.port, log_level="warning")
