"""DeepSeek 客户端。

- 用哪个模型在 设置 › 云端 选：用你的 Key 从官方 /models 查到列表，下拉框里挑（list_models）。
- 默认开思考模式；简单的活传 thinking=disabled 省钱。
- 每次调用记账（data/agent.db 的 costs 表），只用来估算花了多少。
- 不设每月上限：余额用官方接口 /user/balance 查（每 10 分钟一次，调用过后 1 分钟内再查一次）。
  余额不够时官方返回 402，这里会报"余额不足"。
- 隐私内容不准发：调用时 private=True 会直接拒绝。
"""
import time
from datetime import datetime, timezone

import httpx

from . import db, settings


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


async def chat(messages, *, thinking=False, max_tokens=1200, json_mode=False, purpose="chat",
               private=False, event_id=None, temperature=None, timeout=90):
    if private:
        raise PrivacyBlocked("隐私内容不发给 DeepSeek")
    s = settings.S
    body = {"model": s["dsModel"], "messages": messages, "max_tokens": max(max_tokens, 4000) if thinking else max_tokens,
            "thinking": {"type": "enabled" if thinking else "disabled"}}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if temperature is not None and not thinking:
        body["temperature"] = temperature
    t0 = time.time()
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(s["dsBase"].rstrip("/") + "/chat/completions", json=body,
                         headers={"Authorization": f"Bearer {_key()}"})
    if r.status_code == 402:
        _bal["dirty"] = True
        raise NoBalance("DeepSeek 余额不足，充值后就能继续")
    if r.status_code != 200:
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
    return {"text": (msg.get("content") or "").strip(), "usd": usd, "cny": usd * float(s["usdCny"]),
            "latency": time.time() - t0, "model": j.get("model")}


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
