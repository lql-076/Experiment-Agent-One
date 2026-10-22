"""联网搜索：DeepSeek 自研搜索引擎的两个接口（2026-10-17 开放，用同一个 DeepSeek Key）。

- 搜索 POST {api.deepseek.com}/v1/tools/search：一句话 → 网页结果（标题、链接、给模型看的长摘要、相关度、权威度、日期）。
- 抓取 POST {api.deepseek.com}/v1/tools/fetch：一个网址 → 整页正文（Markdown）。
- 价格：每 1000 次成功请求 0.75 美元（国内页写 5 元）。没结果、失败、超时不收钱。

怎么用：交给 DeepSeek 的事，把这两个接口当成工具给它（answer_with_tools），它自己决定要不要搜、搜什么、读哪页。
规矩（写死）：
- 隐私的事根本不给工具；发出去的每个搜索词、网址再过一遍隐私关键词名单，命中就不发。
- 每天最多搜多少次（设置 › 云端），到了就不再给工具，直接凭已有知识回答并说明。
- 每次调用都记进 costs 表（model = web_search / web_fetch），余额、报告里的花费都算上。
"""
import asyncio
import json
import re
import time
from datetime import datetime

import httpx

from . import db, deepseek, privacy, settings

PRICE_USD = 0.75 / 1000          # 每次成功请求
WEEK = "一二三四五六日"

TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "联网搜索（DeepSeek 搜索引擎）。需要最新信息、具体事实、价格、版本、新闻、你不确定的事时用。"
                       "返回编号的结果，每条有标题、网站、日期、链接和摘要。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索词，简短，1~128 字。可以用 site:域名、\"精确词\"、-排除词、after:2026-01-01、before:2026-12-31、lang:zh,en"},
            "count": {"type": "integer", "description": "要几条结果，1~20，默认 8"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "web_fetch",
        "description": "读一个网页的正文（Markdown）。搜索结果的摘要不够、需要看详细内容时用，网址必须来自搜索结果或用户给的。",
        "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "完整网址，http 或 https"}},
                       "required": ["url"]}}},
]


class SearchBlocked(Exception):
    """搜索词或网址涉及隐私，没有发出去。"""


class SearchLimit(Exception):
    """今天的搜索次数用完了。"""


def _base() -> str:
    b = settings.S["dsBase"].rstrip("/")
    return b[:-3] if b.endswith("/v1") else b


def _day_start() -> float:
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def today_count() -> int:
    r = db.one("SELECT COUNT(*) n FROM costs WHERE model IN ('web_search','web_fetch') AND ts>=?", (_day_start(),))
    return int(r["n"]) if r else 0


def stats():
    """给界面看：今天、近 24 小时、这个月各搜了几次、花了多少。"""
    def q(since):
        r = db.one("SELECT COUNT(*) n, COALESCE(SUM(usd),0) usd FROM costs WHERE model IN ('web_search','web_fetch') AND ts>=?", (since,))
        return {"n": int(r["n"]), "cny": float(r["usd"]) * float(settings.S["usdCny"])}
    month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    return {"on": bool(settings.S.get("searchOn", True)), "limit": int(settings.S.get("searchDaily", 200)),
            "today": q(_day_start()), "day": q(time.time() - 86400), "month": q(month)}


def _guard(s: str):
    if privacy.check(s)[0]:
        raise SearchBlocked("涉及隐私，没有发出去")
    if today_count() >= int(settings.S.get("searchDaily", 200)):
        raise SearchLimit(f"今天的联网搜索次数（{settings.S.get('searchDaily', 200)} 次）用完了")


