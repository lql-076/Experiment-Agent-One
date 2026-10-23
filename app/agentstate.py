"""Agent 状态：把"它自己"的每个部分一项一项列出来，一眼看清哪些能用、哪些缺着、缺了去哪补。

和「电脑状态」对应：电脑状态看硬件，这里看 agent 本身——
决策脑的两票（嵌入模型、Kev）、底座和每个小脑、正在攒样本的新类别、DeepSeek 和联网搜索、QQ 和提醒、
后台的各个程序、记忆。界面上「对话」页右边和「总览」都读这里（/api/agent）。

每一项：st = ok（正常）/ idle（正常，闲着，用到才启动）/ warn（进行中、要注意）/ bad（缺了或出错）/ off（没开，可选）
act = 点了去哪：{"label": "去补齐", "sec": "prep"}、{"label": "去填 Key", "sec": "cloud"}……
m = 有数的项给界面画进度环：{"p": 0~1 或没有, "txt": "64/200"}
顶层的 kpi = 界面顶上那一排大数字：余额、今天联网、下一个提醒、整备、记忆
"""
import time

from . import db, deepseek, memory, monitor, obsidian, paths, router, settings, websearch
from .models import M


def _obs_row():
    o = obsidian.status()
    go = {"label": "去接", "sec": "obsidian"}
    if not o["vaults"]:
        return _row("obsidian", "Obsidian 笔记", "off", "还没接库：设置 › Obsidian 笔记 里加", go)
    if not o["on"]:
        return _row("obsidian", "Obsidian 笔记", "off", "设置里关掉了", {"label": "去打开", "sec": "obsidian"})
    gone = [v["name"] for v in o["vaults"] if not v["exists"]]
    if gone:
        return _row("obsidian", "Obsidian 笔记", "bad", f"找不到「{'、'.join(gone)}」的文件夹", {"label": "去看看", "sec": "obsidian"})
    n = sum(v["notes"] for v in o["vaults"])
    p = sum(v["privNotes"] for v in o["vaults"])
    w = sum(v["waiting"] for v in o["vaults"])
    d = f"{len(o['vaults'])} 个库 · {n} 篇" + (f" · 私人 {p} 篇只在本地" if p else "") + (f" · 写到「{o['inboxVault']}/{o['inbox']}」" if o["inboxVault"] else " · 都是只读")
    if w and not o["embedOn"]:
        return _row("obsidian", "Obsidian 笔记", "warn", f"{w} 段等嵌入模型算向量，先按字面找 · " + d, m={"txt": f"{n} 篇"})
    return _row("obsidian", "Obsidian 笔记", "ok", d, m={"txt": f"{n} 篇"})


def _row(k, name, st, detail, act=None, sub=None, m=None):
    r = {"k": k, "name": name, "st": st, "detail": detail}
    if act:
        r["act"] = act
    if sub:
        r["sub"] = sub
    if m:
        r["m"] = m
    return r


