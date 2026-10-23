"""处理一条消息的全过程：先看是不是在回提醒、设提醒、让我记东西（这些不用模型）；
其余的过决策脑两票，交给本地小脑 / DeepSeek / 建议你带提示词去问更强的模型；每一步都写进事件日志。
你也可以推翻决策脑：force 指定去向（界面上「换它重做」），redo_of 记下是哪一条重做的。
交给 DeepSeek 的，带上联网搜索工具（app/websearch.py），要不要搜由它自己定；问到 agent 自己怎么用的，
先从说明书（docs/操作手册.md、docs/AI文档）里找相关段落一起给模型。
接了 Obsidian 的（app/obsidian.py）：回答前先查笔记；私人笔记只给本地小脑（用到私人笔记的事改交本地）；
DeepSeek 还能自己用「查笔记、读笔记」两个工具（只给非私人的）。「存到笔记：……」直接写进库里的 Agent 收件箱。"""
import asyncio
import contextlib
import json
import re
import time
from collections import defaultdict, deque

from . import db, deepseek, events, growth, memory, notify, obsidian, paths, privacy, reminders, router, safety, settings, websearch
from .models import M
from .qq import BOT

MEM_INSTRUCT = "Given a user message, retrieve personal notes and memories that help answer it"
REMEMBER = re.compile(r"^(请)?(帮我)?(记住|记一下|记下来|记下|帮我记)[：:，, ]*(.+)$", re.S)
HIST = defaultdict(lambda: deque(maxlen=8))   # 每个人最近几轮：(role, content, private, ts)
SRC_LABEL = {"qq": "QQ 私聊", "ui": "界面输入", "cron": "定时任务"}


def _history(user, allow_private):
    now = time.time()
    out = []
    for role, content, priv, ts in HIST[user]:
        if now - ts > 1800 or (priv and not allow_private):
            continue
        out.append({"role": role, "content": content})
    return out


QQ_PLAIN = "\n这条回复会发到 QQ 私聊，QQ 不显示格式：不要用 **、#、- 列表、表格、代码块这些符号，用纯文字和换行；链接直接写网址。"