async def _post(path, body, kind, event_id, timeout=30):
    key = settings.get_secret("dsKey")
    if not key:
        raise deepseek.NoKey("还没有填 DeepSeek API Key")
    for attempt in (0, 1):
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(_base() + path, json=body, headers={"Authorization": f"Bearer {key}"})
        if r.status_code in (429, 408, 500, 502, 503, 504) and attempt == 0:
            await asyncio.sleep(1.2)
            continue
        break
    if r.status_code == 402:
        raise deepseek.NoBalance("DeepSeek 余额不足，充值后就能继续")
    if r.status_code == 401:
        raise RuntimeError("Key 不对（401）")
    if r.status_code == 404 and kind == "web_fetch":
        return None                                   # 这个网页读不到可用内容（不收钱）
    if r.status_code != 200:
        raise RuntimeError(f"返回 {r.status_code}：{r.text[:160]}")
    return r.json()


def _bill(kind, event_id, purpose):
    db.insert("costs", {"ts": time.time(), "model": kind, "tin": 0, "thit": 0, "tout": 0, "usd": PRICE_USD,
                        "purpose": purpose, "event_id": event_id})


async def search(query: str, count=8, ori=None, event_id=None, purpose="search"):
    query = (query or "").strip()[:128]
    if not query:
        raise ValueError("搜索词是空的")
    _guard(query)
    body = {"query": query, "count": max(1, min(int(count or 8), 50))}
    if ori and not privacy.check(ori)[0]:
        body["ori_question"] = ori.strip()[:128]
    j = await _post("/v1/tools/search", body, "web_search", event_id)
    res = (j or {}).get("results") or []
    if res:
        _bill("web_search", event_id, purpose)        # 有结果才收钱
    return res


async def fetch(url: str, event_id=None, purpose="search"):
    url = (url or "").strip()
    if not re.match(r"^https?://[^\s/@]+", url) or len(url) > 8192:
        raise ValueError("网址不对")
    _guard(url)
    j = await _post("/v1/tools/fetch", {"url": url}, "web_fetch", event_id, timeout=45)
    if not j or not (j.get("content") or "").strip():
        return None
    _bill("web_fetch", event_id, purpose)
    return {"title": j.get("title") or "", "content": j["content"]}


def _site(u):
    m = re.match(r"^https?://([^/]+)", u or "")
    return m.group(1) if m else ""


def _fmt_results(res, start):
    lines = []
    for i, r in enumerate(res):
        n = start + i
        meta = " · ".join(x for x in (r.get("site_name") or _site(r.get("url")), (r.get("date") or "")[:10],
                                       f"权威度 {r['authority']}" if isinstance(r.get("authority"), (int, float)) and r["authority"] >= 0 else "") if x)
        lines.append(f"[{n}] {r.get('title') or '（无标题）'}（{meta}）\n{r.get('url')}\n{(r.get('summary') or r.get('snippet') or '')[:700]}")
    return "\n\n".join(lines) if lines else "没有搜到结果。换个说法，或者少加几个限定词再试。"


def system_hint() -> str:
    d = datetime.now()
    return (f"今天是 {d.year} 年 {d.month} 月 {d.day} 日（星期{WEEK[d.weekday()]}）。"
            "你可以用 web_search 联网搜索、用 web_fetch 读网页。需要最新信息、具体事实、价格、版本、新闻，或者你不确定的事，先搜再答；"
            "常识和闲聊不用搜。搜索词要简短，不要放进用户的名字、账号、健康、住址这类个人信息。"
            "一般搜 1~2 次就够；摘要不够再读 1~2 个最相关的网页。"
            "回答用中文、简短直接；用到了网上的信息，在最后列出来源（标题 + 链接，最多 3 条）。")


