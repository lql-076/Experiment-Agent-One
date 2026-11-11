"""处理一条消息的全过程：先看是不是在回提醒、设提醒、让我记东西（这些不用模型）；
其余的过决策脑两票，交给本地小脑 / DeepSeek / 建议你带提示词去问更强的模型；每一步都写进事件日志。
你也可以推翻决策脑：force 指定去向（界面上「换它重做」），redo_of 记下是哪一条重做的。
交给 DeepSeek 的，带上联网搜索工具（app/websearch.py）、读文件的工具（app/files.py，只读你允许的文件夹）和它自己工作文件夹的工具
（app/workspace.py，v2.1：在里面写、改、删、挪、运行程序），要不要用由它自己定；
问到 agent 自己怎么用的，先从说明书（docs/操作手册.md、docs/AI文档）里找相关段落一起给模型。
v1.8.17：消息能带图片（界面上粘贴 / 选 / 拖进来），交给 DeepSeek 看（本地小脑看不了图）；消息里贴了路径的，程序直接读出来。"""
import asyncio
import contextlib
import json
import re
import time
from collections import defaultdict, deque
from pathlib import Path

from . import agentkit, ccode, db, deepseek, events, files, growth, memory, notify, paths, privacy, reminders, router, safety, settings, websearch, workspace
from .models import M
from .qq import BOT

MEM_INSTRUCT = "Given a user message, retrieve personal notes and memories that help answer it"
REMEMBER = re.compile(r"^(请)?(帮我)?(记住|记一下|记下来|记下|帮我记)[：:，, ]*(.+)$", re.S)
HIST = defaultdict(lambda: deque(maxlen=8))   # 每个人最近几轮：(role, content, private, ts)
# v2.2：同一件工作区的事，后面说「继续 / 接着做 / 开始第 2 步」沿用上一条的去向和工具，并告诉 DeepSeek 上次做到哪
CONT_RE = re.compile(r"^(好的?|好吧|ok|嗯+|行|可以)?[，,。.！! ]*(继续|接着|下一步|开始第.{1,3}步|做第.{1,3}步|第.{1,3}步|再试|重试|往下|go\s*on|continue)", re.I)
LAST_WS = {}                                  # user -> {"ts", "note"}：上一件动了工作区的事
WS_STEPS = {"写文件", "改文件", "删除", "挪", "复制", "运行", "工作区", "读文件", "列目录", "认出写成文字的工具调用", "工具调用没成"}


def _continuing(user, text) -> bool:
    w = LAST_WS.get(user)
    return bool(w and time.time() - w["ts"] < 7200 and len(text) <= 40 and CONT_RE.search(text.strip()))


def _remember_ws(user, steps, reply, cc=None):
    done = [f"- {x[0]} {x[1]}" for x in steps if x and x[0] in WS_STEPS][-15:]
    LAST_WS[user] = {"ts": time.time(), "cc": bool(cc), "session": (cc or {}).get("session"), "note": "【接着上一件事：你上次在工作文件夹里做到这里（最后几步）：\n" + "\n".join(done) +
                     f"\n你上次最后说的：{reply[:300]}\n这件事的文件夹里有 进度.md 的话先读它，从没做完的地方接着做，不要从头来。】"}
SRC_LABEL = {"qq": "QQ 私聊", "ui": "界面输入", "cron": "定时任务"}
# 问能不能给 agent 加功能（「能不能加个导出的功能」「你能不能支持读 PDF」）：本地小脑以前会答成"系统限制，没法加"
WISH_RE = re.compile(r"(能不能|可不可以|可以|能否)(给你|帮你|让你|给它|在你这)?(加|做|新增|增加|添加|支持|实现|弄)(一?个|上|出)?.{0,24}"
                     r"(功能|按钮|页面|窗口|选项|开关|设置|模式)|"
                     r"(加|做|添加|新增)一?个.{0,24}(功能|按钮|页面|窗口|选项|开关)(吧|呗|好不好|行不行|怎么样|\?|？)|"
                     r"(你|它)(能不能|可不可以|会不会)(支持|实现)")
