"""DeepSeek 客户端。

- 用哪个模型在 设置 › 云端 选：用你的 Key 从官方 /models 查到列表，下拉框里挑（list_models）。
- 默认开思考模式；简单的活传 thinking=disabled 省钱。
- 每次调用记账（data/agent.db 的 costs 表），只用来估算花了多少。
- 不设每月上限：余额用官方接口 /user/balance 查（每 10 分钟一次，调用过后 1 分钟内再查一次）。
  余额不够时官方返回 402，这里会报"余额不足"。
- 隐私内容不准发：调用时 private=True 会直接拒绝。
- 可以带工具（tools，OpenAI 格式）：联网搜索就是这样接的（app/websearch.py）。模型要调工具时，返回里有 tool_calls 和
  原样的 message（思考模式下带 reasoning_content，同一轮里要原样传回去）。
"""
import json
import re
import time
from datetime import datetime, timezone

import httpx

from . import db, paths, settings


class NoBalance(Exception):
    """DeepSeek 余额不足（官方返回 402）。"""


BudgetExceeded = NoBalance   # 旧名字，夜间差事等地方还在用
_bal = {"ts": 0.0, "dirty": True}


class PrivacyBlocked(Exception):
    pass


class NoKey(Exception):
    pass


def _peak_now() -> bool:
    """官方忙时：周一到周五 UTC 01:00-04:00 和 06:00-10:00（北京时间 9-12 点、14-18 点）。"""
    u = datetime.now(timezone.utc)
    if u.weekday() >= 5:
        return False
    return 1 <= u.hour < 4 or 6 <= u.hour < 10


def month_cost_cny() -> float:
    start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    r = db.one("SELECT COALESCE(SUM(usd),0) s FROM costs WHERE ts>=?", (start,))
    return float(r["s"]) * float(settings.S["usdCny"])


def day_cost_cny(day_start: float) -> float:
    r = db.one("SELECT COALESCE(SUM(usd),0) s FROM costs WHERE ts>=?", (day_start,))
    return float(r["s"]) * float(settings.S["usdCny"])


def _key() -> str:
    k = settings.get_secret("dsKey")
    if not k:
        raise NoKey("还没有填 DeepSeek API Key")
    return k


def has_image(messages) -> bool:
    """消息里有没有图片（content 是列表、里面有 image_url）。有就换成能看图的模型（设置 › 云端 › 看图用的模型）。"""
    for m in messages:
        c = m.get("content")
        if isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "image_url" for x in c):
            return True
    return False