async def answer_with_tools(messages, *, thinking, event_id, purpose, user_text, steps):
    """让 DeepSeek 带着搜索工具回答。返回 {"text","cny","searched","fetched","sources"}；steps 里追加每一步。"""
    s = settings.S
    rounds = max(1, int(s.get("searchRounds", 4)))
    msgs = list(messages)
    msgs[0] = {"role": "system", "content": msgs[0]["content"] + "\n\n" + system_hint()}
    total, searched, fetched, sources, n_res = 0.0, 0, 0, [], 1
    for rnd in range(rounds + 1):
        give = rnd < rounds and today_count() < int(s.get("searchDaily", 200))
        out = await deepseek.chat(msgs, thinking=thinking, event_id=event_id, purpose=purpose, tools=TOOLS if give else None,
                                  max_tokens=1600)
        total += out["cny"]
        thinking = out.get("thinking", thinking)          # 被官方拒了改成不思考的话，后面几轮也不思考
        calls = out.get("tool_calls") or []
        if not calls:
            text = out["text"]
            if not give and searched + fetched and rnd >= rounds:
                steps.append(["联网搜索", f"查了 {rounds} 轮，到上限了，用已有的结果回答"])
            if sources and not re.search(r"https?://", text):
                text += "\n\n来源：\n" + "\n".join(f"{i + 1}. {x['title'][:40]} {x['url']}" for i, x in enumerate(sources[:3]))
            return {"text": text, "cny": total, "searched": searched, "fetched": fetched, "sources": sources}
        msgs.append(out["message"])
        for call in calls:
            fn = (call.get("function") or {})
            name = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            t0 = time.time()
            try:
                if name == "web_search":
                    res = await search(args.get("query", ""), args.get("count") or 8, ori=user_text, event_id=event_id, purpose=purpose)
                    searched += 1
                    content = _fmt_results(res, n_res)
                    for r in res:
                        sources.append({"n": n_res, "title": r.get("title") or _site(r.get("url")), "url": r.get("url"), "fetched": False})
                        n_res += 1
                    steps.append(["联网搜索", f"「{args.get('query', '')[:40]}」· {len(res)} 条 · {time.time() - t0:.1f} 秒"])
                elif name == "web_fetch":
                    page = await fetch(args.get("url", ""), event_id=event_id, purpose=purpose)
                    if page:
                        fetched += 1
                        content = f"标题：{page['title']}\n\n{page['content'][:12000]}"
                        hit = next((x for x in sources if x["url"] == args.get("url")), None)
                        if hit:
                            hit["fetched"] = True
                        else:
                            sources.append({"n": None, "title": page["title"] or _site(args.get("url")), "url": args.get("url"), "fetched": True})
                        steps.append(["读网页", f"{(page['title'] or _site(args.get('url')))[:40]} · {_site(args.get('url'))}"])
                    else:
                        content = "这个网页读不到内容（网站拦了或者没有正文），换一个结果。"
                        steps.append(["读网页", f"没读到 · {_site(args.get('url'))}"])
                else:
                    content = f"没有这个工具：{name}"
            except SearchBlocked as e:
                content = f"没有发出去：{e}。不要把个人信息放进搜索词。"
                steps.append(["联网搜索", "搜索词涉及隐私，拦下了"])
            except SearchLimit as e:
                content = str(e) + "，凭已有信息回答，并告诉用户今天的搜索次数用完了。"
                steps.append(["联网搜索", str(e)])
            except (deepseek.NoBalance, deepseek.NoKey):
                raise
            except Exception as e:
                content = f"这次没查成：{str(e)[:120]}"
                steps.append(["联网搜索", f"出错：{str(e)[:50]}"])
            msgs.append({"role": "tool", "tool_call_id": call.get("id") or "", "content": content})
    return {"text": "查了很多轮还没得出结论，换个问法再问我一次吧。", "cny": total, "searched": searched, "fetched": fetched, "sources": sources}


FRESH = re.compile(r"最新|新闻|热搜|今天.*(发生|新闻|比赛|消息)|价格|多少钱|报价|汇率|股价|天气|比分|赛程|发布了|出了没|更新了|"
                   r"版本号|上映|开售|官网|搜一下|搜搜|帮我搜|联网|上网查|最近.*(更新|消息|新闻|发布|动态|版本)")


def wants_fresh(text: str) -> bool:
    """看着像要查最新信息的问题（本地小脑查不了网，这类交给 DeepSeek 联网）。"""
    return bool(FRESH.search(text or ""))
