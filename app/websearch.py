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

from . import agentkit, db, deepseek, files, privacy, settings, workspace

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


def _trim(msgs, keep=14, budget=160_000):
    """做了很多步以后，前面那些工具的长输出（命令的输出、读的文件、看过的图）缩短：只留最近 keep 条完整的，免得越做越贵、越做越慢。"""
    idx = [i for i, m in enumerate(msgs) if m.get("role") == "tool" or isinstance(m.get("content"), list)]
    size = sum(len(m["content"]) if isinstance(m.get("content"), str) else 3000 * len(m["content"]) for m in msgs if m.get("content"))
    if size <= budget or len(idx) <= keep:
        return msgs
    old = set(idx[:-keep])
    out = []
    for i, m in enumerate(msgs):
        if i in old and i > 1:
            c = m.get("content")
            if isinstance(c, list):
                txt = "".join(x.get("text", "") for x in c if x.get("type") == "text")
                m = dict(m, content=txt + "（图片看过了，这里省掉）")
            elif isinstance(c, str) and len(c) > 500:
                m = dict(m, content=c[:300] + f"\n……（中间省掉了 {len(c) - 450} 字，要看重新读 / 重新运行）……\n" + c[-150:])
        out.append(m)
    return out


async def answer_with_tools(messages, *, thinking, event_id, purpose, user_text, steps, progress=None, web=True, local_files=False, ws=False):
    """让 DeepSeek 带着工具回答：联网搜索（web）、读他允许的文件夹（local_files，app/files.py）、在自己的工作文件夹里写写改改跑程序（ws，app/workspace.py，v2.1）、
    列计划 / 看画面 / 下载 / 配音 / 生图 / 配乐（app/agentkit.py，v3.0，跟着 ws 一起给）。
    返回 {"text","cny","searched","fetched","read","ws","sources","stopped"}；steps 里追加每一步。progress(文字)：处理到哪一步了（对话页实时显示）。
    v3.0：每一步之前看一眼这件事的开关（agentkit.CTRL）——他点了停下就停、中途插的话带给 DeepSeek；一件事花的钱到了预算就停下汇报。"""
    say = progress or (lambda _m: None)
    s = settings.S
    rounds = web_max = max(1, int(s.get("searchRounds", 4)))   # 联网搜索最多几轮（带着工作区工具时总步数多，但搜索照旧按这个数）
    if local_files:
        rounds = max(rounds, 8)                         # 翻文件要多几轮：搜 → 读 → 再读
    if ws:
        rounds = max(rounds, int(s.get("agSteps") or 120))   # 做东西（写网页、跑脚本、合成视频）一件事要很多步（v3.0：40 → 120）
        await asyncio.to_thread(agentkit.sync_toolbox)
    budget = float(s.get("agBudget") or 0) if ws else 0.0
    ctl = agentkit.CTRL.get(event_id) or {"stop": "", "inbox": []}
    msgs = list(messages)
    msgs[0] = {"role": "system", "content": msgs[0]["content"] + ("\n\n" + system_hint() if web else "") + ("\n\n" + files.hint() if local_files else "") +
               ("\n\n" + workspace.hint() + "\n\n" + agentkit.hint(user_text) if ws else "")}
    total, searched, fetched, nread, nws, sources, n_res, imgs = 0.0, 0, 0, 0, 0, [], 1, 0
    web_rnds, web_cap_said, dsml_retry, over = 0, False, 0, False

    def done(text, **kw):
        return dict({"text": text, "cny": total, "searched": searched, "fetched": fetched, "read": nread, "ws": nws, "sources": sources}, **kw)
    for rnd in range(rounds + 1):
        if ctl.get("stop"):                              # 他点了停下：这一步做完就到这
            steps.append(["停下", ctl["stop"]])
            return done(f"按你说的停下了，做了 {nws} 步。做好的都在工作文件夹里；要接着做就说「继续」。" if nws else "按你说的停下了。", stopped=True)
        while ctl.get("inbox"):                          # 他中途插了话
            more = ctl["inbox"].pop(0)
            steps.append(["你插了一句", more[:60]])
            msgs.append({"role": "user", "content": f"（他中途补了一句，照这个调整，接着做：）{more}"})
        if budget and total >= budget and not over and rnd < rounds:
            over = True
            steps.append(["到预算了", f"这件事花了 ¥{total:.2f}，到了你设的上限 ¥{budget:.2f}"])
            msgs.append({"role": "user", "content": f"（程序提示：这件事已经花了 ¥{total:.2f}，到了他设的上限。这一轮不能再调用工具：把做到哪、下一步做什么写清楚汇报给他；他说「继续」再接着做。）"})
        msgs = _trim(msgs)
        if ws and nws and rnd == rounds - 3:             # 快到上限：先记下做到哪（v2.2）
            msgs.append({"role": "user", "content": "（程序提示：只剩 3 步了。先把做到哪、下一步做什么写进这件事文件夹里的 进度.md，做不完就停下来汇报。）"})
        if ws and nws and rnd == rounds:
            msgs.append({"role": "user", "content": "（程序提示：步数用完了，这一轮不能再调用工具。用中文简短汇报：做完了什么、文件在哪、下一步做什么；他说「继续」你接着做。）"})
        give_web = web and rnd < rounds and web_rnds < web_max and today_count() < int(s.get("searchDaily", 200))
        if web and web_rnds >= web_max and not web_cap_said and rounds > web_max:
            steps.append(["联网搜索", f"查了 {web_max} 轮，到上限了，不再搜"])
            web_cap_said = True
        tools = [] if over else ((TOOLS if give_web else []) + (files.TOOLS if (local_files or ws) and rnd < rounds else []) +
                                 (workspace.tools() + agentkit.tools() if ws and rnd < rounds else []))
        say("DeepSeek 正在想……" if rnd == 0 else f"DeepSeek 正在接着做（第 {rnd + 1} 步，最多 {rounds} 步）……" if nws else "DeepSeek 正在看查到的内容……")
        out = await deepseek.chat(msgs, thinking=thinking, event_id=event_id, purpose=purpose, tools=tools or None,
                                  max_tokens=8000 if ws else 1600, timeout=300 if ws else 90)
        total += out["cny"]
        thinking = out.get("thinking", thinking)          # 被官方拒了改成不思考的话，后面几轮也不思考
        if out.get("fallback"):
            steps.append(["DeepSeek 拒了一次", "改成" + "、".join(out["fallback"]) + "再试（原因记在 data\\logs\\deepseek.log）"])
            if "去掉图片" in out["fallback"]:
                msgs, imgs = deepseek.no_images(msgs), 99    # 后面也不带图片了，免得每一步都被拒一次
        calls = out.get("tool_calls") or []
        if calls and ws and out.get("finish") == "length":   # 被截断的调用参数不完整，不执行，下面提醒它分段再来
            calls = []
        if not calls and (deepseek.has_dsml(out["text"]) or (ws and out.get("finish") == "length")):
            # v2.2：工具调用被写成了文字（没给工具 / 回复被截断）。认得出就照常执行，认不出就提醒它再来一次，这串文字不给他看
            names = {(t.get("function") or {}).get("name") for t in tools}
            got = deepseek.parse_dsml(out["text"]) if out.get("finish") != "length" else []
            if got and all(n in names for n, _ in got):
                calls = [{"id": f"dsml_{rnd}_{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)}}
                         for i, (n, a) in enumerate(got)]
                out["message"] = dict(out["message"], content=deepseek.strip_dsml(out["text"]), tool_calls=calls)
                steps.append(["认出写成文字的工具调用", f"{len(calls)} 个，照常执行"])
            elif rnd < rounds and dsml_retry < 2:
                dsml_retry += 1
                why = "回复太长被截断了" if out.get("finish") == "length" else "写成了文字"
                steps.append(["工具调用没成", f"{why}，提醒它分段写、用工具调用，再试一次"])
                msgs.append({"role": "user", "content": f"（程序提示：你刚才的工具调用没执行——{why}。请直接用工具调用（function call），不要把调用写成文字；"
                             "长文件分段写，每次不超过 3000 字，后面的 append=true。接着做，不用道歉。）"})
                continue
        if not calls:
            text = out["text"]
            if deepseek.has_dsml(text):
                text = deepseek.strip_dsml(text) or (f"做了 {nws} 步，最后一步的工具调用没成功（被截断了）。跟我说「继续」我接着做。" if nws else
                                                    "这次工具调用没成功，跟我说「继续」我再试一次。")
            if not text.strip() and nws:
                text = f"做了 {nws} 步，最后一步没回上来（回复被截断了）。跟我说「继续」我接着做。"
            if not tools and searched + fetched + nread + nws and rnd >= rounds:
                steps.append(["工作区" if nws else "联网搜索" if searched + fetched else "读文件",
                              f"做了 {rounds} 步，到上限了，先停在这" if nws else f"查了 {rounds} 轮，到上限了，用已有的结果回答"])
            if sources and not re.search(r"https?://", text):
                text += "\n\n来源：\n" + "\n".join(f"{i + 1}. {x['title'][:40]} {x['url']}" for i, x in enumerate(sources[:3]))
            return done(text)
        msgs.append(out["message"])
        if any((c.get("function") or {}).get("name") in ("web_search", "web_fetch") for c in calls) and give_web:
            web_rnds += 1
        pics = []                                        # read_file 读到的图片：工具结果只能是文字，图片放进紧跟着的一条用户消息
        for call in calls:
            fn = (call.get("function") or {})
            name = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            t0 = time.time()
            try:
                if name in ("web_search", "web_fetch") and not give_web:
                    content = "这一轮没给你联网搜索（今天的次数用完了或者关着），凭已有的信息回答。"
                elif name == "web_search":
                    say(f"正在联网搜索「{str(args.get('query', ''))[:40]}」……")
                    res = await search(args.get("query", ""), args.get("count") or 8, ori=user_text, event_id=event_id, purpose=purpose)
                    searched += 1
                    content = _fmt_results(res, n_res)
                    for r in res:
                        sources.append({"n": n_res, "title": r.get("title") or _site(r.get("url")), "url": r.get("url"), "fetched": False})
                        n_res += 1
                    steps.append(["联网搜索", f"「{args.get('query', '')[:40]}」· {len(res)} 条 · {time.time() - t0:.1f} 秒"])
                elif name == "web_fetch":
                    say(f"正在读网页 {_site(args.get('url', ''))}……")
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
                elif name in workspace.NAMES and ws:
                    content, step = await asyncio.to_thread(workspace.run_tool, name, args, say)
                    steps.append(step)
                    nws += 1
                elif name in agentkit.NAMES and ws:
                    content, step, got, cny = await agentkit.run_tool(name, args, event_id, say)
                    steps.append(step)
                    total += cny
                    nws += 1
                    for x in got:
                        if imgs < 24:
                            pics.append(x)
                            imgs += 1
                elif name in files.NAMES and (local_files or ws):
                    say(f"正在{'读文件' if name == 'read_file' else '翻文件夹'}……")
                    content, step, pic, used = await asyncio.to_thread(files.run_tool, name, args)
                    steps.append(step)
                    if used:
                        nread += 1
                        files.note(event_id, "fimg" if pic else "file", used)
                    if pic and imgs < 4:
                        pics.append(pic)
                        imgs += 1
                else:
                    content = f"没有这个工具：{name}"
            except workspace.Denied as e:
                content = f"没做成：{e}"
                steps.append(["工作区", f"没做成：{str(e)[:50]}"])
            except files.Denied as e:
                if name in workspace.NAMES or name in agentkit.NAMES:
                    content = f"没做成：{e}"
                    steps.append(["工作区", f"没做成：{str(e)[:50]}"])
                else:
                    content = f"没读成：{e}"
                    steps.append(["读文件", f"没读成：{str(e)[:50]}"])
            except OSError as e:
                content = f"没做成（{type(e).__name__}）：{str(e)[:160]}"
                steps.append(["工作区" if name in workspace.NAMES or name in agentkit.NAMES else "读文件", f"出错：{str(e)[:50]}"])
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
        if pics:
            msgs.append({"role": "user", "content": [{"type": "text", "text": "（read_file 读到的图片：" + "、".join(x["name"] for x in pics) + "）"}] +
                         [{"type": "image_url", "image_url": {"url": x["uri"]}} for x in pics]})
    if nws:
        return done(f"这件事步骤太多，做了 {rounds} 步先停在这了：做好的都在工作文件夹里（{workspace.folder()}）。跟我说「接着做」我再继续。")
    return done("查了很多轮还没得出结论，换个问法再问我一次吧。")


FRESH = re.compile(r"最新|新闻|热搜|今天.*(发生|新闻|比赛|消息)|价格|多少钱|报价|汇率|股价|天气|比分|赛程|发布了|出了没|更新了|"
                   r"版本号|上映|开售|官网|搜一下|搜搜|帮我搜|联网|上网查|最近.*(更新|消息|新闻|发布|动态|版本)")


def wants_fresh(text: str) -> bool:
    """看着像要查最新信息的问题（本地小脑查不了网，这类交给 DeepSeek 联网）。"""
    return bool(FRESH.search(text or ""))
