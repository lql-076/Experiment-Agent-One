"""提醒：定时、送达、确认、顺延。不依赖任何模型——显卡被游戏占满、模型没装好，提醒照样准时。

三种：每天定点（daily）、每隔几分钟（interval）、一次性（once）。
你回"吃了/好了/收到"就确认；回"晚点/等会/20 分钟后"就顺延。没确认的，过一会儿再提醒一次（次数可调）。
"""
import asyncio
import re
import time
from datetime import datetime, timedelta

from . import db, notify, safety, settings

ACK = re.compile(r"(吃了|吃过|已吃|好了|好的|收到|知道了|完成|搞定|做完|喝了|ok|OK|done|嗯嗯|嗯|行)")
SNOOZE = re.compile(r"(晚点|晚一点|等会|等一会|待会|稍后|一会儿|过会|迟点|再说)")
MIN_N = re.compile(r"(\d+|[一二两三四五六七八九十]+)\s*(分钟|分|小时|个小时)")
CN = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def cn2int(s):
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + CN.get(s[1:], 0)
    if "十" in s:
        a, b = s.split("十", 1)
        return CN.get(a, 1) * 10 + (CN.get(b, 0) if b else 0)
    return CN.get(s, 0)


def compute_next(r, after=None):
    now = after or time.time()
    if r["kind"] == "once":
        return r["once_ts"] if r["once_ts"] and r["once_ts"] > now else None
    if r["kind"] == "interval":
        step = max(5, int(r["every_min"] or 90)) * 60
        base = r["last_ts"] or now
        nxt = base + step
        return nxt if nxt > now else now + step
    try:
        hh, mm = [int(x) for x in (r["at"] or "22:00").split(":")]
    except ValueError:
        hh, mm = 22, 0
    days = r["days"] or "1234567"
    d = datetime.fromtimestamp(now)
    for i in range(0, 8):
        c = (d + timedelta(days=i)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if str(c.isoweekday()) in days and c.timestamp() > now:
            return c.timestamp()
    return None


def all_reminders():
    return db.q("SELECT * FROM reminders ORDER BY id")


def save(r: dict, rid=None):
    allowed = {k: r[k] for k in ("title", "text", "kind", "at", "every_min", "days", "once_ts", "enabled") if k in r}
    if rid:
        cur = db.one("SELECT * FROM reminders WHERE id=?", (rid,))
        if not cur:
            raise KeyError(rid)
        cur.update(allowed)
        cur["next_ts"] = compute_next(cur) if cur["enabled"] else None
        db.update("reminders", rid, {k: cur[k] for k in list(allowed) + ["next_ts"]})
        return rid
    row = {"title": "提醒", "text": "", "kind": "daily", "at": "22:00", "every_min": 90, "days": "1234567", "once_ts": None,
           "enabled": 1, "created": time.time(), **allowed}
    row["next_ts"] = compute_next({**row, "last_ts": None}) if row["enabled"] else None
    return db.insert("reminders", row)


def seed():
    if not db.one("SELECT id FROM reminders LIMIT 1"):
        # 默认关着：先在 设置 › 提醒 里确认时间再打开
        save({"title": "吃药", "text": "该吃药了，吃完回我一句\"吃了\"", "kind": "daily", "at": "22:00", "enabled": 0})


def next_info():
    rows = [r for r in all_reminders() if r["enabled"] and r["next_ts"]]
    if not rows:
        return None
    r = min(rows, key=lambda x: x["next_ts"])
    return {"id": r["id"], "title": r["title"], "at": datetime.fromtimestamp(r["next_ts"]).strftime("%H:%M"),
            "ts": r["next_ts"], "left_s": max(0, int(r["next_ts"] - time.time()))}


async def fire(r, again=False, delivery=None):
    title = r["title"] if not again else f"还没确认：{r['title']}"
    text = r["text"] or ""
    if delivery is None:
        did = db.insert("deliveries", {"reminder_id": r["id"], "ts": time.time(), "title": r["title"], "text": text, "status": "sent"})
    else:
        did = delivery["id"]
    res = await notify.deliver(title, text, did, r["id"])
    db.update("deliveries", did, {"channels": res})
    from . import events
    events.log_system(f"提醒：{r['title']}" + ("（再提醒）" if again else ""), res)
    return did, res


async def test_push():
    did = db.insert("deliveries", {"reminder_id": 0, "ts": time.time(), "title": "测试提醒", "text": "这是一条测试，回\"收到\"确认", "status": "sent"})
    res = await notify.deliver("测试提醒", "这是一条测试，回\"收到\"确认", did, 0)
    db.update("deliveries", did, {"channels": res})
    return res


def pending():
    return db.one("SELECT * FROM deliveries WHERE status='sent' AND ts>? ORDER BY ts DESC", (time.time() - 6 * 3600,))


def ack(did, how="界面"):
    d = db.one("SELECT * FROM deliveries WHERE id=?", (did,))
    if not d or d["status"] != "sent":
        return False
    db.update("deliveries", did, {"status": "acked", "acked_ts": time.time()})
    notify.drop_card(did)
    return True


def snooze(did, minutes=30):
    d = db.one("SELECT * FROM deliveries WHERE id=?", (did,))
    if not d or d["status"] != "sent":
        return False
    db.update("deliveries", did, {"status": "snoozed", "snooze_ts": time.time() + minutes * 60})
    notify.drop_card(did)
    return True


def try_reply(text: str):
    """QQ 上的回复如果是在回应提醒，就在这里处理掉。返回回复文字，或 None（不是在回提醒）。"""
    d = pending()
    if not d or len(text) > 20:
        return None
    if SNOOZE.search(text) or MIN_N.search(text):
        m = MIN_N.search(text)
        mins = 30
        if m:
            n = cn2int(m.group(1))
            mins = n * 60 if "时" in m.group(2) else n
        snooze(d["id"], max(1, min(mins, 600)))
        return f"好，{mins} 分钟后再提醒你「{d['title']}」。"
    if ACK.search(text):
        ack(d["id"], "QQ")
        return f"好的，「{d['title']}」已打卡。"
    return None


# ---------- 从一句话里认出"设提醒" ----------
TIME = re.compile(r"(早上|上午|中午|下午|晚上|今晚|夜里)?\s*(\d{1,2}|[一二两三四五六七八九十]{1,3})\s*(?:点|:|：)\s*(半|(\d{1,2})\s*分?)?")


def parse_command(text: str):
    """认出"每天晚上十点提醒我吃药""半小时后提醒我收衣服""明天八点叫我"。认不出就返回 None。"""
    t = text.strip()
    if not re.search(r"(提醒我|叫我|喊我|提醒一下)", t):
        return None
    what = re.split(r"(提醒我|叫我|喊我|提醒一下)", t)[-1]
    what = re.sub(r"(每天|每晚|每早|天天|每日|今天|明天|后天)", "", what)
    what = TIME.sub("", what)
    what = re.sub(r"(\d+|[一二两三四五六七八九十]+|半)\s*(个)?\s*(分钟|小时)\s*(以)?后", "", what)
    what = what.strip(" ，,。.去要") or "到点了"
    m = re.search(r"(\d+|[一二两三四五六七八九十]+|半)\s*(个)?\s*(分钟|小时)\s*(以)?后", t)
    if m:
        n = 0.5 if m.group(1) == "半" else cn2int(m.group(1))
        sec = n * 3600 if m.group(3) == "小时" else n * 60
        if sec <= 0:
            return None
        return {"title": what, "text": "", "kind": "once", "once_ts": time.time() + sec, "enabled": 1}
    m = TIME.search(t)
    if not m:
        return None
    h = cn2int(m.group(2))
    mi = 30 if m.group(3) == "半" else (int(m.group(4)) if m.group(4) else 0)
    if m.group(1) in ("下午", "晚上", "今晚", "夜里") and h < 12:
        h += 12
    if m.group(1) == "中午" and h < 11:
        h += 12
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None
    at = f"{h:02d}:{mi:02d}"
    if re.search(r"(每天|每晚|每早|天天|每日)", t):
        return {"title": what, "text": "", "kind": "daily", "at": at, "enabled": 1}
    day = datetime.now()
    if "明天" in t:
        day += timedelta(days=1)
    elif "后天" in t:
        day += timedelta(days=2)
    hours = [h] if (m.group(1) or h >= 12) else [h, h + 12]   # 没说上午下午：取最近的那个
    cands = [day.replace(hour=x, minute=mi, second=0, microsecond=0).timestamp() for x in hours]
    future = [c for c in cands if c > time.time()]
    ts = min(future) if future else min(cands) + 86400
    return {"title": what, "text": "", "kind": "once", "once_ts": ts, "enabled": 1}


async def create_from_text(text: str, event_id=None):
    r = parse_command(text)
    if not r:
        return None
    if r["kind"] == "daily":
        same = [x for x in all_reminders() if x["kind"] == "daily" and x["title"] == r["title"]]
        hit = next((x for x in same if x["at"] == r["at"] and x["enabled"]), None) or next((x for x in same if x["at"] == r["at"]), None)
        if hit and hit["enabled"]:
            return f"已经有这个提醒了：每天 {r['at']}「{r['title']}」。"
        if hit or same:
            target = hit or same[0]

            async def run_update():
                save({"at": r["at"], "enabled": 1}, target["id"])
                safety.record_change("reminder.update", f"打开并设好提醒「{r['title']}」（每天 {r['at']}）",
                                     f"你在对话里说的 · 事件 #{event_id}" if event_id else "你在对话里说的")
            done, _ = await safety.request("reminder.update", f"修改提醒「{r['title']}」", "你在对话里说的", {"id": target["id"], "at": r["at"], "title": r["title"]}, run_update)
            return f"好，每天 {r['at']} 提醒你「{r['title']}」（原来那个提醒已改好并打开）。" if done else "要改提醒，已放进「等你决定」。"

    async def run():
        rid = save(r)
        when = r["at"] if r["kind"] == "daily" else datetime.fromtimestamp(r["once_ts"]).strftime("%m-%d %H:%M")
        safety.record_change("reminder.create", f"新增提醒「{r['title']}」（{'每天 ' if r['kind'] == 'daily' else ''}{when}）",
                             f"你在对话里说的 · 事件 #{event_id}" if event_id else "你在对话里说的", f"reminder:{rid}")
        return rid, when

    done, res = await safety.request("reminder.create", f"新增提醒「{r['title']}」", "你在对话里说的", r, run)
    if not done:
        return f"要新增提醒「{r['title']}」，已放进「等你决定」。"
    rid, when = res
    every = "每天 " if r["kind"] == "daily" else ""
    return f"好，{every}{when} 提醒你「{r['title']}」。"


@safety.handler("reminder.create")
async def _approved_create(payload):
    rid = save(payload)
    safety.record_change("reminder.create", f"新增提醒「{payload.get('title')}」", "你同意的改动", f"reminder:{rid}")
    return "提醒已建好"


@safety.handler("reminder.update")
async def _approved_update(payload):
    save({"at": payload["at"], "enabled": 1}, payload["id"])
    safety.record_change("reminder.update", f"打开并设好提醒「{payload.get('title')}」（每天 {payload['at']}）", "你同意的改动")
    return "提醒已改好"


# ---------- 调度 ----------
async def loop():
    for d in db.q("SELECT * FROM deliveries WHERE status='sent' AND ts>?", (time.time() - 6 * 3600,)):
        notify.CARDS[d["id"]] = {"id": d["id"], "title": d["title"], "text": d["text"], "ts": d["ts"], "reminder_id": d["reminder_id"]}
    for r in all_reminders():
        if r["enabled"] and (not r["next_ts"] or r["next_ts"] < time.time() - 3600):
            db.update("reminders", r["id"], {"next_ts": compute_next(r)})
    while True:
        try:
            now = time.time()
            for r in all_reminders():
                if r["enabled"] and r["next_ts"] and r["next_ts"] <= now:
                    db.update("reminders", r["id"], {"last_ts": now})
                    r["last_ts"] = now
                    nxt = compute_next(r, now + 1)
                    db.update("reminders", r["id"], {"next_ts": nxt, "enabled": 1 if nxt else 0})
                    await fire(r)
            # 顺延到点
            for d in db.q("SELECT * FROM deliveries WHERE status='snoozed' AND snooze_ts<=?", (now,)):
                db.update("deliveries", d["id"], {"status": "sent", "ts": now})
                r = db.one("SELECT * FROM reminders WHERE id=?", (d["reminder_id"],)) or {"id": 0, "title": d["title"], "text": d["text"]}
                await fire(r, delivery=d)
            # 没确认的再提醒
            gap = float(settings.S["renotifyMin"]) * 60
            for d in db.q("SELECT * FROM deliveries WHERE status='sent' AND ts<? AND renotified<?", (now - gap, int(settings.S["renotifyMax"]))):
                if now - d["ts"] < gap * (d["renotified"] + 1):
                    continue
                db.update("deliveries", d["id"], {"renotified": d["renotified"] + 1})
                r = db.one("SELECT * FROM reminders WHERE id=?", (d["reminder_id"],)) or {"id": 0, "title": d["title"], "text": d["text"]}
                await fire(r, again=True, delivery=d)
            # 过期没确认的标为错过
            db.run("UPDATE deliveries SET status='missed' WHERE status='sent' AND ts<?", (now - 6 * 3600,))
        except Exception as e:
            print("提醒调度出错：", e)
        await asyncio.sleep(15)
