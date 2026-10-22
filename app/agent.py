"""处理一条消息的全过程：先看是不是在回提醒、设提醒、让我记东西（这些不用模型）；
其余的过决策脑两票，交给本地小脑 / DeepSeek / 建议找网页 Claude；每一步都写进事件日志。"""
import asyncio
import json
import re
import time
from collections import defaultdict, deque

from . import db, deepseek, events, growth, memory, notify, paths, privacy, reminders, router, settings
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


def _build(text, user, snips, allow_private):
    sys = memory.persona()
    if snips:
        sys += "\n\n下面是他的记忆文件里和这条消息相关的内容，用得上就用，用不上别提：\n" + "\n".join(f"- {m['text']}" for m in snips)
    return [{"role": "system", "content": sys}] + _history(user, allow_private) + [{"role": "user", "content": text}]


def _quick_event(text, src, label, why, reply, private=False, steps=None):
    eid = db.insert("events", {"ts": time.time(), "src": src, "text": text, "private": int(private), "route": "local", "ui_to": "local",
                               "label": label, "conf": 100, "scores": {"local": 100, "neu": 0, "ds": 0, "cl": 0}, "why": why,
                               "steps": steps or [["收到", SRC_LABEL.get(src, src)], ["本地处理", label], ["回复", "已回复"]],
                               "result": reply, "reply": reply, "status": "done"})
    return eid


def _save_sample(e_text, reply, label, eid, private, claude_ctx=False):
    """存 DeepSeek 的处理记录给慢成长用（DeepSeek 官方允许用输出训练模型）。
    隐私内容不存；回答时参考了 Claude 的内容（总结、聊天记录）也不存——Claude 的输出不进训练数据。"""
    if private or claude_ctx:
        return
    paths.TRAINING.mkdir(parents=True, exist_ok=True)
    with open(paths.TRAINING / "samples.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "event_id": eid, "label": label, "input": e_text, "output": reply,
                            "source": "deepseek"}, ensure_ascii=False) + "\n")


