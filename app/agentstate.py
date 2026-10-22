"""Agent 状态：把"它自己"的每个部分一项一项列出来，一眼看清哪些能用、哪些缺着、缺了去哪补。

和「电脑状态」对应：电脑状态看硬件，这里看 agent 本身——
决策脑的两票（嵌入模型、Kev）、底座和每个小脑、正在攒样本的新类别、DeepSeek 和联网搜索、QQ 和提醒、
后台的各个程序、记忆。界面上「对话」页右边和「总览」都读这里（/api/agent）。

每一项：st = ok（正常）/ idle（正常，闲着，用到才启动）/ warn（进行中、要注意）/ bad（缺了或出错）/ off（没开，可选）
act = 点了去哪：{"label": "去补齐", "sec": "prep"}、{"label": "去填 Key", "sec": "cloud"}……
"""
import time

from . import db, deepseek, memory, monitor, paths, router, settings, websearch
from .models import M


def _kev_weights() -> bool:
    name = "models--" + settings.S.get("kevRun", "jaredpalmer/kev-0.8b").replace("/", "--")
    snap = paths.HF_CACHE / "hub" / name / "snapshots"
    return snap.is_dir() and any(snap.iterdir())


def _row(k, name, st, detail, act=None, sub=None):
    r = {"k": k, "name": name, "st": st, "detail": detail}
    if act:
        r["act"] = act
    if sub:
        r["sub"] = sub
    return r


PREP = {"label": "去补齐", "sec": "prep"}