async def chat(messages, *, thinking=False, max_tokens=1200, json_mode=False, purpose="chat",
               private=False, event_id=None, temperature=None, timeout=90, tools=None):
    if private:
        raise PrivacyBlocked("隐私内容不发给 DeepSeek")
    s = settings.S
    img = has_image(messages)
    body = {"model": (s.get("dsVision") or s["dsModel"]) if img else s["dsModel"], "messages": messages, "max_tokens": max(max_tokens, 4000) if thinking else max_tokens,
            "thinking": {"type": "enabled" if thinking else "disabled"}}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = tools
    if temperature is not None and not thinking:
        body["temperature"] = temperature
    t0 = time.time()
    ws = any((t.get("function") or {}).get("name") == "write_file" for t in (tools or []))
    fallback = []
    for _ in range(4):
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(s["dsBase"].rstrip("/") + "/chat/completions", json=body,
                             headers={"Authorization": f"Bearer {_key()}"})
        # 带工具时官方要求思考模式把 reasoning_content 原样传回；万一哪条历史消息没带上被拒（400），
        # 先改成不思考再试；在工作区干活时（v2.2）再试去掉图片（带图片 + 工具最容易被拒）；还不行才不带工具直接答——不让一条消息卡死
        if r.status_code == 400 and (body.get("tools") or (img and body["thinking"]["type"] == "enabled")):     # 看图时思考模式万一不支持，也先改成不思考再试
            _log400(r.text, body)
            if body["thinking"]["type"] == "enabled":
                body["thinking"] = {"type": "disabled"}
                body["max_tokens"] = max_tokens
                thinking = False
                fallback.append("不思考")
            elif ws and img and body.get("tools"):
                body["messages"] = no_images(body["messages"])
                body["model"] = s["dsModel"]
                img = False
                fallback.append("去掉图片")
            else:
                body.pop("tools")
                fallback.append("不带工具")
            continue
        break
    if r.status_code == 402:
        _bal["dirty"] = True
        raise NoBalance("DeepSeek 余额不足，充值后就能继续")
    if r.status_code != 200:
        if img and r.status_code == 400:
            raise RuntimeError(f"DeepSeek 看不了这张图（{body['model']} 返回 400：{r.text[:120]}）。设置 › 云端 › 看图用的模型 填 deepseek-flash 试试")
        raise RuntimeError(f"DeepSeek 返回 {r.status_code}：{r.text[:200]}")
    _bal["dirty"] = True
    j = r.json()
    msg = j["choices"][0]["message"]
    u = j.get("usage", {})
    hit = int(u.get("prompt_cache_hit_tokens", 0))
    miss = int(u.get("prompt_cache_miss_tokens", u.get("prompt_tokens", 0) - hit))
    out = int(u.get("completion_tokens", 0))
    x = float(s["peakX"]) if _peak_now() else 1.0
    usd = (miss * float(s["priceIn"]) + hit * float(s["priceHit"]) + out * float(s["priceOut"])) / 1e6 * x
    db.insert("costs", {"ts": time.time(), "model": j.get("model", s["dsModel"]), "tin": miss, "thit": hit,
                        "tout": out, "usd": usd, "purpose": purpose, "event_id": event_id})
    calls = msg.get("tool_calls") or []
    keep = {"role": "assistant", "content": msg.get("content") or ""}
    if calls:
        keep["tool_calls"] = calls
    if msg.get("reasoning_content"):
        keep["reasoning_content"] = msg["reasoning_content"]
    return {"text": (msg.get("content") or "").strip(), "usd": usd, "cny": usd * float(s["usdCny"]),
            "latency": time.time() - t0, "model": j.get("model"), "tool_calls": calls, "message": keep, "thinking": thinking,
            "finish": j["choices"][0].get("finish_reason") or "", "fallback": fallback}


def _log400(text, body):
    """DeepSeek 拒了请求（400）：原因写进 data\\logs\\deepseek.log，排查用（不写 Key、不写消息内容）。"""
    try:
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        p = paths.LOGS / "deepseek.log"
        if p.exists() and p.stat().st_size > 2 << 20:
            p.replace(p.with_suffix(".old.log"))
        n_img = sum(1 for m in body.get("messages", []) if isinstance(m.get("content"), list))
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} 400 model={body.get('model')} thinking={body['thinking']['type']} "
                    f"tools={len(body.get('tools') or [])} msgs={len(body.get('messages', []))} img_msgs={n_img}：{str(text)[:400]}\n")
    except OSError:
        pass


def no_images(messages):
    """把消息里的图片换成一句话（带图片 + 工具被拒时用）。"""
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            txt = "".join(x.get("text", "") for x in c if x.get("type") == "text")
            n = sum(1 for x in c if x.get("type") == "image_url")
            m = dict(m, content=(txt + f"（这里原来有 {n} 张图片，这次带不上）").strip())
        out.append(m)
    return out


# ---------------- DeepSeek 把工具调用写成了文字（v2.2）----------------
# 没给它工具、或者回复被截断时，它会把调用按自己的内部格式写进正文：
# <｜DSML｜function_calls><｜DSML｜invoke name="write_file"><｜DSML｜parameter name="path" string="true">a.txt</｜DSML｜parameter>…
_B = r"[｜|]\s*DSML\s*[｜|]\s*"
DSML_RE = re.compile(_B, re.I)
_INVOKE = re.compile(r"<" + _B + r"invoke\s+name\s*=\s*\"([^\"]+)\"\s*>(.*?)</" + _B + r"invoke\s*>", re.S | re.I)
_PARAM = re.compile(r"<" + _B + r"parameter\s+name\s*=\s*\"([^\"]+)\"(?:\s+string\s*=\s*\"(true|false)\")?\s*>(.*?)</" + _B + r"parameter\s*>", re.S | re.I)
_BLOCK = re.compile(r"<" + _B + r"function_calls\s*>.*?(</" + _B + r"function_calls\s*>|\Z)", re.S | re.I)