def plain(t: str) -> str:
    """发到 QQ 前去掉 Markdown 符号（模型偶尔还是会写），QQ 里看到的是干净的文字。"""
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t or "")
    t = re.sub(r"(?m)^#{1,6}\s*", "", t)
    t = re.sub(r"(?m)^(\s*)[-*]\s+", r"\1· ", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1 \2", t)
    return t.replace("```", "")


def _build(text, user, snips, allow_private, docs=None, src="ui", notes=None):
    d = time.localtime()
    sys = memory.persona() + f"\n现在是 {d.tm_year} 年 {d.tm_mon} 月 {d.tm_mday} 日 {d.tm_hour:02d}:{d.tm_min:02d}（星期{'一二三四五六日'[d.tm_wday]}）。" + (QQ_PLAIN if src == "qq" else "")
    if snips:
        sys += "\n\n下面是他的记忆文件里和这条消息相关的内容，用得上就用，用不上别提：\n" + "\n".join(f"- {m['text']}" for m in snips)
    if docs:
        sys += ("\n\n下面是你自己（这个 agent）的说明书里和这条消息相关的段落。回答关于你自己能做什么、怎么用、在哪设置的问题时，以它为准，"
                "说清楚在界面哪里点：\n" + "\n".join(f"- 〔{m['file'].replace('@说明/', '')}〕{m['text']}" for m in docs))
    if notes:
        sys += ("\n\n下面是他自己 Obsidian 笔记里和这条消息相关的段落（〔库名/路径 · 标题〕开头）。问到他写过、记过的东西，以笔记为准，"
                "不要自己编；用到了哪篇，在回答最后一行写「笔记：《篇名》」。用不上就别提：\n" + obsidian.fmt_hits(notes))
    return [{"role": "system", "content": sys}] + _history(user, allow_private) + [{"role": "user", "content": text}]


def _quick_event(text, src, label, why, reply, private=False, steps=None):
    eid = db.insert("events", {"ts": time.time(), "src": src, "text": text, "private": int(private), "route": "local", "ui_to": "local",
                               "label": label, "conf": 100, "scores": {"local": 100, "neu": 0, "ds": 0, "cl": 0}, "why": why,
                               "steps": steps or [["收到", SRC_LABEL.get(src, src)], ["本地处理", label], ["回复", "已回复"]],
                               "result": reply, "reply": reply, "status": "done"})
    return eid


def _save_sample(e_text, reply, label, eid, private, claude_ctx=False, web=False):
    """存 DeepSeek 的处理记录给慢成长用（DeepSeek 官方允许用输出训练模型）。
    隐私内容不存；回答时参考了 Claude 的内容（总结、聊天记录）也不存——Claude 的输出不进训练数据。
    联网查过的标上 web=true：里面的事实会过时，以后训练时可以只学"怎么答"、不背答案。"""
    if private or claude_ctx:
        return
    paths.TRAINING.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(), "event_id": eid, "label": label, "input": e_text, "output": reply, "source": "deepseek"}
    if web:
        rec["web"] = True
    with open(paths.TRAINING / "samples.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _quick(job, *a, **k):
    eid = _quick_event(*a, **k)
    if job is not None:
        job["eid"] = eid
    return eid


async def handle(text: str, src="qq", user="me", job=None, force=None, allow_private=False, redo_of=None):
    """job：界面上异步发消息时传进来，记下事件编号，界面拿它查处理到哪一步了。
    force：你指定交给谁（local / neu / ds / cl），跳过提醒、记住这些快捷处理，直接按你说的走（决策脑的分数照样算给你看）。
    隐私的事指定给云端要 allow_private（你确认过），不然抛 router.NeedConfirm。"""
    text = (text or "").strip()
    t0 = time.time()
    is_priv_kw = privacy.check(text)[0]

    # 1. 在回提醒？（你指定了去向就不走这些快捷处理）
    r = None if force else reminders.try_reply(text)
    if r:
        eid = _quick(job, text, src, "回应提醒", "这是在回应刚才的提醒，直接打卡或顺延，不经过模型。", r, is_priv_kw)
        HIST[user].extend([("user", text, is_priv_kw, t0), ("assistant", r, is_priv_kw, time.time())])
        return events.get(eid)

    # 1.5 在回"要不要训练"？
    g = None if force else growth.try_reply(text)
    if g:
        eid = _quick(job, text, src, "回应提醒", "这是在回答「要不要训练新小脑」，直接记下，不经过模型。", g, is_priv_kw)
        HIST[user].extend([("user", text, is_priv_kw, t0), ("assistant", g, is_priv_kw, time.time())])
        return events.get(eid)

    # 2. 设提醒？
    if not force and reminders.parse_command(text):
        reply = await reminders.create_from_text(text)
        eid = _quick(job, text, src, "设提醒", "认出了时间和事情，由程序直接建提醒，不经过模型（先斩后奏，写进报告）。", reply, is_priv_kw,
                           [["收到", SRC_LABEL.get(src, src)], ["认出提醒", "时间 + 事情"], ["新建提醒", "先斩后奏"], ["回复", "已回复"]])
        return events.get(eid)

    # 2.5 存到 Obsidian？（「存到笔记：……」「把刚才的回答存到笔记」）
    sv = None if force else obsidian.save_command(text)
    if sv is not None:
        reply = await _save_note(sv, user, src)
        eid = _quick(job, text, src, "存笔记", "你说了存到笔记，直接写进 Obsidian 库的「Agent 收件箱」（不经过模型，先斩后奏，能撤销）。", reply, is_priv_kw,
                     [["收到", SRC_LABEL.get(src, src)], ["认出「存到笔记」", "不经过模型"], ["写笔记", obsidian.inbox_name()], ["回复", "已回复"]])
        HIST[user].extend([("user", text, is_priv_kw, t0), ("assistant", reply, is_priv_kw, time.time())])
        return events.get(eid)

    # 3. 让我记东西？
    m = None if force else REMEMBER.match(text)
    if m and len(m.group(4).strip()) >= 2:
        done, _ = await memory.remember(m.group(4))
        reply = "记下了。" if done else "要写记忆文件，已放进「等你决定」。"
        eid = _quick(job, text, src, "记住", "你明确说了记住，直接写进记忆收件箱（本地文件，先斩后奏，可撤销）。", reply, is_priv_kw,
                           [["收到", SRC_LABEL.get(src, src)], ["认出「记住」", "不经过模型"], ["写记忆", "记忆/收件箱.md"], ["回复", "已回复"]])
        return events.get(eid)

    # 4. 决策脑两票（出错就退回简单规则，不让一条消息卡死）
    try:
        dec = await router.decide(text, force=force, allow_private=allow_private)
    except router.NeedConfirm:
        raise
    except Exception as e:
        print("决策脑出错，改用简单规则：", e)
        dec = await router.decide(text, vec=False, force=force, allow_private=allow_private)
    to_name = dec["brain_name"] if dec["ui_to"] == "local" else {"neu": "新类别", "ds": "DeepSeek", "cl": router.strong_name()}[dec["ui_to"]]
    steps = [["收到", SRC_LABEL.get(src, src)], ["决策脑打分", f"{to_name} {dec['conf']}%"]]
    fz = dec["votes"].get("forced")
    # 隐私的事你确认过要交给云端（界面上点了两次「换它重做」）：这一次放行，按安全线记一笔
    confirmed = bool(fz and allow_private and dec["private"] and dec["ui_to"] != "local")
    if fz:
        steps.append(["你指定了去向", f"交给 {to_name}" + (f"（重做事件 #{redo_of}）" if redo_of else "")])
        if redo_of:
            dec["votes"]["redo_of"] = redo_of
    eid = db.insert("events", {"ts": t0, "src": src, "user": user, "text": text, "private": int(dec["private"]), "route": dec["route"],
                               "ui_to": dec["ui_to"], "label": dec["brain_name"] or "", "conf": dec["conf"], "scores": dec["scores"],
                               "votes": {k: v for k, v in dec["votes"].items()}, "thresholds": dec["thresholds"],
                               "why": dec["why"] + " " + dec["vote_line"] + "。", "steps": steps, "status": "running",
                               "result": f"决策脑打完分，交给 {to_name}……"})
    if job is not None:
        job["eid"] = eid

    def prog(msg):
        """处理到哪一步，随时写进事件，界面（对话页）每半秒来看一次。"""
        with contextlib.suppress(Exception):
            db.update("events", eid, {"steps": steps, "result": msg})
    route, why_extra, reply, cost = dec["route"], "", "", 0.0
    qvec = None
    try:
        qv = await M.embed([text], instruct=MEM_INSTRUCT)
        qvec = qv[0] if qv else None
    except Exception:
        pass

    docs = []
    if memory.about_agent(text):
        docs = await memory.search_docs(qvec, text)
        if docs:
            steps.append(["查了说明书", f"{len(docs)} 段 · " + "、".join(sorted({d['file'].replace('@说明/', '').split('/')[-1].replace('.md', '') for d in docs}))[:40]])
            prog("查了说明书，正在回答……")

    # 查 Obsidian 笔记（和找记忆用同一个向量）
    notes = []
    if obsidian.on() and settings.S.get("obsRead", True):
        with contextlib.suppress(Exception):
            notes = await obsidian.search(qvec, text, k=4, allow_private=True)
    if notes:
        steps.append(["查了笔记", f"{len(notes)} 段 · {obsidian.titles(notes)}"[:60]])
        prog("查了笔记，正在回答……")
    priv_notes = [n for n in notes if n["private"]]

    is_local = dec["brain"] is not None
    if priv_notes and not is_local and dec["route"] in ("ds", "local") and not fz and M.ai_ready() and not M.yielding:
        # 用到了私人笔记：改交本地小脑（私人笔记不出本机）
        is_local, route, dec["brain_name"], dec["lora"] = True, "local", dec.get("brain_name") or "本地通用", None
        why_extra = f"（用到了私人笔记{obsidian.titles(priv_notes)}，只在本地处理）"
    if is_local and not dec["private"] and not priv_notes and settings.S.get("searchOn", True) and websearch.wants_fresh(text) and not docs:
        route, is_local = "ds", False
        why_extra = "（看着要查最新信息，本地小脑上不了网，改交 DeepSeek 联网搜）"
    if is_local and M.yielding and not dec["private"]:
        route, is_local = "ds", False
        why_extra = f"（让路模式：{M.yield_reason}，改交 DeepSeek）"
    if is_local:
        if M.yielding:
            reply = "显卡正忙（你在玩游戏或画图），这件事涉及隐私不能发给云端，我先记着，等显卡空了再回你。"
            db.update("events", eid, {"status": "queued", "result": "排队：让路模式", "reply": reply,
                                      "steps": steps + [["排队", "等显卡空出来"]]})
            _queue(eid)
            return events.get(eid)
        try:
            snips = await memory.search(qvec, allow_private=True)
            prog(f"{dec['brain_name']}正在回答……")
            out = await M.chat(_build(text, user, snips, True, docs, src, notes), lora=dec["lora"], max_new_tokens=400)
            reply = out["text"]
            steps.append(["本地处理", f"{dec['brain_name']} · {out['tokens']} 个 token · {out['tok_per_s']}/秒"])
            if snips:
                steps.append(["用了记忆", f"{len(snips)} 段"])
        except Exception as e:
            if dec["private"] or (priv_notes and why_extra.startswith("（用到了私人笔记")):
                reply = f"本地模型还没准备好（{str(e)[:60]}）。这件事涉及隐私，不发给云端，等本地模型装好后我再处理。"
                db.update("events", eid, {"status": "queued", "result": f"本地模型不可用：{e}", "reply": reply,
                                          "steps": steps + [["排队", "本地模型不可用"]]})
                _queue(eid)
                return events.get(eid)
            route = "ds"
            why_extra = f"（本地模型不可用：{str(e)[:60]}，改交 DeepSeek）"

    if route == "ds":
        try:
            mode = settings.S["dsThinking"]
            thinking = mode == "on" or (mode == "auto" and (dec.get("hard", dec["p"].get("cl", 0)) > 0.25 or len(text) > 150))
            snips = await memory.search(qvec, allow_private=False)
            pub_notes = [n for n in notes if not n["private"]]
            if priv_notes:
                steps.append(["私人笔记没发出去", f"{len(priv_notes)} 段只给本地小脑"])
            msgs = _build(text, user, snips, False, docs, src, pub_notes)
            note_tools = obsidian.tools_on()
            prog("交给 DeepSeek，正在想……")
            purpose = "neu" if dec["neu"] else "chat"
            web = None
            if (settings.S.get("searchOn", True) or note_tools) and not dec["private"]:
                web = await websearch.answer_with_tools(msgs, thinking=thinking, event_id=eid, purpose=purpose, user_text=text, steps=steps,
                                                        progress=prog, web=bool(settings.S.get("searchOn", True)), notes=note_tools)
                out = {"text": web["text"], "cny": web["cny"]}
            else:
                if confirmed:
                    safety.log("privacy.send", {"event": eid, "to": "DeepSeek"}, "user")
                    steps.append(["你确认了发出本机", "隐私内容这一次交给 DeepSeek（不联网搜、不进训练）"])
                out = await deepseek.chat(msgs, thinking=thinking, private=dec["private"] and not confirmed, event_id=eid, purpose=purpose)
            searched = bool(web and (web["searched"] or web["fetched"]))
            cost_all = out["cny"] + (websearch.PRICE_USD * float(settings.S["usdCny"]) * (web["searched"] + web["fetched"]) if web else 0)
            reply, cost = out["text"], cost_all
            steps.append(["交给 DeepSeek", f"{'思考' if thinking else '快速'}模式" + (f" · 联网 {web['searched']} 搜 {web['fetched']} 读" if searched else "") + f" · ¥{cost_all:.4f}"])
            used_claude = any(s.get("claude") for s in snips)
            _save_sample(text, reply, "neu" if dec["neu"] else "ds", eid, dec["private"], used_claude, searched)
            if used_claude:
                steps.append(["不进训练集", "参考了 Claude 的总结"])
            if dec["neu"] and not used_claude and not dec["private"]:
                steps.append(["记为样本", "新类别，攒够了训练新小脑"])
        except deepseek.NoBalance:
            reply = "DeepSeek 余额不足，充值后就能继续（platform.deepseek.com）。这件事我先不处理。"
        except deepseek.NoKey:
            reply = "还没填 DeepSeek API Key，这件事我暂时答不了（设置 › 云端）。"
        except Exception as e:
            reply = f"DeepSeek 这次没回上来：{str(e)[:80]}"
    elif route == "cl":
        sn = router.strong_name()
        prompt = await _claude_prompt(text, dec["private"], eid)
        reply = (f"这件事比较复杂，建议你带着下面的提示词去问{sn}（你能用的最强的 AI 都行）。聊完让它出一份 Markdown 总结，"
                 f"带回来在 界面 › 大脑 › {sn} › 导入总结。\n\n" + prompt)
        steps.append(["写提示词", "DeepSeek 附上背景" if not dec["private"] else "本地模板（涉及隐私）"])

    steps.append(["回复", "已回复" if reply else "没有回复"])
    db.update("events", eid, {"route": route, "ui_to": dec["ui_to"] if route == dec["route"] else route, "result": reply[:2000], "reply": reply,
                              "cost": cost, "latency": time.time() - t0, "status": "done", "steps": steps,
                              "why": dec["why"] + why_extra + " " + dec["vote_line"] + "。"})
    HIST[user].extend([("user", text, dec["private"], t0), ("assistant", reply, dec["private"], time.time())])
    return events.get(eid)


async def _save_note(sv, user, src):
    """「存到笔记」：写进 Obsidian 库的 Agent 收件箱。没写内容、说的是「刚才的回答」，就存上一条回复。"""
    body, use_last = sv
    if use_last and not body:
        last = next((c for role, c, _p, _t in reversed(HIST[user]) if role == "assistant"), "")
        body = last
    if not body.strip():
        return "要存什么？在「存到笔记：」后面写内容；或者先问我一句，再说「把刚才的回答存到笔记」。"
    if not obsidian.on():
        return "还没接 Obsidian 库：设置 › Obsidian 笔记 里加一个库。"
    title = re.sub(r"\s+", " ", body.strip().splitlines()[0])[:24]
    try:
        done, info = await obsidian.write("", f"{time.strftime('%Y-%m-%d %H%M')} {title}", obsidian.note_text(title, body, SRC_LABEL.get(src, src)),
                                          "你让我存进笔记")
    except PermissionError as e:
        return f"没存：{e}"
    return f"存好了：{info}（在 Obsidian 里能看到，不想要可以在 报告 › 改动 里撤销）" if done else "要写笔记，已放进「等你决定」。"


async def _claude_prompt(text, private, eid):
    tpl = settings.S["claudeTpl"]
    if private:
        return f"{tpl}\n\n我的问题：{text}"
    try:
        out = await deepseek.chat([{"role": "system", "content": "你帮用户写一段发给更强的 AI 模型（比如网页 Claude、ChatGPT）的提示词：交代背景、目标、约束、希望得到的输出（结尾要求输出 Markdown 总结）。只输出提示词本身，300 字以内。"},
                                   {"role": "user", "content": f"开头用这句：{tpl}\n\n用户的问题：{text}"}], purpose="claude_prompt", event_id=eid)
        prompt = out["text"]
    except Exception:
        prompt = f"{tpl}\n\n我的问题：{text}"
    lst = db.kv_get("claude_prompts", []) or []
    lst.append({"event_id": eid, "prompt": prompt, "ts": time.time(), "done": False})
    db.kv_set("claude_prompts", lst[-30:])
    return prompt


def _queue(eid):
    q = db.kv_get("queue", []) or []
    if eid not in q:
        q.append(eid)
    db.kv_set("queue", q)


async def process_queue():
    """让路模式结束、本地模型能用了，就把排队的隐私事情处理掉，结果通过 QQ 发给你。"""
    q = db.kv_get("queue", []) or []
    if not q or M.yielding or not M.ai_ready():
        return
    rest = []
    for eid in q:
        e = db.one("SELECT * FROM events WHERE id=?", (eid,))
        if not e or e["status"] != "queued":
            continue
        try:
            snips = []
            out = await M.chat(_build(e["text"], e["user"] or "me", snips, True, None, e["src"]), lora=None, max_new_tokens=400)
            reply = out["text"]
            steps = db.jl(e["steps"], []) + [["本地处理", "排队后处理"], ["回复", "已通过 QQ 发给你"]]
            db.update("events", eid, {"status": "done", "reply": reply, "result": reply, "steps": steps})
            if e["src"] == "qq":
                await notify.say(plain(f"（刚才排队的事）{e['text'][:20]}…\n{reply}"))
        except Exception:
            rest.append(eid)
    db.kv_set("queue", rest)


async def on_qq(text, openid, msg_id):
    ev = await handle(text, "qq", openid)
    if ev and ev.get("reply"):
        ok, info = await BOT.reply(openid, plain(ev["reply"]), msg_id)
        if not ok:
            db.update("events", ev["id"], {"result": (ev.get("result") or "") + f"\n（QQ 回复失败：{info}）"})


BOT.on_message = on_qq
_ = asyncio