async def view():
    chk = (db.kv_get("checks") or {}).get("res") or {}
    svc = {s["k"]: s for s in await monitor.services()}
    h = M._health or {}
    S = settings.S

    def ck(k):
        return (chk.get(k) or {}).get("st")

    # ---------- 大脑 ----------
    brain = []
    env_ok = ck("aienv") == "ok"
    if h.get("embed_loaded"):
        brain.append(_row("embed", "语义路由（嵌入模型）", "ok", "在线 · 决策脑第一票、找记忆、查说明书都靠它"))
    elif ck("embed") == "miss":
        brain.append(_row("embed", "语义路由（嵌入模型）", "bad", "模型文件还没下载：决策脑只能用简单规则，记忆检索用不了", PREP))
    elif not env_ok and ck("aienv"):
        brain.append(_row("embed", "语义路由（嵌入模型）", "bad", "本地模型环境还没装", PREP))
    else:
        brain.append(_row("embed", "语义路由（嵌入模型）", "warn", svc.get("model", {}).get("detail") or "本地模型服务没在运行，后台会自动拉起"))

    kev = svc.get("kev", {})
    if S.get("kevMode") == "off":
        brain.append(_row("kev", "Kev（决策脑第二票）", "off", "设置里关掉了，决策脑只用语义路由一票", {"label": "去打开", "sec": "models"}))
    elif kev.get("st") == "ok":
        brain.append(_row("kev", "Kev（决策脑第二票）", "ok", kev.get("detail", "在线")))
    elif kev.get("st") == "warn":
        brain.append(_row("kev", "Kev（决策脑第二票）", "warn", kev.get("detail", "正在启动")))
    elif not env_ok:
        brain.append(_row("kev", "Kev（决策脑第二票）", "bad", "还没装：要先装本地模型环境，再下载约 2GB 权重", PREP))
    elif _kev_weights():
        brain.append(_row("kev", "Kev（决策脑第二票）", "idle", "已下载 · 闲着，用到才启动"))
    else:
        brain.append(_row("kev", "Kev（决策脑第二票）", "bad", "权重还没下载（约 2GB）", PREP))

    if h.get("base_loaded"):
        brain.append(_row("base", "本地通用（底座 MiniCPM5-2B）", "ok", "已加载在显卡上 · 本地的活和所有隐私内容都由它做"))
    elif ck("base") == "ok":
        brain.append(_row("base", "本地通用（底座 MiniCPM5-2B）", "idle", "已下载 · 闲着，用到才加载" + (" · 现在让路中" if M.yielding else "")))
    else:
        brain.append(_row("base", "本地通用（底座 MiniCPM5-2B）", "bad", "还没下载：本地小脑用不了，隐私的事只能排队", PREP))

    loras = router.brains()[1:]
    for b in loras:
        brain.append(_row("lora:" + b["name"], "小脑 · " + b["name"], "ok" if ck("base") == "ok" else "warn",
                          "已上线 · " + (b.get("desc") or "LoRA，共享底座")))
    need = int(S.get("samples", 200))
    cats = db.q("SELECT * FROM categories ORDER BY count DESC LIMIT 6")
    sub = []
    for c in cats:
        if c["status"] == "approved":
            sub.append(_row("cat:" + c["name"], c["name"], "warn", f"你同意训练了（{c['count']} 条）· 训练这一步还没接"))
        elif c["status"] == "ready":
            sub.append(_row("cat:" + c["name"], c["name"], "warn", f"样本够了（{c['count']} 条）· 等你点头"))
        else:
            sub.append(_row("cat:" + c["name"], c["name"], "idle", f"攒样本中 {c['count']} / {need}"))
    if not loras:
        brain.append(_row("loras", "训练出来的小脑", "off", "还没有 · 某类事攒够样本、你同意后才训练" + (f" · 正在攒 {len(cats)} 类" if cats else ""), sub=sub or None))
    elif sub:
        brain.append(_row("cats", "正在攒样本的新类别", "idle", f"{len(cats)} 类", sub=sub))

    # ---------- 云端 ----------
    cloud = []
    if not settings.get_secret("dsKey"):
        cloud.append(_row("ds", "DeepSeek", "bad", "还没填 Key：难题、联网搜索、每日差事都用不了", {"label": "去填 Key", "sec": "cloud"}))
    else:
        b = deepseek.balance_cached() or {}
        if b.get("err"):
            cloud.append(_row("ds", "DeepSeek", "bad", "Key 有问题：" + str(b["err"])[:60], {"label": "去看看", "sec": "cloud"}))
        else:
            low = b.get("total") is not None and b["total"] < float(S.get("dsLow", 2))
            cloud.append(_row("ds", "DeepSeek", "warn" if low else "ok",
                              f"Key 正常 · 余额 {deepseek.money(b.get('total'), b.get('currency', 'CNY'))}" + (" · 快用完了" if low else "") + f" · 模型 {S.get('dsModel')}"))
    st = websearch.stats()
    if not st["on"]:
        cloud.append(_row("search", "联网搜索", "off", "关着", {"label": "去打开", "sec": "cloud"}))
    elif not settings.get_secret("dsKey"):
        cloud.append(_row("search", "联网搜索", "bad", "要先填 DeepSeek Key", {"label": "去填 Key", "sec": "cloud"}))
    else:
        cloud.append(_row("search", "联网搜索", "warn" if st["today"]["n"] >= st["limit"] else "ok",
                          f"开着 · 今天 {st['today']['n']} / {st['limit']} 次" + (" · 今天的次数用完了" if st["today"]["n"] >= st["limit"] else "")))
    cloud.append(_row("claude", "网页 Claude", "ok", "特别复杂的事写好提示词，你自己去问（不自动登录）"))

    # ---------- 通道 ----------
    chan = []
    q = svc.get("qq", {})
    if not S.get("qqEnabled", True):
        chan.append(_row("qq", "QQ", "off", "设置里关掉了", {"label": "去打开", "sec": "qq"}))
    elif ck("qq") == "miss" and q.get("st") != "ok":
        chan.append(_row("qq", "QQ", "bad", "还没填 AppID 和 AppSecret（只能在界面上聊）", {"label": "去填", "sec": "qq"}))
    else:
        bits = [q.get("detail") or "离线"]
        if not S.get("qqUser"):
            bits.append("还没绑定你的 QQ")
        chan.append(_row("qq", "QQ", {"ok": "ok" if S.get("qqUser") else "warn", "warn": "warn", "bad": "bad"}.get(q.get("st"), "warn"), " · ".join(bits),
                         None if q.get("st") == "ok" and S.get("qqUser") else PREP))
    rems = db.q("SELECT * FROM reminders WHERE enabled=1 ORDER BY next_ts")
    nxt = next((r for r in rems if r["next_ts"]), None)
    chan.append(_row("remind", "提醒", "ok" if rems else "off",
                     (f"开着 {len(rems)} 条 · 下一个 {time.strftime('%m-%d %H:%M', time.localtime(nxt['next_ts']))} {nxt['title']}" if nxt else f"开着 {len(rems)} 条") if rems
                     else "一条都没开（提醒不靠任何模型，显卡被占满也准时）", None if rems else {"label": "去设", "sec": "remind"}))

    # ---------- 后台 ----------
    back = [_row("backend", "后端", "ok", "127.0.0.1:8765 · 界面和所有接口")]
    m = svc.get("model", {})
    back.append(_row("model", "本地模型服务", {"ok": "ok", "warn": "warn", "bad": "bad"}.get(m.get("st"), "bad" if not env_ok else "off"),
                     m.get("detail") or "没在运行", None if env_ok else PREP))
    hwv = svc.get("hw", {})
    back.append(_row("hw", "硬件监控助手", "ok" if hwv.get("st") == "ok" else "off", hwv.get("detail") or "没在运行"))
    nl = svc.get("nightly", {})
    back.append(_row("nightly", "每日差事", "ok" if nl.get("st") == "ok" else ("off" if not S.get("nightly", True) else "idle"),
                     nl.get("detail") or "还没跑过"))
    if S.get("osdOn"):
        from . import osd
        alive = osd.ctl().proc.alive()
        back.append(_row("osd", "游戏内显示", "ok" if alive else ("bad" if paths.IS_WIN else "off"),
                         ("开着 · " + ("只在玩游戏时显示" if S.get("osdWhen") != "always" else "一直显示")) if alive
                         else ("没起来：看 data\\logs\\osd.log" if paths.IS_WIN else "只在 Windows 上能用"), {"label": "去看看", "sec": "osd"}))
    else:
        back.append(_row("osd", "游戏内显示", "off", "没开（设置 › 游戏内显示）", {"label": "去打开", "sec": "osd"}))
    qu = svc.get("queue", {})
    back.append(_row("queue", "排队的事", qu.get("st", "ok"), qu.get("detail", "没有")))
    n_mem = db.one("SELECT COUNT(*) n FROM chunks WHERE file NOT LIKE ?", (memory.DOC_TAG + "%",))["n"]
    n_doc = db.one("SELECT COUNT(*) n FROM chunks WHERE file LIKE ?", (memory.DOC_TAG + "%",))["n"]
    mc = ck("memory")
    back.append(_row("memory", "记忆和说明书", "ok" if mc == "ok" else ("warn" if mc == "wait" else "bad" if mc else "idle"),
                     f"记忆 {n_mem} 段 · 说明书 {n_doc} 段已建索引" + ("" if n_mem + n_doc else "（嵌入模型在线后自动建）")))

    groups = [{"name": "大脑", "items": brain}, {"name": "云端", "items": cloud}, {"name": "通道", "items": chan}, {"name": "后台", "items": back}]
    cnt = {"ok": 0, "idle": 0, "warn": 0, "bad": 0, "off": 0}
    for g in groups:
        for it in g["items"]:
            cnt[it["st"]] = cnt.get(it["st"], 0) + 1
    bad = [it["name"] for g in groups for it in g["items"] if it["st"] == "bad"]
    head = "全部正常" if not bad and not cnt["warn"] else ("缺：" + "、".join(n.split("（")[0] for n in bad[:4]) + ("……" if len(bad) > 4 else "")) if bad else f"{cnt['warn']} 项要注意"
    return {"ts": time.time(), "count": cnt, "head": head, "groups": groups,
            "prep": {"ready": sum(1 for v in chk.values() if v.get("st") == "ok"), "total": len(chk) or 14}}