def has_dsml(text) -> bool:
    return bool(DSML_RE.search(text or ""))


def parse_dsml(text):
    """认出文字里的工具调用：[(名字, 参数), …]；没写完（被截断）的不算。"""
    out = []
    for name, inner in _INVOKE.findall(text or ""):
        args = {}
        for k, is_str, v in _PARAM.findall(inner):
            if is_str.lower() != "true":
                try:
                    v = json.loads(v)
                except (ValueError, TypeError):
                    pass
            args[k] = v
        for k in ("append", "all"):
            if isinstance(args.get(k), str):
                args[k] = args[k].strip().lower() == "true"
        out.append((name.strip(), args))
    return out


def strip_dsml(text) -> str:
    """去掉文字里的工具调用（不给他看这串）。"""
    t = _BLOCK.sub("", text or "")
    m = re.search(r"<?" + _B, t)
    if m:
        t = t[:m.start()]
    return t.strip()


async def balance():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(settings.S["dsBase"].rstrip("/") + "/user/balance", headers={"Authorization": f"Bearer {_key()}"})
    if r.status_code == 401:
        raise RuntimeError("Key 不对（401）")
    r.raise_for_status()
    return r.json()


async def list_models():
    """用你的 Key 问官方：这个 Key 能用哪些模型（OpenAI 兼容的 GET /models）。查到的存起来，设置页下拉框用。"""
    base = settings.S["dsBase"].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(base + "/models", headers={"Authorization": f"Bearer {_key()}"})
    except NoKey:
        raise
    except Exception as e:
        raise RuntimeError(f"连不上 {base}：{str(e)[:80]}") from e
    if r.status_code == 401:
        raise RuntimeError("Key 不对（官方返回 401）")
    if r.status_code == 404:
        raise RuntimeError(f"{base} 不支持查模型列表（404），只能手动填模型名")
    r.raise_for_status()
    ids = sorted({str(m.get("id")) for m in (r.json().get("data") or []) if isinstance(m, dict) and m.get("id")})
    if not ids:
        raise RuntimeError("官方返回的列表是空的")
    out = {"ts": time.time(), "base": base, "models": ids}
    db.kv_set("ds_models", out)
    return out


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


async def refresh_balance(force=False):
    """查一次余额，存进数据库（界面直接读缓存，不每次都去问官方）。"""
    if not settings.get_secret("dsKey"):
        db.kv_set("ds_balance", None)
        return None
    if not force and time.time() - _bal["ts"] < 50:
        return db.kv_get("ds_balance")
    _bal["ts"] = time.time()
    try:
        j = await balance()
    except Exception as e:
        cur = db.kv_get("ds_balance") or {}
        cur.update(err=str(e)[:120], ts_try=time.time())
        db.kv_set("ds_balance", cur)
        return cur
    infos = j.get("balance_infos") or []
    info = next((i for i in infos if i.get("currency") == "CNY"), infos[0] if infos else {})
    out = {"ts": time.time(), "available": bool(j.get("is_available", True)), "currency": info.get("currency", "CNY"),
           "total": _num(info.get("total_balance")), "granted": _num(info.get("granted_balance")),
           "topped": _num(info.get("topped_up_balance")), "err": None}
    db.kv_set("ds_balance", out)
    _bal["dirty"] = False
    return out


def balance_cached():
    return db.kv_get("ds_balance")


async def balance_tick(n):
    """后台照看每 2 秒调一次：调用过就 1 分钟后查一次，平时 10 分钟查一次。"""
    if not settings.get_secret("dsKey"):
        return
    if (_bal["dirty"] and time.time() - _bal["ts"] > 60) or time.time() - _bal["ts"] > 600:
        await refresh_balance(force=True)


def money(v, cur="CNY"):
    if v is None:
        return "—"
    return ("¥" if cur == "CNY" else "$" if cur == "USD" else cur + " ") + f"{v:.2f}"