def _m(v, mx=None, txt=None):
    """进度：v / mx（mx 没有就只给文字）"""
    out = {"txt": txt if txt is not None else (f"{v} / {mx}" if mx else str(v))}
    if mx:
        out["p"] = round(max(0.0, min(1.0, float(v) / float(mx))), 3)
    return out


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
    elif M.kev_weights():
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
        cm = _m(min(c["count"], need), need, f"{c['count']} / {need}")
        if c["status"] == "approved":
            sub.append(_row("cat:" + c["name"], c["name"], "warn", f"你同意训练了（{c['count']} 条）· 训练这一步还没接", m=cm))
        elif c["status"] == "ready":
            sub.append(_row("cat:" + c["name"], c["name"], "warn", f"样本够了（{c['count']} 条）· 等你点头", m=cm))
        else:
            sub.append(_row("cat:" + c["name"], c["name"], "idle", f"攒样本中 {c['count']} / {need}", m=cm))
    top = max((c["count"] for c in cats), default=0)
    if not loras:
        brain.append(_row("loras", "训练出来的小脑", "off", "还没有 · 某类事攒够样本、你同意后才训练" + (f" · 正在攒 {len(cats)} 类" if cats else ""), sub=sub or None,
                          m=_m(min(top, need), need, f"最多 {top} / {need}") if cats else None))
    elif sub:
        brain.append(_row("cats", "正在攒样本的新类别", "idle", f"{len(cats)} 类", sub=sub, m=_m(min(top, need), need, f"最多 {top} / {need}")))

    # Obsidian 笔记
    brain.append(_obs_row())

    # ---------- 云端 ----------
    cloud = []
    kpi = {}
    mc = deepseek.month_cost_cny()
    if not settings.get_secret("dsKey"):
        cloud.append(_row("ds", "DeepSeek", "bad", "还没填 Key：难题、联网搜索、每日差事都用不了", {"label": "去填 Key", "sec": "cloud"}))
        kpi["bal"] = {"st": "bad", "v": "没填 Key", "sub": "设置 › 云端"}
    else:
        b = deepseek.balance_cached() or {}
        if b.get("err"):
            cloud.append(_row("ds", "DeepSeek", "bad", "Key 有问题：" + str(b["err"])[:60], {"label": "去看看", "sec": "cloud"}))
            kpi["bal"] = {"st": "bad", "v": "Key 有问题", "sub": str(b["err"])[:40]}
        else:
            low = b.get("total") is not None and b["total"] < float(S.get("dsLow", 2))
            tot = b.get("total")
            bm = {"txt": deepseek.money(tot, b.get("currency", "CNY"))}
            if tot is not None and tot + mc > 0:
                bm["p"] = round(max(0.0, min(1.0, tot / (tot + mc))), 3)
            cloud.append(_row("ds", "DeepSeek", "warn" if low else "ok",
                              f"Key 正常 · 余额 {deepseek.money(b.get('total'), b.get('currency', 'CNY'))}" + (" · 快用完了" if low else "") + f" · 模型 {S.get('dsModel')}", m=bm))
            kpi["bal"] = {"st": "warn" if low else "ok", "v": bm["txt"], "p": bm.get("p"), "sub": f"本月花了 ¥{mc:.2f}" + (" · 快用完了" if low else "")}
    st = websearch.stats()
    if not st["on"]:
        cloud.append(_row("search", "联网搜索", "off", "关着", {"label": "去打开", "sec": "cloud"}))
        kpi["search"] = {"st": "off", "v": "关着", "sub": "设置 › 云端 打开"}
    elif not settings.get_secret("dsKey"):
        cloud.append(_row("search", "联网搜索", "bad", "要先填 DeepSeek Key", {"label": "去填 Key", "sec": "cloud"}))
        kpi["search"] = {"st": "bad", "v": "用不了", "sub": "要先填 DeepSeek Key"}
    else:
        full = st["today"]["n"] >= st["limit"]
        cloud.append(_row("search", "联网搜索", "warn" if full else "ok",
                          f"开着 · 今天 {st['today']['n']} / {st['limit']} 次" + (" · 今天的次数用完了" if full else ""), m=_m(min(st["today"]["n"], st["limit"]), st["limit"], f"{st['today']['n']} / {st['limit']}")))
        kpi["search"] = {"st": "warn" if full else "ok", "v": str(st["today"]["n"]), "unit": f"/ {st['limit']} 次", "p": round(min(1, st["today"]["n"] / max(1, st["limit"])), 3),
                         "sub": f"本月 {st['month']['n']} 次 · ¥{st['month']['cny']:.2f}"}
    if router.strong_on():
        cloud.append(_row("claude", router.strong_name(), "ok", "特别复杂的事写好提示词，你自己去问（网页 Claude、ChatGPT、Kimi……你能用的最强的都行）"))
    else:
        cloud.append(_row("claude", router.strong_name(), "off", "你选了不用：特别难的事也交给 DeepSeek", {"label": "去打开", "sec": "cloud"}))

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
                     else "一条都没开（提醒不靠任何模型，显卡被占满也准时）", None if rems else {"label": "去设", "sec": "remind"},
                     m={"txt": time.strftime("%H:%M", time.localtime(nxt["next_ts"]))} if nxt else None))
    if not nxt:
        kpi["remind"] = {"st": "off", "v": "--:--", "sub": "一条都没开" if not rems else f"开着 {len(rems)} 条"}
    else:
        kpi["remind"] = {"st": "ok", "v": time.strftime("%H:%M", time.localtime(nxt["next_ts"])), "ts": nxt["next_ts"],
                         "sub": f"{nxt['title']} · 共开着 {len(rems)} 条"}

    # ---------- 后台 ----------
    back = [_row("backend", "后端", "ok", "127.0.0.1:8765 · 界面和所有接口")]
    m = svc.get("model", {})
    vm = None
    al = (h.get("vram") or {}).get("alloc_gb")
    if al is not None:
        from . import hw as hwmod
        vt = ((hwmod._cache.get("data") or {}).get("gpu") or {}).get("vramTotal")
        vm = _m(al, vt, f"{al} GB") if vt else {"txt": f"{al} GB"}
    back.append(_row("model", "本地模型服务", {"ok": "ok", "warn": "warn", "bad": "bad"}.get(m.get("st"), "bad" if not env_ok else "off"),
                     m.get("detail") or "没在运行", None if env_ok else PREP, m=vm))
    hwv = svc.get("hw", {})
    back.append(_row("hw", "硬件监控助手", "ok" if hwv.get("st") == "ok" else ("warn" if S.get("hwOn") else "off"), hwv.get("detail") or "没在运行",
                     None if hwv.get("st") == "ok" else {"label": "去打开" if not S.get("hwOn") else "去看看", "sec": "hw"}))
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
    mck = ck("memory")
    mst = "ok" if mck == "ok" else ("warn" if mck == "wait" else "bad" if mck else "idle")
    back.append(_row("memory", "记忆和说明书", mst,
                     f"记忆 {n_mem} 段 · 说明书 {n_doc} 段已建索引" + ("" if n_mem + n_doc else "（嵌入模型在线后自动建）"), m={"txt": f"{n_mem} · {n_doc}"}))
    kpi["mem"] = {"st": mst, "v": str(n_mem), "unit": "段", "sub": f"说明书 {n_doc} 段已建索引"}

    groups = [{"name": "大脑", "items": brain}, {"name": "云端", "items": cloud}, {"name": "通道", "items": chan}, {"name": "后台", "items": back}]
    cnt = {"ok": 0, "idle": 0, "warn": 0, "bad": 0, "off": 0}
    for g in groups:
        for it in g["items"]:
            cnt[it["st"]] = cnt.get(it["st"], 0) + 1
    bad = [it["name"] for g in groups for it in g["items"] if it["st"] == "bad"]
    head = "全部正常" if not bad and not cnt["warn"] else ("缺：" + "、".join(n.split("（")[0] for n in bad[:4]) + ("……" if len(bad) > 4 else "")) if bad else f"{cnt['warn']} 项要注意"
    ready, total = sum(1 for v in chk.values() if v.get("st") == "ok"), len(chk) or 14
    kpi["prep"] = {"st": "ok" if ready >= total else "warn", "v": str(ready), "unit": f"/ {total} 项", "p": round(ready / total, 3),
                   "sub": "全部就绪" if ready >= total else f"缺 {total - ready} 项 · 去补齐"}
    return {"ts": time.time(), "count": cnt, "head": head, "groups": groups, "kpi": kpi,
            "prep": {"ready": ready, "total": total}}