async def handle(text: str, src="qq", user="me"):
    text = (text or "").strip()
    t0 = time.time()
    is_priv_kw = privacy.check(text)[0]

    # 1. 在回提醒？
    r = reminders.try_reply(text)
    if r:
        eid = _quick_event(text, src, "回应提醒", "这是在回应刚才的提醒，直接打卡或顺延，不经过模型。", r, is_priv_kw)
        HIST[user].extend([("user", text, is_priv_kw, t0), ("assistant", r, is_priv_kw, time.time())])
        return events.get(eid)

    # 1.5 在回"要不要训练"？
    g = growth.try_reply(text)
    if g:
        eid = _quick_event(text, src, "回应提醒", "这是在回答「要不要训练新小脑」，直接记下，不经过模型。", g, is_priv_kw)
        HIST[user].extend([("user", text, is_priv_kw, t0), ("assistant", g, is_priv_kw, time.time())])
        return events.get(eid)

    # 2. 设提醒？
    if reminders.parse_command(text):
        reply = await reminders.create_from_text(text)
        eid = _quick_event(text, src, "设提醒", "认出了时间和事情，由程序直接建提醒，不经过模型（先斩后奏，写进报告）。", reply, is_priv_kw,
                           [["收到", SRC_LABEL.get(src, src)], ["认出提醒", "时间 + 事情"], ["新建提醒", "先斩后奏"], ["回复", "已回复"]])
        return events.get(eid)

    # 3. 让我记东西？
    m = REMEMBER.match(text)
    if m and len(m.group(4).strip()) >= 2:
        done, _ = await memory.remember(m.group(4))
        reply = "记下了。" if done else "要写记忆文件，已放进「等你决定」。"
        eid = _quick_event(text, src, "记住", "你明确说了记住，直接写进记忆收件箱（本地文件，先斩后奏，可撤销）。", reply, is_priv_kw,
                           [["收到", SRC_LABEL.get(src, src)], ["认出「记住」", "不经过模型"], ["写记忆", "记忆/收件箱.md"], ["回复", "已回复"]])
        return events.get(eid)

    # 4. 决策脑两票（出错就退回简单规则，不让一条消息卡死）
    try:
        dec = await router.decide(text)
    except Exception as e:
        print("决策脑出错，改用简单规则：", e)
        dec = await router.decide(text, vec=False)
    to_name = dec["brain_name"] if dec["ui_to"] == "local" else {"neu": "新类别", "ds": "DeepSeek", "cl": "网页 Claude"}[dec["ui_to"]]
    steps = [["收到", SRC_LABEL.get(src, src)], ["决策脑打分", f"{to_name} {dec['conf']}%"]]
    eid = db.insert("events", {"ts": t0, "src": src, "user": user, "text": text, "private": int(dec["private"]), "route": dec["route"],
                               "ui_to": dec["ui_to"], "label": dec["brain_name"] or "", "conf": dec["conf"], "scores": dec["scores"],
                               "votes": {k: v for k, v in dec["votes"].items()}, "thresholds": dec["thresholds"],
                               "why": dec["why"] + " " + dec["vote_line"] + "。", "steps": steps, "status": "running"})
    route, why_extra, reply, cost = dec["route"], "", "", 0.0
    qvec = None
    try:
        qv = await M.embed([text], instruct=MEM_INSTRUCT)
        qvec = qv[0] if qv else None
    except Exception:
        pass

    is_local = dec["brain"] is not None
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
            out = await M.chat(_build(text, user, snips, True), lora=dec["lora"], max_new_tokens=400)
            reply = out["text"]
            steps.append(["本地处理", f"{dec['brain_name']} · {out['tokens']} 个 token · {out['tok_per_s']}/秒"])
            if snips:
                steps.append(["用了记忆", f"{len(snips)} 段"])
        except Exception as e:
            if dec["private"]:
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
            thinking = mode == "on" or (mode == "auto" and (dec["p"].get("cl", 0) > 0.25 or len(text) > 150))
            snips = await memory.search(qvec, allow_private=False)
            out = await deepseek.chat(_build(text, user, snips, False), thinking=thinking, private=dec["private"], event_id=eid,
                                      purpose="neu" if dec["neu"] else "chat")
            reply, cost = out["text"], out["cny"]
            steps.append(["交给 DeepSeek", f"{'思考' if thinking else '快速'}模式 · ¥{out['cny']:.4f}"])
            used_claude = any(s.get("claude") for s in snips)
            _save_sample(text, reply, "neu" if dec["neu"] else "ds", eid, dec["private"], used_claude)
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
        prompt = await _claude_prompt(text, dec["private"], eid)
        reply = ("这件事比较复杂，建议你带着下面的提示词去问网页 Claude。聊完让它出一份 Markdown 总结，"
                 "带回来在 界面 › 大脑 › 网页 Claude › 导入总结。\n\n" + prompt)
        steps.append(["写提示词", "DeepSeek 附上背景" if not dec["private"] else "本地模板（涉及隐私）"])

    steps.append(["回复", "已回复" if reply else "没有回复"])
    db.update("events", eid, {"route": route, "ui_to": dec["ui_to"] if route == dec["route"] else route, "result": reply[:2000], "reply": reply,
                              "cost": cost, "latency": time.time() - t0, "status": "done", "steps": steps,
                              "why": dec["why"] + why_extra + " " + dec["vote_line"] + "。"})
    HIST[user].extend([("user", text, dec["private"], t0), ("assistant", reply, dec["private"], time.time())])
    return events.get(eid)


async def _claude_prompt(text, private, eid):
    tpl = settings.S["claudeTpl"]
    if private:
        return f"{tpl}\n\n我的问题：{text}"
    try:
        out = await deepseek.chat([{"role": "system", "content": "你帮用户写一段发给 Claude 的提示词：交代背景、目标、约束、希望得到的输出（结尾要求输出 Markdown 总结）。只输出提示词本身，300 字以内。"},
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
            out = await M.chat(_build(e["text"], e["user"] or "me", snips, True), lora=None, max_new_tokens=400)
            reply = out["text"]
            steps = db.jl(e["steps"], []) + [["本地处理", "排队后处理"], ["回复", "已通过 QQ 发给你"]]
            db.update("events", eid, {"status": "done", "reply": reply, "result": reply, "steps": steps})
            if e["src"] == "qq":
                await notify.say(f"（刚才排队的事）{e['text'][:20]}…\n{reply}")
        except Exception:
            rest.append(eid)
    db.kv_set("queue", rest)


async def on_qq(text, openid, msg_id):
    ev = await handle(text, "qq", openid)
    if ev and ev.get("reply"):
        ok, info = await BOT.reply(openid, ev["reply"], msg_id)
        if not ok:
            db.update("events", ev["id"], {"result": (ev.get("result") or "") + f"\n（QQ 回复失败：{info}）"})


BOT.on_message = on_qq
_ = asyncio
