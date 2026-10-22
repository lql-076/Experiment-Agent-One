"""慢成长：样本攒够了，先问你要不要训练，不按钟点。

- 某一类事的样本攒够（设置 › 成长与训练 › 新建一个小脑需要的样本数），就在 QQ 和界面上问你一次；
  QQ 发不出去就弹 Windows 通知。
- 你回「开始 / 允许 / 可以 / 练吧」→ 记为同意，开始训练；
  回「先不 / 等一下 / 等我忙完 / 晚点」→ 先不练，过一阵再问；
  一直没回 → 隔「没回的话，隔多久再问」小时再问一次，直到你回。
- 开着免打扰时不问，关掉后再问。
- 训练时显存随便用（不设上限）；训练本身还在做，做好后同意了就直接开练。

状态存在 kv 的 train_ask 里：{cat, n, status: asking|waiting|approved, asked, times, until}
"""
import re
import time

from . import db, feed, notify, safety, settings
from .qq import BOT

GO = re.compile(r"(开始|开练|允许|同意|可以练|可以|练吧|训练吧|行吧|好的?$|来吧|去吧|练)")
WAIT = re.compile(r"(先不|不要|别|等一下|等一会|等等|等我|忙完|晚点|晚一点|稍后|待会|过会|回头|下次|改天|不用)")


def _st():
    return db.kv_get("train_ask") or {}


def _set(st):
    db.kv_set("train_ask", st)


def pending():
    """界面上挂的那张卡片要的东西；没有在问就返回 None。"""
    st = _st()
    if st.get("status") != "asking":
        return None
    return {"cat": st["cat"], "n": st.get("n"), "asked": st.get("asked"), "times": st.get("times", 1)}


def _ready_cat():
    return db.one("SELECT * FROM categories WHERE status='ready' ORDER BY count DESC LIMIT 1")


async def _ask(cat, n, times):
    text = (f"「{cat}」这类事的样本攒够了（{n} 条），可以训练一个新小脑。现在开始吗？\n"
            "训练时显卡会被占满一阵子，玩游戏时别开。\n回「开始」就练，回「等一下」先不练，过一阵再问你。")
    ok, _ = await BOT.push(("🧠 " if times == 1 else f"🧠（第 {times} 次问）") + text)
    if not ok and settings.S.get("toastFallback", True):
        await notify.toast(f"要不要训练「{cat}」？", "样本攒够了。在界面上点「开始训练」或「等一下」。")


async def tick():
    """后台每隔一会调用一次。"""
    if not settings.S.get("slow", True):
        return
    st, now = _st(), time.time()
    status = st.get("status")
    if status == "approved":
        return
    if status == "waiting" and now < st.get("until", 0):
        return
    if status == "asking" and now - st.get("asked", 0) < float(settings.S.get("trainAsk", 2)) * 3600:
        return
    if settings.S.get("quiet"):
        return
    c = _ready_cat()
    if not c:
        if status:
            _set({})
        return
    times = st.get("times", 0) + 1 if status == "asking" and st.get("cat") == c["name"] else 1
    _set({"cat": c["name"], "n": c["count"], "status": "asking", "asked": now, "times": times})
    feed.add(f"「{c['name']}」的样本攒够了（{c['count']} 条），在 QQ 和界面上问你要不要训练" + (f"（第 {times} 次问）" if times > 1 else ""), "warn", job="训练")
    await _ask(c["name"], c["count"], times)


def answer(go: bool, how="界面"):
    st = _st()
    if st.get("status") != "asking":
        return None
    cat = st["cat"]
    if go:
        st.update(status="approved", ok_ts=time.time())
        _set(st)
        db.run("UPDATE categories SET status='approved' WHERE name=?", (cat,))
        safety.record_change("brain.create", f"你同意训练「{cat}」（{how}回复）", "样本攒够后问你")
        feed.add(f"你同意训练「{cat}」（{how}回复）", "ok", job="训练")
        return f"好，「{cat}」记为可以训练。训练这一步还在做，做好后会直接开练；显存随便用。"
    hrs = float(settings.S.get("trainAsk", 2))
    st.update(status="waiting", until=time.time() + hrs * 3600)
    _set(st)
    feed.add(f"你说先不练「{cat}」（{how}回复），{hrs:g} 小时后再问", "info", job="训练")
    return f"好，先不练。{hrs:g} 小时后再问你。"


def try_reply(text: str):
    """QQ 上回的话如果是在答"要不要训练"，在这里处理掉。不是就返回 None。"""
    if not pending() or len(text) > 20:
        return None
    if WAIT.search(text):
        return answer(False, "QQ")
    if GO.search(text):
        return answer(True, "QQ")
    return None