WISH_NOTE = ("（他在问能不能给你——这个 agent——加功能或改功能。先对照上面说明书里的段落：已经有的，告诉他在界面哪里点；"
             "没有的，老实说「现在还没有，这要改代码才能加，我已经记进「想要的功能」，开发的时候会看到」。"
             "不要说「系统限制」「做不到」「不支持」这类话，也不要假装已经能做。）")


class Steps(list):
    """每一步带上离收到消息过了多少秒（第三项），「这条怎么处理的」按它排时间线。"""

    def __init__(self, t0, items=()):
        super().__init__()
        self.t0 = t0
        self.extend(items)

    def append(self, x):
        x = list(x)
        if len(x) == 2:
            x.append(round(time.time() - self.t0, 3))
        super().append(x)

    def extend(self, xs):
        for x in xs:
            self.append(x)


def note_wish(text, eid):
    """记进「想要的功能」（kv wishes，最多留 200 条），报告里能看到，开发窗口排期时看。"""
    w = db.kv_get("wishes", []) or []
    w.append({"ts": time.time(), "text": text[:300], "event": eid})
    db.kv_set("wishes", w[-200:])


def _history(user, allow_private):
    now = time.time()
    out = []
    for role, content, priv, ts in HIST[user]:
        if now - ts > 1800 or (priv and not allow_private):
            continue
        out.append({"role": role, "content": content})
    return out


VOICE_PLAIN = "\n这条回复会被念出来给他听：像说话一样回答，简短（三四句以内），不要用列表、表格、代码、链接、Markdown 记号；要给长内容就说一句结论，告诉他细节在屏幕上。"
QQ_PLAIN = "\n这条回复会发到 QQ 私聊，QQ 不显示格式：不要用 **、#、- 列表、表格、代码块这些符号，用纯文字和换行；链接直接写网址。"


def plain(t: str) -> str:
    """发到 QQ 前去掉 Markdown 符号（模型偶尔还是会写），QQ 里看到的是干净的文字。"""
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t or "")
    t = re.sub(r"(?m)^#{1,6}\s*", "", t)
    t = re.sub(r"(?m)^(\s*)[-*]\s+", r"\1· ", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1 \2", t)
    return t.replace("```", "")


def _build(text, user, snips, allow_private, docs=None, src="ui", extra="", images=None):
    d = time.localtime()
    sys = memory.persona() + f"\n现在是 {d.tm_year} 年 {d.tm_mon} 月 {d.tm_mday} 日 {d.tm_hour:02d}:{d.tm_min:02d}（星期{'一二三四五六日'[d.tm_wday]}）。" + (QQ_PLAIN if src == "qq" else VOICE_PLAIN if src == "voice" else "")
    if snips:
        sys += "\n\n下面是他的记忆文件里和这条消息相关的内容，用得上就用，用不上别提：\n" + "\n".join(f"- {m['text']}" for m in snips)
    if docs:
        sys += ("\n\n下面是你自己（这个 agent）的说明书里和这条消息相关的段落。回答关于你自己能做什么、怎么用、在哪设置的问题时，以它为准，"
                "说清楚在界面哪里点：\n" + "\n".join(f"- 〔{m['file'].replace('@说明/', '')}〕{m['text']}" for m in docs))
    body = text + ("\n\n" + extra if extra else "")
    if images:                                          # 带图片：content 换成列表（DeepSeek 看图的写法）
        body = [{"type": "text", "text": body or "看看这张图。"}] + [{"type": "image_url", "image_url": {"url": u}} for u in images]
    return [{"role": "system", "content": sys}] + _history(user, allow_private) + [{"role": "user", "content": body}]


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


async def handle(text: str, src="qq", user="me", job=None, force=None, allow_private=False, redo_of=None, images=None, received=None, engine=None):
    """job：界面上异步发消息时传进来，记下事件编号，界面拿它查处理到哪一步了。
    force：你指定交给谁（local / neu / ds / cl），跳过提醒、记住这些快捷处理，直接按你说的走（决策脑的分数照样算给你看）。
    隐私的事指定给云端要 allow_private（你确认过），不然抛 router.NeedConfirm。
    images：这条消息带的图片（已经存进 data\\chat 的，files.save_upload 的结果或路径）。
    received：对话里发来的文件（v2.2，已经存进 工作区\\收到的\\，workspace.received 的结果）。
    engine：你指定用哪个执行引擎（v3.0：cc = 交给本地的 Claude Code 去做；不指定就看设置）。"""
    text = (text or "").strip()
    t0 = time.time()
    is_priv_kw = privacy.check(text)[0]
    images = [x if isinstance(x, dict) else {"path": str(x)} for x in (images or [])]
    ments = await asyncio.to_thread(files.mentioned, text)
    denied = [m for m in ments if m["exists"] and not m["allowed"]]
    if denied and not any(m["allowed"] for m in ments):
        m = denied[0]
        folder = m["path"] if m["is_dir"] else str(Path(m["path"]).parent)
        if m["why"]:
            reply = f"「{m['raw']}」我不读：{m['why']}。"
            st = [["收到", SRC_LABEL.get(src, src)], ["不读", m["why"]], ["回复", "已回复"]]
        else:
            reply = (f"「{folder}」这个文件夹还没允许我读。点下面的「允许读这个文件夹」，或者到 设置 › 记忆与文件 ›「能读的文件夹」加上它"
                     "（只读，不改、不删），我再接着看。")
            st = [["收到", SRC_LABEL.get(src, src)], ["没有权限", folder], ["回复", "已回复"]]
        eid = _quick(job, text, src, "读文件", "消息里贴的路径不在能读的文件夹里：要你先允许（给 agent 加权限只能你点）。", reply, is_priv_kw, st)
        for im in images:
            files.note(eid, "img", im["path"])
        HIST[user].extend([("user", text, is_priv_kw, t0), ("assistant", reply, is_priv_kw, time.time())])
        return events.get(eid)

    # 1. 在回提醒？（你指定了去向就不走这些快捷处理）
    r = None if force or images or received else reminders.try_reply(text)
    if r:
        eid = _quick(job, text, src, "回应提醒", "这是在回应刚才的提醒，直接打卡或顺延，不经过模型。", r, is_priv_kw)
        HIST[user].extend([("user", text, is_priv_kw, t0), ("assistant", r, is_priv_kw, time.time())])
        return events.get(eid)

    # 1.5 在回"要不要训练"？
    g = None if force or images or received else growth.try_reply(text)
    if g:
        eid = _quick(job, text, src, "回应提醒", "这是在回答「要不要训练新小脑」，直接记下，不经过模型。", g, is_priv_kw)
        HIST[user].extend([("user", text, is_priv_kw, t0), ("assistant", g, is_priv_kw, time.time())])
        return events.get(eid)

    # 2. 设提醒？
    if not force and not images and not received and reminders.parse_command(text):
        reply = await reminders.create_from_text(text)
        eid = _quick(job, text, src, "设提醒", "认出了时间和事情，由程序直接建提醒，不经过模型（先斩后奏，写进报告）。", reply, is_priv_kw,
                           [["收到", SRC_LABEL.get(src, src)], ["认出提醒", "时间 + 事情"], ["新建提醒", "先斩后奏"], ["回复", "已回复"]])
        return events.get(eid)

    # 3. 让我记东西？
    m = None if force or images or received or workspace.to_file(text) else REMEMBER.match(text)      # 「记到某个文件夹里」是要写文件（v2.1），不进记忆
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
    vt = dec["votes"]
    steps = Steps(t0, [["收到", SRC_LABEL.get(src, src)]])
    if vt.get("mode") != "rules" or vt.get("embed_why") or vt.get("kev_why"):
        steps.append(["语义路由", vt.get("embed_txt") or ("没投票：" + (vt.get("embed_why") or "?"))])
        steps.append(["Kev", vt.get("kev_txt") or ("没投票：" + (vt.get("kev_why") or "?"))])
    steps.append(["决策脑打分", f"{to_name} {dec['conf']}%" + ("（只有一票，打了八折）" if vt.get("single") else "")])
    fz = vt.get("forced")
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
    agentkit.open_ctl(eid, user)                  # v3.0：这件事的开关（喊停、插话、计划）
    try:
        return await _handle2(text, src, user, t0, eid, dec, steps, images, received, fz, confirmed, ments, engine)
    finally:
        agentkit.close_ctl(eid)


async def _handle2(text, src, user, t0, eid, dec, steps, images, received, fz, confirmed, ments, engine):
    for im in images:
        files.note(eid, "img", im["path"], size=im.get("size"))
    if images:
        steps.append(["收到图片", f"{len(images)} 张"])
    received = received or []
    for x in received:
        files.note(eid, "dir" if x.get("dir") else "file", x["path"], x["name"], x["size"])
    if received:
        nd = sum(1 for x in received if x.get("dir"))
        steps.append(["收到文件", (f"{nd} 个文件夹 · " if nd else "") + (f"{len(received) - nd} 个文件 · " if len(received) > nd else "") +
                      f"放进了工作区 {Path(received[0]['rel']).parent}"])
    recv_txt = workspace.recv_note(received)

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

    is_local = dec["brain"] is not None
    readable = [m for m in ments if m["exists"] and m["allowed"]]
    pic_file = any(not m["is_dir"] and files.kind_of(Path(m["path"])) == "image" for m in readable)
    wish_extra = ""
    if not fz and WISH_RE.search(text):
        wish_extra = WISH_NOTE
        note_wish(text, eid)
        steps.append(["记进想要的功能", "开发的时候会看到"])
        if not docs:
            docs = await memory.search_docs(qvec, text)
            if docs:
                steps.append(["查了说明书", f"{len(docs)} 段"])
    if wish_extra and is_local and not dec["private"]:
        route, is_local = "ds", False
        why_extra = "（在问能不能给我加功能：要对照说明书、老实说要不要改代码，本地小脑答不好，交给 DeepSeek）"
    elif is_local and not dec["private"] and not fz and (images or pic_file):
        route, is_local = "ds", False
        why_extra = "（带了图片，本地小脑看不了图，交给 DeepSeek 看）"
    elif is_local and not dec["private"] and not fz and received:
        route, is_local = "ds", False
        why_extra = "（发来了文件，已经放进工作文件夹，本地小脑不会用工具，交给 DeepSeek）"
    elif is_local and not dec["private"] and not fz and any(m["cloud"] for m in readable):
        route, is_local = "ds", False
        why_extra = "（要看你贴的文件 / 文件夹，本地小脑不会翻文件，交给 DeepSeek 带着读文件的工具）"
    elif is_local and not dec["private"] and not fz and workspace.wants(text):
        route, is_local = "ds", False
        why_extra = "（要在工作文件夹里写文件、运行程序，本地小脑不会用工具，交给 DeepSeek）"
    elif is_local and not dec["private"] and not fz and files.wants(text):
        route, is_local = "ds", False
        why_extra = "（要查你电脑上的资料，本地小脑不会翻文件，交给 DeepSeek 带着读文件的工具）"
    cont = _continuing(user, text) and not dec["private"] and not fz
    if engine == "cc" and not dec["private"] and route != "ds":
        route, is_local = "ds", False
        why_extra = "（你指定交给 Claude Code 去做）"
    if cont and (is_local or route == "cl"):
        route, is_local = "ds", False
        why_extra = "（接着上一件工作区的事做，交给 DeepSeek 带着同样的工具）"
    if not is_local and route == "ds" and any(not m["cloud"] for m in readable):
        route, is_local = dec["brain"] or "local", True
        dec["brain_name"] = dec["brain_name"] or "本地通用"
        why_extra = "（你贴的文件所在的文件夹设成了只给本地小脑看，不发给 DeepSeek）"
    if is_local and not dec["private"] and settings.S.get("searchOn", True) and websearch.wants_fresh(text) and not docs and not readable:
        route, is_local = "ds", False
        why_extra = "（看着要查最新信息，本地小脑上不了网，改交 DeepSeek 联网搜）"
    if why_extra:
        steps.append(["按本事分", why_extra.strip("（）")])
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
            extra, _, used = await asyncio.to_thread(files.attach, readable, True)
            if recv_txt:
                extra += "\n\n" + recv_txt[:3000]
            _note_reads(eid, used, steps, "你贴的路径，程序读给本地小脑")
            if images:
                extra += f"\n\n（他附了 {len(images)} 张图片，但这件事只在本地处理，你看不了图：直接告诉他看不了，请他用文字描述。）"
                steps.append(["看不了图", "涉及隐私不发云端，本地小脑看不了图"])
            prog(f"{dec['brain_name']}正在回答……")
            out = await M.chat(_build(text, user, snips, True, docs, src, extra + wish_extra), lora=dec["lora"], max_new_tokens=400)
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
            thinking = mode == "on" or (mode == "auto" and (dec.get("hard", dec["p"].get("cl", 0)) > 0.25 or len(text) > 150))
            snips = await memory.search(qvec, allow_private=False)
            extra, pics, used = await asyncio.to_thread(files.attach, [m for m in readable if m["cloud"]], False)
            if recv_txt:
                extra += "\n\n" + recv_txt
            if cont:
                extra += "\n\n" + LAST_WS[user]["note"]
                steps.append(["接着上一件事", "带上了上次在工作区做到哪"])
            _note_reads(eid, used, steps, "你贴的路径，程序读出来一起发")
            uris = [await asyncio.to_thread(files.uri_of, im["path"]) for im in images] + [x["uri"] for x in pics]
            msgs = _build(text, user, snips, False, docs, src, extra + wish_extra, uris)
            prog("交给 DeepSeek，正在看图……" if uris else "交给 DeepSeek，正在想……")
            purpose = "neu" if dec["neu"] else "chat"
            web = None
            last = LAST_WS.get(user) or {}
            use_cc = ccode.usable() and not dec["private"] and engine != "ds" and (engine == "cc" or (settings.S.get("ccAuto", True) and engine is None and (
                workspace.wants(text) or bool(received) or (cont and last.get("cc")))))
            if use_cc:
                # v3.0：整件事交给他本地的 Claude Code（在工作区里干活，每一步进事件）；出不来就退回 DeepSeek 自己带工具做
                sess = last.get("session") if cont and last.get("cc") else None
                steps.append(["执行引擎", "Claude Code" + ("（接着上次的会话）" if sess else "")])
                prog("交给 Claude Code，正在开工……")
                try:
                    cc = await ccode.run(eid, text, steps, prog, session=sess, extra=extra)
                    web = {"text": cc["text"] or "Claude Code 做完了，但没说话。", "cny": 0.0, "searched": 0, "fetched": 0, "read": 0, "ws": max(1, cc["tools"]),
                           "sources": [], "cc": cc}
                    out = {"text": web["text"], "cny": 0.0}
                except RuntimeError as e:
                    steps.append(["执行引擎", f"Claude Code 没成，改回 DeepSeek 自己做：{str(e)[:60]}"])
                    use_cc = False
            use_web = bool(settings.S.get("searchOn", True))
            use_files = bool(files.dirs(True))
            use_ws = workspace.on()                       # Agent 自己的工作文件夹（v2.1）：写、改、删、挪、运行程序
            if use_cc:
                pass
            elif (use_web or use_files or use_ws) and not dec["private"]:
                web = await websearch.answer_with_tools(msgs, thinking=thinking, event_id=eid, purpose=purpose, user_text=text, steps=steps,
                                                        progress=prog, web=use_web, local_files=use_files, ws=use_ws)
                out = {"text": web["text"], "cny": web["cny"]}
            else:
                if confirmed:
                    safety.log("privacy.send", {"event": eid, "to": "DeepSeek"}, "user")
                    steps.append(["你确认了发出本机", "隐私内容这一次交给 DeepSeek（不联网搜、不进训练）"])
                out = await deepseek.chat(msgs, thinking=thinking, private=dec["private"] and not confirmed, event_id=eid, purpose=purpose)
            searched = bool(web and (web["searched"] or web["fetched"]))
            cost_all = out["cny"] + (websearch.PRICE_USD * float(settings.S["usdCny"]) * (web["searched"] + web["fetched"]) if web else 0)
            reply, cost = out["text"], cost_all
            if web and web.get("ws"):
                _remember_ws(user, steps, reply, web.get("cc"))
                made = await asyncio.to_thread(workspace.note_made, eid, t0)      # v2.3：这件事做出来的文件，回复下面给卡片
                if made["n"]:
                    first = (made["media"] or made["folders"] or made["others"])[0]["name"]
                    steps.append(["做好的文件", f"{first}" + (f" 等 {made['n']} 个" if made["n"] > 1 else "")])
            if web and web.get("cc"):
                steps.append(["交给 Claude Code", f"{web['cc']['turns']} 轮 · {web['cc']['tools']} 次工具（花的钱看 DeepSeek 账单）"])
            else:
                steps.append(["交给 DeepSeek", f"{'思考' if thinking else '快速'}模式" + (f" · 联网 {web['searched']} 搜 {web['fetched']} 读" if searched else "") +
                              (f" · 工作区 {web['ws']} 步" if web and web.get("ws") else "") + f" · ¥{cost_all:.4f}"])
            used_claude = any(s.get("claude") for s in snips)
            if not (uris or used or (web and (web.get("read") or web.get("ws")))):        # 带图片、读了文件、动了工作区的不存样本：光有这句话学不到东西
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
    if deepseek.has_dsml(reply):                  # 工具调用写成的文字不给他看、不进历史（不然下一句它照着写）
        reply = deepseek.strip_dsml(reply) or "这次工具调用没成功，跟我说「继续」我再试一次。"
    db.update("events", eid, {"route": route, "ui_to": dec["ui_to"] if route == dec["route"] else route, "result": reply[:2000], "reply": reply,
                              "cost": cost, "latency": time.time() - t0, "status": "done", "steps": steps,
                              "why": dec["why"] + why_extra + " " + dec["vote_line"] + "。"})
    HIST[user].extend([("user", text + (f"（附了 {len(images)} 张图片）" if images else "") +
                        (f"（发来了文件：{'、'.join(x['rel'] for x in received[:5])}）" if received else ""), dec["private"], t0),
                       ("assistant", reply, dec["private"], time.time())])
    return events.get(eid)


def _note_reads(eid, used, steps, how):
    for kind, path, name, size in used:
        files.note(eid, kind, path, name, size)
        steps.append(["读文件" if kind != "dir" else "列目录", f"{name} · {how}"])


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


async def on_qq(text, openid, msg_id, atts=None):
    """QQ 上发来的一条。v2.3：带的图片、文件先收进 工作区\\收到的\\（图片也给 DeepSeek 看）；这件事做出来的图片发回 QQ（最多 3 张）。"""
    from . import qq as qqmod
    rels, imgs, bad = await qqmod.fetch_attachments(atts)
    got = await asyncio.to_thread(workspace.received, rels)
    if not text and not got and bad:
        await BOT.reply(openid, "附件没收下来：" + "；".join(bad), msg_id)
        return
    text = text or ("看看这张图。" if imgs else "收到这些文件，先放在工作区。")
    ev = await handle(text, "qq", openid, images=imgs or None, received=got or None)
    if ev and ev.get("reply"):
        ok, info = await BOT.reply(openid, plain(ev["reply"]) + ("\n（" + "；".join(bad) + "）" if bad else ""), msg_id)
        if not ok:
            db.update("events", ev["id"], {"result": (ev.get("result") or "") + f"\n（QQ 回复失败：{info}）"})
    if ev and settings.S.get("qqSendImg", True):
        sent, steps = 0, None
        for r in db.q("SELECT path,name,size FROM chat_files WHERE event_id=? AND kind='out' ORDER BY id", (ev["id"],)):
            p = Path(r["path"])
            if sent >= 3 or p.suffix.lower() not in (".png", ".jpg", ".jpeg") or not p.is_file():
                continue
            ok, info = await BOT.send_image(openid, p, msg_id)
            sent += 1
            steps = steps or db.jl((db.one("SELECT steps FROM events WHERE id=?", (ev["id"],)) or {}).get("steps"), [])
            steps.append(["发回 QQ", f"{p.name} · {'发出去了' if ok else '没发成：' + info}"])
        if steps:
            db.update("events", ev["id"], {"steps": steps})


BOT.on_message = on_qq
_ = asyncio
